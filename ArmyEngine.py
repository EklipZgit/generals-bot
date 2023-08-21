from __future__ import annotations

import logging
import time
import typing

from ArmyAnalyzer import ArmyAnalyzer
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from PerformanceTimer import PerformanceTimer
from base.client.map import MapBase, Tile


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

        self.friendly_has_wasted_move = False
        """Whether friendly has no-opped already"""

        self.enemy_has_wasted_move = False
        """Whether enemy has no-opped already"""

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
        copy.friendly_has_wasted_move = self.friendly_has_wasted_move
        copy.enemy_has_wasted_move = self.enemy_has_wasted_move
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
        return str(self)

    def __str__(self):
        pieces = [f'{self.tile_differential + 25 * self.city_differential:+d}']

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


class ArmySimResult(object):
    def __init__(self, cacheDepth: int = 5):
        self.best_result_state: ArmySimState = None

        self.best_result_state_depth: int = 0

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

    def calculate_value(self) -> typing.Tuple[bool, bool, bool, bool, int, bool, bool, bool, bool]:
        s = self.best_result_state
        return (
            s.captures_enemy,
            not s.captured_by_enemy,
            s.can_force_repetition,
            not s.can_enemy_force_repetition,
            s.tile_differential + 25 * s.city_differential + s.friendly_city_control_turns - s.enemy_city_control_turns,
            not s.enemy_has_wasted_move,
            s.kills_all_enemy_armies,
            not s.kills_all_friendly_armies,
            s.friendly_has_wasted_move
        )

    def __str__(self):
        return str(self.best_result_state)

    def __repr__(self):
        return str(self)



class ArmySimCache(object):
    def __init__(self, friendlyMove: Move, enemyMove: Move, simState: ArmySimState,
                 subTreeCache: typing.Dict[Tile, ArmySimCache] | None = None):
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
            boardAnalysis: BoardAnalyzer):
        self.map = map
        self.friendly_armies: typing.List[Army] = friendlyArmies
        self.enemy_armies: typing.List[Army] = enemyArmies
        self.board_analysis: BoardAnalyzer = boardAnalysis
        self.inter_army_analysis: ArmyAnalyzer | None = None
        self.friendly_player = friendlyArmies[0].player
        self.enemy_player = enemyArmies[0].player
        if len(friendlyArmies) == 1 and len(enemyArmies) == 1:
            # Cool, we can inter-analyze armies
            self.inter_army_analysis = ArmyAnalyzer(map, friendlyArmies[0], enemyArmies[0])

    def scan(
            self,
            turns: int
    ) -> ArmySimResult:
        """
        Sims a number of turns and outputs what it believes to be the best move combination for players.
        @param turns:
        @return:
        """

        return ArmySimResult()

    def scan_brute_force(
            self,
            turns: int,
            logEvals: bool = False,
            # perf_timer: PerformanceTimer | None = None,
    ) -> ArmySimResult:
        """
        Sims a number of turns and outputs what it believes to be the best move combination for players. Brute force approach, largely just for validating that any branch and bound approaches produce the correct result.
        @param turns:
        @return:
        """

        baseBoardState = self.get_base_board_state()
        start = time.perf_counter()
        result: ArmySimResult = self.simulate_recursive_brute_force(baseBoardState, self.map.turn, self.map.turn + turns, logEvals=logEvals)
        # build the expected move list up the tree
        equilibriumBoard = result.best_result_state
        while equilibriumBoard is not None:
            result.expected_best_moves.insert(0, (equilibriumBoard.friendly_move, equilibriumBoard.enemy_move))
            equilibriumBoard = equilibriumBoard.parent_board

        duration = time.perf_counter() - start
        logging.info(f'brute force army scrim depth {turns} complete in {duration:.3f}')

        # moves are appended in reverse order, so reverse them
        # result.expected_best_moves = [m for m in reversed(result.expected_best_moves)]

        return result

    def simulate_recursive_brute_force(
            self,
            boardState: ArmySimState,
            currentTurn: int,
            stopTurn: int,
            logEvals: bool = False,
    ) -> ArmySimResult:
        """

        @param currentTurn: the current turn (in the sim, or starting turn that the current map is at)
        @param stopTurn: how far to execute the sim until
        @param boardState: the state of the board at this position
        @return: a tuple of (the min-maxed best sim state down the tree,
        with the list of moves (and their actual board states) up the tree,
        the depth evaluated)
        """

        self.check_army_positions(boardState)

        if len(boardState.friendly_living_armies) == 0:
            boardState.kills_all_friendly_armies = True
        if len(boardState.enemy_living_armies) == 0:
            boardState.kills_all_enemy_armies = True

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

        for frIdx, frMove in enumerate(frMoves):
            for enIdx, enMove in enumerate(enMoves):
                nextBoardState = self.get_next_board_state(nextTurn, boardState, frMove, enMove, logEvals)
                nextResult = self.simulate_recursive_brute_force(
                    nextBoardState,
                    nextTurn,
                    stopTurn,
                    logEvals,
                )

                payoffs[frIdx][enIdx] = nextResult

                # frMoves[frMove].append(nextResult)
                # enMoves[enMove].append(nextResult)

        if logEvals:
            self.render_payoffs(boardState, frMoves, enMoves, payoffs)

        # enemy is going to choose the move that results in the lowest maximum board state

        # build response matrix

        bestEnemyMove: Move | None = None
        bestEnemyMoveExpectedFriendlyMove: Move | None = None
        bestEnemyMoveWorstCaseFriendlyResponse: ArmySimResult | None = None
        for enIdx, enMove in enumerate(enMoves):
            curEnemyMoveWorstCaseFriendlyResponse: ArmySimResult | None = None
            curEnemyExpectedFriendly = None
            for frIdx, frMove in enumerate(frMoves):
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
        for frIdx, frMove in enumerate(frMoves):
            curFriendlyMoveWorstCaseOpponentResponse: ArmySimResult = None
            curFriendlyExpectedEnemy = None
            for enIdx, enMove in enumerate(enMoves):
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

        if logEvals:
            if bestFriendlyMoveExpectedEnemyMove != bestEnemyMove or bestFriendlyMove != bestEnemyMoveExpectedFriendlyMove or bestFriendlyMoveWorstCaseOpponentResponse != bestEnemyMoveWorstCaseFriendlyResponse:
                logging.info(f'~~~  diverged, why?\r\n    FR fr: ({str(bestFriendlyMove)}) en: ({str(bestFriendlyMoveExpectedEnemyMove)})  eval {str(bestFriendlyMoveWorstCaseOpponentResponse)}\r\n    EN fr: ({str(bestEnemyMoveExpectedFriendlyMove)}) en: ({str(bestEnemyMove)})  eval {str(bestEnemyMoveWorstCaseFriendlyResponse)}\r\n')
            else:
                logging.info(f'~~~  both players agreed  fr: ({str(bestFriendlyMove)}) en: ({str(bestEnemyMove)}) eval {str(bestEnemyMoveWorstCaseFriendlyResponse)}\r\n')

        worstCaseForUs = bestFriendlyMoveWorstCaseOpponentResponse
        # DONT do this, the opponent is forced to make worse plays than we think they might due to the threats we have.
        # if bestEnemyMoveWorstCaseFriendlyResponse.calculate_value() < bestFriendlyMoveWorstCaseOpponentResponse.calculate_value():
        #     worstCaseForUs = bestEnemyMoveWorstCaseFriendlyResponse
        #
        # worstCaseForUs.expected_best_moves.insert(0, (bestFriendlyMove, bestEnemyMove))
        # if logEvals:
        #     logging.info(f'\r\nworstCase tileCap {worstCaseForUs.best_result_state.tile_differential}' + '\r\n'.join([f"{str(aMove)}, {str(bMove)}" for aMove, bMove in worstCaseForUs.expected_best_moves]))
        return worstCaseForUs


    def get_next_board_state(
            self,
            turn: int,
            boardState: ArmySimState,
            frMove: Move | None,
            enMove: Move | None,
            logEvals: bool = False,
    ) -> ArmySimState:
        nextBoardState = boardState.get_child_board()
        nextBoardState.friendly_move = frMove
        nextBoardState.enemy_move = enMove

        if self.detect_repetition(boardState, nextBoardState):
            return nextBoardState

        if frMove is None:
            nextBoardState.friendly_has_wasted_move = True
            self.execute(nextBoardState, enMove, self.enemy_player, self.friendly_player)
        elif enMove is None:
            nextBoardState.enemy_has_wasted_move = True
            self.execute(nextBoardState, frMove, self.friendly_player, self.enemy_player)
        else:
            # sources must already be in the sim tiles, so we can skip the null check

            if self.player_has_priority(self.friendly_player, nextBoardState.remaining_cycle_turns):
                self.execute(nextBoardState, frMove, self.friendly_player, self.enemy_player)
                self.execute(nextBoardState, enMove, self.enemy_player, self.friendly_player)
            else:
                self.execute(nextBoardState, enMove, self.enemy_player, self.friendly_player)
                self.execute(nextBoardState, frMove, self.friendly_player, self.enemy_player)

        return nextBoardState

    def execute(self, nextBoardState: ArmySimState, move: Move | None, movingPlayer: int, otherPlayer: int):
        tileDif = 0
        cityDif = 0
        resultDest: SimTile | None = None
        capsGeneral = False

        source = None if move is None else nextBoardState.sim_tiles[move.source]
        dest = None if move is None else nextBoardState.sim_tiles.get(move.dest) or SimTile(move.dest)

        if source.player != movingPlayer:
            # tile was captured by the other player before the move was executed
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
                else: # then the player is capturing neutral / third party tiles
                    tileDif = 1
                    if dest.source_tile.isCity:
                        cityDif = 1
                resultDest = SimTile(dest.source_tile, resultArmy, source.player)
            else:
                resultDest = SimTile(dest.source_tile, resultArmy, dest.player)
        else:
            resultArmy = dest.army + source.army - 1
            resultDest = SimTile(dest.source_tile, resultArmy, dest.player)

        nextBoardState.sim_tiles[source.source_tile] = SimTile(source.source_tile, 1, source.player)
        nextBoardState.sim_tiles[dest.source_tile] = resultDest

        if movingPlayer == self.enemy_player:
            tileDif = 0 - tileDif
            cityDif = 0 - cityDif
            if capsGeneral:
                nextBoardState.captured_by_enemy = True
            try:
                del nextBoardState.enemy_living_armies[source.source_tile]
            except:
                pass
        else:
            if capsGeneral:
                nextBoardState.captures_enemy = True
            try:
                del nextBoardState.friendly_living_armies[source.source_tile]
            except:
                pass

        # shouldn't need to do this...?
        if resultDest.source_tile in nextBoardState.enemy_living_armies:
            del nextBoardState.enemy_living_armies[resultDest.source_tile]
        elif resultDest.source_tile in nextBoardState.friendly_living_armies:
            del nextBoardState.friendly_living_armies[resultDest.source_tile]

        if resultDest.army > 1:
            if resultDest.player == self.friendly_player:
                nextBoardState.friendly_living_armies[resultDest.source_tile] = resultDest
            elif resultDest.player == self.enemy_player:
                nextBoardState.enemy_living_armies[resultDest.source_tile] = resultDest

        nextBoardState.tile_differential += tileDif
        nextBoardState.city_differential += cityDif

    def get_base_board_state(self) -> ArmySimState:
        baseBoardState = ArmySimState(remainingCycleTurns=50 - self.map.turn % 50)

        for friendlyArmy in self.friendly_armies:
            st = SimTile(friendlyArmy.tile)
            baseBoardState.friendly_living_armies[friendlyArmy.tile] = st
            baseBoardState.sim_tiles[friendlyArmy.tile] = st

        for enemyArmy in self.enemy_armies:
            st = SimTile(enemyArmy.tile, enemyArmy.value + 1, self.enemy_player)
            baseBoardState.enemy_living_armies[enemyArmy.tile] = st
            baseBoardState.sim_tiles[enemyArmy.tile] = st

        baseBoardState.tile_differential = self.map.players[self.friendly_player].tileCount - self.map.players[self.enemy_player].tileCount
        baseBoardState.city_differential = self.map.players[self.friendly_player].cityCount - self.map.players[self.enemy_player].cityCount
        return baseBoardState

    def check_army_positions(self, boardState: ArmySimState):
        closestFrSave = 100
        closestEnSave = 100
        closestFrThreat = 100
        closestEnThreat = 100

        for tile, simTile in boardState.friendly_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
            if distToGen < closestFrSave:
                closestFrSave = distToGen
            if simTile.army > self.board_analysis.intergeneral_analysis.tileB.army + distToEnemy * 2:
                if distToEnemy < closestFrThreat:
                    closestFrThreat = distToEnemy

        for tile, simTile in boardState.enemy_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
            if distToEnemy < closestEnSave:
                closestEnSave = distToEnemy
            if simTile.army > self.board_analysis.intergeneral_analysis.tileA.army + distToGen * 2:
                if distToGen < closestEnThreat:
                    closestEnThreat = distToGen

        if closestFrSave - 1 > closestEnThreat and closestFrThreat > closestEnThreat:
            boardState.captured_by_enemy = True
        if closestEnSave - 1 > closestFrThreat and closestEnThreat > closestFrThreat:
            boardState.captures_enemy = True

    def detect_repetition(self, boardState, nextBoardState):
        REPETITION_THRESHOLD = 1
        bothNoOp = False
        if nextBoardState.friendly_move is None and nextBoardState.enemy_move is None:
            bothNoOp = True

        if bothNoOp or (boardState.prev_enemy_move
                and boardState.prev_friendly_move
                and nextBoardState.enemy_move
                and nextBoardState.friendly_move
                and boardState.prev_enemy_move.dest.x == nextBoardState.enemy_move.dest.x
                and boardState.prev_enemy_move.dest.y == nextBoardState.enemy_move.dest.y
                and boardState.prev_friendly_move.dest.x == nextBoardState.friendly_move.dest.x
                and boardState.prev_friendly_move.dest.y == nextBoardState.friendly_move.dest.y):
            nextBoardState.repetition_count += 1
            if bothNoOp or nextBoardState.repetition_count >= REPETITION_THRESHOLD:
                diff = nextBoardState.tile_differential + 25 * nextBoardState.city_differential
                if diff >= 0:
                    nextBoardState.can_force_repetition = True
                if diff <= 0:
                    nextBoardState.can_enemy_force_repetition = True
                # logging.info(f'DETECTED REPETITION')
                return True
        else:
            nextBoardState.repetition_count = 0

        return False

    def generate_friendly_moves(self, boardState: ArmySimState) -> typing.List[Move | None]:
        return self._generate_moves(boardState.friendly_living_armies, allowOptionalNoOp=not boardState.friendly_has_wasted_move)

    def generate_enemy_moves(self, boardState: ArmySimState) -> typing.List[Move | None]:
        return self._generate_moves(boardState.enemy_living_armies, allowOptionalNoOp=not boardState.enemy_has_wasted_move)

    def _generate_moves(self, armies: typing.Dict[Tile, SimTile], allowOptionalNoOp: bool = True) -> typing.List[Move | None]:
        moves = []
        for armyTile in armies:
            for dest in armyTile.movable:
                if dest.isObstacle:
                    continue
                moves.append(Move(armyTile, dest))

        # if allowOptionalNoOp or len(moves) == 0:
        moves.append(None)

        return moves

    def set_final_board_state_depth_estimation(self, boardState: ArmySimState):
        friendlyArmySizes = 0
        enemyArmySizes = 0
        for frArmyTile, frSimArmy in boardState.friendly_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[frSimArmy.source_tile.x][frSimArmy.source_tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[frSimArmy.source_tile.x][frSimArmy.source_tile.y]
            if distToGen + 3 > distToEnemy:
                friendlyArmySizes += frSimArmy.army
            elif distToGen - 3 > distToEnemy:
                friendlyArmySizes += frSimArmy.army // 2
        for enArmyTile, enSimArmy in boardState.enemy_living_armies.items():
            distToEnemy = self.board_analysis.intergeneral_analysis.bMap[enSimArmy.source_tile.x][enSimArmy.source_tile.y]
            distToGen = self.board_analysis.intergeneral_analysis.aMap[enSimArmy.source_tile.x][enSimArmy.source_tile.y]
            if distToEnemy + 3 > distToGen:
                enemyArmySizes += enSimArmy.army
            elif distToEnemy - 3 > distToGen:
                enemyArmySizes += enSimArmy.army // 2

        # on average lets say a surviving army can tilt tile capture one tile per turn it survives
        frEstFinalDamage = min(friendlyArmySizes // 2, int(2 * boardState.remaining_cycle_turns))
        enEstFinalDamage = min(enemyArmySizes // 2, int(2 * boardState.remaining_cycle_turns))
        boardState.tile_differential += frEstFinalDamage
        boardState.tile_differential -= enEstFinalDamage

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

    @staticmethod
    def player_has_priority(player: int, turn: int):
        return player & 1 == turn & 1

