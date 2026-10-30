from __future__ import annotations

import typing
import unittest
from dataclasses import dataclass

from TestBase import TestBase
from Army import Army
from ArmyTracker import ArmyTracker
from Behavior.OffenseAnalyzer import OffenseAnalyzer
from BoardAnalyzer import BoardAnalyzer
from PerformanceTimer import PerformanceTimer
from Strategy.OpponentTracker import OpponentTracker
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile


class FakeOpponentTracker(OpponentTracker):
    """
    Test-only OpponentTracker that returns fixed fog-risk and historical emergence data.
    """
    def __init__(self, map: MapBase, fog_risk: int = 100, last_attacked: typing.List[typing.Tuple[int, Tile] | None] | None = None):
        super().__init__(map, None)
        self.fog_risk = fog_risk
        self.last_attacked = last_attacked or []

    def get_immediate_fog_risk(self, player: int, our_city_spanning_tree_tile_count: int) -> typing.Tuple[int, int, int, int]:
        return self.fog_risk, 50, 50, 0

    def get_last_attacked_from_locations(self, forPlayer: int, lastNRounds: int = 1) -> typing.List[typing.Tuple[int, Tile] | None]:
        return self.last_attacked


@dataclass(slots=True)
class FakeBot:
    targetPlayer: int
    targetPlayerExpectedGeneralLocation: Tile | None
    viewInfo: ViewInfo
    friendly_city_spanning_tree: typing.Set[Tile] | None


class OffenseAnalyzerSectionAUnitTests(TestBase):
    """
    Unit tests for OffenseAnalyzer Section A: anticipated enemy fog armies and aggregate distance matrix.
    """

    def test_should_select_close_well_separated_fog_sources_and_aggregate_distances(self):
        raw_map = (
            "|    |    |    |    |    |\n"
            "aG1  \n"
            "     \n"
            "     \n"
            "     \n"
            "bG1  \n"
            "|    |    |    |    |    |\n"
            "turn=1\n"
            "player_index=0\n"
            "bot_target_player=1\n"
            "targetPlayerExpectedGeneralLocation=4,4\n"
        )
        map, general, _ = self.load_map_and_generals_from_string(raw_map, turn=1, player_index=0, fill_out_tiles=False)

        # Force the enemy general to the far corner (4,4) so the core play area is large
        # and the bG1 tile at (0,4) can be used as a regular fog candidate.
        enemy_general = map.At(4, 4)
        enemy_general.player = 1
        enemy_general.isGeneral = True
        enemy_general.army = 1
        enemy_general.visible = True
        enemy_general.discovered = True
        map.generals[1] = enemy_general
        map.players[1].general = enemy_general

        board = BoardAnalyzer(map, general, None)
        board.rebuild_intergeneral_analysis(enemy_general)

        army_tracker = ArmyTracker(map, PerformanceTimer(), None)

        # two high-emergence fog tiles in the core play area, separated by >= 5 tiles.
        # Both are outside the initial 3x3 vision so they remain undiscovered.
        t1 = map.At(4, 0)
        t2 = map.At(0, 4)
        for t in (t1, t2):
            t.isTempFogPrediction = True
            t.player = 1
            t.army = 1
            t.visible = False
            t.discovered = False
            t.isGeneral = False
            army_tracker.valid_general_positions_by_player[1].add(t)
            army_tracker.emergenceLocationMap[1].raw[t.tile_index] = 10.0

        # a third nearby candidate that should be excluded by the 5-tile separation rule
        t3 = map.At(4, 1)
        t3.isTempFogPrediction = True
        t3.player = 1
        t3.army = 1
        t3.visible = False
        t3.discovered = False
        t3.isGeneral = False
        army_tracker.valid_general_positions_by_player[1].add(t3)
        army_tracker.emergenceLocationMap[1].raw[t3.tile_index] = 10.0

        # tracked fog army on t1 so we can verify subtraction
        fog_army = Army(t1)
        fog_army.value = 7
        fog_army.player = 1
        fog_army.visible = False
        army_tracker.armies[t1] = fog_army

        opponent_tracker = FakeOpponentTracker(map, fog_risk=100)
        timer = PerformanceTimer()
        timer.begin_move('test')
        analyzer = OffenseAnalyzer(map, board, army_tracker, opponent_tracker, timer)

        bot = FakeBot(
            targetPlayer=1,
            targetPlayerExpectedGeneralLocation=enemy_general,
            viewInfo=ViewInfo(2, map),
            friendly_city_spanning_tree=set(),
        )

        analyzer.get_offense_options(bot, 0)

        # t1 and t2 are selected; t3 is too close to t1
        self.assertIn(t1, analyzer.anticipated_fog_armies)
        self.assertIn(t2, analyzer.anticipated_fog_armies)
        self.assertNotIn(t3, analyzer.anticipated_fog_armies)

        expected_t1 = max(0.0, 100 - map.distance_mapper.get_distance_between(t1, enemy_general) - 7)
        expected_t2 = max(0.0, 100 - map.distance_mapper.get_distance_between(t2, enemy_general))
        self.assertEqual(analyzer.anticipated_fog_armies[t1].anticipated_army_value, expected_t1)
        self.assertEqual(analyzer.anticipated_fog_armies[t2].anticipated_army_value, expected_t2)

        # the visible enemy general is also included as a concrete source
        self.assertIn(enemy_general, analyzer.anticipated_fog_armies)

        self.assertIsNotNone(analyzer.all_en_armies_distance_matrix)
        self.assertEqual(analyzer.all_en_armies_distance_matrix.raw[t1.tile_index], 0)
        self.assertEqual(analyzer.all_en_armies_distance_matrix.raw[t2.tile_index], 0)
        self.assertEqual(analyzer.all_en_armies_distance_matrix.raw[enemy_general.tile_index], 0)
        # general is 4 steps from the nearest selected fog source
        self.assertEqual(analyzer.all_en_armies_distance_matrix.raw[general.tile_index], 4)

    def test_should_return_empty_options_when_no_target_player(self):
        raw_map = (
            "|    |    |    |    |    |\n"
            "aG1  \n"
            "     \n"
            "     \n"
            "     \n"
            "bG1  \n"
            "|    |    |    |    |    |\n"
            "turn=1\n"
            "player_index=0\n"
        )
        map, general, enemy_general = self.load_map_and_generals_from_string(raw_map, turn=1, player_index=0, fill_out_tiles=False)

        board = BoardAnalyzer(map, general, None)
        board.rebuild_intergeneral_analysis(enemy_general)

        army_tracker = ArmyTracker(map, PerformanceTimer(), None)
        opponent_tracker = FakeOpponentTracker(map)
        timer = PerformanceTimer()
        timer.begin_move('test')
        analyzer = OffenseAnalyzer(map, board, army_tracker, opponent_tracker, timer)

        bot = FakeBot(
            targetPlayer=-1,
            targetPlayerExpectedGeneralLocation=None,
            viewInfo=ViewInfo(2, map),
            friendly_city_spanning_tree=set(),
        )

        options = analyzer.get_offense_options(bot, 0)
        self.assertEqual(options, [])
        self.assertEqual(analyzer.anticipated_fog_armies, {})
        self.assertIsNone(analyzer.all_en_armies_distance_matrix)


class OffenseAnalyzerSectionBUnitTests(TestBase):
    """
    Unit tests for OffenseAnalyzer Section B: pivot distance maps and reverse threat matrix.
    """

    def test_should_build_pivot_distances_and_reverse_threat_matrix(self):
        raw_map = (
            "|    |    |    |    |    |\n"
            "aG1  \n"
            "     \n"
            "     \n"
            "                    bC1  \n"
            "                    bG1  \n"
            "|    |    |    |    |    |\n"
            "turn=1\n"
            "player_index=0\n"
            "bot_target_player=1\n"
        )
        map, general, enemy_general = self.load_map_and_generals_from_string(raw_map, turn=1, player_index=0, fill_out_tiles=False)

        board = BoardAnalyzer(map, general, None)
        board.rebuild_intergeneral_analysis(enemy_general)

        army_tracker = ArmyTracker(map, PerformanceTimer(), None)
        opponent_tracker = FakeOpponentTracker(map)
        timer = PerformanceTimer()
        timer.begin_move('test')
        analyzer = OffenseAnalyzer(map, board, army_tracker, opponent_tracker, timer)

        bot = FakeBot(
            targetPlayer=1,
            targetPlayerExpectedGeneralLocation=enemy_general,
            viewInfo=ViewInfo(2, map),
            friendly_city_spanning_tree=set(),
        )

        analyzer.get_offense_options(bot, 0)

        # enemy_general is the general at (4,4) and bC1 at (4,3) is a city
        enemy_city = map.At(4, 3)
        self.assertTrue(enemy_city.isCity)
        self.assertEqual(enemy_city.player, 1)

        self.assertIn(enemy_general, analyzer.pivot_distances_by_tile_map)
        self.assertIn(enemy_city, analyzer.pivot_distances_by_tile_map)

        general_pivot = analyzer.pivot_distances_by_tile_map[enemy_general]
        city_pivot = analyzer.pivot_distances_by_tile_map[enemy_city]

        # base reverse threat is army + capture cost
        self.assertEqual(general_pivot.army_needed_to_maintain_threat.raw[enemy_general.tile_index], 2.0)
        self.assertEqual(city_pivot.army_needed_to_maintain_threat.raw[enemy_city.tile_index], 2.0)

        # tile (3,4) is adjacent to the general; its threat requirement should be
        # base + target tile army + 1 move + 1 production on turn 1 depth 1
        adjacent = map.At(3, 4)
        self.assertEqual(general_pivot.army_needed_to_maintain_threat.raw[adjacent.tile_index], 5.0)

        # aggregate distance matrix is the min across both pivots
        self.assertIsNotNone(analyzer.all_pivots_distance_matrix)
        self.assertEqual(analyzer.all_pivots_distance_matrix.raw[enemy_general.tile_index], 0)
        self.assertEqual(analyzer.all_pivots_distance_matrix.raw[enemy_city.tile_index], 0)
        self.assertEqual(analyzer.all_pivots_distance_matrix.raw[general.tile_index], 7)


class OffenseAnalyzerSectionCUnitTests(TestBase):
    """
    Unit tests for OffenseAnalyzer Section C: friendly large-army routing near enemy pivots.
    """

    def test_should_route_friendly_large_army_to_enemy_pivot(self):
        raw_map = (
            "|    |    |    |    |    |\n"
            "aG1  \n"
            "     \n"
            "     \n"
            "                    bC1  \n"
            "               a10  bG1  \n"
            "|    |    |    |    |    |\n"
            "turn=1\n"
            "player_index=0\n"
            "bot_target_player=1\n"
        )
        map, general, enemy_general = self.load_map_and_generals_from_string(raw_map, turn=1, player_index=0, fill_out_tiles=False)

        board = BoardAnalyzer(map, general, None)
        board.rebuild_intergeneral_analysis(enemy_general)

        army_tracker = ArmyTracker(map, PerformanceTimer(), None)
        opponent_tracker = FakeOpponentTracker(map)
        timer = PerformanceTimer()
        timer.begin_move('test')
        analyzer = OffenseAnalyzer(map, board, army_tracker, opponent_tracker, timer)

        bot = FakeBot(
            targetPlayer=1,
            targetPlayerExpectedGeneralLocation=enemy_general,
            viewInfo=ViewInfo(2, map),
            friendly_city_spanning_tree=set(),
        )

        analyzer.get_offense_options(bot, 0)

        friendly_source = map.At(3, 4)
        self.assertEqual(friendly_source.player, 0)
        self.assertEqual(friendly_source.army, 10)

        self.assertIn(friendly_source, analyzer.friendly_army_dist_data)
        data = analyzer.friendly_army_dist_data[friendly_source]

        # moving from (3,4) with 10 army leaves 9 movable
        self.assertEqual(data.distance_matrix.raw[friendly_source.tile_index], 0)
        self.assertEqual(data.enemy_capture_count_matrix.raw[friendly_source.tile_index], 0)
        self.assertEqual(data.army_remaining_matrix.raw[friendly_source.tile_index], 9)

        # adjacent enemy general at (4,4): distance 1, 1 enemy captured, 9 - (1 + 1) = 7 remaining
        enemy_general = map.At(4, 4)
        self.assertEqual(data.distance_matrix.raw[enemy_general.tile_index], 1)
        self.assertEqual(data.enemy_capture_count_matrix.raw[enemy_general.tile_index], 1)
        self.assertEqual(data.army_remaining_matrix.raw[enemy_general.tile_index], 7)

        # enemy city at (4,3): two moves, 2 enemy tiles captured, 7 - (1 + 1) = 5 remaining
        enemy_city = map.At(4, 3)
        self.assertEqual(data.distance_matrix.raw[enemy_city.tile_index], 2)
        self.assertEqual(data.enemy_capture_count_matrix.raw[enemy_city.tile_index], 2)
        self.assertEqual(data.army_remaining_matrix.raw[enemy_city.tile_index], 5)

        # the friendly general at (0,0) is closer to itself than to any pivot, so it is excluded
        self.assertNotIn(general, analyzer.friendly_army_dist_data)


class OffenseAnalyzerSectionDUnitTests(TestBase):
    """
    Unit tests for OffenseAnalyzer Section D: collective offensive space search.
    """

    def test_should_compute_collective_offensive_space_and_mark_equal_distance_boundary(self):
        raw_map = (
            "|    |    |    |    |    |\n"
            "aG1                    \n"
            "                          \n"
            "                          \n"
            "bG3                 a10  \n"
            "|    |    |    |    |    |\n"
            "turn=1\n"
            "player_index=0\n"
            "bot_target_player=1\n"
        )
        map, general, enemy_general = self.load_map_and_generals_from_string(raw_map, turn=1, player_index=0, fill_out_tiles=False)

        board = BoardAnalyzer(map, general, None)
        board.rebuild_intergeneral_analysis(enemy_general)

        army_tracker = ArmyTracker(map, PerformanceTimer(), None)
        opponent_tracker = FakeOpponentTracker(map)
        timer = PerformanceTimer()
        timer.begin_move('test')
        analyzer = OffenseAnalyzer(map, board, army_tracker, opponent_tracker, timer)

        bot = FakeBot(
            targetPlayer=1,
            targetPlayerExpectedGeneralLocation=enemy_general,
            viewInfo=ViewInfo(2, map),
            friendly_city_spanning_tree=set(),
        )

        analyzer.get_offense_options(bot, 0)

        friendly_source = map.At(4, 3)
        self.assertEqual(friendly_source.player, 0)
        self.assertEqual(friendly_source.army, 10)

        # (4,3) is the friendly large army; (0,3) is the enemy general.
        self.assertEqual(analyzer.offensive_tile_team_matrix.raw[friendly_source.tile_index], 0)
        self.assertEqual(analyzer.offensive_tile_army_source_matrix.raw[friendly_source.tile_index], friendly_source.tile_index)
        self.assertEqual(analyzer.offensive_tile_distance_matrix.raw[friendly_source.tile_index], 0)

        self.assertEqual(analyzer.offensive_tile_team_matrix.raw[enemy_general.tile_index], 1)
        self.assertEqual(analyzer.offensive_tile_army_source_matrix.raw[enemy_general.tile_index], enemy_general.tile_index)
        self.assertEqual(analyzer.offensive_tile_distance_matrix.raw[enemy_general.tile_index], 0)

        # (3,3) is one step from the friendly source and is not contested by the enemy.
        friendly_side_tile = map.At(3, 3)
        self.assertEqual(analyzer.offensive_tile_team_matrix.raw[friendly_side_tile.tile_index], 0)
        self.assertEqual(analyzer.offensive_tile_army_source_matrix.raw[friendly_side_tile.tile_index], friendly_source.tile_index)
        self.assertEqual(analyzer.offensive_tile_distance_matrix.raw[friendly_side_tile.tile_index], 1)
        self.assertEqual(analyzer.offensive_num_neutral_traversed_matrix.raw[friendly_side_tile.tile_index], 1)

        # (1,3) is one step from the enemy source.
        target_side_tile = map.At(1, 3)
        self.assertEqual(analyzer.offensive_tile_team_matrix.raw[target_side_tile.tile_index], 1)
        self.assertEqual(analyzer.offensive_tile_army_source_matrix.raw[target_side_tile.tile_index], enemy_general.tile_index)
        self.assertEqual(analyzer.offensive_tile_distance_matrix.raw[target_side_tile.tile_index], 1)
        self.assertEqual(analyzer.offensive_num_neutral_traversed_matrix.raw[target_side_tile.tile_index], 1)

        # (2,3) is equidistant from both seeds and should be marked as a tied boundary.
        boundary_tile = map.At(2, 3)
        self.assertEqual(analyzer.offensive_tile_distance_matrix.raw[boundary_tile.tile_index], 2)
        self.assertEqual(analyzer.offensive_tile_team_matrix.raw[boundary_tile.tile_index], -1)
        self.assertIsNone(analyzer.offensive_tile_army_source_matrix.raw[boundary_tile.tile_index])
        self.assertEqual(analyzer.offensive_num_neutral_traversed_matrix.raw[boundary_tile.tile_index], 2)


class OffenseAnalyzerSectionEUnitTests(TestBase):
    """
    Unit tests for OffenseAnalyzer Section E: stage-one actionable interception paths.
    """

    def test_should_emit_stage_one_interception_path_to_first_target_boundary(self):
        raw_map = (
            "|    |    |    |    |    |\n"
            "aG1                    \n"
            "                          \n"
            "                          \n"
            "bG1                 a10  \n"
            "|    |    |    |    |    |\n"
            "turn=1\n"
            "player_index=0\n"
            "bot_target_player=1\n"
        )
        map, general, enemy_general = self.load_map_and_generals_from_string(raw_map, turn=1, player_index=0, fill_out_tiles=False)

        board = BoardAnalyzer(map, general, None)
        board.rebuild_intergeneral_analysis(enemy_general)

        army_tracker = ArmyTracker(map, PerformanceTimer(), None)
        opponent_tracker = FakeOpponentTracker(map)
        timer = PerformanceTimer()
        timer.begin_move('test')
        analyzer = OffenseAnalyzer(map, board, army_tracker, opponent_tracker, timer)

        bot = FakeBot(
            targetPlayer=1,
            targetPlayerExpectedGeneralLocation=enemy_general,
            viewInfo=ViewInfo(2, map),
            friendly_city_spanning_tree=set(),
        )

        options = analyzer.get_offense_options(bot, 0)

        self.assertEqual(len(options), 1)
        option = options[0]
        self.assertEqual(option.target_pivot_tile, enemy_general)
        self.assertEqual(option.path.tail.tile, map.At(1, 3))
        self.assertEqual(option.path.length, 3)
        self.assertEqual(option.path.value, 7.0)
        self.assertEqual(option.econValue, 4.0)
        self.assertEqual(option.damage_prevented, 1.0)
        self.assertEqual(option.raw_capture_econ_value, 3.0)
