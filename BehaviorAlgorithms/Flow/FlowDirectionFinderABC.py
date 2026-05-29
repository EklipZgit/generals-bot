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
    def ensure_graph_data_available(self, islands: 'TileIslandBuilder', allow_neutral_flow: bool = False):
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
            startTiles.extend(t for t in map.players[p].tiles if t.army > 1 or t in intergeneral_analysis.shortestPathWay.tiles)

        neutFlowDepthDistance = 2

        def _foreach(t: 'Tile', dist: int) -> bool:
            island = islands.tile_island_lookup.raw[t.tile_index]
            if island is None:
                return True
            if island.team == team:
                return False
            if island.team == -1 and t not in intergeneral_analysis.shortestPathWay.tiles:
                existingCap = capacityLookup.get(island.unique_id, 0)
                cap = neutFlowDepthDistance - dist + 1
                if cap > existingCap:
                    capacityLookup[island.unique_id] = cap
                    capacityLookup[island.unique_id] = 100000
            return False

        SearchUtils.breadth_first_foreach_dist_fast_no_neut_cities(map, startTiles, maxDepth=neutFlowDepthDistance, foreachFunc=_foreach)

        neutGenDepth = 8
        def _foreach2(t: 'Tile', dist: int) -> bool:
            island = islands.tile_island_lookup.raw[t.tile_index]
            if island is None:
                return True
            if island.team == -1:
                existingCap = capacityLookup.get(island.unique_id, 0)
                cap = neutGenDepth - dist + 1
                if cap > existingCap:
                    capacityLookup[island.unique_id] = cap
                    capacityLookup[island.unique_id] = 100000
            return False

        SearchUtils.breadth_first_foreach_dist_fast_no_neut_cities(map, [map.players[map.player_index].general], maxDepth=neutGenDepth, foreachFunc=_foreach2)

        result: typing.Dict[int, TileIslandFlowRole] = {}
        for island in islands.all_tile_islands:
            borders_fr = False
            borders_en = False
            for nb in island.border_islands:
                if nb.team == team:
                    borders_fr = True
                    break
            for nb in island.border_islands:
                if nb.team == target_team:
                    borders_en = True
                    break
            are_all_borders_neut = not borders_fr and not borders_en
            is_neut = island.team == -1

            # with_neut sink: outskirt neutral islands not near friendly tiles
            sink_with_neut = is_neut and are_all_borders_neut and island.unique_id not in capacityLookup

            # no_neut sink: neutral islands not on the direct pathway corridor
            sink_no_neut = sink_with_neut
            # if is_neut and not (borders_fr and borders_en):
            #     pw = intergeneral_analysis.pathWayLookupMatrix.raw[island.tiles_by_army[0].tile_index]
            #     sink_no_neut = True
            #     if pw is not None:
            #         dist = pw.distance
            #         if (
            #             dist <= pathwayCutoff
            #             and intergeneral_analysis.bMap.raw[island.tiles_by_army[0].tile_index] <= neutEnDistCutoff
            #         ):
            #             sink_no_neut = False

            cap = capacityLookup.get(island.unique_id, 10000)

            result[island.unique_id] = TileIslandFlowRole(
                island=island,
                is_neutral_sink_with_neut=sink_with_neut,
                is_neutral_sink_no_neut=sink_no_neut,
                borders_friendly=borders_fr,
                borders_enemy=borders_en,
                are_all_borders_neutral=are_all_borders_neut,
                capacity=cap,
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
    ) -> typing.Tuple[typing.List[IslandFlowEdge], typing.List[IslandFlowNode], typing.List[IslandFlowNode]]:
        backfill_neut_edges: typing.List[IslandFlowEdge] = []
        our_set = {i.unique_id for i in our_islands}
        target_set = {i.unique_id for i in target_islands}
        root_output_flow_dict: dict[int, int] = {}
        root_usable_flow_dict: dict[int, int] = {}
        root_fake_or_dropped_flow_dict: dict[int, int] = {}
        enemy_incoming_flow_dict: dict[int, int] = {}

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

                flow_diag_islands = getattr(graph_data, 'flow_diag_island_ids', set())
                if log_debug and (
                    abs(node_id) in flow_diag_islands
                    or abs(target_node_id) in flow_diag_islands
                    or abs(node_id) in graph_data.fake_nodes
                    or abs(target_node_id) in graph_data.fake_nodes
                ):
                    source_desc = 'None' if source_node is None else f'{source_node.island.unique_id}:team{source_node.island.team}:army{source_node.island.sum_army}:tiles{source_node.island.tile_count}'
                    logbook.warning(
                        f'FLOW_DIAG_BUILD_NODE_EDGE raw_node={node_id} is_throughput={is_throughput} '
                        f'target={target_node_id} amount={target_flow_amount} source={source_desc}'
                    )

                if is_throughput and source_node:
                    if target_node_id != -node_id:
                        raise Exception(f'input node flowed to something other than output node...?  {source_node} ({target_flow_amount}a) -> {target_node_id}')
                    if log_debug and source_node.island is target_general_island:
                        logbook.info(
                            f'Flow THROUGH EN GEN of {target_flow_amount} ?? sourceNode.army_flow_received was {source_node.army_flow_received} (now {source_node.army_flow_received + target_flow_amount})')
                    source_node.army_flow_received += target_flow_amount
                    continue

                if source_node is not None and source_node.island.unique_id in our_set:
                    root_output_flow_dict[source_node.island.unique_id] = root_output_flow_dict.get(source_node.island.unique_id, 0) + target_flow_amount

                if node_id not in graph_data.fake_nodes:
                    our_set.discard(target_node_id)
                    target_set.discard(target_node_id)
                target_node = graph_lookup.get(target_node_id, None)
                if target_node is None:
                    if source_node is not None and source_node.island.unique_id in root_output_flow_dict:
                        root_fake_or_dropped_flow_dict[source_node.island.unique_id] = root_fake_or_dropped_flow_dict.get(source_node.island.unique_id, 0) + target_flow_amount
                    if log_debug and source_node is not None and source_node.island is target_general_island:
                        logbook.info(
                            f'Flow from EN GEN of {target_flow_amount} to fake node {target_node_id} -- we overflow the enemy land? sourceNode.army_flow_received was {source_node.army_flow_received}')
                    elif log_debug:
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
                        if log_debug:
                            logbook.info(
                                f'NEUT SINK EN GEN FLOW of {target_flow_amount} to fake node {target_node_id} -- we overflow the enemy land? sourceNode.army_flow_received was {source_node.army_flow_received} (now {source_node.army_flow_received - target_flow_amount})')
                        source_node.army_flow_received -= target_flow_amount
                        continue

                if source_node is None:
                    if target_node.island is target_general_island:
                        if log_debug:
                            logbook.info(f'Flow TO EN GEN from fake node {node_id} of {target_flow_amount} -- we DONT overflow enemy land, targetNode.army_flow_received (en gen backpressure) was {target_node.army_flow_received} (now {target_node.army_flow_received - target_flow_amount})')
                        target_node.army_flow_received -= target_flow_amount
                    elif log_debug:
                        logbook.info(f'Flow from fake node {node_id} of {target_flow_amount} to {target_node}')
                    continue

                source_node.set_flow_to(target_node, target_flow_amount)
                if source_node.island.unique_id in root_output_flow_dict:
                    root_usable_flow_dict[source_node.island.unique_id] = root_usable_flow_dict.get(source_node.island.unique_id, 0) + target_flow_amount
                if target_node.island.unique_id in target_set:
                    enemy_incoming_flow_dict[target_node.island.unique_id] = enemy_incoming_flow_dict.get(target_node.island.unique_id, 0) + target_flow_amount
                if log_debug and (
                    source_node.island.unique_id in flow_diag_islands
                    or target_node.island.unique_id in flow_diag_islands
                ):
                    logbook.warning(
                        f'FLOW_DIAG_FLOW_NODE_EDGE {source_node.island.unique_id}(team={source_node.island.team},army={source_node.island.sum_army}) '
                        f'-> {target_node.island.unique_id}(team={target_node.island.team},army={target_node.island.sum_army}) '
                        f'amount={target_flow_amount} source_received={source_node.army_flow_received} target_received={target_node.army_flow_received}'
                    )
                if log_debug:
                    logbook.info(f'FOUND FLOW EDGE {source_node} ({target_flow_amount}a) -> {target_node}')
                    # DIAGNOSTIC: Trace island 190 flow specifically
                    if source_node.island and source_node.island.unique_id == 190:
                        logbook.info(f'DIAG_190_FLOW: SOURCE {source_node} sending {target_flow_amount} to {target_node}')
                    if target_node.island and target_node.island.unique_id == 190:
                        logbook.info(f'DIAG_190_FLOW: TARGET {target_node} receiving {target_flow_amount} from {source_node}')

        final_root_flow_nodes = [graph_lookup[id] for id in our_set]
        enemy_backfill_flow_nodes = [graph_lookup[id] for id in target_set]
        if log_debug:
            root_nodes_with_edges = [
                (
                    node.island.unique_id,
                    len(node.flow_to),
                    sum(edge.edge_army for edge in node.flow_to),
                    node.island.sum_army,
                    node.desired_army,
                )
                for node in final_root_flow_nodes
                if len(node.flow_to) > 0
            ]
            root_nodes_without_edges = [
                (
                    node.island.unique_id,
                    node.island.sum_army,
                    node.desired_army,
                    root_output_flow_dict.get(node.island.unique_id, 0),
                    root_usable_flow_dict.get(node.island.unique_id, 0),
                    root_fake_or_dropped_flow_dict.get(node.island.unique_id, 0),
                )
                for node in final_root_flow_nodes
                if len(node.flow_to) == 0
            ]
            logbook.warning(
                f'FLOW_DIAG_BUILD_LOOKUP_SUMMARY roots={len(final_root_flow_nodes)} rootNodesWithEdges={root_nodes_with_edges[:32]} '
                f'rootNodesWithoutEdges={root_nodes_without_edges[:32]} enemyIncomingFlow={sorted(enemy_incoming_flow_dict.items())[:32]} '
                f'backfillNeutEdges={[(e.source_flow_node.island.unique_id if e.source_flow_node is not None else None, e.target_flow_node.island.unique_id, e.edge_army) for e in backfill_neut_edges[:32]]}'
            )
            if len(final_root_flow_nodes) > 0 and not root_nodes_with_edges:
                logbook.warning(
                    f'FLOW_DIAG_BAD_BUILD_LOOKUP roots={len(final_root_flow_nodes)} '
                    f'rootOutputFlowDict={sorted(root_output_flow_dict.items())[:64]} '
                    f'rootUsableFlowDict={sorted(root_usable_flow_dict.items())[:64]} '
                    f'rootFakeOrDroppedFlowDict={sorted(root_fake_or_dropped_flow_dict.items())[:64]}'
                )
        return backfill_neut_edges, enemy_backfill_flow_nodes, final_root_flow_nodes
