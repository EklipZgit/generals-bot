import time
import typing
from collections import deque

import logbook

import Gather
import SearchUtils
from Algorithms import TileIslandBuilder
from Algorithms.TileIslandBuilder import IslandBuildMode
from BehaviorAlgorithms import IterativeExpansion
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, IslandFlowNode
from BoardAnalyzer import BoardAnalyzer
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot


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

    def test_build_flow_expand_plan__should_be_fast(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize, maxDuration in [
            ('small', 0.010),
            ('large', 0.050)
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
                opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)

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
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        self.assertEqual(3, len(opts), 'should have an option for each length gather/cap, 1, 3, 5 lengths.')
        longestOpt = self.get_longest_flow_expansion_option(opts)
        # self.assertEqual(1, len(opts), 'should only have one option in this case (assuming we continue not allowing neutral expansion)')
        # opt = opts[0]
        self.assertEqual(5, longestOpt.length, 'should be 5 turns to pull 3x 3s and capture 3x 1s')
        self.assertEqual(6, round(longestOpt.econValue), 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(0, longestOpt.armyRemaining, 'should have NO army remaining')

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
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
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
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
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
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
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
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
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
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
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
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
        self.assertEqual(3, len(opts), 'should have 3 options technically although dunno why youd not cap the zero tile')
        longest = self.get_longest_flow_expansion_option(opts)
        self.assertEqual(6, round(longest.econValue), 'should be 6 econ roughly to capture 3 enemy tiles.')
        self.assertEqual(5, longest.length, 'should be 5 turns to pull everything and capture the 0 too')
        self.assertEqual(0, longest.armyRemaining)

    def test_builds_flow_plan__should_recognize_gather_into_top_path_is_best(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        flowExpander = ArmyFlowExpander(map)
        opts = flowExpander.get_expansion_options(builder, general.player, enemyGeneral.player, turns=50, boardAnalysis=None, territoryMap=None, negativeTiles=None)
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
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 1.5, 'should find a plan with pretty high value per turn')

    def test_should_recognize_gather_into_top_path_is_best__with_time_cutoff(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(10):
            mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

            map.GetTile(7, 12).isMountain = True
            map.GetTile(7, 10).isMountain = True
            map.update_reachable()
            # if debugMode:
            #     self.render_map(map)

            self.enable_search_time_limits_and_disable_debug_asserts()
            self.begin_capturing_logging()

            timeLimit = 10

            opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=50, debugMode=debugMode, renderThresh=700, tileIslandSize=4, timeLimit=timeLimit, shouldRender=False)
            try:
                self.assertNotEqual(0, len(opts))
                self.assertGreater(opts[0].econValue / opts[0].length, 1.5, f'best vt low: {opts[0]}')
            except:
                self.render_gather_capture_plan(map, opts[0], general.player, enemyGeneral.player, f'best vt low: {opts[0]}')
                raise

            longestOpt = next(opt for opt in sorted(opts, key=lambda o: o.length, reverse=True))
            try:
                self.assertGreater(longestOpt.length, 34, f'longest plan too short. {longestOpt}')
            except:
                self.render_gather_capture_plan(map, longestOpt, general.player, enemyGeneral.player, f'longest plan too short. {longestOpt}')
                raise

            bestLongerOpt = next(opt for opt in sorted(opts, key=lambda o: (o.length > 15, o.econValue / o.length), reverse=True))
            try:
                self.assertGreater(bestLongerOpt.econValue / bestLongerOpt.length, 1.1, f'longerOpt vt low: {bestLongerOpt}')
            except:
                self.render_gather_capture_plan(map, bestLongerOpt, general.player, enemyGeneral.player, f'longerOpt vt low: {bestLongerOpt}')
                raise

    def test_should_not_produce_invalid_plan__enemy_cluster_crossing_neutral_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

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

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 0.99, 'should find a plan with pretty high value per turn with one-move-cap')

        optWithCaps = SearchUtils.where(opts, lambda o: SearchUtils.any_where(o.tileSet, lambda t: t.player == enemyGeneral.player))
        self.assertGreater(len(optWithCaps), 0)
        self.assertGreater(optWithCaps[0].econValue, 0.8)

    def test_should_not_produce_invalid_plan__neutral_cap(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

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

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 0.99, 'should find a plan with pretty high value per turn')

    def test_should_not_produce_invalid_enemy_captures(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

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

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 1.5, 'should find a plan with pretty high value per turn')


    def test_should_gather_through_friendly_or_enemy_island_flows(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

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

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=40, debugMode=debugMode, renderThresh=700, tileIslandSize=5)
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

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=False)

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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    
aG12 a8   a2   b1   a2   b2   b1   b1   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |    
player_index=0
"""

        for turns, bestTurns, bestEcon, expectedPath in [
            (40, 10, 7 * IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, '0,0->10,0'),
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

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=False)

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
                map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

                # if debugMode:
                #     self.render_map(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                self.begin_capturing_logging()

                opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=turns, debugMode=debugMode, renderThresh=700, tileIslandSize=5, shouldRender=True)

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
