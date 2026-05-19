from __future__ import annotations

import random
import typing
from collections import defaultdict

import logbook
import numpy as np
from ortools.graph.python import min_cost_flow

from BehaviorAlgorithms.Flow.FlowDirectionFinderABC import FlowDirectionFinderABC
from BehaviorAlgorithms.Flow.FlowGraphModels import IslandFlowNode, IslandMaxFlowGraph, FlowGraphMethod
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.Flow.NxFlowGraphData import NxFlowGraphData
from MapMatrix import MapMatrix
from PerformanceTimer import PerformanceTimer

DEMAND_SATURATION_FROM_GENERAL_ONLY = False

if typing.TYPE_CHECKING:
    from Algorithms import TileIslandBuilder, TileIsland
    from ArmyAnalyzer import ArmyAnalyzer
    from base.client.map import MapBase, Tile
    from Interfaces import MapMatrixInterface, TileSet


class OrToolsGraphData(object):
    """
    Holds the converted OR-Tools SimpleMinCostFlow input arrays derived from NxFlowGraphData.
    All arrays are parallel (index i describes the i-th arc).
    Node supplies follow the OR-Tools convention: positive = supply (source), negative = demand (sink).
    """

    def __init__(
        self,
        start_nodes: np.ndarray,
        end_nodes: np.ndarray,
        capacities: np.ndarray,
        unit_costs: np.ndarray,
        node_ids: np.ndarray,
        node_supplies: np.ndarray,
        node_to_idx: typing.Dict[int, int],
        idx_to_node: typing.Dict[int, int],
        demand_lookup: typing.Dict[int, int],
        neutral_sinks: typing.Set[int],
        fake_nodes: typing.Set[int],
        cumulative_demand: int,
    ):
        self.start_nodes: np.ndarray = start_nodes
        self.end_nodes: np.ndarray = end_nodes
        self.capacities: np.ndarray = capacities
        self.unit_costs: np.ndarray = unit_costs
        self.node_ids: np.ndarray = node_ids
        """Parallel to node_supplies: node_ids[i] is the original NX node id for OR-Tools node i."""
        self.node_supplies: np.ndarray = node_supplies
        """OR-Tools supply per node: positive = source, negative = sink. Index matches node_ids."""
        self.node_to_idx: typing.Dict[int, int] = node_to_idx
        """Maps original NX node id → OR-Tools node index."""
        self.idx_to_node: typing.Dict[int, int] = idx_to_node
        """Maps OR-Tools node index → original NX node id."""
        self.demand_lookup: typing.Dict[int, int] = demand_lookup
        """NX demand per island unique_id (negative = supply, positive = demand). Preserved for flow extraction."""
        self.neutral_sinks: typing.Set[int] = neutral_sinks
        self.fake_nodes: typing.Set[int] = fake_nodes
        self.cumulative_demand: int = cumulative_demand


class DirectOrToolsGraphBuilder(object):
    """
    Builds OrToolsGraphData directly from island topology, mirroring exactly what
    NetworkXFlowDirectionFinder.build_graph_data + NxToOrToolsConverter produce, but
    without constructing a NetworkX DiGraph as an intermediate step.

    The graph structure mirrors the NX builder:
      - For every island: node island.unique_id (with demand/supply) + split edge
        island.unique_id → -island.unique_id (weight=tile_count-1, capacity=100000)
      - For every border pair: edge -island.unique_id → neighbour.unique_id
        (weight=1, capacity=100000)
      - fakeNode: balances cumulative demand; edges to/from generals and neutral sinks

    OR-Tools supply convention: positive = supply, negative = demand.
    NX demand convention:       negative = supply, positive = demand.
    Therefore: or_supply = -nx_demand.
    """

    def __init__(self):
        self.log_debug: bool = False

    def _format_island_tiles(self, island: 'TileIsland') -> str:
        return '|'.join(str(t) for t in island.tiles_by_army[:8])

    def _format_island_for_flow_diag(self, island: 'TileIsland', demand: int | None = None, supply: int | None = None) -> str:
        demand_text = '' if demand is None else f' demand={demand}'
        supply_text = '' if supply is None else f' ort_supply={supply}'
        border_text = '|'.join(
            f'{b.unique_id}:team{b.team}:{b.tile_count}t:{b.sum_army}a:{self._format_island_tiles(b)}'
            for b in island.border_islands
        )
        return (
            f'id={island.unique_id} team={island.team} tiles={island.tile_count} army={island.sum_army}'
            f'{demand_text}{supply_text} topTiles={self._format_island_tiles(island)} borders=[{border_text}]'
        )

    def build(
        self,
        islands: 'TileIslandBuilder',
        intergeneral_analysis,
        map_obj: 'MapBase',
        team: int,
        target_team: int,
        friendly_general: 'Tile',
        enemy_general: 'Tile',
        use_backpressure_from_enemy_general: bool,
        use_neutral_flow: bool,
        army_override_matrix: 'MapMatrixInterface[int] | None',
        negativeTiles: 'TileSet | None',
        perf_timer: 'PerformanceTimer',
    ) -> OrToolsGraphData:
        """
        Build OrToolsGraphData equivalent to what NxFlowDirectionFinder.build_graph_data
        followed by NxToOrToolsConverter.convert would produce.
        """

        target_general_island = islands.tile_island_lookup.raw[enemy_general.tile_index]
        fr_general_island = islands.tile_island_lookup.raw[friendly_general.tile_index]

        def _get_island_army_sum(island: 'TileIsland') -> int:
            if army_override_matrix is None:
                army_sum = island.sum_army
            else:
                army_sum = sum(army_override_matrix.raw[tile.tile_index] for tile in island.tile_set)
            if island.team == team and negativeTiles is not None:
                if army_override_matrix is None:
                    army_sum -= sum(tile.army for tile in island.tile_set if tile in negativeTiles)
                else:
                    army_sum -= sum(army_override_matrix.raw[tile.tile_index] for tile in island.tile_set if tile in negativeTiles)
            return army_sum

        # ----------------------------------------------------------------
        # Phase 1: per-island demands (mirrors _determine_initial_demands...)
        # ----------------------------------------------------------------
        demands: typing.Dict[int, int] = {}
        cumulative_demand: int = 0
        friendly_army_supply: int = 0
        enemy_army_demand: int = 0
        enemy_general_demand: int = target_general_island.sum_army + target_general_island.tile_count

        with perf_timer.begin_move_event('OrTools build classify_islands'):
            island_roles = FlowDirectionFinderABC.classify_islands_for_flow(
                self,  # type: ignore[arg-type]
                islands,
                intergeneral_analysis,
                map_obj,
                team,
                target_team,
            )

        # node supply dict: node_id → or_supply (positive = source)
        node_supply_map: typing.Dict[int, int] = {}

        arc_starts: typing.List[int] = []
        arc_ends: typing.List[int] = []
        arc_caps: typing.List[int] = []
        arc_costs: typing.List[int] = []

        all_node_ids: typing.Set[int] = set()

        with perf_timer.begin_move_event('OrTools build phase1 demands and in/out nodes per island'):
            flow_diag_islands: typing.Set[int] = set()
            for island in islands.all_tile_islands:
                island_army_sum = _get_island_army_sum(island)
                cost = island.tile_count # - 1
                demand = island.tile_count - island_army_sum
                has_nx_demand_attr = False
                if island.team == team:
                    has_nx_demand_attr = True
                    cumulative_demand += demand
                    friendly_army_supply += island_army_sum - island.tile_count
                    if island.tiles_by_army[0].army == 1:
                        # Don't ask me why but 300 works well while like 3 does not.  See test_should_not_waste_a_bunch_of_moves_moving_from_general, which makes suboptimal moves at += 3 but plays great at += 300
                        cost += 300
                elif island.team == target_team:
                    has_nx_demand_attr = True
                    demand = island_army_sum + island.tile_count
                    cumulative_demand += demand
                    enemy_army_demand += demand
                elif island.team == -1:
                    role = island_roles[island.unique_id]
                    if not role.is_neutral_sink_no_neut or use_neutral_flow:
                        has_nx_demand_attr = True
                        cumulative_demand += demand
                        cost = max(1, cost) * 2

                demands[island.unique_id] = demand

                # NX demand → OR-Tools supply: or_supply = -nx_demand.
                # Only islands that get a 'demand' attribute on their NX node contribute
                # a non-zero supply; all others default to 0 (NX nodes without 'demand').
                node_supply_map[island.unique_id] = -demand if has_nx_demand_attr else 0
                # Output port has zero supply (no demand attr in NX)
                node_supply_map[-island.unique_id] = 0

                borders_target = any(b.team == target_team for b in island.border_islands)
                borders_friendly = any(b.team == team for b in island.border_islands)
                if self.log_debug:
                    if (
                        island is target_general_island
                        or island is fr_general_island
                        or island.team == team and borders_target
                        or island.team == target_team and borders_friendly
                    ):
                        flow_diag_islands.add(island.unique_id)
                        for border_island in island.border_islands:
                            if border_island.team == team or border_island.team == target_team:
                                flow_diag_islands.add(border_island.unique_id)
                if self.log_debug and island.unique_id in flow_diag_islands:
                    logbook.warning(
                        f'FLOW_DIAG_PHASE1 use_neutral_flow={use_neutral_flow} '
                        f'{self._format_island_for_flow_diag(island, demand, node_supply_map[island.unique_id])}'
                    )

                all_node_ids.add(island.unique_id)
                all_node_ids.add(-island.unique_id)

                # Split edge: input → output (weight=cost, capacity=100000)
                arc_starts.append(island.unique_id)
                arc_ends.append(-island.unique_id)
                # Note that this is the flow THROUGH an island, all islands can flow any amount of army through them (except perhaps tunnels...?)
                arc_caps.append(100000)
                arc_costs.append(cost)

        # ----------------------------------------------------------------
        # Phase 2: border edges and neutral sinks (mirrors build_graph_data)
        # ----------------------------------------------------------------
        with perf_timer.begin_move_event('OrTools build phase2 border edges'):
            neut_sinks: typing.Set[int] = set()
            for island in islands.all_tile_islands:
                role = island_roles[island.unique_id]

                for movable_island in island.border_islands:
                    # Edge: output port → neighbour input port (weight=1, capacity=100000)
                    src = -island.unique_id
                    dst = movable_island.unique_id
                    arc_starts.append(src)
                    arc_ends.append(dst)
                    arc_caps.append(100000)
                    cost = 2
                    if island.team == team:
                        cost += 2
                    elif island.team == -1:
                        cost += 1
                    arc_costs.append(cost)
                    # if island.team == team:
                    #     arc_costs.append(1000 - island.sum_army + island.tile_count)
                    # elif island.team == target_team:
                    #     arc_costs.append(900 + island.sum_army + island.tile_count)
                    # else:
                    #     arc_costs.append(2000)
                    all_node_ids.add(src)
                    all_node_ids.add(dst)
                    if self.log_debug and (island.unique_id in flow_diag_islands or movable_island.unique_id in flow_diag_islands):
                        logbook.warning(
                            f'FLOW_DIAG_BORDER_EDGE use_neutral_flow={use_neutral_flow} '
                            f'{island.unique_id}(team={island.team},army={island.sum_army},tiles={island.tile_count}) '
                            f'-> {movable_island.unique_id}(team={movable_island.team},army={movable_island.sum_army},tiles={movable_island.tile_count}) '
                            f'arc={src}->{dst} cost=1 cap=100000'
                        )

                if use_neutral_flow:
                    sink_flag = role.is_neutral_sink_with_neut
                else:
                    sink_flag = role.is_neutral_sink_no_neut
                if sink_flag:
                    neut_sinks.add(island.unique_id)
        # ----------------------------------------------------------------
        # Phase 3: fakeNode (mirrors build_graph_data)
        # ----------------------------------------------------------------
        with perf_timer.begin_move_event('OrTools build phase3 fill input arrays'):
            fake_node = random.randint(1000000, 9000000)
            while fake_node in islands.tile_islands_by_unique_id:
                fake_node = random.randint(1000000, 9000000)

            # fakeNode supply = -(-cumulativeDemand) = cumulativeDemand (balances the graph)
            node_supply_map[fake_node] = cumulative_demand
            all_node_ids.add(fake_node)
            fake_node_excess_supply = max(0, cumulative_demand)
            fake_node_enemy_general_fallback_capacity: int
            friendly_pressure_capacities_by_island_id: typing.Dict[int, int]
            if DEMAND_SATURATION_FROM_GENERAL_ONLY:
                fake_node_enemy_general_fallback_capacity = (fake_node_excess_supply + 1) // 2
                friendly_pressure_capacities_by_island_id = {
                    fr_general_island.unique_id: fake_node_excess_supply - fake_node_enemy_general_fallback_capacity
                }
                logbook.warning(
                    f'FLOW_DEMAND_SATURATION mode=general_only fakeNode={fake_node} excess={fake_node_excess_supply} '
                    f'enemyGeneralIsland={target_general_island.unique_id} enemyCapacity={fake_node_enemy_general_fallback_capacity} '
                    f'friendlyGeneralIsland={fr_general_island.unique_id} friendlyCapacity={friendly_pressure_capacities_by_island_id[fr_general_island.unique_id]}'
                )
            else:
                fake_node_enemy_general_fallback_capacity = (fake_node_excess_supply * 35 + 50) // 100
                friendly_fallback_capacity = fake_node_excess_supply - fake_node_enemy_general_fallback_capacity
                pressure_islands_by_id: typing.Dict[int, 'TileIsland'] = {fr_general_island.unique_id: fr_general_island}
                pressure_tiles = sorted(
                    (
                        tile
                        for island in islands.all_tile_islands
                        if island.team == team
                        for tile in island.tile_set
                        if tile.army >= 7
                    ),
                    key=lambda candidate: (candidate.army, -candidate.tile_index),
                    reverse=True,
                )
                for pressure_tile in pressure_tiles:
                    if len(pressure_islands_by_id) >= 11:
                        break
                    pressure_island = islands.tile_island_lookup.raw[pressure_tile.tile_index]
                    if pressure_island is not None:
                        pressure_islands_by_id[pressure_island.unique_id] = pressure_island
                pressure_islands = list(pressure_islands_by_id.values())
                friendly_pressure_capacities_by_island_id = {}
                pressure_island_count = len(pressure_islands)
                base_pressure_capacity = friendly_fallback_capacity // pressure_island_count
                remainder_pressure_capacity = friendly_fallback_capacity - base_pressure_capacity * pressure_island_count
                for pressure_island in pressure_islands:
                    friendly_pressure_capacities_by_island_id[pressure_island.unique_id] = base_pressure_capacity
                if pressure_islands:
                    friendly_pressure_capacities_by_island_id[pressure_islands[0].unique_id] += remainder_pressure_capacity
                pressure_island_log = [
                    (
                        pressure_island.unique_id,
                        pressure_island.sum_army,
                        pressure_island.tile_count,
                        friendly_pressure_capacities_by_island_id[pressure_island.unique_id],
                        [(tile.x, tile.y, tile.army) for tile in pressure_island.tiles_by_army[:4]],
                    )
                    for pressure_island in pressure_islands
                ]
                logbook.warning(
                    f'FLOW_DEMAND_SATURATION mode=distributed fakeNode={fake_node} excess={fake_node_excess_supply} '
                    f'enemyGeneralIsland={target_general_island.unique_id} enemyCapacity={fake_node_enemy_general_fallback_capacity} '
                    f'friendlyCapacityTotal={friendly_fallback_capacity} pressureIslands={pressure_island_log}'
                )

            # Edges to/from neutral sinks
            neut_sink_weight = 10 if use_neutral_flow else 0
            if use_neutral_flow:
                for neut_sink_id in neut_sinks:
                    isl = islands.tile_islands_by_unique_id[neut_sink_id]
                    capacity = isl.tile_count
                    arc_starts.append(fake_node)
                    arc_ends.append(neut_sink_id)
                    arc_caps.append(capacity)
                    arc_costs.append(neut_sink_weight)
                    all_node_ids.add(neut_sink_id)

            # Backpressure weight mirrors NX builder
            backpressure_weight = 0 if use_backpressure_from_enemy_general else 10000

            # -targetGeneralIsland.unique_id → fakeNode
            arc_starts.append(-target_general_island.unique_id)
            arc_ends.append(fake_node)
            arc_caps.append(1000)
            arc_costs.append(backpressure_weight)
            all_node_ids.add(-target_general_island.unique_id)

            # -frGeneralIsland.unique_id → fakeNode
            arc_starts.append(-fr_general_island.unique_id)
            arc_ends.append(fake_node)
            arc_caps.append(1000000)
            arc_costs.append(10000)
            all_node_ids.add(-fr_general_island.unique_id)

            # fakeNode → targetGeneralIsland.unique_id
            arc_starts.append(fake_node)
            arc_ends.append(target_general_island.unique_id)
            arc_caps.append(fake_node_enemy_general_fallback_capacity)
            arc_costs.append(backpressure_weight)
            all_node_ids.add(target_general_island.unique_id)

            for friendly_pressure_island_id, friendly_pressure_capacity in friendly_pressure_capacities_by_island_id.items():
                logbook.warning(
                    f'FLOW_DEMAND_SATURATION_ARC fakeNode={fake_node} targetIsland={friendly_pressure_island_id} '
                    f'capacity={friendly_pressure_capacity} cost=10000'
                )
                arc_starts.append(fake_node)
                arc_ends.append(friendly_pressure_island_id)
                arc_caps.append(friendly_pressure_capacity)
                arc_costs.append(10000)
                all_node_ids.add(friendly_pressure_island_id)

        # ----------------------------------------------------------------
        # Phase 4: build sorted node index arrays (mirrors NxToOrToolsConverter)
        # ----------------------------------------------------------------
        with perf_timer.begin_move_event('OrTools build phase4 node index arrays'):
            all_node_ids.discard(0)
            node_list = sorted(all_node_ids)
            node_to_idx: typing.Dict[int, int] = {nid: i for i, nid in enumerate(node_list)}
            idx_to_node: typing.Dict[int, int] = {i: nid for i, nid in enumerate(node_list)}

            num_nodes = len(node_list)
            node_ids_arr = np.array(node_list, dtype=np.int64)
            node_supplies_arr = np.zeros(num_nodes, dtype=np.int64)
            for nid, supply in node_supply_map.items():
                if nid in node_to_idx:
                    node_supplies_arr[node_to_idx[nid]] = supply

            start_nodes = np.array([node_to_idx[s] for s in arc_starts], dtype=np.int64)
            end_nodes   = np.array([node_to_idx[e] for e in arc_ends],   dtype=np.int64)
            capacities  = np.array(arc_caps,  dtype=np.int64)
            unit_costs  = np.array(arc_costs, dtype=np.int64)

        if self.log_debug:
            non_zero_supply = [(node_list[i], int(node_supplies_arr[i])) for i in range(num_nodes) if node_supplies_arr[i] != 0]
            logbook.info(
                f'DirectOrToolsGraphBuilder: {num_nodes} nodes, {len(arc_starts)} arcs, '
                f'non-zero supplies={non_zero_supply}, cumulative_demand={cumulative_demand}, '
                f'use_neutral_flow={use_neutral_flow}'
            )

        result = OrToolsGraphData(
            start_nodes=start_nodes,
            end_nodes=end_nodes,
            capacities=capacities,
            unit_costs=unit_costs,
            node_ids=node_ids_arr,
            node_supplies=node_supplies_arr,
            node_to_idx=node_to_idx,
            idx_to_node=idx_to_node,
            demand_lookup=demands,
            neutral_sinks=neut_sinks,
            fake_nodes={fake_node},
            cumulative_demand=cumulative_demand,
        )
        result.friendly_army_supply = friendly_army_supply
        result.enemy_army_demand = enemy_army_demand
        result.enemy_general_demand = enemy_general_demand
        result.flow_diag_island_ids = flow_diag_islands
        if self.log_debug:
            diag_supplies = []
            for island_id in sorted(flow_diag_islands):
                if island_id in node_supply_map:
                    diag_supplies.append(f'{island_id}:in_supply={node_supply_map[island_id]} out_supply={node_supply_map.get(-island_id, 0)} demand={demands.get(island_id)}')
            logbook.warning(
                f'FLOW_DIAG_GRAPH_SUMMARY use_neutral_flow={use_neutral_flow} '
                f'friendly_army_supply={friendly_army_supply} enemy_army_demand={enemy_army_demand} '
                f'enemy_general_demand={enemy_general_demand} cumulative_demand={cumulative_demand} '
                f'fake_node={fake_node} target_general_island={target_general_island.unique_id} '
                f'friendly_general_island={fr_general_island.unique_id} diag_supplies=[{" | ".join(diag_supplies)}]'
            )
        return result

    # Delegate classify_islands_for_flow to the ABC mixin
    classify_islands_for_flow = FlowDirectionFinderABC.classify_islands_for_flow


class NxToOrToolsConverter(object):
    """
    Converts NxFlowGraphData (NetworkX DiGraph with node demands) to OrToolsGraphData.

    OR-Tools SimpleMinCostFlow uses:
      - Parallel arc arrays: start_nodes, end_nodes, capacities, unit_costs
      - Per-node supply array: positive = source (supply), negative = sink (demand)

    NX convention: node 'demand' attribute — negative = supply, positive = demand.
    OR-Tools convention: supply — positive = supply, negative = demand.
    Therefore: or_tools_supply[node] = -nx_demand[node].

    The fakeNode in NxFlowGraphData already carries demand = -cumulativeDemand, so its
    OR-Tools supply = cumulativeDemand, which balances the graph correctly.

    Unlike the PyMaxflow converter, we do NOT need to strip supply-output → fakeNode edges
    because SimpleMinCostFlow is a true min-cost solver that respects edge unit_costs.
    The weight=1000 cost on those edges naturally prevents the solver from abusing them.
    """

    def __init__(self):
        self.log_debug: bool = False

    def convert(self, nx_graph_data: NxFlowGraphData) -> OrToolsGraphData:
        nx_graph = nx_graph_data.graph
        demands: typing.Dict[int, int] = nx_graph_data.demand_lookup
        fake_nodes: typing.Set[int] = nx_graph_data.fake_nodes

        # Collect all node ids present in the graph
        all_node_ids: typing.Set[int] = set()
        for node_id, attrs in nx_graph.nodes(data=True):
            all_node_ids.add(node_id)
        for u, v in nx_graph.edges():
            all_node_ids.add(u)
            all_node_ids.add(v)
        all_node_ids.discard(0)

        node_list = sorted(all_node_ids)
        node_to_idx: typing.Dict[int, int] = {nid: i for i, nid in enumerate(node_list)}
        idx_to_node: typing.Dict[int, int] = {i: nid for i, nid in enumerate(node_list)}

        # Build arc arrays
        arc_starts = []
        arc_ends = []
        arc_caps = []
        arc_costs = []

        for u, v, data in nx_graph.edges(data=True):
            if u not in node_to_idx or v not in node_to_idx:
                continue
            capacity = data.get('capacity', 0)
            weight = data.get('weight', 0)
            arc_starts.append(node_to_idx[u])
            arc_ends.append(node_to_idx[v])
            arc_caps.append(capacity)
            arc_costs.append(weight)

        start_nodes = np.array(arc_starts, dtype=np.int64)
        end_nodes = np.array(arc_ends, dtype=np.int64)
        capacities = np.array(arc_caps, dtype=np.int64)
        unit_costs = np.array(arc_costs, dtype=np.int64)

        # Build per-node supply array.
        # NX node 'demand' attr: negative = supply, positive = demand.
        # OR-Tools supply: positive = supply, negative = demand.
        # Therefore: or_supply = -nx_demand.
        num_nodes = len(node_list)
        node_ids_arr = np.array(node_list, dtype=np.int64)
        node_supplies_arr = np.zeros(num_nodes, dtype=np.int64)

        # Demands dict covers island nodes; fakeNode demand is set on the NX graph node directly.
        # We read supplies from the NX graph node attributes to cover all nodes uniformly.
        for node_id, attrs in nx_graph.nodes(data=True):
            if node_id not in node_to_idx:
                continue
            nx_demand = attrs.get('demand', 0)
            node_supplies_arr[node_to_idx[node_id]] = -nx_demand

        if self.log_debug:
            non_zero_supply = [(node_list[i], int(node_supplies_arr[i])) for i in range(num_nodes) if node_supplies_arr[i] != 0]
            logbook.info(f'OrTools converter: {num_nodes} nodes, {len(arc_starts)} arcs, non-zero supplies={non_zero_supply}')

        return OrToolsGraphData(
            start_nodes=start_nodes,
            end_nodes=end_nodes,
            capacities=capacities,
            unit_costs=unit_costs,
            node_ids=node_ids_arr,
            node_supplies=node_supplies_arr,
            node_to_idx=node_to_idx,
            idx_to_node=idx_to_node,
            demand_lookup=dict(demands),
            neutral_sinks=nx_graph_data.neutral_sinks,
            fake_nodes=fake_nodes,
            cumulative_demand=nx_graph_data.cumulative_demand,
        )


class OrToolsFlowComputer(object):
    """
    Runs OR-Tools SimpleMinCostFlow on an OrToolsGraphData and returns a flow dict
    in the same format as NetworkX: {source_node_id: {target_node_id: flow_amount}}.
    """

    def __init__(self, perf_timer: PerformanceTimer, log_debug: bool = False):
        self.perf_timer: PerformanceTimer = perf_timer
        self.log_debug: bool = log_debug

    def compute_flow(
        self,
        graph_data: OrToolsGraphData,
        method: FlowGraphMethod = FlowGraphMethod.OrToolsSimpleMinCost,
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        """
        Solve min-cost flow and return a flow dict matching the NX format.
        Returns an empty dict if the problem is infeasible.
        """
        with self.perf_timer.begin_move_event('OrTools build smcf'):
            smcf = min_cost_flow.SimpleMinCostFlow()
            all_arcs = smcf.add_arcs_with_capacity_and_unit_cost(
                graph_data.start_nodes,
                graph_data.end_nodes,
                graph_data.capacities,
                graph_data.unit_costs,
            )
            smcf.set_nodes_supplies(np.arange(len(graph_data.node_supplies), dtype=np.int64), graph_data.node_supplies)

        if self.log_debug:
            logbook.info(
                f'OrTools smcf: {len(graph_data.node_ids)} nodes, {len(all_arcs)} arcs, '
                f'cumulative_demand={graph_data.cumulative_demand}'
            )

        with self.perf_timer.begin_move_event('OrTools smcf.solve()'):
            status = smcf.solve()

        if status != smcf.OPTIMAL:
            logbook.warning(f'OrTools SimpleMinCostFlow solve status={status} (not OPTIMAL) — returning empty flow dict')
            return {}

        if self.log_debug:
            logbook.info(f'OrTools optimal_cost={smcf.optimal_cost()}')

        with self.perf_timer.begin_move_event('OrTools flow_dict builder post-solve'):
            flow_dict: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))
            fake_nodes = graph_data.fake_nodes
            idx_to_node = graph_data.idx_to_node
            flow_diag_islands = getattr(graph_data, 'flow_diag_island_ids', set())

            solution_flows = smcf.flows(all_arcs)

            for arc_idx in range(len(all_arcs)):
                flow_amount = int(solution_flows[arc_idx])
                if flow_amount <= 0:
                    continue

                from_orig = idx_to_node.get(int(graph_data.start_nodes[arc_idx]))
                to_orig = idx_to_node.get(int(graph_data.end_nodes[arc_idx]))

                if from_orig is None or to_orig is None:
                    continue

                from_is_fake = abs(from_orig) in fake_nodes
                to_is_fake = abs(to_orig) in fake_nodes
                is_fake_saturation_arc = from_is_fake or to_is_fake

                if self.log_debug:
                    logbook.info(
                        f'  OrTools arc {arc_idx}: {from_orig} -> {to_orig} '
                        f'flow={flow_amount} from_fake={from_is_fake} to_fake={to_is_fake}'
                    )
                if self.log_debug and (
                    abs(from_orig) in flow_diag_islands
                    or abs(to_orig) in flow_diag_islands
                    or from_is_fake
                    or to_is_fake
                ):
                    logbook.warning(
                        f'FLOW_DIAG_SOLVED_ARC arc={arc_idx} {from_orig}->{to_orig} flow={flow_amount} '
                        f'cost={int(graph_data.unit_costs[arc_idx])} cap={int(graph_data.capacities[arc_idx])} '
                        f'from_fake={from_is_fake} to_fake={to_is_fake}'
                    )
                if is_fake_saturation_arc:
                    logbook.warning(
                        f'FLOW_DEMAND_SATURATION_SOLVED_ARC arc={arc_idx} {from_orig}->{to_orig} '
                        f'flow={flow_amount} cost={int(graph_data.unit_costs[arc_idx])} cap={int(graph_data.capacities[arc_idx])} '
                        f'from_fake={from_is_fake} to_fake={to_is_fake}'
                    )

                if not from_is_fake and not to_is_fake:
                    flow_dict[from_orig][to_orig] = flow_dict[from_orig].get(to_orig, 0) + flow_amount
                    continue

                if from_is_fake and not to_is_fake and to_orig in graph_data.neutral_sinks:
                    flow_dict[from_orig][to_orig] = flow_dict[from_orig].get(to_orig, 0) + flow_amount
                    continue

                if from_is_fake and not to_is_fake:
                    flow_dict[from_orig][to_orig] = flow_dict[from_orig].get(to_orig, 0) + flow_amount
                    continue

                if self.log_debug:
                    logbook.info(f'    ignored arc (fake-node handling)')

            if self.log_debug:
                diag_flow_dict = {}
                for src, targets in flow_dict.items():
                    if abs(src) in flow_diag_islands:
                        diag_flow_dict[src] = dict(targets)
                        continue
                    diag_targets = {dst: amount for dst, amount in targets.items() if abs(dst) in flow_diag_islands}
                    if diag_targets:
                        diag_flow_dict[src] = diag_targets
                logbook.warning(f'FLOW_DIAG_FLOW_DICT touching_diag_islands={diag_flow_dict}')

        return dict(flow_dict)


class OrToolsFlowDirectionFinder(FlowDirectionFinderABC):
    """
    FlowDirectionFinderABC implementation backed by OR-Tools SimpleMinCostFlow.

    Graph construction is handled directly by DirectOrToolsGraphBuilder, which mirrors
    exactly what NetworkXFlowDirectionFinder.build_graph_data + NxToOrToolsConverter
    produce but without constructing a NetworkX DiGraph as an intermediate step.
    """

    def __init__(
        self,
        map: 'MapBase',
        intergeneral_analysis: 'ArmyAnalyzer',
        perf_timer: PerformanceTimer,
        log_debug: bool,
        use_backpressure: bool,
        friendly_general: 'Tile',
        invalid_flow_renderer,
    ):
        self.map: 'MapBase' = map
        self.perf_timer: PerformanceTimer = perf_timer
        self.log_debug: bool = log_debug
        self.use_backpressure_from_enemy_general: bool = use_backpressure
        self.friendly_general: 'Tile' = friendly_general
        self.invalid_flow_renderer = invalid_flow_renderer
        self.army_override_matrix: 'MapMatrixInterface[int] | None' = None
        self.negative_tiles: 'TileSet | None' = None

        self._intergeneral_analysis: 'ArmyAnalyzer' = intergeneral_analysis
        self._nx_finder: NetworkXFlowDirectionFinder | None = None

        self.team: int = map.friendly_team
        self.target_team: int = [t for t in map.get_teams_array(map) if t != self.team][0]
        self._enemy_general: 'Tile | None' = None

        self.ortools_graph_data: OrToolsGraphData | None = None
        self.ortools_graph_data_no_neut: OrToolsGraphData | None = None
        self._last_built_graphs_turn: int = -1

    def _get_nx_finder(self) -> NetworkXFlowDirectionFinder:
        """Return (and lazily construct) the inner NX finder."""
        if self._nx_finder is None:
            self._nx_finder = NetworkXFlowDirectionFinder(
                self.map,
                self._intergeneral_analysis,
                self.friendly_general,
                self.use_backpressure_from_enemy_general,
                self.perf_timer,
                self.log_debug,
                self.invalid_flow_renderer,
            )
        self._nx_finder.configure(self.team, self.target_team, self._enemy_general)
        return self._nx_finder

    # ------------------------------------------------------------------
    # FlowDirectionFinderABC interface
    # ------------------------------------------------------------------

    def configure(self, team: int, target_team: int, enemy_general: 'Tile | None'):
        self.team = team
        self.target_team = target_team
        self.enemy_general = enemy_general

    def invalidate_cache(self):
        self.ortools_graph_data = None
        self.ortools_graph_data_no_neut = None
        if self._nx_finder is not None:
            self._nx_finder.invalidate_cache()

    @property
    def graph_data(self) -> OrToolsGraphData | None:
        return self.ortools_graph_data

    @property
    def graph_data_no_neut(self) -> OrToolsGraphData | None:
        return self.ortools_graph_data_no_neut

    @property
    def enemy_general(self) -> 'Tile | None':
        return self._enemy_general

    @enemy_general.setter
    def enemy_general(self, value: 'Tile | None'):
        self._enemy_general = value


    def ensure_graph_data_available(self, islands: 'TileIslandBuilder', allow_neutral_flow: bool):
        turn_stale = self._last_built_graphs_turn < self.map.turn
        if self.ortools_graph_data_no_neut is None or turn_stale:
            with self.perf_timer.begin_move_event('OrTools build_graph_data no_neut'):
                self.ortools_graph_data_no_neut = self.build_graph_data(islands, use_neutral_flow=False)
            self._last_built_graphs_turn = self.map.turn
        if allow_neutral_flow and (self.ortools_graph_data is None or turn_stale):
            with self.perf_timer.begin_move_event('OrTools build_graph_data inc_neut'):
                self.ortools_graph_data = self.build_graph_data(islands, use_neutral_flow=True)

    def build_graph_data(self, islands: 'TileIslandBuilder', use_neutral_flow: bool) -> OrToolsGraphData:
        if self._enemy_general is None:
            self._enemy_general = self._intergeneral_analysis.tileB
        enemy_general = self._enemy_general
        if enemy_general is None:
            raise Exception("Enemy general is None")

        builder = DirectOrToolsGraphBuilder()
        builder.log_debug = self.log_debug
        return builder.build(
            islands,
            self._intergeneral_analysis,
            self.map,
            self.team,
            self.target_team,
            self.friendly_general,
            enemy_general,
            self.use_backpressure_from_enemy_general,
            use_neutral_flow,
            self.army_override_matrix,
            self.negative_tiles,
            perf_timer=self.perf_timer,
        )

    def build_graph_data__old(self, islands: 'TileIslandBuilder', use_neutral_flow: bool) -> OrToolsGraphData:
        nx_finder = self._get_nx_finder()
        nx_data: NxFlowGraphData = nx_finder.build_graph_data(islands, use_neutral_flow)
        self._enemy_general = nx_finder.enemy_general
        converter = NxToOrToolsConverter()
        converter.log_debug = self.log_debug
        return converter.convert(nx_data)

    def compute_flow_dict(
        self,
        islands: 'TileIslandBuilder',
        graph_data: OrToolsGraphData,
        method,
        render_on_exception: bool = True,
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        computer = OrToolsFlowComputer(self.perf_timer, self.log_debug)
        return computer.compute_flow(graph_data, method)

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
        if negativeTiles is not self.negative_tiles:
            self.negative_tiles = negativeTiles
            self.invalidate_cache()
        with self.perf_timer.begin_move_event('OrTools ensure_graph_data_available'):
            self.ensure_graph_data_available(islands, allow_neutral_flow=includeNeutralDemand)

        graph_data_with_neut: OrToolsGraphData = self.ortools_graph_data
        graph_data_no_neut: OrToolsGraphData = self.ortools_graph_data_no_neut

        with self.perf_timer.begin_move_event('OrTools compute_flow_dict no_neut'):
            no_neut_flow_dict = self.compute_flow_dict(islands, graph_data_no_neut, method)
        if includeNeutralDemand:
            with self.perf_timer.begin_move_event('OrTools compute_flow_dict inc_neut'):
                with_neut_flow_dict = self.compute_flow_dict(islands, graph_data_with_neut, method)

        target_general_island = islands.tile_island_lookup.raw[self._enemy_general.tile_index]

        with_neut_graph_lookup: typing.Dict[int, IslandFlowNode] = {}
        no_neut_graph_lookup: typing.Dict[int, IslandFlowNode] = {}

        backfill_neut_edges: typing.List = []
        enemy_backfill_flow_nodes: typing.List[IslandFlowNode] = []
        final_root_flow_nodes: typing.List[IslandFlowNode] = []

        with self.perf_timer.begin_move_event(f'OrTools build graph_lookups, {len(islands.all_tile_islands)} islands:'):
            for island in islands.all_tile_islands:
                demand_no_neut = graph_data_no_neut.demand_lookup.get(island.unique_id, 0)
                no_neut_graph_lookup[island.unique_id] = IslandFlowNode(island, demand_no_neut)
                if includeNeutralDemand:
                    demand_with_neut = graph_data_with_neut.demand_lookup.get(island.unique_id, 0)
                    with_neut_graph_lookup[island.unique_id] = IslandFlowNode(island, demand_with_neut)

        with self.perf_timer.begin_move_event('OrTools build_flow_nodes_from_lookups no_neut'):
            backfill_neut_no_neut_edges, enemy_backfill_no_neut_flow_nodes, final_root_no_neut_flow_nodes = self.build_flow_nodes_from_lookups(
                our_islands, target_general_island, target_islands, no_neut_flow_dict, no_neut_graph_lookup, graph_data_no_neut, self.log_debug
            )
        if includeNeutralDemand:
            with self.perf_timer.begin_move_event('OrTools build_flow_nodes_from_lookups inc_neut'):
                backfill_neut_edges, enemy_backfill_flow_nodes, final_root_flow_nodes = self.build_flow_nodes_from_lookups(
                    our_islands, target_general_island, target_islands, with_neut_flow_dict, with_neut_graph_lookup, graph_data_with_neut, self.log_debug
                )


        with self.perf_timer.begin_move_event('OrTools alloc+populate tile MapMatrix lookups'):
            no_neut_flow_node_lookup = MapMatrix(self.map, None)
            inc_neut_flow_node_lookup = MapMatrix(self.map, None)
            for flow_node in no_neut_graph_lookup.values():
                for t in flow_node.island.tile_set:
                    no_neut_flow_node_lookup.raw[t.tile_index] = flow_node
            if includeNeutralDemand:
                for flow_node in with_neut_graph_lookup.values():
                    for t in flow_node.island.tile_set:
                        inc_neut_flow_node_lookup.raw[t.tile_index] = flow_node

        with self.perf_timer.begin_move_event('OrTools IslandMaxFlowGraph ctor'):
            result = IslandMaxFlowGraph(
                final_root_no_neut_flow_nodes,
                final_root_flow_nodes,
                enemy_backfill_no_neut_flow_nodes,
                enemy_backfill_flow_nodes,
                backfill_neut_no_neut_edges,
                backfill_neut_edges,
                no_neut_flow_node_lookup,
                inc_neut_flow_node_lookup,
                no_neut_graph_lookup,
                with_neut_graph_lookup,
            )
        return result
