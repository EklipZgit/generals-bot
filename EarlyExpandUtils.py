import random

import logbook
import time
import typing

import SearchUtils
from DataModels import Move
from MapMatrix import MapMatrix, MapMatrixSet
from Path import Path
from SearchUtils import breadth_first_foreach, breadth_first_dynamic_max
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile

DEBUG_ASSERTS = False
ALLOW_RANDOM_SKIPS = False


EMPTY_COMBINATION = (0, 0, 0, 0)


class ExpansionPlan(object):
    def __init__(self, tile_captures: int, plan_paths: typing.List[Path | None], launch_turn: int, core_tile: Tile):
        self.core_tile: Tile = core_tile
        self.tile_captures: int = tile_captures
        self.launch_turn: int = launch_turn
        if plan_paths is None:
            plan_paths = []
        self.plan_paths: typing.List[Path | None] = plan_paths


def get_start_expand_captures(
        map: MapBase,
        general: Tile,
        generalArmy: int,
        curTurn: int,
        expandPaths: typing.List[Path | None],
        alreadyOwned: typing.Set[Tile] | None = None,
        launchTurn: int = -1,
        noLog: bool = False
) -> int:
    """
    Does NOT update the visitedSet.
    Returns the number of NEW tiles captured that are not already owned.
    None's represent waiting moves, paths represent path moves.
    Include launchTurn to simplify the None BS.

    @param map:
    @param general:
    @param generalArmy: General army ON current turn (not at launch turn)
    @param curTurn:
    @param expandPaths:
    @param alreadyOwned:
    @param launchTurn: if launchTurn is provided, the leading Nones will be ignored and we'll begin at launchTurn from the first non-None path (after incrementing general army from generalArmy at current turn).
    @param noLog:
    @return:
    """
    if not expandPaths:
        return 0

    genPlayer = general.player

    # logbook.info(f'running get_start_expand_value')
    #
    # if visitedSet is not None:
    #     tilesCapped: typing.Set[Tile] = {t for t in visitedSet if t.player == general.player}
    # else:
    alreadyVisited: typing.Set[Tile]
    if alreadyOwned:
        alreadyVisited = alreadyOwned.copy()
    else:
        logbook.info(f'REMOVE ME initing empty alreadyVisited set')
        alreadyVisited = set(map.players[genPlayer].tiles)
        # alreadyVisited.add(general)

    numCapped = 0

    enCapped = set()

    curGenArmy = generalArmy
    pathIdx = 0
    p = expandPaths[pathIdx]
    if launchTurn != -1:
        while p is None and pathIdx + 1 < len(expandPaths):
            pathIdx += 1
            p = expandPaths[pathIdx]

        logbook.info(f'incrementing curTurn {curTurn} towards launchTurn {launchTurn}, dropped {pathIdx} Nones')
        while curTurn < launchTurn:
            curTurn += 1
            if curTurn & 1 == 0:
                curGenArmy += 1

    curMoves: typing.List[Move] | None = None

    if p is not None:
        curMoves = p.get_move_list()

    curMoveIdx = 0
    movingArmy = 0

    teamPlayers = map.get_teammates_no_self(genPlayer)

    turn = curTurn
    if not noLog:
        logbook.info(f'get_start_expand_value turn {curTurn}, genArmy {generalArmy}, paths {len(expandPaths)}, alreadyVisited {len(alreadyVisited)} - {" | ".join([str(t) for t in sorted(alreadyVisited)])}')
    while turn <= 50:
        movingGen = False
        pathComplete = False
        if curMoves is None:
            if not noLog:
                logbook.info(f'{turn} ({curGenArmy}) - no-opped move')
            pathIdx += 1
            if pathIdx >= len(expandPaths):
                break
            pathComplete = True
            movingArmy = 0
        else:
            move = curMoves[curMoveIdx]
            if move.source == general:
                movingArmy = curGenArmy
                movingGen = True
            elif move.dest.isGeneral:
                raise AssertionError(f'Pathed into another general....? {move}')

            curMoveIdx += 1

            nextTile = move.dest
            if nextTile in alreadyVisited:
                if not noLog:
                    logbook.info(f'{turn} ({curGenArmy}) - {str(nextTile)} (a{movingArmy}) already capped')
            elif nextTile.player in teamPlayers:
                if not noLog:
                    logbook.info(f'{turn} ({curGenArmy}) - {str(nextTile)} (a{movingArmy}) was ally tile')
            else:
                numCapped += 1
                movingArmy -= 1

                alreadyVisited.add(nextTile)
                if nextTile.player >= 0:
                    enCapped.add(nextTile)
                    # TODO wait, we don't decrement this because we currently want to route THROUGH enemy tiles as if they werent there (?) I uncommented this for now to see what goes wrong.
                    movingArmy -= nextTile.army
                    if not noLog:
                        logbook.info(f'{turn} ({curGenArmy}) - {str(nextTile)} (a{movingArmy}) ({len(alreadyVisited)}) CAPPED EN')
                elif not noLog:
                    logbook.info(f'{turn} ({curGenArmy}) - {str(nextTile)} (a{movingArmy}) ({len(alreadyVisited)})')

                if movingArmy <= 0 and DEBUG_ASSERTS and len(enCapped) == 0:
                    tileState = f'{turn} ({curGenArmy}) - {str(nextTile)} (a{movingArmy}) ({len(alreadyVisited)})'
                    if noLog:
                        logbook.error(tileState)
                    msg = '^^^^^^illegal plan, moved negative army^^^^^^'
                    logbook.error(msg)
                    raise AssertionError(f'{tileState}\r\n{msg}')
            if curMoveIdx >= len(curMoves):
                pathIdx += 1
                if pathIdx >= len(expandPaths):
                    break
                pathComplete = True
                if movingArmy > 1 and turn < 50:
                    if not noLog:
                        logbook.info(f"Army not fully used. {movingArmy} army ended at {str(nextTile)}, turn {turn}. Should almost never see this in a final result...")

        if pathComplete:
            p = expandPaths[pathIdx]
            curMoves = None
            if p is not None:
                curMoves = p.get_move_list()
                curMoveIdx = 0

        if movingGen:
            curGenArmy = 1

        if turn & 1 == 1:
            curGenArmy += 1

        turn += 1

    if pathIdx < len(expandPaths) and map.turn < 25:
        errorMsg = f'Plan incomplete at turn 50 (there were extra moves in the plan), pathIdx {pathIdx} with subsequent paths {", ".join([str(path) for path in expandPaths[pathIdx:]])}'
        if DEBUG_ASSERTS:
            raise AssertionError(errorMsg)
        else:
            logbook.error(errorMsg)

    if not noLog:
        logbook.info(
            f'result of curTurn {curTurn}: newCapped {numCapped}, capped {len(alreadyVisited)}, enCapped {len(enCapped)}, final genArmy {curGenArmy}')

    # return numCapped
    return len(alreadyVisited)


def __evaluate_plan_value(
        map: MapBase,
        general: Tile,
        general_army: int,
        cur_turn: int,
        path_list: typing.List[Path | None],
        dist_to_gen_map: MapMatrix[int],
        tile_weight_map: MapMatrix[int],
        already_owned: typing.Set[Tile],
        launch_turn: int = -1,
        no_log: bool = False
) -> typing.Tuple[int, int, int, int]:
    """

    @param map:
    @param general:
    @param general_army:
    @param cur_turn:
    @param path_list:
    @param dist_to_gen_map:
    @param tile_weight_map:
    @param already_owned: Must be ONLY the players tiles, no ally tiles or skip tiles.
    @param launch_turn: if set to something other than -1, Nones will be ignored at the start of the thingy
    @param no_log:
    @return:
    """

    adjAvailable = SearchUtils.Counter(0)

    planTileSet = set()
    visibleTileSet = already_owned.copy()
    for tile in already_owned:
        # no points for stuff we can already see
        visibleTileSet.update(tile.adjacents)

    for path in path_list:
        if path is not None:
            visibleTileSet.update(path.tileList)
            planTileSet.update(path.tileList)

    tileWeightSum = 0
    genDistSum = 0
    visibilityValue = 0.0
    for tile in planTileSet:
        tileWeightSum += tile_weight_map[tile]
        genDistSum += dist_to_gen_map[tile]

        for adj in tile.adjacents:
            if adj not in visibleTileSet:
                visibleTileSet.add(adj)
                if not adj.isObstacle:
                    # TODO the fuck is this 8 - *? We should straight up respect the tile_weight_map, not do janky math in here. If we expect to use this weighting, then we damn well should build the -8 into the weight map instead.
                    reward = 8 - tile_weight_map[adj]
                    if reward > 0:
                        visibilityValue += reward

    def count_func(tile: Tile):
        if (tile not in planTileSet
                and tile not in already_owned
                and not tile.isNotPathable
                and not tile.isCity
                and tile.player == -1
                and tile.army == 0):
            adjAvailable.value += 1

    SearchUtils.breadth_first_foreach_fast_no_neut_cities(map, planTileSet, 3, count_func)

    pathValue = get_start_expand_captures(map, general, general_army, cur_turn, path_list, alreadyOwned=already_owned, launchTurn=launch_turn, noLog=no_log)
    # pathValue = len(already_owned) + get_start_expand_captures(map, general, general_army, cur_turn, path_list, alreadyOwned=already_owned, noLog=no_log)

    return (
        pathValue,
        # adjAvailable.value,
        adjAvailable.value + int(visibilityValue),
        # int(visibilityValue.value),
        0 - tileWeightSum,
        genDistSum
    )


def recalculate_max_plan(plan1: ExpansionPlan, plan2: ExpansionPlan, map: MapBase, distToGenMap, tile_weight_map, visited, no_log: bool = False) -> ExpansionPlan:
    launchVal1 = __evaluate_plan_value(
        map,
        plan1.core_tile,
        plan1.core_tile.army,
        map.turn,
        plan1.plan_paths,
        dist_to_gen_map=distToGenMap,
        tile_weight_map=tile_weight_map,
        already_owned=visited,
        no_log=no_log)

    plan1.tile_captures = launchVal1[0]

    launchVal2 = __evaluate_plan_value(
        map,
        plan2.core_tile,
        plan2.core_tile.army,
        map.turn,
        plan2.plan_paths,
        dist_to_gen_map=distToGenMap,
        tile_weight_map=tile_weight_map,
        already_owned=visited,
        no_log=no_log)

    plan2.tile_captures = launchVal2[0]

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
        prune_cutoff: int = -1,
        cramped: bool = False,
        shuffle_launches: bool = False
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

    alreadyOwned: typing.Set[Tile] = set(map.players[general.player].tiles)

    #
    # if skipTiles is not None:
    #     visited = skipTiles.copy()

    # for player in map.players:
    #     if map.is_player_on_team_with(player.index, general.player):
    #         player = map.players[general.player]
    #         for tile in player.tiles:
    #             visited.add(tile)

    mapTurnAtStart = map.turn
    genArmyAtStart = general.army

    maxResultPaths = None
    maxVal = None
    maxTiles = prune_cutoff

    if prune_cutoff == -1:
        if map.turn > 13:
            # Get a preliminary no-wasted-moves result as our baseline
            startTime = time.perf_counter()
            genArmy = general.army

            launchResult = _sub_optimize_remaining_cycle_expand_from_cities(
                map,
                general,
                general.army,
                distToGenMap,
                tile_minimization_map,
                turn=map.turn,
                allow_wasted_moves=-20,  # force no wasted moves for this attempt
                debug_view_info=debug_view_info,
                visited_set=alreadyOwned,
                prune_below=maxTiles,
                skip_tiles=skipTiles,
                cutoff_time=0.01,
                no_log=no_log)

            launchVal = __evaluate_plan_value(map, general, genArmyAtStart, map.turn, launchResult, dist_to_gen_map=distToGenMap, tile_weight_map=tile_minimization_map, already_owned=alreadyOwned, no_log=no_log)
            logbook.info(f'{genArmy} NO WASTED BASELINE launch ({launchVal}) in {time.perf_counter() - startTime:.4f}s')
            maxVal = launchVal
            maxResultPaths = launchResult
            maxTiles = launchVal[0]
        else:
            prune_cutoff = 16

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

    if shuffle_launches:
        random.shuffle(combinationsWithMaxOptimal)

    if len(alreadyOwned) > 1:
        logbook.info(f'DUE TO NUM VISITED {len(alreadyOwned)}, USING NON-PRE-ARRANGED WASTED COUNTS')
        turnInCycle = mapTurnAtStart % 50
        allowWasted = 3
        if map.turn < 50:
            # determine phase in launch cycle:
            tileCount = len(map.players[general.player].tiles)
            turnsLeft = 50 - turnInCycle
            capsLeftForPerfect = 25 - tileCount
            allowWasted = turnsLeft - capsLeftForPerfect
            logbook.info(f'NON PRE ARRANGED: for turn {map.turn} with turns left {turnsLeft} and tileCount {tileCount}, capsLeftForPerfect was {capsLeftForPerfect}, so allowWasted was {allowWasted}')
        result = _sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            genArmyAtStart,
            distToGenMap,
            tile_minimization_map,
            turn=turnInCycle,  # TODO is this +1 right...?
            visited_set=alreadyOwned,
            prune_below=prune_cutoff,
            allow_wasted_moves=allowWasted,
            shuffle_launches=shuffle_launches,
            dont_force_first=True,
            debug_view_info=debug_view_info,
            skip_tiles=skipTiles,
            cutoff_time=cutoff_time,
            no_log=no_log)

        val = get_start_expand_captures(map, general, genArmyAtStart, turnInCycle, result, alreadyOwned=alreadyOwned, noLog=False)
        # val = len(alreadyOwned) + get_start_expand_captures(map, general, genArmyAtStart, turnInCycle, result, alreadyOwned=alreadyOwned, noLog=False)

        return ExpansionPlan(val, result, mapTurnAtStart, general)

    timeLimit = 3.0
    if cutoff_time:
        timeLimit = cutoff_time - time.perf_counter()
        cutoff_time = None

    startTime = time.perf_counter()

    i = 0
    for comboTuple in combinationsWithMaxOptimal:
        i += 1
        if comboTuple is None:
            continue
        (genArmy, launchTurn, optimalWastedMoves) = comboTuple
        perCutoff = cutoff_time
        if perCutoff is None:
            if shuffle_launches:
                perCutoff = startTime + timeLimit
            else:
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
            visited_set=alreadyOwned,
            prune_below=maxTiles,
            skip_tiles=skipTiles,
            cutoff_time=perCutoff,
            no_log=no_log)
        for _ in range(mapTurnAtStart, launchTurn):
            launchResult.insert(0, None)
        launchVal = __evaluate_plan_value(map, general, genArmyAtStart, map.turn, launchResult, dist_to_gen_map=distToGenMap, tile_weight_map=tile_minimization_map, already_owned=alreadyOwned, no_log=no_log)
        logbook.info(f'{genArmy} ({optimalWastedMoves}) launch ({launchVal}) {">>>" if maxVal is None or maxVal < launchVal else "<"} prev launches (prev max {maxVal})')
        if maxVal is None or launchVal > maxVal:
            maxVal = launchVal
            maxResultPaths = launchResult
            maxTiles = launchVal[0]
            if genArmy <= 8:
                # We need to early terminate if we're going to do a 7-plan
                break

    launchTurn = mapTurnAtStart
    maxTiles = 0
    if maxResultPaths is not None:
        for path in maxResultPaths:
            if path is not None:
                break
            launchTurn += 1
        maxTiles = maxVal[0]

    logbook.info(f'max launch result  v')
    val = get_start_expand_captures(map, general, general.army, mapTurnAtStart, maxResultPaths, alreadyOwned=alreadyOwned, noLog=False)
    # val = len(alreadyOwned) + get_start_expand_captures(map, general, general.army, mapTurnAtStart, maxResultPaths, alreadyOwned=alreadyOwned, noLog=False)
    logbook.info(f'max launch result {maxVal}, turn {launchTurn} ^')
    if val != maxTiles:
        raise AssertionError(f'maxTiles {maxTiles} did not match expand val {val}')

    return ExpansionPlan(maxTiles, maxResultPaths, launchTurn, general)


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
        shuffle_launches: bool = False,
        dont_force_first: bool = False,
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS
    ) -> typing.Tuple[typing.Tuple[int, int, int, int], typing.List[Path | None]]:
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
        @param shuffle_launches: if set to True, will randomize launch combinations
        @param dont_force_first: If true, will not force a segment at this exact timing and will instead test subsegments now and at the next general bonus turn.
        @param debug_view_info:
        @param no_log:
        @return:
        """
        pathList = []
        curAttemptGenArmy = gen_army

        curTurn = turn
        capped = EMPTY_COMBINATION

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

            capped = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, [path1], dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_owned=visited_set, no_log=no_log)

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
                if curTurn & 1 == 0:
                    curAttemptGenArmy += 1

        if curTurn >= 50:
            if not no_log:
                logbook.info(f'curTurn {curTurn} >= 50, returning current path')
            return capped, pathList

        allow_wasted_moves = max(0, allow_wasted_moves)

        # try immediate launch
        if not no_log:
            logbook.info(f'immediate, curTurn {curTurn}, genArmy {curAttemptGenArmy}')
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
        maxValue = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, maxOptimized, dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_owned=visited_set, no_log=no_log)

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
            oneWaitVal = __evaluate_plan_value(map, general, curAttemptGenArmy, curTurn, withOneWait, dist_to_gen_map=dist_to_gen_map, tile_weight_map=tile_weight_map, already_owned=visited_set, no_log=no_log)
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
        shuffle_launches: bool = False,
        dont_force_first: bool = False,
        debug_view_info: typing.Union[None, ViewInfo] = None,
        no_log: bool = not DEBUG_ASSERTS,
    ) -> typing.List[Path | None]:
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
    @param shuffle_launches: if set to True, will randomize launch combinations
    @param dont_force_first:
    @param debug_view_info:
    @return:
    """
    if not no_log:
        logbook.info(f'sub-optimizing tile {general} - turn {turn} genArmy {gen_army}')

    maxCombinationValue = EMPTY_COMBINATION
    maxCombinationPathList = [None]
    if visited_set is None or len(visited_set) == 0:
        visited_set = set(map.players[general.player].tiles)
        # visited_set = set()
        # visited_set.add(general)

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
            if turn & 1 == 1:
                turn += 1
                allow_wasted_moves -= 1
                skipMoveCount += 1
    turnsLeft = 50 - turn

    if turnsLeft <= 0:
        return []

    minWastedMovesThisLaunch = max(0, allow_wasted_moves // 2 - 2)

    # wastedAllowed = [i for i in range(allow_wasted_moves + 2, minWastedMovesThisLaunch)]
    maxForce = allow_wasted_moves + 4
    visitLen = len(visited_set)
    if visitLen > 6 and maxForce > visitLen - 1:
        maxForce = visitLen - 1

    forced = [i for i in range(minWastedMovesThisLaunch, maxForce)]
    if shuffle_launches:
        random.shuffle(forced)
    for force_wasted_moves in forced:
        bestCaseResult = len(visited_set) + turnsLeft - force_wasted_moves
        if bestCaseResult < prune_below:
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
            shuffle_launches=shuffle_launches,
            dont_force_first=dont_force_first,
            debug_view_info=debug_view_info,
            cutoff_time=cutoff_time,
            no_log=no_log
        )

        if ALLOW_RANDOM_SKIPS:
            pathLen = len(pathList)
            if pathLen > 5:
                randomSkip = random.choice(pathList[1:min(pathLen - 1, 6)])

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
                    shuffle_launches=shuffle_launches,
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
) -> Path | None:
    searchingPlayer = map.player_index
    friendlyPlayers = map.get_teammates(searchingPlayer)

    if gen_army <= 1:
        if not no_log:
            logbook.info('RETURNING NONE from _optimize_25_launch_segment, gen_army <= 1')
        return None

    i = SearchUtils.Counter(0)

    def value_func(currentTile: Tile, priorityObject, pathList: typing.List[Tile]):
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

        if currentTile.player in friendlyPlayers:
            return None

        # if currentGenDist < fromTileGenDist:
        #     logbook.info(f'bounded off loop path (value)...? {str(fromTile)}->{str(currentTile)}')
            # return None

        valObj = 0 - pathCappedNeg, 0 - abs(repeats - force_wasted_moves), 0 - cappedAdj, currentGenDist, tileValue - negAdjWeight / 3

        return valObj

    adjCapableRewards = [-0.3, 0.0, 0.1, 0.2]

    # must always prioritize the tiles furthest from general first, to make sure we dequeue in the right order
    def prio_func(nextTile: Tile, currentPriorityObject, pathList: typing.List[typing.Tuple[Tile, typing.Any]]):
        repeatAvoider, _, closerToEnemyNeg, pathCappedNeg, negAdjWeight, repeats, cappedAdj, maxGenDist = currentPriorityObject
        visited = nextTile in visited_set
        if not visited:
            pathCappedNeg -= 1
            if nextTile.player != -1 and nextTile.player not in friendlyPlayers:
                pathCappedNeg -= 1
        else:
            repeats += 1

        if debug_view_info:
            i.add(1)
            debug_view_info.bottomRightGridText.raw[nextTile.tile_index] = i.value

        #
        # if pathCappedNeg + genArmy <= 0:
        #     logbook.info(f'tile {str(nextTile)} ought to be skipped...?')
        #     return None

        closerToEnemyNeg = tile_weight_map.raw[nextTile.tile_index]

        # 0 is best value we'll get, after which more repeat tiles become 'bad' again
        repeatAvoider = abs(force_wasted_moves - repeats)
        distToGen = distance_to_gen_map.raw[nextTile.tile_index]
        adjWeight = 0 - negAdjWeight

        if 1 < distToGen < 5:
            # deprioritize paths that orphan tiles, prefer leaving continuous space open.
            # Fixes test__only_got_24_when_seems_easy_25__V2__turn50__force_11_launch
            adjAdjust = 0.0
            for tile in nextTile.movable:
                if tile.isObstacle or tile.player != -1 or tile in visited_set or tile is pathList[-1][0] or tile is pathList[-2][0]:
                    continue
                adjCapable = 0
                for tileAdj in tile.movable:
                    if tileAdj.isObstacle or tileAdj.player != -1 or tileAdj in visited_set or tileAdj is nextTile or tileAdj is pathList[-1][0] or tileAdj is pathList[-2][0]:
                        continue
                    adjCapable += 1
                adjAdjust += adjCapableRewards[adjCapable]
            adjWeight += adjAdjust
            repeatAvoider -= adjAdjust

        remainingArmy = pathCappedNeg + gen_army
        if remainingArmy > 4:
            for tile in nextTile.movable:
                valid = (
                    tile not in visited_set
                    and tile.player == -1
                    and not tile.isNotPathable
                    and not tile.isCity
                )
                if valid and distance_to_gen_map.raw[tile.tile_index] >= distToGen:  # and tile is further from general
                    adjWeight += 1
                if valid and distance_to_gen_map.raw[tile.tile_index] > distToGen:  # and tile is further from general
                    adjWeight += 1

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
            pathList: typing.List[typing.Tuple[Tile, typing.Any]]):
        _, genDist, _, pathCappedNeg, _, repeats, cappedAdj, maxGenDist = currentPriorityObject
        remainingArmy = pathCappedNeg + gen_army

        if skip_tiles is not None and nextTile in skip_tiles:
            return True

        if repeats - force_wasted_moves > 0:
            return True

        # if nextTile.player in friendlyPlayers:
        #     return True

        if maxGenDist > genDist:
            countSearchedAroundGen.add(1)
            if maxGenDist > 5:
                # logbook.info(f'bounded off loop path (skip)...? {str(fromTile)}->{str(nextTile)}')
                return True
            if countSearchedAroundGen.value > loopingGeneralSearchCutoff:
                return True

        # for (lenBack, (tile, prio)) in enumerate(reversed(pathList)):
        #     if nextTile is tile:
        #         return True
        #     if lenBack > 9:
        #         break

        for (tile, prio) in reversed(pathList):
            if nextTile is tile:
                return True

        return remainingArmy <= 0

    startVals: typing.Dict[Tile, typing.Tuple[object, int]] = {general: ((0, 0, -1000, 0, 0, 0, 0, 0), 0)}
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
        useGlobalVisitedSet=False,  # has to be false so we try multiple combinations of deviations from the re-traversal in one go.
        includePath=True)

    return path
