from __future__ import annotations

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

if typing.TYPE_CHECKING:
    from Algorithms import TileIslandBuilder, TileIsland
    from ArmyAnalyzer import ArmyAnalyzer
    from base.client.map import MapBase, Tile
    from Interfaces import TileSet


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

        flow_dict: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        fake_nodes = graph_data.fake_nodes
        idx_to_node = graph_data.idx_to_node

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

            if self.log_debug:
                logbook.info(
                    f'  OrTools arc {arc_idx}: {from_orig} -> {to_orig} '
                    f'flow={flow_amount} from_fake={from_is_fake} to_fake={to_is_fake}'
                )

            if not from_is_fake and not to_is_fake:
                flow_dict[from_orig][to_orig] = flow_dict[from_orig].get(to_orig, 0) + flow_amount
                continue

            if from_is_fake and not to_is_fake and to_orig in graph_data.neutral_sinks:
                flow_dict[from_orig][to_orig] = flow_dict[from_orig].get(to_orig, 0) + flow_amount
                continue

            if self.log_debug:
                logbook.info(f'    ignored arc (fake-node handling)')

        if self.log_debug:
            non_zero = {src: dict(tgts) for src, tgts in flow_dict.items() if tgts}
            logbook.info(f'OrTools flow_dict={non_zero}')

        return dict(flow_dict)


class OrToolsFlowDirectionFinder(FlowDirectionFinderABC):
    """
    FlowDirectionFinderABC implementation backed by OR-Tools SimpleMinCostFlow.

    Graph construction is delegated to NetworkXFlowDirectionFinder (which builds the
    NxFlowGraphData); the result is then converted to OR-Tools input arrays and solved
    with SimpleMinCostFlow — a true min-cost solver that respects edge weights.

    This mirrors the structure of PyMaxFlowDirectionFinder exactly.
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

    def ensure_graph_data_available(self, islands: 'TileIslandBuilder'):
        nx_finder = self._get_nx_finder()
        nx_finder.ensure_graph_data_available(islands)
        self._enemy_general = nx_finder.enemy_general

        converter = NxToOrToolsConverter()
        converter.log_debug = self.log_debug
        self.ortools_graph_data = converter.convert(nx_finder.nx_graph_data)
        self.ortools_graph_data_no_neut = converter.convert(nx_finder.nx_graph_data_no_neut)
        self._last_built_graphs_turn = self.map.turn

    def build_graph_data(self, islands: 'TileIslandBuilder', use_neutral_flow: bool) -> OrToolsGraphData:
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
        self.ensure_graph_data_available(islands)

        graph_data_with_neut: OrToolsGraphData = self.ortools_graph_data
        graph_data_no_neut: OrToolsGraphData = self.ortools_graph_data_no_neut

        with_neut_flow_dict = self.compute_flow_dict(islands, graph_data_with_neut, method)
        no_neut_flow_dict = self.compute_flow_dict(islands, graph_data_no_neut, method)

        target_general_island = islands.tile_island_lookup.raw[self._enemy_general.tile_index]

        with_neut_graph_lookup: typing.Dict[int, IslandFlowNode] = {}
        no_neut_graph_lookup: typing.Dict[int, IslandFlowNode] = {}

        for island in islands.all_tile_islands:
            demand_no_neut = graph_data_no_neut.demand_lookup.get(island.unique_id, 0)
            no_neut_graph_lookup[island.unique_id] = IslandFlowNode(island, demand_no_neut)

            demand_with_neut = graph_data_with_neut.demand_lookup.get(island.unique_id, 0)
            with_neut_graph_lookup[island.unique_id] = IslandFlowNode(island, demand_with_neut)

        backfill_neut_edges, enemy_backfill_flow_nodes, final_root_flow_nodes = self.build_flow_nodes_from_lookups(
            our_islands, target_general_island, target_islands, with_neut_flow_dict, with_neut_graph_lookup, graph_data_with_neut, self.log_debug
        )
        backfill_neut_no_neut_edges, enemy_backfill_no_neut_flow_nodes, final_root_no_neut_flow_nodes = self.build_flow_nodes_from_lookups(
            our_islands, target_general_island, target_islands, no_neut_flow_dict, no_neut_graph_lookup, graph_data_no_neut, self.log_debug
        )

        no_neut_flow_node_lookup = MapMatrix(self.map, None)
        inc_neut_flow_node_lookup = MapMatrix(self.map, None)
        for flow_node in no_neut_graph_lookup.values():
            for t in flow_node.island.tile_set:
                no_neut_flow_node_lookup.raw[t.tile_index] = flow_node
        for flow_node in with_neut_graph_lookup.values():
            for t in flow_node.island.tile_set:
                inc_neut_flow_node_lookup.raw[t.tile_index] = flow_node

        return IslandMaxFlowGraph(
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
