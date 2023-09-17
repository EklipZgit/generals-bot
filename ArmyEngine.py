from __future__ import annotations

import logging
import time
import typing

import nashpy
import numpy

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Engine.ArmyEngineModels import ArmySimState, ArmySimResult, SimTile
from MctsLudii import MctsDUCT, Game, Context
from base.client.map import MapBase, Tile, MapMatrix


class ArmyEngine(object):
    def __init__(
            self,
            map: MapBase,
            friendlyArmies: typing.List[Army],
            enemyArmies: typing.List[Army],
            boardAnalysis: BoardAnalyzer,
            friendlyCaptureValues: MapMatrix | None = None,
            enemyCaptureValues: MapMatrix | None = None,
            timeCap: float = 5.0
    ):
        """

        @param map:
        @param friendlyArmies: The tiles in the scrim
        @param enemyArmies:
        @param boardAnalysis:
        @param friendlyCaptureValues:
        @param enemyCaptureValues:
        """
        self.map = map
        self.friendly_armies: typing.List[Army] = friendlyArmies
        self.enemy_armies: typing.List[Army] = enemyArmies
        self.board_analysis: BoardAnalyzer = boardAnalysis
        self.inter_army_analysis: ArmyAnalyzer | None = None
        self.friendly_player = friendlyArmies[0].player
        self.enemy_player = enemyArmies[0].player
        self.base_city_differential: int = 0
        """The city differential at sim start, used for determining whether we are city-bonus-positive or city-bonus-negative during the duration of a scrim."""
        self.iterations: int = 0
        self.nash_eq_iterations: int = 0
        self.time_in_nash_eq: float = 0.0
        self.time_in_nash: float = 0.0

        ## CONFIGURATION PARAMETERS

        self.enemy_has_kill_threat: bool = False
        """Whether or not the enemy army escaping towards the friendly general is a kill threat or not. Affects the value of board tree states."""
        self.friendly_has_kill_threat: bool = False
        """Whether or not the friendly army escaping towards the enemy general is a kill threat or not. Affects the value of board tree states."""

        self.friendly_capture_values: MapMatrix = friendlyCaptureValues
        """Tile weights indicating how many enemy tiles to 'capture' there are nearby a given tile. Affects how valuable a game end state with an unrestricted opposing army near these tiles are."""
        self.enemy_capture_values: MapMatrix = enemyCaptureValues
        """Tile weights indicating how many friendly tiles to 'capture' there are nearby a given tile. Affects how valuable a game end state with an unrestricted opposing army near these tiles are."""

        self.force_enemy_path: bool = False
        """Whether to forcibly use the Army.expected_path for this player when choosing moves"""

        self.force_friendly_path: bool = False
        """Whether to forcibly use the Army.expected_path for this player when choosing moves"""

        # self.force_enemy_pathway: bool = False
        # """Whether to forcibly use the Army.expected_path for this player when choosing moves"""
        #
        # self.force_friendly_pathway: bool = False
        # """Whether to forcibly use the Army.expected_path for this player when choosing moves"""
        self.force_enemy_towards_or_parallel_to: MapMatrix | None = None
        """A distance gradiant that an enemy army must make moves smaller or equal to to the current value. Pass this a SearchUtils.build_distance_map_matrix from the tile(s) you want to keep the army moving towards. Does not NEED to be ints, and can be any gradient descent (like forcing towards the closest clusters of opponent territory)"""
        self.force_enemy_towards: MapMatrix | None = None
        """A distance gradiant that an enemy army must make moves smaller than the current value. Pass this a SearchUtils.build_distance_map_matrix from the tile(s) you want to keep the army moving towards. Does not NEED to be ints, and can be any gradient descent (like forcing towards the closest clusters of opponent territory)"""

        self.force_friendly_towards_or_parallel_to: MapMatrix | None = None
        """A distance gradiant that an friendly army must make moves smaller or equal to to the current value. Pass this a SearchUtils.build_distance_map_matrix from the tile(s) you want to keep the army moving towards. Does not NEED to be ints, and can be any gradient descent (like forcing towards the closest clusters of opponent territory)"""
        self.force_friendly_towards: MapMatrix | None = None
        """A distance gradiant that an friendly army must make moves smaller than the current value. Pass this a SearchUtils.build_distance_map_matrix from the tile(s) you want to keep the army moving towards. Does not NEED to be ints, and can be any gradient descent (like forcing towards the closest clusters of opponent territory)"""

        self.allow_enemy_no_op: bool = False
        """If true, allows the enemy to use no-op moves in the scrim (reduces search depth by a lot, defaults to false)"""
        self.allow_friendly_no_op: bool = True
        """If true, allows friendly to use no-op moves in the scrim. Default true, as we generally want to know when the player would be better of spending their turn elsewhere on the board."""

        self.friendly_end_board_recap_weight: float = 1.5
        """How much tile-differential per turn a surviving friendly army is worth if near recapturable territory. Reduce to weight the engine away from things like spending moves trying to gather army before intercepting a threat etc."""
        self.enemy_end_board_recap_weight: float = 2.0
        """How much tile-differential per turn a surviving enemy army is worth if near recapturable territory."""

        self.repetition_threshold: int = 5
        """How many repeated tiles in a row constitute a repetition."""

        if len(friendlyArmies) == 1 and len(enemyArmies) == 1:
            # Cool, we can inter-analyze armies
            self.inter_army_analysis = ArmyAnalyzer(map, friendlyArmies[0], enemyArmies[0])

        self._friendly_move_filter: typing.Callable[[Tile, Tile, ArmySimState], bool] | None = None

        self._enemy_move_filter: typing.Callable[[Tile, Tile, ArmySimState], bool] | None = None

        self.log_everything: bool = False

        self.log_payoff_depth: int = 1
        """Even without log_everything set, log payoffs at or below this depth. Depth 1 will log the payoffs for all moves from starting position."""

        self.iteration_limit: int = -1
        self.time_limit: float = timeCap
        self._time_limit_dec: float = 0.01
        """The amount of time to give long running brute force scans per pruned level"""
        self.start_time: float = 0.0
        self.to_turn: int = 0
        """The turn to simulate up to."""

        if SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
            self.iteration_limit = 200
            self.time_limit = 10000000000.0

    def scan(
        self,
        turns: int,
        logEvals: bool = False,
        # perf_timer: PerformanceTimer | None = None,
        noThrow: bool = False,
        mcts: bool = False
    ) -> ArmySimResult:
        """
        Sims a number of turns and outputs what it believes to be the best move combination for players. Brute force approach, largely just for validating that any branch and bound approaches produce the correct result.
        @param turns:
        @return:
        """
        self.iterations: int = 0
        self.nash_eq_iterations: int = 0
        self.time_in_nash_eq: float = 0.0
        self.time_in_nash: float = 0.0

        if logEvals:
            self.log_everything = True

        if self.force_friendly_towards is not None:
            self._friendly_move_filter = lambda source, dest, board: self.force_friendly_towards[source] <= self.force_friendly_towards[dest]
        if self.force_enemy_towards is not None:
            self._enemy_move_filter = lambda source, dest, board: self.force_enemy_towards[source] <= self.force_enemy_towards[dest]
        if self.force_friendly_towards_or_parallel_to is not None:
            self._friendly_move_filter = lambda source, dest, board: self.force_friendly_towards_or_parallel_to[source] < self.force_friendly_towards_or_parallel_to[dest]
        if self.force_enemy_towards_or_parallel_to is not None:
            self._enemy_move_filter = lambda source, dest, board: self.force_enemy_towards_or_parallel_to[source] < self.force_enemy_towards_or_parallel_to[dest]

        baseBoardState = self.get_base_board_state()
        self.base_city_differential = baseBoardState.city_differential
        baseBoardState.friendly_move_generator = self.generate_friendly_moves
        baseBoardState.enemy_move_generator = self.generate_enemy_moves
        baseBoardState.initial_differential = baseBoardState.tile_differential + baseBoardState.city_differential * 25

        start = time.perf_counter()
        if not mcts:
            result = self.execute_scan_brute_force(baseBoardState, turns, noThrow=noThrow)

            duration = time.perf_counter() - start
            logging.info(f'brute force army scrim depth {turns} complete in {duration:.3f} after iter {self.iterations} (nash {self.time_in_nash:.3f} - {self.nash_eq_iterations} eq itr, {self.time_in_nash_eq:.3f} in eq)')
        else:
            result = self.execute_scan_MCTS(baseBoardState, turns, noThrow=noThrow)

            duration = time.perf_counter() - start
            logging.info(f'MONTE CARLO army scrim complete in {duration:.3f}')

        return result

    def simulate_recursive_brute_force(
            self,
            boardState: ArmySimState,
            currentTurn: int
    ) -> ArmySimState:
        """

        @param currentTurn: the current turn (in the sim, or starting turn that the current map is at)
        @param boardState: the state of the board at this position
        @return: a tuple of (the min-maxed best sim state down the tree,
        with the list of moves (and their actual board states) up the tree,
        the depth evaluated)
        """
        self.iterations += 1
        if currentTurn >= self.to_turn or (boardState.kills_all_enemy_armies and boardState.kills_all_friendly_armies):
            self.set_final_board_state_depth_estimation(boardState)

        if self.iterations & 511 == 0:
            duration = time.perf_counter() - self.start_time

            if duration > self.time_limit:
                oldTurn = self.to_turn
                self.to_turn -= 1
                if boardState.depth > 7:
                    self.to_turn -= 2
                elif boardState.depth > 5:
                    self.to_turn -= 1
                else:
                    # don't over-penalize to short depths, give them extra scan time
                    self.time_limit += self._time_limit_dec

                logging.error(f'AE BRUTE ITER {self.iterations} EXCEEDED TIME {self.time_limit:.3f} ({duration:.3f}) reducing end turn from {oldTurn} to {self.to_turn}')
                self.time_limit += self._time_limit_dec

        if (currentTurn >= self.to_turn
                or (boardState.kills_all_friendly_armies and boardState.kills_all_enemy_armies)
                or boardState.captures_enemy
                or boardState.captured_by_enemy
                or boardState.can_enemy_force_repetition
                or boardState.can_force_repetition):

            return boardState

        nextTurn = currentTurn + 1

        frMoves: typing.List[Move | None] = boardState.generate_friendly_moves()

        enMoves: typing.List[Move | None] = boardState.generate_enemy_moves()

        payoffs: typing.List[typing.List[None | ArmySimState]] = [[None for e in enMoves] for f in frMoves]

        nashPayoffs: typing.List[typing.List[int]] = [[0 for e in enMoves] for f in frMoves]

        for frIdx, frMove in enumerate(frMoves):
            for enIdx, enMove in enumerate(enMoves):
                # if (1 == 1
                #         and frMove is not None
                #         and frMove.dest.x == 3
                #         and frMove.dest.y == 4
                #         # and frMove.source.x == 0
                #         # and frMove.source.y == 9
                #         and enMove is not None
                #         and enMove.dest.x == 3
                #         and enMove.dest.y == 3
                #         and enMove.source.x == 3
                #         and enMove.source.y == 4
                #         and boardState.depth < 2
                # ):
                #     logging.info('gotcha')
                nextBoardState = self.get_next_board_state(nextTurn, boardState, frMove, enMove)
                nextResult = self.simulate_recursive_brute_force(
                    nextBoardState,
                    nextTurn
                )

                payoffs[frIdx][enIdx] = nextResult
                nashPayoffs[frIdx][enIdx] = nextResult.calculate_value_int()

                # frMoves[frMove].append(nextResult)
                # enMoves[enMove].append(nextResult)

        frEqMoves = [e for e in enumerate(frMoves)]
        enEqMoves = [e for e in enumerate(enMoves)]
        if boardState.depth < 1:
            nashStart = time.perf_counter()
            nashA = numpy.array(nashPayoffs)
            nashB = -nashA
            game = nashpy.Game(nashA, nashB)
            self.time_in_nash += time.perf_counter() - nashStart
            if boardState.depth >= 0:
                frEqMoves, enEqMoves = self.get_nash_moves_based_on_lemke_howson(
                    boardState,
                    game,
                    frEqMoves,
                    enEqMoves,
                    payoffs)
            else:
                frEqMoves, enEqMoves = self.get_nash_moves_based_on_support_enumeration(
                    boardState,
                    game,
                    frEqMoves,
                    enEqMoves,
                    payoffs)

        if self.log_everything or boardState.depth < self.log_payoff_depth:
            self.render_payoffs(boardState, frMoves, enMoves, payoffs)

        return self.get_comparison_based_expected_result_state(boardState.depth, frEqMoves, enEqMoves, payoffs)

    def simulate_recursive_alpha_beta(
            self,
            boardState: ArmySimState,
            currentTurn: int,
            maxTurn: int,
            maxTime: float = 0.02
    ) -> ArmySimResult:
        """


        Taken from https://gist.github.com/kartikkukreja/e58a77d6380f1af9b1f3

        @param currentTurn: the current turn (in the sim, or starting turn that the current map is at)
        @param maxTurn: how far to execute the sim until
        @param boardState: the state of the board at this position
        @return: a tuple of (the min-maxed best sim state down the tree,
        with the list of moves (and their actual board states) up the tree,
        the depth evaluated)
        """

        self.iterations += 1

        startTime = time.perf_counter()
        MaxUtility = 10000


        def alphaBetaSearch(state: ArmySimState, alpha, beta, depth):
            def maxValue(state: ArmySimState, alpha: int, beta: int, depth: int) -> int:
                val = -MaxUtility
                for successor in state.getSuccessors():
                    val = max(val, alphaBetaSearch(successor, alpha, beta, depth))
                    if val >= beta:
                        return val
                    alpha = max(alpha, val)
                return val

            def minValue(state: ArmySimState, alpha: int, beta: int, depth: int) -> int:
                val = MaxUtility
                for successor in state.getSuccessors():
                    val = min(val, alphaBetaSearch(successor, alpha, beta, depth - 1))
                    if val <= alpha:
                        return val
                    beta = min(beta, val)
                return val

            if state.isTerminalState():
                return state.getTerminalUtility()
            if depth <= 0 or (self.iterations & 512 == 0 and time.perf_counter() - startTime > maxTime):
                return state.calculate_value_int()
            if state.blackToMove == IsPlayerBlack:
                return maxValue(state, alpha, beta, depth)
            else:
                return minValue(state, alpha, beta, depth)

        bestMove = None
        for depth in range(1, MaxDepth):
            if time() - startTime > MaxAllowedTimeInSeconds: break
            val = -MaxUtility
            for successor in boardState.getSuccessors():
                score = alphaBetaSearch(successor, -MaxUtility, MaxUtility, depth)
                if score > val:
                    val, bestMove = score, successor.moves
        return bestMove

        # if currentTurn == stopTurn or (boardState.kills_all_enemy_armies and boardState.kills_all_friendly_armies):
        #     self.set_final_board_state_depth_estimation(boardState)
        #
        # if (currentTurn == stopTurn
        #         or (boardState.kills_all_friendly_armies and boardState.kills_all_enemy_armies)
        #         or boardState.captures_enemy
        #         or boardState.captured_by_enemy
        #         or boardState.can_enemy_force_repetition
        #         or boardState.can_force_repetition):
        #     res = ArmySimResult()
        #     res.best_result_state = boardState
        #     # res.expected_best_moves = [(boardState.friendly_move, boardState.enemy_move)]
        #     res.best_result_state_depth = stopTurn - currentTurn
        #     return res
        #
        # nextTurn = currentTurn + 1
        #
        # frMoves: typing.List[Move | None] = self.generate_friendly_moves(boardState)
        #
        # enMoves: typing.List[Move | None] = self.generate_enemy_moves(boardState)
        #
        # payoffs: typing.List[typing.List[None | ArmySimResult]] = [[None for e in enMoves] for f in frMoves]
        #
        # nashPayoffs: typing.List[typing.List[int]] = [[0 for e in enMoves] for f in frMoves]
        #
        # for frIdx, frMove in enumerate(frMoves):
        #     for enIdx, enMove in enumerate(enMoves):
        #         if (1 == 1
        #                 and frMove is not None
        #                 and frMove.dest.x == 3
        #                 and frMove.dest.y == 4
        #                 # and frMove.source.x == 0
        #                 # and frMove.source.y == 9
        #                 and enMove is not None
        #                 and enMove.dest.x == 3
        #                 and enMove.dest.y == 3
        #                 and enMove.source.x == 3
        #                 and enMove.source.y == 4
        #                 and boardState.depth < 2
        #         ):
        #             logging.info('gotcha')
        #         nextBoardState = self.get_next_board_state(nextTurn, boardState, frMove, enMove)
        #         nextResult = self.simulate_recursive_brute_force(
        #             nextBoardState,
        #             nextTurn,
        #             stopTurn
        #         )
        #
        #         payoffs[frIdx][enIdx] = nextResult
        #         nashPayoffs[frIdx][enIdx] = nextResult.best_result_state.calculate_value_int()
        #
        #         # frMoves[frMove].append(nextResult)
        #         # enMoves[enMove].append(nextResult)
        #
        # frEqMoves = [e for e in enumerate(frMoves)]
        # enEqMoves = [e for e in enumerate(enMoves)]
        # if boardState.depth < 2:
        #     nashStart = time.perf_counter()
        #     nashA = numpy.array(nashPayoffs)
        #     nashB = -nashA
        #     game = nashpy.Game(nashA, nashB)
        #     self.time_in_nash += time.perf_counter() - nashStart
        #     if boardState.depth >= 0:
        #         frEqMoves, enEqMoves = self.get_nash_moves_based_on_lemke_howson(
        #             boardState,
        #             game,
        #             frEqMoves,
        #             enEqMoves,
        #             payoffs)
        #     else:
        #         frEqMoves, enEqMoves = self.get_nash_moves_based_on_support_enumeration(
        #             boardState,
        #             game,
        #             frEqMoves,
        #             enEqMoves,
        #             payoffs)
        #
        # if self.log_everything or boardState.depth < self.log_payoff_depth:
        #     self.render_payoffs(boardState, frMoves, enMoves, payoffs)
        #
        # return self.get_comparison_based_expected_result_state(boardState.depth, frEqMoves, enEqMoves, payoffs)

    def get_next_board_state(
            self,
            turn: int,
            boardState: ArmySimState,
            frMove: Move | None,
            enMove: Move | None
    ) -> ArmySimState:
        nextBoardState = boardState.get_child_board()
        nextBoardState.friendly_move = frMove
        nextBoardState.enemy_move = enMove

        if MapBase.player_had_priority(self.friendly_player, nextBoardState.remaining_cycle_turns):
            self.execute(nextBoardState, frMove, self.friendly_player, self.enemy_player)
            if not nextBoardState.captures_enemy:
                self.execute(nextBoardState, enMove, self.enemy_player, self.friendly_player)
        else:
            self.execute(nextBoardState, enMove, self.enemy_player, self.friendly_player)
            if not nextBoardState.captured_by_enemy:
                self.execute(nextBoardState, frMove, self.friendly_player, self.enemy_player)

        if frMove is None:
            nextBoardState.friendly_skipped_move_count += 1
        if enMove is None:
            nextBoardState.enemy_skipped_move_count += 1

        self.check_army_positions(nextBoardState)

        if len(nextBoardState.friendly_living_armies) == 0:
            nextBoardState.kills_all_friendly_armies = True
        if len(nextBoardState.enemy_living_armies) == 0:
            nextBoardState.kills_all_enemy_armies = True

        if turn & 1 == 0:
            controlDiff = nextBoardState.city_differential - self.base_city_differential
            nextBoardState.controlled_city_turn_differential += controlDiff

        self.detect_repetition(boardState, nextBoardState)

        return nextBoardState

    def execute(self, nextBoardState: ArmySimState, move: Move | None, movingPlayer: int, otherPlayer: int):
        if move is None:
            return

        tileDif = 0
        cityDif = 0
        resultDest: SimTile | None = None
        capsGeneral = False
        capsCity = False

        destTile = move.dest
        sourceTile = move.source

        source = nextBoardState.sim_tiles[sourceTile]
        dest = nextBoardState.sim_tiles.get(destTile) or SimTile(destTile)

        if source.player != movingPlayer or source.army < 2:
            # tile was captured by the other player before the move was executed
            # TODO, do we need to clear any armies here or anything weird?
            return

        if dest.player != source.player:
            resultArmy = dest.army - source.army + 1
            if resultArmy < 0:
                # captured tile
                resultArmy = 0 - resultArmy
                if dest.player == otherPlayer:
                    tileDif = 2
                    if dest.source_tile.isCity:
                        cityDif = 2
                    if dest.source_tile.isGeneral:
                        capsGeneral = True
                else:  # then the player is capturing neutral / third party tiles
                    tileDif = 1
                    if dest.source_tile.isCity:
                        cityDif = 1
                resultDest = SimTile(dest.source_tile, resultArmy, source.player)
            else:
                resultDest = SimTile(dest.source_tile, resultArmy, dest.player)
        else:
            resultArmy = dest.army + source.army - 1  # no gathering in sim :V
            # TODO it SHOULD be the above instead of dest.army - 1 below, but shit is trying to waste moves gathering with scrim armies ffs
            # resultArmy = dest.army - 1
            resultDest = SimTile(dest.source_tile, resultArmy, dest.player)

        nextBoardState.sim_tiles[source.source_tile] = SimTile(source.source_tile, 1, source.player)
        nextBoardState.sim_tiles[dest.source_tile] = resultDest

        movingPlayerArmies = nextBoardState.friendly_living_armies
        otherPlayerArmies = nextBoardState.enemy_living_armies
        if movingPlayer == self.enemy_player:
            movingPlayerArmies = nextBoardState.enemy_living_armies
            otherPlayerArmies = nextBoardState.friendly_living_armies
            tileDif = 0 - tileDif
            cityDif = 0 - cityDif
            if capsGeneral:
                nextBoardState.captured_by_enemy = True
        else:
            if capsGeneral:
                nextBoardState.captures_enemy = True

        movingArmy = movingPlayerArmies.pop(source.source_tile, None)
        # if movingArmy is None:
        #     raise AssertionError("IDK???")
        capped = movingPlayer == resultDest.player

        otherArmy = otherPlayerArmies.pop(destTile, None)

        if capped:
            if resultDest.army > 1:
                movingPlayerArmies[destTile] = resultDest

        elif resultDest.army > 1:
            if otherArmy is not None:
                otherPlayerArmies[destTile] = resultDest

        nextBoardState.tile_differential += tileDif
        nextBoardState.city_differential += cityDif

    def get_base_board_state(self) -> ArmySimState:
        baseBoardState = ArmySimState(remainingCycleTurns=50 - self.map.turn % 50)

        for friendlyArmy in self.friendly_armies:
            if friendlyArmy.value > 0:
                st = SimTile(friendlyArmy.tile, friendlyArmy.value + 1, friendlyArmy.player)
                baseBoardState.friendly_living_armies[friendlyArmy.tile] = st
                baseBoardState.sim_tiles[friendlyArmy.tile] = st

        for enemyArmy in self.enemy_armies:
            if enemyArmy.value > 0:
                st = SimTile(enemyArmy.tile, enemyArmy.value + 1, self.enemy_player)
                baseBoardState.enemy_living_armies[enemyArmy.tile] = st
                baseBoardState.sim_tiles[enemyArmy.tile] = st

        baseBoardState.tile_differential = self.map.players[self.friendly_player].tileCount - self.map.players[self.enemy_player].tileCount
        baseBoardState.city_differential = self.map.players[self.friendly_player].cityCount - self.map.players[self.enemy_player].cityCount
        return baseBoardState

    def check_army_positions(self, boardState: ArmySimState):
        # no need for any of this check if neither player kills
        if not self.enemy_has_kill_threat and not self.friendly_has_kill_threat:
            return
        # if we already found an ACTUAL kill, don't fuck it up with distance logic
        if boardState.captured_by_enemy or boardState.captures_enemy:
            return

        closestFrSave = 100
        closestFrThreat = 100
        closestFrSaveTile = None
        closestFrThreatTile = None
        for tile, simTile in boardState.friendly_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
            if distToGen < closestFrSave:
                closestFrSave = distToGen
                closestFrSaveTile = tile
            if simTile.army > self.board_analysis.intergeneral_analysis.tileB.army + distToEnemy * 2:
                if distToEnemy < closestFrThreat:
                    closestFrThreat = distToEnemy
                    closestFrThreatTile = tile

        closestEnSave = 100
        closestEnThreat = 100
        closestEnSaveTile = None
        closestEnThreatTile = None
        for tile, simTile in boardState.enemy_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
            if distToEnemy < closestEnSave:
                closestEnSave = distToEnemy
                closestEnSaveTile = tile
            if simTile.army > self.board_analysis.intergeneral_analysis.tileA.army + distToGen * 2:
                if distToGen < closestEnThreat:
                    closestEnThreat = distToGen
                    closestEnThreatTile = tile

        if self.enemy_has_kill_threat and closestFrSave > closestEnThreat and (not self.friendly_has_kill_threat or closestFrThreat >= closestEnThreat):
            boardState.captured_by_enemy = True
            if self.are_tiles_adjacent(closestFrSaveTile, closestEnThreatTile) or closestFrSave < closestEnThreat:
                boardState.captured_by_enemy = False

        if self.friendly_has_kill_threat and closestEnSave > closestFrThreat and (not self.enemy_has_kill_threat or closestEnThreat >= closestFrThreat):
            boardState.captures_enemy = True
            if self.are_tiles_adjacent(closestEnSaveTile, closestFrThreatTile) or closestEnSave < closestFrThreat:
                boardState.captures_enemy = False

        if boardState.captured_by_enemy and boardState.captures_enemy:
            # see who wins the race
            if MapBase.player_had_priority(self.friendly_player, boardState.remaining_cycle_turns + closestFrThreat):
                boardState.captured_by_enemy = False
            else:
                boardState.captures_enemy = False

    def detect_repetition(self, prevBoardState, currentBoardState):
        # TODO this needs to probably track each players repetition count separately, so one rep for A followed by one rep for B doesn't trigger a rep thresh of 2, for example.
        bothNoOp = False
        bothNoOpTwice = False
        if currentBoardState.friendly_move is None and currentBoardState.enemy_move is None:
            bothNoOp = True
            if currentBoardState.prev_enemy_move is None and currentBoardState.prev_friendly_move is None and prevBoardState.depth > 1:
                bothNoOpTwice = True

        friendlyRepeats = (prevBoardState.prev_friendly_move
                           and currentBoardState.friendly_move
                           and prevBoardState.prev_friendly_move.dest.x == currentBoardState.friendly_move.dest.x
                           and prevBoardState.prev_friendly_move.dest.y == currentBoardState.friendly_move.dest.y)
        enemyRepeats = (prevBoardState.prev_enemy_move
                        and currentBoardState.enemy_move
                        and prevBoardState.prev_enemy_move.dest.x == currentBoardState.enemy_move.dest.x
                        and prevBoardState.prev_enemy_move.dest.y == currentBoardState.enemy_move.dest.y)

        if bothNoOp or friendlyRepeats or enemyRepeats:
            currentBoardState.repetition_count += 1
            if bothNoOpTwice or currentBoardState.repetition_count >= self.repetition_threshold:
                diff = currentBoardState.tile_differential + 25 * currentBoardState.city_differential
                # if diff >= 0:
                #     nextBoardState.can_force_repetition = True
                # if diff <= 0:
                #     nextBoardState.can_enemy_force_repetition = True
                if (enemyRepeats or bothNoOp) and diff >= 0:
                    currentBoardState.can_force_repetition = True
                if (friendlyRepeats or bothNoOp) and diff <= 0:
                    currentBoardState.can_enemy_force_repetition = True
                # logging.info(f'DETECTED REPETITION')
            return True
        else:
            currentBoardState.repetition_count = 0

        return False

    def generate_friendly_moves(self, boardState: ArmySimState) -> typing.List[Move | None]:
        moves = self._generate_moves(boardState.friendly_living_armies, boardState, allowOptionalNoOp=self.allow_friendly_no_op, filter=self._friendly_move_filter)
        return moves

    def generate_enemy_moves(self, boardState: ArmySimState) -> typing.List[Move | None]:
        moves = self._generate_moves(boardState.enemy_living_armies, boardState, allowOptionalNoOp=self.allow_enemy_no_op, filter=self._enemy_move_filter)
        return moves

    def _generate_moves(
            self,
            armies: typing.Dict[Tile, SimTile],
            boardState: ArmySimState,
            allowOptionalNoOp: bool = True,
            filter: typing.Callable[[Tile, Tile, ArmySimState], bool] | None = None
    ) -> typing.List[Move | None]:
        moves = []
        for armyTile in armies:
            for dest in armyTile.movable:
                if dest.isObstacle:
                    continue
                if filter is not None and filter(armyTile, dest, boardState):
                    continue
                moves.append(Move(armyTile, dest))

        if allowOptionalNoOp or len(moves) == 0:
            moves.append(None)

        return moves

    def set_final_board_state_depth_estimation(self, boardState: ArmySimState):
        pass
        # friendlyArmySizes = 0
        # enemyArmySizes = 0
        # for frArmyTile, frSimArmy in boardState.friendly_living_armies.items():
        #     distToEnemy = self.board_analysis.intergeneral_analysis.bMap[frSimArmy.source_tile.x][frSimArmy.source_tile.y]
        #     distToGen = self.board_analysis.intergeneral_analysis.aMap[frSimArmy.source_tile.x][frSimArmy.source_tile.y]
        #     if distToGen - 3 > distToEnemy:
        #         friendlyArmySizes += frSimArmy.army
        #     elif distToGen + 3 > distToEnemy:
        #         friendlyArmySizes += frSimArmy.army // 2
        # for enArmyTile, enSimArmy in boardState.enemy_living_armies.items():
        #     distToEnemy = self.board_analysis.intergeneral_analysis.bMap[enSimArmy.source_tile.x][enSimArmy.source_tile.y]
        #     distToGen = self.board_analysis.intergeneral_analysis.aMap[enSimArmy.source_tile.x][enSimArmy.source_tile.y]
        #     if distToEnemy - 3 > distToGen:
        #         enemyArmySizes += enSimArmy.army
        #     elif distToEnemy + 3 > distToGen:
        #         enemyArmySizes += enSimArmy.army // 2
        #
        # # on average lets say a surviving army can tilt tile capture one tile per turn it survives
        # frEstFinalDamage = min(friendlyArmySizes // 3, int(self.friendly_end_board_recap_weight * boardState.remaining_cycle_turns))
        # enEstFinalDamage = min(enemyArmySizes // 3, int(self.enemy_end_board_recap_weight * boardState.remaining_cycle_turns))
        # boardState.tile_differential += frEstFinalDamage
        # # make skipped moves worth one extra tile diff as the bot should be able to use those moves for something else useful.
        # boardState.tile_differential += boardState.friendly_skipped_move_count
        # boardState.tile_differential -= boardState.enemy_skipped_move_count
        # boardState.tile_differential -= enEstFinalDamage

    def render_payoffs(self, boardState: ArmySimState, frMoves, enMoves, payoffs):
        colWidth = 16
        logging.info(f'~~~')
        logging.info(boardState.get_moves_string())
        logging.info(f'~~~ {str(boardState.depth).ljust(colWidth - 4)}{" ".join([str(move).ljust(colWidth) for move in enMoves])}')

        for frIdx, frMove in enumerate(frMoves):
            payoffRow = []
            for enIdx, enMove in enumerate(enMoves):
                payoffRow.append(str(payoffs[frIdx][enIdx]).ljust(colWidth))

            logging.info(f'{str(frMove).rjust(colWidth - 2)}  {"".join(payoffRow)}')

    def are_tiles_adjacent(self, saveTile: Tile | None, threatTile: Tile | None):
        if threatTile is not None and saveTile is not None and threatTile in saveTile.movable:
            return True
        return False

    def get_comparison_based_expected_result_state(
            self,
            curDepth: int,
            frEqMoves: typing.List[typing.Tuple[int, Move | None]],
            enEqMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimState]]
    ) -> ArmySimState:
        # enemy is going to choose the move that results in the lowest maximum board state

        # build response matrix

        bestEnemyMove: Move | None = None
        bestEnemyMoveExpectedFriendlyMove: Move | None = None
        bestEnemyMoveWorstCaseFriendlyResponse: ArmySimState | None = None
        for enIdx, enMove in enEqMoves:
            curEnemyMoveWorstCaseFriendlyResponse: ArmySimState | None = None
            curEnemyExpectedFriendly = None
            for frIdx, frMove in frEqMoves:
                state = payoffs[frIdx][enIdx]
                if curEnemyMoveWorstCaseFriendlyResponse is None or state.calculate_value_int() > curEnemyMoveWorstCaseFriendlyResponse.calculate_value_int():
                    curEnemyMoveWorstCaseFriendlyResponse = state
                    curEnemyExpectedFriendly = frMove
            if bestEnemyMoveWorstCaseFriendlyResponse is None or curEnemyMoveWorstCaseFriendlyResponse.calculate_value_int() < bestEnemyMoveWorstCaseFriendlyResponse.calculate_value_int():
                bestEnemyMoveWorstCaseFriendlyResponse = curEnemyMoveWorstCaseFriendlyResponse
                bestEnemyMove = enMove
                bestEnemyMoveExpectedFriendlyMove = curEnemyExpectedFriendly

        # we can assume that any moves we have where the opponent move results in a better state is a move the opponent MUST NOT make because we have already determined that they must make a weaker move?

        # friendly is going to choose the move that results in the highest minimum board state
        bestFriendlyMove: Move | None = None
        bestFriendlyMoveExpectedEnemyMove: Move | None = None
        bestFriendlyMoveWorstCaseOpponentResponse: ArmySimState = None
        for frIdx, frMove in frEqMoves:
            curFriendlyMoveWorstCaseOpponentResponse: ArmySimState = None
            curFriendlyExpectedEnemy = None
            for enIdx, enMove in enEqMoves:
                state = payoffs[frIdx][enIdx]
                # if logEvals:
                #     logging.info(
                #         f'opponent cant make this move :D   {str(state)} <= {str(bestEnemyMoveWorstCaseFriendlyResponse)}')
                if curFriendlyMoveWorstCaseOpponentResponse is None or state.calculate_value_int() < curFriendlyMoveWorstCaseOpponentResponse.calculate_value_int():
                    curFriendlyMoveWorstCaseOpponentResponse = state
                    curFriendlyExpectedEnemy = enMove
            if bestFriendlyMoveWorstCaseOpponentResponse is None or curFriendlyMoveWorstCaseOpponentResponse.calculate_value_int() > bestFriendlyMoveWorstCaseOpponentResponse.calculate_value_int():
                bestFriendlyMoveWorstCaseOpponentResponse = curFriendlyMoveWorstCaseOpponentResponse
                bestFriendlyMove = frMove
                bestFriendlyMoveExpectedEnemyMove = curFriendlyExpectedEnemy

        if self.log_everything or curDepth < self.log_payoff_depth:
            if bestFriendlyMoveExpectedEnemyMove != bestEnemyMove or bestFriendlyMove != bestEnemyMoveExpectedFriendlyMove or bestFriendlyMoveWorstCaseOpponentResponse != bestEnemyMoveWorstCaseFriendlyResponse:
                logging.info(f'~~~  diverged, why?\r\n    FR fr: ({str(bestFriendlyMove)}) en: ({str(bestFriendlyMoveExpectedEnemyMove)})  eval {str(bestFriendlyMoveWorstCaseOpponentResponse)}\r\n    EN fr: ({str(bestEnemyMoveExpectedFriendlyMove)}) en: ({str(bestEnemyMove)})  eval {str(bestEnemyMoveWorstCaseFriendlyResponse)}\r\n')
            else:
                logging.info(f'~~~  both players agreed  fr: ({str(bestFriendlyMove)}) en: ({str(bestEnemyMove)}) eval {str(bestEnemyMoveWorstCaseFriendlyResponse)}\r\n')

        worstCaseForUs = bestFriendlyMoveWorstCaseOpponentResponse
        # worstCaseForUs = bestEnemyMoveWorstCaseFriendlyResponse
        # DONT do this, the opponent is forced to make worse plays than we think they might due to the threats we have.
        # if bestEnemyMoveWorstCaseFriendlyResponse.calculate_value() < bestFriendlyMoveWorstCaseOpponentResponse.calculate_value():
        #     worstCaseForUs = bestEnemyMoveWorstCaseFriendlyResponse
        #
        # worstCaseForUs.expected_best_moves.insert(0, (bestFriendlyMove, bestEnemyMove))
        # if logEvals:
        #     logging.info(f'\r\nworstCase tileCap {worstCaseForUs.best_result_state.tile_differential}' + '\r\n'.join([f"{str(aMove)}, {str(bMove)}" for aMove, bMove in worstCaseForUs.expected_best_moves]))
        return worstCaseForUs

    def get_nash_game_comparison_expected_result_state(
            self,
            game: nashpy.Game,
            boardState: ArmySimState,
            frEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            enEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimState]]
    ) -> typing.Tuple[typing.List[typing.Tuple[int, Move | None]], typing.List[typing.Tuple[int, Move | None]]]:
        # hack do this for now
        # return self.get_comparison_based_expected_result_state(boardState.depth, frEnumMoves, enEnumMoves, payoffs)

        return self.get_nash_moves_based_on_lemke_howson(boardState, game, frEnumMoves, enEnumMoves, payoffs)
        # for frMoveIdx, frMove in frEnumMoves:
        #     for enMoveIdx, enMove in enEnumMoves:

    def get_nash_moves_based_on_support_enumeration(
            self,
            boardState: ArmySimState,
            game: nashpy.Game,
            frEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            enEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimState]]
    ) -> typing.Tuple[typing.List[typing.Tuple[int, Move | None]], typing.List[typing.Tuple[int, Move | None]]]:
        """
        Returns just the enumeration of the moves that are part of the equilibrium.

        @param boardState:
        @param game:
        @param frEnumMoves:
        @param enEnumMoves:
        @param payoffs:
        @return:
        """
        nashEqStart = time.perf_counter()
        frEqMoves = frEnumMoves
        enEqMoves = enEnumMoves

        self.nash_eq_iterations += 1
        equilibria = [e for e in game.support_enumeration(tol=10 ** -15, non_degenerate=True)]
        if len(equilibria) > 0:
            frEqMoves = []
            enEqMoves = []
            for eq in equilibria:
                aEq, bEq = eq
                # get the nash equilibria moves
                for moveIdx, val in enumerate(aEq):
                    if val >= 0.5:
                        frEqMoves.append(frEnumMoves[moveIdx])
                for moveIdx, val in enumerate(bEq):
                    if val >= 0.5:
                        enEqMoves.append(enEnumMoves[moveIdx])

            if len(frEqMoves) > 1:
                logging.warning(
                    f'{len(frEqMoves)} fr support moves returned...? {", ".join([str(move) for move in frEqMoves])}')
            if len(enEqMoves) > 1:
                logging.warning(
                    f'{len(enEqMoves)} en support moves returned...? {", ".join([str(move) for move in enEqMoves])}')

            if len(frEqMoves) == 0 and len(frEnumMoves) > 0:
                logging.warning(
                    f'{len(frEqMoves)} fr support moves returned...? {", ".join([str(move) for move in frEqMoves])}')
                frEqMoves = frEnumMoves
            if len(enEqMoves) == 0 and len(enEnumMoves) > 0:
                logging.warning(
                    f'{len(enEqMoves)} en support moves returned...? {", ".join([str(move) for move in enEqMoves])}')
                enEqMoves = enEnumMoves

        self.time_in_nash_eq += time.perf_counter() - nashEqStart
        return frEqMoves, enEqMoves

    def get_nash_moves_based_on_lemke_howson(
            self,
            boardState: ArmySimState,
            game: nashpy.Game,
            frEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            enEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimState]]
    ) -> typing.Tuple[typing.List[typing.Tuple[int, Move | None]], typing.List[typing.Tuple[int, Move | None]]]:
        """
        Returns just the enumeration of the moves that are part of the equilibrium.

        @param boardState:
        @param game:
        @param frEnumMoves:
        @param enEnumMoves:
        @param payoffs:
        @return:
        """
        nashEqStart = time.perf_counter()
        frEqMoves = frEnumMoves
        enEqMoves = enEnumMoves

        self.nash_eq_iterations += 1
        if len(frEqMoves) < 2 or len(enEqMoves) < 2:
            return self.get_nash_moves_based_on_support_enumeration(boardState, game, frEnumMoves, enEnumMoves, payoffs)

        equilibria = game.lemke_howson(initial_dropped_label=0)
        if equilibria is not None:
            eq = equilibria
        # if len(equilibria) > 0:
            frEqMoves = []
            enEqMoves = []
        #     for eq in equilibria:
            aEq, bEq = eq
            # get the nash equilibria moves
            for moveIdx, val in enumerate(aEq):
                if val >= 0.5:
                    frEqMoves.append(frEnumMoves[moveIdx])
            for moveIdx, val in enumerate(bEq):
                if val >= 0.5:
                    enEqMoves.append(enEnumMoves[moveIdx])

        if len(frEqMoves) > 1:
            logging.warning(
                f'{len(frEqMoves)} fr lemke moves returned...? {", ".join([str(move) for move in frEqMoves])}')
        if len(enEqMoves) > 1:
            logging.warning(
                f'{len(enEqMoves)} en lemke moves returned...? {", ".join([str(move) for move in enEqMoves])}')

        if len(frEqMoves) == 0 and len(frEnumMoves) > 0:
            logging.warning(
                f'{len(frEqMoves)} fr lemke moves returned...? {", ".join([str(move) for move in frEqMoves])}')
            frEqMoves = frEnumMoves
        if len(enEqMoves) == 0 and len(enEnumMoves) > 0:
            logging.warning(
                f'{len(enEqMoves)} en lemke moves returned...? {", ".join([str(move) for move in enEqMoves])}')
            enEqMoves = enEnumMoves

        self.time_in_nash_eq += time.perf_counter() - nashEqStart
        return frEqMoves, enEqMoves

    def execute_scan_brute_force(
            self,
            baseBoardState: ArmySimState,
            turns: int,
            noThrow: bool = False
    ) -> ArmySimResult:
        # we gradually cut off the recursive search depth so the time limit is more a time suggestion, unlike mcts. Back the initial cutoff off slightly.
        self._time_limit_dec = max(self.time_limit * 0.09, 0.004)
        self.time_limit = min(self.time_limit, self.time_limit * 0.6 + 0.007)

        multiFriendly = len(self.friendly_armies) > 1
        multiEnemy = len(self.enemy_armies) > 1
        self.to_turn = self.map.turn + turns
        self.start_time = time.perf_counter()
        ogDiff = baseBoardState.tile_differential + baseBoardState.city_differential * 25

        final_state: ArmySimState = self.simulate_recursive_brute_force(
            baseBoardState,
            self.map.turn)
        result = ArmySimResult(final_state)
        result.best_result_state_depth = final_state.depth

        afterScrimDiff = result.best_result_state.tile_differential + result.best_result_state.city_differential * 25
        result.net_economy_differential = afterScrimDiff - ogDiff

        # build the expected move list up the tree
        equilibriumBoard = result.best_result_state
        # intentionally while .parent_board isn't none to skip the top board, since it will show both moves as None
        parentFr = None
        parentEn = None
        curBoard = equilibriumBoard
        boards = []
        while curBoard is not None:
            boards.append(curBoard)
            curBoard = curBoard.parent_board

        for curBoard in boards:
            if curBoard.parent_board is None:
                continue
            curFr = curBoard.friendly_move
            curEn = curBoard.enemy_move
            result.expected_best_moves.insert(0, (curFr, curEn))
            if curFr is not None:
                if parentFr is not None:
                    if curFr.source not in parentFr.source.movable and not multiFriendly:
                        msg = f"yo, wtf, invalid friendly move sequence returned {str(curFr)}+{str(parentFr)}"
                        if not noThrow:
                            raise AssertionError(msg)
                        else:
                            logging.error(msg)
                parentFr = curFr
            if curEn is not None:
                if parentEn is not None:
                    if curEn.source not in parentEn.source.movable and not multiEnemy:
                        msg = f"yo, wtf, invalid enemy move sequence returned {str(curEn)}+{str(parentEn)}"
                        if not noThrow:
                            raise AssertionError(msg)
                        else:
                            logging.error(msg)
                parentEn = curEn

        return result

    def execute_scan_MCTS(
            self,
            baseBoardState: ArmySimState,
            turns: int,
            noThrow: bool = False
    ):
        # multiFriendly = len(self.friendly_armies) > 1
        # multiEnemy = len(self.enemy_armies) > 1

        mctsRunner: MctsDUCT = MctsDUCT()
        game: Game = Game()
        ctx: Context = Context()
        ctx.set_initial_board_state(self, baseBoardState, game, self.map.turn)

        mctsSummary = mctsRunner.select_action(game, ctx, self.time_limit, self.iteration_limit)
        result = ArmySimResult(mctsSummary.best_result_state)
        result.expected_best_moves = [(bm.playerMoves[0], bm.playerMoves[1]) for bm in mctsSummary.best_moves]

        logging.info(f'MCTS iter {mctsRunner.iterations}, nodesExplored {mctsRunner.nodes_explored}, rollouts {mctsRunner.trials_performed}, backprops {mctsRunner.backprop_iter}, rolloutExpansions {game.rollout_expansions}, biasedRolloutExpansions {game.biased_rollout_expansions}')

        return result

