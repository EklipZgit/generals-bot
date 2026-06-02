from __future__ import annotations

import dataclasses
import io
import os
import pathlib
import pickle
import random
import struct
import subprocess
import sys
import typing
from collections import defaultdict, deque
from typing import Callable, Any

import logbook
import numpy as np

from BehaviorAlgorithms.Flow.FlowDirectionFinderABC import FlowDirectionFinderABC
from BehaviorAlgorithms.Flow.FlowGraphModels import IslandFlowNode, IslandMaxFlowGraph, FlowGraphMethod
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.Flow.NxFlowGraphData import NxFlowGraphData
from BehaviorAlgorithms.Flow.TileIslandFlowRole import TileIslandFlowRole
from MapMatrix import MapMatrix
from Path import Path
from PerformanceTimer import PerformanceTimer
from base.client.tile import Tile

DEMAND_SATURATION_FROM_GENERAL_ONLY = False
DEBUG_OR_TOOLS_FAKE_NODE_ESCAPE_ARCS = True
DEBUG_OR_TOOLS_FAKE_NODE_ESCAPE_COST = 1000000
_ORTOOLS_SIDECAR_ENV_VAR = 'GENERALS_BOT_ORTOOLS_SIDECAR_PYTHON'


class OrToolsSidecarError(Exception):
    pass


# OR-Tools SimpleMinCostFlow.Status enum values. These are stable across the OR-Tools
# versions we support; verified at runtime against smcf.OPTIMAL when solving in-process.
_ORTOOLS_STATUS_NAMES: typing.Dict[int, str] = {
    0: 'NOT_SOLVED',
    1: 'OPTIMAL',
    2: 'FEASIBLE',
    3: 'INFEASIBLE',
    4: 'UNBALANCED',
    5: 'BAD_RESULT',
    6: 'BAD_COST_RANGE',
}


class OrToolsSolveError(Exception):
    """
    Raised when SimpleMinCostFlow.solve() returns any status other than OPTIMAL.

    Combats: UnitTests/test_FlowExpansion.FlowExpansionUnitTests.test_should_not_fail_to_find_flow_expansion_routes__what_the_fuck
    Previously compute_flow swallowed every non-optimal status (e.g. status=3 INFEASIBLE
    caused by unreachable demand islands) and silently returned an empty flow dict, which
    made the whole flow expansion produce zero inter-island flow with no error. Interpreting
    the status is the solver client's job, not the caller's, so any failure status is now
    surfaced as an explicit exception carrying the decoded status name.
    """

    def __init__(self, status: int):
        self.status: int = status
        self.status_name: str = _ORTOOLS_STATUS_NAMES.get(status, f'UNKNOWN_{status}')
        super().__init__(
            f'OR-Tools SimpleMinCostFlow returned non-optimal status {status} ({self.status_name}). '
            f'The min-cost-flow graph is not solvable as built — typically INFEASIBLE due to '
            f'unreachable demand islands, or UNBALANCED supplies.'
        )


@dataclasses.dataclass(slots=True)
class OrToolsSolveResult:
    """Typed result of a successful (OPTIMAL) SimpleMinCostFlow solve.

    flows[i] is the flow on the i-th arc (parallel to the graph_data arc arrays).
    """

    flows: typing.List[int]
    optimal_cost: int


@dataclasses.dataclass(slots=True)
class FlowPathIslandConstraints:
    constrained_source_island_ids: typing.Set[int]
    allowed_destination_island_ids_by_source_id: typing.Dict[int, typing.Set[int]]


def _build_solve_result_or_raise(
    status: int,
    optimal_status: int,
    flows: typing.List[int],
    optimal_cost: int | None,
) -> OrToolsSolveResult:
    """
    Convert raw OR-Tools solve output (shared by the in-process client and the serialized
    sidecar response) into a typed OrToolsSolveResult, raising OrToolsSolveError for any
    non-optimal status instead of returning a sentinel/empty result.
    """
    if status != optimal_status:
        raise OrToolsSolveError(status)
    return OrToolsSolveResult(flows=[int(value) for value in flows], optimal_cost=int(optimal_cost))


class OrToolsSidecarClient(object):
    _instance: OrToolsSidecarClient | None = None

    def __init__(self):
        self._process: subprocess.Popen[bytes] | None = None
        self._repo_root = pathlib.Path(__file__).resolve().parents[2]
        self._sidecar_script = self._repo_root / 'BehaviorAlgorithms' / 'Flow' / 'OrToolsMinCostFlowSidecar.py'

    @classmethod
    def get_instance(cls) -> OrToolsSidecarClient:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def solve(self, graph_data: OrToolsGraphData) -> OrToolsSolveResult:
        self._ensure_process_started()
        request = {
            'command': 'solve',
            'start_nodes': graph_data.start_nodes.tolist(),
            'end_nodes': graph_data.end_nodes.tolist(),
            'capacities': graph_data.capacities.tolist(),
            'unit_costs': graph_data.unit_costs.tolist(),
            'node_supplies': graph_data.node_supplies.tolist(),
        }
        self._write_message(request)
        response = self._read_message()
        if response is None:
            raise OrToolsSidecarError('OR-Tools sidecar exited before sending a response')
        error = response.get('error')
        if error:
            raise OrToolsSidecarError(error)
        # The sidecar wire format is a dict (a serialization boundary); decode it into the
        # same typed result/exception contract as the in-process client so compute_flow is
        # agnostic to which backend ran.
        return _build_solve_result_or_raise(
            int(response['status']),
            int(response['optimal_status']),
            response['flows'],
            response['optimal_cost'],
        )

    def _ensure_process_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        python_path = self._resolve_sidecar_python_path()
        if not self._sidecar_script.exists():
            raise OrToolsSidecarError(f'Unable to find OR-Tools sidecar script at {self._sidecar_script}')

        stderr_target = self._get_popen_stream_or_default(sys.stderr)
        self._process = subprocess.Popen(
            [python_path, str(self._sidecar_script)],
            cwd=str(self._repo_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_target,
        )

    @staticmethod
    def _get_popen_stream_or_default(stream: typing.Any) -> typing.Any:
        if stream is None:
            return None
        fileno = getattr(stream, 'fileno', None)
        if fileno is None:
            return None
        try:
            fileno()
        except (io.UnsupportedOperation, OSError, ValueError):
            return None
        return stream

    def _get_run_config_value(self, *keys: str) -> str | None:
        config_path = self._repo_root.parent / 'run_config.txt'
        if not config_path.exists():
            return None
        for raw_line in config_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            normalized_key = key.strip()
            if normalized_key in keys:
                resolved = value.strip()
                if resolved:
                    return resolved
        return None

    def is_using_pypy(self) -> bool:
        configured = self._get_run_config_value('using_pypy', 'USING_PYPY')
        if configured is None:
            return False
        return configured.lower() in ('1', 'true', 'yes', 'on')

    def _resolve_sidecar_python_path(self) -> str:
        env_override = os.environ.get(_ORTOOLS_SIDECAR_ENV_VAR)
        if env_override:
            return env_override

        configured_python = self._get_run_config_value('current_gen_python_path', 'cpython_path', 'legacy_python_path')
        if configured_python is not None:
            return configured_python

        return 'python'

    def _write_message(self, obj: dict) -> None:
        if self._process is None or self._process.stdin is None:
            raise OrToolsSidecarError('OR-Tools sidecar stdin is unavailable')
        payload = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        self._process.stdin.write(struct.pack('<I', len(payload)))
        self._process.stdin.write(payload)
        self._process.stdin.flush()

    def _read_message(self) -> dict | None:
        if self._process is None or self._process.stdout is None:
            raise OrToolsSidecarError('OR-Tools sidecar stdout is unavailable')
        header = self._process.stdout.read(4)
        if not header:
            return None
        if len(header) != 4:
            raise OrToolsSidecarError('Incomplete OR-Tools sidecar response header')
        (size,) = struct.unpack('<I', header)
        payload = bytearray()
        while len(payload) < size:
            chunk = self._process.stdout.read(size - len(payload))
            if not chunk:
                raise OrToolsSidecarError('Unexpected EOF while reading OR-Tools sidecar response payload')
            payload.extend(chunk)
        return pickle.loads(payload)


class InProcOrToolsClient(object):
    _instance: InProcOrToolsClient | None = None

    def __init__(self):
        self._min_cost_flow_module = None

    @classmethod
    def get_instance(cls) -> InProcOrToolsClient:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def solve(self, graph_data: OrToolsGraphData) -> OrToolsSolveResult:
        min_cost_flow = self._get_min_cost_flow_module()
        smcf = min_cost_flow.SimpleMinCostFlow()
        all_arcs = smcf.add_arcs_with_capacity_and_unit_cost(
            graph_data.start_nodes,
            graph_data.end_nodes,
            graph_data.capacities,
            graph_data.unit_costs,
        )
        smcf.set_nodes_supplies(np.arange(len(graph_data.node_supplies), dtype=np.int64), graph_data.node_supplies)
        status = int(smcf.solve())
        optimal_status = int(smcf.OPTIMAL)
        # Interpret the status here so callers never have to guess what an empty result means;
        # any non-optimal status (INFEASIBLE/UNBALANCED/etc) raises explicitly.
        if status != optimal_status:
            raise OrToolsSolveError(status)
        return OrToolsSolveResult(
            flows=[int(value) for value in smcf.flows(all_arcs)],
            optimal_cost=int(smcf.optimal_cost()),
        )

    def _get_min_cost_flow_module(self):
        if self._min_cost_flow_module is None:
            from ortools.graph.python import min_cost_flow

            self._min_cost_flow_module = min_cost_flow
        return self._min_cost_flow_module

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
        disconnected_component_island_ids: typing.Set[int] | None = None,
        directed_repair_source_island_ids: typing.Set[int] | None = None,
        directed_repair_sink_island_ids: typing.Set[int] | None = None,
        overflow_dump_target_island_ids: typing.Set[int] | None = None,
        debug_fake_escape_arc_indexes: typing.Set[int] | None = None,
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
        self.disconnected_component_island_ids: typing.Set[int] = (
            disconnected_component_island_ids if disconnected_component_island_ids is not None else set()
        )
        """Island unique_ids that were in a graph component disconnected from the enemy general
        and had to be bridged to a fake flow node to keep the min-cost-flow feasible. See the
        Phase 3.5 connectivity repair in DirectOrToolsGraphBuilder.build()."""
        self.directed_repair_source_island_ids: typing.Set[int] = (
            directed_repair_source_island_ids if directed_repair_source_island_ids is not None else set()
        )
        """Island unique_ids that were supply nodes unable to reach any sink due to one-way borders,
        repaired by draining to the fake node. See Phase 3.6 directed reachability repair."""
        self.directed_repair_sink_island_ids: typing.Set[int] = (
            directed_repair_sink_island_ids if directed_repair_sink_island_ids is not None else set()
        )
        """Island unique_ids that were sink nodes unreachable from any source due to one-way borders,
        repaired by injecting from the fake node. See Phase 3.6 directed reachability repair."""
        self.overflow_dump_target_island_ids: typing.Set[int] = (
            overflow_dump_target_island_ids if overflow_dump_target_island_ids is not None else set()
        )
        """Island unique_ids that receive overflow dump arcs from the fake node to guarantee feasibility
        when demand-saturation arcs are saturated. See Phase 3.4 overflow dump."""
        self.debug_fake_escape_arc_indexes: typing.Set[int] = (
            debug_fake_escape_arc_indexes if debug_fake_escape_arc_indexes is not None else set()
        )
        self.debug_fake_escape_usage_by_island: typing.Dict[int, int] = {}


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

    def _build_flow_path_island_constraints(
        self,
        islands: 'TileIslandBuilder',
        constrained_flow_paths: typing.List[Path] | None,
    ) -> FlowPathIslandConstraints:
        constraints = FlowPathIslandConstraints(set(), {})
        if not constrained_flow_paths:
            return constraints

        for path in constrained_flow_paths:
            for move in path.get_move_list():
                source_island = islands.tile_island_lookup.raw[move.source.tile_index]
                destination_island = islands.tile_island_lookup.raw[move.dest.tile_index]
                if source_island is None or destination_island is None:
                    continue
                source_island_id = source_island.unique_id
                constraints.constrained_source_island_ids.add(source_island_id)
                if source_island_id == destination_island.unique_id:
                    continue
                allowed_destinations = constraints.allowed_destination_island_ids_by_source_id.get(source_island_id)
                if allowed_destinations is None:
                    allowed_destinations = set()
                    constraints.allowed_destination_island_ids_by_source_id[source_island_id] = allowed_destinations
                allowed_destinations.add(destination_island.unique_id)

        return constraints

    def _is_border_edge_blocked_by_flow_path_constraints(
        self,
        source_island: 'TileIsland',
        destination_island: 'TileIsland',
        constraints: FlowPathIslandConstraints,
    ) -> bool:
        if source_island.unique_id not in constraints.constrained_source_island_ids:
            return False
        allowed_destinations = constraints.allowed_destination_island_ids_by_source_id.get(source_island.unique_id)
        if allowed_destinations is None:
            return True
        return destination_island.unique_id not in allowed_destinations

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
        threat_blocking_tiles: typing.Dict['Tile', typing.Any] | None,
        constrained_flow_paths: typing.List[Path] | None,
        perf_timer: 'PerformanceTimer',
    ) -> OrToolsGraphData:
        """
        Build OrToolsGraphData equivalent to what NxFlowDirectionFinder.build_graph_data
        followed by NxToOrToolsConverter.convert would produce.
        """

        target_general_island = islands.tile_island_lookup.raw[enemy_general.tile_index]
        fr_general_island = islands.tile_island_lookup.raw[friendly_general.tile_index]
        flow_path_constraints = self._build_flow_path_island_constraints(islands, constrained_flow_paths)

        # Exclude islands that are not reachable on the map from ALL supply/demand and arc
        # construction. Combats: UnitTests/test_FlowExpansion.FlowExpansionUnitTests.test_should_not_fail_to_find_flow_expansion_routes__what_the_fuck
        # Unreachable demand islands (e.g. fogged enemy land disconnected from our territory)
        # were being fed into the demands, leaving an isolated component with non-zero net
        # supply, which made the whole min-cost-flow INFEASIBLE (status=3) and silently
        # produced zero inter-island flow. The map already knows what is reachable, so we
        # simply test a sample tile (highest-army tile) of each island against reachable_tiles.
        excluded_island_ids: typing.Set[int] = set()
        excluded_sample_tiles: typing.List['Tile'] = []
        for island in islands.all_tile_islands:
            sample_tile = island.tiles_by_army[0]
            if sample_tile not in map_obj.reachable_tiles:
                excluded_island_ids.add(island.unique_id)
                excluded_sample_tiles.append(sample_tile)
        if excluded_sample_tiles:
            # This should be extremely rare; log the problematic sample tiles on one line.
            logbook.info(
                f'FLOW_EXCLUDED_UNREACHABLE_ISLANDS count={len(excluded_sample_tiles)} '
                f'sampleTiles=[{", ".join(str(t) for t in excluded_sample_tiles)}]'
            )

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
                # Unreachable islands contribute no node, no supply/demand, and no split edge.
                # See excluded_island_ids comment above (the __what_the_fuck test).
                if island.unique_id in excluded_island_ids:
                    continue
                island_army_sum = _get_island_army_sum(island)
                cost = island.tile_count # - 1
                demand = island.tile_count - island_army_sum
                has_nx_demand_attr = False
                if island.team == team:
                    has_nx_demand_attr = True
                    cumulative_demand += demand
                    friendly_army_supply += island_army_sum - island.tile_count
                    # if island.tiles_by_army[0].army == 1:
                    #     # Don't ask me why but 300 works well while like 3 does not.  See test_should_not_waste_a_bunch_of_moves_moving_from_general, which makes suboptimal moves at += 3 but plays great at += 300
                    #     cost += 30
                    cost = max(2, 30 - island.sum_army // island.tile_count)
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

                # hack
                cost = 0


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

        # Tests/test_ArmyTracker.py ArmyTrackerTests.test_should_not_create_phantom_visible_army:
        # Diagnose persistent INFEASIBLE status after fog-land builder fix. Log per-team supply/demand
        # breakdown to identify if there are no enemy demand nodes or other imbalances.
        friendly_demand_islands = []
        enemy_demand_islands = []
        neutral_demand_islands = []
        for island in islands.all_tile_islands:
            if island.unique_id in excluded_island_ids:
                continue
            if island.unique_id in demands:
                demand = demands[island.unique_id]
                if island.team == team:
                    friendly_demand_islands.append((island.unique_id, demand, island.tile_count, island.sum_army))
                elif island.team == target_team:
                    enemy_demand_islands.append((island.unique_id, demand, island.tile_count, island.sum_army))
                elif island.team == -1:
                    neutral_demand_islands.append((island.unique_id, demand, island.tile_count, island.sum_army))
        logbook.warning(
            f'FLOW_INFEASIBLE_TEAM_BREAKDOWN team={team} target_team={target_team} '
            f'friendly_demand_count={len(friendly_demand_islands)} friendly_demand_sum={sum(d for _, d, _, _ in friendly_demand_islands)} '
            f'friendly_army_supply={friendly_army_supply} '
            f'enemy_demand_count={len(enemy_demand_islands)} enemy_demand_sum={enemy_army_demand} '
            f'neutral_demand_count={len(neutral_demand_islands)} neutral_demand_sum={sum(d for _, d, _, _ in neutral_demand_islands)} '
            f'cumulative_demand={cumulative_demand}'
        )

        # ----------------------------------------------------------------
        # Phase 2: border edges and neutral sinks (mirrors build_graph_data)
        # ----------------------------------------------------------------
        with perf_timer.begin_move_event('OrTools build phase2 border edges'):
            neut_sinks: typing.Set[int] = set()
            for island in islands.all_tile_islands:
                # Skip unreachable islands entirely so we never create a border edge that
                # references a node that phase 1 did not add (the __what_the_fuck test).
                if island.unique_id in excluded_island_ids:
                    continue
                role = island_roles[island.unique_id]

                for movable_island in island.border_islands:
                    # Never create an edge into an unreachable neighbour island.
                    if movable_island.unique_id in excluded_island_ids:
                        continue
                    if self._is_border_edge_blocked_by_threat_blocking_tiles(island, movable_island, threat_blocking_tiles):
                        logbook.warning(
                            f'FLOW_THREAT_BLOCKED_BORDER_EDGE removedDirectedArc=-{island.unique_id}->{movable_island.unique_id} '
                            f'sourceIsland={island.unique_id}(tile={island.tiles_by_army[0]},team={island.team},'
                            f'army={island.sum_army},tiles={island.tile_count}) '
                            f'destinationIsland={movable_island.unique_id}(tile={movable_island.tiles_by_army[0]},'
                            f'team={movable_island.team},army={movable_island.sum_army},tiles={movable_island.tile_count})'
                        )
                        continue
                    # UnitTests/FlowExpansionSubtests/test_FlowExpansion_ExternalOptions.py
                    # ExternalOptionsTests.test_constrained_flow_paths_limit_only_outgoing_edges_from_path_islands:
                    # path-constrained islands must only emit flow along island transitions explicitly present
                    # in the supplied Path objects, while other islands may still emit edges into them.
                    if self._is_border_edge_blocked_by_flow_path_constraints(island, movable_island, flow_path_constraints):
                        if self.log_debug:
                            logbook.info(
                                f'FLOW_PATH_CONSTRAINT_BLOCKED_BORDER_EDGE removedDirectedArc=-{island.unique_id}->{movable_island.unique_id} '
                                f'sourceIsland={island.unique_id} destinationIsland={movable_island.unique_id}'
                            )
                        continue
                    # Edge: output port → neighbour input port (weight=1, capacity=100000)
                    src = -island.unique_id
                    dst = movable_island.unique_id
                    arc_starts.append(src)
                    arc_ends.append(dst)
                    arc_caps.append(100000)
                    cost = 30
                    if island.team == team:
                        # FROM FRIENDLY ISLAND
                        if movable_island.team == target_team:
                            # ALWAYS prefer to flow into enemy land from friendly land directly. This is our most time effective movement strategy.
                            # TODO we want to AVOID large enemy armies when on their land, but we DONT want to avoid them when they're on our land. Need to be intelligent about that then.
                            # TODO keep in sync with other paths below
                            cost = movable_island.sum_army / movable_island.tile_count
                        elif movable_island.team == team:
                            # TODO this is actually not ideal, we'd prefer going to neutral and merging back into friendly land when necessary (as it gives us more immediate short neut capture options to play with)
                            #  But currently we are unable to merge multiple border pair streams back into one gather path, so the 'merged in' path where we go neutral -> friendly land will never get used and kind
                            #  of just dead ends as a one-or-the-other group choice instead of trying to use the combined army from merging paths to capture.
                            #  Revisit later with some approach that recognizes the option to merge streams AFTER the border pair point kind like how we do the merge / collapse grouping logic for gather-through tile options or something idk.
                            #  THEN we can make this more expensive again so we prefer neut caps first over merging streams.
                            cost = 100 // max(1, movable_island.sum_army / movable_island.tile_count)
                            # 100 army = 1 cost
                            # 50 army = 2 cost
                            # 8 army = 12 cost
                            # 5 army = 20 cost
                            # 3 army = 33 cost
                            # 2 army = 50 cost
                            # 1 army = 100 cost
                            # 0 army = 100 cost
                            # NOTE the graduated costs are necessary to avoid merging streams by like, travelling through 2's before joining later, rather than joining the high value stream immediately (caused gathers to lose tiles without this)

                        elif movable_island.team == -1:
                            cost += 0
                    elif island.team == -1:
                        # FROM NEUTRAL ISLAND
                        if movable_island.team == team:
                            # moving back onto our own land should be penalized
                            cost += 2000 // max(1, movable_island.sum_army / movable_island.tile_count)
                        elif movable_island.team == target_team:
                            # low cost moving to enemy land, we want that
                            # cost = 20 // max(1, movable_island.sum_army / movable_island.tile_count)
                            cost = movable_island.sum_army / movable_island.tile_count
                        elif movable_island.team == -1:
                            # normal cost neutral to neutral
                            cost += 0
                    elif island.team == target_team:
                        # FROM TARGET ISLAND
                        if movable_island.team == team:
                            # moving back onto our own land should be penalized
                            cost += 20000 // max(1, movable_island.sum_army / movable_island.tile_count)
                        elif movable_island.team == target_team:
                            # low cost moving to enemy land, we want that
                            cost = movable_island.sum_army / movable_island.tile_count
                        elif movable_island.team == -1:
                            # slight penalty moving to neutral from enemy land
                            cost += 10


                    # hack
                    # cost = 0

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
                            f'{island.unique_id}({island.tiles_by_army[0]} team={island.team},army={island.sum_army},tiles={island.tile_count}) '
                            f'-> {movable_island.unique_id}({movable_island.tiles_by_army[0]} team={movable_island.team},army={movable_island.sum_army},tiles={movable_island.tile_count}) '
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

            # Check if general islands have non-blocked border edges (needed for fake node to distribute flow)
            # UnitTests/test_FlowExpansion.FlowExpansionUnitTests.test_should_not_explode_infeasable
            target_general_border_count = len(target_general_island.border_islands)
            fr_general_border_count = len(fr_general_island.border_islands)
            target_general_unblocked_count = sum(
                1 for b in target_general_island.border_islands
                if not self._is_border_edge_blocked_by_threat_blocking_tiles(target_general_island, b, threat_blocking_tiles)
            )
            fr_general_unblocked_count = sum(
                1 for b in fr_general_island.border_islands
                if not self._is_border_edge_blocked_by_threat_blocking_tiles(fr_general_island, b, threat_blocking_tiles)
            )
            logbook.warning(
                f'FLOW_FAKE_NODE_GENERAL_EDGES target_general={target_general_island.unique_id} '
                f'border_count={target_general_border_count} unblocked={target_general_unblocked_count} '
                f'fr_general={fr_general_island.unique_id} border_count={fr_general_border_count} unblocked={fr_general_unblocked_count}'
            )

            # If friendly general has no unblocked edges, find closest friendly city with unblocked edges to use as fake sink
            # UnitTests/test_FlowExpansion.FlowExpansionUnitTests.test_should_not_explode_infeasable
            fr_fake_sink_island = fr_general_island
            if fr_general_unblocked_count == 0:
                logbook.warning(
                    f'FLOW_FAKE_NODE_SINK_FALLBACK fr_general={fr_general_island.unique_id} has no unblocked edges, '
                    f'searching for closest friendly city with unblocked edges...'
                )
                # Find all friendly cities with unblocked edges
                friendly_cities_with_edges = []
                for island in islands.all_tile_islands:
                    if island.unique_id in excluded_island_ids:
                        continue
                    if island.team == team and any(tile.isCity for tile in island.tile_set):
                        unblocked_count = sum(
                            1 for b in island.border_islands
                            if not self._is_border_edge_blocked_by_threat_blocking_tiles(island, b, threat_blocking_tiles)
                        )
                        if unblocked_count > 0:
                            # Calculate distance to friendly general
                            dist = min(
                                (tile.x - friendly_general.x) ** 2 + (tile.y - friendly_general.y) ** 2
                                for tile in island.tile_set
                            )
                            friendly_cities_with_edges.append((dist, island, unblocked_count))
                # Sort by distance and pick the closest
                if friendly_cities_with_edges:
                    friendly_cities_with_edges.sort(key=lambda x: x[0])
                    fr_fake_sink_island = friendly_cities_with_edges[0][1]
                    logbook.warning(
                        f'FLOW_FAKE_NODE_SINK_FALLBACK using closest friendly city {fr_fake_sink_island.unique_id} '
                        f'(dist={friendly_cities_with_edges[0][0]}, unblocked={friendly_cities_with_edges[0][2]}) '
                        f'instead of fr_general={fr_general_island.unique_id}'
                    )
                else:
                    # Fallback to closest-to-enemy-general tile in friendlyGeneral.movable with unblocked edges
                    # UnitTests/test_FlowExpansion.FlowExpansionUnitTests.test_should_not_explode_infeasable
                    logbook.warning(
                        f'FLOW_FAKE_NODE_SINK_FALLBACK no friendly cities with unblocked edges found, '
                        f'searching for closest-to-enemy-general tile in friendlyGeneral.movable with unblocked edges...'
                    )
                    movable_tiles_with_edges = []
                    for tile in friendly_general.movable:
                        tile_island = islands.tile_island_lookup.raw[tile.tile_index]
                        if tile_island is not None and tile_island.team == team and tile_island.unique_id not in excluded_island_ids:
                            unblocked_count = sum(
                                1 for b in tile_island.border_islands
                                if not self._is_border_edge_blocked_by_threat_blocking_tiles(tile_island, b, threat_blocking_tiles)
                                and b.unique_id != fr_general_island.unique_id  # Exclude edges back to fr_general
                            )
                            if unblocked_count > 0:
                                # Calculate distance to enemy general
                                dist = (tile.x - enemy_general.x) ** 2 + (tile.y - enemy_general.y) ** 2
                                movable_tiles_with_edges.append((dist, tile, tile_island, unblocked_count))
                    # Sort by distance to enemy general and pick the closest
                    if movable_tiles_with_edges:
                        movable_tiles_with_edges.sort(key=lambda x: x[0])
                        fr_fake_sink_island = movable_tiles_with_edges[0][2]
                        logbook.warning(
                            f'FLOW_FAKE_NODE_SINK_FALLBACK using closest-to-enemy-general tile {movable_tiles_with_edges[0][1]} '
                            f'in island {fr_fake_sink_island.unique_id} (dist_to_enemy={movable_tiles_with_edges[0][0]}, unblocked={movable_tiles_with_edges[0][3]}) '
                            f'instead of fr_general={fr_general_island.unique_id}'
                        )
                    else:
                        logbook.warning(
                            f'FLOW_FAKE_NODE_SINK_FALLBACK no movable tiles with unblocked edges found, '
                            f'falling back to fr_general={fr_general_island.unique_id} (will cause INFEASIBLE)'
                        )
            fake_node_excess_supply = max(0, cumulative_demand)
            fake_node_enemy_general_fallback_capacity: int
            friendly_pressure_capacities_by_island_id: typing.Dict[int, int]
            if DEMAND_SATURATION_FROM_GENERAL_ONLY:
                fake_node_enemy_general_fallback_capacity = (fake_node_excess_supply + 1) // 2
                friendly_pressure_capacities_by_island_id = {
                    fr_fake_sink_island.unique_id: fake_node_excess_supply - fake_node_enemy_general_fallback_capacity
                }
                logbook.warning(
                    f'FLOW_DEMAND_SATURATION mode=general_only fakeNode={fake_node} excess={fake_node_excess_supply} '
                    f'enemyGeneralIsland={target_general_island.unique_id} enemyCapacity={fake_node_enemy_general_fallback_capacity} '
                    f'friendlyFakeSinkIsland={fr_fake_sink_island.unique_id} friendlyCapacity={friendly_pressure_capacities_by_island_id[fr_fake_sink_island.unique_id]}'
                )
            else:
                fake_node_enemy_general_fallback_capacity = (fake_node_excess_supply * 35) // 100
                friendly_fallback_capacity = fake_node_excess_supply - fake_node_enemy_general_fallback_capacity
                pressure_islands_by_id: typing.Dict[int, 'TileIsland'] = {fr_fake_sink_island.unique_id: fr_fake_sink_island}
                pressure_tiles = sorted(
                    (
                        tile
                        for island in islands.all_tile_islands
                        if island.team == team
                        for tile in island.tile_set
                        if tile.army >= 6
                    ),
                    key=lambda candidate: (candidate.army, -candidate.tile_index),
                    reverse=True,
                )
                for pressure_tile in pressure_tiles:
                    if len(pressure_islands_by_id) >= 11:
                        break
                    pressure_island = islands.tile_island_lookup.raw[pressure_tile.tile_index]
                    if pressure_island is not None and pressure_island.unique_id not in excluded_island_ids:
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
            neut_sink_cost = 10 if use_neutral_flow else 0
            if use_neutral_flow:
                for neut_sink_id in neut_sinks:
                    isl = islands.tile_islands_by_unique_id[neut_sink_id]
                    capacity = 100000
                    arc_starts.append(fake_node)
                    arc_ends.append(neut_sink_id)
                    arc_caps.append(capacity)
                    arc_costs.append(neut_sink_cost)
                    all_node_ids.add(neut_sink_id)

            # Backpressure weight mirrors NX builder
            backpressure_weight = 0 if use_backpressure_from_enemy_general else 10000

            # -targetGeneralIsland.unique_id → fakeNode
            arc_starts.append(-target_general_island.unique_id)
            arc_ends.append(fake_node)
            arc_caps.append(100000)
            arc_costs.append(backpressure_weight)
            all_node_ids.add(-target_general_island.unique_id)

            # -frFakeSinkIsland.unique_id → fakeNode (use fallback city if fr_general has no unblocked edges)
            arc_starts.append(-fr_fake_sink_island.unique_id)
            arc_ends.append(fake_node)
            arc_caps.append(1000000)
            arc_costs.append(0)
            all_node_ids.add(-fr_fake_sink_island.unique_id)

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
                arc_costs.append(0)
                all_node_ids.add(friendly_pressure_island_id)

            # ---------------------------------------------------------------------------------
            # OVERFLOW DUMP arcs (guarantee feasibility).
            # ---------------------------------------------------------------------------------
            # The distributed demand-saturation arcs above have capacities that sum to EXACTLY the
            # fake node supply (fake_node_excess_supply), leaving zero routing slack. When the chosen
            # injection islands (enemy general + friendly pressure islands) cannot forward all of the
            # injected phantom army to reachable real demand, the min-cost-flow becomes INFEASIBLE
            # (proven by the FLOW_FEASIBILITY_BUG max-flow/min-cut diagnostic: the saturated min-cut
            # is exactly these fake-node arcs). The original NetworkXFlowDirectionFinder never hit this
            # because it injects all phantom supply through the enemy general AND friendly general with
            # capacity=1000000 (uncapped), giving the solver a high-capacity escape.
            #
            # We restore that escape WITHOUT discarding the distributed-pressure behaviour by adding
            # high-cost, high-capacity overflow arcs from the fake node into both the enemy general and
            # the friendly fake sink. Total fake out-capacity now exceeds its supply, so the solver is
            # never FORCED to saturate the cheap distributed arcs; it prefers them (cost 0 / backpressure)
            # and only routes the un-placeable remainder through these expensive overflow arcs, which
            # the central general / friendly-sink regions can forward to whatever demand is reachable.
            # OVERFLOW_DUMP_COST is higher than every other fake-node / bridge cost so overflow is a
            # genuine last resort and never perturbs the normal flow solution.
            OVERFLOW_DUMP_COST = 100000
            overflow_dump_capacity = 100000
            for overflow_target_island_id in (target_general_island.unique_id, fr_fake_sink_island.unique_id):
                arc_starts.append(fake_node)
                arc_ends.append(overflow_target_island_id)
                arc_caps.append(overflow_dump_capacity)
                arc_costs.append(OVERFLOW_DUMP_COST)
                all_node_ids.add(overflow_target_island_id)
            # Always-on log: records that the overflow-dump safety valve exists for this build so that
            # if it is ever exercised (or still insufficient) the FLOW_FEASIBILITY_BUG diagnostic below
            # can be correlated with it.
            logbook.warning(
                f'FLOW_OVERFLOW_DUMP fakeNode={fake_node} overflowCapacityEach={overflow_dump_capacity} '
                f'cost={OVERFLOW_DUMP_COST} enemyGeneralIsland={target_general_island.unique_id} '
                f'friendlyFakeSinkIsland={fr_fake_sink_island.unique_id}'
            )

            # Log total fake node arc capacity for debugging
            total_fake_node_capacity = fake_node_enemy_general_fallback_capacity + sum(friendly_pressure_capacities_by_island_id.values())
            logbook.warning(
                f'FLOW_DEMAND_SATURATION_SUMMARY fakeNode={fake_node} cumulative_demand={cumulative_demand} '
                f'excess_supply={fake_node_excess_supply} total_fake_node_capacity={total_fake_node_capacity} '
            )

        # Track overflow dump targets for rendering (only set when cumulative_demand > 0)
        overflow_dump_target_island_ids: typing.Set[int] = set()
        if cumulative_demand > 0:
            overflow_dump_target_island_ids = {target_general_island.unique_id, fr_fake_sink_island.unique_id}

        # Track directed repair islands for rendering (initialized before phase 3.6)
        directed_repair_source_island_ids: typing.Set[int] = set()
        directed_repair_sink_island_ids: typing.Set[int] = set()

        # ----------------------------------------------------------------
        # Phase 3.5: connectivity repair (GUARANTEES FEASIBILITY)
        # ----------------------------------------------------------------
        # A min-cost-flow with globally balanced supply is still INFEASIBLE when the arc
        # graph splits into >=2 weakly connected components and some component has non-zero
        # net supply: that component cannot route its supply/demand to the rest of the graph
        # (the single main fakeNode supply = cumulative_demand counts ALL included islands,
        # but only the main component can reach the fakeNode). This is the root cause of every
        # OrToolsSolveError INFEASIBLE we have seen (e.g. fogged enemy/neutral land cut off
        # from our territory after threat_blocking_tiles removed border edges).
        #
        # Fix: after ALL edges are built (split + border + fakeNode arcs, with threat-blocked
        # edges already excluded), do an undirected BFS for connected components seeded from
        # the enemy general's component (the "main graph"). Every OTHER component gets bridged
        # to the main fakeNode through an ADDITIONAL fake flow node attached to one arbitrary
        # island in that component. Because every island has a +id->-id split and borders are
        # symmetric, a single bridge per component is enough for any supply in it to route to
        # the global balancing fakeNode, so the whole graph becomes one connected, balanced,
        # feasible component. The bridge arcs use a high cost so the solver only routes through
        # them when forced to (for feasibility), never preferentially over real expansion paths,
        # and the bridge/comp-fake nodes are tracked in fake_nodes so they never appear as real
        # island-to-island flow edges.
        #
        # The arbitrary island per disconnected component is chosen deterministically as the
        # island whose highest-army tile (tiles_by_army[0]) has the smallest
        # intergeneral_analysis.aMap distance value, so the choice is stable across rebuilds.
        all_fake_node_ids: typing.Set[int] = {fake_node}
        disconnected_component_island_ids: typing.Set[int] = set()
        with perf_timer.begin_move_event('OrTools build phase3.5 connectivity repair'):
            # Build the connectivity adjacency from REAL island arcs ONLY (split edges +id->-id
            # and border edges -A->+B). We MUST exclude the fakeNode arcs here: the single main
            # fakeNode connects the enemy general island, the friendly fake sink, and scattered
            # pressure islands all together, which would falsely merge genuinely separate
            # territory regions into one component and hide the real disconnections that cause
            # INFEASIBLE. Restricting to real island nodes gives the true land-connectivity graph.
            adjacency: typing.Dict[int, typing.List[int]] = defaultdict(list)
            for arc_idx in range(len(arc_starts)):
                start_node = arc_starts[arc_idx]
                end_node = arc_ends[arc_idx]
                if abs(start_node) not in islands.tile_islands_by_unique_id:
                    continue
                if abs(end_node) not in islands.tile_islands_by_unique_id:
                    continue
                adjacency[start_node].append(end_node)
                adjacency[end_node].append(start_node)

            visited: typing.Set[int] = set()

            def _bfs_component(seed: int) -> typing.List[int]:
                """Undirected BFS collecting every node reachable from seed (excluding already-visited)."""
                if seed in visited:
                    return []
                component: typing.List[int] = []
                queue: typing.Deque[int] = deque((seed,))
                visited.add(seed)
                while queue:
                    node = queue.popleft()
                    component.append(node)
                    for neighbour in adjacency[node]:
                        if neighbour not in visited:
                            visited.add(neighbour)
                            queue.append(neighbour)
                return component

            # Seed the "main graph" from the enemy general island, then walk every other island
            # looking for components disconnected from it. Timed separately so the BFS connectivity
            # loop cost is visible in the perf logs (it runs on every flow graph build).
            aMap = intergeneral_analysis.aMap
            with perf_timer.begin_move_event('OrTools build phase3.5 BFS connectivity loop'):
                # The main fakeNode connects to the enemy general (and friendly fake sink / pressure
                # islands), so the whole main graph is captured by this single seed BFS.
                _bfs_component(target_general_island.unique_id)

                for island in islands.all_tile_islands:
                    if island.unique_id in excluded_island_ids:
                        continue
                    if island.unique_id in visited:
                        continue
                    # This island is in a component disconnected from the enemy general's main graph.
                    # Collect the whole component, then bridge it to the main fakeNode.
                    component_nodes = _bfs_component(island.unique_id)
                    component_island_ids = [
                        node_id for node_id in component_nodes
                        if node_id > 0 and node_id in islands.tile_islands_by_unique_id
                    ]
                    if not component_island_ids:
                        # Component had no real islands (only output ports / fake nodes); nothing to bridge.
                        continue
                    chosen_island = min(
                        (islands.tile_islands_by_unique_id[node_id] for node_id in component_island_ids),
                        key=lambda isl: aMap.raw[isl.tiles_by_army[0].tile_index],
                    )

                    comp_fake_node = random.randint(1000000, 9000000)
                    while comp_fake_node in all_node_ids or comp_fake_node in islands.tile_islands_by_unique_id:
                        comp_fake_node = random.randint(1000000, 9000000)

                    # Bridge arcs (high cost so they are only used when required for feasibility):
                    #   comp_fake -> +chosen_island   : inject supply into the disconnected component
                    #   -chosen_island -> comp_fake    : drain supply out of the disconnected component
                    #   comp_fake <-> main fakeNode    : connect the component to the global balancing node
                    bridge_arcs = (
                        (comp_fake_node, chosen_island.unique_id),
                        (-chosen_island.unique_id, comp_fake_node),
                        (comp_fake_node, fake_node),
                        (fake_node, comp_fake_node),
                    )
                    for bridge_start, bridge_end in bridge_arcs:
                        arc_starts.append(bridge_start)
                        arc_ends.append(bridge_end)
                        arc_caps.append(100000)
                        arc_costs.append(10000)
                        all_node_ids.add(bridge_start)
                        all_node_ids.add(bridge_end)

                    node_supply_map[comp_fake_node] = 0
                    all_node_ids.add(comp_fake_node)
                    all_fake_node_ids.add(comp_fake_node)
                    disconnected_component_island_ids.add(chosen_island.unique_id)

                    component_net_supply = sum(node_supply_map.get(node_id, 0) for node_id in component_nodes)
                    # Always-on log: a disconnected component had to be bridged to keep the flow feasible.
                    logbook.warning(
                        f'FLOW_CONNECTIVITY_REPAIR disconnected component bridged: compFakeNode={comp_fake_node} '
                        f'islandCount={len(component_island_ids)} netSupply={component_net_supply} '
                        f'chosenIsland={chosen_island.unique_id}(team={chosen_island.team},'
                        f'tile={chosen_island.tiles_by_army[0]},aDist={aMap.raw[chosen_island.tiles_by_army[0].tile_index]})'
                    )

        # ----------------------------------------------------------------
        # Phase 3.6: post-repair feasibility verification diagnostic.
        # ----------------------------------------------------------------
        # Every flow expansion attempt is ALWAYS feasible by construction; any INFEASIBLE result
        # is a BUG in this graph setup. After the connectivity repair, the graph MUST be globally
        # balanced (sum of all node supplies == 0) AND every weakly connected component (over ALL
        # arcs, including the fakeNode + bridge arcs) MUST have net supply 0 -- otherwise the
        # min-cost-flow will be INFEASIBLE. This block recomputes weak components over the FULL
        # arc set and logs any component whose net supply is non-zero so the root cause is visible.
        with perf_timer.begin_move_event('OrTools build phase3.6 feasibility verification'):
            full_parent: typing.Dict[int, int] = {}

            def _full_find(node_id: int) -> int:
                root = node_id
                while full_parent.get(root, root) != root:
                    root = full_parent.get(root, root)
                while full_parent.get(node_id, node_id) != root:
                    nxt = full_parent.get(node_id, node_id)
                    full_parent[node_id] = root
                    node_id = nxt
                return root

            def _full_union(node_a: int, node_b: int) -> None:
                root_a = _full_find(node_a)
                root_b = _full_find(node_b)
                if root_a != root_b:
                    full_parent[root_b] = root_a

            for arc_idx in range(len(arc_starts)):
                _full_union(arc_starts[arc_idx], arc_ends[arc_idx])

            full_comp_members: typing.Dict[int, typing.List[int]] = defaultdict(list)
            for node_id in all_node_ids:
                full_comp_members[_full_find(node_id)].append(node_id)

            global_net_supply = sum(node_supply_map.get(node_id, 0) for node_id in all_node_ids)
            if global_net_supply != 0:
                logbook.error(
                    f'FLOW_FEASIBILITY_BUG global net supply != 0 (globalNetSupply={global_net_supply}). '
                    f'The min-cost-flow graph is UNBALANCED and will be INFEASIBLE -- this is a graph-setup bug.'
                )
            for comp_root, member_nodes in full_comp_members.items():
                net_supply = sum(node_supply_map.get(node_id, 0) for node_id in member_nodes)
                if net_supply == 0:
                    continue
                supply_islands = []
                for node_id in member_nodes:
                    supply = node_supply_map.get(node_id, 0)
                    if node_id > 0 and supply != 0 and node_id in islands.tile_islands_by_unique_id:
                        isl = islands.tile_islands_by_unique_id[node_id]
                        supply_islands.append(f'{node_id}(t{isl.team},{isl.tiles_by_army[0]},or_supply={supply})')
                logbook.error(
                    f'FLOW_FEASIBILITY_BUG weak component with non-zero net supply remains after repair: '
                    f'root={comp_root} nodeCount={len(member_nodes)} netSupply={net_supply} '
                    f'containsMainFakeNode={fake_node in member_nodes} '
                    f'supplyIslands=[{", ".join(supply_islands[:48])}]'
                )

            # DIRECTED reachability check. A balanced, weakly-connected min-cost-flow is still
            # INFEASIBLE if some sink (supply<0) cannot be reached from ANY source (supply>0) along
            # DIRECTED arcs, or some source cannot reach ANY sink. This happens when threat-blocking
            # removed a border edge in only one direction (the block check is directional), leaving a
            # one-way border so flow physically cannot reach a demand island. Log every such node so
            # the directional graph-setup bug is visible.
            forward_adj: typing.Dict[int, typing.List[int]] = defaultdict(list)
            reverse_adj: typing.Dict[int, typing.List[int]] = defaultdict(list)
            for arc_idx in range(len(arc_starts)):
                forward_adj[arc_starts[arc_idx]].append(arc_ends[arc_idx])
                reverse_adj[arc_ends[arc_idx]].append(arc_starts[arc_idx])

            def _directed_reach(adjacency_map: typing.Dict[int, typing.List[int]], seeds: typing.Iterable[int]) -> typing.Set[int]:
                reached: typing.Set[int] = set()
                queue: typing.Deque[int] = deque()
                for seed in seeds:
                    if seed not in reached:
                        reached.add(seed)
                        queue.append(seed)
                while queue:
                    node = queue.popleft()
                    for neighbour in adjacency_map[node]:
                        if neighbour not in reached:
                            reached.add(neighbour)
                            queue.append(neighbour)
                return reached

            source_nodes = [node_id for node_id in all_node_ids if node_supply_map.get(node_id, 0) > 0]
            sink_nodes = [node_id for node_id in all_node_ids if node_supply_map.get(node_id, 0) < 0]
            with perf_timer.begin_move_event('OrTools build phase3.6 directed reachability BFS repair'):
                forward_reachable_from_sources = _directed_reach(forward_adj, source_nodes)
                backward_reachable_from_sinks = _directed_reach(reverse_adj, sink_nodes)
                real_forward_adj: typing.Dict[int, typing.List[int]] = defaultdict(list)
                real_reverse_adj: typing.Dict[int, typing.List[int]] = defaultdict(list)
                with perf_timer.begin_move_event('OrTools build phase3.6 real adjacency for SCC repair'):
                    for arc_idx in range(len(arc_starts)):
                        arc_start = arc_starts[arc_idx]
                        arc_end = arc_ends[arc_idx]
                        if abs(arc_start) in all_fake_node_ids or abs(arc_end) in all_fake_node_ids:
                            continue
                        real_forward_adj[arc_start].append(arc_end)
                        real_reverse_adj[arc_end].append(arc_start)
                    real_sink_nodes = [
                        sink_node for sink_node in sink_nodes
                        if abs(sink_node) not in all_fake_node_ids
                    ]
                    real_backward_reachable_from_sinks = _directed_reach(real_reverse_adj, real_sink_nodes)

                # DIRECTED reachability REPAIR. Flow expansion must ALWAYS be feasible, so we repair
                # rather than just diagnose. A balanced, weakly-connected graph is still INFEASIBLE if a
                # sink (supply<0) cannot be reached from ANY source along DIRECTED arcs, or a source
                # cannot reach ANY sink. This happens when threat-blocking removed a border edge in only
                # one direction (the block check is directional), leaving a one-way border that traps an
                # island's army. Repair: drain each trapped source's output to the fake node
                # (-source -> fakeNode) and let the fake node fill each trapped sink directly
                # (fakeNode -> +sink), at high cost so only the trapped army uses these arcs. The fake
                # node can always push into the enemy general (a sink) and is fed by the drains, so every
                # trapped source/sink becomes routable.
                DIRECTED_REPAIR_COST = 100000
                directed_repair_sources: typing.List[int] = []
                directed_repair_sinks: typing.List[int] = []
                scc_index_by_node: typing.Dict[int, int] = {}
                scc_lowlink_by_node: typing.Dict[int, int] = {}
                scc_stack: typing.List[int] = []
                scc_nodes_on_stack: typing.Set[int] = set()
                scc_components: typing.List[typing.List[int]] = []
                scc_next_index = 0

                def _strongconnect(node_id: int) -> None:
                    nonlocal scc_next_index
                    scc_index_by_node[node_id] = scc_next_index
                    scc_lowlink_by_node[node_id] = scc_next_index
                    scc_next_index += 1
                    scc_stack.append(node_id)
                    scc_nodes_on_stack.add(node_id)

                    for target_node_id in real_forward_adj[node_id]:
                        if target_node_id not in scc_index_by_node:
                            _strongconnect(target_node_id)
                            scc_lowlink_by_node[node_id] = min(
                                scc_lowlink_by_node[node_id],
                                scc_lowlink_by_node[target_node_id],
                            )
                        elif target_node_id in scc_nodes_on_stack:
                            scc_lowlink_by_node[node_id] = min(
                                scc_lowlink_by_node[node_id],
                                scc_index_by_node[target_node_id],
                            )

                    if scc_lowlink_by_node[node_id] != scc_index_by_node[node_id]:
                        return
                    component_nodes: typing.List[int] = []
                    while True:
                        stack_node_id = scc_stack.pop()
                        scc_nodes_on_stack.remove(stack_node_id)
                        component_nodes.append(stack_node_id)
                        if stack_node_id == node_id:
                            break
                    scc_components.append(component_nodes)

                with perf_timer.begin_move_event('OrTools build phase3.6 SCC terminal surplus repair'):
                    for node_id in real_forward_adj.keys() | real_reverse_adj.keys():
                        if node_id not in scc_index_by_node:
                            _strongconnect(node_id)

                    scc_id_by_node: typing.Dict[int, int] = {}
                    for scc_id, component_nodes in enumerate(scc_components):
                        for node_id in component_nodes:
                            scc_id_by_node[node_id] = scc_id
                    scc_has_outgoing_edge: typing.List[bool] = [False] * len(scc_components)
                    for source_node_id, target_node_ids in real_forward_adj.items():
                        source_scc_id = scc_id_by_node[source_node_id]
                        for target_node_id in target_node_ids:
                            if source_scc_id != scc_id_by_node[target_node_id]:
                                scc_has_outgoing_edge[source_scc_id] = True

                    for scc_id, component_nodes in enumerate(scc_components):
                        if scc_has_outgoing_edge[scc_id]:
                            continue
                        scc_net_supply = sum(node_supply_map.get(node_id, 0) for node_id in component_nodes)
                        if scc_net_supply <= 0:
                            continue
                        for source_node in component_nodes:
                            if node_supply_map.get(source_node, 0) <= 0:
                                continue
                            if source_node in all_fake_node_ids:
                                continue
                            if source_node not in islands.tile_islands_by_unique_id:
                                continue
                            # Tests/test_ArmyTracker.py
                            # ArmyTrackerTests.test_should_drop_crazy_broken_army and
                            # ArmyTrackerTests.test_should_not_capture_fog_island_neutral_then_invent_infinite_army:
                            # a closed real SCC with positive net supply cannot discharge all army through real
                            # arcs regardless of unlimited edge capacities. Detect that terminal surplus SCC in
                            # O(V+E) before solving and add a targeted high-cost drain only for its real sources.
                            arc_starts.append(source_node)
                            arc_ends.append(fake_node)
                            arc_caps.append(100000)
                            arc_costs.append(DIRECTED_REPAIR_COST)
                            directed_repair_sources.append(source_node)
                            directed_repair_source_island_ids.add(source_node)
                for source_node in source_nodes:
                    if source_node in all_fake_node_ids:
                        continue
                    if source_node in real_backward_reachable_from_sinks:
                        continue
                    # Tests/test_ArmyTracker.py
                    # ArmyTrackerTests.test_should_drop_crazy_broken_army and
                    # ArmyTrackerTests.test_should_not_capture_fog_island_neutral_then_invent_infinite_army:
                    # detect source islands whose supply cannot reach any real demand through real arcs
                    # before solving. This is a targeted O(V+E) directed reachability check, not an
                    # all-source fake-node escape hatch and not a post-solver retry.
                    arc_starts.append(source_node)
                    arc_ends.append(fake_node)
                    arc_caps.append(100000)
                    arc_costs.append(DIRECTED_REPAIR_COST)
                    directed_repair_sources.append(source_node)
                    directed_repair_source_island_ids.add(source_node)
                for sink_node in sink_nodes:
                    if sink_node in forward_reachable_from_sources:
                        continue
                    if sink_node in all_fake_node_ids:
                        continue
                    arc_starts.append(fake_node)
                    arc_ends.append(sink_node)
                    arc_caps.append(100000)
                    arc_costs.append(DIRECTED_REPAIR_COST)
                    all_node_ids.add(sink_node)
                    directed_repair_sinks.append(sink_node)
                    directed_repair_sink_island_ids.add(sink_node)
                for source_node in source_nodes:
                    if source_node in backward_reachable_from_sinks:
                        continue
                    if source_node in all_fake_node_ids:
                        continue
                    arc_starts.append(-source_node)
                    arc_ends.append(fake_node)
                    arc_caps.append(100000)
                    arc_costs.append(DIRECTED_REPAIR_COST)
                    all_node_ids.add(-source_node)
                    directed_repair_sources.append(source_node)
                if directed_repair_sources or directed_repair_sinks:
                    # Always-on log: directional one-way borders trapped some supply/demand and we
                    # bridged the trapped nodes to the fake node to keep the flow feasible.
                    logbook.warning(
                        f'FLOW_DIRECTED_REPAIR bridged directionally-trapped nodes to fakeNode={fake_node}: '
                        f'trappedSourceCount={len(directed_repair_sources)} trappedSinkCount={len(directed_repair_sinks)} '
                        f'trappedSources={directed_repair_sources[:48]} trappedSinks={directed_repair_sinks[:48]}'
                    )

            # Definitive feasibility check: a balanced, reachable graph can STILL be INFEASIBLE if a
            # finite-capacity cut cannot carry the required supply. Run a max-flow from a virtual
            # super-source (-> every supply node, cap=supply) to a virtual super-sink (every demand node
            # ->, cap=demand). If maxflow < total supply the graph is INFEASIBLE; we then log the min-cut
            # (super-source side) so the exact saturated bottleneck arcs/islands are visible. This is the
            # final verification that the connectivity/overflow/directed repairs above did their job.
            if global_net_supply == 0:
                super_source = -987654321
                super_sink = -987654322
                residual: typing.Dict[int, typing.Dict[int, int]] = defaultdict(dict)

                def _add_residual_arc(u: int, v: int, cap: int) -> None:
                    residual[u][v] = residual[u].get(v, 0) + cap
                    if u not in residual[v]:
                        residual[v][u] = residual[v].get(u, 0)

                def _bfs_augment() -> int:
                    parent: typing.Dict[int, int] = {super_source: super_source}
                    queue: typing.Deque[int] = deque((super_source,))
                    while queue:
                        node = queue.popleft()
                        if node == super_sink:
                            break
                        for neighbour, cap in residual[node].items():
                            if cap > 0 and neighbour not in parent:
                                parent[neighbour] = node
                                queue.append(neighbour)
                    if super_sink not in parent:
                        return 0
                    bottleneck = None
                    cursor = super_sink
                    while cursor != super_source:
                        prev = parent[cursor]
                        edge_cap = residual[prev][cursor]
                        bottleneck = edge_cap if bottleneck is None else min(bottleneck, edge_cap)
                        cursor = prev
                    cursor = super_sink
                    while cursor != super_source:
                        prev = parent[cursor]
                        residual[prev][cursor] -= bottleneck
                        residual[cursor][prev] = residual[cursor].get(prev, 0) + bottleneck
                        cursor = prev
                    return bottleneck

                # Timed separately: the max-flow augmenting BFS loop is the most expensive part of the
                # feasibility verification and runs on every flow graph build, so monitor its cost.
                with perf_timer.begin_move_event('OrTools build phase3.6 max-flow feasibility BFS loop'):
                    for arc_idx in range(len(arc_starts)):
                        _add_residual_arc(arc_starts[arc_idx], arc_ends[arc_idx], int(arc_caps[arc_idx]))
                    total_required_flow = 0
                    for node_id in all_node_ids:
                        supply = node_supply_map.get(node_id, 0)
                        if supply > 0:
                            _add_residual_arc(super_source, node_id, supply)
                            total_required_flow += supply
                        elif supply < 0:
                            _add_residual_arc(node_id, super_sink, -supply)

                    max_flow_value = 0
                    augment = _bfs_augment()
                    while augment > 0:
                        max_flow_value += augment
                        augment = _bfs_augment()

                if max_flow_value < total_required_flow:
                    # Min cut = nodes still reachable from super_source in the residual graph.
                    cut_reached: typing.Set[int] = set()
                    cut_queue: typing.Deque[int] = deque((super_source,))
                    cut_reached.add(super_source)
                    while cut_queue:
                        node = cut_queue.popleft()
                        for neighbour, cap in residual[node].items():
                            if cap > 0 and neighbour not in cut_reached:
                                cut_reached.add(neighbour)
                                cut_queue.append(neighbour)
                    saturated_cut_arcs = []
                    for arc_idx in range(len(arc_starts)):
                        u = arc_starts[arc_idx]
                        v = arc_ends[arc_idx]
                        if u in cut_reached and v not in cut_reached:
                            u_desc = u
                            v_desc = v
                            if abs(u) in islands.tile_islands_by_unique_id:
                                u_isl = islands.tile_islands_by_unique_id[abs(u)]
                                u_desc = f'{u}(t{u_isl.team},{u_isl.tiles_by_army[0]})'
                            if abs(v) in islands.tile_islands_by_unique_id:
                                v_isl = islands.tile_islands_by_unique_id[abs(v)]
                                v_desc = f'{v}(t{v_isl.team},{v_isl.tiles_by_army[0]})'
                            saturated_cut_arcs.append(f'{u_desc}->{v_desc}:cap{int(arc_caps[arc_idx])}')
                    cut_source_nodes = []
                    for node_id in cut_reached:
                        supply = node_supply_map.get(node_id, 0)
                        if supply <= 0:
                            continue
                        node_desc = str(node_id)
                        if node_id in islands.tile_islands_by_unique_id:
                            isl = islands.tile_islands_by_unique_id[node_id]
                            node_desc = f'{node_id}(t{isl.team},{isl.tiles_by_army[0]},supply={supply})'
                        cut_source_nodes.append(node_desc)
                    logbook.error(
                        f'FLOW_FEASIBILITY_BUG capacity cut cannot carry required supply: maxFlow={max_flow_value} '
                        f'requiredFlow={total_required_flow} deficit={total_required_flow - max_flow_value} '
                        f'cutSourceSideNodeCount={len(cut_reached)} mainFakeInCut={fake_node in cut_reached} '
                        f'cutSources=[{", ".join(cut_source_nodes[:48])}] '
                        f'saturatedCutArcs=[{", ".join(saturated_cut_arcs[:48])}]'
                    )

        # ----------------------------------------------------------------
        # Phase 4: build sorted node index arrays (mirrors NxToOrToolsConverter)
        # ----------------------------------------------------------------
        debug_fake_escape_arc_indexes: typing.Set[int] = set()
        if DEBUG_OR_TOOLS_FAKE_NODE_ESCAPE_ARCS:
            with perf_timer.begin_move_event('OrTools build debug fake escape arcs'):
                for node_id in list(all_node_ids):
                    if node_id == 0:
                        continue
                    if abs(node_id) in all_fake_node_ids:
                        continue
                    debug_fake_escape_arc_indexes.add(len(arc_starts))
                    arc_starts.append(node_id)
                    arc_ends.append(fake_node)
                    arc_caps.append(100000)
                    arc_costs.append(DEBUG_OR_TOOLS_FAKE_NODE_ESCAPE_COST)
                    debug_fake_escape_arc_indexes.add(len(arc_starts))
                    arc_starts.append(fake_node)
                    arc_ends.append(node_id)
                    arc_caps.append(100000)
                    arc_costs.append(DEBUG_OR_TOOLS_FAKE_NODE_ESCAPE_COST)
                logbook.warning(
                    f'FLOW_DEBUG_FAKE_ESCAPE_ENABLED fakeNode={fake_node} '
                    f'arcCount={len(debug_fake_escape_arc_indexes)} cost={DEBUG_OR_TOOLS_FAKE_NODE_ESCAPE_COST}'
                )

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

        # Always log when cumulative_demand is 0 to diagnose why real nodes get no flow
        if cumulative_demand == 0:
            # Log real island demands (from demands dict) and supplies (from node_supplies_arr)
            real_island_demands = [(nid, demand) for nid, demand in demands.items() if abs(nid) < 1000000 and demand != 0]
            friendly_supply_demands = [(nid, demand) for nid, demand in real_island_demands if demand < 0]
            enemy_demand_demands = [(nid, demand) for nid, demand in real_island_demands if demand > 0]
            real_island_supplies = [(node_list[i], int(node_supplies_arr[i])) for i in range(num_nodes) if abs(node_list[i]) < 1000000 and node_supplies_arr[i] != 0]
            logbook.warning(
                f'FLOW_DIAG_ZERO_CUMULATIVE_DEMAND_BUILD cumulative_demand=0. '
                f'NX demands (negative=supply, positive=demand): friendly={friendly_supply_demands[:32]} enemy={enemy_demand_demands[:32]} neutral={[(nid, d) for nid, d in real_island_demands if -1 < nid < 1000000 and nid not in [f for f, _ in friendly_supply_demands] and nid not in [e for e, _ in enemy_demand_demands]][:32]}. '
                f'OR-Tools supplies (converted from demands): {real_island_supplies[:32]}. '
                f'Total real arcs: {len(arc_starts)} (split edges + border edges)'
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
            fake_nodes=all_fake_node_ids,
            cumulative_demand=cumulative_demand,
            disconnected_component_island_ids=disconnected_component_island_ids,
            directed_repair_source_island_ids=directed_repair_source_island_ids,
            directed_repair_sink_island_ids=directed_repair_sink_island_ids,
            overflow_dump_target_island_ids=overflow_dump_target_island_ids,
            debug_fake_escape_arc_indexes=debug_fake_escape_arc_indexes,
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

    def _is_border_edge_blocked_by_threat_blocking_tiles(
        self,
        source_island: 'TileIsland',
        destination_island: 'TileIsland',
        threat_blocking_tiles: typing.Dict['Tile', typing.Any] | None,
    ) -> bool:
        if not threat_blocking_tiles:
            return False

        for source_tile in source_island.tile_set:
            block_info = threat_blocking_tiles.get(source_tile, None)
            if block_info is None:
                continue
            for blocked_destination in block_info.blocked_destinations:
                if blocked_destination in destination_island.tile_set:
                    return True

        return False

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
        self.sidecar_client: OrToolsSidecarClient = OrToolsSidecarClient.get_instance()
        self.inproc_client: InProcOrToolsClient = InProcOrToolsClient.get_instance()

    def _should_use_inproc_ortools(self) -> bool:
        return not self.sidecar_client.is_using_pypy()

    def compute_flow(
        self,
        islands: 'TileIslandBuilder',
        graph_data: OrToolsGraphData,
        method: FlowGraphMethod = FlowGraphMethod.OrToolsSimpleMinCost,
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        """
        Solve min-cost flow and return a flow dict matching the NX format.
        Raises OrToolsSolveError if the solver returns any non-optimal status (e.g. INFEASIBLE).
        """
        use_inproc = self._should_use_inproc_ortools()
        solve_scope_name = 'OrTools inproc.solve()' if use_inproc else 'OrTools sidecar.solve()'
        with self.perf_timer.begin_move_event(solve_scope_name):
            if use_inproc:
                solve_result = self.inproc_client.solve(graph_data)
            else:
                solve_result = self.sidecar_client.solve(graph_data)

        if self.log_debug:
            logbook.info(
                f'OrTools {"inproc" if use_inproc else "sidecar"}: {len(graph_data.node_ids)} nodes, {len(graph_data.start_nodes)} arcs, '
                f'cumulative_demand={graph_data.cumulative_demand}'
            )
            logbook.info(f'OrTools optimal_cost={solve_result.optimal_cost}')

        with self.perf_timer.begin_move_event('OrTools flow_dict builder post-solve'):
            flow_dict: typing.Dict[int, typing.Dict[int, int]] = defaultdict(lambda: defaultdict(int))
            fake_nodes = graph_data.fake_nodes
            idx_to_node = graph_data.idx_to_node
            flow_diag_islands = getattr(graph_data, 'flow_diag_island_ids', set())
            total_positive_flow = 0
            total_real_arc_flow = 0
            total_fake_arc_flow = 0
            total_fake_to_real_flow = 0
            total_real_to_fake_flow = 0
            total_root_output_real_flow = 0
            total_root_output_fake_flow = 0
            real_arc_count = 0
            fake_arc_count = 0
            root_output_real_arc_count = 0
            root_output_fake_arc_count = 0
            root_output_flow_by_island: dict[int, int] = defaultdict(int)
            root_output_fake_flow_by_island: dict[int, int] = defaultdict(int)
            root_input_supply_by_island: dict[int, int] = {}
            debug_fake_escape_usage_by_island: dict[int, int] = defaultdict(int)
            for island_id, demand in graph_data.demand_lookup.items():
                if demand < 0:
                    root_input_supply_by_island[island_id] = -demand

            solution_flows = solve_result.flows

            for arc_idx in range(len(solution_flows)):
                flow_amount = int(solution_flows[arc_idx])
                if flow_amount <= 0:
                    continue

                total_positive_flow += flow_amount

                from_orig = idx_to_node.get(int(graph_data.start_nodes[arc_idx]))
                to_orig = idx_to_node.get(int(graph_data.end_nodes[arc_idx]))

                if from_orig is None or to_orig is None:
                    continue

                from_is_fake = abs(from_orig) in fake_nodes
                to_is_fake = abs(to_orig) in fake_nodes
                is_fake_saturation_arc = from_is_fake or to_is_fake
                if arc_idx in graph_data.debug_fake_escape_arc_indexes:
                    if from_is_fake and not to_is_fake and to_orig > 0:
                        debug_fake_escape_usage_by_island[to_orig] += flow_amount
                    elif not from_is_fake and to_is_fake and from_orig > 0:
                        debug_fake_escape_usage_by_island[from_orig] -= flow_amount
                    elif not from_is_fake and to_is_fake and from_orig < 0:
                        debug_fake_escape_usage_by_island[-from_orig] -= flow_amount
                    elif from_is_fake and not to_is_fake and to_orig < 0:
                        debug_fake_escape_usage_by_island[-to_orig] += flow_amount

                if is_fake_saturation_arc:
                    fake_arc_count += 1
                    total_fake_arc_flow += flow_amount
                    if from_is_fake and not to_is_fake:
                        total_fake_to_real_flow += flow_amount
                    elif not from_is_fake and to_is_fake:
                        total_real_to_fake_flow += flow_amount
                else:
                    real_arc_count += 1
                    total_real_arc_flow += flow_amount

                if from_orig < 0 and not from_is_fake:
                    root_output_island_id = -from_orig
                    if to_is_fake:
                        root_output_fake_arc_count += 1
                        total_root_output_fake_flow += flow_amount
                        root_output_fake_flow_by_island[root_output_island_id] += flow_amount
                    else:
                        root_output_real_arc_count += 1
                        total_root_output_real_flow += flow_amount
                        root_output_flow_by_island[root_output_island_id] += flow_amount

                if self.log_debug and (from_is_fake or to_is_fake):
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
                if arc_idx in graph_data.debug_fake_escape_arc_indexes:
                    logbook.error(
                        f'FLOW_DEBUG_FAKE_ESCAPE_USED_ARC arc={arc_idx} {from_orig}->{to_orig} '
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
                logbook.warning(
                    f'FLOW_DIAG_SOLVE_SUMMARY totalPositiveFlow={total_positive_flow} '
                    f'realArcCount={real_arc_count} realArcFlow={total_real_arc_flow} '
                    f'fakeArcCount={fake_arc_count} fakeArcFlow={total_fake_arc_flow} '
                    f'fakeToRealFlow={total_fake_to_real_flow} realToFakeFlow={total_real_to_fake_flow} '
                    f'rootOutputRealArcCount={root_output_real_arc_count} rootOutputRealFlow={total_root_output_real_flow} '
                    f'rootOutputFakeArcCount={root_output_fake_arc_count} rootOutputFakeFlow={total_root_output_fake_flow} '
                    f'rootOutputRealByIsland={sorted(root_output_flow_by_island.items())[:32]} '
                    f'rootOutputFakeByIsland={sorted(root_output_fake_flow_by_island.items())[:32]}'
                )
                if total_positive_flow > 0 and total_root_output_real_flow == 0:
                    suspicious_root_supplies = sorted(root_input_supply_by_island.items(), key=lambda item: item[1], reverse=True)[:32]
                    logbook.warning(
                        f'FLOW_DIAG_BAD_ZERO_ROOT_REAL_FLOW totalPositiveFlow={total_positive_flow} '
                        f'totalFakeArcFlow={total_fake_arc_flow} totalRealArcFlow={total_real_arc_flow} '
                        f'rootInputSupplyByIsland={suspicious_root_supplies}'
                    )

            with self.perf_timer.begin_move_event('OrTools debug fake escape usage summarize'):
                graph_data.debug_fake_escape_usage_by_island = dict(debug_fake_escape_usage_by_island)
                if graph_data.debug_fake_escape_arc_indexes:
                    if graph_data.debug_fake_escape_usage_by_island:
                        debug_usage_descriptions: typing.List[str] = []
                        for island_id, debug_army in sorted(graph_data.debug_fake_escape_usage_by_island.items()):
                            island = islands.tile_islands_by_unique_id.get(island_id)
                            if island is None:
                                debug_usage_descriptions.append(f'{island_id}:debugArmy={debug_army}')
                                continue
                            debug_usage_descriptions.append(
                                f'{island_id}({island.tiles_by_army[0]} team={island.team},army={island.sum_army},'
                                f'tiles={island.tile_count}):debugArmy={debug_army}'
                            )
                        logbook.error(
                            f'FLOW_DEBUG_FAKE_ESCAPE_USED usageByIsland=[{", ".join(debug_usage_descriptions)}]'
                        )
                    else:
                        logbook.warning('FLOW_DEBUG_FAKE_ESCAPE_UNUSED no debug fake escape arcs carried flow')

            # Add diagnostic logging for zero real flow scenarios (always fire, not gated by log_debug)
            if graph_data.cumulative_demand == 0:
                logbook.warning(
                    f'FLOW_DIAG_ZERO_CUMULATIVE_DEMAND cumulative_demand=0 means fake_node has no supply to distribute. '
                    f'This explains why real nodes get no flow - the graph is perfectly balanced without fake node injection.'
                )
            elif total_positive_flow > 0 and total_real_arc_flow == 0:
                logbook.warning(
                    f'FLOW_DIAG_ALL_FAKE_FLOW totalPositiveFlow={total_positive_flow} totalRealArcFlow=0. '
                    f'The solver is using only fake node saturation arcs, not real island-to-island paths. '
                    f'cumulative_demand={graph_data.cumulative_demand} fakeToRealFlow={total_fake_to_real_flow}'
                )
            elif total_positive_flow > 0 and total_root_output_real_flow == 0 and total_real_arc_flow > 0:
                logbook.warning(
                    f'FLOW_DIAG_REAL_FLOW_NO_ROOT_OUTPUT totalPositiveFlow={total_positive_flow} totalRealArcFlow={total_real_arc_flow} '
                    f'totalRootOutputRealFlow=0. Real arcs have flow but none leave root output ports. '
                    f'Flow may be circulating within islands or entering fake nodes from real islands.'
                )

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
        self.threat_blocking_tiles: typing.Dict['Tile', typing.Any] | None = None
        self.constrained_flow_paths: typing.List[Path] | None = None

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
            self.threat_blocking_tiles,
            self.constrained_flow_paths,
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
        return computer.compute_flow(islands, graph_data, method)

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
            if self.log_debug:
                no_neut_root_edge_count = sum(len(node.flow_to) for node in final_root_no_neut_flow_nodes)
                no_neut_root_flow_received = sum(node.army_flow_received for node in final_root_no_neut_flow_nodes)
                no_neut_zero_edge_roots = [
                    (
                        node.island.unique_id,
                        node.island.sum_army,
                        node.desired_army,
                        node.army_flow_received,
                        len(node.flow_to),
                        [(tile.x, tile.y, tile.army) for tile in node.island.tiles_by_army[:4]],
                    )
                    for node in final_root_no_neut_flow_nodes
                    if len(node.flow_to) == 0
                ]
                logbook.warning(
                    f'FLOW_DIAG_ROOT_GRAPH_SUMMARY mode=no_neut roots={len(final_root_no_neut_flow_nodes)} '
                    f'rootEdges={no_neut_root_edge_count} rootArmyFlowReceived={no_neut_root_flow_received} '
                    f'zeroEdgeRoots={no_neut_zero_edge_roots[:32]}'
                )
                if len(final_root_no_neut_flow_nodes) > 0 and no_neut_root_edge_count == 0:
                    logbook.warning(
                        f'FLOW_DIAG_BAD_ROOT_GRAPH mode=no_neut roots={len(final_root_no_neut_flow_nodes)} '
                        f'friendlySupply={getattr(graph_data_no_neut, "friendly_army_supply", None)} '
                        f'enemyDemand={getattr(graph_data_no_neut, "enemy_army_demand", None)} '
                        f'enemyGeneralDemand={getattr(graph_data_no_neut, "enemy_general_demand", None)} '
                        f'cumulativeDemand={graph_data_no_neut.cumulative_demand}'
                    )
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
            result.debug_fake_escape_usage_by_island = dict(graph_data_no_neut.debug_fake_escape_usage_by_island)
        return result
