from __future__ import  annotations

import heapq
import itertools
import time
import typing

import logbook
import networkx
import networkx as nx

import SearchUtils
from Interfaces import TileSet, MapMatrixInterface
from MapMatrix import MapMatrix
from base.client.map import MapBase
from base.client.tile import Tile

#
# def bounded_suboptimal_search():
#     pass
#
#
# def suboptimal_search():
#     pass
#
#
# def anytime_search():
#     pass


# GPT LOL
# PRODUCED INITIALLY BY CHATGPT AND TWEAKED BY ME FROM
# https://ojs.aaai.org/index.php/ICAPS/article/view/6668/6522
#   https://www.youtube.com/watch?v=aMQdnotF9-g
# https://ojs.aaai.org/index.php/SOCS/article/download/18557/18346/22076

# grid = [
#     [0, 0, 1, 0],
#     [0, 1, 0, 0],
#     [0, 0, 0, 1],
#     [1, 0, 0, 0]
# ]


# THIS IS THE DUMB Seiraf A* IMPLEMENTATION, WHICH DOES NOT PREPROCESS THE GRAPH BUT SHOULD ALWAYS PRODUCE OPTIMAL RESULT; VERY VERY EXPENSIVE THOUGH (O(n^3) sort of range)
# https://ojs.aaai.org/index.php/ICAPS/article/view/6668/6522
class BasicAStarWRP:
    def __init__(self, start, map: MapBase, toDiscover: typing.Set[Tile]):
        self.start = start
        self.to_discover: typing.Set[Tile] = toDiscover
        self.map: MapBase = map
        self.open_list: typing.List[typing.Tuple[float, BasicAStarNode]] = []
        self.closed_set = set()
        self.start_node = BasicAStarNode(tile=start, unseen=self.to_discover)
        heapq.heappush(self.open_list, (self.start_node.total_estimated_cost, self.start_node))

    def heuristic(self, node: BasicAStarNode) -> float:
        # Singleton Heuristic; this is quite expensive, something like n^2
        h_singleton = 0
        for tile in node.unseen:
            h_singleton = max(h_singleton, min(self.map.get_distance_between(node.tile, t) for t in tile.adjacents))

        return h_singleton

    def solve(self) -> typing.List[Tile]:
        current_f: float
        current_node: BasicAStarNode

        discoverLen = len(self.to_discover)
        iteration = 0
        while self.open_list:
            iteration += 1
            current_f, current_node = heapq.heappop(self.open_list)
            if iteration & 127 == 0:
                logbook.info(f'iter {iteration}, open {len(self.open_list)}, closed {len(self.closed_set)}, current {current_node.tile} (unseen {len(current_node.unseen)}, cost so far {current_node.cost_so_far}, est remaining {current_node.total_estimated_cost})')
            if not current_node.unseen:
                return current_node.path

            self.closed_set.add(current_node)

            for neighbor in current_node.tile.movable:
                # if neighbor in self.closed_list or neighbor.isObstacle:
                #     continue
                if neighbor.isObstacle or (neighbor.isCity and neighbor.isTempFogPrediction):  # Don't let it path through uncertain predicted cities as those are unlikely to ACTUALLY be routable.
                    continue

                neighbor_node = BasicAStarNode(
                    neighbor,
                    # current_node.seen.union(a for a in neighbor.adjacents if a in current_node.unseen),
                    current_node.unseen.difference(neighbor.adjacents),
                    current_node.path + [neighbor],
                    current_node.cost_so_far + 1)  # actual cost is always 1.

                if neighbor_node in self.closed_set:
                    continue

                neighbor_node.heuristic_cost_remaining = self.heuristic(neighbor_node)
                neighbor_node.total_estimated_cost = neighbor_node.cost_so_far + neighbor_node.heuristic_cost_remaining

                # if neighbor_node not in self.open_list:  # The fuck, chatgpt? There is NO WAY we are supposed to do this. MAYBE we make a set of open entries to prevent adding duplicates, though.
                heapq.heappush(self.open_list, (neighbor_node.total_estimated_cost, neighbor_node))


class BasicAStarNode:
    def __init__(
            self,
            tile: Tile,
            # seen: typing.Set[Tile],
            unseen: typing.Set[Tile],
            path: typing.List[Tile] | None = None,
            cost_so_far=0
    ):
        self.tile: Tile = tile
        # self.seen: typing.Set[Tile] = seen
        self.unseen: typing.Set[Tile] = unseen
        self.path = path or [tile]
        self.cost_so_far = cost_so_far
        self.heuristic_cost_remaining: float = 0
        self.total_estimated_cost: float = 0  # = self.cost_so_far + self.heuristic_cost_remaining
        self._hash: int = 0

    def __eq__(self, other: BasicAStarNode):
        return self.tile == other.tile and hash(self) == hash(other)  # and self.seen == other.seen

    def __hash__(self):
        # return hash((self.tile.tile_index, tuple(self.seen)))

        if self._hash == 0:
            self._hash = hash((self.tile.tile_index, tuple(self.unseen)))

        return self._hash

    def __lt__(self, other: BasicAStarNode):
        return self.total_estimated_cost < other.total_estimated_cost


class PivotComponent:
    def __init__(self, pivot: Tile, frontierNodes: typing.Set[Tile]):
        self.pivot: Tile = pivot
        self.frontier_nodes: typing.Set[Tile] = frontierNodes
        self._hash = 0

    def __eq__(self, other: PivotComponent):
        return self.pivot == other.pivot

    def __hash__(self):
        return hash(self.pivot.tile_index)

    def __lt__(self, other: PivotComponent):
        return len(self.frontier_nodes) < len(other.frontier_nodes)


class FrontierAStarNode:
    def __init__(
            self,
            tile: Tile,
            # seen: typing.Set[Tile],
            unseen: typing.Set[Tile],
            unseenComponents: typing.Set[PivotComponent],
            path: typing.List[Tile] | None = None,
            cost_so_far=0
    ):
        self.tile: Tile = tile
        # self.seen: typing.Set[Tile] = seen
        self.unseen: typing.Set[Tile] = unseen
        self.unseen_components: typing.Set[PivotComponent] = unseenComponents
        self.path = path or [tile]
        self.cost_so_far = cost_so_far
        self.heuristic_cost_remaining: float = 0
        self.total_estimated_cost: float = 0  # = self.cost_so_far + self.heuristic_cost_remaining
        self._hash: int = 0

    def __eq__(self, other: FrontierAStarNode):
        return self.tile == other.tile and hash(self) == hash(other)  # and self.seen == other.seen

    def __hash__(self):
        # return hash((self.tile.tile_index, tuple(self.seen)))

        if self._hash == 0:
            self._hash = hash((self.tile.tile_index, tuple(self.unseen)))

        return self._hash

    def __lt__(self, other: FrontierAStarNode):
        return self.total_estimated_cost < other.total_estimated_cost


# # Example usage
# los_table = preprocess_los(grid)
# apsp = all_pairs_shortest_path(grid)
# start_tile = Tile(0, 0)
# astar_wrp = AStarWRP(start_tile, grid, los_table, apsp)
# path = astar_wrp.solve()
# print("Optimal Path:", path)

# THIS IS THE SMARTER Seiraf ABSTRACTED PIVOT TREE THING IMPLEMENTATION, WHICH DOES NOT PREPROCESS THE GRAPH BUT SHOULD ALWAYS PRODUCE OPTIMAL RESULT; VERY VERY EXPENSIVE THOUGH (O(n^3) sort of range)
class PivotWRP:
    """
    https://ojs.aaai.org/index.php/ICAPS/article/view/6668/6522
    """

    def __init__(self, start: Tile, map: MapBase, toDiscover: typing.Set[Tile], noLog: bool = True):
        self.noLog: bool = noLog
        self.start: Tile = start
        self.to_discover: typing.Set[Tile] = toDiscover
        self.map: MapBase = map
        self.open_list: typing.List[typing.Tuple[float, FrontierAStarNode]] = []
        self.closed_set = set()

        self.pivot_set: typing.Set[Tile] = self.build_pivots(toDiscover)

        self.component_lookup: MapMatrixInterface[PivotComponent | None] = None
        self.components: typing.Set[PivotComponent] = None
        self.frontiers: typing.Set[Tile] = None
        self.mst_set: typing.Set[Tile] = None
        self.nxGraph: nx.Graph = None

        self.build_frontiers()

        self.connect_graph()

        self.start_node = FrontierAStarNode(tile=start, unseen=self.to_discover, unseenComponents=self.components.copy())
        heapq.heappush(self.open_list, (self.start_node.total_estimated_cost, self.start_node))

    def heuristic(self, node: FrontierAStarNode) -> float:
        # Singleton Heuristic; this is quite expensive, something like n^2
        h_singleton = 0
        if len(node.unseen_components) > 3:
            for component in node.unseen_components:
                h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile))
                # h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes))
        # elif len(node.unseen_components) > 0:
        # else:
        #     for component in node.unseen_components:
        #         # h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile))
        #         h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes) + 1)
        else:
            for tile in node.unseen:
                h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in tile.adjacents if not t.isObstacle and not (t.isCity and t.isTempFogPrediction)))

        return h_singleton

    def solve(self, cutoffTime: float | None = None) -> typing.List[Tile]:
        current_f: float
        current_node: FrontierAStarNode

        bestTurns = -1
        bestPath = None
        bestUnseen = 1000
        # bestUnseenReductionPerTurn = 0

        if not cutoffTime:
            cutoffTime = time.perf_counter() + 1000

        iteration = 0
        while self.open_list:
            iteration += 1
            current_f, current_node = heapq.heappop(self.open_list)

            unseenCount = len(current_node.unseen)
            if unseenCount == 0:
                return current_node.path

            if unseenCount < bestUnseen:
                bestTurns = len(current_node.path) - 1
                bestPath = current_node.path
                bestUnseen = unseenCount

            if iteration & 127 == 0:
                if cutoffTime < time.perf_counter():
                    logbook.info(f'watchman a* terminating early with {bestUnseen} unseen still and length {len(current_node.path)} length.')
                    return bestPath

                logbook.info(f'iter {iteration}, open {len(self.open_list)}, closed {len(self.closed_set)}, current {current_node.tile} (unseenComp {len(current_node.unseen_components)}, unseen {len(current_node.unseen)}, cost so far {current_node.cost_so_far}, est remaining {current_node.total_estimated_cost})')

            if len(current_node.unseen_components) == 0 and len(current_node.unseen) > 0:
                logbook.info(f'unseen components 0, but unseen: {current_node.unseen}')

            self.closed_set.add(current_node)

            for neighbor in current_node.tile.movable:
                if neighbor.isObstacle or (neighbor.isCity and neighbor.isTempFogPrediction):  # Don't let it path through uncertain predicted cities as those are unlikely to ACTUALLY be routable.
                    continue

                component = self.component_lookup.raw[neighbor.tile_index]

                # newPath = current_node.path.copy()
                # newPath.append(neighbor)
                newPath = current_node.path + [neighbor]

                # diff = t for t in neighbor.adjacents if

                neighbor_node = FrontierAStarNode(
                    neighbor,
                    # current_node.seen.union(neighbor.adjacents),
                    current_node.unseen.difference(neighbor.adjacents),
                    current_node.unseen_components.difference((component,)),
                    # current_node.unseen_components,
                    newPath,
                    current_node.cost_so_far + 1)  # actual cost is always 1.

                if neighbor_node in self.closed_set:
                    continue

                neighbor_node.heuristic_cost_remaining = self.heuristic(neighbor_node)
                neighbor_node.total_estimated_cost = neighbor_node.cost_so_far + neighbor_node.heuristic_cost_remaining

                # if neighbor_node not in self.open_list:  # The fuck, chatgpt? There is NO WAY we are supposed to do this. MAYBE we make a set of open entries to prevent adding duplicates, though.
                heapq.heappush(self.open_list, (neighbor_node.total_estimated_cost, neighbor_node))

    def build_pivots(self, toDiscover: typing.Set[Tile]) -> typing.Set[Tile]:
        """Pivots are the least seen cells, with disjoint watchers"""
        pivots = set()
        validRemainingPivots = toDiscover.copy()
        leastSeen: typing.List[typing.Tuple[int, Tile]] = []
        # usedWatchers = set()
        """(numberOfUnseenAdjacents, tile)"""
        for t in toDiscover:
            numUnseenAdj = 0
            for adj in t.adjacents:
                if adj.isObstacle or (adj.isCity and adj.isTempFogPrediction):
                    continue
                if adj not in toDiscover:
                    continue
                numUnseenAdj += 1

            heapq.heappush(leastSeen, (numUnseenAdj, t))

        while leastSeen:
            numUnseenAdj, tile = heapq.heappop(leastSeen)
            if tile not in validRemainingPivots:
                continue

            pivots.add(tile)
            validRemainingPivots.difference_update(itertools.chain.from_iterable(t.adjacents for t in tile.adjacents))
            validRemainingPivots.discard(tile)
            # usedWatchers.update(tile.adjacents)

        return pivots

    def build_frontiers(self):
        """
        Builds the frontier set, and the nxGraph, and adds the 0-weight frontier edges to the nx graph

        Frontier watchers are watchers of pivot p that have at least one neighboring
        cell that does not have LOS to p. For example, cell A is a
        frontier watcher but cell B is not. Frontier watchers are connected
        with frontier watchers of other pivots if the shortest
        path between them does not pass through other components
        in GDLS.

        Our pivot selection policy (Seiref et al. 2020) iteratively takes
        a cell P ∈ S.unseen with the fewest watchers and adds it to GDLS
        until no cell can be added to the set of LOS-disjoint pivots. This
        is a greedy policy that balances the pivots selection time and the
        quality of the heuristic derived from the GDLS that is formed.
        """

        start = time.perf_counter()

        # For us this is really simple since we already found our pivots.
        # frontiers = {t for t in itertools.chain.from_iterable(i.adjacents for i in self.pivot_set) if not (t.isCity and t.isTempFogPrediction)}

        frontiers = set()
        self.nxGraph = nx.Graph()

        component_lookup = MapMatrix(self.map)
        componentSet = set()

        for pivot in self.pivot_set:
            # component = set(t for t in pivot.adjacents if not (t.isObstacle or (t.isCity and t.isTempFogPrediction)))
            # component.add(pivot)
            componentWatchers = set()
            for t in pivot.adjacents:
                if t.isObstacle or (t.isCity and t.isTempFogPrediction):
                    continue

                canOnlyPathInThroughAnotherAdj = True
                for fromTile in t.movable:
                    if fromTile.isObstacle or (fromTile.isCity and fromTile.isTempFogPrediction):
                        continue
                    if fromTile not in pivot.adjacents and fromTile is not pivot:
                        canOnlyPathInThroughAnotherAdj = False
                        break

                if canOnlyPathInThroughAnotherAdj:
                    # bypass this node as all its movable are part of this inbound pivot
                    continue

                self.nxGraph.add_edge(pivot.tile_index, t.tile_index, weight=0)
                componentWatchers.add(t)

            frontiers.update(componentWatchers)
            component = PivotComponent(pivot, componentWatchers)
            for t in componentWatchers:
                component_lookup.raw[t.tile_index] = component

            component_lookup.raw[pivot.tile_index] = component
            componentSet.add(component)

        logbook.info(f' frontiers built in {time.perf_counter() - start:.4f}s')

        self.frontiers = frontiers
        self.components = componentSet
        self.component_lookup = component_lookup

    def connect_graph(self):
        start = time.perf_counter()
        self.frontiers.add(self.start)
        self.paths = {}
        ignorePairs = set()
        for tile in self.frontiers:
            for otherTile in self.frontiers:
                if tile is otherTile:
                    continue

                existingPath = self.paths.get((otherTile, tile), None)
                pair = (tile, otherTile)

                if pair in ignorePairs:
                    continue

                if existingPath:
                    self.paths[pair] = existingPath
                    continue

                path = SearchUtils.a_star_find_raw_with_try_avoid([tile], otherTile, tryAvoid=self.frontiers, maxDepth=200, noLog=True)
                if path:
                    skip = False
                    for pathTile in path[1:-1]:
                        # This respects the 'if the path between two frontiers must intersect another then the outer path should be removed
                        if pathTile in self.frontiers:
                            skip = True
                            if not self.noLog:
                                logbook.info(f'{tile}->{otherTile} MUST cross {pathTile}')
                            break

                            # self.paths.pop((pathTile, tile), None)
                            # self.paths.pop((tile, pathTile), None)
                            # self.paths.pop((pathTile, otherTile), None)
                            # self.paths.pop((otherTile, pathTile), None)
                            # ignorePairs.add((pathTile, tile))
                            # ignorePairs.add((tile, pathTile))
                            # ignorePairs.add((pathTile, otherTile))
                            # ignorePairs.add((otherTile, pathTile))

                    if skip:
                        ignorePairs.add((otherTile, tile))
                        continue

                    self.paths[pair] = path

        self.frontiers.discard(self.start)

        logbook.info(f' graph connected in {time.perf_counter() - start:.4f}s')

        # start = time.perf_counter()
        # mst = nx.minimum_spanning_tree(self.nxGraph, algorithm='kruskal')
        # logbook.info(f' mst calced in {time.perf_counter() - start:.4f}s')
        # self.mst_set = {self.map.get_tile_by_tile_index(t) for t in mst}
        # logbook.info(f' mst retrieved in {time.perf_counter() - start:.4f}s')


def mst_heuristic(remaining_tiles, start_tile, apsp):
    from itertools import combinations
    if not remaining_tiles:
        return 0

    vertices = [start_tile] + list(remaining_tiles)
    min_cost = float('inf')

    for edges in combinations(vertices, 2):
        u, v = edges
        cost = apsp[u][v]
        min_cost = min(min_cost, cost)

    return min_cost


def tsp_heuristic(remaining_tiles, start_tile, apsp):
    from itertools import permutations
    if not remaining_tiles:
        return 0

    vertices = [start_tile] + list(remaining_tiles)
    min_cost = float('inf')

    for perm in permutations(vertices):
        cost = 0
        for i in range(len(perm) - 1):
            cost += apsp[perm[i]][perm[i + 1]]
        min_cost = min(min_cost, cost)

    return min_cost
#
#
# # Example usage with heuristics
# remaining_tiles = set(Tile(x, y) for y in range(4) for x in range(4) if grid[y][x] == 0) - {start_tile}
# print("MST Heuristic:", mst_heuristic(remaining_tiles, start_tile, apsp))
# print("TSP Heuristic:", tsp_heuristic(remaining_tiles, start_tile, apsp))