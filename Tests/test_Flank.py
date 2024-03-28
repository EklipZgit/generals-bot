import logbook

import SearchUtils
from Directives import Timings
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile, MapBase, TILE_FOG


class FlankTests(TestBase):
    def test_should_not_over_gather_to_flank(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_over_gather_to_flank___wMQvr_kVV---1--101.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 101, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=101)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        self.assertOwned(-1, playerMap.GetTile(5, 14))
        self.assertOwned(-1, playerMap.GetTile(5, 12))
    
    def test_should_launch_with_less_army_on_questionable_flank(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_launch_with_less_army_on_questionable_flank___rNJJy-29s---1--150.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 150, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=150)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,2->13,2->13,4->12,4->12,6->10,6->10,9->11,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = None
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)

# 0f, 2p