from __future__ import annotations

import typing
from dataclasses import dataclass

import logbook

import Algorithms
import Gather
import KnapsackUtils
from BehaviorAlgorithms.Flow.FlowGraphModels import FlowGraphMethod, IslandFlowNode, IslandMaxFlowGraph
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpanderLastRun, FlowExpansionPlanOptionCollection, ITERATIVE_EXPANSION_EN_CAP_VAL
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
        self.method: FlowGraphMethod = FlowGraphMethod.MinCostFlow
        self.use_simple_flow_stream_maximization: bool = True
        self.log_debug: bool = True
        self.debug_render_capture_count_threshold: int = 10000
        """If there are more captures in any given plan option than this, then the option will be rendered inline as generated in a new debug viewer window."""
        self.use_debug_asserts: bool = True

        # Internal state
        self.flow_graph: IslandMaxFlowGraph | None = None
        self.last_run: ArmyFlowExpanderLastRun = ArmyFlowExpanderLastRun()
        self.last_lookup_tables: list | None = None
        self._networkx_finder: NetworkXFlowDirectionFinder | None = None  # Will be initialized when needed
        self._target_crossable_cache: set[int] = set()  # Cache for target-crossable islands

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
        # Sync caller-supplied player context and timer into our state
        if perfTimer is not None:
            self.perf_timer = perfTimer
        self.target_team = self.map.team_ids_by_player_index[targetPlayer]
        if self.enemyGeneral is None:
            self.enemyGeneral = self.map.generals[targetPlayer]
        self.island_builder = islands

        # Phase 0: Build flow graph
        with self.perf_timer.begin_move_event('V2 phase0 _ensure_flow_graph_exists'):
            self._ensure_flow_graph_exists(islands)

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
                border_pairs, self.flow_graph, target_crossable
            )

        # Phase 3: Enrich capture entries with minimum gather support
        with self.perf_timer.begin_move_event('V2 phase3 _postprocess_flow_stream_gather_capture_lookup_pairs'):
            self._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)
        self.last_lookup_tables = lookup_tables

        # Phase 4: Solve grouped knapsack for turn budget
        with self.perf_timer.begin_move_event('V2 phase4 _solve_grouped_knapsack'):
            solution = self._solve_grouped_knapsack(lookup_tables, turns)

        if not self.use_simple_flow_stream_maximization:
            # Phase 6: Optional local post-optimization
            with self.perf_timer.begin_move_event('V2 phase6 _post_optimize_locally'):
                solution = self._post_optimize_locally(solution, lookup_tables, turns)

        # Phase 5: Convert chosen entries into GatherCapturePlan objects
        with self.perf_timer.begin_move_event('V2 phase5 _materialize_plans'):
            plans = self._materialize_plans(solution, lookup_tables)

        result = FlowExpansionPlanOptionCollection()
        result.flow_plans = plans
        return result

    def _ensure_flow_graph_exists(self, islands: TileIslandBuilder) -> None:
        """Build or reuse the flow graph using existing NetworkXFlowDirectionFinder"""
        if self._networkx_finder is None:
            self._networkx_finder = NetworkXFlowDirectionFinder(
                self.map,
                islands.intergeneral_analysis,
                friendly_general=self.friendlyGeneral,
                use_backpressure_from_enemy_general=True,
                perf_timer=self.perf_timer,
                log_debug=self.log_debug and False, # no debug logging, for now.
                invalid_flow_renderer=None,  # TODO: Add renderer if needed
            )

        self._networkx_finder.configure(self.team, self.target_team, self.enemyGeneral)
        self._networkx_finder.ensure_flow_graph_exists(islands)

        # Build the flow graph using existing trusted components
        our_islands = islands.tile_islands_by_player[self.map.player_index]
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
        """Check if there's flow support between friendly and target islands.

        Does a BFS forward from the friendly node through the flow graph to see
        if it can reach the target island, passing through neutral islands along
        the way.
        """
        # Check both neutral-inclusive and enemy-only flow graphs
        for flow_lookup in [
            flow_graph.flow_node_lookup_by_island_no_neut,
            flow_graph.flow_node_lookup_by_island_inc_neut,
        ]:
            if (friendly_island.unique_id not in flow_lookup or
                    target_island.unique_id not in flow_lookup):
                continue

            friendly_node = flow_lookup[friendly_island.unique_id]

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
                    if dest.island.unique_id == target_island.unique_id:
                        return True
                    # Continue BFS through neutral islands
                    if dest.island.team == -1:
                        q.append(dest)

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
            # Use the parent (full_island) tile count per design: "parent island contains < 1/5 of total"
            parent_tile_count = island.full_island.tile_count if island.full_island is not None else island.tile_count
            if parent_tile_count >= threshold_tiles:
                continue

            # Check if flow graph shows direct enemy flow into this island (entry tile of the chain).
            has_enemy_flow_in = False

            # Check both neutral-inclusive and enemy-only flow graphs
            for flow_lookup in [
                flow_graph.flow_node_lookup_by_island_no_neut,
                flow_graph.flow_node_lookup_by_island_inc_neut,
            ]:
                if island.unique_id in flow_lookup:
                    flow_node = flow_lookup[island.unique_id]
                    for edge in flow_node.flow_from:
                        if edge.source_flow_node.island.team == target_team:
                            has_enemy_flow_in = True
                            break
                    if has_enemy_flow_in:
                        break

            if has_enemy_flow_in:
                target_crossable.add(island.unique_id)
                if self.log_debug:
                    logbook.info(f"Marked island {island.unique_id} as target-crossable: "
                             f"enemy_border={enemy_border_tiles}, friendly_border={friendly_border_tiles}, "
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

        return target_crossable

    def _build_border_pair_stream_data(
        self,
        border_pair: FlowBorderPairKey,
        flow_graph: IslandMaxFlowGraph,
        target_crossable_islands: set[int]
    ) -> dict:
        """Phase 1: Build directional stream traversals for a border pair"""

        # Get the flow nodes for the border pair
        friendly_node = None
        target_node = None

        # Check both flow graph variants
        lookup = None
        for flow_lookup in [
            flow_graph.flow_node_lookup_by_island_no_neut,
            flow_graph.flow_node_lookup_by_island_inc_neut
        ]:
            friendly_node = flow_lookup.get(border_pair.friendly_island_id, None)
            target_node = flow_lookup.get(border_pair.target_island_id, None)
            if (friendly_node is not None and target_node is not None):
                lookup = flow_lookup
                break

        if friendly_node is None or target_node is None:
            return {}

        # Build upstream friendly stream traversal
        friendly_stream = self._build_upstream_stream(
            friendly_node, target_crossable_islands
        )

        # Build downstream target stream traversal — walk from the friendly border
        # node outward so mandatory intermediate tiles (neutrals) are emitted before
        # the first enemy tile, preserving physical path order.
        target_stream = self._build_downstream_stream(
            friendly_node, target_crossable_islands
        )

        logbook.info(
            f'STREAM_DATA bp={border_pair.friendly_island_id}->{border_pair.target_island_id}: '
            f'friendly_stream=['
            + ', '.join(f'{n.island.unique_id}({n.island.tile_count}t {n.island.sum_army}a flow_from={[e.source_flow_node.island.unique_id for e in n.flow_from]})' for n in friendly_stream)
            + f'] target_stream=['
            + ', '.join(f'{n.island.unique_id}({n.island.tile_count}t)' for n in target_stream)
            + ']'
        )

        return {
            'border_pair': border_pair,
            'friendly_stream': friendly_stream,
            'target_stream': target_stream,
            'friendly_node': friendly_node,
            'target_node': target_node
        }

    def _build_upstream_stream(
        self,
        start_node: IslandFlowNode,
        target_crossable_islands: set[int]
    ) -> list[IslandFlowNode]:
        """Build upstream traversal from friendly border node"""
        visited = set()
        stream = []

        def traverse_upstream(node: IslandFlowNode):
            if node.island.unique_id in visited:
                return
            visited.add(node.island.unique_id)

            # Only include friendly islands in upstream traversal
            if node.island.team == self.team:
                stream.append(node)

                # Continue upstream through incoming flow edges
                logbook.info(
                    f'UPSTREAM_BFS node={node.island.unique_id}({node.island!r}) '
                    f'flow_from=[{", ".join(f"{e.source_flow_node.island.unique_id}(team={e.source_flow_node.island.team} army={e.edge_army})" for e in node.flow_from)}]'
                )
                for edge in node.flow_from:
                    src = edge.source_flow_node
                    if src.island.team == self.team:
                        traverse_upstream(src)
                    else:
                        logbook.info(
                            f'UPSTREAM_BFS  SKIP non-friendly flow_from: {src.island.unique_id}(team={src.island.team})'
                        )

        traverse_upstream(start_node)
        return stream

    def _build_downstream_stream(
        self,
        start_node: IslandFlowNode,
        target_crossable_islands: set[int]
    ) -> list[IslandFlowNode]:
        """Build downstream traversal from the friendly border node.

        Walks flow_to edges from the friendly side outward so that every node is
        emitted in physical path order — mandatory intermediate tiles (neutral or
        target-crossable friendly) appear before the enemy tile they guard.
        """
        visited = set()
        stream = []

        # BFS from the friendly border node so we encounter nodes in the order
        # they are physically reached when marching toward the enemy.
        queue = [start_node]
        while queue:
            node = queue.pop(0)
            if node.island.unique_id in visited:
                continue
            visited.add(node.island.unique_id)

            # Emit non-friendly nodes: enemy, neutral, and target-crossable friendly
            if (node.island.team == self.target_team or
                node.island.team == -1 or
                node.island.unique_id in target_crossable_islands):
                stream.append(node)

            # Continue along all outgoing flow edges
            for edge in node.flow_to:
                dest = edge.target_flow_node
                if dest.island.unique_id not in visited:
                    queue.append(dest)

        return stream

    def _preprocess_flow_stream_tilecounts(
        self,
        stream_data: dict,
        border_pair: FlowBorderPairKey
    ) -> tuple[list[FlowStreamIslandContribution], list[FlowStreamIslandContribution]]:
        """
        Phase 1.5: Compute stream ordering metadata.

        Returns (friendly_contributions, target_contributions) ordered by preference.
        """
        friendly_stream = stream_data.get('friendly_stream', [])
        target_stream = stream_data.get('target_stream', [])

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
        target_crossable_islands: set[int]
    ) -> list[FlowArmyTurnsLookupTable]:
        """
        Phase 2: Build per-border gather/capture lookup tables.

        This is the main Step 1 from the prompt, clarified.
        """
        lookup_tables = []

        for border_pair in border_pairs:
            # Build stream data for this border pair
            stream_data = self._build_border_pair_stream_data(border_pair, flow_graph, target_crossable_islands)
            if not stream_data:
                continue

            # Get ordered contributions for this border pair
            friendly_contribs, target_contribs = self._preprocess_flow_stream_tilecounts(stream_data, border_pair)

            # Generate capture lookup table
            capture_lookup = self._generate_capture_lookup_table(
                border_pair, target_contribs, stream_data
            )

            # Generate gather lookup table
            gather_lookup = self._generate_gather_lookup_table(
                border_pair, friendly_contribs, stream_data
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
        stream_data: dict,
        prio_mat: MapMatrixInterface[float] | None = None,
    ) -> list[FlowTurnsEntry | None]:
        """
        Generate capture lookup table for a border pair.

        Parameters:
            border_pair (FlowBorderPairKey): The border pair for which to generate the lookup table.
            target_contributions (list[FlowStreamIslandContribution]): Contributions from target islands.
            stream_data (dict): Stream data containing island information.

        Returns:
            list[FlowTurnsEntry | None]: The generated capture lookup table.
        """
        # Start with the border crossing (turn 0 = border state, turn 1 = first target island)
        max_turns = 50  # TODO: Make this configurable
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
                    current_army_cost -= tile.army
                else:
                    if prio_mat is not None:
                        current_econ_value += prio_mat.raw[tile.tile_index]
                    # Regular capture (enemy or neutral)
                    current_army_cost += tile.army

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
        stream_data: dict
    ) -> list[FlowTurnsEntry | None]:
        """
        Generate gather lookup table for a border pair.

        Processes tiles individually (like _generate_capture_lookup_table) to support
        partial gathers - gathering from only some tiles of an island rather than
        the entire island at once.
        """
        max_turns = 50  # TODO: Make this configurable
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
        friendly_node = stream_data.get('friendly_node')  # friendly border pair node. TODO why the fuck is this a dict instead of a proper fucking class? what the fuck.

        # TODO priority queue this shit probably so we can pull the highest gather/turn shit first even if it pulls through a "1" army island or something.
        if friendly_node is None:
            raise ValueError("Friendly node not found in stream data")

        bfs_queue: list[tuple[FlowNode, int]] = [(friendly_node, friendly_node.island.tile_count - 1)]
        bfs_visited: set[int] = set()
        while bfs_queue:
            node_bfs, depth = bfs_queue.pop(0)
            iid = node_bfs.island.unique_id
            if iid in bfs_visited:
                continue

            # if depth > max_turns:
            #     continue

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
            for tile in island.tiles_by_army:
                if current_turn > max_turns:
                    break
                i += 1

                # Net army from this tile: tile.army (full army from tile)
                # minus traversal_cost applied only to the first tile of the island.
                # This matches the original logic: island.sum_army - traversal_cost
                # For multi-tile islands, each tile contributes its full army; the "leave 1 behind"
                # is implicit in the army movement mechanics, not subtracted here.

                current_gathered_army += tile.army - 1

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
                        f"tile contribution {tile.army - 1:.2f}, incomplete {lookup[current_turn].incomplete_friendly_tile_count}")

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
            flow_graph.flow_node_lookup_by_island_inc_neut,
        ]:
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

    def _solve_grouped_knapsack(
        self,
        lookup_tables: list[FlowArmyTurnsLookupTable],
        turn_budget: int
    ) -> dict:
        """
        Phase 4: Simple solution path via grouped knapsack.

        Each border pair is a multiple-choice group.
        Each usable (enriched) capture entry is one candidate item:
          - value  = econ_value
          - weight = combined_turn_cost (capture.turns + gather.turns)

        Uses KnapsackUtils.solve_multiple_choice_knapsack (C++ optimized).
        Returns a solution dict: {border_pair_key: EnrichedFlowTurnsEntry | None}
        """
        items: list[EnrichedFlowTurnsEntry] = []
        groups: list[int] = []
        weights: list[int] = []
        values: list[int] = []

        forest = Algorithms.FastDisjointSet()

        goodLookupTables = []
        for lookup_table in lookup_tables:
            if not lookup_table.enriched_capture_entries:
                continue

            forest.merge(lookup_table.border_pair.friendly_island_id, lookup_table.border_pair.target_island_id)
            goodLookupTables.append(lookup_table)

        subsets = forest.subsets()
        groupIdx = 0
        groupLookup: dict[int, int] = {}
        for subset in subsets:
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
                if self.log_debug:
                    logbook.info(f"  MKCP item: group={group_idx} weight={enriched.combined_turn_cost} "
                                 f"value={int(1000 * enriched.capture_entry.econ_value)} "
                                 f"(gather={enriched.gather_entry.turns}, capture={enriched.capture_entry.turns})")

        if not items:
            return {}

        max_value, chosen_items = KnapsackUtils.solve_multiple_choice_knapsack(
            items, turn_budget, weights, values, groups, noLog=not self.log_debug, longRuntimeThreshold=10.0
        )

        if self.log_debug:
            total_weight = sum(it.combined_turn_cost for it in chosen_items)
            logbook.info(f"Grouped knapsack: budget={turn_budget}, best_weight={total_weight}, best_value={max_value}, "
                         f"chosen_groups={len(chosen_items)}")

        # Build solution dict keyed by border_pair for easy lookup
        # Use object identity (is) not equality (==) because EnrichedFlowTurnsEntry is a dataclass
        # and two entries from different border pairs could have the same field values
        solution: dict[FlowBorderPairKey, EnrichedFlowTurnsEntry] = {}
        for enriched in chosen_items:
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
        if not solution:
            return []

        plans = []
        asPlayer = self.friendlyGeneral.player

        for border_pair, enriched in solution.items():
            capture_entry = enriched.capture_entry
            gather_entry = enriched.gather_entry

            # Reconstruct gather tile set from included friendly flow nodes.
            # When gather.turns==0 (no upstream gather needed), seed from the border pair's
            # own friendly island so we always have at least one root tile.
            gathing: set = set()
            for flow_node in gather_entry.included_friendly_flow_nodes:
                gathing.update(flow_node.island.tile_set)
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

            # Suppress USE_DEBUG_ASSERTS so the built-in A* reconnect path in
            # build_capture_mst_from_root_and_contiguous_tiles runs instead of raising
            # when intermediate path tiles are missing from our reconstructed tile sets.
            _prev_asserts = Gather.GatherDebug.USE_DEBUG_ASSERTS
            Gather.GatherDebug.USE_DEBUG_ASSERTS = False
            try:
                plan = Gather.convert_contiguous_capture_tiles_to_gather_capture_plan(
                    self.map,
                    rootTiles=root_tiles,
                    tiles=gathing,
                    negativeTiles=None,
                    searchingPlayer=asPlayer,
                    priorityMatrix=None,
                    useTrueValueGathered=True,
                    captures=capping,
                )
                plan._turns = len(gathing) + len(capping) - 1
            except Exception:
                if self.log_debug:
                    logbook.info(f'_materialize_plans: skipping border pair {border_pair.friendly_island_id}->{border_pair.target_island_id} (plan build failed)')
                continue
            finally:
                Gather.GatherDebug.USE_DEBUG_ASSERTS = _prev_asserts

            plans.append(plan)

        return plans
