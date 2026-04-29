import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms import PyMaxFlowIteratorHelpers
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, FlowGraphMethod
from BehaviorAlgorithms.Flow.NxFlowGraphData import NxFlowGraphData
from BehaviorAlgorithms.PyMaxFlowIteratorHelpers import PyMaxFlowGraphData, NxToPyMaxflowConverter
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot

method = FlowGraphMethod.PyMaxflowBoykovKolmogorov


class FlowExpansionNetworkXPyMaxEquivalencyTests(TestBase):
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

    def assertNxAndPyMaxEquivalent(self, map: MapBase, general: Tile, enemyGeneral: Tile):
        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        expanderPyMax = ArmyFlowExpanderV2(map)
        expanderPyMax.method = FlowGraphMethod.PyMaxflowBoykovKolmogorov
        expanderPyMax.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expanderPyMax.enemy_general = enemyGeneral
        expanderPyMax._ensure_flow_graph_exists(builder)

        expanderNx = ArmyFlowExpanderV2(map)
        expanderNx.method = FlowGraphMethod.MinCostFlow
        expanderNx.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expanderNx.enemy_general = enemyGeneral
        expanderNx._ensure_flow_graph_exists(builder)

        pyMaxInputGraph: PyMaxFlowGraphData = expanderPyMax._pymax_finder.pymax_graph_data

        # Use the NX graph that was internally used to build pyMaxInputGraph so that
        # unique_ids are consistent between the two PyMaxFlowGraphData objects.
        nxInputGraph: NxFlowGraphData = expanderPyMax._pymax_finder._nx_finder.nx_graph_data

        conv = NxToPyMaxflowConverter()
        pyMaxConverted = conv.convert_nx_flow_graph_data(nxInputGraph)

        self.assertPyMaxInputGraphsExactEquivalent(pyMaxInputGraph, pyMaxConverted)

    def assertPyMaxInputGraphsExactEquivalent(self, pyMaxInputGraph: PyMaxFlowGraphData, pyMaxConverted: PyMaxFlowGraphData):
        self.assertIsNotNone(pyMaxInputGraph)
        self.assertIsNotNone(pyMaxConverted)

        self.assertEqual(pyMaxInputGraph.num_nodes, pyMaxConverted.num_nodes,
                         f'num_nodes mismatch: {pyMaxInputGraph.num_nodes} != {pyMaxConverted.num_nodes}')

        self.assertEqual(pyMaxInputGraph.cumulative_demand, pyMaxConverted.cumulative_demand,
                         f'cumulative_demand mismatch: {pyMaxInputGraph.cumulative_demand} != {pyMaxConverted.cumulative_demand}')

        self.assertEqual(pyMaxInputGraph.neutral_sinks, pyMaxConverted.neutral_sinks,
                         f'neutral_sinks mismatch: {pyMaxInputGraph.neutral_sinks} != {pyMaxConverted.neutral_sinks}')

        self.assertEqual(pyMaxInputGraph.fake_nodes, pyMaxConverted.fake_nodes,
                         f'fake_nodes mismatch: {pyMaxInputGraph.fake_nodes} != {pyMaxConverted.fake_nodes}')

        self.assertEqual(pyMaxInputGraph.demand_lookup, pyMaxConverted.demand_lookup,
                         f'demand_lookup mismatch:\n  direct={pyMaxInputGraph.demand_lookup}\n  converted={pyMaxConverted.demand_lookup}')

        self.assertEqual(pyMaxInputGraph.node_id_mapping, pyMaxConverted.node_id_mapping,
                         f'node_id_mapping mismatch:\n  direct={pyMaxInputGraph.node_id_mapping}\n  converted={pyMaxConverted.node_id_mapping}')

        self.assertEqual(pyMaxInputGraph.reverse_node_mapping, pyMaxConverted.reverse_node_mapping,
                         f'reverse_node_mapping mismatch:\n  direct={pyMaxInputGraph.reverse_node_mapping}\n  converted={pyMaxConverted.reverse_node_mapping}')

        # Edges are order-independent — compare as sorted sets of tuples
        self.assertEqual(sorted(pyMaxInputGraph.edges), sorted(pyMaxConverted.edges),
                         f'edges mismatch:\n  direct={sorted(pyMaxInputGraph.edges)}\n  converted={sorted(pyMaxConverted.edges)}')

        # Terminal edges are order-independent — compare as sorted sets of tuples
        self.assertEqual(sorted(pyMaxInputGraph.terminal_edges), sorted(pyMaxConverted.terminal_edges),
                         f'terminal_edges mismatch:\n  direct={sorted(pyMaxInputGraph.terminal_edges)}\n  converted={sorted(pyMaxConverted.terminal_edges)}')


    # ------------------------------------------------------------------
    # No target-crossable cases
    # ------------------------------------------------------------------

    def test_target_crossable__simple_linear_map__no_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__large_friendly_island_on_border__not_crossable_due_to_size__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__friendly_island_with_equal_border_tiles__not_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    # ------------------------------------------------------------------
    # Target-crossable cases
    # ------------------------------------------------------------------

    def test_target_crossable__small_encircled_friendly_outpost__is_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__small_outpost_excluded_from_border_pair_seeding__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__outpost_not_crossable_when_no_enemy_flow_in__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__two_outposts__both_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__two_outposts__neither_appear_as_border_pair_seeds__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__outpost_threshold_boundary__exactly_at_threshold_not_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__outpost_one_below_threshold__is_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__multi_tile_outpost_fully_surrounded__is_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__multi_tile_outpost_fully_surrounded__not_crossable_at_threshold__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)

    def test_target_crossable__three_tile_chain_outpost__all_crossable__should_be_equivalent(self):
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

        self.assertNxAndPyMaxEquivalent(map, general, enemyGeneral)