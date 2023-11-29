import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class ArmyInterceptionTests(TestBase):
    def test_should_intercept_army_that_is_one_tile_kill_and_city_threat_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        for i in range(10):
            with self.subTest(i=i):
                mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=307)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
                self.assertIsNone(winner)

                self.assertEqual(general.player, playerMap.GetTile(7, 14).player)
