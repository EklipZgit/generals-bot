import heapq
import time
import typing

import networkx as nx

import logbook
from pcst_fast import pcst_fast

from Interfaces import TileSet
from MapMatrix import MapMatrixInterface, MapMatrix
from base.client.map import MapBase, Tile


def build_network_x_steiner_tree(
        map: MapBase,
        includingTiles: typing.Iterable[Tile],
        weightMod: MapMatrixInterface[float],
        searchingPlayer=-2,
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None,
        # faster: bool = False
) -> typing.List[Tile]:
    """
    Builds an arbitrarily sized steiner tree (connected to includingTiles) based on some baseWeight.
    Non-iterative, this just does single network x steiner tree.

    @param map:
    @param includingTiles:
    @param searchingPlayer:
    @param weightMod:
    @param baseWeight:
    @param bannedTiles:
    @return:
    """
    # bannedTiles = None
    start = time.perf_counter()
    ogStart = start
    # if faster:
    g = build_networkX_graph_flat_add(map, weightMod, baseWeight, bannedTiles=bannedTiles)
    # else:
    #     g = build_networkX_graph(map, weightMod, baseWeight, bannedTiles=bannedTiles)

    nextTime = time.perf_counter()
    logbook.info(f'networkX graph build in {nextTime - start:.5f}s')
    start = nextTime

    terminalNodes = [t.tile_index for t in includingTiles]

    nextTime = time.perf_counter()
    logbook.info(f'terminalNodes in {nextTime - start:.5f}s')
    start = nextTime

    steinerTree: nx.Graph = nx.algorithms.approximation.steiner_tree(g, terminal_nodes=terminalNodes, method='mehlhorn')  # kou or mehlhorn. kou is just bad...?
    # steinerTree: nx.Graph = nx.algorithms.approximation.steiner_tree(g, terminal_nodes=terminalNodes)

    nextTime = time.perf_counter()
    logbook.info(f'steiner calc in {nextTime - start:.5f}s')
    start = nextTime
    includedNodes = [map.tiles_by_index[n] for n in steinerTree.nodes]

    nextTime = time.perf_counter()
    logbook.info(f'includedNodes in {nextTime - start:.5f}s')

    complete = time.perf_counter() - ogStart
    logbook.info(f'networkX steiner calculated {len(includedNodes)} node subtree in {complete:.5f}s')

    return includedNodes

#  SLOWER
# def build_networkX_graph(
#         map: MapBase,
#         weightMod: MapMatrixInterface[float] | None = None,
#         baseWeight: int = 1,
#         bannedTiles: typing.Container[Tile] | None = None
# ) -> nx.Graph:
#     def _tree_edges() -> typing.Generator[typing.Tuple[int, int, typing.Dict[str, typing.Any]], None, None]:
#         for tile in map.get_all_tiles():
#             if tile.isMountain:
#                 continue
#             # if tile.isObstacle:
#             #     continue
#
#             fromWeight = baseWeight
#             if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
#                 fromWeight += baseWeight * 1000
#
#             if weightMod:
#                 fromWeight -= weightMod.raw[tile.tile_index]
#
#             right = map.GetTile(tile.x + 1, tile.y)
#             down = map.GetTile(tile.x, tile.y + 1)
#             if right and not right.isObstacle:
#                 weight = fromWeight
#                 if right.isObstacle or (bannedTiles is not None and right in bannedTiles):
#                     weight += baseWeight * 1000
#
#                 if weightMod:
#                     weight -= weightMod.raw[right.tile_index]
#
#                 yield tile.tile_index, right.tile_index, {"weight": weight}
#             if down and not down.isObstacle:
#                 weight = fromWeight
#                 if down.isObstacle or (bannedTiles is not None and down in bannedTiles):
#                     weight += baseWeight * 1000
#
#                 if weightMod:
#                     weight -= weightMod.raw[down.tile_index]
#
#                 yield tile.tile_index, down.tile_index, {"weight": weight}
#
#     start = time.perf_counter()
#     # edges = [e for e in _tree_edges()]
#     #
#     # nextTime = time.perf_counter()
#     # logbook.info(f'networkX initial edges build in {nextTime - start:.5f}s')
#     # start = nextTime
#     #
#     # g = nx.Graph(edges)
#     g = nx.Graph(_tree_edges())
#
#     nextTime = time.perf_counter()
#     logbook.info(f'networkX graph itself built in {nextTime - start:.5f}s')
#     return g


def build_networkX_graph_flat_add(
        map: MapBase,
        weightMod: MapMatrixInterface[float],
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None
) -> nx.Graph:
    start = time.perf_counter()

    g = nx.Graph()

    for tile in map.get_all_tiles():
        if tile.isMountain:
            continue
        # if tile.isObstacle:
        #     continue

        fromWeight = baseWeight
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            fromWeight += baseWeight * 1000

        fromWeight -= weightMod.raw[tile.tile_index]

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and not right.isObstacle:
            weight = fromWeight
            if right.isObstacle or (bannedTiles is not None and right in bannedTiles):
                weight += baseWeight * 1000

            weight -= weightMod.raw[right.tile_index]

            g.add_edge(tileIndex, right.tile_index, weight=weight)
        if down and not down.isObstacle:
            weight = fromWeight
            if down.isObstacle or (bannedTiles is not None and down in bannedTiles):
                weight += baseWeight * 1000

            weight -= weightMod.raw[down.tile_index]

            g.add_edge(tileIndex, down.tile_index, weight=weight)

    nextTime = time.perf_counter()
    logbook.info(f'networkX graph itself built in {nextTime - start:.5f}s')
    return g


def _build_pcst_tile_prize_matrix(
        map: MapBase,
        searchingPlayer: int,
        rootTiles: typing.List[Tile],
        negativeTiles: TileSet | None,
        prioritizeCaptureHighArmyTiles: bool,
        skipTiles: TileSet | None,
        enemyArmyFactor: float = 0.1,
        enemyArmyLimit: int = 10,
        gatherMatrix: MapMatrixInterface[float] | None = None,
        captureMatrix: MapMatrixInterface[float] | None = None,
        hintIncludeTiles: TileSet | None = None,
) -> typing.Tuple[MapMatrix[float], MapMatrix[float]]:
    """
    Returns prizeMatrix, extraCostMatrix

    @param map:
    @param searchingPlayer:
    @param rootTiles:
    @param negativeTiles:
    @param prioritizeCaptureHighArmyTiles:
    @param skipTiles:
    @param enemyArmyFactor: if prioritizeCaptureHighArmyTiles is True, then the enemy tile army is multiplied by this number and added to prize, if the enemy army is under enemyArmyLimit. If prioritizeCaptureHighArmyTiles is false, the enemy tile army is multiplied by this and then added to the extra cost table.
    @param enemyArmyLimit: If an enemy tiles army is above this value, it will not affect the cost/prize matrices.
    @param gatherMatrix:
    @param captureMatrix:
    @param hintIncludeTiles: any tiles in here will be rewarded with a lower movement cost.
    @return:
    """

    tilePrizeMatrix = MapMatrix(map, 0.0)
    tileExtraCostMatrix = MapMatrix(map, 0.0)

    for tile in map.reachable_tiles:
        prize = 0.0
        extraCost = 0.0

        if map.is_tile_on_team_with(tile, searchingPlayer):
            prize = float(tile.army)
            if gatherMatrix:
                prize += gatherMatrix.raw[tile.tile_index]
        else:
            if not prioritizeCaptureHighArmyTiles:
                extraCost = tile.army * enemyArmyFactor
                if captureMatrix and tile.army < enemyArmyLimit:
                    capVal = captureMatrix.raw[tile.tile_index]
                    prize = capVal
            else:
                if captureMatrix and tile.army < enemyArmyLimit:
                    prize = float(tile.army) * enemyArmyFactor
                    capVal = captureMatrix.raw[tile.tile_index]
                    prize += capVal

        tilePrizeMatrix.raw[tile.tile_index] = prize
        tileExtraCostMatrix.raw[tile.tile_index] = extraCost

    if negativeTiles:
        for tile in map.iterate_tile_set(negativeTiles):
            tileExtraCostMatrix.raw[tile.tile_index] += 2.0
            tilePrizeMatrix.raw[tile.tile_index] = -1.0

    if hintIncludeTiles:
        for tile in map.iterate_tile_set(hintIncludeTiles):
            # never extra-cost these, and make their cost hint lower than other nearby
            tileExtraCostMatrix.raw[tile.tile_index] = -1.0
            tilePrizeMatrix.raw[tile.tile_index] += 0.5

    # root tiles have no value themselves, should always be included
    for tile in rootTiles:
        tilePrizeMatrix.raw[tile.tile_index] += 1.0
        tileExtraCostMatrix.raw[tile.tile_index] = -1.0

    return tilePrizeMatrix, tileExtraCostMatrix


def get_prize_collecting_gather_mapmatrix(
        map: MapBase,
        searchingPlayer=-2,
        # armyCutoff = 2.0,
        targetTurns = -1,
        maxTurns: int | None = None,
        gatherMatrix: MapMatrixInterface[float] | None = None,
        captureMatrix: MapMatrixInterface[float] | None = None,
        rootTiles: typing.List[Tile] | None = None,
        negativeTiles: TileSet | None = None,
        prioritizeCaptureHighArmyTiles: bool = False,
        skipTiles: TileSet | None = None,
        hintIncludeTiles: TileSet | None = None,
        sameResultCutoff = 5,
        enemyArmyCostFactor = 0.1,
        enemyArmyLimit: int = 10,
        timeLimit: float = 0.2
) -> typing.List[Tile] | None:
    """
    Does black magic and shits out a spiderweb with numbers in it, sometimes the numbers are even right

    @param map:
    startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile]
    valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object
    @param searchingPlayer:
    priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted
    @return:
    """

    start = time.perf_counter()

    tilePrizeMatrix, tileExtraCostMatrix = _build_pcst_tile_prize_matrix(
        map=map,
        searchingPlayer=searchingPlayer,
        rootTiles=rootTiles,
        negativeTiles=negativeTiles,
        prioritizeCaptureHighArmyTiles=prioritizeCaptureHighArmyTiles,
        skipTiles=skipTiles,
        enemyArmyFactor=enemyArmyCostFactor,
        enemyArmyLimit=enemyArmyLimit,
        gatherMatrix=gatherMatrix,
        captureMatrix=captureMatrix,
        hintIncludeTiles=hintIncludeTiles,
    )

    bestResult = _pcst_gradient_search(
        map,
        sameResultCutoff,
        targetTurns,
        rootTiles,
        costIterations=7,
        prizeIterations=7,
        tilePrizeMatrix=tilePrizeMatrix,
        tileExtraCostMatrix=tileExtraCostMatrix,
        cutoffTime=time.perf_counter() + timeLimit,
        skipTiles=skipTiles,
        maxTurns=maxTurns,
    )

    # bestResult = _pcst_gradient_quadrant_search(
    #     map,
    #     sameResultCutoff,
    #     targetTurns,
    #     rootTiles,
    #     iterations=7,
    #     tilePrizeMatrix=tilePrizeMatrix,
    #     tileExtraCostMatrix=tileExtraCostMatrix,
    #     cutoffTime=time.perf_counter() + timeLimit,
    #     skipTiles=skipTiles,
    #     maxTurns=maxTurns,
    # )

    if bestResult is not None:
        outTiles = [map.get_tile_by_tile_index(v) for v in bestResult]
        logbook.info(f'pcst iterative took {time.perf_counter() - start:.5f}s, output {len(outTiles) - len(rootTiles)} turns {len(bestResult)} nodes (target {targetTurns})')
        return outTiles
    else:
        logbook.info(f'pcst iterative took {time.perf_counter() - start:.5f}s, output None.')
        return None


def _pcst_gradient_search(
        map,
        sameResultCutoff,
        targetTurns,
        rootTiles: typing.List[Tile] | None,
        costIterations: int,
        prizeIterations: int,
        tilePrizeMatrix: MapMatrixInterface[float],
        tileExtraCostMatrix: MapMatrixInterface[float],
        cutoffTime: float | None = None,
        skipTiles: TileSet | None = None,
        maxTurns: int | None = None,
) -> typing.List[int] | None:
    start = time.perf_counter()
    lastCount = -1000
    bestResult = None
    bestDiff = 100000
    sameResultCount = 0
    bestMin = 0.0
    bestMax = 200.0
    costIters = 0
    lastDiffRaw = -1

    targetNodeCount = targetTurns + len(rootTiles)
    maxNodes = 2000
    if maxTurns is not None:
        maxNodes = maxTurns + len(rootTiles)

    rootCount = 0
    if rootTiles:
        rootCount = len(rootTiles)

    costCutoffsToTry = [1.0, 2.0, 5.0, 10.0, 50.0, 100.0]
    results = []

    prevCutoff = None
    bestPrev = 0.0
    bestNext = 20.0
    wasMax = False
    for initialCostCutoff in costCutoffsToTry:
        costIters += 1
        curPrizeIterLimit = 4
        prizeMax, prizeMin, vertices = _pcst_gradient_descent_prize_basis(
            map,
            targetNodeCount=targetNodeCount,
            # maxNodeCount=maxNodes,  # if we limit this by max nodes, then it will make the algo thing we're always undershooting instead of understanding we overshot.
            costCutoff=initialCostCutoff,
            iterationLimit=curPrizeIterLimit,
            sameResultCutoff=sameResultCutoff,
            rootTiles=rootTiles,
            skipTiles=skipTiles,
            tilePrizeMatrix=tilePrizeMatrix,
            tileExtraCostMatrix=tileExtraCostMatrix,
        )
        vCount = 0 - targetNodeCount
        if vertices is not None:
            vCount = len(vertices)

        logbook.info(f'  cost attempt at {initialCostCutoff:.5f} output {vCount} nodes (target {targetNodeCount}, prizeMin {prizeMin:.5f}, prizeMax {prizeMax:.5f})')

        newDiff = vCount - targetNodeCount

        if wasMax:
            wasMax = False
            bestNext = initialCostCutoff

        lastCount = vCount
        absNewDiff = abs(newDiff)
        if absNewDiff <= bestDiff and 1 < vCount <= maxNodes:
            if prevCutoff is not None:
                bestPrev = prevCutoff
            wasMax = True
            bestDiff = absNewDiff
            bestResult = vertices
            logbook.info(f'  --cost attempt NEW BEST {initialCostCutoff:.5f} output {vCount} nodes (target {targetNodeCount}, prizeMin {prizeMin:.5f}, prizeMax {prizeMax:.5f})')

        lastDiffRaw = newDiff

        if cutoffTime is not None and time.perf_counter() > cutoffTime - 0.001:
            logbook.info(f'  cost attempt BREAKING EARLY')
            break
        prevCutoff = initialCostCutoff

    logbook.info(f'  cost INITIAL RESULTS {time.perf_counter() - start:.4f}s in: min {bestPrev:.2f} max {bestNext:.2f}')

    minCutoff = bestPrev
    maxCutoff = bestNext
    nextCutoff = (bestPrev + bestNext) / 2

    leniencyFactor = 0.6
    leniencyFactor = 1.0
    leniencyScaler = 0.1
    costIters = 0
    while (sameResultCount != sameResultCutoff or costIters < 10) and costIters < costIterations:
        costIters += 1

        # vertices = _pcst_iteration_internal(map, searchingPlayer, toTile, nextCutoff, enemyArmyCostFactor, gatherMatrix, captureMatrix)
        curPrizeIterLimit = max(2, prizeIterations - (costIterations - costIters) // 2)
        prizeMax, prizeMin, vertices = _pcst_gradient_descent_prize_basis(
            map,
            targetNodeCount=targetNodeCount,
            # maxNodeCount=maxNodes,  # if we limit this by max nodes, then it will make the algo thing we're always undershooting instead of understanding we overshot.
            costCutoff=nextCutoff,
            iterationLimit=curPrizeIterLimit,
            sameResultCutoff=sameResultCutoff,
            rootTiles=rootTiles,
            skipTiles=skipTiles,
            tilePrizeMatrix=tilePrizeMatrix,
            tileExtraCostMatrix=tileExtraCostMatrix,
        )
        vCount = 0 - targetNodeCount
        if vertices is not None:
            vCount = len(vertices)

        logbook.info(f'  cost attempt at {nextCutoff:.5f} output {vCount} nodes (target {targetNodeCount}, min {minCutoff:.5f}, max {maxCutoff:.5f}, prizeMin {prizeMin:.5f}, prizeMax {prizeMax:.5f})')

        newDiff = vCount - targetNodeCount
        # if newDiff > 2:
        #     # because the algo is not exact, adjust the cutoff a bit more leniently
        #     minCutoff = minCutoff + (nextCutoff - minCutoff) * 0.8
        # elif newDiff < -2:
        #     # because the algo is not exact, adjust the cutoff a bit more leniently
        #     maxCutoff = maxCutoff - (maxCutoff - nextCutoff) * 0.8

        if newDiff > 0:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            minCutoff = minCutoff + (nextCutoff - minCutoff) * leniencyFactor
        elif newDiff < 0:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            maxCutoff = maxCutoff - (maxCutoff - nextCutoff) * leniencyFactor
        else:
            minCutoff = minCutoff + (nextCutoff - minCutoff) * (leniencyFactor - 0.2)
            maxCutoff = maxCutoff - (maxCutoff - nextCutoff) * (leniencyFactor - 0.2)

        if vCount != lastCount:
            sameResultCount = 0
        else:
            sameResultCount += 1

        nextCutoff = (maxCutoff + minCutoff) / 2

        lastCount = vCount
        absNewDiff = abs(newDiff)
        if absNewDiff <= bestDiff and 1 < vCount <= maxNodes:
            if bestMin < minCutoff and lastDiffRaw < newDiff:
                bestMin = minCutoff
            if bestMax > maxCutoff and lastDiffRaw > newDiff:
                bestMax = maxCutoff
            bestDiff = absNewDiff
            bestResult = vertices

        lastDiffRaw = newDiff

        if cutoffTime is not None and time.perf_counter() > cutoffTime - 0.001:
            logbook.info(f'  cost attempt BREAKING EARLY')
            break

        leniencyFactor = min(1.0, leniencyFactor + leniencyScaler)

    bestCount = 0-targetNodeCount
    if bestResult is not None:
        bestCount = len(bestResult)

    logbook.info(f'pcst cost cutoff took {time.perf_counter() - start:.5f}s, output {bestCount - rootCount} turns, {bestCount} nodes. (bestMin {bestMin:.4f}, bestMax {bestMax:.4f})')

    return bestResult


def _adjust_weights(minVal: float, midVal: float, maxVal: float, bestVals: typing.Set[float], leniencyFactor: float, bestVal: float, varName: str, force: bool = False) -> typing.Tuple[float, float, float, bool]:
    changed = False
    if midVal not in bestVals:
        if maxVal not in bestVals:
            logbook.info(f'mid{varName} out, max{varName} out')
            maxVal = maxVal - (maxVal - midVal) * leniencyFactor
            changed = True
        elif minVal not in bestVals:
            logbook.info(f'mid{varName} out, min{varName} out')
            minVal = minVal + (midVal - minVal) * leniencyFactor
            changed = True
        else:
            if not force:
                logbook.info(f'WTF mid{varName} WASNT IN BEST BUT MAX AND MIN BOTH WERE?? NOT ADJUSTING')
            else:
                logbook.info(f'WTF mid{varName} WASNT IN BEST BUT MAX AND MIN BOTH WERE?? Adjusting slightly')
                minVal = minVal + (bestVal - minVal) * 0.3
                maxVal = maxVal - (maxVal - bestVal) * 0.3
                changed = True
    else:
        if maxVal not in bestVals and minVal not in bestVals:
            logbook.info(f'mid{varName} in, max{varName} and min{varName} out')
            maxVal = maxVal - (maxVal - midVal) * leniencyFactor
            minVal = minVal + (midVal - minVal) * leniencyFactor
            changed = True
        elif maxVal not in bestVals:
            logbook.info(f'mid{varName} in, max{varName} out')
            maxVal = maxVal - (maxVal - midVal) * leniencyFactor
            changed = True
        elif minVal not in bestVals:
            logbook.info(f'mid{varName} in, min{varName} out')
            minVal = minVal + (midVal - minVal) * leniencyFactor
            changed = True
        else:
            if not force:
                logbook.info(f'EVERYTHING was in best{varName}s...? WTF? Skipping')
            else:
                logbook.info(f'EVERYTHING was in best{varName}s...? WTF? Using JUST best {varName} {bestVal:.4f}.')
                minVal = minVal + (bestVal - minVal) * 0.3
                maxVal = maxVal - (maxVal - bestVal) * 0.3
                changed = True

    midVal = (minVal + maxVal) / 2

    return minVal, midVal, maxVal, changed



def _pcst_gradient_quadrant_search(
        map,
        sameResultCutoff,
        targetTurns,
        rootTiles: typing.List[Tile] | None,
        iterations: int,
        tilePrizeMatrix: MapMatrixInterface[float],
        tileExtraCostMatrix: MapMatrixInterface[float],
        cutoffTime: float | None = None,
        skipTiles: TileSet | None = None,
        maxTurns: int | None = None,
        exactTurnsLeeway: int = 0
) -> typing.List[int] | None:
    minPrize = -150
    maxPrize = 20
    minCost = -1.0
    maxCost = 100.0

    midPrize = -1
    midCost = 20

    start = time.perf_counter()
    lastCount = -1000
    bestResult = None
    bestDiff = 100000
    bestValue = -1000
    sameResultCount = 0
    lastDiffRaw = -1

    targetNodeCount = targetTurns + len(rootTiles)
    maxNodes = 2000
    if maxTurns is not None:
        maxNodes = maxTurns + len(rootTiles)

    rootCount = 0
    if rootTiles:
        rootCount = len(rootTiles)

    # each iteration checks the 4 corners and the middle and then we shift away from the worst performers.

    creep = 0.06

    leniencyFactor = 0.9
    # leniencyFactor = 1.0
    leniencyScaler = -0.07
    curIter = 0
    cache = {}
    # changeSeed = 13
    while curIter < iterations: #(sameResultCount != sameResultCutoff or curIter < 10) and
        curIter += 1

        costsToCheck = [minCost, midCost, maxCost]
        prizesToCheck = [minPrize, midPrize, maxPrize]

        rawOutput = [[-1000 for j in range(len(prizesToCheck))] for i in range(len(costsToCheck))]
        absoluteOutput = [[-1000 for j in range(len(prizesToCheck))] for i in range(len(costsToCheck))]
        verticesOutput = [[-1000 for j in range(len(prizesToCheck))] for i in range(len(costsToCheck))]
        for i, costCutoff in enumerate(costsToCheck):
            for j, prizeCutoff in enumerate(prizesToCheck):
                vertices = cache.get((costCutoff, prizeCutoff), None)
                if vertices is None:
                    vertices = _pcst_iteration_internal(
                        map,
                        cutoffFactor=costCutoff,
                        tilePrizeMatrix=tilePrizeMatrix,
                        tileExtraCostMatrix=tileExtraCostMatrix,
                        prizeOffset=prizeCutoff,
                        rootTiles=rootTiles,
                        skipTiles=skipTiles)
                    cache[(costCutoff, prizeCutoff)] = vertices

                numV = -1000
                if vertices is not None:
                    numV = len(vertices)

                # logbook.info(f'  cost {costCutoff:.5f} prize {prizeCutoff:.5f} output {numV} nodes (target {targetNodeCount})')

                if numV <= rootCount:
                    numV = -1000

                diff = numV - targetNodeCount
                absNewDiff = abs(diff)
                if diff > 0 and maxNodes < numV:
                    absNewDiff += 10
                rawOutput[i][j] = diff
                absoluteOutput[i][j] = absNewDiff
                verticesOutput[i][j] = vertices
                if absNewDiff <= bestDiff and 1 < numV <= maxNodes:
                    value = 0.0
                    for tIdx in vertices:
                        value += tilePrizeMatrix.raw[tIdx]

                    valFactored = value / (absNewDiff + exactTurnsLeeway + 1)
                    if valFactored >= bestValue or absNewDiff < bestDiff:
                        bestDiff = absNewDiff
                        bestResult = vertices
                        bestValue = valFactored
                        logbook.info(f'bestResult updated to val {bestValue:.3f} turns {len(vertices) - len(rootTiles)}')

        # sum each row and each column and compute the average?
        # shift away from columns / rows that all produce bad values?
        minHeap = []
        for i, col in enumerate(absoluteOutput):
            for j, absDiff in enumerate(col):
                heapq.heappush(minHeap, (absDiff, (i, j), rawOutput[i][j]))

        vals = []
        last = -1
        while minHeap:
            vals.append(heapq.heappop(minHeap))

        # see what the best 4 of the 9 are a mix of.
        bestCosts = set()
        bestPrizes = set()

        bestAbsDiff, (i, j), rawDiff = vals[0]
        logbook.info(f'best abs diff was {bestAbsDiff}')
        bestCost = costsToCheck[i]
        bestPrize = prizesToCheck[j]
        secondBestAbsDiff, (i, j), rawDiff = vals[1]
        secondBestCost = costsToCheck[i]
        secondBestPrize = prizesToCheck[j]

        cutoffPoint = 3

        cutoffAbsDiff, (i, j), rawDiff = vals[cutoffPoint]
        if cutoffAbsDiff == bestAbsDiff:
            cutoffAbsDiff += 1

        if cutoffAbsDiff > secondBestAbsDiff:
            cutoffAbsDiff = min(cutoffAbsDiff, (secondBestAbsDiff * 1.2) + 2)

        header = f'prize      {str(f"{costsToCheck[0]:.4f}").rjust(8)} {str(f"{costsToCheck[1]:.4f}").rjust(8)} {str(f"{costsToCheck[2]:.4f}").rjust(8)} cost'
        r1 = f'{str(f"{prizesToCheck[0]:.4f}").rjust(10)} {str(absoluteOutput[0][0]).rjust(8)} {str(absoluteOutput[1][0]).rjust(8)} {str(absoluteOutput[2][0]).rjust(8)}'
        r2 = f'{str(f"{prizesToCheck[1]:.4f}").rjust(10)} {str(absoluteOutput[0][1]).rjust(8)} {str(absoluteOutput[1][1]).rjust(8)} {str(absoluteOutput[2][1]).rjust(8)}'
        r3 = f'{str(f"{prizesToCheck[2]:.4f}").rjust(10)} {str(absoluteOutput[0][2]).rjust(8)} {str(absoluteOutput[1][2]).rjust(8)} {str(absoluteOutput[2][2]).rjust(8)}'
        logbook.info(f'iter {curIter} results:\r\n{header}\r\n{r1}\r\n{r2}\r\n{r3}')

        # pull anything else out with the same value, so we dont leave things out of 'best' due to tiebreaks.
        for i, val in enumerate(vals):
            absDiff, (i, j), rawDiff = val
            if absDiff >= cutoffAbsDiff:
                break

            cost = costsToCheck[i]
            prize = prizesToCheck[j]
            bestCosts.add(cost)
            bestPrizes.add(prize)
            logbook.info(f'popped val {absDiff} cost {cost:.5f} prize {prize:.5f}')

        preMinMaxLine = f'OLD: minCost {minCost:.3f} maxCost {maxCost:.3f} minPrize {minPrize:.3f} maxPrize {maxPrize:.3f}'

        minCost, midCost, maxCost, changedCost = _adjust_weights(minCost, midCost, maxCost, bestCosts, leniencyFactor, bestCost, varName='Cost')
        minPrize, midPrize, maxPrize, changedPrize = _adjust_weights(minPrize, midPrize, maxPrize, bestPrizes, leniencyFactor, bestPrize, varName='Prize')

        if not changedCost and not changedPrize:
            if curIter & 1 == 0:
                minCost, midCost, maxCost, changedCost = _adjust_weights(minCost, midCost, maxCost, bestCosts, leniencyFactor, bestCost, varName='Cost', force=True)
                if not changedCost:
                    minPrize, midPrize, maxPrize, changedPrize = _adjust_weights(minPrize, midPrize, maxPrize, bestPrizes, leniencyFactor, bestPrize, varName='Prize', force=True)
            else:
                minPrize, midPrize, maxPrize, changedPrize = _adjust_weights(minPrize, midPrize, maxPrize, bestPrizes, leniencyFactor, bestPrize, varName='Prize', force=True)
                if not changedPrize:
                    minCost, midCost, maxCost, changedCost = _adjust_weights(minCost, midCost, maxCost, bestCosts, leniencyFactor, bestCost, varName='Cost', force=True)

        if curIter & 1 == 0:
            minCost -= (maxCost - minCost) * creep
            minPrize -= (maxPrize - minPrize) * creep
        else:
            maxCost += (maxCost - minCost) * creep
            maxPrize += (maxPrize - minPrize) * creep

        postMinMaxLine = f'NEW: minCost {minCost:.3f} maxCost {maxCost:.3f} minPrize {minPrize:.3f} maxPrize {maxPrize:.3f}'

        logbook.info(f'\r\n{preMinMaxLine}\r\n{postMinMaxLine}\r\ntaken {time.perf_counter() - start:.5f}s so far')

        # logbook.info(f'  cost attempt at {nextCutoff:.5f} output {vCount} nodes (target {targetNodeCount}, min {minCutoff:.5f}, max {maxCutoff:.5f}, prizeMin {prizeMin:.5f}, prizeMax {prizeMax:.5f})')
        if cutoffTime is not None and time.perf_counter() > cutoffTime - 0.001:
            logbook.info(f'  cost attempt BREAKING EARLY')
            break

        leniencyFactor = max(0.4, min(1.1, leniencyFactor + leniencyScaler))

        if not changedCost and not changedPrize:
            logbook.info(f'pcst quadrant breaking early because no changes made to min/maxes')
            break

    bestCount = 0-targetNodeCount
    if bestResult is not None:
        bestCount = len(bestResult)

    logbook.info(f'pcst cost cutoff took {time.perf_counter() - start:.5f}s, output {bestCount - rootCount} turns, {bestCount} nodes.')

    return bestResult


def _pcst_gradient_descent_prize_basis(
        map,
        targetNodeCount,
        costCutoff,
        iterationLimit,
        sameResultCutoff,
        tilePrizeMatrix: MapMatrixInterface[float],
        tileExtraCostMatrix: MapMatrixInterface[float],
        rootTiles: typing.List[Tile] | None,
        skipTiles: TileSet | None = None,
) -> typing.Tuple[int, int, typing.List[int] | None]:
    lastCount = -1000
    minCutoff = -80.0
    maxCutoff = 10.0
    bestResult = None
    bestDiff = 100000
    nextCutoff = -5.0
    sameResultCount = 0
    bestMax = 100.0
    bestMin = -100
    iters = 0
    lastDiffRaw = -1
    leniencyFactor = 1.0 - max(0, iterationLimit - 3) * 0.15
    leniencyScaler = 0.1
    rootLen = len(rootTiles)
    while (sameResultCount != sameResultCutoff or iters < 10) and iters < iterationLimit:
        iters += 1

        vertices = _pcst_iteration_internal(
            map,
            cutoffFactor=costCutoff,
            tilePrizeMatrix=tilePrizeMatrix,
            tileExtraCostMatrix=tileExtraCostMatrix,
            prizeOffset=nextCutoff,
            rootTiles=rootTiles,
            skipTiles=skipTiles)

        vCount = -1000
        if len(vertices) > rootLen:
            vCount = len(vertices)

        logbook.info(f'     prize attempt at {nextCutoff:.5f} output {vCount} nodes (target {targetNodeCount}, min {minCutoff:.5f}, max {maxCutoff:.5f}, cost cutoff {costCutoff:.5f})')

        newDiff = vCount - targetNodeCount
        if newDiff < 0:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            minCutoff = minCutoff + (nextCutoff - minCutoff) * leniencyFactor
        else:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            maxCutoff = maxCutoff - (maxCutoff - nextCutoff) * leniencyFactor

        if vCount != lastCount:
            sameResultCount = 0
        else:
            sameResultCount += 1

        nextCutoff = (maxCutoff + minCutoff) / 2

        lastCount = vCount
        absNewDiff = abs(newDiff)
        if absNewDiff <= bestDiff and vCount > rootLen:
            if bestMin < minCutoff and lastDiffRaw < newDiff:
                bestMin = minCutoff
            if bestMax > maxCutoff and lastDiffRaw > newDiff:
                bestMax = maxCutoff
            bestDiff = absNewDiff
            bestResult = vertices

        lastDiffRaw = newDiff
        if targetNodeCount == -1:
            break

        # leniencyFactor = min(1.0, leniencyFactor + leniencyScaler)
        leniencyFactor = min(1.0, leniencyFactor + leniencyScaler)

    return bestMax, bestMin, bestResult


def _pcst_iteration_internal(
        map: MapBase,
        cutoffFactor: float,
        tilePrizeMatrix: MapMatrixInterface[float],
        tileExtraCostMatrix: MapMatrixInterface[float],
        skipTiles: TileSet | None = None,
        prizeOffset: float = 0.0,
        rootTiles: typing.List[Tile] | None = None,
        fastMode: bool = False
) -> typing.List[int]:
    """
    THIS IS THE FULL DOCS FROM GITHUB, DONT LOOK FOR BETTER DOCS.
    The pcst_fast package contains the following function:

    vertices, edges = pcst_fast(edges, prizes, costs, root, num_clusters, pruning, verbosity_level)
    The parameters are:

    edges: a 2D int64 array. Each row (of length 2) specifies an undirected edge in the input graph. The nodes are labeled 0 to n-1, where n is the number of nodes.
    prizes: the node prizes as a 1D float64 array.
    costs: the edge costs as a 1D float64 array.
    root: the root note for rooted PCST. For the unrooted variant, this parameter should be -1.
    num_clusters: the number of connected components in the output.
    pruning: a string value indicating the pruning method. Possible values are 'none', 'simple', 'gw', and 'strong' (all literals are case-insensitive). 'none' and 'simple' return intermediate stages of the algorithm and do not have approximation guarantees. They are only intended for development. The standard GW pruning method is 'gw', which is also the default. 'strong' uses "strong pruning", which was introduced in [JMP00]. It has the same theoretical guarantees as GW pruning but better empirical performance in some cases. For the PCSF problem, the output of strong pruning is at least as good as the output of GW pruning.
    verbosity_level: an integer indicating how much debug output the function should produce.
    The output variables are:

    vertices: the vertices in the solution as a 1D int64 array.
    edges: the edges in the output as a 1D int64 array. The list contains indices into the list of edges passed into the function.
    """

    edges = []
    """ edges: a 2D int64 array. Each row (of length 2) specifies an undirected edge in the input graph. The nodes are labeled 0 to n-1, where n is the number of nodes."""

    prizes = []
    """ prizes: the node prizes as a 1D float64 array."""

    costs = []
    """ costs: the edge costs as a 1D float64 array."""

    root = -1  # or a node # if we want to root somewhere specific
    if rootTiles:
        root = rootTiles[0].tile_index
    """ root: the root note for rooted PCST. For the unrooted variant, this parameter should be -1."""

    num_clusters = 1  # we want exactly one subtree...?
    """ num_clusters: the number of connected components in the output."""

    pruning = 'strong'
    if fastMode:
        pruning = 'gw'
    """ pruning: a string value indicating the pruning method. 
        Possible values are 'none', 'simple', 'gw', and 'strong' (all literals are case-insensitive). 
        'none' and 'simple' return intermediate stages of the algorithm and do not have approximation guarantees. They are only intended for development. 
        The standard GW pruning method is 'gw', which is also the default. 
        'strong' uses "strong pruning", which was introduced in [JMP00]. It has the same theoretical guarantees as GW pruning but better empirical performance in some cases. 
        For the PCSF problem, the output of strong pruning is at least as good as the output of GW pruning."""

    verbosity_level = 0
    """ verbosity_level: an integer indicating how much debug output the function should produce."""
    for tileIndex, tile in enumerate(map.tiles_by_index):
        prize = tilePrizeMatrix.raw[tileIndex]
        extraCost = tileExtraCostMatrix.raw[tileIndex]
        # if tile.army > 1 or not map.is_tile_friendly(tile):
        prize += prizeOffset

        # prizes.append(max(0.0, prize))
        if prize < 1:
            prize = 1 / (1 - prize)
        prizes.append(prize)
        if tile.isObstacle:
            continue

        if skipTiles is not None and tile in skipTiles:
            continue

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        if right and not right.isObstacle:
            if skipTiles is None or right not in skipTiles:
                edges.append([tileIndex, right.tile_index])
                cost = cutoffFactor + extraCost
                costs.append(max(0.0, cost))
            # logbook.info(f'prize {prize:.3f} for {tile}<->{right}  cost {cost:.3f}')

        if down and not down.isObstacle:
            if skipTiles is None or down not in skipTiles:
                edges.append([tileIndex, down.tile_index])
                cost = cutoffFactor + extraCost
                costs.append(max(0.0, cost))
            # logbook.info(f'prize {prize:.3f} for {tile}<->{down}  cost {cost:.3f}')

    # all rootnodes are implicitly connected by a 0 cost edge so that we can gather to all of them without them ACTUALLY being connected
    last = None
    for t in rootTiles:
        if last is not None:
            edges.append([t.tile_index, last.tile_index])
            cost = 0
            costs.append(max(0.0, cost))
        last = t

    vertices, edges = pcst_fast(edges, prizes, costs, root, num_clusters, pruning, verbosity_level)

    return vertices
