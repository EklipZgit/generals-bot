import logbook
import time
import typing

import DebugHelper
import GatherUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot


class GatherUnitTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        bot.info_render_centrality_distances = True
        GatherUtils.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True

        return bot

    def test_should_not_try_to_gather_1s_after_prune(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_try_to_gather_1s_after_prune___Human.exe-TEST__ef67143f-5238-4441-b95b-dc85bc64e06b---1--122.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 122, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=122)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertEqual(19, playerMap.GetTile(6, 15).army)
    
    def test_should_not_get_divide_by_zero_exc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_get_divide_by_zero_exc___uY5YnPrx_---0--378.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 378, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=378)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
