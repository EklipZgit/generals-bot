from collections import deque
from dataclasses import dataclass

from Behavior.ArmyInterceptionModels import ArmyInterception
from Behavior.ArmyInterceptorV2 import (
    FriendlyMultiSourceMatrix,
    SourceLayeredReach,
    ThreatReachMatrix,
    V2CandidatePath,
)
from DangerAnalyzer import ThreatType
from TestBase import TestBase
from base.client.map import MapBase, Tile


@dataclass(slots=True)
class ArmyInterceptionV2Scenario:
    map: MapBase
    general: Tile
    enemy_general: Tile
    enemy_tile: Tile | None


class ArmyInterceptionV2UnitTests(TestBase):
    __slots__ = ()

    USE_V2_INTERCEPTION: bool = True

    def __init__(self, methodName: str = ...) -> None:
        """Initialize deterministic V2 interception scenarios."""
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)
        self.use_v2_interception = (
            ArmyInterceptionV2UnitTests.USE_V2_INTERCEPTION)
        TestBase.GLOBAL_BYPASS_RENDERING = True

    def test_should_build_v2_invariants_for_kill_and_city_threat(self) -> None:
        """Exercise the V2 matrices on the existing kill/city test scenario."""
        map_file = (
            'GameContinuationEntries/'
            'should_see_city_as_forward_from_central_point___'
            'HgAyaVTVa---1--307.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            307,
            fill_out_tiles=True)
        self._assert_v2_scenario_invariants(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=map.At(7, 14),
            ))

    def test_should_build_v2_invariants_for_one_kill_threat(self) -> None:
        """Exercise V2 with the existing single-kill interception scenario."""
        map_file = (
            'GameContinuationEntries/'
            'should_kill_one_away_armies_that_can_do_real_damage_'
            'immediately___Human.exe-TEST__665a5e30-6063-4675-bff6-'
            '61edf7423b72---1--386.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            386,
            fill_out_tiles=True)
        self._assert_v2_scenario_invariants(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=None,
            ),
            require_single_kill_threat=True)

    def _assert_v2_scenario_invariants(
        self,
        scenario: ArmyInterceptionV2Scenario,
        require_single_kill_threat: bool = False,
    ) -> None:
        """Compare V1 and V2 plans and validate each V2 search stage."""
        turns_left_in_cycle = 50 - scenario.map.turn % 50
        self.use_v2_interception = False
        v1_plan = self.get_interception_plan(
            scenario.map,
            scenario.general,
            scenario.enemy_general,
            enTile=scenario.enemy_tile,
            turnsLeftInCycle=turns_left_in_cycle,
            useDebugLogging=False)
        self.assertIsNotNone(v1_plan)
        if require_single_kill_threat:
            self.assertEqual(1, len(v1_plan.threat_values))
            self.assertEqual(
                ThreatType.Kill,
                v1_plan.threat_values[0].threat.threatType)

        best_v1_damage_blocked = max(
            (
                option.damage_blocked
                for option in v1_plan.intercept_options.values()
            ),
            default=0.0)

        self.use_v2_interception = True
        v2_plan = self.get_interception_plan(
            scenario.map,
            scenario.general,
            scenario.enemy_general,
            enTile=scenario.enemy_tile,
            turnsLeftInCycle=turns_left_in_cycle,
            useDebugLogging=False)
        self.assertIsNotNone(v2_plan)
        self.assertTrue(v2_plan.intercept_options)

        for option in v2_plan.intercept_options.values():
            self.assertTrue(
                scenario.map.is_tile_friendly(option.path.start.tile))
            self.assertIn(
                option.path.tail.tile,
                v2_plan.common_intercept_chokes)
        self.assertGreaterEqual(
            max(
                option.damage_blocked
                for option in v2_plan.intercept_options.values()),
            best_v1_damage_blocked)

        v2_interceptor = self.get_interceptor(
            scenario.map,
            scenario.general,
            scenario.enemy_general,
            useDebugLogging=False)
        max_depth = min(
            v2_interceptor._get_max_interception_search_depth(
                v1_plan.threats),
            turns_left_in_cycle)
        threat_reach = v2_interceptor.v2.build_threat_reach_matrix(
            v1_plan,
            max_depth,
            turns_left_in_cycle)
        friendly_reach = v2_interceptor.v2.build_friendly_multi_source_matrix(
            v1_plan,
            threat_reach)
        layered_reaches = [
            v2_interceptor.v2.build_source_layered_reach(
                threat_reach,
                source_index)
            for source_index in friendly_reach.selected_source_indices
        ]
        candidates = v2_interceptor.v2.build_intercept_candidates(
            v1_plan,
            threat_reach,
            friendly_reach,
            layered_reaches,
            turns_left_in_cycle)
        candidate_paths = (
            v2_interceptor.v2.reconstruct_candidate_paths(
                threat_reach,
                friendly_reach,
                layered_reaches,
                candidates))
        self.assertTrue(candidate_paths)

        for source in threat_reach.candidate_sources:
            self.assertTrue(scenario.map.is_tile_friendly(source))
            self.assertGreaterEqual(source.army, 2)

        for source_index in friendly_reach.selected_source_indices:
            source = friendly_reach.candidate_sources[source_index]
            self.assertGreaterEqual(
                threat_reach.choke_budget.budget[source.tile_index],
                0)

        for source_reach in layered_reaches:
            for depth, states in enumerate(source_reach.states_by_depth):
                for tile_index in states:
                    self.assertLessEqual(
                        depth,
                        threat_reach.choke_budget.budget[tile_index])

        for candidate in candidates:
            intercept_info = v1_plan.common_intercept_chokes[
                candidate.choke_tile]
            limit = min(intercept_info.max_delay_turns, max_depth)
            self.assertLessEqual(candidate.depth, limit)

        self._assert_threat_reach_distances(
            scenario.map,
            v1_plan.target_tile,
            threat_reach.enemy_turn,
            max_depth)
        self._assert_candidate_path_invariants(
            scenario,
            v1_plan,
            threat_reach,
            friendly_reach,
            layered_reaches,
            candidate_paths)

    def _assert_threat_reach_distances(
        self,
        map: MapBase,
        target_tile: Tile,
        enemy_turn: list[int],
        max_depth: int,
    ) -> None:
        """Compare threat BFS distances except where a neutral-city detour applies."""
        distance_matrix = map.distance_mapper.get_tile_dist_matrix(
            target_tile).raw
        neutral_allowed_distances = self._get_distances(
            map,
            target_tile,
            allow_neutral_cities=True)
        tile_count = len(enemy_turn)
        for tile_index in range(tile_count):
            matrix_distance = distance_matrix[tile_index]
            if (
                matrix_distance > max_depth
                or matrix_distance >= 1000
                or enemy_turn[tile_index] == -1
            ):
                continue
            if enemy_turn[tile_index] == matrix_distance:
                continue
            has_neutral_city_detour = (
                neutral_allowed_distances[tile_index] == matrix_distance
                and matrix_distance < enemy_turn[tile_index])
            self.assertTrue(
                has_neutral_city_detour,
                f'threat turn {enemy_turn[tile_index]} != map distance '
                f'{matrix_distance} at tile {map.get_tile_by_tile_index(tile_index)}')

    def _get_distances(
        self,
        map: MapBase,
        start_tile: Tile,
        allow_neutral_cities: bool,
    ) -> list[int]:
        """Build a test-only shortest-distance map with optional neutral cities."""
        tiles = list(map.get_all_tiles())
        distances = [-1] * len(tiles)
        start_index = start_tile.tile_index
        distances[start_index] = 0
        frontier: deque[int] = deque([start_index])
        while frontier:
            tile_index = frontier.popleft()
            current_tile = tiles[tile_index]
            for next_tile in current_tile.movable:
                if next_tile.isObstacle:
                    continue
                if (
                    not allow_neutral_cities
                    and next_tile.isCity
                    and next_tile.isNeutral
                ):
                    continue
                next_index = next_tile.tile_index
                if distances[next_index] != -1:
                    continue
                distances[next_index] = distances[tile_index] + 1
                frontier.append(next_index)
        return distances

    def _assert_candidate_path_invariants(
        self,
        scenario: ArmyInterceptionV2Scenario,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        layered_reaches: list[SourceLayeredReach],
        candidate_paths: list[V2CandidatePath],
    ) -> None:
        """Validate candidate paths and their stored layered army values."""
        for candidate_path in candidate_paths:
            candidate = candidate_path.candidate
            source = friendly_reach.candidate_sources[
                candidate.source_index]
            path_tiles = candidate_path.path.tileList
            self.assertEqual(source, path_tiles[0])
            self.assertEqual(candidate.choke_tile, path_tiles[-1])
            self.assertEqual(
                len(path_tiles),
                len({tile.tile_index for tile in path_tiles}))
            for previous_tile, next_tile in zip(
                path_tiles,
                path_tiles[1:]):
                self.assertIn(next_tile, previous_tile.movable)
            self.assertIn(
                candidate.choke_tile,
                interception.common_intercept_chokes)

            friendly_army = 0
            for tile in path_tiles:
                friendly_army += (
                    threat_reach.step_deltas.friendly_step_delta[
                        tile.tile_index])
            self.assertEqual(
                candidate_path.friendly_army_at_choke,
                friendly_army)
            candidate_states = layered_reaches[
                candidate.layer_index
            ].states_by_depth[candidate.depth]
            self.assertIn(candidate.choke_tile.tile_index, candidate_states)
            self.assertEqual(
                candidate_path.friendly_army_at_choke,
                candidate_states[candidate.choke_tile.tile_index][0])
