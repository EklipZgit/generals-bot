import logging
import time
import traceback
import typing

import DebugHelper
import KnapsackUtils
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from KnapsackUtils import solve_knapsack
from MapMatrix import MapMatrix
from Path import Path
from PerformanceTimer import PerformanceTimer
from SearchUtils import breadth_first_foreach, count, where
from ViewInfo import PathColorer, ViewInfo
from base.client.map import Tile, MapBase


# attempt to get this to a* able?
def get_expansion_single_knapsack_path_trimmed(
        paths: typing.List[typing.Tuple[int, int, Path]],
        targetPlayers: typing.List[int],
        turns: int,
        enemyDistMap: typing.List[typing.List[int]],
        calculateTrimmable: bool,
        territoryMap: typing.List[typing.List[int]],
        viewInfo: ViewInfo,
) -> typing.Tuple[Path | None, typing.List[Path]]:
    """
    Knapsacks a set of paths that all start from unique tiles, and returns the best one.

    @param paths:
    @param targetPlayers:
    @param turns:
    @param enemyDistMap:
    @param calculateTrimmable:
    @param territoryMap:
    @param viewInfo:
    @return:
    """

    trimmable = {}
    if calculateTrimmable:
        for friendlyCityCount, tilesCaptured, path in paths:
            tailNode = path.tail
            trimCount = 0
            while tailNode.tile.player == -1 and territoryMap[tailNode.tile.x][
                tailNode.tile.y] not in targetPlayers and tailNode.tile.discovered:
                trimCount += 1
                tailNode = tailNode.prev
            if trimCount > 0:
                trimmable[path.start.tile] = (path, trimCount)

            if viewInfo:
                viewInfo.bottomRightGridText[path.start.tile.x][path.start.tile.y] = f'cap{tilesCaptured:.1f}'
                # viewInfo.paths.appendleft(PathColorer(path, 180, 51, 254, alpha, alphaDec, minAlpha))

    intFactor = 100
    # build knapsack weights and values
    weights = [path.length for friendlyCityCount, tilesCaptured, path in paths]
    values = [int(intFactor * tilesCaptured) for friendlyCityCount, tilesCaptured, path in paths]
    logging.info(f"Feeding the following paths into knapsackSolver at turns {turns}...")
    for i, pathTuple in enumerate(paths):
        friendlyCityCount, tilesCaptured, curPath = pathTuple
        logging.info(f"{i}:  cap {tilesCaptured:.2f} length {curPath.length} path {curPath.toString()}")

    totalValue, maxKnapsackedPaths = solve_knapsack(paths, turns, weights, values)
    logging.info(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")

    path: typing.Union[None, Path] = None
    if len(maxKnapsackedPaths) > 0:
        maxVal = (-10000, -1)
        totalTrimmable = 0
        for friendlyCityCount, tilesCaptured, curPath in maxKnapsackedPaths:
            if curPath.start.tile in trimmable:
                logging.info(
                    f"trimmable in current knapsack, {curPath.toString()} (friendlyCityCount {friendlyCityCount}, tilesCaptured {tilesCaptured})")
                trimmablePath, possibleTrim = trimmable[curPath.start.tile]
                totalTrimmable += possibleTrim
        logging.info(f"totalTrimmable! {totalTrimmable}")

        if totalTrimmable > 0:
            trimmableStart = time.perf_counter()
            trimRange = min(10, 1 + totalTrimmable)
            # see if there are better knapsacks if we trim the ends off some of these
            maxKnapsackVal = totalValue
            for i in range(trimRange):
                otherValue, otherKnapsackedPaths = solve_knapsack(paths, turns + i, weights, values)
                # offset by i to compensate for the skipped moves
                otherValueWeightedByTrim = otherValue - i * intFactor
                logging.info(
                    f"i {i} - otherKnapsackedPaths value {otherValue} weightedValue {otherValueWeightedByTrim} length {len(otherKnapsackedPaths)}")
                if otherValueWeightedByTrim > maxKnapsackVal:
                    maxKnapsackVal = otherValueWeightedByTrim
                    maxKnapsackedPaths = otherKnapsackedPaths
                    logging.info(f"NEW MAX {maxKnapsackVal}")
            logging.info(
                f"(Time spent on {trimRange} trimmable iterations: {time.perf_counter() - trimmableStart:.3f})")
        # Select which of the knapsack paths to move first
        logging.info("Selecting which of the above paths to move first")
        for friendlyCityCount, tilesCaptured, curPath in maxKnapsackedPaths:
            trimmableVal = 0
            if curPath.start.tile in trimmable:
                trimmablePath, possibleTrim = trimmable[curPath.start.tile]
                trimmableVal = possibleTrim
            # Paths ending with the largest armies go first to allow for more path selection options later
            thisVal = (0 - friendlyCityCount,
                       curPath.value,
                       0 - trimmableVal,
                       0 - enemyDistMap[curPath.start.tile.x][curPath.start.tile.y],
                       tilesCaptured / curPath.length)
            if thisVal > maxVal:
                maxVal = thisVal
                path = curPath
                logging.info(
                    f"new max val, eval [{'], ['.join(str(x) for x in maxVal)}], path {path.toString()}")
            else:
                logging.info(
                    f"NOT max val, eval [{'], ['.join(str(x) for x in thisVal)}], path {curPath.toString()}")

    otherPaths = [p for _, _, p in maxKnapsackedPaths if p != path]

    for curPath in otherPaths:
        if viewInfo:
            # draw other paths darker
            alpha = 150
            minAlpha = 150
            alphaDec = 0
            viewInfo.paths.appendleft(PathColorer(curPath, 200, 51, 204, alpha, alphaDec, minAlpha))

        # draw maximal path brighter
        alpha = 255
        minAlpha = 200
        alphaDec = 0
        if viewInfo:
            viewInfo.paths.appendleft(PathColorer(path, 255, 100, 200, alpha, alphaDec, minAlpha))

    return path, otherPaths


def path_has_cities_and_should_wait(
        path: Path | None,
        friendlyPlayers,
        playerCities: typing.List[Tile],
        negativeTiles: typing.Set[Tile],
        territoryMap: typing.List[typing.List[int]],
        remainingTurns: int
) -> bool:
    cityCount = 0
    for c in playerCities:
        if c in path.tileSet:
            cityCount += 1

    if cityCount == 0:
        return False

    if path.length >= remainingTurns:
        return False

    # TODO get better about this later
    assumeTerritoryTileValue = 1
    if remainingTurns > 20:
        # assume 2's, otherwise assume 1s
        assumeTerritoryTileValue = 2

    pathWorstCaseTurns = 0
    curArmy = 0
    turn = 0
    worstCaseArmy = 0
    for tile in path.tileList:
        tileRealArmyCost = tile.army
        tileArmyCost = tileRealArmyCost
        if tile.player in friendlyPlayers:
            tileRealArmyCost = 0 - tile.army
        elif tile.isNeutral:
            tileArmyCost = tileRealArmyCost
            tileProbPlayer = territoryMap[tile.x][tile.y]
            if tileProbPlayer == -1:
                for m in tile.adjacents:
                    if not m.isNeutral:
                        tileProbPlayer = m.player

            if not tile.discovered and tileProbPlayer != -1:
                tileArmyCost += assumeTerritoryTileValue

        nextWorstCaseArmy = worstCaseArmy - tileRealArmyCost + 1
        nextArmy = curArmy - tileArmyCost + 1

        if curArmy > 0 and nextArmy <= 0 and pathWorstCaseTurns == 0:
            pathWorstCaseTurns = turn

        curArmy = nextArmy
        worstCaseArmy = nextWorstCaseArmy
        turn += 1

    if worstCaseArmy > 2:
        cappable = []
        for movable in path.tail.tile.movable:
            if movable.isObstacle or movable.army > worstCaseArmy - 2 or movable in negativeTiles:
                continue
            if movable.player not in friendlyPlayers:
                cappable.append(movable)
        if len(cappable) > 0:
            if DebugHelper.IS_DEBUGGING:
                logging.info(f'  WORST CASE END ARMY {worstCaseArmy} (realArmy {curArmy}) CAN CAP MORE TILES, RETURNING FALSE ({str(path)})')
            return False

    if pathWorstCaseTurns != path.length and DebugHelper.IS_DEBUGGING:
        logging.info(f'  WORST CASE TURNS {pathWorstCaseTurns} < path len {path.length} ({str(path)})')

    return True


def _group_expand_paths_by_crossovers(
    pathsCrossingTiles: typing.Dict[Tile, typing.List[Path]],
    multiPathDict: typing.Dict[Tile, typing.Dict[int, typing.Tuple[int, Path]]],
) -> typing.Dict[int, typing.List[Path]]:
    pathGroupLookup = {}
    #
    # allPaths = []
    # combinedTurnLengths = 0
    # for tile in multiPathDict.keys():
    #     for val, p in multiPathDict[tile].values():
    #         allPaths.append((val, p))
    #         combinedTurnLengths += p.length
    # logging.info(
    #     f'EXP MULT KNAP {len(multiPathDict)} grps, {len(allPaths)} paths, {remainingTurns} turns, combinedPathLengths {combinedTurnLengths}:')
    # for val, p in allPaths:
    #     logging.info(f'    INPUT {val:.2f} len {p.length}: {str(p)}')
    #
    allPaths = []
    # initially group by starting tile
    i = 0
    for pathList in pathsCrossingTiles.values():
        for path in pathList:
            pathGroupLookup[path] = i
        allPaths.extend(pathList)
        i += 1

    for path in allPaths:
        groupNumber = pathGroupLookup[path]
        _merge_path_groups_recurse(groupNumber, path, pathGroupLookup, pathsCrossingTiles)

    pathsGrouped: typing.Dict[int, typing.Set[Path]] = {}
    for path in allPaths:
        groupNumber = pathGroupLookup[path]
        groupList = pathsGrouped.get(groupNumber, set())
        groupList.add(path)
        if len(groupList) == 1:
            pathsGrouped[groupNumber] = groupList

    final = {}
    for g, pathSet in pathsGrouped.items():
        final[g] = list(pathSet)

    return final


def _merge_path_groups_recurse(
        groupNumber: int,
        path: Path,
        pathGroupLookup: typing.Dict[Path, int],
        pathsCrossingTiles: typing.Dict[Tile, typing.List[Path]]):
    for tile in path.tileList:
        for crossedPath in pathsCrossingTiles[tile]:
            if crossedPath == path:
                continue

            crossedPathGroup = pathGroupLookup[crossedPath]
            if groupNumber != crossedPathGroup:
                if DebugHelper.IS_DEBUGGING:
                    logging.info(f'path {groupNumber} {str(path)}\r\n  crosses path {crossedPathGroup} {str(crossedPath)}, converting')
                pathGroupLookup[crossedPath] = groupNumber
                _merge_path_groups_recurse(groupNumber, crossedPath, pathGroupLookup, pathsCrossingTiles)


def _get_tile_path_value(
        map: MapBase,
        tile,
        lastTile,
        negativeTiles,
        targetPlayers,
        searchingPlayer,
        enemyDistMap,
        generalDistMap,
        territoryMap,
        enemyDistPenaltyPoint,
        bonusCapturePointMatrix: MapMatrix[float] | None):
    value = 0.0
    if tile in negativeTiles:
        value -= 0.1
        # or do nothing?
    else:

        if tile.player in targetPlayers:
            value += 2.1
        elif not tile.discovered and territoryMap[tile.x][tile.y] in targetPlayers:
            value += 1.45
        elif not tile.visible and territoryMap[tile.x][tile.y] in targetPlayers:
            value += 1.2
        elif tile.player == -1:
            value += 1.0
        elif map.is_player_on_team_with(searchingPlayer, tile.player):
            value -= 0.5 / (1 + tile.army)

        # if tile.visible:
        #     value += 0.02
        # el
        if not tile.discovered:
            value += 0.01
        if bonusCapturePointMatrix is not None:
            value += bonusCapturePointMatrix[tile]

        # elif lastTile is not None and tile.player == searchingPlayer:
        #     value -= 0.05

        sourceEnDist = enemyDistMap[lastTile.x][lastTile.y]
        destEnDist = enemyDistMap[tile.x][tile.y]
        sourceGenDist = generalDistMap[lastTile.x][lastTile.y]
        destGenDist = generalDistMap[tile.x][tile.y]

        sourceDistSum = sourceEnDist + sourceGenDist
        destDistSum = destEnDist + destGenDist

        if destDistSum >= enemyDistPenaltyPoint:
            if destDistSum < sourceDistSum:
                # logging.info(f"move {str(last)}->{str(tile)} was TOWARDS shortest path")
                value += 0.01

        if destDistSum == sourceDistSum:
            # logging.info(f"move {str(last)}->{str(tile)} was flanking parallel to shortest path")
            value += 0.01

        if abs(destEnDist - destGenDist) <= abs(sourceEnDist - sourceGenDist):
            valueAdd = abs(destEnDist - destGenDist) / 200
            # logging.info(
            #     f"move {last.toString()}->{tile.toString()} was moving towards the center, valuing it {valueAdd} higher")
            value += valueAdd
    return value


def add_path_to_try_avoid_paths_crossing_tiles(
        path: Path,
        negativeTiles: typing.Set[Tile],
        tryAvoidSet: typing.Set[Tile],
        pathsCrossingTiles: typing.Dict[Tile, typing.List[Path]],
        addToNegativeTiles = False,
):
    for t in path.tileList:
        tryAvoidSet.add(t)
        if addToNegativeTiles:
            negativeTiles.add(t)
        tileCrossList = pathsCrossingTiles.get(t, [])
        tileCrossList.append(path)
        if len(tileCrossList) == 1:
            pathsCrossingTiles[t] = tileCrossList


def move_can_cap_more(leafMove: Move) -> bool:
    """Returns whether a leafmove could continue capping tiles, or is a final cap."""
    capAmt = leafMove.source.army - leafMove.dest.army - 1
    canCapMoreOnPathWithNoSplit = False
    for nextCap in leafMove.dest.movable:
        if nextCap == leafMove.source:
            continue
        if nextCap.player != leafMove.source.player and capAmt - 1 > nextCap.army:
            canCapMoreOnPathWithNoSplit = True
            break

    return canCapMoreOnPathWithNoSplit


def knapsack_multi_paths(
        map: MapBase,
        searchingPlayer: int,
        friendlyPlayers,
        targetPlayers,
        remainingTurns: int,
        pathsCrossingTiles,
        multiPathDict,
        territoryMap: typing.List[typing.List[int]],
        postPathEvalFunction: typing.Callable[[Path, typing.Set[Tile]], float],
        negativeTiles: typing.Set[Tile],
        tryAvoidSet: typing.Set[Tile],
        viewInfo: ViewInfo | None,
) -> typing.Tuple[Path | None, typing.List[Path], int, float]:
    """
    Returns firstPath, allPaths, totalTurns, totalValue

    @param map:
    @param searchingPlayer:
    @param remainingTurns:
    @param pathsCrossingTiles:
    @param multiPathDict:
    @param territoryMap:
    @param postPathEvalFunction:
    @param negativeTiles:
    @param tryAvoidSet:
    @param viewInfo:
    @return:
    """
    tilePathGroupsRebuilt: typing.Dict[int, typing.List[Path]] = _group_expand_paths_by_crossovers(
        pathsCrossingTiles,
        multiPathDict)

    allPaths = []
    combinedTurnLengths = 0
    groupsWithPaths = 0
    for grp, paths in tilePathGroupsRebuilt.items():
        if len(paths) > 0:
            groupsWithPaths += 1

    for tile in multiPathDict.keys():
        pathValues = multiPathDict[tile].values()
        for val, p in pathValues:
            allPaths.append((val, p))
            combinedTurnLengths += p.length
    logging.info(
        f'EXP MULT KNAP {groupsWithPaths} grps, {len(allPaths)} paths, {remainingTurns} turns, combinedPathLengths {combinedTurnLengths}:')
    if DebugHelper.IS_DEBUGGING:
        for val, p in allPaths:
            logging.info(f'    INPUT {val:.2f} len {p.length}: {str(p)}')

    def multiple_choice_knapsack_expansion_path_value_converter(p: Path) -> int:
        floatVal = postPathEvalFunction(p, negativeTiles)
        intVal = int(floatVal * 10000.0)
        return intVal

    totalValue, maxPaths = expansion_knapsack_gather_iteration(
        remainingTurns,
        tilePathGroupsRebuilt,
        shouldLog=DebugHelper.IS_DEBUGGING,
        valueFunc=multiple_choice_knapsack_expansion_path_value_converter
    )

    path = find_best_expansion_path_to_move_first_by_city_weights(
        map,
        maxPaths,
        tryAvoidSet,
        negativeTiles,
        postPathEvalFunction,
        remainingTurns,
        searchingPlayer,
        friendlyPlayers,
        territoryMap)

    otherPaths = [p for p in maxPaths if p != path]

    turnsUsed, enemyCapped, neutralCapped = _get_capture_counts(
        searchingPlayer,
        friendlyPlayers,
        targetPlayers,
        path,
        otherPaths,
        negativeTiles)

    # viewInfo.add_info_line(
    logging.info(
        f'MEXPC en{enemyCapped} neut{neutralCapped} {turnsUsed}/{remainingTurns} {totalValue}v num paths {len(maxPaths)}')

    otherPaths = [p for p in sorted(otherPaths, key=lambda pa: postPathEvalFunction(pa, negativeTiles) / pa.length, reverse=True)]

    return path, otherPaths, turnsUsed, 2 * enemyCapped + neutralCapped


def knapsack_multi_paths_no_crossover(
        map: MapBase,
        searchingPlayer: int,
        friendlyPlayers: typing.List[int],
        targetPlayers: typing.List[int],
        remainingTurns: int,
        pathsCrossingTiles,
        multiPathDict: typing.Dict[Tile, typing.Dict[int, typing.Tuple[int, Path]]],
        territoryMap: typing.List[typing.List[int]],
        postPathEvalFunction: typing.Callable[[Path, typing.Set[Tile]], float],
        negativeTiles: typing.Set[Tile],
        tryAvoidSet: typing.Set[Tile],
        viewInfo: ViewInfo | None,
) -> typing.Tuple[Path | None, typing.List[Path], int, float]:
    """
    Returns firstPath, allPaths, totalTurns, totalValue

    @param map:
    @param searchingPlayer:
    @param remainingTurns:
    @param pathsCrossingTiles:
    @param multiPathDict:
    @param territoryMap:
    @param postPathEvalFunction:
    @param negativeTiles:
    @param tryAvoidSet:
    @param viewInfo:
    @return:
    """

    allPaths = []
    groupsWithPaths = 0
    groups = {}

    # group cityPaths by first tile captured, instead
    cityPaths = {}

    for tile, pathsByDist in multiPathDict.items():
        if len(pathsByDist) == 0:
            continue

        groupsWithPaths += 1
        groupPaths = []

        for dist, pathTuple in pathsByDist.items():
            val, p = pathTuple

            if (tile.isCity or tile.isGeneral) and p.length < 5:
                groupTile = tile
                for t in p.tileList:
                    if not map.is_player_on_team_with(tile.player, t.player):
                        groupTile = t
                        break

                existingGroup = groups.get(groupTile, [])
                existingGroup.append(p)

                groups[groupTile] = existingGroup

                continue

            groupPaths.append(p)

        groups[tile] = groupPaths

    combinedTurnLengths = 0
    for tile in multiPathDict.keys():
        pathValues = multiPathDict[tile].values()
        for val, p in pathValues:
            allPaths.append((val, p))
            combinedTurnLengths += p.length
    logging.info(
        f'EXP MULT KNAP {groupsWithPaths} grps, {len(allPaths)} paths, {remainingTurns} turns, combinedPathLengths {combinedTurnLengths}:')
    if DebugHelper.IS_DEBUGGING:
        for val, p in allPaths:
            logging.info(f'    INPUT {val:.2f} len {p.length}: {str(p)}')

    def multiple_choice_knapsack_expansion_path_value_converter(p: Path) -> int:
        floatVal = postPathEvalFunction(p, negativeTiles)
        intVal = int(floatVal * 10000.0)
        return intVal

    totalValue, maxPaths = expansion_knapsack_gather_iteration(
        remainingTurns,
        groups,
        shouldLog=DebugHelper.IS_DEBUGGING,
        valueFunc=multiple_choice_knapsack_expansion_path_value_converter
    )

    path = find_best_expansion_path_to_move_first_by_city_weights(
        map,
        maxPaths,
        tryAvoidSet,
        negativeTiles,
        postPathEvalFunction,
        remainingTurns,
        searchingPlayer,
        friendlyPlayers,
        territoryMap)

    otherPaths = [p for p in maxPaths if p != path]

    turnsUsed, enemyCapped, neutralCapped = _get_capture_counts(
        searchingPlayer,
        friendlyPlayers,
        targetPlayers,
        path,
        otherPaths,
        negativeTiles)

    # viewInfo.add_info_line(
    logging.info(
        f'MEXPN en{enemyCapped} neut{neutralCapped} {turnsUsed}/{remainingTurns} {totalValue}v num paths {len(maxPaths)}')

    otherPaths = [p for p in sorted(otherPaths, key=lambda pa: postPathEvalFunction(pa, negativeTiles) / pa.length, reverse=True)]

    return path, otherPaths, turnsUsed, 2 * enemyCapped + neutralCapped


def _add_expansion_to_view_info(path: Path, otherPaths: typing.List[Path], viewInfo: ViewInfo, colors: typing.Tuple[int, int, int]):
    r, g, b = colors
    for curPath in otherPaths:
        if viewInfo:
            # draw other paths darker
            alpha = 190
            minAlpha = 100
            alphaDec = 5
            viewInfo.paths.appendleft(PathColorer(curPath, max(0, r-40), max(0, g-40), max(0, b-40), alpha, alphaDec, minAlpha))

    # draw maximal path brighter
    alpha = 255
    minAlpha = 200
    alphaDec = 0
    if viewInfo:
        # viewInfo.paths = deque(where(viewInfo.paths, lambda pathCol: pathCol.path != path))
        viewInfo.paths.appendleft(PathColorer(path, r, g, b, alpha, alphaDec, minAlpha))


def get_optimal_expansion(
        map: MapBase,
        searchingPlayer: int,
        targetPlayer: int,
        turns: int,
        boardAnalysis: BoardAnalyzer,
        territoryMap: typing.List[typing.List[int]],
        negativeTiles: typing.Set[Tile] = None,
        leafMoves: typing.Union[None, typing.List[Move]] = None,
        viewInfo: ViewInfo = None,
        valueFunc=None,
        priorityFunc=None,
        initFunc=None,
        skipFunc=None,
        boundFunc=None,
        allowLeafMoves=True,
        useLeafMovesFirst: bool = False,
        calculateTrimmable=True,
        singleIterationPathTimeCap=0.03,
        forceNoGlobalVisited: bool = True,
        forceGlobalVisitedStage1: bool = False,
        useIterativeNegTiles: bool = False,
        allowGatherPlanExtension=False,
        alwaysIncludeNonTerminatingLeavesInIteration=False,
        smallTileExpansionTimeRatio: float = 1.0,
        lengthWeightOffset: float = -0.3,
        time_limit=0.2,
        useCutoff: bool = True,
        bonusCapturePointMatrix: MapMatrix[float] | None = None,
        colors: typing.Tuple[int, int, int] = (235, 240, 50),
        perfTimer: PerformanceTimer | None = None,
) -> typing.Tuple[Path | None, typing.List[Path]]:
    """
    Does 3 phases of knapsacking expansion paths:
    First, large tile plans.
    Second, small tile expansion plans.
    Third, adds all unused leafmove tiles into the path list and knapsacks.
    """

    logEntries = []
    try:

        start = time.perf_counter()

        teams = MapBase.get_teams_array(map)
        targetPlayers = [p for p, t in enumerate(teams) if teams[targetPlayer] == t]
        friendlyPlayers = [p for p, t in enumerate(teams) if teams[searchingPlayer] == t]

        enemyDistMap = boardAnalysis.intergeneral_analysis.bMap
        generalDistMap = boardAnalysis.intergeneral_analysis.aMap

        respectTerritoryMap = map.players[targetPlayer].tileCount // 2 > len(map.players[targetPlayer].tiles)

        ## The more turns remaining, the more we prioritize longer paths. Towards the end of expansion, we prioritize sheer captured tiles.
        ## This hopefully leads to finding more ideal expansion plans earlier on while being greedier later
        # lengthWeightOffset = 0.3 * ((turns ** 0.5) - 3)
        # lengthWeightOffset = max(0.25, lengthWeightOffset)

        logEntries.append(f"\n\nAttempting Optimal Expansion (tm) for turns {turns} (lengthWeightOffset {lengthWeightOffset}), negatives {str([str(t) for t in negativeTiles])}:\n")
        startTime = time.perf_counter()
        generalPlayer = map.players[searchingPlayer]
        if negativeTiles is None:
            negativeTiles = set()

        originalNegativeTiles = negativeTiles
        negativeTiles = negativeTiles.copy()

        cityUsages = {}

        # TODO be better about this
        expectedUnseenEnemyTileArmy = 1
        if turns > 25:
            expectedUnseenEnemyTileArmy = 2
        if map.turn > 300:
            expectedUnseenEnemyTileArmy += 1

        enemyDistPenaltyPoint = boardAnalysis.inter_general_distance // 3
        if turns < 12:
            enemyDistPenaltyPoint -= 1
        if turns < 8:
            enemyDistPenaltyPoint = boardAnalysis.inter_general_distance // 4
        if turns < 5:
            enemyDistPenaltyPoint = boardAnalysis.inter_general_distance // 6
        if turns < 3:
            enemyDistPenaltyPoint = 0

        # for tile in skipTiles:
        #     logEntries.append(f"expansion starting negativeTile: {tile.toString()}")

        # wastedMoveCap = 4
        wastedMoveCap = min(7, max(3, turns // 4)) + 1

        iter = [0]

        # skipFunc(next, nextVal). Not sure why this is 0 instead of 1, but 1 breaks it. I guess the 1 is already subtracted
        if not skipFunc:
            def skip_after_out_of_army(nextTile, nextVal):
                (
                    distSoFar,
                    prioWeighted,
                    fakeDistSoFar,
                    wastedMoves,
                    tileCapturePoints,
                    negArmyRemaining,
                    enemyTiles,
                    neutralTiles,
                    pathPriority,
                    tileSetSoFar,
                    # adjacentSetSoFar,
                    # enemyExpansionValue,
                    # enemyExpansionTileSet
                ) = nextVal
                # skip if out of army, or if we've wasted a bunch of moves already and have nothing to show
                if negArmyRemaining >= 0 or (wastedMoves > wastedMoveCap and tileCapturePoints > -5):
                    return True

                if nextTile.isCity and nextTile.isNeutral:
                    return True

                return False

            skipFunc = skip_after_out_of_army

        if not valueFunc:
            def value_priority_army_dist_basic(currentTile, priorityObject):
                (
                    distSoFar,
                    prioWeighted,
                    fakeDistSoFar,
                    wastedMoves,
                    tileCapturePoints,
                    negArmyRemaining,
                    enemyTiles,
                    neutralTiles,
                    pathPriority,
                    tileSetSoFar,
                    # adjacentSetSoFar,
                    # enemyExpansionValue,
                    # enemyExpansionTileSet
                ) = priorityObject
                # negative these back to positive
                value = -1000
                dist = 1
                if currentTile in negativeTiles or negArmyRemaining >= 0 or distSoFar == 0:
                    return None
                if map.is_tile_friendly(currentTile):
                    return None

                if currentTile.isCity and currentTile.isNeutral:
                    return None

                if viewInfo:
                    viewInfo.evaluatedGrid[currentTile.x][currentTile.y] += 1

                if distSoFar > 0 and tileCapturePoints < 0:
                    dist = distSoFar + lengthWeightOffset
                    # negative points for wasted moves until the end of expansion
                    value = 0 - tileCapturePoints  # - 2 * wastedMoves * lengthWeightOffset

                if value <= 0:
                    return None

                valuePerTurn = value / dist
                # if valuePerTurn < valPerTurnCutoff:
                #     return None

                # return ((value / (dist + wastedMoves)) - wastedMoves,
                # return ((value / (dist + wastedMoves)) - wastedMoves / 10,
                # return ((value / (dist + wastedMoves)),  # ACTUAL ORIG
                return (value,
                        valuePerTurn,
                        # prioWeighted,
                        # value,
                        0 - negArmyRemaining,
                        # 0 - enemyTiles / dist,
                        # 0,
                        0 - distSoFar)

            valueFunc = value_priority_army_dist_basic

        # def a_starey_value_priority_army_dist(currentTile, priorityObject):
        #    pathPriorityDivided, wastedMoves, armyRemaining, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, adjacentSetSoFar = priorityObject
        #    # negative these back to positive
        #    posPathPrio = 0-pathPriorityDivided
        #    #return (posPathPrio, 0-armyRemaining, distSoFar)
        #    return (0-(enemyTiles*2 + neutralTiles) / (max(1, distSoFar)), 0-enemyTiles / (max(1, distSoFar)), posPathPrio, distSoFar)

        ENEMY_EXPANSION_TILE_PENALTY = 0.7

        if not priorityFunc:
            def default_priority_func_basic(nextTile, currentPriorityObject):
                (
                    distSoFar,
                    prioWeighted,
                    fakeDistSoFar,
                    wastedMoves,
                    negTileCapturePoints,
                    negArmyRemaining,
                    enemyTiles,
                    neutralTiles,
                    pathPriority,
                    tileSetSoFar,
                    # adjacentSetSoFar,
                    # enemyExpansionValue,
                    # enemyExpansionTileSet
                ) = currentPriorityObject
                nextTerritory = territoryMap[nextTile.x][nextTile.y]
                armyRemaining = 0 - negArmyRemaining
                distSoFar += 1
                fakeDistSoFar += 1
                if nextTile.player == -1 and nextTerritory not in targetPlayers:
                    fakeDistSoFar += 1
                # weight tiles closer to the target player higher

                armyRemaining -= 1

                if nextTile in tileSetSoFar:
                    return None

                nextTileSet = tileSetSoFar.copy()
                nextTileSet.add(nextTile)

                # only reward closeness to enemy up to a point then penalize it
                cutoffEnemyDist = abs(enemyDistMap[nextTile.x][nextTile.y] - enemyDistPenaltyPoint)
                addedPriority = 3 * (0 - cutoffEnemyDist ** 0.5 + 1)

                # reward away from our general but not THAT far away
                cutoffGenDist = abs(generalDistMap[nextTile.x][nextTile.y])
                addedPriority += 3 * (cutoffGenDist ** 0.5 - 1)

                # negTileCapturePoints += cutoffEnemyDist / 100
                # negTileCapturePoints -= cutoffGenDist / 100

                # releventAdjacents = where(nextTile.adjacents, lambda adjTile: adjTile not in adjacentSetSoFar and adjTile not in tileSetSoFar)
                if negativeTiles is None or (nextTile not in negativeTiles):
                    if nextTile.player in friendlyPlayers:
                        armyRemaining += nextTile.army
                    elif nextTile.player not in map.teammates:
                        armyRemaining -= nextTile.army
                if armyRemaining <= 0:
                    return None
                # Tiles penalized that are further than 7 tiles from enemy general
                # tileModifierPreScale = max(8, enemyDistMap[nextTile.x][nextTile.y]) - 8
                # tileModScaled = tileModifierPreScale / 200
                # negTileCapturePoints += tileModScaled
                usefulMove = nextTile not in negativeTiles
                # enemytiles or enemyterritory undiscovered tiles
                isProbablyEnemyTile = (nextTile.isNeutral
                                       and not nextTile.visible
                                       and nextTerritory in targetPlayers)
                if isProbablyEnemyTile:
                    armyRemaining -= expectedUnseenEnemyTileArmy

                if (
                        nextTile in tryAvoidSet
                        or nextTile in negativeTiles
                        or nextTile in tileSetSoFar
                ):
                    # our tiles and non-target enemy tiles get negatively weighted
                    addedPriority -= 1
                    # 0.7
                    usefulMove = False
                    wastedMoves += 0.5
                elif (
                        targetPlayer != -1
                        and (
                                nextTile.player in targetPlayers
                                or (not nextTile.visible and respectTerritoryMap and territoryMap[nextTile.x][nextTile.y] in targetPlayers)
                        )
                ):
                    # if nextTile.player == -1:
                    #     # these are usually 1 or more army since usually after army bonus
                    #     armyRemaining -= 1
                    addedPriority += 8
                    if nextTile.player != -1:
                        negTileCapturePoints -= 2.0
                    else:
                        negTileCapturePoints -= 1.5
                    enemyTiles -= 1

                    ## points for locking all nearby enemy tiles down
                    # numEnemyNear = count(nextTile.adjacents, lambda adjTile: adjTile.player in targetPlayers)
                    # numEnemyLocked = count(releventAdjacents, lambda adjTile: adjTile.player in targetPlayers)
                    ##    for every other nearby enemy tile on the path that we've already included in the path, add some priority
                    # addedPriority += (numEnemyNear - numEnemyLocked) * 12
                elif nextTile.player == -1:
                    # if nextTile.isCity: #TODO and is reasonably placed?
                    #    neutralTiles -= 12
                    # we'd prefer to be killing enemy tiles, yeah?
                    # wastedMoves += 0.2
                    neutralTiles -= 1
                    negTileCapturePoints -= 1
                    # points for capping tiles in general
                    addedPriority += 2
                    # points for taking neutrals next to enemy tiles
                    # numEnemyNear = count(nextTile.movable, lambda adjTile: adjTile not in adjacentSetSoFar and adjTile.player in targetPlayers)
                    # if numEnemyNear > 0:
                    #    addedPriority += 2
                else:  # our tiles and non-target enemy tiles get negatively weighted
                    addedPriority -= 1
                    # 0.7
                    usefulMove = False
                    wastedMoves += 0.5

                if nextTile in tryAvoidSet:
                    addedPriority -= 5
                    negTileCapturePoints += 0.2

                if bonusCapturePointMatrix is not None:
                    bonusPoints = bonusCapturePointMatrix[nextTile]
                    if bonusPoints < 0.0 or usefulMove:  # for penalized tiles, always apply the penalty. For rewarded tiles, only reward when it is a move that does something.
                        negTileCapturePoints -= bonusPoints

                iter[0] += 1
                nextAdjacentSet = None
                # nextAdjacentSet = adjacentSetSoFar.copy()
                # for adj in nextTile.adjacents:
                #    nextAdjacentSet.add(adj)
                # nextEnemyExpansionSet = enemyExpansionTileSet.copy()
                nextEnemyExpansionSet = None
                # deprioritize paths that allow counterplay
                # for adj in nextTile.movable:
                #    if adj.army >= 3 and adj.player != searchingPlayer and adj.player != -1 and adj not in skipTiles and adj not in tileSetSoFar and adj not in nextEnemyExpansionSet:
                #        nextEnemyExpansionSet.add(adj)
                #        enemyExpansionValue += (adj.army - 1) // 2
                #        tileCapturePoints += ENEMY_EXPANSION_TILE_PENALTY
                newPathPriority = pathPriority - addedPriority
                # newPathPriority = addedPriority
                # prioPerTurn = newPathPriority/distSoFar
                prioPerTurn = (negTileCapturePoints) / (distSoFar + wastedMoves)  # - addedPriority / 4
                # if iter[0] < 50 and fullLog:
                #     logEntries.append(
                #         f" - nextTile {str(nextTile)}, waste [{wastedMoves:.2f}], prioPerTurn [{prioPerTurn:.2f}], dsf {distSoFar}, capPts [{negTileCapturePoints:.2f}], negArmRem [{0 - armyRemaining}]\n    eTiles {enemyTiles}, nTiles {neutralTiles}, npPrio {newPathPriority:.2f}, nextTileSet {len(nextTileSet)}\n    nextAdjSet {None}, enemyExpVal {enemyExpansionValue}, nextEnExpSet {None}")

                return distSoFar, prioPerTurn, fakeDistSoFar, wastedMoves, negTileCapturePoints, 0 - armyRemaining, enemyTiles, neutralTiles, newPathPriority, nextTileSet  # , nextAdjacentSet, enemyExpansionValue, nextEnemyExpansionSet

            priorityFunc = default_priority_func_basic
        #
        # if not boundFunc:
        #     def default_bound_func(currentTile, currentPriorityObject, maxPriorityObject):
        #         if maxPriorityObject is None:
        #             return False
        #         distSoFar, prioWeighted, fakeDistSoFar, wastedMoves, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = currentPriorityObject
        #         distSoFarMax, prioWeightedMax, fakeDistSoFarMax, wastedMovesMax, tileCapturePointsMax, negArmyRemainingMax, enemyTilesMax, neutralTilesMax, pathPriorityMax, tileSetSoFarMax, adjacentSetSoFarMax, enemyExpansionValueMax, enemyExpansionTileSetMax = maxPriorityObject
        #         if distSoFarMax <= 3 or distSoFar <= 3:
        #             return False
        #         # if wastedMoves > wastedMovesMax * 1.3 + 0.5:
        #         #     # logEntries.append(
        #         #     #     f"Pruned {currentTile} via wastedMoves {wastedMoves:.2f}  >  wastedMovesMax {wastedMovesMax:.2f} * 1.2 + 0.4 {wastedMovesMax * 1.2 + 0.4:.3f}")
        #         #     return True
        #         thisCapPoints = tileCapturePoints / distSoFar
        #         maxCapPoints = tileCapturePointsMax / distSoFarMax
        #         weightedMax = 0.7 * maxCapPoints + 0.01
        #         if enemyTilesMax + neutralTilesMax > 0 and thisCapPoints > weightedMax:
        #             logEntries.append(
        #                 f"Pruned {currentTile} via tileCap thisCapPoints {thisCapPoints:.3f}  >  weightedMax {weightedMax:.3f} (maxCapPoints {maxCapPoints:.3f})")
        #             return True
        #
        #         return False
        #
        #     boundFunc = default_bound_func

        if not initFunc:
            def initial_value_func_default(tile):
                startingSet = set()
                startingSet.add(tile)
                startingAdjSet = set()
                for adj in tile.adjacents:
                    startingAdjSet.add(adj)
                startingEnemyExpansionTiles = set()
                enemyExpansionValue = 0
                tileCapturePoints = 0

                tileArmy = tile.army

                cityUsage = cityUsages.get(tile, None)
                if cityUsage is not None:
                    tileArmy = 5

                for adj in tile.movable:
                    if adj.army > 3 and not map.is_tile_friendly(adj) and adj.player != -1 and adj not in negativeTiles:
                        startingEnemyExpansionTiles.add(adj)
                        enemyExpansionValue += (adj.army - 1) // 2
                        tileCapturePoints += ENEMY_EXPANSION_TILE_PENALTY
                return 0, -10000, 0, 0, tileCapturePoints, 0 - tileArmy, 0, 0, 0, startingSet  # , startingAdjSet, enemyExpansionValue, startingEnemyExpansionTiles

            initFunc = initial_value_func_default

        # Switch this up to use more tiles at the start, just removing the first tile in each path at a time. Maybe this will let us find more 'maximal' paths?
        def postPathEvalFunction(path, negativeTiles):
            value = 0
            last = path.start.tile
            # if bonusCapturePointMatrix:
            #     value += bonusCapturePointMatrix[path.start.tile]
            nextNode = path.start.next
            while nextNode is not None:
                tile = nextNode.tile
                val = _get_tile_path_value(map, tile, last, negativeTiles, targetPlayers, searchingPlayer, enemyDistMap, generalDistMap, territoryMap, enemyDistPenaltyPoint, bonusCapturePointMatrix)
                value += val

                last = tile
                nextNode = nextNode.next
            return value

        if turns <= 0:
            raise AssertionError(f"turns {turns} <= 0 in optimal_expansion...")

        # if turns > 30:
        #     logEntries.append(f"turns {turns} < 30 in optimal_expansion... Setting to 30")
        #     turns = 30

        tileMinValueCutoff = 2
        remainingTurns = turns
        sortedTiles = sorted(list(where(generalPlayer.tiles, lambda tile: tile.army > tileMinValueCutoff and tile not in negativeTiles)),
                             key=lambda tile: (0 - tile.army, enemyDistMap[tile.x][tile.y]))
        if len(sortedTiles) <= 4:
            tileMinValueCutoff = 1
            sortedTiles = sorted(list(where(generalPlayer.tiles, lambda tile: tile.army > tileMinValueCutoff and tile not in negativeTiles)),
                                 key=lambda tile: (0 - tile.army, enemyDistMap[tile.x][tile.y]))

        if len(sortedTiles) == 0:
            return None, []

        paths = []
        # fullCutoff
        fullCutoff = 20
        cutoffFactor = 5
        valPerTurnCutoff = 0.5
        valPerTurnCutoffScaledown = 0.8
        if not useCutoff:
            cutoffFactor = 20
            valPerTurnCutoff = 0.25
            valPerTurnCutoffScaledown = 0.5

        # if len(sortedTiles) < 5:
        #    logEntries.append("Only had {} tiles to play with, switching cutoffFactor to full...".format(len(sortedTiles)))
        #    cutoffFactor = fullCutoff
        player = map.players[searchingPlayer]
        logStuff = True
        if player.tileCount > 70 or turns > 25:
            logEntries.append("Not doing algorithm logging for expansion due to player tilecount > 70 or turn count > 25")
            logStuff = False

        pathsCrossingTiles: typing.Dict[Tile, typing.List[Path]] = {}

        tryAvoidSet: typing.Set[Tile] = negativeTiles.copy()

        defaultNoPathValue = (0, None)

        multiPathDict: typing.Dict[Tile, typing.Dict[int, typing.Tuple[int, Path]]] = {}
        """Contains the current max value path per distance per start tile"""

        alwaysIncludes = []
        includeForGath: typing.List[Move] = []

        # expansionGather = greedy_backpack_gather(map, tilesLargerThanAverage, turns, None, valueFunc, baseCaseFunc, skipTiles, None, searchingPlayer, priorityFunc, skipFunc = None)
        if allowLeafMoves and leafMoves is not None and useLeafMovesFirst:
            logEntries.append(f"Allowing leafMoves FIRST as part of optimal expansion.... elapsed {time.perf_counter() - startTime:.4f}")
            _include_leaf_moves_in_exp_plan(
                allowGatherPlanExtension=allowGatherPlanExtension,
                alwaysIncludes=alwaysIncludes,
                defaultNoPathValue=defaultNoPathValue,
                includeForGath=includeForGath,
                leafMoves=leafMoves,
                map=map,
                multiPathDict=multiPathDict,
                negativeTiles=negativeTiles,
                paths=paths,
                pathsCrossingTiles=pathsCrossingTiles,
                postPathEvalFunction=postPathEvalFunction,
                searchingPlayer=searchingPlayer,
                targetPlayers=targetPlayers,
                tryAvoidSet=tryAvoidSet,
                useIterativeNegTiles=useIterativeNegTiles,
                skipNeutrals=True)

        if allowGatherPlanExtension:
            logEntries.append(f"Beginning gather extension.... elapsed {time.perf_counter() - startTime:.4f}")
            addlPaths = _execute_expansion_gather_to_borders(
                map,
                [t.dest for t in includeForGath if t.source not in negativeTiles and t.dest not in negativeTiles],
                2,
                preferNeutral=True,
                negativeTiles=negativeTiles,
                searchingPlayer=searchingPlayer,
            )

            counts = {}
            for path in addlPaths:
                for tile in path.tileList:
                    count = counts.get(tile, 0)
                    counts[tile] = count + 1

            addlPaths = [p for p in sorted(addlPaths, key=lambda p: sum([counts[t] for t in p.tileList]))]

            for path in addlPaths:
                if SearchUtils.any_where(path.tileList, lambda t: t in negativeTiles):
                    continue

                _try_include_alt_sourced_path(
                    map,
                    searchingPlayer,
                    defaultNoPathValue,
                    multiPathDict,
                    negativeTiles,
                    path,
                    paths,
                    pathsCrossingTiles,
                    postPathEvalFunction,
                    tryAvoidSet,
                    useIterativeNegTiles)
            logEntries.append(f"Completed gather extension.... elapsed {time.perf_counter() - startTime:.4f}")

        if allowLeafMoves and leafMoves is not None and useLeafMovesFirst:
            logEntries.append(f"Second pass initial leaf-moves.... elapsed {time.perf_counter() - startTime:.4f}")
            _include_leaf_moves_in_exp_plan(
                allowGatherPlanExtension=allowGatherPlanExtension,
                alwaysIncludes=None,
                defaultNoPathValue=defaultNoPathValue,
                includeForGath=None,
                leafMoves=leafMoves,
                map=map,
                multiPathDict=multiPathDict,
                negativeTiles=negativeTiles,
                paths=paths,
                pathsCrossingTiles=pathsCrossingTiles,
                postPathEvalFunction=postPathEvalFunction,
                searchingPlayer=searchingPlayer,
                targetPlayers=targetPlayers,
                tryAvoidSet=tryAvoidSet,
                useIterativeNegTiles=useIterativeNegTiles,
                skipNeutrals=False)

        stage1 = time_limit / 4
        stage2 = time_limit / 2
        breakStage = 3 * time_limit / 4

        overrideGlobalVisitedOneCycle = False
        standingArmyGlobalVisitedOverrideThresh = map.players[searchingPlayer].standingArmy
        linearOffset = 15
        if standingArmyGlobalVisitedOverrideThresh > linearOffset:
            standingArmyGlobalVisitedOverrideThresh = linearOffset + (standingArmyGlobalVisitedOverrideThresh - linearOffset) ** 0.75

        if len(sortedTiles) > 0 and sortedTiles[0].army >= standingArmyGlobalVisitedOverrideThresh:
            logEntries.append(f'overriding global visited to False for the first cycle due to large tile {str(sortedTiles[0])}')
            overrideGlobalVisitedOneCycle = True

        inStage2 = False
        firstIteration = True
        iteration = 0

        while True:
            logEntries.append(f"Main cycle iter {iter} start - elapsed {time.perf_counter() - startTime:.4f}")
            if remainingTurns <= 0:
                logEntries.append("breaking due to remainingTurns <= 0")
                break
            if cutoffFactor > fullCutoff:
                logEntries.append("breaking due to cutoffFactor > fullCutoff")
                break
            if len(sortedTiles) == 0:
                logEntries.append("breaking due to no tiles left in sortedTiles")
                break
            timeUsed = time.perf_counter() - startTime
            logEntries.append(f'EXP iter {iter[0]} time used {timeUsed:.3f}')
            # Stages:
            # first 0.1s, use large tiles and shift smaller. (do nothing)
            # second 0.1s, use all tiles (to make sure our small tiles are included)
            # third 0.1s - knapsack optimal stuff outside this loop i guess?
            if timeUsed > stage1 and timeUsed < stage2:
                logEntries.append(f"timeUsed > {stage1} ({timeUsed})... Breaking loop and knapsacking...")
            if timeUsed > breakStage and inStage2:
                logEntries.append(f"timeUsed > {breakStage} ({timeUsed})... breaking and knapsacking...")
                break
            if timeUsed > stage2:
                logEntries.append(
                    f"timeUsed > {stage2} ({timeUsed})... Switching to using all tiles, cutoffFactor = fullCutoff...")
                inStage2 = True
                cutoffFactor = fullCutoff

            # startIdx = max(0, ((cutoffFactor - 1) * len(sortedTiles))//fullCutoff)
            startIdx = 0
            endIdx = min(len(sortedTiles), (cutoffFactor * len(sortedTiles)) // fullCutoff + 1)
            if endIdx < 3:
                oldEndIdx = endIdx
                endIdx = min(len(sortedTiles), 3)
                logEntries.append(f'forcing endIdx up from {oldEndIdx} to {endIdx}')
            logEntries.append(
                f"startIdx {startIdx} endIdx {endIdx}, where endIdx = min(len(sortedTiles) {len(sortedTiles)}, (cutoffFactor {cutoffFactor} * len(sortedTiles) {len(sortedTiles)}) // fullCutoff {fullCutoff} + 1)")
            tilePercentile = [t for t in sortedTiles if t not in negativeTiles][startIdx:endIdx]
            if len(tilePercentile) == 0:
                cutoffFactor += 3
                continue

            # filter out the bottom value of tiles (will filter out 1's in the early game, or the remaining 2's, etc)
            smallTiles = where(
                tilePercentile,
                lambda tile: tile.army < 15)

            if len(smallTiles) > len(tilePercentile) - 2:
                if firstIteration:
                    tilePercentile = where(tilePercentile, lambda t: t.army > tilePercentile[0].army // 2)
                else:
                    overrideGlobalVisitedOneCycle = True

            tilesLargerThanAverage = tilePercentile

            # if alwaysIncludeNonTerminatingLeavesInIteration and inStage2:
            if alwaysIncludeNonTerminatingLeavesInIteration and not firstIteration:
                for tile in alwaysIncludes:
                    if tile not in negativeTiles and tile not in tryAvoidSet:
                        tilesLargerThanAverage.append(tile)

            timeCap = singleIterationPathTimeCap
            if inStage2 and smallTileExpansionTimeRatio != 1.0:
                timeCap = singleIterationPathTimeCap * smallTileExpansionTimeRatio

            searchTime = min(time_limit - timeUsed, singleIterationPathTimeCap)

            logEntries.append(
                f'cutoffFactor {cutoffFactor}/{fullCutoff}, numTiles {len(tilesLargerThanAverage)}, largestTile {tilePercentile[0].toString()}: {tilePercentile[0].army} army, smallestTile {tilePercentile[-1].toString()}: {tilePercentile[-1].army} army')
            logEntries.append(f'about to run an optimal expansion for {timeCap:.4f}s max for remainingTurns {remainingTurns}, negatives {str([str(t) for t in negativeTiles])}')
            if DebugHelper.IS_DEBUGGING:
                logEntries.append('TILES INCLUDED FROM CURRENT PERCENTILE: ')
                logEntries.append('\n' + f'\n    '.join([str(t) for t in tilesLargerThanAverage]))

            # hack,  see what happens TODO
            # tilesLargerThanAverage = where(generalPlayer.tiles, lambda tile: tile.army > 1)
            # logEntries.append("Filtered for tilesLargerThanAverage with army > {}, found {} of them".format(tilePercentile[-1].army, len(tilesLargerThanAverage)))
            startDict = {}
            for i, tile in enumerate(tilesLargerThanAverage):
                # skip tiles we've already used or intentionally ignored
                if tile in negativeTiles:
                    continue
                # self.mark_tile(tile, 10)

                initVal = initFunc(tile)
                # pathPriorityDivided, wastedMoves, armyRemaining, pathPriority, distSoFar, tileSetSoFar
                # 10 because it puts the tile above any other first move tile, so it gets explored at least 1 deep...
                startDict[tile] = (initVal, 0)

            useGlobalVisited = not forceNoGlobalVisited
            if forceGlobalVisitedStage1 and not inStage2:
                useGlobalVisited = True
            # if remainingTurns < 6:
            #     useGlobalVisited = False
            if overrideGlobalVisitedOneCycle:
                useGlobalVisited = False
                overrideGlobalVisitedOneCycle = False
            startCopy = startDict.copy()
            for tile in negativeTiles:
                startCopy.pop(tile, None)

            newPathDict = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
                map,
                startCopy,
                valueFunc,
                searchTime,  # TODO not timeCap because we should find lots at once...?
                remainingTurns,
                maxDepth=min(remainingTurns, 15),
                # maxDepth=remainingTurns,
                noNeutralCities=True,
                negativeTiles=negativeTiles,
                searchingPlayer=searchingPlayer,
                priorityFunc=priorityFunc,
                useGlobalVisitedSet=useGlobalVisited,
                skipFunc=skipFunc,
                logResultValues=logStuff,
                fullOnly=False,
                # fullOnlyArmyDistFunc=fullOnly_func,
                # boundFunc=boundFunc,
                noLog=True)

            newPaths = []
            for tile in newPathDict.keys():
                curTileDict = multiPathDict.get(tile, {})
                for path in newPathDict[tile]:

                    value = postPathEvalFunction(path, negativeTiles)
                    if value >= 0.1 and value / path.length >= valPerTurnCutoff:
                        anyHighValue = True
                        visited = set()
                        friendlyCityCount = 0
                        node = path.start
                        while node is not None:
                            if node.tile not in negativeTiles and node.tile not in visited:
                                visited.add(node.tile)

                                if node.tile.player in friendlyPlayers and (
                                        node.tile.isCity or node.tile.isGeneral):
                                    friendlyCityCount += 1
                            node = node.next
                        existingMax, existingPath = curTileDict.get(path.length, defaultNoPathValue)
                        if value > existingMax:
                            node = path.start
                            while node is not None:
                                if (node.tile.isGeneral or node.tile.isCity) and node.tile.player == searchingPlayer:
                                    usage = cityUsages.get(node.tile, 0)
                                    cityUsages[node.tile] = usage + 1
                                node = node.next
                            if existingPath is not None:
                                logEntries.append(f'path for {str(tile)} BETTER than existing:\r\n      new {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')
                            curTileDict[path.length] = (value, path)

                            # todo dont need this...?
                            # sortedTiles.remove(path.start.tile)
                            newPaths.append((value, path))
                        else:
                            logEntries.append(f'path for {str(tile)} worse than existing:\r\n      bad {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')

                multiPathDict[tile] = curTileDict

            logEntries.append(f'iter complete @ {time.perf_counter() - startTime:.3f} iter {iter[0]} paths {len(newPaths)}')

            oldCutoffFactor = cutoffFactor
            oldValPerTurnCutoff = valPerTurnCutoff
            cutoffFactor += 3
            valPerTurnCutoff = valPerTurnCutoff * valPerTurnCutoffScaledown
            logEntries.append(
                f"Cycle complete with {len(newPaths)} paths, remainingTurns {remainingTurns}, incrementing cutoffFactor {oldCutoffFactor}->{cutoffFactor}, valuePerTurnCutoff {oldValPerTurnCutoff:.3f}->{valPerTurnCutoff:.3f}.")

            if len(newPaths) == 0:
                logEntries.append(
                    f"No multi path found for remainingTurns {remainingTurns}. Allowing global visited disable for one cycle.")
                overrideGlobalVisitedOneCycle = True
            else:
                for value, path in newPaths:
                    logEntries.append(f'  new path {value:.2f}v  {value / path.length:.2f}vt  {str(path)}')
                    add_path_to_try_avoid_paths_crossing_tiles(path, negativeTiles, tryAvoidSet, pathsCrossingTiles, addToNegativeTiles=useIterativeNegTiles)
                    # for tile in path.tileList:
                    #     cityUsage = cityUsages.get(tile, 0)
                    #     if (tile.isCity or tile.isGeneral) and cityUsage < 2 and tile not in originalNegativeTiles:
                    #         logEntries.append('re-including city for additional usage.')
                    #         negativeTiles.remove(tile)
                    #         tryAvoidSet.remove(tile)

            firstIteration = False

        # expansionGather = greedy_backpack_gather(map, tilesLargerThanAverage, turns, None, valueFunc, baseCaseFunc, skipTiles, None, searchingPlayer, priorityFunc, skipFunc = None)
        if allowLeafMoves and leafMoves is not None:
            logEntries.append("Allowing leafMoves as part of optimal expansion....")
            for leafMove in leafMoves:
                if (leafMove.source not in negativeTiles
                        and leafMove.dest not in negativeTiles
                        and (leafMove.dest.player == -1 or leafMove.dest.player in targetPlayers)):
                    if leafMove.source.army >= 30:
                        logEntries.append(
                            f"Did NOT add leafMove {str(leafMove)} to knapsack input because its value was high. Why wasn't it already input if it is a good move?")
                        continue
                    if leafMove.source.army - 1 <= leafMove.dest.army:
                        continue

                    if not move_can_cap_more(leafMove) and useLeafMovesFirst:
                        continue  # already added first

                    if leafMove.dest.isCity and leafMove.dest.isNeutral:
                        continue

                    logEntries.append(f"adding leafMove {str(leafMove)} to knapsack input")
                    path = Path(leafMove.source.army - leafMove.dest.army - 1)
                    path.add_next(leafMove.source)
                    path.add_next(leafMove.dest)
                    value = postPathEvalFunction(path, negativeTiles)
                    cityCount = 0
                    if leafMove.source.isGeneral or leafMove.source.isCity:
                        cityCount += 1
                    paths.append((cityCount, value, path))
                    add_path_to_try_avoid_paths_crossing_tiles(path, negativeTiles, tryAvoidSet, pathsCrossingTiles, addToNegativeTiles=useIterativeNegTiles)

                    curTileDict = multiPathDict.get(leafMove.source, {})
                    existingMax, existingPath = curTileDict.get(path.length, defaultNoPathValue)
                    if value > existingMax:
                        logEntries.append(
                            f'leafMove for {str(leafMove.source)} BETTER than existing:\r\n      new {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')
                        curTileDict[path.length] = (value, path)
                    else:
                        logEntries.append(
                            f'leafMove for {str(leafMove.source)} worse than existing:\r\n      bad {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')
                    multiPathDict[leafMove.source] = curTileDict

        path, otherPaths, totalTurns, totalValue = knapsack_multi_paths(
            map,
            searchingPlayer,
            friendlyPlayers,
            targetPlayers,
            remainingTurns,
            pathsCrossingTiles,
            multiPathDict,
            territoryMap,
            postPathEvalFunction,
            originalNegativeTiles,
            tryAvoidSet,
            viewInfo)

        altPath, altOtherPaths, altTotalTurns, altTotalValue = knapsack_multi_paths_no_crossover(
            map,
            searchingPlayer,
            friendlyPlayers,
            targetPlayers,
            remainingTurns,
            pathsCrossingTiles,
            multiPathDict,
            territoryMap,
            postPathEvalFunction,
            originalNegativeTiles,
            tryAvoidSet,
            viewInfo)

        if totalTurns == 0 or (altTotalTurns > 0 and altTotalValue / altTotalTurns > totalValue / totalTurns):
            msg = f'EXP CROSS-KNAP WORSE THAN NON, v{altTotalValue}/{totalValue} t{altTotalTurns}/{totalTurns}'
            if viewInfo is not None:
                viewInfo.add_info_line(msg)
            else:
                logging.warning(msg)

            path = altPath
            otherPaths = altOtherPaths
            totalValue = altTotalValue
            totalTurns = altTotalTurns
        if viewInfo is not None:
            _add_expansion_to_view_info(path, otherPaths, viewInfo, colors)

        tilesInKnapsackOtherThanCurrent = set()

        for curPath in otherPaths:
            for tile in curPath.tileList:
                tilesInKnapsackOtherThanCurrent.add(tile)

        if path is None:
            logEntries.append(
                f"No expansion plan.... :( iterations {iter[0]}, Duration {time.perf_counter() - startTime:.3f}")
            return path, otherPaths

        logEntries.append(
            f"EXPANSION PLANNED HOLY SHIT? iterations {iter[0]}, Duration {time.perf_counter() - startTime:.3f}, path {str(path)}")

        shouldConsiderMoveHalf = should_consider_path_move_half(
            map,
            path,
            negativeTiles=tilesInKnapsackOtherThanCurrent,
            player=searchingPlayer,
            enemyDistMap=enemyDistMap,
            playerDistMap=generalDistMap,
            withinGenPathThreshold=boardAnalysis.within_extended_play_area_threshold,
            tilesOnMainPathDist=boardAnalysis.within_core_play_area_threshold)

        if not shouldConsiderMoveHalf:
            return path, otherPaths

        path.start.move_half = True
        value = path.calculate_value(searchingPlayer, map._teams, originalNegativeTiles)
        if viewInfo:
            viewInfo.add_info_line(f'path move_half value was {value} (path {str(path)})')
        if value <= 0:
            path.start.move_half = False

        return path, otherPaths

    finally:
        logging.info('\n'.join(logEntries))


def _include_leaf_moves_in_exp_plan(
        allowGatherPlanExtension,
        alwaysIncludes: typing.List[Tile] | None,
        defaultNoPathValue,
        includeForGath: typing.List[Move] | None,
        leafMoves,
        map,
        multiPathDict,
        negativeTiles,
        paths,
        pathsCrossingTiles,
        postPathEvalFunction,
        searchingPlayer,
        targetPlayers,
        tryAvoidSet,
        useIterativeNegTiles,
        skipNeutrals: bool = False
):
    for leafMove in leafMoves:
        if (leafMove.source not in negativeTiles
                and leafMove.dest not in negativeTiles
                and (leafMove.dest.player == -1 or leafMove.dest.player in targetPlayers)):

            if leafMove.dest.isCity and leafMove.dest.isNeutral:
                continue

            if leafMove.source.army - 1 <= leafMove.dest.army:
                if leafMove.dest.player in targetPlayers and allowGatherPlanExtension and includeForGath is not None and leafMove.source.army > 1:
                    includeForGath.append(leafMove)
                continue

            if move_can_cap_more(leafMove):
                if alwaysIncludes is not None:
                    alwaysIncludes.append(leafMove.source)
                continue

            if leafMove.source.army - leafMove.dest.army >= 3:
                logging.info(
                    f"Did NOT add leafMove {str(leafMove)} to knapsack input because its value was high. Why wasn't it already input if it is a good move?")
                continue

            if skipNeutrals and leafMove.dest.isNeutral:
                continue

            # logging.info(f"adding leafMove {str(leafMove)} to knapsack input")
            path = Path(leafMove.source.army - leafMove.dest.army - 1)
            path.add_next(leafMove.source)
            path.add_next(leafMove.dest)
            _try_include_alt_sourced_path(
                map,
                searchingPlayer,
                defaultNoPathValue,
                multiPathDict,
                negativeTiles,
                path,
                paths,
                pathsCrossingTiles,
                postPathEvalFunction,
                tryAvoidSet,
                useIterativeNegTiles)


def _execute_expansion_gather_to_borders(
        map: MapBase,
        startTiles,
        depth: int,
        valueFunc=None,
        baseCaseFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=True,
        preferNeutral=False,
        distPriorityMap=None,
        shouldLog=False,
        priorityMatrix: MapMatrix[float] | None = None
) -> typing.List[Path]:
    """
    Does black magic and shits out a spiderweb with numbers in it, sometimes the numbers are even right

    @param map:
    @param startTiles:
    startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile]
    @param depth:
    @param valueFunc:
    valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object
    @param baseCaseFunc:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc:
    priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted
    @param skipFunc:
    @param priorityTiles:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param distPriorityMap:
    @return:
    """
    useTrueValueGathered = True
    includeGatherTreeNodesThatGatherNegative = False
    shouldLog = False
    startTime = time.perf_counter()
    if negativeTiles is not None:
        negativeTiles = negativeTiles.copy()
    else:
        negativeTiles = set()

    teams = MapBase.get_teams_array(map)

    # TODO break ties by maximum distance from threat (ideally, gathers from behind our gen are better
    #           than gathering stuff that may open up a better attack path in front of our gen)

    # TODO factor in cities, right now they're not even incrementing. need to factor them into the timing and calculate when they'll be moved.
    if searchingPlayer == -2:
        if isinstance(startTiles, dict):
            searchingPlayer = [t for t in startTiles.keys()][0].player
        else:
            searchingPlayer = startTiles[0].player

    if shouldLog:
        logging.info(f"Trying exp timing gather. Turns {depth}. Searching player {searchingPlayer}")
    if valueFunc is None:

        if shouldLog:
            logging.info("Using default valueFunc")

        def default_value_func_max_gathered_per_turn(
                currentTile,
                priorityObject
        ):
            (
                threatDist,
                depthDist,
                realDist,
                negPrioTilesPerTurn,
                negGatheredSum,
                negArmySum,
                # xSum,
                # ySum,
                numPrioTiles
            ) = priorityObject

            if negArmySum >= 0 and not includeGatherTreeNodesThatGatherNegative:
                return None
            if currentTile.army < 2 or currentTile.player != searchingPlayer:
                return None

            value = 0 - negGatheredSum

            vt = 0
            if realDist > 0:
                vt = value / realDist

            prioObj = (vt,  # most army per turn
                       0 - threatDist,
                       # then by the furthest 'distance' (which when gathering to a path, weights short paths to the top of the path higher which is important)
                       0 - negGatheredSum,  # then by maximum amount gathered...?
                       0 - depthDist,  # furthest distance traveled
                       realDist,  # then by the real distance
                       # 0 - xSum,
                       # 0 - ySum
            )
            if shouldLog:
                logging.info(f'VALUE {str(currentTile)} : {str(prioObj)}')
            return prioObj

        valueFunc = default_value_func_max_gathered_per_turn

    if priorityFunc is None:
        if shouldLog:
            logging.info("Using default priorityFunc")

        def default_priority_func(nextTile, currentPriorityObject):
            (
                threatDist,
                depthDist,
                realDist,
                negPrioTilesPerTurn,
                negGatheredSum,
                negArmySum,
                #xSum,
                #ySum,
                numPrioTiles
            ) = currentPriorityObject
            negArmySum += 1
            negGatheredSum += 1
            if nextTile not in negativeTiles:
                if teams[searchingPlayer] == teams[nextTile.player]:
                    negArmySum -= nextTile.army
                    negGatheredSum -= nextTile.army
                # # this broke gather approximation, couldn't predict actual gather values based on this
                # if nextTile.isCity:
                #    negArmySum -= turns // 3
                else:
                    negArmySum += nextTile.army
                    if useTrueValueGathered:
                        negGatheredSum += nextTile.army

            if priorityMatrix:
                negGatheredSum += priorityMatrix[nextTile]

            # if nextTile.player != searchingPlayer and not (nextTile.player == -1 and nextTile.isCity):
            #    negDistanceSum -= 1
            # hacks us prioritizing further away tiles
            # if distPriorityMap is not None:
            #     negDistanceSum -= distPriorityMap[nextTile.x][nextTile.y]
            if priorityTiles is not None and nextTile in priorityTiles:
                numPrioTiles += 1
            realDist += 1
            depthDist += 1
            prioObj = (
                threatDist + 1,
                depthDist,
                realDist,
                numPrioTiles / max(1, depthDist),
                negGatheredSum,
                negArmySum,
                #xSum + nextTile.x,
                #ySum + nextTile.y,
                numPrioTiles
            )
            if shouldLog:
                logging.info(f'PRIO {str(nextTile)} : {str(prioObj)}')
            # logging.info("prio: nextTile {} got realDist {}, negNextArmy {}, negDistanceSum {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
            return prioObj

        priorityFunc = default_priority_func

    if baseCaseFunc is None:
        if shouldLog:
            logging.info("Using default baseCaseFunc")

        def default_base_case_func(tile, startingDist):
            startArmy = tile.army
            # we would like to not gather to an enemy tile without killing it, so must factor it into the path. army value is negative for priority, so use positive for enemy army.
            # if useTrueValueGathered and tile.player != searchingPlayer:
            #     if shouldLog:
            #         logging.info(
            #             f"tile {tile.toString()} was not owned by searchingPlayer {searchingPlayer}, adding its army {tile.army}")
            #     startArmy = tile.army

            initialDistance = 0
            if distPriorityMap is not None:
                initialDistance = distPriorityMap[tile.x][tile.y]
            prioObj = (
                0 - initialDistance,
                startingDist,
                0,
                0,
                0,
                startArmy,
                # tile.x,
                # tile.y,
                0
            )
            if shouldLog:
                logging.info(f"BASE CASE: {str(tile)} -> {str(prioObj)}")
            return prioObj

        baseCaseFunc = default_base_case_func

    startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]] = {}
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            if isinstance(startTiles[tile], int):
                distance = startTiles[tile]
                startTilesDict[tile] = (baseCaseFunc(tile, distance), distance)
            else:
                startTilesDict = startTiles

            negativeTiles.add(tile)
    else:
        for tile in startTiles:
            # then use baseCaseFunc to initialize their priorities, and set initial distance to 0
            startTilesDict[tile] = (baseCaseFunc(tile, 0), 0)
            negativeTiles.add(tile)

    for tile in startTilesDict.keys():
        (startPriorityObject, distance) = startTilesDict[tile]

        if shouldLog:
            logging.info(f"Including tile {tile.x},{tile.y} in startTiles at distance {distance}")

    valuePerTurnPathPerTilePerDistance = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
        map,
        startTilesDict,
        valueFunc,
        0.003,
        maxTurns=len(startTilesDict) * 2,
        maxDepth=depth,
        noNeutralCities=True,
        negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=skipFunc,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        logResultValues=shouldLog,
        ignoreNonPlayerArmy=not useTrueValueGathered,
        ignoreIncrement=True,
        useGlobalVisitedSet=False,
        )

    paths: typing.List[Path] = []

    for tile, pathList in valuePerTurnPathPerTilePerDistance.items():
        for path in pathList:
            path = path.get_reversed()

            if path.value > 3:
                # these will get calculated by the real iterations
                continue

            paths.append(path)

    return paths


def _try_include_alt_sourced_path(
        map: MapBase,
        searchingPlayer: int,
        defaultNoPathValue,
        multiPathDict,
        negativeTiles,
        path,
        paths,
        pathsCrossingTiles,
        postPathEvalFunction,
        tryAvoidSet,
        useIterativeNegTiles
):

    value = postPathEvalFunction(path, negativeTiles)
    if value <= 0:
        return

    cityCount = 0
    for tile in path.tileList:
        if (tile.isGeneral or tile.isCity) and map.is_player_on_team_with(tile.player, searchingPlayer):
            cityCount += 1

    paths.append((cityCount, value, path))
    add_path_to_try_avoid_paths_crossing_tiles(
        path,
        negativeTiles,
        tryAvoidSet,
        pathsCrossingTiles,
        addToNegativeTiles=useIterativeNegTiles)

    curTileDict = multiPathDict.get(path.start.tile, {})
    existingMax, existingPath = curTileDict.get(path.length, defaultNoPathValue)
    # if value > existingMax:
    #     logging.info(
    #         f'leafMove {str(path.start.tile)} BETTER than existing:\r\n'
    #         f'   new   {value} {str(path)}\r\n'
    #         f'   exist {existingMax} {str(existingPath)}')
    #     curTileDict[path.length] = (value, path)
    # else:
    #     logging.info(
    #         f'leafMove for {str(path.start.tile)} worse than existing:\r\n      bad {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')
    multiPathDict[path.start.tile] = curTileDict


def _get_capture_counts(
        searchingPlayer: int,
        friendlyPlayers: typing.List[int],
        targetPlayers: typing.List[int],
        mainPath: Path | None,
        otherPaths: typing.List[Path],
        negativeTiles: typing.Set[Tile]
) -> typing.Tuple[int, int, int]:
    """
    Returns (turnsUsed, enemyCaptured, neutralCaptured). Negative tiles dont count towards the sums but do count towards turns used.

    @param mainPath:
    @param otherPaths:
    @param negativeTiles:
    @return:
    """

    allPaths = []
    if mainPath is not None:
        allPaths.append(mainPath)

    allPaths.extend(otherPaths)
    visited = negativeTiles.copy()
    enemyCapped = 0
    neutralCapped = 0
    turnsUsed = 0
    for path in allPaths:
        turnsUsed -= 1  # first tile in a path doesn't count
        for tile in path.tileList:
            turnsUsed += 1
            if tile in visited:
                continue
            visited.add(tile)
            if tile.player not in friendlyPlayers:
                if tile.player not in targetPlayers:
                    neutralCapped += 1
                else:
                    enemyCapped += 1

    return turnsUsed, enemyCapped, neutralCapped


def _get_uncertainty_capture_rating(friendlyPlayers: typing.List[int], path: Path, originalNegativeTiles: typing.Set[Tile]) -> float:
    rating = max(0, path.value) ** 0.5
    for t in path.tileList:
        if t.player not in friendlyPlayers:
            rating += 0.5
            if t.player >= 0:
                rating += 2.0

        if not t.visible:
            rating += 0.25
        if not t.discovered:
            rating += 0.5

    return rating

def find_best_expansion_path_to_move_first_by_city_weights(
        map,
        maxPaths,
        negativeTiles,
        originalNegativeTiles,
        postPathEvalFunction,
        remainingTurns,
        searchingPlayer,
        friendlyPlayers,
        territoryMap
) -> Path | None:
    playerCities = list(map.players[searchingPlayer].cities)
    if map.players[searchingPlayer].general is not None:
        playerCities.append(map.players[searchingPlayer].general)
    maxVal = 0
    maxUncertainty = 0
    path: Path | None = None
    waitingPaths = []
    for p in maxPaths:
        shouldWaitDueToCities = path_has_cities_and_should_wait(
            p,
            friendlyPlayers,
            playerCities,
            negativeTiles,
            territoryMap,
            remainingTurns)
        if shouldWaitDueToCities:
            waitingPaths.append(p)
    sumWaiting = 0
    for waitingPath in waitingPaths:
        sumWaiting += waitingPath.length
    if sumWaiting > remainingTurns - 2:
        logging.info('bypassing waiting city paths due to them covering most of the expansion plan')
        waitingPaths = []
    for p in maxPaths:
        thisVal = postPathEvalFunction(p, originalNegativeTiles) + (p.start.tile.army * p.start.tile.army - 4)
        thisUncertainty = _get_uncertainty_capture_rating(friendlyPlayers, p, originalNegativeTiles)

        if thisUncertainty > maxUncertainty or thisUncertainty == maxUncertainty and thisVal > maxVal:
            if p not in waitingPaths:
                logging.info(f'    path uncert{thisUncertainty:.2f} v{thisVal:.2f} > uncert{maxUncertainty:.2f} v{maxVal:.2f} {str(p)} and is new best')
                path = p
                maxVal = thisVal
                maxUncertainty = thisUncertainty
            else:
                logging.info(
                    f'    waiting on city path uncert{thisUncertainty:.2f} v{thisVal:.2f} > uncert{maxUncertainty:.2f} v{maxVal:.2f} {str(p)} because path_has_cities_and_should_wait')

    return path


def _prune_worst_paths_greedily(
        valuePerTurnPathPerTile: typing.Dict[typing.Any, typing.List[Path]],
        valueFunc: typing.Callable[[Path], int]
) -> typing.Dict[typing.Any, typing.List[Path]]:
    sum = 0
    count = 0
    for group in valuePerTurnPathPerTile.keys():
        for path in valuePerTurnPathPerTile[group]:
            sum += valueFunc(path) / path.length
            count += 1
    avg = sum / count

    newDict = {}
    for group in valuePerTurnPathPerTile.keys():
        pathListByGroup = valuePerTurnPathPerTile[group]
        newListByGroup = []
        for path in pathListByGroup:
            valPerTurn = valueFunc(path) / path.length
            if valPerTurn > avg:
                newListByGroup.append(path)
        if len(newListByGroup) > 0:
            newDict[group] = newListByGroup

    return newDict


def expansion_knapsack_gather_iteration(
        turns: int,
        valuePerTurnPathPerTile: typing.Dict[typing.Any, typing.List[Path]],
        shouldLog: bool = False,
        valueFunc: typing.Callable[[Path], int] | None = None,
) -> typing.Tuple[int, typing.List[Path]]:
    if valueFunc is None:
        def value_func(p: Path) -> int:
            return p.value
        valueFunc = value_func

    totalValue = 0
    maxKnapsackedPaths = []

    error = True
    attempts = 0
    while error and attempts < 4:
        attempts += 1
        try:
            # build knapsack weights and values
            groupedPaths = [valuePerTurnPathPerTile[item] for item in valuePerTurnPathPerTile]
            groups = []
            paths = []
            values = []
            weights = []
            groupIdx = 0
            for pathGroup in groupedPaths:
                if len(pathGroup) > 0:
                    for path in pathGroup:
                        groups.append(groupIdx)
                        paths.append(path)
                        values.append(valueFunc(path))
                        weights.append(path.length)
                    groupIdx += 1
            if len(paths) == 0:
                return 0, []

            # if shouldLog:
            logging.info(f"Feeding solve_multiple_choice_knapsack {len(paths)} paths turns {turns}:")
            if shouldLog:
                for i, path in enumerate(paths):
                    logging.info(
                        f"{i}:  group[{groups[i]}] value {values[i]} length {weights[i]} path {str(path)}")

            totalValue, maxKnapsackedPaths = KnapsackUtils.solve_multiple_choice_knapsack(
                paths,
                turns,
                weights,
                values,
                groups,
                longRuntimeThreshold=0.1)
            logging.info(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")
            error = False
        except AssertionError:
            logging.error(f'OVER-KNAPSACKED, PRUNING ALL PATHS UNDER AVERAGE. v\r\n{traceback.format_exc()}\r\nOVER-KNAPSACKED, PRUNING ALL PATHS UNDER AVERAGE.^ ')
            valuePerTurnPathPerTile = _prune_worst_paths_greedily(valuePerTurnPathPerTile, valueFunc)

    return totalValue, maxKnapsackedPaths


def should_consider_path_move_half(
        map: MapBase,
        path: Path,
        negativeTiles: typing.Set[Tile],
        player: int,
        playerDistMap: typing.List[typing.List[int]],
        enemyDistMap: typing.List[typing.List[int]],
        withinGenPathThreshold: int,
        tilesOnMainPathDist: int):
    # if is perfect amount to capture dest but not other dest
    src = path.start.tile
    dest = path.start.next.tile
    if src.player != dest.player:
        capAmt = src.army - 1 - dest.army
        halfCapAmt = Tile.get_move_half_amount(src.army) - dest.army
        halfCapLeftBehind = src.army - halfCapAmt
        canCapWithSplit = halfCapAmt > 0
        moreCapTile = None
        if (
                canCapWithSplit
                # and capAmt < 7
        ):
            canCapMoreOnPathWithNoSplit = False
            for nextCap in dest.movable:
                if nextCap == src:
                    continue
                if nextCap.player != src.player and capAmt - 1 > nextCap.army:
                    canCapMoreOnPathWithNoSplit = True
                    moreCapTile = nextCap
                    break

            canCapMoreAdjToSrcWithSplit = False
            for nextSrcCap in src.movable:
                if nextSrcCap == moreCapTile or nextSrcCap == dest:
                    continue
                if nextSrcCap.player != src.player and halfCapLeftBehind - 1 > nextSrcCap.army:
                    canCapMoreAdjToSrcWithSplit = True

            if (
                    capAmt < 7
                    and canCapMoreAdjToSrcWithSplit
                    and not canCapMoreOnPathWithNoSplit
                    and canCapWithSplit
            ):
                return True

    largeTileThreshold = int(
        max(16, map.players[player].standingArmy) ** 0.5)  # no smaller than sqrt(16) (4) can move half.

    pathTile: Tile = path.start.tile
    pathTileDistSum = enemyDistMap[pathTile.x][pathTile.y] + playerDistMap[pathTile.x][pathTile.y]

    def filter_alternate_movables(tile: Tile):
        if tile.isMountain:
            return False
        if tile.isCity and tile.player != player:
            return False
        if tile in negativeTiles:
            return False
        if tile in path.tileSet:
            return False
        if tile.player == player:
            return False

        tileDistSum = enemyDistMap[tile.x][tile.y] + playerDistMap[tile.x][tile.y]
        tileNotTooFarToFlank = tileDistSum < withinGenPathThreshold
        tileShouldTakeEverything = tileDistSum < tilesOnMainPathDist

        altMovableMovingAwayFromPath = pathTileDistSum < tileDistSum
        if altMovableMovingAwayFromPath and not tileNotTooFarToFlank:
            return False

        # a 4 move-half leaves 2 behind, a 5 move_half leaves 3 behind. +1 because path.value is already -1
        movingTile = path.start.tile
        capArmy = movingTile.army // 2
        pathValueWithoutCapArmy = path.value - capArmy

        altCappable = set()

        def filter_alternate_path(altTile: Tile):
            if altTile.isMountain:
                return
            if altTile in negativeTiles:
                return
            if altTile in path.tileSet:
                return
            if altTile.isCity and altTile.player != player:
                return
            if altTile.player == player:
                return
            if altTile.isNeutral and capArmy > 3:
                return
            if altTile == tile:
                return

            altTileDistSum = enemyDistMap[altTile.x][altTile.y] + playerDistMap[altTile.x][altTile.y]
            movingTowardPath = altTileDistSum < tileDistSum
            movingParallelToPath = altTileDistSum == tileDistSum
            if movingTowardPath or tileShouldTakeEverything or (tileNotTooFarToFlank and movingParallelToPath):
                altCappable.add(altTile)

        breadth_first_foreach(
            map,
            [tile],
            maxDepth=5,
            foreachFunc=filter_alternate_path)

        canCapTile = capArmy - 1 > tile.army
        isEnemyTileThatCanRecapture = tile.player >= 0 and tile.army > 2
        canProbablyCaptureNearbyTiles = len(altCappable) > capArmy // 2

        altPathSplitThresh = largeTileThreshold * 2

        if ((canCapTile and canProbablyCaptureNearbyTiles and movingTile.army < altPathSplitThresh)
                or (isEnemyTileThatCanRecapture and movingTile.army < largeTileThreshold)):
            return True

        return False

    if count(pathTile.movable, filter_alternate_movables) > 0:
        # TODO take into account whether the alt path would expand away from both generals
        return True

    return False
