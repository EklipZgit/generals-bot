from __future__ import annotations

import typing
from dataclasses import dataclass

from BehaviorAlgorithms.Flow.FlowGraphModels import FlowGraphMethod, IslandFlowNode, IslandMaxFlowGraph
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.IterativeExpansion import FlowExpansionPlanOptionCollection
from Interfaces import MapMatrixInterface
from PerformanceTimer import PerformanceTimer

if typing.TYPE_CHECKING:
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
    """One lookup-table entry for exactly n turns"""
    turns: int
    required_army: int
    econ_value: float
    army_remaining: int
    gathered_army: int
    included_friendly_flow_nodes: tuple[IslandFlowNode, ...]
    included_target_flow_nodes: tuple[IslandFlowNode, ...]
    incomplete_friendly_island_id: int | None
    incomplete_friendly_tile_count: float | int
    incomplete_target_island_id: int | None
    incomplete_target_tile_count: float | int
    gather_index: int | None = None  # Populated in Step 2
    combined_value_density: float | None = None  # Populated in Step 2


@dataclass
class FlowArmyTurnsLookupTable:
    """Per border pair lookup table"""
    border_pair: FlowBorderPairKey
    capture_entries_by_turn: list[FlowTurnsEntry | None]
    gather_entries_by_turn: list[FlowTurnsEntry | None]
    best_capture_entries_prefix: list[FlowTurnsEntry | None]
    best_gather_entries_prefix: list[FlowTurnsEntry | None]
    metadata: dict  # Contains max_flow_across_border, friendly_stream_tile_count, etc.


@dataclass
class FlowExpansionV2DebugSnapshot:
    """Optional debug snapshot for tests/debug"""
    graph_stats: dict
    num_border_pairs: int
    entries_generated_per_border_pair: dict
    overlap_warnings: list[str]
    pruned_vs_kept_choices: dict


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
        self.friendly_general: Tile = map.generals[map.player_index]
        self.target_team: int = -1
        self.enemy_general: Tile | None = None

        # Configuration options
        self.method: FlowGraphMethod = FlowGraphMethod.MinCostFlow
        self.use_simple_flow_stream_maximization: bool = True
        self.log_debug: bool = True

        # Internal state
        self.flow_graph: IslandMaxFlowGraph | None = None
        self._networkx_finder: NetworkXFlowDirectionFinder | None = None  # Will be initialized when needed

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
            cutoffTime: float | None = None
    ) -> FlowExpansionPlanOptionCollection:
        """
        Main entry point - returns expansion options compatible with existing interface.

        This is the V2 implementation following the FlowExpansion.md plan.
        """
        # TODO: Implement the V2 algorithm phases:
        # Phase 1: Build explicit border stream extraction
        # Phase 1.5: Compute stream ordering metadata
        # Phase 2: Build per-border gather/capture lookup tables
        # Phase 3: Enrich capture entries with minimum gather support
        # Phase 4: Simple solution path via grouped knapsack (or post-optimization)
        # Phase 5: Convert chosen lookup entries into GatherCapturePlan

        # For now, return empty collection as scaffolding
        result = FlowExpansionPlanOptionCollection()
        result.flow_plans = []
        return result

    def _ensure_flow_graph_exists(self, islands: TileIslandBuilder) -> None:
        """Build or reuse the flow graph using existing NetworkXFlowDirectionFinder"""
        if self._networkx_finder is None:
            self._networkx_finder = NetworkXFlowDirectionFinder(
                self.map,
                self.perf_timer,
                self.log_debug,
                use_backpressure_from_enemy_general=True,
                friendly_general=self.friendly_general,
                invalid_flow_renderer=None  # TODO: Add renderer if needed
            )

        self._networkx_finder.configure(self.team, self.target_team, self.enemy_general)
        self._networkx_finder.ensure_flow_graph_exists(islands)

        # Build the flow graph using existing trusted components
        our_islands = islands.tile_islands_by_player_index[self.map.player_index]
        target_islands = islands.tile_islands_by_team_id[self.target_team]

        self.flow_graph = self._networkx_finder.build_max_flow_min_cost_flow_nodes(
            islands,
            our_islands,
            target_islands,
            self.map.player_index,
            turns=50,  # TODO: Pass actual turns parameter
            blockGatherFromEnemyBorders=True,
            negativeTiles=None,
            includeNeutralDemand=True,
            method=self.method
        )

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

        for target_island in islands.tile_islands_by_team_id[target_team]:
            for friendly_island in target_island.border_islands:
                if friendly_island.team != my_team:
                    continue

                # Skip target-crossable friendly islands from border-pair seeding
                if friendly_island.unique_id in target_crossable_islands:
                    if self.log_debug:
                        print(f"Skipping target-crossable friendly island {friendly_island.unique_id} "
                              f"from border-pair seeding with target {target_island.unique_id}")
                    continue

                # Verify there is actual flow support across the pair
                if self._is_flow_supported(friendly_island, target_island, flow_graph):
                    border_pair = FlowBorderPairKey(
                        friendly_island_id=friendly_island.unique_id,
                        target_island_id=target_island.unique_id
                    )
                    border_pairs.append(border_pair)

                    if self.log_debug:
                        print(f"Added border pair: friendly {friendly_island.unique_id} -> target {target_island.unique_id}")

        return border_pairs

    def _is_flow_supported(
        self,
        friendly_island: 'TileIsland',
        target_island: 'TileIsland',
        flow_graph: IslandMaxFlowGraph
    ) -> bool:
        """Check if there's flow support between friendly and target islands"""
        # Check both neutral-inclusive and enemy-only flow graphs
        for flow_lookup in [flow_graph.flow_node_lookup_by_island_inc_neut,
                          flow_graph.flow_node_lookup_by_island_no_neut]:
            if (friendly_island.unique_id in flow_lookup and
                target_island.unique_id in flow_lookup):
                friendly_node = flow_lookup[friendly_island.unique_id]
                target_node = flow_lookup[target_island.unique_id]

                # Check if there's flow from friendly to target or vice versa
                # through the flow graph structure
                for edge in friendly_node.flow_to:
                    if edge.target_flow_node.island.unique_id == target_island.unique_id:
                        return True

                # Also check reverse direction in case flow is oriented differently
                for edge in target_node.flow_to:
                    if edge.target_flow_node.island.unique_id == friendly_island.unique_id:
                        return True

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
        - it is bordered by more enemy island tile counts than friendly island tile counts
        - its parent island contains less than 1/5 of the friendly team's total tile count
        - the max-flow graph shows pathing into the friendly island from enemy islands
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

            # Count bordering enemy vs friendly tile counts
            enemy_border_tiles = 0
            friendly_border_tiles = 0

            for border_island in island.border_islands:
                if border_island.team == target_team:
                    enemy_border_tiles += border_island.tile_count
                elif border_island.team == my_team:
                    friendly_border_tiles += border_island.tile_count

            # Check if bordered by more enemy than friendly tiles
            if enemy_border_tiles <= friendly_border_tiles:
                continue

            # Check if island is small enough (< 1/5 of total friendly tiles)
            if island.tile_count >= threshold_tiles:
                continue

            # Check if flow graph shows pathing into this friendly island from enemy islands
            # This means checking if there are flow edges from enemy islands to this friendly island
            has_enemy_flow_in = False

            # Check both neutral-inclusive and enemy-only flow graphs
            for flow_lookup in [flow_graph.flow_node_lookup_by_island_inc_neut,
                              flow_graph.flow_node_lookup_by_island_no_neut]:
                if island.unique_id in flow_lookup:
                    flow_node = flow_lookup[island.unique_id]
                    # Check if any incoming flow from enemy islands
                    for edge in flow_node.flow_to:
                        if edge.target_flow_node.island.team == target_team:
                            has_enemy_flow_in = True
                            break
                    if has_enemy_flow_in:
                        break

            if has_enemy_flow_in:
                target_crossable.add(island.unique_id)
                if self.log_debug:
                    print(f"Marked island {island.unique_id} as target-crossable: "
                          f"enemy_border={enemy_border_tiles}, friendly_border={friendly_border_tiles}, "
                          f"size={island.tile_count}, threshold={threshold_tiles}")

        return target_crossable

    def _build_border_pair_stream_data(
        self,
        border_pair: FlowBorderPairKey,
        flow_graph: IslandMaxFlowGraph,
        target_crossable_islands: set[int]
    ) -> dict:
        """Phase 1: Build directional stream traversals for a border pair"""
        # TODO: Implement stream data building
        return {}

    def _preprocess_flow_stream_tilecounts(
        self,
        stream_data: dict,
        border_pair: FlowBorderPairKey
    ) -> tuple[list[FlowStreamIslandContribution], list[FlowStreamIslandContribution]]:
        """
        Phase 1.5: Compute stream ordering metadata.

        Returns (friendly_contributions, target_contributions) ordered by preference.
        """
        # TODO: Implement stream preprocessing with heuristics
        return [], []

    def _process_flow_into_flow_army_turns(
        self,
        border_pairs: list[FlowBorderPairKey],
        flow_graph: IslandMaxFlowGraph,
        target_crossable_islands: set[int]
    ) -> list[FlowArmyTurnsLookupTable]:
        """
        Phase 2: Build per-border gather/capture lookup tables.

        This is the main Step 1 from the prompt, clarified.
        """
        # TODO: Implement lookup table generation
        return []

    def _postprocess_flow_stream_gather_capture_lookup_pairs(
        self,
        lookup_tables: list[FlowArmyTurnsLookupTable]
    ) -> None:
        """
        Phase 3: Enrich capture entries with minimum gather support.

        For each border pair and each capture entry:
        - find the minimum-turn gather entry whose gathered_army >= capture.required_army
        - record gather_index, combined_turn_cost, combined_value_density
        """
        # TODO: Implement Step 2 enrichment
        pass

    def _solve_grouped_knapsack(
        self,
        lookup_tables: list[FlowArmyTurnsLookupTable],
        turn_budget: int
    ) -> dict:
        """
        Phase 4: Simple solution path via grouped knapsack.

        When use_simple_flow_stream_maximization is True:
        - each border pair is a multiple-choice group
        - each usable capture entry contributes one candidate item
        - solve grouped knapsack for turn_budget
        """
        # TODO: Implement grouped knapsack solver
        return {}

    def _post_optimize_locally(
        self,
        baseline_solution: dict,
        lookup_tables: list[FlowArmyTurnsLookupTable],
        turn_budget: int
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
        lookup_tables: list[FlowArmyTurnsLookupTable]
    ) -> list[GatherCapturePlan]:
        """
        Phase 5: Convert chosen lookup entries into GatherCapturePlan objects.

        Responsibilities:
        - reconstruct chosen gather/capture island sets
        - derive concrete tile paths / moves
        - populate plan metrics consistently with old tests
        """
        # TODO: Implement plan materialization
        return []
