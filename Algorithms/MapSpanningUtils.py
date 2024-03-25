import logbook
import typing
from collections import deque

import SearchUtils
from MapMatrix import MapMatrix, MapMatrixSet, TileSet
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
    def __init__(self, graph: MapMatrix[TileNode]):
        self.nodes: MapMatrix[TileNode[T] | None] = graph

    def reduce_to_tiles(self, bannedTiles: typing.List[Tile], tiles: typing.List[Tile]):
        for tile in bannedTiles:
            n = self.nodes[tile]
            for adj in n.adjacents:
                adj.adjacents.remove(n)
            self.nodes[tile] = None

    def get_connected_tiles(self) -> typing.List[Tile]:
        return [t.tile for t in self.nodes.values() if t is not None]


def get_map_as_graph(map: MapBase) -> TileGraph:
    table: MapMatrix[TileNode] = MapMatrix(map, None)

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
        bannedTiles: typing.List[Tile],
        requiredTiles: typing.List[Tile]
) -> typing.Tuple[TileGraph, typing.Set[Tile]]:
    """
    Returns the graph of all those connected, as well as the set of any required that couldn't be connected to the first required tile.

    @param map:
    @param bannedTiles:
    @param requiredTiles:
    @return:
    """
    if LOG_VERBOSE:
        logbook.info('starting get_map_as_graph_from_tiles')
    table: MapMatrix[TileNode] = MapMatrix(map, None)

    bannedSet = MapMatrixSet(map, bannedTiles)
    includedSet = MapMatrixSet(map)
    missingIncluded = set(requiredTiles)
    for req in requiredTiles:
        bannedSet.discard(req)

    # for tile in map.reachableTiles:
    #     if tile in bannedSet:
    #         continue
    #     node = TileNode(tile)
    #     table[tile] = node

    # for tile in requiredTiles:
    #     node = TileNode(tile)
    #     table[tile] = node

    # for tile in requiredTiles:
    #     node = table[tile]
    #     for moveable in tile.movable:
    #         if moveable in bannedSet:
    #             continue
    #         adjNode = table[moveable]
    #         if adjNode is not None:
    #             node.adjacents.append(adjNode)
    graph = TileGraph(table)

    root = TileNode(requiredTiles[0])
    graph.nodes[requiredTiles[0]] = root
    usefulStartSet = includedSet.copy()

    if LOG_VERBOSE:
        logbook.info('Completed sets setup')

    _include_all_adj_required(graph, root, includedSet, usefulStartSet, missingIncluded)

    if LOG_VERBOSE:
        logbook.info('Completed root _include_all_adj_required')

    def findFunc(t: Tile, depth: int, army: int) -> bool:
        # if depth > 1 and t in usefulStartSet:
        return t in missingIncluded

    iter = 0
    while missingIncluded:
        # iter += 1
        # if LOG_VERBOSE:
        #     logbook.info(f'missingIncluded iter {iter}')
        path = SearchUtils.breadth_first_find_queue(map, usefulStartSet, findFunc, skipTiles=bannedSet, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if path is None:
            # if LOG_VERBOSE:
            #     logbook.info(f'  Path NONE! Performing altBanned set')
            altBanned = bannedSet.copy()
            altBanned.update([t for t in map.reachableTiles if t.isMountain])
            path = SearchUtils.breadth_first_find_queue(map, includedSet, findFunc, skipTiles=altBanned, bypassDefaultSkipLogic=True, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if path is None:
                # if LOG_VERBOSE:
                #     logbook.info(f'  No AltPath, breaking')
                break
                # raise AssertionError(f'No MST building path found...? \r\nFrom {includedSet} \r\nto {missingIncluded}')
            # else:
            #     if LOG_VERBOSE:
            #         logbook.info(f'  AltPath len {path.length}')
        # else:
        #     if LOG_VERBOSE:
        #         logbook.info(f'  Path len {path.length}')

        lastNode: TileNode | None = None

        for tile in path.tileList:
            node = graph.nodes[tile]
            if node is None:
                node = TileNode(tile)
                graph.nodes[tile] = node

            _include_all_adj_required(graph, node, includedSet, usefulStartSet, missingIncluded, lastNode)
            lastNode = node

    # for tile in map.reachableTiles:
    #     if tile not in includedSet:
    #         table[tile] = None

    return graph, missingIncluded


def _include_all_adj_required(graph: TileGraph, node: TileNode, includedSet: TileSet, usefulStartSet: TileSet, missingIncludedSet: TileSet, fromNode: TileNode | None = None):
    """
    Inlcudes all adjacent required tiles int the

    @param graph:
    @param node:
    @param includedSet:
    @param usefulStartSet:
    @param missingIncludedSet:
    @param fromNode:
    @return:
    """
    q = deque()
    q.append((node, fromNode))

    iter = 0
    while q:
        iter += 1
        node, fromNode = q.popleft()

        if fromNode is not None:
            node.adjacents.append(fromNode)
            fromNode.adjacents.append(node)

        if node.tile in includedSet:
            continue

        includedSet.add(node.tile)
        usefulStartSet.add(node.tile)
        missingIncludedSet.discard(node.tile)

        for movable in node.tile.movable:
            if movable not in missingIncludedSet:
                continue

            nextNode = graph.nodes[movable]
            if nextNode is None:
                nextNode = TileNode(movable)
                graph.nodes[movable] = nextNode

            if nextNode is not None:
                q.append((nextNode, node))