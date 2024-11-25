import logbook
import time
import typing

import DebugHelper
import Gather
import SearchUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot


class GatherCapturePlanTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.gather_use_pcst = True
        # bot.info_render_centrality_distances = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True

        return bot

    def test_build_capture_tree_contiguous(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        gathing = {
            map.GetTile(9, 6),
            map.GetTile(9, 5),
            map.GetTile(9, 7),
        }

        capping = {
            map.GetTile(10, 6),
            map.GetTile(10, 7),
            map.GetTile(10, 8),
            map.GetTile(10, 9),
            map.GetTile(10, 10),
            map.GetTile(11, 8),
        }

        allBorderTiles = {
            map.GetTile(10, 6),
            map.GetTile(10, 7),
        }

        negativeTiles = set()

        plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
            map,
            rootTiles=allBorderTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=True,
            captures=capping,
        )

        self.assertEqual(8, plan.length)
        self.assertEqual(6 * 1.0, plan.econValue)

        # IterativeExpansion

    def test_build_capture_tree_contiguous__should_property_respect_gathered_THROUGH_friendly_land(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    
aG12 a8   a2   b1   a2   b2   b1   b1   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |    
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        gathing = {
            map.GetTile(4, 0),
            map.GetTile(1, 0),
            map.GetTile(2, 0),
            map.GetTile(0, 0),
        }

        capping = {
            map.GetTile(9, 0),
            map.GetTile(10, 0),
            map.GetTile(6, 0),
            map.GetTile(7, 0),
            map.GetTile(8, 0),
            map.GetTile(3, 0),
            map.GetTile(0, 0),
            map.GetTile(5, 0),
        }

        allBorderTiles = {
            map.GetTile(3, 0),
            map.GetTile(5, 0),
        }

        negativeTiles = set()

        plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
            map,
            rootTiles=allBorderTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=True,
            captures=capping,
        )

        self.render_gather_capture_plan(map, plan, general.player, enemyGeneral.player)

        self.assertEqual(10, plan.length)
        self.assertEqual(round(7 * 2.2, 3), round(plan.econValue, 3))

    def test_build_capture_tree_contiguous__should_build_something_sane_on_forked_land(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    
aG12 a9   a6   a3   a5   b1   b1   b1   M    M    
     M    M    M    b1   M    M    M    M    M    
     M    M    M    b1   M    M    M    M    M    
     M    M    M    b1   M    M    M    M    M    
     M    M    M    b1   M    M    M    M    M    
     M    M    M    b1   b1   b1   b1   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |    
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        gathing = set()
        capping = set()

        for i in range(5):
            gathing.add(map.GetTile(i, 0))

        for i in range(4, 10):
            capping.add(map.GetTile(i, 5))

        for i in range(1, 5):
            capping.add(map.GetTile(4, i))

        for i in range(5, 8):
            capping.add(map.GetTile(i, 0))

        rootTiles = {
            map.GetTile(3, 0),
            map.GetTile(5, 0),
        }

        negativeTiles = set()

        plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
            map,
            rootTiles=rootTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=True,
            captures=capping,
        )

        self.render_gather_capture_plan(map, plan, general.player, enemyGeneral.player)

        # gather for 4, need to cap 3 right, need to cap 10 down (we didnt include en general here)
        self.assertEqual(17, plan.length)
        self.assertEqual(round(13 * 2.2, 3), round(plan.econValue, 3))

    def test_build_capture_tree_contiguous__should_build_something_sane_on_forked_land__mixed_fr_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    
aG12 a9   a6   a3   a5   b1   b1   b1   b1   M    M
M    M    M    M    b1   M    M    M    M    M    M
M    M    M    M    b1   M    M    M    M    M    M
M    M    M    M    b1   M    M    M    M    M    M
M    M    M    M    b1   M    M    M    M    M    M
M    M    M    M    a1   b1   a1   b1   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |    
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        gathing = set()
        capping = set()
        for tile in map.pathable_tiles:
            if tile.player == general.player:
                gathing.add(tile)
            else:
                capping.add(tile)

        rootTiles = {map.GetTile(0, 0)}

        negativeTiles = set()

        plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
            map,
            rootTiles=rootTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=True,
            captures=capping,
        )

        self.render_gather_capture_plan(map, plan, general.player, enemyGeneral.player)

        # gather for 4, need to cap 3 right, need to cap 9 down (we did include en general here)
        self.assertEqual(19, plan.length)
        self.assertEqual(round(13 * 2.2, 3), round(plan.econValue, 3))

    def test_should_not_fail_to_find_contiguous_tiles(self):
        self.begin_capturing_logging()
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        for i, invalidSet in enumerate([
            {map.GetTile(10, 8), map.GetTile(14, 7), map.GetTile(15, 7), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(16, 7), map.GetTile(14, 8), map.GetTile(15, 8), map.GetTile(10, 7), map.GetTile(10, 10),
             map.GetTile(12, 10), map.GetTile(12, 8), map.GetTile(12, 9), map.GetTile(13, 9), map.GetTile(12, 11), map.GetTile(10, 5)},
            {map.GetTile(10, 8), map.GetTile(14, 7), map.GetTile(15, 7), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(16, 7), map.GetTile(14, 8), map.GetTile(15, 8), map.GetTile(10, 7), map.GetTile(14, 6),
             map.GetTile(10, 10), map.GetTile(15, 6), map.GetTile(12, 10), map.GetTile(12, 8), map.GetTile(12, 9), map.GetTile(13, 9), map.GetTile(12, 11), map.GetTile(10, 5)},
            {map.GetTile(10, 8), map.GetTile(14, 7), map.GetTile(15, 7), map.GetTile(16, 6), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(16, 7), map.GetTile(14, 8), map.GetTile(15, 8), map.GetTile(10, 7),
             map.GetTile(14, 6), map.GetTile(10, 10), map.GetTile(15, 6), map.GetTile(12, 10), map.GetTile(12, 8), map.GetTile(12, 9), map.GetTile(13, 9), map.GetTile(12, 11), map.GetTile(10, 5)},
            {map.GetTile(10, 8), map.GetTile(14, 7), map.GetTile(15, 7), map.GetTile(16, 6), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(16, 7), map.GetTile(15, 5), map.GetTile(14, 8), map.GetTile(15, 8),
             map.GetTile(10, 7), map.GetTile(14, 6), map.GetTile(10, 10), map.GetTile(15, 6), map.GetTile(16, 5), map.GetTile(12, 10), map.GetTile(11, 5), map.GetTile(12, 5), map.GetTile(12, 8), map.GetTile(12, 9), map.GetTile(13, 9),
             map.GetTile(12, 11), map.GetTile(10, 5)},
            {map.GetTile(10, 8), map.GetTile(14, 7), map.GetTile(15, 7), map.GetTile(16, 6), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(16, 7), map.GetTile(15, 5), map.GetTile(14, 8), map.GetTile(15, 8),
             map.GetTile(10, 7), map.GetTile(14, 6), map.GetTile(10, 10), map.GetTile(15, 6), map.GetTile(16, 5), map.GetTile(12, 10), map.GetTile(12, 8), map.GetTile(10, 4), map.GetTile(12, 9), map.GetTile(13, 9), map.GetTile(12, 11),
             map.GetTile(10, 5)},
            {map.GetTile(14, 8), map.GetTile(15, 8), map.GetTile(10, 8), map.GetTile(10, 7), map.GetTile(10, 10), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(12, 10), map.GetTile(12, 9), map.GetTile(12, 8),
             map.GetTile(13, 9), map.GetTile(12, 11), map.GetTile(10, 5)},
            {map.GetTile(14, 8), map.GetTile(15, 8), map.GetTile(10, 8), map.GetTile(14, 7), map.GetTile(10, 7), map.GetTile(10, 10), map.GetTile(10, 6), map.GetTile(10, 9), map.GetTile(11, 8), map.GetTile(12, 10), map.GetTile(12, 9),
             map.GetTile(12, 8), map.GetTile(13, 9), map.GetTile(12, 11), map.GetTile(10, 5)},
        ]):
            with self.subTest(i=i):
                gathing = set()
                capping = set()
                for tile in invalidSet:
                    if tile.player == general.player:
                        gathing.add(tile)
                    else:
                        capping.add(tile)

                rootTiles = {next(iter(invalidSet))}

                negativeTiles = set()
                # this is actually invalid because the tiles werent all contiguous, so turn off debug asserts.
                # we SHOULD produce a valid plan as output.
                GatherDebug.USE_DEBUG_ASSERTS = False
                plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
                    map,
                    rootTiles=rootTiles,
                    tiles=gathing,
                    negativeTiles=negativeTiles,
                    searchingPlayer=general.player,
                    priorityMatrix=None,
                    useTrueValueGathered=True,
                    captures=capping,
                )

                self.render_gather_capture_plan(map, plan, general.player, enemyGeneral.player)

                # gather for 4, need to cap 3 right, need to cap 9 down (we did include en general here)
                self.assertEqual(19, plan.length)
                self.assertEqual(round(13 * 2.2, 3), round(plan.econValue, 3))