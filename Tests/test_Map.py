import time
import typing

import EarlyExpandUtils
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase, Tile, TILE_FOG, TILE_OBSTACLE, TILE_MOUNTAIN, Score


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


class MapTests(TestBase):
    def assertCorrectArmyDeltas(
            self,
            simHost: GameSimulatorHost,
            player: int = -1,
            excludeFogMoves: bool = False,
            minTurn = -1,
            includeAllPlayers: bool = False
    ):
        realMap = simHost.sim.sim_map
        if realMap.turn <= minTurn:
            return

        players = [i for i in range(len(simHost.sim.players))]
        if player > -1:
            players = [player]

        failures = []

        skipFromToCollisionTiles = set()
        # # WHY WOULD WE SKIP COLLISION TILES, THIS IS MESSING UP test_run_adj_collision_mutual TEST!?
        # if len(simHost.sim.moves_history) > 0:
        #     skipFromToCollisionTiles = self.get_collision_tiles(simHost.sim.moves_history[-1])

        killedOrIndeterminateMoves: typing.Set[Move] = set()
        for player in players:
            if not includeAllPlayers and player > 1:
                continue

            playerMap = simHost.get_player_map(player)
            # playerBot = simHost.get_bot(player)
            # if playerBot.armyTracker.lastTurn != realMap.turn:
            #     playerBot.init_turn()

            for playerMapPlayer in playerMap.players:
                if not includeAllPlayers and playerMapPlayer.index > 1:
                    continue
                if len(simHost.sim.moves_history) > 0:
                    simPlayerMove = simHost.sim.moves_history[-1][playerMapPlayer.index]

                    if simPlayerMove is None and playerMapPlayer.last_move is not None:
                        failures.append(
                            f'(pMap {player} had incorrect last move for player {playerMapPlayer.index}. Expected None, found {str(playerMapPlayer.last_move)}')
                    elif simPlayerMove is not None:
                        # ignore if the target players move got nuked with priority:
                        simDest = simHost.sim.sim_map.GetTile(simPlayerMove.dest.x, simPlayerMove.dest.y)
                        if simDest.delta.armyDelta == 0:
                            continue
                        simSrc = simHost.sim.sim_map.GetTile(simPlayerMove.source.x, simPlayerMove.source.y)
                        simDest = simHost.sim.sim_map.GetTile(simPlayerMove.dest.x, simPlayerMove.dest.y)
                        priorityKillerMoves = []
                        for i, move in enumerate(simHost.sim.moves_history[-1]):
                            if i == playerMapPlayer.index:
                                continue
                            if move is None:
                                continue
                            if (
                                    move.dest.x == simSrc.x
                                    and move.dest.y == simSrc.y
                                    and MapBase.player_had_priority_over_other(i, playerMapPlayer.index, simHost.sim.turn)
                                    and move.army_moved >= simSrc.delta.oldArmy - 1
                            ):
                                priorityKillerMoves.append(move)

                            if (
                                    move.dest.x == simSrc.x
                                    and move.dest.y == simSrc.y
                                    and move.source.x == simDest.x
                                    and move.source.y == simDest.y
                                    and move.army_moved >= simSrc.delta.oldArmy - 1
                            ):
                                # then this is a collision and doesn't have enough information to differentiate between
                                priorityKillerMoves.append(move)

                        if len(priorityKillerMoves) > 0:
                            killedOrIndeterminateMoves.add(simPlayerMove)
                            continue

                        if playerMapPlayer.last_move is None:
                            failures.append(
                                f'(pMap {player} had incorrect last move for player {playerMapPlayer.index}. Expected {str(simPlayerMove)}, found None')
                        else:
                            pSource, pDest, movedHalf = playerMapPlayer.last_move
                            if (
                                    simPlayerMove.source.x != pSource.x
                                    or simPlayerMove.source.y != pSource.y
                                    or simPlayerMove.dest.x != pDest.x
                                    or simPlayerMove.dest.y != pDest.y
                                    or simPlayerMove.move_half != movedHalf
                            ):
                                failures.append(
                                    f'(pMap {player} had incorrect last move for player {playerMapPlayer.index}. Expected {str(simPlayerMove)}, found {str(playerMapPlayer.last_move)}')

        for player in players:
            playerMap = simHost.get_player_map(player)
            if not includeAllPlayers and player > 1:
                continue

            for tile in realMap.get_all_tiles():
                playerTile = playerMap.GetTile(tile.x, tile.y)
                if not playerTile.visible:
                    # TODO FIX THIS
                    if playerTile.lastSeen < playerMap.turn - 2 and excludeFogMoves:
                        continue
                    #
                    # pTilePlayer = simHost.sim.players[playerTile.player]
                    # if pTilePlayer.move_history[-1] is not None and
                    if playerTile.isGeneral != tile.isGeneral:
                        continue

                if not playerTile.discovered and playerTile.army == 0 and playerTile.player == -1:
                    continue

                if playerTile.army != tile.army:
                    failures.append(f'(pMap {player} tile {str(tile)}) expected tile.army {tile.army} on {repr(tile)}, found {playerTile.army} on {repr(playerTile)}')
                if playerTile.player != tile.player:
                    failures.append(f'(pMap {player} tile {str(tile)}) expected player {tile.player} on {repr(tile)}, found {playerTile.player} on {repr(playerTile)}')
                if playerTile.isCity != tile.isCity:
                    failures.append(f'(pMap {player} tile {str(tile)}) expected isCity {tile.isCity} on {repr(tile)}, found {playerTile.isCity} on {repr(playerTile)}')

                if not playerTile.delta.discovered:
                    # these asserts are not valid the turn of discovery...?
                    if playerTile.delta.armyDelta != tile.delta.armyDelta:
                        failures.append(f'(pMap {player} tile {str(tile)}) expected tile.delta.armyDelta {tile.delta.armyDelta} on {repr(tile)}, found {playerTile.delta.armyDelta} on {repr(playerTile)}')
                    if playerTile.delta.oldArmy != tile.delta.oldArmy:
                        failures.append(f'(pMap {player} tile {str(tile)}) expected delta.oldArmy {tile.delta.oldArmy} on {repr(tile)}, found {playerTile.delta.oldArmy} on {repr(playerTile)}')
                    if playerTile.delta.oldOwner != tile.delta.oldOwner:
                        failures.append(f'(pMap {player} tile {str(tile)}) expected delta.oldOwner {tile.delta.oldOwner} on {repr(tile)}, found {playerTile.delta.oldOwner} on {repr(playerTile)}')
                if playerTile.delta.newOwner != tile.delta.newOwner:
                    failures.append(f'(pMap {player} tile {str(tile)}) expected delta.newOwner {tile.delta.newOwner} on {repr(tile)}, found {playerTile.delta.newOwner} on {repr(playerTile)}')
                if playerTile not in skipFromToCollisionTiles:
                    if playerTile.delta.fromTile != tile.delta.fromTile:
                        # a tile can be moved to from multiple tiles at once. However a tile cannot move TO multiple tiles
                        # at once, so cross reference the mismatched froms corresponding to-tiles in the real map.
                        # If they match, then this mismatch is fine.
                        fMessage = f'(pMap {player} tile {str(tile)}) expected delta.fromTile {str(tile.delta.fromTile)} on {repr(tile)}, found {str(playerTile.delta.fromTile)} on {repr(playerTile)}'
                        # all bets are off when the dest tile has no delta and both players moved at each others armies. Both players think their move took effect and the other player didn't move, as those two cases are indistinguishable from each players perspective.
                        if playerTile.delta.fromTile is None:
                            if Move(tile.delta.fromTile, tile) not in killedOrIndeterminateMoves:
                                failures.append(fMessage)
                        else:
                            realPlayerFrom = realMap.GetTile(playerTile.delta.fromTile.x, playerTile.delta.fromTile.y)
                            realFrom = tile.delta.fromTile
                            if realFrom is None:
                                if Move(realPlayerFrom, playerTile) not in killedOrIndeterminateMoves:
                                    failures.append(fMessage)
                            elif realPlayerFrom.delta.toTile != realFrom.delta.toTile and Move(realFrom, realFrom.delta.toTile) not in killedOrIndeterminateMoves:
                                failures.append(fMessage)

                    if playerTile.delta.toTile != tile.delta.toTile:
                        fMessage = f'(pMap {player} tile {str(tile)}) expected delta.toTile {str(tile.delta.toTile)} on {repr(tile)}, found {str(playerTile.delta.toTile)} on {repr(playerTile)}'
                        if tile.delta.toTile is None:
                            if Move(playerTile, playerTile.delta.toTile) not in killedOrIndeterminateMoves:
                                failures.append(fMessage)
                        elif playerTile.delta.toTile is None:
                            if Move(tile, tile.delta.toTile) not in killedOrIndeterminateMoves:
                                failures.append(fMessage)
                        else:
                            failures.append(fMessage)

        if len(failures) > 0:
            self.fail(f'TURN {simHost.sim.turn}\r\n' + '\r\n'.join(failures))

    def get_collision_tiles(self, playerMoves: typing.List[Move | None]) -> typing.Set[Tile]:
        ignoreCollisions: typing.Set[Tile] = set()
        for pp, pMove in enumerate(playerMoves):
            if pMove is None:
                continue
            for op, opMove in enumerate(playerMoves):
                if opMove is None:
                    continue
                if pMove == opMove:
                    continue
                if (
                        pMove.source.x == opMove.dest.x
                        and pMove.source.y == opMove.dest.y
                        and pMove.dest.x == opMove.source.x
                        and pMove.dest.y == opMove.source.y
                ):
                    # then these moves collided completely and the players will not be able to differentiate whether
                    # the player with the smaller army tile made a move at all.
                    if pMove.source.army - 1 < opMove.source.army:
                        # then cant differentiate this from no move
                        ignoreCollisions.add(pMove.source)
                    if opMove.source.army - 1 < pMove.source.army:
                        # then cant differentiate this from no move
                        ignoreCollisions.add(pMove.dest)
        return ignoreCollisions

    def run_map_delta_test(
            self,
            map: MapBase,
            aTile: Tile,
            bTile: Tile,
            general: Tile,
            enemyGeneral: Tile,
            debugMode: bool,
            aArmy: int,
            bArmy: int,
            aMove: typing.Tuple[int, int] | None,
            bMove: typing.Tuple[int, int] | None,
            seenFog: bool = True,
            includeAllPlayerMaps: bool = False,
    ):
        if aTile is not None:
            aTile.army = aArmy
        if bTile is not None:
            bTile.army = bArmy

        simHost = GameSimulatorHost(map, player_with_viewer=-2, afkPlayers=[i for i in range(len(map.players))])
        if debugMode:
            startTurn = map.turn + 1

            renderTurnBeforeSim = False
            renderTurnBeforePlayers = False
            renderP0 = False
            renderP1 = False

            renderTurnBeforeSim = True
            # renderTurnBeforePlayers = True
            renderP0 = True
            renderP1 = True

            def mapRenderer():
                if map.turn >= startTurn:
                    if map.turn > startTurn:
                        # self.render_sim_map_from_all_perspectives(simHost.sim)
                        if renderP0:
                            self.render_map(simHost.get_player_map(0), includeTileDiffs=True, infoString='p0')
                        if renderP1:
                            self.render_map(simHost.get_player_map(1), includeTileDiffs=True, infoString='p1')
                    else:
                        if renderTurnBeforeSim:
                            self.render_map(simHost.sim.sim_map, includeTileDiffs=True)
                        if renderTurnBeforePlayers:
                            if renderP0:
                                self.render_map(simHost.get_player_map(0), includeTileDiffs=True, infoString='p0')
                            if renderP1:
                                self.render_map(simHost.get_player_map(1), includeTileDiffs=True, infoString='p1')

            simHost.run_between_turns(mapRenderer)

        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost, includeAllPlayers=includeAllPlayerMaps))

        if seenFog:
            for player in map.players:
                simHost.apply_map_vision(player=player.index, rawMap=map)

        # simHost.sim.sim_map.USE_OLD_MOVEMENT_DETECTION = False
        # simHost.get_player_map(0).USE_OLD_MOVEMENT_DETECTION = False
        # simHost.get_player_map(1).USE_OLD_MOVEMENT_DETECTION = False

        if aMove is not None:
            aX, aY = aMove
            simHost.queue_player_moves_str(general.player,
                                           f'None  {aTile.x},{aTile.y}->{aTile.x + aX},{aTile.y + aY}  None')
        else:
            simHost.queue_player_moves_str(general.player, f'None  None  None')

        if bMove is not None:
            bX, bY = bMove
            simHost.queue_player_moves_str(enemyGeneral.player,
                                           f'None  {bTile.x},{bTile.y}->{bTile.x + bX},{bTile.y + bY}  None')
        else:
            simHost.queue_player_moves_str(enemyGeneral.player, f'None  None  None')

        if debugMode:
            self.begin_capturing_logging()
        simHost.run_sim(run_real_time=False, turn_time=5.5, turns=3)
        if debugMode:
            self.stop_capturing_logging()

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
                                    self.run_fog_island_border_capture_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, bMove=bMove, turn=turn, seenFog=seenFog, bArmyAdjacent=bArmyAdjacent)

    def test_run_one_off_fog_island_border_capture_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO!!
        self.run_fog_island_border_capture_test(debugMode=debugMode, aArmy=8, bArmy=9, bMove=(-1, 0), turn=96, seenFog=False, bArmyAdjacent=True)

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
                                    self.run_fog_island_full_capture_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, bMove=bMove, turn=turn, seenFog=seenFog, bHasNearbyVision=bHasNearbyVision)

    def test_run_one_off_fog_island_full_capture_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO
        self.run_fog_island_full_capture_test(debugMode=debugMode, aArmy=5, bArmy=2, bMove=(1, 0), turn=96, seenFog=True, bHasNearbyVision=True)

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
                                self.run_diag_test(debugMode=debugMode, aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove, turn=turn)

    def test_run_one_off_diag_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        self.run_diag_test(debugMode=debugMode, aArmy=5, bArmy=15, aMove=(0, 1), bMove=(1, 0), turn=96)

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
        simHost = GameSimulatorHost(map, player_with_viewer=2, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(0, '6,7->5,7  None')
        simHost.queue_player_moves_str(3, '5,6->6,6  None')
        simHost.queue_player_moves_str(1, 'None  None')
        simHost.queue_player_moves_str(2, 'None  None')
        # bot = simHost.get_bot(general.player)
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
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,14->11,15->11,16')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertCorrectArmyDeltas(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=3)
        self.assertNoFriendliesKilled(map, general, allyGen)

    # 4590 failed, 23,663 passed