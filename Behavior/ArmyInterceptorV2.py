from __future__ import annotations

import heapq
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

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
from Behavior.ArmyInterceptionPreselection import (
    PreselectionResult,
    evaluate_preselected,
)
from Behavior.ArmyInterceptionProxy import (
    V2ProxyShadowResult,
    compare_route_proxy,
)
from DangerAnalyzer import ThreatObj, ThreatType
from Path import Path
from Strategy import OpponentTracker
from base.client.map import MapBase, Tile


# When False (the default), every native table winner is re-verified by running
# V1's _evaluate_intercept_path_into_table on a reconstructed Path so the real
# option table is written by V1 itself. When True, the native scorer's values
# are written into InterceptionOptionInfo objects directly, skipping the V1
# winner re-evaluation entirely. Only enable after the shadow A/B shows the
# native port agrees with V1 on essentially every emitted entry.
V2_SKIP_V1_WINNER_REEVAL = True
# When True, V2's candidate set comes from a native port of V1's per-choke
# breadth_first_dynamic_max_per_tile_per_distance search, so exactly the
# paths V1's own search would produce are evaluated. When False (the
# default), V2 generates candidates from the BFS matrices instead: one
# multi-source friendly reach, one choke-budget reach, and per-source
# layered reaches for every budget-reachable source — eliminating V1's
# per-choke heap search cost while keeping the same candidate coverage.
V2_USE_V1_EXACT_SEARCH = False


class V2ThreatDamageMode(Enum):
    THREAT_PATHS = 'threat_paths'
    UNRESTRICTED = 'unrestricted'


V2_THREAT_DAMAGE_MODE: V2ThreatDamageMode = V2ThreatDamageMode.THREAT_PATHS
UNREACHABLE_DISTANCE = 1000
NO_PARENT = -1
# Parent-chained multi-source wave top-K. V2's original design intent:
# scan the friendly/threat matrices, find the handful of armies that can
# produce the highest-value intercept options, and only build bounded
# per-source layered reaches for those. The layered reach is deleted
# entirely now: ONE multi-source BFS fans out from every candidate
# source at once, keeping the best state PER SOURCE per (tile, depth)
# slot ordered by army_at_arrival, and each kept state carries a
# parent link to the (tile', depth-1) state it expanded from — so
# every candidate path reconstructs by walking parent links back to a
# depth-0 source seed with no per-source reach and no per-choke
# distance matrices at all.
#
# The earlier top-K-per-tile wave (pre-layered-reach) evicted
# late-but-big sources at intermediate tiles before they could push
# into a choke (shadow_ab.py LOST_SOURCE_NOT_SELECTED,
# Tests/test_ArmyInterception.py::
# test_should_not_use_defensive_intercept_tile_for_expansion turns
# 238-253: the 47-army winner's wave was evicted at every choke
# neighbor by earlier-turn arrivals). Per-(tile, depth) slots with
# per-source retention fix the structural blindness: a distant strong
# source only competes with its own alternative arrivals, so its
# chain survives to the choke at its own BFS depth instead of being
# evicted by other sources' shallower waves — matching the coverage of
# V1's independent per-source searches.


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
    searched_choke_indices: set[int]
    """tile_index of every choke V1 would search this call
    (choke_search_depths keys). The multi-source wave records every
    kept state it produces on these tiles; only states at these chokes
    are candidate-eligible."""


@dataclass(slots=True)
class FriendlyMultiSourceMatrix:
    candidate_sources: list[Tile]
    ownership_scores: list[float]
    selected_source_indices: list[int]
    """Sources that produced at least one candidate-admissible kept
    wave state at a searched choke (depth <= min(search_depth,
    max_depth)) — the wave's equivalent of the old admissible-source
    pool and the set shadow_ab's LOST_SOURCE_NOT_SELECTED check
    validates against."""
    states_by_depth: list[dict[int, list[V2WaveState]]]
    """Every kept wave state per (tile_index, depth) slot: the best
    arrival per source that the multi-source BFS retained. Choke-tile
    slots hold the raw candidate pool; interior slots exist only to
    chain candidate paths back to their source seeds."""
    alternates_by_depth: list[dict[int, list[V2WaveState]]]
    """Same-source pushes into a (tile_index, depth) slot that lost the
    slot's per-source dedupe while tying the kept state's
    (net_army, cap_points) — the wave's equivalent of the deleted
    layered reach's equal_alternates pool. _runner_up_paths splices
    these prefixes into a gate-rejected group winner's suffix to retry
    the equal-valueFunc alternates V1's heap could have popped
    instead."""


@dataclass(slots=True)
class V2WaveState:
    """One kept (tile, depth) state in the parent-chained wave.

    net_army accumulates V1's prioFunc army walk over the path nodes
    BEFORE this tile: +(army-1) per friendly-team node and -(army+1)
    per enemy or neutral node, exactly matching
    _advance_friendly_intercept_army and _v1_path_value_key. The
    endpoint tile's own contribution is excluded because it is
    identical for every push to that tile — so the stored value is the
    path-value walk over tiles[:-1] that _v1_path_value_key computes.
    cap_points mirrors V1's negTileCapPoints (0 friendly, 1 neutral, 2
    enemy-owned) over the same prefix.

    The source->tile index chain is stored as a parent_state linked
    list (kept states are immutable and never replaced, so sharing the
    prefix chain is free). _state_tile_indices materializes the chain
    when a candidate path is reconstructed; every chain terminates at
    a depth-0 source seed, so the walk always produces a complete
    source->choke path. A per-source claim bitset bounds each source
    to one state per tile, which also makes ancestor cycles
    impossible: a push into a tile the source already claimed at an
    earlier depth is skipped, so a chain can never revisit a tile.
    """

    tile_index: int
    depth: int
    source_index: int
    net_army: int
    cap_points: int
    parent_state: V2WaveState | None
    # The fromEuclidCur element of the prio tuple V1's heap would hold
    # for this state's push (euclidDistExp scale — squared euclid,
    # ordering-equivalent — to positions_by_turn[threat_dist-1],
    # 10000.0 fallback matching V1's 100.0 squared). -1.0 means not yet
    # computed: it is only needed when two same-source pushes into the
    # same slot tie on every earlier heap field, at which point
    # _v1_wave_parent_pop_key computes and caches it lazily.
    push_euclid: float = -1.0


@dataclass(slots=True)
class V2InterceptCandidate:
    source_index: int
    wave_state: V2WaveState | None
    """The kept wave state whose parent chain is this candidate's
    source->choke path. None only for candidates synthesized by the
    V2_USE_V1_EXACT_SEARCH branch, which carries its tile list
    directly."""
    choke_tile: Tile
    depth: int
    friendly_army: int
    prescreen_value: float
    group_key: tuple[int, int, int] | None
    """V1's max-valueFunc-per-distance ranking for this candidate's
    wave endpoint state, computed at build time from the state's
    stored (net_army, cap_points) — identical to the +(army-1)/
    -(army+1), +0/+1|+2 cap walk over tiles[:-1] that
    _v1_path_value_key performs. None mirrors _v1_path_value_key
    returning None (source not owned by the searching player, army
    <= 1, or net-negative army walk): the candidate cannot be its
    (choke, depth) group winner."""


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
    positions_by_turn: list[tuple[float, float] | None]
    """averageEnemyPositionByTurn passthrough — V1's prioFunc endpoint
    euclid (euclid from a tile to the threat's approx position at that
    tile's threat-distance) used to break equal-valueFunc candidate ties
    in heap pop order."""
    threat_dist_raw: list[int]
    """distance_mapper matrix to interception.threats[0].path.start.tile —
    V1's threatDistMap, used to index positions_by_turn for endpoint
    pop-order euclids."""


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
    bound_group: V2BoundGroup | None = None
    """The bound record this eval was (or would have been) gated by.
    Shadow A/B reads it to check bound - actual value margins; None
    only for evals produced under V2_USE_V1_EXACT_SEARCH or the
    preselection path, whose rows carry no admissible bound."""


@dataclass(slots=True)
class V2BoundContext:
    """Per-call inputs for the admissible candidate upper bound."""

    army_bound_by_source: list[list[int]]
    """army_bound_by_source[source_index][d] = maximum
    (net_army + bound_delta(tile)) over the source's kept wave states
    at depth <= d, where bound_delta is tile.army for friendly tiles
    (covers the collision sim's same-tile full-garrison reinforcement)
    and -(army+1) otherwise. This bounds friendly_army_at_intercept for
    every path the source could produce through depth d, including
    equal-key alternate splices (whose prefixes are kept states of the
    same source) and mid-path peaks."""
    enemy_min_prefix_army: int
    """min(0, min(enemy_prefix_army)) — lowest physical army the threat
    can carry at any intercept node, driving the worst-case recapture
    allowance."""
    first_threat_player_count: int
    """Players on interception.threats[0]'s team — bounds the number of
    enemy general tiles (one per player) a path could capture."""


@dataclass(slots=True)
class V2FallbackPath:
    """One lazily materialized non-winner path in V1 record order.

    sort_key is the same key the eager fallback build sorted by:
    (-group_key[0], -group_key[1], -group_key[2]) followed by the V1
    endpoint pop key, so stable ordering is preserved exactly.
    """

    sort_key: tuple
    candidate: V2InterceptCandidate
    tile_indices: list[int]


@dataclass(slots=True)
class V2BoundGroup:
    """One recorded (choke, depth) group's admissible value bound.

    bound(c) for a possible curDist key c is
        bound_base + (c - key_lo) * RECAPTURE_VALUE
        + (city_value_bound if c >= city_step_key else 0)
    which provably >= the thisValue any of the group's paths (winner
    plus equal-key alternates) could emit at key c: raw econ is
    bounded per path length, blocked damage via _estimate_threat_
    blocked at the per-source army bound (monotone in army),
    recapture turns by c - key_lo since base_len >= key_lo, the city
    contest bonus by the bounded army reaching the contestable city,
    and the -0.06*baseLen penalty is relaxed to the smallest possible
    base length."""
    choke_tile: Tile
    group_index: int
    """Position inside the choke's sorted-depth recorded group list."""
    v1_eval_order: int
    """Sequential rank in V1's choke-major, depth-ascending evaluation
    order; used to rebuild V1's first-write dict ordering regardless of
    the bound-sorted processing order."""
    candidate: V2InterceptCandidate
    """The group's V1-valueFunc winner — the only candidate whose rows
    V1 would emit."""
    tile_indices: list[int]
    """The winner's materialized source->choke path (built once and
    reused for both the bound's prefix walk and the native eval)."""
    winner_key: tuple[int, int, int]
    key_lo: int
    """Lower bound on the group's base_len — the smallest possible
    turns-used-without-recapture the econ walk could produce (earliest
    army-death break, full-walk, or cycle-end truncation), so every
    real key is >= key_lo."""
    key_hi: int
    """Upper bound on turns_used_with_recap + max_extra — the largest
    curDist key the group could emit (twr <= turns_left + max_extra)."""
    bound_base: float
    """Key-independent bound terms: raw econ cap + blocked estimate +
    possible sparse bonus - 0.06 * key_lo."""
    bound_hi: float
    """U — bound(key_hi), the maximum bound over the key range; sorts
    groups best-first."""
    city_step_key: int
    """First key where the city-contest bound applies
    (key_lo + contestable_dist); always > key_hi when no contestable
    city is in play."""
    city_value_bound: float
    """Upper bound on the city contest bonus term."""
    has_alternates: bool
    """Whether equal-key alternate prefixes exist along the path —
    widened base_len/army margins were folded into the bound."""
    fallback_candidates: list[V2InterceptCandidate]
    """Every non-winner candidate in the same (choke, depth) group,
    retained as raw references in stable depth_group order with
    group_key-None endpoints already excluded. The wave's winner can
    be a chain V1's global-visited search never discovered, so when
    the winner is gate-rejected these are the remaining paths V1
    could plausibly have recorded for the distance slot. Paths are
    materialized lazily by _prepare_fallback_paths only when a
    fallback is actually attempted."""
    prepared_fallback_paths: list[V2FallbackPath] | None = None
    """Cached V1 record-order fallback paths; None until the first
    fallback attempt for this group."""


class ArmyInterceptorV2:
    __slots__ = (
        'v1',
        'last_stage_timings',
        'damage_estimate_cache',
        'last_native_evals',
        'last_average_enemy_position_by_turn',
        '_fallback_override',
        'proxy_shadow_enabled',
        'last_proxy_shadow',
        'preselection_enabled',
        'last_preselection',
    )

    v1: ArmyInterceptorV1Protocol
    last_stage_timings: V2StageTimings
    damage_estimate_cache: dict[tuple[int, int, int], float]
    last_native_evals: list[V2NativeCandidateEval]
    last_average_enemy_position_by_turn: list[tuple[float, float] | None]
    _fallback_override: bool | None
    proxy_shadow_enabled: bool
    last_proxy_shadow: V2ProxyShadowResult | None
    preselection_enabled: bool
    last_preselection: PreselectionResult | None

    def __init__(self, v1: ArmyInterceptorV1Protocol) -> None:
        """Initialize V2 with the V1 surface it reuses."""
        self.v1 = v1
        self.last_stage_timings = V2StageTimings()
        self.damage_estimate_cache = {}
        self.last_native_evals = []
        self.last_average_enemy_position_by_turn = []
        self._fallback_override = None
        self.proxy_shadow_enabled = False
        self.last_proxy_shadow = None
        self.preselection_enabled = True
        self.last_preselection = None

    def get_intercept_plan_options(
        self,
        interception: ArmyInterception,
        turnsLeftInCycle: int,
        opponentTracker: OpponentTracker,
        otherThreatsBlockingTiles: dict[Tile, ThreatBlockInfo] | None,
    ) -> dict[int, InterceptionOptionInfo]:
        """Find a bounded set of V2 candidate paths and score them with V1."""
        self.last_proxy_shadow = None
        self.last_preselection = None
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
            # One parent-chained multi-source wave replaces the old
            # per-source layered reaches entirely: the wave fans out
            # from every candidate source at once, keeps top-K states
            # per (tile, depth) slot, and every kept state chains back
            # to its source seed through parent links — no per-choke
            # distance matrices, no source selection, no per-source
            # reach construction.
            friendly_reach = self.build_friendly_multi_source_matrix(
                interception,
                threat_reach,
                choke_search_depths,
                average_enemy_position_by_turn)
            candidates = self.build_intercept_candidates(
                interception,
                threat_reach,
                friendly_reach,
                turnsLeftInCycle,
                choke_search_depths)
            native_table = self.evaluate_candidates_native(
                interception,
                threat_reach,
                friendly_reach,
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
        #
        # Bound-gated evaluation processes groups in descending bound
        # order rather than V1's choke-major depth-ascending order, so
        # iterate the recorded evals by their stored V1 eval rank to
        # reconstruct V1's first-write sequence exactly.
        first_write_rank: dict[int, int] = {}
        for ranked_eval in sorted(
            self.last_native_evals,
            key=lambda ranked_eval: (
                ranked_eval.bound_group.v1_eval_order
                if ranked_eval.bound_group is not None
                else -1)):
            for ranked_entry in ranked_eval.entries:
                if ranked_entry.cur_dist not in first_write_rank:
                    first_write_rank[ranked_entry.cur_dist] = (
                        len(first_write_rank))
        best_intercept_table = {
            cur_dist: best_intercept_table[cur_dist]
            for cur_dist in sorted(
                best_intercept_table,
                key=lambda cur_dist: first_write_rank.get(
                    cur_dist, len(first_write_rank)))
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

        # downstream_damage was only consumed by the removed ownership-score
        # source selection; the active path estimates blocked damage through
        # _estimate_threat_blocked's cached per-threat walk instead, so both
        # builders are skipped (zeros kept for matrix shape compatibility).
        downstream_damage = [0.0] * tile_count

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
            searched_choke_indices={
                choke_tile.tile_index
                for choke_tile in choke_search_depths
            },
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
        # The negative filter needs each tile's distance to its NEAREST
        # searched choke. One multi-seed bounded field gives exactly min
        # over the per-choke distance matrices in a single flood, built
        # lazily on the first negative-subsegment source tile. The cap
        # is max_limit because every tile this BFS pops has a
        # no-neutral-cities distance <= max_limit to some choke (the
        # offset encoding subtracts, never adds), and the
        # neutral-allowed mapper distance can only be shorter.
        nearest_choke_dist_raw: list[int] | None = None
        # Hoisted locals for the inlined _ensure_friendly_step_delta —
        # one method call per popped tile dominated this BFS's per-tile
        # cost on wide allowed regions.
        team_ids = self.v1.map.team_ids_by_player_index
        friendly_team = self.v1.map.friendly_team
        negative_tile_indexes = (
            interception.positive_threat_subsegment_negative_tile_indexes)
        friendly_tile_mask = step_deltas.friendly_tile_mask
        negative_tile_mask = step_deltas.negative_tile_mask
        friendly_step_delta = step_deltas.friendly_step_delta
        friendly_delta_computed = step_deltas.friendly_delta_computed
        while frontier:
            tile_index, dist = frontier.popleft()
            if bfs_dist[tile_index] != dist or dist > max_limit:
                continue
            tile = tiles_by_index[tile_index]
            if not friendly_delta_computed[tile_index]:
                # Inlined _ensure_friendly_step_delta (its only call
                # site): fills the friendly mask, the
                # negative-subsegment mask, and the per-tile army delta
                # on first visit.
                is_friendly = team_ids[tile.player] == friendly_team
                if is_friendly:
                    friendly_tile_mask[tile_index] = 1
                if tile in negative_tile_indexes:
                    negative_tile_mask[tile_index] = 1
                    friendly_step_delta[tile_index] = -1
                elif is_friendly:
                    friendly_step_delta[tile_index] = tile.army - 1
                else:
                    friendly_step_delta[tile_index] = -tile.army - 1
                friendly_delta_computed[tile_index] = 1
            if (
                max_limit - dist >= 0
                and friendly_tile_mask[tile_index]
                and tile.army >= 2
            ):
                is_source = True
                if negative_tile_mask[tile_index]:
                    if threat_path_mask[tile_index] == full_path_mask:
                        is_source = False
                    else:
                        if nearest_choke_dist_raw is None:
                            nearest_choke_dist_raw = (
                                self._build_min_distance_field(
                                    [
                                        choke_tile
                                        for choke_tile, _ in choke_limits
                                    ],
                                    max_limit,
                                    tiles_by_index))
                        nearest_choke_distance = (
                            nearest_choke_dist_raw[tile_index])
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

    def _build_min_distance_field(
        self,
        seed_tiles: list[Tile],
        depth_cap: int,
        tiles_by_index: list[Tile],
    ) -> list[int]:
        """DistanceMapper-equivalent min-distance field, depth-capped.

        Mirrors _build_distance_map_matrix_fast's semantics exactly for
        tiles within depth_cap of a seed: a neighbor's distance is
        marked on first sight (obstacle tiles included), and every
        non-obstacle tile expands — neutral cities included — so the
        values match the mapper's matrices at every tile the callers
        read. Tiles beyond depth_cap keep UNREACHABLE_DISTANCE, which
        callers treat identically to the mapper's own unreachable
        sentinel (arrival drop / is_source=False). One bounded flood
        replaces a full-map matrix build per searched choke, and with
        multiple seeds gives the negative-subsegment filter's
        nearest-searched-choke distance — min over the same per-choke
        matrices — in a single pass.
        """
        dist_raw = [UNREACHABLE_DISTANCE] * len(tiles_by_index)
        frontier: deque[tuple[int, int]] = deque()
        for seed_tile in seed_tiles:
            seed_index = seed_tile.tile_index
            if dist_raw[seed_index] == 0:
                continue
            dist_raw[seed_index] = 0
            frontier.append((seed_index, 0))
        while frontier:
            tile_index, dist = frontier.popleft()
            if dist >= depth_cap:
                continue
            new_dist = dist + 1
            for next_tile in tiles_by_index[tile_index].movable:
                next_index = next_tile.tile_index
                if dist_raw[next_index] != UNREACHABLE_DISTANCE:
                    continue
                dist_raw[next_index] = new_dist
                if next_tile.isObstacle:
                    continue
                frontier.append((next_index, new_dist))
        return dist_raw

    def _threat_progress_gate_accepts(
        self,
        tile: Tile,
        next_tile: Tile,
        next_threat_dist: int,
        cur_dist_tuple: tuple[float, float] | None,
        positions_by_turn: list[tuple[float, float] | None],
        num_positions: int,
        grid: list[list[Tile]],
        euclid_dist: Callable[[float, float, float, float], float],
    ) -> bool:
        """Return whether V1's euclid-progress escape allows this step.

        This is the source/depth-independent half of the prioFunc
        monotonicity gate: it depends only on the directed edge's two
        tiles and their threat distances, so
        build_friendly_multi_source_matrix caches the result per
        directed edge for the duration of one call.
        UnitTests/test_ArmyInterceptionV2Unit.py::
        test_should_cache_directed_threat_gate_within_friendly_wave
        covers the cache contract.
        """
        if cur_dist_tuple is None:
            return False
        next_dist_tuple = (
            positions_by_turn[next_threat_dist]
            if next_threat_dist < num_positions
            else None)
        if (
            next_dist_tuple is None
            or grid[round(cur_dist_tuple[1])][
                round(cur_dist_tuple[0])].isObstacle
        ):
            return True
        from_euclid_cur = euclid_dist(
            cur_dist_tuple[0],
            cur_dist_tuple[1],
            tile.x,
            tile.y)
        to_last_euclid = euclid_dist(
            next_dist_tuple[0],
            next_dist_tuple[1],
            next_tile.x,
            next_tile.y)
        return from_euclid_cur >= to_last_euclid + 0.5

    def build_friendly_multi_source_matrix(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        choke_search_depths: dict[Tile, int],
        positions_by_turn: list[tuple[float, float] | None],
        *,
        _cache_threat_gate: bool = True,
    ) -> FriendlyMultiSourceMatrix:
        """One parent-chained multi-source BFS from every source.

        The user's original V2 design realized: instead of enumerating
        (source, choke, depth) arrivals from per-choke distance
        matrices and reconstructing a bounded layered reach per
        selected source (~9.4 heap searches per call, the dominant
        stage-B cost), ONE wave fans out from every candidate source
        simultaneously. Each (tile, depth) slot keeps the best state
        per source ordered by army_at_arrival, and every kept state
        links to the (tile', depth-1) state it expanded from —
        candidate paths materialize by walking parents back to a
        depth-0 source seed.

        Correctness notes:

        - Depth layers are expanded strictly in order, so a source's
          first claim of a tile is always at its minimum BFS depth —
          the same min-distance first-claim V1's endpoint pop
          produces. Per-source claim bits (claimed_source_bits) give
          each source at most one state per tile, which also makes
          ancestor cycles impossible: every ancestor of a pushing
          state was claimed at a shallower depth, so the check blocks
          pushes that would revisit the chain.
        - Slot eviction is NOT a source claim: a source whose push
          loses the slot can still claim that tile deeper. V1 emits
          sources at their min-distance pop, so the deferral only adds
          candidates V1 could also have recorded deeper — it never
          removes the slot's stronger arrivals.
        - net_army accumulates the DEPARTING tile's plain V1 delta
          (friendly +(army-1), else -(army+1) — the prioFunc walk,
          deliberately not the step_deltas -1 negative-subsegment
          refinement), so a state at (tile, d) holds the V1-style path
          walk over tiles[:-1] — the same bound the (net-cap, -cap,
          net) group key ranks by. cap_points accumulates the
          departing tile's cap delta (0 friendly, 1 neutral, 2
          enemy-owned).
        - The frontier is bounded by choke_budget exactly like the
          deleted layered reach: a state deeper than every searched
          choke's remaining slack can never produce a candidate. The
          budget matrix is only nonzero inside allowed_search_region,
          so the bound confines the wave to V1's funnel union for
          free.
        - Every push carries V1's _get_intercept_paths prioFunc
          monotonicity gate: a forward step may never increase
          distance-to-threat, escaped only by V1's euclid-progress
          check against the average enemy position. Without it the
          wave emitted candidates (and therefore option rows) V1's
          reverse per-choke search could never enumerate — e.g.
          Tests/test_ArmyInterception.py::
          test_should_not_loop_on_intercepting_army_and_then_blocking_threat_choke
          and test_should_always_defend_general__can_split_from_this_position
          regressed because V2 produced whole delay-variant option
          families at chokes V1 never reached through.

        _cache_threat_gate=False is a test-only seam that disables the
        call-local directed-edge gate cache so UnitTests can compare
        the cached wave against the uncached gate evaluation.
        """
        tiles_by_index = threat_reach.tiles_by_index
        tile_count = len(tiles_by_index)
        candidate_sources = threat_reach.candidate_sources
        choke_budget = threat_reach.choke_budget.budget
        max_depth = threat_reach.max_depth
        game_map = self.v1.map
        team_ids = game_map.team_ids_by_player_index
        friendly_team = game_map.friendly_team
        # V1's threat-dist monotonicity gate inputs, identical to the
        # exact-search branch: distance map from the primary threat's
        # start tile plus the average-enemy-position list V1 built for
        # this call.
        threat_tile = interception.threats[0].path.start.tile
        threat_dist_raw = game_map.distance_mapper.get_tile_dist_matrix(
            threat_tile).raw
        num_positions = len(positions_by_turn)
        euclid_dist = game_map.euclidDist
        euclid_dist_exp = game_map.euclidDistExp
        grid = game_map.grid
        # Call-local cache for the source/depth-independent threat-gate
        # acceptance of each directed tile edge (outer_index * tile_count +
        # inner_index). It never persists across calls; UnitTests/
        # test_ArmyInterceptionV2Unit.py::
        # test_should_cache_directed_threat_gate_within_friendly_wave
        # covers reuse, rejected-edge caching, and per-call refresh.
        edge_gate_cache: dict[int, bool] = {}
        # Per-tile bitmask of the sources that have a KEPT state on it —
        # the wave's per-source visited set (V1 pops each tile at most
        # once per search; a source's chain here likewise claims each
        # tile at most once, at its minimum surviving depth).
        claimed_source_bits: list[int] = [0] * tile_count
        states_by_depth: list[dict[int, list[V2WaveState]]] = [
            {}
            for _ in range(max_depth + 1)
        ]
        alternates_by_depth: list[dict[int, list[V2WaveState]]] = [
            {}
            for _ in range(max_depth + 1)
        ]

        frontier: list[V2WaveState] = []
        for source_index, source in enumerate(candidate_sources):
            # A source the choke budget never reached can produce no
            # candidate; the deleted reach raised on one, and skipping
            # its seed keeps states_by_depth strictly inside the
            # budget frontier.
            if choke_budget[source.tile_index] < 0:
                continue
            seed = V2WaveState(
                tile_index=source.tile_index,
                depth=0,
                source_index=source_index,
                net_army=0,
                cap_points=0,
                parent_state=None)
            claimed_source_bits[source.tile_index] |= (
                1 << source_index)
            frontier.append(seed)
            states_by_depth[0][source.tile_index] = [seed]

        depth = 0
        while frontier:
            next_depth = depth + 1
            next_slots: dict[int, list[V2WaveState]] = {}
            for state in frontier:
                tile_index = state.tile_index
                tile = tiles_by_index[tile_index]
                source_bit = 1 << state.source_index
                # The departing tile's delta is added when LEAVING it
                # (see V2WaveState): a state at depth d+1 sums the
                # deltas of its chain's first d+1 tiles, i.e.
                # path[:-1] relative to the pushed endpoint. The
                # accumulation is V1's prioFunc/_advance_friendly_
                # intercept_army walk exactly — +(army-1) per
                # friendly-team tile, -(army+1) otherwise; the -1
                # positive-subsegment refinement in step_deltas.
                # friendly_step_delta is intentionally NOT used here
                # because it diverges from V1's scorer semantics
                # (UnitTests/test_ArmyInterceptionV2Unit.py::
                # test_should_build_v2_invariants_for_one_kill_threat
                # asserts the plain walk).
                if team_ids[tile.player] == friendly_team:
                    next_net = state.net_army + tile.army - 1
                    next_cap = state.cap_points
                elif tile.isNeutral:
                    next_net = state.net_army - tile.army - 1
                    next_cap = state.cap_points + 1
                else:
                    next_net = state.net_army - tile.army - 1
                    next_cap = state.cap_points + 2
                cur_threat_dist = threat_dist_raw[tile_index]
                cur_dist_tuple: tuple[float, float] | None = None
                cur_dist_tuple_computed = False
                for next_tile in tile.movable:
                    if next_tile.isObstacle or (
                        next_tile.isCity and next_tile.isNeutral
                    ):
                        continue
                    next_index = next_tile.tile_index
                    # Budget/depth and the per-source claim are cheaper than
                    # the threat-distance gate and are local to this push, so
                    # they run before it. The gate itself is source/depth
                    # independent and cached per directed edge for this call.
                    if (
                        next_depth > choke_budget[next_index]
                        or next_depth > max_depth
                    ):
                        continue
                    if (
                        claimed_source_bits[next_index]
                        & source_bit
                    ):
                        continue
                    # V1's prioFunc monotonicity gate (reverse search
                    # expands choke-outward; there nextTile is the outer
                    # tile and toTile the inner). In this forward wave
                    # cur is the outer tile and next the inner, so V1's
                    # toTileDistToThreat > nextTileDistToThreat becomes
                    # next_threat_dist > cur_threat_dist: a forward step
                    # may not increase distance-to-threat unless the
                    # euclid-progress escape passes. See
                    # evaluate_v1_search_paths_native for the same gate
                    # in V1's own direction.
                    next_threat_dist = threat_dist_raw[next_index]
                    # Cheap distance check first: most neighbors do not
                    # increase distance-to-threat, so the position-tuple
                    # indexing and euclid probe below only run for the
                    # minority of dist-increasing steps.
                    if next_threat_dist > cur_threat_dist:
                        gate_accepted: bool | None = None
                        edge_key = -1
                        if _cache_threat_gate:
                            edge_key = (
                                tile_index * tile_count + next_index)
                            gate_accepted = edge_gate_cache.get(edge_key)
                        if gate_accepted is None:
                            if not cur_dist_tuple_computed:
                                cur_dist_tuple = (
                                    positions_by_turn[
                                        cur_threat_dist - 1]
                                    if 0 < cur_threat_dist <= num_positions
                                    else None)
                                cur_dist_tuple_computed = True
                            gate_accepted = (
                                self._threat_progress_gate_accepts(
                                    tile,
                                    next_tile,
                                    next_threat_dist,
                                    cur_dist_tuple,
                                    positions_by_turn,
                                    num_positions,
                                    grid,
                                    euclid_dist))
                            if _cache_threat_gate:
                                edge_gate_cache[edge_key] = gate_accepted
                        if not gate_accepted:
                            continue
                    new_state = V2WaveState(
                        tile_index=next_index,
                        depth=next_depth,
                        source_index=state.source_index,
                        net_army=next_net,
                        cap_points=next_cap,
                        parent_state=state)
                    slot = next_slots.get(next_index)
                    if slot is None:
                        next_slots[next_index] = [new_state]
                    else:
                        slot.append(new_state)
            # Finalize the layer: keep each source's BEST push into the
            # slot. V1 runs a per-source search with a per-source
            # visited set, so a source's chain never competes against
            # other sources' arrivals; a global top-K slot starved
            # weaker chains at same-depth intermediate tiles before
            # they could reach a searched choke
            # (Tests/test_ArmyInterception.py::
            # test_should_always_intercept_at_the_point_adjacent_to_all_good_enemy_moves,
            # test_should_intercept_all_path_combinations_when_possible).
            # Per-source retention restores that independence while the
            # shared layer loop still amortizes the expansion across
            # sources — the claimed bit gives each source at most one
            # state per tile ever, bounding total state exactly like
            # V1's union of visited sets.
            #
            # Within a source, V1's heap claims the slot for the push
            # that pops first: its entry (prioVals, dist, curTurns,
            # nextTile, fromTile, maxDict) with prioVals (dist,
            # fromEuclidCur, negTileCapPoints, negArmy, nextTile) ties
            # on dist/euclid/curTurns/tile for pushes into the SAME
            # tile, so claim order is (cap_points ASC, net_army DESC via
            # negArmy, then fromTile.army via Tile.__lt__). Fully-tied
            # entries resolve in heap order, which correlates with which
            # parent popped first — approximated by comparing the
            # parents' own prio keys, computed lazily so only contended
            # pushes pay the euclid
            # (Tests/test_ArmyInterception.py::
            # test_should_always_intercept_at_the_point_adjacent_to_all_good_enemy_moves:
            # movable-order luck previously recorded 6,5->7,5->7,6
            # where V1's euclid-ordered heap records 6,5->6,6->7,6, and
            # only the latter deposits army adjacent to the enemy's
            # alternative move). Pushes tying the kept push on
            # (net_army, cap_points) stay as alternates.
            next_frontier: list[V2WaveState] = []
            for next_index, slot in next_slots.items():
                best_by_source: dict[int, V2WaveState] = {}
                for wave_state in slot:
                    prev = best_by_source.get(wave_state.source_index)
                    if prev is None:
                        best_by_source[wave_state.source_index] = (
                            wave_state)
                        continue
                    state_key = (
                        wave_state.cap_points,
                        -wave_state.net_army,
                        tiles_by_index[
                            wave_state.parent_state.tile_index].army)
                    prev_key = (
                        prev.cap_points,
                        -prev.net_army,
                        tiles_by_index[
                            prev.parent_state.tile_index].army)
                    if state_key == prev_key:
                        state_key = (
                            state_key
                            + self._v1_wave_parent_pop_key(
                                wave_state.parent_state,
                                tiles_by_index,
                                threat_dist_raw,
                                positions_by_turn,
                                num_positions,
                                euclid_dist_exp))
                        prev_key = (
                            prev_key
                            + self._v1_wave_parent_pop_key(
                                prev.parent_state,
                                tiles_by_index,
                                threat_dist_raw,
                                positions_by_turn,
                                num_positions,
                                euclid_dist_exp))
                    if state_key < prev_key:
                        best_by_source[wave_state.source_index] = (
                            wave_state)
                kept: list[V2WaveState] = []
                alt_states: list[V2WaveState] = []
                for wave_state in slot:
                    if (
                        wave_state
                        is best_by_source[wave_state.source_index]
                    ):
                        kept.append(wave_state)
                        claimed_source_bits[next_index] |= (
                            1 << wave_state.source_index)
                # states_by_depth ordering is a presentation contract —
                # UnitTests/test_ArmyInterceptionV2Unit.py asserts kept
                # states are net_army-sorted; the claim-order scan above
                # decides which chain survives, this only reorders the
                # stored list.
                kept.sort(
                    key=lambda kept_state: (
                        -kept_state.net_army,
                        kept_state.cap_points,
                        kept_state.source_index))
                for wave_state in slot:
                    best = best_by_source[wave_state.source_index]
                    if wave_state is not best and (
                        wave_state.net_army,
                        wave_state.cap_points
                    ) == (
                        best.net_army,
                        best.cap_points
                    ):
                        alt_states.append(wave_state)
                if alt_states:
                    alternates_by_depth[next_depth][next_index] = (
                        alt_states)
                next_frontier.extend(kept)
                states_by_depth[next_depth][next_index] = kept
            frontier = next_frontier
            depth = next_depth

        selected_source_indices = self._selected_wave_sources(
            states_by_depth,
            choke_search_depths,
            max_depth)
        # Ownership/damage scoring used to pick a handful of sources;
        # every candidate source now participates in one shared wave,
        # so the scores are reported as zeros for shadow diagnostics.
        ownership_scores = [0.0] * len(candidate_sources)
        return FriendlyMultiSourceMatrix(
            candidate_sources=candidate_sources,
            ownership_scores=ownership_scores,
            selected_source_indices=selected_source_indices,
            states_by_depth=states_by_depth,
            alternates_by_depth=alternates_by_depth,
        )

    def _v1_wave_parent_pop_key(
        self,
        state: V2WaveState,
        tiles_by_index: list[Tile],
        threat_dist_raw: list[int],
        positions_by_turn: list[tuple[float, float] | None],
        num_positions: int,
        euclid_dist_exp: Callable[
            [float, float, float, float], float],
    ) -> tuple[float, int, int, int, int]:
        """A kept state's V1 heap pop key, for resolving same-source
        pushes into a shared (tile, depth) slot that tied on
        (cap_points, -net_army, parent_tile.army).

        V1's heap resolves fully-equal entries in internal order, which
        correlates with which parent entry popped first; comparing the
        parents' own prio keys approximates that order deterministically
        (Tests/test_ArmyInterception.py::
        test_should_always_intercept_at_the_point_adjacent_to_all_good_enemy_moves).
        The key is (fromEuclidCur, negTileCapPoints, negArmy,
        nextTile.army, fromTile.army): the state's own prio tuple minus
        the layer-uniform dist, with the entry-level fromTile.army
        appended. push_euclid is computed lazily and cached on the
        state (-1.0 sentinel) so uncontended expansions never pay the
        euclid; it is stored on the euclidDistExp (squared) scale —
        ordering-equivalent to V1's euclid — with a 10000.0 fallback
        matching V1's 100.0 squared.
        """
        if state.push_euclid < 0.0:
            tile = tiles_by_index[state.tile_index]
            threat_dist = threat_dist_raw[state.tile_index]
            dist_tuple = (
                positions_by_turn[threat_dist - 1]
                if 0 < threat_dist <= num_positions
                else None)
            state.push_euclid = (
                euclid_dist_exp(
                    dist_tuple[0], dist_tuple[1], tile.x, tile.y)
                if dist_tuple is not None else 10000.0)
        parent_army = (
            tiles_by_index[state.parent_state.tile_index].army
            if state.parent_state is not None else 0)
        return (
            state.push_euclid,
            state.cap_points,
            -state.net_army,
            tiles_by_index[state.tile_index].army,
            parent_army)

    def _selected_wave_sources(
        self,
        states_by_depth: list[dict[int, list[V2WaveState]]],
        choke_search_depths: dict[Tile, int],
        max_depth: int,
    ) -> list[int]:
        """Sources with at least one candidate-admissible choke state.

        A kept state at searched choke C only feeds a real candidate
        at depths <= min(search_depth, max_depth) — the same bound
        build_intercept_candidates applies — so this set is the wave's
        answer to 'which sources can produce a candidate this call'.
        """
        selected: set[int] = set()
        depth_cap = len(states_by_depth) - 1
        for choke_tile, search_depth in choke_search_depths.items():
            choke_index = choke_tile.tile_index
            max_candidate_depth = min(
                search_depth,
                max_depth,
                depth_cap)
            for depth in range(1, max_candidate_depth + 1):
                states = states_by_depth[depth].get(choke_index)
                if not states:
                    continue
                for wave_state in states:
                    selected.add(wave_state.source_index)
        return sorted(selected)

    def build_intercept_candidates(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        turns_left_in_cycle: int,
        choke_search_depths: dict[Tile, int],
    ) -> list[V2InterceptCandidate]:
        """Emit one candidate per kept wave state at a searched choke.

        The wave's per-source claim means a source holds at most one
        state at any tile — always at its minimum surviving BFS depth,
        which mirrors the one endpoint pop V1's per-choke search gives
        each source. evaluate_candidates_native iterates
        common_intercept_chokes order x ascending depth and picks each
        (choke, depth) group's winner by the stored group key, so
        candidate ordering carries no semantics. The group_key is the
        V1 valueFunc ranking computed O(1) from the wave state's stored
        (net_army, cap_points); the prescreen_value kept for
        diagnostics is the same cheap army-density bound
        build_intercept_candidates has always emitted.
        """
        candidates: list[V2InterceptCandidate] = []
        target_is_city = interception.target_tile.isCity
        map_player_index = self.v1.map.player_index
        max_depth = threat_reach.max_depth
        states_by_depth = friendly_reach.states_by_depth
        candidate_sources = friendly_reach.candidate_sources
        depth_cap = len(states_by_depth) - 1
        for choke_tile, intercept_info in (
                interception.common_intercept_chokes.items()):
            search_depth = choke_search_depths.get(choke_tile)
            if search_depth is None:
                continue
            choke_index = choke_tile.tile_index
            intercept_point_distance = (
                interception.threats[0]
                .armyAnalysis.bMap[choke_tile])
            max_candidate_depth = min(
                search_depth,
                max_depth,
                depth_cap)
            for depth in range(1, max_candidate_depth + 1):
                states = states_by_depth[depth].get(choke_index)
                if not states:
                    continue
                for state in states:
                    source_tile = candidate_sources[state.source_index]
                    # V1's valueFunc drops a path whose source endpoint
                    # is not the searching player's tile or holds army
                    # <= 1; both are per-source constants folded into
                    # the group key here.
                    source_valid = (
                        source_tile.player == map_player_index
                        and source_tile.army > 1)
                    friendly_army = state.net_army
                    group_key = (
                        (
                            friendly_army - state.cap_points,
                            -state.cap_points,
                            friendly_army)
                        if source_valid and friendly_army >= 0
                        else None)
                    additional_turns = (
                        max(0, intercept_point_distance - depth)
                        if not target_is_city
                        else intercept_point_distance)
                    estimated_base_turns_key = (
                        depth
                        + additional_turns
                        + intercept_info.max_extra_moves_to_capture)
                    candidates.append(V2InterceptCandidate(
                        source_index=state.source_index,
                        wave_state=state,
                        choke_tile=choke_tile,
                        depth=depth,
                        friendly_army=friendly_army,
                        prescreen_value=(
                            friendly_army
                            / max(1, estimated_base_turns_key)),
                        group_key=group_key))
        return candidates

    def _state_tile_indices(
        self,
        state: V2WaveState,
    ) -> list[int]:
        """Materialize a state's source->tile index chain.

        States store parent_state links instead of path tuples so the
        per-claim cost stays O(1); the chain only walks here, for the
        candidates that actually reach evaluation.
        """
        tile_indices = [state.tile_index]
        cursor = state.parent_state
        while cursor is not None:
            tile_indices.append(cursor.tile_index)
            cursor = cursor.parent_state
        tile_indices.reverse()
        return tile_indices

    def _candidate_tile_indices(
        self,
        candidate: V2InterceptCandidate,
    ) -> list[int]:
        """Return the candidate's stored source-to-choke tile-index path.

        The chain terminates at a depth-0 source seed by construction;
        the depth check catches a wave_state wired to a different
        (choke, depth) slot than the candidate claims.
        """
        wave_state = candidate.wave_state
        if wave_state is None:
            raise ValueError(
                f'V2 candidate for choke {candidate.choke_tile} '
                f'carries no wave state')
        tile_path = self._state_tile_indices(wave_state)
        if (
            len(tile_path) != candidate.depth + 1
            or tile_path[-1] != candidate.choke_tile.tile_index
        ):
            raise ValueError(
                f'V2 path does not reconstruct to choke '
                f'{candidate.choke_tile} at depth {candidate.depth}')
        return tile_path

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
        candidates: list[V2InterceptCandidate],
    ) -> list[V2CandidatePath]:
        """Reconstruct each retained wave state as a forward Path."""
        candidate_paths: list[V2CandidatePath] = []
        for candidate in candidates:
            wave_state = candidate.wave_state
            if wave_state is None:
                raise ValueError(
                    f'V2 candidate for choke {candidate.choke_tile} '
                    f'carries no wave state')
            source_tile = friendly_reach.candidate_sources[
                candidate.source_index]
            tile_indices = self._candidate_tile_indices(candidate)
            if (
                candidate.source_index != wave_state.source_index
                or tile_indices[0] != source_tile.tile_index
            ):
                raise ValueError(
                    f'V2 candidate source mismatch for {source_tile}')
            path = self.build_path_from_tile_indices(
                threat_reach.tiles_by_index,
                tile_indices)
            candidate_paths.append(
                V2CandidatePath(
                    candidate=candidate,
                    path=path,
                    friendly_army_at_choke=wave_state.net_army,
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
                    wave_state=None,
                    choke_tile=choke_tile,
                    depth=dist,
                    friendly_army=0,
                    prescreen_value=0.0,
                    group_key=None)
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
        friendly_reach: FriendlyMultiSourceMatrix,
        candidates: list[V2InterceptCandidate],
        turns_left_in_cycle: int,
        opponent_tracker: OpponentTracker,
        other_blocking: dict[Tile, ThreatBlockInfo] | None,
        average_enemy_position_by_turn: list[tuple[float, float] | None],
    ) -> dict[int, V2NativeOptionEntry]:
        """Natively score retained candidates exactly like V1's scorer.

        By default (preselection_enabled=True) this dispatches to the
        bounded preselection scorer: at most six (choke, depth) groups
        and at most twelve native evaluations per call, returning that
        result's table directly. Setting preselection_enabled=False on
        the instance opts back into the exhaustive bound-gated pipeline
        described below.

        Port of ArmyInterceptor._evaluate_intercept_path_into_table applied to
        reconstructed tile-index lists (plus a parallel move_half flag array)
        instead of Path objects, then folded into a plain-data shadow of V1's
        bestInterceptTable keyed by curDist.

        With preselection_enabled=False, evaluation runs best-first behind
        an admissible upper bound:
        every recorded (choke, depth) group gets a per-curDist bound on
        the thisValue any of its paths could emit, groups are ordered by
        their top-of-range bound, and a group is skipped only when its
        bound is strictly below the incumbent option at every key in its
        range (strict, because an equal-value row could still win the
        worst-case/target-distance tiebreak). Skipped groups still run
        the eval through the collision sim in probe mode so V1's
        evaluation_continued=False choke break is reproduced exactly —
        the set of V1-reachable groups is order-independent, but a
        skipped group whose real eval would break must not let deeper
        same-choke groups emit rows V1 never produced.
        """
        self.last_proxy_shadow = None
        self.last_preselection = None
        context = self._build_native_eval_context(
            interception,
            threat_reach,
            turns_left_in_cycle,
            opponent_tracker,
            other_blocking,
            average_enemy_position_by_turn)
        if self.preselection_enabled:
            result = evaluate_preselected(
                self,
                context,
                friendly_reach,
                candidates)
            self.last_preselection = result
            self.last_native_evals = result.evaluations
            return result.table
        bound_context = self._build_bound_context(
            context,
            friendly_reach)
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
        choke_groups: dict[int, list[V2BoundGroup]] = {}
        bound_groups: list[V2BoundGroup] = []
        v1_eval_order = 0
        for choke_tile in interception.common_intercept_chokes:
            choke_index = choke_tile.tile_index
            choke_candidates = candidates_by_choke.get(choke_index)
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
            groups_for_choke: list[V2BoundGroup] = []
            for depth in sorted(depth_groups):
                depth_group = depth_groups[depth]
                # V1's search keeps exactly one path per length per choke —
                # the maximum-valueFunc path at that distance — and drops
                # paths whose source endpoint fails valueFunc entirely
                # (net-negative army, army<=1, or not the searching player),
                # so only the group winner is reconstructed and evaluated.
                winner_candidate: V2InterceptCandidate | None = None
                winner_indices: list[int] | None = None
                winner_key: tuple[int, int, int] | None = None
                winner_pop_key: tuple | None = None
                for candidate in depth_group:
                    # The group key was computed at candidate build time
                    # from the wave state's stored (net_army,
                    # cap_points) — identical to _v1_path_value_key's
                    # tiles[:-1] walk — so losing candidates never pay
                    # for path reconstruction or the per-tile key walk.
                    candidate_key = candidate.group_key
                    if candidate_key is None:
                        continue
                    if winner_key is None or candidate_key > winner_key:
                        winner_candidate = candidate
                        winner_indices = None
                        winner_key = candidate_key
                        winner_pop_key = None
                    elif candidate_key == winner_key:
                        # V1 records the distance slot for the FIRST heap
                        # pop carrying the max valueFunc (SearchUtils
                        # breadth_first_dynamic_max_per_tile_per_distance_
                        # global_visited writes only on strict improvement),
                        # so equal-key candidates must order by V1's
                        # endpoint pop priority, not generation order.
                        #
                        # Tests/test_ArmyInterception.py::
                        # test_should_not_wastefully_intercept_early_in_the_round
                        # (shadow_ab.py turn 301, choke 1,6): sources 4,6
                        # and 3,7 produced identical depth-3 keys, V1 popped
                        # the 4,6 endpoint first (same parent 117, earlier
                        # movable position) and recorded its path, while
                        # generation order picked 3,7 and changed the whole
                        # k3-k5 option rows downstream.
                        tile_indices = (
                            self._candidate_tile_indices(
                                candidate))
                        candidate_pop_key = self._v1_endpoint_pop_key(
                            context,
                            tile_indices,
                            candidate_key)
                        if winner_indices is None:
                            winner_indices = (
                                self._candidate_tile_indices(
                                    winner_candidate))
                        if winner_pop_key is None:
                            winner_pop_key = self._v1_endpoint_pop_key(
                                context,
                                winner_indices,
                                winner_key)
                        if candidate_pop_key < winner_pop_key:
                            winner_candidate = candidate
                            winner_indices = tile_indices
                            winner_pop_key = candidate_pop_key
                if winner_candidate is None:
                    continue
                previous_record = recorded_key_by_depth.get(depth - 1)
                if (
                    previous_record is not None
                    and winner_key <= previous_record
                ):
                    continue
                recorded_key_by_depth[depth] = winner_key
                if winner_indices is None:
                    winner_indices = (
                        self._candidate_tile_indices(
                            winner_candidate))
                # Every non-winner candidate in this distance slot is a
                # chain V1's global-visited search could have recorded
                # instead of the wave's winner (the wave retains
                # per-source chains V1 never discovers). Keep them as raw
                # references in stable depth_group order; _prepare_fallback_paths
                # materializes V1 record order lazily only when a fallback
                # is actually attempted.
                fallback_candidates: list[V2InterceptCandidate] = []
                for other_candidate in depth_group:
                    if other_candidate is winner_candidate:
                        continue
                    # Same skip the winner loop applies: a None group_key
                    # marks an endpoint V1's valueFunc rejects outright
                    # (enemy/1-army source or negative arrival army), so it
                    # can never be a recorded alternate either.
                    if other_candidate.group_key is None:
                        continue
                    fallback_candidates.append(other_candidate)
                bound_group = self._build_bound_group(
                    context,
                    bound_context,
                    friendly_reach,
                    interception,
                    choke_tile,
                    len(groups_for_choke),
                    v1_eval_order,
                    winner_candidate,
                    winner_indices,
                    winner_key,
                    fallback_candidates)
                v1_eval_order += 1
                groups_for_choke.append(bound_group)
                bound_groups.append(bound_group)
            if groups_for_choke:
                choke_groups[choke_index] = groups_for_choke

        # Best-first processing in descending bound order. Within one
        # choke, groups still resolve shallowest-first via the prefix
        # walk below: V1's choke loop evaluates paths ascending by
        # distance and stops on the first unreachable eval, so a deeper
        # group may only emit rows once every shallower recorded group
        # is known to continue — either fully evaluated and continued,
        # or bound-killed and confirmed continuing by the collision-only
        # probe.
        bound_groups.sort(
            key=lambda bound_group: (
                -bound_group.bound_hi,
                bound_group.v1_eval_order))
        choke_cursor: dict[int, int] = {}
        choke_blocked: dict[int, bool] = {}
        for trigger_group in bound_groups:
            choke_index = trigger_group.choke_tile.tile_index
            if choke_blocked.get(choke_index):
                continue
            groups_for_choke = choke_groups[choke_index]
            index = choke_cursor.get(choke_index, 0)
            if trigger_group.group_index < index:
                # Already resolved inside an earlier prefix walk.
                continue
            while index <= trigger_group.group_index:
                bound_group = groups_for_choke[index]
                index += 1
                if self._bound_kills(bound_group, best_table):
                    probe_eval = self._evaluate_candidate_native(
                        context,
                        bound_group.candidate,
                        bound_group.tile_indices,
                        probe_only=True)
                    if not probe_eval.evaluation_continued:
                        # The wave's winner may be a chain V1's
                        # global-visited search never discovered — a
                        # fallback could be the path V1 actually
                        # recorded, so probe them in V1 record order for
                        # one that keeps the choke alive.
                        for fallback_path in (
                            self._prepare_fallback_paths(
                                context,
                                bound_group)
                        ):
                            fallback_probe = (
                                self._evaluate_candidate_native(
                                    context,
                                    fallback_path.candidate,
                                    fallback_path.tile_indices,
                                    probe_only=True))
                            if fallback_probe.evaluation_continued:
                                probe_eval = fallback_probe
                                break
                    probe_eval.bound_group = bound_group
                    if probe_eval.evaluation_continued:
                        probe_eval.skip_reason = 'bound_skipped'
                    evals.append(probe_eval)
                    if not probe_eval.evaluation_continued:
                        choke_blocked[choke_index] = True
                        break
                    continue
                candidate_eval = self._evaluate_candidate_native(
                    context,
                    bound_group.candidate,
                    bound_group.tile_indices)
                if (
                    not candidate_eval.entries
                    and candidate_eval.skip_reason in (
                        'unsplittable_blocked_destination',
                        'best_case_intercept_1000')
                ):
                    # V1's heap commits arbitrarily among equal-key
                    # pushes, so when the winner's path is gate-rejected
                    # on a path-dependent check, V1's recorded path may
                    # well have been a runner-up. Retry equal-key
                    # runner-up paths (deepest divergent slot first)
                    # until one evaluates into rows.
                    #
                    # Tests/test_ArmyInterception.py::
                    # test_should_prevent_run_around_general__stop_multi_threat
                    # (shadow_ab.py turn 140): winner [149,X,166] took an
                    # unsplittable blocked hop while V1's twin [149,Y,166]
                    # emitted the k3 option row — the runner-up state at
                    # the choke slot carries exactly that alternate.
                    for alt_indices in self._runner_up_paths(
                        context,
                        friendly_reach,
                        bound_group.candidate.source_index,
                        bound_group.tile_indices,
                        bound_group.winner_key):
                        alt_eval = self._evaluate_candidate_native(
                            context,
                            bound_group.candidate,
                            alt_indices)
                        if alt_eval.entries:
                            candidate_eval = alt_eval
                            break
                if not candidate_eval.entries:
                    # The wave's winner can be a chain V1's
                    # global-visited search never discovered — its
                    # higher group key doesn't prove V1 recorded it.
                    # Walk the remaining group candidates in V1's record
                    # order (key desc, endpoint pop asc) and adopt the
                    # first one that produces V1-style rows.
                    #
                    # Tests/test_ArmyInterception.py::
                    # test_should_prevent_run_around_general__stop_multi_threat
                    # (shadow_ab.py turn 141): the (4,7,d3) group's winner
                    # from source 5,9 was gate-rejected while V1's
                    # recorded lower-key source 6,8 path emitted the k3
                    # option row.
                    #
                    # Tests/test_ArmyInterception.py::
                    # test_should_not_use_defensive_intercept_tile_for_expansion
                    # (shadow_ab.py turn 241): every (5,12,d*) group
                    # winner was debug-bypassed while V1's recorded
                    # 6,15-source d4 path emitted its option row.
                    for fallback_path in (
                        self._prepare_fallback_paths(
                            context,
                            bound_group)
                    ):
                        alt_eval = self._evaluate_candidate_native(
                            context,
                            fallback_path.candidate,
                            fallback_path.tile_indices)
                        if alt_eval.entries:
                            candidate_eval = alt_eval
                            break
                        if (
                            alt_eval.evaluation_continued
                            and not candidate_eval.evaluation_continued
                        ):
                            # A continuing no-rows fallback still beats
                            # the winner's choke-blocking outcome: keep
                            # it as the group's result but keep scanning
                            # for a fallback that emits rows.
                            candidate_eval = alt_eval
                candidate_eval.bound_group = bound_group
                evals.append(candidate_eval)
                if not candidate_eval.evaluation_continued:
                    choke_blocked[choke_index] = True
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
            choke_cursor[choke_index] = index
        self.last_native_evals = evals
        if self.proxy_shadow_enabled:
            self.last_proxy_shadow = compare_route_proxy(
                self, context, evals, best_table)
        return best_table

    def _build_bound_context(
        self,
        context: V2NativeEvalContext,
        friendly_reach: FriendlyMultiSourceMatrix,
    ) -> V2BoundContext:
        """Per-call bound inputs shared by every candidate group."""
        states_by_depth = friendly_reach.states_by_depth
        tiles_by_index = context.tiles_by_index
        team_ids = context.team_ids
        friendly_team = context.friendly_team
        source_count = len(friendly_reach.candidate_sources)
        bound_by_source: list[list[int]] = [
            [-1_000_000] * len(states_by_depth)
            for _ in range(source_count)
        ]
        for depth, slots in enumerate(states_by_depth):
            for tile_index, states in slots.items():
                tile = tiles_by_index[tile_index]
                # Friendly tiles use the full tile.army rather than the
                # usual army-1 prefix delta so the bound also covers the
                # collision sim's same-tile garrison reinforcement
                # (friendly_before + tile.army on a tail collision).
                bound_delta = (
                    tile.army
                    if team_ids[tile.player] == friendly_team
                    else -tile.army - 1)
                for wave_state in states:
                    source_bounds = bound_by_source[
                        wave_state.source_index]
                    value = wave_state.net_army + bound_delta
                    if value > source_bounds[depth]:
                        source_bounds[depth] = value
        # Prefix-max over depth: [d] must bound every state at depth <= d.
        for source_bounds in bound_by_source:
            running = source_bounds[0]
            for depth in range(1, len(source_bounds)):
                if source_bounds[depth] < running:
                    source_bounds[depth] = running
                else:
                    running = source_bounds[depth]
        enemy_min = 0
        for value in context.enemy_prefix_army:
            if value < enemy_min:
                enemy_min = value
        first_threat_player_count = sum(
            1
            for team_id in context.team_ids
            if team_id == context.first_threat_team)
        return V2BoundContext(
            army_bound_by_source=bound_by_source,
            enemy_min_prefix_army=enemy_min,
            first_threat_player_count=first_threat_player_count)

    def _build_bound_group(
        self,
        context: V2NativeEvalContext,
        bound_context: V2BoundContext,
        friendly_reach: FriendlyMultiSourceMatrix,
        interception: ArmyInterception,
        choke_tile: Tile,
        group_index: int,
        v1_eval_order: int,
        candidate: V2InterceptCandidate,
        tile_indices: list[int],
        winner_key: tuple[int, int, int],
        fallback_candidates: list[V2InterceptCandidate],
    ) -> V2BoundGroup:
        """Compute the admissible per-key upper bound for one group.

        thisValue at curDist c decomposes as
            raw_econ + blocked + recaps(c)*RECAP + city(c) + sparse
            - 0.06*base_len
        and every term is bounded independently above; see V2BoundGroup
        for the per-term arguments."""
        depth = candidate.depth
        intercept_info = interception.common_intercept_chokes[choke_tile]
        max_extra = intercept_info.max_extra_moves_to_capture
        choke_index = choke_tile.tile_index
        intercept_point_dist = context.first_bmap_raw[choke_index]
        if context.target_is_city:
            addl_turns = intercept_point_dist
        else:
            addl_turns = max(0, intercept_point_dist - depth)

        # Winner-path army prefix (the econ walk's army_left and the
        # collision sim's friendly_prefix share this accumulation).
        # first_dead_index bounds base_len below: the econ loop breaks
        # at the first index >= 1 whose incoming prefix is <= 0, giving
        # base_len = index + halves + incl + max_extra - 1 ... measured
        # precisely: base_len = iters + halves + incl + max_extra - 1
        # with iters = break_index + 1, so base_len >= break_index +
        # max_extra. A full walk gives base_len >= depth + max_extra,
        # and a cycle-end truncation at index i needs i + halves_i >=
        # turns_left with halves_i <= i, hence i >= turns_left // 2.
        tiles_by_index = context.tiles_by_index
        team_ids = context.team_ids
        friendly_team = context.friendly_team
        prefix_army = 0
        prefix_max = 0
        prefix_min = 0
        first_dead_index = depth + 1
        for index, tile_index in enumerate(tile_indices):
            if (
                index >= 1
                and prefix_army <= 0
                and first_dead_index > depth
            ):
                first_dead_index = index
            tile = tiles_by_index[tile_index]
            if team_ids[tile.player] == friendly_team:
                prefix_army += tile.army - 1
            else:
                prefix_army -= tile.army + 1
            if prefix_army > prefix_max:
                prefix_max = prefix_army
            if prefix_army < prefix_min:
                prefix_min = prefix_army

        # Equal-key alternates share the source, depth, and choke: their
        # army can die earlier than the winner's (flooring base_len at
        # the minimum possible index 2 + max_extra), and a spliced
        # alternate path's mid intercept army is bounded by the source's
        # state bound plus the winner path's maximum suffix swing
        # (prefix_max - prefix_min). Non-winner candidates from ANY
        # source in the group are also evaluable on gate rejection
        # (V1's global-visited search may have recorded any of them
        # instead of the wave's winner), so the bound must additionally
        # cover each fallback source's own per-depth bound — a fallback
        # candidate's whole chain consists of kept states of its source,
        # and it can die as early as index 2 as well.
        same_source_alternates = False
        alternates_by_depth = friendly_reach.alternates_by_depth
        for position in range(depth, 0, -1):
            tied_states = alternates_by_depth[position].get(
                tile_indices[position])
            if tied_states and any(
                tied_state.source_index == candidate.source_index
                for tied_state in tied_states
            ):
                same_source_alternates = True
                break
        has_alternates = (
            same_source_alternates or bool(fallback_candidates))

        base_lo = min(
            first_dead_index,
            depth,
            max(1, context.turns_left_in_cycle // 2)) + max_extra
        if has_alternates:
            base_lo = min(base_lo, 2 + max_extra)

        depth_clamped = min(
            depth,
            len(friendly_reach.states_by_depth) - 1)
        army_bound = bound_context.army_bound_by_source[
            candidate.source_index][depth_clamped]
        if same_source_alternates:
            army_bound += prefix_max - prefix_min
        for fallback_candidate in fallback_candidates:
            fallback_bound = bound_context.army_bound_by_source[
                fallback_candidate.source_index][depth_clamped]
            if fallback_bound > army_bound:
                army_bound = fallback_bound

        # Per-key bound terms.
        raw_bound = (
            depth * (TARGET_CAP_VALUE + OWNED_CITY_CAP_VALUE_BONUS)
            + (GENERAL_CAP_VALUE - TARGET_CAP_VALUE
               - OWNED_CITY_CAP_VALUE_BONUS)
            * bound_context.first_threat_player_count)
        blocked_bound = self._estimate_threat_blocked(
            interception,
            choke_tile,
            army_bound,
            context.turns_left_in_cycle)
        sparse_bound = (
            context.sparse_bonus
            if addl_turns == 0 and base_lo < context.sparse_len_cutoff
            else 0.0)
        key_lo = base_lo
        # turns_used_with_recap is capped by the cycle end (the econ
        # walk stops at cur_turn > cycle_end and recaps only fill the
        # remaining slack), so twr <= turns_left_in_cycle + max_extra.
        key_hi = context.turns_left_in_cycle + max_extra
        contestable_dist = context.contestable_city_dist
        city_value_bound = 0.0
        city_step_key = key_hi + 1
        if contestable_dist >= 0:
            army_reaching_bound = max(
                0,
                army_bound - 2 * contestable_dist)
            city_value_bound = (
                context.opponent_tracker
                .estimate_city_contest_econ_value(
                    asPlayer=context.map_player_index,
                    enPlayer=context.threats[0].threatPlayer,
                    armyReachingContestableCity=army_reaching_bound))
            city_step_key = key_lo + contestable_dist
        bound_base = (
            raw_bound
            + blocked_bound
            + sparse_bound
            - 0.06 * key_lo)
        bound_hi = bound_base + (key_hi - key_lo) * RECAPTURE_VALUE
        if key_hi >= city_step_key:
            bound_hi += city_value_bound
        return V2BoundGroup(
            choke_tile=choke_tile,
            group_index=group_index,
            v1_eval_order=v1_eval_order,
            candidate=candidate,
            tile_indices=tile_indices,
            winner_key=winner_key,
            key_lo=key_lo,
            key_hi=key_hi,
            bound_base=bound_base,
            bound_hi=bound_hi,
            city_step_key=city_step_key,
            city_value_bound=city_value_bound,
            has_alternates=has_alternates,
            fallback_candidates=fallback_candidates)

    def _prepare_fallback_paths(
        self,
        context: V2NativeEvalContext,
        bound_group: V2BoundGroup,
    ) -> list[V2FallbackPath]:
        """Materialize and cache a group's fallback paths in V1 order.

        The eager build used to reconstruct every non-winner path and
        compute its endpoint pop key while recording the group, even
        though most groups never reach a fallback. This helper performs
        that work only when a bound-killed probe or a no-entries eval
        actually walks fallbacks, and caches the result on the group so
        a second attempt in the same call reuses it. The sort key is
        unchanged: (-group_key[0], -group_key[1], -group_key[2]) followed
        by _v1_endpoint_pop_key, sorted stably.
        """
        prepared = bound_group.prepared_fallback_paths
        if prepared is not None:
            return prepared
        prepared = []
        for candidate in bound_group.fallback_candidates:
            candidate_key = candidate.group_key
            if candidate_key is None:
                continue
            tile_indices = self._candidate_tile_indices(candidate)
            pop_key = self._v1_endpoint_pop_key(
                context,
                tile_indices,
                candidate_key)
            prepared.append(V2FallbackPath(
                sort_key=(
                    (-candidate_key[0], -candidate_key[1],
                     -candidate_key[2])
                    + pop_key),
                candidate=candidate,
                tile_indices=tile_indices))
        prepared.sort(key=lambda fallback_path: fallback_path.sort_key)
        bound_group.prepared_fallback_paths = prepared
        return prepared

    def _bound_kills(
        self,
        bound_group: V2BoundGroup,
        best_table: dict[int, V2NativeOptionEntry],
    ) -> bool:
        """True when the group's bound cannot beat any incumbent it covers.

        The comparison is per curDist key across the group's whole
        possible key range — a single global bound vs a single
        incumbent would wrongly let a low-key winner pass while the
        group could still own uncovered high keys. The strict
        inequality is required because _native_should_replace also
        replaces equal-value rows on the worst-case/target-distance
        tiebreak."""
        bound_base = bound_group.bound_base
        city_step_key = bound_group.city_step_key
        city_value = bound_group.city_value_bound
        key_lo = bound_group.key_lo
        for cur_dist in range(key_lo, bound_group.key_hi + 1):
            incumbent = best_table.get(cur_dist)
            if incumbent is None:
                return False
            bound_value = bound_base + (cur_dist - key_lo) * (
                RECAPTURE_VALUE)
            if cur_dist >= city_step_key:
                bound_value += city_value
            if bound_value >= incumbent.this_value:
                return False
        return True

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

    def _v1_endpoint_pop_key(
        self,
        context: V2NativeEvalContext,
        tile_indices: list[int],
        candidate_key: tuple[int, int, int],
    ) -> tuple:
        """V1 heap pop ordering for one candidate's source endpoint.

        V1 pushes the path's source tile last; equal-valueFunc endpoints
        pop in heap-element order
        ((dist, euclid, cap, negArmy, srcTile), dist, curTurns, srcTile,
        parentTile). dist/cap/negArmy are identical for tied candidates,
        so the remaining order is: source's fromEuclidCur, source army
        (Tile.__lt__ compares army only), the parent's own push priority
        (its pop happens before it can push — approximated by the
        parent's prio tuple since heap pops are prio-ordered), the
        parent's army, and finally the source's position inside the
        parent's movable list — V1 pushes neighbors in movable order, so
        fully-equal elements from one parent pop land in that order and
        the earlier push pops first. When pushes are still equal after
        all of this, V1's heap-array order decides — which is
        nondeterministic across runs (movable iteration order varies
        per process and reshuffles the heap), so exact-residual parity
        is unachievable and unnecessary; the wave's keep-best dedupe
        resolves the same residual nondeterministically in V1's terms.
        """
        tiles_by_index = context.tiles_by_index
        positions_by_turn = context.positions_by_turn
        threat_dist_raw = context.threat_dist_raw
        num_positions = len(positions_by_turn)
        euclid_dist = self.v1.map.euclidDist
        source_tile = tiles_by_index[tile_indices[0]]
        parent_tile = (
            tiles_by_index[tile_indices[1]]
            if len(tile_indices) > 1
            else source_tile)

        def _from_euclid(tile: Tile) -> float:
            dist_to_threat = threat_dist_raw[tile.tile_index]
            dist_tuple = (
                positions_by_turn[dist_to_threat - 1]
                if 0 < dist_to_threat <= num_positions
                else None)
            if dist_tuple is None:
                return 100.0
            return euclid_dist(
                dist_tuple[0],
                dist_tuple[1],
                tile.x,
                tile.y)

        source_euclid = _from_euclid(source_tile)
        parent_euclid = _from_euclid(parent_tile)
        # The parent's accumulated prio fields equal the candidate's
        # full-path accumulation minus the source tile's own delta.
        # The candidate key stores (net-cap, -cap, net); cap_points is
        # unchanged because the source endpoint is always a friendly
        # tile (0 cap delta), and parent's negArmy drops the source's
        # -(army-1) friendly contribution.
        cap_points = -candidate_key[1]
        net_army = candidate_key[2]
        parent_cap = cap_points
        parent_neg_army = -(net_army - (source_tile.army - 1))
        arrival_movable_index = parent_tile.movable.index(source_tile)
        return (
            source_euclid,
            source_tile.army,
            parent_euclid,
            parent_cap,
            parent_neg_army,
            parent_tile.army,
            arrival_movable_index)

    def _runner_up_paths(
        self,
        context: V2NativeEvalContext,
        friendly_reach: FriendlyMultiSourceMatrix,
        winner_source_index: int,
        winner_indices: list[int],
        winner_key: tuple[int, int, int],
    ) -> list[list[int]]:
        """Value-tied alternate paths for a gate-rejected winner.

        V1's heap commits to whichever same-priority push pops first for
        a tile slot, so the retained pool is every same-source
        same-depth push the wave deduped away while tying the kept
        state's (net_army, cap_points) — exactly the alternates the
        deleted layered reach carried in equal_alternates_by_depth.
        Each alternate state carries its own complete source->tile
        prefix chain, so the alternate path for the slot at path
        position i is the tied state's materialized prefix + the
        winner's unchanged suffix — the seam edge path[i]->path[i+1] is
        the winner's own edge and stays valid for any state of the same
        tile. Slots are walked deepest-first so the smallest divergence
        is tried first. Paths that revisit a tile (V1's global visited
        set forbids them) or score differently under _v1_path_value_key
        are not V1-plausible alternates and are skipped.
        """
        alternates: list[list[int]] = []
        depth = len(winner_indices) - 1
        for position in range(depth, 0, -1):
            tied_states = friendly_reach.alternates_by_depth[
                position].get(winner_indices[position])
            if not tied_states:
                continue
            for tied_state in tied_states:
                if tied_state.source_index != winner_source_index:
                    continue
                alt_indices = (
                    self._state_tile_indices(tied_state)
                    + winner_indices[position + 1:])
                if len(set(alt_indices)) != len(alt_indices):
                    continue
                if self._v1_path_value_key(
                    context,
                    alt_indices) != winner_key:
                    continue
                alternates.append(alt_indices)
        return alternates

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
            positions_by_turn=average_enemy_position_by_turn,
            threat_dist_raw=(
                game_map.distance_mapper.get_tile_dist_matrix(
                    interception.threats[0].path.start.tile).raw),
        )

    def _evaluate_candidate_native(
        self,
        context: V2NativeEvalContext,
        candidate: V2InterceptCandidate,
        tile_indices: list[int],
        probe_only: bool = False,
    ) -> V2NativeCandidateEval:
        """Score one candidate exactly like V1's per-path option evaluation.

        probe_only=True stops right after the collision sim's
        continuation decision (skipping the damage walk, blocker gate,
        and econ walk): bound-killed groups only need to know whether
        V1's evaluation of this path would return False and stop the
        choke's deeper paths from being evaluated — identical
        reachability at a fraction of the eval cost. The early gates
        (threatened city source, debug bypass) run exactly as before
        because they return True before the collision check in V1's
        order."""
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
        if probe_only:
            return V2NativeCandidateEval(
                candidate=candidate,
                tile_indices=tile_indices,
                move_half_flags=move_half_flags,
                entries=[],
                evaluation_continued=True,
                skip_reason='probe_continued')

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

        For a positive friendly general-kill threat the LOCAL physics horizon
        (turns_left_in_cycle alias) extends to best_threat.turns + 1 so
        en-route city armies are still collected before the real intercept;
        context.turns_left_in_cycle and every economic budget stay unchanged.
        See Tests/test_BotBehavior.py
        test_should_intercept_large_army_instead_of_abandoning_general and
        test_should_keep_defending_general_against_large_army_for_fifty_turns,
        and UnitTests/test_ArmyInterceptionV2Unit.py
        test_should_collect_city_army_after_round_end_before_general_intercept.
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
        # Tests/test_BotBehavior.py::BotBehaviorTests.test_should_intercept_large_army_instead_of_abandoning_general
        # and ::test_should_keep_defending_general_against_large_army_for_fifty_turns, plus
        # UnitTests/test_ArmyInterceptionV2Unit.py::ArmyInterceptionV2UnitTests.
        # test_should_collect_city_army_after_round_end_before_general_intercept: lethal-general collision
        # physics must keep simulating past the economic cycle end so en-route city armies are collected;
        # only this local horizon extends -- context.turns_left_in_cycle and the econ budget are unchanged.
        if (context.best_threat.threatType == ThreatType.Kill
                and context.best_threat.threatValue > 0
                and context.best_threat.path.tail.tile.isGeneral
                and team_ids[context.best_threat.path.tail.tile.player] == friendly_team):
            turns_left_in_cycle = max(
                turns_left_in_cycle, context.best_threat.turns + 1)
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
