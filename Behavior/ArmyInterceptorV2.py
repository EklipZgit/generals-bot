from __future__ import annotations

import heapq
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import logbook

import SearchUtils

from Behavior.ArmyInterceptionModels import (
    DEBUG_BYPASS_BAD_INTERCEPTIONS,
    GENERAL_CAP_VALUE,
    NEUTRAL_CAP_VALUE,
    OTHER_PARTY_CAP_VALUE,
    OWNED_CITY_CAP_VALUE_BONUS,
    RECAPTURE_VALUE,
    TARGET_CAP_VALUE,
    ArmyInterception,
    InterceptPointTileInfo,
    InterceptionOptionInfo,
    ThreatBlockInfo,
    ThreatValueInfo,
)
from DangerAnalyzer import ThreatObj, ThreatType
from Path import Path
from Strategy import OpponentTracker
from base.client.map import MapBase, Tile


V2_MAX_OWNERSHIP_SOURCES = 3
V2_MAX_LARGEST_ARMY_SOURCES = 2
V2_PATH_SLACK = 2
# When False (the default), every native table winner is re-verified by running
# V1's _evaluate_intercept_path_into_table on a reconstructed Path so the real
# option table is written by V1 itself. When True, the native scorer's values
# are written into InterceptionOptionInfo objects directly, skipping the V1
# winner re-evaluation entirely. Only enable after the shadow A/B shows the
# native port agrees with V1 on essentially every emitted entry.
V2_SKIP_V1_WINNER_REEVAL = True
# When True (the default), V2's candidate set comes from a native port of
# V1's per-choke breadth_first_dynamic_max_per_tile_per_distance search, so
# exactly the paths V1's own search would produce are evaluated. When False,
# V2 falls back to the earlier matrix-layered candidate generation (multi-
# source reach + per-source layered reaches + ownership/largest-army source
# selection), which only approximates V1's candidate set.
V2_USE_V1_EXACT_SEARCH = True


class V2ThreatDamageMode(Enum):
    THREAT_PATHS = 'threat_paths'
    UNRESTRICTED = 'unrestricted'


V2_THREAT_DAMAGE_MODE: V2ThreatDamageMode = V2ThreatDamageMode.THREAT_PATHS
UNREACHABLE_DISTANCE = 1000
UNREACHED_ARMY = -1_000_000_000
NO_PARENT = -1


class ArmyInterceptorV1Protocol(Protocol):
    __slots__ = ()

    map: MapBase
    log_debug: bool

    def _get_max_interception_search_depth(
        self,
        threats: list[ThreatObj],
    ) -> int:
        """Return the V1 threat-dependent search depth."""
        ...

    def _build_average_enemy_position_by_turn(
        self,
        interception: ArmyInterception,
        maxDepth: int,
    ) -> list[tuple[float, float] | None]:
        """Build average enemy positions by turn."""
        ...

    def filter_interception_best_points(
        self,
        interception: ArmyInterception,
        maxDepth: int,
        positionsByTurn: list[tuple[float, float] | None],
    ) -> None:
        """Prune each choke's max_search_dist exactly like V1."""
        ...

    def _get_middlest_intercept_tiles_by_distance(
        self,
        interception: ArmyInterception,
    ) -> set[Tile]:
        """Return V1's middlest-per-distance intercept tile set."""
        ...

    def _evaluate_intercept_path_into_table(
        self,
        interception: ArmyInterception,
        interceptInfo: InterceptPointTileInfo,
        path: Path,
        turnsLeftInCycle: int,
        opponentTracker: OpponentTracker,
        otherThreatsBlockingTiles: dict[Tile, ThreatBlockInfo] | None,
        averageEnemyPositionByTurn: list[tuple[float, float] | None],
        bestInterceptTable: dict[int, InterceptionOptionInfo],
    ) -> bool:
        """Evaluate a single path with the V1 option scorer."""
        ...


@dataclass(slots=True)
class ChokeBudgetMatrix:
    budget: list[int]


@dataclass(slots=True)
class ChokeBudgetBuildResult:
    matrix: ChokeBudgetMatrix
    candidate_sources: list[Tile]


@dataclass(slots=True)
class ArmyStepDeltaMatrix:
    friendly_step_delta: list[int]
    enemy_step_delta: list[int]
    friendly_tile_mask: bytearray
    negative_tile_mask: bytearray
    friendly_delta_computed: bytearray
    enemy_delta_computed: bytearray
    threat_players: list[int]


@dataclass(slots=True)
class ThreatReachMatrix:
    tiles_by_index: list[Tile]
    max_depth: int
    enemy_turn: list[int]
    enemy_army: list[int]
    threat_path_mask: list[int]
    downstream_damage: list[float]
    choke_budget: ChokeBudgetMatrix
    step_deltas: ArmyStepDeltaMatrix
    candidate_sources: list[Tile]
    blocking_sources: list[Tile]


@dataclass(slots=True)
class FriendlyMultiSourceMatrix:
    candidate_sources: list[Tile]
    turns: list[int]
    army_at_arrival: list[int]
    source_index: list[int]
    ownership_scores: list[float]
    selected_source_indices: list[int]


@dataclass(slots=True)
class SourceLayeredReach:
    source_index: int
    source_tile: Tile
    max_depth: int
    states_by_depth: list[dict[int, tuple[int, int]]]


@dataclass(slots=True)
class V2InterceptCandidate:
    source_index: int
    layer_index: int
    choke_tile: Tile
    depth: int
    friendly_army: int
    prescreen_value: float


@dataclass(slots=True)
class V2CandidatePath:
    candidate: V2InterceptCandidate
    path: Path
    friendly_army_at_choke: int


@dataclass(slots=True)
class V2StageTimings:
    stage_a_seconds: float = 0.0
    stage_b_seconds: float = 0.0
    stage_c_seconds: float = 0.0
    stage_d_seconds: float = 0.0
    stage_e_seconds: float = 0.0


@dataclass(slots=True)
class V2NativeEvalContext:
    """Per-call precomputed inputs for the native port of V1's option scorer.

    Mirrors the free variables that V1's _evaluate_intercept_path_into_table
    reads for every candidate path, so the port only pays matrix/dict lookups
    inside the per-candidate loops.
    """

    interception: ArmyInterception
    tiles_by_index: list[Tile]
    turns_left_in_cycle: int
    map_turn: int
    map_player_index: int
    team_ids: list[int]
    friendly_team: int
    first_threat_team: int
    """team id of interception.threats[0].threatPlayer (econ target player)."""
    first_bmap_raw: list[int]
    """interception.threats[0].armyAnalysis.bMap.raw -> interceptPointDist."""
    best_threat: ThreatObj
    best_threat_team: int
    best_threat_players: list[int]
    """map.get_teammates(best_threat.threatPlayer) for _advance_enemy_physical_army."""
    best_bmap_raw: list[int]
    """best_enemy_threat.armyAnalysis.bMap.raw -> interceptDistFromTarget."""
    best_tile_distances_lookup: dict[int, list[Tile]]
    enemy_tiles: list[Tile]
    """Best enemy threat path node tiles in forward order (index == node index)."""
    enemy_prefix_army: list[int]
    """enemy_prefix_army[k] = enPhysicalArmy after processing enemy node k."""
    enemy_path_tile_set: set[Tile]
    enemy_path_value: int
    """int(best_enemy_threat.path.value), the backward-walk army seed."""
    target_is_city: bool
    sparse_bonus: float
    sparse_len_cutoff: float
    contestable_city_dist: int
    opponent_tracker: OpponentTracker
    other_blocking: dict[Tile, ThreatBlockInfo] | None
    debug_bad_cutoff: int
    threat_values: list[ThreatValueInfo]
    threats: list[ThreatObj]
    target_dist_raw: list[int]
    """distance_mapper matrix to interception.target_tile for replace ties."""
    delay_split_by_source: dict[int, tuple[bool, bool]]
    """Per-source-tile cache of the ported _should_delay_or_split result."""
    city_skip_by_source: dict[int, bool]
    """Per-source-tile cache of _is_intercept_from_threatened_friendly_city."""


@dataclass(slots=True)
class V2NativeCollisionResult:
    """Ported output of V1's _get_result_of_executing_paths_to_intercept_point.

    Carries enemy-path-node INDICES instead of PathMove objects; -1 mirrors a
    None PathMove.
    """

    enemy_intercept_index: int
    enemy_physical_army_at_intercept: int
    friendly_army_at_intercept: int
    best_case_intercept_turn: int
    worst_case_intercept_turn: int


@dataclass(slots=True)
class V2NativeOptionEntry:
    """One native copy of a row V1 would write to bestInterceptTable[curDist]."""

    cur_dist: int
    this_value: float
    damage_blocked: float
    enemy_army_left_after_intercept: int
    best_case_intercept_moves: int
    worst_case_intercept_moves: int
    recapture_turns: int
    required_delay: int
    friendly_army_reaching_intercept: int
    candidate_eval: V2NativeCandidateEval
    """Back-reference used to rebuild the real Path for winning entries."""


@dataclass(slots=True)
class V2NativeCandidateEval:
    """Native evaluation of one retained candidate's tile list."""

    candidate: V2InterceptCandidate
    tile_indices: list[int]
    move_half_flags: list[bool]
    """Parallel to tile_indices; index j mirrors PathMove.move_half on node j."""
    entries: list[V2NativeOptionEntry]
    evaluation_continued: bool
    """False mirrors V1's return False (bestCaseInterceptMoves == 1000)."""
    skip_reason: str
    """Why no entries were emitted, for shadow mismatch diagnostics."""


class ArmyInterceptorV2:
    __slots__ = (
        'v1',
        'last_stage_timings',
        'damage_estimate_cache',
        'last_native_evals',
        'last_average_enemy_position_by_turn',
        '_fallback_override',
    )

    v1: ArmyInterceptorV1Protocol
    last_stage_timings: V2StageTimings
    damage_estimate_cache: dict[tuple[int, int, int], float]
    last_native_evals: list[V2NativeCandidateEval]
    last_average_enemy_position_by_turn: list[tuple[float, float] | None]
    _fallback_override: bool | None

    def __init__(self, v1: ArmyInterceptorV1Protocol) -> None:
        """Initialize V2 with the V1 surface it reuses."""
        self.v1 = v1
        self.last_stage_timings = V2StageTimings()
        self.damage_estimate_cache = {}
        self.last_native_evals = []
        self.last_average_enemy_position_by_turn = []
        self._fallback_override = None

    def get_intercept_plan_options(
        self,
        interception: ArmyInterception,
        turnsLeftInCycle: int,
        opponentTracker: OpponentTracker,
        otherThreatsBlockingTiles: dict[Tile, ThreatBlockInfo] | None,
    ) -> dict[int, InterceptionOptionInfo]:
        """Find a bounded set of V2 candidate paths and score them with V1."""
        # V1 retries its plan call with includeNonMiddlestPositiveDepthFallback
        # when the first attempt produced no options, but the V1 dispatch to
        # this method does not forward that flag (ArmyInterceptor is read-only
        # for this work). V2 writes interception.middlest_intercept_tiles on
        # every call it handles, so a populated middlest set paired with an
        # empty intercept_options marks the fallback retry. The shadow A/B
        # harness sets _fallback_override explicitly because V1's first-pass
        # run populates middlest before the shadow V2 call, which would make
        # the marker infer fallback on every primary call.
        if self._fallback_override is not None:
            include_non_middlest_fallback = self._fallback_override
        else:
            include_non_middlest_fallback = (
                len(interception.middlest_intercept_tiles) > 0
                and not interception.intercept_options)
        # V1 searches every middlest choke up to its filtered max_search_dist,
        # which is bounded by _get_max_interception_search_depth but NOT by
        # turnsLeftInCycle, so the V1 search bound is used unclamped here.
        max_depth = self.v1._get_max_interception_search_depth(
            interception.threats)
        self.last_stage_timings = V2StageTimings()
        self.damage_estimate_cache.clear()
        if not interception.common_intercept_chokes or max_depth <= 0:
            return {}

        stages_started_at = time.perf_counter()
        # Prologue replicating V1's _get_intercept_plan_options preamble so the
        # V2 candidate set is admissible under the same gates: the funnel
        # search region, the adjacency-pruned per-choke search depths, and the
        # middlest-tile selection.
        allowed_search_region = self.build_allowed_search_region(interception)
        average_enemy_position_by_turn = (
            self.v1._build_average_enemy_position_by_turn(
                interception,
                max_depth))
        self.last_average_enemy_position_by_turn = (
            average_enemy_position_by_turn)
        self.v1.filter_interception_best_points(
            interception,
            max_depth,
            positionsByTurn=average_enemy_position_by_turn)
        middlest_tiles = (
            self.v1._get_middlest_intercept_tiles_by_distance(interception))
        interception.middlest_intercept_tiles = middlest_tiles
        choke_search_depths = self.resolve_choke_search_depths(
            interception,
            middlest_tiles,
            include_non_middlest_fallback)

        threat_reach = self.build_threat_reach_matrix(
            interception,
            max_depth,
            turnsLeftInCycle,
            choke_search_depths,
            allowed_search_region)
        stage_a_seconds = time.perf_counter() - stages_started_at

        stage_started_at = time.perf_counter()
        native_table: dict[int, V2NativeOptionEntry]
        candidates: list[V2InterceptCandidate] = []
        friendly_reach: FriendlyMultiSourceMatrix | None = None
        if V2_USE_V1_EXACT_SEARCH:
            context = self._build_native_eval_context(
                interception,
                threat_reach,
                turnsLeftInCycle,
                opponentTracker,
                otherThreatsBlockingTiles,
                average_enemy_position_by_turn)
            native_table = self.evaluate_v1_search_paths_native(
                interception,
                context,
                choke_search_depths,
                average_enemy_position_by_turn,
                allowed_search_region,
                threat_reach.tiles_by_index)
        else:
            friendly_reach = self.build_friendly_multi_source_matrix(
                interception,
                threat_reach,
                choke_search_depths)
            layered_reaches = [
                self.build_source_layered_reach(
                    threat_reach,
                    source_index)
                for source_index in friendly_reach.selected_source_indices
            ]
            candidates = self.build_intercept_candidates(
                interception,
                threat_reach,
                friendly_reach,
                layered_reaches,
                turnsLeftInCycle,
                choke_search_depths)
            native_table = self.evaluate_candidates_native(
                interception,
                threat_reach,
                layered_reaches,
                candidates,
                turnsLeftInCycle,
                opponentTracker,
                otherThreatsBlockingTiles,
                average_enemy_position_by_turn)
        stage_b_seconds = time.perf_counter() - stage_started_at
        stage_c_seconds = 0.0
        stage_d_seconds = 0.0

        stage_started_at = time.perf_counter()
        best_intercept_table: dict[int, InterceptionOptionInfo] = {}
        if V2_SKIP_V1_WINNER_REEVAL:
            self._write_native_table_options(
                interception,
                threat_reach,
                native_table,
                best_intercept_table)
        else:
            # Re-verify each unique winning candidate with V1's own scorer on
            # a reconstructed Path so the emitted option table is identical to
            # evaluating those candidates through V1 directly. One V1 eval
            # writes every curDist row for its candidate, so dedupe the
            # winners that own multiple table keys instead of re-evaluating
            # the same path once per key.
            verified_eval_ids: set[int] = set()
            for cur_dist in sorted(native_table):
                winner_eval = native_table[cur_dist].candidate_eval
                winner_eval_id = id(winner_eval)
                if winner_eval_id in verified_eval_ids:
                    continue
                verified_eval_ids.add(winner_eval_id)
                intercept_info = interception.common_intercept_chokes[
                    winner_eval.candidate.choke_tile]
                winner_path = self.build_path_from_tile_indices(
                    threat_reach.tiles_by_index,
                    winner_eval.tile_indices)
                self.v1._evaluate_intercept_path_into_table(
                    interception,
                    intercept_info,
                    winner_path,
                    turnsLeftInCycle,
                    opponentTracker,
                    otherThreatsBlockingTiles,
                    average_enemy_position_by_turn,
                    best_intercept_table)
        # V1's bestInterceptTable key order is the order each curDist key was
        # first written across every evaluated candidate in eval order
        # (choke-major, dist-ascending). Order-sensitive consumers like
        # BotDefense.build_defense_intercept_plan replace only on a strict
        # `optVt > vt`, so the first-iterated tied option wins — rebuild the
        # emitted dict in V1's first-write order so econValue/turn ratio
        # ties resolve to the same option V1 would emit first.
        # shadow_ab.py SAME vs V2_NEW_BEST classification: every residual
        # V2_NEW_BEST row had identical option tables with v1_ratio ==
        # v2_ratio and a different tied best pick.
        first_write_rank: dict[int, int] = {}
        for ranked_eval in self.last_native_evals:
            for ranked_entry in ranked_eval.entries:
                if ranked_entry.cur_dist not in first_write_rank:
                    first_write_rank[ranked_entry.cur_dist] = (
                        len(first_write_rank))
        best_intercept_table = {
            cur_dist: best_intercept_table[cur_dist]
            for cur_dist in sorted(
                best_intercept_table,
                key=first_write_rank.__getitem__)
        }
        stage_e_seconds = time.perf_counter() - stage_started_at
        self.last_stage_timings = V2StageTimings(
            stage_a_seconds=stage_a_seconds,
            stage_b_seconds=stage_b_seconds,
            stage_c_seconds=stage_c_seconds,
            stage_d_seconds=stage_d_seconds,
            stage_e_seconds=stage_e_seconds)

        if self.v1.log_debug:
            if friendly_reach is not None:
                selected_source_summary = ', '.join(
                    f'{friendly_reach.candidate_sources[source_index]} '
                    f'ownership={friendly_reach.ownership_scores[source_index]:.2f} '
                    f'army={friendly_reach.candidate_sources[source_index].army}'
                    for source_index in friendly_reach.selected_source_indices)
                candidate_summary = ', '.join(
                    f'{candidate.choke_tile} from '
                    f'{friendly_reach.candidate_sources[candidate.source_index]} '
                    f'at d{candidate.depth} score={candidate.prescreen_value:.2f}'
                    for candidate in candidates)
                logbook.info(
                    f'ArmyInterceptorV2 matrices: tiles={len(threat_reach.tiles_by_index)}, '
                    f'enemyReached={sum(1 for turn in threat_reach.enemy_turn if turn >= 0)}, '
                    f'sources={len(threat_reach.candidate_sources)}, '
                    f'blockingSources={len(threat_reach.blocking_sources)}, '
                    f'selectedSources={len(friendly_reach.selected_source_indices)}, '
                    f'candidates={len(candidates)}')
                logbook.info(
                    f'ArmyInterceptorV2 selected sources: {selected_source_summary}')
                logbook.info(
                    f'ArmyInterceptorV2 kept candidates: {candidate_summary}')
            else:
                logbook.info(
                    f'ArmyInterceptorV2 v1-search candidates: '
                    f'evals={len(self.last_native_evals)}')
            logbook.info(
                f'ArmyInterceptorV2 stage seconds: '
                f'A={stage_a_seconds:.6f}, B={stage_b_seconds:.6f}, '
                f'C={stage_c_seconds:.6f}, D={stage_d_seconds:.6f}, '
                f'E={stage_e_seconds:.6f}, '
                f'total={time.perf_counter() - stages_started_at:.6f}')

        return best_intercept_table

    def resolve_choke_search_depths(
        self,
        interception: ArmyInterception,
        middlest_tiles: set[Tile],
        include_non_middlest_fallback: bool,
    ) -> dict[Tile, int]:
        """Per-choke search depths with V1's admissibility gates applied.

        Mirrors V1's choke loop: skip neutral cities, skip non-middlest
        chokes unless the fallback pass allows them, give fallback chokes
        their +1 depth, and drop chokes whose filtered depth reached zero.
        Requires filter_interception_best_points to have run already so
        intercept_info.max_search_dist holds the pruned value.
        """
        choke_search_depths: dict[Tile, int] = {}
        for choke_tile, intercept_info in (
                interception.common_intercept_chokes.items()):
            if choke_tile.isCity and choke_tile.isNeutral:
                continue
            is_non_middlest_fallback = (
                include_non_middlest_fallback
                and choke_tile not in middlest_tiles
                and intercept_info.max_search_dist > 0)
            if (
                choke_tile not in middlest_tiles
                and not is_non_middlest_fallback
            ):
                continue
            search_depth = intercept_info.max_search_dist
            if is_non_middlest_fallback:
                search_depth += 1
            if search_depth <= 0:
                continue
            choke_search_depths[choke_tile] = search_depth
        return choke_search_depths

    def build_allowed_search_region(
        self,
        interception: ArmyInterception,
    ) -> bytearray:
        """Port of V1's funnel-union allowedSearchRegion construction.

        Each common intercept choke seeds an offset-BFS radius of
        bMap[choke] + 1; marking seeds at offset maxRadius - radius makes the
        popped distance <= maxRadius equivalent to "tile is within radius of
        at least one choke", matching V1's single multi-source pass exactly.
        """
        b_map_raw = interception.threats[0].armyAnalysis.bMap.raw
        region = bytearray(len(b_map_raw))
        bfs_dist = [-1] * len(region)
        max_radius = 0
        seeds: list[tuple[Tile, int]] = []
        for choke_tile in interception.common_intercept_chokes.keys():
            radius = b_map_raw[choke_tile.tile_index] + 1
            seeds.append((choke_tile, radius))
            if radius > max_radius:
                max_radius = radius

        frontier: deque[tuple[Tile, int]] = deque()
        # sort descending by radius so seeds enter the BFS in ascending
        # offset order, keeping the deque monotonic like V1's pass.
        for choke_tile, radius in sorted(seeds, key=lambda s: -s[1]):
            offset = max_radius - radius
            choke_index = choke_tile.tile_index
            if bfs_dist[choke_index] == -1:
                bfs_dist[choke_index] = offset
                region[choke_index] = 1
                frontier.append((choke_tile, offset))

        while frontier:
            cur_tile, dist = frontier.popleft()
            if dist >= max_radius:
                continue
            new_dist = dist + 1
            for neighbor in cur_tile.movable:
                if bfs_dist[neighbor.tile_index] != -1:
                    continue
                bfs_dist[neighbor.tile_index] = new_dist
                region[neighbor.tile_index] = 1
                if neighbor.isObstacle:
                    continue
                frontier.append((neighbor, new_dist))
        return region

    def build_threat_reach_matrix(
        self,
        interception: ArmyInterception,
        max_depth: int,
        turns_left_in_cycle: int,
        choke_search_depths: dict[Tile, int],
        allowed_search_region: bytearray,
    ) -> ThreatReachMatrix:
        """Build threat reach, army, threat-path, damage, and source arrays."""
        tiles_by_index = list(self.v1.map.get_all_tiles())
        tile_count = len(tiles_by_index)
        step_deltas = self._build_army_step_deltas(
            interception,
            tiles_by_index)
        enemy_turn = [-1] * tile_count
        enemy_army = [0] * tile_count
        threat_path_mask = [0] * tile_count

        for threat_index, threat in enumerate(interception.threats):
            path_bit = 1 << threat_index
            for node in threat.path:
                threat_path_mask[node.tile.tile_index] |= path_bit

        target_index = interception.target_tile.tile_index
        enemy_turn[target_index] = 0
        enemy_army[target_index] = self._ensure_enemy_step_delta(
            step_deltas,
            interception.target_tile)
        frontier: deque[int] = deque([target_index])
        while frontier:
            tile_index = frontier.popleft()
            current_turn = enemy_turn[tile_index]
            current_tile = tiles_by_index[tile_index]
            if current_turn >= max_depth:
                continue
            for next_tile in current_tile.movable:
                if next_tile.isObstacle or (
                    next_tile.isCity and next_tile.isNeutral):
                    continue
                next_index = next_tile.tile_index
                next_turn = current_turn + 1
                if not step_deltas.enemy_delta_computed[next_index]:
                    self._ensure_enemy_step_delta(step_deltas, next_tile)
                next_army = (
                    enemy_army[tile_index]
                    + step_deltas.enemy_step_delta[next_index])
                if enemy_turn[next_index] == -1:
                    enemy_turn[next_index] = next_turn
                    enemy_army[next_index] = next_army
                    frontier.append(next_index)
                elif enemy_turn[next_index] == next_turn:
                    enemy_army[next_index] = max(
                        enemy_army[next_index],
                        next_army)

        downstream_damage = [0.0] * tile_count
        if V2_THREAT_DAMAGE_MODE == V2ThreatDamageMode.THREAT_PATHS:
            self._build_threat_path_downstream_damage(
                interception,
                turns_left_in_cycle,
                step_deltas,
                downstream_damage)
        else:
            self._build_unrestricted_downstream_damage(
                interception,
                turns_left_in_cycle,
                enemy_turn,
                enemy_army,
                tiles_by_index,
                downstream_damage)

        budget_result = self.build_choke_budget_matrix(
            interception,
            max_depth,
            tiles_by_index,
            threat_path_mask,
            step_deltas,
            choke_search_depths,
            allowed_search_region)
        choke_budget = budget_result.matrix
        candidate_sources = budget_result.candidate_sources
        blocking_sources = [
            tile
            for tile in candidate_sources
            if enemy_turn[tile.tile_index] != -1
            and enemy_army[tile.tile_index] <= tile.army
        ]
        return ThreatReachMatrix(
            tiles_by_index=tiles_by_index,
            max_depth=max_depth,
            enemy_turn=enemy_turn,
            enemy_army=enemy_army,
            threat_path_mask=threat_path_mask,
            downstream_damage=downstream_damage,
            choke_budget=choke_budget,
            step_deltas=step_deltas,
            candidate_sources=candidate_sources,
            blocking_sources=blocking_sources,
        )

    def build_choke_budget_matrix(
        self,
        interception: ArmyInterception,
        max_depth: int,
        tiles_by_index: list[Tile],
        threat_path_mask: list[int],
        step_deltas: ArmyStepDeltaMatrix,
        choke_search_depths: dict[Tile, int],
        allowed_search_region: bytearray,
    ) -> ChokeBudgetBuildResult:
        """Build choke slack and collect candidate sources in one offset BFS."""
        choke_limits = [
            (tile, search_depth)
            for tile, search_depth in choke_search_depths.items()
        ]
        tile_count = len(tiles_by_index)
        if not choke_limits:
            return ChokeBudgetBuildResult(
                matrix=ChokeBudgetMatrix(budget=[-1] * tile_count),
                candidate_sources=[])

        max_limit = max(limit for _, limit in choke_limits)
        bfs_dist = [UNREACHABLE_DISTANCE] * tile_count
        frontier: deque[tuple[int, int]] = deque()
        for choke_tile, limit in sorted(
            choke_limits,
            key=lambda choke_and_limit: max_limit - choke_and_limit[1]):
            offset = max_limit - limit
            choke_index = choke_tile.tile_index
            if bfs_dist[choke_index] <= offset:
                continue
            bfs_dist[choke_index] = offset
            frontier.append((choke_index, offset))

        full_path_mask = (1 << len(interception.threats)) - 1
        candidate_sources: list[Tile] = []
        candidate_source_seen = bytearray(tile_count)
        while frontier:
            tile_index, dist = frontier.popleft()
            if bfs_dist[tile_index] != dist or dist > max_limit:
                continue
            tile = tiles_by_index[tile_index]
            self._ensure_friendly_step_delta(
                interception,
                step_deltas,
                tile)
            if (
                max_limit - dist >= 0
                and step_deltas.friendly_tile_mask[tile_index]
                and tile.army >= 2
            ):
                is_source = True
                if step_deltas.negative_tile_mask[tile_index]:
                    if threat_path_mask[tile_index] == full_path_mask:
                        is_source = False
                    else:
                        source_distances = (
                            self.v1.map.distance_mapper.get_tile_dist_matrix(
                                tile).raw)
                        nearest_choke_distance = min(
                            (
                                source_distances[choke_tile.tile_index]
                                for choke_tile, _ in choke_limits
                            ),
                            default=UNREACHABLE_DISTANCE)
                        if nearest_choke_distance >= UNREACHABLE_DISTANCE:
                            is_source = False
                        else:
                            minimum_army = (
                                interception.base_threat_army
                                * (nearest_choke_distance + 1)
                            ) // (nearest_choke_distance + 2)
                            if tile.army < minimum_army:
                                is_source = False
                if is_source and not candidate_source_seen[tile_index]:
                    candidate_source_seen[tile_index] = 1
                    candidate_sources.append(tile)

            if dist >= max_limit:
                continue
            new_dist = dist + 1
            for neighbor in tile.movable:
                if neighbor.isObstacle or (
                    neighbor.isCity and neighbor.isNeutral):
                    continue
                neighbor_index = neighbor.tile_index
                # V1's path search is bounded by the funnel union region
                # (allowedSearchRegion); tiles outside it cannot be path
                # nodes, so they get no choke budget either.
                if not allowed_search_region[neighbor_index]:
                    continue
                if new_dist >= bfs_dist[neighbor_index]:
                    continue
                bfs_dist[neighbor_index] = new_dist
                frontier.append((neighbor_index, new_dist))

        for tile_index, dist in enumerate(bfs_dist):
            bfs_dist[tile_index] = (
                max_limit - dist
                if dist < UNREACHABLE_DISTANCE and dist <= max_limit
                else -1)
        return ChokeBudgetBuildResult(
            matrix=ChokeBudgetMatrix(budget=bfs_dist),
            candidate_sources=candidate_sources)

    def _build_army_step_deltas(
        self,
        interception: ArmyInterception,
        tiles_by_index: list[Tile],
    ) -> ArmyStepDeltaMatrix:
        """Allocate per-tile deltas; reachable tiles are filled on first visit."""
        threat_players = self.v1.map.get_teammates(
            interception.threats[0].threatPlayer)
        return ArmyStepDeltaMatrix(
            friendly_step_delta=[0] * len(tiles_by_index),
            enemy_step_delta=[0] * len(tiles_by_index),
            friendly_tile_mask=bytearray(len(tiles_by_index)),
            negative_tile_mask=bytearray(len(tiles_by_index)),
            friendly_delta_computed=bytearray(len(tiles_by_index)),
            enemy_delta_computed=bytearray(len(tiles_by_index)),
            threat_players=threat_players)

    def _ensure_enemy_step_delta(
        self,
        step_deltas: ArmyStepDeltaMatrix,
        tile: Tile,
    ) -> int:
        """Compute a threat-team delta the first time a BFS reaches a tile."""
        tile_index = tile.tile_index
        if not step_deltas.enemy_delta_computed[tile_index]:
            if tile.player in step_deltas.threat_players:
                step_deltas.enemy_step_delta[tile_index] = tile.army - 1
            else:
                step_deltas.enemy_step_delta[tile_index] = -tile.army - 1
            step_deltas.enemy_delta_computed[tile_index] = 1
        return step_deltas.enemy_step_delta[tile_index]

    def _ensure_friendly_step_delta(
        self,
        interception: ArmyInterception,
        step_deltas: ArmyStepDeltaMatrix,
        tile: Tile,
    ) -> int:
        """Compute a friendly delta only for tiles in the choke-budget region."""
        tile_index = tile.tile_index
        if not step_deltas.friendly_delta_computed[tile_index]:
            is_friendly = self.v1.map.is_tile_friendly(tile)
            is_negative = (
                tile
                in interception.positive_threat_subsegment_negative_tile_indexes)
            if is_friendly:
                step_deltas.friendly_tile_mask[tile_index] = 1
            if is_negative:
                step_deltas.negative_tile_mask[tile_index] = 1
                step_deltas.friendly_step_delta[tile_index] = -1
            elif is_friendly:
                step_deltas.friendly_step_delta[tile_index] = tile.army - 1
            else:
                step_deltas.friendly_step_delta[tile_index] = -tile.army - 1
            step_deltas.friendly_delta_computed[tile_index] = 1
        return step_deltas.friendly_step_delta[tile_index]

    def build_friendly_multi_source_matrix(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        choke_search_depths: dict[Tile, int],
    ) -> FriendlyMultiSourceMatrix:
        """Run one best-army, minimum-turn BFS from every candidate source."""
        tile_count = len(threat_reach.tiles_by_index)
        candidate_sources = threat_reach.candidate_sources
        choke_budget = threat_reach.choke_budget.budget
        friendly_step_delta = (
            threat_reach.step_deltas.friendly_step_delta)
        turns = [-1] * tile_count
        army_at_arrival = [UNREACHED_ARMY] * tile_count
        source_index = [-1] * tile_count
        frontier: deque[int] = deque()

        for candidate_index, source in enumerate(candidate_sources):
            tile_index = source.tile_index
            if choke_budget[tile_index] < 0:
                continue
            source_army = friendly_step_delta[tile_index]
            turns[tile_index] = 0
            army_at_arrival[tile_index] = source_army
            source_index[tile_index] = candidate_index
            frontier.append(tile_index)

        while frontier:
            tile_index = frontier.popleft()
            current_turn = turns[tile_index]
            if (
                current_turn >= threat_reach.max_depth
                or current_turn > choke_budget[tile_index]
            ):
                continue
            next_turn = current_turn + 1
            current_tile = threat_reach.tiles_by_index[tile_index]
            for next_tile in current_tile.movable:
                if next_tile.isObstacle or (
                    next_tile.isCity and next_tile.isNeutral):
                    continue
                next_index = next_tile.tile_index
                if next_turn > choke_budget[next_index]:
                    continue
                next_army = (
                    army_at_arrival[tile_index]
                    + friendly_step_delta[next_index])
                if turns[next_index] == -1 or next_turn < turns[next_index]:
                    turns[next_index] = next_turn
                    army_at_arrival[next_index] = next_army
                    source_index[next_index] = source_index[tile_index]
                    frontier.append(next_index)
                elif (
                    next_turn == turns[next_index]
                    and next_army > army_at_arrival[next_index]
                ):
                    army_at_arrival[next_index] = next_army
                    source_index[next_index] = source_index[tile_index]
                    frontier.append(next_index)

        ownership_scores = [0.0] * len(candidate_sources)
        for choke_tile, intercept_info in interception.common_intercept_chokes.items():
            # Only chokes V1 would actually search count toward source
            # ownership so non-admissible chokes cannot skew selection.
            if choke_tile not in choke_search_depths:
                continue
            choke_index = choke_tile.tile_index
            owner_index = source_index[choke_index]
            if owner_index == -1:
                continue
            if turns[choke_index] > intercept_info.max_delay_turns:
                continue
            enemy_army = max(1, threat_reach.enemy_army[choke_index])
            ownership_scores[owner_index] += (
                threat_reach.downstream_damage[choke_index]
                * min(1.0, army_at_arrival[choke_index] / enemy_army))

        selected_source_indices: list[int] = []
        ownership_order = sorted(
            range(len(candidate_sources)),
            key=lambda index: (ownership_scores[index], -index),
            reverse=True)
        for candidate_index in ownership_order:
            if ownership_scores[candidate_index] <= 0:
                continue
            selected_source_indices.append(candidate_index)
            if len(selected_source_indices) >= V2_MAX_OWNERSHIP_SOURCES:
                break

        reachability_by_source = [
            choke_budget[source.tile_index] >= 0
            for source in candidate_sources]

        largest_army_order = sorted(
            (
                index
                for index, source in enumerate(candidate_sources)
                if reachability_by_source[index]
            ),
            key=lambda index: (
                candidate_sources[index].army,
                -index),
            reverse=True)
        for candidate_index in largest_army_order[
            :V2_MAX_LARGEST_ARMY_SOURCES]:
            if candidate_index not in selected_source_indices:
                selected_source_indices.append(candidate_index)

        source_index_by_tile = [-1] * tile_count
        for candidate_index, source in enumerate(candidate_sources):
            source_index_by_tile[source.tile_index] = candidate_index
        for blocking_source in threat_reach.blocking_sources:
            candidate_index = source_index_by_tile[blocking_source.tile_index]
            if (
                candidate_index != -1
                and reachability_by_source[candidate_index]
                and candidate_index not in selected_source_indices
            ):
                selected_source_indices.append(candidate_index)

        return FriendlyMultiSourceMatrix(
            candidate_sources=candidate_sources,
            turns=turns,
            army_at_arrival=army_at_arrival,
            source_index=source_index,
            ownership_scores=ownership_scores,
            selected_source_indices=selected_source_indices,
        )

    def build_source_layered_reach(
        self,
        threat_reach: ThreatReachMatrix,
        source_index: int,
    ) -> SourceLayeredReach:
        """Build bounded army states from one source to threat-relevant tiles."""
        source_tile = threat_reach.candidate_sources[source_index]
        distance_matrix = self.v1.map.distance_mapper.get_tile_dist_matrix(
            source_tile)
        shortest_dist = distance_matrix.raw
        choke_budget = threat_reach.choke_budget.budget
        friendly_step_delta = (
            threat_reach.step_deltas.friendly_step_delta)
        max_depth = threat_reach.max_depth
        source_tile_index = source_tile.tile_index
        if choke_budget[source_tile_index] < 0:
            raise ValueError(
                f'V2 selected unreachable source {source_tile}')
        states_by_depth: list[dict[int, tuple[int, int]]] = [
            {}
            for _ in range(max_depth + 1)
        ]
        states_by_depth[0][source_tile_index] = (
            friendly_step_delta[source_tile_index],
            NO_PARENT)
        state_frontier: deque[tuple[int, int]] = deque([
            (source_tile_index, 0)
        ])
        while state_frontier:
            tile_index, depth = state_frontier.popleft()
            if depth >= max_depth:
                continue
            next_depth = depth + 1
            current_army, parent_tile_index = (
                states_by_depth[depth][tile_index])
            current_tile = threat_reach.tiles_by_index[tile_index]
            for next_tile in current_tile.movable:
                if next_tile.isObstacle or (
                    next_tile.isCity and next_tile.isNeutral):
                    continue
                next_index = next_tile.tile_index
                shortest_distance = shortest_dist[next_index]
                if (
                    shortest_distance < 0
                    or shortest_distance >= UNREACHABLE_DISTANCE
                    or next_depth > shortest_distance + V2_PATH_SLACK
                    or next_depth > choke_budget[next_index]
                ):
                    continue
                # Grid cycles are at least 4 moves; with immediate backtracking
                # banned, any revisit needs slack >= 4.
                if next_index == parent_tile_index:
                    continue

                next_army = (
                    current_army + friendly_step_delta[next_index])
                current_best_state = states_by_depth[next_depth].get(
                    next_index)
                if (
                    current_best_state is not None
                    and next_army <= current_best_state[0]
                ):
                    continue
                states_by_depth[next_depth][next_index] = (
                    next_army,
                    tile_index)
                state_frontier.append((next_index, next_depth))

        return SourceLayeredReach(
            source_index=source_index,
            source_tile=source_tile,
            max_depth=max_depth,
            states_by_depth=states_by_depth,
        )

    def build_intercept_candidates(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        layered_reaches: list[SourceLayeredReach],
        turns_left_in_cycle: int,
        choke_search_depths: dict[Tile, int],
    ) -> list[V2InterceptCandidate]:
        """Retain every per-source/depth and per-depth winner plus all scores.

        Native scoring is cheap enough that every produced candidate is
        evaluated; the per-(source, depth) and per-depth winner passes only
        order the kept list so table-insertion tie-breaks match V1's
        first-seen-wins semantics. Only chokes V1 itself would search (per
        choke_search_depths) produce candidates.
        """
        candidates: list[V2InterceptCandidate] = []
        best_candidate_by_source_and_depth: dict[
            tuple[int, int],
            V2InterceptCandidate,
        ] = {}
        best_candidate_by_depth: dict[int, V2InterceptCandidate] = {}
        for layer_index, source_reach in enumerate(layered_reaches):
            source_index = source_reach.source_index
            for choke_tile, intercept_info in interception.common_intercept_chokes.items():
                search_depth = choke_search_depths.get(choke_tile)
                if search_depth is None:
                    continue
                choke_index = choke_tile.tile_index
                max_candidate_depth = min(
                    search_depth,
                    source_reach.max_depth)
                for depth in range(1, max_candidate_depth + 1):
                    state = source_reach.states_by_depth[depth].get(
                        choke_index)
                    if state is None:
                        continue
                    friendly_army = state[0]
                    if threat_reach.enemy_turn[choke_index] != -1:
                        enemy_army = max(
                            1,
                            threat_reach.enemy_army[choke_index])
                    else:
                        enemy_army = max(1, interception.base_threat_army)
                    turns_left = (
                        turns_left_in_cycle
                        - depth
                        - intercept_info.max_extra_moves_to_capture)
                    recapture_turns = max(
                        0,
                        min(
                            turns_left,
                            (friendly_army - enemy_army) // 2))
                    blocked_estimate = self._estimate_threat_blocked(
                        interception,
                        choke_tile,
                        friendly_army,
                        turns_left_in_cycle)
                    intercept_point_distance = (
                        interception.threats[0]
                        .armyAnalysis.bMap[choke_tile])
                    additional_turns = (
                        max(0, intercept_point_distance - depth)
                        if not interception.target_tile.isCity
                        else intercept_point_distance)
                    estimated_base_turns_key = (
                        depth
                        + additional_turns
                        + intercept_info.max_extra_moves_to_capture)
                    # Regression cases: Tests.test_ArmyInterception.test_should_complete_intercept_one_tile_away and Tests.test_ArmyInterception.test_should_complete_city_capture.
                    prescreen_value = max(
                        (
                            blocked_estimate
                            + RECAPTURE_VALUE * recap_turns
                        ) / max(1, estimated_base_turns_key + recap_turns)
                        for recap_turns in range(recapture_turns + 1))
                    candidate = V2InterceptCandidate(
                        source_index=source_index,
                        layer_index=layer_index,
                        choke_tile=choke_tile,
                        depth=depth,
                        friendly_army=friendly_army,
                        prescreen_value=prescreen_value,
                    )
                    candidates.append(candidate)
                    source_depth_key = (source_index, depth)
                    current_best = (
                        best_candidate_by_source_and_depth.get(
                            source_depth_key))
                    if (
                        current_best is None
                        or self._candidate_sort_key(candidate)
                        < self._candidate_sort_key(current_best)
                    ):
                        best_candidate_by_source_and_depth[
                            source_depth_key] = candidate
                    current_depth_best = best_candidate_by_depth.get(depth)
                    if (
                        current_depth_best is None
                        or self._candidate_sort_key(candidate)
                        < self._candidate_sort_key(current_depth_best)
                    ):
                        best_candidate_by_depth[depth] = candidate

        kept_candidates = list(
            best_candidate_by_source_and_depth.values())
        included_candidate_keys = {
            self._candidate_key(candidate)
            for candidate in kept_candidates
        }
        for candidate in best_candidate_by_depth.values():
            candidate_key = self._candidate_key(candidate)
            if candidate_key in included_candidate_keys:
                continue
            kept_candidates.append(candidate)
            included_candidate_keys.add(candidate_key)

        for candidate in sorted(candidates, key=self._candidate_sort_key):
            candidate_key = self._candidate_key(candidate)
            if candidate_key in included_candidate_keys:
                continue
            kept_candidates.append(candidate)
            included_candidate_keys.add(candidate_key)
        return kept_candidates

    def _reconstruct_candidate_tile_indices(
        self,
        source_reach: SourceLayeredReach,
        candidate: V2InterceptCandidate,
    ) -> list[int]:
        """Rebuild one candidate's tile-index list from layered parents."""
        tile_indices = [candidate.choke_tile.tile_index]
        current_index = candidate.choke_tile.tile_index
        for depth in range(candidate.depth, 0, -1):
            current_state = source_reach.states_by_depth[depth].get(
                current_index)
            if current_state is None:
                raise ValueError(
                    f'No V2 parent for source {source_reach.source_tile}, '
                    f'choke {candidate.choke_tile}, depth {candidate.depth}')
            parent_index = current_state[1]
            if parent_index == NO_PARENT:
                raise ValueError(
                    f'No V2 parent for source {source_reach.source_tile}, '
                    f'choke {candidate.choke_tile}, depth {candidate.depth}')
            current_index = parent_index
            tile_indices.append(current_index)
        if current_index != source_reach.source_tile.tile_index:
            raise ValueError(
                f'V2 path did not reconstruct to source '
                f'{source_reach.source_tile}')
        tile_indices.reverse()
        return tile_indices

    def build_path_from_tile_indices(
        self,
        tiles_by_index: list[Tile],
        tile_indices: list[int],
    ) -> Path:
        """Materialize a forward Path from a candidate tile-index list."""
        path = Path()
        for tile_index in tile_indices:
            path.add_next(tiles_by_index[tile_index])
        return path

    def reconstruct_candidate_paths(
        self,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        layered_reaches: list[SourceLayeredReach],
        candidates: list[V2InterceptCandidate],
    ) -> list[V2CandidatePath]:
        """Reconstruct each retained layered state as a forward Path."""
        candidate_paths: list[V2CandidatePath] = []
        for candidate in candidates:
            source_reach = layered_reaches[candidate.layer_index]
            if (
                source_reach.source_tile
                != friendly_reach.candidate_sources[candidate.source_index]
            ):
                raise ValueError(
                    f'V2 candidate source mismatch for '
                    f'{source_reach.source_tile}')
            tile_indices = self._reconstruct_candidate_tile_indices(
                source_reach,
                candidate)
            path = self.build_path_from_tile_indices(
                threat_reach.tiles_by_index,
                tile_indices)
            candidate_paths.append(
                V2CandidatePath(
                    candidate=candidate,
                    path=path,
                    friendly_army_at_choke=source_reach.states_by_depth[
                        candidate.depth][candidate.choke_tile.tile_index][0],
                ))
        return candidate_paths

    def _build_threat_path_downstream_damage(
        self,
        interception: ArmyInterception,
        turns_left_in_cycle: int,
        step_deltas: ArmyStepDeltaMatrix,
        downstream_damage: list[float],
    ) -> None:
        """Accumulate maximum strictly downstream damage along threat paths."""
        for threat_value in interception.threat_values:
            threat = threat_value.threat
            threat_players = self.v1.map.get_teammates(threat.threatPlayer)
            path_tiles = [node.tile for node in threat.path]
            cap_values = [0.0] * len(path_tiles)
            enemy_army = 0
            for path_index, tile in enumerate(path_tiles):
                if not step_deltas.enemy_delta_computed[tile.tile_index]:
                    self._ensure_enemy_step_delta(step_deltas, tile)
                enemy_army += step_deltas.enemy_step_delta[tile.tile_index]
                if enemy_army > 0 and path_index < turns_left_in_cycle:
                    cap_values[path_index] = self._get_cap_value(
                        tile,
                        threat.threatType,
                        turns_left_in_cycle - path_index,
                        threat_players)

            suffix_damage = 0.0
            for path_index in range(len(path_tiles) - 1, -1, -1):
                tile_index = path_tiles[path_index].tile_index
                downstream_damage[tile_index] = max(
                    downstream_damage[tile_index],
                    suffix_damage)
                suffix_damage += cap_values[path_index]

    def _estimate_threat_blocked(
        self,
        interception: ArmyInterception,
        choke_tile: Tile,
        friendly_army: int,
        turns_left_in_cycle: int,
    ) -> float:
        """Estimate V1 blocked damage with its backward threat-path walk."""
        max_blocked_damage = float('-inf')
        for threat_index, threat_value in enumerate(interception.threat_values):
            threat = threat_value.threat
            intercept_distance = (
                threat.armyAnalysis.bMap[choke_tile])
            cache_key = (
                threat_index,
                intercept_distance,
                friendly_army)
            cached_damage = self.damage_estimate_cache.get(cache_key)
            if cached_damage is not None:
                max_blocked_damage = max(max_blocked_damage, cached_damage)
                continue

            enemy_army = int(threat.path.value)
            enemy_length = threat.path.length
            enemy_node = threat.path.tail
            while (
                enemy_node is not None
                and enemy_army < 0
                and enemy_length > intercept_distance
            ):
                if self.v1.map.is_tile_on_team_with(
                    enemy_node.tile,
                    threat.threatPlayer):
                    enemy_army -= enemy_node.tile.army
                else:
                    enemy_army += enemy_node.tile.army
                enemy_army += 1
                enemy_node = enemy_node.prev
                enemy_length -= 1

            enemy_army -= friendly_army
            blocked_damage = 0.0
            main_damage_complete = False
            turns_left = turns_left_in_cycle
            while enemy_node is not None:
                if turns_left <= 0:
                    main_damage_complete = True
                if (
                    enemy_army > 0
                    or enemy_length <= intercept_distance
                ):
                    break

                tile = enemy_node.tile
                if self.v1.map.is_tile_on_team_with(
                    tile,
                    threat.threatPlayer):
                    enemy_army -= tile.army
                else:
                    enemy_army += tile.army
                    if self.v1.map.is_tile_friendly(tile):
                        if tile.isGeneral and enemy_army < 0:
                            blocked_damage += GENERAL_CAP_VALUE
                        elif tile.isCity:
                            if not main_damage_complete:
                                blocked_damage += (
                                    turns_left_in_cycle - enemy_length)
                            if enemy_army < 0:
                                blocked_damage += OWNED_CITY_CAP_VALUE_BONUS
                        if not main_damage_complete:
                            blocked_damage += TARGET_CAP_VALUE
                    elif tile.player >= 0:
                        if not main_damage_complete:
                            blocked_damage += NEUTRAL_CAP_VALUE
                    elif not main_damage_complete:
                        blocked_damage += OTHER_PARTY_CAP_VALUE

                enemy_army += 1
                enemy_node = enemy_node.prev
                enemy_length -= 1
                turns_left -= 1

            self.damage_estimate_cache[cache_key] = blocked_damage
            max_blocked_damage = max(max_blocked_damage, blocked_damage)
        return (
            max_blocked_damage
            if max_blocked_damage != float('-inf')
            else 0.0)

    def _build_unrestricted_downstream_damage(
        self,
        interception: ArmyInterception,
        turns_left_in_cycle: int,
        enemy_turn: list[int],
        enemy_army: list[int],
        tiles_by_index: list[Tile],
        downstream_damage: list[float],
    ) -> None:
        """Use reverse dynamic programming over the threat-reach DAG."""
        kill_threat_players = self.v1.map.get_teammates(
            interception.threats[0].threatPlayer)
        has_kill_threat = any(
            threat.threatType == ThreatType.Kill
            for threat in interception.threats)
        threat_type = (
            ThreatType.Kill
            if has_kill_threat
            else interception.threats[0].threatType)
        for depth in range(
            min(turns_left_in_cycle, max(enemy_turn, default=-1)),
            -1,
            -1):
            for tile_index, enemy_turn_value in enumerate(enemy_turn):
                if enemy_turn_value != depth:
                    continue
                tile = tiles_by_index[tile_index]
                tile_damage = 0.0
                if enemy_army[tile_index] > 0:
                    remaining_turns = turns_left_in_cycle - depth
                    tile_damage = self._get_cap_value(
                        tile,
                        threat_type,
                        remaining_turns,
                        kill_threat_players)
                max_child_damage = 0.0
                for child_tile in tile.movable:
                    if child_tile.isObstacle or (
                        child_tile.isCity and child_tile.isNeutral):
                        continue
                    child_index = child_tile.tile_index
                    if enemy_turn[child_index] == depth + 1:
                        max_child_damage = max(
                            max_child_damage,
                            downstream_damage[child_index])
                downstream_damage[tile_index] = (
                    tile_damage + max_child_damage)

    def _get_cap_value(
        self,
        tile: Tile,
        threat_type: ThreatType,
        remaining_turns: int,
        threat_players: list[int],
    ) -> float:
        """Return the V1-style economic value of capturing one tile."""
        if tile.player in threat_players:
            return 0.0
        if self.v1.map.is_tile_friendly(tile):
            value = TARGET_CAP_VALUE
            if tile.isCity:
                value += OWNED_CITY_CAP_VALUE_BONUS + max(
                    0,
                    remaining_turns)
            if tile.isGeneral and threat_type == ThreatType.Kill:
                value += GENERAL_CAP_VALUE
            return value
        if tile.player >= 0:
            return NEUTRAL_CAP_VALUE
        return OTHER_PARTY_CAP_VALUE

    def _candidate_sort_key(
        self,
        candidate: V2InterceptCandidate,
    ) -> tuple[float, int, int, int]:
        """Sort higher prescreen values first with stable tile/depth ties."""
        return (
            -candidate.prescreen_value,
            candidate.source_index,
            candidate.choke_tile.tile_index,
            candidate.depth,
        )

    def _candidate_key(
        self,
        candidate: V2InterceptCandidate,
    ) -> tuple[int, int, int]:
        """Return the unique source/choke/depth identity for a candidate."""
        return (
            candidate.source_index,
            candidate.choke_tile.tile_index,
            candidate.depth,
        )

    def _v1_get_intercept_paths_native(
        self,
        interception: ArmyInterception,
        choke_tile: Tile,
        max_depth: int,
        positions_by_turn: list[tuple[float, float] | None],
        allowed_search_region: bytearray,
        tiles_by_index: list[Tile],
        pop_log: list[tuple] | None = None,
    ) -> dict[int, list[int]]:
        """Port of V1's _get_intercept_paths for one choke tile.

        Reproduces breadth_first_dynamic_max_per_tile_per_distance (the
        global-visited variant) exactly on tile-index data: a heap ordered by
        V1's (dist, fromEuclid, negTileCapPoints, negArmy, nextTile.army)
        priority object, a first-pop-wins parent table, the same prioFunc
        expansion gates (allowed region, neutral cities, euclid regression
        toward the average enemy position), the same valueFunc endpoint
        checks, and the same "recorded value must exceed the value recorded
        at dist-1" result gate. Returns dist -> tile-index list in
        source-to-choke order, matching the reversed Path objects V1 places
        in its byDist dict (one path per path length).
        """
        game_map = self.v1.map
        threat_tile = interception.threats[0].path.start.tile
        threat_dist_raw = game_map.distance_mapper.get_tile_dist_matrix(
            threat_tile).raw
        num_positions = len(positions_by_turn)
        player_index = game_map.player_index
        team_ids = game_map.team_ids_by_player_index
        searching_team = team_ids[player_index]
        euclid_dist = game_map.euclidDist
        grid = game_map.grid

        choke_index = choke_tile.tile_index
        # V1's startArmy seeds negArmy at -choke.army when the choke sits on
        # the searching team so a friendly choke contributes its army.
        start_army = 0
        if team_ids[choke_tile.player] == searching_team:
            start_army = -choke_tile.army
        start_dist = threat_dist_raw[choke_index]
        start_euclid = float(start_dist)
        raw_pos = (
            positions_by_turn[start_dist]
            if start_dist < num_positions
            else None)
        if raw_pos is not None:
            start_euclid = euclid_dist(
                raw_pos[0],
                raw_pos[1],
                choke_tile.x,
                choke_tile.y)

        # Heap entries use V1's exact tuple shape
        # (prioVals, dist, curTurns, nextTile, fromTile, maxDict) with real
        # Tile objects so Python's element-wise tuple comparison reproduces
        # breadth_first_dynamic_max_per_tile_per_distance's ordering 1:1:
        # prioVals=(dist, fromEuclidCur, negTileCapPoints, negArmy, nextTile)
        # compares element-wise and stops at the FIRST non-equal element;
        # different tiles with equal armies compare Tile.__lt__ -> False and
        # the entries fall back to heap push order (fromTile is only reached
        # when the same next tile was pushed by different parents, and the
        # shared maxDict object never decides anything). Using real tiles
        # also makes the None-vs-Tile seed ordering identical.
        # Tests/test_ArmyInterception.py::test_should_just_cap_tiles_when_inbound_army_isnt_kill_threat:
        # a flat (army, army, seq) sort key ordered equal-army entries by
        # fromTile army where V1 ties them to push order, which dropped a
        # distance-7 path record at turn 671 choke 259 and picked a
        # different distance-11 endpoint; only the real Tile-object tuple
        # reproduces V1's tie semantics exactly.
        max_dict: dict[int, tuple[tuple[int, int, int], int]] = {}
        frontier: list[tuple] = [
            (
                (0, start_euclid, 0, start_army, choke_tile),
                0,
                0,
                choke_tile,
                None,
                max_dict,
            )
        ]
        visited_parent = [NO_PARENT] * len(tiles_by_index)
        visited = bytearray(len(tiles_by_index))
        recorded = max_dict
        iterations = 0
        search_started_at = time.perf_counter()
        while frontier:
            iterations += 1
            # Mirrors V1's iter & 63 timeout poll inside
            # breadth_first_dynamic_max_per_tile_per_distance so searches
            # that V1 would cut off at 0.2s produce the same partial result.
            if (
                iterations & 63 == 0
                and time.perf_counter() - search_started_at > 0.2
                and not SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING
            ):
                logbook.info(
                    f'V2 V1-SEARCH BREAKING EARLY @ '
                    f'{time.perf_counter() - search_started_at:.3f} '
                    f'iter {iterations}')
                break
            entry = heapq.heappop(frontier)
            prio_vals = entry[0]
            prio_dist = prio_vals[0]
            cur_turns = entry[2]
            current_tile = entry[3]
            from_tile = entry[4]
            current_index = current_tile.tile_index
            from_index = (
                from_tile.tile_index
                if from_tile is not None
                else NO_PARENT)
            if visited[current_index]:
                continue
            visited[current_index] = 1
            visited_parent[current_index] = from_index
            cap_points = prio_vals[2]
            neg_army = prio_vals[3]
            if pop_log is not None:
                pop_log.append(
                    (current_index, prio_dist, round(prio_vals[1], 6),
                     cap_points, neg_army))
            # valueFunc(current, prioVals): only the searching player's own
            # tiles with army > 1 and a non-positive army walk can record.
            if (
                current_tile.player == player_index
                and current_tile.army > 1
                and neg_army <= 0
            ):
                new_value = (
                    -(cap_points + neg_army),
                    -cap_points,
                    -neg_army)
                previous_record = recorded.get(prio_dist - 1)
                if (
                    previous_record is None
                    or previous_record[0] < new_value
                ):
                    current_record = recorded.get(prio_dist)
                    if (
                        current_record is None
                        or new_value > current_record[0]
                    ):
                        recorded[prio_dist] = (new_value, current_index)
            if prio_dist >= max_depth or cur_turns >= 100:
                continue
            current_dist_to_threat = threat_dist_raw[current_index]
            to_dist_tuple = (
                positions_by_turn[current_dist_to_threat]
                if 0 <= current_dist_to_threat < num_positions
                else None)
            for next_tile in current_tile.movable:
                next_index = next_tile.tile_index
                if next_index == from_index:
                    continue
                if (
                    next_tile.isMountain
                    or next_tile.isCostlyNeutral
                    or (not next_tile.discovered and next_tile.isNotPathable)
                ):
                    continue
                # prioFunc(next, prioVals) inline: expansion gates first.
                if not allowed_search_region[next_index]:
                    continue
                if next_tile.isCity and next_tile.isNeutral:
                    continue
                next_neg_army = neg_army
                next_cap_points = cap_points
                if team_ids[next_tile.player] == searching_team:
                    next_neg_army -= next_tile.army
                else:
                    next_neg_army += next_tile.army
                    next_cap_points += 1
                    if not next_tile.isNeutral:
                        next_cap_points += 1
                next_neg_army += 1
                from_euclid_cur = 100.0
                next_dist_to_threat = threat_dist_raw[next_index]
                next_dist_tuple = (
                    positions_by_turn[next_dist_to_threat - 1]
                    if 0 < next_dist_to_threat <= num_positions
                    else None)
                if next_dist_tuple is not None:
                    approx_x, approx_y = next_dist_tuple
                    from_euclid_cur = euclid_dist(
                        approx_x,
                        approx_y,
                        next_tile.x,
                        next_tile.y)
                    if to_dist_tuple is not None:
                        last_x, last_y = to_dist_tuple
                        # V1's isApproxMtn indexes the grid at the NEXT
                        # distance tuple's approx position (approxPos), not
                        # the last position — this gate mirrors that exactly.
                        if (
                            not grid[round(approx_y)][round(approx_x)]
                            .isObstacle
                            and current_dist_to_threat > next_dist_to_threat
                        ):
                            to_last_euclid = euclid_dist(
                                last_x,
                                last_y,
                                current_tile.x,
                                current_tile.y)
                            if from_euclid_cur < to_last_euclid + 0.5:
                                continue
                elif current_dist_to_threat > next_dist_to_threat:
                    continue
                heapq.heappush(
                    frontier,
                    (
                        (
                            prio_dist + 1,
                            from_euclid_cur,
                            next_cap_points,
                            next_neg_army,
                            next_tile,
                        ),
                        prio_dist + 1,
                        cur_turns + 1,
                        next_tile,
                        current_tile,
                        max_dict,
                    ))

        negative_indexes = (
            interception.positive_threat_subsegment_negative_tile_indexes)
        paths_by_dist: dict[int, list[int]] = {}
        # V1 iterates its recorded table in insertion order (ascending dist).
        for dist, record in recorded.items():
            # The search still records the dist-0 seed state so it can gate
            # the dist-1 record, but the reconstructed single-node path has
            # length 0 and breadth_first_dynamic_max_per_tile_per_distance
            # drops length-0 paths from its results entirely.
            if dist == 0:
                continue
            endpoint_index = record[1]
            # Walking parents from the recorded endpoint back to the choke
            # yields the source-to-choke order V1 evaluates after reversing
            # its choke-to-source search path.
            tile_indices: list[int] = []
            walk_index = endpoint_index
            while walk_index != NO_PARENT:
                tile_indices.append(walk_index)
                walk_index = visited_parent[walk_index]
            endpoint_tile = tiles_by_index[endpoint_index]
            if endpoint_tile in negative_indexes:
                all_in_set = True
                for threat in interception.threats:
                    if endpoint_tile not in threat.path.tileSet:
                        all_in_set = False
                        break
                if all_in_set:
                    continue
                army_fact = (
                    interception.base_threat_army * (dist + 1)) // (dist + 2)
                if endpoint_tile.army < army_fact:
                    continue
            paths_by_dist[dist] = tile_indices
        return paths_by_dist

    def evaluate_v1_search_paths_native(
        self,
        interception: ArmyInterception,
        context: V2NativeEvalContext,
        choke_search_depths: dict[Tile, int],
        positions_by_turn: list[tuple[float, float] | None],
        allowed_search_region: bytearray,
        tiles_by_index: list[Tile],
    ) -> dict[int, V2NativeOptionEntry]:
        """Evaluate V1's exact per-choke search paths through the native scorer.

        Mirrors V1's outer loop in _get_intercept_plan_options: per admissible
        choke (in common_intercept_chokes insertion order), iterate the
        search's recorded paths ascending by distance, score each natively,
        stop the choke on the first evaluation_continued=False, and fold the
        emitted entries into the curDist->winner table via _native_should_replace.
        """
        evals: list[V2NativeCandidateEval] = []
        best_table: dict[int, V2NativeOptionEntry] = {}
        for choke_tile in interception.common_intercept_chokes:
            search_depth = choke_search_depths.get(choke_tile)
            if search_depth is None:
                continue
            paths_by_dist = self._v1_get_intercept_paths_native(
                interception,
                choke_tile,
                search_depth,
                positions_by_turn,
                allowed_search_region,
                tiles_by_index)
            for dist, tile_indices in paths_by_dist.items():
                candidate = V2InterceptCandidate(
                    source_index=-1,
                    layer_index=-1,
                    choke_tile=choke_tile,
                    depth=dist,
                    friendly_army=0,
                    prescreen_value=0.0)
                candidate_eval = self._evaluate_candidate_native(
                    context,
                    candidate,
                    tile_indices)
                evals.append(candidate_eval)
                if not candidate_eval.evaluation_continued:
                    break
                for entry in candidate_eval.entries:
                    existing = best_table.get(entry.cur_dist)
                    if (
                        existing is None
                        or self._native_should_replace(
                            context,
                            existing,
                            entry)
                    ):
                        best_table[entry.cur_dist] = entry
        self.last_native_evals = evals
        return best_table

    def evaluate_candidates_native(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        layered_reaches: list[SourceLayeredReach],
        candidates: list[V2InterceptCandidate],
        turns_left_in_cycle: int,
        opponent_tracker: OpponentTracker,
        other_blocking: dict[Tile, ThreatBlockInfo] | None,
        average_enemy_position_by_turn: list[tuple[float, float] | None],
    ) -> dict[int, V2NativeOptionEntry]:
        """Natively score every retained candidate exactly like V1's scorer.

        Port of ArmyInterceptor._evaluate_intercept_path_into_table applied to
        reconstructed tile-index lists (plus a parallel move_half flag array)
        instead of Path objects, then folded into a plain-data shadow of V1's
        bestInterceptTable keyed by curDist. Returns the winning entry per
        curDist; also stores the per-candidate eval records on
        self.last_native_evals for shadow A/B comparison.
        """
        context = self._build_native_eval_context(
            interception,
            threat_reach,
            turns_left_in_cycle,
            opponent_tracker,
            other_blocking,
            average_enemy_position_by_turn)
        evals: list[V2NativeCandidateEval] = []
        best_table: dict[int, V2NativeOptionEntry] = {}
        # V1 iterates candidates choke-by-choke and breaks out of a choke's
        # path loop the first time an evaluation reports an unreachable
        # interception (returns False). Group the flat candidate list the
        # same way so candidates V1 would never reach do not emit table rows.
        # V1's per-choke path dict holds exactly one path per path length —
        # the maximum-valueFunc path its search found at that distance — so
        # each (choke, depth) group is collapsed to its V1-valueFunc winner
        # before evaluation, mirroring that one-path-per-length structure.
        candidates_by_choke: dict[int, list[V2InterceptCandidate]] = {}
        for candidate in candidates:
            candidates_by_choke.setdefault(
                candidate.choke_tile.tile_index,
                []).append(candidate)
        for choke_tile in interception.common_intercept_chokes:
            choke_candidates = candidates_by_choke.get(
                choke_tile.tile_index)
            if choke_candidates is None:
                continue
            depth_groups: dict[int, list[V2InterceptCandidate]] = {}
            for candidate in choke_candidates:
                depth_groups.setdefault(
                    candidate.depth,
                    []).append(candidate)
            # V1's breadth_first_dynamic_max_per_tile_per_distance records a
            # path at distance d only when its valueFunc strictly exceeds the
            # value recorded at d-1 (the maxDict gate in the global-visited
            # search loop), so a deeper candidate that is not strictly better
            # than the previous distance's record never reaches
            # _evaluate_intercept_path_into_table. Track the recorded key per
            # depth and skip depths V1's search would have dropped; a depth
            # with no recorded neighbor at d-1 records freely, matching the
            # maxMinusOne-is-None branch.
            recorded_key_by_depth: dict[int, tuple[int, int, int]] = {}
            for depth in sorted(depth_groups):
                depth_group = depth_groups[depth]
                # V1's search keeps exactly one path per length per choke —
                # the maximum-valueFunc path at that distance — and drops
                # paths whose source endpoint fails valueFunc entirely
                # (net-negative army, army<=1, or not the searching player),
                # so only the group winner is reconstructed and evaluated.
                winner_candidate: V2InterceptCandidate | None = None
                winner_indices: list[int] = []
                winner_key: tuple[int, int, int] | None = None
                for candidate in depth_group:
                    tile_indices = self._reconstruct_candidate_tile_indices(
                        layered_reaches[candidate.layer_index],
                        candidate)
                    candidate_key = self._v1_path_value_key(
                        context,
                        tile_indices)
                    if candidate_key is None:
                        continue
                    if winner_key is None or candidate_key > winner_key:
                        winner_candidate = candidate
                        winner_indices = tile_indices
                        winner_key = candidate_key
                if winner_candidate is None:
                    continue
                previous_record = recorded_key_by_depth.get(depth - 1)
                if (
                    previous_record is not None
                    and winner_key <= previous_record
                ):
                    continue
                recorded_key_by_depth[depth] = winner_key
                candidate_eval = self._evaluate_candidate_native(
                    context,
                    winner_candidate,
                    winner_indices)
                evals.append(candidate_eval)
                if not candidate_eval.evaluation_continued:
                    break
                for entry in candidate_eval.entries:
                    existing = best_table.get(entry.cur_dist)
                    if (
                        existing is None
                        or self._native_should_replace(
                            context,
                            existing,
                            entry)
                    ):
                        best_table[entry.cur_dist] = entry
        self.last_native_evals = evals
        return best_table

    def _v1_path_value_key(
        self,
        context: V2NativeEvalContext,
        tile_indices: list[int],
    ) -> tuple[int, int, int] | None:
        """V1's _get_intercept_paths valueFunc ranking for a path.

        V1's per-choke search keeps the max-valueFunc path per distance:
        (recapVal, -negTileCapPoints, -negArmy) where negArmy accumulates
        -(army-1) per friendly node and +(army+1) per enemy node, and
        negTileCapPoints counts each enemy node once plus once more when
        owned. The accumulation covers every path node except the choke
        (the BFS seeds the choke separately, a constant offset shared by
        all candidates at that choke). Returns None when the source
        endpoint fails V1's valueFunc checks (not the searching player,
        army <= 1, or a net-negative army walk), matching V1 dropping the
        path result entirely.
        """
        tiles_by_index = context.tiles_by_index
        team_ids = context.team_ids
        friendly_team = context.friendly_team
        source_tile = tiles_by_index[tile_indices[0]]
        if source_tile.player != context.map_player_index:
            return None
        if source_tile.army <= 1:
            return None
        net_army = 0
        cap_points = 0
        for tile_index in tile_indices[:-1]:
            tile = tiles_by_index[tile_index]
            if team_ids[tile.player] == friendly_team:
                net_army += tile.army - 1
            else:
                net_army -= tile.army + 1
                if tile.isNeutral:
                    cap_points += 1
                else:
                    cap_points += 2
        if net_army < 0:
            return None
        return (
            net_army - cap_points,
            -cap_points,
            net_army)

    def _build_native_eval_context(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        turns_left_in_cycle: int,
        opponent_tracker: OpponentTracker,
        other_blocking: dict[Tile, ThreatBlockInfo] | None,
        average_enemy_position_by_turn: list[tuple[float, float] | None],
    ) -> V2NativeEvalContext:
        """Precompute every V1-eval input that is constant per plan call."""
        game_map = self.v1.map
        best_threat_info = interception.best_enemy_threat
        best_threat = best_threat_info.threat
        best_threat_players = game_map.get_teammates(
            best_threat.threatPlayer)
        enemy_tiles = [node.tile for node in best_threat.path]
        # enemy physical-army prefix: index k mirrors enPhysicalArmy after V1's
        # main loop advances at enemy path node index k, so any post-loop enemy
        # walk can be resumed by index instead of re-walking PathMove links.
        enemy_prefix_army = [0] * len(enemy_tiles)
        accumulated = 0
        for index, tile in enumerate(enemy_tiles):
            if tile.player in best_threat_players:
                accumulated += tile.army - 1
            else:
                accumulated -= tile.army + 1
            enemy_prefix_army[index] = accumulated
        first_threat = interception.threats[0]
        team_ids = game_map.team_ids_by_player_index
        return V2NativeEvalContext(
            interception=interception,
            tiles_by_index=threat_reach.tiles_by_index,
            turns_left_in_cycle=turns_left_in_cycle,
            map_turn=game_map.turn,
            map_player_index=game_map.player_index,
            team_ids=team_ids,
            friendly_team=game_map.friendly_team,
            first_threat_team=team_ids[first_threat.threatPlayer],
            first_bmap_raw=first_threat.armyAnalysis.bMap.raw,
            best_threat=best_threat,
            best_threat_team=team_ids[best_threat.threatPlayer],
            best_threat_players=best_threat_players,
            best_bmap_raw=best_threat.armyAnalysis.bMap.raw,
            best_tile_distances_lookup=(
                best_threat.armyAnalysis.tileDistancesLookup),
            enemy_tiles=enemy_tiles,
            enemy_prefix_army=enemy_prefix_army,
            enemy_path_tile_set=best_threat.path.tileSet,
            enemy_path_value=int(best_threat.path.value),
            target_is_city=interception.target_tile.isCity,
            sparse_bonus=interception.sparse_recapture_bonus,
            sparse_len_cutoff=len(average_enemy_position_by_turn) / 2,
            contestable_city_dist=(
                interception.distance_from_threat_to_contestable_en_city),
            opponent_tracker=opponent_tracker,
            other_blocking=other_blocking,
            debug_bad_cutoff=max(1, interception.base_threat_army // 10),
            threat_values=interception.threat_values,
            threats=interception.threats,
            target_dist_raw=(
                game_map.distance_mapper.get_tile_dist_matrix(
                    interception.target_tile).raw),
            delay_split_by_source={},
            city_skip_by_source={},
        )

    def _evaluate_candidate_native(
        self,
        context: V2NativeEvalContext,
        candidate: V2InterceptCandidate,
        tile_indices: list[int],
    ) -> V2NativeCandidateEval:
        """Score one candidate exactly like V1's per-path option evaluation."""
        tiles_by_index = context.tiles_by_index
        tiles = [tiles_by_index[index] for index in tile_indices]
        move_half_flags = [False] * len(tiles)
        path_length = len(tiles) - 1
        tail_tile = tiles[-1]
        source_tile_index = tile_indices[0]
        source_tile = tiles[0]
        intercept_point_dist = context.first_bmap_raw[
            tail_tile.tile_index]

        city_skip = context.city_skip_by_source.get(source_tile_index)
        if city_skip is None:
            city_skip = self._native_is_threatened_city_source(
                context,
                source_tile)
            context.city_skip_by_source[source_tile_index] = city_skip
        if city_skip:
            return V2NativeCandidateEval(
                candidate=candidate,
                tile_indices=tile_indices,
                move_half_flags=move_half_flags,
                entries=[],
                evaluation_continued=True,
                skip_reason='threatened_friendly_city_source')

        if not context.target_is_city:
            addl_turns = max(0, intercept_point_dist - path_length)
        else:
            addl_turns = intercept_point_dist

        delay_split = context.delay_split_by_source.get(source_tile_index)
        if delay_split is None:
            delay_split = self._native_should_delay_or_split(
                context,
                source_tile)
            context.delay_split_by_source[source_tile_index] = delay_split
        should_delay, should_split = delay_split

        if (
            DEBUG_BYPASS_BAD_INTERCEPTIONS
            and source_tile.army <= context.debug_bad_cutoff
            and not should_delay
            and not should_split
        ):
            logbook.error(
                f'bypassed bad intercept plan {source_tile}->{tail_tile} '
                f'depth {candidate.depth}')
            return V2NativeCandidateEval(
                candidate=candidate,
                tile_indices=tile_indices,
                move_half_flags=move_half_flags,
                entries=[],
                evaluation_continued=True,
                skip_reason='debug_bypass_bad_interception')

        collision = self._native_collision_sim(context, tiles)
        if collision.best_case_intercept_turn == 1000:
            return V2NativeCandidateEval(
                candidate=candidate,
                tile_indices=tile_indices,
                move_half_flags=move_half_flags,
                entries=[],
                evaluation_continued=False,
                skip_reason='best_case_intercept_1000')

        blocked_damage, enemy_army_left, enemy_army_collided = (
            self._native_blocked_damage(
                context,
                collision.enemy_intercept_index,
                collision.enemy_physical_army_at_intercept,
                collision.friendly_army_at_intercept,
                context.best_bmap_raw[tail_tile.tile_index]))

        if context.other_blocking is not None:
            # Port of V1's otherThreatsBlockingTiles walk: any mid-path node
            # whose next tile is a blocked destination gets move_half forced
            # when the hold can be afforded; unaffordable holds invalidate.
            blocker_army = 0
            split_forced = False
            invalid = False
            node_count = len(tiles)
            for node_index in range(node_count):
                tile = tiles[node_index]
                if context.team_ids[tile.player] == context.friendly_team:
                    blocker_army += tile.army - 1
                else:
                    blocker_army -= tile.army + 1
                tile_hold = context.other_blocking.get(tile)
                if (
                    tile_hold is not None
                    and node_index + 1 < node_count
                    and tiles[node_index + 1] in tile_hold.blocked_destinations
                ):
                    if tile_hold.amount_needed_to_block > blocker_army // 2:
                        invalid = True
                        logbook.error(
                            f'bypassed unsplittable intercept plan '
                            f'{source_tile}->{tail_tile} due to blocker '
                            f'{tile_hold} and split army {blocker_army}')
                        break
                    if enemy_army_left > 0:
                        move_half_flags[node_index] = True
                        split_forced = True
                        blocker_army = blocker_army // 2
            if invalid:
                return V2NativeCandidateEval(
                    candidate=candidate,
                    tile_indices=tile_indices,
                    move_half_flags=move_half_flags,
                    entries=[],
                    evaluation_continued=True,
                    skip_reason='unsplittable_blocked_destination')
            # V1 re-runs _get_value_of_threat_blocked when a split is forced,
            # but move_half is not read by the collision sim or the backward
            # damage walk, so the recalculated values are identical.
            _ = split_forced

        full_addl_turns = addl_turns + (1 if should_split else 0)

        raw_value_no_recap, turns_used_with_recap, recap_turns_used = (
            self._native_path_econ_values(
                context,
                tiles,
                move_half_flags,
                0 - enemy_army_left,
                full_addl_turns))

        # V1 sets path.start.move_half only AFTER the econ value calc: the
        # split is for safety, not because recapture uses only the half.
        if should_split:
            move_half_flags[0] = True

        intercept_info = context.interception.common_intercept_chokes[
            candidate.choke_tile]
        turns_used_with_recap += intercept_info.max_extra_moves_to_capture

        new_value = raw_value_no_recap + blocked_damage
        base_len = turns_used_with_recap - recap_turns_used
        if (
            addl_turns == 0
            and collision.worst_case_intercept_turn < 5
            and base_len < context.sparse_len_cutoff
        ):
            sparse_bonus = context.sparse_bonus
            logbook.info(
                f'INCLUDING SPARSE BONUS OF {sparse_bonus:.2f} DUE TO '
                f'addlTurnsToReachThreatWorstCase {addl_turns}, '
                f'worstCaseInterceptMoves '
                f'{collision.worst_case_intercept_turn}, baseLen {base_len} '
                f'< sparseLenCutoff {context.sparse_len_cutoff}')
            new_value += sparse_bonus

        entries: list[V2NativeOptionEntry] = []
        candidate_eval = V2NativeCandidateEval(
            candidate=candidate,
            tile_indices=tile_indices,
            move_half_flags=move_half_flags,
            entries=entries,
            evaluation_continued=True,
            skip_reason='')
        for cur_dist in range(base_len, turns_used_with_recap + 1):
            recap_turns = cur_dist - base_len
            this_value = new_value + recap_turns * RECAPTURE_VALUE
            if (
                context.contestable_city_dist >= 0
                and recap_turns >= context.contestable_city_dist
            ):
                army_reaching_contestable = max(
                    0,
                    enemy_army_collided - enemy_army_left
                    - 2 * context.contestable_city_dist)
                if army_reaching_contestable > 0:
                    this_value += (
                        context.opponent_tracker
                        .estimate_city_contest_econ_value(
                            asPlayer=context.map_player_index,
                            enPlayer=(
                                context.threats[0].threatPlayer),
                            armyReachingContestableCity=(
                                army_reaching_contestable)))
            this_value -= 0.06 * base_len
            entries.append(
                V2NativeOptionEntry(
                    cur_dist=cur_dist,
                    this_value=this_value,
                    damage_blocked=blocked_damage,
                    enemy_army_left_after_intercept=enemy_army_left,
                    best_case_intercept_moves=(
                        collision.best_case_intercept_turn),
                    worst_case_intercept_moves=(
                        collision.worst_case_intercept_turn),
                    recapture_turns=recap_turns,
                    required_delay=1 if should_delay else 0,
                    friendly_army_reaching_intercept=(
                        enemy_army_collided - enemy_army_left),
                    candidate_eval=candidate_eval))
        return candidate_eval

    def _native_is_threatened_city_source(
        self,
        context: V2NativeEvalContext,
        source_tile: Tile,
    ) -> bool:
        """Port of V1's _is_intercept_from_threatened_friendly_city."""
        if not source_tile.isCity:
            return False
        if context.team_ids[source_tile.player] != context.friendly_team:
            return False
        for threat in context.threats:
            if (
                threat.path.tail.tile is source_tile
                and threat.threatValue > threat.turns // 2
            ):
                return True
        return False

    def _native_should_delay_or_split(
        self,
        context: V2NativeEvalContext,
        source_tile: Tile,
    ) -> tuple[bool, bool]:
        """Port of V1's _should_delay_or_split (depends only on path.start)."""
        first_threat = context.threats[0]
        is_two_away = (
            context.first_bmap_raw[source_tile.tile_index] == 2)
        if not is_two_away and source_tile.isGeneral:
            low_general_army_cutoff = max(
                1,
                first_threat.threatValue // 10)
            tiles_at_dist = (
                first_threat.armyAnalysis.tileDistancesLookup.get(1))
            if (
                tiles_at_dist is not None
                and len(tiles_at_dist) == 1
                and source_tile.army <= low_general_army_cutoff
            ):
                return True, False
            return False, False
        if not is_two_away:
            return False, False

        allow_split = True
        threat_nexts: set[Tile] = set()
        us_nexts: set[Tile] = set()
        for threat_info in context.threat_values:
            tiles_at_dist = (
                threat_info.threat.armyAnalysis.tileDistancesLookup.get(1))
            threat_base = threat_info.threat.path.start.tile.army
            if tiles_at_dist:
                for threat_next in tiles_at_dist:
                    if (
                        context.team_ids[threat_next.player]
                        == context.team_ids[
                            threat_info.threat.threatPlayer]
                    ):
                        threat_army = threat_base + threat_next.army - 1
                    else:
                        threat_army = threat_base - threat_next.army - 1
                    half_lower = source_tile.army // 2
                    if half_lower < threat_army - 1:
                        allow_split = False
                    threat_nexts.add(threat_next)
                    if threat_next in source_tile.movable:
                        us_nexts.add(threat_next)

        should_delay = False
        should_split = False
        if (
            len(threat_nexts) > 1
            and len(us_nexts) > 1
            and threat_nexts.issubset(us_nexts)
        ):
            if not allow_split:
                should_delay = True
            else:
                should_split = True
        if should_delay:
            should_split = False
        return should_delay, should_split

    def _native_collision_sim(
        self,
        context: V2NativeEvalContext,
        tiles: list[Tile],
    ) -> V2NativeCollisionResult:
        """Port of V1's _get_result_of_executing_paths_to_intercept_point.

        Enemy path nodes are indexed by position (enemy index == loop counter
        i) so the physical-army prefix array replaces the PathMove walk.
        """
        enemy_tiles = context.enemy_tiles
        enemy_prefix = context.enemy_prefix_army
        enemy_last_index = len(enemy_tiles) - 1
        path_last_index = len(tiles) - 1
        turns_left_in_cycle = context.turns_left_in_cycle
        tile_distances_lookup = context.best_tile_distances_lookup

        # friendly accumulated army prefix, matching V1's
        # _advance_friendly_intercept_army: friendly -> +army-1 else -army-1.
        # (step_deltas.friendly_step_delta is NOT used here: its -1 rule for
        # positive_threat_subsegment_negative tiles diverges from V1's scorer.)
        friendly_team = context.friendly_team
        team_ids = context.team_ids
        friendly_prefix = [0] * len(tiles)
        accumulated = 0
        for index, tile in enumerate(tiles):
            if team_ids[tile.player] == friendly_team:
                accumulated += tile.army - 1
            else:
                accumulated -= tile.army + 1
            friendly_prefix[index] = accumulated

        enemy_physical = 0
        friendly_army = 0
        best_case = 1000
        worst_case = 1000
        enemy_intercept_index = -1
        turns_left = turns_left_in_cycle
        closest_index = -1
        closest_manhattan = 1000
        closest_friendly = 0
        closest_enemy_physical = 0
        direct_concrete_index = -1
        direct_concrete_enemy_physical = 0
        direct_concrete_friendly = 0
        same_tile_index = -1
        same_tile_enemy_physical = 0
        same_tile_friendly = 0

        i = 0
        enemy_index = 0
        while i <= path_last_index:
            if turns_left == 0:
                break
            if enemy_index > enemy_last_index:
                break
            enemy_physical_before = enemy_physical
            friendly_before = friendly_army
            enemy_physical = enemy_prefix[enemy_index]
            enemy_intercept_index = enemy_index
            turns_left -= 1
            friendly_army = friendly_prefix[i]
            tile = tiles[i]
            tiles_at_dist = tile_distances_lookup.get(i)
            direct_intercept = False

            if tiles_at_dist:
                # Middle-tile closest-approach tracking: heuristic fallback
                # positions for candidates that never truly collide. Manual
                # argmin keeps V1's first-minimum tie behavior without
                # allocating a lambda per loop iteration.
                x_sum = 0
                y_sum = 0
                for dist_tile in tiles_at_dist:
                    x_sum += dist_tile.x
                    y_sum += dist_tile.y
                avg_x = x_sum / len(tiles_at_dist)
                avg_y = y_sum / len(tiles_at_dist)
                closest_enemy_tile = tiles_at_dist[0]
                best_centroid_dist = (
                    abs(closest_enemy_tile.x - avg_x)
                    + abs(closest_enemy_tile.y - avg_y))
                for dist_tile in tiles_at_dist:
                    centroid_dist = (
                        abs(dist_tile.x - avg_x)
                        + abs(dist_tile.y - avg_y))
                    if centroid_dist < best_centroid_dist:
                        closest_enemy_tile = dist_tile
                        best_centroid_dist = centroid_dist
                manhattan = (
                    abs(tile.x - closest_enemy_tile.x)
                    + abs(tile.y - closest_enemy_tile.y))
                if manhattan < closest_manhattan:
                    closest_index = i
                    closest_manhattan = manhattan
                    closest_friendly = friendly_army
                    closest_enemy_physical = enemy_physical

            if i == 0:
                if (
                    tiles_at_dist
                    and len(tiles_at_dist) == 1
                    and path_last_index == 1
                    and tiles[1] is tiles_at_dist[0]
                ):
                    worst_case = min(i + 1, worst_case)
                    best_case = min(i + 1, best_case)
                    direct_intercept = True
            elif tiles_at_dist:
                all_in_movable = len(tiles_at_dist) < 4
                found_at_dist = False
                for dist_tile in tiles_at_dist:
                    if tile in dist_tile.movable:
                        # hasPrio is hardcoded True in V1, so offs stays 1.
                        best_case = min(best_case, i + 1)
                        if (
                            dist_tile is enemy_tiles[i]
                            and direct_concrete_index < 0
                        ):
                            direct_concrete_index = i
                            direct_concrete_enemy_physical = enemy_physical
                            direct_concrete_friendly = friendly_army
                    elif dist_tile is tile:
                        found_at_dist = True
                        if (
                            i == path_last_index
                            and team_ids[tile.player] == friendly_team
                        ):
                            # Same-tile friendly collision: our move lands
                            # first and reinforces the tail garrison, so the
                            # defending army includes the full tile army.
                            same_tile_index = i
                            same_tile_enemy_physical = enemy_physical_before
                            same_tile_friendly = friendly_before + tile.army
                        if len(tiles_at_dist) == 1:
                            direct_intercept = True
                            worst_case = min(i, worst_case)
                        best_case = min(best_case, i)
                    elif all_in_movable:
                        all_in_movable = False

                if (
                    not found_at_dist
                    and tile in context.enemy_path_tile_set
                ):
                    threat_dist = context.best_bmap_raw[tile.tile_index]
                    if threat_dist > 0:
                        best_case = min(best_case, threat_dist)

                if all_in_movable:
                    offs = 0 if direct_intercept else 1
                    worst_case = min(i + offs, worst_case)

            if direct_intercept:
                if (
                    i != path_last_index
                    and (
                        i + 1 > path_last_index
                        or tiles[i + 1] is not tiles[path_last_index]
                    )
                ):
                    logbook.error(
                        f'WARNING, BAD DIRECT INTERCEPT DETECTED, PROBABLY '
                        f'SHOULD DROP THIS IMMEDIATELY FROM INTERCEPT OUTPUT! '
                        f'{tile}, interceptPath '
                        f'{tiles[0]}..{tiles[path_last_index]}')
                break

            enemy_index += 1
            i += 1

        # Scenario 1: same-tile direct collision at the candidate tail.
        if (
            worst_case == 1000
            and best_case < 1000
            and closest_index >= 0
            and tiles[closest_index] is tiles[path_last_index]
        ):
            worst_case = best_case
            if same_tile_index >= 0:
                enemy_physical = same_tile_enemy_physical
                friendly_army = same_tile_friendly

        # Scenario 2a: concrete movable-adjacent collision while synchronized.
        if worst_case == 1000 and direct_concrete_index >= 0:
            worst_case = best_case
            enemy_physical = direct_concrete_enemy_physical
            friendly_army = direct_concrete_friendly
            enemy_intercept_index = direct_concrete_index
            enemy_index = direct_concrete_index + 1

        # Scenario 2b: friendly waits at tail; enemy walks until adjacent.
        if worst_case == 1000 and enemy_index <= enemy_last_index:
            tail_tile = tiles[path_last_index]
            waiting_index = enemy_index
            waiting_physical = enemy_physical
            waiting_turn = i
            while (
                waiting_index <= enemy_last_index
                and waiting_turn < turns_left_in_cycle
            ):
                waiting_physical = enemy_prefix[waiting_index]
                if tail_tile in enemy_tiles[waiting_index].movable:
                    best_case = waiting_turn
                    worst_case = waiting_turn
                    turns_left = turns_left_in_cycle - waiting_turn
                    enemy_physical = waiting_physical
                    enemy_intercept_index = waiting_index
                    enemy_index = waiting_index + 1
                    break
                waiting_index += 1
                waiting_turn += 1

        # Scenario 3: closest middle-tile chase fallback.
        if worst_case == 1000 and closest_index >= 0:
            fallback_index = closest_index
            extra_enemy_moves = 0
            while (
                extra_enemy_moves < closest_manhattan
                and fallback_index + 1 <= enemy_last_index
            ):
                fallback_index += 1
                extra_enemy_moves += 1
            fallback_turn = closest_index + extra_enemy_moves
            best_case = fallback_turn
            worst_case = fallback_turn
            turns_left = turns_left_in_cycle - fallback_turn
            friendly_army = closest_friendly
            enemy_physical = enemy_prefix[fallback_index]
            enemy_intercept_index = fallback_index
            enemy_index = fallback_index + 1

        # Advance the enemy to the worst-case intercept turn (or its path end
        # when no intercept was ever found). This must accumulate like V1's
        # running enPhysicalArmy: scenario 1 can reset enemy_physical to a
        # pre-tile value while enemy_index keeps the synchronized position,
        # so prefix indexing would incorrectly re-add skipped enemy nodes.
        threat_players = context.best_threat_players
        turns_used = turns_left_in_cycle - turns_left
        while turns_used < worst_case and enemy_index <= enemy_last_index:
            turns_used += 1
            turns_left -= 1
            enemy_tile = enemy_tiles[enemy_index]
            if enemy_tile.player in threat_players:
                enemy_physical += enemy_tile.army - 1
            else:
                enemy_physical -= enemy_tile.army + 1
            enemy_intercept_index = enemy_index
            enemy_index += 1

        if enemy_index > enemy_last_index and self.v1.log_debug:
            logbook.error(
                f'we got to the end of the enemy path before we got past our '
                f'worst case intercept turn {worst_case} (turnsUsed '
                f'{turns_used})')

        best_case = min(best_case, worst_case)
        return V2NativeCollisionResult(
            enemy_intercept_index=enemy_intercept_index,
            enemy_physical_army_at_intercept=enemy_physical,
            friendly_army_at_intercept=friendly_army,
            best_case_intercept_turn=best_case,
            worst_case_intercept_turn=worst_case)

    def _native_blocked_damage(
        self,
        context: V2NativeEvalContext,
        enemy_intercept_index: int,
        enemy_physical_at_intercept: int,
        friendly_army_at_intercept: int,
        intercept_dist_from_target: int,
    ) -> tuple[float, int, int]:
        """Port of V1's _get_value_of_threat_blocked backward damage walk.

        Returns (econValueBlocked, enemyArmyLeftAtIntercept,
        enemyArmyCollidedWithAtIntercept).
        """
        enemy_tiles = context.enemy_tiles
        enemy_team = context.best_threat_team
        friendly_team = context.friendly_team
        team_ids = context.team_ids
        turns_left_in_cycle = context.turns_left_in_cycle
        en_army = context.enemy_path_value
        en_len = len(enemy_tiles) - 1

        # Skip backwards until the threat is actually capturing tiles.
        while en_len >= 0 and en_army < 0 and en_len > intercept_dist_from_target:
            tile = enemy_tiles[en_len]
            if team_ids[tile.player] == enemy_team:
                en_army -= tile.army
            else:
                en_army += tile.army
            en_army += 1
            en_len -= 1

        en_army -= friendly_army_at_intercept
        blocked_damage = 0.0
        main_damage_complete = False
        turns_left = turns_left_in_cycle
        while en_len >= 0:
            if turns_left <= 0:
                main_damage_complete = True
            if en_army > 0:
                break
            if en_len <= intercept_dist_from_target:
                break
            tile = enemy_tiles[en_len]
            if team_ids[tile.player] == enemy_team:
                en_army -= tile.army
            else:
                en_army += tile.army
                if team_ids[tile.player] == friendly_team:
                    if tile.isGeneral and en_army < 0:
                        blocked_damage += GENERAL_CAP_VALUE
                    elif tile.isCity:
                        if not main_damage_complete:
                            blocked_damage += turns_left_in_cycle - en_len
                        if en_army < 0:
                            blocked_damage += OWNED_CITY_CAP_VALUE_BONUS
                    if not main_damage_complete:
                        blocked_damage += TARGET_CAP_VALUE
                elif tile.player >= 0:
                    if not main_damage_complete:
                        blocked_damage += NEUTRAL_CAP_VALUE
                else:
                    if not main_damage_complete:
                        blocked_damage += OTHER_PARTY_CAP_VALUE
            en_army += 1
            en_len -= 1
            turns_left -= 1

        enemy_army_left = (
            enemy_physical_at_intercept - friendly_army_at_intercept)
        enemy_army_collided = enemy_physical_at_intercept
        if (
            en_len >= 0
            and enemy_intercept_index >= 0
            and enemy_tiles[en_len] is enemy_tiles[enemy_intercept_index]
        ):
            # Stopped the army exactly at the intercept tile; V1 only logs.
            pass
        elif enemy_army_left <= 0 and self.v1.log_debug:
            intercept_tile = (
                enemy_tiles[enemy_intercept_index]
                if enemy_intercept_index >= 0
                else None)
            logbook.error(
                f'wtf broke somewhere other than the expected intercept '
                f'spot? node index {en_len} vs {intercept_tile}. '
                f'enemyArmyLeftAtInterceptPointBeforeRemainingCapture '
                f'{enemy_army_left}')

        return blocked_damage, enemy_army_left, enemy_army_collided

    def _native_path_econ_values(
        self,
        context: V2NativeEvalContext,
        tiles: list[Tile],
        move_half_flags: list[bool],
        friendly_remaining_army: int,
        include_recapture_start_dist: int,
    ) -> tuple[float, int, int]:
        """Port of V1's _get_path_econ_values_for_player.

        Returns (rawValueNoRecaptures, turnsUsedWithRecaps, recaptureTurns).
        """
        friendly_team = context.friendly_team
        first_threat_team = context.first_threat_team
        team_ids = context.team_ids
        map_turn = context.map_turn
        cycle_end = map_turn + context.turns_left_in_cycle
        val = 0.0
        city_hold_turns = 0
        cur_turn = map_turn
        army_left = 0
        for index, tile in enumerate(tiles):
            if army_left <= 0 and cur_turn > map_turn:
                cur_turn += 1
                break
            if team_ids[tile.player] != friendly_team:
                army_left -= tile.army
                if army_left > 0:
                    is_target = team_ids[tile.player] == first_threat_team
                    if tile.isGeneral and is_target:
                        val += GENERAL_CAP_VALUE
                    if tile.isCity:
                        city_hold_turns += cycle_end - cur_turn
                        if is_target:
                            val += OWNED_CITY_CAP_VALUE_BONUS
                            city_hold_turns += cycle_end - cur_turn
                    if is_target:
                        val += TARGET_CAP_VALUE
                    elif tile.player >= 0:
                        val += OTHER_PARTY_CAP_VALUE
                    else:
                        val += NEUTRAL_CAP_VALUE
            else:
                army_left += tile.army
                if move_half_flags[index]:
                    cur_turn += 1
            army_left -= 1
            cur_turn += 1
            if cur_turn > cycle_end:
                break

        # V1 counts the first tile as a move; undo that one extra turn.
        cur_turn -= 1
        # friendlyRemainingArmy is always provided by the caller.
        army_left = friendly_remaining_army

        raw_value_no_recap = val
        recaps = 0
        if cycle_end > cur_turn and army_left > 0:
            left = cycle_end - cur_turn
            # V1 adds cityHoldTurns // 2 into valWithRecaptures only, never to
            # the raw value the option table uses.
            if include_recapture_start_dist >= 0:
                left -= include_recapture_start_dist
                cur_turn += include_recapture_start_dist
                recaps = max(0, min(left, army_left // 2))
                cur_turn += recaps

        turns_used_with_recap = cur_turn - map_turn
        return raw_value_no_recap, turns_used_with_recap, recaps

    def _native_should_replace(
        self,
        context: V2NativeEvalContext,
        existing: V2NativeOptionEntry,
        candidate: V2NativeOptionEntry,
    ) -> bool:
        """Port of V1's _should_replace_best_intercept_option ordering."""
        if candidate.this_value < existing.this_value:
            return False
        if candidate.this_value > existing.this_value:
            return True
        if (
            candidate.worst_case_intercept_moves
            < existing.worst_case_intercept_moves
        ):
            return True
        if (
            candidate.worst_case_intercept_moves
            > existing.worst_case_intercept_moves
        ):
            return False
        candidate_tail = candidate.candidate_eval.tile_indices[-1]
        existing_tail = existing.candidate_eval.tile_indices[-1]
        return (
            context.target_dist_raw[candidate_tail]
            < context.target_dist_raw[existing_tail])

    def _write_native_table_options(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        native_table: dict[int, V2NativeOptionEntry],
        best_intercept_table: dict[int, InterceptionOptionInfo],
    ) -> None:
        """Emit real InterceptionOptionInfo rows from native winners.

        Only used when V2_SKIP_V1_WINNER_REEVAL is enabled after the shadow
        A/B proves native agreement; applies the eval's final move_half flags
        (blocker-walk splits and shouldSplit) to the reconstructed Path.
        """
        for cur_dist in sorted(native_table):
            entry = native_table[cur_dist]
            candidate_eval = entry.candidate_eval
            path = self.build_path_from_tile_indices(
                threat_reach.tiles_by_index,
                candidate_eval.tile_indices)
            if any(candidate_eval.move_half_flags):
                node_index = 0
                for node in path:
                    if candidate_eval.move_half_flags[node_index]:
                        node.move_half = True
                    node_index += 1
            option = InterceptionOptionInfo(
                path,
                entry.this_value,
                entry.cur_dist,
                damageBlocked=entry.damage_blocked,
                interceptingArmyRemaining=(
                    entry.enemy_army_left_after_intercept),
                bestCaseInterceptMoves=entry.best_case_intercept_moves,
                worstCaseInterceptMoves=entry.worst_case_intercept_moves,
                recaptureTurns=entry.recapture_turns,
                requiredDelay=entry.required_delay,
                friendlyArmyReachingIntercept=(
                    entry.friendly_army_reaching_intercept))
            option.intercept = interception
            # native_table already resolved the per-cur_dist winner, so this
            # is a direct write, not a _should_replace comparison.
            best_intercept_table[cur_dist] = option
