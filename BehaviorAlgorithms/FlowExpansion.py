from __future__ import annotations

import typing
import heapq
from collections import deque
from dataclasses import dataclass

import logbook

import Algorithms
import DebugHelper
import Gather
import KnapsackUtils
from BehaviorAlgorithms.Flow.FlowDirectionFinderABC import FlowDirectionFinderABC
from BehaviorAlgorithms.Flow.FlowGraphModels import FlowGraphMethod, IslandFlowNode, IslandMaxFlowGraph
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.Flow.PyMaxFlowDirectionFinder import PyMaxFlowDirectionFinder
from BehaviorAlgorithms.Flow.OrToolsFlowDirectionFinder import OrToolsFlowDirectionFinder
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpanderLastRun, FlowExpansionPlanOptionCollection, ITERATIVE_EXPANSION_EN_CAP_VAL
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix
from PerformanceTimer import PerformanceTimer

if typing.TYPE_CHECKING:
    from Algorithms import TileIsland
    from Algorithms import TileIslandBuilder
    from BoardAnalyzer import BoardAnalyzer
    from Interfaces import TileSet
    from base.client.map import MapBase
    from base.client.tile import Tile
    from Models import Move
    from Gather import GatherCapturePlan
    from ViewInfo import ViewInfo


@dataclass
class FlowBorderPairKey:
    """Key for identifying a specific friendly-target border pair"""
    friendly_island_id: int
    target_island_id: int

    def __hash__(self) -> int:
        return hash((self.friendly_island_id, self.target_island_id))

    def __eq__(self, other) -> bool:
        if not isinstance(other, FlowBorderPairKey):
            return False
        return (self.friendly_island_id == other.friendly_island_id and
                self.target_island_id == other.target_island_id)


@dataclass
class FlowStreamIslandContribution:
    """Lightweight metadata about one flow node's contribution to a stream"""
    island_id: int
    is_friendly: bool
    flow_node: IslandFlowNode
    tile_count: int
    army_amount: int
    marginal_flow: int
    sort_score: float
    is_crossing: bool  # True when friendly island is used as target-side crossing node


@dataclass
class FlowTurnsEntry:
    """Represents a specific turn-based flow expansion option"""
    turns: int
    required_army: int
    econ_value: float
    army_remaining: int
    gathered_army: int
    included_friendly_flow_nodes: tuple[IslandFlowNode, ...]
    included_target_flow_nodes: tuple[IslandFlowNode, ...]
    incomplete_friendly_island_id: int | None
    incomplete_friendly_tile_count: int
    incomplete_target_island_id: int | None
    incomplete_target_tile_count: int


@dataclass
class EnrichedFlowTurnsEntry:
    """Represents a capture entry enriched with its minimum gather support"""
    capture_entry: FlowTurnsEntry
    gather_entry: FlowTurnsEntry
    gather_index: int
    combined_turn_cost: int
    combined_value_density: float


@dataclass
class FlowArmyTurnsLookupTable:
    """Per border pair lookup table"""
    border_pair: FlowBorderPairKey
    capture_entries_by_turn: list[FlowTurnsEntry | None]
    gather_entries_by_turn: list[FlowTurnsEntry | None]
    best_capture_entries_prefix: list[FlowTurnsEntry | None]
    best_gather_entries_prefix: list[FlowTurnsEntry | None]
    enriched_capture_entries: list[EnrichedFlowTurnsEntry]
    metadata: dict  # Contains max_flow_across_border, friendly_stream_tile_count, etc.


@dataclass
class FlowExpansionV2DebugSnapshot:
    """Optional debug snapshot for tests/debug"""
    graph_stats: dict
    num_border_pairs: int
    entries_generated_per_border_pair: dict
    overlap_warnings: list[str]
    pruned_vs_kept_choices: dict


@dataclass
class ExternalPlanOption:
    """
    Wrapper for external plan options (intercepts, etc.) to participate in MKCP.
    These are not flow-based but need to be considered alongside flow options.
    """
    plan: typing.Any  # TilePlanInterface (InterceptionOptionInfo, etc.)
    turns: int
    econ_value: float
    tile_set: frozenset  # Set of tiles for conflict detection
    group_id: int  # Unique group ID for MKCP (mutually exclusive with other externals)


def get_tile_army_mapmatrix(map: MapBase) -> MapMatrix:
    """
    Build a MapMatrix[int] where each entry is the current tile.army for that tile.
    Useful as a baseline army_override_matrix for ArmyFlowExpanderV2, allowing callers
    to override specific tiles (e.g. predicted fog armies) before passing it in.
    """
    matrix: MapMatrix = MapMatrix(map, 0)
    for tile in map.get_all_tiles():
        matrix.raw[tile.tile_index] = tile.army
    return matrix


class ArmyFlowExpanderV2:
    """
    V2 flow expansion implementation that eventually replaces ArmyFlowExpander.

    Design goals:
    - Reuse only trustworthy existing pieces
    - Separate preprocessing from optimization for testability
    - Preserve current output shape: FlowExpansionPlanOptionCollection with GatherCapturePlan instances
    """

    def __init__(self, map: MapBase, perf_timer: PerformanceTimer | None = None):
        self.map: MapBase = map
        self.perf_timer: PerformanceTimer = perf_timer
        if self.perf_timer is None:
            self.perf_timer = PerformanceTimer()
            self.perf_timer.begin_move(map.turn)

        self.team: int = map.team_ids_by_player_index[map.player_index]
        self.target_team: int = -1

        # Canonical camelCase names (match ArmyFlowExpander interface used by TestBase and BotExpansionOps)
        self.friendlyGeneral: Tile = map.generals[map.player_index]
        self.enemyGeneral: Tile | None = None
        self.island_builder: TileIslandBuilder | None = None

        # Configuration options
        self.method: FlowGraphMethod = FlowGraphMethod.OrToolsSimpleMinCost
        self.use_simple_flow_stream_maximization: bool = True
        self.log_debug: bool = DebugHelper.IS_DEBUGGING
        self.debug_render_capture_count_threshold: int = 10000
        """If there are more captures in any given plan option than this, then the option will be rendered inline as generated in a new debug viewer window."""
        self.use_debug_asserts: bool = DebugHelper.IS_DEBUGGING

        # Internal state
        self.flow_graph: IslandMaxFlowGraph | None = None
        self.last_run: ArmyFlowExpanderLastRun = ArmyFlowExpanderLastRun()
        self.last_lookup_tables: list | None = None
        self._networkx_finder: NetworkXFlowDirectionFinder | None = None  # Will be initialized when needed
        self._pymax_finder: PyMaxFlowDirectionFinder | None = None  # Will be initialized when needed
        self._ortools_finder: OrToolsFlowDirectionFinder | None = None  # Will be initialized when needed
        self.use_backpressure_from_enemy_general: bool = False
        self.live_render_invalid_flow_config = None
        self._target_crossable_cache: set[int] = set()  # Cache for target-crossable islands
        self._allow_neut_only_flow: bool = False
        self.bonus_capture_point_matrix: MapMatrixInterface[float] | None = None
        self.army_override_matrix: MapMatrixInterface[int] | None = None
        """If set, per-tile army amounts read from this matrix instead of tile.army during lookup table generation."""

    def get_expansion_options(
            self,
            islands: TileIslandBuilder,
            asPlayer: int,
            targetPlayer: int,
            turns: int,
            boardAnalysis: BoardAnalyzer,
            territoryMap: MapMatrixInterface[int],
            negativeTiles: TileSet | None = None,
            leafMoves: typing.Union[None, typing.List[Move]] = None,
            viewInfo: ViewInfo = None,
            bonusCapturePointMatrix: MapMatrixInterface[float] | None = None,
            perfTimer: PerformanceTimer | None = None,
            cutoffTime: float | None = None,
            additional_options: typing.List[typing.Any] | None = None,
            army_override_matrix: MapMatrixInterface[int] | None = None
    ) -> FlowExpansionPlanOptionCollection:
        """
        Main entry point - returns expansion options compatible with existing interface.

        This is the V2 implementation following the FlowExpansion.md plan.
        """
        # Sync caller-supplied player context and timer into our state
        if perfTimer is not None:
            self.perf_timer = perfTimer
        self.target_team = self.map.team_ids_by_player_index[targetPlayer]
        if self.enemyGeneral is None:
            self.enemyGeneral = self.map.generals[targetPlayer]
        self.island_builder = islands
        self.bonus_capture_point_matrix = bonusCapturePointMatrix
        if army_override_matrix is not None:
            self.army_override_matrix = army_override_matrix

        # Process additional_options (intercepts, etc.) into MKCP-compatible format
        external_options: list[ExternalPlanOption] = []
        if additional_options:
            external_options = self._convert_additional_options_to_external(additional_options, turns)

        # Phase 0: Build flow graph
        with self.perf_timer.begin_move_event('V2 phase0 _ensure_flow_graph_exists'):
            self._ensure_flow_graph_exists(islands, turns)

        # Phase 1 / 1.5: Enumerate border pairs and compute stream ordering metadata
        with self.perf_timer.begin_move_event('V2 phase1 _detect_target_crossable + _enumerate_border_pairs'):
            target_crossable = self._detect_target_crossable_friendly_islands(
                islands, self.flow_graph, self.team, self.target_team
            )
            border_pairs = self._enumerate_border_pairs(
                self.flow_graph, islands, self.team, self.target_team, target_crossable
            )

        # Phase 2: Build per-border gather/capture lookup tables
        with self.perf_timer.begin_move_event('V2 phase2 _process_flow_into_flow_army_turns'):
            lookup_tables = self._process_flow_into_flow_army_turns(
                border_pairs, self.flow_graph, target_crossable, turns
            )

        # Phase 3: Enrich capture entries with minimum gather support
        with self.perf_timer.begin_move_event('V2 phase3 _postprocess_flow_stream_gather_capture_lookup_pairs'):
            self._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)
        self.last_lookup_tables = lookup_tables

        # Phase 4: Solve grouped knapsack for turn budget (includes external options like intercepts)
        with self.perf_timer.begin_move_event('V2 phase4 _solve_grouped_knapsack'):
            solution = self._solve_grouped_knapsack(lookup_tables, turns, external_options)

        if not self.use_simple_flow_stream_maximization:
            # Phase 6: Optional local post-optimization
            with self.perf_timer.begin_move_event('V2 phase6 _post_optimize_locally'):
                solution = self._post_optimize_locally(solution, lookup_tables, turns, external_options)

        # Phase 5: Convert chosen entries into GatherCapturePlan objects
        with self.perf_timer.begin_move_event('V2 phase5 _materialize_plans'):
            plans = self._materialize_plans(solution, lookup_tables, external_options)

        result = FlowExpansionPlanOptionCollection()
        total = 0
        for plan in plans:
            total += plan.length
        if total > turns:
            raise AssertionError(f'Requested {turns} but received {total} turns worth of plans.\r\n  {"\r\n    ".join(f"{opt}: {'|'.join(f"{t.x},{t.y}" for t in sorted(opt.tiles, key=lambda t2: self.island_builder.intergeneral_analysis.aMap.raw[t2.tile_index]))}" for opt in plans)}')
        result.flow_plans = plans
        return result

    def _get_tile_army(self, tile: Tile) -> int:
        """Returns the army amount for a tile, using army_override_matrix if set."""
        if self.army_override_matrix is not None:
            return self.army_override_matrix.raw[tile.tile_index]
        return tile.army

    def _get_networkx_finder(self) -> NetworkXFlowDirectionFinder:
        """Lazily construct the NetworkX-backed flow direction finder."""
        if self._networkx_finder is None:
            assert self.island_builder is not None, '_get_networkx_finder requires island_builder to be set'
            self._networkx_finder = NetworkXFlowDirectionFinder(
                self.map,
                self.island_builder.intergeneral_analysis,
                friendly_general=self.friendlyGeneral,
                use_backpressure_from_enemy_general=self.use_backpressure_from_enemy_general,
                perf_timer=self.perf_timer,
                log_debug=self.log_debug,  # enable debug logging for comparison
                invalid_flow_renderer=None,  # TODO: Add renderer if needed
            )
        self._networkx_finder.configure(self.team, self.target_team, self.enemyGeneral)
        return self._networkx_finder

    def _get_pymax_finder(self) -> PyMaxFlowDirectionFinder:
        """Lazily construct the PyMaxflow-backed flow direction finder. Mirrors the
        construction pattern in ArmyFlowExpander._get_pymax_flow_direction_finder."""
        if self._pymax_finder is None:
            self._pymax_finder = PyMaxFlowDirectionFinder(
                self.map,
                self.island_builder.intergeneral_analysis,
                self.perf_timer,
                self.log_debug,
                self.use_backpressure_from_enemy_general,
                self.friendlyGeneral,
                self.live_render_invalid_flow_config,
            )
        self._pymax_finder.configure(self.team, self.target_team, self.enemyGeneral)
        return self._pymax_finder

    def _get_ortools_finder(self) -> OrToolsFlowDirectionFinder:
        """Lazily construct the OR-Tools-backed flow direction finder."""
        if self._ortools_finder is None:
            self._ortools_finder = OrToolsFlowDirectionFinder(
                self.map,
                self.island_builder.intergeneral_analysis,
                self.perf_timer,
                self.log_debug,
                self.use_backpressure_from_enemy_general,
                self.friendlyGeneral,
                self.live_render_invalid_flow_config,
            )
        self._ortools_finder.configure(self.team, self.target_team, self.enemyGeneral)
        return self._ortools_finder

    def _get_flow_direction_finder(self, method: FlowGraphMethod | None = None) -> FlowDirectionFinderABC:
        """Dispatch to the correct concrete finder for the requested flow method.
        Mirrors ArmyFlowExpander._get_flow_direction_finder so V2 supports the same
        FlowGraphMethod values as the legacy expander."""
        if method is None:
            method = self.method
        if method in (FlowGraphMethod.PyMaxflowBoykovKolmogorov, FlowGraphMethod.PyMaxflowWithNodeSplitting):
            return self._get_pymax_finder()
        if method == FlowGraphMethod.OrToolsSimpleMinCost:
            return self._get_ortools_finder()
        return self._get_networkx_finder()

    def _ensure_flow_graph_exists(self, islands: TileIslandBuilder, turns: int) -> None:
        """Build or reuse the flow graph using whichever finder backs self.method.

        This used to be hardcoded to NetworkXFlowDirectionFinder; it now mirrors
        ArmyFlowExpander's dispatcher so PyMaxflow-based methods (BoykovKolmogorov /
        WithNodeSplitting) actually run their concrete finder instead of silently
        falling back to NetworkX.
        """
        self.island_builder = islands
        finder = self._get_flow_direction_finder(self.method)

        our_islands = islands.tile_islands_by_player[self.map.player_index]
        target_islands = islands.tile_islands_by_team_id[self.target_team]

        self.flow_graph = finder.build_flow_graph(
            islands,
            our_islands,
            target_islands,
            self.map.player_index,
            turns=turns,
            blockGatherFromEnemyBorders=True,
            negativeTiles=None,
            includeNeutralDemand=self._allow_neut_only_flow,
            method=self.method,
        )
        self.enemyGeneral = finder.enemy_general

    def _enumerate_border_pairs(
        self,
        flow_graph: IslandMaxFlowGraph,
        islands: TileIslandBuilder,
        my_team: int,
        target_team: int,
        target_crossable_islands: set[int]
    ) -> list[FlowBorderPairKey]:
        """Phase 1: Enumerate valid friendly-target border pairs"""
        border_pairs = []

        for friendly_island in islands.tile_islands_by_team_id[my_team]:
            if friendly_island.unique_id in target_crossable_islands:
                if self.log_debug:
                    logbook.info(f"Skipping target-crossable friendly island {friendly_island}")
                continue

            for target_island in sorted(friendly_island.border_islands, key=lambda b: b.tile_count_all_adjacent_friendly, reverse=True):
                if target_island.team != target_team and target_island.team != -1 and target_island.unique_id not in target_crossable_islands:
                    continue

                # Verify there's actual flow support between these islands
                if not self._is_flow_supported(friendly_island, target_island, flow_graph):
                    if self.log_debug:
                        logbook.info(f"Skipping border pair {friendly_island.unique_id}->{target_island.unique_id}: no flow support")
                    continue

                border_pair = FlowBorderPairKey(
                    friendly_island_id=friendly_island.unique_id,
                    target_island_id=target_island.unique_id
                )
                border_pairs.append(border_pair)
                if self.log_debug:
                    logbook.info(f"Added border pair: friendly {friendly_island} -> target {target_island}")

        return border_pairs

    def _is_flow_supported(
        self,
        friendly_island: 'TileIsland',
        target_island: 'TileIsland',
        flow_graph: IslandMaxFlowGraph
    ) -> bool:
        """
        Check if there's flow support between friendly and target islands. O(n) to n islands in flow...

        Does a BFS forward from the friendly node through the flow graph to see
        if it can reach the target island, passing through neutral islands along
        the way.
        """

        if self.log_debug:
            logbook.info(f"Checking flow support: {friendly_island.unique_id} -> {target_island.unique_id}")

        # TODO why the fuck is this a bfs?
        # Check both neutral-inclusive and enemy-only flow graphs
        for flow_lookup in [
            flow_graph.flow_node_lookup_by_island_no_neut,
            flow_graph.flow_node_lookup_by_island_inc_neut if self._allow_neut_only_flow else None,
        ]:
            if flow_lookup is None:
                continue
            if (friendly_island.unique_id not in flow_lookup or
                target_island.unique_id not in flow_lookup):
                if self.log_debug:
                    logbook.info(f"  Flow lookup missing: friendly {friendly_island.unique_id} in_lookup={friendly_island.unique_id in flow_lookup}, target {target_island.unique_id} in_lookup={target_island.unique_id in flow_lookup}")
                continue

            friendly_node = flow_lookup[friendly_island.unique_id]

            # This replaces the BFS below for now until I figure out why the BFS was necessary lol
            for edge in friendly_node.flow_to:
                dest = edge.target_flow_node
                if self.log_debug:
                    logbook.info(f"    BFS: {friendly_node.island.unique_id} -> {dest.island.unique_id} (team={dest.island.team})")
                if dest.island.unique_id == target_island.unique_id:
                    if self.log_debug:
                        logbook.info(f"    BFS FOUND PATH to {target_island.unique_id}")
                    return True
            continue

            if self.log_debug:
                logbook.info(f"  Starting BFS from friendly node {friendly_island.unique_id}, flow_to={[e.target_flow_node.island.unique_id for e in friendly_node.flow_to]}")

            # BFS forward through flow edges from the friendly node
            visited: set[int] = set()
            q = [friendly_node]
            while q:
                cur = q.pop()
                if cur.island.unique_id in visited:
                    continue
                visited.add(cur.island.unique_id)

                for edge in cur.flow_to:
                    dest = edge.target_flow_node
                    if self.log_debug:
                        logbook.info(f"    BFS: {cur.island.unique_id} -> {dest.island.unique_id} (team={dest.island.team})")
                    if dest.island.unique_id == target_island.unique_id:
                        if self.log_debug:
                            logbook.info(f"    BFS FOUND PATH to {target_island.unique_id}")
                        return True
                    # Continue BFS through neutral islands
                    if dest.island.team == -1:
                        q.append(dest)

            if self.log_debug:
                logbook.info(f"  BFS failed to reach {target_island.unique_id}, visited={visited}")

        return False

    def _detect_target_crossable_friendly_islands(
        self,
        islands: TileIslandBuilder,
        flow_graph: IslandMaxFlowGraph,
        my_team: int,
        target_team: int
    ) -> set[int]:
        """
        Detect friendly islands that should be treated as target-side crossing nodes.

        A friendly island is target crossable when:
        - it is a friendly island
        - the max-flow graph shows more non-friendly flow sources than friendly flow sources
        - its parent island contains less than 1/5 of the friendly team's total tile count
        - the max-flow graph shows pathing into the friendly island from non-friendly sources
        """
        target_crossable = set()

        # Calculate total friendly tile count for the 1/5 threshold
        total_friendly_tiles = sum(
            island.tile_count
            for island in islands.tile_islands_by_team_id[my_team]
        )
        threshold_tiles = total_friendly_tiles // 5

        for island in islands.all_tile_islands:
            if island.team != my_team:
                continue

            # Check if flow graph shows direct non-friendly flow into this island.
            # An island is crossable if flow comes from non-friendly sources (enemy or neutral).
            non_friendly_flow_in_count = 0
            friendly_flow_in_count = 0
            has_non_friendly_flow_in = False

            # Check both neutral-inclusive and enemy-only flow graphs
            for flow_lookup in [
                flow_graph.flow_node_lookup_by_island_no_neut,
                flow_graph.flow_node_lookup_by_island_inc_neut if self._allow_neut_only_flow else None,
            ]:
                if flow_lookup is None:
                    continue
                flow_node = flow_lookup.get(island.unique_id, None)
                if flow_node is None:
                    continue
                for edge in flow_node.flow_from:
                    source_team = edge.source_flow_node.island.team
                    if source_team != my_team:
                        non_friendly_flow_in_count += 1
                        has_non_friendly_flow_in = True
                    else:
                        friendly_flow_in_count += 1

            # Must have more non-friendly flow sources than friendly flow sources
            if non_friendly_flow_in_count <= friendly_flow_in_count:
                continue

            # Check if island is small enough (< 1/5 of total friendly tiles)
            # Use the parent (full_island) tile count per design: "parent island contains < 1/5 of total"
            parent_tile_count = island.full_island.tile_count if island.full_island is not None else island.tile_count
            if parent_tile_count >= threshold_tiles:
                continue

            if has_non_friendly_flow_in:
                target_crossable.add(island.unique_id)
                if self.log_debug:
                    logbook.info(f"Marked island {island.unique_id} as target-crossable: "
                             f"non_friendly_flow_in={non_friendly_flow_in_count}, friendly_flow_in={friendly_flow_in_count}, "
                             f"size={island.tile_count}, threshold={threshold_tiles}")

        # Propagate crossability via island border adjacency: any friendly island that borders
        # an already-crossable island and passes conditions 1-3 is also crossable.
        # Uses border_islands (not flow edges) so tiles not in the flow graph are handled too.
        # Repeat until stable to cover chains of arbitrary length.
        changed = True
        while changed:
            changed = False
            for island in islands.all_tile_islands:
                if island.unique_id in target_crossable:
                    continue
                if island.team != my_team:
                    continue
                # Check size threshold (condition 3)
                parent_tc = island.full_island.tile_count if island.full_island is not None else island.tile_count
                if parent_tc >= threshold_tiles:
                    continue
                # Must touch at least one enemy island (condition 2 relaxed: eb >= 1 sufficient
                # during propagation, since the chain anchor already established enemy contact)
                touches_enemy = any(b.team == target_team for b in island.border_islands)
                if not touches_enemy:
                    continue
                # Propagate if any bordering friendly island is already crossable
                for border_island in island.border_islands:
                    if border_island.unique_id in target_crossable:
                        target_crossable.add(island.unique_id)
                        changed = True
                        if self.log_debug:
                            logbook.info(f"Propagated island {island.unique_id} as target-crossable via border adjacency: "
                                     f"size={island.tile_count}, threshold={threshold_tiles}")
                        break

        # Update cache
        self._target_crossable_cache = target_crossable

        logbook.info(f"[TARGET_CROSSABLE] EXIT: found {len(target_crossable)} target-crossable islands: {sorted(target_crossable)}")

        return target_crossable

    class BorderPairStreamPotential(object):
        def __init__(
            self,
            border_pair: FlowBorderPairKey,
            econ_value_potential: float,
            cap_army_potential: int,
            gather_turns_potential: int,
            gather_army_potential: int,
            friendly_stream: list[IslandFlowNode],
            target_stream: list[IslandFlowNode],
            friendly_node: IslandFlowNode,
            target_node: IslandFlowNode,
        ):
            self.border_pair = border_pair
            self.econ_value_potential = econ_value_potential
            self.cap_army_potential = cap_army_potential
            self.gather_turns_potential = gather_turns_potential
            self.gather_army_potential = gather_army_potential
            self.friendly_stream = friendly_stream
            self.target_stream = target_stream
            self.friendly_node = friendly_node
            self.target_node = target_node

    def _build_border_pair_stream_data(
        self,
        border_pair: FlowBorderPairKey,
        flow_graph: IslandMaxFlowGraph,
        target_crossable_islands: set[int],
        turn_budget: int,
    ) -> BorderPairStreamPotential:
        """Phase 1: Build directional stream traversals for a border pair"""

        # Get the flow nodes for the border pair
        friendly_node = None
        target_node = None

        # Check both flow graph variants
        lookup = None
        for flow_lookup in [
            flow_graph.flow_node_lookup_by_island_no_neut,
            flow_graph.flow_node_lookup_by_island_inc_neut if self._allow_neut_only_flow else None,
        ]:
            if flow_lookup is None:
                continue
            friendly_node = flow_lookup.get(border_pair.friendly_island_id, None)
            target_node = flow_lookup.get(border_pair.target_island_id, None)
            if (friendly_node is not None and target_node is not None):
                lookup = flow_lookup
                break

        if friendly_node is None or target_node is None:
            return None

        # Build upstream friendly stream traversal
        friendly_stream = self._build_upstream_stream(
            friendly_node, target_crossable_islands
        )

        # Build downstream target stream traversal — walk starting AT the target
        # border node. Starting from the friendly source would fork into sibling
        # border pairs that share the same friendly node (friendly.flow_to often
        # contains multiple target neighbours, each of which is its own border pair).
        target_stream = self._build_downstream_stream(
            target_node, target_crossable_islands, flow_graph, turn_budget
        )

        # Calculate potential values from streams
        # Econ value potential: total economic value from target stream
        econ_value_potential = sum(
            self._calculate_island_econ_value(node.island, target_crossable_islands)
            for node in target_stream
        )

        # Cap army potential: total army required to capture all targets
        # = sum of defender armies + tiles traversed (one per tile) + 1 for final capture
        cap_army_potential = sum(
            node.island.sum_army + node.island.tile_count
            for node in target_stream
        )

        # Gather turns potential: total tiles in friendly stream (turns to gather)
        gather_tile_count = sum(node.island.tile_count for node in friendly_stream)
        gather_turns_potential = gather_tile_count - 1

        # Gather army potential: total army available from friendly stream
        gather_army_potential = sum(node.island.sum_army for node in friendly_stream) - gather_tile_count

        if self.log_debug:
            logbook.info(
                f'STREAM_DATA bp={border_pair.friendly_island_id}->{border_pair.target_island_id}: '
                f'friendly_stream=['
                + ', '.join(f'{n.island.unique_id}({n.island.tile_count}t {n.island.sum_army}a flow_from={[e.source_flow_node.island.unique_id for e in n.flow_from]})' for n in friendly_stream)
                + f'] target_stream=['
                + ', '.join(f'{n.island.unique_id}({n.island.tile_count}t)' for n in target_stream)
                + f'] econ_potential={econ_value_potential:.1f} cap_army={cap_army_potential} '
                f'gather_turns={gather_turns_potential} gather_army={gather_army_potential}'
            )

        return self.BorderPairStreamPotential(
            border_pair=border_pair,
            econ_value_potential=econ_value_potential,
            cap_army_potential=cap_army_potential,
            gather_turns_potential=gather_turns_potential,
            gather_army_potential=gather_army_potential,
            friendly_stream=friendly_stream,
            target_stream=target_stream,
            friendly_node=friendly_node,
            target_node=target_node,
        )

    def _build_upstream_stream(
        self,
        start_node: IslandFlowNode,
        target_crossable_islands: set[int]
    ) -> list[IslandFlowNode]:
        """Build upstream traversal from friendly border node using priority queue.

        Uses a priority queue with heuristic = sum_army / tile_count, preferring
        islands with higher army density.

        Flow edges (flow_from) are created only between islands that are in each
        other's border_islands (see NetworkXFlowDirectionFinder.build_network_graph),
        and border_islands is strictly asserted as tile-adjacent in
        TileIslandBuilder.debug_verify_all_islands. Therefore every edge we walk
        here is guaranteed to connect two spatially adjacent islands — no
        per-tile adjacency check is needed.
        """

        visited = set()
        stream = []

        # Priority queue: (-heuristic, island_id, node, upstream_army_sum)
        # Negative heuristic for max-heap behavior (higher = better)
        frontier = []

        # Calculate initial heuristic for start node
        start_island = start_node.island
        if start_island.team == self.team:
            start_heuristic = start_island.sum_army / max(start_island.tile_count, 1)
            heapq.heappush(frontier, (-start_heuristic, start_island.unique_id, start_node, start_island.sum_army))
            visited.add(start_island.unique_id)

        while frontier:
            _, _, current_node, upstream_army = heapq.heappop(frontier)

            # Add to stream
            stream.append(current_node)

            if self.log_debug:
                logbook.info(
                    f'UPSTREAM_PQ node={current_node.island.unique_id}({current_node.island!r}) '
                    f'heuristic={upstream_army / max(current_node.island.tile_count, 1):.2f} '
                    f'upstream_army={upstream_army}'
                )

            # Explore upstream neighbors
            for edge in current_node.flow_from:
                src = edge.source_flow_node
                src_island = src.island

                if src_island.unique_id in visited:
                    continue
                if src_island.team != self.team:
                    if self.log_debug:
                        logbook.info(
                            f'UPSTREAM_PQ  SKIP non-friendly: {src_island.unique_id}(team={src_island.team})'
                        )
                    continue

                # Calculate heuristic: sum_army / tile_count
                # Higher army density = higher priority for gathering
                heuristic = src_island.sum_army / max(src_island.tile_count, 1)

                # Track total upstream army (current upstream + this island's army)
                # This is used for gather calculations, not for priority
                total_upstream_army = upstream_army + src_island.sum_army

                visited.add(src_island.unique_id)
                heapq.heappush(frontier, (-heuristic, src_island.unique_id, src, total_upstream_army))

        return stream

    def _build_downstream_stream(
        self,
        start_node: IslandFlowNode,
        target_crossable_islands: set[int],
        flow_graph: IslandMaxFlowGraph,
        max_stream_size: int,
    ) -> list[IslandFlowNode]:
        """Build downstream traversal starting AT the target border node.

        start_node is the target half of a border pair; it is emitted first as the
        entry point into enemy/neutral territory, and the traversal then walks
        outward in priority-queue order (heuristic = econ_value / army_sum,
        higher is better).

        Two edge sources are considered from each visited node:
          1. flow_to edges produced by MinCostFlow — the "routed" downstream path.
          2. physical adjacency via island.border_islands — a fallback so that
             neutrals/enemies adjacent to the routed path (but not themselves
             receiving flow) still appear as capture targets. Without this, each
             border pair's capture count is capped at whatever MinCostFlow chose
             to route, starving the MCKP of capture items and leaving faraway
             friendly army (e.g. landlocked cave tiles) with no plan to fund.

        Flow edges and border_islands are both strictly tile-adjacent (the
        former via NetworkXFlowDirectionFinder.build_network_graph, the latter
        via TileIslandBuilder.debug_verify_all_islands). Because every newly
        added node is adjacent to at least one already-visited node, the stream
        preserves its "each tile is adjacent to a predecessor" invariant that
        downstream capture-plan materialization relies on.

        max_stream_size bounds traversal at the turn budget — capture entries
        beyond that are unusable in the MCKP anyway.
        """

        visited = {start_node.island.unique_id}
        stream = [start_node]

        # Priority queue: (-heuristic, island_id, node)
        # Negative heuristic for max-heap behavior (higher = better)
        frontier = []

        flow_lookup = flow_graph.flow_node_lookup_by_island_no_neut

        def _enqueue_candidate(dest_node: IslandFlowNode) -> None:
            dest_island = dest_node.island
            if dest_island.unique_id in visited:
                return

            # Only include targets, neutrals, or target-crossable friendlies
            is_target = (dest_island.team == self.target_team or
                         dest_island.team == -1 or
                         dest_island.unique_id in target_crossable_islands)
            if not is_target:
                return

            econ_value = self._calculate_island_econ_value(dest_island, target_crossable_islands)
            army_sum = max(dest_island.sum_army, 1)  # Avoid division by zero
            heuristic = econ_value / army_sum

            visited.add(dest_island.unique_id)
            heapq.heappush(frontier, (-heuristic, dest_island.unique_id, dest_node))

        def _enqueue_downstream(node: IslandFlowNode) -> None:
            # 1) Routed flow_to edges (preferred: preserves prior behavior for
            #    pairs where MinCostFlow already routed into neutrals).
            for edge in node.flow_to:
                _enqueue_candidate(edge.target_flow_node)
            # 2) Physical-adjacency fallback: include neutral/enemy neighbors
            #    that MinCostFlow did not route to. Dedup via `visited` prevents
            #    doubling of candidates already enqueued through flow_to.
            for neighbor_island in node.island.border_islands:
                if neighbor_island.unique_id in visited:
                    continue
                neighbor_node = flow_lookup.get(neighbor_island.unique_id)
                if neighbor_node is None:
                    continue
                _enqueue_candidate(neighbor_node)

        if self.log_debug:
            econ_val = self._calculate_island_econ_value(start_node.island, target_crossable_islands)
            logbook.info(
                f'DOWNSTREAM_PQ start node={start_node.island.unique_id}({start_node.island!r}) '
                f'econ={econ_val:.1f} army={start_node.island.sum_army}'
            )

        _enqueue_downstream(start_node)

        while frontier and len(stream) < max_stream_size:
            _, _, current_node = heapq.heappop(frontier)
            current_island = current_node.island

            stream.append(current_node)

            if self.log_debug:
                econ_val = self._calculate_island_econ_value(current_island, target_crossable_islands)
                logbook.info(
                    f'DOWNSTREAM_PQ node={current_island.unique_id}({current_island!r}) '
                    f'heuristic={econ_val / max(current_island.sum_army, 1):.4f} '
                    f'econ={econ_val:.1f} army={current_island.sum_army}'
                )

            _enqueue_downstream(current_node)

        return stream

    def _calculate_island_econ_value(self, island, target_crossable_islands: set[int]) -> float:
        """Calculate total econ value for an island."""

        is_crossing = island.unique_id in target_crossable_islands

        if is_crossing:
            return 0.0
        elif island.team == -1:
            # Neutral island: 1.0 per tile
            base_value = island.tile_count * 1.0
        elif island.team == self.target_team:
            # Enemy island: value per tile
            base_value = island.tile_count * ITERATIVE_EXPANSION_EN_CAP_VAL
        else:
            return 0.0

        if self.bonus_capture_point_matrix is not None:
            for tile in island.tile_set:
                base_value += self.bonus_capture_point_matrix.raw[tile.tile_index]

        return base_value

    def _preprocess_flow_stream_tilecounts(
        self,
        stream_data: BorderPairStreamPotential,
        border_pair: FlowBorderPairKey
    ) -> tuple[list[FlowStreamIslandContribution], list[FlowStreamIslandContribution]]:
        """
        Phase 1.5: Compute stream ordering metadata.

        Returns (friendly_contributions, target_contributions) ordered by preference.
        """
        friendly_stream = stream_data.friendly_stream
        target_stream = stream_data.target_stream

        # Build friendly contributions with gather-focused heuristics
        friendly_contributions = self._compute_friendly_contributions(friendly_stream)

        # Build target contributions with capture-focused heuristics
        target_contributions = self._compute_target_contributions(target_stream)

        # Friendly contributions: sort by preference (higher army-per-tile first)
        friendly_contributions.sort(key=lambda x: x.sort_score, reverse=True)
        # Target contributions: preserve physical path order from _build_downstream_stream.
        # Sorting by value here would reorder mandatory traversal nodes (e.g. neutrals
        # sitting between the friendly border and the first enemy tile) after high-value
        # enemy tiles, producing impossible capture plans.

        return friendly_contributions, target_contributions

    def _compute_friendly_contributions(
        self,
        friendly_stream: list[IslandFlowNode]
    ) -> list[FlowStreamIslandContribution]:
        """Compute friendly-side contributions with gather-focused heuristics"""
        contributions = []

        for node in friendly_stream:
            # Calculate gatherable army / committed tiles ratio
            army_amount = node.island.sum_army
            tile_count = node.island.tile_count

            # Effective ratio: gatherable_army / committed_tiles
            if tile_count > 0:
                effective_ratio = army_amount / tile_count
            else:
                effective_ratio = 0.0

            # Use flow magnitude as tie-breaker
            flow_magnitude = sum(edge.edge_army for edge in node.flow_to)

            # Sort score combines ratio and flow magnitude
            sort_score = effective_ratio * 1000 + flow_magnitude * 0.1

            contribution = FlowStreamIslandContribution(
                island_id=node.island.unique_id,
                is_friendly=True,
                flow_node=node,
                tile_count=tile_count,
                army_amount=army_amount,
                marginal_flow=int(flow_magnitude),
                sort_score=sort_score,
                is_crossing=False
            )
            contributions.append(contribution)

        return contributions

    def _compute_target_contributions(
        self,
        target_stream: list[IslandFlowNode]
    ) -> list[FlowStreamIslandContribution]:
        """Compute target-side contributions with capture-focused heuristics"""
        contributions = []

        for node in target_stream:
            is_crossing = (node.island.team == self.team and
                          node.island.unique_id in self._target_crossable_cache)

            # Calculate capture cost and value
            army_cost = node.island.sum_army if not is_crossing else 0  # Crossing nodes have no direct capture cost
            tile_count = node.island.tile_count

            # Heuristic score: prefer lower army-per-tile and better downstream potential
            if tile_count > 0:
                army_per_tile = army_cost / tile_count
            else:
                army_per_tile = float('inf')

            # Lower army_per_tile is better (invert for sorting)
            cost_score = 1.0 / (1.0 + army_per_tile)

            # Use the same econ capture values as the rest of the codebase:
            #   enemy tile cap = ITERATIVE_EXPANSION_EN_CAP_VAL (2.2)
            #   neutral tile cap = 1.0
            #   crossing (friendly, no capture cost) = 0.0
            if is_crossing:
                type_bonus = 0.0
            elif node.island.team == self.target_team:
                type_bonus = ITERATIVE_EXPANSION_EN_CAP_VAL
            else:
                type_bonus = 1.0

            # Flow magnitude represents downstream continuation potential
            flow_magnitude = sum(edge.edge_army for edge in node.flow_to)

            # cost_score in [0, 1]; type_bonus separates enemy (2.2) from neutral (1.0)
            # and neutral from crossing (0.0) regardless of cost_score
            sort_score = cost_score + type_bonus + flow_magnitude * 0.1

            contribution = FlowStreamIslandContribution(
                island_id=node.island.unique_id,
                is_friendly=is_crossing,  # Only true for crossing nodes
                flow_node=node,
                tile_count=tile_count,
                army_amount=army_cost,
                marginal_flow=int(flow_magnitude),
                sort_score=sort_score,
                is_crossing=is_crossing
            )
            contributions.append(contribution)

        return contributions

    def _process_flow_into_flow_army_turns(
        self,
        border_pairs: list[FlowBorderPairKey],
        flow_graph: IslandMaxFlowGraph,
        target_crossable_islands: set[int],
        turn_budget: int,
    ) -> list[FlowArmyTurnsLookupTable]:
        """
        Phase 2: Build per-border gather/capture lookup tables.

        This is the main Step 1 from the prompt, clarified.
        """
        lookup_tables = []

        # TODO order by the border pairs with the highest potential econValue per turn heuristic.
        # border_pairs.sort(key=lambda x: x.)

        for border_pair in border_pairs:
            # Build stream data for this border pair
            stream_data = self._build_border_pair_stream_data(border_pair, flow_graph, target_crossable_islands, turn_budget)
            if stream_data is None:
                continue

            # Get ordered contributions for this border pair
            friendly_contribs, target_contribs = self._preprocess_flow_stream_tilecounts(stream_data, border_pair)

            # Generate capture lookup table
            capture_lookup = self._generate_capture_lookup_table(
                border_pair, target_contribs, stream_data, turn_budget
            )

            # Generate gather lookup table
            gather_lookup = self._generate_gather_lookup_table(
                border_pair, friendly_contribs, stream_data, turn_budget
            )

            # Build prefix tables (best entries up to each turn)
            best_capture_prefix = self._build_prefix_table(capture_lookup)
            best_gather_prefix = self._build_prefix_table(gather_lookup)

            # Create metadata
            metadata = {
                'max_flow_across_border': self._calculate_max_flow_across_border(border_pair, flow_graph),
                'friendly_stream_tile_count': sum(c.tile_count for c in friendly_contribs),
                'target_stream_tile_count': sum(c.tile_count for c in target_contribs),
                'border_pair': border_pair
            }

            lookup_table = FlowArmyTurnsLookupTable(
                border_pair=border_pair,
                capture_entries_by_turn=capture_lookup,
                gather_entries_by_turn=gather_lookup,
                best_capture_entries_prefix=best_capture_prefix,
                best_gather_entries_prefix=best_gather_prefix,
                enriched_capture_entries=[],  # Will be filled in Phase 3
                metadata=metadata
            )

            lookup_tables.append(lookup_table)

            if self.log_debug:
                logbook.info(f"Generated lookup table for border pair {border_pair.friendly_island_id}->{border_pair.target_island_id}: "
                             f"capture_entries={len([e for e in capture_lookup if e is not None])}, "
                             f"gather_entries={len([e for e in gather_lookup if e is not None])}")

        return lookup_tables

    def _generate_capture_lookup_table(
        self,
        border_pair: FlowBorderPairKey,
        target_contributions: list[FlowStreamIslandContribution],
        stream_data: BorderPairStreamPotential,
        turn_budget: int,
        prio_mat: MapMatrixInterface[float] | None = None,
    ) -> list[FlowTurnsEntry | None]:
        """
        Generate capture lookup table for a border pair.

        Parameters:
            border_pair (FlowBorderPairKey): The border pair for which to generate the lookup table.
            target_contributions (list[FlowStreamIslandContribution]): Contributions from target islands.
            stream_data (BorderPairStreamPotential): Stream data containing island information.

        Returns:
            list[FlowTurnsEntry | None]: The generated capture lookup table.
        """
        # Start with the border crossing (turn 0 = border state, turn 1 = first target island)
        max_turns = turn_budget
        lookup: typing.List[FlowTurnsEntry | None] = [None] * (max_turns + 1)

        current_turn = 0
        current_army_cost = 0
        current_econ_value = 0.0
        current_army_remaining = 0
        current_gathered_army = 0
        included_target_nodes = []
        included_friendly_nodes = []
        incomplete_friendly_island_id = None
        incomplete_friendly_tile_count = 0

        # Turn 0 represents the initial border state (no capture yet)
        lookup[0] = FlowTurnsEntry(
            turns=0,
            required_army=0,
            econ_value=0.0,
            army_remaining=0,
            gathered_army=0,
            included_friendly_flow_nodes=tuple(),
            included_target_flow_nodes=tuple(),
            incomplete_friendly_island_id=None,
            incomplete_friendly_tile_count=0,
            incomplete_target_island_id=None,
            incomplete_target_tile_count=0
        )

        # Process target contributions in order
        for contrib in target_contributions:
            node = contrib.flow_node
            island = node.island

            # Add this island to the capture plan
            included_target_nodes.append(node)

            i = 0
            for tile in island.tiles_by_army:
                current_turn += 1
                if current_turn > max_turns:
                    break
                i += 1

                if contrib.is_crossing:
                    # Target-crossable friendly island: only turn cost, no econ value
                    current_army_cost -= self._get_tile_army(tile)
                else:
                    if prio_mat is not None:
                        current_econ_value += prio_mat.raw[tile.tile_index]
                    # Regular capture (enemy or neutral)
                    current_army_cost += self._get_tile_army(tile)

                    if island.team == self.target_team:
                        # Enemy island capture
                        current_econ_value += ITERATIVE_EXPANSION_EN_CAP_VAL
                    else:
                        # Neutral island capture
                        current_econ_value += 1.0

                # Create entry for this exact turn count if within bounds
                # required_army = sum(defender_armies) + tiles_traversed + 1
                # Each tile traversed costs 1 army (left behind on source/intermediate tile),
                # and the final capture requires arriving with strictly more than the defender
                # (generals.io rule: attacker wins only if attacker > defender, so need +1).
                required_army_for_entry = current_army_cost + current_turn
                lookup[current_turn] = FlowTurnsEntry(
                    turns=current_turn,
                    required_army=required_army_for_entry,
                    econ_value=current_econ_value,
                    army_remaining=current_army_remaining,
                    gathered_army=current_gathered_army,
                    included_friendly_flow_nodes=tuple(included_friendly_nodes),
                    included_target_flow_nodes=tuple(included_target_nodes),
                    incomplete_friendly_island_id=incomplete_friendly_island_id,
                    incomplete_friendly_tile_count=incomplete_friendly_tile_count,
                    incomplete_target_island_id=island.unique_id if island.tile_count > i else None,
                    incomplete_target_tile_count=island.tile_count - i
                )
                if self.log_debug:
                    logbook.info(f"CAPTURES: {border_pair.friendly_island_id}->{border_pair.target_island_id}  (cur {island.unique_id}) - Adding capture entry @{tile} for turn {current_turn} with econ value {current_econ_value:.2f}, army cost {current_army_cost}, "
                                 f"army remaining {current_army_remaining}, gathered army {current_gathered_army}, required army {required_army_for_entry}, incomplete {lookup[current_turn].incomplete_target_tile_count}")

            if current_turn > max_turns:
                break

        return lookup

    def _generate_gather_lookup_table(
        self,
        border_pair: FlowBorderPairKey,
        friendly_contributions: list[FlowStreamIslandContribution],
        stream_data: BorderPairStreamPotential,
        turn_budget: int,
    ) -> list[FlowTurnsEntry | None]:
        """
        Generate gather lookup table for a border pair.

        Processes tiles individually (like _generate_capture_lookup_table) to support
        partial gathers - gathering from only some tiles of an island rather than
        the entire island at once.
        """
        max_turns = turn_budget
        lookup: typing.List[FlowTurnsEntry | None] = [None] * (max_turns + 1)

        current_turn = 0
        current_gathered_army = 0
        current_econ_value = 0.0  # Gather entries have no direct econ value
        current_army_remaining = 0
        current_required_army = 0
        included_target_nodes = []
        included_friendly_nodes = []
        incomplete_target_island_id = None
        incomplete_target_tile_count = 0
        incomplete_friendly_island_id = None
        incomplete_friendly_tile_count = 0

        # Turn 0 represents the initial border state
        lookup[0] = FlowTurnsEntry(
            turns=0,
            required_army=0,
            econ_value=0.0,
            army_remaining=0,
            gathered_army=0,
            included_friendly_flow_nodes=tuple(),
            included_target_flow_nodes=tuple(),
            incomplete_friendly_island_id=None,
            incomplete_friendly_tile_count=0,
            incomplete_target_island_id=None,
            incomplete_target_tile_count=0
        )

        friendlyContributionsByIslandId = {}
        for contribution in friendly_contributions:
            friendlyContributionsByIslandId[contribution.island_id] = contribution

        # Compute path-depth for each friendly island via BFS from the border node through
        # flow_from edges (upstream direction).  Depth = cumulative tile_count of islands
        # traversed on the shortest path from the border island to this island, INCLUDING
        # this island's own tile_count.  So traversal_cost = depth - island.tile_count.
        # Army contribution per island = island.sum_army - traversal_cost.
        friendly_node: IslandFlowNode = stream_data.friendly_node  # friendly border pair node

        # TODO priority queue this shit probably so we can pull the highest gather/turn shit first even if it pulls through a "1" army island or something.
        if friendly_node is None:
            raise ValueError("Friendly node not found in stream data")

        bfs_queue: typing.Deque[tuple[IslandFlowNode, int]] = deque([(friendly_node, friendly_node.island.tile_count - 1)])
        bfs_visited: set[int] = set()
        while bfs_queue:
            node_bfs, depth = bfs_queue.popleft()
            iid = node_bfs.island.unique_id
            if iid in bfs_visited:
                continue

            if depth > max_turns:
                continue

            bfs_visited.add(iid)

            contrib = friendlyContributionsByIslandId.get(node_bfs.island.unique_id, None)
            if contrib is None:
                raise ValueError(f"Contribution not found for island {node_bfs.island.unique_id}")

            node = contrib.flow_node
            island = node.island

            # Get the island's depth - this represents the minimum turn when we can start
            # gathering from this island (army from upstream islands needs this many turns
            # to reach the border). Since we increment current_turn at the start of each tile
            # loop, we use island_depth - 1 as the baseline.

            # Add this island to the gather plan
            included_friendly_nodes.append(node)

            currentArmy = 0

            # Process each tile individually (like capture lookup)
            i = 0
            for tile in reversed(island.tiles_by_army):
                if current_turn > max_turns:
                    break
                i += 1

                # Net army from this tile: tile.army (full army from tile)
                # minus traversal_cost applied only to the first tile of the island.
                # This matches the original logic: island.sum_army - traversal_cost
                # For multi-tile islands, each tile contributes its full army; the "leave 1 behind"
                # is implicit in the army movement mechanics, not subtracted here.

                tile_contribution = self._get_tile_army(tile) - 1

                current_gathered_army += tile_contribution

                # We don't need a lookup entry for bad gathers. It cant be more useful than the shorter one, so skip for this level.
                if tile_contribution <= 0:
                    current_turn += 1
                    continue

                # if tile_contribution >= 0:
                # Create entry for this exact turn count
                lookup[current_turn] = FlowTurnsEntry(
                    turns=current_turn,
                    required_army=current_required_army,
                    econ_value=current_econ_value,
                    army_remaining=current_army_remaining,
                    gathered_army=current_gathered_army,
                    included_friendly_flow_nodes=tuple(included_friendly_nodes),
                    included_target_flow_nodes=tuple(included_target_nodes),
                    incomplete_friendly_island_id=island.unique_id if island.tile_count > i else None,
                    incomplete_friendly_tile_count=island.tile_count - i,
                    incomplete_target_island_id=incomplete_target_island_id,
                    incomplete_target_tile_count=incomplete_target_tile_count
                )
                if self.log_debug:
                    logbook.info(
                        f"GATHERS: {border_pair.friendly_island_id}->{border_pair.target_island_id}  (cur {island.unique_id}) - Adding gather entry @{tile} for turn {current_turn} with gathered army {int(current_gathered_army)}, "
                        f"tile contribution {self._get_tile_army(tile) - 1:.2f}, incomplete {lookup[current_turn].incomplete_friendly_tile_count}")

                current_turn += 1

            if current_turn > max_turns:
                continue

            for edge in node_bfs.flow_from:
                src = edge.source_flow_node
                if src.island.team == self.team and src.island.unique_id not in bfs_visited:
                    bfs_queue.append((src, depth + src.island.tile_count))

        return lookup

    def _build_prefix_table(
        self,
        lookup: list[FlowTurnsEntry | None]
    ) -> list[FlowTurnsEntry | None]:
        """Build prefix table with best entry up to each turn"""
        prefix = [None] * len(lookup)
        best_so_far = None

        for i in range(len(lookup)):
            entry = lookup[i]
            if entry is not None:
                # For capture tables, prefer higher econ_value
                # For gather tables, prefer higher gathered_army
                if best_so_far is None:
                    best_so_far = entry
                else:
                    # Simple comparison - could be made more sophisticated
                    if entry.econ_value > best_so_far.econ_value or entry.gathered_army > best_so_far.gathered_army:
                        best_so_far = entry

            prefix[i] = best_so_far

        return prefix

    def _calculate_max_flow_across_border(
        self,
        border_pair: FlowBorderPairKey,
        flow_graph: IslandMaxFlowGraph
    ) -> int:
        """Calculate the maximum flow capacity across this border pair"""
        # Find the flow nodes for this border pair
        friendly_node = None
        target_node = None

        for flow_lookup in [
            flow_graph.flow_node_lookup_by_island_no_neut,
            flow_graph.flow_node_lookup_by_island_inc_neut if self._allow_neut_only_flow else None,
        ]:
            if flow_lookup is None:
                continue
            if (border_pair.friendly_island_id in flow_lookup and
                border_pair.target_island_id in flow_lookup):
                friendly_node = flow_lookup[border_pair.friendly_island_id]
                target_node = flow_lookup[border_pair.target_island_id]
                break

        if friendly_node is None or target_node is None:
            return 0

        # Sum the capacity of edges between these nodes
        max_flow = 0
        for edge in friendly_node.flow_to:
            if edge.target_flow_node.island.unique_id == border_pair.target_island_id:
                max_flow += edge.edge_army

        return max_flow

    def _postprocess_flow_stream_gather_capture_lookup_pairs(
        self,
        lookup_tables: list[FlowArmyTurnsLookupTable]
    ) -> None:
        """
        Phase 3: Enrich capture entries with minimum gather support.

        For each border pair and each capture entry:
        - find the minimum-turn gather entry whose gathered_army >= capture.required_army
        - record:
          - gather_index
          - combined_turn_cost = capture.turns + gather.turns
          - combined_value_density = capture.econ_value / combined_turn_cost
        """
        for lookup_table in lookup_tables:
            capture_entries = lookup_table.capture_entries_by_turn
            gather_entries = lookup_table.gather_entries_by_turn

            # Create enriched capture entries list
            enriched_captures = []

            for capture_turn, capture_entry in enumerate(capture_entries):
                if capture_entry is None or capture_turn == 0:
                    continue

                # TODO this is inefficient, we should be maintaining a gather index and just walking backwards up the gathers while we walk forwards through the captures. No reason to loop gathers completely for every capture entry...
                # Find the minimum-turn gather entry that supports this capture
                min_gather_entry = self._find_minimum_gather_support(
                    capture_entry, gather_entries
                )

                if min_gather_entry is not None:
                    # Calculate combined metrics
                    combined_turn_cost = capture_entry.turns + min_gather_entry.turns
                    combined_value_density = (capture_entry.econ_value / combined_turn_cost
                                            if combined_turn_cost > 0 else 0.0)

                    # Create enriched capture entry
                    enriched_capture = EnrichedFlowTurnsEntry(
                        capture_entry=capture_entry,
                        gather_entry=min_gather_entry,
                        gather_index=min_gather_entry.turns,
                        combined_turn_cost=combined_turn_cost,
                        combined_value_density=combined_value_density
                    )

                    enriched_captures.append(enriched_capture)

                    if self.log_debug:
                        logbook.info(f"Border pair {lookup_table.border_pair.friendly_island_id}->{lookup_table.border_pair.target_island_id}: "
                                     f"Capture turn {capture_turn} (army={capture_entry.required_army}) "
                                     f"paired with gather turn {min_gather_entry.turns} (army={min_gather_entry.gathered_army}) "
                                     f"-> total econ {capture_entry.econ_value:.2f} / combined cost {combined_turn_cost} = density {combined_value_density:.3f}")
                else:
                    # No gather support available for this capture
                    if self.log_debug:
                        logbook.info(f"Border pair {lookup_table.border_pair.friendly_island_id}->{lookup_table.border_pair.target_island_id}: "
                                     f"Capture turn {capture_turn} (army={capture_entry.required_army}) "
                                     f"has no sufficient gather support")

            # Store enriched captures in the lookup table
            lookup_table.enriched_capture_entries = enriched_captures

    def _find_minimum_gather_support(
        self,
        capture_entry: FlowTurnsEntry,
        gather_entries: list[FlowTurnsEntry | None]
    ) -> FlowTurnsEntry | None:
        """
        Find the minimum-turn gather entry whose gathered_army >= capture.required_army.

        Uses the prefix table approach for efficiency.
        """
        required_army = capture_entry.required_army

        # If no army required, the turn 0 gather entry is sufficient
        if required_army <= 0:
            return gather_entries[0]

        # Search through gather entries to find the minimum turn that provides sufficient army
        best_gather = None
        best_turn = float('inf')

        for gather_turn, gather_entry in enumerate(gather_entries):
            if gather_entry is None:
                continue

            if (gather_entry.gathered_army >= required_army and
                gather_turn < best_turn):
                best_gather = gather_entry
                best_turn = gather_turn

        return best_gather

    def _convert_additional_options_to_external(
        self,
        additional_options: typing.List[TilePlanInterface],
        turns: int
    ) -> list[ExternalPlanOption]:
        """
        Convert TilePlanInterface options (InterceptionOptionInfo, etc.) to ExternalPlanOption
        for inclusion in the MKCP solver.
        """
        external_options: list[ExternalPlanOption] = []
        group_id = 1000000  # Start external groups at high number to avoid collision with flow groups

        for opt in additional_options:
            if opt is None:
                continue
            # Skip options that exceed turn budget
            total_turns = opt.length + opt.requiredDelay
            if total_turns > turns:
                continue

            # Skip options with no economic value
            if opt.econValue <= 0:
                continue

            # Get tile set for conflict detection
            tile_set = frozenset(opt.tileSet)

            external_options.append(ExternalPlanOption(
                plan=opt,
                turns=total_turns,
                econ_value=opt.econValue,
                tile_set=tile_set,
                group_id=group_id
            ))
            group_id += 1

        return external_options

    def _solve_grouped_knapsack(
        self,
        lookup_tables: list[FlowArmyTurnsLookupTable],
        turn_budget: int,
        external_options: list[ExternalPlanOption] | None = None
    ) -> dict:
        """
        Phase 4: Solve grouped knapsack for turn budget, respecting tile-use mutex.

        Includes external options (intercepts, etc.) alongside flow-based options.

        ===========================================================================
        Multi-pair tile mutex problem
        ===========================================================================
        Different border pairs can share tiles in two ways:
        (a) Friendly gather chains — a passthrough tile that the max-flow solution
            forwards army through toward both target T1 and target T2 produces two
            pairs F->T1 and F->T2 whose gather chains both consume F's army.
        (b) Target capture chains — a downstream neutral/enemy island (e.g. 2064)
            can appear in the capture stream of two different border pairs (e.g.
            2041->2011 and 2036->2009), causing _materialize_plans to assign the
            same physical tiles to both plans.
        The base MCKP treats every candidate item as independent and can therefore
        double-spend the same tile across two chosen items.

        Required behaviour: among items chosen from DIFFERENT border-pair groups,
        no two may share a friendly island in their gather chains OR a target island
        in their capture chains. Items WITHIN the same group are already mutex via
        standard MCKP.

        ===========================================================================
        Approaches considered
        ===========================================================================

        (1) Greedy + conflict-repair  *** IMPLEMENTED BELOW ***
            Run MCKP unchanged. Inspect chosen items for cross-group friendly-island
            overlap. For each conflicting pair, blacklist the lower-density item
            from the input set and re-run MCKP. Iterate until MCKP output is
            conflict-free. The "greedy" decision is only the choice of which item
            to remove from the input set; MCKP itself remains optimal on each
            reduced set. Fast (sub-ms) and converges in a small number of
            iterations because each pass removes at least one item from candidacy.
            Heuristic: not guaranteed globally optimal (a different combination
            of pair-internal items might score higher than the greedy reductions
            allow), but in practice resolves the realistic conflict patterns.

        (2) Multi-dimensional DP
            Add one knapsack dimension per shared friendly island, each with
            capacity 1, weight 1 if the item consumes that island else 0. Cost
            is O(N * T * 2^S) where S = number of shared friendly islands.
            Optimal but blows up when many islands fork into multiple pairs.
            Could be wrapped with a fallback to (1) once S exceeds a threshold.

        (3) ILP via scipy.optimize.milp / PuLP
            Encode the constrained MCKP as a 0/1 integer linear program: one
            binary per item, sum<=1 per group, sum<=1 per shared friendly island,
            sum(weight) <= turn_budget, maximise sum(value). Always optimal but
            adds an external solver dependency and is the slowest option.

        (4) Pure greedy without MCKP
            Sort items by value-density and walk the list, picking each item
            whose group is unused and whose friendly islands are unconsumed. No
            DP at all. Even faster than (1) but loses MCKP's tradeoff search
            within a group entirely.
        ===========================================================================
        """
        items: list[EnrichedFlowTurnsEntry | ExternalPlanOption] = []
        groups: list[int] = []
        weights: list[int] = []
        values: list[int] = []
        # Per-item set of friendly island ids consumed by the gather chain.
        # Used by the conflict-repair pass below.
        friendly_island_sets: list[frozenset[int]] = []
        # Per-item set of target island ids consumed by the capture chain.
        # Two items from different groups that share a target island would
        # produce duplicate tile captures and must also be treated as conflicts.
        target_island_sets: list[frozenset[int]] = []
        # Per-item tile set for external options (for tile-based conflict detection)
        external_tile_sets: list[frozenset] = []
        # Track which items are external options (index -> True)
        is_external_item: dict[int, bool] = {}

        forest = Algorithms.FastDisjointSet()

        goodLookupTables = []
        # Pre-compute the union of all friendly gather-chain island IDs for each
        # lookup table.  Two border pairs that share ANY gather-chain island must
        # end up in the same MCKP group so the solver naturally enforces the
        # mutex rather than relying on the post-solve conflict-repair loop.
        table_friendly_union: dict[int, set[int]] = {}  # index -> set of island ids
        for idx, lookup_table in enumerate(lookup_tables):
            if not lookup_table.enriched_capture_entries:
                continue

            forest.merge(lookup_table.border_pair.friendly_island_id, lookup_table.border_pair.target_island_id)
            goodLookupTables.append(lookup_table)

            union: set[int] = set()
            for enriched in lookup_table.enriched_capture_entries:
                for n in enriched.gather_entry.included_friendly_flow_nodes:
                    union.add(n.island.unique_id)
            table_friendly_union[idx] = union

        # Merge groups for any two border pairs that share a gather-chain island.
        # Build an island-id -> table-index map (first table that owns the island
        # wins; subsequent tables sharing it get merged into that group).
        island_to_table_idx: dict[int, int] = {}
        for idx, lookup_table in enumerate(lookup_tables):
            if idx not in table_friendly_union:
                continue
            for iid in table_friendly_union[idx]:
                if iid in island_to_table_idx:
                    # Another table already claimed this island — merge the groups.
                    other_idx = island_to_table_idx[iid]
                    forest.merge(
                        lookup_table.border_pair.friendly_island_id,
                        lookup_tables[other_idx].border_pair.friendly_island_id,
                    )
                else:
                    island_to_table_idx[iid] = idx

        subsets = forest.subsets()
        groupIdx = 0
        groupLookup: dict[int, int] = {}
        for subset in subsets:
            if self.log_debug:
                logbook.info(f"Group {groupIdx}: {subset}")
            for i in subset:
                groupLookup[i] = groupIdx
            groupIdx += 1

        for lookup_table in sorted(goodLookupTables, key=lambda t: groupLookup[t.border_pair.friendly_island_id]):
            group_idx = groupLookup[lookup_table.border_pair.friendly_island_id]
            if self.log_debug:
                logbook.info(f"MKCP group {group_idx}: border pair {lookup_table.border_pair.friendly_island_id}->{lookup_table.border_pair.target_island_id} "
                             f"with {len(lookup_table.enriched_capture_entries)} entries. Group {group_idx} has {len(subsets[group_idx])} lookup tables.")

            for enriched in lookup_table.enriched_capture_entries:
                items.append(enriched)
                groups.append(group_idx)
                weights.append(enriched.combined_turn_cost)
                values.append(int(1000 * enriched.capture_entry.econ_value))
                friendly_island_sets.append(frozenset(
                    n.island.unique_id for n in enriched.gather_entry.included_friendly_flow_nodes
                ))
                target_island_sets.append(frozenset(
                    n.island.unique_id for n in enriched.capture_entry.included_target_flow_nodes
                ))
                external_tile_sets.append(frozenset())  # Flow items have no external tile set
                if self.log_debug:
                    logbook.info(f"  MKCP item: group={group_idx} weight={enriched.combined_turn_cost} "
                                 f"value={int(1000 * enriched.capture_entry.econ_value)} "
                                 f"(gather={enriched.gather_entry.turns}, capture={enriched.capture_entry.turns})")

        # Add external options (intercepts, etc.) to MKCP with unique group IDs
        if external_options:
            for ext_opt in external_options:
                idx = len(items)
                items.append(ext_opt)
                groups.append(ext_opt.group_id)
                weights.append(ext_opt.turns)
                values.append(int(1000 * ext_opt.econ_value))
                # External options don't have island-based gather/capture chains
                friendly_island_sets.append(frozenset())
                target_island_sets.append(frozenset())
                # But they do have tile sets for conflict detection
                external_tile_sets.append(ext_opt.tile_set)
                is_external_item[idx] = True
                if self.log_debug:
                    logbook.info(f"  MKCP external item: group={ext_opt.group_id} weight={ext_opt.turns} "
                                 f"value={int(1000 * ext_opt.econ_value)} type={type(ext_opt.plan).__name__}")

        if not items:
            return {}

        # --- Conflict-repair loop -------------------------------------------------
        # Map item identity -> original index so we can blacklist by index even
        # when we filter the active list each iteration.
        item_to_index = {id(it): i for i, it in enumerate(items)}
        blacklist: set[int] = set()
        max_iterations = 32  # bounded; each iteration blacklists >= 1 item.

        chosen_items: list[EnrichedFlowTurnsEntry | ExternalPlanOption] = []
        max_value = 0
        for iteration in range(max_iterations):
            active_idx = [i for i in range(len(items)) if i not in blacklist]
            if not active_idx:
                chosen_items = []
                max_value = 0
                break

            a_items = [items[i] for i in active_idx]
            a_weights = [weights[i] for i in active_idx]
            a_values = [values[i] for i in active_idx]
            # MCKP requires group indices to be contiguous (no gaps). After
            # blacklisting empties an entire group, the surviving items may
            # span e.g. groups {0, 1, 3, 4} — remap those to {0, 1, 2, 3}
            # so the solver doesn't reject the input.
            present_groups = sorted({groups[i] for i in active_idx})
            group_remap = {g: idx for idx, g in enumerate(present_groups)}
            a_groups = [group_remap[groups[i]] for i in active_idx]

            max_value, chosen_items = KnapsackUtils.solve_multiple_choice_knapsack(
                a_items, turn_budget, a_weights, a_values, a_groups,
                noLog=not self.log_debug, longRuntimeThreshold=10.0
            )

            # Detect cross-group conflicts among chosen items.
            # Two items conflict iff they belong to different groups (intra-group
            # mutex is already enforced by MCKP) AND either:
            #   (a) their gather chains share a friendly island, OR
            #   (b) their capture chains share a target island
            #   (c) for external options: their tile sets overlap (tile-based conflict)
            # Case (b) catches the scenario where a downstream target island
            # (e.g. island 2064) appears in the capture stream of two different
            # border pairs, producing duplicate tile captures in materialization.
            conflicts: list[tuple] = []
            n = len(chosen_items)
            chosen_orig_idx = [item_to_index[id(c)] for c in chosen_items]

            # Helper to safely get external tile set
            def _get_external_tiles(idx: int) -> frozenset:
                if is_external_item.get(idx, False):
                    # Map from item index to external_options index
                    ext_idx = sum(1 for k in range(idx) if is_external_item.get(k, False))
                    if ext_idx < len(external_options):
                        return external_options[ext_idx].tile_set
                return frozenset()

            for i in range(n):
                gi = groups[chosen_orig_idx[i]]
                fi = friendly_island_sets[chosen_orig_idx[i]]
                ti = target_island_sets[chosen_orig_idx[i]]
                is_ext_i = is_external_item.get(chosen_orig_idx[i], False)
                ext_tiles_i = _get_external_tiles(chosen_orig_idx[i])
                for j in range(i + 1, n):
                    if groups[chosen_orig_idx[j]] == gi:
                        continue
                    fj = friendly_island_sets[chosen_orig_idx[j]]
                    tj = target_island_sets[chosen_orig_idx[j]]
                    is_ext_j = is_external_item.get(chosen_orig_idx[j], False)
                    ext_tiles_j = _get_external_tiles(chosen_orig_idx[j])

                    # Island-based conflicts (flow vs flow)
                    island_conflict = (fi & fj) or (ti & tj)

                    # Tile-based conflicts for external options
                    tile_conflict = False
                    if is_ext_i or is_ext_j:
                        # Two external options: check tile overlap directly
                        if ext_tiles_i and ext_tiles_j:
                            tile_conflict = bool(ext_tiles_i & ext_tiles_j)
                        # External vs Flow: check if external tiles belong to flow's islands
                        # This requires island_builder to be available
                        if self.island_builder is not None:
                            if is_ext_i and not is_ext_j and ext_tiles_i:
                                # Item i is external, item j is flow - check if i's tiles are in j's islands
                                flow_islands_j = fj | tj
                                for tile in ext_tiles_i:
                                    tile_island = self.island_builder.tile_island_lookup.raw[tile.tile_index]
                                    if tile_island is not None and tile_island.unique_id in flow_islands_j:
                                        tile_conflict = True
                                        break
                            elif is_ext_j and not is_ext_i and ext_tiles_j:
                                # Item j is external, item i is flow - check if j's tiles are in i's islands
                                flow_islands_i = fi | ti
                                for tile in ext_tiles_j:
                                    tile_island = self.island_builder.tile_island_lookup.raw[tile.tile_index]
                                    if tile_island is not None and tile_island.unique_id in flow_islands_i:
                                        tile_conflict = True
                                        break

                    if island_conflict or tile_conflict:
                        conflicts.append((chosen_items[i], chosen_items[j]))

            if not conflicts:
                break

            # Choose the loser per conflict pair using a hybrid heuristic:
            #
            #   DEFAULT  — drop the lower value-per-turn item (density pruning).
            #              Density is the right metric when the knapsack budget
            #              is the binding constraint: every freed turn can be
            #              backfilled by smaller high-density items, so keeping
            #              the densest options yields the best total value.
            #
            #   EXCEPTION — if density says to drop the HEAVIER plan AND doing
            #              so would leave the chosen total weight below the
            #              turn budget, keep the heavier plan instead and drop
            #              the lighter one. Rationale: a low-density deep
            #              chain is only worth dropping if the freed weight
            #              gets refilled. When the knapsack already has slack
            #              after the drop, the freed weight is just wasted
            #              budget, so we strictly lose absolute econ value by
            #              dropping the heavier (higher-absolute-value) chain.
            #
            # Ties on density: compare absolute econ_value, then weight.
            def _get_item_weight(item):
                if isinstance(item, ExternalPlanOption):
                    return item.turns
                return item.combined_turn_cost

            def _get_item_value(item):
                if isinstance(item, ExternalPlanOption):
                    return item.econ_value
                return item.capture_entry.econ_value

            current_chosen_weight = sum(_get_item_weight(c) for c in chosen_items)
            newly_blacklisted = 0
            for item_a, item_b in conflicts:
                wa = max(_get_item_weight(item_a), 1)
                wb = max(_get_item_weight(item_b), 1)
                va = _get_item_value(item_a)
                vb = _get_item_value(item_b)
                da = va / wa
                db = vb / wb

                # Density-based default loser
                if da < db:
                    default_loser, default_winner = item_a, item_b
                elif da > db:
                    default_loser, default_winner = item_b, item_a
                else:
                    # density tie — fall back to absolute value, then weight
                    if va < vb:
                        default_loser, default_winner = item_a, item_b
                    elif va > vb:
                        default_loser, default_winner = item_b, item_a
                    else:
                        default_loser, default_winner = (
                            (item_a, item_b) if _get_item_weight(item_a) < _get_item_weight(item_b)
                            else (item_b, item_a)
                        )

                # Exception: if dropping the default loser is the heavier item AND
                # doing so leaves total weight below capacity, swap — keep the heavier.
                weight_a = _get_item_weight(item_a)
                weight_b = _get_item_weight(item_b)
                heavier = item_a if weight_a > weight_b else item_b
                lighter = item_b if heavier is item_a else item_a
                if (default_loser is heavier and heavier is not lighter and
                        current_chosen_weight - _get_item_weight(heavier) < turn_budget):
                    loser = lighter
                else:
                    loser = default_loser

                loser_idx = item_to_index[id(loser)]
                if loser_idx not in blacklist:
                    blacklist.add(loser_idx)
                    newly_blacklisted += 1

            if self.log_debug:
                logbook.info(
                    f"Conflict-repair iter {iteration}: detected {len(conflicts)} cross-group "
                    f"tile conflicts (friendly-gather or target-capture), blacklisted {newly_blacklisted} items "
                    f"(total blacklisted: {len(blacklist)})"
                )

            if newly_blacklisted == 0:
                # Defensive: no progress — should not happen but avoid infinite loop.
                if self.log_debug:
                    logbook.warning("Conflict-repair made no progress; aborting loop")
                break
        else:
            if self.log_debug:
                logbook.warning(
                    f"Conflict-repair hit max_iterations={max_iterations}; returning last MCKP result"
                )

        if self.log_debug:
            total_weight = sum(_get_item_weight(it) for it in chosen_items)
            logbook.info(f"Grouped knapsack: budget={turn_budget}, best_weight={total_weight}, best_value={max_value}, "
                         f"chosen_groups={len(chosen_items)}, repair_iterations={iteration if chosen_items else 0}, "
                         f"blacklisted={len(blacklist)}")

        # Build solution dict keyed by border_pair for easy lookup
        # Use object identity (is) not equality (==) because EnrichedFlowTurnsEntry is a dataclass
        # and two entries from different border pairs could have the same field values
        solution: dict[FlowBorderPairKey | str, EnrichedFlowTurnsEntry | ExternalPlanOption] = {}
        for chosen_item in chosen_items:
            # Handle external options (intercepts, etc.)
            if isinstance(chosen_item, ExternalPlanOption):
                # Store external options with a special key
                solution[f"external_{chosen_item.group_id}"] = chosen_item
                if self.log_debug:
                    logbook.info(f"Grouped knapsack solution: EXTERNAL group={chosen_item.group_id} "
                                 f"weight={chosen_item.turns}, value={chosen_item.econ_value:.2f}, "
                                 f"type={type(chosen_item.plan).__name__}")
                continue

            # Handle flow-based entries
            enriched = chosen_item
            # Find the lookup table this enriched entry belongs to using identity check
            found = False
            for lookup_table in lookup_tables:
                if any(enriched is e for e in lookup_table.enriched_capture_entries):
                    solution[lookup_table.border_pair] = enriched
                    if self.log_debug:
                        logbook.info(f"Grouped knapsack solution: {lookup_table.border_pair.friendly_island_id}->{lookup_table.border_pair.target_island_id} "
                                     f"(gather={enriched.gather_entry.turns}, capture={enriched.capture_entry.turns}, "
                                     f"weight={enriched.combined_turn_cost}, value={enriched.capture_entry.econ_value:.2f})")
                    found = True
                    break
            if not found and self.log_debug:
                logbook.info(f"Grouped knapsack WARNING: chosen item not found in any lookup table! "
                             f"(gather={enriched.gather_entry.turns}, capture={enriched.capture_entry.turns})")

        return solution

    def _post_optimize_locally(
        self,
        baseline_solution: dict,
        lookup_tables: list[FlowArmyTurnsLookupTable],
        turn_budget: int,
        external_options: list[ExternalPlanOption] | None = None
    ) -> dict:
        """
        Phase 6: Optional post-optimization path.

        When use_simple_flow_stream_maximization is False:
        - run grouped knapsack first to produce baseline
        - then run localized improvement search
        """
        # TODO: Implement local post-optimization
        return baseline_solution

    def _materialize_plans(
        self,
        solution: dict,
        lookup_tables: list[FlowArmyTurnsLookupTable],
        external_options: list[ExternalPlanOption] | None = None
    ) -> list:
        """
        Phase 5: Convert chosen lookup entries into GatherCapturePlan objects.

        Responsibilities:
        - reconstruct chosen gather/capture island sets
        - derive concrete tile paths / moves
        - populate plan metrics consistently with old tests
        - include selected external options (intercepts, etc.) in the output
        """
        if not solution:
            return []

        plans = []
        asPlayer = self.friendlyGeneral.player
        plan_errors: list[tuple] = []  # Collect all errors for aggregated reporting

        # Track which external options were selected
        selected_external_ids: set[str] = set()

        for key, item in solution.items():
            # Handle external options (intercepts, etc.)
            if isinstance(item, ExternalPlanOption):
                selected_external_ids.add(key)
                # External options are already TilePlanInterface (e.g., InterceptionOptionInfo)
                # Return them directly without materialization
                plans.append(item.plan)
                if self.log_debug:
                    logbook.info(f"_materialize_plans: including external option {type(item.plan).__name__} "
                                 f"turns={item.turns} value={item.econ_value:.2f}")
                continue

            # Handle flow-based entries
            enriched = item
            border_pair = key
            capture_entry = enriched.capture_entry
            gather_entry = enriched.gather_entry

            # Reconstruct gather tile set from included friendly flow nodes.
            # When gather.turns==0 (no upstream gather needed), seed from the border pair's
            # own friendly island so we always have at least one root tile.
            # If the gather entry marks an incomplete island (only some of its tiles were
            # planned), restrict that island to just the planned tile count so that
            # plan._turns = len(gathing) + len(capping) - 1 matches combined_turn_cost.
            #
            # For partial gathers, we must select tiles closest to the capture border
            # (not by army value) to maintain physical connectivity with capture tiles.
            gathing: set = set()

            # First pass: collect all full islands and determine border adjacency
            # for partial island tile selection
            capture_island_ids = {n.island.unique_id for n in capture_entry.included_target_flow_nodes}
            # Also get IDs of other friendly islands in the gather chain for connectivity
            friendly_island_ids = {n.island.unique_id for n in gather_entry.included_friendly_flow_nodes}

            if self.log_debug:
                logbook.info(f'[GATHER_DEBUG] border_pair {border_pair.friendly_island_id}->{border_pair.target_island_id}')
                logbook.info(f'  friendly_flow_nodes: {[n.island.unique_id for n in gather_entry.included_friendly_flow_nodes]}')
                logbook.info(f'  incomplete_friendly_island_id: {gather_entry.incomplete_friendly_island_id}')
                logbook.info(f'  incomplete_friendly_tile_count: {gather_entry.incomplete_friendly_tile_count}')

            for flow_node in gather_entry.included_friendly_flow_nodes:
                island = flow_node.island
                if (gather_entry.incomplete_friendly_island_id is not None and
                        island.unique_id == gather_entry.incomplete_friendly_island_id):
                    tiles_to_gather = island.tile_count - gather_entry.incomplete_friendly_tile_count
                    if tiles_to_gather <= 0:
                        continue
                    # For partial gather, select tiles closest to capture islands
                    # AND tiles adjacent to other friendly islands in the chain
                    # to maintain physical connectivity
                    partial_gather_tiles = self._select_partial_gather_tiles(
                        island, capture_island_ids, tiles_to_gather,
                        other_friendly_island_ids=friendly_island_ids - {island.unique_id},
                        connected_tiles=gathing
                    )
                    if self.log_debug:
                        logbook.info(f'  island {island.unique_id}: partial gather {len(partial_gather_tiles)}/{island.tile_count} tiles: {sorted([(t.x, t.y) for t in partial_gather_tiles])}')
                    gathing.update(partial_gather_tiles)
                else:
                    if self.log_debug:
                        logbook.info(f'  island {island.unique_id}: full gather {len(island.tile_set)} tiles')
                    gathing.update(island.tile_set)
            if not gathing and self.island_builder is not None:
                fr_island = self.island_builder.tile_islands_by_unique_id.get(border_pair.friendly_island_id)
                if fr_island is not None:
                    gathing.update(fr_island.tile_set)

            # Reconstruct capture tile set from included target flow nodes.
            # Target-crossable friendly islands (team == self.team) on the capture path
            # are pass-through gather nodes, not captures — include them in gathing.
            capping: set = set()
            for flow_node in capture_entry.included_target_flow_nodes:
                island = flow_node.island
                # if island.team == self.team:
                #     gathing.update(island.tile_set)
                # else:
                #     capping.update(island.tile_set)

                # Check if this island has partial capture (incomplete capture)
                if (capture_entry.incomplete_target_island_id is not None and
                        island.unique_id == capture_entry.incomplete_target_island_id):
                    # Calculate how many tiles to capture from this island
                    # incomplete_target_tile_count = tiles NOT captured
                    tiles_to_capture = island.tile_count - capture_entry.incomplete_target_tile_count
                    if tiles_to_capture <= 0:
                        continue  # Skip this island entirely

                    # Select tiles closest to friendly territory (the border)
                    # Build a distance map from friendly tiles (gathered or border)
                    partial_capture_tiles = self._select_partial_capture_tiles(
                        island, gathing | capping, tiles_to_capture
                    )
                    capping.update(partial_capture_tiles)
                else:
                    capping.update(island.tile_set)

            if not gathing and not capping:
                if self.log_debug:
                    logbook.info(f'_materialize_plans: skipping border pair {border_pair.friendly_island_id}->{border_pair.target_island_id} (no tiles)')
                continue

            # Derive border root tiles: friendly tiles physically adjacent to capture tiles
            all_border_tiles: set = set()
            if gathing and capping:
                for t in capping:
                    for adj in t.movable:
                        if adj in gathing:
                            all_border_tiles.add(adj)

            root_tiles = all_border_tiles if all_border_tiles else gathing

            if self.log_debug:
                logbook.info(
                    f'_materialize_plans: {border_pair.friendly_island_id}->{border_pair.target_island_id} '
                    f'gathing={len(gathing)} capping={len(capping)} border_tiles={len(all_border_tiles)}'
                )
                logbook.info(
                    f'  gather_entry.turns={gather_entry.turns} '
                    f'gather_entry.included_friendly_flow_nodes count={len(gather_entry.included_friendly_flow_nodes)} '
                    f'islands=[{", ".join(str(n.island.unique_id) for n in gather_entry.included_friendly_flow_nodes)}]'
                )
                logbook.info(
                    f'  capture_entry.turns={capture_entry.turns} '
                    f'capture_entry.included_target_flow_nodes count={len(capture_entry.included_target_flow_nodes)} '
                    f'islands=[{", ".join(str(n.island.unique_id) for n in capture_entry.included_target_flow_nodes)}]'
                )
                logbook.info(f'  gathing tiles: {" | ".join(f"{t.x},{t.y}" for t in sorted(gathing, key=lambda t: (t.x, t.y)))}')
                logbook.info(f'  capping tiles: {" | ".join(f"{t.x},{t.y}" for t in sorted(capping, key=lambda t: (t.x, t.y)))}')
                logbook.info(f'  root_tiles: {" | ".join(f"{t.x},{t.y}" for t in sorted(root_tiles, key=lambda t: (t.x, t.y)))}')

            try:
                plan = Gather.convert_contiguous_capture_tiles_to_gather_capture_plan(
                    self.map,
                    rootTiles=root_tiles,
                    tiles=gathing,
                    negativeTiles=None,
                    searchingPlayer=asPlayer,
                    priorityMatrix=None,
                    useTrueValueGathered=False,
                    captures=capping,
                )
                plan._turns = len(gathing) + len(capping) - 1
            except Exception as ex:
                # Collect error for aggregated reporting
                error_details = {
                    'border_pair': f"{border_pair.friendly_island_id}->{border_pair.target_island_id}",
                    'gathing_count': len(gathing),
                    'capping_count': len(capping),
                    'root_tiles_count': len(root_tiles),
                    'gather_entry_turns': gather_entry.turns,
                    'capture_entry_turns': capture_entry.turns,
                    'exception': str(ex),
                    'exception_type': type(ex).__name__,
                }
                plan_errors.append((border_pair, error_details, ex))
                if self.log_debug:
                    logbook.info(f'_materialize_plans: skipping border pair {border_pair.friendly_island_id}->{border_pair.target_island_id} (plan build failed): {ex}')
                continue

            plans.append(plan)

        # Aggregate error reporting: log all failures together for visibility
        if plan_errors:
            error_summary = [
                f"\n{'='*80}",
                f"FLOW_EXPANSION_V2: PLAN MATERIALIZATION ERRORS",
                f"{'='*80}",
                f"Total plans attempted: {len(solution)}",
                f"Successful plans: {len(plans)}",
                f"Failed plans: {len(plan_errors)}",
                f"\nFAILED BORDER PAIRS:",
            ]
            for i, (border_pair, details, ex) in enumerate(plan_errors, 1):
                error_summary.append(
                    f"  {i}. {details['border_pair']}: {details['exception_type']}: {details['exception']}"
                )
                error_summary.append(
                    f"     (gathing={details['gathing_count']}, capping={details['capping_count']}, "
                    f"gather_turns={details['gather_entry_turns']}, capture_turns={details['capture_entry_turns']})"
                )
            error_summary.append(f"{'='*80}\n")
            logbook.error("\n".join(error_summary))

            # Always fail immediately if any plan has errors. ALWAYS. DONT FUCKING CHANGE THIS ASSHOLE.
            # We should never be unable to produce a plan.
            if len(plan_errors) > 0:
                all_errors_str = "\n\n".join([
                    f"{details['border_pair']}: {details['exception_type']}: {details['exception']}"
                    for _, details, _ in plan_errors
                ])
                raise AssertionError(
                    f"ALL {len(plan_errors)} plan materializations failed!\n\n"
                    f"Errors:\n{all_errors_str}\n\n"
                    f"Check logs above for detailed parameter dumps from each failed GCP creation."
                )

        return plans

    def _select_partial_capture_tiles(
        self,
        island,
        friendly_tiles: set,
        tiles_to_capture: int
    ) -> set:
        """
        Select a subset of tiles from an island for partial capture.

        Strategy:
        1. Build a distance map from friendly tiles (border/gathered tiles)
        2. Sort island tiles by distance to friendly tiles (closest first)
        3. Select tiles_to_capture closest tiles, prioritizing path connectivity

        This ensures we capture tiles on the path from the border, not random
        tiles deep in the island interior.

        Args:
            island: The island being partially captured
            friendly_tiles: Set of friendly tiles (border/gathered) adjacent to this island
            tiles_to_capture: Number of tiles to select from this island

        Returns:
            Set of tiles to include in the capture plan
        """
        if tiles_to_capture >= island.tile_count:
            return set(island.tile_set)

        if tiles_to_capture <= 0:
            return set()

        # Find tiles in the island that are adjacent to friendly tiles
        # These form the "entry points" into the island
        entry_points = set()
        for tile in island.tile_set:
            for neighbor in tile.movable:
                if neighbor in friendly_tiles:
                    entry_points.add(tile)
                    break

        if not entry_points:
            # No direct adjacency - use tiles closest to any friendly tile
            entry_points = set(island.tile_set)

        # Build a connected component from one entry point within the island
        # using BFS to find the shortest path through the island
        queue = deque()
        distances = {}
        selected = set()

        entry = min(entry_points, key=lambda t: (t.x, t.y))
        queue.append((entry, 0))
        distances[entry] = 0

        while queue and len(selected) < tiles_to_capture:
            tile, dist = queue.popleft()
            selected.add(tile)
            for neighbor in tile.movable:
                if neighbor in island.tile_set and neighbor not in distances:
                    distances[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        if self.log_debug:
            logbook.info(
                f'_select_partial_capture_tiles: island {island.unique_id} '
                f'(tiles={island.tile_count}) -> capturing {len(selected)} tiles: '
                f'{" | ".join(f"{t.x},{t.y}" for t in sorted(selected, key=lambda t: (t.x, t.y)))}'
            )

        return selected

    def _select_partial_gather_tiles(
            self,
            island: 'TileIsland',
            capture_island_ids: set[int],
            tiles_to_gather: int,
            other_friendly_island_ids: set[int] | None = None,
            connected_tiles: set['Tile'] | None = None
    ) -> set:
        """
        Select a subset of tiles from a gather island for partial gather.

        Strategy:
        1. Find tiles in the island that are adjacent to capture islands
           (these are the "exit points" toward the capture)
        2. ALSO find tiles adjacent to other friendly islands in the chain
           (to maintain connectivity through the gather path)
        3. Build distance map from exit points within the island using BFS
        4. Select tiles_to_gather closest tiles, prioritizing path connectivity

        This ensures we gather tiles on the path to the capture border,
        not random tiles deep in the island interior that would be disconnected.

        Args:
            island: The friendly island being partially gathered
            capture_island_ids: Set of island unique_ids that are capture targets
            tiles_to_gather: Number of tiles to select from this island
            other_friendly_island_ids: Set of other friendly island IDs in the gather chain

        Returns:
            Set of tiles to include in the gather plan
        """
        if tiles_to_gather >= island.tile_count:
            return set(island.tile_set)

        if tiles_to_gather <= 0:
            return set()

        # Find tiles in the island that are adjacent to capture islands
        # These form the "exit points" toward the capture
        connected_exit_points = set()
        exit_points = set()
        for tile in island.tile_set:
            for neighbor in tile.movable:
                neighbor_island = self.island_builder.tile_island_lookup.raw[neighbor.tile_index]
                if neighbor_island is not None:
                    if connected_tiles is not None and neighbor in connected_tiles:
                        connected_exit_points.add(tile)
                        break
                    # Check if neighbor is a capture island
                    if neighbor_island.unique_id in capture_island_ids:
                        exit_points.add(tile)
                        break
                    # ALSO check if neighbor is another friendly island in the chain
                    if (other_friendly_island_ids is not None and
                            neighbor_island.unique_id in other_friendly_island_ids):
                        exit_points.add(tile)
                        break

        if connected_exit_points:
            exit_points = connected_exit_points

        if not exit_points:
            logbook.info(f'NO DIRECT ADJACENCY TO CAPTURE...? {island}')
            # No direct adjacency to capture - use tiles closest to island border
            # (tiles that have neighbors outside this island)
            for tile in island.tile_set:
                for neighbor in tile.movable:
                    neighbor_island = self.island_builder.tile_island_lookup.get(neighbor)
                    if neighbor_island is None or neighbor_island.unique_id != island.unique_id:
                        exit_points.add(tile)
                        break

        if not exit_points:
            raise AssertionError(f'NO exit_points...? {island}')
            # Fallback: use all tiles as entry points
            exit_points = set(island.tile_set)

        # Build distance map from exit points within the island
        # using BFS to find the shortest path through the island
        queue = deque()
        distances = {}
        selected = set()

        exit_tile = min(exit_points, key=lambda t: (t.x, t.y))
        queue.append((exit_tile, 0))
        distances[exit_tile] = 0

        while queue and len(selected) < tiles_to_gather:
            tile, dist = queue.popleft()
            selected.add(tile)
            for neighbor in tile.movable:
                if neighbor in island.tile_set and neighbor not in distances:
                    distances[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        if self.log_debug:
            logbook.info(
                f'_select_partial_gather_tiles: island {island.unique_id} '
                f'(tiles={island.tile_count}) -> gathering {len(selected)} tiles: '
                f'{" | ".join(f"{t.x},{t.y}" for t in sorted(selected, key=lambda t: (t.x, t.y)))}'
            )
            logbook.info(
                f'  exit_points={len(exit_points)}, other_friendly_ids={other_friendly_island_ids}, capture_ids={capture_island_ids}'
            )

        return selected
