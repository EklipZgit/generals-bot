import time

import logbook
import typing
from collections import deque

import SearchUtils
from Interfaces import MapMatrixInterface, TileSet
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
    table: MapMatrixInterface[TileNode] = MapMatrix(map, None)

    for tile in map.reachableTiles:
        node = TileNode(tile)
        table[tile] = node

    for tile in map.reachableTiles:
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
    includedSet, missingIncluded = get_spanning_tree_matrix_from_tile_lists(map, requiredTiles, bannedTiles)

    return [t for t in includedSet], missingIncluded


def get_spanning_tree_matrix_from_tile_lists(
        map: MapBase,
        requiredTiles: typing.List[Tile],
        bannedSet: TileSet,
        # oneOfTiles: typing.Iterable[Tile] | None = None,
) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile]]:
    """
    Returns the graph of all those connected, as well as the set of any required that couldn't be connected to the first required tile.

    @param map:
    @param bannedSet:
    @param requiredTiles:
    @return:
    """
    start = time.perf_counter()
    if LOG_VERBOSE:
        logbook.info('starting get_map_as_graph_from_tiles')
    includedSet = set()
    missingIncluded = set(requiredTiles)

    # bannedSet.difference_update(requiredTiles)
    for req in requiredTiles:
        bannedSet.discard(req)

    if len(requiredTiles) == 0:
        return includedSet, missingIncluded

    root = requiredTiles[0]
    usefulStartSet = includedSet.copy()
    if LOG_VERBOSE:
        logbook.info('Completed sets setup')
    _include_all_adj_required(root, includedSet, usefulStartSet, missingIncluded)
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
            altBanned.update([t for t in map.reachableTiles if t.isMountain])
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

            _include_all_adj_required(tile, includedSet, usefulStartSet, missingIncluded, lastTile)
            lastTile = tile

    if LOG_VERBOSE:
        logbook.info(f'get_spanning_tree_matrix_from_tile_lists completed in {time.perf_counter() - start:.5f}s with {len(missingIncluded)} missing')

    return includedSet, missingIncluded


def _include_all_adj_required(node: Tile, includedSet: TileSet, usefulStartSet: TileSet, missingIncludedSet: TileSet, fromNode: Tile | None = None):
    """
    Inlcudes all adjacent required tiles int the

    @param node:
    @param includedSet:
    @param usefulStartSet:
    @param missingIncludedSet:
    @param fromNode:
    @return:
    """
    q = deque()
    q.append(node)

    iter = 0
    included = 0
    while q:
        iter += 1
        tile = q.popleft()

        # if fromNode is not None:
        #     node.adjacents.append(fromNode)
        #     fromNode.adjacents.append(node)

        if tile in includedSet:
            continue

        included += 1

        includedSet.add(tile)
        usefulStartSet.add(tile)
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