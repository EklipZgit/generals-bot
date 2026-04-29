import time
import typing
from collections import deque

import logbook

import Gather
import SearchUtils
from Algorithms import TileIslandBuilder
from Algorithms.TileIslandBuilder import IslandBuildMode
from BehaviorAlgorithms import IterativeExpansion
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, IslandFlowNode, FlowGraphMethod
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot

method = FlowGraphMethod.OrToolsSimpleMinCost

class FlowExpansionBorderStreamPreprocessTests(TestBase):
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

    def test_border_stream_preprocessing__basic_two_island_map(self):
        """Test basic border stream preprocessing on a simple two-island map"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Import and test the V2 expander
        from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player
        flowExpanderV2.enemyGeneral = enemyGeneral

        # Test the preprocessing components
        flowExpanderV2._ensure_flow_graph_exists(builder)
        self.assertIsNotNone(flowExpanderV2.flow_graph, 'Flow graph should be built')

        # Test target-crossable detection
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        self.assertEqual(0, len(target_crossable), 'No islands should be target-crossable in this simple map')

        # Test border pair enumeration
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )
        self.assertEqual(1, len(border_pairs), 'Should find exactly one border pair')

        # Verify the border pair is correct.
        # The friendly border island is the a3 tile at (1,0) — the tile that directly touches the enemy,
        # not the general at (0,0). The target island is b1 at (2,0), which contains the enemy general.
        border_pair = border_pairs[0]
        friendly_border_tile = map.GetTile(1, 0)  # a3 — the friendly tile adjacent to enemy
        target_border_tile = map.GetTile(2, 0)    # b1 — the enemy tile adjacent to friendly (contains bG1 island)
        friendly_island = builder.tile_island_lookup.raw[friendly_border_tile.tile_index]
        target_island = builder.tile_island_lookup.raw[target_border_tile.tile_index]
        self.assertEqual(friendly_island.unique_id, border_pair.friendly_island_id)
        self.assertEqual(target_island.unique_id, border_pair.target_island_id)


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a3   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'only one option')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(2, longestOpt.length, 'should be 5 turns to pull 3x 3s and capture 3x 1s')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(2, longestOpt.gathered_army, 'gathered a 3')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a4        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        if debugMode:
            self.render_flow_expansion_debug(flowExpander, flowResult, renderAll=False)

        self.assertEqual(1, len(opts), 'taking the neut, and taking the neut + enemy 1')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(2, longestOpt.length, 'must make 2 moves')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        # this shit is wrong
        self.assertEqual(3, longestOpt.gathered_army, 'gathered a 4')


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__excess_source(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a4   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'Only one option')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(1, longestOpt.length, 'only one move')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(3, longestOpt.gathered_army, 'gathered a 4')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly__excess_source(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a4   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'only one option')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(2, longestOpt.length, 'only valid should be pulling the 4 through the friendly 1')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(3, longestOpt.gathered_army, 'gathered a 4')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral__excess_source(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a5        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'taking the neut, and taking the neut + enemy 1')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(2, longestOpt.length, 'must make 2 moves')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(4, longestOpt.gathered_army, 'gathered a 5')


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__need_cumulative_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |
aG2  a2   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'Only one option')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(2, longestOpt.length, 'two 2s needed')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(2, longestOpt.gathered_army, 'gathered two 2s')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly__need_cumulative_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG2  a2   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'only one option')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(3, longestOpt.length, 'only valid should be pulling the two 2s through the friendly 1')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(2, longestOpt.gathered_army, 'gathered two 2s')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral__need_cumulative_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG2  a3        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'taking the neut, and taking the neut + enemy 1')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(3, longestOpt.length, 'must make 3 moves to pull the ')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(3, longestOpt.gathered_army, 'gathered a 2 and a 3')


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__multi_enemy_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG3  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'Shorter and longer options')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(3, longestOpt.length, 'two 3s needed, two caps')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(4, longestOpt.gathered_army, 'gathered two 3s')


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__multi_enemy_tiles__differing_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG3  a5   b1   bG3
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'Shorter and longer options')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(3, longestOpt.length, 'two 3s needed, two caps')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(6, longestOpt.gathered_army, 'gathered 3 and 5')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly__multi_enemy_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG3  a3   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(1, len(opts), 'shorter and longer option')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(4, longestOpt.length, 'only valid should be pulling the two 2s through the friendly 1')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(4, longestOpt.gathered_army, 'gathered two 2s')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral__multi_enemy_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |
aG2  a5   b1        bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpanderV2(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        # if debugMode:
        #     self.render_flow_expansion_debug(flowExpander, flowResult, renderAll=False)

        self.assertEqual(1, len(opts), 'taking the neut, and taking the neut + enemy 1, and + enemy 2')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(4, longestOpt.length, 'must make 4 moves to pull the ')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2 + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(5, longestOpt.gathered_army, 'gathered a 2 and a 5')

    # ------------------------------------------------------------------
    # Connectivity validation tests for stream building
    # ------------------------------------------------------------------

    def _assert_stream_islands_spatially_connected(
        self,
        stream: typing.List,
        set_name: str,
        test_context: str
    ):
        """
        Assert that islands in a stream form a spatially connected sequence.
        Each island in the stream should be adjacent to at least one previous island.
        """
        if not stream:
            return

        # Build a set of all tiles we've seen so far as we iterate
        accumulated_tiles: typing.Set[Tile] = set()

        for i, flow_node in enumerate(stream):
            island = flow_node.island
            island_tiles = set(island.tile_set)

            if i == 0:
                # First island - just add it
                accumulated_tiles.update(island_tiles)
                continue

            # Check if this island is adjacent to any previously accumulated tiles
            is_adjacent = False
            for tile in island_tiles:
                for neighbor in tile.movable:
                    if neighbor in accumulated_tiles:
                        is_adjacent = True
                        break
                if is_adjacent:
                    break

            if not is_adjacent:
                # Find the closest distance for debugging
                min_dist = float('inf')
                closest_pair = None
                for tile in island_tiles:
                    for acc_tile in accumulated_tiles:
                        dist = abs(tile.x - acc_tile.x) + abs(tile.y - acc_tile.y)
                        if dist < min_dist:
                            min_dist = dist
                            closest_pair = (tile, acc_tile)

                island_center = self._get_island_center(island)
                accumulated_str = ', '.join([f"({t.x},{t.y})" for t in sorted(accumulated_tiles, key=lambda t: (t.x, t.y))[:10]])
                island_str = ', '.join([f"({t.x},{t.y})" for t in sorted(island_tiles, key=lambda t: (t.x, t.y))])

                error_msg = (
                    f"{set_name} stream ISLAND DISCONNECT at index {i} in {test_context}!\n"
                    f"Island {island.unique_id} (center ~{island_center}) is NOT adjacent to any previous island.\n"
                    f"Closest distance to accumulated tiles: {min_dist}\n"
                    f"Closest pair: {closest_pair[0].x},{closest_pair[0].y} -> {closest_pair[1].x},{closest_pair[1].y}\n"
                    f"Current island tiles ({len(island_tiles)}): {island_str}\n"
                    f"Accumulated tiles (first 10): {accumulated_str}..."
                )
                self.fail(error_msg)

            # Add this island's tiles to accumulated set
            accumulated_tiles.update(island_tiles)

    def _get_island_center(self, island) -> typing.Tuple[int, int]:
        """Get approximate center of an island for debugging."""
        if not island.tile_set:
            return (-1, -1)
        avg_x = sum(t.x for t in island.tile_set) // len(island.tile_set)
        avg_y = sum(t.y for t in island.tile_set) // len(island.tile_set)
        return (avg_x, avg_y)

    def test_border_stream__connectivity__downstream_stream_spatially_connected(self):
        """
        Regression test: Verify that _build_downstream_stream produces spatially connected
        island sequences.

        The downstream stream should only include islands that are adjacent to previously
        included islands, forming a contiguous path from the border outward.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  M    M    a3   a4   a4   a8   a2   a6   a1   a1   a1   a1   a1   a1   a1   a1   a1
a1   M    M    a3   a3   a3   a3   a2   a1   a2   b2   b2   b2   b6   b2   b2   b2   a1
a2   a3   a4   a2   a3   a3   a8   a2   a2   a2   b2   a2   b2   b5   b2   b2   b3   a1
a3   a3   a3   a3   a3   a3   a3   a3   a3   a2   b2   a2   b2   b4   b4   b4   b3   a1
a3   a3   a2   a3   a4   a3   a4   a3   a3   a2   b2   a2   a2   a2   a2   a2   b2   a1
a3   a3   a3   a5   a3   a2   a2   a3   a2   a1   a1   a1   a1   b2   b2   b2   b2   a1
a3   a3   a3   a3   a3   a3   a3   a3   a2   a4   a4   a4   a4   b4   b3   b3   b3   a1
a4   a4   a2   a4   a4   a3   a3   a4   a2   a4   a3   a3   a3   b3   b2   b2   b2   b2
a4   a2   a3   a3   a4   a3   a2   a2   M    M    a2   b2   b2   b2   b2   b2   b2   b2
a2   a3   a3   a2   a3   a2   a3   a2   M    b1   a2   b2   M    M    b2   b2   b2   b2
a2   a3   a3   a3   a3   a2   a2   a3   M    b1   a2   b2   b2   M    b2   b2   b2   b2
a2   a3   a2   a3   a2   a2   M    M    M    b2   b2   b2   b2   b2   b2   b2   b2   b2
a4   a4   a4   a4   a3   a3   M    a2   M    M    b2   b2   b2   b2   b2   b2   b2   b2
a3   a3   a4   a3   a3   a2   M    a2   a2   b2   b2   b2   b2   b2   b2   b1   b1   b2
a3   a3   a3   a3   a3   a2   M    a2   a2   b2   b2   b2   b1   b1   b1   b1   b1   b1
a3   a3   a3   a2   a3   a3   M    a2   a2   b2   b2   b2   b2   b1   b1   b1   b1   b1
a2   a3   a2   a2   a2   a2   M    M    M    b2   b2   b2   b2   b2   b2   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
        """

        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        self.assertGreater(len(border_pairs), 0, 'Should find at least one border pair')

        # Validate connectivity for each border pair's downstream stream
        for border_pair in border_pairs:
            stream_data = flowExpanderV2._build_border_pair_stream_data(
                border_pair, flowExpanderV2.flow_graph, target_crossable
            )

            if not stream_data:
                continue

            target_stream = stream_data.target_stream

            # The target stream should be spatially connected
            self._assert_stream_islands_spatially_connected(
                target_stream,
                "Target (downstream)",
                f"border_pair {border_pair.friendly_island_id}->{border_pair.target_island_id}"
            )

        if debugMode:
            logbook.info(f"Validated spatial connectivity for {len(border_pairs)} border pairs")
