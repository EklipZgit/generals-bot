from __future__ import annotations

import random
import time
import typing

import logbook
import networkx as nx

from ArmyAnalyzer import ArmyAnalyzer
from MapMatrix import MapMatrix
from Gather import GatherDebug
from BehaviorAlgorithms.Flow.FlowDirectionFinderABC import FlowDirectionFinderABC
from BehaviorAlgorithms.Flow.FlowGraphModels import FlowGraphMethod, IslandFlowEdge, IslandFlowNode, IslandMaxFlowGraph
from BehaviorAlgorithms.Flow.NxFlowGraphData import NxFlowGraphData

if typing.TYPE_CHECKING:
    from Algorithms import TileIslandBuilder, TileIsland
    from Interfaces import TileSet
    from base.client.map import Tile
    from base.client.map import MapBase
    from PerformanceTimer import PerformanceTimer


class NetworkXFlowDirectionFinder(FlowDirectionFinderABC):
    def __init__(
            self,
            map: 'MapBase',
            intergeneral_analysis: 'ArmyAnalyzer',
            friendly_general: 'Tile',
            use_backpressure_from_enemy_general: bool,
            perf_timer: 'PerformanceTimer',
            log_debug: bool,
            invalid_flow_renderer,
    ):
        self.map: 'MapBase' = map
        self.perf_timer = perf_timer
        self.log_debug = log_debug
        self.intergeneral_analysis: 'ArmyAnalyzer' = intergeneral_analysis
        self.use_backpressure_from_enemy_general = use_backpressure_from_enemy_general
        self.friendly_general: 'Tile' = friendly_general
        self.invalid_flow_renderer = invalid_flow_renderer

        self.team: int = map.friendly_team
        self.target_team: int = [t for t in map.get_teams_array(map) if t != self.team][0]
        self._enemy_general: 'Tile | None' = None
        self.nx_graph_data: 'NxFlowGraphData | None' = None
        self.nx_graph_data_no_neut: 'NxFlowGraphData | None' = None
        self._last_built_graphs_turn: int = -1

    def configure(self, team: int, target_team: int, enemy_general: 'Tile | None'):
        self.team = team
        self.target_team = target_team
        self.enemy_general = enemy_general

    def invalidate_cache(self):
        self.nx_graph_data = None
        self.nx_graph_data_no_neut = None

    @property
    def graph_data(self) -> 'NxFlowGraphData | None':
        return self.nx_graph_data

    @property
    def graph_data_no_neut(self) -> 'NxFlowGraphData | None':
        return self.nx_graph_data_no_neut

    @property
    def enemy_general(self) -> 'Tile | None':
        return self._enemy_general

    @enemy_general.setter
    def enemy_general(self, value: 'Tile | None'):
        self._enemy_general = value

    @property
    def nxGraphData(self) -> 'NxFlowGraphData | None':
        return self.graph_data

    @property
    def nxGraphDataNoNeut(self) -> 'NxFlowGraphData | None':
        return self.graph_data_no_neut

    def ensure_flow_graph_exists(self, islands: 'TileIslandBuilder'):
        self.ensure_graph_data_available(islands)

    def _build_island_flow_precursor_nx_data(self, islands: 'TileIslandBuilder', useNeutralFlow: bool) -> 'NxFlowGraphData':
        return self.build_graph_data(islands, useNeutralFlow)

    def get_island_max_flow_dict(
            self,
            islands: 'TileIslandBuilder',
            graphData: 'NxFlowGraphData',
            method: 'FlowGraphMethod',
            render_on_exception: bool = True
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        return self.compute_flow_dict(islands, graphData, method, render_on_exception)

    def build_max_flow_min_cost_flow_nodes(
            self,
            islands: 'TileIslandBuilder',
            ourIslands: typing.List['TileIsland'],
            targetIslands: typing.List['TileIsland'],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: 'TileSet | None' = None,
            includeNeutralDemand: bool = False,
            method: 'FlowGraphMethod' = None
    ) -> 'IslandMaxFlowGraph':
        return self.build_flow_graph(islands, ourIslands, targetIslands, searchingPlayer, turns, blockGatherFromEnemyBorders, negativeTiles, includeNeutralDemand, method)

    def ensure_graph_data_available(self, islands: 'TileIslandBuilder'):
        if self.nx_graph_data is None or self.nx_graph_data_no_neut is None or self._last_built_graphs_turn < self.map.turn:
            self.nx_graph_data = self.build_graph_data(islands, use_neutral_flow=True)
            self.nx_graph_data_no_neut = self.build_graph_data(islands, use_neutral_flow=False)
            self._last_built_graphs_turn = self.map.turn

    def build_graph_data(self, islands: 'TileIslandBuilder', use_neutral_flow: bool) -> 'NxFlowGraphData':
        enDist = self.intergeneral_analysis.shortestPathWay.distance
        neutEnDistCutoff = int(enDist * 1.0)
        pathwayCutoff = int(1.25 * enDist) + 1
        graph: nx.DiGraph = nx.DiGraph()
        myTeam = self.team
        ourSet = {i.unique_id for i in islands.tile_islands_by_team_id[myTeam]}
        targetSet = {i.unique_id for i in islands.tile_islands_by_team_id[self.target_team]}
        logbook.info(f'build_graph_data entry: enemy_general={self.enemy_general!r} (player={getattr(self.enemy_general, "player", None)}) myTeam={myTeam} target_team={self.target_team} use_neutral_flow={use_neutral_flow}')
        if self.enemy_general is None or (self.enemy_general.player >= 0 and self.map.is_player_on_team(self.enemy_general.player, myTeam)):
            logbook.info(f'build_graph_data: enemy_general fallback triggered (was {self.enemy_general!r})')
            try:
                self.enemy_general = next(t for t in self.map.pathable_tiles if not t.discovered and self.map.is_tile_on_team(t, self.target_team))
            except:
                try:
                    self.enemy_general = next(t for t in self.map.pathable_tiles if not t.discovered)
                except:
                    try:
                        self.enemy_general = next(t for t in self.map.pathable_tiles if not t.visible)
                    except:
                        try:
                            self.enemy_general = next(t for t in self.map.pathable_tiles if self.map.is_tile_on_team(t, self.target_team))
                        except:
                            self.enemy_general = next(t for t in self.map.pathable_tiles if not self.map.is_tile_on_team(t, self.team))
        logbook.info(f'build_graph_data: after fallback enemy_general={self.enemy_general!r}')

        if self.enemy_general is None or self.map.is_player_on_team(self.enemy_general.player, myTeam):
            raise Exception(f'Cannot call ensure_flow_graph_exists without setting enemyGeneral to some (enemy) tile.')
        targetGeneralIsland = islands.tile_island_lookup.raw[self.enemy_general.tile_index]
        frGeneralIsland = islands.tile_island_lookup.raw[self.friendly_general.tile_index]

        cumulativeDemand, demands, friendlyArmySupply, enemyArmyDemand, enemyGeneralDemand = self._determine_initial_demands_and_split_input_output_nodes(graph, islands, ourSet, targetSet, use_neutral_flow)

        island_roles = self.classify_islands_for_flow(islands, self.intergeneral_analysis, self.map, self.team, self.target_team)

        neutSinks = set()
        for island in islands.all_tile_islands:
            sourceCapacity = 100000
            role = island_roles[island.unique_id]

            weight = 1

            for movableIsland in island.border_islands:
                destCapacity = 100000
                if self.log_debug:
                    logbook.info(f'For edge from {island} to {movableIsland} capacities were src {sourceCapacity}, dest {destCapacity}')
                edgeCapacity = max(sourceCapacity, destCapacity)
                # it costs 1 weight to move between islands. From the output port of this one to the input of the other.
                graph.add_edge(-island.unique_id, movableIsland.unique_id, weight=weight, capacity=edgeCapacity)
            # neutEnDistCutoff
            # pathwayCutoff
            if use_neutral_flow:
                sinkEnemyGeneral = role.is_neutral_sink_with_neut
            else:
                sinkEnemyGeneral = role.is_neutral_sink_no_neut
            if sinkEnemyGeneral:
                neutSinks.add(island.unique_id)

        fakeNode = random.randint(1000000, 9000000)
        while fakeNode in islands.tile_islands_by_unique_id:
            fakeNode = random.randint(1000000, 9000000)

        graph.add_node(fakeNode, demand=-cumulativeDemand)

        # TODO document what this does
        weight = 10
        if not use_neutral_flow:
            weight = 0

        for neutSinkId in neutSinks:
            isl = islands.tile_islands_by_unique_id[neutSinkId]
            capacity = isl.tile_count
            graph.add_edge(fakeNode, neutSinkId, weight=weight, capacity=capacity)

        # TODO document what this does
        backpressureWeight = 0
        if not self.use_backpressure_from_enemy_general:
            backpressureWeight = 10000

        graph.add_edge(-targetGeneralIsland.unique_id, fakeNode, weight=backpressureWeight, capacity=1000000)
        graph.add_edge(-frGeneralIsland.unique_id, fakeNode, weight=1000, capacity=1000000)
        graph.add_edge(fakeNode, targetGeneralIsland.unique_id, weight=backpressureWeight, capacity=1000000)
        graph.add_edge(fakeNode, frGeneralIsland.unique_id, weight=1000, capacity=1000000)
        fakeNodes = {fakeNode}

        if self.log_debug:
            special_node_ids = {
                frGeneralIsland.unique_id,
                -frGeneralIsland.unique_id,
                targetGeneralIsland.unique_id,
                -targetGeneralIsland.unique_id,
                fakeNode,
            }
            special_edges = []
            for from_id, to_id, data_bag in graph.edges(data=True):
                if from_id in special_node_ids or to_id in special_node_ids:
                    special_edges.append((from_id, to_id, data_bag.get('weight'), data_bag.get('capacity')))
            special_edges.sort()
            logbook.info(
                f'flow precursor special nodes: '
                f'friendly_general_in={frGeneralIsland.unique_id}, '
                f'friendly_general_out={-frGeneralIsland.unique_id}, '
                f'enemy_general_in={targetGeneralIsland.unique_id}, '
                f'enemy_general_out={-targetGeneralIsland.unique_id}, '
                f'fake_node={fakeNode}, '
                f'useNeutralFlow={use_neutral_flow}'
            )
            logbook.info(f'flow precursor special edges={special_edges}')

            neutSinkTotalCap = sum(islands.tile_islands_by_unique_id[uid].tile_count for uid in neutSinks if uid in islands.tile_islands_by_unique_id)
            fakeNodeSupply = -cumulativeDemand
            logbook.error(
                f'build_graph_data neutSinks: count={len(neutSinks)}, totalCap={neutSinkTotalCap}, '
                f'fakeNodeSupply={fakeNodeSupply}, '
                f'cumulativeDemand={cumulativeDemand}, use_neutral_flow={use_neutral_flow}'
            )
            if use_neutral_flow and neutSinkTotalCap > fakeNodeSupply:
                logbook.error(
                    f'build_graph_data IMBALANCE: neutSinkTotalCap {neutSinkTotalCap} '
                    f'exceeds fakeNodeSupply {fakeNodeSupply} — graph likely infeasible'
                )

            isolatedDemandIslands = [
                isl for isl in islands.all_tile_islands
                if len(isl.border_islands) == 0 and demands.get(isl.unique_id, 0) != 0
            ]
            if isolatedDemandIslands:
                logbook.error(
                    f'build_graph_data ISOLATED islands with non-zero demand (use_neutral_flow={use_neutral_flow}): '
                    + ' | '.join(f'{isl}(team={isl.team},dem={demands.get(isl.unique_id)})' for isl in isolatedDemandIslands)
                )

            topDemandIslands = sorted(
                [(demands[isl.unique_id], isl) for isl in islands.all_tile_islands if isl.unique_id in demands],
                key=lambda x: abs(x[0]), reverse=True
            )[:10]
            logbook.info(
                f'build_graph_data top 10 demand contributors (use_neutral_flow={use_neutral_flow}): '
                + ' | '.join(f'{isl}(team={isl.team},dem={dem})' for dem, isl in topDemandIslands)
            )
            logbook.info(
                f'build_graph_data: fakeNode demand={-cumulativeDemand}, '
                f'targetGeneralIsland={targetGeneralIsland}(borders={len(targetGeneralIsland.border_islands) if targetGeneralIsland else "N/A"}), '
                f'frGeneralIsland={frGeneralIsland}'
            )
            if targetGeneralIsland:
                logbook.info(
                    f'build_graph_data targetGeneralIsland border_islands: '
                    + ' | '.join(f'{b}(team={b.team})' for b in targetGeneralIsland.border_islands)
                )

            weakComponents = list(nx.weakly_connected_components(graph))
            if len(weakComponents) > 1:
                logbook.error(
                    f'build_graph_data DISCONNECTED GRAPH: {len(weakComponents)} weakly connected components, '
                    f'use_neutral_flow={use_neutral_flow}, cumulativeDemand={cumulativeDemand}'
                )
                for i, comp in enumerate(weakComponents):
                    islandIds = [n for n in comp if n > 0]
                    islandDescs = []
                    for uid in islandIds[:8]:
                        isl = islands.tile_islands_by_unique_id.get(uid)
                        if isl:
                            islandDescs.append(f'{isl}(team={isl.team})')
                    logbook.error(f'  component {i}: nodes={len(comp)}, islands={islandDescs}{"..." if len(islandIds) > 8 else ""}')
            else:
                logbook.info(
                    f'build_graph_data graph OK: fully connected, use_neutral_flow={use_neutral_flow}, '
                    f'cumulativeDemand={cumulativeDemand}'
                )

        nxData = NxFlowGraphData(graph, neutSinks, demands, cumulativeDemand, fakeNodes)
        nxData.friendly_army_supply = friendlyArmySupply
        nxData.enemy_army_demand = enemyArmyDemand
        nxData.enemy_general_demand = enemyGeneralDemand
        return nxData

    def _determine_initial_demands_and_split_input_output_nodes(self, graph, islands, ourSet, targetSet, includeNeutralFlow: bool):
        demands = {}
        cumulativeDemand = 0
        friendlyArmySupply = 0
        enemyArmyDemand = 0
        enemyGeneralDemand = 0
        targetGeneralIsland = islands.tile_island_lookup.raw[self.enemy_general.tile_index]
        for island in islands.all_tile_islands:
            cost = island.tile_count - 1
            inAttrs = {}
            demand = island.tile_count - island.sum_army
            if island.unique_id in ourSet:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
                friendlyArmySupply += island.sum_army - island.tile_count
            elif island.unique_id in targetSet:
                demand = island.sum_army + island.tile_count
                inAttrs['demand'] = demand
                cumulativeDemand += demand
                enemyArmyDemand += demand
                if island is targetGeneralIsland:
                    enemyGeneralDemand = demand
            elif includeNeutralFlow and island.team == -1:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
                cost *= 2

            demands[island.unique_id] = demand

            if self.log_debug:
                logbook.info(f'node {island.unique_id}: {repr(inAttrs)}')
            graph.add_node(island.unique_id, **inAttrs)

            if self.log_debug:
                logbook.info(f'  edge {island.unique_id} -> {-island.unique_id} cost {cost}')
            graph.add_edge(island.unique_id, -island.unique_id, weight=cost, capacity=100000)

        return cumulativeDemand, demands, friendlyArmySupply, enemyArmyDemand, enemyGeneralDemand

    def compute_flow_dict(
            self,
            islands: 'TileIslandBuilder',
            graphData: 'NxFlowGraphData',
            method: 'FlowGraphMethod',
            render_on_exception: bool = True
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        start = time.perf_counter()
        flowCost: int = -1
        flowDict: typing.Dict[int, typing.Dict[int, int]]

        try:
            if method == FlowGraphMethod.NetworkSimplex:
                flowCost, flowDict = nx.flow.network_simplex(graphData.graph)
            elif method == FlowGraphMethod.CapacityScaling:
                flowCost, flowDict = nx.flow.capacity_scaling(graphData.graph)
            elif method == FlowGraphMethod.MinCostFlow:
                flowDict = nx.flow.min_cost_flow(graphData.graph)
            else:
                raise NotImplementedError(str(method))
        except Exception as ex:
            nodeDemandsNonZero = {n: d for n, d in graphData.graph.nodes(data="demand") if d}
            demandSum = sum(nodeDemandsNonZero.values())
            logbook.error(
                f'compute_flow_dict INFEASIBLE: method={method}, '
                f'cumulativeDemand={graphData.cumulative_demand}, '
                f'nodes={graphData.graph.number_of_nodes()}, '
                f'edges={graphData.graph.number_of_edges()}, '
                f'fakeNodes={graphData.fake_nodes}, '
                f'demandSum={demandSum} (should be 0)'
            )
            logbook.error(f'compute_flow_dict non-zero node demands: {nodeDemandsNonZero}')
            capViolations = [
                (u, v, d)
                for u, v, d in graphData.graph.edges(data=True)
                if d.get('capacity', 100000) < abs(nodeDemandsNonZero.get(u, 0))
                   or d.get('capacity', 100000) < abs(nodeDemandsNonZero.get(v, 0))
            ]
            if capViolations:
                logbook.error(f'compute_flow_dict capacity violations (demand > capacity): {capViolations}')
            if render_on_exception and GatherDebug.USE_DEBUG_ASSERTS and self.log_debug:
                self.invalid_flow_renderer(islands, graphData.graph, f'Invalid Graph input... Caught flow exception: {ex}')
            raise

        if self.log_debug:
            non_zero_flow_dict = {
                src: {dst: amount for dst, amount in targets.items() if amount != 0}
                for src, targets in flowDict.items()
                if any(amount != 0 for amount in targets.values())
            }
            logbook.info(f'{method} non-zero flowDict={non_zero_flow_dict}')

        logbook.info(f'{method} complete with flowCost {flowCost} in {time.perf_counter() - start:.5f}s')
        return flowDict

    def build_flow_graph(
            self,
            islands: 'TileIslandBuilder',
            ourIslands: typing.List['TileIsland'],
            targetIslands: typing.List['TileIsland'],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: 'TileSet | None' = None,
            includeNeutralDemand: bool = False,
            method: 'FlowGraphMethod' = None
    ) -> 'IslandMaxFlowGraph':
        if method is None:
            method = FlowGraphMethod.NetworkSimplex

        withNeutFlowDict = self.compute_flow_dict(islands, self.nx_graph_data, method)
        noNeutFlowDict = self.compute_flow_dict(islands, self.nx_graph_data_no_neut, method)

        if self.log_debug:
            logbook.info(f'withNeutFlowDict keys: {list(withNeutFlowDict.keys())}')
            for src, targets in withNeutFlowDict.items():
                non_zero = {k: v for k, v in targets.items() if v != 0}
                if non_zero:
                    logbook.info(f'  {src} -> {non_zero}')
            logbook.info(f'noNeutFlowDict keys: {list(noNeutFlowDict.keys())}')
            for src, targets in noNeutFlowDict.items():
                non_zero = {k: v for k, v in targets.items() if v != 0}
                if non_zero:
                    logbook.info(f'  {src} -> {non_zero}')

        start = time.perf_counter()
        targetGeneralIsland = islands.tile_island_lookup.raw[self.enemy_general.tile_index]

        withNeutGraphLookup: typing.Dict[int, IslandFlowNode] = {}
        noNeutGraphLookup: typing.Dict[int, IslandFlowNode] = {}

        for island in islands.all_tile_islands:
            demandNoNeut = self.nx_graph_data_no_neut.demand_lookup[island.unique_id]
            flowNodeNoNeut = IslandFlowNode(island, demandNoNeut)
            noNeutGraphLookup[island.unique_id] = flowNodeNoNeut

            demandWithNeut = self.nx_graph_data.demand_lookup[island.unique_id]
            flowNodeWithNeut = IslandFlowNode(island, demandWithNeut)
            withNeutGraphLookup[island.unique_id] = flowNodeWithNeut

        backfillNeutEdges, enemyBackfillFlowNodes, finalRootFlowNodes = self.build_flow_nodes_from_lookups(ourIslands, targetGeneralIsland, targetIslands, withNeutFlowDict, withNeutGraphLookup, self.nx_graph_data)
        backfillNeutNoNeutEdges, enemyBackfillNoNeutFlowNodes, finalRootNoNeutFlowNodes = self.build_flow_nodes_from_lookups(ourIslands, targetGeneralIsland, targetIslands, noNeutFlowDict, noNeutGraphLookup, self.nx_graph_data_no_neut)

        noNeutFlowNodeLookup = MapMatrix(self.map, None)
        incNeutFlowNodeLookup = MapMatrix(self.map, None)
        for flowNode in noNeutGraphLookup.values():
            for t in flowNode.island.tile_set:
                noNeutFlowNodeLookup.raw[t.tile_index] = flowNode
        for flowNode in withNeutGraphLookup.values():
            for t in flowNode.island.tile_set:
                incNeutFlowNodeLookup.raw[t.tile_index] = flowNode

        flowGraph = IslandMaxFlowGraph(finalRootNoNeutFlowNodes, finalRootFlowNodes, enemyBackfillNoNeutFlowNodes, enemyBackfillFlowNodes, backfillNeutEdges, backfillNeutNoNeutEdges, noNeutFlowNodeLookup, incNeutFlowNodeLookup, noNeutGraphLookup, withNeutGraphLookup)
        logbook.info(f'{method} FlowNodes complete in {time.perf_counter() - start:.5f}s')
        return flowGraph
