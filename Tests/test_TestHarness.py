import logbook

import SearchUtils
from Directives import Timings
from MapMatrix import MapMatrix
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import Tile, TILE_FOG
from BotModules.BotCombatOps import BotCombatOps
from BotModules.BotTimings import BotTimings

class TestHarnessTests(TestBase):
    def test_should_load_map_correctly_when_too_many_split_armies_and_tiles_vs_real(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        self.begin_capturing_logging()
        mapFile = 'GameContinuationEntries/force_far_gathers_shouldnt_trigger_a_massive_gather_resulting_in_loss___wVkZWg5RH---1--662.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 662, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=662)

        with self.subTest('tile count vision'):
            self.assertEqual(129, rawMap.players[enemyGeneral.player].tileCount)
        with self.subTest('army amount vision'):
            self.assertEqual(570, rawMap.players[enemyGeneral.player].score)
        with self.subTest('tile count real'):
            self.assertEqual(129, map.players[enemyGeneral.player].tileCount)
        with self.subTest('army amount real'):
            self.assertEqual(570, map.players[enemyGeneral.player].score)

    def test_should_not_fuck_up_armies(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_remove_both_entangled_armies_when_army_emerges_from_fog___QoMfyZD0B---1--287.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 287, fill_out_tiles=True)
        # map.GetTile(12, 7).army = 113

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=287)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,7->12,6')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.assertEqual(113, rawMap.GetTile(12, 7).army)
        self.assertEqual(112, rawMap.GetTile(12, 8).army)

        self.assertEqual(113, bot._map.GetTile(12, 7).army)
        self.assertEqual(112, bot._map.GetTile(12, 8).army)

        self.assertEqual(113, playerMap.GetTile(12, 7).army)
