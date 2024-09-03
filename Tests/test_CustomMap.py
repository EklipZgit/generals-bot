import time
import typing

import SearchUtils
from ExpandUtils import get_round_plan_with_expansion
from Interfaces import TilePlanInterface
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot


class CustomMapTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_expansion_matrix_values = True
        # bot.info_render_general_undiscovered_prediction_values = True
        # bot.info_render_leaf_move_values = True
        # bot.info_render_tile_islands = True
        # bot.expansion_use_legacy = False

        return bot

    def test_should_be_able_to_play_on_all_minus_1_city_map(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_able_to_play_on_all_-1_city_map___is1thQnQv---1--2.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 2, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=2)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=350)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_be_able_to_play_on_all_-1_city_map")

    def test_should_not_find_no_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_find_no_moves___7uoX7ICS8---1--256.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 256, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=256)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.info_render_general_undiscovered_prediction_values = True
        playerMap = simHost.get_player_map(general.player)

        initCityCount = playerMap.players[general.player].cityCount
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=18)
        self.assertNoFriendliesKilled(map, general)
        self.assertGreater(playerMap.players[general.player].cityCount, initCityCount, 'should have captured more cities in 18 moves...')
    
    def test_should_rapid_expand_cities_when_boxed_in(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_rapid_expand_cities_when_boxed_in___DWdL72byB---1--124.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 124, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=124)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        initCityCount = playerMap.players[general.player].cityCount
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=14)
        self.assertNoFriendliesKilled(map, general)
        self.assertGreater(playerMap.players[general.player].cityCount, initCityCount, 'should have captured more cities in 14 moves...')
    
    def test_should_capture_cities_across_swamps(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_cities_across_swamps___HaltWhoGoesThere-TEST__b70cb27e-4c59-4355-8982-6525259757ed---1--192.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 192, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=192)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        initCityCount = playerMap.players[general.player].cityCount
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertNoFriendliesKilled(map, general)
        self.assertGreater(playerMap.players[general.player].cityCount, initCityCount, 'should have captured more cities in after this long')
    
    def test_should_find_quick_kills_on_tiny_cities_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_quick_kills_on_tiny_cities_wtf___oiPQatIY6---0--76.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 76, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=76)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        initCityCount = playerMap.players[general.player].cityCount
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=108)
        self.assertNoFriendliesKilled(map, general)
        self.assertGreater(playerMap.players[general.player].cityCount, initCityCount, 'should have captured more cities in after this long')
    
    def test_should_prepare_wallbreak_city_in_walled_customs_even_when_not_enough_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prepare_wallbreak_city_in_walled_customs_even_when_not_enough_army___oiPQatIY6---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=108)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = None
        playerMap = simHost.get_player_map(general.player)

        initCityCount = playerMap.players[general.player].cityCount
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)
        self.assertGreater(playerMap.players[general.player].cityCount, initCityCount, 'should have captured more cities in after this long')
