import logging

import SearchUtils
from Directives import Timings
from Path import Path
from SearchUtils import Counter
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class FFATests(TestBase):
    def test_should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos___j4GQjpuy4---0--379.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 379, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=379)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)

        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos")
