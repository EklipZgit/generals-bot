import time
import typing
from collections import deque

import logbook

import Gather
import SearchUtils
from Algorithms import TileIslandBuilder
from Algorithms.TileIslandBuilder import IslandBuildMode
from BehaviorAlgorithms import IterativeExpansion
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, IslandFlowNode, FlowGraphMethod
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot

method = FlowGraphMethod.MinCostFlow

class FlowExpansionUnitTests(TestBase):
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


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move(self):
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
        self.assertEqual(2, longestOpt.gathered_army, 'gathered a 3')


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
        #     self.render_flow_expansion_debug(builder, flowExpander, flowResult, renderAll=False)

        self.assertEqual(3, len(opts), 'taking the neut, and taking the neut + enemy 1, and + enemy 2')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(4, longestOpt.length, 'must make 4 moves to pull the ')
        self.assertEqual(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2 + 1, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(5, longestOpt.gathered_army, 'gathered a 2 and a 5')


    def test_build_flow_expand_plan__should_produce_valid_only(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
a3   a2   a1   a1
aG1  M    a1   b1
M    M         b1
          M    bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)

        start = time.perf_counter()
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans

        duration = time.perf_counter() - start

    def test_build_flow_expand_plan__should_be_fast(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize, maxDuration in [
            ('large', 0.050),
            ('small', 0.010),
        ]:
            with self.subTest(mapSize=mapSize):
                if mapSize == 'large':
                    mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                else:
                    mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                if debugMode:
                    self.render_map(map)

                self.begin_capturing_logging()
                builder = TileIslandBuilder(map)

                start = time.perf_counter()
                builder.recalculate_tile_islands(enemyGeneral)
                flowExpander = ArmyFlowExpander(map)
                flowExpander.method = method
                flowExpander.use_debug_asserts = False
                flowExpander.log_debug = False
                flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
                opts = flowResult.flow_plans

                duration = time.perf_counter() - start
                self.assertLess(duration, maxDuration, 'should not take ages to build flow plan')

    def test_builds_flow_plan_from_single_segment__exact_cap(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a3   a3
a20                 b1
                    b1
                    b1
a2
                              bG1
|    |    |    |    |
        """

        #optimal is taking the 3x 3's above and using them to capture the 3x 1's, which is 5 moves for 3 caps.


        for turns in [5, 50]:
            with self.subTest(limitTurns=turns):
                map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

                self.begin_capturing_logging()
                builder = TileIslandBuilder(map)
                # builder.break_apart_neutral_islands = True
                builder.recalculate_tile_islands(enemyGeneral)
                flowExpander = ArmyFlowExpander(map)
                flowExpander.method = method
                flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=turns, boardAnalysis=None, territoryMap=None, negativeTiles=None)
                opts = flowResult.flow_plans
                # self.assertEqual(3, len(opts), 'should have an option for each length gather/cap, 1, 3, 5 lengths.')
                longestOpt = self.get_longest_flow_expansion_option(opts)
                # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
                # opt = opts[0]
                self.assertEqual(5, longestOpt.length, 'should be 5 turns to pull 3x 3s and capture 3x 1s')
                self.assertEqual(round(3 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 2), round(longestOpt.econValue, 2), 'should be 6 econ roughly to capture 3 enemy tiles.')
                self.assertEqual(6, longestOpt.gathered_army, 'should have NO army remaining')

    def test_builds_flow_plan_from_single_segment__exact_cap__only_option(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1            M    M    M    M
               N40  a3   a3   a3
a1             M    b1   M    M
               M    b1   M
               M    b1   M
a1                  N40
                              bG1
|    |    |    |    |
        """

        #optimal is taking the 3x 3's above and using them to capture the 3x 1's, which is 5 moves for 3 caps.

        for turns in [5, 50]:
            with self.subTest(limitTurns=turns):
                map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

                self.begin_capturing_logging()
                builder = TileIslandBuilder(map)
                # builder.break_apart_neutral_islands = True
                builder.recalculate_tile_islands(enemyGeneral)
                flowExpander = ArmyFlowExpander(map)
                flowExpander.method = method
                flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=turns, boardAnalysis=None, territoryMap=None, negativeTiles=None)
                opts = flowResult.flow_plans
                self.assertEqual(3, len(opts), 'should have an option for each length gather/cap, 1, 3, 5 lengths.')
                longestOpt = self.get_longest_flow_expansion_option(opts)
                # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
                # opt = opts[0]
                self.assertEqual(5, longestOpt.length, 'should be 5 turns to pull 3x 3s and capture 3x 1s')
                self.assertEqual(3 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, longestOpt.econValue, 'should be 6 econ roughly to capture 3 enemy tiles.')
                self.assertEqual(6, longestOpt.gathered_army, 'should have NO army remaining')

    def test_builds_flow_plan_from_single_segment__extra_army(self):
        # TODO recognize the 1/econ/t expansion into neutral as part of this? or nah?
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a3   a5
a20                 b1
                    b1
                    b1
a2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans
        self.assertEqual(3, len(opts), 'one for each length plan opt, 1 3 and 5')
        shortOpt = SearchUtils.where(opts, lambda o: o.length == 3)[0]
        self.assertEqual(3, shortOpt.length)
        self.assertEqual(4, round(shortOpt.econValue))
        self.assertEqual(0, round(shortOpt.armyRemaining))
        longOpt = SearchUtils.where(opts, lambda o: o.length == 5)[0]
        self.assertEqual(5, longOpt.length, 'should be 5 turns to pull 2x 3s and a 5 and capture 3x 1s')
        self.assertEqual(6, round(longOpt.econValue), 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(2, round(longOpt.armyRemaining), 'should have 2 army remaining now, due to the 5')

    def test_builds_flow_plan_from_single_segment__not_enough_army_to_fully_cap(self):
        # TODO this system should optimize which tiles to leave behind.
        #  The 2 can capture another adjacent, so it should NOT be gathered as part of this and should capture a neutral instead.
        #  Maybe the plan includes that?
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a3   a2
a20                 b1
                    b1
                    b1
a2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans
        self.assertEqual(2, len(opts), 'pulling the extra 2 should not result in an option since it does not result in another capture')
        opt = self.get_longest_flow_expansion_option(opts)
        self.assertEqual(4, round(opt.econValue), 'should be 4 econ roughly to capture 2 enemy tiles.')
        self.assertEqual(3, opt.length, 'should be 3 turns to pull 2x 3s. Should not use the 2.')
        self.assertEqual(0, opt.armyRemaining)

    def test_builds_flow_plan_from_single_segment__not_enough_army_to_fully_cap__pull_second_friendly_island(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a2   a2
a20                 b1
                    b1
                    b1
a2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans
        self.assertEqual(2, len(opts), 'should have 3 cap, and 3 + 2x2s cap options')
        longest = sorted(opts, key=lambda o: 0-o.length)[0]
        self.assertEqual(4, round(longest.econValue), 'should be 4 econ roughly to capture 2 enemy tiles.')
        self.assertEqual(4, longest.length, 'should be 5 turns to pull 2x 2s and 1x 3.')
        self.assertEqual(0, longest.armyRemaining)

    def test_builds_flow_plan_from_single_segment__not_enough_army_to_fully_cap__pull_third_friendly_island__leftover(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a2   a3
a20                 b1
                    b1
                    b1
a2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans
        self.assertEqual(2, len(opts), 'should have just 3 opt, and 3 + 2 + 3opts.')
        longest = self.get_longest_flow_expansion_option(opts)
        self.assertEqual(4, round(longest.econValue), 'should be 4 econ roughly to capture 2 enemy tiles.')
        self.assertEqual(4, longest.length, 'should be 4 turns to pull 2x 3s and 1x 2. (should assume pull of ally tiles in worst case order)')
        self.assertEqual(1, longest.armyRemaining)

    def test_builds_flow_plan_from_single_segment__not_enough_army_to_fully_cap__pull_fourth_friendly_island(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a2   a3
a20                 b1        a2
                    b1
                    b1
a2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans
        self.assertEqual(3, len(opts), 'should have just 3 opt, and 3 + 2 + 3opts.')
        longest = self.get_longest_flow_expansion_option(opts)
        self.assertEqual(6, round(longest.econValue), 'should be 4 econ roughly to capture 2 enemy tiles.')
        self.assertEqual(6, longest.length, 'should be 5 turns to pull 2x 3s and 2x 2. (should assume pull of ally tiles in worst case order)')
        self.assertEqual(0, longest.armyRemaining)

    def test_builds_flow_plan_from_single_segment__hit_multiple_target_islands(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
aG1
                    a3   a2   a3
a20                 b1
                    b1
                    b0
a2                  b1
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.desired_tile_island_size = 0.3
        builder.recalculate_tile_islands(enemyGeneral)
        self.assertEqual(len(builder.tile_islands_by_player[enemyGeneral.player]), 5)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        opts = flowResult.flow_plans
        self.assertEqual(3, len(opts), 'should have 3 options technically although dunno why youd not cap the zero tile')
        longest = self.get_longest_flow_expansion_option(opts)
        self.assertEqual(6, round(longest.econValue), 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(5, longest.length, 'should be 5 turns to pull everything and capture the 0 too')
        self.assertEqual(0, longest.armyRemaining)

    def test_builds_flow_plan__should_recognize_gather_into_top_path_is_best(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        flowExpander.method = method
        flowResult = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        if debugMode:
            self.render_flow_expansion_debug(builder, flowExpander, flowResult, renderAll=False)
        opts = flowResult.flow_plans
        self.assertGreater(len(opts), 0)
        sortedOpts = sorted(opts, key=lambda o: o.econValue / o.length, reverse=True)
        maxOpt = sortedOpts[0]
        maxVt = maxOpt.econValue / maxOpt.length
        self.assertGreater(maxVt, 1.6, 'at least SOME plan should have had a higher value-per-turn than 1.6...?')
        self.assertLess(maxVt, 2.3, 'this method of capture calculation should not be possible to acquire much more than 2 econ value per turn even with priomatrix bonuses')
        # self.assertEqual(5, maxOpt.length, 'should be 5 turns to pull 3x 2s and capture 3x 1s')
        # self.assertEqual(6, round(maxOpt.econValue), 'should be 6 econ roughly to capture 3 enemy tiles.')

    def test_should_recognize_gather_into_top_path_is_best(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=False)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=debugMode, method=method)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 1.5, 'should find a plan with pretty high value per turn')

    def test_should_recognize_gather_into_top_path_is_best__with_time_cutoff(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(10):
            mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=False)

            map.GetTile(7, 12).isMountain = True
            map.GetTile(7, 10).isMountain = True
            map.update_reachable()
            # if debugMode:
            #     self.render_map(map)

            self.enable_search_time_limits_and_disable_debug_asserts()
            self.begin_capturing_logging()

            timeLimit = 10

            opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=50, debugMode=debugMode, renderThresh=700, tileIslandSize=4, timeLimit=timeLimit, shouldRender=False, method=method)

            maxVt = sorted(opts, key=lambda o: o.econValue / o.length, reverse=True)[0]

            self.assertNotEqual(0, len(opts))
            try:
                self.assertGreater(maxVt.econValue / maxVt.length, 1.5, f'best vt low: {maxVt}')
            except:
                if debugMode:
                    self.render_gather_capture_plan(map, maxVt, general.player, enemyGeneral.player, f'best vt low: {maxVt}')
                raise

            longestOpt = next(opt for opt in sorted(opts, key=lambda o: o.length, reverse=True))
            try:
                self.assertGreater(longestOpt.length, 34, f'longest plan too short. {longestOpt}')
            except:
                if debugMode:
                    self.render_gather_capture_plan(map, longestOpt, general.player, enemyGeneral.player, f'longest plan too short. {longestOpt}')
                raise

            bestLongerOpt = next(opt for opt in sorted(opts, key=lambda o: (o.length > 15, o.econValue / o.length), reverse=True))
            try:
                self.assertGreater(bestLongerOpt.econValue / bestLongerOpt.length, 0.9, f'longerOpt vt low: {bestLongerOpt}')
            except:
                if debugMode:
                    self.render_gather_capture_plan(map, bestLongerOpt, general.player, enemyGeneral.player, f'longerOpt vt low: {bestLongerOpt}')
                raise

    def test_should_not_produce_invalid_plan__enemy_cluster_crossing_neutral_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=False)

        map.GetTile(12, 8).isMountain = True
        map.GetTile(12, 9).isMountain = True
        map.GetTile(12, 10).isMountain = True
        map.GetTile(12, 11).isMountain = True
        map.GetTile(10, 11).isMountain = True
        map.GetTile(10, 12).isMountain = True
        map.GetTile(10, 13).isMountain = True
        map.GetTile(5, 1).isMountain = True
        map.GetTile(8, 10).isMountain = True
        map.GetTile(8, 11).isMountain = True
        map.GetTile(8, 12).isMountain = True
        map.GetTile(3, 3).isMountain = True
        map.GetTile(2, 1).isMountain = True
        map.GetTile(2, 2).isMountain = True
        map.GetTile(5, 0).isMountain = True
        map.GetTile(14, 1).isMountain = True
        map.GetTile(13, 0).isMountain = True
        map.GetTile(14, 4).isMountain = True
        map.GetTile(14, 8).isMountain = True
        map.GetTile(15, 10).isMountain = True
        map.GetTile(15, 11).isMountain = True
        map.GetTile(14, 12).isMountain = True
        map.GetTile(11, 8).isMountain = True
        for i in range(12, 16):
            map.GetTile(7, i).isMountain = True
        for i in range(6, 11):
            map.GetTile(10, i).isMountain = True
        for i in range(7, 10):
            map.GetTile(i, 15).isMountain = True

        map.update_reachable()

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5, method=method)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 0.99, 'should find a plan with pretty high value per turn with one-move-cap')

        optWithCaps = SearchUtils.where(opts, lambda o: SearchUtils.any_where(o.tileSet, lambda t: t.player == enemyGeneral.player))
        self.assertGreater(len(optWithCaps), 0)
        self.assertGreater(optWithCaps[0].econValue, 0.8)

    def test_should_not_produce_invalid_plan__neutral_cap(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=False)

        map.GetTile(12, 8).isMountain = True
        map.GetTile(12, 9).isMountain = True
        map.GetTile(12, 10).isMountain = True
        map.GetTile(12, 11).isMountain = True
        map.GetTile(10, 11).isMountain = True
        map.GetTile(10, 12).isMountain = True
        map.GetTile(10, 13).isMountain = True
        map.GetTile(5, 1).isMountain = True
        map.GetTile(8, 10).isMountain = True
        map.GetTile(8, 11).isMountain = True
        map.GetTile(8, 12).isMountain = True
        map.GetTile(3, 3).isMountain = True
        map.GetTile(2, 1).isMountain = True
        map.GetTile(2, 2).isMountain = True
        map.GetTile(5, 0).isMountain = True
        # map.GetTile(14, 1).isMountain = True
        # map.GetTile(13, 0).isMountain = True
        # map.GetTile(14, 4).isMountain = True
        map.GetTile(14, 8).isMountain = True
        map.GetTile(15, 10).isMountain = True
        map.GetTile(15, 11).isMountain = True
        map.GetTile(14, 12).isMountain = True
        map.GetTile(11, 8).isMountain = True
        map.GetTile(13, 10).isMountain = True
        map.GetTile(13, 11).isMountain = True
        map.GetTile(13, 1).isMountain = True
        map.GetTile(15, 14).isMountain = True
        map.GetTile(13, 16).isMountain = True
        map.GetTile(11, 16).isMountain = True
        map.GetTile(10, 16).isMountain = True
        map.GetTile(8, 17).isMountain = True
        for i in range(12, 16):
            map.GetTile(7, i).isMountain = True
        for i in range(6, 11):
            map.GetTile(10, i).isMountain = True
        for i in range(7, 10):
            map.GetTile(i, 15).isMountain = True

        map.update_reachable()

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5, method=method)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 0.99, 'should find a plan with pretty high value per turn')

    def test_should_have_enemy_general_backpressure(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for (extraArmy, expectEnFlow) in [
            (0, 100),
            (50, 50),
            (200, -50), # we overflow the enemy general and need excess sink. I think this isn't -100 because after overflowing enemy land we start filling neutral tiles we were ignoring...? or something? idk. This was the no-neut though
        ]:
            with self.subTest(extraArmy=extraArmy, expectEnFlow=expectEnFlow):
                mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

                map.GetTile(12, 8).isMountain = True
                map.GetTile(12, 9).isMountain = True
                map.GetTile(12, 10).isMountain = True
                map.GetTile(12, 11).isMountain = True
                map.GetTile(10, 11).isMountain = True
                map.GetTile(10, 12).isMountain = True
                map.GetTile(10, 13).isMountain = True
                # map.GetTile(5, 1).isMountain = True # leave this wall open
                map.GetTile(8, 10).isMountain = True
                map.GetTile(8, 11).isMountain = True
                map.GetTile(8, 12).isMountain = True
                map.GetTile(3, 3).isMountain = True
                map.GetTile(2, 1).isMountain = True
                map.GetTile(2, 2).isMountain = True
                map.GetTile(5, 0).isMountain = True
                # map.GetTile(14, 1).isMountain = True
                # map.GetTile(13, 0).isMountain = True
                # map.GetTile(14, 4).isMountain = True
                map.GetTile(14, 8).isMountain = True
                map.GetTile(15, 10).isMountain = True
                map.GetTile(15, 11).isMountain = True
                map.GetTile(14, 12).isMountain = True
                map.GetTile(11, 8).isMountain = True
                map.GetTile(13, 10).isMountain = True
                map.GetTile(13, 11).isMountain = True
                map.GetTile(13, 1).isMountain = True
                map.GetTile(15, 14).isMountain = True
                map.GetTile(13, 16).isMountain = True
                map.GetTile(11, 16).isMountain = True
                map.GetTile(10, 16).isMountain = True
                map.GetTile(8, 17).isMountain = True
                for i in range(12, 16):
                    map.GetTile(7, i).isMountain = True
                for i in range(6, 11):
                    map.GetTile(10, i).isMountain = True
                for i in range(7, 10):
                    map.GetTile(i, 15).isMountain = True
                general.army += extraArmy

                map.update_reachable()

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                expander, opts = self.run_army_flow_expansion_and_get_expander(map, general, enemyGeneral, turns=400, debugMode=debugMode, renderThresh=700, tileIslandSize=5, method=method)
                flowGraph = expander.flow_graph
                tgGenFlowNode = flowGraph.flow_node_lookup_by_tile_no_neut.raw[enemyGeneral.tile_index]
                flowedFromEnGen = sum(i.edge_army for i in tgGenFlowNode.flow_to if i.target_flow_node is not None)
                actualFlowSum = flowedFromEnGen - tgGenFlowNode.army_flow_received
                self.assertGreater(actualFlowSum, expectEnFlow, f'flowedFromEnGen {flowedFromEnGen}, tgGenFlowNode.army_flow_received {tgGenFlowNode.army_flow_received}, not enough to capture all en land so there should be backpressure from enemy general to its own land.')
                self.assertLess(actualFlowSum, expectEnFlow + 50, f'flowedFromEnGen {flowedFromEnGen}, tgGenFlowNode.army_flow_received {tgGenFlowNode.army_flow_received}, not enough to capture all en land so there should be backpressure from enemy general to its own land.')
                self.assertNotEqual(0, len(opts))
                self.assertGreater(opts[0].econValue / opts[0].length, 0.99, 'should find a plan with pretty high value per turn')

    def test_should_not_produce_invalid_enemy_captures(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for (turns, expectedMin) in [
            (2, 2.0),
            (3, 2.0),
            (5, 0.85),
            (40, 1.0),
            (60, 1.1),
        ]:
            with self.subTest(turns=turns, expectedMin=expectedMin):
                mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

                general.army += 50

                map.GetTile(12, 8).isMountain = True
                map.GetTile(12, 9).isMountain = True
                map.GetTile(12, 10).isMountain = True
                map.GetTile(12, 11).isMountain = True
                # map.GetTile(10, 11).isMountain = True
                map.GetTile(10, 12).isMountain = True
                map.GetTile(10, 13).isMountain = True
                map.GetTile(5, 1).isMountain = True
                # map.GetTile(8, 10).isMountain = True
                # map.GetTile(8, 11).isMountain = True
                # map.GetTile(8, 12).isMountain = True
                map.GetTile(3, 3).isMountain = True
                map.GetTile(2, 1).isMountain = True
                map.GetTile(2, 2).isMountain = True
                map.GetTile(5, 0).isMountain = True
                # map.GetTile(14, 1).isMountain = True
                # map.GetTile(13, 0).isMountain = True
                map.GetTile(14, 4).isMountain = True
                map.GetTile(14, 8).isMountain = True
                map.GetTile(15, 10).isMountain = True
                map.GetTile(15, 11).isMountain = True
                map.GetTile(14, 12).isMountain = True
                map.GetTile(11, 8).isMountain = True
                map.GetTile(13, 10).isMountain = True
                map.GetTile(13, 11).isMountain = True
                map.GetTile(13, 1).isMountain = True
                map.GetTile(15, 14).isMountain = True
                map.GetTile(13, 16).isMountain = True
                map.GetTile(11, 16).isMountain = True
                map.GetTile(10, 16).isMountain = True
                map.GetTile(10, 12).isMountain = True
                map.GetTile(8, 17).isMountain = True
                # map.GetTile(7, 14).isMountain = True
                # map.GetTile(9, 10).isMountain = True
                map.GetTile(10, 10).isMountain = True
                map.GetTile(6, 12).isMountain = True
                map.GetTile(5, 16).isMountain = True
                map.GetTile(5, 13).isMountain = True
                # map.GetTile(3, 15).isMountain = True
                # map.GetTile(2, 14).isMountain = True
                # map.GetTile(3, 13).isMountain = True
                map.GetTile(7, 10).isMountain = True
                # for i in range(12, 16):
                #     map.GetTile(7, i).isMountain = True
                for i in range(6, 11):
                    map.GetTile(10, i).isMountain = True
                # for i in range(6, 10):
                #     map.GetTile(i, 15).isMountain = True

                map.update_reachable()

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=1, method=method, shouldRender=True)
                self.assertNotEqual(0, len(opts))
                self.assertGreater(opts[0].econValue / opts[0].length, expectedMin, 'should find a plan with pretty high value per turn')


    def test_should_gather_through_friendly_or_enemy_island_flows(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=False)

        map.GetTile(12, 11).isMountain = True
        map.GetTile(10, 12).isMountain = True
        map.GetTile(10, 13).isMountain = True
        map.GetTile(7, 13).isMountain = True
        map.GetTile(7, 14).isMountain = True
        map.GetTile(5, 0).isMountain = True
        map.GetTile(14, 4).isMountain = True
        map.GetTile(14, 8).isMountain = True
        map.GetTile(15, 10).isMountain = True
        map.GetTile(15, 11).isMountain = True
        map.GetTile(14, 12).isMountain = True
        map.GetTile(11, 8).isMountain = True
        map.GetTile(13, 10).isMountain = True
        map.GetTile(13, 11).isMountain = True
        map.GetTile(13, 1).isMountain = True
        map.GetTile(15, 14).isMountain = True
        map.GetTile(13, 16).isMountain = True
        map.GetTile(11, 16).isMountain = True
        map.GetTile(10, 16).isMountain = True
        map.GetTile(10, 12).isMountain = True
        map.GetTile(8, 17).isMountain = True
        map.GetTile(10, 10).isMountain = True
        map.GetTile(6, 12).isMountain = True
        map.GetTile(5, 16).isMountain = True
        map.GetTile(5, 13).isMountain = True
        map.GetTile(7, 10).isMountain = True
        # for i in range(12, 16):
        #     map.GetTile(7, i).isMountain = True
        for i in range(6, 11):
            map.GetTile(10, i).isMountain = True
        for i in range(7, 10):
            map.GetTile(i, 15).isMountain = True
        # for i in range(6, 10):
        #     map.GetTile(i, 15).isMountain = True

        map.update_reachable()

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=False, renderThresh=700, tileIslandSize=5, method=method)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 1.5, 'should find a plan with pretty high value per turn')

    def test_should_gather_through_friendly_or_enemy_island_flows__simple_base_case(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |
aG12 bG1
|    |
player_index=0
"""

        for turns, bestTurns, bestEcon in [
            (40, 1, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL),
            (2, 1, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL),  # should not use the extra 7th turn when not necessary, to grab extra army...?
            (1, 1, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL),
            (0, 0, 0.0),
        ]:
            with self.subTest(turns=turns):
                self.begin_capturing_logging()
                map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=False, method=method)

                # if debugMode:
                #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
                #     simHost.queue_player_moves_str(general.player, expectedPath)
                #
                #     self.begin_capturing_logging()
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=min(10, turns))

                if bestEcon == 0.0:
                    self.assertEqual(0, len(opts))
                    # we shouldn't have any 0-turn options or worse, more than 0 turn options
                    continue

                self.assertNotEqual(0, len(opts))

                self.assertEqual(round(bestEcon, 5), round(opts[0].econValue, 5))
                self.assertEqual(bestTurns, opts[0].length)

    def test_should_gather_through_friendly_or_enemy_island_flows__basic(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |
aG12 a8   a2   b1   a2   b2   b1   b1   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |
player_index=0
"""

        for turns, bestTurns, bestEcon, expectedPath in [
            (40, 10, 7 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->10,0'),
            (2, 2, 1 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '1,0->3,0'),
            (3, 2, 1 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '1,0->3,0'),
            (7, 6, 4 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '1,0->7,0'),  # should not use the extra 7th turn when not necessary, to grab extra army...?
            (6, 6, 4 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '1,0->7,0'),
            (9, 9, 6 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->9,0'),
            (8, 8, 5 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->8,0'),
        ]:
            with self.subTest(turns=turns):
                map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=debugMode, method=method)

                # if debugMode:
                #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
                #     simHost.queue_player_moves_str(general.player, expectedPath)
                #
                #     self.begin_capturing_logging()
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=min(10, turns))

                self.assertNotEqual(0, len(opts))

                longestOpt = max(opts, key=lambda opt: opt.length)

                # 7 en caps, 10 moves, should be our best case scenario.
                self.assertEqual(round(bestEcon, 5), round(longestOpt.econValue, 5))
                self.assertEqual(bestTurns, longestOpt.length)


    def test_should_gather_through_friendly_or_enemy_island_flows__double(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |    |    |    |    |
aG12 a8   a2   b1   a2   b2   b1   a0   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |
player_index=0
"""

        for turns, bestTurns, bestEcon, expectedPath in [
            (40, 10, 6 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->10,0'),
            # (7, 6, 4 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '1,0->7,0'),  # should not use the extra 7th turn when not necessary, to grab extra army...?
            # (6, 6, 4 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '1,0->7,0'),
            # (9, 9, 6 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->9,0'),
            # (8, 8, 5 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->8,0'),
        ]:
            with self.subTest(turns=turns):
                map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=True, method=method)

                # if debugMode:
                #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
                #     simHost.queue_player_moves_str(general.player, expectedPath)
                #
                #     self.begin_capturing_logging()
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=min(10, turns))

                self.assertNotEqual(0, len(opts))

                longestOpt = max(opts, key=lambda opt: opt.length)

                # 7 en caps, 10 moves, should be our best case scenario.
                self.assertEqual(round(bestEcon, 5), round(longestOpt.econValue, 5))
                self.assertEqual(bestTurns, longestOpt.length)


    def test_build_flow_expand_plan__incomplete_target_island__should_not_overcap_tiles_beyond_algo_army(self):
        """
        Regression test: when the incompleteTarget island is fully exhausted by incompleteUsedTurns,
        the GCP plan must not include an extra tile the algo didn't have army for.
        The +1 offset in incompleteUsedTurns caused incompleteUsedTurns > incompleteTarget.tile_count
        when the island was exactly exhausted, giving the plan an extra free capture with negative army.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 6 friendly tiles (incomplete source) + 6 neutral tiles (incomplete target) + enemy general.
        # With turns=12 the algo captures 5 neutrals and stops; the +1 bug causes the GCP
        # builder to select 6 tiles, producing a root node with value < 0.
        # 13 columns: 6 friendly (aG1, a3x5) + 6 neutral + 1 enemy general
        # Each cell is exactly 5 chars; blank cells become neutral tiles via fill_out_tiles
        sep = '|    ' * 12 + '|'
        friendly = 'aG1  ' + 'a3   ' * 5  # cols 0-5
        neutral6 = '     ' * 6            # cols 6-11
        mapData = f'\n{sep}\n{friendly}{neutral6}bG1\n{sep}\nplayer_index=0\n'
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        expander, opts = self.run_army_flow_expansion_and_get_expander(
            map,
            general,
            enemyGeneral,
            turns=12,
            debugMode=debugMode,
            renderThresh=700,
            tileIslandSize=5,
            shouldRender=False,
            method=method,
        )

        self.assertNotEqual(0, len(opts), 'should produce at least one valid plan')
        for opt in opts:
            for rootNode in opt.root_nodes:
                self.assertGreaterEqual(
                    rootNode.value,
                    0,
                    f'Plan root node had negative army ({rootNode.value}) - invalid plan produced: {opt}',
                )
    
    def test_a_more_open_normal_map(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/a_more_open_normal_map___VY49QNB72---1--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        turns = 50

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=1, shouldRender=debugMode, method=method)

        # if debugMode:
        #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        #     simHost.queue_player_moves_str(general.player, expectedPath)
        #
        #     self.begin_capturing_logging()
        #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=min(10, turns))

        self.assertNotEqual(0, len(opts))

        longestOpt = max(opts, key=lambda opt: opt.length)

    def test_should_find_merging_streams_when_optimal(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |
aG13 b1   b1   b7   b7   M    bG1
a12                 b7   b1   b1
|    |    |    |    |    |    |
player_index=0
"""
        for turns, bestTurns, bestEcon, expectedPath in [
            (7, 5, 4 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->3,0  0,1->4,1'),
            (3, 3, 3 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->3,0'),
            (5, 5, 4 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,1->0,0->4,0'),
        ]:
            with self.subTest(turns=turns):
                map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=debugMode, method=method)

                # if debugMode:
                #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
                #     simHost.queue_player_moves_str(general.player, expectedPath)
                #
                #     self.begin_capturing_logging()
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=min(10, turns))

                self.assertNotEqual(0, len(opts))

                longestOpt = max(opts, key=lambda opt: opt.length)

                # 7 en caps, 10 moves, should be our best case scenario.
                self.assertEqual(round(bestEcon, 5), round(longestOpt.econValue, 5))
                self.assertEqual(bestTurns, longestOpt.length)



    def test_should_not_include_separate_streams_in_same_plan(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |
aG13 b1                  M    bG1

a12  b1             b7   b1   b1
|    |    |    |    |    |    |
player_index=0
"""
        for turns, bestTurns, bestEcon, expectedPath in [
            (2, 2, 1 + 1 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->2,0'), # should not find using both a12s in the same plan (?)
            (1, 1, 1 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->1,0'),
        ]:
            with self.subTest(turns=turns):
                map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=False, method=method)

                # if debugMode:
                #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
                #     simHost.queue_player_moves_str(general.player, expectedPath)
                #
                #     self.begin_capturing_logging()
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=min(10, turns))

                self.assertNotEqual(0, len(opts))

                longestOpt = max(opts, key=lambda opt: opt.length)

                # 7 en caps, 10 moves, should be our best case scenario.
                self.assertEqual(round(bestEcon, 5), round(longestOpt.econValue, 5))
                self.assertEqual(bestTurns, longestOpt.length)
