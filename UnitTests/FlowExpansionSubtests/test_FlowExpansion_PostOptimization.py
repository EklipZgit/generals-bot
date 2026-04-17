import logbook

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms import IterativeExpansion
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, FlowGraphMethod
from BehaviorAlgorithms.FlowExpansion import FlowExpansionPlanOptionCollection
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot

method = FlowGraphMethod.MinCostFlow

class FlowExpansionPostOptimizationTests(TestBase):
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

    def test_post_optimization__basic_two_island_map(self):
        """Test post-optimization and plan materialization on a simple two-island map"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        # Import and test the V2 expander
        from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player
        flowExpanderV2.enemyGeneral = enemyGeneral

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )
        flowExpanderV2._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        # Test grouped knapsack optimization
        turn_budget = 10
        solution = flowExpanderV2._solve_grouped_knapsack(lookup_tables, turn_budget)

        # Test post-optimization (Phase 6)
        optimized_solution = flowExpanderV2._post_optimize_locally(
            solution, lookup_tables, turn_budget
        )

        self.assertIsNotNone(optimized_solution, 'Should produce an optimized solution')
        self.assertIsInstance(optimized_solution, dict, 'Optimized solution should be a dict keyed by border pair')
        self.assertGreater(len(optimized_solution), 0, 'Optimized solution should contain at least one selected border pair')

        # Test plan materialization (Phase 5)
        plans = flowExpanderV2._materialize_plans(optimized_solution, lookup_tables)

        self.assertIsInstance(plans, list, 'Should return a list of plans')

        # For this simple case, we expect at least one plan
        self.assertGreater(len(plans), 0, 'Should materialize at least one plan')

        # Verify the plan structure
        first_plan = plans[0]
        self.assertIsNotNone(first_plan, 'Plan should not be None')
        # Note: The exact structure will depend on GatherCapturePlan implementation
        # For now, we just verify we get something reasonable back

        # Test the full integration through the main interface
        result = flowExpanderV2.get_expansion_options(
            builder, general.player, enemyGeneral.player,
            turns=turn_budget, boardAnalysis=None, territoryMap=None, negativeTiles=None
        )

        self.assertIsInstance(result, FlowExpansionPlanOptionCollection, 'Should return FlowExpansionPlanOptionCollection')
        self.assertIsInstance(result.flow_plans, list, 'Should contain a list of flow plans')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a3   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(2, len(opts), 'taking the neut, and taking the neut + enemy 1')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(2, longestOpt.length, 'must make 2 moves')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(2, len(opts), 'taking the neut, and taking the neut + enemy 1')
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(2, len(opts), 'taking the neut, and taking the neut + enemy 1')
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(2, len(opts), 'Shorter and longer options')
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(2, len(opts), 'Shorter and longer options')
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        self.assertEqual(2, len(opts), 'shorter and longer option')
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
        builder = TileIslandBuilder(map)

        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        # if debugMode:
        #     self.render_flow_expansion_debug(flowExpander, flowResult, renderAll=False)

        self.assertEqual(3, len(opts), 'taking the neut, and taking the neut + enemy 1, and + enemy 2')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(4, longestOpt.length, 'must make 4 moves to pull the ')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2 + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(5, longestOpt.gathered_army, 'gathered a 2 and a 5')
