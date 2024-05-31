import inspect
import random
import time
import typing
import unittest

import KnapsackUtils
import SearchUtils
from Algorithms import MapSpanningUtils
from SearchUtils import dest_breadth_first_target
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.tile import Tile
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


class MapSpanningUtilsTests(TestBase):
    def test_should_build_spanning_tree(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49_actual_spawn.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 49, fill_out_tiles=True)

        ogFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49.txtmap'
        rawMap, _ = self.load_map_and_general(ogFile, respect_undiscovered=True, turn=49)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->9,3  5,11->6,11->7,11->8,11->9,11->10,11->11,11->12,11->13,11  5,11->5,10->5,9->4,9->4,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = bot._map

        banned = {t for t in playerMap.get_all_tiles() if t.visible}
        t1 = playerMap.GetTile(13, 11)
        t2 = playerMap.GetTile(9, 3)
        required = [t1, t2]

        inclTiles, missingTiles = MapSpanningUtils.get_spanning_tree_from_tile_lists(playerMap, required, banned)

        self.assertIn(t1, inclTiles)
        self.assertIn(t2, inclTiles)
        self.assertEqual(0, len(missingTiles))
