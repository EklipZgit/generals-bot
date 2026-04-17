import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, FlowGraphMethod
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot

method = FlowGraphMethod.MinCostFlow


class FlowExpansionTargetCrossableTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def _build_expander_v2(self, map, builder):
        """Helper: build ArmyFlowExpanderV2 with flow graph and detection results."""
        from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
        expander = ArmyFlowExpanderV2(map)
        enemy_general = map.generals[1 - map.player_index]
        expander.target_team = map.team_ids_by_player_index[enemy_general.player]
        expander.enemyGeneral = enemy_general
        expander._ensure_flow_graph_exists(builder)
        return expander

    # ------------------------------------------------------------------
    # No target-crossable cases
    # ------------------------------------------------------------------

    def test_target_crossable__simple_linear_map__no_crossable(self):
        """
        Simplest map: single friendly island borders single enemy island directly.
        The friendly border island is the main gather source, not an encircled outpost.
        Expected: zero target-crossable islands.

        Layout:
          aG10  a1  b1  bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG10 a1   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        self.assertEqual(0, len(target_crossable), 'No islands should be target-crossable in a simple two-island linear map')

    def test_target_crossable__large_friendly_island_on_border__not_crossable_due_to_size(self):
        """
        A friendly island that is mostly surrounded by enemy tiles but is too large (>= 1/5 of
        total friendly tiles) should NOT be marked target-crossable.

        In the map format each cell is one tile (a# = 1 tile with army #).  To get a 5-tile
        friendly island surrounded by enemy tiles, we place 5 adjacent a-cells together.

        Layout (5 rows, 7 cols):
          b1   b1   b1   b1   b1   b1
          b1   a1   a1   a1   b1   bG1
          b1   a1   a1   b1   b1   b1
          b1   b1   b1   b1   b1   b1

        The 5 friendly a1 tiles form one island (tile_count = 5).
        Total friendly = 5.  Threshold = 5 // 5 = 1.  Island has 5 tiles >= 1 → NOT crossable.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
b1   b1   b1   b1   b1   b1
b1   aG1  a1   a1   b1   bG1
b1   a1   a1   b1   b1   b1
b1   b1   b1   b1   b1   b1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # All a-tiles are border tiles so each is a 1-tile leaf island; full_island.tile_count = 5.
        # total_friendly = 5, threshold = 1.  parent_tile_count = 5 >= 1 → condition 3 blocks → NOT crossable.
        self.assertEqual(0, len(target_crossable),
                         'Large friendly island should not be target-crossable even when surrounded by enemies')

    def test_target_crossable__friendly_island_with_equal_border_tiles__not_crossable(self):
        """
        A small friendly island where enemy and friendly border tile counts are equal.
        Condition 2 (enemy > friendly border tiles) fails, so it must NOT be target-crossable.

        Layout (3 rows, 4 cols):
          a1  M   b1  bG1
          a1  a1  b1  b1
          a1  M   b1  b1

        The lone a1 at (col1, row1) borders: M above/below (mountains, no island), a1 left
        (1 friendly tile), b1 right (1 enemy tile).
        enemy_border_tiles == friendly_border_tiles (both = 1) → condition 2 fails → NOT crossable.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  M    b1   bG1
a1   a1   b1   b1
a1   M    b1   b1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # The lone a1 at (col1, row1) borders exactly 1 friendly tile (left) and 1 enemy tile (right).
        # Mountains block top/bottom.  enemy_border_tiles == friendly_border_tiles → condition 2 fails.
        self.assertEqual(0, len(target_crossable),
                         'Friendly island with equal enemy/friendly border tile counts must not be target-crossable')

    # ------------------------------------------------------------------
    # Target-crossable cases
    # ------------------------------------------------------------------

    def test_target_crossable__small_encircled_friendly_outpost__is_crossable(self):
        """
        A small 1-tile friendly outpost separated from the main friendly island by b-tiles,
        sitting adjacent to the enemy general.  All four conditions for target-crossable must fire.

        FINAL layout (5 rows, 6 cols) — outpost fully surrounded on all 4 sides by b1:
          b1   b1   b1   b1   b1   b1
          aG1  a1   a1   a1   b1   bG1
          a1   a1   a1   b1   a1   b1   ← outpost at (col4,row2)
          a1   a1   a1   a1   b1   b1
          b1   b1   b1   b1   b1   b1

        Main: 9 tiles (aG1+8 a1s).  Outpost at (4,2): b1 on all 4 sides.
        Total friendly leaf tiles = 9+1 = 10.  Threshold = 10//5 = 2.
        Outpost full_island = itself (1 tile) < 2 → condition 3 passes.
        enemy_border_tiles = 4 b-team tiles, friendly_border = 0 → condition 2 passes.
        Flow routes through outpost toward bG1 → condition 4 passes.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
b1   b1   b1   b1   b1   b1
aG1  a1   a1   a1   b1   bG1
a1   a1   a1   b1   a1   b1
a1   a1   a1   a1   b1   b1
b1   b1   b1   b1   b1   b1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # Outpost at (4,2): b1 on all 4 sides → no adjacent friendly tiles → full_island = itself (1 tile).
        # total_friendly = 10 leaf tiles, threshold = 2, outpost parent = 1 < 2 → crossable.
        outpost_tile = map.GetTile(4, 2)  # column 4, row 2 (0-indexed)
        outpost_island = builder.tile_island_lookup.raw[outpost_tile.tile_index]

        main_tile = map.GetTile(0, 1)  # any main-island tile (aG1)
        main_island = builder.tile_island_lookup.raw[main_tile.tile_index]

        self.assertEqual(1, outpost_island.tile_count, 'Outpost should be a 1-tile leaf island')
        outpost_parent_count = outpost_island.full_island.tile_count if outpost_island.full_island is not None else outpost_island.tile_count
        total_friendly = sum(i.tile_count for i in builder.tile_islands_by_team_id[expander.team])
        threshold = total_friendly // 5
        self.assertEqual(1, outpost_parent_count,
                         'Outpost full_island should be itself (1 tile) since it has no friendly neighbours')
        self.assertLess(outpost_parent_count, threshold,
                        f'Outpost parent_tile_count={outpost_parent_count} must be < threshold={threshold}')

        self.assertIn(outpost_island.unique_id, target_crossable,
                      'Small friendly outpost surrounded on all sides by enemy tiles should be target-crossable')
        self.assertNotIn(main_island.unique_id, target_crossable,
                         'Main large friendly island must NOT be target-crossable')

    def test_target_crossable__small_outpost_excluded_from_border_pair_seeding(self):
        """
        When a small friendly outpost is detected as target-crossable, it must be excluded
        from border-pair seeding (i.e., must not appear as the friendly_island_id in any
        returned FlowBorderPairKey).

        Same layout as the encircled-outpost test above.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
b1   b1   b1   b1   b1   b1
aG1  a1   a1   a1   b1   bG1
a1   a1   a1   b1   a1   b1
a1   a1   a1   a1   b1   b1
b1   b1   b1   b1   b1   b1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )

        outpost_tile = map.GetTile(4, 2)  # outpost: b1 on all 4 sides
        outpost_island = builder.tile_island_lookup.raw[outpost_tile.tile_index]

        # The outpost must be in target_crossable
        self.assertIn(outpost_island.unique_id, target_crossable,
                      'Outpost must have been marked target-crossable first')

        # No border pair should use the outpost as the friendly seed
        for bp in border_pairs:
            self.assertNotEqual(outpost_island.unique_id, bp.friendly_island_id,
                                f'Target-crossable outpost island {outpost_island.unique_id} must not appear '
                                f'as friendly_island_id in any border pair')

    def test_target_crossable__outpost_not_crossable_when_no_enemy_flow_in(self):
        """
        A small friendly island that satisfies the size and border-ratio conditions but does
        NOT have enemy flow routed through it in the flow graph must NOT be marked
        target-crossable.

        Layout: the outpost is reachable only via friendly tiles; enemy tiles are on the
        far right of the map, separated from the outpost by a neutral column.

          aG20  a1   (neutral)  b1  bG1

        The a1 island is immediately right of aG20 and left of a neutral tile.
        Border neighbours of a1: aG20 (friendly, many tiles) on left, neutral on right.
        enemy_border_tiles = 0, friendly_border_tiles = big → condition 2 fails → not crossable.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG20 a1        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # a1 only borders the large friendly aG20 island on its left and a neutral on its right.
        # No enemy tiles border it, so condition 2 never triggers.
        self.assertEqual(0, len(target_crossable),
                         'Friendly island with no enemy border tiles must not be target-crossable')

    def test_target_crossable__two_outposts__both_crossable(self):
        """
        Two separate small friendly outposts, each bordered only by enemy tiles, with a large
        multi-tile main friendly island as the primary source.  Both outposts must be detected
        as target-crossable.

        Layout (6 rows, 7 cols):
          b1   b1   b1   b1   b1   b1   b1
          aG1  a1   a1   b1   a1   b1   bG1  ← outpost1 at (col4,row1)
          a1   a1   a1   b1   b1   b1   b1   ← b1 below outpost1
          a1   a1   a1   b1   b1   a1   b1   ← outpost2 at (col5,row3)
          a1   a1   a1   b1   b1   b1   b1   ← b1 below outpost2
          b1   b1   b1   b1   b1   b1   b1

        Main: cols 0-2, rows 1-4 = 12 tiles (all border, 1-tile leaves).
        Outpost1 at (4,1): b1 above, b1 below (4,2), b1 left (3,1), bG1 right (5,1) → enemy_border=4.
        Outpost2 at (5,3): b1 above (5,2), b1 below (5,4), b1 left (4,3), b1 right (6,3) → enemy_border=4.
        Total = 12+1+1 = 14.  Threshold = 14//5 = 2.
        Each outpost full_island = itself (1 tile) < 2 → condition 3 passes.
        Flow routes each outpost toward bG1 at (6,1) → condition 4 passes.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
b1   b1   b1   b1   b1   b1   b1
aG1  a1   a1   b1   a1   b1   bG1
a1   a1   a1   b1   b1   b1   b1
a1   a1   a1   b1   b1   a1   b1
a1   a1   a1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # Outpost1 at (4,1): b1 on all 4 sides (fully isolated).  Outpost2 at (5,3): b1 on all 4 sides.
        # Each full_island = itself (1 tile).  Total friendly = 14.  Threshold = 14//5 = 2.  1 < 2 → passes.
        outpost1_tile = map.GetTile(4, 1)  # first outpost
        outpost2_tile = map.GetTile(5, 3)  # second outpost
        outpost1_island = builder.tile_island_lookup.raw[outpost1_tile.tile_index]
        outpost2_island = builder.tile_island_lookup.raw[outpost2_tile.tile_index]

        main_tile = map.GetTile(0, 1)
        main_island = builder.tile_island_lookup.raw[main_tile.tile_index]

        self.assertEqual(1, outpost1_island.tile_count, 'First outpost should be a 1-tile island')
        self.assertEqual(1, outpost2_island.tile_count, 'Second outpost should be a 1-tile island')

        # Both outposts should be target-crossable
        self.assertIn(outpost1_island.unique_id, target_crossable,
                      'First outpost should be target-crossable')
        self.assertIn(outpost2_island.unique_id, target_crossable,
                      'Second outpost should be target-crossable')

        # Main island must never be target-crossable
        self.assertNotIn(main_island.unique_id, target_crossable,
                         'Main large friendly island must not be target-crossable')

        self.assertEqual(2, len(target_crossable),
                         'Exactly the two outposts should be detected as target-crossable')

    def test_target_crossable__two_outposts__neither_appear_as_border_pair_seeds(self):
        """
        Given two target-crossable outposts, neither of them should appear as
        friendly_island_id in any border pair returned by _enumerate_border_pairs.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
b1   b1   b1   b1   b1   b1   b1
aG1  a1   a1   b1   a1   b1   bG1
a1   a1   a1   b1   b1   b1   b1
a1   a1   a1   b1   b1   a1   b1
a1   a1   a1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )

        outpost1_tile = map.GetTile(4, 1)  # outpost1: b1 on all 4 sides
        outpost2_tile = map.GetTile(5, 3)  # outpost2: b1 on all 4 sides
        outpost1_island = builder.tile_island_lookup.raw[outpost1_tile.tile_index]
        outpost2_island = builder.tile_island_lookup.raw[outpost2_tile.tile_index]

        crossable_ids = {outpost1_island.unique_id, outpost2_island.unique_id}
        for bp in border_pairs:
            self.assertNotIn(bp.friendly_island_id, crossable_ids,
                             f'Target-crossable outpost {bp.friendly_island_id} must never seed a border pair')

    def test_target_crossable__outpost_threshold_boundary__exactly_at_threshold_not_crossable(self):
        """
        A friendly outpost whose tile count is EXACTLY equal to the 1/5 threshold must NOT
        be marked target-crossable (the check is strict: island.tile_count >= threshold → skip).

        Layout (6 rows, 6 cols):
          b1   b1   b1   b1   b1   b1
          aG1  a1   b1   b1   b1   b1
          a1   a1   b1   a1   a1   b1   ← outpost at cols 3-4, row 2
          a1   a1   b1   b1   b1   b1
          a1   a1   b1   b1   b1   b1
          b1   b1   b1   b1   bG1  b1

        Main: cols 0-1, rows 1-4 = 8 tiles.  Outpost: (3,2)+(4,2) = 2 tiles.
        full_island of outpost covers both contiguous tiles = 2 tiles.
        Total = 8+2 = 10.  Threshold = 10//5 = 2.  Outpost parent = 2 >= 2 → NOT crossable.
        bG1 is placed at (4,5) so its tile_index (5*6+4=34) > aG1's tile_index (1*6+0=6),
        ensuring player 0 (a) is recognised as the bot.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
b1   b1   b1   b1   b1   b1
aG1  a1   b1   b1   b1   b1
a1   a1   b1   a1   a1   b1
a1   a1   b1   b1   b1   b1
a1   a1   b1   b1   b1   b1
b1   b1   b1   b1   bG1  b1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # Outpost at (3,2) and (4,2): two contiguous tiles, b1 above (row1) and b1 below (row3).
        # They share a full_island of 2 tiles.  Total = 8+2 = 10.  Threshold = 2.  parent=2 >= 2 → NOT crossable.
        outpost_tile = map.GetTile(3, 2)
        outpost_island = builder.tile_island_lookup.raw[outpost_tile.tile_index]
        outpost_parent = outpost_island.full_island if outpost_island.full_island is not None else outpost_island

        total_friendly = sum(i.tile_count for i in builder.tile_islands_by_team_id[expander.team])
        threshold = total_friendly // 5
        self.assertEqual(2, outpost_parent.tile_count,
                         'Outpost full_island should cover exactly 2 tiles')
        self.assertEqual(2, threshold,
                         f'Total=10 tiles so threshold must be 2, got threshold={threshold}')
        self.assertGreaterEqual(outpost_parent.tile_count, threshold,
                                f'Outpost parent_tile_count=2 must be >= threshold={threshold} → NOT crossable')
        self.assertNotIn(outpost_island.unique_id, target_crossable,
                         'Island whose parent is exactly at the 1/5-threshold must NOT be target-crossable '
                         '(check is >=, so equal is excluded)')

    def test_target_crossable__outpost_one_below_threshold__is_crossable(self):
        """
        A friendly outpost whose tile count is exactly ONE BELOW the 1/5 threshold must
        be detected as target-crossable (assuming all other conditions are met).

        Layout (5 rows, 6 cols):
          b1   b1   b1   b1   b1   b1
          aG1  a1   a1   b1   a1   bG1   ← outpost at (col4,row1), b1 on all 4 sides
          a1   a1   a1   b1   b1   b1
          a1   a1   a1   b1   b1   b1
          b1   b1   b1   b1   b1   b1

        Main: cols 0-2, rows 1-3 = 9 tiles (all border leaves).  Outpost at (4,1): 1 tile.
        Outpost neighbours: b1(4,0) above, b1(4,2) below, b1(3,1) left, bG1(5,1) right.
        full_island of outpost = itself (1 tile, no friendly neighbours).
        Total = 9+1 = 10.  Threshold = 10//5 = 2.  Outpost parent = 1 < 2 → IS crossable.
        enemy_border = 4, friendly_border = 0 → condition 2 passes.
        Flow routes outpost toward bG1 → condition 4 passes.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
b1   b1   b1   b1   b1   b1
aG1  a1   a1   b1   a1   bG1
a1   a1   a1   b1   b1   b1
a1   a1   a1   b1   b1   b1
b1   b1   b1   b1   b1   b1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        outpost_tile = map.GetTile(4, 1)
        outpost_island = builder.tile_island_lookup.raw[outpost_tile.tile_index]
        outpost_parent = outpost_island.full_island if outpost_island.full_island is not None else outpost_island

        total_friendly = sum(i.tile_count for i in builder.tile_islands_by_team_id[expander.team])
        threshold = total_friendly // 5

        self.assertEqual(1, outpost_parent.tile_count,
                         'Outpost parent island should cover exactly 1 tile')
        self.assertGreaterEqual(threshold, 2,
                                f'Total friendly tiles should be >= 10 so threshold >= 2, got threshold={threshold}')
        self.assertLess(outpost_parent.tile_count, threshold,
                        f'Outpost parent_tile_count=1 must be < threshold={threshold} → IS crossable')
        self.assertIn(outpost_island.unique_id, target_crossable,
                      'Island whose parent is one tile below the 1/5-threshold should be target-crossable')

    def test_target_crossable__multi_tile_outpost_fully_surrounded__is_crossable(self):
        """
        A 2-tile friendly outpost fully enclosed by enemy tiles must be detected as
        target-crossable when: the parent island size is below the 1/5 threshold,
        enemy_border > friendly_border, and flow routes through the outpost.

        Layout (7 rows, 7 cols):
          b1   b1   b1   b1   b1   b1   b1
          aG1  a1   a1   a1   b1   b1   bG1  ← bG1 at (6,1)
          a1   a1   a1   a1   b1   a1   b1   ← outpost tile 1 at (5,2)
          a1   a1   a1   a1   b1   a1   b1   ← outpost tile 2 at (5,3), receives enemy flow via (6,3)
          a1   a1   a1   a1   b1   b1   b1
          b1   b1   b1   b1   b1   b1   b1

        bG1 at (6,1) drives enemy flow via (6,3) into the outpost at (5,3), making (5,3)
        the sole crossing point for enemy flow into friendly territory.

        Main: cols 0-3, rows 1-4 = 16 tiles.  Outpost: (5,2) + (5,3) = 2 tiles.
        full_island of outpost covers 2 tiles (isolated from main by col-4 b1 barrier).
        Total = 16+2 = 18.  Threshold = 18//5 = 3.  Outpost parent = 2 < 3 → IS crossable.

        Condition 2 (enemy_border > friendly_border) per leaf island:
          - (5,2) top: up=b1, left=b1, right=b1 → enemy=3 vs friendly=1 (down=(5,3)) → passes
          - (5,3) bot: down=b1, left=b1, right=b1 → enemy=3 vs friendly=1 (up=(5,2)) → passes

        Condition 4 (enemy flow / crossable chain propagation):
          - (5,3) bot: direct enemy flow_from (6,3) → marked crossable directly
          - (5,2) top: flow_from (5,3) which is already crossable → propagated as crossable

        Both tiles satisfy all conditions → both are crossable.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
b1   b1   b1   b1   b1   b1   b1
aG1  a1   a1   a1   b1   b1   bG1
a1   a1   a1   a1   b1   a1   b1
a1   a1   a1   a1   b1   a1   b1
a1   a1   a1   a1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        # Both outpost tiles are contiguous and share a full_island of 2 tiles.
        # Neither touches any main-island tile (separated by the col-4 b1 barrier).
        outpost_top = builder.tile_island_lookup.raw[map.GetTile(5, 2).tile_index]
        outpost_bot = builder.tile_island_lookup.raw[map.GetTile(5, 3).tile_index]

        def get_parent(isl):
            return isl.full_island if isl.full_island is not None else isl

        parent_top = get_parent(outpost_top)
        parent_bot = get_parent(outpost_bot)

        self.assertEqual(2, parent_top.tile_count, 'Outpost full_island must cover exactly 2 tiles')
        self.assertIs(parent_top, parent_bot, 'Both outpost leaf islands must share the same full_island')

        total_friendly = sum(i.tile_count for i in builder.tile_islands_by_team_id[expander.team])
        threshold = total_friendly // 5
        self.assertGreater(threshold, 2,
                           f'Threshold must exceed 2 for this test to be valid, got threshold={threshold} (total={total_friendly})')
        self.assertLess(parent_top.tile_count, threshold,
                        f'Outpost parent_tile_count=2 must be < threshold={threshold} → IS crossable')

        # Condition 2: both tiles have enemy_border=3 > friendly_border=1 → pass.
        # Condition 4: one tile receives direct enemy flow; the other is propagated via the
        # flow chain (flow_from a crossable friendly). Both must be crossable.
        self.assertIn(outpost_top.unique_id, target_crossable,
                      'Outpost top (5,2) must be target-crossable: surrounded by enemy tiles and in flow chain')
        self.assertIn(outpost_bot.unique_id, target_crossable,
                      'Outpost bot (5,3) must be target-crossable: surrounded by enemy tiles and in flow chain')

        # Main island must not be affected
        main_island = builder.tile_island_lookup.raw[map.GetTile(0, 1).tile_index]
        self.assertNotIn(main_island.unique_id, target_crossable,
                         'Main large friendly island must NOT be target-crossable')

    def test_target_crossable__multi_tile_outpost_fully_surrounded__not_crossable_at_threshold(self):
        """
        A 3-tile friendly outpost fully enclosed by enemy tiles must NOT be target-crossable
        when its parent island size exactly meets the 1/5 threshold.

        Layout (6 rows, 7 cols):
          b1   b1   b1   b1   b1   b1   b1
          aG1  a1   a1   b1   b1   a1   b1   ← outpost tile 1 at (5,1)
          a1   a1   a1   b1   b1   a1   b1   ← outpost tile 2 at (5,2)
          a1   a1   a1   b1   b1   a1   bG1  ← outpost tile 3 at (5,3)
          a1   a1   a1   b1   b1   b1   b1
          b1   b1   b1   b1   b1   b1   b1

        Main: cols 0-2, rows 1-4 = 12 tiles.  Outpost: (5,1),(5,2),(5,3) = 3 tiles.
        full_island of outpost = 3 tiles (no friendly neighbours across the col-4/5 b1 gap).
        Total = 12+3 = 15.  Threshold = 15//5 = 3.  Outpost parent = 3 >= 3 → NOT crossable.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
b1   b1   b1   b1   b1   b1   b1
aG1  a1   a1   b1   b1   a1   b1
a1   a1   a1   b1   b1   a1   b1
a1   a1   a1   b1   b1   a1   bG1
a1   a1   a1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        outpost_top = builder.tile_island_lookup.raw[map.GetTile(5, 1).tile_index]
        outpost_mid = builder.tile_island_lookup.raw[map.GetTile(5, 2).tile_index]
        outpost_bot = builder.tile_island_lookup.raw[map.GetTile(5, 3).tile_index]

        def get_parent(isl):
            return isl.full_island if isl.full_island is not None else isl

        parent = get_parent(outpost_top)
        self.assertEqual(3, parent.tile_count, 'Outpost full_island must cover exactly 3 tiles')
        self.assertIs(parent, get_parent(outpost_mid), 'All outpost tiles must share the same full_island')
        self.assertIs(parent, get_parent(outpost_bot), 'All outpost tiles must share the same full_island')

        total_friendly = sum(i.tile_count for i in builder.tile_islands_by_team_id[expander.team])
        threshold = total_friendly // 5
        self.assertEqual(3, threshold,
                         f'Total=15 tiles so threshold must be 3, got threshold={threshold} (total={total_friendly})')
        self.assertGreaterEqual(parent.tile_count, threshold,
                                f'Outpost parent_tile_count=3 must be >= threshold={threshold} → NOT crossable')

        for isl, label in [(outpost_top, '(5,1)'), (outpost_mid, '(5,2)'), (outpost_bot, '(5,3)')]:
            self.assertNotIn(isl.unique_id, target_crossable,
                             f'Multi-tile outpost leaf at {label} must NOT be target-crossable (parent meets threshold)')

    def test_target_crossable__three_tile_chain_outpost__all_crossable(self):
        """
        A 3-tile friendly outpost in a vertical chain, fully enclosed by enemy tiles, must
        have ALL three tiles detected as target-crossable when the parent island size is below
        the 1/5 threshold.

        Layout (7 rows, 7 cols):
          b1   b1   b1   b1   b1   b1   b1
          aG1  a1   a1   a1   b1   a1   b1   ← outpost tile 1 at (5,1)
          a1   a1   a1   a1   b1   a1   b1   ← outpost tile 2 at (5,2)
          a1   a1   a1   a1   b1   a1   bG1  ← outpost tile 3 at (5,3), receives enemy flow
          a1   a1   a1   a1   b1   b1   b1
          b1   b1   b1   b1   b1   b1   b1

        Main: cols 0-3, rows 1-4 = 16 tiles.  Outpost: (5,1),(5,2),(5,3) = 3 tiles.
        full_island of outpost = 3 tiles (isolated from main by col-4 b1 barrier).
        Total = 16+3 = 19.  Threshold = 19//5 = 3.  Outpost parent = 3 >= 3 → NOT crossable.

        Need threshold > 3, so main = 17 tiles (add one row): cols 0-3 rows 1-5 = 20 tiles.
        Total = 20+3 = 23.  Threshold = 23//5 = 4.  Outpost parent = 3 < 4 → IS crossable.

        bG1 at (6,3) drives enemy flow into (5,3) directly.
        (5,2) and (5,1) each have enemy_border=3 > friendly_border=1 and border a crossable
        island → both propagated as crossable.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
b1   b1   b1   b1   b1   b1   b1
aG1  a1   a1   a1   b1   a1   b1
a1   a1   a1   a1   b1   a1   b1
a1   a1   a1   a1   b1   a1   bG1
a1   a1   a1   a1   b1   b1   b1
a1   a1   a1   a1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = self._build_expander_v2(map, builder)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        outpost_top = builder.tile_island_lookup.raw[map.GetTile(5, 1).tile_index]
        outpost_mid = builder.tile_island_lookup.raw[map.GetTile(5, 2).tile_index]
        outpost_bot = builder.tile_island_lookup.raw[map.GetTile(5, 3).tile_index]

        def get_parent(isl):
            return isl.full_island if isl.full_island is not None else isl

        parent = get_parent(outpost_top)
        self.assertEqual(3, parent.tile_count, 'Outpost full_island must cover exactly 3 tiles')
        self.assertIs(parent, get_parent(outpost_mid), 'All outpost tiles must share the same full_island')
        self.assertIs(parent, get_parent(outpost_bot), 'All outpost tiles must share the same full_island')

        total_friendly = sum(i.tile_count for i in builder.tile_islands_by_team_id[expander.team])
        threshold = total_friendly // 5
        self.assertGreater(threshold, 3,
                           f'Threshold must exceed 3 for this test to be valid, got threshold={threshold} (total={total_friendly})')
        self.assertLess(parent.tile_count, threshold,
                        f'Outpost parent_tile_count=3 must be < threshold={threshold} → IS crossable')

        for isl, label in [(outpost_top, '(5,1)'), (outpost_mid, '(5,2)'), (outpost_bot, '(5,3)')]:
            self.assertIn(isl.unique_id, target_crossable,
                          f'Outpost tile {label} must be target-crossable: fully enclosed in enemy territory')

        main_island = builder.tile_island_lookup.raw[map.GetTile(0, 1).tile_index]
        self.assertNotIn(main_island.unique_id, target_crossable,
                         'Main large friendly island must NOT be target-crossable')
