import time
import typing

import EarlyExpandUtils
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase, Tile, TILE_FOG, TILE_OBSTACLE, TILE_MOUNTAIN, Score
from bot_ek0x45 import EklipZBot
from test_MapBaseClass import MapTestsBase

ALL_SCENARIOS_TEAM_MAP = data = """
|    |    |    |    |    
          b60
b20  cG3  aG55 c2          
          c0
d3   d3             
a5   b5                    
c3   c3
               b1     
     a55  C45  bC5  b1      
     aC5       b55     
     a1        a0       
                    
          d0          
     d2   bG55 dG3  a20
          a60       
|    |    |    |    |    
player_index=0
teams=0,1,0,1
mode=team
bot_target_player=1
aTiles=7
bTiles=8
cTiles=5
dTiles=5
"""


class MapTests(MapTestsBase):
    def run_all_scenarios_team_test(self, debugMode, aMove, bMove, turn):
        # 4x4 map, with all fog scenarios covered. Each player has enough information to unequivocably determine which tile moved to where.

        map, general, allyGen, enemyGen, enemyAllyGen = self.load_map_and_generals_2v2_from_string(ALL_SCENARIOS_TEAM_MAP, turn)
        # give them COMPLETELY separate maps so they can't possibly affect each other during the diff
        engineMap, _, _, _, _ = self.load_map_and_generals_2v2_from_string(ALL_SCENARIOS_TEAM_MAP, turn)

        aMovement = None
        aTile = None
        aArmy = 0
        if aMove is not None:
            aFromTileXY, aToTileXY, aMoveHalf = aMove
            aX, aY = aFromTileXY
            aDX, aDY = aToTileXY
            aTile = map.GetTile(aX, aY)
            aMovement = (aDX - aX, aDY - aY)
            aArmy = aTile.army

        bMovement = None
        bTile = None
        bArmy = 0
        if bMove is not None:
            bFromTileXY, bToTileXY, bMoveHalf = bMove
            bX, bY = bFromTileXY
            bDX, bDY = bToTileXY
            bTile = map.GetTile(bX, bY)
            bMovement = (bDX - bX, bDY - bY)
            bArmy = bTile.army

        self.run_map_delta_test(map, aTile, bTile, general, allyGen, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMovement, bMove=bMovement, includeAllPlayerMaps=True)

    def run_team_adj_test(self, debugMode, aArmy, bArmy, aMove, bMove, targetTileFriendly, turn):
        # 4x4 map, with all fog scenarios covered. Each player has enough information to unequivocably determine which tile moved to where.
        data = """
|    |    |    |
aG1  a1   a1   b1
cG1  a1   b1   b1
a1   a1   b1   dG1
a1   b1   b1   bG1
|    |    |    |
mode=team
teams=1,1,2,2
player_index=0
bot_target_player=2
aUsername=[Bot] Sora_ai_ek
aTiles=32
bUsername=[Bot] Sora_ai_2
bTiles=27
cUsername=Bot EklipZ_ai_2
cTiles=25
dUsername=EklipZ_0x45
dTiles=27
"""
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2_from_string(
            data,
            turn,
            fill_out_tiles=True,
            player_index=0)

        tgTile = map.GetTile(1, 2)
        tgTile2 = map.GetTile(2, 1)

        if not targetTileFriendly:
            tgTile.player = 2
            tgTile2.player = 2

        aTile = map.GetTile(1, 1)
        bTile = map.GetTile(2, 2)
        self.run_map_delta_test(map, aTile, bTile, general, allyGen, debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove)

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

    def test_generate_all_team_adjacent_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        moveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for aMove in moveOpts:
            for bMove in moveOpts:
                for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                    for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                        for targetTileFriendly in [False, True]:
                            for turn in [96, 97]:
                                with self.subTest(aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, targetTileFriendly=targetTileFriendly, turn=turn):
                                    # 1667
                                    # 4501
                                    self.run_team_adj_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, targetTileFriendly=targetTileFriendly, turn=turn)

    def test_run_one_off_team_adj_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        self.run_team_adj_test(debugMode=debugMode, aArmy=9, bArmy=12, aMove=(1, 0), bMove=(1, 0), targetTileFriendly=False, turn=97)

    def test_generate_all_all_scenarios_team_playground_scenarios(self):
        outerMap, general, allyGen, enemyGen, enemyAllyGen = self.load_map_and_generals_2v2_from_string(ALL_SCENARIOS_TEAM_MAP, 0)

        frTiles = SearchUtils.where(outerMap.players[general.player].tiles, lambda t: t.army > 1)

        enTiles = []

        enTiles.extend(SearchUtils.where(outerMap.players[allyGen.player].tiles, lambda t: t.army > 1))
        enTiles.extend(SearchUtils.where(outerMap.players[enemyAllyGen.player].tiles, lambda t: t.army > 1))
        # enTiles.extend(SearchUtils.where(outerMap.players[enemyGen.player].tiles, lambda t: t.army > 1))

        allFrMoves = []
        allEnMoves = []

        for tile in frTiles:
            for movable in tile.movable:
                allFrMoves.append(Move(tile, movable, move_half=False))
                # allFrMoves.append(Move(tile, movable, move_half=True))
        for tile in enTiles:
            for movable in tile.movable:
                allEnMoves.append(Move(tile, movable, move_half=False))
                # allEnMoves.append(Move(tile, movable, move_half=True))

        allFrMoves.append(None)
        allEnMoves.append(None)

        # for turn in [148, 149, 150]:
        for turn in [120]:
            for playerMove in allFrMoves:
                for otherMove in allEnMoves:
                    with self.subTest(turn=turn, playerMove=playerMove, otherMove=otherMove):
                        aMove = None
                        bMove = None
                        if playerMove:
                            aMove = ((playerMove.source.x, playerMove.source.y), (playerMove.dest.x, playerMove.dest.y), playerMove.move_half)
                        if otherMove:
                            bMove = ((otherMove.source.x, otherMove.source.y), (otherMove.dest.x, otherMove.dest.y), otherMove.move_half)
                        self.run_all_scenarios_team_test(debugMode=False, aMove=aMove, bMove=bMove, turn=turn)

    def test_run_one_off__all_scenarios_team_playground(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        self.begin_capturing_logging()
        self.run_all_scenarios_team_test(debugMode=debugMode, aMove=((2, 1), (3, 1), True), bMove=((0, 1), (1, 1), True), turn=96)
    
    def test_should_not_think_2v2_move_is_from_neut_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_think_2v2_move_is_from_neut_city___HeB_SpEW6---2--65.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 65, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=65)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=2, playerMapVision=rawMap, allAfkExceptMapPlayer=False, botInitOnly=True)
        simHost.queue_player_moves_str(0, '6,7->5,7  None')
        simHost.queue_player_moves_str(3, '5,6->6,6  None')
        simHost.queue_player_moves_str(1, 'None  None')
        simHost.queue_player_moves_str(2, 'None  None')
        # bot = self.get_debug_render_bot(simHost, general.player)
        # playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
        self.assertIsNone(winner)
    
    def test_should_handle_fog_island_capture_in_2v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_handle_fog_island_capture_in_2v2___F6_mInEvD---0--264.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 264, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=264)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,14->11,15->11,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=3)
        self.assertNoFriendliesKilled(map, general, allyGen)

    def test_should_not_try_to_set_ally_general_to_other_player(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for move in [0, -1, 1]:
            with self.subTest(move=move):
                mapFile = 'GameContinuationEntries/should_not_try_to_set_ally_general_to_other_player___ydcsakF7K---2--237.txtmap'
                map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 237, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=237)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False, botInitOnly=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '17,13->17,12->17,11')
                if move != 0:
                    simHost.queue_player_moves_str(allyGen.player, f'17,11->17,{11+move}')
                else:
                    simHost.queue_player_moves_str(allyGen.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
                self.assertNoFriendliesKilled(map, general, allyGen)

# 4788f, 4005p