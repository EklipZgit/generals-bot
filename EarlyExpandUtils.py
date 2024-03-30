import random

import logbook
import time
import typing

import SearchUtils
from MapMatrix import MapMatrix, MapMatrixSet
from Path import Path
from SearchUtils import breadth_first_foreach, breadth_first_dynamic_max
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile

DEBUG_ASSERTS = False
ALLOW_RANDOM_SKIPS = False

class ExpansionPlan(object):
    def __init__(self, tile_captures: int, plan_paths: typing.List[typing.Union[None, Path]], launch_turn: int, core_tile: Tile):
        self.core_tile: Tile = core_tile
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
        visitedSet: typing.Set[Tile] | None = None,
        noLog: bool = False) -> int:

    if len(expandPaths) == 0:
        return 0

    tilesCapped: typing.Set[Tile] = set()
    if visitedSet is not None:
        tilesCapped = visitedSet.copy()
    tilesCapped.add(general)
    enCapped = set()

    genArmy = generalArmy
    pathIdx = 0
    curPath: typing.Union[None, Path] = expandPaths[pathIdx]
    if curPath is not None:
        curPath = curPath.clone()
    movingArmy = 0
    for turn in range(curTurn, 50):
        movingGen = False
        pathComplete = False
        if curPath is None:
            if not noLog:
                logbook.info(f'{turn} ({genArmy}) - no-opped move')
            pathIdx += 1
            if pathIdx >= len(expandPaths):
                break
            pathComplete = True
            movingArmy = 0
        else:
            move = curPath.remove_start()
            if move.tile == general:
                movingArmy = genArmy
                movingGen = True

            nextTile = move.next.tile
            if nextTile in tilesCapped or map.is_player_on_team_with(nextTile.player, general.player):
                if not noLog:
                    logbook.info(f'{turn} ({genArmy}) - {str(nextTile)} (a{movingArmy}) already capped')
            else:
                movingArmy -= 1
                tilesCapped.add(nextTile)
                if nextTile.player >= 0:
                    enCapped.add(nextTile)
                if not noLog:
                    logbook.info(f'{turn} ({genArmy}) - {str(nextTile)} (a{movingArmy}) ({len(tilesCapped)})')
                if movingArmy <= 0 and DEBUG_ASSERTS:
                    raise AssertionError(f'illegal plan, moved army from 1 tile, see last log above')
            if curPath.length == 0:
                pathIdx += 1
                if pathIdx >= len(expandPaths):
                    break
                pathComplete = True
                if movingArmy > 1 and turn < 50:
                    if not noLog:
                        logbook.info(f"Army not fully used. {movingArmy} army ended at {str(nextTile)}, turn {turn}. Should almost never see this in a final result...")

        if pathComplete:
            curPath = expandPaths[pathIdx]
            if curPath is not None:
                curPath = curPath.clone()

        if movingGen:
            genArmy = 1

        if turn % 2 == 1:
            genArmy += 1

    if pathIdx < len(expandPaths) and map.turn < 25:
        errorMsg = f'Plan incomplete at turn 50, pathIdx {pathIdx} with subsequent paths {", ".join([str(path) for path in expandPaths[pathIdx:]])}'
        if DEBUG_ASSERTS:
            raise AssertionError(errorMsg)
        else:
            logbook.info(errorMsg)

    if not noLog:
        logbook.info(
            f'result of curTurn {curTurn}: capped {len(tilesCapped)}, final genArmy {genArmy}')

    return len(tilesCapped) + len(enCapped)

def __evaluate_plan_value(
        map: MapBase,
        general: Tile,
        general_army: int,
        cur_turn: int,
        path_list: typing.List[typing.Union[None, Path]],
        dist_to_gen_map: MapMatrix[int],
        tile_weight_map: MapMatrix[int],
        already_visited: typing.Set[Tile],
        no_log: bool = False
) -> typing.Tuple[int, int, int, int]:

    tileWeightSum = 0
    genDistSum = 0
    adjAvailable = SearchUtils.Counter(0)

    pathTileSet = set()
    visibleTileSet = already_visited.copy()
    for tile in already_visited:
        visibleTileSet.update(tile.adjacents)

    for path in path_list:
        if path is not None:
            visibleTileSet.update(path.tileList)
            pathTileSet.update(path.tileList)

    visibilityValue = SearchUtils.Counter(0.0)

    for tile in pathTileSet:
        tileWeightSum += tile_weight_map[tile]
        genDistSum += dist_to_gen_map[tile]
        for adj in tile.adjacents:
            if adj not in visibleTileSet:
                visibleTileSet.add(adj)
                if not adj.isNotPathable:
                    reward = 8 - tile_weight_map[adj]
                    if reward > 0:
                        visibilityValue.value += reward

    def count_func(tile: Tile):
        if (tile not in pathTileSet
                and tile not in already_visited
                and not tile.isNotPathable
                and not tile.isCity
                and tile.player == -1
                and tile.army == 0):
            adjAvailable.value += 1

    breadth_first_foreach(map, pathTileSet, 3, count_func, noLog=True)

    pathValue = get_start_expand_value(map, general, general_army, cur_turn, path_list, visitedSet=already_visited, noLog=no_log)

    return (
        pathValue,
        # adjAvailable.value,
        adjAvailable.value + int(visibilityValue.value),
        # int(visibilityValue.value),
        0 - tileWeightSum,
        genDistSum
    )


def max_plan(plan1: ExpansionPlan, plan2: ExpansionPlan, map: MapBase, distToGenMap, tile_weight_map, visited) -> ExpansionPlan:
    launchVal1 = __evaluate_plan_value(
        map,
        plan1.core_tile,
        plan1.core_tile.army,
        map.turn,
        plan1.plan_paths,
        dist_to_gen_map=distToGenMap,
        tile_weight_map=tile_weight_map,
        already_visited=visited,
        no_log=False)

    launchVal2 = __evaluate_plan_value(
        map,
        plan2.core_tile,
        plan2.core_tile.army,
        map.turn,
        plan2.plan_paths,
        dist_to_gen_map=distToGenMap,
        tile_weight_map=tile_weight_map,
        already_visited=visited,
        no_log=False)

    if launchVal1 >= launchVal2:
        return plan1

    return plan2


def optimize_first_25(
        map: MapBase,
        general: Tile,
        tile_minimization_map: MapMatrix[int],
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_recurse: bool = False,
        skipTiles: typing.Set[Tile] | None = None,
        no_log=not DEBUG_ASSERTS,
        cutoff_time: float | None = None,
        prune_cutoff: int = 14,
        cramped: bool = False
) -> ExpansionPlan:
    """

    @param map:
    @param general:
    @param tile_minimization_map: lower numbers = better
    @param debug_view_info: the viewInfo to write debug data to (mainly for unit testing).
    @param no_recurse: Used to prevent infinite recursion when optimizing with alt tile weights
    @param skipTiles: Tiles that will be not counted for expansion
    @param no_log: skip logging everything except the final result
    @return:
    """

    distToGenMap = map.distance_mapper.get_tile_dist_matrix(general)
    if debug_view_info:
        debug_view_info.bottomLeftGridText = distToGenMap

    visited: typing.Set[Tile] = set()
    #
    # if skipTiles is not None:
    #     visited = skipTiles.copy()

    for player in map.players:
        if map.is_player_on_team_with(player.index, general.player):
            player = map.players[general.player]
            for tile in player.tiles:
                visited.add(tile)

    mapTurnAtStart = map.turn
    genArmyAtStart = general.army

    if mapTurnAtStart > 25:
        turnInCycle = mapTurnAtStart % 50
        result = _sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            genArmyAtStart,
            distToGenMap,
            tile_minimization_map,
            turn=turnInCycle,
            visited_set=visited,
            prune_below=prune_cutoff,
            allow_wasted_moves=3,
            dont_force_first=True,
            debug_view_info=debug_view_info,
            skip_tiles=skipTiles,
            cutoff_time=cutoff_time,
            no_log=no_log)
        val = get_start_expand_value(map, general, genArmyAtStart, turnInCycle, result, visitedSet=visited, noLog=False)

        return ExpansionPlan(val, result, mapTurnAtStart, general)

    timeLimit = 3.0
    if cutoff_time:
        timeLimit = cutoff_time - time.perf_counter()
        cutoff_time = None

    if cramped:
        # genArmy, turn, optimalMaxWasteMoves
        combinationsWithMaxOptimal = [
            None,  # buys 11 more time
            (11, 20, 8),
            (10, 18, 10),
            (13, 24, 2),
            None,
            None,  # buys 9 more time
            (8, 14, 10),
            None,  # buys 7 more time
            (7, 12, 14),
            None,
            None,  # buys 7 more time
            (9, 16, 10),
            # None,  # buys 7 more time
            # None,  # buys 10 more time
            (14, 26, 0),
            (15, 28, 0),
            # (12, 22, 4),
            # (13, 24, 8),
        ]
    else:
        # genArmy, turn, optimalMaxWasteMoves
        combinationsWithMaxOptimal = [
            (13, 24, 2),  # most likely to find high value paths first
            (11, 20, 6),
            (10, 18, 8),
            None,  # buys 9 more time
            (9, 16, 10),
            (12, 22, 4),
            (14, 26, 0),
        ]
        # 12-6-5-4-1

    maxResult = None
    maxVal = None
    maxTiles = prune_cutoff
    startTime = time.perf_counter()

    i = 0
    for comboTuple in combinationsWithMaxOptimal:
        i += 1
        if comboTuple is None:
            continue
        (genArmy, launchTurn, optimalWastedMoves) = comboTuple
        perCutoff = cutoff_time
        if perCutoff is None:
            perCutoff = startTime + (timeLimit / len(combinationsWithMaxOptimal)) * i
        if mapTurnAtStart > launchTurn:
            continue

        launchResult = _sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            genArmy,
            distToGenMap,
            tile_minimization_map,
            turn=launchTurn,
            allow_wasted_moves=optimalWastedMoves + 3,
            debug_view_info=debug_view_info,
            visited_set=visited,
            prune_below=maxTiles,
            skip_tiles=skipTiles,
            cutoff_time=perCutoff,
            no_log=no_log)
        for _ in range(mapTurnAtStart, launchTurn):
            launchResult.insert(0, None)
        launchVal = __evaluate_plan_value(map, general, genArmyAtStart, map.turn, launchResult, dist_to_gen_map=distToGenMap, tile_weight_map=tile_minimization_map, already_visited=visited, no_log=no_log)
        logbook.info(f'{genArmy} ({optimalWastedMoves}) launch ({launchVal}) {">>>" if maxVal is None or maxVal < launchVal else "<"} prev launches (prev max {maxVal})')
        if maxVal is None or launchVal > maxVal:
            maxVal = launchVal
            maxResult = launchResult
            maxTiles = launchVal[0]
            if genArmy <= 8:
                # We need to early terminate if we're going to do a 7-plan
                break

    launchTurn = mapTurnAtStart
    for path in maxResult:
        if path is not None:
            break
        launchTurn += 1

    logbook.info(f'max launch result  v')
    get_start_expand_value(map, general, general.army, mapTurnAtStart, maxResult, visitedSet=visited, noLog=False)
    logbook.info(f'max launch result {maxVal}, turn {launchTurn} ^')

    return ExpansionPlan(maxVal[0], maxResult, launchTurn, general)


def _sub_optimize_first_25_specific_wasted(
        map: MapBase,
        general: Tile,
        gen_army: int,
        dist_to_gen_map: MapMatrix[int],
        tile_weight_map: MapMatrix[int],
        turn: int,
        force_wasted_moves: int,
        allow_wasted_moves: int,
        prune_below: int,
        visited_set: typing.Set[Tile],
        cutoff_time: float,
        additional_one_level_skip: Tile | None = None,
        skip_tiles: typing.Set[Tile] = None,
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

        if time.perf_counter() > cutoff_time:
            return capped, pathList

        visited_set = visited_set.copy()

        if not dont_force_first:

            if curAttemptGenArmy <= 1:
                raise AssertionError(f'Someone ran a sub_optimize_specific_wasted with gen army 1 lol')

            if additional_one_level_skip and ALLOW_RANDOM_SKIPS:
                skip_tiles.add(additional_one_level_skip)
            path1 = _optimize_25_launch_segment(
                map,
                general,
                curAttemptGenArmy,
                50 - curTurn,
                dist_to_gen_map,
                force_wasted_moves=force_wasted_moves,
                tile_weight_map=tile_weight_map,
                visited_set=visited_set,
                skip_tiles=skip_tiles,
                debug_view_info=debug_view_info,
                no_log=no_log)
            if additional_one_level_skip and ALLOW_RANDOM_SKIPS:
                skip_tiles.remove(additional_one_level_skip)

            if path1 is None:
                if not no_log:
                    logbook.info(f'got none path for genArmy {curAttemptGenArmy} with allow_wasted {force_wasted_moves} (already visited {len(visited_set)})')
                pathList.append(None)
                return capped, pathList

            capped = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, [path1], dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_visited=visited_set, no_log=no_log)

            if capped[0] == 0:
                pathList.append(None)
                logbook.info(f'got 0 value path {str(path1)}, returning None instead')
                return capped, pathList

            if not no_log:
                logbook.info(f'appending val {capped}, path {str(path1)}')

            pathList.append(path1)

            for tile in path1.tileList:
                if tile in visited_set and tile != general:
                    allow_wasted_moves -= 1
                visited_set.add(tile)

            curAttemptGenArmy = 1
            if not no_log:
                logbook.info(f'path1.length {path1.length} ({str(path1)})')
            for _ in range(path1.length):
                curTurn += 1
                if curTurn % 2 == 0:
                    curAttemptGenArmy += 1

        if curTurn >= 50:
            if not no_log:
                logbook.info(f'curTurn {curTurn} >= 50, returning current path')
            return capped, pathList

        allow_wasted_moves = max(0, allow_wasted_moves)

        # try immediate launch
        if not no_log:
            logbook.info(f'normal, curTurn {curTurn}, genArmy {curAttemptGenArmy}')
        maxOptimized = _sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            curAttemptGenArmy,
            dist_to_gen_map,
            tile_weight_map,
            curTurn,
            allow_wasted_moves,
            prune_below=prune_below,
            cutoff_time=cutoff_time,
            visited_set=visited_set,
            skip_tiles=skip_tiles,
            debug_view_info=debug_view_info,
            no_log=no_log)
        maxValue = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, maxOptimized, dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_visited=visited_set, no_log=no_log)

        isSuboptimalLaunchTurn = curTurn & 1 == 1
        # try one turn wait if turns remaining long enough
        if curTurn <= 47:
            curAttemptGenArmy += 1
            curTurn += 1
            allow_wasted_moves -= 1
            if not isSuboptimalLaunchTurn:
                curTurn += 1
                allow_wasted_moves -= 1
            if not no_log:
                logbook.info(
                    f'withWait (double: {not isSuboptimalLaunchTurn}), curTurn {curTurn}, genArmy {curAttemptGenArmy}')
            withOneWait = _sub_optimize_remaining_cycle_expand_from_cities(
                map,
                general,
                curAttemptGenArmy,
                dist_to_gen_map,
                tile_weight_map,
                curTurn,
                allow_wasted_moves,
                cutoff_time=cutoff_time,
                prune_below=max(maxValue[0], prune_below),
                visited_set=visited_set,
                skip_tiles=skip_tiles,
                debug_view_info=debug_view_info,
                no_log=no_log)
            oneWaitVal = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, withOneWait, dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_visited=visited_set, no_log=no_log)
            if oneWaitVal >= maxValue:
                if not no_log:
                    logbook.info(
                        f'waiting (double: {not isSuboptimalLaunchTurn}) until {curTurn} resulted in better yield, {maxValue} vs {oneWaitVal}')
                maxOptimized = withOneWait
                maxValue = oneWaitVal
                pathList.append(None)
                if not isSuboptimalLaunchTurn:
                    pathList.append(None)

        if maxValue[0] == 0:
            if not no_log:
                logbook.info('throwing out bad path')
            return maxValue, [None]

        for pathVal in maxOptimized:
            pathList.append(pathVal)

        return maxValue, pathList

def _sub_optimize_remaining_cycle_expand_from_cities(
        map: MapBase,
        general: Tile,
        gen_army: int,
        dist_to_gen_map: MapMatrix[int],
        tile_weight_map: MapMatrix[int],
        turn: int,
        allow_wasted_moves: int,
        prune_below: int,
        cutoff_time: float,
        visited_set: typing.Set[Tile] = None,
        skip_tiles: typing.Set[Tile] = None,
        dont_force_first: bool = False,
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS,
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
        logbook.info(f'sub-optimizing turn {turn} genArmy {gen_army}')

    maxCombinationValue = (0, 0, 0, 0)
    maxCombinationPathList = [None]
    if visited_set is None or len(visited_set) == 0:
        visited_set = set()
        visited_set.add(general)

    if skip_tiles is None and ALLOW_RANDOM_SKIPS:
        skip_tiles = set()

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

    # wastedAllowed = [i for i in range(allow_wasted_moves + 2, minWastedMovesThisLaunch)]

    for force_wasted_moves in range(minWastedMovesThisLaunch, allow_wasted_moves + 4):
        bestCaseResult = len(visited_set) + turnsLeft - force_wasted_moves
        if bestCaseResult <= prune_below:
            if not no_log:
                logbook.info(f'pruning due to bestCaseResult {bestCaseResult} compared to prune_below {prune_below}')
            break

        if time.perf_counter() > cutoff_time:
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
            skip_tiles=skip_tiles,
            dont_force_first=dont_force_first,
            debug_view_info=debug_view_info,
            cutoff_time=cutoff_time,
            no_log=no_log
        )

        if ALLOW_RANDOM_SKIPS:
            pathLen = len(pathList)
            if pathLen > 2:
                randomSkip = random.choice(pathList[1:min(pathLen - 1, 5)])

                altValue, altPathList = _sub_optimize_first_25_specific_wasted(
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
                    skip_tiles=skip_tiles,
                    additional_one_level_skip=randomSkip,
                    dont_force_first=dont_force_first,
                    debug_view_info=debug_view_info,
                    cutoff_time=cutoff_time,
                    no_log=no_log
                )

                if altValue > maxCombinationValue:
                    maxCombinationValue = altValue
                    maxCombinationPathList = altPathList
                    prune_below = max(prune_below, altValue[0])

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
        distance_to_gen_map: MapMatrix[int],
        force_wasted_moves: int,
        tile_weight_map: MapMatrix[int],
        visited_set: typing.Set[Tile],
        skip_tiles: typing.Set[Tile] = None,
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS
    ) -> typing.Union[None, Path]:

    if gen_army <= 1:
        if not no_log:
            logbook.info('RETURNING NONE from _optimize_25_launch_segment, gen_army <= 1')
        return None

    i = SearchUtils.Counter(0)

    def value_func(currentTile, priorityObject, pathList: typing.List[Tile]):
        _, currentGenDist, _, pathCappedNeg, negAdjWeight, repeats, cappedAdj, maxGenDist = priorityObject
        # currentGenDist = 0 - negCurrentGenDist
        # higher better
        tileValue = 0 - tile_weight_map[currentTile]

        if repeats - force_wasted_moves > 0:
            return None

        if pathCappedNeg == 0:
            return None

        # dont return paths that end in an already capped tile
        if currentTile in visited_set:
            return None

        if map.is_tile_friendly(currentTile):
            return None

        # if currentGenDist < fromTileGenDist:
        #     logbook.info(f'bounded off loop path (value)...? {str(fromTile)}->{str(currentTile)}')
            # return None

        valObj = 0 - pathCappedNeg, 0 - abs(repeats - force_wasted_moves), 0 - cappedAdj, currentGenDist, tileValue - negAdjWeight / 3

        return valObj

    # must always prioritize the tiles furthest from general first, to make sure we dequeue in the right order
    def prio_func(nextTile, currentPriorityObject, pathList: typing.List[Tile]):
        repeatAvoider, _, closerToEnemyNeg, pathCappedNeg, negAdjWeight, repeats, cappedAdj, maxGenDist = currentPriorityObject
        visited = nextTile in visited_set
        if not visited:
            pathCappedNeg -= 1
            if nextTile.player != -1:
                pathCappedNeg -= 1
        else:
            repeats += 1

        if debug_view_info:
            i.add(1)
            debug_view_info.bottomRightGridText[nextTile] = i.value

        #
        # if pathCappedNeg + genArmy <= 0:
        #     logbook.info(f'tile {str(nextTile)} ought to be skipped...?')
        #     return None

        closerToEnemyNeg = tile_weight_map[nextTile]

        # 0 is best value we'll get, after which more repeat tiles become 'bad' again
        repeatAvoider = abs(force_wasted_moves - repeats)
        distToGen = min(1000, distance_to_gen_map[nextTile])
        adjWeight = 0 - negAdjWeight

        remainingArmy = pathCappedNeg + gen_army
        if remainingArmy > 4:
            adjWeight += SearchUtils.count(
                nextTile.movable,
                lambda tile: tile not in visited_set
                             and distance_to_gen_map[tile] >= distToGen  #and tile is further from general
                             and tile.player == -1
                             and not tile.isNotPathable
                             and not tile.isCity)

            adjWeight += SearchUtils.count(
                nextTile.movable,
                lambda tile: tile not in visited_set
                             and distance_to_gen_map[tile] > distToGen  #and tile is further from general
                             and tile.player == -1
                             and not tile.isNotPathable
                             and not tile.isCity)

        if distToGen < 4 and nextTile not in visited_set:
            cappedAdj += 1
            repeatAvoider += cappedAdj

        if debug_view_info:
            debug_view_info.midRightGridText[nextTile] = adjWeight

        maxGenDist = max(maxGenDist, distToGen)

        priObj = repeatAvoider, distToGen, closerToEnemyNeg, pathCappedNeg, 0 - adjWeight, repeats, cappedAdj, maxGenDist

        return priObj

    countSearchedAroundGen = SearchUtils.Counter(0)
    loopingGeneralSearchCutoff = 500

    def skip_func(
            nextTile: Tile,
            currentPriorityObject,
            pathList: typing.List[Tile]):
        _, genDist, _, pathCappedNeg, _, repeats, cappedAdj, maxGenDist = currentPriorityObject
        remainingArmy = pathCappedNeg + gen_army

        if skip_tiles is not None and nextTile in skip_tiles:
            return True

        if repeats - force_wasted_moves > 0:
            return True

        if nextTile.player in map.teammates:
            return True

        if maxGenDist > genDist:
            countSearchedAroundGen.add(1)
            if maxGenDist > 5:
                # logbook.info(f'bounded off loop path (skip)...? {str(fromTile)}->{str(nextTile)}')
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
        logbook.info(f'finding segment for genArmy {gen_army}, force_wasted_moves {force_wasted_moves}, alreadyVisited {len(visited_set)}')
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
