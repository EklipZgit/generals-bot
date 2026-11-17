"""Opt-in route-aware candidate experiment; never selects live bot moves."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import logbook

from Behavior.ArmyInterceptionModels import (
    GENERAL_CAP_VALUE,
    NEUTRAL_CAP_VALUE,
    OTHER_PARTY_CAP_VALUE,
    OWNED_CITY_CAP_VALUE_BONUS,
    TARGET_CAP_VALUE,
)

if TYPE_CHECKING:
    from Behavior.ArmyInterceptorV2 import (
        ArmyInterceptorV2,
        V2BoundGroup,
        V2InterceptCandidate,
        V2NativeCandidateEval,
        V2NativeEvalContext,
        V2NativeOptionEntry,
        V2WaveState,
    )


@dataclass(slots=True, frozen=True)
class ProxyRouteFeatures:
    """Memoized source-to-state route and static capture reward, not a bound."""

    route: tuple[int, ...]
    capture_value: float


@dataclass(slots=True)
class ProxyCandidate:
    """An already-generated alternative and its two explicit proxy priorities."""

    candidate: V2InterceptCandidate
    group: V2BoundGroup
    route: tuple[int, ...]
    coverage: int
    economic_priority: float


@dataclass(slots=True, frozen=True)
class ProxyOptionSnapshot:
    """Complete actionable route plus the existing scorer's winning fields."""

    cur_dist: int
    value: float
    damage_blocked: float
    enemy_remaining: int
    best_case: int
    worst_case: int
    recapture_turns: int
    required_delay: int
    friendly_reaching: int
    route: tuple[tuple[int, bool], ...]

    @property
    def first_move(self) -> tuple[int, int, bool] | None:
        """Return the literal first move, including its split flag."""
        if len(self.route) < 2:
            return None
        return self.route[0][0], self.route[1][0], self.route[0][1]


@dataclass(slots=True)
class ProxyComparison:
    """Serializable comparison; best-V/T is a diagnostic, not bot selection."""

    turn: int
    threat_tile: int
    eligible_routes: int
    extra_evaluations: int
    changed_rows: tuple[int, ...]
    same_table: bool
    best_value_per_turn_same: bool
    first_move_same: bool
    baseline_best: ProxyOptionSnapshot | None
    proposed_best: ProxyOptionSnapshot | None
    extra_routes: tuple[tuple[int, ...], ...]
    seconds: float


@dataclass(slots=True)
class V2ProxyShadowResult:
    """Detached proposed table/eval list, for diagnostics and offline tests only."""

    proposed_table: dict[int, V2NativeOptionEntry]
    proposed_evals: list[V2NativeCandidateEval]
    comparison: ProxyComparison


def _capture_reward(context: V2NativeEvalContext, tile_index: int) -> float:
    """Use existing capture constants without simulating combat or city growth."""
    tile = context.tiles_by_index[tile_index]
    team = context.team_ids[tile.player]
    if team == context.friendly_team:
        return 0.0
    target = team == context.first_threat_team
    reward = (
        TARGET_CAP_VALUE if target
        else OTHER_PARTY_CAP_VALUE if tile.player >= 0
        else NEUTRAL_CAP_VALUE)
    if target and tile.isGeneral:
        reward += GENERAL_CAP_VALUE
    if target and tile.isCity:
        reward += OWNED_CITY_CAP_VALUE_BONUS
    return reward


def _route_features(
    context: V2NativeEvalContext,
    state: V2WaveState,
    cache: dict[int, ProxyRouteFeatures],
) -> ProxyRouteFeatures:
    """Walk each shared prefix once; no BFS or Path objects are constructed."""
    pending: list[V2WaveState] = []
    cursor: V2WaveState | None = state
    while cursor is not None and id(cursor) not in cache:
        pending.append(cursor)
        cursor = cursor.parent_state
    prefix = (
        cache[id(cursor)] if cursor is not None
        else ProxyRouteFeatures((), 0.0))
    for node in reversed(pending):
        prefix = ProxyRouteFeatures(
            route=prefix.route + (node.tile_index,),
            capture_value=prefix.capture_value + _capture_reward(
                context, node.tile_index))
        cache[id(node)] = prefix
    return prefix


def _snapshot(entry: V2NativeOptionEntry) -> ProxyOptionSnapshot:
    """Do not collapse routes to endpoints: intermediate tiles change behavior."""
    evaluation = entry.candidate_eval
    return ProxyOptionSnapshot(
        cur_dist=entry.cur_dist,
        value=entry.this_value,
        damage_blocked=entry.damage_blocked,
        enemy_remaining=entry.enemy_army_left_after_intercept,
        best_case=entry.best_case_intercept_moves,
        worst_case=entry.worst_case_intercept_moves,
        recapture_turns=entry.recapture_turns,
        required_delay=entry.required_delay,
        friendly_reaching=entry.friendly_army_reaching_intercept,
        route=tuple(zip(
            evaluation.tile_indices, evaluation.move_half_flags, strict=True)))


def _ordered_table(
    table: dict[int, V2NativeOptionEntry],
    evaluations: list[V2NativeCandidateEval],
) -> dict[int, V2NativeOptionEntry]:
    """Match the emitter's choke-major first-write ordering, including new keys."""
    first_write: dict[int, int] = {}
    for evaluation in sorted(
        evaluations,
        key=lambda item: (
            item.bound_group.v1_eval_order
            if item.bound_group is not None else -1),
    ):
        for entry in evaluation.entries:
            if entry.cur_dist not in first_write:
                first_write[entry.cur_dist] = len(first_write)
    return {
        key: table[key]
        for key in sorted(
            table, key=lambda key: first_write.get(key, len(first_write)))
    }


def _best_value_per_turn(
    table: dict[int, V2NativeOptionEntry],
) -> ProxyOptionSnapshot | None:
    """Summarize positive V/T only; downstream defense has additional gates."""
    best: V2NativeOptionEntry | None = None
    best_ratio = 0.0
    for key, entry in table.items():
        if key <= 0:
            continue
        ratio = entry.this_value / key
        if ratio > best_ratio:
            best = entry
            best_ratio = ratio
    return _snapshot(best) if best is not None else None


def compare_route_proxy(
    interceptor: ArmyInterceptorV2,
    context: V2NativeEvalContext,
    evaluations: list[V2NativeCandidateEval],
    baseline_table: dict[int, V2NativeOptionEntry],
) -> V2ProxyShadowResult:
    """Score at most two route-distinct extras without changing live selection.

    The shortlist tries one tactical alternative, then one economic alternative:
    tactical priority is the count of the threat's immediate legal destinations
    adjacent to (or on) our first destination; economic priority is
    (min(nonnegative arrival army, nonnegative base threat army)
     + static capture rewards) / estimated turns including choke slack.
    Existing group_key is the stable final tie-break. These are heuristics,
    NOT admissible bounds or safety certificates.

    Only already-recorded groups that the incumbent evaluation reached and
    allowed to continue participate. Extra failures never change choke
    continuation. Current table entries remain incumbents and extras use the
    unchanged native replacement rule. Tests must verify both default-off
    dispatch and nonmutation; real moves always use baseline_table.
    """
    started = time.perf_counter()
    feature_cache: dict[int, ProxyRouteFeatures] = {}
    seen_routes = {tuple(item.tile_indices) for item in evaluations}
    seen_groups: set[int] = set()
    alternatives: list[ProxyCandidate] = []
    threat_moves = set(context.interception.target_tile.movableNoObstacles)
    for evaluation in evaluations:
        group = evaluation.bound_group
        if (
            group is None
            or not evaluation.evaluation_continued
            or id(group) in seen_groups
        ):
            continue
        seen_groups.add(id(group))
        for candidate in (group.candidate, *group.fallback_candidates):
            state = candidate.wave_state
            if candidate.group_key is None or state is None:
                continue
            features = _route_features(context, state, feature_cache)
            route = features.route
            if len(route) < 2 or route in seen_routes:
                continue
            seen_routes.add(route)
            first_dest = context.tiles_by_index[route[1]]
            covered = set(first_dest.movableNoObstacles)
            covered.add(first_dest)
            coverage = len(threat_moves & covered)
            intercept_distance = context.first_bmap_raw[route[-1]]
            additional_turns = (
                intercept_distance if context.target_is_city
                else max(0, intercept_distance - candidate.depth))
            turns = max(
                1,
                candidate.depth + additional_turns
                + context.interception.common_intercept_chokes[
                    candidate.choke_tile].max_extra_moves_to_capture)
            effective_army = min(
                max(0, candidate.friendly_army),
                max(0, context.interception.base_threat_army))
            alternatives.append(ProxyCandidate(
                candidate=candidate,
                group=group,
                route=route,
                coverage=coverage,
                economic_priority=(
                    effective_army + features.capture_value) / turns))
    selected: list[ProxyCandidate] = []
    if alternatives:
        tactical = max(
            alternatives,
            key=lambda item: (
                item.coverage, item.economic_priority,
                item.candidate.group_key))
        selected.append(tactical)
        remaining = [item for item in alternatives if item is not tactical]
        if remaining:
            selected.append(max(
                remaining,
                key=lambda item: (
                    item.economic_priority, item.coverage,
                    item.candidate.group_key)))
    proposed_table = dict(baseline_table)
    proposed_evals = list(evaluations)
    for item in selected:
        extra = interceptor._evaluate_candidate_native(
            context, item.candidate, list(item.route))
        extra.bound_group = item.group
        proposed_evals.append(extra)
        for entry in extra.entries:
            existing = proposed_table.get(entry.cur_dist)
            if existing is None or interceptor._native_should_replace(
                context, existing, entry,
            ):
                proposed_table[entry.cur_dist] = entry
    baseline_ordered = _ordered_table(baseline_table, evaluations)
    proposed_ordered = _ordered_table(proposed_table, proposed_evals)
    changed_rows = tuple(
        key
        for key in sorted(set(baseline_table) | set(proposed_table))
        if (
            (_snapshot(baseline_table[key]) if key in baseline_table else None)
            != (_snapshot(proposed_table[key]) if key in proposed_table else None)
        ))
    baseline_best = _best_value_per_turn(baseline_ordered)
    proposed_best = _best_value_per_turn(proposed_ordered)
    comparison = ProxyComparison(
        turn=context.map_turn,
        threat_tile=context.interception.target_tile.tile_index,
        eligible_routes=len(alternatives),
        extra_evaluations=len(selected),
        changed_rows=changed_rows,
        same_table=(
            not changed_rows
            and list(baseline_ordered) == list(proposed_ordered)),
        best_value_per_turn_same=baseline_best == proposed_best,
        first_move_same=(
            (baseline_best.first_move if baseline_best is not None else None)
            == (proposed_best.first_move if proposed_best is not None else None)),
        baseline_best=baseline_best,
        proposed_best=proposed_best,
        extra_routes=tuple(item.route for item in selected),
        seconds=time.perf_counter() - started)
    logbook.info(
        'INTERCEPT_PROXY_SHADOW ' + json.dumps(
            asdict(comparison), sort_keys=True, separators=(',', ':')))
    return V2ProxyShadowResult(
        proposed_table=proposed_ordered,
        proposed_evals=proposed_evals,
        comparison=comparison)
