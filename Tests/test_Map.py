import time

import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile, TILE_FOG
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


