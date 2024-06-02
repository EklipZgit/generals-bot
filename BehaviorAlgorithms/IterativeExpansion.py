from __future__ import annotations

import heapq
import itertools
import time
import typing
from collections import deque
from enum import Enum

import logbook
import networkx as nx

import GatherUtils
import SearchUtils
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
        self.flow_to: typing.List[IslandFlowEdge] = []

    def __str__(self) -> str:
        targets = [f'({n.edge_army}) {{t{n.target_flow_node.island.team}:{n.target_flow_node.island.unique_id}/{n.target_flow_node.island.name} ({next(i for i in n.target_flow_node.island.tile_set)})}}' for n in self.flow_to]
        flowStr = ''
        if targets:
            flowStr = f' (-> {" | ".join(targets)})'
        return f'{{t{self.island.team}:{self.island.unique_id}/{self.island.name} ({next(i for i in self.island.tile_set)})}}{flowStr}'

    def __repr__(self) -> str:
        return str(self)

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
    def __init__(self, ourRootFlowNodes: typing.List[IslandFlowNode], enemyBackfillFlowNodes: typing.List[IslandFlowNode], enemyBackfillNeutEdges: typing.List[IslandFlowEdge]):
        self.root_flow_nodes: typing.List[IslandFlowNode] = ourRootFlowNodes
        self.enemy_backfill_nodes: typing.List[IslandFlowNode] = enemyBackfillFlowNodes
        self.enemy_neut_dump_edges: typing.List[IslandFlowEdge] = enemyBackfillNeutEdges

    def copy(self) -> IslandMaxFlowGraph:
        """
        Clones the lists and island flownodes / island flow edges, but not the islands
        @return:
        """

        clone = IslandMaxFlowGraph([n.copy() for n in self.root_flow_nodes], [n.copy() for n in self.enemy_backfill_nodes], [e.copy() for e in self.enemy_neut_dump_edges])

        return clone


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
    def __init__(self, graph: nx.DiGraph, neutSinks: typing.Set[int], demands: typing.Dict[int, int], cumulativeDemand: int):
        self.graph: nx.DiGraph = graph

        self.neutral_sinks: typing.Set[int] = neutSinks
        """The set of neutral-sink TileIsland unique_ids used in this graph. This is the set of all outskirt neutral tile islands who the enemy generals overflow was allowed to help fill with zero cost."""

        self.demand_lookup: typing.Dict[int, int] = demands
        """Demand amount lookup by island unique_id. Negative demand = want to gather army, positive = want to capture with army"""

        self.cumulative_demand: int = cumulativeDemand
        """The cumulative demand (prior to adjusting the nxGraph by making enemy general / cities as graph balancing sinks). If negative, then we do not have enough standing army to fully flow the entire map (or the part this graph covers) by the negative amount of army."""


class ArmyFlowExpander(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.team: int = map.team_ids_by_player_index[map.player_index]
        self.friendlyGeneral: Tile = map.generals[map.player_index]
        self.target_team: int = -1
        self.enemyGeneral: Tile | None = None

        self.nxGraphData: NxFlowGraphData | None = None
        self.flow_graph: IslandMaxFlowGraph | None = None

        self.include_neutral_flow: bool = True
        """Whether or not to allow flowing into neutral tiles. Make sure to set this before calling any methods on the class, as cached graph data will have already used or not used it once cached."""

        self.debug_render_capture_count_threshold: int = 10000
        """If there are more captures in any given plan option than this, then the option will be rendered inline as generated in a new debug viewer window."""

        self.log_debug: bool = False

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
    ) -> typing.List[FlowExpansionPlanOption]:
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

        flowPlan = self.find_flow_plans(islands, asPlayer, targetPlayer, turns, negativeTiles=negativeTiles)
        plans = sorted(flowPlan, key=lambda p: (p.econValue / p.length, p.length), reverse=True)

        return plans
        # output = []
        # for (target, source), planOptionsByTurns in flowPlan.items():
        #     for turns, bestPlan in planOptionsByTurns.items():
        #         output.append(bestPlan)
        #
        # return output

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
        flowGraph = self.build_max_flow_min_cost_flow_nodes(
            islands,
            ourIslands,
            targetIslands,
            searchingPlayer,
            turns,
            blockGatherFromEnemyBorders,
            negativeTiles
        )

        return []

    def build_max_flow_min_cost_flow_nodes(
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
        start = time.perf_counter()
        self.ensure_flow_graph_exists(islands)

        targetGeneralIsland: TileIsland = islands.tile_island_lookup.raw[self.enemyGeneral.tile_index]

        flowGraphLookup: typing.Dict[int, IslandFlowNode] = {}

        for island in islands.all_tile_islands:
            flowNode = IslandFlowNode(island, self.nxGraphData.demand_lookup[island.unique_id])
            flowGraphLookup[island.unique_id] = flowNode

        flowCost: int = -1
        """The cost of the whole flow network that is output. Pretty useless to us."""
        flowDict: typing.Dict[int, typing.Dict[int, int]]
        """The lookup from a given node to a dictionary of target nodes (and the army to send across to those nodes)."""

        # TODO look at gomory_hu_tree - A Gomory-Hu tree of an undirected graph with capacities is a weighted tree that represents the minimum s-t cuts for all s-t pairs in the graph.
        #  probably useless because doesn't use weight.

        # TODO look at cd_index (Time dependent)

        # TODO look at random_tournament + other tournament methods like hamiltonian_path ?
        if method == FlowGraphMethod.NetworkSimplex:
            flowCost, flowDict = nx.flow.network_simplex(self.nxGraphData.graph)
        elif method == FlowGraphMethod.CapacityScaling:
            flowCost, flowDict = nx.flow.capacity_scaling(self.nxGraphData.graph)
        elif method == FlowGraphMethod.MinCostFlow:
            flowDict = nx.flow.min_cost_flow(self.nxGraphData.graph)
        else:
            raise NotImplemented(str(method))

        logbook.info(f'{method} complete in {time.perf_counter() - start:.5f}s')

        start = time.perf_counter()

        backfillNeutEdges = []
        ourSet = {i.unique_id for i in ourIslands}
        targetSet = {i.unique_id for i in targetIslands}

        for nodeId, targets in flowDict.items():
            if nodeId > 0:
                # we don't care about the movement of army through a node so skip the input -> output entries
                continue

            nodeId = -nodeId
            sourceNode = flowGraphLookup[nodeId]

            # if len(targets) == 0:
            #     continue
            for targetNodeId, targetFlowAmount in targets.items():
                if targetFlowAmount == 0:
                    continue
                ourSet.discard(targetNodeId)
                targetSet.discard(targetNodeId)
                targetNode = flowGraphLookup[targetNodeId]
                edge = IslandFlowEdge(targetNode, targetFlowAmount)
                if targetNodeId in self.nxGraphData.neutral_sinks and sourceNode.island is targetGeneralIsland:
                    backfillNeutEdges.append(edge)
                    continue

                sourceNode.set_flow_to(targetNode, targetFlowAmount)
                logbook.info(f'ADDING FLOW EDGE {sourceNode} -{targetFlowAmount}> {targetNode}')

        finalRootFlowNodes = [flowGraphLookup[id] for id in ourSet]
        enemyBackfillFlowNodes = [flowGraphLookup[id] for id in targetSet]

        flowGraph = IslandMaxFlowGraph(finalRootFlowNodes, enemyBackfillFlowNodes, backfillNeutEdges)

        logbook.info(f'{method} FlowNodes complete in {time.perf_counter() - start:.5f}s')
        return flowGraph

    def find_flow_plans(
            self,
            islands: TileIslandBuilder,
            searchingPlayer: int,
            targetPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: TileSet | None = None,
    ) -> typing.List[FlowExpansionPlanOption]:
        """
        Build a plan of which islands should flow into which other islands.
        This is basically a bi-directional search from all borders between islands, and currently brute forces all possible combinations.

        @param islands:
        @param searchingPlayer:
        @param targetPlayer:
        @param turns:
        @param blockGatherFromEnemyBorders:
        @param negativeTiles:
        @return:
        """

        start = time.perf_counter()

        opts: typing.Dict[typing.Tuple[TileIsland, TileIsland], typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]]] = {}
        """
        Inner tuple is """

        self.team = myTeam = self.map.team_ids_by_player_index[searchingPlayer]
        self.target_team = targetTeam = self.map.team_ids_by_player_index[targetPlayer]

        ourIslands = islands.tile_islands_by_player[searchingPlayer]
        targetIslands = islands.tile_islands_by_team_id[targetTeam]

        # self.flow_graph = self.build_flow_graph(
        #     islands,
        #     ourIslands,
        #     targetIslands,
        #     searchingPlayer,
        #     turns,
        #     # blockGatherFromEnemyBorders=
        #     includeNeutralDemand=True,
        #     negativeTiles=negativeTiles,
        #     # method=FlowGraphMethod.CapacityScaling
        # )

        turnsUsed: int

        targetCalculatedNode: IslandFlowNode
        friendlyUncalculatedNone: IslandFlowNode
        targetCalculated: TileIsland
        friendlyUncalculated: TileIsland
        turnsLeft: int
        numTilesLeftToCapFromTarget: int
        armyToCap: int
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
        """for each starting border pair, a new dict of distance -> (flowGraph, econValue, turnsUsed, armyRemaining, incompleteTargetIsland or none, incompleteFriendlyIsland or none, unusedIncompleteSourceArmy, friendlyGatheredSum)"""

        maxTeam = max(self.map.team_ids_by_player_index)
        capValueByTeam = [1 for t in range(maxTeam + 2)]
        capValueByTeam[myTeam] = 0
        # TODO intentional decision for now to value flow expansion en caps lower than other expansion-fed algos do, to prioritize their more concrete results over these wishywashy results.
        capValueByTeam[targetTeam] = 2

        if blockGatherFromEnemyBorders:
            friendlyBorderingEnemy = {i for i in itertools.chain.from_iterable(t.border_islands for t in targetIslands if t.tile_count_all_adjacent_friendly > 8) if i.team == myTeam}
        else:
            friendlyBorderingEnemy = set()

        q: HeapQueue[typing.Tuple[
            float,
            int,
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
        ]] = HeapQueue()

        queueIterCount = 0
        tileIterCount = 0
        dumpIterCount = 0
        tieBreaker = 0
        for targetIsland in islands.all_tile_islands:
            if targetIsland.team == myTeam:
                continue
            for adjacentFriendlyIsland in targetIsland.border_islands:
                if adjacentFriendlyIsland.team != myTeam:
                    continue
                tgCapValue = capValueByTeam[targetIsland.team]
                tieBreaker += 1
                pairOptions = {}
                opts[(targetIsland, adjacentFriendlyIsland)] = pairOptions
                # turns+1 because pulling the first tile doesn't count as a move (the tile we move to counts as the move, whether thats to enemy or to another friendly gather tile), however this algo doesn't know whether it is first move or not, so we just start the whole cycle with one extra 'turn' so we can pull that initial tile for free.
                maxPossibleAddlCaps = (adjacentFriendlyIsland.sum_army - adjacentFriendlyIsland.tile_count) // 2
                maxPossibleNewEconPerTurn = (maxPossibleAddlCaps * tgCapValue) / (maxPossibleAddlCaps + adjacentFriendlyIsland.tile_count)
                sourceNode = IslandFlowNode(adjacentFriendlyIsland, desiredArmy=0 - adjacentFriendlyIsland.sum_army + adjacentFriendlyIsland.tile_count)
                destNode = IslandFlowNode(targetIsland, desiredArmy=targetIsland.sum_army + targetIsland.tile_count)
                if self.log_debug:
                    logbook.info(f'ADDING EDGE (start) FROM {sourceNode} TO {destNode}')
                sourceNode.set_flow_to(destNode, 0)
                visited = set()
                visited.add(targetIsland)
                q.put((
                    maxPossibleNewEconPerTurn,
                    -1,
                    turns + 1,
                    targetIsland.tile_count,
                    targetIsland.sum_army + targetIsland.tile_count,
                    tieBreaker,
                    deque(t.army for t in targetIsland.tiles_by_army),
                    0.0,
                    0,
                    0,  #frTileLeftoverArmy,
                    sourceNode.island.tile_count - 1,  #friendlyTileLeftoverIdx,
                    destNode,
                    sourceNode,
                    visited,
                    {t: destNode for t in targetIsland.border_islands if t.team != myTeam},  # nextTargets
                    {t: sourceNode for t in adjacentFriendlyIsland.border_islands if t.team == myTeam and t not in friendlyBorderingEnemy},  # nextFriendlies
                    {sourceNode.island.unique_id: sourceNode},  # rootNodes
                    pairOptions
                ))

                logbook.info(f'------------------\r\n---------------\r\nBEGINNING {targetIsland}<--->{adjacentFriendlyIsland}')
                while q:
                    (
                        negVt,
                        turnsUsed,
                        turnsLeft,
                        numTilesLeftToCapFromTarget,
                        armyToCap,
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

                    # TODO THESE ARE FOR DEBUGGING PURPOSES TO ENSURE NO REFERENCE CROSS SECTION AND TO WHITTLE DOWN WHICH VARIABLE IS THE PROBLEM:
                    targetTiles = targetTiles.copy()
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
                            f'popped {friendlyUncalculated} <-> {targetCalculated}  (nextFriendlies {" | ".join(str(n.unique_id) for n in nextFriendlies.keys())}  ->  {" | ".join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(nextFriendlies.values()))}')
                        logbook.info(
                            f'  root nodes: root nodes {" | ".join(str(n.island.unique_id) for n in rootNodes.values())}  ->  {" | ".join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_children(rootNodes.values()))}')
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

                    if turnsLeft > 4:
                        self.assertEverythingSafe(
                            turns,
                            negVt,
                            turnsUsed,
                            turnsLeft,
                            numTilesLeftToCapFromTarget,
                            armyToCap,
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

                    # have to leave 1's behind when leaving our own land
                    friendlyCappingArmy = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count
                    necessaryToFullyCap = armyToCap
                    # have to leave 1's behind when capping enemy land, too
                    armyLeftIfFullyCapping = friendlyCappingArmy - necessaryToFullyCap
                    turnsLeftIfFullyCapping = turnsLeft - numTilesLeftToCapFromTarget - friendlyUncalculated.tile_count
                    validOpt = True
                    # TODO turn short circuit back on? Probably no because then we can't do the partial captures...?
                    if False and turnsLeftIfFullyCapping >= 0 and armyLeftIfFullyCapping >= 0:
                        # then we can actually dump all in and shortcut the more expensive logic
                        turnsLeft = turnsLeftIfFullyCapping
                        armyToCap = 0 - armyLeftIfFullyCapping
                        econValue += numTilesLeftToCapFromTarget * capValue
                        nextGathedSum += friendlyCappingArmy
                        numTilesLeftToCapFromTarget = 0

                        turnsUsed = turns - turnsLeft
                        existingBestTuple = pairOptions.get(turnsUsed, None)

                        if validOpt and (existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed):
                            pairOptions[turnsUsed] = (
                                rootNodes,
                                econValue,
                                turnsUsed,
                                0 - armyToCap,
                                None,  # TODO this may be an incomplete capture... right...?
                                None,
                                None,
                                nextGathedSum
                            )
                    else:
                        # then we can't dump it all in, have to do iterative check.

                        armyToDump = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count  # We need to leave 1 army behind per tile.
                        # # ############## we start at 1, because pulling the first tile doesn't count as a move (the tile we move to counts as the move, whether thats to enemy or to another friendly gather tile)
                        # friendlyIdx = 1
                        # frTileArmy = friendlyUncalculated.tiles_by_army[0].army
                        # friendlyIdx = 0
                        while armyToDump > 0 and targetTiles and turnsLeft > 0:
                            tgTileArmyToCap = targetTiles.popleft() + 1
                            # if validOpt:
                            dumpIterCount += 1

                            # pull as many fr tiles as necessary to cap the en tile
                            # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
                            while frLeftoverArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyTileLeftoverIdx >= 0:
                                frTileArmy = friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
                                nextGathedSum += frTileArmy
                                frLeftoverArmy += frTileArmy
                                turnsLeft -= 1
                                friendlyTileLeftoverIdx -= 1
                                # friendlyIdx += 1
                                tileIterCount += 1

                            if frLeftoverArmy < tgTileArmyToCap:
                                # validOpt = False
                                targetTiles.appendleft(tgTileArmyToCap - frLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
                                # turnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
                                armyToCap -= frLeftoverArmy
                                # we dont use this after breaking
                                # armyToDump = 0
                                if self.log_debug:
                                    logbook.info(f'  broke early on standard army usage {frLeftoverArmy} < {tgTileArmyToCap} at friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army}) w/ turnsLeft {turnsLeft} and targetTiles {targetTiles}')
                                frLeftoverArmy = 0
                                break

                            # cap the en tile
                            numTilesLeftToCapFromTarget -= 1
                            econValue += capValue
                            armyToCap -= tgTileArmyToCap
                            armyToDump -= tgTileArmyToCap
                            frLeftoverArmy -= tgTileArmyToCap
                            turnsLeft -= 1
                            turnsUsed = turns - turnsLeft
                            existingBestTuple = pairOptions.get(turnsUsed, None)

                            if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed:
                                pairOptions[turnsUsed] = (
                                    rootNodes,
                                    econValue,
                                    turnsUsed,
                                    armyToDump,
                                    targetCalculated if targetTiles else None,
                                    friendlyUncalculated if friendlyTileLeftoverIdx >= 0 else None,
                                    armyToDump if friendlyTileLeftoverIdx >= 0 else None,
                                    nextGathedSum,
                                )

                            if numTilesLeftToCapFromTarget < 0:
                                raise AssertionError('todo remove later, this should never be possible or we would have hit the other case above.')

                        # Necessary because when we terminate the loop early above due to running out of TARGET tiles, we need to keep track of the remaining army we have to gather for the second loop below.
                        armyToCap -= armyToDump

                    if numTilesLeftToCapFromTarget == 0:
                        # we need to include new targets, then.
                        dumpIterCount, tieBreaker, tileIterCount = self._queue_next_targets_and_next_friendlies(
                            armyToCap,
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
                            numTilesLeftToCapFromTarget,
                            turns,
                            turnsLeft,
                            visited)
                    else:
                        tieBreaker = self._queue_next_friendlies_only(
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
                            numTilesLeftToCapFromTarget,
                            turns,
                            turnsLeft,
                            visited)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion iteration complete in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')

        output = []
        for (targetIsland, source), planOptionsByTurns in opts.items():
            for turns, (rootNodes, econValue, otherTurns, armyRemaining, incompleteTarget, incompleteSource, unusedSourceArmy, gathedArmySum) in planOptionsByTurns.items():
                if otherTurns != turns:
                    raise Exception(f'Shouldnt happen, turn mismatch {turns} vs {otherTurns}')

                if armyRemaining < 0:
                    # then this is a partial capture option, we already pruned out the other moves in theory, and it is already worst-case moves assuming our largest tiles are furthest and their largest tiles are in front
                    armyRemaining = 0

                plan = self._build_flow_expansion_option(islands, targetIsland, source, rootNodes, econValue, armyRemaining, turns, targetIslands, ourIslands, incompleteTarget, incompleteSource, unusedSourceArmy)
                logbook.info(f'built gcap plan {plan}\r\n   FOR econValue {econValue:.2f}, otherTurns {otherTurns}, armyRemaining {armyRemaining}, incompleteTarget {incompleteTarget}, incompleteSource {incompleteSource}, unusedSourceArmy {unusedSourceArmy}, gathedArmySum {gathedArmySum}')
                output.append(plan)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion complete in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')

        return output

    def _queue_next_targets_and_next_friendlies(
            self,
            armyToCap,
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
                    logbook.info(f'skipped targ {nextTargetIsland.name} from {nextTargetFromNode.name}')
                continue

            capValue = capValueByTeam[nextTargetIsland.team]

            # capture as much of the new target as we can
            newTilesToCap = tilesToCap + nextTargetIsland.tile_count
            newEconValue = econValue
            newTargetTiles = deque(t.army for t in nextTargetIsland.tiles_by_army)
            newTurnsLeft = turnsLeft
            newArmyToDump = 0 - armyToCap
            newArmyToCap = armyToCap
            newArmyToCap += nextTargetIsland.sum_army + nextTargetIsland.tile_count
            newFriendlyTileLeftoverIdx = friendlyTileLeftoverIdx
            newFrLeftoverArmy = frLeftoverArmy

            # proves only these 3 value variables are being modified (of value variables)
            dumpIterCount, tieBreaker, tileIterCount = self._calculate_next_target_and_queue_next_friendlies(
                capValue,
                dumpIterCount,
                friendlyBorderingEnemy,
                friendlyUncalculated,
                myTeam,
                newArmyToCap,
                newArmyToDump,
                newEconValue,
                newFrLeftoverArmy,
                newFriendlyTileLeftoverIdx,
                newTargetTiles,
                newTilesToCap,
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
            newArmyToCap,
            newArmyToDump,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTilesToCap,
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
        dumpIterCount, newArmyToCap, newEconValue, newTilesToCap, newTurnsLeft, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, tileIterCount = self._calculate_next_target_values(
            capValue,
            dumpIterCount,
            friendlyUncalculated,
            newArmyToCap,
            newArmyToDump,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTilesToCap,
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
                newArmyToCap,
                newEconValue,
                newTargetTiles,
                newTilesToCap,
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
                    newArmyToCap,
                    newEconValue,
                    newTargetTiles,
                    newTilesToCap,
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
            newArmyToCap,
            newEconValue,
            newTargetTiles,
            newTilesToCap,
            newTurnsLeft,
            nextFriendlies,
            nextFriendlyFromNode,
            nextFriendlyUncalculated,
            nextGathedSum,
            nextFrLeftoverArmy,
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
        maxPossibleAddlCaps = (nextFriendlyUncalculated.sum_army - nextFriendlyUncalculated.tile_count) // 2
        # the logic in the other spot
        # maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)
        maxPossibleNewEconPerTurn = (newEconValue + maxPossibleAddlCaps * capValue) / (newTurnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)

        if self.log_debug:
            logbook.info(f'tg {nextTargetIsland}, newTurnsUsed {newTurnsUsed} newTurnsLeft {newTurnsLeft}, fr {nextFriendlyUncalculated}')

        lookup = {}

        newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}

        copyTargetFromNode = lookup[nextTargetFromNode.island.unique_id]
        nextTargetCalculatedNode = IslandFlowNode(nextTargetIsland, nextTargetIsland.sum_army + nextTargetIsland.tile_count)

        if copyTargetFromNode.island not in nextTargetCalculatedNode.island.border_islands:
            # TODO remove once algo reliable
            raise AssertionError(f'Tried to add illegal edge from {copyTargetFromNode} TO {nextTargetCalculatedNode}')
        if self.log_debug:
            logbook.info(f'adding target (friendly) edge from {copyTargetFromNode.island.unique_id} TO {nextTargetCalculatedNode.island.unique_id}')
        copyTargetFromNode.set_flow_to(nextTargetCalculatedNode, 0)

        # TODO remove try catches
        try:
            copyFriendlyFromNode = lookup[nextFriendlyFromNode.island.unique_id]
        except:
            logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
            raise
        newRootNodes.pop(copyFriendlyFromNode.island.unique_id, None)
        nextFriendlyUncalculatedNode = IslandFlowNode(nextFriendlyUncalculated, 0 - nextFriendlyUncalculated.sum_army + nextFriendlyUncalculated.tile_count)
        if nextFriendlyUncalculatedNode.island not in copyFriendlyFromNode.island.border_islands:
            # TODO remove once algo reliable
            raise AssertionError(f'Tried to add illegal edge from {nextFriendlyUncalculatedNode} TO {copyFriendlyFromNode}')
        if self.log_debug:
            logbook.info(f'adding friendly (target) edge from {nextFriendlyUncalculatedNode.island.unique_id} TO {copyFriendlyFromNode.island.unique_id}')

        nextFriendlyUncalculatedNode.set_flow_to(copyFriendlyFromNode, 0)
        newRootNodes[nextFriendlyUncalculated.unique_id] = nextFriendlyUncalculatedNode
        newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}
        del newNextFriendlies[nextFriendlyUncalculated]
        for adj in nextFriendlyUncalculated.border_islands:
            if adj.team != myTeam or adj in visited or adj in friendlyBorderingEnemy or adj in newNextFriendlies:
                continue
            newNextFriendlies[adj] = nextFriendlyUncalculatedNode

        # this lets us visit in arbitrary orders (ew)
        newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}
        del newNextTargets[nextTargetIsland]
        for adj in nextTargetIsland.border_islands:
            # TODO note this restricts us to only sink one-island-deep into FFA enemy territory who is not target player
            #  (since we allow them as destinations above but will only branch into neutral or target from there).
            if (adj.team != targetTeam and adj.team != -1) or adj in visited:
                continue
            newNextTargets[adj] = nextTargetCalculatedNode

        tieBreaker += 1

        q.put((
            0 - maxPossibleNewEconPerTurn,
            newTurnsUsed,
            newTurnsLeft,
            newTilesToCap,
            newArmyToCap,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            nextFrLeftoverArmy,
            nextFriendlyUncalculated.tile_count - 1,
            nextTargetCalculatedNode,
            nextFriendlyUncalculatedNode,
            # visited.copy(),
            visited,  # note we are not cloning visited, so this isn't full TSP
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        ))
        return tieBreaker

    def _queue_current_friendlies_from_next_target_values(
            self,
            capValue,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newArmyToCap,
            newEconValue,
            newTargetTiles,
            newTilesToCap,
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
        frArmyLeft = sum(t.army for t in friendlyUncalculated.tiles_by_army[0:newFriendlyTileLeftoverIdx + 1]) - newFriendlyTileLeftoverIdx
        maxPossibleAddlCaps = frArmyLeft // 2
        # the logic in the other spot
        # maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)
        maxPossibleNewEconPerTurn = (newEconValue + maxPossibleAddlCaps * capValue) / (newTurnsUsed + maxPossibleAddlCaps + newFriendlyTileLeftoverIdx)
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
            logbook.info(f'adding target (solo) edge from {copyTargetFromNode.island.unique_id} TO {nextTargetCalculatedNode.island.unique_id}')

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
        for adj in nextTargetIsland.border_islands:
            # TODO note this restricts us to only sink one-island-deep into FFA enemy territory who is not target player
            #  (since we allow them as destinations above but will only branch into neutral or target from there).
            if (adj.team != targetTeam and adj.team != -1) or adj in visited:
                continue
            newNextTargets[adj] = nextTargetCalculatedNode

        tieBreaker += 1

        q.put((
            0 - maxPossibleNewEconPerTurn,
            newTurnsUsed,
            newTurnsLeft,
            newTilesToCap,
            newArmyToCap,
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
        ))
        return tieBreaker

    def _calculate_next_target_values(
            self,
            capValue,
            dumpIterCount,
            friendlyUncalculated,
            newArmyToCap,
            newArmyToDump,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTilesToCap,
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

        while newArmyToDump > 0 and newTargetTiles and newTurnsLeft > 0:
            tgTileArmyToCap = newTargetTiles.popleft() + 1
            # if validOpt:
            dumpIterCount += 1

            # pull as many fr tiles as necessary to cap the en tile
            # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
            while newFrLeftoverArmy < tgTileArmyToCap and newTurnsLeft > 1 and newFriendlyTileLeftoverIdx >= 0:
                newFrLeftoverArmy += friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
                newTurnsLeft -= 1
                newFriendlyTileLeftoverIdx -= 1
                # friendlyIdx += 1
                tileIterCount += 1

            if newFrLeftoverArmy < tgTileArmyToCap:
                # # validOpt = False
                newTargetTiles.appendleft(tgTileArmyToCap - newFrLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
                # # newTurnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
                # # newFriendlyTileLeftoverIdx += 1
                newArmyToCap -= newFrLeftoverArmy
                # newArmyToDump -= newFrLeftoverArmy
                if self.log_debug:
                    logbook.info(f'    broke early on {newFrLeftoverArmy} < {tgTileArmyToCap} at newFriendlyTileLeftoverIdx {newFriendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx].army}) w/ newTurnsLeft {newTurnsLeft} and newTargetTiles {newTargetTiles}, newArmyToCap {newArmyToCap}')
                newFrLeftoverArmy = 0
                # # armyToDump = 0
                break

            # cap the en tile
            newTilesToCap -= 1
            newEconValue += capValue
            newArmyToCap -= tgTileArmyToCap
            newArmyToDump -= tgTileArmyToCap
            newFrLeftoverArmy -= tgTileArmyToCap
            newTurnsLeft -= 1

            turnsUsed = turns - newTurnsLeft
            existingBestTuple = pairOptions.get(turnsUsed, None)

            if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < newEconValue / turnsUsed:
                pairOptions[turnsUsed] = (
                    rootNodes,
                    newEconValue,
                    turnsUsed,
                    newArmyToDump,
                    nextTargetIsland if newTargetTiles else None,
                    friendlyUncalculated if newFriendlyTileLeftoverIdx >= 0 else None,
                    newArmyToDump if newFriendlyTileLeftoverIdx >= 0 else None,
                    nextGathedSum
                )
        # #TODO THIS WAS COMMENTED
        # armyLeftOver = 0 - armyToCap
        # while armyLeftOver > 0 and newTargetTiles:
        #     tileArmyToCap = newTargetTiles.popleft() + 1
        #
        #     if tileArmyToCap > armyLeftOver:
        #         newTargetTiles.appendleft(tileArmyToCap - 1)
        #         break
        #
        #     # then we technically actually pre-capture some of the tiles to capture here
        #     #  ought to increment newTilesCapped and decrement newTilesToCap based on the tile values in the island...?
        #     newTilesToCap -= 1
        #     newEconValue += capValue
        #     newArmyToCap -= tileArmyToCap
        #     armyLeftOver -= tileArmyToCap
        #     newTurnsLeft -= 1
        #
        #     if newArmyToCap <= 0:
        #         turnsUsed = turns - newTurnsLeft
        #         existingBestTuple = pairOptions.get(turnsUsed, None)
        #
        #         if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < newEconValue / turnsUsed:
        #             pairOptions[turnsUsed] = (
        #                 rootNodes,
        #                 newEconValue,
        #                 turnsUsed,
        #                 armyToDump,
        #                 targetCalculated if targetTiles else None,
        #                 friendlyUncalculated if friendlyTileLeftoverIdx >= 0 else None,
        #                 armyToDump if friendlyTileLeftoverIdx >= 0 else None,
        #                 nextGathedSum,
        #             )
        #
        #             pairOptions[turnsUsed] = (
        #                 flowGraph,
        #                 newEconValue,
        #                 turnsUsed,
        #                 0 - newArmyToCap
        #             )
        # # END TODO
        return dumpIterCount, newArmyToCap, newEconValue, newTilesToCap, newTurnsLeft, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, tileIterCount

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
            tilesToCap,
            turns,
            turnsLeft,
            visited
    ):
        turnsUsed = turns - turnsLeft
        for (nextFriendlyUncalculated, nextFriendlyFromNode) in nextFriendlies.items():
            if nextFriendlyUncalculated in visited:
                # logbook.info(f'skipped src  {newFriendlyUncalculated.name} from {friendlyUncalculated.name}')
                continue

            maxPossibleAddlCaps = (nextFriendlyUncalculated.sum_army - nextFriendlyUncalculated.tile_count) // 2
            maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)

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
            if nextFriendlyUncalculatedNode.island not in copyFriendlyFromNode.island.border_islands:
                # TODO remove once algo reliable
                raise Exception(f'Tried to add illegal edge from {nextFriendlyUncalculatedNode} TO {copyFriendlyFromNode}')

            if self.log_debug:
                logbook.info(f'adding friendly edge from {nextFriendlyUncalculatedNode.island.unique_id} TO {copyFriendlyFromNode.island.unique_id}')
            nextFriendlyUncalculatedNode.set_flow_to(copyFriendlyFromNode, 0)
            newRootNodes[nextFriendlyUncalculated.unique_id] = nextFriendlyUncalculatedNode

            newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}
            del newNextFriendlies[nextFriendlyUncalculated]
            for adj in nextFriendlyUncalculated.border_islands:
                if adj.team != myTeam or adj in visited or adj in newNextFriendlies:
                    continue
                newNextFriendlies[adj] = nextFriendlyUncalculatedNode

            newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}

            tieBreaker += 1
            q.put((
                0 - maxPossibleNewEconPerTurn,
                turnsUsed,
                turnsLeft,
                tilesToCap,
                armyToCap,
                tieBreaker,
                targetTiles.copy(),
                econValue,
                nextGathedSum,
                frLeftoverArmy,
                nextFriendlyUncalculated.tile_count - 1,
                copyTargetCalculatedNode,
                nextFriendlyUncalculatedNode,
                # visited.copy(),
                visited,  # note we are not cloning visited, so this isn't full TSP
                newNextTargets,
                newNextFriendlies,
                newRootNodes,
                pairOptions
            ))
        return tieBreaker

    def _build_flow_expansion_option(
            self,
            islandBuilder: TileIslandBuilder,
            target: TileIsland,
            source: TileIsland,
            sourceNodes: typing.Dict[int, IslandFlowNode],
            econValue: float,
            armyRemaining: int,
            turns,
            targetIslands: typing.List[TileIsland],
            ourIslands: typing.List[TileIsland],
            incompleteTarget: TileIsland | None,
            incompleteSource: TileIsland | None,
            unusedSourceArmy: int | None,
            negativeTiles: TileSet | None = None,
            useTrueValueGathered: bool = True,
    ) -> FlowExpansionPlanOption:
        # if self.log_debug:
        logbook.info(f'building plan for {source.name}->{target.name} (econ {econValue:.2f} turns {turns} army rem {armyRemaining})')

        # TODO we want to keep our moves as wide across any borders as possible, if we combine everything into one big tile then we have the potential to waste moves.
        # need to build our initial lines outwards from the border as straight as possible, then combine as needed as captures fail.
        # fromMatrix: MapMatrixInterface[Tile] = MapMatrix(self.map)
        # fromArmy: MapMatrixInterface[int] = MapMatrix(self.map)

        # border = set(itertools.chain.from_iterable(t.movable for t in target.tile_set if t in source.tile_set))
        capping = set()
        gathing = set()
        targetTeam = self.target_team
        team = self.team

        moves = []
        captures = 0
        finalTurns = 0

        curArmy: int
        curIdk: int
        curNode: IslandFlowNode
        fromNode: IslandFlowNode | None

        incompleteSourceNode: IslandFlowNode | None = None
        incompleteTargetNode: IslandFlowNode | None = None
        incompleteTargetFrom: typing.Dict[int, IslandFlowNode] = {}
        allBorderTiles = set()

        lookup = {}
        q: typing.List[typing.Tuple[int, int, IslandFlowNode, IslandFlowNode | None]] = [(0, 0, n, None) for n in sourceNodes.values()]
        while q:
            curArmy, curIdk, curNode, fromNode = q.pop()
            if fromNode is not None and fromNode.island.team == team and curNode.island.team != team:
                borderTiles = islandBuilder.get_inner_border_tiles(fromNode.island, curNode.island)
                allBorderTiles.update(borderTiles)

            lookup[curNode.island.unique_id] = curNode
            if curNode.island == incompleteTarget:
                incompleteTargetNode = curNode
                if fromNode:
                    incompleteTargetFrom[fromNode.island.unique_id] = fromNode
            elif curNode.island == incompleteSource:
                incompleteSourceNode = curNode
                curArmy += curNode.island.sum_army - curNode.island.tile_count - unusedSourceArmy
            else:
                if curNode.island.team == team:
                    gathing.update(curNode.island.tile_set)
                    curArmy += curNode.island.sum_army - curNode.island.tile_count
                else:
                    capping.update(curNode.island.tile_set)
                    curArmy -= curNode.island.sum_army + curNode.island.tile_count

            for edge in curNode.flow_to:
                # right now can only flow to one,
                # TODO must figure out how to split in future when can target multiple....
                edge.edge_army = curArmy
                q.append((curArmy, curIdk, edge.target_flow_node, curNode))

        if incompleteSourceNode:
            tiles = self._find_island_consumed_tiles_from_borders(islandBuilder, incompleteSourceNode, unusedSourceArmy, incompleteSourceNode.flow_to, negativeTiles)
            gathing.update(tiles)

        if incompleteTargetNode:
            tiles = self._find_island_consumed_tiles_from_borders_by_count(islandBuilder, incompleteTargetNode, turns - len(gathing) - len(capping), incompleteTargetFrom, negativeTiles)
            capping.update(tiles)

        gatherPlan = GatherUtils.convert_contiguous_tiles_to_gather_tree_nodes_with_values(
            self.map,
            allBorderTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=self.friendlyGeneral.player,
            priorityMatrix=None,
            useTrueValueGathered=useTrueValueGathered,
            captures=capping,
        )

        # ok now we need to figure out how to route the captures...
        # self.flow_graph

        #
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

        return gatherPlan

    def live_render_capture_stuff(self, islandBuilder: TileIslandBuilder, capping: TileSet, gathing: TileSet, incompleteSource: TileIsland, incompleteTarget: TileIsland, sourceUnused: int | None = None):
        from Viewer import ViewerProcessHost
        inf = f'capping {len(capping)}, gathing {len(gathing)}'

        debugViewInfo = ViewerProcessHost.get_renderable_view_info(self.map)
        for tile in capping:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.RED)
        for tile in gathing:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.GREEN)
        debugViewInfo.add_info_line_no_log(f'GREEN = gathing')
        debugViewInfo.add_info_line_no_log(f'ORANGE = capping')
        if incompleteTarget:
            debugViewInfo.add_info_line_no_log(f'ORANGE = incompleteTarget tileset')
            for tile in incompleteTarget.tile_set:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.ORANGE, radiusReduction=10)
        if incompleteSource:
            debugViewInfo.add_info_line_no_log(f'BLUE = incompleteSource tileset ({sourceUnused} unused)')
            for tile in incompleteSource.tile_set:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.BLUE, radiusReduction=8)

        islandBuilder.add_tile_islands_to_view_info(debugViewInfo, printIslandInfoLines=True, printIslandNames=True)
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
    def add_flow_graph_to_view_info(flowGraph: IslandMaxFlowGraph, viewInfo: ViewInfo):
        q: typing.Deque[IslandFlowNode] = deque()
        for flowSource in flowGraph.root_flow_nodes:
            q.append(flowSource)
        while q:
            flowNode: IslandFlowNode = q.popleft()

            allSourceX = [t.x for t in flowNode.island.tile_set]
            allSourceY = [t.y for t in flowNode.island.tile_set]
            sourceX = sum(allSourceX) / len(allSourceX)
            sourceY = sum(allSourceY) / len(allSourceY)

            for destinationEdge in flowNode.flow_to:
                allDestX = [t.x for t in destinationEdge.target_flow_node.island.tile_set]
                allDestY = [t.y for t in destinationEdge.target_flow_node.island.tile_set]
                destX = sum(allDestX) / len(allDestX)
                destY = sum(allDestY) / len(allDestY)

                viewInfo.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{destinationEdge.edge_army}', color=Colors.BLACK)
                q.append(destinationEdge.target_flow_node)
        for flowSource in flowGraph.enemy_backfill_nodes:
            q.append(flowSource)
        while q:
            flowNode: IslandFlowNode = q.popleft()

            allSourceX = [t.x for t in flowNode.island.tile_set]
            allSourceY = [t.y for t in flowNode.island.tile_set]
            sourceX = sum(allSourceX) / len(allSourceX)
            sourceY = sum(allSourceY) / len(allSourceY)

            for destinationEdge in flowNode.flow_to:
                allDestX = [t.x for t in destinationEdge.target_flow_node.island.tile_set]
                allDestY = [t.y for t in destinationEdge.target_flow_node.island.tile_set]
                destX = sum(allDestX) / len(allDestX)
                destY = sum(allDestY) / len(allDestY)

                viewInfo.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{destinationEdge.edge_army}', color=Colors.GRAY, alpha=155)
                q.append(destinationEdge.target_flow_node)

    def ensure_flow_graph_exists(self, islands: TileIslandBuilder):
        # has to be digraph because of input/output node pairs
        # positive island ids = 'in' nodes, negative island ids = corresponding 'out' node.
        graph: nx.DiGraph = nx.DiGraph()

        myTeam = self.team
        ourSet = {i.unique_id for i in islands.tile_islands_by_team_id[myTeam]}
        targetSet = {i.unique_id for i in islands.tile_islands_by_team_id[self.target_team]}
        if self.enemyGeneral is None or self.enemyGeneral.player == -1 or self.map.is_player_on_team(self.enemyGeneral.player, myTeam):
            raise Exception(f'Cannot call ensure_flow_graph_exists without setting enemyGeneral to some (enemy) tile.')

        # TODO use capacity to avoid chokepoints and such and route around enemy focal points

        targetGeneralIsland: TileIsland = islands.tile_island_lookup.raw[self.enemyGeneral.tile_index]

        neutSinks = set()

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
            elif self.include_neutral_flow and island.team == -1:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
                cost *= 2

            demands[island.unique_id] = demand

            graph.add_node(island.unique_id, **inAttrs)

            # edge from in_island to out_island with the node crossing cost
            graph.add_edge(island.unique_id, -island.unique_id, weight=cost, capacity=100000)

        for island in islands.all_tile_islands:
            # TODO can change this to some other criteria for forcing the neutral sinks further out, letting us branch more out into useful neutral areas
            areAllBordersNeut = True
            for movableIsland in island.border_islands:
                # edge from out_island to in_movableIsland
                graph.add_edge(-island.unique_id, movableIsland.unique_id, weight=1, capacity=100000)
                if movableIsland.team != -1:
                    areAllBordersNeut = False

            isIslandNeut = island.team == -1
            if self.include_neutral_flow and isIslandNeut and areAllBordersNeut:
                neutSinks.add(island.unique_id)

        demand = demands[targetGeneralIsland.unique_id] - cumulativeDemand
        graph.add_node(targetGeneralIsland.unique_id, demand=demand)

        if self.include_neutral_flow:
            for neutSinkId in neutSinks:
                graph.add_edge(-targetGeneralIsland.unique_id, neutSinkId, weight=0, capacity=100000)

        self.nxGraphData = NxFlowGraphData(graph, neutSinks, demands, cumulativeDemand)

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
            logbook.warn(f'toUse was {toUse}, expected 0. We will have extra army in the flow that isnt going to be known about by the algo')

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
            if len(used) == countToInclude:
                break

            for mv in tile.movable:
                if mv in incIsland.tile_set:
                    heapq.heappush(q, (1 - mv.army, mv))

        return used

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
            numTilesLeftToCapFromTarget,
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
                    minTurnsUsed += n.island.tile_count - numTilesLeftToCapFromTarget
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count - numTilesLeftToCapFromTarget
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
        # for n in ArmyFlowExpander.iterate_flow_nodes(nextTargets.values()):
        #     existing = safetyChecker.get(n.island.unique_id, None)
        #     if existing is not None:
        #         if existing != n:
        #             mismatches.append(f'Corrupted nextTarget nodes; {n}  !=  {existing}')
        #     else:
        #         safetyChecker[n.island.unique_id] = n
        #
        # for n in ArmyFlowExpander.iterate_flow_nodes(nextFriendlies.values()):
        #     existing = safetyChecker.get(n.island.unique_id, None)
        #     if existing is not None:
        #         if existing != n:
        #             mismatches.append(f'Corrupted nextFriendlies nodes; {n}  !=  {existing}')
        #     else:
        #         safetyChecker[n.island.unique_id] = n
        #
        # existing = safetyChecker.get(targetCalculatedNode.island.unique_id, None)
        # if existing is not None:
        #     if existing != targetCalculatedNode:
        #         mismatches.append(f'Corrupted targetCalculatedNode node; {targetCalculatedNode}  !=  {existing}')
        # else:
        #     safetyChecker[targetCalculatedNode.island.unique_id] = targetCalculatedNode
        #
        # existing = safetyChecker.get(friendlyUncalculatedNode.island.unique_id, None)
        # if existing is not None:
        #     if existing != friendlyUncalculatedNode:
        #         mismatches.append(f'Corrupted friendlyUncalculatedNode node; {friendlyUncalculatedNode}  !=  {existing}')
        # else:
        #     safetyChecker[friendlyUncalculatedNode.island.unique_id] = friendlyUncalculatedNode

        if mismatches:
            msg = "Search is corrupted;\r\n" + "\r\n".join(mismatches)
            logbook.error(msg)
            raise Exception(msg)