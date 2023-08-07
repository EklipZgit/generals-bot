import logging
import typing

import SearchUtils
from Path import Path
from SearchUtils import breadth_first_foreach, breadth_first_dynamic_max
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile

DEBUG_ASSERTS = False


class ExpansionPlan(object):
    def __init__(self, tile_captures: int, plan_paths: typing.List[typing.Union[None, Path]]):
        self.tile_captures: int = tile_captures
        self.plan_paths: typing.List[typing.Union[None, Path]] = plan_paths

# None's represent waiting moves, paths represent path moves
def get_start_expand_value(
        map: MapBase,
        general: Tile,
        generalArmy: int,
        curTurn: int,
        expandPaths: typing.List[typing.Union[None, Path]],
        visitedSet: typing.Set[Tile] = None,
        noLog: bool = False) -> int:

    if len(expandPaths) == 0:
        return 0

    tilesCapped: typing.Set[Tile] = set()
    if visitedSet is not None:
        tilesCapped = visitedSet.copy()
    tilesCapped.add(general)

    genArmy = generalArmy
    pathIdx = 0
    curPath: typing.Union[None, Path] = expandPaths[pathIdx]
    if curPath is not None:
        curPath = curPath.clone()
    movingArmy = 0
    for turn in range(curTurn, 50):
        # logging.info(f'turn: {turn}')
        movingGen = False
        pathComplete = False
        if curPath is None:
            if not noLog:
                logging.info(f'{turn} ({genArmy}) - no-opped move')
            pathIdx += 1
            if pathIdx >= len(expandPaths):
                break
            pathComplete = True
            movingArmy = 0
        else:
            move = curPath.made_move()
            if move.tile == general:
                movingArmy = genArmy
                movingGen = True

            next = move.next.tile
            if next in tilesCapped or next.player == general.player:
                if not noLog:
                    logging.info(f'{turn} ({genArmy}) - {str(next)} (a{movingArmy}) already capped')
            else:
                movingArmy -= 1
                tilesCapped.add(move.next.tile)
                if not noLog:
                    logging.info(f'{turn} ({genArmy}) - {str(next)} (a{movingArmy}) ({len(tilesCapped)})')
                if movingArmy <= 0 and DEBUG_ASSERTS:
                    raise AssertionError(f'illegal plan, moved army from 1 tile, see last log above')
            if curPath.length == 0:
                pathIdx += 1
                if pathIdx >= len(expandPaths):
                    break
                pathComplete = True

        if pathComplete:
            if movingArmy > 1:
                logging.info(f"expected to use full army...? {movingArmy}")
            curPath = expandPaths[pathIdx]
            if curPath is not None:
                curPath = curPath.clone()

        if movingGen:
            genArmy = 1

        if turn % 2 == 1:
            genArmy += 1

    if not noLog:
        logging.info(
            f'result of curTurn {curTurn}: capped {len(tilesCapped)}, final genArmy {genArmy}')

    return len(tilesCapped)

#
# def print_expansion_optimization(expansionOptimization: ExpansionPlan):
#


def optimize_first_25(
        map: MapBase,
        general: Tile,
        tile_weight_map: typing.List[typing.List[int]],
        debug_view_info: typing.Union[None, ViewInfo] = None) -> ExpansionPlan:
    """

    @param map:
    @param general:
    @param tile_weight_map: lower numbers = better
    @return:
    """

    distToGenMap = SearchUtils.build_distance_map(map, [general])
    if debug_view_info:
        debug_view_info.bottomLeftGridText = distToGenMap

    """
    corner start, perfect:
    11 launch
    6 launch (3 overlap)
    5 launch (2 overlap)
    4 launch (1 overlap
    3 launch (take 2)
    """

    visited: typing.Set[Tile] = set()
    player = map.players[general.player]
    for tile in player.tiles:
        visited.add(tile)

    if map.turn > 25:
        result = _sub_optimize_first_25(
            map,
            general,
            general.army,
            distToGenMap,
            tile_weight_map,
            turn=map.turn,
            visitedSet=visited,
            repeatTiles=1,
            dontForceFirst=True,
            debug_view_info=debug_view_info)
        val = get_start_expand_value(map, general, general.army, map.turn, result, visitedSet=visited, noLog=False)

        return ExpansionPlan(val, result)


    openLaunchTurn = 24
    # 13 army launch
    maxResult = _sub_optimize_first_25(map, general, 13, distToGenMap, tile_weight_map, turn=openLaunchTurn, repeatTiles=1, debug_view_info=debug_view_info)
    for _ in range(map.turn, openLaunchTurn):
        maxResult.insert(0, None)
    maxVal = get_start_expand_value(map, general, general.army, map.turn, maxResult, visitedSet=visited, noLog=False)
    # skip moves up to initial launch

    lessOpenLaunchTurn = 22
    if map.turn <= lessOpenLaunchTurn:
        # 12
        lessOpenResult = _sub_optimize_first_25(map, general, 12, distToGenMap, tile_weight_map, turn=lessOpenLaunchTurn, repeatTiles=3, debug_view_info=debug_view_info)
        for _ in range(map.turn, lessOpenLaunchTurn):
            lessOpenResult.insert(0, None)
        lessOpenVal = get_start_expand_value(map, general, general.army, map.turn, lessOpenResult, visitedSet=visited, noLog=False)

        if lessOpenVal > maxVal:
            logging.info(f'12 launch > 13 launch, {maxVal} vs {lessOpenVal}')
            maxVal = lessOpenVal
            maxResult = lessOpenResult

    lessLessOpenLaunchTurn = 20
    if map.turn <= lessLessOpenLaunchTurn:
        # 11
        lessLessOpenResult = _sub_optimize_first_25(map, general, 11, distToGenMap, tile_weight_map, turn=lessLessOpenLaunchTurn,
                                                    repeatTiles=6, debug_view_info=debug_view_info)
        for _ in range(map.turn, lessLessOpenLaunchTurn):
            lessLessOpenResult.insert(0, None)
        lessLessOpenVal = get_start_expand_value(map, general, general.army, map.turn, lessLessOpenResult, visitedSet=visited, noLog=False)

        if lessLessOpenVal > maxVal:
            logging.info(f'11 launch > 13/12 launch, {maxVal} vs {lessLessOpenVal}')
            maxVal = lessLessOpenVal
            maxResult = lessLessOpenResult

    return ExpansionPlan(maxVal, maxResult)


def _sub_optimize_first_25(
        map: MapBase,
        general: Tile,
        genArmy: int,
        distToGenMap: typing.List[typing.List[int]],
        tile_weight_map: typing.List[typing.List[int]],
        turn: int,
        repeatTiles: int,
        visitedSet: typing.Set[Tile] = None,
        dontForceFirst: bool = False,
        debug_view_info: typing.Union[None, ViewInfo] = None) -> typing.List[typing.Union[None, Path]]:
    """
    recursively optimize first 25

    @param map:
    @param general:
    @param genAdjacent:
    @param tile_weight_map:
    @param launchTurn:
    @param repeatTiles:
    @return:
    """

    logging.info(f'sub-optimizing turn {turn} genArmy {genArmy}')

    pathList = []

    if turn >= 50:
        return pathList

    if genArmy <= 1:
        logging.info(f'waiting a move due to gen army 1 (appending None)')
        pathList.append(None)
        return pathList

    if visitedSet is not None:
        visitedSet = visitedSet.copy()
    else:
        visitedSet = set()
        visitedSet.add(general)

    curTurn = turn
    if not dontForceFirst:
        path1 = _optimize_25_launch_segment(map, general, genArmy, distToGenMap, (repeatTiles + 1) // 2, tile_weight_map,
                                            visitedSet, debug_view_info=debug_view_info)
        pathList.append(path1)

        if path1 is None:
            return pathList

        for tile in path1.tileList:
            if tile in visitedSet and tile != general:
                repeatTiles -= 1
            visitedSet.add(tile)

        genArmy = 1
        logging.info(f'path1.length {path1.length} ({str(path1)})')
        for _ in range(path1.length):
            curTurn += 1
            if curTurn % 2 == 0:
                genArmy += 1
            logging.info(f'curTurn {curTurn} genArmy {genArmy}')

    if curTurn >= 50:
        return pathList

    repeatTiles = max(0, repeatTiles)

    # try immediate launch
    logging.info(f'normal, curTurn {curTurn}, genArmy {genArmy}')
    maxOptimized = _sub_optimize_first_25(map, general, genArmy, distToGenMap, tile_weight_map, curTurn, repeatTiles,
                                          visitedSet, debug_view_info=debug_view_info)
    maxValue = get_start_expand_value(map, general, genArmy, curTurn, maxOptimized, visitedSet)

    isSuboptimalLaunchTurn = curTurn % 2 != 0
    # try one turn wait if turns remaining long enough
    if curTurn <= 47:
        genArmy += 1
        curTurn += 1
        if not isSuboptimalLaunchTurn:
            curTurn += 1
        logging.info(f'withWait (double: {not isSuboptimalLaunchTurn}), curTurn {curTurn}, genArmy {genArmy}')
        withOneWait = _sub_optimize_first_25(map, general, genArmy, distToGenMap, tile_weight_map, curTurn, repeatTiles,
                                             visitedSet, debug_view_info=debug_view_info)
        oneWaitVal = get_start_expand_value(map, general, genArmy, curTurn, withOneWait, visitedSet)
        if oneWaitVal >= maxValue:
            logging.info(f'waiting (double: {not isSuboptimalLaunchTurn}) until {curTurn} resulted in better yield, {maxValue} vs {oneWaitVal}')
            maxOptimized = withOneWait
            maxValue = oneWaitVal
            pathList.append(None)
            if not isSuboptimalLaunchTurn:
                pathList.append(None)

    for pathVal in maxOptimized:
        pathList.append(pathVal)

    return pathList


def _optimize_25_launch_segment(
        map: MapBase,
        general: Tile,
        genArmy: int,
        distanceToGenMap: typing.List[typing.List[int]],
        tilesNeedingRepeat: int,
        tile_weight_map: typing.List[typing.List[int]],
        visitedSet: typing.Set[Tile],
        debug_view_info: typing.Union[None, ViewInfo] = None) -> typing.Union[None, Path]:

    if genArmy <= 1:
        logging.info('RETURNING NONE')
        return None

    i = SearchUtils.Counter(0)

    def value_func(currentTile, priorityObject):
        negGenDist, _, _, pathCappedNeg, negAdjWeight, repeats, cappedAdj = priorityObject
        # higher better
        closerToEnemy = 0 - tile_weight_map[currentTile.x][currentTile.y]

        # if pathCappedNeg + genArmy <= 0:
        #     logging.info(f'tile {str(currentTile)} ought to be skipped...?')
        #     return None
        valObj = 0 - pathCappedNeg, 0 - abs(repeats - tilesNeedingRepeat), 0 - cappedAdj, closerToEnemy

        if currentTile.x == 0 and currentTile.y == 0:
            logging.info(f'v - 0,0, {valObj}')
        if currentTile.x == 1 and currentTile.y == 1:
            logging.info(f'v - 1,1, {valObj}')

        return valObj

    # must always prioritize the tiles furthest from general first, to make sure we dequeue in the right order
    def prio_func(nextTile, currentPriorityObject):
        _, repeatAvoider, closerToEnemyNeg, pathCappedNeg, negAdjWeight, repeats, cappedAdj = currentPriorityObject
        visited = nextTile in visitedSet
        if not visited:
            pathCappedNeg -= 1
        else:
            repeats += 1

        if debug_view_info:
            i.add(1)
            debug_view_info.bottomRightGridText[nextTile.x][nextTile.y] = i.value


        #
        # if pathCappedNeg + genArmy <= 0:
        #     logging.info(f'tile {str(nextTile)} ought to be skipped...?')
        #     return None

        closerToEnemyNeg = tile_weight_map[nextTile.x][nextTile.y]

        # 0 is best value we'll get, after which more repeat tiles become 'bad' again
        repeatAvoider = abs(tilesNeedingRepeat - repeats)
        distToGen = min(1000, distanceToGenMap[nextTile.x][nextTile.y])
        adjWeight = 0 - negAdjWeight

        adjWeight += SearchUtils.count(
            nextTile.moveable,
            lambda tile: tile not in visitedSet and distanceToGenMap[tile.x][
                tile.y] >= distToGen and tile.player == -1 and not tile.isobstacle() and not tile.isCity)

        if distToGen < 4:
            cappedAdj += 1
            repeatAvoider += cappedAdj

        if debug_view_info:
            debug_view_info.midRightGridText[nextTile.x][nextTile.y] = adjWeight

        priObj = 0 - distToGen, repeatAvoider, closerToEnemyNeg, pathCappedNeg, 0 - adjWeight, repeats, cappedAdj
        if nextTile.x == 0 and nextTile.y == 0:
            logging.info(f'p - 0,0, {priObj}')
        if nextTile.x == 1 and nextTile.y == 1:
            logging.info(f'p - 1,1, {priObj}')

        return priObj

    def skip_func(nextTile, currentPriorityObject):
        _, _, _, pathCappedNeg, _, repeats, cappedAdj = currentPriorityObject
        return pathCappedNeg + genArmy <= 0

    startVals: typing.Dict[Tile, typing.Tuple[object, int]] = {}
    startVals[general] = ((0, 0, -1000, 0, 0, 0, 0), 0)
    logging.info(f'starting launch with genArmy {genArmy}, needRepeat {tilesNeedingRepeat}, alreadyVisited {len(visitedSet)}')
    path = breadth_first_dynamic_max(
        map,
        startVals,
        value_func,
        noNeutralCities=True,
        priorityFunc=prio_func,
        skipFunc=skip_func,
        noLog=True)

    return path
