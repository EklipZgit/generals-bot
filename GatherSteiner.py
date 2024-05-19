import time
import typing

import networkx as nx

import logbook
import numpy as np
from pcst_fast import pcst_fast

from MapMatrix import MapMatrixInterface, MapMatrixSet
from base.client.map import MapBase, Tile


def build_network_x_steiner_tree(
        map: MapBase,
        includingTiles: typing.Iterable[Tile],
        searchingPlayer=-2,
        weightMod: MapMatrixInterface[float] | None = None,
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None,
        # faster: bool = False
) -> typing.List[Tile]:
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
    includedNodes = [map.get_tile_by_tile_index(n) for n in steinerTree.nodes]

    nextTime = time.perf_counter()
    logbook.info(f'includedNodes in {nextTime - start:.5f}s')

    complete = time.perf_counter() - ogStart
    logbook.info(f'networkX steiner calculated {len(includedNodes)} node subtree in {complete:.5f}s')

    return includedNodes


def plot_mst(g: nx.Graph):
    import matplotlib.pyplot as plt
    # Find the minimum spanning tree
    T = nx.minimum_spanning_tree(g)

    # Visualize the graph and the minimum spanning tree
    pos = nx.spring_layout(g)
    nx.draw_networkx_nodes(g, pos, node_color="lightblue", node_size=500)
    nx.draw_networkx_edges(g, pos, edge_color="grey")
    nx.draw_networkx_labels(g, pos, font_size=12, font_family="sans-serif")
    nx.draw_networkx_edge_labels(
        g, pos, edge_labels={(u, v): d["weight"] for u, v, d in g.edges(data=True)}
    )
    nx.draw_networkx_edges(T, pos, edge_color="green", width=2)
    plt.axis("off")
    plt.show()

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
        weightMod: MapMatrixInterface[float] | None = None,
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

        if weightMod:
            fromWeight -= weightMod.raw[tile.tile_index]

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and not right.isObstacle:
            weight = fromWeight
            if right.isObstacle or (bannedTiles is not None and right in bannedTiles):
                weight += baseWeight * 1000

            if weightMod:
                weight -= weightMod.raw[right.tile_index]

            g.add_edge(tileIndex, right.tile_index, weight=weight)
        if down and not down.isObstacle:
            weight = fromWeight
            if down.isObstacle or (bannedTiles is not None and down in bannedTiles):
                weight += baseWeight * 1000

            if weightMod:
                weight -= weightMod.raw[down.tile_index]

            g.add_edge(tileIndex, down.tile_index, weight=weight)

    nextTime = time.perf_counter()
    logbook.info(f'networkX graph itself built in {nextTime - start:.5f}s')
    return g

def get_prize_collecting_gather_mapmatrix(
        map: MapBase,
        searchingPlayer=-2,
        toTile: Tile | None = None,
        # armyCutoff = 2.0,
        targetNodeCount = -1,
        gatherMatrix: MapMatrixInterface[float] | None = None,
        captureMatrix: MapMatrixInterface[float] | None = None,
        sameResultCutoff = 5,
        iterationLimit = 15,
        enemyArmyCostFactor = 0.1
) -> typing.List[Tile]:
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

    bestMax, bestMin, bestResult = _pcst_gradient_binary_search(captureMatrix, enemyArmyCostFactor, gatherMatrix, map, sameResultCutoff, searchingPlayer, targetNodeCount, toTile, costIterations=7, prizeIterations=5)
    logbook.info(f'pcst cost cutoff took {time.perf_counter() - start:.5f}s, output {len(bestResult)} nodes, (bestMin {bestMin:.4f}, bestMax {bestMax:.4f})')

    outTiles = [map.get_tile_by_tile_index(v) for v in bestResult]

    logbook.info(f'pcst iterative took {time.perf_counter() - start:.5f}s, output {len(outTiles)} nodes (target {targetNodeCount})')

    return outTiles


def _pcst_gradient_binary_search(captureMatrix, enemyArmyCostFactor, gatherMatrix, map, sameResultCutoff, searchingPlayer, targetNodeCount, toTile, costIterations: int, prizeIterations: int, cutoffTime: float | None = None):
    lastCount = -1000
    minCutoff = 0.0
    maxCutoff = 20.0
    bestResult = None
    bestDiff = 100000
    nextCutoff = 3.0
    sameResultCount = 0
    bestMax = 100.0
    bestMin = 0.0
    costIters = 0
    lastDiffRaw = -1
    while (sameResultCount != sameResultCutoff or costIters < 10) and costIters < costIterations and (cutoffTime is None or time.perf_counter() < cutoffTime - 0.001):
        costIters += 1

        # vertices = _pcst_iteration_internal(map, searchingPlayer, toTile, nextCutoff, enemyArmyCostFactor, gatherMatrix, captureMatrix)
        curPrizeIterLimit = max(1, prizeIterations - (costIterations - costIters))
        prizeMax, prizeMin, vertices = _pcst_gradient_descent_prize_basis(captureMatrix, enemyArmyCostFactor, gatherMatrix, curPrizeIterLimit, map, sameResultCutoff, costCutoff=nextCutoff, searchingPlayer=searchingPlayer, targetNodeCount=targetNodeCount, toTile=toTile)
        vCount = 0 - targetNodeCount
        if vertices is not None:
            vCount = len(vertices)

        logbook.info(f' cost attempt at {nextCutoff:.5f} output {vCount} nodes (target {targetNodeCount}, min {minCutoff:.5f}, max {maxCutoff:.5f}, prizeMin {prizeMin:.5f}, prizeMax {prizeMax:.5f})')

        newDiff = vCount - targetNodeCount
        if newDiff > 0:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            minCutoff = minCutoff + (nextCutoff - minCutoff) * 0.75
        else:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            maxCutoff = maxCutoff - (maxCutoff - nextCutoff) * 0.75

        if vCount != lastCount:
            sameResultCount = 0
        else:
            sameResultCount += 1

        nextCutoff = (maxCutoff + minCutoff) / 2

        lastCount = vCount
        absNewDiff = abs(newDiff)
        if absNewDiff <= bestDiff and vCount > 1:
            if bestMin < minCutoff and lastDiffRaw < newDiff:
                bestMin = minCutoff
            if bestMax > maxCutoff and lastDiffRaw > newDiff:
                bestMax = maxCutoff
            bestDiff = absNewDiff
            bestResult = vertices

        lastDiffRaw = newDiff
        if targetNodeCount == -1:
            break
    return bestMax, bestMin, bestResult


def _pcst_gradient_descent_prize_basis(captureMatrix, enemyArmyCostFactor, gatherMatrix, iterationLimit, map, sameResultCutoff, costCutoff, searchingPlayer, targetNodeCount, toTile):
    lastCount = -1000
    minCutoff = -1.0
    maxCutoff = 2.0
    bestResult = None
    bestDiff = 100000
    nextCutoff = 0.0
    sameResultCount = 0
    bestMax = 100.0
    bestMin = -100
    iters = 0
    lastDiffRaw = -1
    while (sameResultCount != sameResultCutoff or iters < 10) and iters < iterationLimit:
        iters += 1

        vertices = _pcst_iteration_internal(map, searchingPlayer, toTile, cutoffFactor=costCutoff, enemyArmyCostFactor=enemyArmyCostFactor, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix, prizeOffset=nextCutoff)

        logbook.info(f' prize attempt at {nextCutoff:.5f} output {len(vertices)} nodes (target {targetNodeCount}, min {minCutoff:.5f}, max {maxCutoff:.5f}, cost cutoff {costCutoff:.5f})')

        newDiff = len(vertices) - targetNodeCount
        if newDiff < 0:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            minCutoff = minCutoff + (nextCutoff - minCutoff) * 1.0
        else:
            # because the algo is not exact, adjust the cutoff a bit more leniently
            maxCutoff = maxCutoff - (maxCutoff - nextCutoff) * 1.0

        if len(vertices) != lastCount:
            sameResultCount = 0
        else:
            sameResultCount += 1

        nextCutoff = (maxCutoff + minCutoff) / 2

        lastCount = len(vertices)
        absNewDiff = abs(newDiff)
        if absNewDiff <= bestDiff and lastCount != 1:
            if bestMin < minCutoff and lastDiffRaw < newDiff:
                bestMin = minCutoff
            if bestMax > maxCutoff and lastDiffRaw > newDiff:
                bestMax = maxCutoff
            bestDiff = absNewDiff
            bestResult = vertices

        lastDiffRaw = newDiff
        if targetNodeCount == -1:
            break
    return bestMax, bestMin, bestResult


def _pcst_iteration_internal(
        map: MapBase,
        searchingPlayer: int,
        toTile: Tile | None,
        cutoffFactor: float,
        enemyArmyCostFactor: float = 0.2,
        gatherMatrix: MapMatrixInterface[float] | None = None,
        captureMatrix: MapMatrixInterface[float] | None = None,
        prizeOffset: float = 0.0
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
    if toTile is not None:
        root = toTile.tile_index
    """ root: the root note for rooted PCST. For the unrooted variant, this parameter should be -1."""

    num_clusters = 1  # we want exactly one subtree...?
    """ num_clusters: the number of connected components in the output."""

    pruning = 'strong'
    """ pruning: a string value indicating the pruning method. 
        Possible values are 'none', 'simple', 'gw', and 'strong' (all literals are case-insensitive). 
        'none' and 'simple' return intermediate stages of the algorithm and do not have approximation guarantees. They are only intended for development. 
        The standard GW pruning method is 'gw', which is also the default. 
        'strong' uses "strong pruning", which was introduced in [JMP00]. It has the same theoretical guarantees as GW pruning but better empirical performance in some cases. 
        For the PCSF problem, the output of strong pruning is at least as good as the output of GW pruning."""

    verbosity_level = 0
    """ verbosity_level: an integer indicating how much debug output the function should produce."""
    for tileIndex in range(map.cols * map.rows):
        tile = map.get_tile_by_tile_index(tileIndex)

        prize = 0.0
        extraCost = 0.0
        if map.is_tile_on_team_with(tile, searchingPlayer):
            prize = float(tile.army)
            if gatherMatrix:
                prize += gatherMatrix.raw[tile.tile_index] * prizeOffset
        else:
            extraCost = tile.army * enemyArmyCostFactor
            # extraCost = 0.0
            if captureMatrix:
                capVal = captureMatrix.raw[tile.tile_index] * prizeOffset
                prize += capVal
                extraCost -= capVal

        prizes.append(max(0.0, prize + prizeOffset))

        if tile.isObstacle:
            continue

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        if right and not right.isObstacle:
            edges.append([tileIndex, right.tile_index])
            cost = cutoffFactor + extraCost
            costs.append(max(0.0, cost))
            # logbook.info(f'prize {prize:.3f} for {tile}<->{right}  cost {cost:.3f}')

        if down and not down.isObstacle:
            edges.append([tileIndex, down.tile_index])
            cost = cutoffFactor + extraCost
            costs.append(max(0.0, cost))
            # logbook.info(f'prize {prize:.3f} for {tile}<->{down}  cost {cost:.3f}')

    vertices, edges = pcst_fast(edges, prizes, costs, root, num_clusters, pruning, verbosity_level)

    return vertices
