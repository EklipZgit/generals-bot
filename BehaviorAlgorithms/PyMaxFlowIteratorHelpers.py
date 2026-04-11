from __future__ import annotations

import typing
from enum import Enum
from collections import defaultdict, deque

import networkx

import logbook
import time

from PerformanceTimer import PerformanceTimer
import PyMaxflowLocal as maxflow


# Make sure these match the values in IterativeExpansion.py FlowGraphMethod enum
# We add new methods here to avoid circular imports
class FlowGraphMethod(Enum):
    """Flow graph algorithm methods for island max flow computations."""
    # NetworkX min-cost flow methods
    NetworkSimplex = 1
    CapacityScaling = 2
    MinCostFlow = 3

    # PyMaxflow max-flow methods
    PyMaxflowBoykovKolmogorov = 10  # Standard BK maxflow algorithm
    PyMaxflowWithNodeSplitting = 11  # Maxflow with node splitting to approximate min-cost


class PyMaxFlowGraphData(object):
    """
    PyMaxflow-based alternative to NxFlowGraphData.
    Stores graph data in a format compatible with PyMaxflow's maxflow implementation.
    """
    def __init__(
        self,
        num_nodes: int,
        edges: typing.List[typing.Tuple[int, int, int, int]],  # (i, j, capacity, rcapacity)
        terminal_edges: typing.List[typing.Tuple[int, int, int]],  # (node, source_capacity, sink_capacity)
        node_id_mapping: typing.Dict[int, int],  # Maps island unique_id -> PyMaxflow node index
        reverse_node_mapping: typing.Dict[int, int],  # Maps PyMaxflow node index -> island unique_id
        demands: typing.Dict[int, int],  # Original demands by island unique_id (for reference)
        neutral_sinks: typing.Set[int],  # Set of neutral sink island unique_ids
        cumulative_demand: int,
        fake_nodes: typing.Set[int] | None = None
    ):
        self.num_nodes: int = num_nodes
        self.edges: typing.List[typing.Tuple[int, int, int, int]] = edges
        self.terminal_edges: typing.List[typing.Tuple[int, int, int]] = terminal_edges

        # Mappings between island unique IDs and PyMaxflow node indices (0-based)
        self.node_id_mapping: typing.Dict[int, int] = node_id_mapping
        self.reverse_node_mapping: typing.Dict[int, int] = reverse_node_mapping

        # Original demands for reference/debugging
        self.demand_lookup: typing.Dict[int, int] = demands
        self.cumulative_demand: int = cumulative_demand

        self.neutral_sinks: typing.Set[int] = neutral_sinks
        self.fake_nodes: typing.Set[int] = fake_nodes if fake_nodes is not None else frozenset()

        # Cached graph - built on first use
        self._graph: typing.Any = None


class PyMaxFlowComputer(object):
    """
    Computes max flow using PyMaxflow library.
    Converts results to the same format as NetworkX flow algorithms.
    """

    def __init__(self, perfTimer: PerformanceTimer, logDebug: bool = False):
        self.perf_timer: PerformanceTimer = perfTimer
        self.log_debug: bool = logDebug

    def compute_flow(
        self,

        graph_data: PyMaxFlowGraphData,
        method: FlowGraphMethod = FlowGraphMethod.PyMaxflowBoykovKolmogorov
    ) -> typing.Tuple[int, typing.Dict[int, typing.Dict[int, int]]]:
        """
        Compute max flow using PyMaxflow and return in NetworkX-compatible format.

        @param graph_data: PyMaxFlowGraphData containing the graph structure
        @param method: Which PyMaxflow algorithm to use
        @return: Tuple of (flow_value, flow_dict) where flow_dict maps source_node_id -> {target_node_id: flow_amount}
        """

        start = time.perf_counter()

        with self.perf_timer.begin_move_event('_build_maxflow_graph'):
            # Build or retrieve cached graph
            g = self._build_maxflow_graph(graph_data)

        logbook.info(f'PyMaxflow graph: {graph_data.num_nodes} nodes, {len(graph_data.edges)} edges, {len(graph_data.terminal_edges)} terminal edges')
        if self.log_debug:
            # Log all edges with their node ID mappings
            for i, (u, v, cap, rcap) in enumerate(graph_data.edges):
                u_node = graph_data.reverse_node_mapping.get(u, '?')
                v_node = graph_data.reverse_node_mapping.get(v, '?')
                logbook.info(f'  Edge {i}: {u}({u_node}) -> {v}({v_node}) cap={cap}')
            logbook.info(f'  Terminal edges: {graph_data.terminal_edges}')
            logbook.info(f'  Node mapping: {graph_data.reverse_node_mapping}')

        # Compute max flow
        with self.perf_timer.begin_move_event('compute g.maxflow()'):
            flow_value = g.maxflow()

        # Extract flow assignment from segments
        # In PyMaxflow, after maxflow(), nodes are partitioned into source-side (0) and sink-side (1)
        # We need to reconstruct which flows actually occurred
        with self.perf_timer.begin_move_event('_extract_flow_dict'):
            flow_dict = self._extract_flow_dict(g, graph_data)

        elapsed = time.perf_counter() - start
        if self.log_debug:
            logbook.info(f'{method} complete with flow_value {flow_value} in {elapsed:.5f}s')
            # Log segments for debugging
            segments = {idx: g.get_segment(idx) for idx in range(graph_data.num_nodes)}
            logbook.info(f'  Segments: {segments}')

        return flow_value, flow_dict

    def _build_maxflow_graph(self, graph_data: PyMaxFlowGraphData) -> typing.Any:
        """Build a PyMaxflow graph from the graph data."""
        if graph_data._graph is not None:
            return graph_data._graph

        # Create graph with estimated nodes and edges
        # PyMaxflow.Graph[int](num_nodes, num_edges)
        num_edges = len(graph_data.edges)
        g = maxflow.Graph[int](graph_data.num_nodes, num_edges)

        # Add nodes (they are assigned indices 0 to num_nodes-1)
        nodes = g.add_nodes(graph_data.num_nodes)

        # Add non-terminal edges
        for i, j, capacity, rcapacity in graph_data.edges:
            g.add_edge(i, j, capacity, rcapacity)

        # Add terminal edges (source/sink connections)
        for node, source_cap, sink_cap in graph_data.terminal_edges:
            g.add_tedge(node, source_cap, sink_cap)

        graph_data._graph = g
        return g

    def _extract_flow_dict(
        self,
        g: typing.Any,
        graph_data: PyMaxFlowGraphData
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        """
        Extract flow dictionary from PyMaxflow result.

        The flow_dict format matches NetworkX:
        {source_node_id: {target_node_id: flow_amount, ...}, ...}
        where node_ids are positive for output nodes and negative for input nodes.
        """
        flow_dict: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        raw_flow_dict: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))

        fake_nodes = graph_data.fake_nodes

        extract_start = time.perf_counter()
        residual_arrays = getattr(g, 'get_edge_residuals', None)
        get_residuals_elapsed = 0.0
        residual_graph = None
        residual_caps_by_edge: typing.Dict[typing.Tuple[int, int], typing.Any] | None = None

        if residual_arrays is not None:
            from_nodes, to_nodes, residual_caps = residual_arrays()
            get_residuals_elapsed = time.perf_counter() - extract_start
            residual_caps_by_edge = {}
            for idx in range(len(from_nodes)):
                edge = (int(from_nodes[idx]), int(to_nodes[idx]))
                residual_value = residual_caps[idx]
                residual_caps_by_edge[edge] = residual_caps_by_edge.get(edge, 0) + residual_value
        else:
            residual_graph = g.get_nx_graph()
            get_residuals_elapsed = time.perf_counter() - extract_start
        scan_start = time.perf_counter()

        if self.log_debug and residual_graph is not None:
            logbook.info(f'  Extracting flow from residual graph with {residual_graph.number_of_nodes()} nodes and {residual_graph.number_of_edges()} edges')

        for from_idx, to_idx, capacity, _ in graph_data.edges:
            if residual_caps_by_edge is not None:
                residual_capacity = residual_caps_by_edge.get((from_idx, to_idx), 0)
            else:
                residual_capacity = 0
                if residual_graph is not None and residual_graph.has_edge(from_idx, to_idx):
                    residual_capacity = residual_graph[from_idx][to_idx].get('weight', 0)

            flow_amount = capacity - residual_capacity
            if flow_amount <= 0:
                continue

            node_from = graph_data.reverse_node_mapping.get(from_idx)
            node_to = graph_data.reverse_node_mapping.get(to_idx)

            if self.log_debug:
                logbook.info(f'    Residual lookup: {from_idx} -> {to_idx}, residual={residual_capacity}, flow={flow_amount}, mapped={node_from} -> {node_to}')

            if node_from is None or node_to is None:
                continue

            raw_flow_dict[node_from][node_to] = raw_flow_dict[node_from].get(node_to, 0) + flow_amount

        pending_fake_edges: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))

        for node_from, targets in raw_flow_dict.items():
            if abs(node_from) in fake_nodes:
                pending_fake_edges[node_from].update(targets)
                continue

            for node_to, flow_amount in targets.items():
                if abs(node_to) in fake_nodes:
                    pending_fake_edges[node_from][node_to] = pending_fake_edges[node_from].get(node_to, 0) + flow_amount
                    continue
                flow_dict[node_from][node_to] = flow_dict[node_from].get(node_to, 0) + flow_amount

        while pending_fake_edges:
            next_pending_fake_edges: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))
            progressed = False

            for node_from, targets in pending_fake_edges.items():
                for node_to, flow_amount in targets.items():
                    if flow_amount <= 0:
                        continue

                    if abs(node_to) not in fake_nodes:
                        flow_dict[node_from][node_to] = flow_dict[node_from].get(node_to, 0) + flow_amount
                        progressed = True
                        continue

                    fake_targets = raw_flow_dict.get(node_to)
                    if not fake_targets:
                        continue

                    progressed = True
                    for fake_target, fake_target_flow in fake_targets.items():
                        forwarded_flow = min(flow_amount, fake_target_flow)
                        if forwarded_flow <= 0:
                            continue
                        if abs(fake_target) in fake_nodes:
                            next_pending_fake_edges[node_from][fake_target] = next_pending_fake_edges[node_from].get(fake_target, 0) + forwarded_flow
                        else:
                            flow_dict[node_from][fake_target] = flow_dict[node_from].get(fake_target, 0) + forwarded_flow

            if not progressed:
                break

            pending_fake_edges = next_pending_fake_edges

        scan_elapsed = time.perf_counter() - scan_start
        total_elapsed = time.perf_counter() - extract_start
        logbook.info(
            f'_extract_flow_dict split: '
            f'get_residuals={get_residuals_elapsed:.5f}s, '
            f'scan_edges={scan_elapsed:.5f}s, '
            f'total={total_elapsed:.5f}s'
        )

        return dict(flow_dict)


class NxToPyMaxflowConverter(object):
    """
    Converts NetworkX-style min-cost flow graphs to PyMaxflow max-flow format.

    This handles the conversion from:
    - NetworkX DiGraph with node demands and edge capacities/weights
    - To PyMaxflow Graph with terminal edges representing supply/demand
    """

    def __init__(self):
        self.log_debug: bool = False

    def convert_nx_flow_graph_data(
        self,
        nx_graph_data,  # NxFlowGraphData from IterativeExpansion
        include_weights: bool = False  # If True, attempt to incorporate edge weights
    ) -> PyMaxFlowGraphData:
        """
        Convert NxFlowGraphData to PyMaxFlowGraphData.

        Strategy for converting min-cost flow to max-flow:
        1. Nodes with negative demand (supply) connect to source with capacity = -demand
        2. Nodes with positive demand (demand) connect to sink with capacity = demand
        3. Regular edges use their capacity

        This gives us a max-flow solution that respects capacity constraints.
        Note: This does NOT optimize for minimum cost - it only finds a feasible flow.
        """
        nx_graph = nx_graph_data.graph
        demands = nx_graph_data.demand_lookup

        # Build node mappings - include ALL nodes including throughput (negative IDs)
        # The NetworkX graph uses positive IDs for output nodes and negative IDs for input nodes
        all_node_ids = set()
        for node_id in demands.keys():
            all_node_ids.add(node_id)
            # Also add the corresponding throughput node
            all_node_ids.add(-node_id)

        # Add nodes from graph edges too
        for edge in nx_graph.edges():
            u, v = edge[0], edge[1]
            all_node_ids.add(u)
            all_node_ids.add(v)

        # Remove 0 if present (not a valid node)
        all_node_ids.discard(0)

        # Create ordered list and mapping
        node_list = sorted(all_node_ids)
        node_to_idx = {node_id: idx for idx, node_id in enumerate(node_list)}
        idx_to_node = {idx: node_id for idx, node_id in enumerate(node_list)}

        num_nodes = len(node_list)

        # Build edges list for PyMaxflow
        edges = []
        for u, v, data in nx_graph.edges(data=True):
            capacity = data.get('capacity', 0)
            # PyMaxflow uses bidirectional edges with separate forward/reverse capacities
            # For directed flows, we set reverse capacity to 0
            if u in node_to_idx and v in node_to_idx:
                edges.append((node_to_idx[u], node_to_idx[v], capacity, 0))

        # Build terminal edges based on demands
        # Negative demand = supply (connect to source)
        # Positive demand = demand (connect to sink)
        terminal_edges = []
        for node_id, demand in demands.items():
            if node_id <= 0 or node_id not in node_to_idx:
                continue
            node_idx = node_to_idx[node_id]
            if demand < 0:
                # Supply node - connect to source
                terminal_edges.append((node_idx, -demand, 0))
            elif demand > 0:
                # Demand node - connect to sink
                terminal_edges.append((node_idx, 0, demand))

        return PyMaxFlowGraphData(
            num_nodes=num_nodes,
            edges=edges,
            terminal_edges=terminal_edges,
            node_id_mapping=node_to_idx,
            reverse_node_mapping=idx_to_node,
            demands=dict(demands),
            neutral_sinks=nx_graph_data.neutral_sinks,
            cumulative_demand=nx_graph_data.cumulative_demand,
            fake_nodes=nx_graph_data.fake_nodes
        )


def compute_island_max_flow_with_pymaxflow(
    islands,
    nx_graph_data,  # NxFlowGraphData
    perf_timer: PerformanceTimer,
    method: FlowGraphMethod = FlowGraphMethod.PyMaxflowBoykovKolmogorov,
    log_debug: bool = False
) -> typing.Dict[int, typing.Dict[int, int]]:
    """
    Compute island max flow using PyMaxflow instead of NetworkX.

    This is a drop-in replacement for _get_island_max_flow_dict in IterativeExpansion.py.

    @param islands: TileIslandBuilder
    @param nx_graph_data: NxFlowGraphData containing the NetworkX graph
    @param method: Which flow algorithm to use (from FlowGraphMethod enum)
    @param log_debug: Whether to log debug info
    @return: Flow dict in the same format as NetworkX: {source_id: {target_id: flow_amount}}
    """

    converter = NxToPyMaxflowConverter()
    converter.log_debug = log_debug

    # Convert to PyMaxflow format
    py_max_data = converter.convert_nx_flow_graph_data(nx_graph_data)

    # Compute flow
    computer = PyMaxFlowComputer(perf_timer, log_debug)

    flow_value, flow_dict = computer.compute_flow(py_max_data, method)

    return flow_dict


def patch_flow_graph_method_enum():
    """
    Helper to add PyMaxflow methods to the FlowGraphMethod enum in IterativeExpansion.
    Call this once at module load time.
    """
    # This is a no-op because we've defined the enum values above
    # The user should update FlowGraphMethod in IterativeExpansion.py to include:
    #   PyMaxflowBoykovKolmogorov = 10
    #   PyMaxflowWithNodeSplitting = 11
    pass


# Convenience function for testing
def create_simple_test_graph() -> PyMaxFlowGraphData:
    """Create a simple test graph for debugging."""
    # Simple graph: source (node 1) -> intermediate (node 2) -> sink (node 3)
    # Node 1 has supply 10, Node 3 has demand 10
    node_id_mapping = {1: 0, 2: 1, 3: 2}
    reverse_mapping = {0: 1, 1: 2, 2: 3}

    edges = [
        (0, 1, 10, 0),  # 1 -> 2, capacity 10
        (1, 2, 10, 0),  # 2 -> 3, capacity 10
    ]

    terminal_edges = [
        (0, 10, 0),  # Node 1: source capacity 10 (supply)
        (2, 0, 10),  # Node 3: sink capacity 10 (demand)
    ]

    demands = {1: -10, 2: 0, 3: 10}

    return PyMaxFlowGraphData(
        num_nodes=3,
        edges=edges,
        terminal_edges=terminal_edges,
        node_id_mapping=node_id_mapping,
        reverse_node_mapping=reverse_mapping,
        demands=demands,
        neutral_sinks=set(),
        cumulative_demand=0,
        fake_nodes=set()
    )


if __name__ == "__main__":
    # Simple test
    test_data = create_simple_test_graph()
    computer = PyMaxFlowComputer()
    computer.log_debug = True
    flow_value, flow_dict = computer.compute_flow(test_data, FlowGraphMethod.PyMaxflowBoykovKolmogorov)
    print(f"Flow value: {flow_value}")
    print(f"Flow dict: {flow_dict}")
