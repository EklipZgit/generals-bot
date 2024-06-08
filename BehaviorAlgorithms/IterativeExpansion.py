from __future__ import annotations

import heapq
import itertools
import random
import time
import typing
from collections import deque
from enum import Enum

import logbook
import networkx as nx

import DebugHelper
import GatherUtils
import SearchUtils
from Interfaces.MapMatrixInterface import EmptySet
from MapMatrix import MapMatrix
from Path import Path
from SearchUtils import HeapQueue
from Algorithms import TileIslandBuilder, TileIsland
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Interfaces import MapMatrixInterface, TileSet
from PerformanceTimer import PerformanceTimer
from ViewInfo import ViewInfo, TargetStyle, PathColorer
from base import Colors
from base.client.map import MapBase, Tile


ITERATIVE_EXPANSION_EN_CAP_VAL = 2.2


class IslandCompletionInfo(object):
    def __init__(self, island: TileIsland):
        self.tiles_left: int = island.tile_count
        self.army_left: int = island.sum_army


FlowExpansionPlanOption = GatherUtils.GatherCapturePlan


#
# class FlowExpansionPlanOption(TilePlanInterface):
#     def __init__(self, moveList: typing.List[Move] | None, econValue: float, turns: int, captures: int, armyRemaining: int):
#         self.moves: typing.List[Move] = moveList
#         self._tileSet: typing.Set[Tile] | None = None
#         self._tileList: typing.List[Tile] | None = None
#         self._econ_value: float = econValue
#         self._turns: int = turns
#         self.num_captures: int = captures
#         """The number of tiles this plan captures."""
#         self.armyRemaining: int = armyRemaining
#
#     @property
#     def length(self) -> int:
#         return self._turns
#
#     @property
#     def econValue(self) -> float:
#         return self._econ_value
#
#     @econValue.setter
#     def econValue(self, value: float):
#         self._econ_value = value
#
#     @property
#     def tileSet(self) -> typing.Set[Tile]:
#         if self._tileSet is None:
#             self._tileSet = set()
#             for move in self.moves:
#                 self._tileSet.add(move.source)
#                 self._tileSet.add(move.dest)
#         return self._tileSet
#
#     @property
#     def tileList(self) -> typing.List[Tile]:
#         if self._tileList is None:
#             self._tileList = []
#             for move in self.moves:
#                 self._tileList.append(move.source)
#                 self._tileList.append(move.dest)
#         return self._tileList
#
#     @property
#     def requiredDelay(self) -> int:
#         return 0
#
#     def get_move_list(self) -> typing.List[Move]:
#         return self.moves
#
#     def get_first_move(self) -> Move:
#         return self.moves[0]
#
#     def pop_first_move(self) -> Move:
#         move = self.moves[0]
#         self.moves.remove(move)
#         return move
#
#     def __str__(self):
#         return f'flow {self.econValue:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt) cap {self.num_captures}, rA {self.armyRemaining}: {self.moves}'
#
#     def __repr__(self):
#         return str(self)
#
#     def clone(self) -> FlowExpansionPlanOption:
#         clone = FlowExpansionPlanOption(
#             self.moves.copy(),
#             self.econValue,
#             self._turns,
#             self.num_captures,
#             self.armyRemaining)
#         return clone


class FlowGraphMethod(Enum):
    NetworkSimplex = 1,
    CapacityScaling = 2,
    MinCostFlow = 3


class FlowExpansionVal(object):
    def __init__(self, distSoFar: int, armyGathered: int, tilesLeftToCap: int, armyLeftToCap: int, islandInfo: IslandCompletionInfo):
        self.dist_so_far: int = distSoFar
        self.army_gathered: int = armyGathered
        self.tiles_left_to_cap: int = tilesLeftToCap
        self.army_left_to_cap: int = armyLeftToCap
        self.island_info: IslandCompletionInfo = islandInfo
        self.incidental_tile_capture_points: int = 0
        self.incidental_neutral_caps: int = 0
        self.incidental_enemy_caps: int = 0

    def __lt__(self, other: FlowExpansionVal | None) -> bool:
        if self.dist_so_far != other.dist_so_far:
            return self.dist_so_far < other.dist_so_far
        if self.incidental_tile_capture_points != other.incidental_tile_capture_points:
            return self.incidental_tile_capture_points < other.incidental_tile_capture_points
        if self.army_gathered != other.army_gathered:
            return self.army_gathered < other.army_gathered
        if self.tiles_left_to_cap != other.tiles_left_to_cap:
            return self.tiles_left_to_cap < other.tiles_left_to_cap
        if self.army_left_to_cap != other.army_left_to_cap:
            return self.army_left_to_cap < other.army_left_to_cap
        return False

    def __gt__(self, other: FlowExpansionVal | None) -> bool:
        return not self < other

    def __str__(self) -> str:
        return str(self.__dict__)

    # def __eq__(self, other) -> bool:
    #     if other is None:
    #         return False
    #     return self.x == other.x and self.y == other.y


class IslandFlowNode(object):
    def __init__(self, island: TileIsland, desiredArmy: int):
        self.island: TileIsland = island
        self.desired_army: int = desiredArmy
        """Negative if wishes to send army (friendly), positive if wishes to receive army (enemy/neutral)"""
        self.army_flow_received: int = 0
        self.flow_to: typing.List[IslandFlowEdge] = []

    def base_str(self) -> str:
        return f'{{t{self.island.team}:{self.island.unique_id}/{self.island.name} {self.island.tile_count}t {self.island.sum_army}a ({next(i for i in self.island.tile_set)})}}'

    def __str__(self) -> str:
        targets = [f'({n.edge_army}) {{t{n.target_flow_node.island.team}:{n.target_flow_node.island.unique_id}/{n.target_flow_node.island.name} ({next(i for i in n.target_flow_node.island.tile_set)})}}' for n in self.flow_to]
        flowStr = ''
        if targets:
            flowStr = f' (-> {" | ".join(targets)})'
        return f'{self.base_str()}{flowStr}'

    def __repr__(self) -> str:
        targets = [f'({n.edge_army}) {repr(n.target_flow_node)}' for n in self.flow_to]
        flowStr = ''
        if targets:
            flowStr = f' (-> {" | ".join(targets)})'
        return f'{self.base_str()}{flowStr}'

    def copy(self) -> IslandFlowNode:
        clone = IslandFlowNode(self.island, self.desired_army)
        clone.flow_to = [e.copy() for e in self.flow_to]
        return clone

    def set_flow_to(self, destNode: IslandFlowNode, edgeArmy: int) -> bool:
        """
        returns true if the edge was added, false if the edge existed and was updated.

        @param destNode:
        @param edgeArmy:
        @return:
        """
        existingEdge = SearchUtils.where(self.flow_to, lambda e: e.target_flow_node.island.unique_id == destNode.island.unique_id)
        if existingEdge:
            if destNode != existingEdge[0].target_flow_node:
                raise Exception(f'Corrupt flow nodes in add_edge. destNode and existingEdge target nodes were not equal, despite being for the same island. {existingEdge[0]}  |  {destNode}')
            existingEdge[0].edge_army = edgeArmy
            return False
        else:
            self.flow_to.append(IslandFlowEdge(destNode, edgeArmy))
            return True


class IslandFlowEdge(object):
    def __init__(self, targetIslandFlowNode: IslandFlowNode, edgeArmy: int):
        self.target_flow_node: IslandFlowNode = targetIslandFlowNode
        self.edge_army: int = edgeArmy

    def __str__(self) -> str:
        return f'({self.edge_army}) {self.target_flow_node}'

    def __repr__(self) -> str:
        return str(self)

    def copy(self) -> IslandFlowEdge:
        return IslandFlowEdge(self.target_flow_node.copy(), self.edge_army)


class IslandMaxFlowGraph(object):
    def __init__(
        self,
        ourRootNoNeutFlowNodes: typing.List[IslandFlowNode],
        ourRootNeutFlowNodes: typing.List[IslandFlowNode],
        enemyBackfillNoNeutFlowNodes: typing.List[IslandFlowNode],
        enemyBackfillNeutFlowNodes: typing.List[IslandFlowNode],
        enemyBackfillNeutEdges: typing.List[IslandFlowEdge],
        enemyBackfillNeutNoNeutEdges: typing.List[IslandFlowEdge],
        flowNodeLookupNoNeut: MapMatrixInterface[IslandFlowNode],
        flowNodeLookupIncNeut: MapMatrixInterface[IslandFlowNode],
        flowNodeIslandIdLookupNoNeut: typing.Dict[int, IslandFlowNode],
        flowNodeIslandIdLookupIncNeut: typing.Dict[int, IslandFlowNode],
    ):
        self.root_flow_nodes_no_neut: typing.List[IslandFlowNode] = ourRootNoNeutFlowNodes
        self.root_flow_nodes_inc_neut: typing.List[IslandFlowNode] = ourRootNeutFlowNodes

        self.enemy_backfill_nodes_no_neut: typing.List[IslandFlowNode] = enemyBackfillNoNeutFlowNodes
        self.enemy_backfill_nodes_inc_neut: typing.List[IslandFlowNode] = enemyBackfillNeutFlowNodes

        self.enemy_backfill_neut_dump_edges: typing.List[IslandFlowEdge] = enemyBackfillNeutEdges
        self.enemy_backfill_neut_dump_edges_no_neut: typing.List[IslandFlowEdge] = enemyBackfillNeutNoNeutEdges

        self.flow_node_lookup_by_tile_no_neut: MapMatrixInterface[IslandFlowNode] = flowNodeLookupNoNeut
        self.flow_node_lookup_by_tile_inc_neut: MapMatrixInterface[IslandFlowNode] = flowNodeLookupIncNeut

        self.flow_node_lookup_by_island_no_neut: typing.Dict[int, IslandFlowNode] = flowNodeIslandIdLookupNoNeut
        self.flow_node_lookup_by_island_inc_neut: typing.Dict[int, IslandFlowNode] = flowNodeIslandIdLookupIncNeut

    # def copy(self) -> IslandMaxFlowGraph:
    #     """
    #     Clones the lists and island flownodes / island flow edges, but not the islands
    #     @return:
    #     """
    #
    #     clone = IslandMaxFlowGraph(None,None,None,None,None,None,None, None)
    #
    #     return clone


def _deep_copy_flow_nodes(rootNodes: typing.Iterable[IslandFlowNode], cloneScopeLookup: typing.Dict[int, IslandFlowNode]) -> typing.Iterable[IslandFlowNode]:
    """
    returns an iterable on deep copies of the original root nodes (in their original order). Reuses nodes from, and backfills, the cloneScopeLookup node table.

    Infinite loops if there are cycles.
    """
    q: typing.List[typing.Tuple[IslandFlowNode | None, int, IslandFlowNode]] = []
    """fromCloneNode, toOriginalNode"""
    for r in rootNodes:
        q.append((None, 0, r))

    while q:
        sourceClone, flowAmt, destOriginal = q.pop()
        destId = destOriginal.island.unique_id
        destClone = cloneScopeLookup.get(destId, None)
        if destClone is None:
            destClone = IslandFlowNode(destOriginal.island, destOriginal.desired_army)
            cloneScopeLookup[destId] = destClone

        if sourceClone is not None:
            sourceClone.set_flow_to(destClone, flowAmt)

        for destEdge in destOriginal.flow_to:
            q.append((destClone, destEdge.edge_army, destEdge.target_flow_node))

    nodeIterable = (cloneScopeLookup[r.island.unique_id] for r in rootNodes)
    return nodeIterable


def _deep_copy_flow_node(rootNode: IslandFlowNode, cloneScopeLookup: typing.Dict[int, IslandFlowNode]) -> IslandFlowNode:
    """
    Infinite loops if there are cycles. Reuses nodes from, and backfills, the cloneScopeLookup node table.
    """
    q: typing.List[typing.Tuple[IslandFlowNode | None, int, IslandFlowNode]] = []
    """fromCloneNode, toOriginalNode"""

    q.append((None, 0, rootNode))

    while q:
        sourceClone, flowAmt, destOriginal = q.pop()
        destId = destOriginal.island.unique_id
        destClone = cloneScopeLookup.get(destId, None)
        if destClone is None:
            destClone = IslandFlowNode(destOriginal.island, destOriginal.desired_army)
            cloneScopeLookup[destId] = destClone

        if sourceClone is not None:
            sourceClone.set_flow_to(destClone, flowAmt)

        for destEdge in destOriginal.flow_to:
            q.append((destClone, destEdge.edge_army, destEdge.target_flow_node))

    return cloneScopeLookup[rootNode.island.unique_id]


class NxFlowGraphData(object):
    def __init__(self, graph: nx.DiGraph, neutSinks: typing.Set[int], demands: typing.Dict[int, int], cumulativeDemand: int, fakeNodes: typing.Set[int] | None = None):
        self.graph: nx.DiGraph = graph

        self.neutral_sinks: typing.Set[int] = neutSinks
        """The set of neutral-sink TileIsland unique_ids used in this graph. This is the set of all outskirt neutral tile islands who the enemy generals overflow was allowed to help fill with zero cost."""

        self.demand_lookup: typing.Dict[int, int] = demands
        """Demand amount lookup by island unique_id. Negative demand = want to gather army, positive = want to capture with army"""

        self.cumulative_demand: int = cumulativeDemand
        """The cumulative demand (prior to adjusting the nxGraph by making enemy general / cities as graph balancing sinks). If negative, then we do not have enough standing army to fully flow the entire map (or the part this graph covers) by the negative amount of army."""

        self.fake_nodes: typing.Set[int] = fakeNodes
        if fakeNodes is None:
            self.fake_nodes = frozenset()


class FlowExpansionPlanOptionCollection(object):
    def __init__(self):
        self.flow_plans: typing.List[FlowExpansionPlanOption] = []
        self.best_plans_by_tile: MapMatrixInterface[FlowExpansionPlanOption] = None
        self.superset_flow_plans: typing.List[FlowExpansionPlanOption] = []


class ArmyFlowExpander(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.team: int = map.team_ids_by_player_index[map.player_index]
        self.friendlyGeneral: Tile = map.generals[map.player_index]
        self.target_team: int = -1
        self.enemyGeneral: Tile | None = None

        self.nxGraphData: NxFlowGraphData | None = None
        self.nxGraphDataNoNeut: NxFlowGraphData | None = None
        self.flow_graph: IslandMaxFlowGraph | None = None

        self.debug_render_capture_count_threshold: int = 10000
        """If there are more captures in any given plan option than this, then the option will be rendered inline as generated in a new debug viewer window."""

        self.log_debug: bool = False
        self.use_debug_asserts: bool = True

        # TODO determine if this should always be true when using use_min_cost_flow_edges_only=True
        self.use_all_pairs_visited: bool = False
        """If True, a global visited set will be used to avoid finding overlapping gathers from multiple contact points. If false (much slower) we will build a visited set per border with enemy land."""
        #
        # self.include_neutral_flow: bool = True
        # """Whether or not to allow flowing into neutral tiles. Make sure to set this before calling any methods on the class, as cached graph data will have already used or not used it once cached."""

        self.use_min_cost_flow_edges_only: bool = True
        """If true, use the min-cost-max-flow flownodes to route army. Otherwise, brute force / AStar."""

        self.use_back_pressure_from_enemy_general: bool = False
        """If True, lets the enemy general push back."""

        self.block_cross_gather_from_enemy_borders: bool = False
        """If true, tries to prevent criss-cross gathers that pull other border tiles to attack another border."""

    def get_expansion_options(
            self,
            islands: TileIslandBuilder,
            asPlayer: int,
            targetPlayer: int,
            turns: int,
            boardAnalysis: BoardAnalyzer,
            territoryMap: typing.List[typing.List[int]],
            negativeTiles: typing.Set[Tile] = None,
            leafMoves: typing.Union[None, typing.List[Move]] = None,
            viewInfo: ViewInfo = None,
            # valueFunc=None,
            # priorityFunc=None,
            # initFunc=None,
            # skipFunc=None,
            # boundFunc=None,
            # allowLeafMoves=True,
            # useLeafMovesFirst: bool = False,
            bonusCapturePointMatrix: MapMatrixInterface[float] | None = None,
            # colors: typing.Tuple[int, int, int] = (235, 240, 50),
            # additionalOptionValues: typing.List[typing.Tuple[float, int, Path]] | None = None,
            perfTimer: PerformanceTimer | None = None,
    ) -> FlowExpansionPlanOptionCollection:
        """
        The goal of this algorithm is to produce a maximal flow of army from your territory into target players friendly territories without overfilling them.
        Should produce good tile plan interface of estimated movements of army into enemy territory. Wont include all the tiles that will be captured in enemy territory since calculating that is pretty pointless.

        @param islands:
        @param asPlayer:
        @param targetPlayer:
        @param turns:
        @param boardAnalysis:
        @param territoryMap:
        @param negativeTiles:
        @param leafMoves:
        @param viewInfo:
        @param bonusCapturePointMatrix:
        @param perfTimer:
        @return:
        """
        startTiles: typing.Dict[Tile, typing.Tuple[FlowExpansionVal, int]] = {}
        # friendlyPlayers = self.map.get_teammates(asPlayer)
        # targetPlayers = self.map.get_teammates(targetPlayer)

        # blah = self.find_flow_plans_nx_maxflow(islands, ourIslands, targetIslands, asPlayer, turns, negativeTiles=negativeTiles)

        # self.flow_graph = self.build_max_flow_min_cost_flow_nodes(
        #     islands,
        #     ourIslands,
        #     targetIslands,
        #     searchingPlayer,
        #     turns,
        #     blockGatherFromEnemyBorders,
        #     negativeTiles
        # )

        plans = self.find_flow_plans(islands, asPlayer, targetPlayer, turns, negativeTiles=negativeTiles)

        start = time.perf_counter()

        finalPlans = self.filter_plans_by_common_supersets_and_sort(plans)
        logbook.info(f'finished pruning flow plans in {time.perf_counter() - start:.5f} additional seconds')
        return finalPlans

    def filter_plans_by_common_supersets_and_sort(self, plans: typing.List[FlowExpansionPlanOption]) -> FlowExpansionPlanOptionCollection:
        # this forces us to not eliminate longer larger gathers with tiny little leaf-move style captures.
        # Prio first by longer lengths, then by whether they had any captures, and THEN by econ value.
        plans.sort(key=lambda p: (p.length > 5, len(p.approximate_capture_tiles) > 1, p.econValue / p.length), reverse=True)

        finalPlans = []

        # unvisited = {t for t in self.map.pathableTiles}
        plansVisited: MapMatrixInterface[PlanDupeChecker] = MapMatrix(self.map, None)
        bestPlanByTile: MapMatrixInterface[FlowExpansionPlanOption | None] = MapMatrix(self.map, None)

        planSets = []

        debugTile = self.map.GetTile(7, 5)
        for plan in plans:
            if debugTile in plan.tileSet:
                pass
            planSet = None
            illegalPlan = False
            for tile in plan.tileSet:
                existing = plansVisited.raw[tile.tile_index]
                if existing is not None:
                    if planSet is not None and planSet != existing:
                        illegalPlan = True
                        if self.log_debug:
                            logbook.info(f'bypassed {plan.shortInfo()} due to crossover on {tile} with {existing} (and {planSet})')
                        break
                    planSet = existing

            if illegalPlan:
                continue

            newTiles = plan.tileSet
            if planSet is None:
                if self.log_debug:
                    logbook.info(f'BRAND NEW SETS {plan.shortInfo()}')
                planSet = PlanDupeChecker()
                planSets.append(planSet)
            else:
                diff = plan.tileSet.symmetric_difference(planSet.set)
                if len(diff) == 0:
                    if self.log_debug:
                        logbook.info(f'bypassed same but lower vt {plan.shortInfo()} due to exact tile match in {planSet}')
                    continue

                if diff.issubset(plan.tileSet):
                    newTiles = diff
                    if self.log_debug:
                        logbook.info(f'INCLUSION SUPERSET UPDATES FROM {planSet} to {plan.shortInfo()}')
                else:
                    newTiles = diff.intersection(plan.tileSet)
                    if self.log_debug:
                        logbook.info(f'INCLUSION SINGLE OVERLAP SETS {plan.shortInfo()} FOR JUST {[t for t in newTiles]}')

            planSet.plans.append(plan)
            planSet.set.update(newTiles)
            for tile in newTiles:
                plansVisited.raw[tile.tile_index] = planSet
                bestPlanByTile.raw[tile.tile_index] = plan

            if illegalPlan:
                continue

            if self.log_debug:
                logbook.info(f'INCLUDING {plan.shortInfo()}')
            finalPlans.append(plan)

        finalPlans = sorted(finalPlans, key=lambda p: (p.econValue / p.length, p.length), reverse=True)

        start = time.perf_counter()
        superSetPlans = []
        planContainer = FlowExpansionPlanOptionCollection()
        planContainer.flow_plans = finalPlans
        for planSet in planSets:
            planSet.plans.sort(key=lambda p: (p.length, p.econValue), reverse=True)

            unIncluded = planSet.set.copy()
            for flowPlan in planSet.plans:
                includeSuper = False
                for tile in flowPlan.tileSet:
                    if tile in unIncluded:
                        unIncluded.discard(tile)
                        includeSuper = True

                if includeSuper:
                    superSetPlans.append(flowPlan)
            #
            # exist = plansVisited.raw[tile.tile_index]
            # if exist is not None:
            #     # ignore warning, we're intentionally changing the type of the contents in the matrix
            #     plansVisited.raw[tile.tile_index] = exist.plan

        logbook.info(f'FlowExpansionPlanOptionCollection iterated all tiles in all plans in {time.perf_counter() - start:.5f}s')

        planContainer.best_plans_by_tile = bestPlanByTile
        planContainer.superset_flow_plans = superSetPlans

        return planContainer

    def find_flow_plans_nx_maxflow(
            self,
            islands: TileIslandBuilder,
            ourIslands: typing.List[TileIsland],
            targetIslands: typing.List[TileIsland],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: TileSet | None = None
    ) -> typing.List[FlowExpansionPlanOption]:
        self.ensure_flow_graph_exists(islands)
        flowGraph = self._build_max_flow_min_cost_flow_nodes(
            islands,
            ourIslands,
            targetIslands,
            searchingPlayer,
            turns,
            blockGatherFromEnemyBorders,
            negativeTiles
        )

        return []

    #
    # def ensure_min_cost_max_flow_graph_exists(self, islands: TileIslandBuilder):
    #     self.ensure_flow_graph_exists(islands)

    def _get_island_max_flow_dict(
            self,
            islands: TileIslandBuilder,
            graphData: NxFlowGraphData,
            method: FlowGraphMethod = FlowGraphMethod.NetworkSimplex
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        """Returns the flow dict produced from the input graph data"""
        start = time.perf_counter()

        flowCost: int = -1
        """The cost of the whole flow network that is output. Pretty useless to us."""
        flowDict: typing.Dict[int, typing.Dict[int, int]]
        """The lookup from a given node to a dictionary of target nodes (and the army to send across to those nodes)."""

        # TODO look at gomory_hu_tree - A Gomory-Hu tree of an undirected graph with capacities is a weighted tree that represents the minimum s-t cuts for all s-t pairs in the graph.
        #  probably useless because doesn't use weight.

        # TODO look at cd_index (Time dependent)

        # TODO look at random_tournament + other tournament methods like hamiltonian_path ?
        try:
            if method == FlowGraphMethod.NetworkSimplex:
                flowCost, flowDict = nx.flow.network_simplex(graphData.graph)
            elif method == FlowGraphMethod.CapacityScaling:
                flowCost, flowDict = nx.flow.capacity_scaling(graphData.graph)
            elif method == FlowGraphMethod.MinCostFlow:
                flowDict = nx.flow.min_cost_flow(graphData.graph)
            else:
                raise NotImplemented(str(method))
        except Exception as ex:
            # if DebugHelper.IS_DEBUGGING:
            self.live_render_invalid_flow_config(islands, graphData.graph, f'{ex}')
            raise

        logbook.info(f'{method} complete with flowCost {flowCost} in {time.perf_counter() - start:.5f}s')

        return flowDict

    def _build_max_flow_min_cost_flow_nodes(
            self,
            islands: TileIslandBuilder,
            ourIslands: typing.List[TileIsland],
            targetIslands: typing.List[TileIsland],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: TileSet | None = None,
            includeNeutralDemand: bool = False,
            method: FlowGraphMethod = FlowGraphMethod.NetworkSimplex
    ) -> IslandMaxFlowGraph:
        """Returns the list of root IslandFlowNodes that have nothing that flows in to them. The entire graph can be traversed from the root nodes (from possibly multiple directions)."""

        withNeutFlowDict = self._get_island_max_flow_dict(islands, self.nxGraphData, method)
        noNeutFlowDict = self._get_island_max_flow_dict(islands, self.nxGraphDataNoNeut, method)

        start = time.perf_counter()

        targetGeneralIsland: TileIsland = islands.tile_island_lookup.raw[self.enemyGeneral.tile_index]

        withNeutGraphLookup: typing.Dict[int, IslandFlowNode] = {}
        noNeutGraphLookup: typing.Dict[int, IslandFlowNode] = {}

        for island in islands.all_tile_islands:
            demandNoNeut = self.nxGraphDataNoNeut.demand_lookup[island.unique_id]
            flowNodeNoNeut = IslandFlowNode(island, demandNoNeut)
            noNeutGraphLookup[island.unique_id] = flowNodeNoNeut

            demandWithNeut = self.nxGraphData.demand_lookup[island.unique_id]
            flowNodeWithNeut = IslandFlowNode(island, demandWithNeut)
            withNeutGraphLookup[island.unique_id] = flowNodeWithNeut

        backfillNeutEdges = []
        ourSet = {i.unique_id for i in ourIslands}
        targetSet = {i.unique_id for i in targetIslands}

        # first see what ALWAYS goes to enemy territory, these are our highest priority to gather things.
        for nodeId, targets in withNeutFlowDict.items():
            isThroughput = False
            if nodeId > 0:
                isThroughput = True
                # we don't care about the movement of army through a node so skip the input -> output entries
            else:
                nodeId = -nodeId

            if nodeId in self.nxGraphData.fake_nodes:
                continue

            sourceNode = withNeutGraphLookup[nodeId]

            for targetNodeId, targetFlowAmount in targets.items():
                if isThroughput:
                    if targetNodeId != -nodeId:
                        raise AssertionError(f'input node flowed to something other than output node...?  {sourceNode} ({targetFlowAmount}a) -> {targetNodeId}')
                    sourceNode.army_flow_received = targetFlowAmount
                    continue
                if targetFlowAmount == 0:
                    # raise AssertionError(f'wut? Connection, but zero flow between  {sourceNode} ({targetFlowAmount}a) -> {targetNodeId}')
                    # logbook.info(f'wut? Connection, but zero flow between  {sourceNode} ({targetFlowAmount}a) -> {targetNodeId}')
                    continue
                ourSet.discard(targetNodeId)
                targetSet.discard(targetNodeId)
                targetNode = withNeutGraphLookup[targetNodeId]
                if targetNodeId in self.nxGraphData.neutral_sinks and sourceNode.island is targetGeneralIsland:
                    edge = IslandFlowEdge(targetNode, targetFlowAmount)
                    backfillNeutEdges.append(edge)
                    continue

                sourceNode.set_flow_to(targetNode, targetFlowAmount)
                if self.log_debug:
                    logbook.info(f'FOUND INC NEUT FLOW EDGE {sourceNode} ({targetFlowAmount}a) -> {targetNode}')

        finalRootFlowNodes = [withNeutGraphLookup[id] for id in ourSet]
        enemyBackfillFlowNodes = [withNeutGraphLookup[id] for id in targetSet]

        backfillNeutNoNeutEdges = []
        ourSetNoNeut = {i.unique_id for i in ourIslands}
        targetSetNoNeut = {i.unique_id for i in targetIslands}

        # first see what ALWAYS goes to enemy territory, these are our highest priority to gather things.
        for nodeId, targets in noNeutFlowDict.items():
            isThroughput = False
            if nodeId > 0:
                isThroughput = True
                # we don't care about the movement of army through a node so skip the input -> output entries
            else:
                nodeId = -nodeId

            if nodeId in self.nxGraphDataNoNeut.fake_nodes:
                continue

            sourceNode = noNeutGraphLookup[nodeId]

            for targetNodeId, targetFlowAmount in targets.items():
                if isThroughput:
                    if targetNodeId != -nodeId:
                        raise AssertionError(f'input node flowed to something other than output node...?  {sourceNode} ({targetFlowAmount}a) -> {targetNodeId}')
                    sourceNode.army_flow_received = targetFlowAmount
                    continue
                if targetFlowAmount == 0:
                    # raise AssertionError(f'wut? Connection, but zero flow between  {sourceNode} ({targetFlowAmount}a) -> {targetNodeId}')
                    # logbook.info(f'wut? Connection, but zero flow between  {sourceNode} ({targetFlowAmount}a) -> {targetNodeId}')
                    continue
                ourSetNoNeut.discard(targetNodeId)
                targetSetNoNeut.discard(targetNodeId)
                targetNode = noNeutGraphLookup[targetNodeId]
                if targetNodeId in self.nxGraphDataNoNeut.neutral_sinks and sourceNode.island is targetGeneralIsland:
                    # raise AssertionError(f'wut? shouldnt have backfill neut edges here? No demand allowed on neuts?   {sourceNode} ({targetFlowAmount}a) -> {targetNode}')
                    edge = IslandFlowEdge(targetNode, targetFlowAmount)
                    backfillNeutNoNeutEdges.append(edge)
                    continue

                sourceNode.set_flow_to(targetNode, targetFlowAmount)
                if self.log_debug:
                    logbook.info(f'FOUND NO-NEUT FLOW EDGE {sourceNode} ({targetFlowAmount}a) -> {targetNode}')

        finalRootNoNeutFlowNodes = [noNeutGraphLookup[id] for id in ourSetNoNeut]
        enemyBackfillNoNeutFlowNodes = [noNeutGraphLookup[id] for id in targetSetNoNeut]

        noNeutFlowNodeLookup: MapMatrixInterface[IslandFlowNode] = MapMatrix(self.map, None)
        incNeutFlowNodeLookup: MapMatrixInterface[IslandFlowNode] = MapMatrix(self.map, None)
        for flowNode in withNeutGraphLookup.values():
            for t in flowNode.island.tile_set:
                incNeutFlowNodeLookup.raw[t.tile_index] = flowNode
        for flowNode in noNeutGraphLookup.values():
            for t in flowNode.island.tile_set:
                noNeutFlowNodeLookup.raw[t.tile_index] = flowNode

        flowGraph = IslandMaxFlowGraph(finalRootNoNeutFlowNodes, finalRootFlowNodes, enemyBackfillNoNeutFlowNodes, enemyBackfillFlowNodes, backfillNeutEdges, backfillNeutNoNeutEdges, noNeutFlowNodeLookup, incNeutFlowNodeLookup, withNeutGraphLookup, noNeutGraphLookup)

        logbook.info(f'{method} FlowNodes complete in {time.perf_counter() - start:.5f}s')
        return flowGraph

    def find_flow_plans(
            self,
            islands: TileIslandBuilder,
            searchingPlayer: int,
            targetPlayer: int,
            turns: int,
            negativeTiles: TileSet | None = None
    ) -> typing.List[FlowExpansionPlanOption]:
        """
        Build a plan of which islands should flow into which other islands.
        This is basically a bi-directional search from all borders between islands, and currently brute forces all possible combinations.

        @param islands:
        @param searchingPlayer:
        @param targetPlayer:
        @param turns:
        @param negativeTiles:
        @return:
        """

        start = time.perf_counter()

        opts: typing.Dict[typing.Tuple[TileIsland, TileIsland], typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]]] = {}
        """"""

        self.team = myTeam = self.map.team_ids_by_player_index[searchingPlayer]
        self.target_team = targetTeam = self.map.team_ids_by_player_index[targetPlayer]

        ourIslands = islands.tile_islands_by_player[searchingPlayer]
        targetIslands = islands.tile_islands_by_team_id[targetTeam]

        if self.use_min_cost_flow_edges_only:
            self.ensure_flow_graph_exists(islands)

            self.flow_graph = self._build_max_flow_min_cost_flow_nodes(
                islands,
                ourIslands,
                targetIslands,
                searchingPlayer,
                turns,
                # blockGatherFromEnemyBorders=
                includeNeutralDemand=True,
                negativeTiles=negativeTiles,
                # method=FlowGraphMethod.CapacityScaling  # 67ms on test_should_recognize_gather_into_top_path_is_best (with single-tile islands on borders)
                # method=FlowGraphMethod.MinCostFlow    # 6.5ms on test_should_recognize_gather_into_top_path_is_best (with single-tile islands on borders)
                # method=FlowGraphMethod.NetworkSimplex    # 9ms on test_should_recognize_gather_into_top_path_is_best (with single-tile islands on borders)
                method=FlowGraphMethod.MinCostFlow
            )

        turnsUsed: int

        targetCalculatedNode: IslandFlowNode
        friendlyUncalculatedNone: IslandFlowNode
        targetCalculated: TileIsland
        friendlyUncalculated: TileIsland
        turnsLeft: int
        numTilesLeftToCapFromTarget: int
        uncappedTargetIslandArmy: int
        frLeftoverArmy: int
        friendlyTileLeftoverIdx: int
        targetTiles: typing.Deque[int]
        """Uncaptured target tiles"""
        econValue: float
        visited: typing.Set[TileIsland]
        """This is NOT global, but per-border-island-pair"""
        nextTargets: typing.Dict[TileIsland, IslandFlowNode]
        nextFriendlies: typing.Dict[TileIsland, IslandFlowNode | None]
        rootNodes: typing.Dict[int, IslandFlowNode]
        pairOptions: typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]]
        """for each starting border pair, a new dict of distance -> (flowGraph, econValue, turnsUsed, armyRemainingTotal, incompleteTargetIsland or none, incompleteFriendlyIsland or none, unusedIncompleteSourceArmy, friendlyGatheredSum)"""

        maxTeam = max(self.map.team_ids_by_player_index)
        capValueByTeam = [1.0 for t in range(maxTeam + 2)]
        capValueByTeam[myTeam] = 0.0
        # TODO intentional decision for now to value flow expansion en caps lower than other expansion-fed algos do, to prioritize their more concrete results over these wishywashy results.
        capValueByTeam[targetTeam] = ITERATIVE_EXPANSION_EN_CAP_VAL

        if self.block_cross_gather_from_enemy_borders:
            friendlyBorderingEnemy = {i for i in itertools.chain.from_iterable(t.border_islands for t in targetIslands if t.tile_count_all_adjacent_friendly > 8) if i.team == myTeam}
        else:
            friendlyBorderingEnemy = set()

        q: SearchUtils.HeapQueueMax[typing.Tuple[
            float,
            int,
            int,
            int,
            int,
            typing.Deque[int],
            float,
            int,
            int,
            int,
            IslandFlowNode,
            IslandFlowNode,
            typing.Set[TileIsland],
            typing.Dict[TileIsland, IslandFlowNode],
            typing.Dict[TileIsland, IslandFlowNode],
            typing.Dict[int, IslandFlowNode],
            typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]],
        ]] = SearchUtils.HeapQueueMax()

        queueIterCount = 0
        tileIterCount = 0
        dumpIterCount = 0
        tieBreaker = 0

        globalVisited = set()

        for targetIsland in islands.all_tile_islands:
            if targetIsland.team == myTeam:
                continue
            for adjacentFriendlyIsland in targetIsland.border_islands:
                if adjacentFriendlyIsland.team != myTeam:
                    continue

                if not self._is_flow_allowed(adjacentFriendlyIsland, targetIsland, armyAmount=0):
                    continue

                tgCapValue = capValueByTeam[targetIsland.team]
                tieBreaker += 1
                pairOptions = {}
                opts[(targetIsland, adjacentFriendlyIsland)] = pairOptions

                sourceNode = IslandFlowNode(adjacentFriendlyIsland, desiredArmy=0 - adjacentFriendlyIsland.sum_army + adjacentFriendlyIsland.tile_count)
                destNode = IslandFlowNode(targetIsland, desiredArmy=targetIsland.sum_army + targetIsland.tile_count)
                if self.log_debug:
                    logbook.info(f'ADDING EDGE (start) FROM {sourceNode} TO {destNode}')
                sourceNode.set_flow_to(destNode, 0)
                if not self.use_all_pairs_visited:
                    visited = set()
                else:
                    visited = globalVisited
                # visited.add(targetIsland)
                # visited.add(adjacentFriendlyIsland)
                frLeftoverIdx = sourceNode.island.tile_count - 1
                tgTiles = deque(t.army for t in targetIsland.tiles_by_army)

                nextTargs = {}
                nextFriendlies = {t: sourceNode for t in adjacentFriendlyIsland.border_islands if t.team == myTeam }
                for altNext in targetIsland.border_islands:
                    if altNext == adjacentFriendlyIsland:
                        continue
                    if altNext.team != myTeam and altNext not in nextTargs:
                        nextTargs[altNext] = destNode
                    if altNext.team == myTeam and altNext not in nextFriendlies:
                        if altNext not in friendlyBorderingEnemy:
                            nextFriendlies[altNext] = destNode

                for altNext in adjacentFriendlyIsland.border_islands:
                    if altNext == targetIsland:
                        continue
                    if altNext.team != myTeam and altNext not in nextTargs:
                        nextTargs[altNext] = sourceNode
                    if altNext.team == myTeam and altNext not in nextFriendlies:
                        if altNext not in friendlyBorderingEnemy:
                            nextFriendlies[altNext] = sourceNode

                q.put((
                    self._get_a_star_priority_val(tgCapValue, 0.0, -1, 0, frLeftoverIdx, adjacentFriendlyIsland, searchTurns=turns, tgTiles=tgTiles),
                    -1,
                    turns + 1,  # turns + 1 (and turns left -1) because the very first tile doesn't count as a move, as only the dest counts.
                    targetIsland.sum_army + targetIsland.tile_count,
                    tieBreaker,
                    tgTiles,
                    0.0,
                    0,
                    0,  # frTileLeftoverArmy,
                    frLeftoverIdx,  # friendlyTileLeftoverIdx,
                    destNode,
                    sourceNode,
                    visited,
                    nextTargs,  # nextTargets
                    nextFriendlies,  # nextFriendlies
                    {sourceNode.island.unique_id: sourceNode},  # rootNodes
                    pairOptions
                ))

                # logbook.info(f'------------------\r\n---------------\r\nBEGINNING {targetIsland}<--->{adjacentFriendlyIsland}')
        while q:
            (
                negVt,
                turnsUsed,
                turnsLeft,
                uncappedTargetIslandArmy,
                randomTieBreak,
                targetTiles,
                econValue,
                gathSum,
                frLeftoverArmy,
                friendlyTileLeftoverIdx,
                targetCalculatedNode,
                friendlyUncalculatedNode,
                visited,
                nextTargets,
                nextFriendlies,
                rootNodes,
                pairOptions
            ) = q.get()

            # TODO this should not be necessary...
            if turnsLeft <= 0:
                continue

            targetTiles = targetTiles.copy()
            # TODO THESE ARE FOR DEBUGGING PURPOSES TO ENSURE NO REFERENCE CROSS SECTION AND TO WHITTLE DOWN WHICH VARIABLE IS THE PROBLEM:
            # tempLookup = {}
            # rootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), tempLookup)}
            # targetCalculatedNode = _deep_copy_flow_node(targetCalculatedNode, tempLookup)
            # friendlyUncalculatedNode = _deep_copy_flow_node(friendlyUncalculatedNode, tempLookup)
            # nextFriendlies = {island: _deep_copy_flow_node(n, tempLookup) for island, n in nextFriendlies.items()}
            # nextTargets = {island: _deep_copy_flow_node(n, tempLookup) for island, n in nextTargets.items()}
            # END TODO

            # visited = visited.copy()

            targetCalculated = targetCalculatedNode.island
            friendlyUncalculated = friendlyUncalculatedNode.island
            if self.log_debug:
                logbook.info(
                    f'\r\n  popped {friendlyUncalculated} -...-> {targetCalculated}'
                    f'\r\n        negVt: {negVt}'
                    f'\r\n        rootNodes: {" | ".join(str(n.island.shortIdent()) for n in rootNodes.values())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_children(rootNodes.values()))}'
                    f'\r\n        nextFriendlies {" | ".join(str(n.shortIdent()) for n in nextFriendlies.keys())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(nextFriendlies.values()))}'
                    f'\r\n        nextTargets {" | ".join(str(n.shortIdent()) for n in nextTargets.keys())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(nextTargets.values()))}'
                    f'\r\n        turnsUsed: {turnsUsed}, turnsLeft: {turnsLeft}'
                    f'\r\n        uncappedTargetIslandArmy: {uncappedTargetIslandArmy}, targetTiles: {repr(targetTiles)}'
                    f'\r\n        econValue: {econValue:.3f}, gathSum: {gathSum}'
                    f'\r\n        frLeftoverArmy: {frLeftoverArmy}, friendlyTileLeftoverIdx: {friendlyTileLeftoverIdx}'
                    f'\r\n        visited: {({t.shortIdent() for t in visited})}'
                )
            queueIterCount += 1

            # we re-visit the same friendly node if we were unable to use all of its army on the last target cycle.
            # if friendlyUncalculated in visited and friendlyUncalculated.:
            #     logbook.info(f'DOUBLE VISITING {friendlyUncalculated} ???')
            # continue

            # TODO orig
            if not self.log_debug:
                visited.add(friendlyUncalculated)
                visited.add(targetCalculated)
            else:
                if friendlyUncalculated not in visited:
                    logbook.info(f'    visiting friendlyUncalculated {friendlyUncalculated}')
                    visited.add(friendlyUncalculated)
                if targetCalculated not in visited:
                    logbook.info(f'    visiting targetCalculated {targetCalculated}')
                    visited.add(targetCalculated)

            if friendlyTileLeftoverIdx < 0:
                # TODO this shouldn't be necessary if my code is correct
                if self.log_debug:
                    logbook.info(f'    Resetting friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} frLeftoverArmy {frLeftoverArmy}')
                friendlyTileLeftoverIdx = friendlyUncalculated.tile_count - 1
                frLeftoverArmy = friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1
                if self.log_debug:
                    logbook.info(f'    --Reset to friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} frLeftoverArmy {frLeftoverArmy}')

            # TODO remove the turnsLeft > 1, this shouldn't be necessary, something is doing a final increment after running out of moves and then letting us re-enter this loop.
            if self.use_debug_asserts:
                self.assertEverythingSafe(
                    turns,
                    negVt,
                    turnsUsed,
                    turnsLeft,
                    uncappedTargetIslandArmy,
                    randomTieBreak,
                    targetTiles,
                    econValue,
                    gathSum,
                    frLeftoverArmy,
                    friendlyTileLeftoverIdx,
                    targetCalculatedNode,
                    friendlyUncalculatedNode,
                    visited,
                    nextTargets,
                    nextFriendlies,
                    rootNodes,
                    pairOptions
                )
            # logbook.info(f'Processing {targetCalculated.name} <- {friendlyUncalculated.name}')

            nextGathedSum = gathSum
            capValue = capValueByTeam[targetCalculated.team]

            # # have to leave 1's behind when leaving our own land
            # friendlyCappingArmy = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count
            # necessaryToFullyCap = uncappedTargetIslandArmy
            # # have to leave 1's behind when capping enemy land, too
            # armyLeftIfFullyCapping = friendlyCappingArmy - necessaryToFullyCap
            # turnsLeftIfFullyCapping = turnsLeft - numTilesLeftToCapFromTarget - friendlyUncalculated.tile_count
            # canFullyCap = turnsLeftIfFullyCapping >= 0 and armyLeftIfFullyCapping >= 0
            #
            # canFullyCap = False
            # validOpt = True
            # # TODO turn short circuit back on? Probably no because then we can't do the partial captures...?
            # if False and canFullyCap:
            #     # then we can actually dump all in and shortcut the more expensive logic
            #     turnsLeft = turnsLeftIfFullyCapping
            #     uncappedTargetIslandArmy = 0 - armyLeftIfFullyCapping
            #     econValue += numTilesLeftToCapFromTarget * capValue
            #     nextGathedSum += friendlyCappingArmy
            #     numTilesLeftToCapFromTarget = 0
            #
            #     turnsUsed = turns - turnsLeft
            #     existingBestTuple = pairOptions.get(turnsUsed, None)
            #
            #     if validOpt and (existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed):
            #         # turnsUsed == 13 and ArmyFlowExpander.is_any_tile_in_flow(rootNodes, [self.map.GetTile(14, 1), self.map.GetTile(13, 0)])
            #         pairOptions[turnsUsed] = (
            #             rootNodes,
            #             econValue,
            #             turnsUsed,
            #             0 - uncappedTargetIslandArmy,
            #             None,  # TODO this may be an incomplete capture... right...?
            #             None,
            #             None,
            #             nextGathedSum
            #         )
            # else:
            if True:
                # then we can't dump it all in, have to do iterative check.

                (
                    uncappedTargetIslandArmy,
                    dumpIterCount,
                    econValue,
                    frLeftoverArmy,
                    friendlyTileLeftoverIdx,
                    islandArmyToDump,
                    nextGathedSum,
                    tileIterCount,
                    turnsLeft
                ) = self._execute_island_tile_gather_capture_loop_and_record_options(
                    uncappedTargetIslandArmy,
                    capValue,
                    dumpIterCount,
                    econValue,
                    frLeftoverArmy,
                    friendlyTileLeftoverIdx,
                    friendlyUncalculated,
                    nextGathedSum,
                    pairOptions,
                    rootNodes,
                    targetCalculated,
                    targetTiles,
                    tileIterCount,
                    turns,
                    turnsLeft)

                if self.use_debug_asserts and islandArmyToDump != 0:
                    if targetTiles and targetTiles[0] < islandArmyToDump and turnsLeft > 0:
                        raise Exception(
                            f'Expected armyToDump to be 0, was {islandArmyToDump}, turnsLeft {turnsLeft} (fr leftover {frLeftoverArmy}, index {friendlyTileLeftoverIdx}, targetTiles {targetTiles}) to always have been reduced to 0 unless there are no target tiles left')

                # Necessary because when we terminate the loop early above due to running out of TARGET tiles, we need to keep track of the remaining army we have to gather for the second loop below.
                # TODO ACTUALLY THIS IS COVERED BY frLeftoverArmy NOW, NO...?
                # uncappedTargetIslandArmy -= islandArmyToDump

            if turnsLeft == 0:
                continue

            if not targetTiles:
                # we need to include new targets, then.
                dumpIterCount, tieBreaker, tileIterCount = self._queue_next_targets_and_next_friendlies(
                    uncappedTargetIslandArmy,
                    capValueByTeam,
                    dumpIterCount,
                    econValue,
                    frLeftoverArmy,
                    friendlyBorderingEnemy,
                    friendlyTileLeftoverIdx,
                    friendlyUncalculated,
                    myTeam,
                    nextFriendlies,
                    nextGathedSum,
                    nextTargets,
                    pairOptions,
                    q,
                    rootNodes,
                    targetTeam,
                    tieBreaker,
                    tileIterCount,
                    targetTiles,
                    turns,
                    turnsLeft,
                    visited)
            else:
                tieBreaker = self._queue_next_friendlies_only(
                    uncappedTargetIslandArmy,
                    capValue,
                    econValue,
                    frLeftoverArmy,
                    friendlyUncalculated,
                    myTeam,
                    nextFriendlies,
                    nextGathedSum,
                    nextTargets,
                    pairOptions,
                    q,
                    rootNodes,
                    targetCalculatedNode,
                    targetTiles,
                    tieBreaker,
                    turns,
                    turnsLeft,
                    visited)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion iteration complete in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')
        start = time.perf_counter()

        output = []
        for (targetIsland, source), planOptionsByTurns in opts.items():
            for turns, (rootNodes, econValue, otherTurns, armyRemainingInIncompleteSource, incompleteTarget, incompleteSource, unusedSourceArmy, gathedArmySum) in planOptionsByTurns.items():
                if otherTurns != turns:
                    raise Exception(f'Shouldnt happen, turn mismatch {turns} vs {otherTurns}')

                # if armyRemaining < 0:
                #     # then this is a partial capture option, we already pruned out the other moves in theory, and it is already worst-case moves assuming our largest tiles are furthest and their largest tiles are in front
                #     armyRemaining = 0

                plan = self._build_flow_expansion_option(
                    islands,
                    targetIsland,
                    source,
                    rootNodes,
                    econValue,
                    armyRemainingInIncompleteSource,
                    turns,
                    targetIslands,
                    ourIslands,
                    incompleteTarget,
                    incompleteSource,
                    unusedSourceArmy,
                    gathedArmySum)
                output.append(plan)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion plan build in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')

        return output

    def _execute_island_tile_gather_capture_loop_and_record_options(
            self,
            uncappedTargetIslandArmy,
            capValue,
            dumpIterCount,
            econValue,
            frLeftoverArmy,
            friendlyTileLeftoverIdx,
            friendlyUncalculated,
            nextGathedSum,
            pairOptions,
            rootNodes,
            targetCalculated,
            targetTiles,
            tileIterCount,
            turns,
            turnsLeft,
            # remainingIslandArmy: int | None = None
    ):
        # brokeOnTurns = False
        # if remainingIslandArmy is None:
        remainingIslandArmy = self.get_friendly_island_army_left(friendlyUncalculated, frLeftoverArmy, friendlyTileLeftoverIdx)

        # islandArmyToDump = self.get_friendly_island_army_left(friendlyUncalculated, 0, friendlyTileLeftoverIdx)
        # trueArmyToDump = islandArmyToDump + frLeftoverArmy
        # armyToDump = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count  # We need to leave 1 army behind per tile.
        # # ############## we start at 1, because pulling the first tile doesn't count as a move (the tile we move to counts as the move, whether thats to enemy or to another friendly gather tile)
        # friendlyIdx = 1
        # frTileArmy = friendlyUncalculated.tiles_by_army[0].army
        # friendlyIdx = 0
        while remainingIslandArmy > 0 and targetTiles and turnsLeft > 0:
            tgTileArmyToCap = targetTiles.popleft() + 1
            # if validOpt:
            dumpIterCount += 1

            # pull as many fr tiles as necessary to cap the en tile
            # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
            # turns left > 1 because there is no point to gather one more tile if we dont have a turn left to capture another tile with that army.
            while frLeftoverArmy < tgTileArmyToCap and turnsLeft > 0 and friendlyTileLeftoverIdx >= 0:
                frTileArmy = friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
                nextGathedSum += frTileArmy
                frLeftoverArmy += frTileArmy
                turnsLeft -= 1
                friendlyTileLeftoverIdx -= 1
                tileIterCount += 1

            if turnsLeft <= 0:
                # we already put all the data for all valid options in the pairOptions, so we can just break here and not worry about anything else if there is nothing else to add to the queue.
                # brokeOnTurns = True
                break

            if friendlyTileLeftoverIdx >= 0:
                pass

            if frLeftoverArmy < tgTileArmyToCap:
                # then we didn't complete the capture
                # validOpt = False
                targetTiles.appendleft(tgTileArmyToCap - frLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
                # turnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
                uncappedTargetIslandArmy -= frLeftoverArmy
                remainingIslandArmy -= frLeftoverArmy
                # we dont use this after breaking
                # armyToDump = 0
                if self.log_debug:
                    logbook.info(
                        f'    broke early on standard army usage {frLeftoverArmy} < {tgTileArmyToCap} at friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army}) w/ turnsLeft {turnsLeft} and targetTiles {targetTiles}')
                frLeftoverArmy = 0
                break

            # cap the en tile
            econValue += capValue
            uncappedTargetIslandArmy -= tgTileArmyToCap
            remainingIslandArmy -= tgTileArmyToCap
            frLeftoverArmy -= tgTileArmyToCap
            turnsLeft -= 1
            turnsUsed = turns - turnsLeft
            existingBestTuple = pairOptions.get(turnsUsed, None)

            if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed:
                # turnsUsed == 13 and ArmyFlowExpander.is_any_tile_in_flow(rootNodes.values(), [self.map.GetTile(14, 1), self.map.GetTile(13, 0)])
                pairOptions[turnsUsed] = (
                    rootNodes,
                    econValue,
                    turnsUsed,
                    remainingIslandArmy,
                    targetCalculated if targetTiles else None,
                    friendlyUncalculated if friendlyTileLeftoverIdx >= 0 else None,
                    remainingIslandArmy if friendlyTileLeftoverIdx >= 0 else None,
                    nextGathedSum,
                )

        return uncappedTargetIslandArmy, dumpIterCount, econValue, frLeftoverArmy, friendlyTileLeftoverIdx, remainingIslandArmy, nextGathedSum, tileIterCount, turnsLeft

    def _queue_next_targets_and_next_friendlies(
            self,
            uncappedTargetIslandArmy,
            capValueByTeam,
            dumpIterCount,
            econValue,
            frLeftoverArmy,
            friendlyBorderingEnemy,
            friendlyTileLeftoverIdx,
            friendlyUncalculated,
            myTeam,
            nextFriendlies,
            nextGathedSum,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            tileIterCount,
            tilesToCap,
            turns,
            turnsLeft,
            visited
    ):
        for (nextTargetIsland, nextTargetFromNode) in nextTargets.items():
            if nextTargetIsland in visited:
                if self.log_debug:
                    logbook.info(f'skipped targ {nextTargetIsland} from {nextTargetFromNode}')
                continue

            capValue = capValueByTeam[nextTargetIsland.team]

            # capture as much of the new target as we can
            newEconValue = econValue
            newTargetTiles = deque(t.army for t in nextTargetIsland.tiles_by_army)
            newTurnsLeft = turnsLeft
            # add
            newUncappedTargetIslandArmy = uncappedTargetIslandArmy
            newUncappedTargetIslandArmy += nextTargetIsland.sum_army + nextTargetIsland.tile_count
            newFriendlyTileLeftoverIdx = friendlyTileLeftoverIdx
            newFrLeftoverArmy = frLeftoverArmy

            # proves only these 3 value variables are being modified (of value variables)
            dumpIterCount, tieBreaker, tileIterCount = self._calculate_next_target_and_queue_next_friendlies(
                capValue,
                dumpIterCount,
                friendlyBorderingEnemy,
                friendlyUncalculated,
                myTeam,
                newUncappedTargetIslandArmy,
                newEconValue,
                newFrLeftoverArmy,
                newFriendlyTileLeftoverIdx,
                newTargetTiles,
                newTurnsLeft,
                nextFriendlies,
                nextGathedSum,
                nextTargetFromNode,
                nextTargetIsland,
                nextTargets,
                pairOptions,
                q,
                rootNodes,
                targetTeam,
                tieBreaker,
                tileIterCount,
                turns,
                visited)

        return dumpIterCount, tieBreaker, tileIterCount

    def _calculate_next_target_and_queue_next_friendlies(
            self,
            capValue,
            dumpIterCount,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextGathedSum,
            nextTargetFromNode,
            nextTargetIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            tileIterCount,
            turns,
            visited
    ):
        dumpIterCount, newUncappedTargetIslandArmy, newEconValue, newTurnsLeft, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, tileIterCount = self._calculate_next_target_values(
            capValue,
            dumpIterCount,
            friendlyUncalculated,
            newUncappedTargetIslandArmy,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTurnsLeft,
            nextGathedSum,
            nextTargetIsland,
            pairOptions,
            rootNodes,
            tileIterCount,
            turns)

        stillUnusedExistingFriendlyArmy = newFriendlyTileLeftoverIdx >= 0
        newTurnsUsed = turns - newTurnsLeft
        if stillUnusedExistingFriendlyArmy:
            tieBreaker = self._queue_current_friendlies_from_next_target_values(
                capValue,
                friendlyBorderingEnemy,
                friendlyUncalculated,
                myTeam,
                newUncappedTargetIslandArmy,
                newEconValue,
                newTargetTiles,
                newTurnsLeft,
                nextFriendlies,
                nextGathedSum,
                newFrLeftoverArmy,
                newFriendlyTileLeftoverIdx,
                nextTargetFromNode,
                nextTargetIsland,
                nextTargets,
                pairOptions,
                q,
                rootNodes,
                targetTeam,
                tieBreaker,
                newTurnsUsed,
                visited)

        else:
            for (nextFriendlyUncalculated, nextFriendlyFromNode) in nextFriendlies.items():
                if nextFriendlyUncalculated in visited:
                    if self.log_debug:
                        logbook.info(f'skipped src  {nextFriendlyUncalculated} from {nextFriendlyFromNode}')
                    continue

                # TODO check if would orphan gatherable islands in the middle of 1s? Actually, we keep having the option to pull orphans in, so really we should value the plan by the amount of orphaned stuff, not the search through the plan.

                tieBreaker = self._queue_next_friendlies_from_next_target_values(
                    capValue,
                    friendlyBorderingEnemy,
                    friendlyUncalculated,
                    myTeam,
                    newUncappedTargetIslandArmy,
                    newEconValue,
                    newTargetTiles,
                    newTurnsLeft,
                    nextFriendlies,
                    nextFriendlyFromNode,
                    nextFriendlyUncalculated,
                    nextGathedSum,
                    newFrLeftoverArmy,
                    nextTargetFromNode,
                    nextTargetIsland,
                    nextTargets,
                    pairOptions,
                    q,
                    rootNodes,
                    targetTeam,
                    tieBreaker,
                    newTurnsUsed,
                    visited)

        return dumpIterCount, tieBreaker, tileIterCount

    def _queue_next_friendlies_from_next_target_values(
            self,
            capValue,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextFriendlyFromNode,
            nextFriendlyUncalculated,
            nextGathedSum,
            nextFrLeftoverArmy,
            nextTargetFromNode,
            nextTargetIsland: TileIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            newTurnsUsed,
            visited
    ):
        if self.log_debug:
            logbook.info(f'tg {nextTargetIsland}, newTurnsUsed {newTurnsUsed} newTurnsLeft {newTurnsLeft}, fr {nextFriendlyUncalculated}')

        lookup = {}

        newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}

        copyTargetFromNode = lookup[nextTargetFromNode.island.unique_id]
        nextTargetCalculatedNode = IslandFlowNode(nextTargetIsland, nextTargetIsland.sum_army + nextTargetIsland.tile_count)

        if self.use_debug_asserts and copyTargetFromNode.island not in nextTargetCalculatedNode.island.border_islands:
            # TODO remove once algo reliable
            raise AssertionError(f'Tried to add illegal edge from {copyTargetFromNode} TO {nextTargetCalculatedNode}')
        if self.log_debug:
            logbook.info(f'    adding target (friendly) edge from {copyTargetFromNode.island.unique_id} TO {nextTargetCalculatedNode.island.unique_id}')
        copyTargetFromNode.set_flow_to(nextTargetCalculatedNode, 0)

        # TODO remove try catches
        try:
            copyFriendlyFromNode = lookup[nextFriendlyFromNode.island.unique_id]
        except:
            logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
            raise
        newRootNodes.pop(copyFriendlyFromNode.island.unique_id, None)
        nextFriendlyUncalculatedNode = IslandFlowNode(nextFriendlyUncalculated, 0 - nextFriendlyUncalculated.sum_army + nextFriendlyUncalculated.tile_count)
        if self.use_debug_asserts and nextFriendlyUncalculatedNode.island not in copyFriendlyFromNode.island.border_islands:
            # TODO remove once algo reliable
            raise AssertionError(f'Tried to add illegal edge from {nextFriendlyUncalculatedNode} TO {copyFriendlyFromNode}')
        if self.log_debug:
            logbook.info(f'    adding friendly (target) edge from {nextFriendlyUncalculatedNode.island.unique_id} TO {copyFriendlyFromNode.island.unique_id}')

        nextFriendlyUncalculatedNode.set_flow_to(copyFriendlyFromNode, 0)
        newRootNodes[nextFriendlyUncalculated.unique_id] = nextFriendlyUncalculatedNode
        newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}
        del newNextFriendlies[nextFriendlyUncalculated]

        # this lets us visit in arbitrary orders (ew)
        newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}
        del newNextTargets[nextTargetIsland]

        self._try_queue_next_gather(
            myTeam,
            nextFriendlyUncalculated.border_islands,
            newNextFriendlies,
            newNextTargets,
            nextFrLeftoverArmy,
            nextFriendlyUncalculated,
            nextFriendlyUncalculatedNode,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy)

        self._try_queue_next_capture(
            myTeam,
            nextTargetIsland.border_islands,
            newNextFriendlies,
            newNextTargets,
            nextFrLeftoverArmy,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy)

        tieBreaker += 1
        nextFrTileIdx = nextFriendlyUncalculated.tile_count - 1

        self.enqueue(
            q,
            self._get_a_star_priority_val(capValue, newEconValue, newTurnsUsed, nextFrLeftoverArmy, nextFrTileIdx, nextFriendlyUncalculated, searchTurns=newTurnsUsed + newTurnsLeft, tgTiles=newTargetTiles),
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            nextFrLeftoverArmy,
            nextFrTileIdx,
            nextTargetCalculatedNode,
            nextFriendlyUncalculatedNode,
            # visited.copy(),
            visited,  # note we are not cloning visited, so this isn't full TSP
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        )
        return tieBreaker

    def enqueue(
            self,
            q,
            prioVal,
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            nextFrLeftoverArmy,
            nextFrTileIdx,
            nextTargetCalculatedNode,
            nextFriendlyUncalculatedNode,
            visited,
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions):

        if self.log_debug:
            logbook.info(
                f'\r\n      enqueueing {nextFriendlyUncalculatedNode.island} -...-> {nextTargetCalculatedNode.island}'
                f'\r\n            negVt: {prioVal}'
                f'\r\n            rootNodes: {" | ".join(str(n.island.shortIdent()) for n in newRootNodes.values())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_children(newRootNodes.values()))}'
                f'\r\n            nextFriendlies {" | ".join(str(n.shortIdent()) for n in newNextFriendlies.keys())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(newNextFriendlies.values()))}'
                f'\r\n            nextTargets {" | ".join(str(n.shortIdent()) for n in newNextTargets.keys())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(newNextTargets.values()))}'
                f'\r\n            turnsUsed: {newTurnsUsed}, turnsLeft: {newTurnsLeft}'
                f'\r\n            uncappedTargetIslandArmy: {newUncappedTargetIslandArmy}, targetTiles: {repr(newTargetTiles)}'
                f'\r\n            econValue: {newEconValue:.3f}, gathSum: {nextGathedSum}'
                f'\r\n            frLeftoverArmy: {nextFrLeftoverArmy}, friendlyTileLeftoverIdx: {nextFrTileIdx}'
                f'\r\n            visited: {({t.shortIdent() for t in visited})}'
            )
        q.put((
            prioVal,
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            nextFrLeftoverArmy,
            nextFrTileIdx,
            nextTargetCalculatedNode,
            nextFriendlyUncalculatedNode,
            visited,
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        ))

    def _try_queue_next_gather(
            self,
            myTeam,
            borderIslands,
            newNextFriendlies,
            newNextTargets,
            nextFrLeftoverArmy,
            nextFriendlyUncalculated,
            nextFriendlyUncalculatedNode,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy=None,
    ):
        for adj in borderIslands:
            if adj.team == myTeam:
                if adj in visited or adj in newNextFriendlies:
                    continue
                # TODO need to allow gathering through neutral land
                if not self._is_flow_allowed(adj, nextFriendlyUncalculated, armyAmount=nextGathedSum, isSubsequentFriendly=True, friendlyBorderingEnemy=friendlyBorderingEnemy):
                    continue
                newNextFriendlies[adj] = nextFriendlyUncalculatedNode
            else:
                if adj in visited or not self._is_flow_allowed(fromIsland=nextFriendlyUncalculated, toIsland=adj, armyAmount=nextFrLeftoverArmy, isSubsequentTarget=True):
                    continue
                # This isnt safe, it assumes our gather so far can split in either direction. Which, actually, I suppose that's maybe fine, we can split after all.
                newNextTargets[adj] = nextFriendlyUncalculatedNode

    def _try_queue_next_capture(
            self,
            myTeam,
            borderIslands,
            newNextFriendlies,
            newNextTargets,
            nextFrLeftoverArmy,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy=None,
    ):
        for adj in borderIslands:
            if adj.team == myTeam:
                if adj in visited or adj in newNextFriendlies:
                    continue
                # TODO need to allow gathering through neutral land
                if not self._is_flow_allowed(adj, nextTargetIsland, armyAmount=nextGathedSum, isSubsequentFriendly=True, friendlyBorderingEnemy=friendlyBorderingEnemy):
                    continue
                newNextFriendlies[adj] = nextTargetCalculatedNode
            else:
                if adj in visited or not self._is_flow_allowed(fromIsland=nextTargetIsland, toIsland=adj, armyAmount=nextFrLeftoverArmy, isSubsequentTarget=True):
                    continue
                newNextTargets[adj] = nextTargetCalculatedNode

    def _queue_current_friendlies_from_next_target_values(
            self,
            capValue,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextGathedSum,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            nextTargetFromNode,
            nextTargetIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            newTurnsUsed,
            visited
    ):
        if self.log_debug:
            logbook.info(f'tg {nextTargetIsland}, newTurnsUsed {newTurnsUsed} newTurnsLeft {newTurnsLeft}, EXIST fr {friendlyUncalculated} (newFriendlyTileLeftoverIdx {newFriendlyTileLeftoverIdx})')

        lookup = {}

        newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}

        copyTargetFromNode = lookup[nextTargetFromNode.island.unique_id]
        nextTargetCalculatedNode = IslandFlowNode(nextTargetIsland, nextTargetIsland.sum_army + nextTargetIsland.tile_count)

        if copyTargetFromNode.island not in nextTargetCalculatedNode.island.border_islands:
            # TODO remove once algo reliable
            raise AssertionError(f'Tried to add illegal edge from {copyTargetFromNode} TO {nextTargetCalculatedNode}')
        if self.log_debug:
            logbook.info(f'    adding target (solo) edge from {copyTargetFromNode.island.unique_id} TO {nextTargetCalculatedNode.island.unique_id}')

        copyTargetFromNode.set_flow_to(nextTargetCalculatedNode, 0)
        try:
            copyFriendlyFromNode = lookup[friendlyUncalculated.unique_id]
        except:
            logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
            raise

        newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}

        # this lets us visit in arbitrary orders (ew)
        newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}
        del newNextTargets[nextTargetIsland]

        self._try_queue_next_capture(
            myTeam,
            nextTargetIsland.border_islands,
            newNextFriendlies,
            newNextTargets,
            newFrLeftoverArmy,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy)

        tieBreaker += 1

        self.enqueue(
            q,
            self._get_a_star_priority_val(capValue, newEconValue, newTurnsUsed, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, friendlyUncalculated, searchTurns=newTurnsUsed + newTurnsLeft, tgTiles=newTargetTiles),
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            nextTargetCalculatedNode,
            copyFriendlyFromNode,
            # visited.copy(),
            visited,  # note we are not cloning visited, so this isn't full TSP
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        )
        return tieBreaker

    def _calculate_next_target_values(
            self,
            capValue,
            dumpIterCount,
            friendlyUncalculated,
            newUncappedTargetIslandArmy,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTurnsLeft,
            nextGathedSum,
            nextTargetIsland,
            pairOptions,
            rootNodes,
            tileIterCount,
            turns):
        if self.log_debug:
            logbook.info(
                f'  beginning newFrLeftoverArmy {newFrLeftoverArmy} with newFriendlyTileLeftoverIdx {newFriendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx].army}) w/ starting newTurnsLeft {newTurnsLeft} and newTargetTiles {newTargetTiles}')
        #
        # while newArmyToDump > 0 and newTargetTiles and newTurnsLeft > 0:
        #     tgTileArmyToCap = newTargetTiles.popleft() + 1
        #     # if validOpt:
        #     dumpIterCount += 1
        #
        #     # pull as many fr tiles as necessary to cap the en tile
        #     # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
        #     while newFrLeftoverArmy < tgTileArmyToCap and newTurnsLeft > 1 and newFriendlyTileLeftoverIdx >= 0:
        #         newFrLeftoverArmy += friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
        #         newTurnsLeft -= 1
        #         newFriendlyTileLeftoverIdx -= 1
        #         # friendlyIdx += 1
        #         tileIterCount += 1
        #
        #     if newFriendlyTileLeftoverIdx >= 0:
        #         pass
        #
        #     if newFrLeftoverArmy < tgTileArmyToCap:
        #         # then we didn't complete the capture of target island
        #         # # validOpt = False
        #         newTargetTiles.appendleft(tgTileArmyToCap - newFrLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
        #         # # newTurnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
        #         # # newFriendlyTileLeftoverIdx += 1
        #         newUncappedTargetIslandArmy -= newFrLeftoverArmy
        #         # newArmyToDump -= newFrLeftoverArmy
        #         if self.log_debug:
        #             logbook.info(f'    broke early on {newFrLeftoverArmy} < {tgTileArmyToCap} at newFriendlyTileLeftoverIdx {newFriendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx].army}) w/ newTurnsLeft {newTurnsLeft} and newTargetTiles {newTargetTiles}, newUncappedTargetIslandArmy {newUncappedTargetIslandArmy}')
        #         newFrLeftoverArmy = 0
        #         # # armyToDump = 0
        #         break
        #
        #     # cap the en tile
        #     newTilesToCap -= 1
        #     newEconValue += capValue
        #     newUncappedTargetIslandArmy -= tgTileArmyToCap
        #     newArmyToDump -= tgTileArmyToCap
        #     newFrLeftoverArmy -= tgTileArmyToCap
        #     newTurnsLeft -= 1
        #
        #     turnsUsed = turns - newTurnsLeft
        #     existingBestTuple = pairOptions.get(turnsUsed, None)
        #
        #     if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < newEconValue / turnsUsed:
        #         # turnsUsed == 13 and ArmyFlowExpander.is_any_tile_in_flow(rootNodes, [self.map.GetTile(14, 1), self.map.GetTile(13, 0)])
        #         pairOptions[turnsUsed] = (
        #             rootNodes,
        #             newEconValue,
        #             turnsUsed,
        #             newArmyToDump,
        #             nextTargetIsland if newTargetTiles else None,
        #             friendlyUncalculated if newFriendlyTileLeftoverIdx >= 0 else None,
        #             newArmyToDump if newFriendlyTileLeftoverIdx >= 0 else None,
        #             nextGathedSum
        #         )
        # # #TODO THIS WAS COMMENTED
        # # armyLeftOver = 0 - armyToCap
        # # while armyLeftOver > 0 and newTargetTiles:
        # #     tileArmyToCap = newTargetTiles.popleft() + 1
        # #
        # #     if tileArmyToCap > armyLeftOver:
        # #         newTargetTiles.appendleft(tileArmyToCap - 1)
        # #         break
        # #
        # #     # then we technically actually pre-capture some of the tiles to capture here
        # #     #  ought to increment newTilesCapped and decrement newTilesToCap based on the tile values in the island...?
        # #     newTilesToCap -= 1
        # #     newEconValue += capValue
        # #     newUncappedTargetIslandArmy -= tileArmyToCap
        # #     armyLeftOver -= tileArmyToCap
        # #     newTurnsLeft -= 1
        # #
        # #     if newUncappedTargetIslandArmy <= 0:
        # #         turnsUsed = turns - newTurnsLeft
        # #         existingBestTuple = pairOptions.get(turnsUsed, None)
        # #
        # #         if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < newEconValue / turnsUsed:
        # #             pairOptions[turnsUsed] = (
        # #                 rootNodes,
        # #                 newEconValue,
        # #                 turnsUsed,
        # #                 armyToDump,
        # #                 targetCalculated if targetTiles else None,
        # #                 friendlyUncalculated if friendlyTileLeftoverIdx >= 0 else None,
        # #                 armyToDump if friendlyTileLeftoverIdx >= 0 else None,
        # #                 nextGathedSum,
        # #             )
        # #
        # #             pairOptions[turnsUsed] = (
        # #                 flowGraph,
        # #                 newEconValue,
        # #                 turnsUsed,
        # #                 0 - newUncappedTargetIslandArmy
        # #             )
        # # # END TODO

        (
            armyToCap,
            dumpIterCount,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            islandArmyToDump,
            nextGathedSum,
            tileIterCount,
            newTurnsLeft
        ) = self._execute_island_tile_gather_capture_loop_and_record_options(
            newUncappedTargetIslandArmy,
            capValue,
            dumpIterCount,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            friendlyUncalculated,
            nextGathedSum,
            pairOptions,
            rootNodes,
            nextTargetIsland,
            newTargetTiles,
            tileIterCount,
            turns,
            newTurnsLeft)
        return dumpIterCount, newUncappedTargetIslandArmy, newEconValue, newTurnsLeft, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, tileIterCount

    def _queue_next_friendlies_only(
            self,
            armyToCap,
            capValue,
            econValue,
            frLeftoverArmy,
            friendlyUncalculated,
            myTeam,
            nextFriendlies,
            nextGathedSum,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetCalculatedNode,
            targetTiles,
            tieBreaker,
            turns,
            turnsLeft,
            visited
    ):
        turnsUsed = turns - turnsLeft
        for (nextFriendlyUncalculated, nextFriendlyFromNode) in nextFriendlies.items():
            if nextFriendlyUncalculated in visited:
                # logbook.info(f'skipped src  {newFriendlyUncalculated.name} from {friendlyUncalculated.name}')
                continue

            lookup = {}
            newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}
            copyTargetCalculatedNode = lookup[targetCalculatedNode.island.unique_id]

            newRootNodes.pop(nextFriendlyFromNode.island.unique_id, None)
            try:
                copyFriendlyFromNode = lookup[nextFriendlyFromNode.island.unique_id]
            except:
                logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
                raise

            nextFriendlyUncalculatedNode = IslandFlowNode(nextFriendlyUncalculated, 0 - nextFriendlyUncalculated.sum_army + nextFriendlyUncalculated.tile_count)
            if self.use_debug_asserts and nextFriendlyUncalculatedNode.island not in copyFriendlyFromNode.island.border_islands:
                # TODO remove once algo reliable
                raise Exception(f'Tried to add illegal edge from {nextFriendlyUncalculatedNode} TO {copyFriendlyFromNode}')

            if self.log_debug:
                logbook.info(f'    adding friendly edge from {nextFriendlyUncalculatedNode.island.unique_id} TO {copyFriendlyFromNode.island.unique_id}')
            nextFriendlyUncalculatedNode.set_flow_to(copyFriendlyFromNode, 0)
            newRootNodes[nextFriendlyUncalculated.unique_id] = nextFriendlyUncalculatedNode

            newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}
            del newNextFriendlies[nextFriendlyUncalculated]
            newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}

            self._try_queue_next_gather(
                myTeam,
                nextFriendlyUncalculated.border_islands,
                newNextFriendlies,
                newNextTargets,
                frLeftoverArmy,
                nextFriendlyUncalculated,
                nextFriendlyUncalculatedNode,
                nextGathedSum,
                copyTargetCalculatedNode,
                targetCalculatedNode.island,
                visited,
                friendlyBorderingEnemy=None)  # TODO

            tieBreaker += 1
            frTileIdx = nextFriendlyUncalculated.tile_count - 1

            self.enqueue(
                q,
                self._get_a_star_priority_val(capValue, econValue, turnsUsed, frLeftoverArmy, frTileIdx, nextFriendlyUncalculated, searchTurns=turnsUsed + turnsLeft, tgTiles=targetTiles),
                turnsUsed,
                turnsLeft,
                armyToCap,
                tieBreaker,
                targetTiles.copy(),
                econValue,
                nextGathedSum,
                frLeftoverArmy,
                frTileIdx,
                copyTargetCalculatedNode,
                nextFriendlyUncalculatedNode,
                # visited.copy(),
                visited,  # note we are not cloning visited, so this isn't full TSP
                newNextTargets,
                newNextFriendlies,
                newRootNodes,
                pairOptions
            )
        return tieBreaker

    def _build_flow_expansion_option(
            self,
            islandBuilder: TileIslandBuilder,
            target: TileIsland,
            source: TileIsland,
            sourceNodes: typing.Dict[int, IslandFlowNode],
            econValue: float,
            armyRemainingInIncompleteSource: int,
            turns,
            targetIslands: typing.List[TileIsland],
            ourIslands: typing.List[TileIsland],
            incompleteTarget: TileIsland | None,
            incompleteSource: TileIsland | None,
            unusedSourceArmy: int | None,
            gathedArmySum: int,
            negativeTiles: TileSet | None = None,
            useTrueValueGathered: bool = True,
    ) -> FlowExpansionPlanOption:
        if self.log_debug:
            logbook.info(f'building plan for {source.name}->{target.name} (econ {econValue:.2f} turns {turns} armyRemainingInIncompleteSource {armyRemainingInIncompleteSource})')

        # TODO we want to keep our moves as wide across any borders as possible, if we combine everything into one big tile then we have the potential to waste moves.
        # need to build our initial lines outwards from the border as straight as possible, then combine as needed as captures fail.
        # fromMatrix: MapMatrixInterface[Tile] = MapMatrix(self.map)
        # fromArmy: MapMatrixInterface[int] = MapMatrix(self.map)

        # border = set(itertools.chain.from_iterable(t.movable for t in target.tile_set if t in source.tile_set))
        capping = set()
        gathing = set()
        team = self.team

        curArmy: int
        curIdk: int
        curNode: IslandFlowNode
        fromNode: IslandFlowNode | None

        incompleteSourceNode: IslandFlowNode | None = None
        incompleteTargetNode: IslandFlowNode | None = None
        incompleteTargetFrom: typing.Dict[int, IslandFlowNode] = {}
        allBorderTiles = set()

        # TODO this can be completely redone much more efficient by using the raw queue loop below to build the gather / capture plan itself instead of using it for tile lists and then building a whole addl tree.

        rebuiltGathedSum = unusedSourceArmy
        rebuiltCumulativeSum = unusedSourceArmy
        if rebuiltGathedSum is None:
            rebuiltGathedSum = 0
            rebuiltCumulativeSum = 0
        rebuiltCumulativeTurns = -1
        lookup = {}
        q: typing.List[typing.Tuple[int, int, IslandFlowNode, IslandFlowNode | None]] = [(0, 0, n, None) for n in sourceNodes.values()]
        while q:
            curArmy, curIdk, curNode, fromNode = q.pop()
            # TODO not sure why the below would be needed instead of the hardcoded source/target. Revert if necessary...?
            # if fromNode is not None and fromNode.island == source and curNode.island == target:
            if fromNode is not None and fromNode.island.team == team and curNode.island.team != team:
                # borderTiles = islandBuilder.get_inner_border_tiles(fromNode.island, curNode.island)
                borderTiles = islandBuilder.get_inner_border_tiles(curNode.island, fromNode.island)
                allBorderTiles.update(borderTiles)

            lookup[curNode.island.unique_id] = curNode
            if curNode.island == incompleteTarget:
                incompleteTargetNode = curNode
                if fromNode:
                    incompleteTargetFrom[fromNode.island.unique_id] = fromNode
            elif curNode.island == incompleteSource:
                incompleteSourceNode = curNode
                gathed = curNode.island.sum_army - curNode.island.tile_count - unusedSourceArmy
                curArmy += gathed
                rebuiltGathedSum += gathed
                rebuiltCumulativeSum += gathed
            else:
                rebuiltCumulativeTurns += curNode.island.tile_count
                if curNode.island.team == team:
                    gathing.update(curNode.island.tile_set)
                    gathed = curNode.island.sum_army - curNode.island.tile_count
                    curArmy += gathed
                    rebuiltGathedSum += gathed
                    rebuiltCumulativeSum += gathed
                else:
                    capping.update(curNode.island.tile_set)
                    gathed = curNode.island.sum_army + curNode.island.tile_count
                    curArmy -= gathed
                    # rebuiltGathedSum -= gathed
                    rebuiltCumulativeSum -= gathed

            for edge in curNode.flow_to:
                # right now can only flow to one,
                # TODO must figure out how to split in future when can target multiple....
                edge.edge_army = curArmy
                q.append((curArmy, curIdk, edge.target_flow_node, curNode))

        if incompleteSourceNode:
            tiles = self._find_island_consumed_tiles_from_borders(islandBuilder, incompleteSourceNode, unusedSourceArmy, incompleteSourceNode.flow_to, negativeTiles)
            gathing.update(tiles)
            rebuiltCumulativeTurns += len(tiles)
            # gathed = incompleteSourceNode.island.sum_army - incompleteSourceNode.island.tile_count
            # rebuiltGathedSum += gathed

        if incompleteTargetNode:
            # +1 because first gathered-from-tile doesn't count so we get one extra move
            tiles = self._find_island_consumed_tiles_from_borders_by_count(islandBuilder, incompleteTargetNode, turns - len(gathing) - len(capping) + 1, incompleteTargetFrom, negativeTiles)
            capping.update(tiles)
            rebuiltCumulativeTurns += len(tiles)
            for t in tiles:
                rebuiltCumulativeSum -= t.army - 1

        plan = GatherUtils.convert_contiguous_tiles_to_gather_capture_plan(
            self.map,
            rootTiles=allBorderTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=self.friendlyGeneral.player,
            priorityMatrix=None,
            useTrueValueGathered=useTrueValueGathered,
            captures=capping,
        )

        # ok now we need to figure out how to route the captures...
        # self.flow_graph

        # for toIsland, fromIsland in flowGraph.items():
        #     if toIsland == incompleteTarget:
        #         pass
        #     else:
        #         if toIsland.team == team:
        #             gathing.update(toIsland.tile_set)
        #         else:
        #             capping.update(toIsland.tile_set)
        #
        #     if fromIsland == incompleteSource:
        #         pass
        #     else:
        #         if fromIsland.team == team:
        #             gathing.update(fromIsland.tile_set)
        #         else:
        #             capping.update(fromIsland.tile_set)

        if len(capping) > self.debug_render_capture_count_threshold:
            self.live_render_capture_stuff(islandBuilder, capping, gathing, incompleteSource, incompleteTarget, unusedSourceArmy)

        # q = deque()
        # # border = set()
        # for tile in gathing:
        #     for adj in tile.movable:
        #         if adj not in capping:
        #             continue
        #         border.add((tile, adj))

        # visited = set()
        # while q

        # tilesToKill =
        #
        # q = deque()
        # for t in border:

        # plan = FlowExpansionPlanOption(
        #     moves,
        #     econValue,
        #     turns,  # TODO should be finalTurns once implemented
        #     captures,
        #     armyRemaining
        # )

        if self.log_debug or self.use_debug_asserts:
            planVt = plan.econValue / plan.length
            expectedVt = econValue / turns
            cutoffVt = econValue / max(1, turns - 1)
            violatesVtCutoff = planVt > cutoffVt * 1.10001
            if self.log_debug or violatesVtCutoff:
                logbook.info(
                    f'\r\n(expected {expectedVt:.3f} ({econValue:.2f}v/{turns}t) - built gcap plan {plan}'
                    f'\r\n   FOR algo output econValue {econValue:.2f}, turns {turns}, incompleteTarget {incompleteTarget}, incompleteSource {incompleteSource}, unusedSourceArmy {unusedSourceArmy}, gathedArmySum {gathedArmySum}, armyRemainingInIncompleteSource {armyRemainingInIncompleteSource}'
                    f'\r\n   FOR raw rebuiltCumulativeTurns {rebuiltCumulativeTurns} (vs {plan.length}), rebuiltGathedSum {rebuiltGathedSum}, rebuiltCumulativeSum {rebuiltCumulativeSum} (vs plan.gathered_army {plan.gathered_army})')
            if violatesVtCutoff and self.use_debug_asserts:
                err = f'Something went wrong. {expectedVt:.3f} ({econValue:.2f}v/{turns}t). The GCP is overvalued {planVt:.3f} ({plan.econValue:2f}v/{plan.length}t)'
                self.live_render_capture_stuff(
                    islandBuilder,
                    capping=plan.approximate_capture_tiles,
                    gathing=plan.tileSet.difference(plan.approximate_capture_tiles),
                    incompleteSource=incompleteSource,
                    incompleteTarget=incompleteTarget,
                    sourceUnused=unusedSourceArmy,
                    plan=plan,
                    extraInfo=err)
                raise AssertionError(err)

        return plan

    def live_render_capture_stuff(
            self,
            islandBuilder: TileIslandBuilder,
            capping: TileSet,
            gathing: TileSet,
            incompleteSource: TileIsland,
            incompleteTarget: TileIsland,
            sourceUnused: int | None = None,
            extraInfo: str | None = None,
            plan: FlowExpansionPlanOption | None = None,
    ):
        from Viewer import ViewerProcessHost
        debugViewInfo = ViewerProcessHost.get_renderable_view_info(self.map)
        inf = f'capping {len(capping)}, gathing {len(gathing)}'
        if extraInfo:
            inf = extraInfo
            debugViewInfo.add_info_line(inf)

        for tile in capping:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.RED)
        for tile in gathing:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.GREEN)
        debugViewInfo.add_info_line_no_log(f'GREEN = gathing')
        debugViewInfo.add_info_line_no_log(f'RED = capping')
        if incompleteTarget:
            debugViewInfo.add_info_line_no_log(f'ORANGE = incompleteTarget tileset')
            for tile in incompleteTarget.tile_set:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.ORANGE, radiusReduction=10)
        if incompleteSource:
            debugViewInfo.add_info_line_no_log(f'BLUE = incompleteSource tileset ({sourceUnused} unused)')
            for tile in incompleteSource.tile_set:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.BLUE, radiusReduction=8)

        if plan:
            ArmyFlowExpander.add_flow_expansion_option_to_view_info(
                self.map,
                plan,
                plan.player,
                tgPlayer=self.enemyGeneral.player,
                viewInfo=debugViewInfo
            )

        islandBuilder.add_tile_islands_to_view_info(debugViewInfo, printIslandInfoLines=True, printIslandNames=True)
        ViewerProcessHost.render_view_info_debug(inf, inf, self.map, debugViewInfo)

    def live_render_invalid_flow_config(
            self,
            islandBuilder: TileIslandBuilder,
            nxGraph: nx.DiGraph,
            extraInfo: str | None = None,
    ):
        from Viewer import ViewerProcessHost
        debugViewInfo = ViewerProcessHost.get_renderable_view_info(self.map)
        inf = 'invalid flow config'
        if extraInfo:
            inf = extraInfo
            debugViewInfo.add_info_line(inf)

        ArmyFlowExpander.add_nx_flow_precursor_graph_to_view_info(nxGraph, islandBuilder, debugViewInfo)
        islandBuilder.add_tile_islands_to_view_info(debugViewInfo, printIslandInfoLines=False, printIslandNames=True)

        ViewerProcessHost.render_view_info_debug(inf, inf, self.map, debugViewInfo)

    @staticmethod
    def add_flow_expansion_option_to_view_info(map: MapBase, bestOpt: FlowExpansionPlanOption, sourcePlayer: int, tgPlayer: int, viewInfo: ViewInfo):
        tgTeam = map.team_ids_by_player_index[tgPlayer]
        sourceTeam = map.team_ids_by_player_index[sourcePlayer]

        for move in bestOpt.get_move_list():
            path = Path.from_move(move)
            viewInfo.color_path(PathColorer(
                path,
                100, 200, 100,
                200,
                0, 0
            ))

        for tile in bestOpt.tileSet:
            ts = TargetStyle.YELLOW
            if map.is_tile_on_team(tile, tgTeam):
                ts = TargetStyle.RED
            elif map.is_tile_on_team(tile, sourceTeam):
                ts = TargetStyle.GREEN

            viewInfo.add_targeted_tile(tile, ts, radiusReduction=10)

    @staticmethod
    def add_flow_graph_to_view_info(flowGraph: IslandMaxFlowGraph, viewInfo: ViewInfo, noNeut: bool = True, withNeut: bool = True, showBackfillNeut: bool = False):
        # things drawn last win
        if withNeut:
            viewInfo.add_info_line(f'PURPLE/BLUE = YES neutral max flows')
            # Need to draw the blue last since it will be covered by the gray if drawn earlier.
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.enemy_backfill_nodes_inc_neut, Colors.LIGHT_BLUE)

        if noNeut:
            viewInfo.add_info_line(f'BLACK/PINK = NO neutral max flows')
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.enemy_backfill_nodes_no_neut, Colors.WHITE_PURPLE)
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.root_flow_nodes_no_neut, Colors.BLACK)

        if withNeut:
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.root_flow_nodes_inc_neut, Colors.DARK_PURPLE)
            # if showBackfillNeut:
            #     ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.enemy_backfill_neut_dump_edges, Colors.DARK_PURPLE)

    @staticmethod
    def _include_flow_with_colors(viewInfo, sources, sourceColor):
        q: typing.Deque[IslandFlowNode] = deque()
        visited = set()
        for flowSource in sources:
            q.append(flowSource)
        while q:
            flowNode: IslandFlowNode = q.popleft()
            if flowNode.island.unique_id in visited:
                continue
            visited.add(flowNode.island.unique_id)

            allSourceX = [t.x for t in flowNode.island.tile_set]
            allSourceY = [t.y for t in flowNode.island.tile_set]
            sourceX = sum(allSourceX) / len(allSourceX)
            sourceY = sum(allSourceY) / len(allSourceY)

            for destinationEdge in flowNode.flow_to:
                allDestX = [t.x for t in destinationEdge.target_flow_node.island.tile_set]
                allDestY = [t.y for t in destinationEdge.target_flow_node.island.tile_set]
                destX = sum(allDestX) / len(allDestX)
                destY = sum(allDestY) / len(allDestY)

                viewInfo.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{destinationEdge.edge_army}', color=sourceColor)
                q.append(destinationEdge.target_flow_node)

    @staticmethod
    def add_nx_flow_precursor_graph_to_view_info(digraph: nx.DiGraph, islandBuilder: TileIslandBuilder, viewInfo: ViewInfo):
        for flowSource in digraph.edges(data=True):
            fromId, toId, dataBag = flowSource
            if fromId < 0:
                fromId = -fromId
            if toId < 0:
                toId = -toId
            if toId == fromId:
                continue

            weight = dataBag['weight']
            capacity = dataBag['capacity']

            fromIsland = islandBuilder.tile_islands_by_unique_id[fromId]
            toIsland = islandBuilder.tile_islands_by_unique_id[toId]

            allSourceX = [t.x for t in fromIsland.tile_set]
            allSourceY = [t.y for t in fromIsland.tile_set]
            sourceX = sum(allSourceX) / len(allSourceX)
            sourceY = sum(allSourceY) / len(allSourceY)

            allDestX = [t.x for t in toIsland.tile_set]
            allDestY = [t.y for t in toIsland.tile_set]
            destX = sum(allDestX) / len(allDestX)
            destY = sum(allDestY) / len(allDestY)

            viewInfo.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{weight}, {capacity}', color=Colors.BLACK)

    def ensure_flow_graph_exists(self, islands: TileIslandBuilder):
        if self.nxGraphData is None or self.nxGraphDataNoNeut is None:
            self.nxGraphData = self._build_island_flow_precursor_nx_data(islands, useNeutralFlow=True)

            self.nxGraphDataNoNeut = self._build_island_flow_precursor_nx_data(islands, useNeutralFlow=False)

    def _build_island_flow_precursor_nx_data(self, islands: TileIslandBuilder, useNeutralFlow: bool) -> NxFlowGraphData:
        # has to be digraph because of input/output node pairs
        # positive island ids = 'in' nodes, negative island ids = corresponding 'out' node.
        graph: nx.DiGraph = nx.DiGraph()
        myTeam = self.team
        ourSet = {i.unique_id for i in islands.tile_islands_by_team_id[myTeam]}
        targetSet = {i.unique_id for i in islands.tile_islands_by_team_id[self.target_team]}
        if self.enemyGeneral is None or self.enemyGeneral.player == -1 or self.map.is_player_on_team(self.enemyGeneral.player, myTeam):
            raise Exception(f'Cannot call ensure_flow_graph_exists without setting enemyGeneral to some (enemy) tile.')
        # TODO use capacity to avoid chokepoints and such and route around enemy focal points?
        #  USE CAPACITY TO PREVENT OVER-FLOWING INTO BACKWARDS NEUTRAL LAND
        targetGeneralIsland: TileIsland = islands.tile_island_lookup.raw[self.enemyGeneral.tile_index]
        frGeneralIsland: TileIsland = islands.tile_island_lookup.raw[self.friendlyGeneral.tile_index]

        cumulativeDemand, demands = self._determine_initial_demands_and_split_input_output_nodes(graph, islands, ourSet, targetSet, useNeutralFlow)

        neutSinks = set()
        capacityLookup = {}
        # figure out capacity and neut sinks
        startTiles = []
        usPlayers = self.map.get_team_stats_by_team_id(self.team).livingPlayers
        for p in usPlayers:
            startTiles.extend(self.map.players[p].tiles)

        # if useNeutralFlow:
        def foreachFunc(t: Tile, dist: int) -> bool:
            island = islands.tile_island_lookup.raw[t.tile_index]
            if island is None:
                logbook.info(f'TILE {t} WAS NONE ISLAND IN FOREACH???')
                return True
            if island.team == myTeam:
                return False

            if island.team == -1:
                existCapac = capacityLookup.get(island.unique_id, -1)
                if existCapac < 0:
                    capacityLookup[island.unique_id] = 5 - dist
            return False

        SearchUtils.breadth_first_foreach_dist(
            self.map,
            startTiles,
            maxDepth=3,
            foreachFunc=foreachFunc)

        for island in islands.all_tile_islands:
            # TODO can change this to some other criteria for forcing the neutral sinks further out, letting us branch more out into useful neutral areas
            # sourceCapacityTemp = 100000
            # if island.team == -1:
            #     sourceCapacityTemp = 4
            # sourceCapacity = capacityLookup.get(island.unique_id, sourceCapacityTemp)
            sourceCapacity = 100000
            isIslandNeut = island.team == -1
            bordersFr = False
            bordersEn = False
            bordersBothPlayers = False
            for movableIsland in island.border_islands:
                # if movableIsland.team != -1:
                if movableIsland.team == self.target_team:
                    bordersEn = True
                if movableIsland.team == self.team:
                    bordersFr = True
            areAllBordersNeut = not bordersFr and not bordersEn
            # TODO this does not seem to be needed to keep the graph connected
            # if island != targetGeneralIsland:
            #     graph.add_edge(-targetGeneralIsland.unique_id, island.unique_id, weight=100000, capacity=1000000)
            # if island != frGeneralIsland:
            #     graph.add_edge(-frGeneralIsland.unique_id, island.unique_id, weight=100000, capacity=1000000)

            weight = 1
            # TODO Adding this is safe, and exerts even less backpressure from enemy general. Just need to tune.
            # if not self.use_back_pressure_from_enemy_general and island == targetGeneralIsland:
            #     weight = 10

            for movableIsland in island.border_islands:
                # destCapacityTemp = 100000
                # if movableIsland.team == -1:
                #     destCapacityTemp = 4
                # destCapacity = capacityLookup.get(movableIsland.unique_id, destCapacityTemp)
                destCapacity = 100000
                if self.log_debug:
                    logbook.info(f'For edge from {island} to {movableIsland} capacities were src {sourceCapacity}, dest {destCapacity}')
                edgeCapacity = max(sourceCapacity, destCapacity)
                # edge from out_island to in_movableIsland
                graph.add_edge(-island.unique_id, movableIsland.unique_id, weight=weight, capacity=edgeCapacity)

            sinkEnemyGeneral: bool
            if useNeutralFlow:
                sinkEnemyGeneral = areAllBordersNeut and island.unique_id not in capacityLookup
            else:
                sinkEnemyGeneral = isIslandNeut and not bordersBothPlayers
            # sinkEnemyGeneral = areAllBordersNeut and island.unique_id not in capacityLookup
            if sinkEnemyGeneral:
                neutSinks.add(island.unique_id)

        fakeNodes = None

        if self.use_back_pressure_from_enemy_general:
            demand = demands[targetGeneralIsland.unique_id] - cumulativeDemand
            graph.add_node(targetGeneralIsland.unique_id, demand=demand)

            weight = 10
            if not useNeutralFlow:
                weight = 0
            for neutSinkId in neutSinks:
                # capacity = 100000
                capacity = islands.tile_islands_by_unique_id[neutSinkId].tile_count
                # if not useNeutralFlow:
                #     capacity = islands.tile_islands_by_unique_id[neutSinkId].tile_count
                graph.add_edge(-targetGeneralIsland.unique_id, neutSinkId, weight=weight, capacity=capacity)

            graph.add_edge(-targetGeneralIsland.unique_id, frGeneralIsland.unique_id, weight=100000, capacity=1000000)
            graph.add_edge(-frGeneralIsland.unique_id, targetGeneralIsland.unique_id, weight=100000, capacity=1000000)
            graph.add_edge(-targetGeneralIsland.unique_id, frGeneralIsland.unique_id, weight=100000, capacity=1000000)
            graph.add_edge(-frGeneralIsland.unique_id, targetGeneralIsland.unique_id, weight=100000, capacity=1000000)
        else:
            fakeNode = random.randint(1000000, 9000000)
            while fakeNode in islands.tile_islands_by_unique_id:
                fakeNode = random.randint(1000000, 9000000)

            graph.add_node(fakeNode, demand=-cumulativeDemand)

            weight = 10
            if not useNeutralFlow:
                weight = 0
            for neutSinkId in neutSinks:
                capacity = islands.tile_islands_by_unique_id[neutSinkId].tile_count
                # if not useNeutralFlow:
                #     capacity = islands.tile_islands_by_unique_id[neutSinkId].tile_count
                graph.add_edge(fakeNode, neutSinkId, weight=weight, capacity=capacity)

            graph.add_edge(-targetGeneralIsland.unique_id, fakeNode, weight=weight, capacity=1000000)
            graph.add_edge(-frGeneralIsland.unique_id, fakeNode, weight=100000, capacity=1000000)
            graph.add_edge(fakeNode, targetGeneralIsland.unique_id, weight=100000, capacity=1000000)
            graph.add_edge(fakeNode, frGeneralIsland.unique_id, weight=100000, capacity=1000000)
            fakeNodes = {fakeNode}

        return NxFlowGraphData(graph, neutSinks, demands, cumulativeDemand, fakeNodes)

    def _determine_initial_demands_and_split_input_output_nodes(self, graph, islands, ourSet, targetSet, includeNeutralFlow: bool):
        demands = {}
        cumulativeDemand = 0
        # build input output connectivity edges
        for island in islands.all_tile_islands:
            # TODO this - 1 assumes no retraverses / pocket tiles with only one adjacency
            cost = island.tile_count - 1
            inAttrs = {}
            demand = island.tile_count - island.sum_army
            if island.unique_id in ourSet:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
            elif island.unique_id in targetSet:
                demand = island.sum_army + island.tile_count
                inAttrs['demand'] = demand
                cumulativeDemand += demand
            elif includeNeutralFlow and island.team == -1:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
                cost *= 2

            demands[island.unique_id] = demand

            graph.add_node(island.unique_id, **inAttrs)

            # edge from in_island to out_island with the node crossing cost
            graph.add_edge(island.unique_id, -island.unique_id, weight=cost, capacity=100000)

        return cumulativeDemand, demands

    def _find_island_consumed_tiles_from_borders(
            self,
            islandBuilder: TileIslandBuilder,
            incompleteSource: IslandFlowNode,
            unusedSourceArmy: int,
            flowTo: typing.List[IslandFlowEdge],
            negativeTiles: TileSet | None = None
    ) -> typing.Set[Tile]:
        q: typing.List[typing.Tuple[int, Tile]] = []

        incIsland = incompleteSource.island
        borders = set()
        borderLookup = islandBuilder.get_island_border_tile_lookup(incIsland)
        for destEdge in flowTo:
            try:
                borders.update(borderLookup[destEdge.target_flow_node.island.unique_id])
            except:
                logbook.error(f'failed to find border from {incompleteSource.island} to {destEdge.target_flow_node.island}')
                raise

        toUse = incIsland.sum_army - unusedSourceArmy - incIsland.tile_count

        for tile in borders:
            heapq.heappush(q, (1 - tile.army, tile))

        used = set()
        # overFillOpts = set()
        while q:
            negArmy, tile = heapq.heappop(q)
            if tile in used:
                continue

            toUse = toUse + negArmy
            used.add(tile)
            if toUse <= 0:
                break

            # nextToUse = toUse + negArmy
            # if nextToUse < 0:
            #     overFillOpts.add(tile)
            #     continue
            #
            # used.add(tile)
            # toUse = nextToUse
            # if toUse == 0:
            #     break

            for mv in tile.movable:
                if mv in incIsland.tile_set:
                    heapq.heappush(q, (1 - mv.army, mv))

        if toUse < 0:
            logbook.warn(
                f'toUse was {toUse}, expected 0. We will have extra army in the flow that isnt going to be known about by the algo. unusedSourceArmy was {unusedSourceArmy}, island tile army was {[t.army for t in incompleteSource.island.tiles_by_army]}')
        if toUse > 0:
            logbook.warn(f'toUse was {toUse}, expected 0. THIS IS INVALID. unusedSourceArmy was {unusedSourceArmy}, island tile army was {[t.army for t in incompleteSource.island.tiles_by_army]}')

        return used

    def _find_island_consumed_tiles_from_borders_by_count(
            self,
            islandBuilder: TileIslandBuilder,
            incompleteDest: IslandFlowNode,
            countToInclude: int,
            comeFrom: typing.Dict[int, IslandFlowNode],
            negativeTiles: TileSet | None = None
    ) -> typing.Set[Tile]:
        q: typing.List[typing.Tuple[int, Tile]] = []
        if countToInclude <= 0:
            return set()

        incIsland = incompleteDest.island
        borders = set()
        borderLookup = islandBuilder.get_island_border_tile_lookup(incIsland)
        for borderNode in comeFrom.values():
            try:
                borders.update(borderLookup[borderNode.island.unique_id])
            except:
                logbook.error(f'failed to find border from {incompleteDest.island} to {borderNode.island}')
                raise

        for tile in borders:
            heapq.heappush(q, (1 - tile.army, tile))

        used = set()
        while q:
            negArmy, tile = heapq.heappop(q)
            if tile in used:
                continue
            used.add(tile)
            if len(used) >= countToInclude:
                break

            for mv in tile.movable:
                if mv in incIsland.tile_set:
                    heapq.heappush(q, (1 - mv.army, mv))

        return used

    @staticmethod
    def is_any_tile_in_flow(rootNodes: typing.Iterable[IslandFlowNode], tiles: typing.Iterable[Tile]) -> bool:
        for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes):
            for tile in tiles:
                if tile in n.island.tile_set:
                    return True

        return False

    @staticmethod
    def are_all_tiles_in_flow(rootNodes: typing.Iterable[IslandFlowNode], tiles: typing.Iterable[Tile]) -> bool:
        toFind = set(t for t in tiles)
        for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes):
            toFind.difference_update(n.island.tile_set)
            if len(toFind) == 0:
                return True

        return False

    @staticmethod
    def is_tile_in_flow(rootNodes: typing.Iterable[IslandFlowNode], tile: Tile) -> bool:
        for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes):
            if tile in n.island.tile_set:
                return True

        return False

    @staticmethod
    def iterate_flow_nodes(rootNodes: typing.Iterable[IslandFlowNode]) -> typing.Generator[IslandFlowNode, None, None]:
        q = deque()

        n: IslandFlowNode
        initVisited = set()
        for n in rootNodes:
            if n in initVisited:
                continue
            q.append(n)
            initVisited.add(n)

        visited = set()

        while q:
            n = q.popleft()
            alreadyVis = n.island.unique_id in visited
            if alreadyVis:
                continue

            visited.add(n.island.unique_id)
            yield n

            for edge in n.flow_to:
                q.append(edge.target_flow_node)

        # TODO second test, remove EVERYTHING below this line later
        initVisited = set()
        iter = 0
        for n in rootNodes:
            if n in initVisited:
                continue
            q.append(n)
            initVisited.add(n)

        vis2 = set()
        while q:
            iter += 1
            n = q.popleft()
            vis2.add(n.island.unique_id)

            for edge in n.flow_to:
                q.append(edge.target_flow_node)
            if iter > 600:
                raise Exception(f'infinite looped. Nodes in loop: {" | ".join(str(n) for n in q)}')

        if len(vis2) != len(visited):
            raise Exception(
                f'flow nodes were corrupted, there were paths to different copies of the same node in them, with different flow_to contents, resulting in {len(vis2)} visited without visited set, and {len(visited)} with visited set.')

    @staticmethod
    def iterate_flow_children(rootNodes: typing.Iterable[IslandFlowNode]) -> typing.Generator[IslandFlowNode, None, None]:
        q = deque()

        n: IslandFlowNode
        initVisited = set()
        for n in rootNodes:
            if n in initVisited:
                continue
            for edge in n.flow_to:
                q.append(edge.target_flow_node)
            initVisited.add(n)

        visited = set()

        while q:
            n = q.popleft()
            alreadyVis = n.island.unique_id in visited
            if alreadyVis:
                continue

            visited.add(n.island.unique_id)
            yield n

            for edge in n.flow_to:
                q.append(edge.target_flow_node)

        # TODO second test, remove EVERYTHING below this line later
        iter = 0
        initVisited = set()
        for n in rootNodes:
            if n in initVisited:
                continue
            for edge in n.flow_to:
                q.append(edge.target_flow_node)
            initVisited.add(n)

        vis2 = set()
        while q:
            iter += 1
            n = q.popleft()
            vis2.add(n.island.unique_id)

            for edge in n.flow_to:
                q.append(edge.target_flow_node)

            if iter > 600:
                raise Exception(f'infinite looped. Nodes in loop: {" | ".join(str(n) for n in q)}')

        if len(vis2) != len(visited):
            raise Exception(
                f'flow nodes were corrupted, there were paths to different copies of the same node in them, with different flow_to contents, resulting in {len(vis2)} visited without visited set, and {len(visited)} with visited set.')

    def assertEverythingSafe(
            self,
            fullSearchTurns,
            negVt,
            turnsUsed,
            turnsLeft,
            armyToCap,
            randomTieBreak,
            targetTiles: typing.Deque[int],
            econValue,
            gathSum,
            # TODO
            frLeftoverArmy,
            friendlyTileLeftoverIdx,
            targetCalculatedNode,
            friendlyUncalculatedNode,
            visited: typing.Set[TileIsland],
            nextTargets,
            nextFriendlies,
            rootNodes,
            pairOptions,
    ):
        mismatches = []
        safetyChecker = {}
        minTurnsUsed = -1  # first move doesn't cost anything
        maxTurnsUsed = -1
        expectedTurnsUsed = -1
        for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values()):
            existing = safetyChecker.get(n.island.unique_id, None)
            if existing is not None:
                if existing != n:
                    mismatches.append(f'Corrupted root nodes; {n}  !=  {existing}')
                logbook.info(f'double visiting {existing}')
                # we flow to this node twice...? means we make two moves into it, at minimum.
                minTurnsUsed += 1
                maxTurnsUsed += 1
            else:
                safetyChecker[n.island.unique_id] = n
                if n.island.unique_id == targetCalculatedNode.island.unique_id:
                    minTurnsUsed += n.island.tile_count - len(targetTiles)
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count - len(targetTiles)
                elif n.island.unique_id == friendlyUncalculatedNode.island.unique_id:
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count - friendlyTileLeftoverIdx - 1
                    continue
                else:
                    minTurnsUsed += n.island.tile_count
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count

        if turnsUsed < minTurnsUsed:
            mismatches.append(f'rootNodes min traversed tilecount summed to {minTurnsUsed} but turnsUsed was {turnsUsed}')
        if turnsUsed > maxTurnsUsed:
            mismatches.append(f'rootNodes max traversed tilecount summed to {maxTurnsUsed} but turnsUsed was {turnsUsed}')
        if turnsUsed != expectedTurnsUsed:
            mismatches.append(f'rootNodes expected turnsUsed summed to {expectedTurnsUsed} but turnsUsed was {turnsUsed}')

        maxTurnsLeft = fullSearchTurns - minTurnsUsed
        minTurnsLeft = fullSearchTurns - maxTurnsUsed
        if turnsLeft < minTurnsLeft:
            mismatches.append(f'rootNodes min traversed turnsLeft (fullSearch - maxTurnsUsed) to {minTurnsLeft} but turnsLeft was {turnsLeft}')
        if turnsLeft > maxTurnsLeft:
            mismatches.append(f'rootNodes max traversed turnsLeft (fullSearch - minTurnsUsed) to {maxTurnsLeft} but turnsLeft was {turnsLeft}')
        #
        # # if len(safetyChecker) != len(visited):
        # #     mismatches.append(f'visited {len(visited)}  != len(safetyChecker) {len(safetyChecker)}')
        # #     for i, islandFlowNode in safetyChecker.items():
        # #         if islandFlowNode.island not in visited:
        # #             mismatches.append(f'  rootNodes visited {islandFlowNode} but it was not in visited.')
        # #
        # #     for island in visited:
        # #         match = safetyChecker.get(island.unique_id, None)
        # #         if match is None:
        # #             mismatches.append(f'  visited contained {island} but it was not in rootNodes.')
        #
        for n in ArmyFlowExpander.iterate_flow_nodes(nextTargets.values()):
            existing = safetyChecker.get(n.island.unique_id, None)
            if existing is not None:
                if existing != n:
                    mismatches.append(f'Corrupted nextTarget nodes; {n}  !=  {existing}')
            else:
                safetyChecker[n.island.unique_id] = n

        for n in ArmyFlowExpander.iterate_flow_nodes(nextFriendlies.values()):
            existing = safetyChecker.get(n.island.unique_id, None)
            if existing is not None:
                if existing != n:
                    mismatches.append(f'Corrupted nextFriendlies nodes; {n}  !=  {existing}')
            else:
                safetyChecker[n.island.unique_id] = n

        existing = safetyChecker.get(targetCalculatedNode.island.unique_id, None)
        if existing is not None:
            if existing != targetCalculatedNode:
                mismatches.append(f'Corrupted targetCalculatedNode node; {targetCalculatedNode}  !=  {existing}')
        else:
            safetyChecker[targetCalculatedNode.island.unique_id] = targetCalculatedNode

        existing = safetyChecker.get(friendlyUncalculatedNode.island.unique_id, None)
        if existing is not None:
            if existing != friendlyUncalculatedNode:
                mismatches.append(f'Corrupted friendlyUncalculatedNode node; {friendlyUncalculatedNode}  !=  {existing}')
        else:
            safetyChecker[friendlyUncalculatedNode.island.unique_id] = friendlyUncalculatedNode

        if mismatches:
            msg = "Search is corrupted;\r\n" + "\r\n".join(mismatches)
            logbook.error(msg)
            raise Exception(msg)

    def _get_a_star_priority_val(
            self,
            capValue: float,
            newEconValue: float,
            newTurnsUsed: int,
            newFrLeftoverArmy: int,
            newFriendlyTileLeftoverIdx: int,
            friendlyUncalculated: TileIsland,
            searchTurns: int,
            tgTiles: typing.Deque[int]
    ) -> float:
        """
        Must always OVERESTIMATE the potential reward if we want to properly A*.
        Reward should always be based on a full searchTurns length plan potential.

        @param capValue:
        @param newEconValue:
        @param newTurnsUsed:
        @param newFrLeftoverArmy:
        @param newFriendlyTileLeftoverIdx:
        @param friendlyUncalculated:
        @param searchTurns:
        @param tgTiles:
        @return:
        """
        # TODO we can look at the current tile islands adjacent friendly total and deduce whether we must waste at least one extra move bridging a gap to reach our full max value econ vt...?
        # TODO look at army avail to gather vs army avail to capture vs tiles avail to capture to estimate how move-effective the next gather would be...?
        frIslandArmyLeft = self.get_friendly_island_army_left(friendlyUncalculated, newFrLeftoverArmy, newFriendlyTileLeftoverIdx)

        maxCaps = frIslandArmyLeft // 2

        turnsAtOptimalCaps = searchTurns - newTurnsUsed - newFriendlyTileLeftoverIdx
        maxAddlEcon = 0.0
        if capValue == 1.0:
            turnsAtOptimalCaps -= len(tgTiles)
            # assume that we finish out this island and then go back to capturing enemy tiles for the rest of the time
            maxAddlEcon += capValue * len(tgTiles)
            maxCaps -= len(tgTiles) // 2

        if maxCaps < turnsAtOptimalCaps:
            # we must spend at LEAST one more turn gathering.
            # TODO this is probably where we can break A* and approximate how many turns we probably have to gather to keep capping, maybe? Or maybe this doesn't matter if using global visited set.
            turnsAtOptimalCaps -= 1

        maxAddlEcon += turnsAtOptimalCaps * 2

        bestRewardPossible = newEconValue + maxAddlEcon

        # the logic in the other spot
        # maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)
        # maxPossibleNewEconPerTurn = (newEconValue + maxCaps * capValue) / (newTurnsUsed + maxCaps + newFriendlyTileLeftoverIdx)

        return bestRewardPossible

    def get_friendly_island_army_left(self, friendlyUncalculated, newFrLeftoverArmy, newFriendlyTileLeftoverIdx):
        frIslandArmyLeft: int = newFrLeftoverArmy
        # TODO can get rid of this iteration by just also maintaining a 'friendlyIslandArmyUsed' that we can subtract from its total army to avoid these extra sums
        if newFriendlyTileLeftoverIdx * 2 >= friendlyUncalculated.tile_count:
            frIslandArmyLeft += friendlyUncalculated.sum_army - sum(t.army for t in friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx + 1:])
        else:
            frIslandArmyLeft += sum(t.army for t in friendlyUncalculated.tiles_by_army[0:newFriendlyTileLeftoverIdx + 1])
        if newFriendlyTileLeftoverIdx >= 0:
            frIslandArmyLeft -= newFriendlyTileLeftoverIdx + 1
        return frIslandArmyLeft

    def _is_flow_allowed(
            self,
            fromIsland: TileIsland,
            toIsland: TileIsland,
            armyAmount: int,
            isSubsequentTarget: bool = False,
            isSubsequentFriendly: bool = False,
            friendlyBorderingEnemy: typing.Set[TileIsland] | None = None
    ) -> bool:
        if not self.use_min_cost_flow_edges_only:
            if isSubsequentTarget:
                # TODO note this restricts us to only sink one-island-deep into FFA enemy territory who is not target player
                #  (since we allow them as destinations above but will only branch into neutral or target from there).
                if fromIsland.team != self.target_team and fromIsland.team != -1 and toIsland.team != self.target_team:
                    return False
            if isSubsequentFriendly:
                if fromIsland.team != self.team:  # or (friendlyBorderingEnemy and fromIsland in friendlyBorderingEnemy)
                    return False
            return True

        #
        # # TODO remove these later
        # if isSubsequentTarget:
        #     # TODO note this restricts us to only sink one-island-deep into FFA enemy territory who is not target player
        #     #  (since we allow them as destinations above but will only branch into neutral or target from there).
        #     if fromIsland.team != self.target_team and fromIsland.team != -1 and fromIsland.team != self.team and toIsland.team != self.target_team:
        #         return False

        # if isSubsequentFriendly:
        #     if fromIsland.team != self.team:  # or (friendlyBorderingEnemy and fromIsland in friendlyBorderingEnemy)
        #         return False


        allow = False
        fromNoNeut = self.flow_graph.flow_node_lookup_by_island_no_neut[fromIsland.unique_id]
        toNoNeut = self.flow_graph.flow_node_lookup_by_island_no_neut[toIsland.unique_id]
        for dest in fromNoNeut.flow_to:
            if toNoNeut == dest.target_flow_node:
                allow = True

        fromWithNeut = self.flow_graph.flow_node_lookup_by_island_inc_neut[fromIsland.unique_id]
        toWithNeut = self.flow_graph.flow_node_lookup_by_island_inc_neut[toIsland.unique_id]
        for dest in fromWithNeut.flow_to:
            if toWithNeut == dest.target_flow_node:
                allow = True

        return allow
        # fromWithNeut = self.flow_graph.flow_node_lookup_by_island_inc_neut[fromIsland.unique_id]
        #
        # if fromNoNeut.



class PlanDupeChecker(object):
    def __init__(self):
        self.plans: typing.List[FlowExpansionPlanOption] = []
        self.set: typing.Set[Tile] = set()

    def __str__(self) -> str:
        return ' | '.join(p.shortInfo() for p in self.plans)

    def __repr__(self) -> str:
        return str(self)