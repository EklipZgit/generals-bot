from __future__ import annotations

import typing
from abc import ABC, abstractmethod

import logbook



from BehaviorAlgorithms.Flow.FlowGraphModels import IslandFlowEdge, IslandFlowNode, IslandMaxFlowGraph

if typing.TYPE_CHECKING:
    from Algorithms import TileIslandBuilder, TileIsland
    from base.client.map import Tile
    from Interfaces import TileSet


class FlowDirectionFinderABC(ABC):
    @abstractmethod
    def configure(self, team: int, target_team: int, enemy_general: 'Tile | None'):
        raise NotImplementedError()

    @abstractmethod
    def invalidate_cache(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def graph_data(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def graph_data_no_neut(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def enemy_general(self):
        raise NotImplementedError()

    @enemy_general.setter
    @abstractmethod
    def enemy_general(self, value):
        raise NotImplementedError()

    @abstractmethod
    def ensure_graph_data_available(self, islands: 'TileIslandBuilder'):
        raise NotImplementedError()

    @abstractmethod
    def build_graph_data(self, islands: 'TileIslandBuilder', use_neutral_flow: bool):
        raise NotImplementedError()

    @abstractmethod
    def compute_flow_dict(self, islands: 'TileIslandBuilder', graph_data, method, render_on_exception: bool = True):
        raise NotImplementedError()

    @abstractmethod
    def build_flow_graph(
            self,
            islands: 'TileIslandBuilder',
            our_islands: typing.List['TileIsland'],
            target_islands: typing.List['TileIsland'],
            searching_player: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: 'TileSet | None' = None,
            includeNeutralDemand: bool = False,
            method=None,
    ) -> 'IslandMaxFlowGraph':
        raise NotImplementedError()

    def build_flow_nodes_from_lookups(
            self,
            our_islands,
            target_general_island,
            target_islands,
            flow_dict,
            graph_lookup,
            graph_data,
    ):
        backfill_neut_edges: typing.List[IslandFlowEdge] = []
        our_set = {i.unique_id for i in our_islands}
        target_set = {i.unique_id for i in target_islands}

        for node_id, targets in flow_dict.items():
            is_throughput = False
            if node_id > 0:
                is_throughput = True
            else:
                node_id = -node_id

            source_node = graph_lookup.get(node_id, None)

            for target_node_id, target_flow_amount in targets.items():
                if target_flow_amount == 0:
                    continue

                if is_throughput and source_node:
                    if target_node_id != -node_id:
                        raise Exception(f'input node flowed to something other than output node...?  {source_node} ({target_flow_amount}a) -> {target_node_id}')
                    if source_node.island is target_general_island:
                        logbook.info(
                            f'Flow THROUGH EN GEN of {target_flow_amount} ?? sourceNode.army_flow_received was {source_node.army_flow_received} (now {source_node.army_flow_received + target_flow_amount})')
                    source_node.army_flow_received += target_flow_amount
                    continue

                if node_id not in graph_data.fake_nodes:
                    our_set.discard(target_node_id)
                    target_set.discard(target_node_id)
                target_node = graph_lookup.get(target_node_id, None)
                if target_node is None:
                    if source_node.island is target_general_island:
                        logbook.info(
                            f'Flow from EN GEN of {target_flow_amount} to fake node {target_node_id} -- we overflow the enemy land? sourceNode.army_flow_received was {source_node.army_flow_received}')
                    else:
                        logbook.info(f'Flow of {target_flow_amount} to fake node {target_node_id} from {source_node}')
                    continue

                if target_node_id in graph_data.neutral_sinks:
                    if source_node is None:
                        edge = IslandFlowEdge(None, target_node, target_flow_amount)
                        backfill_neut_edges.append(edge)
                        continue

                    if source_node.island is target_general_island:
                        edge = IslandFlowEdge(source_node, target_node, target_flow_amount)
                        backfill_neut_edges.append(edge)
                        logbook.info(
                            f'NEUT SINK EN GEN FLOW of {target_flow_amount} to fake node {target_node_id} -- we overflow the enemy land? sourceNode.army_flow_received was {source_node.army_flow_received} (now {source_node.army_flow_received - target_flow_amount})')
                        source_node.army_flow_received -= target_flow_amount
                        continue

                if source_node is None:
                    if target_node.island is target_general_island:
                        logbook.info(f'Flow TO EN GEN from fake node {node_id} of {target_flow_amount} -- we DONT overflow enemy land, targetNode.army_flow_received (en gen backpressure) was {target_node.army_flow_received} (now {target_node.army_flow_received - target_flow_amount})')
                        target_node.army_flow_received -= target_flow_amount
                    else:
                        logbook.info(f'Flow from fake node {node_id} of {target_flow_amount} to {target_node}')
                    continue

                source_node.set_flow_to(target_node, target_flow_amount)
                logbook.info(f'FOUND FLOW EDGE {source_node} ({target_flow_amount}a) -> {target_node}')

        final_root_flow_nodes = [graph_lookup[id] for id in our_set]
        enemy_backfill_flow_nodes = [graph_lookup[id] for id in target_set]
        return backfill_neut_edges, enemy_backfill_flow_nodes, final_root_flow_nodes
