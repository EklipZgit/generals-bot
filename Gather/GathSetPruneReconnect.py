import heapq
import time
import typing

import logbook

import SearchUtils
import base.Colors
from Algorithms import MapSpanningUtils
from Algorithms.FastDisjointSet import FastDisjointTileSetSum
from Interfaces.MapMatrixInterface import EmptySet
from MapMatrix import MapMatrix
from ViewInfo import TargetStyle
from Viewer import ViewerProcessHost
from . import GatherCapturePlan, GatherSteiner, convert_contiguous_tile_tree_to_gather_capture_plan, prune_raw_connected_nodes_to_turns__bfs, GatherDebug
from Interfaces import MapMatrixInterface, TileSet
from base.client.map import MapBase
from base.client.tile import Tile


def get_gather_plan_set_prune(
        map: MapBase,
        rootTiles: typing.Set[Tile],
        valueMatrix: MapMatrixInterface[float],
        targetTurns: int,
        asPlayer: int = -1,
        negativeTiles: TileSet | None = None,
        useTrueValueGathered: bool = True,
        includeGatherPriorityAsEconValues: bool = False,
        includeCapturePriorityAsEconValues: bool = True,
        skipTiles: TileSet | None = None,
        viewInfo=None,
) -> GatherCapturePlan:
    """
    When you want to gather some specific tiles.

    Currently just shits out a steiner tree that includes ALL the requested nodes, with no pruning, along with the optimal capture path into targets.

    Does calculate gather tree values.

    @param map:
    @param rootTiles: The tile(s) that will be the destination(s) of the gather.=
    @param targetTurns: the number of turns to output
    @param asPlayer:
    @param valueMatrix: the raw value matrix used for gathering. Should include the army gathered, as well as the equivalent value of capturing enemy tiles (as compared to gathering army).
    @param negativeTiles: The negative tile set, as with any other gather. Does not bypass the capture/gather priority matrix values.
    @param useTrueValueGathered: if True, the gathered_value will be the RAW army that ends up on the target tile(s) rather than just the sum of friendly army gathered, excluding army lost traversing enemy tiles.
    @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
    @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
    @param skipTiles: tiles to skip
    @param viewInfo: if provided, debug output will be written to the view info tile zones.
    @return:
    """
    startTime = time.perf_counter()

    if asPlayer == -1:
        asPlayer = map.player_index

    bestTiles = sorted((t for t in map.players[asPlayer].tiles if t.army > 1), key=lambda t: valueMatrix.raw[t.tile_index], reverse=True)
    # allNodes = rootTiles.union(t for t in map.players[asPlayer].tiles if t.army > 1)
    allNodes = rootTiles.union(bestTiles[:targetTurns])

    steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, allNodes, weightMod=valueMatrix, searchingPlayer=asPlayer, baseWeight=1000, bannedTiles=skipTiles)

    outputTiles = _k_prune_reconnect_greedy(map, targetTurns, steinerNodes, rootTiles, valueMatrix, skipTiles=skipTiles, renderLive=True)

    usedTime = time.perf_counter() - startTime
    logbook.info(f'k_prune_reconnect_greedy complete in {usedTime:.4f}s with {len(outputTiles) - len(rootTiles)}')

    #
    # steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, rootTiles.union(tiles), weightMod=valueMatrix, searchingPlayer=asPlayer, baseWeight=1000, bannedTiles=skipTiles)
    #
    # outputTiles = steinerNodes
    # if pruneToTurns is not None:
    #     outputTiles = set(steinerNodes)
    #     prune_raw_connected_nodes_to_turns__bfs(rootTiles, outputTiles, pruneToTurns, asPlayer, valueMatrix, negativeTiles)
    #
    #     # inclTiles = set(steinerNodes)
    #     # if viewInfo:
    #     #     viewInfo.add_map_zone(inclTiles, (0, 155, 255), alpha=88)
    #     # value, outputTiles = cutesy_chatgpt_gather(map, pruneToTurns, rootTiles, asPlayer, valueMatrix, tilesToInclude=inclTiles, viewInfo=viewInfo)
    #     # if viewInfo:
    #     #     viewInfo.add_map_zone(outputTiles, (255, 255, 0), alpha=75)
    #
    plan = convert_contiguous_tile_tree_to_gather_capture_plan(
        map,
        rootTiles=rootTiles,
        tiles=outputTiles,
        negativeTiles=negativeTiles,
        searchingPlayer=asPlayer,
        priorityMatrix=valueMatrix,
        useTrueValueGathered=useTrueValueGathered,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        # viewInfo=viewInfo,
    )

    usedTime = time.perf_counter() - startTime
    logbook.info(f'get_gather_plan_set_prune complete in {usedTime:.4f}s with {plan}')

    return plan



def _k_prune_reconnect_greedy(
        map: MapBase,
        toTurns: int,
        contiguousTiles: typing.Set[Tile],
        rootTiles: typing.Set[Tile],
        initialRawValueMatrix: MapMatrixInterface[float],
        addlRequiredTiles: typing.Set[Tile] | None = None,
        skipTiles: TileSet | None = None,
        renderLive: bool = True
) -> typing.Set[Tile]:
    """
    Takes a set of tiles with specific values and greedily prunes tiles and reconnects.

    @param contiguousTiles:
    @param rootTiles:
    @param initialRawValueMatrix:
    @param skipTiles:
    @return:
    """
    start = time.perf_counter()

    liveRenderer = None
    if renderLive:
        liveRenderer = ViewerProcessHost.start_debug_live_renderer(map, startPaused=True)

    disconnectQueue = []

    greedyTemp = 10.0
    """How much to weight value in the reconnect heuristic, vs weighting shortest path"""

    overPruneGathMoreTemp = 10.0
    """How much to over-prune and then try a re-gather"""

    liveValueMatrix = initialRawValueMatrix.copy()
    # liveValueMatrix = MapMatrix.get_min_normalized_via_sum(initialRawValueMatrix, normalizedMinimum=1.0)

    disconnectCounts: MapMatrixInterface[int] = MapMatrix(map, 0)

    pruneTo = toTurns + len(rootTiles)
    curSet = contiguousTiles.union(rootTiles)

    iteration = 0
    pruneIters = 0
    prunedThisIter: typing.Set[Tile] = set()
    nextDisconnect: Tile

    # Determine the bare minimum that we can do with no prioritization at all, given the required tiles.
    requiredTiles = rootTiles
    if addlRequiredTiles:
        requiredTiles = rootTiles.union(addlRequiredTiles)
    banned = skipTiles
    if banned is None:
        banned = EmptySet()
    minIncluded, unconnectable, costPer = MapSpanningUtils.get_spanning_tree_set_from_tile_lists_with_cost_per(map, requiredTiles, banned)
    bareMinTurns = len(minIncluded)

    excessTiles = len(contiguousTiles.union(requiredTiles)) - toTurns
    prunePerIter = 5
    if excessTiles > toTurns * 0.5:
        prunePerIter = excessTiles // 10
    """How many tiles to prune per reconnect"""

    liveValRenderMatrix = None
    if liveRenderer:
        liveRenderer.view_info.add_info_line(f'MIN INCLUDED {bareMinTurns} {costPer}')
        liveRenderer.view_info.infoText = f'MIN INCLUDED {bareMinTurns} {costPer}'
        liveRenderer.view_info.add_map_zone(minIncluded, base.Colors.PURPLE, alpha=150)
        for t, v in costPer.items():
            liveRenderer.view_info.topRightGridText.raw[t.tile_index] = f'cp{v}'

        for t in map.get_all_tiles():
            liveRenderer.view_info.bottomLeftGridText.raw[t.tile_index] = f'{liveValueMatrix.raw[t.tile_index]:.1f}'

        liveRenderer.trigger_update(clearViewInfoAfter=False)

        liveValRenderMatrix = liveRenderer.view_info.bottomLeftGridText.copy()

    for t in contiguousTiles:
        if t in rootTiles:
            continue

        heapq.heappush(disconnectQueue, (liveValueMatrix.raw[t.tile_index], t))

    closestConnected = None

    while True:
        iterStart = time.perf_counter()
        iteration += 1

        if liveRenderer:
            liveRenderer.view_info.clear_for_next_turn()

        # for i in range(prunePerIter):
        while len(curSet) > toTurns - prunePerIter:
            if not disconnectQueue:
                break

            # while disconnectQueue:
            prio, nextDisconnect = heapq.heappop(disconnectQueue)
            pruneIters += 1
            prunedThisIter.add(nextDisconnect)
            disconnectCounts.raw[nextDisconnect.tile_index] += 1

            if liveRenderer:
                liveRenderer.view_info.evaluatedGrid[nextDisconnect.x][nextDisconnect.y] = 100
                liveRenderer.view_info.midRightGridText.raw[nextDisconnect.tile_index] = f'{prio:.3f}'.lstrip('0')
                # liveRenderer.view_info.midRightGridText.raw[nextDisconnect.tile_index] = f'I{val:.1f}'
            curSet.discard(nextDisconnect)

        if liveRenderer:
            liveRenderer.view_info.add_stats_line(f'X = {len(prunedThisIter)} prunedThisIter {" | ".join([str(t) for t in prunedThisIter])}')

        # if liveRenderer:
        #     liveRenderer.view_info.add_stats_line(f'RED = {len(curSet)} iteration start tiles (out of {pruneTo})')
        #     liveRenderer.view_info.add_map_zone(curSet.copy(), base.Colors.P_DARK_RED, alpha=60)

        if liveRenderer:
            liveRenderer.view_info.add_stats_line(f'RED = {len(curSet)} reconnect start tiles (out of {pruneTo})')
            liveRenderer.view_info.add_map_zone(curSet.copy(), base.Colors.P_DARK_RED, alpha=120)

        newTiles, closestConnected = _reconnect(
            map,
            pruneTo,
            curSet,
            rootTiles,
            prunedThisIter,
            skipTiles,
            initialRawValueMatrix,
            bareMinTurns)
        curSet = closestConnected

        if liveRenderer:
            liveRenderer.view_info.add_stats_line(f'GREEN Circle = {len(newTiles)} reconnected this iter {" | ".join([str(t) for t in newTiles])}')
        for tile in newTiles:
            discCount = disconnectCounts.raw[tile.tile_index]
            val = liveValueMatrix.raw[tile.tile_index]
            if discCount > 0:
                # val *= 1.0 + 0.05 * (discCount)
                # val += 1
                val += 0.2 * discCount
                if liveRenderer:
                    liveValRenderMatrix.raw[tile.tile_index] = f'I{val:.1f}'

            curSet.add(tile)

            if liveRenderer:
                liveRenderer.view_info.add_targeted_tile(tile, TargetStyle.GREEN, radiusReduction=8)

            heapq.heappush(disconnectQueue, (val, tile))

        if len(closestConnected) == pruneTo:
            break

        prunedThisIter.clear()
        if liveRenderer:
            liveRenderer.view_info.bottomLeftGridText = liveValRenderMatrix.copy()
            liveRenderer.view_info.topRightGridText = disconnectCounts.copy()
            liveRenderer.trigger_update(clearViewInfoAfter=False)
            for t in map.get_all_tiles():
                existing = liveValRenderMatrix.raw[t.tile_index]
                if existing:
                    existing = existing.lstrip('I')
                    liveValRenderMatrix.raw[t.tile_index] = existing
            liveRenderer.view_info.add_info_line(f'iter {iteration} (pruneIter {pruneIters}), {len(curSet)} left, {len(newTiles)} added')

    msg = f'k-prune ended after iter {iteration} with {len(closestConnected)} closestConnected, greedyTemp {greedyTemp:.2f}, overPruneGathMoreTemp {overPruneGathMoreTemp:.2f}, prunePerIter {prunePerIter}'
    logbook.info(msg)
    if liveRenderer:
        liveRenderer.view_info.add_map_zone(closestConnected, base.Colors.LIGHT_BLUE, alpha=160)
        liveRenderer.send_final_result_and_close(msg)

    return closestConnected


# def get_max_gather_spanning_tree_set_from_tile_lists(
#         map: MapBase,
#         requiredTiles: typing.List[Tile],
#         skipTiles: TileSet,
#         negativeTiles: TileSet | None = None,
#         maxTurns: int = 1000,
#         gatherPrioMatrix: MapMatrixInterface[float] | None = None,
#         searchingPlayer: int = -1,
#         # gatherMult: float = 1.0,
#         # oneOfTiles: typing.Iterable[Tile] | None = None,
# ) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile]]:

def _reconnect(
        map: MapBase,
        pruneTo: int,
        curSet: typing.Set[Tile],
        rootTiles: typing.Set[Tile],
        justDisconnectedTiles: typing.Set[Tile],
        skipTiles: TileSet | None,
        valueMatrix: MapMatrixInterface[float],
        bareMinTurns: int,
        # costPer: typing.Dict[Tile, int]
) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile]]:
    """
    Returns set of all those connected, as well as the set of any required that couldn't be connected to the first required tile.
    Prioritizes gathering army, optionally modifying the gather value with the value from the prio matrix

    @param map:
    @param pruneTo: limit the number of turns we can potentially use. This isn't guaranteed and may cause the gather to not connect all nodes or something?
    @param curSet: the (possibly disconnected) tiles currently have in the set, to begin reconnection from.
    @param skipTiles:
    @param rootTiles:
    @param justDisconnectedTiles: tiles that should be punished
    @param valueMatrix: gather prio values.
    @return:
    """

    excessTurns = pruneTo - bareMinTurns

    start = time.perf_counter()
    if GatherDebug.USE_DEBUG_LOGGING:
        logbook.info('starting _reconnect')
    # includedSet = set()

    forest = FastDisjointTileSetSum(valueMatrix, curSet)

    # missingIncluded = curSet.copy()
    newTiles: typing.Set[Tile] = set()

    negativeTiles = None

    # if justDisconnectedTiles is None:
    #     justDisconnectedTiles = missingIncluded
    # else:
    #     # missingIncluded tiles shouldn't have a 'gather value', treat them as negative. Our goal is finding the best tiles in between all the included, not the highest value included connection point
    #     justDisconnectedTiles = justDisconnectedTiles.copy()
    #     justDisconnectedTiles.update(missingIncluded)

    # expectedMinRemaining = 0
    # for tile in missingIncluded:
    #     expectedMinRemaining += costPer.get(tile, 0)

    # logbook.info(f'bareMinTurns {bareMinTurns}, excessTurns {excessTurns}, expectedMinRemaining {expectedMinRemaining}')
    logbook.info(f'bareMinTurns {bareMinTurns}, excessTurns {excessTurns}')

    # # skipTiles.difference_update(requiredTiles)
    # for req in requiredTiles:
    #     skipTiles.discard(req)

    # if len(requiredTiles) == 0:
    #     return includedSet, missingIncluded

    # usefulStartSet = {t: baseTuple for t in includedSet}
    usefulStartSet = dict()

    if GatherDebug.USE_DEBUG_LOGGING:
        logbook.info('Completed sets setup')

    someRoot = None
    for root in rootTiles:
        someRoot = root
        _include_all_adj_required_set_forest(root, forest, newTiles, usefulStartSet, missingIncluded, valueMatrix, lastTile=someRoot, someRoot=someRoot)
        # _include_all_adj_required_set_gather(root, , newTiles, usefulStartSet, missingIncluded, valueMatrix)

    if GatherDebug.USE_DEBUG_LOGGING:
        logbook.info('Completed root _include_all_adj_required')

    # def findFunc(t: Tile, prio: typing.Tuple) -> bool:
    #     return t in missingIncluded

    def findFunc(t: Tile, prio: typing.Tuple) -> bool:
        return t in forest and not forest.connected(t, someRoot)

    def valueFunc(t: Tile, prio: typing.Tuple) -> typing.Tuple | None:
        if t not in missingIncluded:
            return None

        missingVal = disjoin

        (
            prio,
            dist,
            negGatherPoints,
        ) = prio

        return negGatherPoints + t

    iteration = 0
    # while len(missingIncluded) > 0:
    while len(includedSet) < pruneTo:
        # iter += 1
        if GatherDebug.USE_DEBUG_LOGGING:
            logbook.info(f'missingIncluded iter {iteration}')

        # expectedMinRemaining = 0
        # closestDist = pruneTo
        # closest = None
        # for tile in missingIncluded:
        #     # TODO
        #     # cost = costPer.get(tile, 0)
        #     cost = 1
        #     expectedMinRemaining += cost
        #     if 1 < cost < closestDist:
        #         closestDist = cost
        #         closest = tile
        #
        # costSoFar = len(includedSet)
        # excessTurnsLeft = pruneTo - (costSoFar + expectedMinRemaining)
        #
        # logbook.info(f'  costSoFar {costSoFar}, expectedMinRemaining {expectedMinRemaining} (out of max {pruneTo}, min {bareMinTurns}), closestDist {closestDist}, excessTurnsLeft {excessTurnsLeft}')

        excessTurnsLeft = pruneTo - len(includedSet)
        logbook.info(f'  included so far {len(includedSet)} (missing {len(missingIncluded)}, (out of max {pruneTo}, min {bareMinTurns}), excessTurnsLeft {excessTurnsLeft}')

        def prioFunc(tile: Tile, prioObj: typing.Tuple):
            (
                prio,
                dist,
                negGatherPoints,
            ) = prioObj

            # if tile not in justDisconnectedTiles:
            negGatherPoints -= valueMatrix.raw[tile.tile_index]

            # TODO ASTARIFY THIS?
            # newCost = dist + 1
            # costWeight = excessTurnsLeft - (dist + 1)
            # # tile.coords in [(8, 6)]
            # if costWeight > 0 and negGatherPoints < 0:
            #     excessCostRat = costWeight / excessTurnsLeft
            #     """Ratio of excess turns left over"""
            #     costDivisor = (0 - negGatherPoints) * excessCostRat
            #     newCost -= costWeight * excessCostRat  #- 1/costDivisor
            #     # newCost -= excessTurnsLeft * (1 / excessCostRat)

            newDist = dist + 1
            newPrio = negGatherPoints / newDist if negGatherPoints < 0 else negGatherPoints * newDist
            return (
                newPrio,
                newDist,
                negGatherPoints,
            )

        # path = SearchUtils.breadth_first_dynamic(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noLog=not GatherDebug.USE_DEBUG_LOGGING)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        path = SearchUtils.breadth_first_dynamic_max(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noLog=not GatherDebug.USE_DEBUG_LOGGING)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if path is None:
            if GatherDebug.USE_DEBUG_LOGGING:
                logbook.info(f'  Path NONE! Performing altBanned set')
            # altBanned = skipTiles.copy()
            # altBanned.update([t for t in map.reachableTiles if t.isMountain])
#             path = SearchUtils.breadth_first_dynamic(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noNeutralCities=False, noLog=not GatherDebug.USE_DEBUG_LOGGING)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            path = SearchUtils.breadth_first_dynamic_max(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noNeutralCities=False, noLog=not GatherDebug.USE_DEBUG_LOGGING)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if path is None:
                if GatherDebug.USE_DEBUG_LOGGING:
                    logbook.info(f'  No AltPath, breaking early with {len(missingIncluded)} left missing')
                break
                # raise AssertionError(f'No MST building path found...? \r\nFrom {includedSet} \r\nto {missingIncluded}')
            # else:
            #     if GatherDebug.USE_DEBUG_LOGGING:
            #         logbook.info(f'  AltPath len {path.length}')
        # else:
        #     if GatherDebug.USE_DEBUG_LOGGING:
        #         logbook.info(f'  Path len {path.length}')

        # logbook.info(f'    found {path.start.tile}->{path.tail.tile} len {path.length} (closest {closest} len {closestDist}) {path}')
        logbook.info(f'    found {path.start.tile}->{path.tail.tile} len {path.length}')

        lastTile: Tile = someRoot

        for tile in path.tileList:
            _include_all_adj_required_set_forest(tile, forest, newTiles, usefulStartSet, missingIncluded, valueMatrix, lastTile, someRoot) # , lastTile
#             _include_all_adj_required_set_gather(tile, includedSet, newTiles, usefulStartSet, missingIncluded, valueMatrix) # , lastTile
            lastTile = tile

    if GatherDebug.USE_DEBUG_LOGGING:
        logbook.info(f'_reconnect completed in {time.perf_counter() - start:.5f}s with {len(missingIncluded)} missing after {iteration} path iterations')

    return newTiles, includedSet


def _include_all_adj_required_set_gather(node: Tile, includedSet: TileSet, newTiles: typing.Set[Tile], usefulStartSet: TileSet, missingIncludedSet: TileSet, valueMatrix: MapMatrixInterface[float]):
    """
    Inlcudes all adjacent required tiles int the

    @param node:
    @param includedSet:
    @param newTiles: set of tiles to update with tiles that werent previously in missing or included sets.
    @param usefulStartSet:
    @param missingIncludedSet:
    @param valueMatrix:
    @return:
    """
    q = [node]

    while q:
        tile = q.pop()

        # if fromNode is not None:
        #     node.adjacents.append(fromNode)
        #     fromNode.adjacents.append(node)

        if tile in includedSet:
            continue

        if tile not in missingIncludedSet:
            newTiles.add(tile)

        includedSet.add(tile)
        # usefulStartSet.add(tile)
        # usefulStartSet[tile] = ((-100000, 0, 0), 0)
        usefulStartSet[tile] = ((-valueMatrix.raw[tile.tile_index], 0, 0), 0)

        missingIncludedSet.discard(tile)

        for movable in tile.movable:
            if movable not in missingIncludedSet:
                continue

            # nextNode = graph.nodes[movable]
            # if nextNode is None:
            #     nextNode = TileNode(movable)
            #     graph.nodes[movable] = nextNode
            #
            # else:
            q.append(movable)

    # logbook.info(f'_include_all_adj_required, iter {iter} included {included}')

def _include_all_adj_required_set_forest(node: Tile, includedSet: FastDisjointTileSetSum, newTiles: typing.Set[Tile], usefulStartSet: TileSet, missingIncludedSet: TileSet, valueMatrix: MapMatrixInterface[float], lastTile: Tile, someRoot: Tile):
    """
    Inlcudes all adjacent required tiles int the

    @param node:
    @param includedSet:
    @param newTiles: set of tiles to update with tiles that werent previously in missing or included sets.
    @param usefulStartSet:
    @param missingIncludedSet:
    @param valueMatrix:
    @return:
    """
    q = [node]

    while q:
        tile = q.pop()

        # if not includedSet.merge(tile, lastTile):
        if tile in includedSet:
            continue

        if tile not in missingIncludedSet:
            newTiles.add(tile)

        includedSet.merge(tile, someRoot)

        usefulStartSet[tile] = ((-valueMatrix.raw[tile.tile_index], 0, 0), 0)

        missingIncludedSet.discard(tile)

        for movable in tile.movable:
            if movable not in missingIncludedSet:
                continue

            q.append(movable)

        lastTile = tile
