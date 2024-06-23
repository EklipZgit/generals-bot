import time
import typing

import logbook

from .GatherCapturePlan import *
from .GatherDebug import USE_DEBUG_LOGGING, USE_DEBUG_ASSERTS, assertConnected
from Interfaces import TileSet, MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile
import heapq


# TODO THIS IS CHATGPT CODE FROM https://chatgpt.com/g/g-3w1rEXGE0-web-browser/c/4fe68032-e88c-4057-a329-d37a42df465b
def find_exact_best_steiner_gather_slow(
        map: MapBase,
        targetTurns: int,
        rootTiles: typing.Set[Tile],
        searchingPlayer: int,
        valueMatrix: MapMatrixInterface[float],
        tilesToInclude: typing.Set[Tile] | None = None,
        negativeTiles: TileSet | None = None,
        viewInfo: ViewInfo | None = None,
) -> typing.Tuple[float, typing.Set[Tile]]:
    if tilesToInclude is None:
        tilesToInclude = map.pathable_tiles
    else:
        # if DebugHelper.IS_DEBUGGING:
        if USE_DEBUG_ASSERTS:
            missing = rootTiles.difference(tilesToInclude)
            if missing:
                raise Exception(f'Bruh rootTiles still `need to be in tilesToInclude. {" | ".join([str(t) for t in missing])} missing.')

    """
    Psuedocode:
    N = targetTurns
    K = best subset
    
    Start with the set of all gatherable tiles.
    Connect them through enemy/neutral land.
    for every tile in the set check if removing it disconnects the graph, and prune the disconnected portion of the graph.
        
    
    """

    if USE_DEBUG_ASSERTS:
        assertConnected(tilesToInclude.union(rootTiles))

    useFullSearch = len(tilesToInclude) < 100
    useFullSearch = False

    rootCount = len(rootTiles)
    nodeCount = targetTurns + rootCount

    start = time.perf_counter()

    # DP table to store the best values for k nodes starting from a given node
    dpValues: MapMatrixInterface[typing.List[float]] = MapMatrix(map)
    dpBestSets: MapMatrixInterface[typing.List[typing.Set[Tile] | None]] = MapMatrix(map)
    dpSize = nodeCount + 1
    for tile in tilesToInclude:
        dpValues.raw[tile.tile_index] = [0.0] * dpSize
        dpBestSets.raw[tile.tile_index] = [None] * dpSize

    rootSet = set(rootTiles)
    # if rootCount > nodeCount:
    #     raise Exception("Error: K is less than the number of root nodes")

    # Priority queue to explore nodes by value, max-heap
    pq = []

    # rootSum = sum(valueMatrix.raw[tile.tile_index] for tile in rootTiles)
    for tile in rootTiles:
        valueMatrix.raw[tile.tile_index] += 1000
        # dpValues.raw[tile.tile_index][rootCount] = rootSum
        dpValues.raw[tile.tile_index][rootCount] = 1000
        dpBestSets.raw[tile.tile_index][rootCount] = rootSet
        dpValues.raw[tile.tile_index][1] = 1000
        dpBestSets.raw[tile.tile_index][1] = {tile}
        # force rootnode eval first (?)
        heapq.heappush(pq, (-100000000, tile))

    for tile in tilesToInclude:
        if tile in rootTiles:
            continue
        value = valueMatrix.raw[tile.tile_index]
        # if useFullSearch:
        #     heapq.heappush(pq, (value, tile))
        # else:
        heapq.heappush(pq, (-value, tile))
        # Initialize the DP table with single node values
        dpValues.raw[tile.tile_index][1] = value
        dpBestSets.raw[tile.tile_index][1] = {tile}

    # Perform the DP and priority search
    maxValue = 0
    maxSet = None
    visited: MapMatrixSet = MapMatrixSet(map)
    visCount = 0
    internalQueue: typing.List[typing.Tuple[float, int, Tile]] = []
    # internalQueue: typing.Deque[typing.Tuple[Tile, int]] = deque()
    # internalQueue: typing.Deque[typing.Tuple[Tile, int, typing.Set[Tile]]] = deque()

    # internalVisited = set()

    # TODO connected adjacency prunable structure for any searches like this where we have a set of good tiles and visit tiles permanently pulling them out of the available pool. Would allow us to not skip visited neighbors in a loop constantly?
    #  MapMatrix[Set[Tile]] and visiting something removes it from the set? Hell the same structure could also track the visitedness of a node at the same time, too so we have just one structure for both is visited and tracking neighbors?

    # for tile in tilesToInclude:
    while pq:  #  and visCount < nodeCount    chatgpt did not have this, and rightly so, this outer loop isn't whats choosing the nodes in the set...
        value, tile = heapq.heappop(pq)
        value = -value
        # No reason to check visited; we dont ever add anything extra to the outer queue. It is literally just for looping the tiles from greatest bonus to worst bonus.
        # if visited.raw[tile.tile_index]:
        #     continue

        # TODO this should be priorityQueue 99.9% sure. We are DFSing randomly through the rest of the map tiles to explore here otherwise.
        if useFullSearch:
            heapq.heappush(internalQueue, (-1, 0.0, tile))
        else:
            heapq.heappush(internalQueue, (1, 0.0, tile))
        # internalQueue.append((tile, 1))
        # internalQueue.append((tile, 1, set()))
        # Use BFS to explore neighbors and update DP table
        # internalVisited.clear()
        while internalQueue:
            count, prio, internalTile = heapq.heappop(internalQueue)
            if useFullSearch:
                count = -count
            # count = -count
            # internalTile, count, internalVisited = internalQueue.popleft()
            # internalTile, count = internalQueue.popleft()
            if count >= nodeCount:
                continue

            sourceVal = dpValues.raw[internalTile.tile_index][count]
            curSet = dpBestSets.raw[internalTile.tile_index][count]

            for neighbor in internalTile.movable:
                nNodeDp = dpValues.raw[neighbor.tile_index]
                if nNodeDp is None:  #
                    continue

                # if curSet is None:
                #     raise Exception(f'curSet null at depth {count} for {internalTile} ???')

                if neighbor in curSet:
                    continue

                # if visited.raw[neighbor.tile_index]:
                #     continue

            #     openSet.add(neighbor)
            #
            # for neighbor in openSet:
                if visited.raw[neighbor.tile_index]:
                    continue

                nNodeDp = dpValues.raw[neighbor.tile_index]
                nVal = valueMatrix.raw[neighbor.tile_index]
                newValue = sourceVal + nVal
                nextCount = count + 1
                if newValue > nNodeDp[nextCount]:
                    nNodeDp[nextCount] = newValue

                    nextSet = curSet.copy()
                    nextSet.add(neighbor)
                    dpBestSets.raw[neighbor.tile_index][nextCount] = nextSet

                    # internalQueue.append((neighbor, nextCount))
                    if useFullSearch:
                        heapq.heappush(internalQueue, (-nextCount, nVal, neighbor))
                    else:
                        heapq.heappush(internalQueue, (nextCount, -nVal, neighbor))

        visited.raw[tile.tile_index] = True
        visCount += 1

        if viewInfo:
            viewInfo.bottomMidRightGridText.raw[tile.tile_index] = f'v{visCount}'

    timeTaken = time.perf_counter() - start

    for tile in rootTiles:
        valueMatrix.raw[tile.tile_index] -= 1000

    for tile in tilesToInclude:
        # Update the maximum value found for exactly K nodes
        tileDpVals = dpValues.raw[tile.tile_index]
        maxIdx = 0
        tileMax = -100
        thisSet = None
        for i in range(nodeCount - 2, nodeCount + 1):
            val = tileDpVals[i]
            thisSet = dpBestSets.raw[tile.tile_index][i]

            if val > tileMax:
                tileMax = val
                maxIdx = i

                if viewInfo:
                    viewInfo.bottomRightGridText.raw[tile.tile_index] = f'{tileMax:.1f}'
                    viewInfo.midRightGridText.raw[tile.tile_index] = f'{valueMatrix.raw[tile.tile_index]:.1f}'
                    viewInfo.bottomLeftGridText.raw[tile.tile_index] = f'i{maxIdx}'
                    if thisSet:
                        viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'c{len(thisSet)}'

        if thisSet is None:
            logbook.info(f'skipping tile {tile} because none thisSet??')
            continue

        containsRoot = rootTiles.issubset(thisSet)
        if not containsRoot:
            logbook.info(f'skipping tile {tile} because fails to contain the root')
            continue

        if tileMax > maxValue:
            newMaxSet = dpBestSets.raw[tile.tile_index][maxIdx]
            logbook.info(f'found new max {tileMax:.2f} at {tile} (index {maxIdx})')
            logbook.info(f'     its set len {len(newMaxSet)}: {newMaxSet}')
            maxValue = tileMax
            maxSet = newMaxSet

        # # Update the maximum value found for exactly K nodes
        # tileDpVals = dpValues.raw[tile.tile_index]
        # maxIdx = 0
        # tileMax = -100
        # for index in range(dpSize):
        #     val = tileDpVals[index]
        #     if val > tileMax:
        #         tileMax = val
        #         maxIdx = index
        #
        # if tileMax > maxValue:
        #     newMaxSet = dpBestSets.raw[tile.tile_index][maxIdx]
        #     logbook.info(f'found new max {tileMax:.2f} at {tile} (index {maxIdx})')
        #     logbook.info(f'     its set len {len(newMaxSet)}: {newMaxSet}')
        #     maxValue = tileMax
        #     maxSet = newMaxSet
        #
        # if viewInfo:
        #     viewInfo.bottomRightGridText.raw[tile.tile_index] = f'{tileMax:.1f}'
        #     viewInfo.midRightGridText.raw[tile.tile_index] = f'{valueMatrix.raw[tile.tile_index]:.1f}'
        #     viewInfo.bottomLeftGridText.raw[tile.tile_index] = f'i{maxIdx}'
        #     thisSet = dpBestSets.raw[tile.tile_index][maxIdx]
        #     if thisSet:
        #         viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'c{len(thisSet)}'

    for tile in rootTiles:
        tileDpVals = dpValues.raw[tile.tile_index]
        tileDpSets = dpBestSets.raw[tile.tile_index]
        logbook.info(f'rootTile {tile}:')
        for idx in range(dpSize):
            value = tileDpVals[idx]
            bestSet = tileDpSets[idx]

            tilesInf = "NONE"
            if bestSet:
                tilesInf = f'{len(bestSet)}  {" | ".join([str(t) for t in bestSet])}'

            logbook.info(f'    {idx} val {value:.2f}  tiles {tilesInf}')

    logbook.info(f'Crazy chatGpt fullSearch {useFullSearch} dynamic programming gather in iter {timeTaken:.5f}s full {time.perf_counter() - start:.5f}s with {len(maxSet)} tiles and value {maxValue}')
    logbook.info(f'Crazy chatGpt output tiles: {maxSet}')
    return maxValue, maxSet



# TODO THIS IS CHATGPT CODE FROM https://chatgpt.com/g/g-3w1rEXGE0-web-browser/c/4fe68032-e88c-4057-a329-d37a42df465b
def cutesy_chatgpt_gather_stack(
        map: MapBase,
        targetTurns: int,
        rootTiles: typing.Set[Tile],
        searchingPlayer: int,
        valueMatrix: MapMatrixInterface[float],
        tilesToInclude: typing.Set[Tile] | None = None,
        negativeTiles: TileSet | None = None,
        viewInfo: ViewInfo | None = None,
) -> typing.Tuple[float, typing.Set[Tile]]:
    if tilesToInclude is None:
        tilesToInclude = map.pathable_tiles
    else:
        # if DebugHelper.IS_DEBUGGING:
        if USE_DEBUG_ASSERTS:
            missing = rootTiles.difference(tilesToInclude)
            if missing:
                raise Exception(f'Bruh rootTiles still `need to be in tilesToInclude. {" | ".join([str(t) for t in missing])} missing.')

    if USE_DEBUG_ASSERTS:
        assertConnected(tilesToInclude.union(rootTiles))

    useFullSearch = len(tilesToInclude) < 100
    useFullSearch = False

    rootCount = len(rootTiles)
    nodeCount = targetTurns + rootCount

    start = time.perf_counter()

    # DP table to store the best values for k nodes starting from a given node
    dpValues: MapMatrixInterface[typing.List[float]] = MapMatrix(map)
    dpBestSets: MapMatrixInterface[typing.List[typing.Set[Tile] | None]] = MapMatrix(map)
    dpSize = nodeCount + 1
    for tile in tilesToInclude:
        dpValues.raw[tile.tile_index] = [0.0] * dpSize
        dpBestSets.raw[tile.tile_index] = [None] * dpSize

    rootSet = set(rootTiles)
    # if rootCount > nodeCount:
    #     raise Exception("Error: K is less than the number of root nodes")

    # Priority queue to explore nodes by value, max-heap
    pq = []

    # rootSum = sum(valueMatrix.raw[tile.tile_index] for tile in rootTiles)
    for tile in rootTiles:
        valueMatrix.raw[tile.tile_index] += 1000
        # dpValues.raw[tile.tile_index][rootCount] = rootSum
        dpValues.raw[tile.tile_index][rootCount] = 1000
        dpBestSets.raw[tile.tile_index][rootCount] = rootSet
        # dpValues.raw[tile.tile_index][1] = 0
        # dpBestSets.raw[tile.tile_index][1] = {tile}
        # force rootnode eval first (?)
        heapq.heappush(pq, (-100000000, tile))

    for tile in tilesToInclude:
        if tile in rootTiles:
            continue
        value = valueMatrix.raw[tile.tile_index]
        # if useFullSearch:
        #     heapq.heappush(pq, (value, tile))
        # else:
        heapq.heappush(pq, (-value, tile))
        # Initialize the DP table with single node values
        dpValues.raw[tile.tile_index][1] = value
        dpBestSets.raw[tile.tile_index][1] = {tile}

    # Perform the DP and priority search
    maxValue = 0
    maxSet = None
    visited: MapMatrixSet = MapMatrixSet(map)
    visCount = 0
    internalQueue: typing.List[typing.Tuple[int, float, Tile]] = []
    # internalQueue: typing.Deque[typing.Tuple[Tile, int]] = deque()
    # internalQueue: typing.Deque[typing.Tuple[Tile, int, typing.Set[Tile]]] = deque()

    # internalVisited = set()

    # TODO connected adjacency prunable structure for any searches like this where we have a set of good tiles and visit tiles permanently pulling them out of the available pool. Would allow us to not skip visited neighbors in a loop constantly?
    #  MapMatrix[Set[Tile]] and visiting something removes it from the set? Hell the same structure could also track the visitedness of a node at the same time, too so we have just one structure for both is visited and tracking neighbors?

    # for tile in tilesToInclude:
    while pq:  #  and visCount < nodeCount    chatgpt did not have this, and rightly so, this outer loop isn't whats choosing the nodes in the set...
        value, tile = heapq.heappop(pq)
        value = -value
        # No reason to check visited; we dont ever add anything extra to the outer queue. It is literally just for looping the tiles from greatest bonus to worst bonus.
        # if visited.raw[tile.tile_index]:
        #     continue

        # TODO this should be priorityQueue 99.9% sure. We are DFSing randomly through the rest of the map tiles to explore here otherwise.
        # if useFullSearch:
        #     heapq.heappush(internalQueue, (-1, 0.0, tile, set()))
        # else:
        #     heapq.heappush(internalQueue, (1, 0.0, tile, set()))

        # STACK
        internalQueue.append((1, 0.0, tile))

        # internalQueue.append((tile, 1))
        # internalQueue.append((tile, 1, set()))
        # Use BFS to explore neighbors and update DP table
        # internalVisited.clear()
        while internalQueue:
            # count, prio, internalTile, openStack = heapq.heappop(internalQueue)
            # if useFullSearch:
            #     count = -count

            # STACK
            count, prio, internalTile = internalQueue.pop()

            # internalTile, count, internalVisited = internalQueue.popleft()
            # internalTile, count = internalQueue.popleft()
            if count >= nodeCount:
                continue

            sourceVal = dpValues.raw[internalTile.tile_index][count]
            curSet = dpBestSets.raw[internalTile.tile_index][count]

            for neighbor in internalTile.movable:
                nNodeDp = dpValues.raw[neighbor.tile_index]
                if nNodeDp is None:  #
                    continue

                if visited.raw[neighbor.tile_index]:
                    continue

                nNodeDp = dpValues.raw[neighbor.tile_index]
                nVal = valueMatrix.raw[neighbor.tile_index]

                if neighbor in curSet:
                    continue
                newValue = sourceVal + nVal
                nextCount = count + 1
                if newValue > nNodeDp[nextCount]:
                    nNodeDp[nextCount] = newValue

                    nextSet = curSet.copy()
                    nextSet.add(neighbor)
                    # nextOpenStack = openStack.copy()
                    dpBestSets.raw[neighbor.tile_index][nextCount] = nextSet

                    # internalQueue.append((neighbor, nextCount))
                    # if useFullSearch:
                    #     heapq.heappush(internalQueue, (-nextCount, nVal, neighbor, nextOpenStack))
                    # else:
                    #     heapq.heappush(internalQueue, (nextCount, -nVal, neighbor, nextOpenStack))
                    internalQueue.append((nextCount, nVal, neighbor))

        visited.raw[tile.tile_index] = True
        visCount += 1

        if viewInfo:
            viewInfo.bottomMidRightGridText.raw[tile.tile_index] = f'v{visCount}'

    timeTaken = time.perf_counter() - start

    for tile in tilesToInclude:
        # Update the maximum value found for exactly K nodes
        tileDpVals = dpValues.raw[tile.tile_index]
        maxIdx = 0
        tileMax = -100
        thisSet = None
        for i in range(nodeCount - 2, nodeCount + 1):
            val = tileDpVals[i]
            thisSet = dpBestSets.raw[tile.tile_index][i]

            if val > tileMax:
                tileMax = val
                maxIdx = i

                if viewInfo:
                    viewInfo.bottomRightGridText.raw[tile.tile_index] = f'{tileMax:.1f}'
                    viewInfo.midRightGridText.raw[tile.tile_index] = f'{valueMatrix.raw[tile.tile_index]:.1f}'
                    viewInfo.bottomLeftGridText.raw[tile.tile_index] = f'i{maxIdx}'
                    if thisSet:
                        viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'c{len(thisSet)}'

        if thisSet is None:
            logbook.info(f'skipping tile {tile} because none thisSet??')
            continue

        containsRoot = rootTiles.issubset(thisSet)
        if not containsRoot:
            logbook.info(f'skipping tile {tile} because fails to contain the root')
            continue

        if tileMax > maxValue:
            newMaxSet = dpBestSets.raw[tile.tile_index][maxIdx]
            logbook.info(f'found new max {tileMax:.2f} at {tile} (index {maxIdx})')
            logbook.info(f'     its set len {len(newMaxSet)}: {newMaxSet}')
            maxValue = tileMax
            maxSet = newMaxSet

        # # Update the maximum value found for exactly K nodes
        # tileDpVals = dpValues.raw[tile.tile_index]
        # maxIdx = 0
        # tileMax = -100
        # for index in range(dpSize):
        #     val = tileDpVals[index]
        #     if val > tileMax:
        #         tileMax = val
        #         maxIdx = index
        #
        # if tileMax > maxValue:
        #     newMaxSet = dpBestSets.raw[tile.tile_index][maxIdx]
        #     logbook.info(f'found new max {tileMax:.2f} at {tile} (index {maxIdx})')
        #     logbook.info(f'     its set len {len(newMaxSet)}: {newMaxSet}')
        #     maxValue = tileMax
        #     maxSet = newMaxSet
        #
        # if viewInfo:
        #     viewInfo.bottomRightGridText.raw[tile.tile_index] = f'{tileMax:.1f}'
        #     viewInfo.midRightGridText.raw[tile.tile_index] = f'{valueMatrix.raw[tile.tile_index]:.1f}'
        #     viewInfo.bottomLeftGridText.raw[tile.tile_index] = f'i{maxIdx}'
        #     thisSet = dpBestSets.raw[tile.tile_index][maxIdx]
        #     if thisSet:
        #         viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'c{len(thisSet)}'

    for tile in rootTiles:
        tileDpVals = dpValues.raw[tile.tile_index]
        tileDpSets = dpBestSets.raw[tile.tile_index]
        logbook.info(f'rootTile {tile}:')
        for idx in range(dpSize):
            value = tileDpVals[idx]
            bestSet = tileDpSets[idx]

            tilesInf = "NONE"
            if bestSet:
                tilesInf = f'{len(bestSet)}  {" | ".join([str(t) for t in bestSet])}'

            logbook.info(f'    {idx} val {value:.2f}  tiles {tilesInf}')

    logbook.info(f'Crazy chatGpt fullSearch {useFullSearch} dynamic programming gather in iter {timeTaken:.5f}s full {time.perf_counter() - start:.5f}s with {len(maxSet)} tiles and value {maxValue}')
    logbook.info(f'Crazy chatGpt output tiles: {maxSet}')
    return maxValue, maxSet
