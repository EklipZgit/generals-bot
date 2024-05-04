import typing

import SearchUtils
from DataModels import Move
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class MapTestsBase(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2)->EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_tile_deltas = True
        bot.info_render_army_emergence_values = True

        return bot

    def assertCorrectArmyDeltas(
            self,
            simHost: GameSimulatorHost,
            player: int = -1,
            excludeFogMoves: bool = False,
            minTurn = -1,
            includeAllPlayers: bool = False,
            excludeTempFogPredictions: bool = True,
            nearTile: Tile | None = None
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
                        src, dest, moveHalf = playerMapPlayer.last_move
                        move = Move(src, dest, moveHalf)
                        failures.append(
                            f'(pMap {player} had incorrect last move for player {playerMapPlayer.index}. Expected None, found {str(move)}')
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
                                src, dest, moveHalf = playerMapPlayer.last_move
                                move = Move(src, dest, moveHalf)
                                failures.append(
                                    f'(pMap {player} had incorrect last move for player {playerMapPlayer.index}. Expected {str(simPlayerMove)}, found {str(move)}')

        for player in players:
            playerMap = simHost.get_player_map(player)
            if not includeAllPlayers and player > 1:
                continue

            for tile in realMap.get_all_tiles():
                playerTile = playerMap.GetTile(tile.x, tile.y)
                if nearTile and SearchUtils.euclidean_distance(nearTile, tile) > 2.2:
                    continue
                if not playerTile.visible:
                    # TODO FIX THIS
                    if playerTile.lastSeen < playerMap.turn - 2 and excludeFogMoves:
                        continue
                    #
                    # pTilePlayer = simHost.sim.players[playerTile.player]
                    # if pTilePlayer.move_history[-1] is not None and
                    if playerTile.isGeneral != tile.isGeneral:
                        continue

                    if playerTile.isTempFogPrediction and excludeTempFogPredictions:
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

    def get_collision_tiles(self, playerMoves: typing.List[Move | None])->typing.Set[Tile]:
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

        simHost = GameSimulatorHost(map, player_with_viewer=-2, afkPlayers=[i for i in range(len(map.players))], botInitOnly=True)
        if debugMode:
            startTurn = map.turn + 1

            renderTurnBeforeSim = False
            renderTurnBeforePlayers = False
            renderP0 = False
            renderP1 = False

            # renderTurnBeforeSim = True
            # renderTurnBeforePlayers = True
            renderP0 = True
            # renderP1 = True

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
