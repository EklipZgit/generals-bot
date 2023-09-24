import logging
import typing

import SearchUtils
from Path import Path
from SearchUtils import breadth_first_foreach, breadth_first_dynamic_max
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile

DEBUG_ASSERTS = False


class ExpansionPlan(object):
    def __init__(self, tile_captures: int, plan_paths: typing.List[typing.Union[None, Path]], launch_turn: int):
        self.tile_captures: int = tile_captures
        self.launch_turn: int = launch_turn
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
                if movingArmy > 1 and turn < 50:
                    if not noLog:
                        logging.info(f"Army not fully used. {movingArmy} army ended at {str(next)}, turn {turn}. Should almost never see this in a final result...")

        if pathComplete:
            curPath = expandPaths[pathIdx]
            if curPath is not None:
                curPath = curPath.clone()

        if movingGen:
            genArmy = 1

        if turn % 2 == 1:
            genArmy += 1

    if pathIdx < len(expandPaths):
        errorMsg = f'Plan incomplete at turn 50, pathIdx {pathIdx} with subsequent paths {", ".join([str(path) for path in expandPaths[pathIdx:]])}'
        if DEBUG_ASSERTS:
            raise AssertionError(errorMsg)
        else:
            logging.info(errorMsg)

    if not noLog:
        logging.info(
            f'result of curTurn {curTurn}: capped {len(tilesCapped)}, final genArmy {genArmy}')

    return len(tilesCapped)

def __evaluate_plan_value(
        map: MapBase,
        general: Tile,
        general_army: int,
        cur_turn: int,
        path_list: typing.List[typing.Union[None, Path]],
        dist_to_gen_map: typing.List[typing.List[int]],
        tile_weight_map: typing.List[typing.List[int]],
        already_visited: typing.Set[Tile],
        no_log: bool = False
) -> typing.Tuple[int, int, int, int]:

    tileWeightSum = 0
    genDistSum = 0
    adjAvailable = SearchUtils.Counter(0)

    pathTileSet = set()
    for path in path_list:
        if path is not None:
            pathTileSet.update(path.tileList)

    for tile in pathTileSet:
        tileWeightSum += tile_weight_map[tile.x][tile.y]
        genDistSum += dist_to_gen_map[tile.x][tile.y]

    def count_func(tile: Tile):
        if (tile not in pathTileSet
                and tile not in already_visited
                and not tile.isNotPathable
                and not tile.isCity
                and tile.player == -1
                and tile.army == 0):
            adjAvailable.add(1)

    breadth_first_foreach(map, pathTileSet, 4, count_func, noLog=True)

    pathValue = get_start_expand_value(map, general, general_army, cur_turn, path_list, visitedSet=already_visited, noLog=no_log)

    return pathValue, adjAvailable.value, 0-tileWeightSum, genDistSum




def optimize_first_25(
        map: MapBase,
        general: Tile,
        tile_weight_map: typing.List[typing.List[int]],
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_recurse: bool = False,
        no_log=not DEBUG_ASSERTS) -> ExpansionPlan:
    """

    @param map:
    @param general:
    @param tile_weight_map: lower numbers = better
    @param debug_view_info: the viewInfo to write debug data to (mainly for unit testing).
    @param no_recurse: Used to prevent infinite recursion when optimizing with alt tile weights
    @param no_log: skip logging everything except the final result
    @return:
    """

    distToGenMap = SearchUtils.build_distance_map(map, [general])
    if debug_view_info:
        debug_view_info.bottomLeftGridText = distToGenMap

    visited: typing.Set[Tile] = set()
    player = map.players[general.player]
    for tile in player.tiles:
        visited.add(tile)

    mapTurnAtStart = map.turn
    genArmyAtStart = general.army

    if mapTurnAtStart > 25:
        result = _sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            genArmyAtStart,
            distToGenMap,
            tile_weight_map,
            turn=mapTurnAtStart,
            visited_set=visited,
            prune_below=0,
            allow_wasted_moves=5,
            dont_force_first=True,
            debug_view_info=debug_view_info,
            no_log=no_log)
        val = get_start_expand_value(map, general, genArmyAtStart, mapTurnAtStart, result, visitedSet=visited, noLog=no_log)

        return ExpansionPlan(val, result, mapTurnAtStart)

    # genArmy, turn, optimalMaxWasteMoves
    combinationsWithMaxOptimal = [
        (13, 24, 2),  # most likely to find high value paths first
        (11, 20, 6),
        (14, 26, 0),
        (10, 20, 8),
        (12, 22, 4),
    ]
    # 12-6-5-4-1

    maxResult = None
    maxVal = None
    maxTiles = 0

    for (genArmy, launchTurn, optimalWastedMoves) in combinationsWithMaxOptimal:
        if mapTurnAtStart > launchTurn:
            continue

        launchResult = _sub_optimize_remaining_cycle_expand_from_cities(map, general, genArmy, distToGenMap, tile_weight_map, turn=launchTurn, allow_wasted_moves=optimalWastedMoves + 3, debug_view_info=debug_view_info, prune_below=maxTiles, no_log=no_log)
        for _ in range(mapTurnAtStart, launchTurn):
            launchResult.insert(0, None)
        launchVal = __evaluate_plan_value(map, general, genArmyAtStart, map.turn, launchResult, dist_to_gen_map=distToGenMap, tile_weight_map=tile_weight_map, already_visited=visited, no_log=no_log)
        logging.info(f'{genArmy} ({optimalWastedMoves}) launch ({launchVal}) {">>>" if maxVal is None or maxVal < launchVal else "<"} prev launches (prev max {maxVal})')
        if maxVal is None or launchVal > maxVal:
            maxVal = launchVal
            maxResult = launchResult
            maxTiles = launchVal[0]

    launchTurn = mapTurnAtStart
    for path in maxResult:
        if path is not None:
            break
        launchTurn += 1

    logging.info(f'max launch result  v')
    get_start_expand_value(map, general, general.army, mapTurnAtStart, maxResult, visitedSet=visited, noLog=False)
    logging.info(f'max launch result {maxVal}, turn {launchTurn} ^')

    return ExpansionPlan(maxVal[0], maxResult, launchTurn)


def _sub_optimize_first_25_specific_wasted(
        map: MapBase,
        general: Tile,
        gen_army: int,
        dist_to_gen_map: typing.List[typing.List[int]],
        tile_weight_map: typing.List[typing.List[int]],
        turn: int,
        force_wasted_moves: int,
        allow_wasted_moves: int,
        prune_below: int,
        visited_set: typing.Set[Tile],
        dont_force_first: bool = False,
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS
    ) -> typing.Tuple[typing.Tuple[int, int, int, int], typing.List[typing.Union[None, Path]]]:
        """

        @param map:
        @param general:
        @param gen_army:
        @param dist_to_gen_map:
        @param tile_weight_map:
        @param turn:
        @param force_wasted_moves: The amount of moves to force-waste on THIS segment. Must always be less than allow_wasted_moves.
        @param allow_wasted_moves: The amount of wasted moves allowed overall for the remaining segments.
        @param visited_set:
        @param dont_force_first: If true, will not force a segment at this exact timing and will instead test subsegments now and at the next general bonus turn.
        @param debug_view_info:
        @param no_log:
        @return:
        """
        pathList = []
        curAttemptGenArmy = gen_army

        curTurn = turn
        capped = (0, 0, 0, 0)

        visited_set = visited_set.copy()

        if not dont_force_first:

            if curAttemptGenArmy <= 1:
                raise AssertionError(f'Someone ran a sub_optimize_specific_wasted with gen army 1 lol')

            path1 = _optimize_25_launch_segment(
                map,
                general,
                curAttemptGenArmy,
                50 - curTurn,
                dist_to_gen_map,
                force_wasted_moves=force_wasted_moves,
                tile_weight_map=tile_weight_map,
                visited_set=visited_set,
                debug_view_info=debug_view_info,
                no_log=no_log)

            if path1 is None:
                if not no_log:
                    logging.info(f'got none path for genArmy {curAttemptGenArmy} with allow_wasted {force_wasted_moves} (already visited {len(visited_set)})')
                pathList.append(None)
                return capped, pathList

            capped = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, [path1], dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_visited=visited_set, no_log=no_log)

            if capped[0] == 0:
                pathList.append(None)
                logging.info(f'got 0 value path {str(path1)}, returning None instead')
                return capped, pathList

            if not no_log:
                logging.info(f'appending val {capped}, path {str(path1)}')

            pathList.append(path1)

            for tile in path1.tileList:
                if tile in visited_set and tile != general:
                    allow_wasted_moves -= 1
                visited_set.add(tile)

            curAttemptGenArmy = 1
            if not no_log:
                logging.info(f'path1.length {path1.length} ({str(path1)})')
            for _ in range(path1.length):
                curTurn += 1
                if curTurn % 2 == 0:
                    curAttemptGenArmy += 1

        if curTurn >= 50:
            if not no_log:
                logging.info(f'curTurn {curTurn} >= 50, returning current path')
            return capped, pathList

        allow_wasted_moves = max(0, allow_wasted_moves)

        # try immediate launch
        if not no_log:
            logging.info(f'normal, curTurn {curTurn}, genArmy {curAttemptGenArmy}')
        maxOptimized = _sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            curAttemptGenArmy,
            dist_to_gen_map,
            tile_weight_map,
            curTurn,
            allow_wasted_moves,
            prune_below=prune_below,
            visited_set=visited_set,
            debug_view_info=debug_view_info,
            no_log=no_log)
        maxValue = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, maxOptimized, dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_visited=visited_set, no_log=no_log)

        isSuboptimalLaunchTurn = curTurn % 2 != 0
        # try one turn wait if turns remaining long enough
        if curTurn <= 47:
            curAttemptGenArmy += 1
            curTurn += 1
            allow_wasted_moves -= 1
            if not isSuboptimalLaunchTurn:
                curTurn += 1
                allow_wasted_moves -= 1
            if not no_log:
                logging.info(
                    f'withWait (double: {not isSuboptimalLaunchTurn}), curTurn {curTurn}, genArmy {curAttemptGenArmy}')
            withOneWait = _sub_optimize_remaining_cycle_expand_from_cities(
                map,
                general,
                curAttemptGenArmy,
                dist_to_gen_map,
                tile_weight_map,
                curTurn,
                allow_wasted_moves,
                prune_below=max(maxValue[0], prune_below),
                visited_set=visited_set,
                debug_view_info=debug_view_info,
                no_log=no_log)
            oneWaitVal = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, withOneWait, dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_visited=visited_set, no_log=no_log)
            if oneWaitVal >= maxValue:
                if not no_log:
                    logging.info(
                        f'waiting (double: {not isSuboptimalLaunchTurn}) until {curTurn} resulted in better yield, {maxValue} vs {oneWaitVal}')
                maxOptimized = withOneWait
                maxValue = oneWaitVal
                pathList.append(None)
                if not isSuboptimalLaunchTurn:
                    pathList.append(None)

        if maxValue[0] == 0:
            if not no_log:
                logging.info('throwing out bad path')
            return maxValue, [None]

        for pathVal in maxOptimized:
            pathList.append(pathVal)

        return maxValue, pathList

def _sub_optimize_remaining_cycle_expand_from_cities(
        map: MapBase,
        general: Tile,
        gen_army: int,
        dist_to_gen_map: typing.List[typing.List[int]],
        tile_weight_map: typing.List[typing.List[int]],
        turn: int,
        allow_wasted_moves: int,
        prune_below: int,
        visited_set: typing.Set[Tile] = None,
        dont_force_first: bool = False,
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS
    ) -> typing.List[typing.Union[None, Path]]:
    """
    recursively optimize first 25

    @param map:
    @param general:
    @param gen_army:
    @param dist_to_gen_map: higher = better priority
    @param tile_weight_map: lower = better priority
    @param turn: turn launch is from (used to cap paths at turn 50)
    @param allow_wasted_moves: number of tiles ALLOWED to be repeated / moves allowed to be wasted.
    @param visited_set:
    @param dont_force_first:
    @param debug_view_info:
    @return:
    """
    if not no_log:
        logging.info(f'sub-optimizing turn {turn} genArmy {gen_army}')

    maxCombinationValue = (0, 0, 0, 0)
    maxCombinationPathList = [None]
    if visited_set is None or len(visited_set) == 0:
        visited_set = set()
        visited_set.add(general)

    turn = turn % 50

    skipMoveCount = 0
    if not dont_force_first:
        if gen_army == 1:
            gen_army = 2
            turn += 1
            allow_wasted_moves -= 1
            skipMoveCount += 1
            if turn % 2 == 1:
                turn += 1
                allow_wasted_moves -= 1
                skipMoveCount += 1
    turnsLeft = 50 - turn

    if turnsLeft <= 0:
        return []

    minWastedMovesThisLaunch = max(0, allow_wasted_moves // 2 - 2)
    for force_wasted_moves in range(minWastedMovesThisLaunch, allow_wasted_moves + 1):
        bestCaseResult = len(visited_set) + turnsLeft - force_wasted_moves
        if bestCaseResult < prune_below:
            if not no_log:
                logging.info(f'pruning due to bestCaseResult {bestCaseResult} compared to prune_below {prune_below}')
            break

        value, pathList = _sub_optimize_first_25_specific_wasted(
            map=map,
            general=general,
            gen_army=gen_army,
            dist_to_gen_map=dist_to_gen_map,
            tile_weight_map=tile_weight_map,
            turn=turn,
            force_wasted_moves=force_wasted_moves,
            allow_wasted_moves=allow_wasted_moves,
            prune_below=prune_below,
            visited_set=visited_set,
            dont_force_first=dont_force_first,
            debug_view_info=debug_view_info,
            no_log=no_log
        )

        if value > maxCombinationValue:
            maxCombinationValue = value
            maxCombinationPathList = pathList
            prune_below = max(prune_below, value[0])

    if len(maxCombinationPathList) > 0:
        for i in range(skipMoveCount):
            maxCombinationPathList.insert(0, None)

    return maxCombinationPathList


def _optimize_25_launch_segment(
        map: MapBase,
        general: Tile,
        gen_army: int,
        turns_left: int,
        distance_to_gen_map: typing.List[typing.List[int]],
        force_wasted_moves: int,
        tile_weight_map: typing.List[typing.List[int]],
        visited_set: typing.Set[Tile],
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS
    ) -> typing.Union[None, Path]:

    if gen_army <= 1:
        if not no_log:
            logging.info('RETURNING NONE from _optimize_25_launch_segment, gen_army <= 1')
        return None

    i = SearchUtils.Counter(0)

    def value_func(currentTile, priorityObject, pathList: typing.List[Tile]):
        _, currentGenDist, _, pathCappedNeg, negAdjWeight, repeats, cappedAdj, maxGenDist = priorityObject
        # currentGenDist = 0 - negCurrentGenDist
        # higher better
        tileValue = 0 - tile_weight_map[currentTile.x][currentTile.y]

        if repeats - force_wasted_moves > 0:
            return None

        if pathCappedNeg == 0:
            return None

        # dont return paths that end in an already capped tile
        if currentTile in visited_set:
            return None

        # if currentGenDist < fromTileGenDist:
        #     logging.info(f'bounded off loop path (value)...? {str(fromTile)}->{str(currentTile)}')
            # return None

        valObj = 0 - pathCappedNeg, 0 - abs(repeats - force_wasted_moves), 0 - cappedAdj, currentGenDist, tileValue - negAdjWeight / 3

        return valObj

    # must always prioritize the tiles furthest from general first, to make sure we dequeue in the right order
    def prio_func(nextTile, currentPriorityObject, pathList: typing.List[Tile]):
        repeatAvoider, _, closerToEnemyNeg, pathCappedNeg, negAdjWeight, repeats, cappedAdj, maxGenDist = currentPriorityObject
        visited = nextTile in visited_set
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
        repeatAvoider = abs(force_wasted_moves - repeats)
        distToGen = min(1000, distance_to_gen_map[nextTile.x][nextTile.y])
        adjWeight = 0 - negAdjWeight

        remainingArmy = pathCappedNeg + gen_army
        if remainingArmy > 4:
            adjWeight += SearchUtils.count(
                nextTile.movable,
                lambda tile: tile not in visited_set
                             and distance_to_gen_map[tile.x][tile.y] >= distToGen  #and tile is further from general
                             and tile.player == -1
                             and not tile.isNotPathable
                             and not tile.isCity)

            adjWeight += SearchUtils.count(
                nextTile.movable,
                lambda tile: tile not in visited_set
                             and distance_to_gen_map[tile.x][tile.y] > distToGen  #and tile is further from general
                             and tile.player == -1
                             and not tile.isNotPathable
                             and not tile.isCity)

        if distToGen < 4 and nextTile not in visited_set:
            cappedAdj += 1
            repeatAvoider += cappedAdj

        if debug_view_info:
            debug_view_info.midRightGridText[nextTile.x][nextTile.y] = adjWeight

        maxGenDist = max(maxGenDist, distToGen)

        priObj = repeatAvoider, distToGen, closerToEnemyNeg, pathCappedNeg, 0 - adjWeight, repeats, cappedAdj, maxGenDist

        return priObj

    countSearchedAroundGen = SearchUtils.Counter(0)
    loopingGeneralSearchCutoff = 500

    def skip_func(
            nextTile,
            currentPriorityObject,
            pathList: typing.List[Tile]):
        _, genDist, _, pathCappedNeg, _, repeats, cappedAdj, maxGenDist = currentPriorityObject
        remainingArmy = pathCappedNeg + gen_army

        if repeats - force_wasted_moves > 0:
            return True

        if maxGenDist > genDist:
            countSearchedAroundGen.add(1)
            if maxGenDist > 5:
                # logging.info(f'bounded off loop path (skip)...? {str(fromTile)}->{str(nextTile)}')
                return True
            if countSearchedAroundGen.value > loopingGeneralSearchCutoff:
                return True

        for tile, prio in reversed(pathList):
            if nextTile == tile:
                return True

        return remainingArmy <= 0

    startVals: typing.Dict[Tile, typing.Tuple[object, int]] = {}
    startVals[general] = ((0, 0, -1000, 0, 0, 0, 0, 0), 0)
    if not no_log:
        logging.info(f'finding segment for genArmy {gen_army}, force_wasted_moves {force_wasted_moves}, alreadyVisited {len(visited_set)}')
    path = breadth_first_dynamic_max(
        map,
        startVals,
        value_func,
        noNeutralCities=True,
        priorityFunc=prio_func,
        skipFunc=skip_func,
        noLog=True,
        maxTurns=turns_left,
        useGlobalVisitedSet=False,
        includePath=True)

    return path
