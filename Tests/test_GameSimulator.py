import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase, Tile, TILE_FOG
from bot_ek0x45 import EklipZBot


class GameSimulatorTests(TestBase):

    def test_loads_map_data_correctly_per_player(self):
        map, general = self.load_map_and_general('Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap', 242, player_index=1)
        fakeEnemyGen = map.GetTile(2, 16)
        fakeEnemyGen.isGeneral = True
        fakeEnemyGen.player = 0
        fakeEnemyGen.army = 7

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

        sim = GameSimulator(map)

        p0Map = sim.players[0].map
        p1Map = sim.players[1].map

        # assert player 1's map loaded correctly from base map
        self.assertEqual(1, p1Map.GetTile(5, 8).player)
        self.assertEqual(1, p1Map.GetTile(5, 8).tile)
        self.assertEqual(10, p1Map.GetTile(5, 8).army)
        self.assertTrue(p1Map.GetTile(5, 8).visible)

        self.assertEqual(1, p1Map.GetTile(5, 9).player)
        self.assertEqual(1, p1Map.GetTile(5, 9).tile)
        self.assertEqual(2, p1Map.GetTile(5, 9).army)
        self.assertTrue(p1Map.GetTile(5, 9).visible)

        self.assertEqual(0, p1Map.GetTile(6, 10).player)
        self.assertEqual(0, p1Map.GetTile(6, 10).tile)
        self.assertEqual(33, p1Map.GetTile(6, 10).army)
        self.assertTrue(p1Map.GetTile(6, 10).visible)

        # this tile is out of reds vision
        self.assertEqual(-1, p0Map.GetTile(5, 8).player)
        self.assertEqual(TILE_FOG, p0Map.GetTile(5, 8).tile)
        self.assertEqual(0, p0Map.GetTile(5, 8).army)
        self.assertFalse(p0Map.GetTile(5, 8).visible)

        self.assertEqual(1, p0Map.GetTile(5, 9).player)
        self.assertEqual(1, p0Map.GetTile(5, 9).tile)
        self.assertEqual(2, p0Map.GetTile(5, 9).army)
        self.assertTrue(p0Map.GetTile(5, 9).visible)

        self.assertEqual(0, p0Map.GetTile(6, 10).player)
        self.assertEqual(0, p0Map.GetTile(6, 10).tile)
        self.assertEqual(33, p0Map.GetTile(6, 10).army)
        self.assertTrue(p0Map.GetTile(6, 10).visible)

        sim.make_move(0, Move(Tile(6, 10), Tile(6, 9)))

        sim.make_move(1, Move(Tile(5, 9), Tile(5, 8)))

        sim.execute_turn()

        # assert player 1's map loaded correctly from base map
        self.assertEqual(1, p1Map.GetTile(5, 8).player)
        self.assertEqual(1, p1Map.GetTile(5, 8).tile)
        self.assertEqual(11, p1Map.GetTile(5, 8).army)
        self.assertTrue(p1Map.GetTile(5, 8).visible)

        self.assertEqual(1, p1Map.GetTile(5, 9).player)
        self.assertEqual(1, p1Map.GetTile(5, 9).tile)
        self.assertEqual(1, p1Map.GetTile(5, 9).army)
        self.assertTrue(p1Map.GetTile(5, 9).visible)

        self.assertEqual(0, p1Map.GetTile(6, 10).player)
        self.assertEqual(0, p1Map.GetTile(6, 10).tile)
        self.assertEqual(1, p1Map.GetTile(6, 10).army)
        self.assertTrue(p1Map.GetTile(6, 10).visible)

        # should be captured by red on blues board, but visible
        self.assertEqual(0, p1Map.GetTile(6, 9).player)
        self.assertEqual(0, p1Map.GetTile(6, 9).tile)
        self.assertEqual(31, p1Map.GetTile(6, 9).army)
        self.assertTrue(p1Map.GetTile(6, 9).visible)

        # this tile is now IN of reds vision
        self.assertEqual(1, p0Map.GetTile(5, 8).player)
        self.assertEqual(1, p0Map.GetTile(5, 8).tile)
        self.assertEqual(11, p0Map.GetTile(5, 8).army)
        self.assertTrue(p0Map.GetTile(5, 8).visible)

        self.assertEqual(1, p0Map.GetTile(5, 9).player)
        self.assertEqual(1, p0Map.GetTile(5, 9).tile)
        self.assertEqual(1, p0Map.GetTile(5, 9).army)
        self.assertTrue(p0Map.GetTile(5, 9).visible)


        self.assertEqual(0, p0Map.GetTile(6, 10).player)
        self.assertEqual(0, p0Map.GetTile(6, 10).tile)
        self.assertEqual(1, p0Map.GetTile(6, 10).army)
        self.assertTrue(p0Map.GetTile(6, 10).visible)

        # should be captured by red on reds board
        self.assertEqual(0, p0Map.GetTile(6, 9).player)
        self.assertEqual(0, p0Map.GetTile(6, 9).tile)
        self.assertEqual(31, p0Map.GetTile(6, 9).army)
        self.assertTrue(p0Map.GetTile(6, 9).visible)

        sim.make_move(0, Move(Tile(6, 9), Tile(7, 9)))

        sim.make_move(1, Move(Tile(5, 8), Tile(6, 8)))

        sim.execute_turn()

        sim.make_move(0, Move(Tile(7, 9), Tile(7, 8)))

        sim.make_move(1, Move(Tile(6, 8), Tile(7, 8)))

        sim.execute_turn()

        # should be captured by red on blues board
        self.assertEqual(0, p1Map.GetTile(7, 8).player)
        self.assertEqual(0, p1Map.GetTile(7, 8).tile)
        self.assertEqual(17, p1Map.GetTile(7, 8).army)
        self.assertTrue(p1Map.GetTile(7, 8).visible)

        # should be captured by red on reds board
        self.assertEqual(0, p0Map.GetTile(7, 8).player)
        self.assertEqual(0, p0Map.GetTile(7, 8).tile)
        self.assertEqual(17, p0Map.GetTile(7, 8).army)
        self.assertTrue(p0Map.GetTile(7, 8).visible)

        # general should be incremented and visible on blues board
        self.assertEqual(1, p1Map.GetTile(8, 8).player)
        self.assertEqual(1, p1Map.GetTile(8, 8).tile)
        self.assertEqual(16, p1Map.GetTile(8, 8).army)
        self.assertTrue(p1Map.GetTile(8, 8).visible)

        # general should be incremented and visible on reds board
        self.assertEqual(1, p0Map.GetTile(8, 8).player)
        self.assertEqual(1, p0Map.GetTile(8, 8).tile)
        self.assertEqual(16, p0Map.GetTile(8, 8).army)
        self.assertTrue(p0Map.GetTile(8, 8).visible)


    def test_simulates_a_game(self):
        map, general = self.load_map_and_general('Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/243.txtmap', 243, player_index=1)
        fakeEnemyGen = map.GetTile(2, 16)
        fakeEnemyGen.isGeneral = True
        fakeEnemyGen.player = 0
        fakeEnemyGen.army = 7

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player)

        simHost.run_sim(run_real_time=True, turn_time=10.0)


    def test_simulates_a_game_from_turn_1(self):
        map, general = self.load_map_and_general('Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/243.txtmap', 243, player_index=1)
        fakeEnemyGen = map.GetTile(2, 16)
        fakeEnemyGen.isGeneral = True
        fakeEnemyGen.player = 0
        fakeEnemyGen.army = 1

        self.reset_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=1)

        simHost.run_sim(run_real_time=True, turn_time=0.1)