from __future__ import  annotations

import heapq
import itertools
import time
import typing

import logbook
import networkx
import networkx as nx

import SearchUtils
from Algorithms import TravelingSalesmanUtils
from Interfaces import TileSet, MapMatrixInterface
from MapMatrix import MapMatrix
from Path import Path
from base.client.map import MapBase
from base.client.tile import Tile


def get_watchman_path(map: MapBase, startTile: Tile, toDiscover: typing.Iterable[Tile], timeLimit: float = 1000.0) -> Path | None:
    """
    Will be updated with more efficient algorithms in future. Currently an optimized A* approach that searches
     tile by tile but compares against the frontier watchers of the disjoint pivot nodes that are at the extremes of the hunted territory.
    @param map:
    @param startTile:
    @param toDiscover:
    @param timeLimit:
    @return:
    """
    startTime = time.perf_counter()
    pivot_wrp = PivotWRP(startTile, map, set(toDiscover))
    path = pivot_wrp.solve(cutoffTime=startTime + timeLimit)
    completedTime = time.perf_counter() - startTime
    logbook.info(f'Watchman path length {path.length} found in {completedTime:.4f}s')
    return path


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
            h_singleton = max(h_singleton, min(self.map.get_distance_between(node.tile, t) for t in tile.adjacents if not t.isObstacle and not (t.isCity and t.isTempFogPrediction)))

        return h_singleton

    def solve(self) -> Path | None:
        current_f: float
        current_node: BasicAStarNode

        discoverLen = len(self.to_discover)
        bestPath = None
        iteration = 0
        while self.open_list:
            iteration += 1
            current_f, current_node = heapq.heappop(self.open_list)
            if iteration & 1023 == 0:
                logbook.info(f'iter {iteration}, open {len(self.open_list)}, closed {len(self.closed_set)}, current {current_node.tile} (unseen {len(current_node.unseen)}, cost so far {current_node.cost_so_far}, est total {current_node.total_estimated_cost})')
            if not current_node.unseen:
                bestPath = current_node.path
                break

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

        if not bestPath:
            return None

        finalPath = Path()
        for t in bestPath:
            finalPath.add_next(t)

        return finalPath


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
        return (self.total_estimated_cost, 0-self.cost_so_far) < (other.total_estimated_cost, 0-other.cost_so_far)


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
        return (self.total_estimated_cost, 0-self.cost_so_far) < (other.total_estimated_cost, 0-other.cost_so_far)


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
        self.all_pairs_shortest_paths: typing.Dict[typing.Tuple[Tile, Tile], typing.List[Tile]] = None
        self.longest_crossing: int = 20
        """This is the max value our expensive heuristic value could ever return. So if we can shortcircuit the expensive heuristic stuff, then we should speed some stuff up."""
        # self.mst_set: typing.Set[Tile] = None
        # self.tsp_set: typing.Set[Tile] = None
        self.nxGraph: nx.Graph = None

        self.build_frontiers()

        # TODO once adding the TSP or MST heuristic with Jump Frontier Search
        # self.connect_graph()

        # nonComp = self.to_discover.difference(itertools.chain.from_iterable(c.frontier_nodes for c in self.components))
        # nonComp.difference_update(c.pivot for c in self.components)

        self.start_node: FrontierAStarNode = None

    def heuristic(self, node: FrontierAStarNode) -> float:
        # Singleton Heuristic; this is quite expensive, something like n^2
        h_singleton = 0

        # any move into the fog can reveal at most 3 new tiles (assuming we move 1 tile at a time).
        h_singleton = max(h_singleton, len(node.unseen) // 3)

        if h_singleton >= self.longest_crossing:
            # logbook.info(f'took advantage of longest crossing')
            return h_singleton

        dmapper = self.map.distance_mapper
        # 19 seconds for 20 when always use components
        for component in node.unseen_components:
            # THIS HEURISTIC IS ALWAYS OPTIMAL WITH THE -1, DO NOT remove the -1, the heuristic MUST NEVER over-estimate
            # h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile) - 2)
            # THIS HEURISTIC IS ALWAYS OPTIMAL. FASTER!?
            h_singleton = max(h_singleton, min(dmapper.get_distance_between_dual_cache(t, node.tile) for t in component.frontier_nodes))

        # # 16 s (-2)
        # for component in node.unseen_components:
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL WITH THE -2, DO NOT remove the -2, the heuristic MUST NEVER over-estimate
        #     h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile) - 2)
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL. FASTER!?
        #     # h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes))

        # # 16 s (-1)
        # for component in node.unseen_components:
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL WITH THE -2, DO NOT remove the -2, the heuristic MUST NEVER over-estimate
        #     h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile) - 1)
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL. FASTER!?
        #     # h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes))

        # # 16 s (-0)
        # for component in node.unseen_components:
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL WITH THE -2, DO NOT remove the -2, the heuristic MUST NEVER over-estimate
        #     h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile))
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL. FASTER!?
        #     # h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes))

        # if len(node.unseen_components) > 3:
        #     for component in node.unseen_components:
        #         # THIS HEURISTIC DOESNT UNDERSTAND THAT YOU CAN SEE ACROSS DIAGONAL TO TILES AND THUS WILL PRODUCE BAD PLANS
        #         # h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile) - 2)
        #         # THIS HEURISTIC IS ALWAYS OPTIMAL. FASTER!?
        #         h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes))
        # # elif len(node.unseen_components) > 3:
        # # # else:
        # #     for component in node.unseen_components:
        # #         # h_singleton = max(h_singleton, self.map.get_distance_between(component.pivot, node.tile))
        # #         h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in component.frontier_nodes))
        # else:
        #     # THIS HEURISTIC IS ALWAYS OPTIMAL. SLOW, THOUGH.
        #     for tile in node.unseen:
        #         h_singleton = max(h_singleton, min(self.map.get_distance_between(t, node.tile) for t in tile.adjacents if not t.isObstacle and not (t.isCity and t.isTempFogPrediction)))

        return h_singleton

    def solve(self, cutoffTime: float | None = None) -> Path | None:
        current_f: float
        current_node: FrontierAStarNode
        start = time.perf_counter()

        bestTurns = -1
        bestPath = None
        bestUnseen = 1000
        # bestUnseenReductionPerTurn = 0

        logbook.info(f'longest crossing {self.longest_crossing}')

        if not cutoffTime:
            cutoffTime = time.perf_counter() + 1000
        self.start_node = FrontierAStarNode(tile=self.start, unseen=self.to_discover, unseenComponents=self.components.copy())
        heapq.heappush(self.open_list, (self.start_node.total_estimated_cost, self.start_node))
        openList = self.open_list
        closedSet = self.closed_set
        iteration = 0
        while openList:
            iteration += 1
            current_f, current_node = heapq.heappop(openList)

            unseenCount = len(current_node.unseen)
            if unseenCount == 0:
                bestPath = current_node.path
                # return current_node.path
                break

            if unseenCount < bestUnseen:
                bestTurns = len(current_node.path) - 1
                bestPath = current_node.path
                bestUnseen = unseenCount

            if iteration & 127 == 0:
                if cutoffTime < time.perf_counter():
                    logbook.info(f'watchman a* terminating early after {time.perf_counter() - start:.4f}s with {bestUnseen} unseen still and length {len(current_node.path)} length.')
                    break

            if iteration & 1023 == 0:
                logbook.info(f'iter {iteration}, open {len(openList)}, closed {len(closedSet)}, current {current_node.tile} (unseenComp {len(current_node.unseen_components)}, unseen {len(current_node.unseen)}, cost so far {current_node.cost_so_far}, est total {current_node.total_estimated_cost})')

            # if len(current_node.unseen_components) == 0 and len(current_node.unseen) > 0:
            #     logbook.info(f'unseen components 0, but unseen: {current_node.unseen}')

            closedSet.add(current_node)

            for neighbor in current_node.tile.movable:
                if neighbor.isObstacle or (neighbor.isCity and neighbor.isTempFogPrediction):  # Don't let it path through uncertain predicted cities as those are unlikely to ACTUALLY be routable.
                    continue

                component = self.component_lookup.raw[neighbor.tile_index]

                unseenComp = current_node.unseen_components
                if component:
                    unseenComp = unseenComp.difference((component,))

                # newPath = current_node.path.copy()
                # newPath.append(neighbor)
                newPath = current_node.path + [neighbor]

                # diff = t for t in neighbor.adjacents if

                neighbor_node = FrontierAStarNode(
                    neighbor,
                    # current_node.seen.union(neighbor.adjacents),
                    current_node.unseen.difference(neighbor.adjacents),
                    unseenComp,
                    # current_node.unseen_components,
                    newPath,
                    current_node.cost_so_far + 1)  # actual cost is always 1.

                if neighbor_node in closedSet:
                    continue

                neighbor_node.heuristic_cost_remaining = self.heuristic(neighbor_node)
                neighbor_node.total_estimated_cost = neighbor_node.cost_so_far + neighbor_node.heuristic_cost_remaining

                # if neighbor_node not in openList:  # The fuck, chatgpt? There is NO WAY we are supposed to do this. MAYBE we make a set of open entries to prevent adding duplicates, though.
                heapq.heappush(openList, (neighbor_node.total_estimated_cost, neighbor_node))

        if not bestPath:
            return None

        finalPath = Path()
        for t in bestPath:
            finalPath.add_next(t)

        return finalPath

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

            if len(componentWatchers) == 0:
                raise AssertionError(f'no watchers for {pivot}???')

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
        self.all_pairs_shortest_paths = {}
        ignorePairs = set()
        self.longest_crossing = 0

        logbook.info(f' graph before connecting: {self.nxGraph}')
        # ALL PAIRS SHORTEST PATHS, BUT ONLY FOR FRONTIERS
        for tile in self.frontiers:
            for otherTile in self.frontiers:
                if tile is otherTile:
                    continue

                pair = (tile, otherTile)
                if pair in ignorePairs:
                    continue

                existingPath = self.all_pairs_shortest_paths.get((otherTile, tile), None)
                if existingPath:
                    self.all_pairs_shortest_paths[pair] = existingPath
                    continue

                path = SearchUtils.a_star_find_raw_with_try_avoid([tile], otherTile, tryAvoid=self.frontiers, maxDepth=200, noLog=True)
                pathLen = len(path) - 1
                if pathLen > self.longest_crossing:
                    self.longest_crossing = pathLen

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

                    self.all_pairs_shortest_paths[pair] = path
                    self.nxGraph.add_edge(tile.tile_index, otherTile.tile_index, weight=len(path) - 1)

        self.frontiers.discard(self.start)

        logbook.info(f' graph connected (APSP frontiers) in {time.perf_counter() - start:.4f}s {self.nxGraph}')

        # start = time.perf_counter()
        # mst = nx.minimum_spanning_tree(self.nxGraph, algorithm='kruskal')
        # logbook.info(f' mst calced in {time.perf_counter() - start:.4f}s')
        # self.mst_set = {self.map.get_tile_by_tile_index(t) for t in mst}
        # logbook.info(f' mst retrieved in {time.perf_counter() - start:.4f}s')

    def get_tsp_path(self) -> Path | None:
        self.connect_graph()

        tileIndexList = TravelingSalesmanUtils.solve_tsp_path_nx_raw(self.map, self.nxGraph, self.pivot_set, self.start)
        if not tileIndexList:
            return None

        path = Path()
        prev = None
        for t in tileIndexList:
            tile = self.map.get_tile_by_tile_index(t)
            # if tile in self.pivot_set:
            #     continue
            # if tile is self.start:
            #     continue

            if prev:
                actualPath = self.all_pairs_shortest_paths.get((prev, tile), None)
                if not actualPath:
                    logbook.info(f'tsp MISSING ({prev} -> {tile})')
                    continue

                if actualPath[0] != prev:
                    actualPath = reversed(actualPath)

                for pathTile in actualPath:
                    logbook.info(f'tsp adding {pathTile} ({prev} -> {tile})')
                    path.add_next(pathTile)

            prev = tile

        logbook.info(f'TSP path {path}')
        return path


class PivotIterativeWRP(PivotWRP):
    def __init__(self, start: Tile, map: MapBase, toDiscover: typing.Set[Tile], noLog: bool = True):
        super().__init__(start, map, toDiscover, noLog)

    def solve(self, cutoffTime: float | None = None) -> Path | None:
        current_f: float
        current_node: FrontierAStarNode

        bestPath = None
        bestUnseen = 1000
        # bestUnseenReductionPerTurn = 0

        if not cutoffTime:
            cutoffTime = time.perf_counter() + 1000

        cutoffThresh = 1000
        w = 2
        start = time.perf_counter()
        lastStart = start

        while w >= 1.0:
            start_node = FrontierAStarNode(tile=self.start, unseen=self.to_discover, unseenComponents=self.components.copy())
            openList = []
            heapq.heappush(openList, (start_node.total_estimated_cost, start_node))
            closedSet = set()
            iteration = 0
            lenThreshs = [i + (cutoffThresh - i) * w for i in range(cutoffThresh + 2)]

            while openList:
                iteration += 1
                current_f, current_node = heapq.heappop(openList)

                unseenCount = len(current_node.unseen)
                if unseenCount == 0:
                    newLen = len(current_node.path) - 1
                    nextStart = time.perf_counter()
                    logbook.info(f'--iter {iteration} found len {newLen} (vs {cutoffThresh}) at w {w:.2f} after {nextStart - start:.5f}s ({nextStart - lastStart:.5f}s)')
                    lastStart = nextStart
                    if bestPath is None or newLen < cutoffThresh:
                        bestPath = current_node.path
                        cutoffThresh = newLen
                    # return current_node.path
                    break

                if unseenCount < bestUnseen:
                    bestTurns = len(current_node.path) - 1
                    bestPath = current_node.path
                    bestUnseen = unseenCount

                if iteration & 127 == 0:
                    if cutoffTime < time.perf_counter():
                        logbook.info(f'watchman a* terminating early with {bestUnseen} unseen still and length {len(current_node.path)} length.')
                        break

                if iteration & 1023 == 0:
                    logbook.info(f'iter {iteration}, open {len(openList)}, closed {len(closedSet)}, current {current_node.tile} (unseenComp {len(current_node.unseen_components)}, unseen {len(current_node.unseen)}, cost so far {current_node.cost_so_far}, est total {current_node.total_estimated_cost})')

                # if len(current_node.unseen_components) == 0 and len(current_node.unseen) > 0:
                #     logbook.info(f'unseen components 0, but unseen: {current_node.unseen}')

                closedSet.add(current_node)

                for neighbor in current_node.tile.movable:
                    if neighbor.isObstacle or (neighbor.isCity and neighbor.isTempFogPrediction):  # Don't let it path through uncertain predicted cities as those are unlikely to ACTUALLY be routable.
                        continue

                    component = self.component_lookup.raw[neighbor.tile_index]

                    unseenComp = current_node.unseen_components
                    if component:
                        unseenComp = unseenComp.difference((component,))

                    # newPath = current_node.path.copy()
                    # newPath.append(neighbor)
                    newPath = current_node.path + [neighbor]

                    # diff = t for t in neighbor.adjacents if

                    neighbor_node = FrontierAStarNode(
                        neighbor,
                        # current_node.seen.union(neighbor.adjacents),
                        current_node.unseen.difference(neighbor.adjacents),
                        unseenComp,
                        # current_node.unseen_components,
                        newPath,
                        current_node.cost_so_far + 1)  # actual cost is always 1.

                    if neighbor_node in closedSet:
                        continue

                    neighbor_node.heuristic_cost_remaining = self.heuristic(neighbor_node) * w

                    neighbor_node.total_estimated_cost = neighbor_node.cost_so_far + neighbor_node.heuristic_cost_remaining
                    if neighbor_node.total_estimated_cost >= lenThreshs[neighbor_node.cost_so_far]:
                        continue

                    # if neighbor_node not in openList:  # The fuck, chatgpt? There is NO WAY we are supposed to do this. MAYBE we make a set of open entries to prevent adding duplicates, though.
                    heapq.heappush(openList, (neighbor_node.total_estimated_cost, neighbor_node))

            w //= 2
            self.open_list = openList
            self.closed_set = closedSet
            self.start_node = start_node

        if not bestPath:
            return None

        finalPath = Path()
        for t in bestPath:
            finalPath.add_next(t)

        return finalPath

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