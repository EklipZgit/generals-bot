from __future__ import annotations

import typing
from enum import Enum

import SearchUtils
from Interfaces import MapMatrixInterface

if typing.TYPE_CHECKING:
    from Algorithms import TileIsland


class FlowGraphMethod(Enum):
    NetworkSimplex = 1,
    CapacityScaling = 2,
    MinCostFlow = 3

    # PyMaxflow max-flow methods (experimental)
    PyMaxflowBoykovKolmogorov = 10  # Standard BK maxflow - fast but not min-cost
    PyMaxflowWithNodeSplitting = 11  # Experimental: node splitting to approximate min-cost


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

    def __lt__(self, other: IslandFlowNode) -> bool:
        return self.island.unique_id < other.island.unique_id

    def __cmp__(self, other: IslandFlowNode) -> int:
        return self.island.unique_id - other.island.unique_id

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
