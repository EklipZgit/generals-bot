import time

import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile, TILE_FOG, TILE_OBSTACLE
from bot_ek0x45 import EklipZBot


class MapTests(TestBase):

    def test_tile_delta_against_neutral(self):
        mapRaw = """
|  
aG7



| 
"""
        map, general = self.load_map_and_general_from_string(mapRaw, turn=12, player_index=0)

        targetTile = map.GetTile(0, 1)
        genArmyMoved = general.army - 1

        map.update_turn(13)
        map.update_visible_tile(targetTile.x, targetTile.y, general.player, genArmyMoved - targetTile.army, is_city=False,
                                is_general=False)
        map.update_visible_tile(general.x, general.y, general.player, 1, is_city=False, is_general=True)
        map.update()

        self.assertEqual(0 - genArmyMoved, general.delta.armyDelta)
        self.assertEqual(0 - genArmyMoved, targetTile.delta.armyDelta)
        self.assertEqual(general, targetTile.delta.fromTile)
        self.assertEqual(targetTile, general.delta.toTile)

    def test_tile_delta_against_friendly(self):
        mapRaw = """
|  
aG7
a1 


| 
"""
        map, general = self.load_map_and_general_from_string(mapRaw, turn=12, player_index=0)

        targetTile = map.GetTile(0, 1)
        genArmyMoved = general.army - 1

        map.update_turn(13)
        map.update_visible_tile(targetTile.x, targetTile.y, general.player, targetTile.army + genArmyMoved, is_city=False,
                                is_general=False)
        map.update_visible_tile(general.x, general.y, general.player, 1, is_city=False, is_general=True)
        map.update()

        self.assertEqual(0 - genArmyMoved, general.delta.armyDelta)
        self.assertEqual(genArmyMoved, targetTile.delta.armyDelta)
        self.assertEqual(general, targetTile.delta.fromTile)
        self.assertEqual(targetTile, general.delta.toTile)

    def test_tile_delta_against_enemy(self):
        mapRaw = """
|  
aG7
b1 


| 
"""
        map, general = self.load_map_and_general_from_string(mapRaw, turn=12, player_index=0)

        targetTile = map.GetTile(0, 1)
        genArmyMoved = general.army - 1

        map.update_turn(13)
        map.update_visible_tile(targetTile.x, targetTile.y, general.player, genArmyMoved - targetTile.army, is_city=False,
                                is_general=False)
        map.update_visible_tile(general.x, general.y, general.player, 1, is_city=False, is_general=True)
        map.update()

        self.assertEqual(0 - genArmyMoved, general.delta.armyDelta)
        self.assertEqual(5, targetTile.army)
        self.assertEqual(0-genArmyMoved, targetTile.delta.armyDelta)
        self.assertEqual(general, targetTile.delta.fromTile)
        self.assertEqual(targetTile, general.delta.toTile)

        def test_tile_delta_against_neutral_city_non_bonus_turn(self):
            mapRaw = """
    |  
    aG7
    C5


    | 
    """
            map, general = self.load_map_and_general_from_string(mapRaw, turn=12, player_index=0)

            targetTile = map.GetTile(0, 1)
            genArmyMoved = general.army - 1

            map.update_turn(13)
            map.update_visible_tile(targetTile.x, targetTile.y, general.player, genArmyMoved - targetTile.army,
                                    is_city=True,
                                    is_general=False)
            map.update_visible_tile(general.x, general.y, general.player, 1, is_city=False, is_general=True)
            map.update()

            self.assertEqual(0 - genArmyMoved, general.delta.armyDelta)
            self.assertEqual(0 - genArmyMoved, targetTile.delta.armyDelta)
            self.assertEqual(1, targetTile.army)
            self.assertEqual(0, targetTile.player)
            self.assertEqual(general, targetTile.delta.fromTile)
            self.assertEqual(targetTile, general.delta.toTile)

    def test_tile_delta_against_neutral_city_on_bonus_turn(self):
        mapRaw = """
|  
aG7
C5


| 
"""
        map, general = self.load_map_and_general_from_string(mapRaw, turn=13, player_index=0)

        targetTile = map.GetTile(0, 1)
        genArmyMoved = general.army - 1

        map.update_turn(14)
        # city ends up with the 1 from gen capture + 1 from it being a bonus turn, I think?
        cityResultArmy = genArmyMoved - targetTile.army + 1
        map.update_visible_tile(targetTile.x, targetTile.y, general.player, cityResultArmy, is_city=True,
                                is_general=False)
        map.update_visible_tile(general.x, general.y, general.player, 2, is_city=False, is_general=True) # gen has 2 army because bonus
        map.update()

        self.assertEqual(0 - genArmyMoved, general.delta.armyDelta)
        self.assertEqual(0 - genArmyMoved, targetTile.delta.armyDelta)
        self.assertEqual(general, targetTile.delta.fromTile)
        self.assertEqual(targetTile, general.delta.toTile)

    def test_should_not_duplicate_army_in_fog_on_army_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_in_fog_on_army_capture___rgj-w2G62---b--166.txtmap'

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, gen = self.load_map_and_general(mapFile, 166)

        if debugMode:
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 166)
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

            simHost.queue_player_moves_str(enemyGeneral.player, "6,16 -> 6,15 -> 6,14 -> 6,13")
            simHost.queue_player_moves_str(general.player, "5,5 -> 6,5 -> 7,5 -> 8,5")
            simHost.run_sim(run_real_time=True, turn_time=2, turns=5)

        enemyPlayer = (gen.player + 1) & 1

        botMap = rawMap
        t5_16 = botMap.GetTile(5, 16)
        t7_16 = botMap.GetTile(7, 16)

        t6_16 = botMap.GetTile(6, 16)
        t6_15 = botMap.GetTile(6, 15)

        botMap.update_turn(167)
        botMap.update_visible_tile(6, 16, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(5, 16, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(7, 16, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(6, 15, enemyPlayer, tile_army=7)

        self.assertFalse(t6_16.delta.armyMovedHere)
        self.assertTrue(t6_15.delta.armyMovedHere)
        self.assertEqual(-1, t5_16.player)
        self.assertEqual(enemyPlayer, t7_16.player)
        self.assertEqual(enemyPlayer, t6_15.delta.newOwner)
        self.assertEqual(-22, t6_15.delta.armyDelta)

        botMap.update()

        self.assertEqual(t6_16, t6_15.delta.fromTile)
        self.assertEqual(t6_15, t6_16.delta.toTile)
        self.assertEqual(1, t6_16.army)
        self.assertEqual(7, t6_15.army)
        self.assertEqual(-22, t6_15.delta.armyDelta)
        self.assertEqual(22, t6_16.delta.armyDelta)
        # this shouldn't get reset as we use this in armytracker later...?
        self.assertFalse(t6_16.delta.armyMovedHere)
        self.assertTrue(t6_15.delta.armyMovedHere)
        self.assertEqual(enemyPlayer, t6_16.player)
        self.assertEqual(enemyPlayer, t6_15.player)
        self.assertEqual(-1, t5_16.player)
        self.assertEqual(enemyPlayer, t7_16.player)
        self.assertEqual(enemyPlayer, t6_15.delta.newOwner)

        # next turn
        botMap.update_turn(168)
        botMap.update_visible_tile(6, 15, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(5, 15, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(7, 15, TILE_OBSTACLE, tile_army=0)
        botMap.update_visible_tile(6, 14, enemyPlayer, tile_army=5)

        self.assertFalse(t6_15.delta.armyMovedHere)
        self.assertTrue(botMap.GetTile(6,14).delta.armyMovedHere)
        self.assertEqual(-1, botMap.GetTile(5,15).player)
        self.assertEqual(-1, botMap.GetTile(7,15).player)
        self.assertTrue(botMap.GetTile(7,15).isMountain)
        self.assertEqual(enemyPlayer, botMap.GetTile(6,14).delta.newOwner)
        self.assertEqual(-6, botMap.GetTile(6,14).delta.armyDelta)

        botMap.update()
        self.assertEqual(6, botMap.GetTile(6,15).delta.armyDelta)
        self.assertEqual(1, botMap.GetTile(6,15).army)
        self.assertEqual(enemyPlayer, botMap.GetTile(6,15).player)

        # next turn
        botMap.update_turn(169)
        botMap.update_visible_tile(6, 14, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(5, 14, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(7, 14, TILE_OBSTACLE, tile_army=0)
        botMap.update_visible_tile(6, 13, enemyPlayer, tile_army=3)

        self.assertFalse(botMap.GetTile(6,14).delta.armyMovedHere)
        self.assertTrue(botMap.GetTile(6,13).delta.armyMovedHere)
        self.assertEqual(-1, botMap.GetTile(5,14).player)
        self.assertEqual(enemyPlayer, botMap.GetTile(6,13).delta.newOwner)
        self.assertEqual(-4, botMap.GetTile(6,13).delta.armyDelta)

        botMap.update()
        self.assertEqual(4, botMap.GetTile(6,14).delta.armyDelta)
        self.assertEqual(1, botMap.GetTile(6,14).army)
        self.assertEqual(enemyPlayer, botMap.GetTile(6,14).player)

        # next turn
        botMap.update_turn(170)
        botMap.update_visible_tile(6, 13, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(5, 13, TILE_FOG, tile_army=0)
        botMap.update_visible_tile(7, 13, TILE_OBSTACLE, tile_army=0)
        botMap.update_visible_tile(6, 12, enemyPlayer, tile_army=1)

        self.assertFalse(botMap.GetTile(6,13).delta.armyMovedHere)
        self.assertTrue(botMap.GetTile(6,12).delta.armyMovedHere)
        self.assertEqual(-1, botMap.GetTile(5,13).player)
        self.assertEqual(enemyPlayer, botMap.GetTile(6,12).delta.newOwner)
        self.assertEqual(-2, botMap.GetTile(6,12).delta.armyDelta)

        botMap.update()
        self.assertEqual(2, botMap.GetTile(6,13).delta.armyDelta)
        self.assertEqual(1, botMap.GetTile(6,13).army)
        self.assertEqual(enemyPlayer, botMap.GetTile(6,13).player)

    def test_army_should_not_duplicate_backwards_on_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/army_should_not_duplicate_backwards_on_capture___Bgb7Eiba2---a--399.txtmap'

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, gen = self.load_map_and_general(mapFile, 399)

        if debugMode:
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 399)

            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

            simHost.queue_player_moves_str(general.player, "14,6 -> 15,6 -> 16,6 -> 17,6")
            simHost.queue_player_moves_str(enemyGeneral.player, "12,13 -> 12,12 -> 12,11 -> 12,10")
            self.begin_capturing_logging()
            simHost.run_sim(run_real_time=True, turn_time=2, turns=5)

        self.begin_capturing_logging()
        enemyPlayer = (gen.player + 1) & 1

        m = rawMap

        m.update_turn(400)
        # ugh, have to simulate army bonus
        m.update_visible_tile(11, 12, enemyPlayer, tile_army=4)
        m.update_visible_tile(12, 11, gen.player, tile_army=3)

        m.update_visible_tile(12, 13, TILE_FOG, tile_army=0)
        m.update_visible_tile(11, 13, TILE_FOG, tile_army=0)
        m.update_visible_tile(13, 13, TILE_OBSTACLE, tile_army=0)
        m.update_visible_tile(12, 12, enemyPlayer, tile_army=81 + 1)  # army bonus this turn

        self.assertTrue(m.GetTile(12, 12).delta.armyMovedHere)
        self.assertFalse(m.GetTile(12, 13).delta.armyMovedHere)
        self.assertEqual(enemyPlayer, m.GetTile(12, 12).delta.newOwner)
        self.assertEqual(-210, m.GetTile(12, 12).delta.armyDelta)
        self.assertEqual(0, m.GetTile(12, 13).delta.armyDelta)
        m.update()

        self.assertTrue(m.GetTile(12, 12), m.GetTile(12, 13).delta.toTile)
        self.assertEqual(m.GetTile(12, 13), m.GetTile(12, 12).delta.fromTile)

        self.assertEqual(enemyPlayer, m.GetTile(12, 12).delta.newOwner)
        self.assertEqual(enemyPlayer, m.GetTile(12, 12).player)
        self.assertEqual(enemyPlayer, m.GetTile(12, 13).player)
        self.assertEqual(210, m.GetTile(12, 13).delta.armyDelta) # army delta should have been corrected once we determine the army moved here

        # 11,13 should be a 2 because of army bonus
        self.assertEqual(2, m.GetTile(11, 13).army)
        # should have predicted 12,13s army is now 1 + 1 army bonus
        self.assertEqual(2, m.GetTile(12, 13).army)
        # should still have right players
        self.assertEqual(enemyPlayer, m.GetTile(11, 13).player)
        self.assertEqual(enemyPlayer, m.GetTile(12, 13).player)

        m.update_turn(401)
        m.update_visible_tile(12, 12, TILE_FOG, tile_army=0)
        m.update_visible_tile(11, 12, TILE_FOG, tile_army=0)
        m.update_visible_tile(13, 12, TILE_OBSTACLE, tile_army=0)
        m.update_visible_tile(12, 11, enemyPlayer, tile_army=78)  # 82 -> 3 = 3 - 81

        self.assertTrue(m.GetTile(12, 11).delta.armyMovedHere)
        self.assertFalse(m.GetTile(12, 12).delta.armyMovedHere)
        self.assertEqual(enemyPlayer, m.GetTile(12, 11).delta.newOwner)
        self.assertEqual(-81, m.GetTile(12, 11).delta.armyDelta)
        self.assertEqual(0, m.GetTile(12, 12).delta.armyDelta)
        self.assertEqual(4, m.GetTile(11, 12).army)
        m.update()

        self.assertEqual(4, m.GetTile(11, 12).army)
        # should have predicted 12,13s army is now 1
        self.assertEqual(1, m.GetTile(12, 12).army)

        self.assertEqual(enemyPlayer, m.GetTile(12, 11).delta.newOwner)
        self.assertEqual(enemyPlayer, m.GetTile(12, 11).player)
        self.assertEqual(enemyPlayer, m.GetTile(12, 12).player)

        self.assertTrue(m.GetTile(12, 11), m.GetTile(12, 12).delta.toTile)
        self.assertEqual(m.GetTile(12, 12), m.GetTile(12, 11).delta.fromTile)
        self.assertEqual(81, m.GetTile(12, 12).delta.armyDelta) # army delta should have been corrected once we determine the army moved here

        # 11,12 should still have the 3 army it already had + 1 army bonus
        # should still have right players
        self.assertEqual(enemyPlayer, m.GetTile(11, 12).player)
        self.assertEqual(enemyPlayer, m.GetTile(12, 12).player)

# TODO missing test for army collision deltas? Actually I think that test exists, somewhere
    
    def test_small_gather_adj_to_fog_should_not_double_gather_from_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/small_gather_adj_to_fog_should_not_double_gather_from_fog___rgI9fxNa3---a--451.txtmap'
        rawMap, gen = self.load_map_and_general(mapFile, 451)

        if debugMode:
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 451)

            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

            simHost.queue_player_moves_str(general.player, "8,12 -> 7,12 -> 8,12 -> 7,12")
            simHost.queue_player_moves_str(enemyGeneral.player, "10,13 -> 10,14")
            self.begin_capturing_logging()
            simHost.run_sim(run_real_time=True, turn_time=2, turns=5)

        self.begin_capturing_logging()
        enemyPlayer = (gen.player + 1) & 1

        m = rawMap

        self.assertEqual(3, m.GetTile(10, 13).army)
        self.assertEqual(3, m.GetTile(11, 13).army)
        self.assertEqual(8, m.GetTile(10, 14).army)
        self.assertEqual(6, m.GetTile(9, 13).army)

        m.update_turn(452)
        # ugh, have to simulate army bonus
        m.update_visible_tile(10, 13, enemyPlayer, tile_army=1)
        m.update_visible_tile(10, 14, enemyPlayer, tile_army=10)

        self.assertEqual(1, m.GetTile(10, 13).army)
        self.assertEqual(3, m.GetTile(11, 13).army)
        self.assertEqual(6, m.GetTile(9, 13).army)
        self.assertEqual(10, m.GetTile(10, 14).army)
        self.assertEqual(2, m.GetTile(10, 14).delta.armyDelta)
        self.assertEqual(-2, m.GetTile(10, 13).delta.armyDelta)
        m.update()

        # NONE of this should have changed
        self.assertEqual(1, m.GetTile(10, 13).army)
        self.assertEqual(3, m.GetTile(11, 13).army)
        self.assertEqual(6, m.GetTile(9, 13).army)
        self.assertEqual(10, m.GetTile(10, 14).army)
        self.assertEqual(2, m.GetTile(10, 14).delta.armyDelta)
        self.assertEqual(-2, m.GetTile(10, 13).delta.armyDelta)

        # Except, now fromTile / toTile should have updated.
        self.assertEqual(m.GetTile(10, 13), m.GetTile(10, 14).delta.fromTile)
        self.assertEqual(m.GetTile(10, 14), m.GetTile(10, 13).delta.toTile)
        # OK so this works correctly at the map level, must be the bot itself with army tracking / emergence updating the fog to 1/0...?

    def test_capture_from_fog_should_not_duplicate_out_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/capture_from_fog_should_not_duplicate_out_into_fog___rgI9fxNa3---a--485.txtmap'
        rawMap, gen = self.load_map_and_general(mapFile, 485)

        if debugMode:
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 485)

            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

            simHost.queue_player_moves_str(general.player, "8,12 -> 7,12 -> 8,12 -> 7,12")
            simHost.queue_player_moves_str(enemyGeneral.player, "7,16 -> 7,15")
            self.begin_capturing_logging()
            simHost.run_sim(run_real_time=True, turn_time=2, turns=5)

        self.begin_capturing_logging()
        enemyPlayer = (gen.player + 1) & 1

        m = rawMap

        # assert base state
        self.assertEqual(97, m.GetTile(7, 15).army)
        self.assertEqual(101, m.GetTile(7, 16).army)
        self.assertEqual(2, m.GetTile(6, 16).army)
        self.assertEqual(3, m.GetTile(8, 16).army)

        m.update_turn(486)
        m.update_visible_tile(7, 15, enemyPlayer, tile_army=3)
        m.update_visible_tile(7, 16, TILE_FOG, tile_army=0)
        m.update_visible_tile(8, 16, TILE_FOG, tile_army=0)
        m.update_visible_tile(6, 16, TILE_FOG, tile_army=0)

        self.assertEqual(3, m.GetTile(7, 15).army)
        self.assertEqual(enemyPlayer, m.GetTile(7, 15).player)
        self.assertEqual(101, m.GetTile(7, 16).army) # still has its army
        self.assertEqual(2, m.GetTile(6, 16).army)
        self.assertEqual(3, m.GetTile(8, 16).army)

        m.update()

        self.assertEqual(3, m.GetTile(7, 15).army)
        self.assertEqual(enemyPlayer, m.GetTile(7, 15).player)
        self.assertEqual(1, m.GetTile(7, 16).army, "army should have been recognized as moved to 7,15")
        self.assertEqual(enemyPlayer, m.GetTile(7, 16).player)
        self.assertEqual(2, m.GetTile(6, 16).army)
        self.assertEqual(3, m.GetTile(8, 16).army)

        self.assertEqual(m.GetTile(7, 16), m.GetTile(7, 15).delta.fromTile)
        self.assertEqual(m.GetTile(7, 15), m.GetTile(7, 16).delta.toTile)

    def test_load_map_should_load_with_actual_scores(self):
        mapFile = 'GameContinuationEntries/should_not_dance_around_armies_standing_still___HeEzmHU03---0--269.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 269, fill_out_tiles=True)
        # aTiles = 79
        # aScore = 199
        # bTiles = 76
        # bScore = 191
        self.assertEqual(79, map.players[0].tileCount)
        self.assertEqual(199, map.players[0].score)
        self.assertEqual(76, map.players[1].tileCount)
        self.assertEqual(191, map.players[1].score)
