import logbook
import typing

import SearchUtils
from BotModules.BotStateQueries import BotStateQueries
from DangerAnalyzer import ThreatObj
from Interfaces import MapMatrixInterface, TilePlanInterface
from Path import Path
from Gather import GatherCapturePlan
from ViewInfo import PathColorer
from Models.Move import Move
from base.client.map import Tile


class BotPathingUtils:
    @staticmethod
    def get_undiscovered_count_on_path(bot, path: Path) -> int:
        numFog = 0
        for t in path.tileList:
            if not t.discovered:
                numFog += 1
        return numFog

    @staticmethod
    def get_first_path_move(bot, path: TilePlanInterface):
        return path.get_first_move()

    @staticmethod
    def is_move_safe_valid(bot, move, allowNonKill=True):
        if move is None:
            return False
        if move.source == bot.general:
            return BotStateQueries.general_move_safe(bot, move.dest)
        if move.source.player != move.dest.player and move.source.army - 2 < move.dest.army and not allowNonKill:
            logbook.info(
                f"{move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} was not a move that killed the dest tile")
            return False
        return True

    @staticmethod
    def continue_cur_path(bot, threat: ThreatObj | None, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if bot.expansion_plan.includes_intercept:
            bot.curPath = None
            bot.viewInfo.add_info_line(f'clearing curPath because expansion includes intercept')
            return None

        if bot.curPath is None:
            return None

        nextMove = bot.curPath.get_first_move()

        if nextMove is None:
            bot.info(f'curPath None move. curPath: {bot.curPath}')
            try:
                bot.curPath.pop_first_move()
            except:
                bot.curPath = None
            return None

        if nextMove.source not in nextMove.dest.movable:
            bot.info(f'!!!!!! curPath returned invalid move {nextMove}, nuking curPath and continuing...')
            bot.curPath = None
            return None

        inc = 0
        while (
                nextMove
                and (
                   nextMove.source.army <= 1
                   or nextMove.source.player != bot._map.player_index
                )
        ):
            inc += 1
            if nextMove.source.army <= 1:
                logbook.info(
                    f"!!!!\nMove was from square with 1 or 0 army\n!!!!! {nextMove.source.x},{nextMove.source.y} -> {nextMove.dest.x},{nextMove.dest.y}")
            elif nextMove.source.player != bot._map.player_index:
                logbook.info(
                    f"!!!!\nMove was from square OWNED BY THE ENEMY\n!!!!! [{nextMove.source.player}] {nextMove.source.x},{nextMove.source.y} -> {nextMove.dest.x},{nextMove.dest.y}")
            logbook.info(f"{inc}: doing made move thing? Path: {bot.curPath}")
            bot.curPath.pop_first_move()
            if inc > 20:
                raise AssertionError("bitch, what you doin?")
            try:
                nextMove = bot.curPath.get_first_move()
            except:
                bot.curPath = None
                return None

        if nextMove is None:
            return None

        if nextMove.dest is not None:
            dest = nextMove.dest
            source = nextMove.source
            if source.isGeneral and not BotStateQueries.general_move_safe(bot, dest):
                logbook.info(
                    f"Attempting to execute path move from self.curPath?")
                if BotStateQueries.general_move_safe(bot, dest, move_half=True):
                    logbook.info("General move in path would have violated general min army allowable. Moving half.")
                    move = Move(source, dest, True)
                    return move
                else:
                    bot.curPath = None
                    bot.curPathPrio = -1
                    logbook.info("General move in path would have violated general min army allowable. Repathing.")

            else:
                while bot.curPath is not None:
                    if nextMove.source in defenseCriticalTileSet and nextMove.source.army > 5:
                        tile = nextMove.source
                        logbook.info(
                            f"\n\n\n~~~~~~~~~~~\nSKIPPED: Move was from a negative tile {tile.x},{tile.y}\n~~~~~~~~~~~~~\n\n~~~\n")
                        bot.curPath = None
                        bot.curPathPrio = -1
                        if threat is not None:
                            isNonDominantFfa = BotStateQueries.is_still_ffa_and_non_dominant(bot)
                            if killThreatPath is not None:
                                bot.info(f"REPLACED CURPATH WITH Final path to kill threat! {killThreatPath.toString()}")
                                bot.viewInfo.color_path(PathColorer(killThreatPath, 0, 255, 204, 255, 10, 200))
                                logbook.info(f'setting targetingArmy to {str(threat.path.start.tile)} in continue_cur_path when move wasnt safe for general')
                                bot.targetingArmy = bot.armyTracker.armies[threat.path.start.tile]
                                return BotPathingUtils.get_first_path_move(bot, killThreatPath)
                        else:
                            logbook.warn("Negative tiles prevented a move but there was no threat???")

                    elif nextMove.source.player != bot._map.player_index or nextMove.source.army < 2:
                        logbook.info("\n\n\n~~~~~~~~~~~\nCleaned useless move from path\n~~~~~~~~~~~~~\n\n~~~\n")
                        bot.curPath.pop_first_move()
                        try:
                            nextMove = bot.curPath.get_first_move()
                        except:
                            bot.curPath = None
                            return None
                    else:
                        break
                if bot.curPath is not None and nextMove.dest is not None:
                    if nextMove.source == bot.general and not BotStateQueries.general_move_safe(bot, bot.curPath.start.next.tile, bot.curPath.start.move_half):
                        bot.curPath = None
                        bot.curPathPrio = -1
                    else:
                        move = bot.curPath.get_first_move()
                        lastFrom = None
                        lastTo = None
                        if bot._map.last_player_index_submitted_move:
                            lastFrom, lastTo, _ = bot._map.last_player_index_submitted_move

                        if move.source == lastFrom and move.dest == lastTo:
                            bot.curPath.pop_first_move()
                            move = bot.curPath.get_first_move()

                        bot.info(f"CurPath cont {move}")
                        return BotPathingUtils.move_half_on_repetition(bot, move, 6, 3)

        bot.info("path move failed...? setting curPath to none...")
        bot.info(f'path move WAS {bot.curPath}')
        bot.curPath = None
        return None

    @staticmethod
    def get_enemy_count_on_path(bot, path: Path) -> int:
        numEn = 0
        for t in path.tileList:
            if bot._map.is_tile_enemy(t):
                numEn += 1
        return numEn

    @staticmethod
    def distance_from_general(bot, sourceTile):
        if sourceTile == bot.general:
            return 0
        val = 0

        if bot._gen_distances:
            val = bot._gen_distances[sourceTile]
        return val

    @staticmethod
    def distance_from_teammate(bot, sourceTile):
        if sourceTile == bot.teammate_general:
            return 0
        val = 0

        if BotStateQueries.is_all_in(bot):
            val = bot._ally_distances[sourceTile]
        return val

    @staticmethod
    def is_path_moving_mostly_away(bot, path: Path, bMap: MapMatrixInterface[int]):
        distSum = 0
        for tile in path.tileList:
            distSum += bMap[tile]

        distAvg = distSum / path.length

        distStart = bMap[path.start.tile]
        distEnd = bMap[path.tail.tile]

        doesntAverageCloserToEnemySlightly = distEnd > distStart - path.length // 4
        notHuntingNearby = distEnd > bot.shortest_path_to_target_player.length // 6

        if notHuntingNearby and doesntAverageCloserToEnemySlightly and distAvg > distStart - path.length // 4:
            return True

        return False

    @staticmethod
    def get_path_subsegment_starting_from_last_move(bot, launchPath: Path) -> Path:
        lastMoved = -1
        if bot.armyTracker.lastMove is not None:
            i = 1
            for t in launchPath.tileList:
                if bot.armyTracker.lastMove.source == t:
                    lastMoved = i
                    break
                if bot.armyTracker.lastMove.dest == t:
                    lastMoved = i - 1
                    break
                i += 1

        cut = False
        if 0 <= lastMoved < launchPath.length:
            if lastMoved > 0:
                tilePre = launchPath.tileList[lastMoved - 1]
                if tilePre.army <= 3 and launchPath.tileList[lastMoved].player == bot.general.player:
                    cut = True
            else:
                cut = True
        if cut:
            launchPath = launchPath.get_subsegment(launchPath.length - lastMoved, end=True)

        return launchPath

    @staticmethod
    def check_cur_path(bot):
        if bot.curPath is None:
            return
        if bot.curPath.length == 0:
            bot.curPath = None
            return
        move = None
        try:
            move = bot.curPath.get_first_move()
        except:
            pass

        if move is None:
            logbook.info(f'curpath had no first move, dropping. {bot.curPath}')
            bot.curPath = None
            return

        if move.source is None or move.dest is None:
            logbook.info(f'curpath had bad move {move}, dropping. {bot.curPath}')
            bot.curPath = None
            return

        if isinstance(bot.curPath, Path):
            if bot.curPath.start is None:
                bot.curPath = None
                return
            if bot.curPath.tail is None:
                bot.curPath = None
                return
            if bot.curPath.start.tile is None:
                bot.curPath = None
                return
            if bot.curPath.start.next is None:
                bot.curPath = None
                return
            if bot.curPath.start.next.tile is None:
                bot.curPath = None
                return
            if bot.curPath.tail.tile is None:
                bot.curPath = None
                return
            if bot.curPath.start.tile.player != bot.general.player:
                bot.curPath = None
                return
            if bot.curPath.length == 0:
                bot.curPath = None
                return

    @staticmethod
    def clean_up_path_before_evaluating(bot):
        if not bot.curPath:
            return

        if bot.curPath.length == 0:
            bot.curPath = None
            return

        if isinstance(bot.curPath, GatherCapturePlan):
            firstMove = bot.curPath.get_first_move()
            thresh = bot.curPath.gathered_army / bot.curPath.length / 2 + 0.5
            while firstMove is not None and (firstMove.source.army < thresh or firstMove.source.player != bot.player.index):
                bot.curPath.pop_first_move()
                firstMove = bot.curPath.get_first_move()

        if not isinstance(bot.curPath, Path):
            return

        if bot.curPath.start.next is not None and not BotPathingUtils.dropped_move(bot, bot.curPath.start.tile, bot.curPath.start.next.tile):
            bot.curPath.pop_first_move()
            if bot.curPath.length <= 0:
                logbook.info("TERMINATING CURPATH BECAUSE <= 0 ???? Path better be over")
                bot.curPath = None
            if bot.curPath is not None:
                if bot.curPath.start.next is not None and bot.curPath.start.next.next is not None and bot.curPath.start.next.next.next is not None and bot.curPath.start.tile == bot.curPath.start.next.next.tile and bot.curPath.start.next.tile == bot.curPath.start.next.next.next.tile:
                    logbook.info("\n\n\n~~~~~~~~~~~\nDe-duped path\n~~~~~~~~~~~~~\n\n~~~\n")
                    bot.curPath.pop_first_move()
                    bot.curPath.pop_first_move()
                    bot.curPath.pop_first_move()
                    bot.curPath.pop_first_move()
                elif bot.curPath.start.next is not None and bot.curPath.start.tile.x == bot.curPath.start.next.tile.x and bot.curPath.start.tile.y == bot.curPath.start.next.tile.y:
                    logbook.warn("           wtf, doubled up tiles in path?????")
                    bot.curPath.pop_first_move()
                    bot.curPath.pop_first_move()
        else:
            logbook.info("         --         missed move?")

    @staticmethod
    def get_value_per_turn_subsegment(
            bot,
            path: Path,
            minFactor=0.7,
            minLengthFactor=0.1,
            negativeTiles=None
    ) -> Path:
        if not isinstance(path, Path):
            return path

        return path

        tileArrayRev = [t for t in reversed(path.tileList)]

        tileCount = len(tileArrayRev)
        vtArray = [0.0] * tileCount
        valArray = [0] * tileCount

        rollingSum = 0
        for i, tile in enumerate(tileArrayRev):
            if negativeTiles and tile in negativeTiles:
                continue

            if bot._map.is_tile_friendly(tile):
                rollingSum += tile.army - 1

            if i > 0:
                vtArray[tileCount - i - 1] = rollingSum / i
            valArray[tileCount - i - 1] = rollingSum

        trueVt = rollingSum / path.length
        cutoffVal = rollingSum * minFactor

        maxVtStart = 0
        maxVt = 0.0

        for i, tile in enumerate(path.tileList):
            if tile.player != bot.general.player:
                continue
            if i == path.length:
                continue
            if tile.army <= 1:
                continue

            lengthFactor = (path.length - i) / path.length
            if lengthFactor <= minLengthFactor:
                break

            vt = vtArray[i]
            if vt > maxVt and valArray[i] >= cutoffVal:
                maxVtStart = i
                maxVt = vt

        if maxVtStart == 0:
            return path

        newPath = path.get_subsegment(path.length - maxVtStart, end=True)

        if newPath.start.tile.army <= 1:
            bot.info(f'VT SUBSEGMENT HAD BAD ARMY {newPath.start.tile.army} on start tile {newPath.start.tile}')
            logbook.error(f'value_per_turn_subsegment turned {str(path)} into {str(newPath)}...? Start tile is 1. Returning original path...')
        if newPath.start.tile.player != bot.general.player:
            bot.info(f'VT SUBSEGMENT HAD BAD PLAYER {newPath.start.tile.player} on start tile {newPath.start.tile}')
            logbook.error(f'value_per_turn_subsegment turned {str(path)} into {str(newPath)}...? Start tile is not even owned by us. Returning the original path...')
        newPath.calculate_value(bot.general.player, teams=bot._map.team_ids_by_player_index)

        while newPath.start is not None and (newPath.start.tile.army < 2 or newPath.start.tile.player != bot.general.player):
            bot.viewInfo.add_info_line(f'Popping bad move {str(newPath.start.tile)} off of value-per-turn-subsegment-path')
            newPath.pop_first_move()
            if newPath.length == 0:
                break

        if newPath.length == 0:
            newPath = path.clone()
            bot.viewInfo.add_info_line(f'VT subsegment repair ALSO bad.')

            while newPath.get_first_move() is not None and (newPath.start.tile.army < 2 or newPath.start.tile.player != bot.general.player):
                bot.viewInfo.add_info_line(f'Popping bad move {str(newPath.start.tile)} off of value-per-turn-subsegment-path')
                newPath.pop_first_move()

        return newPath

    @staticmethod
    def get_path_to_target(
            bot,
            target,
            maxTime=0.1,
            maxDepth=400,
            skipNeutralCities=True,
            skipEnemyCities=False,
            preferNeutral=True,
            fromTile=None,
            preferEnemy=False,
            maxObstacleCost: int | None = None
    ) -> Path | None:
        targets = set()
        targets.add(target)
        return BotPathingUtils.get_path_to_targets(
            bot,
            targets,
            maxTime,
            maxDepth,
            skipNeutralCities,
            skipEnemyCities,
            preferNeutral,
            fromTile,
            preferEnemy=preferEnemy,
            maxObstacleCost=maxObstacleCost)

    @staticmethod
    def is_move_towards_enemy(bot, move) -> bool:
        if move is None:
            return False

        if bot.targetPlayer is None:
            return False

        if bot.territories.territoryDistances[bot.targetPlayer][move.source] > bot.territories.territoryDistances[bot.targetPlayer][move.dest]:
            return True

        return False

    @staticmethod
    def is_tile_in_range_from(bot, source: Tile, target: Tile, maxDist: int, minDist: int = 0) -> bool:
        dist = 1000
        if target == bot.general:
            dist = bot.distance_from_general(source)
        elif target == bot.targetPlayerExpectedGeneralLocation:
            dist = bot.distance_from_opp(source)
        else:
            captDist = [dist]

            def distFinder(tile: Tile, d: int) -> bool:
                if tile.x == target.x and tile.y == target.y:
                    captDist[0] = d

                return tile.isObstacle

            SearchUtils.breadth_first_foreach_dist(bot._map, [source], maxDepth=maxDist + 1, foreachFunc=distFinder)

            dist = captDist[0]

        return minDist <= dist <= maxDist

    @staticmethod
    def get_euclid_shortest_from_tile_towards_target(bot, sourceTile: Tile, towardsTile: Tile) -> Move:
        shortest = 100
        shortestTile = None
        for adj in sourceTile.movable:
            if adj.isObstacle:
                continue
            dist = bot._map.euclidDist(towardsTile.x, towardsTile.y, adj.x, adj.y)
            if dist < shortest:
                shortest = dist
                shortestTile = adj

        return Move(sourceTile, shortestTile)

    @staticmethod
    def get_path_to_targets(
            bot,
            targets,
            maxTime=0.1,
            maxDepth=400,
            skipNeutralCities=True,
            skipEnemyCities=False,
            preferNeutral=True,
            fromTile=None,
            preferEnemy=True,
            maxObstacleCost: int | None = None
    ) -> Path | None:
        if fromTile is None:
            fromTile = bot.general
        negativeTiles = None
        if skipEnemyCities:
            negativeTiles = set()
            for enemyCity in bot.enemyCities:
                negativeTiles.add(enemyCity)

        if maxObstacleCost is None and BotStateQueries.is_weird_custom(bot):
            maxObstacleCost = bot._map.walled_city_base_value

        def path_to_targets_priority_func(
                nextTile: Tile,
                currentPriorityObject):
            (dist, negEnemyTiles, negCityCount, negArmySum, goalIncrement) = currentPriorityObject
            dist += 1

            if nextTile.isCity:
                if skipEnemyCities and bot._map.is_tile_enemy(nextTile):
                    return None

                if nextTile.player == -1 and maxObstacleCost is not None and nextTile.army >= maxObstacleCost:
                    return None

            if preferEnemy and not BotStateQueries.is_all_in(bot):
                if bot._map.is_tile_on_team_with(nextTile, bot.targetPlayer):
                    negEnemyTiles -= 1
                    if nextTile.isCity:
                        negCityCount -= 1

                if not BotTargeting.is_ffa_situation(bot):
                    if not nextTile.visible:
                        negEnemyTiles -= 1
                    if not nextTile.discovered:
                        negEnemyTiles -= 1

                negEnemyTiles -= int(bot.armyTracker.emergenceLocationMap[bot.targetPlayer][nextTile] ** 0.25)

            if negativeTiles is None or nextTile not in negativeTiles:
                if nextTile.isNeutral:
                    if nextTile.army <= 0 or (nextTile.isCity and nextTile.army < bot.player.standingArmy):
                        if preferNeutral:
                            negEnemyTiles -= 0.5
                            if nextTile.isCity:
                                negCityCount -= 1
                    else:
                        negEnemyTiles += 2
                        dist += min(nextTile.army + 1, 8)
                if bot._map.is_tile_friendly(nextTile):
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            negArmySum += 1
            negArmySum -= goalIncrement
            return dist, negEnemyTiles, negCityCount, negArmySum, goalIncrement

        startPriorityObject = (0, 0, 0, 0, 0.5)
        startTiles = {fromTile: (startPriorityObject, 0)}

        path = SearchUtils.breadth_first_dynamic(
            bot._map,
            startTiles,
            lambda tile, prioObj: tile in targets,
            maxDepth,
            skipNeutralCities,
            negativeTiles=negativeTiles,
            priorityFunc=path_to_targets_priority_func)

        return path

    @staticmethod
    def get_path_subsegment_to_closest_enemy_team_territory(bot, path: Path) -> Path | None:
        idx = 0
        team = bot.targetPlayerObj.team
        minDist = bot.territories.territoryTeamDistances[team][path.start.tile]
        minIdx = 100
        for tile in path.tileList:
            thisDist = bot.territories.territoryTeamDistances[team][tile]
            if thisDist < minDist:
                minDist = thisDist
                minIdx = idx

            idx += 1

        if minIdx == 100:
            logbook.info(f'No closer path to enemy territory found than the start of the path, prefer not using this path at all.')
            return None

        subsegment = path.get_subsegment(minIdx)
        logbook.info(f'closest to enemy team territory was {str(subsegment.tail.tile)} at dist {minIdx}/{path.length}')
        return subsegment

    @staticmethod
    def distance_from_opp(bot, sourceTile):
        if sourceTile == bot.targetPlayerExpectedGeneralLocation:
            return 0
        val = 0
        if bot.board_analysis and bot.board_analysis.intergeneral_analysis:
            val = bot.board_analysis.intergeneral_analysis.bMap[sourceTile]
        return val

    @staticmethod
    def distance_from_target_path(bot, sourceTile):
        if sourceTile in bot.shortest_path_to_target_player.tileSet:
            return 0

        val = 0
        if bot.board_analysis and bot.board_analysis.shortest_path_distances:
            val = bot.board_analysis.shortest_path_distances[sourceTile]
        return val

    @staticmethod
    def get_distance_from_board_center(bot, tile, center_ratio=0.25) -> float:
        distFromCenterX = abs((bot._map.cols / 2) - tile.x)
        distFromCenterY = abs((bot._map.rows / 2) - tile.y)

        distFromCenterX -= bot._map.cols * center_ratio
        distFromCenterY -= bot._map.rows * center_ratio

        if distFromCenterX < 0:
            distFromCenterX = 0
        if distFromCenterY < 0:
            distFromCenterY = 0
        return distFromCenterX + distFromCenterY
