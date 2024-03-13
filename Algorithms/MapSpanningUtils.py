import logbook
import typing
from collections import deque
import SearchUtils
from MapMatrix import MapMatrix
from base.client.map import Tile, MapBase

USE_DEBUG_ASSERTS = False


T = typing.TypeVar('T')


class TileNode(typing.Generic[T]):
    def __init__(self, tile: Tile, data: T | None = None):
        self.tile: Tile = tile
        self.adjacents: typing.List[TileNode] = []
        self.data: T | None = data


class TileGraph(typing.Generic[T]):
    def __init__(self, graph: MapMatrix[TileNode]):
        self.graph: MapMatrix[TileNode[T]] = graph

    def reduce_to_tiles(self, bannedTiles: typing.List[Tile], tiles: typing.List[Tile]):
        for tile in bannedTiles:
            n = self.graph[tile]
            for adj in n.adjacents:
                adj.adjacents.remove(n)
            self.graph[tile] = None

    def get_connected_tiles(self) -> typing.List[Tile]:
        return [t.tile for t in self.graph.values() if t is not None]


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


def get_map_as_graph_from_tiles(
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
    table: MapMatrix[TileNode] = MapMatrix(map, None)

    ourGen = map.generals[map.player_index]

    bannedSet = set(bannedTiles)
    includedSet = set()
    missingIncluded = set(requiredTiles)
    bannedSet.difference_update(requiredTiles)

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
    graph.graph[requiredTiles[0]] = root
    usefulStartSet = set(includedSet)

    _include_all_adj_required(graph, root, includedSet, usefulStartSet, missingIncluded)

    def findFunc(t: Tile, depth: int, army: int) -> bool:
        # if depth > 1 and t in usefulStartSet:
        return t in missingIncluded

    while missingIncluded:
        path = SearchUtils.breadth_first_find_queue(map, usefulStartSet, findFunc, skipTiles=bannedSet)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if path is None:
            altBanned = set(bannedSet)
            altBanned.update([t for t in map.reachableTiles if t.isMountain])
            path = SearchUtils.breadth_first_find_queue(map, includedSet, findFunc, skipTiles=altBanned, bypassDefaultSkipLogic=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if path is None:
                break
                # raise AssertionError(f'No MST building path found...? \r\nFrom {includedSet} \r\nto {missingIncluded}')

        lastNode: TileNode | None = None
        for tile in path.tileList:
            node = graph.graph[tile]
            if node is None:
                node = TileNode(tile)
                graph.graph[tile] = node

            _include_all_adj_required(graph, node, includedSet, usefulStartSet, missingIncluded, lastNode)
            lastNode = node

    # for tile in map.reachableTiles:
    #     if tile not in includedSet:
    #         table[tile] = None

    return graph, missingIncluded


def _include_all_adj_required(graph: TileGraph, node: TileNode, includedSet: typing.Set[Tile], usefulStartSet: typing.Set[Tile], missingIncludedSet: typing.Set[Tile], fromNode: TileNode | None = None):
    q = deque()
    q.append((node, fromNode))

    while q:
        node, fromNode = q.popleft()

        if fromNode is not None:
            node.adjacents.append(fromNode)
            fromNode.adjacents.append(node)

        includedSet.add(node.tile)
        usefulStartSet.add(node.tile)
        missingIncludedSet.discard(node.tile)

        for movable in node.tile.movable:
            if movable not in missingIncludedSet:
                continue
            nextNode = graph.graph[movable]
            if nextNode is None:
                nextNode = TileNode(movable)
                graph.graph[movable] = nextNode

            if nextNode is not None:
                q.append((nextNode, node))
