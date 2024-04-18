import typing

import SearchUtils
from DataModels import Move
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import TILE_FOG, TILE_OBSTACLE, TILE_MOUNTAIN, Score
from test_MapBaseClass import MapTestsBase


class MapTests(MapTestsBase):
    def run_diag_test(self, debugMode, aArmy, bArmy, aMove, bMove, turn):
        # 4x4 map, with all fog scenarios covered. Each player has enough information to unequivocably determine which tile moved to where.
        data = """
|    |    |    |
aG1  a1   a1   b1
a1   a1   b1   b1
a1   a1   b1   b1
a1   b1   b1   bG1
|    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(
            data,
            turn,
            fill_out_tiles=False,
            player_index=0)

        aTile = map.GetTile(1, 1)
        bTile = map.GetTile(2, 2)
        self.run_map_delta_test(map, aTile, bTile, general, enemyGeneral, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove)

    def run_adj_test(self, debugMode, aArmy, bArmy, aMove, bMove, turn):
        # 4x4 map, with all fog scenarios covered.
        data = """
|    |    |    |
aG1  a1   a1   b1
a1   a1   b1   b1
a1   a1   b1   b1
a1   b1   b1   bG1
|    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(
            data,
            turn,
            fill_out_tiles=False,
            player_index=0)

        aTile = map.GetTile(1, 1)
        bTile = map.GetTile(2, 1)
        self.run_map_delta_test(map, aTile, bTile, general, enemyGeneral, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove)

    def run_out_of_fog_collision_test(self, debugMode: bool, aArmy: int, bArmy: int, aMove: typing.Tuple[int, int], bMove: typing.Tuple[int, int], turn: int, seenFog: bool):
        # 4x4 map, with all fog scenarios covered.
        data = """
|    |    |    |
aG1  a1   a1   b1
a1   a1   b1   b1
a1   a1   b1   b1
a1   b1   b1   bG1
|    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(
            data,
            turn,
            fill_out_tiles=False,
            player_index=0)

        aTile = map.GetTile(0, 1)
        bTile = map.GetTile(2, 1)
        self.run_map_delta_test(map, aTile, bTile, general, enemyGeneral, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, seenFog=seenFog)

    def run_fog_island_full_capture_test(self, debugMode: bool, aArmy: int, bArmy: int, bMove: typing.Tuple[int, int], turn: int, seenFog: bool, bHasNearbyVision: bool):
        # 4x4 map, with all fog scenarios covered.
        data = """
|    |    |    |
aG1  a1   a1   a1
a1   b1   a1   a1
a1   a1   a1   a1
a1   b1   b1   b1
a1   b1   b1   bG1
|    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(
            data,
            turn,
            fill_out_tiles=False,
            player_index=0)

        aTile = map.GetTile(0, 1)
        bTile = map.GetTile(1, 1)

        if not bHasNearbyVision:
            map.GetTile(1, 3).player = 0
            map.GetTile(2, 3).player = 0
            map.GetTile(3, 3).player = 0

        self.run_map_delta_test(map, aTile, bTile, general, enemyGeneral, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=(1, 0), bMove=bMove, seenFog=seenFog)

    def run_fog_island_border_capture_test(self, debugMode: bool, aArmy: int, bArmy: int, bMove: typing.Tuple[int, int], turn: int, seenFog: bool, bArmyAdjacent: bool):
        # 4x4 map, with all fog scenarios covered.
        data = """
|    |    |    |    |    |
aG1  a1   a1   a1   a1   a1
a1   a1   a1   b1   b1   a1
a1   a1   a1   a1   a1   a1
a1   a1   b1   b1   b1   b1
a1   a1   b1   b1   b1   b1
a1   b1   b1   b1   b1   bG1
|    |    |    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(
            data,
            turn,
            fill_out_tiles=False,
            player_index=0)

        aTile = map.GetTile(2, 1)
        bTile = map.GetTile(3, 1)
        if not bArmyAdjacent:
            bTile = map.GetTile(4, 1)
        self.run_map_delta_test(map, aTile, bTile, general, enemyGeneral, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=(1, 0), bMove=bMove, seenFog=seenFog)

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

        self.begin_capturing_logging()
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
        self.assertEqual(targetTile, general.delta.toTile)
        self.assertEqual(general, targetTile.delta.fromTile)

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

    def test_incorrect_city_fog_prediction_one_of_each_incorrect_adjacent(self):
        mapRaw = """
|    |    |    |    |
aG7
      
aC10
aC9
aC5       b5        bG1
|    |    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapRaw, turn=13, player_index=1)

        targetTileActuallyEnCity = map.GetTile(0, 2)
        targetTileActuallyEnCity.discovered = False
        targetTileActuallyEnCity.visible = False
        targetTileActuallyEnCity.tile = TILE_OBSTACLE
        targetTileActuallyEnCity.lastSeen = -1
        targetTileActuallyEnCity.lastMovedTurn = -1

        targetTileActuallyNeutral = map.GetTile(0, 3)
        targetTileActuallyNeutral.discovered = False
        targetTileActuallyNeutral.visible = False
        targetTileActuallyNeutral.tile = TILE_OBSTACLE
        targetTileActuallyNeutral.lastSeen = -1
        targetTileActuallyNeutral.lastMovedTurn = -1

        targetTileActuallyMountain = map.GetTile(0, 4)
        targetTileActuallyMountain.discovered = False
        targetTileActuallyMountain.visible = False
        targetTileActuallyMountain.tile = TILE_OBSTACLE
        targetTileActuallyMountain.lastSeen = -1
        targetTileActuallyMountain.lastMovedTurn = -1

        self.assertFalse(targetTileActuallyEnCity.isNeutral)
        self.assertEqual(10, targetTileActuallyEnCity.army)  # would have been 11 on this turn due to city increment, so 1 more than expected.
        self.assertEqual(0, targetTileActuallyEnCity.delta.unexplainedDelta)

        self.begin_capturing_logging()
        map.update_turn(14)
        map.update_scores([
            Score(enemyGeneral.player, map.scores[enemyGeneral.player].total + 2, map.scores[enemyGeneral.player].tiles, False),
            Score(general.player, map.scores[general.player].total + 1, map.scores[general.player].tiles, False)
        ])

        map.update_visible_tile(targetTileActuallyEnCity.x, targetTileActuallyEnCity.y, enemyGeneral.player, 12, is_city=True, is_general=False)
        # should result in delta of 1..?

        map.update_visible_tile(targetTileActuallyNeutral.x, targetTileActuallyNeutral.y, -1, 45, is_city=True, is_general=False)

        map.update_visible_tile(targetTileActuallyMountain.x, targetTileActuallyMountain.y, TILE_MOUNTAIN, 0, is_city=False, is_general=False)

        map.update()

        self.assertFalse(targetTileActuallyEnCity.isNeutral)
        self.assertEqual(12, targetTileActuallyEnCity.army)  # would have been 11 on this turn due to city increment, so 1 more than expected.
        self.assertEqual(1, targetTileActuallyEnCity.delta.unexplainedDelta)
        self.assertIn(targetTileActuallyEnCity, map.army_emergences)

        emergenceVal, emergencePlayer = map.army_emergences[targetTileActuallyEnCity]
        self.assertEqual(1, emergenceVal)
        self.assertEqual(0, emergencePlayer)

        self.assertFalse(targetTileActuallyEnCity.isMountain)
        self.assertFalse(targetTileActuallyEnCity.isUndiscoveredObstacle)
        self.assertFalse(targetTileActuallyEnCity.isObstacle)  # player cities are not obstacles
        self.assertEqual(enemyGeneral.player, targetTileActuallyEnCity.delta.oldOwner)
        self.assertEqual(enemyGeneral.player, targetTileActuallyEnCity.delta.newOwner)
        self.assertEqual(enemyGeneral.player, targetTileActuallyEnCity.player)
        self.assertTrue(targetTileActuallyEnCity.delta.armyMovedHere)
        self.assertTrue(targetTileActuallyEnCity.delta.imperfectArmyDelta)  # since it isn't neutral, we don't know for sure what happened between turns since we just gained vision.

        self.assertTrue(targetTileActuallyNeutral.isNeutral)
        self.assertEqual(45, targetTileActuallyNeutral.army)
        self.assertFalse(targetTileActuallyNeutral.isMountain)
        self.assertFalse(targetTileActuallyNeutral.isUndiscoveredObstacle)
        self.assertTrue(targetTileActuallyNeutral.isObstacle)
        self.assertEqual(enemyGeneral.player, targetTileActuallyNeutral.delta.oldOwner)
        self.assertFalse(targetTileActuallyNeutral.delta.armyMovedHere)
        self.assertFalse(targetTileActuallyNeutral.delta.imperfectArmyDelta)
        self.assertEqual(0, targetTileActuallyNeutral.delta.armyDelta)
        self.assertEqual(0, targetTileActuallyNeutral.delta.unexplainedDelta)

        self.assertEqual(0, targetTileActuallyMountain.army)
        self.assertTrue(targetTileActuallyMountain.isMountain)
        self.assertFalse(targetTileActuallyMountain.isUndiscoveredObstacle)
        self.assertTrue(targetTileActuallyMountain.isObstacle)
        self.assertEqual(enemyGeneral.player, targetTileActuallyMountain.delta.oldOwner)
        self.assertEqual(-1, targetTileActuallyMountain.delta.newOwner)
        self.assertFalse(targetTileActuallyMountain.delta.armyMovedHere)
        self.assertEqual(0, targetTileActuallyMountain.delta.armyDelta)
        self.assertEqual(0, targetTileActuallyMountain.delta.unexplainedDelta)
        self.assertFalse(targetTileActuallyMountain.delta.imperfectArmyDelta)
        self.assertFalse(targetTileActuallyMountain.isCity)
        self.assertEqual(TILE_MOUNTAIN, targetTileActuallyMountain.tile)

        self.assertEqual(1, len(map.army_emergences))  # should only be the one emergence in there.

    def test_specific_non_prio_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        self.run_fog_island_border_capture_test(debugMode=debugMode, aArmy=20, bArmy=12, bMove=(-1, 0), turn=97, seenFog=True, bArmyAdjacent=True)

    def test_incorrect_city_fog_prediction_correct_but_wrong_army(self):
        mapRaw = """
|    |    |    |    |
aG7
      
aC10
C45
M         b5        bG1
|    |    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapRaw, turn=13, player_index=1)

        targetTileActuallyEnCity = map.GetTile(0, 2)
        targetTileActuallyEnCity.discovered = False
        targetTileActuallyEnCity.visible = False
        targetTileActuallyEnCity.tile = TILE_OBSTACLE
        targetTileActuallyEnCity.lastSeen = -1
        targetTileActuallyEnCity.lastMovedTurn = -1

        self.assertFalse(targetTileActuallyEnCity.isNeutral)
        self.assertEqual(10, targetTileActuallyEnCity.army)  # would have been 11 on this turn due to city increment, so 1 more than expected.
        self.assertEqual(0, targetTileActuallyEnCity.delta.unexplainedDelta)

        self.begin_capturing_logging()
        map.update_turn(14)
        map.update_scores([
            Score(enemyGeneral.player, map.scores[enemyGeneral.player].total + 2, map.scores[enemyGeneral.player].tiles, False),
            Score(general.player, map.scores[general.player].total + 1, map.scores[general.player].tiles, False)
        ])

        map.update_visible_tile(targetTileActuallyEnCity.x, targetTileActuallyEnCity.y, enemyGeneral.player, 12, is_city=True, is_general=False)
        # should result in delta of 1..?

        map.update()

        self.assertFalse(targetTileActuallyEnCity.isNeutral)
        self.assertEqual(12, targetTileActuallyEnCity.army)  # would have been 11 on this turn due to city increment, so 1 more than expected.
        self.assertEqual(1, targetTileActuallyEnCity.delta.unexplainedDelta)
        self.assertEqual(1, targetTileActuallyEnCity.delta.armyDelta)
        self.assertIn(targetTileActuallyEnCity, map.army_emergences)

        emergenceVal, emergencePlayer = map.army_emergences[targetTileActuallyEnCity]
        self.assertEqual(1, emergenceVal)
        self.assertEqual(0, emergencePlayer)

        self.assertFalse(targetTileActuallyEnCity.isMountain)
        self.assertFalse(targetTileActuallyEnCity.isUndiscoveredObstacle)
        self.assertFalse(targetTileActuallyEnCity.isObstacle)  # player cities are not obstacles
        self.assertEqual(enemyGeneral.player, targetTileActuallyEnCity.delta.oldOwner)
        self.assertEqual(enemyGeneral.player, targetTileActuallyEnCity.delta.newOwner)
        self.assertEqual(enemyGeneral.player, targetTileActuallyEnCity.player)
        self.assertTrue(targetTileActuallyEnCity.delta.armyMovedHere)
        self.assertTrue(targetTileActuallyEnCity.delta.imperfectArmyDelta)  # since it isn't neutral, we don't know for sure what happened between turns since we just gained vision.

        self.assertEqual(1, len(map.army_emergences))  # should only be the one emergence in there.

    def test_incorrect_city_fog_prediction_was_neutral_city(self):
        mapRaw = """
|    |    |    |    |
aG7
      
M
aC9
M         b5        bG1
|    |    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapRaw, turn=13, player_index=1)

        targetTileActuallyNeutral = map.GetTile(0, 3)
        targetTileActuallyNeutral.discovered = False
        targetTileActuallyNeutral.visible = False
        targetTileActuallyNeutral.tile = TILE_OBSTACLE
        targetTileActuallyNeutral.lastSeen = -1
        targetTileActuallyNeutral.lastMovedTurn = -1

        self.begin_capturing_logging()
        map.update_turn(14)
        map.update_scores([
            Score(enemyGeneral.player, map.scores[enemyGeneral.player].total + 2, map.scores[enemyGeneral.player].tiles, False),
            Score(general.player, map.scores[general.player].total + 1, map.scores[general.player].tiles, False)
        ])

        map.update_visible_tile(targetTileActuallyNeutral.x, targetTileActuallyNeutral.y, -1, 45, is_city=True, is_general=False)

        map.update()

        self.assertTrue(targetTileActuallyNeutral.isNeutral)
        self.assertEqual(45, targetTileActuallyNeutral.army)
        self.assertFalse(targetTileActuallyNeutral.isMountain)
        self.assertFalse(targetTileActuallyNeutral.isUndiscoveredObstacle)
        self.assertTrue(targetTileActuallyNeutral.isObstacle)
        self.assertEqual(enemyGeneral.player, targetTileActuallyNeutral.delta.oldOwner)
        self.assertFalse(targetTileActuallyNeutral.delta.armyMovedHere)
        self.assertFalse(targetTileActuallyNeutral.delta.imperfectArmyDelta)
        self.assertEqual(0, targetTileActuallyNeutral.delta.unexplainedDelta)
        self.assertEqual(0, targetTileActuallyNeutral.delta.armyDelta)

        self.assertEqual(0, len(map.army_emergences))  # should only be the one emergence in there.

    def test_incorrect_city_fog_prediction_was_mountain(self):
        mapRaw = """
|    |    |    |    |
aG7
      
M 
M
aC5       b5        bG1
|    |    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapRaw, turn=13, player_index=1)

        targetTileActuallyMountain = map.GetTile(0, 4)
        targetTileActuallyMountain.discovered = False
        targetTileActuallyMountain.visible = False
        targetTileActuallyMountain.tile = TILE_OBSTACLE
        targetTileActuallyMountain.lastSeen = -1
        targetTileActuallyMountain.lastMovedTurn = -1

        self.begin_capturing_logging()
        map.update_turn(14)
        map.update_scores([
            Score(enemyGeneral.player, map.scores[enemyGeneral.player].total + 2, map.scores[enemyGeneral.player].tiles, False),
            Score(general.player, map.scores[general.player].total + 1, map.scores[general.player].tiles, False)
        ])

        map.update_visible_tile(targetTileActuallyMountain.x, targetTileActuallyMountain.y, TILE_MOUNTAIN, 0, is_city=False, is_general=False)

        map.update()

        self.assertEqual(0, targetTileActuallyMountain.army)
        self.assertTrue(targetTileActuallyMountain.isMountain)
        self.assertFalse(targetTileActuallyMountain.isUndiscoveredObstacle)
        self.assertTrue(targetTileActuallyMountain.isObstacle)
        self.assertEqual(enemyGeneral.player, targetTileActuallyMountain.delta.oldOwner)
        self.assertEqual(-1, targetTileActuallyMountain.delta.newOwner)
        self.assertEqual(0, targetTileActuallyMountain.delta.armyDelta)
        self.assertEqual(0, targetTileActuallyMountain.delta.unexplainedDelta)
        self.assertFalse(targetTileActuallyMountain.delta.imperfectArmyDelta)
        self.assertFalse(targetTileActuallyMountain.isCity)
        self.assertEqual(TILE_MOUNTAIN, targetTileActuallyMountain.tile)
        self.assertFalse(targetTileActuallyMountain.delta.armyMovedHere)

        self.assertEqual(0, len(map.army_emergences))  # should only be the one emergence in there.

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

            simHost.queue_player_moves_str(enemyGeneral.player, "6,16->6,15->6,14->6,13")
            simHost.queue_player_moves_str(general.player, "5,5->6,5->7,5->8,5")
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/army_should_not_duplicate_backwards_on_capture___Bgb7Eiba2---a--399.txtmap'

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, gen = self.load_map_and_general(mapFile, 399)
        #
        # if debugMode:
        #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 399)
        #
        #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        #
        #     simHost.queue_player_moves_str(general.player, "14,6->15,6->16,6->17,6")
        #     simHost.queue_player_moves_str(enemyGeneral.player, "12,13->12,12->12,11->13,11")
        #     self.begin_capturing_logging()
        #     simHost.run_sim(run_real_time=True, turn_time=2, turns=5)

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
        m.update_visible_tile(12, 11, enemyPlayer, tile_army=78)  # 82->3 = 3 - 81

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

    def test_run_adj_collision_mutual(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # DONT CHANGE THIS ONE, IT WAS FAILING AND BYPASSING THE COLLISION ASSERTS...
        self.run_adj_test(debugMode=debugMode, aArmy=20, bArmy=5, aMove=(1, 0), bMove=(-1, -0), turn=96)
    
    def test_small_gather_adj_to_fog_should_not_double_gather_from_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/small_gather_adj_to_fog_should_not_double_gather_from_fog___rgI9fxNa3---a--451.txtmap'
        rawMap, gen = self.load_map_and_general(mapFile, 451)

        if debugMode:
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 451)

            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

            simHost.queue_player_moves_str(general.player, "8,12->7,12->8,12->7,12")
            simHost.queue_player_moves_str(enemyGeneral.player, "10,13->10,14")
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/capture_from_fog_should_not_duplicate_out_into_fog___rgI9fxNa3---a--485.txtmap'
        rawMap, gen = self.load_map_and_general(mapFile, 485)

        if debugMode:
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 485)

            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

            simHost.queue_player_moves_str(general.player, "8,12->7,12->8,12->7,12")
            simHost.queue_player_moves_str(enemyGeneral.player, "7,16->7,15")
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

    def test_generate_all_fog_island_border_capture_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        bMoveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for bArmyAdjacent in [True, False]:
            for bMove in bMoveOpts:
                for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                    for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                        for turn in [96, 97]:
                            for seenFog in [True, False]:
                                with self.subTest(aArmy=aArmy, bArmy=bArmy, bMove=bMove, turn=turn, seenFog=seenFog, bArmyAdjacent=bArmyAdjacent):
                                    # 1905
                                    # 113
                                    # 0
                                    # 261~
                                    # 197~
                                    # 181
                                    # 133
                                    # 181
                                    # 0
                                    # 145
                                    # 17
                                    # 0
                                    # 0
                                    self.run_fog_island_border_capture_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, bMove=bMove, turn=turn, seenFog=seenFog, bArmyAdjacent=bArmyAdjacent)

    def test_run_one_off_fog_island_border_capture_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        self.run_fog_island_border_capture_test(debugMode=debugMode, aArmy=12, bArmy=11, bMove=(0, -1), turn=96, seenFog=True, bArmyAdjacent=True)

    def test_generate_all_fog_island_full_capture_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        bMoveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for bHasNearbyVision in [True, False]:
            for bMove in bMoveOpts:
                for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                    for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                        for turn in [96, 97]:
                            for seenFog in [True, False]:
                                with self.subTest(aArmy=aArmy, bArmy=bArmy, bMove=bMove, turn=turn, seenFog=seenFog, bHasNearbyVision=bHasNearbyVision):
                                    # 1329
                                    # 1073
                                    # 1073
                                    # 177
                                    # 697~
                                    # 569~
                                    # 921
                                    # 521
                                    # 425
                                    # 521
                                    # 161 after fixing move determinism assert detection
                                    # 0
                                    # 209
                                    # 161
                                    # 209
                                    # 145
                                    self.run_fog_island_full_capture_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, bMove=bMove, turn=turn, seenFog=seenFog, bHasNearbyVision=bHasNearbyVision)

    def test_run_one_off_fog_island_full_capture_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO
        self.run_fog_island_full_capture_test(debugMode=debugMode, aArmy=9, bArmy=15, bMove=(1, 0), turn=97, seenFog=False, bHasNearbyVision=True)

    def test_generate_all_out_of_fog_collision_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        aMoveOpts = [None, (1, 0), (0, 1)]  # no left or up
        bMoveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for aMove in aMoveOpts:
            for bMove in bMoveOpts:
                for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                    for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                        for turn in [96, 97]:
                            for seenFog in [True, False]:
                                with self.subTest(aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn, seenFog=seenFog):
                                    # 0
                                    # 69
                                    self.run_out_of_fog_collision_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn, seenFog=seenFog)

    def test_run_one_off_out_of_fog_collision_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        self.run_out_of_fog_collision_test(debugMode=debugMode, aArmy=8, bArmy=5, aMove=(0, 1), bMove=(0, -1), turn=96, seenFog=False)

    def test_generate_all_adjacent_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        moveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for aMove in moveOpts:
            for bMove in moveOpts:
                for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                    for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                        for turn in [96, 97]:
                            with self.subTest(aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn):
                                # 0
                                # 163~
                                # 99~
                                # 91
                                # 67
                                # 19
                                # 91
                                # 163
                                # 73  after fixing move determinism assert detection
                                # 0
                                # 77
                                # 73
                                self.run_adj_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn)

    def test_run_one_off_adj_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO
        self.run_adj_test(debugMode=debugMode, aArmy=20, bArmy=20, aMove=(1, 0), bMove=(-1, 0), turn=97)

    def test_generate_all_diagonal_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        moveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for aMove in moveOpts:
            for bMove in moveOpts:
                for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                    for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                        for turn in [96, 97]:
                            with self.subTest(aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn):
                                # 0
                                # 0
                                self.run_diag_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn)

    def test_run_one_off_diag_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        self.run_diag_test(debugMode=debugMode, aArmy=11, bArmy=9, aMove=(1, 0), bMove=(0, -1), turn=96)

    def test_should_not_turn_cities_neutral_on_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_turn_cities_neutral_on_capture___Human.exe-TEST__fd14d74c-6889-4816-85b9-9a692c3f397e---0--297.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 297, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=297)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->8,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        city = playerMap.GetTile(8, 5)
        self.assertEqual(enemyGeneral.player, city.player)

    def test_should_not_leave_captured_city_as_own_city_in_the_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for turn in [396, 397, 399]:
            for isCity in [False, True]:
                for playerMoves in [True, False]:
                    with self.subTest(turn=turn, isCity=isCity, playerMoves=playerMoves):
                        # all pass
                        mapFile = 'GameContinuationEntries/should_not_leave_captured_city_as_own_city_in_the_fog___UTLSPeD5A---0--396.txtmap'
                        rawData = TextMapLoader.get_map_raw_string_from_file(mapFile)
                        if not isCity:
                            rawData = rawData.replace('aC60', 'a60 ')
                        map, general, enemyGeneral = self.load_map_and_generals_from_string(rawData, 396, fill_out_tiles=True)

                        rawMap, _ = self.load_map_and_general_from_string(rawData, respect_undiscovered=True, turn=396)

                        self.enable_search_time_limits_and_disable_debug_asserts()
                        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                        simHost.queue_player_moves_str(enemyGeneral.player, '6,21->7,21')
                        if playerMoves:
                            simHost.queue_player_moves_str(general.player, '7,21->6,21')
                        bot = self.get_debug_render_bot(simHost, general.player)
                        playerMap = simHost.get_player_map(general.player)

                        self.begin_capturing_logging()
                        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
                        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
                        self.assertNoFriendliesKilled(map, general)

                        self.assertOwned(enemyGeneral.player, playerMap.GetTile(7, 21))

    def test_fog_island_capture_with_vision_both_sides__from_after_capture_visible(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapRaw = """
|    |    |    |    |
aG15
b1   a1   b1
b12  a1   b1
b1   a1   b1 
b1   b1   b1         
b1   b1   a1         


          b5        bG1
|    |    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapRaw, turn=50, player_index=0)

        rawMap, _ = self.load_map_and_general_from_string(mapRaw, turn=50, player_index=general.player, respect_undiscovered=True)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '0,2->1,2->1,3')
        simHost.queue_player_moves_str(general.player, 'None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwned(enemyGeneral.player, playerMap.GetTile(1, 3))

    def test_fog_island_capture_with_vision_both_sides__from_after_capture_NOT_visible(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapRaw = """
|    |    |    |    |
aG15
b1   a1   b1
     b1   b1
b12  a1   b1 
b1   b1   b1         
b1   b1   a1         


          b5        bG1
|    |    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapRaw, turn=50, player_index=0)

        rawMap, _ = self.load_map_and_general_from_string(mapRaw, turn=50, player_index=general.player, respect_undiscovered=True)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '0,3->1,3')
        simHost.queue_player_moves_str(general.player, 'None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwned(enemyGeneral.player, playerMap.GetTile(1, 3))


    # THIS IS ALL BEFORE SPLITTING 2v2 OUT
    # 4590 failed, 23,663 passed
    # 4904 failed, 23,353 passed after fixing move into fog issue
    # 4904 failed, 23,354 passed after fixing city capture at fog border issue
    # 5095 failed, 23,177 passed after ??? changes that were made since last test run....
    # 8485 failed, 19,787 passed with the current changes
    # AFTER SPLITTING 2v2 OUT
    # 295f, 19,187p