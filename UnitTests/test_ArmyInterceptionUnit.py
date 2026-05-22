import time
import typing
from dataclasses import dataclass

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from Behavior.ArmyInterceptor import TARGET_CAP_VALUE
from BotModules import BotDefense
from BotModules.imports import BotCombatOps
from DangerAnalyzer import ThreatObj, ThreatType
from Models import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from bot_ek0x45 import EklipZBot
from base.client.map import MapBase


@dataclass(slots=True)
class InterceptCollisionExpectation:
    path: str
    turns_left: int
    friendly_army: int
    best_case_turn: int
    worst_case_turn: int
    intercept_x: int
    intercept_y: int
    enemy_physical_army: int
    enemy_remaining_after_intercept: int
    enemy_collided_army: int


@dataclass(slots=True)
class ActualInterceptExecutionStats:
    case_name: str
    actual_threat_tile_differential: int
    final_tile_differential_after_intercept: int
    recapture_adjusted_tile_differential_after_intercept: int
    did_meet: bool
    did_become_movable_adjacent: bool
    closest_turn: int
    closest_distance: int
    closest_friendly_army: int
    closest_enemy_army: int
    friendly_army_remaining_after_intercept: int
    enemy_army_remaining_after_intercept: int
    intercept_x: int
    intercept_y: int


@dataclass(slots=True)
class InterceptHarnessParams:
    map_file: str
    turn: int
    fill_out_tiles: bool
    threat_path: str
    turns_left_in_cycle: int


class ArmyInterceptionUnitTests(TestBase):
    INNER_PATH_INTERCEPT_DEBUG_MAP_FILE = 'GameContinuationEntries/should_correctly_value_intercept_from_general___jzXGxMXQl---1--323.txtmap'
    INNER_PATH_INTERCEPT_DEBUG_TURN = 323

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)
        # TestBase.GLOBAL_BYPASS_REAL_TIME_TEST = True
        TestBase.GLOBAL_BYPASS_RENDERING = True

    def test_should_limit_econ_interception_search_depth_using_max_threat_len_with_critical_floor(self):
        map, general, enemyGeneral = self.load_map_and_generals('GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap', 307, fill_out_tiles=True)
        interceptor = self.get_interceptor(map, general, enemyGeneral)

        threats = [
            self._create_intercept_depth_test_threat(map, enemyGeneral, map.At(5, 5), 10, ThreatType.Kill, isGeneral=True),
            self._create_intercept_depth_test_threat(map, enemyGeneral, map.At(6, 5), 11, ThreatType.Kill, isCity=True),
            self._create_intercept_depth_test_threat(map, enemyGeneral, map.At(7, 5), 12, ThreatType.Econ),
        ]

        self.assertEqual(11, interceptor._get_max_interception_search_depth(threats))

    def test_should_limit_econ_only_interception_search_depth_to_two_thirds_plus_one(self):
        map, general, enemyGeneral = self.load_map_and_generals('GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap', 307, fill_out_tiles=True)
        interceptor = self.get_interceptor(map, general, enemyGeneral)

        threats = [
            self._create_intercept_depth_test_threat(map, enemyGeneral, map.At(5, 5), 10, ThreatType.Econ),
        ]

        self.assertEqual(7, interceptor._get_max_interception_search_depth(threats))

    def _create_intercept_depth_test_threat(
            self,
            map,
            enemyGeneral,
            targetTile,
            turns: int,
            threatType: ThreatType,
            isGeneral: bool = False,
            isCity: bool = False
    ) -> ThreatObj:
        targetTile.isGeneral = isGeneral
        targetTile.isCity = isCity
        path = Path()
        path.add_next(enemyGeneral)
        path.add_next(targetTile)
        return ThreatObj(turns, 1, path, threatType)

    def _get_inner_path_intercept_debug_case(self, useDebugLogging: bool = False):
        map, general, enemyGeneral = self.load_map_and_generals(self.INNER_PATH_INTERCEPT_DEBUG_MAP_FILE, self.INNER_PATH_INTERCEPT_DEBUG_TURN, fill_out_tiles=False)
        plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, paths=[
            '6,4->6,5->5,5->5,11->6,11->6,15->5,15->4,15->4,16',
            '6,4->6,5->6,6->5,6->5,7->4,7->4,8->4,9->4,10->4,11->3,11',
            '6,4->6,5->5,5->5,6->5,7->5,8->5,9->5,10->5,11->4,11->3,11->3,12->2,12->1,12->0,12',
        ], useDebugLogging=useDebugLogging)
        self.stop_capturing_logging()
        interceptor = self.get_interceptor(map, general, enemyGeneral, useDebugLogging=useDebugLogging)
        self.stop_capturing_logging()
        return map, plan, interceptor

    def _get_inner_path_intercept_harness_params(self, threatPath: Path) -> InterceptHarnessParams:
        return InterceptHarnessParams(
            self.INNER_PATH_INTERCEPT_DEBUG_MAP_FILE,
            self.INNER_PATH_INTERCEPT_DEBUG_TURN,
            False,
            self._format_path_coords_for_sim(threatPath),
            27)

    def _load_intercept_harness_map_copy(self, harnessParams: InterceptHarnessParams):
        return self.load_map_and_generals(harnessParams.map_file, harnessParams.turn, fill_out_tiles=harnessParams.fill_out_tiles)

    def _create_intercept_harness_sim_host(self, map: MapBase) -> GameSimulatorHost:
        self.stop_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=-1, afkPlayers=[player.index for player in map.players], botInitOnly=True)
        self.assertTrue(all(botHost is None for botHost in simHost.bot_hosts))
        return simHost

    def _get_inner_path_intercept_collision_mismatches(self, expectation: InterceptCollisionExpectation) -> typing.List[str]:
        map, plan, interceptor = self._get_inner_path_intercept_debug_case()
        interceptPath = Path.from_string(map, expectation.path)
        harnessParams = self._get_inner_path_intercept_harness_params(plan.best_enemy_threat.threat.path)
        self.begin_capturing_logging()
        try:
            collisionResult = interceptor._get_result_of_executing_paths_to_intercept_point(
                plan,
                plan.best_enemy_threat.threat,
                interceptPath,
                harnessParams.turns_left_in_cycle
            )
        finally:
            self.stop_capturing_logging()

        mismatches = []
        if expectation.turns_left != collisionResult.turns_left:
            mismatches.append(f'turns_left mismatch for {expectation.path}: expected {expectation.turns_left}, algo {collisionResult.turns_left}')
        if expectation.friendly_army != collisionResult.friendly_army_at_intercept:
            mismatches.append(f'friendly_army expectation mismatch for {expectation.path}: expected {expectation.friendly_army}, algo {collisionResult.friendly_army_at_intercept}')
        if expectation.best_case_turn != collisionResult.best_case_intercept_turn:
            mismatches.append(f'best_case_turn mismatch for {expectation.path}: expected {expectation.best_case_turn}, algo {collisionResult.best_case_intercept_turn}')
        if expectation.worst_case_turn != collisionResult.worst_case_intercept_turn:
            mismatches.append(f'worst_case_turn mismatch for {expectation.path}: expected {expectation.worst_case_turn}, algo {collisionResult.worst_case_intercept_turn}')
        if map.At(expectation.intercept_x, expectation.intercept_y) != collisionResult.enemy_intercept_point_node.tile:
            mismatches.append(f'intercept tile expectation mismatch for {expectation.path}: expected {expectation.intercept_x},{expectation.intercept_y}, algo {collisionResult.enemy_intercept_point_node.tile}')
        if expectation.enemy_physical_army != collisionResult.enemy_physical_army_at_intercept:
            mismatches.append(f'enemy_physical_army expectation mismatch for {expectation.path}: expected {expectation.enemy_physical_army}, algo {collisionResult.enemy_physical_army_at_intercept}')
        mismatches.extend(self._get_inner_path_actual_execution_mismatches(expectation, collisionResult, harnessParams))
        return mismatches

    def _assert_inner_path_intercept_collision_expectation(self, expectation: InterceptCollisionExpectation):
        TestBase.GLOBAL_BYPASS_REAL_TIME_TEST = False
        mismatches = self._get_inner_path_intercept_collision_mismatches(expectation)
        if len(mismatches) > 0:
            self.fail('\n'.join(mismatches))

    def _get_inner_path_intercept_value_mismatches(self, expectation: InterceptCollisionExpectation) -> typing.List[str]:
        map, plan, interceptor = self._get_inner_path_intercept_debug_case()
        interceptPath = Path.from_string(map, expectation.path)
        harnessParams = self._get_inner_path_intercept_harness_params(plan.best_enemy_threat.threat.path)

        self.begin_capturing_logging()
        try:
            _, blockedDamage, enemyArmyRemainingAtIntercept, enemyArmyIntercepted, bestCaseTurn, worstCaseTurn = interceptor._get_value_of_threat_blocked(
                plan,
                interceptPath,
                plan.best_enemy_threat,
                harnessParams.turns_left_in_cycle
            )
        finally:
            self.stop_capturing_logging()

        actual = self._get_actual_intercept_execution_stats(harnessParams, expectation.path)
        mismatches = []
        if expectation.enemy_remaining_after_intercept != enemyArmyRemainingAtIntercept:
            mismatches.append(f'enemy remaining expectation mismatch for {expectation.path}: expected {expectation.enemy_remaining_after_intercept}, algo {enemyArmyRemainingAtIntercept}')
        if expectation.enemy_collided_army != enemyArmyIntercepted:
            mismatches.append(f'enemy collided expectation mismatch for {expectation.path}: expected {expectation.enemy_collided_army}, algo {enemyArmyIntercepted}')
        if expectation.best_case_turn != bestCaseTurn:
            mismatches.append(f'best case turn expectation mismatch for {expectation.path}: expected {expectation.best_case_turn}, algo {bestCaseTurn}')
        if expectation.worst_case_turn != worstCaseTurn:
            mismatches.append(f'worst case turn expectation mismatch for {expectation.path}: expected {expectation.worst_case_turn}, algo {worstCaseTurn}')

        if actual.friendly_army_remaining_after_intercept > 0:
            actualEnemyRemaining = 0 - actual.friendly_army_remaining_after_intercept
        else:
            actualEnemyRemaining = actual.enemy_army_remaining_after_intercept

        if actualEnemyRemaining != enemyArmyRemainingAtIntercept:
            mismatches.append(f'enemy remaining actual mismatch for {expectation.path}: algo {enemyArmyRemainingAtIntercept}, actual {actualEnemyRemaining}')
        if actual.closest_enemy_army != enemyArmyIntercepted:
            mismatches.append(f'enemy collided actual mismatch for {expectation.path}: algo {enemyArmyIntercepted}, actual {actual.closest_enemy_army}')
        return mismatches

    def _assert_inner_path_intercept_value_expectation(self, expectation: InterceptCollisionExpectation):
        mismatches = self._get_inner_path_intercept_value_mismatches(expectation)
        if len(mismatches) > 0:
            self.fail('\n'.join(mismatches))

    def _get_inner_path_actual_execution_mismatches(self, expectation: InterceptCollisionExpectation, collisionResult, harnessParams: InterceptHarnessParams) -> typing.List[str]:
        actual = self._get_actual_intercept_execution_stats(harnessParams, expectation.path)
        mismatches = []

        if actual.closest_friendly_army != collisionResult.friendly_army_at_intercept:
            mismatches.append(f'friendly army mismatch for {expectation.path} ({actual.case_name}): algo {collisionResult.friendly_army_at_intercept}, actual {actual.closest_friendly_army}')
        if actual.closest_enemy_army != collisionResult.enemy_physical_army_at_intercept:
            mismatches.append(f'enemy army mismatch for {expectation.path} ({actual.case_name}): algo {collisionResult.enemy_physical_army_at_intercept}, actual {actual.closest_enemy_army}')
        if actual.friendly_army_remaining_after_intercept > 0:
            actualEnemyRemaining = 0 - actual.friendly_army_remaining_after_intercept
        else:
            actualEnemyRemaining = actual.enemy_army_remaining_after_intercept
        algoEnemyRemaining = collisionResult.enemy_physical_army_at_intercept - collisionResult.friendly_army_at_intercept
        if actualEnemyRemaining != algoEnemyRemaining:
            mismatches.append(f'enemy remaining mismatch for {expectation.path} ({actual.case_name}): algo {algoEnemyRemaining}, actual {actualEnemyRemaining}')
        if actual.intercept_x != collisionResult.enemy_intercept_point_node.tile.x or actual.intercept_y != collisionResult.enemy_intercept_point_node.tile.y:
            mismatches.append(f'intercept tile mismatch for {expectation.path} ({actual.case_name}): algo {collisionResult.enemy_intercept_point_node.tile}, actual {actual.intercept_x},{actual.intercept_y}')
        if not actual.did_meet and not actual.did_become_movable_adjacent:
            mismatches.append(f'intercept never met or became adjacent for {expectation.path} ({actual.case_name}): closest turn {actual.closest_turn}, closest distance {actual.closest_distance}')

        return mismatches

    def _get_actual_intercept_execution_stats(self, harnessParams: InterceptHarnessParams, interceptPathStr: str) -> ActualInterceptExecutionStats:
        self.stop_capturing_logging()
        actualThreatTileDifferential = self._get_actual_threat_tile_differential(harnessParams)
        map, general, enemyGeneral = self._load_intercept_harness_map_copy(harnessParams)
        simHost = self._create_intercept_harness_sim_host(map)
        simHost.queue_player_moves_str(enemyGeneral.player, harnessParams.threat_path)
        simHost.queue_player_moves_str(general.player, interceptPathStr)

        threatPath = Path.from_string(map, harnessParams.threat_path)
        interceptPath = Path.from_string(map, interceptPathStr)
        maxTurns = max(threatPath.length, interceptPath.length) + 8
        closestTurn = 0
        closestDistance = 1000
        closestFriendlyArmy = 0
        closestEnemyArmy = 0
        closestFriendlyTile = interceptPath.start.tile
        closestEnemyTile = threatPath.start.tile
        didMeet = False
        didBecomeMovableAdjacent = False
        caseName = 'estimated chase hack collision'
        friendlyArmyRemaining = 0
        enemyArmyRemaining = 0

        for turnOffset in range(maxTurns):
            friendlyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, interceptPath, turnOffset)
            enemyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, threatPath, turnOffset)
            distance = abs(friendlyTile.x - enemyTile.x) + abs(friendlyTile.y - enemyTile.y)
            if distance < closestDistance:
                closestTurn = turnOffset
                closestDistance = distance
                closestFriendlyTile = friendlyTile
                closestEnemyTile = enemyTile
                closestFriendlyArmy = self._get_movable_army_for_player(friendlyTile, general.player)
                closestEnemyArmy = self._get_movable_army_for_player(enemyTile, enemyGeneral.player)

            if friendlyTile == enemyTile:
                didMeet = True
                caseName = 'direct collision intercept'
                if turnOffset > 0 and friendlyTile.player == general.player:
                    previousFriendlyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, interceptPath, turnOffset - 1)
                    previousEnemyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, threatPath, turnOffset - 1)
                    closestFriendlyArmy = self._get_movable_army_for_player(previousFriendlyTile, general.player) + friendlyTile.army
                    closestEnemyArmy = self._get_movable_army_for_player(previousEnemyTile, enemyGeneral.player)
                    friendlyArmyRemaining = max(0, closestFriendlyArmy - closestEnemyArmy)
                    enemyArmyRemaining = max(0, closestEnemyArmy - closestFriendlyArmy)
                else:
                    friendlyArmyRemaining = friendlyTile.army if friendlyTile.player == general.player else 0
                    enemyArmyRemaining = friendlyTile.army if friendlyTile.player == enemyGeneral.player else 0
                break

            if enemyTile in friendlyTile.movable:
                didBecomeMovableAdjacent = True
                caseName = 'movable intercept'
                closestFriendlyArmy = self._get_movable_army_for_player(friendlyTile, general.player)
                closestEnemyArmy = self._get_movable_army_for_player(enemyTile, enemyGeneral.player)
                friendlyArmyRemaining = max(0, closestFriendlyArmy - closestEnemyArmy)
                enemyArmyRemaining = max(0, closestEnemyArmy - closestFriendlyArmy)
                closestFriendlyTile = friendlyTile
                closestEnemyTile = enemyTile
                break

            nextFriendlyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, interceptPath, turnOffset + 1)
            nextEnemyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, threatPath, turnOffset + 1)
            if nextFriendlyTile == nextEnemyTile and nextFriendlyTile.player == general.player:
                didMeet = True
                caseName = 'direct collision intercept'
                closestTurn = turnOffset + 1
                closestDistance = 0
                closestFriendlyTile = nextFriendlyTile
                closestEnemyTile = nextEnemyTile
                closestFriendlyArmy = self._get_movable_army_for_player(friendlyTile, general.player) + nextFriendlyTile.army
                closestEnemyArmy = self._get_movable_army_for_player(enemyTile, enemyGeneral.player)
                friendlyArmyRemaining = max(0, closestFriendlyArmy - closestEnemyArmy)
                enemyArmyRemaining = max(0, closestEnemyArmy - closestFriendlyArmy)
                simHost.execute_turn()
                break

            simHost.execute_turn()

        finalTileDifferential = self.get_tile_differential(simHost, general.player, enemyGeneral.player)
        if not didMeet and not didBecomeMovableAdjacent:
            friendlyArmyRemaining, enemyArmyRemaining, closestFriendlyArmy, closestEnemyArmy, closestEnemyTile, finalTileDifferential = self._execute_closest_approach_chase(harnessParams, interceptPathStr, closestTurn)

        recaptures = max(0, (friendlyArmyRemaining - 1) // 2)
        return ActualInterceptExecutionStats(
            caseName,
            actualThreatTileDifferential,
            finalTileDifferential,
            finalTileDifferential + 2 * recaptures,
            didMeet,
            didBecomeMovableAdjacent,
            closestTurn,
            closestDistance,
            closestFriendlyArmy,
            closestEnemyArmy,
            friendlyArmyRemaining,
            enemyArmyRemaining,
            closestEnemyTile.x,
            closestEnemyTile.y)

    def _get_actual_threat_tile_differential(self, harnessParams: InterceptHarnessParams) -> int:
        self.stop_capturing_logging()
        map, general, enemyGeneral = self._load_intercept_harness_map_copy(harnessParams)
        simHost = self._create_intercept_harness_sim_host(map)
        beforeTileDifferential = self.get_tile_differential(simHost, general.player, enemyGeneral.player)
        simHost.queue_player_moves_str(enemyGeneral.player, harnessParams.threat_path)
        threatPath = Path.from_string(map, harnessParams.threat_path)
        for _ in range(threatPath.length):
            simHost.execute_turn()
        afterTileDifferential = self.get_tile_differential(simHost, general.player, enemyGeneral.player)
        return afterTileDifferential - beforeTileDifferential

    def _execute_closest_approach_chase(self, harnessParams: InterceptHarnessParams, interceptPathStr: str, closestTurn: int) -> typing.Tuple[int, int, int, int, Tile, int]:
        self.stop_capturing_logging()
        map, general, enemyGeneral = self._load_intercept_harness_map_copy(harnessParams)
        simHost = self._create_intercept_harness_sim_host(map)
        simHost.queue_player_moves_str(enemyGeneral.player, harnessParams.threat_path)
        simHost.queue_player_moves_str(general.player, interceptPathStr)
        for _ in range(closestTurn):
            simHost.execute_turn()

        threatPath = Path.from_string(simHost.sim.sim_map, harnessParams.threat_path)
        interceptPath = Path.from_string(simHost.sim.sim_map, interceptPathStr)
        friendlyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, interceptPath, closestTurn)
        enemyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, threatPath, closestTurn)
        closestFriendlyArmy = self._get_movable_army_for_player(friendlyTile, general.player)
        closestEnemyArmy = self._get_movable_army_for_player(enemyTile, enemyGeneral.player)
        chaseTurns = 0
        while friendlyTile != enemyTile and enemyTile not in friendlyTile.movable and chaseTurns < 20:
            nextFriendlyTile = min(friendlyTile.movable, key=lambda t: abs(t.x - enemyTile.x) + abs(t.y - enemyTile.y))
            simHost.queue_player_move(general.player, Move(friendlyTile, nextFriendlyTile))
            simHost.execute_turn()
            friendlyTile = simHost.sim.sim_map.GetTile(nextFriendlyTile.x, nextFriendlyTile.y)
            enemyTile = self._get_path_tile_for_turn(simHost.sim.sim_map, threatPath, closestTurn + chaseTurns + 1)
            chaseTurns += 1

        if enemyTile in friendlyTile.movable:
            friendlyArmyRemaining = max(0, self._get_movable_army_for_player(friendlyTile, general.player) - self._get_movable_army_for_player(enemyTile, enemyGeneral.player))
            enemyArmyRemaining = max(0, self._get_movable_army_for_player(enemyTile, enemyGeneral.player) - self._get_movable_army_for_player(friendlyTile, general.player))
        elif friendlyTile == enemyTile:
            friendlyArmyRemaining = friendlyTile.army if friendlyTile.player == general.player else 0
            enemyArmyRemaining = friendlyTile.army if friendlyTile.player == enemyGeneral.player else 0
        else:
            friendlyArmyRemaining = 0
            enemyArmyRemaining = 0

        finalTileDifferential = self.get_tile_differential(simHost, general.player, enemyGeneral.player)
        return friendlyArmyRemaining, enemyArmyRemaining, closestFriendlyArmy, closestEnemyArmy, enemyTile, finalTileDifferential

    def _get_path_tile_for_turn(self, map: MapBase, path: Path, turnOffset: int) -> Tile:
        idx = min(turnOffset, len(path.tileList) - 1)
        tile = path.tileList[idx]
        return map.GetTile(tile.x, tile.y)

    def _get_movable_army_for_player(self, tile: Tile, player: int) -> int:
        if tile.player != player:
            return 0
        return max(0, tile.army - 1)

    def _format_path_coords_for_sim(self, path: Path) -> str:
        return '->'.join(f'{tile.x},{tile.y}' for tile in path.tileList)

    def _get_inner_path_intercept_expectations(self) -> typing.List[InterceptCollisionExpectation]:
        return [
            InterceptCollisionExpectation(
                path='4,11->4,10->4,9->5,9->5,8',
                turns_left=22,
                friendly_army=24,
                best_case_turn=5,
                worst_case_turn=5,
                intercept_x=5,
                intercept_y=7,
                enemy_physical_army=46,
                enemy_remaining_after_intercept=22,
                enemy_collided_army=46
            ),
            InterceptCollisionExpectation(
                path='4,11->4,10->4,9->5,9',
                turns_left=22,
                friendly_army=23,
                best_case_turn=5,
                worst_case_turn=5,
                intercept_x=5,
                intercept_y=8,
                enemy_physical_army=43,
                enemy_remaining_after_intercept=20,
                enemy_collided_army=43
            ),
            InterceptCollisionExpectation(
                path='4,11->4,10->5,10',
                turns_left=20,
                friendly_army=20,
                best_case_turn=7,
                worst_case_turn=7,
                intercept_x=5,
                intercept_y=9,
                enemy_physical_army=40,
                enemy_remaining_after_intercept=20,
                enemy_collided_army=40
            ),
            InterceptCollisionExpectation(
                path='2,11->3,11->4,11->4,10->4,9->5,9->5,8',
                turns_left=20,
                friendly_army=38,
                best_case_turn=5,
                worst_case_turn=5,
                intercept_x=5,
                intercept_y=8,
                enemy_physical_army=43,
                enemy_remaining_after_intercept=5,
                enemy_collided_army=43
            ),
            InterceptCollisionExpectation(
                path='2,11->3,11->4,11->4,10->5,10',
                turns_left=20,
                friendly_army=35,
                best_case_turn=7,
                worst_case_turn=7,
                intercept_x=5,
                intercept_y=9,
                enemy_physical_army=40,
                enemy_remaining_after_intercept=5,
                enemy_collided_army=40
            ),
            InterceptCollisionExpectation(
                path='2,11->3,11->4,11->4,10->4,9->5,9',
                turns_left=21,
                friendly_army=38,
                best_case_turn=6,
                worst_case_turn=6,
                intercept_x=5,
                intercept_y=8,
                enemy_physical_army=43,
                enemy_remaining_after_intercept=5,
                enemy_collided_army=43
            ),
            InterceptCollisionExpectation(
                path='2,10->2,11->3,11->4,11->4,10->4,9->5,9',
                turns_left=20,
                friendly_army=62,
                best_case_turn=6,
                worst_case_turn=6,
                intercept_x=5,
                intercept_y=9,
                enemy_physical_army=43,
                enemy_remaining_after_intercept=-19,
                enemy_collided_army=43
            ),
            InterceptCollisionExpectation(
                path='2,10->2,11->3,11->4,11->4,10->5,10',
                turns_left=20,
                friendly_army=58,
                best_case_turn=7,
                worst_case_turn=7,
                intercept_x=5,
                intercept_y=9,
                enemy_physical_army=40,
                enemy_remaining_after_intercept=-18,
                enemy_collided_army=40
            ),
            InterceptCollisionExpectation(
                path='2,10->2,11->3,11->4,11->5,11',
                turns_left=19,
                friendly_army=56,
                best_case_turn=8,
                worst_case_turn=8,
                intercept_x=5,
                intercept_y=10,
                enemy_physical_army=37,
                enemy_remaining_after_intercept=-19,
                enemy_collided_army=37
            ),
        ]

    def test_should_report_all_inner_path_intercept_stat_mismatches_together(self):
        mismatches = []
        for expectation in self._get_inner_path_intercept_expectations():
            mismatches.extend(self._get_inner_path_intercept_collision_mismatches(expectation))
            mismatches.extend(self._get_inner_path_intercept_value_mismatches(expectation))
        if len(mismatches) > 0:
            self.fail('\n'.join(mismatches))

    def test_should_calculate_inner_path_collision_stats_for_shortest_candidate(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='4,11->4,10->4,9->5,9->5,8',
            turns_left=22,
            friendly_army=24,
            best_case_turn=5,
            worst_case_turn=5,
            intercept_x=5,
            intercept_y=7,
            enemy_physical_army=46,
            enemy_remaining_after_intercept=22,
            enemy_collided_army=46
        ))

    def test_should_calculate_inner_path_value_stats_for_shortest_candidate(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='4,11->4,10->4,9->5,9->5,8',
            turns_left=22,
            friendly_army=24,
            best_case_turn=5,
            worst_case_turn=5,
            intercept_x=5,
            intercept_y=7,
            enemy_physical_army=46,
            enemy_remaining_after_intercept=22,
            enemy_collided_army=46
        ))

    def test_should_calculate_inner_path_collision_stats_for_near_candidate_to_5_9(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='4,11->4,10->4,9->5,9',
            turns_left=22,
            friendly_army=23,
            best_case_turn=5,
            worst_case_turn=5,
            intercept_x=5,
            intercept_y=8,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=20,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_value_stats_for_near_candidate_to_5_9(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='4,11->4,10->4,9->5,9',
            turns_left=22,
            friendly_army=23,
            best_case_turn=5,
            worst_case_turn=5,
            intercept_x=5,
            intercept_y=8,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=20,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_collision_stats_for_near_candidate_to_5_10(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='4,11->4,10->5,10',
            turns_left=20,
            friendly_army=20,
            best_case_turn=7,
            worst_case_turn=7,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=40,
            enemy_remaining_after_intercept=20,
            enemy_collided_army=40
        ))

    def test_should_calculate_inner_path_value_stats_for_near_candidate_to_5_10(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='4,11->4,10->5,10',
            turns_left=20,
            friendly_army=20,
            best_case_turn=7,
            worst_case_turn=7,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=40,
            enemy_remaining_after_intercept=20,
            enemy_collided_army=40
        ))

    def test_should_calculate_inner_path_collision_stats_for_short_candidate_to_5_8(self):
        TestBase.GLOBAL_BYPASS_REAL_TIME_TEST = False
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='2,11->3,11->4,11->4,10->4,9->5,9->5,8',
            turns_left=20,
            friendly_army=38,
            best_case_turn=5,
            worst_case_turn=5,
            intercept_x=5,
            intercept_y=8,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=5,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_value_stats_for_short_candidate_to_5_8(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='2,11->3,11->4,11->4,10->4,9->5,9->5,8',
            turns_left=20,
            friendly_army=38,
            best_case_turn=5,
            worst_case_turn=5,
            intercept_x=5,
            intercept_y=8,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=5,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_collision_stats_for_short_candidate_to_5_10(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='2,11->3,11->4,11->4,10->5,10',
            turns_left=20,
            friendly_army=35,
            best_case_turn=7,
            worst_case_turn=7,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=40,
            enemy_remaining_after_intercept=5,
            enemy_collided_army=40
        ))

    def test_should_calculate_inner_path_value_stats_for_short_candidate_to_5_10(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='2,11->3,11->4,11->4,10->5,10',
            turns_left=20,
            friendly_army=35,
            best_case_turn=7,
            worst_case_turn=7,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=40,
            enemy_remaining_after_intercept=5,
            enemy_collided_army=40
        ))

    def test_should_calculate_inner_path_collision_stats_for_short_candidate_to_5_9(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='2,11->3,11->4,11->4,10->4,9->5,9',
            turns_left=21,
            friendly_army=38,
            best_case_turn=6,
            worst_case_turn=6,
            intercept_x=5,
            intercept_y=8,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=5,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_value_stats_for_short_candidate_to_5_9(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='2,11->3,11->4,11->4,10->4,9->5,9',
            turns_left=21,
            friendly_army=38,
            best_case_turn=6,
            worst_case_turn=6,
            intercept_x=5,
            intercept_y=8,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=5,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_collision_stats_for_long_candidate_to_5_9(self):
        TestBase.GLOBAL_BYPASS_REAL_TIME_TEST = False
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='2,10->2,11->3,11->4,11->4,10->4,9->5,9',
            turns_left=20,
            friendly_army=62,
            best_case_turn=6,
            worst_case_turn=6,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=-19,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_value_stats_for_long_candidate_to_5_9(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='2,10->2,11->3,11->4,11->4,10->4,9->5,9',
            turns_left=20,
            friendly_army=62,
            best_case_turn=6,
            worst_case_turn=6,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=43,
            enemy_remaining_after_intercept=-19,
            enemy_collided_army=43
        ))

    def test_should_calculate_inner_path_collision_stats_for_long_candidate_to_5_10(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='2,10->2,11->3,11->4,11->4,10->5,10',
            turns_left=20,
            friendly_army=58,
            best_case_turn=7,
            worst_case_turn=7,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=40,
            enemy_remaining_after_intercept=-18,
            enemy_collided_army=40
        ))

    def test_should_calculate_inner_path_value_stats_for_long_candidate_to_5_10(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='2,10->2,11->3,11->4,11->4,10->5,10',
            turns_left=20,
            friendly_army=58,
            best_case_turn=7,
            worst_case_turn=7,
            intercept_x=5,
            intercept_y=9,
            enemy_physical_army=40,
            enemy_remaining_after_intercept=-18,
            enemy_collided_army=40
        ))

    def test_should_calculate_inner_path_collision_stats_for_long_candidate_to_5_11(self):
        self._assert_inner_path_intercept_collision_expectation(InterceptCollisionExpectation(
            path='2,10->2,11->3,11->4,11->5,11',
            turns_left=19,
            friendly_army=56,
            best_case_turn=8,
            worst_case_turn=8,
            intercept_x=5,
            intercept_y=10,
            enemy_physical_army=37,
            enemy_remaining_after_intercept=-19,
            enemy_collided_army=37
        ))

    def test_should_calculate_inner_path_value_stats_for_long_candidate_to_5_11(self):
        self._assert_inner_path_intercept_value_expectation(InterceptCollisionExpectation(
            path='2,10->2,11->3,11->4,11->5,11',
            turns_left=19,
            friendly_army=56,
            best_case_turn=8,
            worst_case_turn=8,
            intercept_x=5,
            intercept_y=10,
            enemy_physical_army=37,
            enemy_remaining_after_intercept=-19,
            enemy_collided_army=37
        ))

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2, clearCurPath: bool = True) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_intercept_data = True
        bot.info_render_board_analysis_choke_widths = True
        bot.info_render_army_emergence_values = False
        bot.army_interceptor.log_debug = True
        if clearCurPath:
            bot.curPath = None

        return bot

    def test_should_intercept_army_that_is_one_tile_kill_and_city_threat_lol__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)
        enTile = map.At(7, 14)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertEqual(1, bestOpt.length)
        self.assertEqual(enTile, bestOpt.tail.tile)

    def test_should_continue_to_intercept_army__unit_test_should_not_value_pointless_intercepts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_value_pointless_intercepts___Human.exe-TEST__bee0a7ef-ea4e-4234-aba2-4d8c5384d938---0--141.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 141, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)
        opt = self.get_best_intercept_option_path_values(plan)

        if debugMode:
            self.render_intercept_plan(map, plan)

    def test_should_prevent_run_around_general__correctly_analyze_intercept_value_addons(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_analyze_intercept_values___Human.exe-TEST__3c8fbffc-3762-4a68-a059-27bf06366d28---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        # rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)

        plan = self.get_interception_plan(map, general, enemyGeneral) #, additionalPath='7,9->7,10->6,10->6,11->5,11->5,9')

        if debugMode:
            self.render_intercept_plan(map, plan)

        val, turns, bestOpt = self.get_best_intercept_option_path_values(plan)

        self.assertEqual(general, bestOpt.start.tile)

    def test_should_intercept_with_large_tile__should_intercept_despite_leftward_unpreventable_option__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_large_tile___qWwqozFbe---1--138.txtmap'
        self.begin_capturing_logging()
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        # enTile = map.At(12, 9)
        enTile = map.At(10, 9)

        self.begin_capturing_logging()
        analysis = ArmyAnalyzer(map, map.At(10, 14), enTile)
        # if debugMode:
        #     self.render_army_analyzer(map, analysis)

        # this is NOT a shortest path to the target tile, is found naturally because the 18 runs out before reaching it if it goes straight down but in theory we could always find a path like this anyway even if the 13 to the right wasn't there.
        addlPath = '10,9->14,9->14,15->13,15'
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile, additionalPath=addlPath)
        # plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        self.assertIsNotNone(plan)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        self.assertNotIn(map.At(9, 10), plan.common_intercept_chokes)

        self.assert_no_intercept_option_by_coords(plan, 10, 13, 10, 15, "should not have found a path just heading back to general")
        self.assert_no_intercept_option_by_coords(plan, 10, 14, 10, 15, "should not have found a path just heading back to general")
        self.assert_no_intercept_option_by_coords(plan, 10, 11, 10, 14, "should not have found a path just heading back to general")
        self.assert_no_intercept_option_by_coords(plan, 10, 10, 10, 14, "should not have found a path just heading back to general")

        val, turns, bestPath = self.get_best_intercept_option_path_values(plan)
        self.assertLess(bestPath.tail.tile.y, 12)

    def test_should_value_recaptures_properly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        interceptor = self.get_interceptor(map, general, enemyGeneral)
        path = Path()
        path.add_next(map.At(14, 6))
        path.add_next(map.At(13, 6))
        path.add_next(map.At(12, 6))
        path.add_next(map.At(11, 6))
        path.add_next(map.At(10, 6))
        path.add_next(map.At(10, 5))
        path.add_next(map.At(9, 5))

        val, turnsUsed, recapTurnsUsed, rawVal = interceptor._get_path_econ_values_for_player(path, searchingPlayer=general.player, targetPlayer=enemyGeneral.player, turnsLeftInCycle=19, includeRecaptureEffectiveStartDist=1)
        # we move 6 to intercept, they move 6 forward to 7,5. No collision yet.
        # We collide with over 30 more army with them, giving us full recapture turns.
        self.assertEqual(19, turnsUsed)

        # Since we captured 0 other tiles, the value of the intercept should equal number of remaining recapture turns * 2, which should be 22
        self.assertGreater(val, 10.5 * TARGET_CAP_VALUE)

    def test_should_identify_multi_threat_chokes_in_defense_plan(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)
        self.assertEqual(2, len(plan.threats))

        self.assertInterceptChokeTileMoves(plan, map, x=8, y=5, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=9, y=5, w=1)
        self.assertNotInterceptChoke(plan, map, x=10, y=5)
        self.assertNotInterceptChoke(plan, map, x=9, y=4)
        self.assertNotInterceptChoke(plan, map, x=10, y=6)

        self.assertEqual(map.At(14, 6), plan.best_enemy_threat.threat.path.tail.tile)

    def test_should_identify_best_meeting_point_in_intercept_options(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)
        notCity = map.At(14, 6)
        notCity.isCity = False
        map.players[general.player].cities.remove(notCity)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan)

        self.assertEqual(2, len(plan.threats))

        self.assertInterceptChokeTileMoves(plan, map, x=8, y=5, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=9, y=5, w=1)
        self.assertInterceptChokeTileMoves(plan, map, x=13, y=3, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=14, y=3, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=9, y=4, w=0)
        self.assertNotInterceptChoke(plan, map, x=10, y=5)
        self.assertNotInterceptChoke(plan, map, x=10, y=6)

        val, turns, bestOpt = self.get_best_intercept_option_path_values(plan)

        self.assertEqual(map.At(9, 5), bestOpt.tail.tile)

# TODO still need an open-map wide choke example to test finding mid-choke-points on. 3 or wider choke required.
# TODO what about threats where the chokes diverge super early from the threat? Need intercept chokes that are NOT on the shortest path, and find the lowest common denominator between them still?
# TODO ^ also needs to detect when the path SPLITS vs lines on opposite sides of the same choke where an army could stage in the middle, vs being unable to stage in the middle due to blockage by mountains or pure split scenario.
    def test_should_recognize_multi_threat_and_intercept_at_choke__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=289)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        self.assertEqual(2, len(plan.threats))
        self.assertInterceptChokeTileMoves(plan, map, x=2, y=7, w=1)
        self.assertNotInterceptChoke(plan, map, x=5, y=7)
        self.assertNotInterceptChoke(plan, map, x=1, y=5)
        self.assertNotInterceptChoke(plan, map, x=1, y=6)
        self.assertNotInterceptChoke(plan, map, x=1, y=7)
        self.assertNotInterceptChoke(plan, map, x=2, y=8)
        self.assertNotInterceptChoke(plan, map, x=3, y=8)
        self.assertNotInterceptChoke(plan, map, x=4, y=8)

        bestOpt = None
        bestOptAmt = 0
        gatherDepth = 20
        option = plan.intercept_options[3]
        val, path = option
        if path.length < gatherDepth and val > bestOptAmt:
            logbook.info(f'NEW BEST INTERCEPT OPT {val:.2f} -- {str(path)}')
            bestOpt = path
            bestOptAmt = val

        self.assertEqual(map.At(2, 7), bestOpt.tail.tile)

    def test_should_recognize_multi_threat_and_intercept_at_choke__correctly_values_intercept_from_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)
        map.At(1, 8).army = 1
        map.At(1, 8).player = 0
        map.At(1, 9).army = 75

        interception = self.get_interception_plan(map, general, enemyGeneral, additionalPath='1,9->1,8->6,8')

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 8)

        self.assertEqual(1, interception.common_intercept_chokes[map.At(2, 7)], 'all routes can be intercepted in one extra move from this point')
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        # the raw econ differential from this play is +14 econ (-9 -> +5) however it prevents a huge amount of enemy damage as well, so should be calculated as blocking 20 additional econ damage from opponent
        # 14 + 20 should be a value of 36
        self.assertEqual(34, val, 'prevents 20 enemy damage and also recaptures 14 econ worth of tiles')
        # TODO CONTINUE

    def test_should_recognize_multi_threat_and_intercept_at_choke__unit_test_does_not_value_incoming_collisions_that_dont_prevent_caps_to_round_end(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 0, 8, 1, 8)

        if path is not None:  # not even finding this as an intercept is also valid, so only fail if it is found AND its value isn't 0
            self.assertEqual(0, val, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_recognize_multi_threat_and_cannot_fully_intercept_at_choke__unit_recognizes_can_only_block_along_bottom_if_goes_right(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 0, 8, 1, 8)

        if path is not None:  # not even finding this as an intercept is also valid, so only fail if it is found AND its value isn't 0
            self.assertEqual(0, val, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_recognize_multi_threat_and_cannot_fully_intercept_at_choke__unit_recognizes_can_only_block_along_bottom_if_goes_right__including_over_top(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral, additionalPath='1,8->1,4->5,4->5,1')

        if debugMode:
            self.render_intercept_plan(map, interception)

        self.assert_no_intercept_option_by_coords(interception, 0, 8, 1, 8, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_intercept_large_incoming_at_choke_even_with_not_quite_enough__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_large_incoming_at_choke_even_with_not_quite_enough___DiPqVAsND---0--273.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 273, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=273)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)
        self.assertEqual(2, len(plan.threats))

        self.assertNotEqual(0, len(plan.intercept_options))
        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        paths = SearchUtils.where(plan.intercept_options.values(), lambda p: p[1].start.tile.x == 3 and p[1].start.tile.y == 9 and p[1].tail.tile.x == 7 and p[1].tail.tile.y == 9)
        self.assertEqual(1, len(paths))

    def test_should_not_intercept_when_more_economic_to_just_keep_expanding__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gracefully_handle_deviating_en_expansion_path___YuXhnQtCE---1--142.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 142, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=142)
        self.reset_general(rawMap, enemyGeneral)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        # self.assertEqual(1, len(plan.threats), "only econ threat")

        bestVal, bestTurns, bestPath = self.get_best_intercept_option_path_values(plan)
        self.assertLess(bestVal, 7, "should not overvalue any of these intercepts")
        self.assertLess(bestVal/bestTurns, 0.5, 'should not think any of these have great value per turn.')

        self.assertEqual(map.At(9, 8), bestPath.tail.tile)

    def test_should_not_do_infinite_intercepts_costing_tons_of_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 708, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=708)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()

        start = time.perf_counter()
        ArmyAnalyzer.reset_times()
        with bot.perf_timer.begin_move(map.turn):
            BotDefense.build_intercept_plans(bot)
            done = time.perf_counter() - start
        timings = '\r\n'.join(bot.perf_timer.current_move.get_events_organized_longest_to_shortest(25))
        ArmyAnalyzer.dump_times()

        if debugMode:
            winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
            self.assertIsNone(winner)

        self.assertLess(done, 0.05, f'should spent no more than 50ms on intercepts, \r\n{timings}')

    def test_should_see_split_path_blocker_as_mid_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_see_split_path_blocker_as_mid_choke___Human.exe-TEST__0ec78983-f5c3-4648-a5a6-d1d6ac807db9---0--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        enTile = map.At(14, 8)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.At(14, 9), bestOpt.tileList)

    def test_should_meet_to_defend_multi_choke__when_can_reach_not_one_behind(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   a40  b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.At(2, 9), bestOpt.tileList)

    def test_should_meet_to_defend_multi_choke__when_can_reach_one_behind(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
a40  b1   b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.At(2, 9), bestOpt.tileList)

    def test_should_not_take_literal_lifetimes_to_load_intercepts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_literal_lifetimes_to_load_intercepts___nyeEPub4n---7--1165.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1165, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1165)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        start = time.perf_counter()
        ArmyAnalyzer.reset_times()
        with bot.perf_timer.begin_move(map.turn):
            BotDefense.build_intercept_plans(bot)
            done = time.perf_counter() - start
        timings = '\r\n'.join(bot.perf_timer.current_move.get_events_organized_longest_to_shortest(25))
        ArmyAnalyzer.dump_times()
        self.assertLess(done, 0.04, f'should spent no more than 40ms on intercepts, \r\n{timings}')

    def test_should_kill_one_away_armies_that_can_do_real_damage_immediately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_kill_one_away_armies_that_can_do_real_damage_immediately___Human.exe-TEST__665a5e30-6063-4675-bff6-61edf7423b72---1--386.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 386, fill_out_tiles=True)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.At(10, 11), bestOpt.tileList)
        self.assertIn(map.At(10, 12), bestOpt.tileList)

    def test_should_not_miss_intercept_because_of_enemy_expansion_plan_that_is_short_and_irrelevant(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_miss_intercept_for_unknown_reason___Human.exe-TEST__7eae0a59-1775-4864-a321-282de6ef2c4d---0--182.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 182, fill_out_tiles=True)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile, additionalPath='4,7->4,6')

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.At(10, 6), bestOpt.tileList)

    # TODO this is important test map scenario
    def test_should_recognize_diverging_path_around_mountain_as_non_intercept_chokes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=False)

        # map.At(6, 7).isMountain = False
        # map.update_reachable()

        analysis = ArmyAnalyzer(map, map.At(5, 17), map.At(7, 6))
        analysis.scan()
        # if debugMode:
        #     self.render_army_analyzer(map, analysis)
        interceptWidth = analysis.interceptChokes.get(map.At(6, 6), None)
        # TODO
        # self.assertEqual(4, interceptWidth)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        value, turns, bestPath = self.get_best_intercept_option_path_values(interception)
        self.assertEqual(6, bestPath.start.tile.x)
        self.assertEqual(6, bestPath.start.tile.y)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 6, 6, 7, 6)
        self.assertIsNotNone(path)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 5, 6, 7, 6)
        self.assertIsNone(path)

        self.assertNotInterceptChoke(interception, map, 6, 6)
        self.assertNotInterceptChoke(interception, map, 7, 7)

    def test_should_intercept_one_late_at_midpoint_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for includeThirdOpt in [False, True]:
            with self.subTest(includeThirdOpt=includeThirdOpt):
                mapFile = 'GameContinuationEntries/should_intercept_one_late_at_midpoint_choke___Human.exe-TEST__7548ab1f-0519-41ce-a83c-785a43ba5915---0--289.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

                paths = [
                    '1,9->1,4->3,4->3,5',
                    '1,9->1,8->4,8->4,7->5,7->5,2',
                ]
                if includeThirdOpt:
                    paths.append('1,9->1,8->3,8->3,9->5,9->5,8->6,8->6,7->8,7')

                plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, paths)

                if debugMode:
                    self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

                value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
                self.assertIn(map.At(2, 6), bestOpt.tileList)

    def test_should_understand_can_intercept_army_against_corner(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   a40  b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)
        enTile = map.At(3, 11)
        # frTile = map.At(6, 0)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        canInterceptStillTile = map.At(2, 9)
        self.assertEqual(2, plan.common_intercept_chokes[canInterceptStillTile].max_delay_turns, 'can intercept from this tile 1 turn from now by chasing to the right for 4 moves max')
        self.assertEqual(4, plan.common_intercept_chokes[canInterceptStillTile].max_extra_moves_to_capture, 'can intercept from this tile by chasing to the right for 4 moves max')

    def test_should_split_upwards_to_guarantee_damage_control(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_upwards_to_guarantee_damage_control___Human.exe-TEST__a0054186-be26-4c65-90be-ab546e3cc541---1--347.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 347, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=347)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

    def test_should_find_interception_from_4_moves_away(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_interception_from_4_moves_away___Human.exe-TEST__7f68e044-60e0-4a38-9ae8-47af7df82c85---1--346.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 344, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, additionalPath='9,6->8,6->8,7->6,7->6,8->4,8', turnsLeftInCycle= 15)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

    def test_should_delay_intercept_when_enemy_army_is_cornered__maybe_split_half(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_delay_intercept_when_enemy_army_is_cornered__maybe_split_half___13nFmhR-q---0--444.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 444, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
        bestOpt = self.get_best_intercept_option(plan)

        self.assertTrue(bestOpt.path.start.move_half or bestOpt.requiredDelay > 0, 'should EITHER delay or move half TODO figure out which is optimal?')

    def test_should_intercept_with_further_large_tile_when_possible_not_closer_small_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_further_large_tile_when_possible_not_closer_small_tile___Human.exe-TEST__713fc243-c4e6-4f75-8ec6-38e4b0887581---1--188.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 188, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
        bestOpt = self.get_best_intercept_option(plan)

        self.assertTrue(bestOpt.path.start.move_half or bestOpt.requiredDelay > 0, 'should EITHER delay or move half TODO figure out which is optimal?')

    def test_should_not_mis_evaluate_intercept_value_blocked_damage(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_mis_evaluate_intercept_value_blocked_damage___Human.exe-TEST__f7bcf26d-70ff-4e1e-9c87-e0022affe96f---1--348.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 348, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
        bestOpt = self.assert_no_best_intercept_option(plan)
        self.skipTest(f'TODO figure out what this was trying to test, test was never completed.')

    def test_should_not_split_randomly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_split_randomly___-Zrosee5X---0--81.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 81, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        bestOpt = self.get_best_intercept_option(plan)

        self.assertIn(map.At(13, 10), bestOpt.tileList)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        path = self.get_interceptor_option_by_coords_or_none(plan, 13, 9, 12, 9)
        if path is not None:
            self.assertFalse(path.path.start.move_half)

    def test_should_respect_and_defend_defenseless_modifier(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for mustDefend in [False, True]:
            with self.subTest(mustDefend=mustDefend):
                mapFile = 'GameContinuationEntries/should_respect_and_defend_defenseless_modifier___2v3zDUjUn---1--73.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 73, fill_out_tiles=True)
                if mustDefend:
                    map.At(18, 11).army = 1
                    map.At(13, 10).army = 26

                plan = self.get_interception_plan(map, general, enemyGeneral)

                if debugMode:
                    self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

                self.assert_no_intercept_option_by_coords(plan, 12, 10, message='shouldnt even have an option that wastes intercept time regardless of general death')
                bestOpt = self.get_best_intercept_option(plan)

                self.assertIsNotNone(bestOpt, 'should have found an intercept move to the right, though')
                self.assertNotIn(map.At(12, 10), bestOpt.tileList, 'shouldnt delay and let general die')

    def test_should_intercept_obvious_intercept_use_case(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_obvious_intercept_use_case___wQ-7lZL7d---0--131.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 131, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(11, 10), fromTile=map.At(10, 10))

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)

        self.assertEqual((12, 6), bestOpt.path.start.tile.coords)
        self.assertCoordsInPath((12, 8), bestOpt.path)

        # if path is not None:
        #     self.assertFalse(path.path.start.move_half)

    def test_should_evaluate_simple_threat_intercept_correctly__single_threat(self):
        # ref test_should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment for proof of values asserted here
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment___xBu7OEmps---1--185.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 185, fill_out_tiles=True)

        plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, ['9,6->9,5->12,5->12,4->15,4->15,3->17,3->17,2'])

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)

        with self.subTest(baseAssumptions=True):
            self.assertEqual((18, 7), bestOpt.path.start.tile.coords)
            self.assertCoordsInPath((14, 7), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
            self.assertCoordsInPath((14, 6), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
            # if intercept gets revamped to include the recapture path, drop this assert since the above is here.
            self.assertEqual((14, 5), bestOpt.path.tail.tile.coords)

        with self.subTest(damageBlocked=True):
            # 24 total damage by opponent (up top), we block 6 tiles in, so we block 12
            # So assert we block somewhere in that range...
            self.assertGreater(bestOpt.damage_blocked, 5 * TARGET_CAP_VALUE)
            self.assertLess(bestOpt.damage_blocked, 7 * TARGET_CAP_VALUE)

        with self.subTest(recapTurns=True):
            # we recapture 1 post-block tile, so the full econ value should be one more target tile than the raw econ damage blocked
            self.assertEqual(1, bestOpt.recapture_turns)

        with self.subTest(econValue=True):
            # we recapture 1 post-block tile, so the full econ value should be one more target tile than the raw econ damage blocked
            self.assertGreater(bestOpt.econValue, 6 * TARGET_CAP_VALUE)
            self.assertLess(bestOpt.econValue, 8 * TARGET_CAP_VALUE)

        with self.subTest(remainingArmy=True):
            # TODO not sure yet
            self.assertEqual(-1, bestOpt.intercepting_army_remaining)

    def test_should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment(self):
        # ref test_should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment for proof of values asserted here
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment___xBu7OEmps---1--185.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 185, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(9, 6), fromTile=map.At(9, 7))

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)

        self.assertEqual((18, 7), bestOpt.path.start.tile.coords)
        self.assertCoordsInPath((14, 7), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
        self.assertCoordsInPath((14, 6), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
        # if intercept gets revamped to include the recapture path, drop this assert since the above is here.
        self.assertEqual((14, 6), bestOpt.path.tail.tile.coords)

        # bestOpt.intercept.best_enemy_threat

        # 24 total damage by opponent (up top), we block / recapture all but 10 of it, so we block ~ 14 econ damage. 15.4 damage if we do 2.2 damage per tile as calculation.
        # 31.5 damage by opponent (down right), we block recapture all but 10 of it, so we block ~21 econ damage.
        # So assert we block somewhere in that range...
        self.assertGreater(bestOpt.damage_blocked, 13)
        self.assertLess(bestOpt.damage_blocked, 22)

        # self.assertEqual(0, bestOpt.intercepting_army_remaining, 'or should we actually declare how negative the path value ends up being, like we do now?')
        self.assertLessEqual(bestOpt.intercepting_army_remaining, 0, 'Or, should we return 0 when the path goes negative?')

# 18f, 17p, 0s
# 19f, 17p, 0s  before fixing  test_should_intercept_obvious_intercept_use_case
# 26f, 17p, 0s  after reworking a bunch of stuff and better unit testing. Prior to fixing other tests that may be asserting incorrectly. Broke splitting and started disregarding tile-blocking, for now.

    def test_should_delay_any_intercept_from_general_that_could_die__unit(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        for path in [
            '12,4->11,4->11,3',
            '12,4->12,3->11,3',
            '12,4->9,4',
            None,
        ]:
            for canSplit in [True, False]:
                with self.subTest(path=path, canSplit=canSplit):
                    mapFile = 'GameContinuationEntries/should_delay_any_intercept_from_general_that_could_die___INbO_bt38---0--342.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 342, fill_out_tiles=True)

                    if not canSplit:
                        general.army -= 4

                    plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(12, 4), fromTile=map.At(12, 5), additionalPath=path)

                    if debugMode:
                        self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

                    # we SHOULD find an intercept, but plan to delay it.
                    bestOpt = self.get_best_intercept_option(plan)
                    self.assertIsNotNone(bestOpt)
                    self.assertEqual((11, 3), bestOpt.path.start.tile.coords, 'should be intercepting from general')
                    if canSplit:
                        self.assertTrue(bestOpt.path.start.move_half, 'Should prefer splitting to delaying (TODO MAY CHANGE IN FUTURE, THEYRE PRETTY MUCH EVEN IN THIS INSTANCE).')
                        self.assertEqual(0, bestOpt.requiredDelay, 'Should prefer splitting to delaying (TODO MAY CHANGE IN FUTURE, THEYRE PRETTY MUCH EVEN IN THIS INSTANCE).')
                    else:
                        self.assertFalse(bestOpt.path.start.move_half, 'splitting dies here.')
                        self.assertGreater(bestOpt.requiredDelay, 0, 'MUST delay a move to be safe, here.')

    def test_should_NOT_delay_any_intercept_from_general_that_could_not_yet_die(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '12,5->12,3->11,3',
            '12,5->12,4->11,4->11,3',
            '12,5->12,4->9,4',
            None,
        ]:
            for canSplit in [True, False]:
                with self.subTest(path=path, canSplit=canSplit):
                    mapFile = 'GameContinuationEntries/should_delay_any_intercept_from_general_that_could_die___INbO_bt38---0--342.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 342, fill_out_tiles=True)
                    map.At(12, 4).army = 1
                    map.At(12, 4).player = general.player
                    map.At(12, 5).army = 9
                    map.At(12, 5).player = enemyGeneral.player

                    if not canSplit:
                        general.army -= 4

                    plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(12, 5), fromTile=map.At(11, 5), additionalPath=path)

                    if debugMode:
                        self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

                    # we SHOULD find an intercept, but plan to delay it.
                    bestOpt = self.get_best_intercept_option(plan)
                    self.assertIsNotNone(bestOpt)
                    self.assertEqual((11, 3), bestOpt.path.start.tile.coords, 'should be intercepting from general')
                    self.assertEqual(bestOpt.requiredDelay, 0, 'must NOT delay a move to be safe, here.')
                    self.assertFalse(bestOpt.path.start.move_half)
                    # TODO we need some property for this, for indicating when an intercept could not be delayed without taking the extra damage.
                    #   Sometimes it's better to wait when they have no turnaround options, other times like now we MUST not wait.
                    # self.assertEqual(bestOpt.allowedDelay, 0, 'must NOT delay a move to be safe (and prevent econ damage), here.')
    #
    # def test_should_intercept_attack_lmao(self):
    #     # TODO I mean realistically, opponent should NOT move down here, and SHOULD go left or up, so really the bot is probably ok to say no intercept here
    #     #  and just let expansion be the reason it moves up / left from general?
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
    #     mapFile = 'GameContinuationEntries/should_intercept_attack_lmao___Hq7BF7XYj---1--76.txtmap'
    #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 76, fill_out_tiles=True)
    #
    #     plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(14, 15), fromTile=map.At(14, 14), additionalPath='14,15->14,17->15,17')
    #
    #     if debugMode:
    #         self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
    #
    #     # we SHOULD find an intercept, but plan to delay it.
    #     bestOpt = self.get_best_intercept_option(plan)
    #     self.assertIsNotNone(bestOpt)
    #     self.assertEqual((15, 17), bestOpt.path.start.tile.coords, 'should be intercepting from general')
    #     self.assertEqual((15, 16), bestOpt.path.start.next.tile.coords, 'should be intercepting upwards')
    #     self.assertEqual(bestOpt.requiredDelay, 0, 'must NOT delay a move to be safe, here.')
    #     self.assertFalse(bestOpt.path.start.move_half)

    def test_should_intercept_in_one_only__anything_else_dies_or_loses_econ_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_in_one_only__anything_else_dies_or_loses_econ_wtf___Human.exe-TEST__d7e2b2f9-2685-4c2f-9777-da4592c829d8---1--77.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 77, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(14, 16), fromTile=map.At(14, 15), additionalPath='14,16->14,17->15,17')

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        planTileInfo = plan.common_intercept_chokes[map.At(14, 16)]
        self.assertEqual(1, planTileInfo.max_delay_turns, 'if we dont reach it this turn, it gets away. Obviously.')

        # we SHOULD find an intercept, but plan to delay it.
        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)
        self.assertEqual((11, 3), bestOpt.path.start.tile.coords, 'should be intercepting from general')
        self.assertEqual(bestOpt.requiredDelay, 0, 'must NOT delay a move to be safe, here.')
        self.assertFalse(bestOpt.path.start.move_half)

        #
        # self.enable_search_time_limits_and_disable_debug_asserts()
        # simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # simHost.queue_player_moves_str(enemyGeneral.player, path)
        # bot = self.get_debug_render_bot(simHost, general.player)
        # playerMap = simHost.get_player_map(general.player)
        #
        # self.begin_capturing_logging()
        # winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=4)
        # self.assertNoFriendliesKilled(map, general)
        #
        # self.assertOwnedXY(14, 17)
        # self.assertOwnedXY(13, 17)
    def test_should_never_consider_intercepting_parallel_to_be_better_than_literally_hitting_the_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_never_consider_intercepting_parallel_to_be_better_than_literally_hitting_the_tile___52vlrZ4Bz---1--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=136)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(4, 9), fromTile=map.At(4, 10), additionalPath='4,9->0,9->0,14')
        #
        # if debugMode:
        #     self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        # Move 4,10->3,10 is parallel to the enemy army - should be substantially worse than directly hitting 4,10->4,9
        parallel_path, parallel_val, parallel_turns = self.get_interceptor_path_by_coords(plan, 4, 10, 3, 10)
        direct_path, direct_val, direct_turns = self.get_interceptor_path_by_coords(plan, 4, 10, 4, 9)

        # Direct hit should exist and have positive value
        self.assertIsNotNone(direct_path, "direct hit path 4,10->4,9 should exist")
        self.assertGreater(direct_val, 0, "direct hit should have positive value")

        # Parallel move should either not exist, or be substantially worse than direct hit
        if parallel_path is not None:
            self.assertLess(parallel_val / parallel_turns, direct_val / direct_turns, "parallel move 4,10->3,10 should not be better than direct hit 4,10->4,9")
            self.assertLess(parallel_val / parallel_turns, direct_val * 0.5 / direct_turns, f"parallel move should be substantially worse (less than half the value) than direct hit (direct_val {direct_val:.2f}/{direct_turns}t vs parallel_val {parallel_val:.2f}/{parallel_turns}t")

    def test_should_recognize_blocking_enemy_capture_properly__12_13__11_13(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_blocking_enemy_capture_properly__12_13__11_13___Human.exe-TEST__1f3d225e-505f-4eb3-91e0-bda127fdf8c1---0--299.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 299, fill_out_tiles=False)
        self.begin_capturing_logging()

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.At(11, 14), additionalPath='11,14->11,13')

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        opt = self.get_interceptor_option_by_coords(plan, 12, 13, 11, 13)
        self.assertEqual(1, opt.turns)
        self.assertGreater(opt.econValue, 2)

    def test_should_correctly_value_intercept_from_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_value_intercept_from_general___jzXGxMXQl---1--323.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 323, fill_out_tiles=False)
        self.begin_capturing_logging()

        plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, paths=[
            # '6,4->6,5->5,5->5,11->6,11->6,15->5,15z->4,15->4,16->5,16', # actual worst case, however these were teh ones in game:
            '6,4->6,5->6,6->5,6->5,7->4,7->4,8->4,9->4,10->4,11->3,11',
            '6,4->7,4->7,5->7,6->7,7->7,8->7,9->6,9->6,10->6,11->6,12->6,13->6,14->6,15->7,15->8,15->9,15->9,14->9,13',
            '6,4->6,5->5,5->5,6->5,7->5,8->5,9->5,10->5,11->4,11->3,11->3,12->2,12->1,12->0,12',
            '6,4->6,5',
        ])
        self.assertIsNotNone(plan)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        # # # TODO REF test_should_correctly_value_intercept_from_general in /Tests/test_ArmyInterception.py
        #       which goes through all the raw simulations of pure econ damage to prove exactly what each of the two intercepts should actually be worth, and what the threat is worth max.
        #       The below is a copy paste from that test along with the notes on the exact damage that each of these intercept options does.
        # simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # simHost.queue_player_moves_str(enemyGeneral.player, '6,4->6,5->5,5->5,11->6,11->6,15->5,15z->4,15->4,16->5,16  6,15->10,15')
        # # ^ literally does 38 econ damage in 21 turns, so that's the best we could hope to block. (goes from +8 to -30 tile differential if we do nothing).
        # #   A single path at best can get 30 econ damage in 17 turns though.
        #
        # # proof ignore, proves that ^ literally does 38 econ damage, so that's the best we could hope to block.
        # # simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None')
        #
        # # proof shortest. This goes from +8 to -16 tile differential, or 24 damage, blocking 14 (or 6 if evaling against single path).
        # #  Terminates at 5 turns with enemy army remaining = 21, enemy captures 9 more turns
        # # simHost.queue_player_moves_str(general.player, '4,11->4,9->5,9->5,7  None  None  None  None  None  None  None  None  None  None  None  None  None')
        #
        # # proof short. This goes from +8 to -2 tile differential, or 10 damage, blocking 28 (or 20 if evaling against single path).
        # #  Terminates at 6 turns with enemy army remaining = 4, enemy makes a single additional capture after.
        # # simHost.queue_player_moves_str(general.player, '2,11->4,11->4,9->5,9->5,8')
        #
        # # proof long. This goes from +8 to +20 tile differential, REVERSING 12 damage, blocking all 38 (or 30 if evaling against single path) AND doing 12 damage.
        # #  Intercepts at turn 6 with -19 enemy army remaining, recapture complete at 15 turns.
        # # simHost.queue_player_moves_str(general.player, '2,10->2,11->4,11->4,9->5,9->5,5->6,5->6,4')

        # should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can do is either 4,8 or 5,9 depending which we choose.
        optGenBad = self.get_interceptor_option_by_coords_or_none(plan, 2, 10, 5, 8)
        # should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can do is either 4,8 or 5,9 depending which we choose.
        optShortBad = self.get_interceptor_option_by_coords_or_none(plan, 2, 11, 5, 8)

        # SHOULD exist, this one CAN intercept at 4,7 / 5,8 in 4 (5 bc one more move to actually intercept) turns
        optShortest = self.get_interceptor_option_by_coords_or_none(plan, 4, 11, 5, 8)

        optGen = self.get_interceptor_option_by_coords(plan, 2, 10, 5, 9)  # intercepts with army at 5,9 and enemy army at 5,9
        optShort = self.get_interceptor_option_by_coords(plan, 2, 11, 5, 9)  # intercepts with army at 5,9 and enemy army at 5,8. So arguably this is 5,8 intercept idk
        worstCaseAddlMovesBecauseRightPath = 2
        with self.subTest(assertion='should find correct move lengths for short intercept'):
            self.assertEqual(6+worstCaseAddlMovesBecauseRightPath, optShort.length, 'See comment above, but our army dies at the intercept, enemy has 4 army left over, and we intercept 6 moves in but our worst case is +2 (?).')
        with self.subTest(assertion='should find correct move lengths for long intercept'):
            self.assertEqual(15+worstCaseAddlMovesBecauseRightPath, optGen.length, 'See comment above, but our army ends with 16 left over for us at intercept (also after 6 moves since enemy is moving towards us). We can recapture until 15 turns have passed at which point we\'ll have spent all our army capping 1\'s.')


        with self.subTest(assertion='should only find midway intercept point'):
            self.assertIsNone(optGenBad, "should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can intercept at is either 4,8 or 5,9 depending which we choose.")
            self.assertIsNone(optShortBad, "should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can intercept at is either 4,8 or 5,9 depending which we choose.")
        with self.subTest(assertion='should find shortest int at 4,7 / 5,8'):
            self.assertIsNotNone(optShortest, 'should find shortest int at 4,7 / 5,8')

        enemyMinExpectedDamage = 28 # a straight longest path find must find 28 damage for this armies attack.
        enemyMaxExpectedDamage = 38 # if we somehow calculated flow or splits, the enemy army CAN do 38 tile damage.

        genIntExpectedRecaptures = 6

        enemyDamageStillDealtWithShortIntercept = 10

        with self.subTest(assertion='should find correct econvalue for general intercept'):
            self.assertGreaterEqual(optGen.econValue, enemyMinExpectedDamage + genIntExpectedRecaptures * 2)
            self.assertLessEqual(optGen.econValue, enemyMaxExpectedDamage + genIntExpectedRecaptures * 2.2)

        with self.subTest(assertion='should find correct econvalue for shorter intercept'):
            self.assertGreaterEqual(optShort.econValue, (enemyMinExpectedDamage - enemyDamageStillDealtWithShortIntercept))
            self.assertLessEqual(optShort.econValue, (enemyMaxExpectedDamage - enemyDamageStillDealtWithShortIntercept))

        with self.subTest(assertion='shouldnt overvalue shortest'):
            self.assertGreaterEqual(optShortest.econValue, 3 * 2, "if evaling against single path the best it can block is 6 damage")
            self.assertLessEqual(optShortest.econValue, 7 * 2.2, "if evaling against split path / expand flow, the best it can block is 7 tiles * cap value")

    def test_should_correctly_value_intercept_from_general__inner_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_value_intercept_from_general___jzXGxMXQl---1--323.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 323, fill_out_tiles=False)
        self.begin_capturing_logging()

        plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, paths=[
            '6,4->6,5->5,5->5,11->6,11->6,15->5,15->4,15->4,16', # actual worst case, however these were teh ones in game:
            '6,4->6,5->6,6->5,6->5,7->4,7->4,8->4,9->4,10->4,11->3,11',
            '6,4->6,5->5,5->5,6->5,7->5,8->5,9->5,10->5,11->4,11->3,11->3,12->2,12->1,12->0,12',
        ])
        self.assertIsNotNone(plan)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        # # # TODO REF test_should_correctly_value_intercept_from_general in /Tests/test_ArmyInterception.py
        #       which goes through all the raw simulations of pure econ damage to prove exactly what each of the two intercepts should actually be worth, and what the threat is worth max.
        #       The below is a copy paste from that test along with the notes on the exact damage that each of these intercept options does.
        # simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # simHost.queue_player_moves_str(enemyGeneral.player, '6,4->6,5->5,5->5,11->6,11->6,15->5,15z->4,15->4,16->5,16  6,15->10,15')
        # # ^ literally does 38 econ damage in 21 turns, so that's the best we could hope to block. (goes from +8 to -30 tile differential if we do nothing).
        # #   A single path at best can get 30 econ damage in 17 turns though.
        #
        # # proof ignore, proves that ^ literally does 38 econ damage, so that's the best we could hope to block.
        # # simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None')
        #
        # # proof shortest. This goes from +8 to -16 tile differential, or 24 damage, blocking 14 (or 6 if evaling against single path).
        # #  Terminates at 5 turns with enemy army remaining = 21, enemy captures 9 more turns
        # # simHost.queue_player_moves_str(general.player, '4,11->4,9->5,9->5,7  None  None  None  None  None  None  None  None  None  None  None  None  None')
        #
        # # proof short. This goes from +8 to -2 tile differential, or 10 damage, blocking 28 (or 20 if evaling against single path).
        # #  Terminates at 6 turns with enemy army remaining = 4, enemy makes a single additional capture after.
        # # simHost.queue_player_moves_str(general.player, '2,11->4,11->4,9->5,9->5,8')
        #
        # # proof long. This goes from +8 to +20 tile differential, REVERSING 12 damage, blocking all 38 (or 30 if evaling against single path) AND doing 12 damage.
        # #  Intercepts at turn 6 with -19 enemy army remaining, recapture complete at 15 turns.
        # # simHost.queue_player_moves_str(general.player, '2,10->2,11->4,11->4,9->5,9->5,5->6,5->6,4')

        # FOR THE LONG PATH:
        #   We know we should actually be intercepting with -19 (so, 19) army remaining:
        #   The move right before they intercept is a friendly 61 (4,9) moving onto a friendly 2 (5,9).
        #   The enemy is moving a 44 (5,8) onto that same friendly 2 (4,9).
        #
        #   So effectively after executing our move first, the enemy is moving 44 onto 62 (since 2 + 61 -1 = 62, we leave 1 behind on the tile we leave as always).
        #   The enemy moves 43 (leaving 1 of their 44 behind), 62-43 = 19. We have a 19 left

        # should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can do is either 4,8 or 5,9 depending which we choose.
        optGenBad = self.get_interceptor_option_by_coords_or_none(plan, 2, 10, 5, 8)
        # should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can do is either 4,8 or 5,9 depending which we choose.
        optShortBad = self.get_interceptor_option_by_coords_or_none(plan, 2, 11, 5, 8)

        # SHOULD exist, this one CAN intercept at 4,7 / 5,8 in 4 (5 bc one more move to actually intercept) turns
        optShortest = self.get_interceptor_option_by_coords_or_none(plan, 4, 11, 5, 8)

        optGen = self.get_interceptor_option_by_coords_or_none(plan, 2, 10, 5, 9)  # intercepts with army at 5,9 and enemy army at 5,9
        optShort = self.get_interceptor_option_by_coords_or_none(plan, 2, 11, 5, 9)  # intercepts with army at 5,9 and enemy army at 5,8. So arguably this is 5,8 intercept idk
        with self.subTest(assertion='should find correct move lengths for short intercept'):
            self.assertEqual(6, optShort.length, 'See comment above, but our army dies at the intercept, enemy has 4 army left over, and we intercept 6 moves in but our worst case is +2 (?).')
        with self.subTest(assertion='should find correct move lengths for long intercept'):
            self.assertEqual(15, optGen.length, 'See comment above, but our army ends with 16 left over for us at intercept (also after 6 moves since enemy is moving towards us). We can recapture until 15 turns have passed at which point we\'ll have spent all our army capping 1\'s.')


        with self.subTest(assertion='should only find midway intercept point'):
            self.assertIsNone(optGenBad, "should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can intercept at is either 4,8 or 5,9 depending which we choose.")
            self.assertIsNone(optShortBad, "should not exist, we can't intercept at 4,7 / 5,8 from 2,11. Best we can intercept at is either 4,8 or 5,9 depending which we choose.")
        with self.subTest(assertion='should find shortest int at 4,7 / 5,8'):
            self.assertIsNotNone(optShortest, 'should find shortest int at 4,7 / 5,8')

        enemyMinExpectedDamage = 28 # a straight longest path find must find 28 damage for this armies attack.
        enemyMaxExpectedDamage = 38 # if we somehow calculated flow or splits, the enemy army CAN do 38 tile damage.

        genIntExpectedRecaptures = 6

        enemyDamageStillDealtWithShortIntercept = 10

        with self.subTest(assertion='should find correct econvalue for general intercept'):
            self.assertGreaterEqual(optGen.econValue, enemyMinExpectedDamage + genIntExpectedRecaptures * 2)
            self.assertLessEqual(optGen.econValue, enemyMaxExpectedDamage + genIntExpectedRecaptures * 2.2)

        with self.subTest(assertion='should find correct econvalue for shorter intercept'):
            self.assertGreaterEqual(optShort.econValue, (enemyMinExpectedDamage - enemyDamageStillDealtWithShortIntercept))
            self.assertLessEqual(optShort.econValue, (enemyMaxExpectedDamage - enemyDamageStillDealtWithShortIntercept))

        with self.subTest(assertion='shouldnt overvalue shortest'):
            self.assertGreaterEqual(optShortest.econValue, 3 * 2, "if evaling against single path the best it can block is 6 damage")
            self.assertLessEqual(optShortest.econValue, 7 * 2.2, "if evaling against split path / expand flow, the best it can block is 7 tiles * cap value")