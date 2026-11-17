"""Bounded native scoring used by default; independent of incumbent evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from Behavior.ArmyInterceptionModels import RECAPTURE_VALUE
from Behavior.ArmyInterceptionProxy import (
    ProxyRouteFeatures,
    _route_features,
)

if TYPE_CHECKING:
    from Behavior.ArmyInterceptorV2 import (
        ArmyInterceptorV2,
        FriendlyMultiSourceMatrix,
        V2InterceptCandidate,
        V2NativeCandidateEval,
        V2NativeEvalContext,
        V2NativeOptionEntry,
    )


@dataclass(slots=True)
class PreselectionGroup:
    """One V1-recordable choke/depth slot, ranked before any collision scoring."""

    winner: V2InterceptCandidate
    alternatives: list[V2InterceptCandidate]
    route: tuple[int, ...]
    v1_order: int
    estimated_turns: int
    estimated_blocked: float
    estimated_value_per_turn: float


@dataclass(slots=True)
class PreselectionStats:
    """Actual work performed by the bounded replacement, not predicted savings."""

    candidates: int
    eligible_groups: int
    selected_groups: int
    scored_groups: int
    native_evaluations: int


@dataclass(slots=True)
class PreselectionResult:
    """Detached native result that the ordinary option emitter can consume."""

    table: dict[int, V2NativeOptionEntry]
    evaluations: list[V2NativeCandidateEval]
    stats: PreselectionStats


def _winner(
    interceptor: ArmyInterceptorV2,
    context: V2NativeEvalContext,
    candidates: list[V2InterceptCandidate],
) -> V2InterceptCandidate | None:
    """Retain the current group-key winner and endpoint-pop tie ordering."""
    winner: V2InterceptCandidate | None = None
    winner_pop: tuple | None = None
    for candidate in candidates:
        key = candidate.group_key
        if key is None:
            continue
        if winner is None or key > winner.group_key:
            winner = candidate
            winner_pop = None
        elif key == winner.group_key:
            pop = interceptor._v1_endpoint_pop_key(
                context, interceptor._candidate_tile_indices(candidate), key)
            if winner_pop is None:
                winner_pop = interceptor._v1_endpoint_pop_key(
                    context, interceptor._candidate_tile_indices(winner), key)
            if pop < winner_pop:
                winner = candidate
                winner_pop = pop
    return winner


def build_preselection_groups(
    interceptor: ArmyInterceptorV2,
    context: V2NativeEvalContext,
    candidates: list[V2InterceptCandidate],
) -> list[PreselectionGroup]:
    """Apply existing recording gates, then estimate V/T without collision sims.

    Estimate = blocked-damage walk at the approximate tail army + static
    capture rewards + applicable sparse bonus - existing length penalty.
    Compare its base V/T with a surplus-army recapture extension's V/T.
    This is a ranking heuristic, not an admissible bound or safety proof.
    """
    by_choke: dict[int, list[V2InterceptCandidate]] = {}
    for candidate in candidates:
        by_choke.setdefault(
            candidate.choke_tile.tile_index, []).append(candidate)
    groups: list[PreselectionGroup] = []
    features: dict[int, ProxyRouteFeatures] = {}
    for choke in context.interception.common_intercept_chokes:
        depths: dict[int, list[V2InterceptCandidate]] = {}
        for candidate in by_choke.get(choke.tile_index, []):
            depths.setdefault(candidate.depth, []).append(candidate)
        recorded: dict[int, tuple[int, int, int]] = {}
        for depth in sorted(depths):
            winner = _winner(interceptor, context, depths[depth])
            if winner is None:
                continue
            key = winner.group_key
            assert key is not None
            previous = recorded.get(depth - 1)
            if previous is not None and key <= previous:
                continue
            recorded[depth] = key
            assert winner.wave_state is not None
            route_features = _route_features(
                context, winner.wave_state, features)
            route = route_features.route
            tail = context.tiles_by_index[route[-1]]
            tail_friendly = (
                context.team_ids[tail.player] == context.friendly_team)
            arrival_army = winner.friendly_army + (
                tail.army if tail_friendly else -tail.army)
            blocked = interceptor._estimate_threat_blocked(
                context.interception, choke, arrival_army,
                context.turns_left_in_cycle)
            intercept_distance = context.first_bmap_raw[choke.tile_index]
            additional = (
                intercept_distance if context.target_is_city
                else max(0, intercept_distance - depth))
            turns = max(
                1, depth + additional
                + context.interception.common_intercept_chokes[
                    choke].max_extra_moves_to_capture)
            value = blocked + route_features.capture_value - 0.06 * turns
            if additional == 0 and turns < min(5, context.sparse_len_cutoff):
                value += context.sparse_bonus
            recaptures = min(
                max(0, context.turns_left_in_cycle - turns),
                max(0, arrival_army - context.interception.base_threat_army) // 2)
            estimate = max(
                value / turns,
                (value + recaptures * RECAPTURE_VALUE) / (turns + recaptures))
            groups.append(PreselectionGroup(
                winner=winner,
                alternatives=[
                    item for item in depths[depth]
                    if item is not winner and item.group_key is not None],
                route=route,
                v1_order=len(groups),
                estimated_turns=turns,
                estimated_blocked=blocked,
                estimated_value_per_turn=estimate))
    return groups


def select_preselection_groups(
    groups: list[PreselectionGroup],
) -> list[PreselectionGroup]:
    """Keep at most six slots, reserving early arrival and blocked damage.

    Pick best estimated V/T, earliest arrival, and greatest estimated blocked
    damage. Fill remaining places by V/T, preferring distinct source/first-move
    pairs before taking redundant routes. Final scoring keeps V1 iteration order.
    """
    if not groups:
        return []
    ranked = sorted(
        groups,
        key=lambda item: (
            -item.estimated_value_per_turn, -item.estimated_blocked,
            item.estimated_turns, item.v1_order))
    selected: list[PreselectionGroup] = []
    selected_orders: set[int] = set()
    first_moves: set[tuple[int, ...]] = set()

    def retain(group: PreselectionGroup) -> None:
        """Track stable identity and the executed first-step diversity key."""
        if len(selected) >= 6 or group.v1_order in selected_orders:
            return
        selected.append(group)
        selected_orders.add(group.v1_order)
        first_moves.add(group.route[:2])

    retain(ranked[0])
    retain(min(
        groups,
        key=lambda item: (
            item.estimated_turns, -item.estimated_value_per_turn, item.v1_order)))
    retain(max(
        groups,
        key=lambda item: (
            item.estimated_blocked, item.estimated_value_per_turn, -item.v1_order)))
    for group in ranked:
        if group.route[:2] not in first_moves:
            retain(group)
    for group in ranked:
        retain(group)
    return sorted(selected, key=lambda item: item.v1_order)


def evaluate_preselected(
    interceptor: ArmyInterceptorV2,
    context: V2NativeEvalContext,
    friendly_reach: FriendlyMultiSourceMatrix,
    candidates: list[V2InterceptCandidate],
) -> PreselectionResult:
    """Replace exhaustive scoring with at most six groups and twelve full evals.

    Neither incumbent table nor incumbent evaluations are inputs. Unselected
    groups are not probed. Selected groups honor choke continuation among
    themselves; skipping a shallower group is an explicit coverage tradeoff.
    Each selected winner gets at most one rejected-path retry (a tied prefix
    first, otherwise the next V1-key candidate). No emergency exhaustive
    fallback is hidden here: missed options must be visible in shadow tests.
    """
    interceptor.damage_estimate_cache.clear()
    groups = build_preselection_groups(interceptor, context, candidates)
    selected = select_preselection_groups(groups)
    table: dict[int, V2NativeOptionEntry] = {}
    evaluations: list[V2NativeCandidateEval] = []
    blocked_chokes: set[int] = set()
    native_calls = 0
    for group in selected:
        choke_index = group.winner.choke_tile.tile_index
        if choke_index in blocked_chokes:
            continue
        winner_route = list(group.route)
        evaluation = interceptor._evaluate_candidate_native(
            context, group.winner, winner_route)
        native_calls += 1
        if not evaluation.entries:
            retry_route: list[int] | None = None
            retry_candidate = group.winner
            if evaluation.skip_reason in (
                'unsplittable_blocked_destination', 'best_case_intercept_1000',
            ):
                retry_route = next(
                    iter(interceptor._runner_up_paths(
                        context, friendly_reach, group.winner.source_index,
                        winner_route, group.winner.group_key)),
                    None)
            if retry_route is None:
                fallback = _winner(interceptor, context, group.alternatives)
                if fallback is not None:
                    retry_candidate = fallback
                    retry_route = interceptor._candidate_tile_indices(fallback)
            if retry_route is not None:
                retry = interceptor._evaluate_candidate_native(
                    context, retry_candidate, retry_route)
                native_calls += 1
                if retry.entries or (
                    retry.evaluation_continued
                    and not evaluation.evaluation_continued
                ):
                    evaluation = retry
        # bound_group stays None: these rows have no admissible bound. The
        # emitter's stable sort preserves this already-V1-ordered eval list.
        evaluations.append(evaluation)
        if not evaluation.evaluation_continued:
            blocked_chokes.add(choke_index)
            continue
        for entry in evaluation.entries:
            existing = table.get(entry.cur_dist)
            if existing is None or interceptor._native_should_replace(
                context, existing, entry,
            ):
                table[entry.cur_dist] = entry
    return PreselectionResult(
        table=table,
        evaluations=evaluations,
        stats=PreselectionStats(
            candidates=len(candidates),
            eligible_groups=len(groups),
            selected_groups=len(selected),
            scored_groups=len(evaluations),
            native_evaluations=native_calls))
