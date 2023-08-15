import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class DefenseTests(TestBase):

    def test_simulates_a_failed_defense_scenario(self):
        mapFile = 'Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, player_index=1)

        self.enable_search_time_limits_and_disable_debug_asserts()
        # assert map loaded correctly
        self.assertEqual(1, map.GetTile(5, 8).player)
        self.assertEqual(10, map.GetTile(5, 8).army)
        self.assertTrue(map.GetTile(5, 8).visible)

        self.assertEqual(1, map.GetTile(5, 9).player)
        self.assertEqual(2, map.GetTile(5, 9).army)
        self.assertTrue(map.GetTile(5, 9).visible)

        self.assertEqual(0, map.GetTile(6, 10).player)
        self.assertEqual(33, map.GetTile(6, 10).army)
        self.assertTrue(map.GetTile(6, 10).visible)

        # simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        simHost = GameSimulatorHost(map, player_with_viewer=enemyGeneral.player)
        simHost.sim.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        p0Map = simHost.sim.players[0].map
        p1Map = simHost.sim.players[1].map

        # assert player 1's map loaded correctly from base map
        self.assertEqual(1, p1Map.GetTile(5, 8).player)
        self.assertEqual(10, p1Map.GetTile(5, 8).army)
        self.assertTrue(p1Map.GetTile(5, 8).visible)

        self.assertEqual(1, p1Map.GetTile(5, 9).player)
        self.assertEqual(2, p1Map.GetTile(5, 9).army)
        self.assertTrue(p1Map.GetTile(5, 9).visible)

        self.assertEqual(0, p1Map.GetTile(6, 10).player)
        self.assertEqual(33, p1Map.GetTile(6, 10).army)
        self.assertTrue(p1Map.GetTile(6, 10).visible)

        # this tile is out of reds vision
        self.assertEqual(-1, p0Map.GetTile(5, 8).player)
        self.assertEqual(0, p0Map.GetTile(5, 8).army)
        self.assertFalse(p0Map.GetTile(5, 8).visible)

        self.assertEqual(1, p0Map.GetTile(5, 9).player)
        self.assertEqual(2, p0Map.GetTile(5, 9).army)
        self.assertTrue(p0Map.GetTile(5, 9).visible)

        self.assertEqual(0, p0Map.GetTile(6, 10).player)
        self.assertEqual(33, p0Map.GetTile(6, 10).army)
        self.assertTrue(p0Map.GetTile(6, 10).visible)

        simHost.run_sim(run_real_time=True, turn_time=3.0)

    def test_should_not_spin_on_defense_gathers_against_sitting_cities(self):
        mapFile = 'GameContinuationEntries/should_not_spin_on_defense_gathers_against_sitting_cities___BelzKSdhh---b--275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 275)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.sim.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.sim.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        simHost.run_sim(run_real_time=True, turn_time=0.5)

