from __future__ import annotations

import logging
import time
import typing

import nashpy
import numpy

from ArmyAnalyzer import ArmyAnalyzer
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from base.client.map import MapBase, Tile, MapMatrix


class SimTile(object):
    def __init__(self, sourceTile: Tile, army: int | None = None, player: int | None = None):
        self.source_tile = sourceTile
        self.army = sourceTile.army if army is None else army
        self.player = sourceTile.player if player is None else player

    def __str__(self):
        return f"[{self.source_tile.x},{self.source_tile.y} p{self.player} a{self.army}]"

    def __repr__(self):
        return str(self)


class ArmySimState(object):
    def __init__(
            self,
            remainingCycleTurns: int,
            simTiles: typing.Dict[Tile, SimTile] | None = None,
            friendlyLivingArmies: typing.Dict[Tile, SimTile] | None = None,
            enemyLivingArmies: typing.Dict[Tile, SimTile] | None = None
    ):
        if simTiles is None:
            simTiles = {}

        if friendlyLivingArmies is None:
            friendlyLivingArmies = {}

        if enemyLivingArmies is None:
            enemyLivingArmies = {}

        self.remaining_cycle_turns: int = remainingCycleTurns

        self.depth: int = 0

        self.tile_differential: int = 0
        """negative means they captured our tiles, positive means we captured theirs"""

        self.city_differential: int = 0
        """
        negative means they have that many more cities active than us, positive means we have more. 
        This is as of the CURRENT board state; bonuses owned is covered under the *city_control_turns fields.
        """

        self.captures_enemy: bool = False
        """if kill on enemy general appears guaranteed"""

        self.captured_by_enemy: bool = False
        """if kill against our general appears guaranteed"""

        self.can_force_repetition: bool = False
        """if we can force a repetition in our favor"""

        self.can_enemy_force_repetition: bool = False
        """if the enemy can force a repetition in their favor"""

        self.kills_all_friendly_armies: bool = False
        """If their armies kill friendly armies with 3+ army to spare (ignoring remaining tile capture)"""

        self.kills_all_enemy_armies: bool = False
        """If our armies kill all enemy armies with 3+ army to spare (ignoring remaining tile capture)"""

        self.sim_tiles: typing.Dict[Tile, SimTile] = simTiles
        """
        the set of tiles that have been involved in the scrim so far, tracking the current owner and army amount on them
        """

        self.friendly_city_control_turns: int = 0
        """
        for cities in the scrim area, this is how many turns WE were able to control a city 
        that would otherwise have been controlled by an enemy.
        """

        self.enemy_city_control_turns: int = 0
        """
        for cities in the scrim area, this is how many turns an enemy was able to control a city 
        that would otherwise have been controlled by us.
        """

        self.friendly_living_armies: typing.Dict[Tile, SimTile] = friendlyLivingArmies
        """
        Actively alive friendly armies at this point in the board state
        """

        self.enemy_living_armies: typing.Dict[Tile, SimTile] = enemyLivingArmies
        """
        Actively alive enemy armies at this point in the board state
        """

        self.friendly_skipped_move_count: int = 0
        """How many times friendly has no-opped already"""

        self.enemy_skipped_move_count: int = 0
        """How many times enemy has no-opped already"""

        self.friendly_move: Move | None = None
        """Friendly move made to reach this board state"""

        self.enemy_move: Move | None = None
        """Enemy move made to reach this board state"""

        self.prev_friendly_move: Move | None = None
        """Friendly move made before the last move to reach this board state, for detecting repetitions"""

        self.prev_enemy_move: Move | None = None
        """Enemy move made before the last move to reach this board state, for detecting repetitions"""

        self.repetition_count: int = 0

        self.parent_board: ArmySimState | None = None

    def get_child_board(self) -> ArmySimState:
        copy = ArmySimState(self.remaining_cycle_turns - 1, self.sim_tiles.copy(), self.friendly_living_armies.copy(), self.enemy_living_armies.copy())
        copy.tile_differential = self.tile_differential
        copy.city_differential = self.city_differential
        copy.captures_enemy = self.captures_enemy
        copy.captured_by_enemy = self.captured_by_enemy
        copy.can_force_repetition = self.can_force_repetition
        copy.can_enemy_force_repetition = self.can_enemy_force_repetition
        copy.kills_all_friendly_armies = self.kills_all_friendly_armies
        copy.kills_all_enemy_armies = self.kills_all_enemy_armies
        copy.enemy_city_control_turns = self.enemy_city_control_turns
        copy.friendly_city_control_turns = self.friendly_city_control_turns
        copy.friendly_skipped_move_count = self.friendly_skipped_move_count
        copy.enemy_skipped_move_count = self.enemy_skipped_move_count
        copy.repetition_count = self.repetition_count
        copy.depth = self.depth + 1

        copy.prev_friendly_move = self.friendly_move
        copy.prev_enemy_move = self.enemy_move
        copy.parent_board = self

        return copy

    def get_moves_string(self):
        frMoves = []
        enMoves = []
        curState = self
        # intentionally while .parent_board isn't none to skip the top board, since it will show both moves as None
        while curState.parent_board is not None:
            frMoves.insert(0, curState.friendly_move)
            enMoves.insert(0, curState.enemy_move)
            curState = curState.parent_board

        fr = f'fr: {" -> ".join([str(move.dest).ljust(5) if move is not None else "None " for move in frMoves])}'
        en = f'en: {" -> ".join([str(move.dest).ljust(5) if move is not None else "None " for move in enMoves])}'

        return f"{fr}\r\n{en}"

    def __repr__(self):
        return f'{str(self)} [{self.get_moves_string()}]'

    def __str__(self):
        pieces = [f'(d{self.depth}) {self.get_econ_value():+d}']

        if self.kills_all_friendly_armies and self.kills_all_enemy_armies:
            pieces.append(f'x ')
        elif self.kills_all_friendly_armies:
            pieces.append(f'x-')
        elif self.kills_all_enemy_armies:
            pieces.append(f'x+')

        if self.can_enemy_force_repetition and self.can_force_repetition:
            pieces.append('REP')
        elif self.can_force_repetition:
            pieces.append('REP+')
        elif self.can_enemy_force_repetition:
            pieces.append('REP-')

        if self.captures_enemy:
            pieces.append('WIN')

        if self.captured_by_enemy:
            pieces.append('LOSS')

        return ' '.join(pieces)

    def calculate_value(self) -> typing.Tuple:
        econDiff = self.get_econ_value()
        return (
            self.captures_enemy,
            not self.captured_by_enemy,
            # self.can_force_repetition,
            # not self.can_enemy_force_repetition,
            econDiff,
            self.friendly_skipped_move_count,
            0 - self.enemy_skipped_move_count,
            self.kills_all_enemy_armies,
            not self.kills_all_friendly_armies,
        )

    def calculate_value_int(self) -> int:
        """Gets a (10x econ diff based) integer representation of the value of the board state. Used for Nashpy"""
        econDiff = self.get_econ_value() * 10
        if self.captures_enemy:
            econDiff += 10000
        if self.captured_by_enemy:
            econDiff -= 10000
        # skipped moves are worth 0.7 econ each
        econDiff += self.friendly_skipped_move_count * 5
        #enemy skipped moves are worth slightly less..? than ours?
        econDiff -= self.enemy_skipped_move_count * 4

        # if self.kills_all_enemy_armies:
        #     econDiff += 5
        # if self.kills_all_friendly_armies:
        #     econDiff -= 5

        return econDiff

    def get_econ_value(self) -> int:
        return (self.tile_differential
                + 25 * self.city_differential
                + self.friendly_city_control_turns
                - self.enemy_city_control_turns)


class ArmySimResult(object):
    def __init__(self, cacheDepth: int = 5):
        self.best_result_state: ArmySimState = None

        self.best_result_state_depth: int = 0

        self.net_economy_differential: int = 0

        self.expected_best_moves: typing.List[typing.Tuple[Move, Move]] = []
        """A list of (friendly, enemy) move tuples that the min-max best move board state is expected to take"""

        self.cache_depth: int = cacheDepth

        self.expected_moves_cache: ArmySimCache = None
        """
        A cache of the current and alternate move branches (for the enemy, since we know what 
        move we will make we dont care about our alternates), out to cacheDepth depth, 
        to be used on future turns to save time recalculating the full board tree from 
        scratch every turn. If the move wasn't in cache, then we didn't think it was remotely valuable.
        IF the opp makes a move outside this dict and our board evaluation goes down, then the analysis
        here was poor and should be logged and tests written to predict the better opponent move next time.
        """

    def calculate_value(self) -> typing.Tuple:
        return (self.best_result_state.calculate_value_int(), False)

    def __str__(self):
        return f'({self.net_economy_differential:+d}) {str(self.best_result_state)}'

    def __repr__(self):
        return f'{str(self)} [{self.calculate_value()}]'


class ArmySimCache(object):
    def __init__(
            self,
            friendlyMove: Move,
            enemyMove: Move,
            simState: ArmySimState,
            subTreeCache: typing.Dict[Tile, ArmySimCache] | None = None
    ):
        self.friendly_move: Move = friendlyMove
        self.enemy_move: Move = enemyMove
        self.sim_state: ArmySimState = simState
        self.move_tree_cache: typing.Dict[Tile, ArmySimCache] | None = subTreeCache


class ArmyEngine(object):
    def __init__(
            self,
            map: MapBase,
            friendlyArmies: typing.List[Army],
            enemyArmies: typing.List[Army],
            boardAnalysis: BoardAnalyzer,
            friendlyCaptureValues: MapMatrix | None = None,
            enemyCaptureValues: MapMatrix | None = None,
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

        self.repetition_threshold: int = 2
        """How many repeated tiles in a row constitute a repetition."""

        if len(friendlyArmies) == 1 and len(enemyArmies) == 1:
            # Cool, we can inter-analyze armies
            self.inter_army_analysis = ArmyAnalyzer(map, friendlyArmies[0], enemyArmies[0])

        self._friendly_move_filter: typing.Callable[[Tile, Tile, ArmySimState], bool] | None = None

        self._enemy_move_filter: typing.Callable[[Tile, Tile, ArmySimState], bool] | None = None

        self.log_everything: bool = False

        self.log_payoff_depth: int = 1
        """Even without log_everything set, log payoffs at or below this depth. Depth 1 will log the payoffs for all moves from starting position."""

    def scan(
            self,
            turns: int,
            logEvals: bool = False,
            # perf_timer: PerformanceTimer | None = None,
            noThrow: bool = False
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

        multiFriendly = len(self.friendly_armies) > 1
        multiEnemy = len(self.enemy_armies) > 1

        baseBoardState = self.get_base_board_state()
        start = time.perf_counter()
        result: ArmySimResult = self.simulate_recursive_brute_force(
            baseBoardState,
            self.map.turn,
            self.map.turn + turns)

        ogDiff = baseBoardState.tile_differential + baseBoardState.city_differential * 25
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

        duration = time.perf_counter() - start
        logging.info(f'brute force army scrim depth {turns} complete in {duration:.3f} after iter {self.iterations} (nash {self.time_in_nash:.3f} - {self.nash_eq_iterations} eq itr, {self.time_in_nash_eq:.3f} in eq)')

        # moves are appended in reverse order, so reverse them
        # result.expected_best_moves = [m for m in reversed(result.expected_best_moves)]

        return result

    def simulate_recursive_brute_force(
            self,
            boardState: ArmySimState,
            currentTurn: int,
            stopTurn: int
    ) -> ArmySimResult:
        """

        @param currentTurn: the current turn (in the sim, or starting turn that the current map is at)
        @param stopTurn: how far to execute the sim until
        @param boardState: the state of the board at this position
        @return: a tuple of (the min-maxed best sim state down the tree,
        with the list of moves (and their actual board states) up the tree,
        the depth evaluated)
        """
        self.iterations += 1
        if currentTurn == stopTurn or (boardState.kills_all_enemy_armies and boardState.kills_all_friendly_armies):
            self.set_final_board_state_depth_estimation(boardState)

        if (currentTurn == stopTurn
                or (boardState.kills_all_friendly_armies and boardState.kills_all_enemy_armies)
                or boardState.captures_enemy
                or boardState.captured_by_enemy
                or boardState.can_enemy_force_repetition
                or boardState.can_force_repetition):
            res = ArmySimResult()
            res.best_result_state = boardState
            # res.expected_best_moves = [(boardState.friendly_move, boardState.enemy_move)]
            res.best_result_state_depth = stopTurn - currentTurn
            return res

        nextTurn = currentTurn + 1

        frMoves: typing.List[Move | None] = self.generate_friendly_moves(boardState)

        enMoves: typing.List[Move | None] = self.generate_enemy_moves(boardState)

        payoffs: typing.List[typing.List[None | ArmySimResult]] = [[None for e in enMoves] for f in frMoves]

        nashPayoffs: typing.List[typing.List[int]] = [[0 for e in enMoves] for f in frMoves]

        for frIdx, frMove in enumerate(frMoves):
            for enIdx, enMove in enumerate(enMoves):
                if (1 == 1
                        and frMove is not None
                        and frMove.dest.x == 3
                        and frMove.dest.y == 4
                        # and frMove.source.x == 0
                        # and frMove.source.y == 9
                        and enMove is not None
                        and enMove.dest.x == 3
                        and enMove.dest.y == 3
                        and enMove.source.x == 3
                        and enMove.source.y == 4
                        and boardState.depth < 2
                ):
                    logging.info('gotcha')
                nextBoardState = self.get_next_board_state(nextTurn, boardState, frMove, enMove)
                nextResult = self.simulate_recursive_brute_force(
                    nextBoardState,
                    nextTurn,
                    stopTurn
                )

                payoffs[frIdx][enIdx] = nextResult
                nashPayoffs[frIdx][enIdx] = nextResult.best_result_state.calculate_value_int()

                # frMoves[frMove].append(nextResult)
                # enMoves[enMove].append(nextResult)

        frEqMoves = [e for e in enumerate(frMoves)]
        enEqMoves = [e for e in enumerate(enMoves)]
        if boardState.depth < 2:
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

        return self.get_comparison_based_expected_result_state(boardState, frEqMoves, enEqMoves, payoffs)

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

        if self.player_had_priority(self.friendly_player, nextBoardState.remaining_cycle_turns):
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

        self.detect_repetition(boardState, nextBoardState)

        return nextBoardState

    def execute(self, nextBoardState: ArmySimState, move: Move | None, movingPlayer: int, otherPlayer: int):
        if move is None:
            return

        tileDif = 0
        cityDif = 0
        resultDest: SimTile | None = None
        capsGeneral = False

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
        if movingArmy is None:
            raise AssertionError("IDK???")
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
            if ArmyEngine.player_had_priority(self.friendly_player, boardState.remaining_cycle_turns + closestFrThreat):
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
        friendlyArmySizes = 0
        enemyArmySizes = 0
        for frArmyTile, frSimArmy in boardState.friendly_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[frSimArmy.source_tile.x][frSimArmy.source_tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[frSimArmy.source_tile.x][frSimArmy.source_tile.y]
            if distToGen - 3 > distToEnemy:
                friendlyArmySizes += frSimArmy.army
            elif distToGen + 3 > distToEnemy:
                friendlyArmySizes += frSimArmy.army // 2
        for enArmyTile, enSimArmy in boardState.enemy_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[enSimArmy.source_tile.x][enSimArmy.source_tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[enSimArmy.source_tile.x][enSimArmy.source_tile.y]
            if distToEnemy - 3 > distToGen:
                enemyArmySizes += enSimArmy.army
            elif distToEnemy + 3 > distToGen:
                enemyArmySizes += enSimArmy.army // 2

        # on average lets say a surviving army can tilt tile capture one tile per turn it survives
        frEstFinalDamage = min(friendlyArmySizes // 3, int(self.friendly_end_board_recap_weight * boardState.remaining_cycle_turns))
        enEstFinalDamage = min(enemyArmySizes // 3, int(self.enemy_end_board_recap_weight * boardState.remaining_cycle_turns))
        boardState.tile_differential += frEstFinalDamage
        # make skipped moves worth one extra tile diff as the bot should be able to use those moves for something else useful.
        boardState.tile_differential += boardState.friendly_skipped_move_count
        boardState.tile_differential -= boardState.enemy_skipped_move_count
        boardState.tile_differential -= enEstFinalDamage

    def render_payoffs(self, boardState: ArmySimState, frMoves, enMoves, payoffs):
        colWidth = 16
        logging.info(f'~~~')
        logging.info(boardState.get_moves_string())
        logging.info(f'~~~ {str(boardState.depth).ljust(colWidth - 4)}{" ".join([str(move).ljust(colWidth) for move in enMoves])}')

        for frIdx, frMove in enumerate(frMoves):
            payoffRow = []
            for enIdx, enMove in enumerate(enMoves):
                payoffRow.append(str(payoffs[frIdx][enIdx].best_result_state).ljust(colWidth))

            logging.info(f'{str(frMove).rjust(colWidth - 2)}  {"".join(payoffRow)}')

    @staticmethod
    def player_had_priority(player: int, turn: int):
        """Whether the player HAD priority on the current turns move that they sent last turn"""
        return player & 1 != turn & 1

    @staticmethod
    def player_has_priority(player: int, turn: int):
        """Whether the player WILL HAVE priority on the move they are about to make on current turn"""
        return player & 1 == turn & 1

    def are_tiles_adjacent(self, saveTile: Tile | None, threatTile: Tile | None):
        if threatTile is not None and saveTile is not None and threatTile in saveTile.movable:
            return True
        return False

    #
    # def scan_mcts(self):
    #     """thiefed from https://pastebin.com/bUcRrKwF / https://www.youtube.com/watch?v=gvlO_-Fdk9w"""
    #     ### The Monte Carlo Search Tree AI
    #
    #     ### 1 - It takes the current game state
    #
    #     ### 2 - It runs multiple random game simulations starting from this game state
    #
    #     ### 3 - For each simulation, the final state is evaluated by a score (higher score = better outcome)
    #
    #     ### 4 - It only remembers the next move of each simulation and accumulates the scores for that move
    #
    #     ### 5 - Finally, it returns the next move with the highest score
    #
    #     import random
    #     import ast
    #
    #     userPlayer = 'O'
    #     # boardSize = 3
    #     numberOfSimulations = 200
    #
    #     startingPlayer = 'X'
    #     currentPlayer = startingPlayer
    #
    #     def getBoardCopy(board):
    #         boardCopy = []
    #
    #         for row in board:
    #             boardCopy.append(row.copy())
    #
    #         return boardCopy
    #
    #     def hasMovesLeft(board):
    #         for y in range(boardSize):
    #             for x in range(boardSize):
    #                 if board[y][x] == '.':
    #                     return True
    #
    #         return False
    #
    #     def getNextMoves(currentBoard, player):
    #         nextMoves = []
    #
    #         for y in range(boardSize):
    #             for x in range(boardSize):
    #                 if currentBoard[y][x] == '.':
    #                     boardCopy = getBoardCopy(currentBoard)
    #                     boardCopy[y][x] = player
    #                     nextMoves.append(boardCopy)
    #
    #         return nextMoves
    #
    #     def hasWon(currentBoard, player):
    #         winningSet = [player for _ in range(boardSize)]
    #
    #         for row in currentBoard:
    #             if row == winningSet:
    #                 return True
    #
    #         for y in range(len(currentBoard)):
    #             column = [currentBoard[index][y] for index in range(boardSize)]
    #
    #             if column == winningSet:
    #                 return True
    #
    #         diagonal1 = []
    #         diagonal2 = []
    #         for index in range(len(currentBoard)):
    #             diagonal1.append(currentBoard[index][index])
    #             diagonal2.append(currentBoard[index][boardSize - index - 1])
    #
    #         if diagonal1 == winningSet or diagonal2 == winningSet:
    #             return True
    #
    #         return False
    #
    #     def getNextPlayer(currentPlayer):
    #         if currentPlayer == 'X':
    #             return 'O'
    #
    #         return 'X'
    #
    #     def getBestNextMove(currentBoard, currentPlayer):
    #         evaluations = {}
    #
    #         for generation in range(numberOfSimulations):
    #             player = currentPlayer
    #             boardCopy = getBoardCopy(currentBoard)
    #
    #             simulationMoves = []
    #             nextMoves = getNextMoves(boardCopy, player)
    #
    #             score = boardSize * boardSize
    #
    #             while nextMoves != []:
    #                 roll = random.randint(1, len(nextMoves)) - 1
    #                 boardCopy = nextMoves[roll]
    #
    #                 simulationMoves.append(boardCopy)
    #
    #                 if hasWon(boardCopy, player):
    #                     break
    #
    #                 score -= 1
    #
    #                 player = getNextPlayer(player)
    #                 nextMoves = getNextMoves(boardCopy, player)
    #
    #             firstMove = simulationMoves[0]
    #             lastMove = simulationMoves[-1]
    #
    #             firstMoveKey = repr(firstMove)
    #
    #             if player == userPlayer and hasWon(boardCopy, player):
    #                 score *= -1
    #
    #             if firstMoveKey in evaluations:
    #                 evaluations[firstMoveKey] += score
    #             else:
    #                 evaluations[firstMoveKey] = score
    #
    #         bestMove = []
    #         highestScore = 0
    #         firstRound = True
    #
    #         for move, score in evaluations.items():
    #             if firstRound or score > highestScore:
    #                 highestScore = score
    #                 bestMove = ast.literal_eval(move)
    #                 firstRound = False
    #
    #         return bestMove
    #
    #     def printBoard(board):
    #         firstRow = True
    #
    #         for index in range(boardSize):
    #             if firstRow:
    #                 print('  012')
    #                 firstRow = False
    #
    #             print(str(index) + ' ' + ''.join(board[index]))
    #
    #     def getPlayerMove(board, currentPlayer):
    #         isMoveValid = False
    #         while isMoveValid == False:
    #             print('')
    #             userMove = input('X,Y? ')
    #             userX, userY = map(int, userMove.split(','))
    #
    #             if board[userY][userX] == '.':
    #                 isMoveValid = True
    #
    #         board[userY][userX] = currentPlayer
    #         return board
    #
    #     printBoard(board)
    #
    #     while hasMovesLeft(board):
    #         if currentPlayer == userPlayer:
    #             board = getPlayerMove(board, currentPlayer)
    #         else:
    #             board = getBestNextMove(board, currentPlayer)
    #
    #         print('')
    #         printBoard(board)
    #
    #         if hasWon(board, currentPlayer):
    #             print('Player ' + currentPlayer + ' has won!')
    #             break
    #
    #         currentPlayer = getNextPlayer(currentPlayer)
    def get_comparison_based_expected_result_state(
            self,
            boardState: ArmySimState,
            frEqMoves: typing.List[typing.Tuple[int, Move | None]],
            enEqMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimResult]]
    ) -> ArmySimResult:
        # enemy is going to choose the move that results in the lowest maximum board state

        # build response matrix

        bestEnemyMove: Move | None = None
        bestEnemyMoveExpectedFriendlyMove: Move | None = None
        bestEnemyMoveWorstCaseFriendlyResponse: ArmySimResult | None = None
        for enIdx, enMove in enEqMoves:
            curEnemyMoveWorstCaseFriendlyResponse: ArmySimResult | None = None
            curEnemyExpectedFriendly = None
            for frIdx, frMove in frEqMoves:
                state = payoffs[frIdx][enIdx]
                if curEnemyMoveWorstCaseFriendlyResponse is None or state.calculate_value() > curEnemyMoveWorstCaseFriendlyResponse.calculate_value():
                    curEnemyMoveWorstCaseFriendlyResponse = state
                    curEnemyExpectedFriendly = frMove
            if bestEnemyMoveWorstCaseFriendlyResponse is None or curEnemyMoveWorstCaseFriendlyResponse.calculate_value() < bestEnemyMoveWorstCaseFriendlyResponse.calculate_value():
                bestEnemyMoveWorstCaseFriendlyResponse = curEnemyMoveWorstCaseFriendlyResponse
                bestEnemyMove = enMove
                bestEnemyMoveExpectedFriendlyMove = curEnemyExpectedFriendly

        # we can assume that any moves we have where the opponent move results in a better state is a move the opponent MUST NOT make because we have already determined that they must make a weaker move?

        # friendly is going to choose the move that results in the highest minimum board state
        bestFriendlyMove: Move | None = None
        bestFriendlyMoveExpectedEnemyMove: Move | None = None
        bestFriendlyMoveWorstCaseOpponentResponse: ArmySimResult = None
        for frIdx, frMove in frEqMoves:
            curFriendlyMoveWorstCaseOpponentResponse: ArmySimResult = None
            curFriendlyExpectedEnemy = None
            for enIdx, enMove in enEqMoves:
                state = payoffs[frIdx][enIdx]
                # if logEvals:
                #     logging.info(
                #         f'opponent cant make this move :D   {str(state)} <= {str(bestEnemyMoveWorstCaseFriendlyResponse)}')
                if curFriendlyMoveWorstCaseOpponentResponse is None or state.calculate_value() < curFriendlyMoveWorstCaseOpponentResponse.calculate_value():
                    curFriendlyMoveWorstCaseOpponentResponse = state
                    curFriendlyExpectedEnemy = enMove
            if bestFriendlyMoveWorstCaseOpponentResponse is None or curFriendlyMoveWorstCaseOpponentResponse.calculate_value() > bestFriendlyMoveWorstCaseOpponentResponse.calculate_value():
                bestFriendlyMoveWorstCaseOpponentResponse = curFriendlyMoveWorstCaseOpponentResponse
                bestFriendlyMove = frMove
                bestFriendlyMoveExpectedEnemyMove = curFriendlyExpectedEnemy

        if self.log_everything or boardState.depth < self.log_payoff_depth:
            if bestFriendlyMoveExpectedEnemyMove != bestEnemyMove or bestFriendlyMove != bestEnemyMoveExpectedFriendlyMove or bestFriendlyMoveWorstCaseOpponentResponse != bestEnemyMoveWorstCaseFriendlyResponse:
                logging.info(f'~~~  diverged, why?\r\n    FR fr: ({str(bestFriendlyMove)}) en: ({str(bestFriendlyMoveExpectedEnemyMove)})  eval {str(bestFriendlyMoveWorstCaseOpponentResponse.best_result_state)}\r\n    EN fr: ({str(bestEnemyMoveExpectedFriendlyMove)}) en: ({str(bestEnemyMove)})  eval {str(bestEnemyMoveWorstCaseFriendlyResponse.best_result_state)}\r\n')
            else:
                logging.info(f'~~~  both players agreed  fr: ({str(bestFriendlyMove)}) en: ({str(bestEnemyMove)}) eval {str(bestEnemyMoveWorstCaseFriendlyResponse.best_result_state)}\r\n')

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
            payoffs: typing.List[typing.List[ArmySimResult]]
    ) -> typing.Tuple[typing.List[typing.Tuple[int, Move | None]], typing.List[typing.Tuple[int, Move | None]]]:
        # hack do this for now
        # return self.get_comparison_based_expected_result_state(boardState, frEnumMoves, enEnumMoves, payoffs)

        return self.get_nash_moves_based_on_lemke_howson(boardState, game, frEnumMoves, enEnumMoves, payoffs)
        # for frMoveIdx, frMove in frEnumMoves:
        #     for enMoveIdx, enMove in enEnumMoves:


    def get_nash_moves_based_on_support_enumeration(
            self,
            boardState: ArmySimState,
            game: nashpy.Game,
            frEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            enEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimResult]]
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

            if len(frEqMoves) == 0 and len(frEnumMoves) > 0:
                raise AssertionError(f'No fr moves returned...?')
            if len(enEqMoves) == 0 and len(enEnumMoves) > 0:
                raise AssertionError(f'No en moves returned...?')

            if len(frEqMoves) > 1:
                logging.warning(
                    f'{len(frEqMoves)} fr moves returned...? {", ".join([str(move) for move in frEqMoves])}')
            if len(enEqMoves) > 1:
                logging.warning(
                    f'{len(enEqMoves)} en moves returned...? {", ".join([str(move) for move in enEqMoves])}')
        self.time_in_nash_eq += time.perf_counter() - nashEqStart
        return frEqMoves, enEqMoves

    def get_nash_moves_based_on_lemke_howson(
            self,
            boardState: ArmySimState,
            game: nashpy.Game,
            frEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            enEnumMoves: typing.List[typing.Tuple[int, Move | None]],
            payoffs: typing.List[typing.List[ArmySimResult]]
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

        if len(frEqMoves) == 0 and len(frEnumMoves) > 0:
            frEqMoves = frEnumMoves
        if len(enEqMoves) == 0 and len(enEnumMoves) > 0:
            enEqMoves = enEnumMoves

        if len(frEqMoves) > 1:
            logging.warning(
                f'{len(frEqMoves)} fr moves returned...? {", ".join([str(move) for move in frEqMoves])}')
        if len(enEqMoves) > 1:
            logging.warning(
                f'{len(enEqMoves)} en moves returned...? {", ".join([str(move) for move in enEqMoves])}')
        self.time_in_nash_eq += time.perf_counter() - nashEqStart
        return frEqMoves, enEqMoves

