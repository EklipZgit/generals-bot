import time

import logbook
import typing
from collections import deque

import SearchUtils
from Interfaces import MapMatrixInterface, TileSet
from Interfaces.MapMatrixInterface import EmptySet
from MapMatrix import MapMatrix
from base.client.map import Tile, MapBase

USE_DEBUG_ASSERTS = False
LOG_VERBOSE = False


T = typing.TypeVar('T')


class TileNode(typing.Generic[T]):
    def __init__(self, tile: Tile, data: T | None = None):
        self.tile: Tile = tile
        self.adjacents: typing.List[TileNode] = []
        self.data: T | None = data


class TileGraph(typing.Generic[T]):
    def __init__(self, graph: MapMatrixInterface[TileNode]):
        self.nodes: MapMatrixInterface[TileNode[T] | None] = graph

    def reduce_to_tiles(self, bannedTiles: typing.List[Tile], tiles: typing.List[Tile]):
        for tile in bannedTiles:
            n = self.nodes[tile]
            for adj in n.adjacents:
                adj.adjacents.remove(n)
            self.nodes[tile] = None

    def get_connected_tiles(self) -> typing.List[Tile]:
        return [t.tile for t in self.nodes.values() if t is not None]


def get_map_as_graph(map: MapBase) -> TileGraph:
    """Unused"""
    table: MapMatrixInterface[TileNode] = MapMatrix(map, None)

    for tile in map.reachable_tiles:
        node = TileNode(tile)
        table[tile] = node

    for tile in map.reachable_tiles:
        node = table[tile]
        for moveable in tile.movable:
            adjNode = table[moveable]
            if adjNode is not None:
                node.adjacents.append(adjNode)

    graph = TileGraph(table)

    return graph


def get_spanning_tree_from_tile_lists(
        map: MapBase,
        requiredTiles: typing.List[Tile],
        bannedTiles: TileSet,
) -> typing.Tuple[typing.List[Tile], typing.Set[Tile]]:
    """
    Returns the graph of all those connected, as well as the set of any required that couldn't be connected to the first required tile.

    @param map:
    @param bannedTiles:
    @param requiredTiles:
    @return:
    """
    includedSet, missingIncluded = get_spanning_tree_set_from_tile_lists(map, requiredTiles, bannedTiles)

    return [t for t in includedSet], missingIncluded


def get_spanning_tree_set_from_tile_lists(
        map: MapBase,
        requiredTiles: typing.List[Tile],
        bannedSet: TileSet,
        # oneOfTiles: typing.Iterable[Tile] | None = None,
) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile]]:
    included, missingIncluded, costPer = get_spanning_tree_set_from_tile_lists_with_cost_per(
        map,
        requiredTiles,
        bannedSet
    )
    return included, missingIncluded


def get_spanning_tree_set_from_tile_lists_with_cost_per(
        map: MapBase,
        requiredTiles: typing.List[Tile],
        bannedSet: TileSet,
        # oneOfTiles: typing.Iterable[Tile] | None = None,
) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile], typing.Dict[Tile, int]]:
    """
    Returns set of all those connected, as well as the set of any required that couldn't be connected to the first required tile.
    This is extremely fast, but builds an arbitrary set of connections between nodes.
    This does not require iterating all nodes in the map, so if you connect a bunch of nearby tiles, the rest of the map shouldn't affect runtime.
    Should be something like T log (T) where T is the number of nodes in the resulting tree.

    @param map:
    @param bannedSet:
    @param requiredTiles:
    @return:
    """
    start = time.perf_counter()
    if LOG_VERBOSE:
        logbook.info('starting get_spanning_tree_set_from_tile_lists')
    includedSet = set()
    missingIncluded = set(requiredTiles)
    costPer = {}

    # bannedSet.difference_update(requiredTiles)
    for req in requiredTiles:
        bannedSet.discard(req)

    if len(requiredTiles) == 0:
        return includedSet, missingIncluded, costPer

    root = requiredTiles[0]
    usefulStartSet = includedSet.copy()
    if LOG_VERBOSE:
        logbook.info('Completed sets setup')
    _include_all_adj_required(root, includedSet, usefulStartSet, missingIncluded, costPer)
    if LOG_VERBOSE:
        logbook.info('Completed root _include_all_adj_required')

    def findFunc(t: Tile, depth: int, army: int) -> bool:
        # if depth > 1 and t in usefulStartSet:
        return t in missingIncluded

    iter = 0
    while missingIncluded:
        # iter += 1
        if LOG_VERBOSE:
            logbook.info(f'missingIncluded iter {iter}')
        path = SearchUtils.breadth_first_find_queue(map, usefulStartSet, findFunc, skipTiles=bannedSet, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if path is None:
            if LOG_VERBOSE:
                logbook.info(f'  Path NONE! Performing altBanned set')
            altBanned = bannedSet.copy()
            altBanned.update([t for t in map.reachable_tiles if t.isMountain])
            path = SearchUtils.breadth_first_find_queue(map, includedSet, findFunc, skipTiles=altBanned, bypassDefaultSkipLogic=True, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if path is None:
                if LOG_VERBOSE:
                    logbook.info(f'  No AltPath, breaking early with {len(missingIncluded)} left missing')
                break
                # raise AssertionError(f'No MST building path found...? \r\nFrom {includedSet} \r\nto {missingIncluded}')
            # else:
            #     if LOG_VERBOSE:
            #         logbook.info(f'  AltPath len {path.length}')
        # else:
        #     if LOG_VERBOSE:
        #         logbook.info(f'  Path len {path.length}')

        lastTile: Tile | None = None

        for tile in path.tileList:
            # table.add(tile)

            _include_all_adj_required(tile, includedSet, usefulStartSet, missingIncluded, costPer, lastTile)
            lastTile = tile

        costPer[lastTile] = path.length

    costPer[root] = 0

    if LOG_VERBOSE:
        logbook.info(f'get_spanning_tree_set_from_tile_lists completed in {time.perf_counter() - start:.5f}s with {len(missingIncluded)} missing after {iter} path iterations')

    return includedSet, missingIncluded, costPer


def _include_all_adj_required(node: Tile, includedSet: TileSet, usefulStartSet: TileSet, missingIncludedSet: TileSet, costPer: typing.Dict[Tile, int], fromNode: Tile | None = None):
    """
    Inlcudes all adjacent required tiles int the

    @param node:
    @param includedSet:
    @param usefulStartSet:
    @param missingIncludedSet:
    @param costPer: the cost per reaching each tile
    @param fromNode:
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

        includedSet.add(tile)
        usefulStartSet.add(tile)
        if tile in missingIncludedSet:
            missingIncludedSet.discard(tile)
            costPer[tile] = 1

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


def get_max_gather_spanning_tree_set_from_tile_lists(
        map: MapBase,
        requiredTiles: typing.List[Tile],
        bannedSet: TileSet,
        negativeTiles: TileSet | None = None,
        maxTurns: int = 1000,
        gatherPrioMatrix: MapMatrixInterface[float] | None = None,
        searchingPlayer: int = -1,
        # gatherMult: float = 1.0,
        # oneOfTiles: typing.Iterable[Tile] | None = None,
) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile]]:
    """
    Returns set of all those connected, as well as the set of any required that couldn't be connected to the first required tile.
    Prioritizes gathering army, optionally modifying the gather value with the value from the prio matrix

    @param negativeTiles:
    @param map:
    @param bannedSet:
    @param requiredTiles:
    @param maxTurns: limit the number of turns we can potentially use. This isn't guaranteed and may cause the gather to not connect all nodes or something?
    @param gatherPrioMatrix: gather prio values.
    @param searchingPlayer:
    @return:
    """
    # Determine the bare minimum that we can do with no prioritization
    minIncluded, unconnectable, costPer = get_spanning_tree_set_from_tile_lists_with_cost_per(map, requiredTiles, bannedSet)

    bareMinTurns = len(minIncluded)
    excessTurns = maxTurns - bareMinTurns

    start = time.perf_counter()
    if LOG_VERBOSE:
        logbook.info('starting get_max_gather_spanning_tree_set_from_tile_lists')
    includedSet = set()
    missingIncluded = set(requiredTiles)
    if negativeTiles is None:
        negativeTiles = missingIncluded.copy()
    else:
        # missingIncluded tiles shouldn't have a 'gather value', treat them as negative. Our goal is finding the best tiles in between all the included, not the highest value included connection point
        negativeTiles = negativeTiles.copy()
        negativeTiles.update(missingIncluded)

    expectedMinRemaining = 0
    for tile in missingIncluded:
        expectedMinRemaining += costPer.get(tile, 0)

    logbook.info(f'bareMinTurns {bareMinTurns}, excessTurns {excessTurns}, expectedMinRemaining {expectedMinRemaining}')

    if searchingPlayer == -1:
        searchingPlayer = map.player_index

    # bannedSet.difference_update(requiredTiles)
    for req in requiredTiles:
        bannedSet.discard(req)

    if len(requiredTiles) == 0:
        return includedSet, missingIncluded

    baseTuple = ((-100000, 0, 0.0, 0), 0)

    root = requiredTiles[0]
    usefulStartSet = {t: baseTuple for t in includedSet}

    if LOG_VERBOSE:
        logbook.info('Completed sets setup')
    _include_all_adj_required_max_gather(root, includedSet, usefulStartSet, missingIncluded, gatherPrioMatrix, baseTuple)
    if LOG_VERBOSE:
        logbook.info('Completed root _include_all_adj_required')

    def findFunc(t: Tile, prio: typing.Tuple) -> bool:
        return t in missingIncluded

    iter = 0
    while missingIncluded:
        # iter += 1
        if LOG_VERBOSE:
            logbook.info(f'missingIncluded iter {iter}')

        expectedMinRemaining = 0
        closestDist = maxTurns
        closest = None
        for tile in missingIncluded:
            cost = costPer.get(tile, 0)
            expectedMinRemaining += cost
            if 1 < cost < closestDist:
                closestDist = cost
                closest = tile

        costSoFar = len(includedSet)
        excessTurnsLeft = maxTurns - (costSoFar + expectedMinRemaining)

        logbook.info(f'  costSoFar {costSoFar}, expectedMinRemaining {expectedMinRemaining} (out of max {maxTurns}, min {bareMinTurns}), closestDist {closestDist}, excessTurnsLeft {excessTurnsLeft}')

        def prioFunc(tile: Tile, prioObj: typing.Tuple):
            (
                cost,
                dist,
                negGatherPoints,
                negGather,
            ) = prioObj

            if tile not in negativeTiles:
                if map.is_tile_on_team_with(tile, searchingPlayer):
                    negGather -= tile.army - 1
                    negGatherPoints -= tile.army - 1
                    negGatherPoints -= gatherPrioMatrix.raw[tile.tile_index]
                else:
                    negGather += tile.army + 1
                    negGatherPoints += 1
                    # if negGather < 0:
                    # # No points for enemy tiles...?
                    #     negGatherPoints -= tile.army + 1
                    # else:
                    negGatherPoints -= gatherPrioMatrix.raw[tile.tile_index]

            # TODO ASTARIFY THIS?
            newCost = dist + 1
            costWeight = excessTurnsLeft - (dist + 1)
            # tile.coords in [(8, 6)]
            if costWeight > 0 and negGatherPoints < 0:
                excessCostRat = costWeight / excessTurnsLeft
                """Ratio of excess turns left over"""
                costDivisor = (0 - negGatherPoints) * excessCostRat
                newCost -= costWeight * excessCostRat  #- 1/costDivisor
                # newCost -= excessTurnsLeft * (1 / excessCostRat)

            return (
                newCost,
                dist + 1,
                negGatherPoints,
                negGather
            )

        path = SearchUtils.breadth_first_dynamic(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=bannedSet, priorityFunc=prioFunc, noLog=not LOG_VERBOSE)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if path is None:
            if LOG_VERBOSE:
                logbook.info(f'  Path NONE! Performing altBanned set')
            # altBanned = bannedSet.copy()
            # altBanned.update([t for t in map.reachableTiles if t.isMountain])
            path = SearchUtils.breadth_first_dynamic(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=bannedSet, priorityFunc=prioFunc, noNeutralCities=False, noLog=not LOG_VERBOSE)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if path is None:
                if LOG_VERBOSE:
                    logbook.info(f'  No AltPath, breaking early with {len(missingIncluded)} left missing')
                break
                # raise AssertionError(f'No MST building path found...? \r\nFrom {includedSet} \r\nto {missingIncluded}')
            # else:
            #     if LOG_VERBOSE:
            #         logbook.info(f'  AltPath len {path.length}')
        # else:
        #     if LOG_VERBOSE:
        #         logbook.info(f'  Path len {path.length}')

        logbook.info(f'    found {path.start.tile}->{path.tail.tile} len {path.length} (closest {closest} len {closestDist}) {path}')

        lastTile: Tile | None = None

        for tile in path.tileList:
            # table.add(tile)

            _include_all_adj_required_max_gather(tile, includedSet, usefulStartSet, missingIncluded, gatherPrioMatrix, baseTuple, lastTile)
            lastTile = tile

    if LOG_VERBOSE:
        logbook.info(f'get_max_gather_spanning_tree_set_from_tile_lists completed in {time.perf_counter() - start:.5f}s with {len(missingIncluded)} missing after {iter} path iterations')

    return includedSet, missingIncluded


def _include_all_adj_required_max_gather(node: Tile, includedSet: TileSet, usefulStartSet: TileSet, missingIncludedSet: TileSet, gatherMatrix: MapMatrixInterface[float], baseTuple: typing.Tuple[typing.Tuple, int], fromNode: Tile | None = None):
    """
    Inlcudes all adjacent required tiles int the

    @param node:
    @param includedSet:
    @param usefulStartSet:
    @param missingIncludedSet:
    @param gatherMatrix:
    @param fromNode:
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

        includedSet.add(tile)
        # usefulStartSet.add(tile)
        usefulStartSet[tile] = baseTuple

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
