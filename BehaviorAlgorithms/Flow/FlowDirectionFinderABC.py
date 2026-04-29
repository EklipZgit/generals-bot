from __future__ import annotations

import typing
from abc import ABC, abstractmethod

import logbook

import SearchUtils
from BehaviorAlgorithms.Flow.FlowGraphModels import IslandFlowEdge, IslandFlowNode, IslandMaxFlowGraph
from BehaviorAlgorithms.Flow.TileIslandFlowRole import TileIslandFlowRole

if typing.TYPE_CHECKING:
    from Algorithms import TileIslandBuilder, TileIsland
    from ArmyAnalyzer import ArmyAnalyzer
    from base.client.map import Tile, MapBase
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

    def classify_islands_for_flow(
            self,
            islands: 'TileIslandBuilder',
            intergeneral_analysis: 'ArmyAnalyzer',
            map: 'MapBase',
            team: int,
            target_team: int,
    ) -> typing.Dict[int, TileIslandFlowRole]:
        """
        Classify every island's role in the flow graph — which are neutral sinks, border flags,
        etc. — using intergeneral distance data.  Returns a dict keyed by island.unique_id.

        This is a concrete shared implementation so that NetworkX and PyMaxflow builders produce
        identical classifications from the same island topology.
        """
        enDist = intergeneral_analysis.shortestPathWay.distance
        neutEnDistCutoff = int(enDist * 1.0)
        pathwayCutoff = int(1.25 * enDist) + 1

        # BFS from all friendly tiles (depth 3) to find neutral islands adjacent to us;
        # their proximity is used to exclude them from being neutral sinks in certain modes.
        capacityLookup: typing.Dict[int, int] = {}
        startTiles = []
        usPlayers = map.get_team_stats_by_team_id(team).livingPlayers
        for p in usPlayers:
            startTiles.extend(map.players[p].tiles)

        def _foreach(t: 'Tile', dist: int) -> bool:
            island = islands.tile_island_lookup.raw[t.tile_index]
            if island is None:
                return True
            if island.team == team:
                return False
            if island.team == -1:
                if island.unique_id not in capacityLookup:
                    capacityLookup[island.unique_id] = 5 - dist
            return False

        SearchUtils.breadth_first_foreach_dist(map, startTiles, maxDepth=3, foreachFunc=_foreach)

        result: typing.Dict[int, TileIslandFlowRole] = {}
        for island in islands.all_tile_islands:
            borders_fr = False
            borders_en = False
            for nb in island.border_islands:
                if nb.team == target_team:
                    borders_en = True
                if nb.team == team:
                    borders_fr = True
            are_all_borders_neut = not borders_fr and not borders_en
            is_neut = island.team == -1

            # with_neut sink: outskirt neutral islands not near friendly tiles
            sink_with_neut = are_all_borders_neut and island.unique_id not in capacityLookup

            # no_neut sink: neutral islands not on the direct pathway corridor
            sink_no_neut = False
            if is_neut and not (borders_fr and borders_en):
                pw = intergeneral_analysis.pathWayLookupMatrix.raw[island.tiles_by_army[0].tile_index]
                sink_no_neut = True
                if pw is not None:
                    dist = pw.distance
                    if (
                        dist <= pathwayCutoff
                        and intergeneral_analysis.bMap.raw[island.tiles_by_army[0].tile_index] <= neutEnDistCutoff
                    ):
                        sink_no_neut = False

            result[island.unique_id] = TileIslandFlowRole(
                island=island,
                is_neutral_sink_with_neut=sink_with_neut,
                is_neutral_sink_no_neut=sink_no_neut,
                borders_friendly=borders_fr,
                borders_enemy=borders_en,
                are_all_borders_neutral=are_all_borders_neut,
            )
        return result

    def build_flow_nodes_from_lookups(
            self,
            our_islands,
            target_general_island,
            target_islands,
            flow_dict,
            graph_lookup,
            graph_data,
            log_debug: bool = False,
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
                if log_debug:
                    logbook.info(f'FOUND FLOW EDGE {source_node} ({target_flow_amount}a) -> {target_node}')
                    # DIAGNOSTIC: Trace island 190 flow specifically
                    if source_node.island and source_node.island.unique_id == 190:
                        logbook.info(f'DIAG_190_FLOW: SOURCE {source_node} sending {target_flow_amount} to {target_node}')
                    if target_node.island and target_node.island.unique_id == 190:
                        logbook.info(f'DIAG_190_FLOW: TARGET {target_node} receiving {target_flow_amount} from {source_node}')

        final_root_flow_nodes = [graph_lookup[id] for id in our_set]
        enemy_backfill_flow_nodes = [graph_lookup[id] for id in target_set]
        return backfill_neut_edges, enemy_backfill_flow_nodes, final_root_flow_nodes
