from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile, TILE_FOG
from bot_ek0x45 import EklipZBot


class GameSimulatorTests(TestBase):
    def test_simulates_a_game_from_turn_1(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general = self.load_map_and_general('Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/243.txtmap', 243, player_index=1)
        # fakeEnemyGen = map.GetTile(2, 16)
        # fakeEnemyGen.isGeneral = True
        # fakeEnemyGen.player = 0
        # fakeEnemyGen.army = 7

        self.begin_capturing_logging()
        self.reset_map_to_just_generals(map, turn=16)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player)

        simHost.run_sim(run_real_time=debugMode, turn_time=0.0001)

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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general = self.load_map_and_general('Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/243.txtmap', 243, player_index=1)
        fakeEnemyGen = map.GetTile(2, 16)
        fakeEnemyGen.isGeneral = True
        fakeEnemyGen.player = 0
        fakeEnemyGen.army = 7

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert red of blues general location so it continues the attack
        simHost.sim.players[0].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
        # simHost = GameSimulatorHost(map)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.1)

    def test_simulates_a_2v2_game(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
                         M                                                                M
M              M                   M                   M         cG7  M                             M
          M                        M                   M              M    M    C45            M         M
                                   M                   M                                            M
     C48  M                                                                          M
                                             M                   M         M                   M
               M                                                           M              C41
          C42       M    M                                            M    M                        M
          M    C48  M                                                                dG7  M              M
     M                                  M                   M                     
               M    M                                                 M                   M
               M                                                           M    M         M
                    C41  C45       M                   M              M         C41
     M                                                                          M    M                   M
               M                   C43  M              C43  M           
M    aG7                      M                   M                                  M              M    M
                                        M                   M         M                   M         M
                                             M                   M         M                   M
          M                   bG7                      M
     M                                                                               M
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
turn=4
player_index=0
teams=1,1,2,2
mode=team
targetPlayerExpectedGeneralLocation=7,7
aUsername=A
bUsername=B
cUsername=C
dUsername=D
aTiles=1
bTiles=1
cTiles=1
dTiles=1
"""
        map, general = self.load_map_and_general_from_string(mapData, 4, player_index=0)
        self.reset_map_to_just_generals(map)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.1)

    def test_game_simulator__correctly_updates_client_fog_of_war__robust_against_manually_tweaked_maps(self):
        map, general = self.load_map_and_general('Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/243.txtmap', 243, player_index=1)
        fakeEnemyGen = map.GetTile(2, 16)
        fakeEnemyGen.isGeneral = True
        fakeEnemyGen.player = 0
        fakeEnemyGen.army = 7

        self.reset_map_to_just_generals(map, turn=12)
        self.assertEqual(fakeEnemyGen, map.generals[0])
        self.assertEqual(general, map.generals[1])

        """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
                         M                                            M
M              M                   M              M                             M
          M                        M              M    M    M              M         M
                                   M                                            M
     C48  M                                                      M
                                             M         M                   M
               M                                       M              M
          C42       M    M                        M    M                        M
          M    C48  M                   bG1                           M              M
     M                                  M                     
          M    M    M                             M                   M
          M    M                                       M    M         M
                    C41  C45       M              M         M
     M                                                      M    M                   M
               M                   C43  M           
M                             M                                  M              M    M
          aG7  !b1  !b1                 M         M                   M         M
                                             M         M                   M
          M                             M
     M
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
"""

        p1TileNextToEnemy = map.GetTile(3, 16)
        p1TileNextToEnemy.player = 1
        p1TileNextToEnemy.army = 1
        # tile still -1

        p1TileNextToEnemyCorrectTile = map.GetTile(4, 16)
        p1TileNextToEnemyCorrectTile.player = 1
        p1TileNextToEnemyCorrectTile.army = 1
        p1TileNextToEnemyCorrectTile.tile = 1

        self.enable_search_time_limits_and_disable_debug_asserts()

        # loading the game simulator should correct all inconsistencies with the map data for a base map,
        # player tiles should be synced up, mountain vs obstacle should be corrected etc.
        sim = GameSimulator(map, ignore_illegal_moves=False)
        self.assertPlayerTileVisibleAndCorrect(fakeEnemyGen.x, fakeEnemyGen.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemy.x, p1TileNextToEnemy.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemyCorrectTile.x, p1TileNextToEnemyCorrectTile.y, sim, general.player)

        self.assertPlayerTileVisibleAndCorrect(fakeEnemyGen.x, fakeEnemyGen.y, sim, fakeEnemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemy.x, p1TileNextToEnemy.y, sim, fakeEnemyGen.player)
        # enemy gen can't see p1s tile two tiles away
        self.assertPlayerTileNotVisible(p1TileNextToEnemyCorrectTile.x, p1TileNextToEnemyCorrectTile.y, sim, fakeEnemyGen.player)

        # p0 captures p1s tile
        sim.make_move(0, Move(fakeEnemyGen, p1TileNextToEnemy))
        sim.make_move(1, Move(general, general.movable[0]))
        sim.execute_turn()
        self.assertEqual(13, map.turn)
        self.assertEqual(13, sim.players[0].map.turn)
        self.assertEqual(13, sim.players[1].map.turn)

        self.assertPlayerTileLostVision(fakeEnemyGen.x, fakeEnemyGen.y, sim, general.player)
        # assert the tiles that that tile exclusively was granting vision of, are lost vision too
        self.assertPlayerTileLostVision(2, 17, sim, general.player)
        self.assertPlayerTileLostVision(2, 15, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemy.x, p1TileNextToEnemy.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemyCorrectTile.x, p1TileNextToEnemyCorrectTile.y, sim, general.player)

        self.assertPlayerTileVisibleAndCorrect(fakeEnemyGen.x, fakeEnemyGen.y, sim, fakeEnemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemy.x, p1TileNextToEnemy.y, sim, fakeEnemyGen.player)
        # enemy gen can see our tile two tiles away now
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemyCorrectTile.x, p1TileNextToEnemyCorrectTile.y, sim, fakeEnemyGen.player)

        # p0 captures p1s final tile down there
        sim.make_move(0, Move(p1TileNextToEnemy, p1TileNextToEnemyCorrectTile))
        sim.make_move(1, Move(general.movable[0], general.movable[0].movable[0]))
        sim.execute_turn()

        self.assertPlayerTileNotVisible(fakeEnemyGen.x, fakeEnemyGen.y, sim, general.player)
        # should have lost vision of BOTH of these tiles, and the tiles around them
        self.assertPlayerTileLostVision(p1TileNextToEnemy.x, p1TileNextToEnemy.y, sim, general.player)
        self.assertPlayerTileLostVision(p1TileNextToEnemyCorrectTile.x, p1TileNextToEnemyCorrectTile.y, sim, general.player)
        for adj in p1TileNextToEnemy.adjacents:
            self.assertPlayerTileNotVisible(adj.x, adj.y, sim, general.player)
        for adj in p1TileNextToEnemyCorrectTile.adjacents:
            self.assertPlayerTileLostVision(adj.x, adj.y, sim, general.player)

        self.assertPlayerTileVisibleAndCorrect(fakeEnemyGen.x, fakeEnemyGen.y, sim, fakeEnemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemy.x, p1TileNextToEnemy.y, sim, fakeEnemyGen.player)
        # enemy gen can see our tile two tiles away now
        self.assertPlayerTileVisibleAndCorrect(p1TileNextToEnemyCorrectTile.x, p1TileNextToEnemyCorrectTile.y, sim, fakeEnemyGen.player)

    def test_game_simulator__collided_armies_have_correct_deltas__both_move_to_same_tile(self):
        # (a army amount, b army amount, target tile player, target tile army)
        testCases = [
            # neutral target
            (10, 10, -1, 0),
            (10, 2, -1, 0),
            (2, 10, -1, 0),
            (100, 10, -1, 0),
            (10, 100, -1, 0),

            # player target, '1' tile
            (10, 10, 0, 1),
            (10, 2, 0, 1),
            (2, 10, 0, 1),
            (10, 3, 0, 1),
            (3, 10, 0, 1),
            (100, 10, 0, 1),
            (10, 100, 0, 1),

            # player target, larger tile
            (10, 10, 0, 20),
            (10, 2, 0, 20),
            (2, 10, 0, 20),
            (100, 10, 0, 20),
            (10, 100, 0, 20),
        ]

        for aArmyAmount, bArmyAmount, targetTilePlayer, targetTileArmy in testCases:
            for turn in [50, 51]:
                with self.subTest(aArmyAmount=aArmyAmount, bArmyAmount=bArmyAmount, targetTilePlayer=targetTilePlayer, targetTileArmy=targetTileArmy, turn=turn):
                    self.run_corner_collision_test(aArmyAmount, bArmyAmount, targetTilePlayer, targetTileArmy, turn)

    def test_specific_corner_collision(self):
        self.run_corner_collision_test(10, 10, -1, 0, 50)

    def run_corner_collision_test(self, aArmyAmount: int, bArmyAmount: int, targetTilePlayer: int, targetTileArmy: int, turn: int, render: bool = False):
        # note Turn parameterized because odd/evenness impact p1 vs p2 tiebreaks
        mapRaw = """
|    |    |    |
aG7
     a1
          b1
               bG7
|    |    |    |
"""
        map, general = self.load_map_and_general_from_string(mapRaw, turn=turn, player_index=0)

        enemyGen = map.GetTile(3, 3)

        aCollisionSource = map.GetTile(1, 1)
        aCollisionSource.army = aArmyAmount

        bCollisionSource = map.GetTile(2, 2)
        bCollisionSource.army = bArmyAmount

        collisionTarget = map.GetTile(1, 2)
        collisionTarget.player = targetTilePlayer
        collisionTarget.army = targetTileArmy

        glitchyTile = map.GetTile(1, 3)
        self.assertEqual(0, glitchyTile.army)
        self.assertEqual(-1, glitchyTile.player)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # loading the game simulator should correct all inconsistencies with the map data for a base map,
        # player tiles should be synced up, mountain vs obstacle should be corrected etc.
        sim = GameSimulator(map, ignore_illegal_moves=False)
        self.assertPlayerTileVisibleAndCorrect(general.x, general.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(aCollisionSource.x, aCollisionSource.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(bCollisionSource.x, bCollisionSource.y, sim, general.player)

        self.assertPlayerTileVisibleAndCorrect(enemyGen.x, enemyGen.y, sim, enemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(aCollisionSource.x, aCollisionSource.y, sim, enemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(bCollisionSource.x, bCollisionSource.y, sim, enemyGen.player)

        glitchyTile = map.GetTile(1, 3)
        self.assertEqual(0, glitchyTile.army)
        self.assertEqual(-1, glitchyTile.player)
        self.assertPlayerTileCorrect(1, 3, sim, 0)
        self.assertPlayerTileCorrect(1, 3, sim, 1)

        # armies collide
        sim.make_move(0, Move(aCollisionSource, collisionTarget))
        sim.make_move(1, Move(bCollisionSource, collisionTarget))
        sim.execute_turn()

        if render:
            self.render_sim_map_from_all_perspectives(sim)

        glitchyTile = map.GetTile(1, 3)
        self.assertEqual(0, glitchyTile.army)
        self.assertEqual(-1, glitchyTile.player)
        self.assertPlayerTileCorrect(1, 3, sim, 0)
        self.assertPlayerTileCorrect(1, 3, sim, 1)

        # assert all the players still have all the correct base tile information:
        self.assertPlayerTileVisibleAndCorrect(general.x, general.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(aCollisionSource.x, aCollisionSource.y, sim, general.player)
        self.assertPlayerTileVisibleAndCorrect(bCollisionSource.x, bCollisionSource.y, sim, general.player)

        self.assertPlayerTileVisibleAndCorrect(enemyGen.x, enemyGen.y, sim, enemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(aCollisionSource.x, aCollisionSource.y, sim, enemyGen.player)
        self.assertPlayerTileVisibleAndCorrect(bCollisionSource.x, bCollisionSource.y, sim, enemyGen.player)

        # ok NOW lets see what it thinks about armies nearby
        for tile in aCollisionSource.adjacents:
            if tile == general:
                # b doesn't have perfect information about a's gen
                continue
            self.assertPlayerTileCorrect(tile.x, tile.y, sim, 0)
            self.assertPlayerTileCorrect(tile.x, tile.y, sim, 1)

        for tile in bCollisionSource.adjacents:
            if tile == enemyGen:
                # a doesn't have perfect information about b's gen
                continue
            self.assertPlayerTileCorrect(tile.x, tile.y, sim, 0)
            self.assertPlayerTileCorrect(tile.x, tile.y, sim, 1)

        aMovedAmount = aArmyAmount - 1
        bMovedAmount = bArmyAmount - 1

        # assert army deltas correct
        p0aSourceTile = self.get_player_tile(aCollisionSource.x, aCollisionSource.y, sim, 0)
        self.assertEqual(0 - aMovedAmount, p0aSourceTile.delta.armyDelta)
        p1aSourceTile = self.get_player_tile(aCollisionSource.x, aCollisionSource.y, sim, 1)
        self.assertEqual(0 - aMovedAmount, p1aSourceTile.delta.armyDelta)
        p0bSourceTile = self.get_player_tile(bCollisionSource.x, bCollisionSource.y, sim, 0)
        self.assertEqual(0 - bMovedAmount, p0bSourceTile.delta.armyDelta)
        p1bSourceTile = self.get_player_tile(bCollisionSource.x, bCollisionSource.y, sim, 1)
        self.assertEqual(0 - bMovedAmount, p1bSourceTile.delta.armyDelta)
        # abs's because these will be positive or negative per player depending who won the tiebreak and
        # i don't know how the server tiebreaks currently so don't want to bother asserting
        p0targetTile = self.get_player_tile(collisionTarget.x, collisionTarget.y, sim, 0)
        self.assertEqual(abs(aMovedAmount - bMovedAmount), abs(p0targetTile.delta.armyDelta))
        p1targetTile = self.get_player_tile(collisionTarget.x, collisionTarget.y, sim, 1)
        self.assertEqual(abs(aMovedAmount - bMovedAmount), abs(p1targetTile.delta.armyDelta))

    def test_should_recognize_real_world_loss_on_army_priority(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        """
        real world game where bot lost on priority while thinking it won...
        """

        for turn in [495, 496]:
            with self.subTest(turn=turn):
                mapFile = 'GameContinuationEntries/should_recognize_loss_on_army_priority___ayWl0cB6S---1--495.txtmap'
                map, general, enemyGen = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)
                # self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                genPlayer = general.player
                enPlayer = enemyGen.player

                sim = GameSimulator(map)
                pMap = sim.players[general.player].map
                eMap = sim.players[enemyGen.player].map
                sim.make_move(general.player, Move(pMap.GetTile(6, 7), pMap.GetTile(5, 7)))
                sim.make_move(enemyGen.player, Move(eMap.GetTile(6, 9), eMap.GetTile(5, 9)))
                sim.execute_turn()
                sim.make_move(general.player, Move(pMap.GetTile(5, 7), pMap.GetTile(5, 8)))
                sim.make_move(enemyGen.player, Move(eMap.GetTile(5, 9), eMap.GetTile(5, 8)))
                sim.execute_turn()

                if turn == 495:
                    self.assertTrue(sim.is_game_over())
                    self.assertTrue(pMap.players[genPlayer].dead)
                    self.assertTrue(sim.players[genPlayer].dead)
                else:
                    self.assertFalse(sim.is_game_over())
                    self.assertFalse(pMap.players[genPlayer].dead)
                    self.assertFalse(sim.players[genPlayer].dead)
