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


class AllInTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.gather_use_pcst = True
        # bot.info_render_centrality_distances = True

        return bot
    
    def test_should_execute_the_full_all_in(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_execute_the_full_all_in___ESW_l8ssb---1--358.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 358, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=358)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=75)
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(general.player, winner)
    
    def test_should_not_make_unsafe_winning_all_in_plans(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO should just keep some army near general? As much as 30 turn attack risk?
        #  Or, should make sure to launch attacks down the straight line path?
        mapFile = 'GameContinuationEntries/should_not_make_unsafe_winning_all_in_plans___f1tVhCbAr---1--458.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 458, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=458)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=55)
        self.assertNoFriendliesKilled(map, general)
