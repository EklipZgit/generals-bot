from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from unittest import mock

from Behavior.ArmyInterceptor import ArmyInterceptor
from Behavior.ArmyInterceptionModels import ArmyInterception
from Behavior.ArmyInterceptorV2 import (
    ArmyInterceptorV2,
    FriendlyMultiSourceMatrix,
    ThreatReachMatrix,
    V2BoundContext,
    V2BoundGroup,
    V2CandidatePath,
    V2InterceptCandidate,
    V2NativeCandidateEval,
    V2NativeEvalContext,
    V2NativeOptionEntry,
    V2WaveState,
)
from Behavior.ArmyInterceptionPreselection import (
    PreselectionGroup,
    PreselectionResult,
    select_preselection_groups,
)
from Behavior.ArmyInterceptionProxy import compare_route_proxy
from DangerAnalyzer import ThreatType
from Path import Path
from Strategy import OpponentTracker
from TestBase import TestBase
from base.client.map import MapBase, Tile


@dataclass(slots=True)
class ArmyInterceptionV2Scenario:
    map: MapBase
    general: Tile
    enemy_general: Tile
    enemy_tile: Tile | None


@dataclass(slots=True)
class ArmyInterceptionV2WaveInputs:
    """V1 plan plus the V2 wave inputs built from it (no option scoring)."""
    scenario: ArmyInterceptionV2Scenario
    turns_left_in_cycle: int
    v1_plan: ArmyInterception
    best_v1_damage_blocked: float
    interceptor: ArmyInterceptor
    max_depth: int
    allowed_search_region: bytearray
    choke_search_depths: dict[Tile, int]
    threat_reach: ThreatReachMatrix
    positions_by_turn: list[tuple[float, float] | None]
    friendly_reach: FriendlyMultiSourceMatrix
    candidates: list[V2InterceptCandidate]
    candidate_paths: list[V2CandidatePath]


class ArmyInterceptionV2UnitTests(TestBase):
    __slots__ = ()

    USE_V2_INTERCEPTION: bool = True

    def __init__(self, methodName: str = ...) -> None:
        """Initialize deterministic V2 interception scenarios."""
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)
        self.use_v2_interception = (
            ArmyInterceptionV2UnitTests.USE_V2_INTERCEPTION)
        TestBase.GLOBAL_BYPASS_RENDERING = True

    def test_should_build_v2_invariants_for_kill_and_city_threat(self) -> None:
        """Exercise the V2 matrices on the existing kill/city test scenario."""
        map_file = (
            'GameContinuationEntries/'
            'should_see_city_as_forward_from_central_point___'
            'HgAyaVTVa---1--307.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            307,
            fill_out_tiles=True)
        self._assert_v2_scenario_invariants(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=map.At(7, 14),
            ))

    def test_should_build_v2_invariants_for_one_kill_threat(self) -> None:
        """Exercise V2 with the existing single-kill interception scenario."""
        map_file = (
            'GameContinuationEntries/'
            'should_kill_one_away_armies_that_can_do_real_damage_'
            'immediately___Human.exe-TEST__665a5e30-6063-4675-bff6-'
            '61edf7423b72---1--386.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            386,
            fill_out_tiles=True)
        self._assert_v2_scenario_invariants(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=None,
            ),
            require_single_kill_threat=True)

    def test_should_cache_directed_threat_gate_within_friendly_wave(
        self,
    ) -> None:
        """The call-local directed-edge gate cache must not change output."""
        map_file = (
            'GameContinuationEntries/'
            'should_see_city_as_forward_from_central_point___'
            'HgAyaVTVa---1--307.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            307,
            fill_out_tiles=True)
        computed = self._compute_v2_wave_inputs(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=map.At(7, 14),
            ))
        v2 = computed.interceptor.v2

        gate_results: list[tuple[tuple[int, int], bool]] = []
        real_gate = ArmyInterceptorV2._threat_progress_gate_accepts

        def counting_gate(
            self_arg: ArmyInterceptorV2,
            tile: Tile,
            next_tile: Tile,
            next_threat_dist: int,
            cur_dist_tuple: tuple[float, float] | None,
            positions_by_turn: list[tuple[float, float] | None],
            num_positions: int,
            grid: list[list[Tile]],
            euclid_dist: Callable[[float, float, float, float], float],
        ) -> bool:
            result = real_gate(
                self_arg,
                tile,
                next_tile,
                next_threat_dist,
                cur_dist_tuple,
                positions_by_turn,
                num_positions,
                grid,
                euclid_dist)
            gate_results.append(
                ((tile.tile_index, next_tile.tile_index), result))
            return result

        with mock.patch.object(
            ArmyInterceptorV2,
            '_threat_progress_gate_accepts',
            counting_gate):
            cached_reach = v2.build_friendly_multi_source_matrix(
                computed.v1_plan,
                computed.threat_reach,
                computed.choke_search_depths,
                computed.positions_by_turn)
            first_call_results = list(gate_results)
            gate_results.clear()
            cached_reach_again = v2.build_friendly_multi_source_matrix(
                computed.v1_plan,
                computed.threat_reach,
                computed.choke_search_depths,
                computed.positions_by_turn)
            second_call_results = list(gate_results)
            gate_results.clear()
            uncached_reach = v2.build_friendly_multi_source_matrix(
                computed.v1_plan,
                computed.threat_reach,
                computed.choke_search_depths,
                computed.positions_by_turn,
                _cache_threat_gate=False)
            uncached_results = list(gate_results)

        self.assertEqual(
            self._friendly_wave_signature(cached_reach, v2),
            self._friendly_wave_signature(uncached_reach, v2))
        self.assertEqual(
            self._friendly_wave_signature(cached_reach, v2),
            self._friendly_wave_signature(cached_reach_again, v2))
        first_call_edges = [edge for edge, _ in first_call_results]
        second_call_edges = [edge for edge, _ in second_call_results]
        uncached_edges = [edge for edge, _ in uncached_results]
        # Each directed edge is evaluated at most once per call.
        self.assertEqual(
            len(first_call_edges),
            len(set(first_call_edges)))
        # The cache is call-local: a fresh call recomputes the same
        # directed-edge set rather than reusing a persisted cache.
        self.assertEqual(len(first_call_edges), len(second_call_edges))
        self.assertGreater(len(first_call_edges), 0)
        self.assertGreater(len(uncached_edges), 0)
        self.assertLess(len(first_call_edges), len(uncached_edges))
        # A rejected edge the uncached wave evaluates more than once is
        # computed exactly once when cached.
        uncached_edge_counts = Counter(uncached_edges)
        repeated_rejected_edges = {
            edge
            for edge, accepted in uncached_results
            if not accepted and uncached_edge_counts[edge] > 1}
        self.assertTrue(repeated_rejected_edges)
        cached_edge_counts = Counter(first_call_edges)
        for edge in repeated_rejected_edges:
            self.assertEqual(1, cached_edge_counts[edge])

    def test_should_prepare_fallback_paths_lazily_in_v1_order(self) -> None:
        """Fallback paths materialize on demand in V1 record order.

        _build_bound_group keeps raw candidate references and must not
        reconstruct any fallback path; _prepare_fallback_paths pays for
        reconstruction/pop keys only on the first fallback attempt and
        caches the result. group_key-None exclusion is enforced when
        evaluate_candidates_native builds the raw fallback list (the
        helper re-checks it defensively). A shallow dataclasses.replace
        copy with an identical sort key verifies the stable sort keeps
        the earlier fallback ahead of the later tie.
        """
        map_file = (
            'GameContinuationEntries/'
            'should_see_city_as_forward_from_central_point___'
            'HgAyaVTVa---1--307.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            307,
            fill_out_tiles=True)
        computed = self._compute_v2_wave_inputs(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=map.At(7, 14),
            ))
        v2 = computed.interceptor.v2
        opponent_tracker = OpponentTracker(computed.scenario.map)
        opponent_tracker.analyze_turn(
            computed.v1_plan.threats[0].threatPlayer)
        context = v2._build_native_eval_context(
            computed.v1_plan,
            computed.threat_reach,
            computed.turns_left_in_cycle,
            opponent_tracker,
            None,
            computed.positions_by_turn)
        bound_context = v2._build_bound_context(
            context,
            computed.friendly_reach)

        selected: tuple[tuple[int, int], Tile, int, list[V2InterceptCandidate]] | None = None
        for choke_tile in computed.v1_plan.common_intercept_chokes:
            depth_groups: dict[int, list[V2InterceptCandidate]] = {}
            for candidate in computed.candidates:
                if candidate.choke_tile.tile_index == choke_tile.tile_index:
                    depth_groups.setdefault(
                        candidate.depth,
                        []).append(candidate)
            for depth in sorted(depth_groups):
                group = depth_groups[depth]
                eligible = [
                    candidate
                    for candidate in group
                    if candidate.group_key is not None]
                has_none_key = any(
                    candidate.group_key is None for candidate in group)
                score = (1 if has_none_key else 0, len(eligible))
                if selected is None or score > selected[0]:
                    selected = (score, choke_tile, depth, group)
        self.assertIsNotNone(selected)
        _, choke_tile, _, group = selected
        winner = max(
            (
                candidate
                for candidate in group
                if candidate.group_key is not None),
            key=lambda candidate: candidate.group_key)
        fallback_candidates = [
            candidate
            for candidate in group
            if candidate is not winner
            and candidate.group_key is not None]
        self.assertGreaterEqual(len(fallback_candidates), 1)
        # A shallow copy shares group_key and wave state, so its sort key
        # ties the original; the stable sort must keep the earlier
        # fallback ahead of this later tie.
        tied_candidate = replace(fallback_candidates[0])
        fallback_candidates.append(tied_candidate)
        winner_indices = v2._candidate_tile_indices(winner)

        expected: list[
            tuple[tuple, V2InterceptCandidate, list[int]]] = []
        for candidate in fallback_candidates:
            candidate_key = candidate.group_key
            if candidate_key is None:
                continue
            tile_indices = v2._candidate_tile_indices(candidate)
            pop_key = v2._v1_endpoint_pop_key(
                context,
                tile_indices,
                candidate_key)
            expected.append((
                (
                    (-candidate_key[0], -candidate_key[1],
                     -candidate_key[2])
                    + pop_key),
                candidate,
                tile_indices))
        expected.sort(key=lambda entry: entry[0])

        tile_index_calls = 0
        real_candidate_tile_indices = (
            ArmyInterceptorV2._candidate_tile_indices)

        def counting_candidate_tile_indices(
            self_arg: ArmyInterceptorV2,
            candidate: V2InterceptCandidate,
        ) -> list[int]:
            nonlocal tile_index_calls
            tile_index_calls += 1
            return real_candidate_tile_indices(self_arg, candidate)

        with mock.patch.object(
            ArmyInterceptorV2,
            '_candidate_tile_indices',
            counting_candidate_tile_indices):
            bound_group = v2._build_bound_group(
                context,
                bound_context,
                computed.friendly_reach,
                computed.v1_plan,
                choke_tile,
                0,
                0,
                winner,
                winner_indices,
                winner.group_key,
                fallback_candidates)
            # Group creation keeps raw fallback references; it must not
            # reconstruct any fallback path.
            self.assertEqual(0, tile_index_calls)
            self.assertIsNone(bound_group.prepared_fallback_paths)
            prepared = v2._prepare_fallback_paths(context, bound_group)
            self.assertEqual(len(fallback_candidates), tile_index_calls)
            first_prepare_calls = tile_index_calls
            self.assertIs(
                v2._prepare_fallback_paths(context, bound_group),
                prepared)
            self.assertEqual(first_prepare_calls, tile_index_calls)

        self.assertIs(bound_group.prepared_fallback_paths, prepared)
        self.assertEqual(len(prepared), len(expected))
        self.assertEqual(
            [entry.sort_key for entry in prepared],
            [entry[0] for entry in expected])
        self.assertEqual(
            [id(entry.candidate) for entry in prepared],
            [id(entry[1]) for entry in expected])
        self.assertEqual(
            [entry.tile_indices for entry in prepared],
            [entry[2] for entry in expected])
        first_candidate = fallback_candidates[0]
        first_position = next(
            index
            for index, entry in enumerate(prepared)
            if entry.candidate is first_candidate)
        tied_position = next(
            index
            for index, entry in enumerate(prepared)
            if entry.candidate is tied_candidate)
        self.assertLess(first_position, tied_position)

    def test_should_collect_city_army_after_round_end_before_general_intercept(
        self,
    ) -> None:
        """Lethal-general collision sims must run past the cycle end.

        Regression coverage for
        Tests/test_BotBehavior.py::BotBehaviorTests.
        test_should_intercept_large_army_instead_of_abandoning_general and
        test_should_keep_defending_general_against_large_army_for_fifty_turns:
        the scripted defensive proof route collects the (3,12) city army after
        the 6-turn cycle boundary, so both collision engines must extend only
        their local physics horizon to the general-kill threat's arrival
        instead of truncating at turns_left_in_cycle. Frozen values come from
        the turn-694 truemap and the exact enemy/proof paths below; before the
        horizon fix both engines stop after six iterations and report
        friendly=576 via closest-approach fallback, after it they agree on
        friendly=647 / enemy=617 at intercept turn 14.
        """
        map_file = (
            'GameContinuationEntries/'
            'should_intercept_large_army_instead_of_abandoning_general___'
            'Y9S75moK8---7--694.truemap.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            694,
            fill_out_tiles=True)
        interceptor = self.get_interceptor(
            map,
            general,
            enemy_general,
            useDebugLogging=False)
        enemy_path = Path.from_string(
            map,
            '7,4->7,5->6,5->5,5->5,6->5,7->5,8->5,9->5,10->5,11->4,11'
            '->3,11->2,11->1,11->1,12->0,12->0,13')
        threat = self.build_threat(map, enemy_path)
        plan = interceptor.get_interception_plan([threat], 6)
        self.assertIsNotNone(plan)

        max_depth = interceptor._get_max_interception_search_depth(
            plan.threats)
        allowed_search_region = (
            interceptor.v2.build_allowed_search_region(plan))
        choke_search_depths = (
            interceptor.v2.resolve_choke_search_depths(
                plan,
                plan.middlest_intercept_tiles,
                False))
        threat_reach = interceptor.v2.build_threat_reach_matrix(
            plan,
            max_depth,
            6,
            choke_search_depths,
            allowed_search_region)
        positions_by_turn = (
            interceptor._build_average_enemy_position_by_turn(
                plan,
                max_depth))
        opponent_tracker = OpponentTracker(map)
        opponent_tracker.analyze_turn(threat.threatPlayer)
        context = interceptor.v2._build_native_eval_context(
            plan,
            threat_reach,
            6,
            opponent_tracker,
            None,
            positions_by_turn)
        proof_path = Path.from_string(
            map,
            '9,13->8,13->7,13->6,13->6,12->5,12->4,12->3,12->2,12'
            '->1,12->0,12')
        proof_tiles = proof_path.tileList

        with self.subTest(engine='v1_shared'):
            v1_result = (
                interceptor
                ._get_result_of_executing_paths_to_intercept_point(
                    plan, threat, proof_path, 6))
            self.assertEqual(647, v1_result.friendly_army_at_intercept)
            self.assertEqual(
                617, v1_result.enemy_physical_army_at_intercept)
            self.assertEqual(14, v1_result.worst_case_intercept_turn)
            self.assertEqual(-8, v1_result.turns_left)
        with self.subTest(engine='v2_native'):
            v2_result = interceptor.v2._native_collision_sim(
                context, proof_tiles)
            self.assertEqual(647, v2_result.friendly_army_at_intercept)
            self.assertEqual(
                617, v2_result.enemy_physical_army_at_intercept)
            self.assertEqual(14, v2_result.worst_case_intercept_turn)
        self.assertEqual(6, context.turns_left_in_cycle)

    def _load_proxy_scenario(self) -> ArmyInterceptionV2WaveInputs:
        """Load the shared kill/city scenario for proxy shadow tests."""
        map_file = (
            'GameContinuationEntries/'
            'should_see_city_as_forward_from_central_point___'
            'HgAyaVTVa---1--307.txtmap')
        map, general, enemy_general = self.load_map_and_generals(
            map_file,
            307,
            fill_out_tiles=True)
        return self._compute_v2_wave_inputs(
            ArmyInterceptionV2Scenario(
                map=map,
                general=general,
                enemy_general=enemy_general,
                enemy_tile=map.At(7, 14),
            ))

    def _native_opponent_tracker(
        self,
        computed: ArmyInterceptionV2WaveInputs,
    ) -> OpponentTracker:
        """Build the opponent tracker evaluate_candidates_native expects."""
        opponent_tracker = OpponentTracker(computed.scenario.map)
        opponent_tracker.analyze_turn(
            computed.v1_plan.threats[0].threatPlayer)
        return opponent_tracker

    def _run_native_eval(
        self,
        computed: ArmyInterceptionV2WaveInputs,
        candidates: list[V2InterceptCandidate] | None = None,
    ) -> dict[int, V2NativeOptionEntry]:
        """Run evaluate_candidates_native on the computed wave inputs."""
        v2 = computed.interceptor.v2
        return v2.evaluate_candidates_native(
            computed.v1_plan,
            computed.threat_reach,
            computed.friendly_reach,
            computed.candidates if candidates is None else candidates,
            computed.turns_left_in_cycle,
            self._native_opponent_tracker(computed),
            None,
            computed.positions_by_turn)

    def _entry_signature(self, entry: V2NativeOptionEntry) -> tuple:
        """Full option row plus route/move_half for exact table compare."""
        evaluation = entry.candidate_eval
        return (
            entry.cur_dist,
            entry.this_value,
            entry.damage_blocked,
            entry.enemy_army_left_after_intercept,
            entry.best_case_intercept_moves,
            entry.worst_case_intercept_moves,
            entry.recapture_turns,
            entry.required_delay,
            entry.friendly_army_reaching_intercept,
            tuple(evaluation.tile_indices),
            tuple(evaluation.move_half_flags))

    def _proxy_shadow_fixture(
        self,
        computed: ArmyInterceptionV2WaveInputs,
    ) -> tuple[
        V2NativeEvalContext,
        V2NativeCandidateEval,
        dict[int, V2NativeOptionEntry]]:
        """Real context plus one baseline eval/group for direct compare calls."""
        v2 = computed.interceptor.v2
        context = v2._build_native_eval_context(
            computed.v1_plan,
            computed.threat_reach,
            computed.turns_left_in_cycle,
            self._native_opponent_tracker(computed),
            None,
            computed.positions_by_turn)
        eligible = [
            candidate
            for candidate in computed.candidates
            if candidate.group_key is not None
            and candidate.wave_state is not None]
        self.assertGreaterEqual(len(eligible), 2)
        winner = eligible[0]
        fallbacks = eligible[1:5]
        winner_indices = v2._candidate_tile_indices(winner)
        bound_group = V2BoundGroup(
            choke_tile=winner.choke_tile,
            group_index=0,
            v1_eval_order=0,
            candidate=winner,
            tile_indices=winner_indices,
            winner_key=winner.group_key,
            key_lo=0,
            key_hi=10,
            bound_base=0.0,
            bound_hi=0.0,
            city_step_key=11,
            city_value_bound=0.0,
            has_alternates=False,
            fallback_candidates=fallbacks)
        baseline_eval = V2NativeCandidateEval(
            candidate=winner,
            tile_indices=winner_indices,
            move_half_flags=[False] * len(winner_indices),
            entries=[],
            evaluation_continued=True,
            skip_reason='',
            bound_group=bound_group)
        baseline_entry = V2NativeOptionEntry(
            cur_dist=5,
            this_value=10.0,
            damage_blocked=1.0,
            enemy_army_left_after_intercept=3,
            best_case_intercept_moves=4,
            worst_case_intercept_moves=6,
            recapture_turns=2,
            required_delay=1,
            friendly_army_reaching_intercept=7,
            candidate_eval=baseline_eval)
        baseline_eval.entries.append(baseline_entry)
        return context, baseline_eval, {5: baseline_entry}

    def test_proxy_shadow_disabled_by_default_and_not_called(self) -> None:
        """Flag off: no proxy work, no shadow result, baseline table intact."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        self.assertFalse(v2.proxy_shadow_enabled)
        self.assertIsNone(v2.last_proxy_shadow)
        with mock.patch(
            'Behavior.ArmyInterceptorV2.compare_route_proxy'
        ) as compare_spy:
            table = self._run_native_eval(computed)
        compare_spy.assert_not_called()
        self.assertIsNone(v2.last_proxy_shadow)
        self.assertTrue(table)

    def test_proxy_shadow_matches_baseline_and_preserves_live_evals(
        self,
    ) -> None:
        """Shadow run returns the untouched baseline table and evals."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        v2.preselection_enabled = False
        baseline_table = self._run_native_eval(computed)
        baseline_eval_count = len(v2.last_native_evals)
        self.assertTrue(baseline_table)
        v2.proxy_shadow_enabled = True
        shadow_table = self._run_native_eval(computed)
        self.assertEqual(
            [key for key in baseline_table],
            [key for key in shadow_table])
        self.assertEqual(
            [
                self._entry_signature(baseline_table[key])
                for key in baseline_table],
            [
                self._entry_signature(shadow_table[key])
                for key in shadow_table])
        shadow = v2.last_proxy_shadow
        self.assertIsNotNone(shadow)
        comparison = shadow.comparison
        self.assertLessEqual(comparison.extra_evaluations, 2)
        self.assertEqual(
            comparison.extra_evaluations,
            len(comparison.extra_routes))
        live_evals = v2.last_native_evals
        self.assertEqual(baseline_eval_count, len(live_evals))
        self.assertTrue(all(
            shadow.proposed_evals[index] is live_evals[index]
            for index in range(len(live_evals))))
        self.assertEqual(
            len(live_evals) + comparison.extra_evaluations,
            len(shadow.proposed_evals))
        baseline_routes = {
            tuple(evaluation.tile_indices)
            for evaluation in live_evals}
        for route in comparison.extra_routes:
            self.assertNotIn(route, baseline_routes)
        self.assertEqual(
            len(set(comparison.extra_routes)),
            len(comparison.extra_routes))

    def test_proxy_shadow_fake_high_extra_changes_only_proposed(self) -> None:
        """A higher-value extra changes the proposed row, never baseline."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        context, baseline_eval, baseline_table = (
            self._proxy_shadow_fixture(computed))

        def fake_native_eval(
            self_arg: ArmyInterceptorV2,
            eval_context: V2NativeEvalContext,
            candidate: V2InterceptCandidate,
            tile_indices: list[int],
            probe_only: bool = False,
        ) -> V2NativeCandidateEval:
            fake_eval = V2NativeCandidateEval(
                candidate=candidate,
                tile_indices=list(tile_indices),
                move_half_flags=[False] * len(tile_indices),
                entries=[],
                evaluation_continued=True,
                skip_reason='',
                bound_group=None)
            fake_eval.entries.append(V2NativeOptionEntry(
                cur_dist=5,
                this_value=1000.0,
                damage_blocked=500.0,
                enemy_army_left_after_intercept=0,
                best_case_intercept_moves=1,
                worst_case_intercept_moves=1,
                recapture_turns=0,
                required_delay=0,
                friendly_army_reaching_intercept=100,
                candidate_eval=fake_eval))
            return fake_eval

        with mock.patch.object(
            ArmyInterceptorV2,
            '_evaluate_candidate_native',
            fake_native_eval):
            result = compare_route_proxy(
                v2, context, [baseline_eval], baseline_table)
        comparison = result.comparison
        self.assertGreaterEqual(comparison.extra_evaluations, 1)
        self.assertLessEqual(comparison.extra_evaluations, 2)
        self.assertEqual((5,), comparison.changed_rows)
        self.assertFalse(comparison.same_table)
        self.assertFalse(comparison.first_move_same)
        self.assertEqual([5], list(baseline_table))
        self.assertEqual(10.0, baseline_table[5].this_value)
        self.assertEqual(1000.0, result.proposed_table[5].this_value)

    def test_proxy_shadow_rejected_extra_cannot_remove_baseline(self) -> None:
        """A rejected extra eval cannot block or remove baseline rows."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        context, baseline_eval, baseline_table = (
            self._proxy_shadow_fixture(computed))

        def fake_native_eval(
            self_arg: ArmyInterceptorV2,
            eval_context: V2NativeEvalContext,
            candidate: V2InterceptCandidate,
            tile_indices: list[int],
            probe_only: bool = False,
        ) -> V2NativeCandidateEval:
            return V2NativeCandidateEval(
                candidate=candidate,
                tile_indices=list(tile_indices),
                move_half_flags=[False] * len(tile_indices),
                entries=[],
                evaluation_continued=False,
                skip_reason='rejected',
                bound_group=None)

        with mock.patch.object(
            ArmyInterceptorV2,
            '_evaluate_candidate_native',
            fake_native_eval):
            result = compare_route_proxy(
                v2, context, [baseline_eval], baseline_table)
        comparison = result.comparison
        self.assertTrue(comparison.same_table)
        self.assertEqual((), comparison.changed_rows)
        self.assertTrue(comparison.first_move_same)
        self.assertEqual([5], list(result.proposed_table))
        self.assertEqual(10.0, result.proposed_table[5].this_value)
        self.assertIs(result.proposed_evals[0], baseline_eval)
        self.assertEqual(
            1 + comparison.extra_evaluations,
            len(result.proposed_evals))

    def test_proxy_shadow_empty_candidates_returns_empty(self) -> None:
        """No candidates: empty table and an empty shadow comparison."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        v2.proxy_shadow_enabled = True
        v2.preselection_enabled = False
        table = self._run_native_eval(computed, candidates=[])
        self.assertEqual({}, table)
        shadow = v2.last_proxy_shadow
        self.assertIsNotNone(shadow)
        self.assertEqual({}, shadow.proposed_table)
        self.assertEqual(0, shadow.comparison.extra_evaluations)
        self.assertTrue(shadow.comparison.same_table)

    def test_proxy_shadow_stale_result_cleared_on_empty_get(self) -> None:
        """get_intercept_plan_options clears a stale shadow result first."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        v2.proxy_shadow_enabled = True
        v2.preselection_enabled = False
        self._run_native_eval(computed)
        self.assertIsNotNone(v2.last_proxy_shadow)
        computed.v1_plan.common_intercept_chokes.clear()
        result = v2.get_intercept_plan_options(
            computed.v1_plan,
            computed.turns_left_in_cycle,
            self._native_opponent_tracker(computed),
            None)
        self.assertEqual({}, result)
        self.assertIsNone(v2.last_proxy_shadow)

    def test_preselection_explicit_opt_out_not_called(self) -> None:
        """Explicit opt-out: exhaustive scorer runs; preselection skipped."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        self.assertTrue(v2.preselection_enabled)
        v2.preselection_enabled = False
        self.assertIsNone(v2.last_preselection)
        bound_calls: list[V2NativeEvalContext] = []
        real_build_bound = ArmyInterceptorV2._build_bound_context

        def spy_build_bound(
            self_arg: ArmyInterceptorV2,
            eval_context: V2NativeEvalContext,
            friendly_reach: FriendlyMultiSourceMatrix,
        ) -> V2BoundContext:
            """Count exhaustive bound-context construction for the opt-out."""
            bound_calls.append(eval_context)
            return real_build_bound(
                self_arg, eval_context, friendly_reach)

        with mock.patch(
            'Behavior.ArmyInterceptorV2.evaluate_preselected'
        ) as preselect_spy, mock.patch.object(
            ArmyInterceptorV2, '_build_bound_context', spy_build_bound):
            table = self._run_native_eval(computed)
        preselect_spy.assert_not_called()
        self.assertEqual(1, len(bound_calls))
        self.assertIsNone(v2.last_preselection)
        self.assertTrue(table)

    def test_preselection_enabled_by_default_bypasses_bound_context(
        self,
    ) -> None:
        """Default dispatch returns the bounded table without bound groups."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        self.assertTrue(v2.preselection_enabled)
        with mock.patch.object(
                ArmyInterceptorV2, '_build_bound_context') as bound_spy:
            table = self._run_native_eval(computed)
        bound_spy.assert_not_called()
        result = v2.last_preselection
        self.assertIsInstance(result, PreselectionResult)
        self.assertIs(table, result.table)
        self.assertIs(v2.last_native_evals, result.evaluations)
        self.assertLessEqual(result.stats.selected_groups, 6)
        self.assertLessEqual(result.stats.native_evaluations, 12)

    def test_preselection_counts_match_actual_native_evals(self) -> None:
        """Stats record actual native calls, not the input candidate count."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        eval_calls: list[V2InterceptCandidate] = []
        real_eval = ArmyInterceptorV2._evaluate_candidate_native

        def counting_eval(
            self_arg: ArmyInterceptorV2,
            eval_context: V2NativeEvalContext,
            candidate: V2InterceptCandidate,
            tile_indices: list[int],
            probe_only: bool = False,
        ) -> V2NativeCandidateEval:
            """Count each real native evaluation the preselection path makes."""
            eval_calls.append(candidate)
            return real_eval(
                self_arg, eval_context, candidate, tile_indices, probe_only)

        with mock.patch.object(
                ArmyInterceptorV2,
                '_evaluate_candidate_native',
                counting_eval):
            self._run_native_eval(computed)
        result = v2.last_preselection
        self.assertIsNotNone(result)
        stats = result.stats
        self.assertEqual(len(computed.candidates), stats.candidates)
        self.assertLessEqual(stats.selected_groups, 6)
        self.assertLessEqual(stats.native_evaluations, 12)
        self.assertEqual(len(eval_calls), stats.native_evaluations)
        self.assertEqual(stats.scored_groups, len(v2.last_native_evals))
        self.assertLessEqual(stats.scored_groups, stats.selected_groups)
        self.assertIs(v2.last_native_evals, result.evaluations)

    def test_preselection_empty_candidates_returns_empty(self) -> None:
        """No candidates: empty table, empty evals, zeroed stats."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        table = self._run_native_eval(computed, candidates=[])
        self.assertEqual({}, table)
        result = v2.last_preselection
        self.assertIsNotNone(result)
        self.assertEqual({}, result.table)
        self.assertEqual([], result.evaluations)
        stats = result.stats
        self.assertEqual(0, stats.candidates)
        self.assertEqual(0, stats.eligible_groups)
        self.assertEqual(0, stats.selected_groups)
        self.assertEqual(0, stats.scored_groups)
        self.assertEqual(0, stats.native_evaluations)
        self.assertEqual([], v2.last_native_evals)
        self.assertIs(v2.last_native_evals, result.evaluations)

    def test_preselection_stale_result_cleared_on_empty_get(self) -> None:
        """get_intercept_plan_options clears a stale preselection result."""
        computed = self._load_proxy_scenario()
        v2 = computed.interceptor.v2
        self._run_native_eval(computed)
        self.assertIsNotNone(v2.last_preselection)
        computed.v1_plan.common_intercept_chokes.clear()
        result = v2.get_intercept_plan_options(
            computed.v1_plan,
            computed.turns_left_in_cycle,
            self._native_opponent_tracker(computed),
            None)
        self.assertEqual({}, result)
        self.assertIsNone(v2.last_preselection)

    def test_select_preselection_groups_preserves_coverage_and_order(
        self,
    ) -> None:
        """Synthetic groups keep top V/T, earliest, max blocked, diversity."""
        computed = self._load_proxy_scenario()
        winner = computed.candidates[0]
        specs = [
            (1.00, 5.0, 10, (100, 1)),
            (0.90, 1.0, 2, (200, 2)),
            (0.80, 50.0, 9, (300, 3)),
            (0.70, 4.0, 5, (100, 1)),
            (0.60, 3.0, 6, (400, 4)),
            (0.50, 2.0, 7, (500, 5)),
            (0.40, 1.0, 8, (600, 6)),
            (0.30, 0.0, 11, (700, 7)),
        ]
        groups = [
            PreselectionGroup(
                winner=winner,
                alternatives=[],
                route=(route[0], route[1], route[0] + 1),
                v1_order=index,
                estimated_turns=turns,
                estimated_blocked=blocked,
                estimated_value_per_turn=value_per_turn)
            for index, (
                value_per_turn, blocked, turns, route) in enumerate(specs)]
        selected = select_preselection_groups(groups)
        self.assertEqual(6, len(selected))
        self.assertEqual(
            [0, 1, 2, 4, 5, 6],
            [group.v1_order for group in selected])
        selected_orders = {
            group.v1_order for group in selected}
        self.assertIn(0, selected_orders)
        self.assertIn(1, selected_orders)
        self.assertIn(2, selected_orders)
        self.assertNotIn(3, selected_orders)
        self.assertNotIn(7, selected_orders)

    def _friendly_wave_signature(
        self,
        friendly_reach: FriendlyMultiSourceMatrix,
        v2: ArmyInterceptorV2,
    ) -> tuple:
        """Canonical kept/alternate wave contents for cache comparison."""
        def state_signature(
            state: V2WaveState,
        ) -> tuple[int, int, int, int, int, tuple[int, ...]]:
            return (
                state.tile_index,
                state.depth,
                state.source_index,
                state.net_army,
                state.cap_points,
                tuple(v2._state_tile_indices(state)))

        states_signature = tuple(
            (
                depth,
                tile_index,
                tuple(state_signature(state) for state in states))
            for depth, slots in enumerate(friendly_reach.states_by_depth)
            for tile_index, states in sorted(slots.items()))
        alternates_signature = tuple(
            (
                depth,
                tile_index,
                tuple(state_signature(state) for state in states))
            for depth, slots in enumerate(
                friendly_reach.alternates_by_depth)
            for tile_index, states in sorted(slots.items()))
        return (
            states_signature,
            alternates_signature,
            tuple(friendly_reach.selected_source_indices))

    def _compute_v2_wave_inputs(
        self,
        scenario: ArmyInterceptionV2Scenario,
        require_single_kill_threat: bool = False,
    ) -> ArmyInterceptionV2WaveInputs:
        """Build the V1 plan and V2 wave inputs without scoring options."""
        turns_left_in_cycle = 50 - scenario.map.turn % 50
        self.use_v2_interception = False
        v1_plan = self.get_interception_plan(
            scenario.map,
            scenario.general,
            scenario.enemy_general,
            enTile=scenario.enemy_tile,
            turnsLeftInCycle=turns_left_in_cycle,
            useDebugLogging=False)
        self.assertIsNotNone(v1_plan)
        if require_single_kill_threat:
            self.assertEqual(1, len(v1_plan.threat_values))
            self.assertEqual(
                ThreatType.Kill,
                v1_plan.threat_values[0].threat.threatType)

        best_v1_damage_blocked = max(
            (
                option.damage_blocked
                for option in v1_plan.intercept_options.values()
            ),
            default=0.0)

        self.use_v2_interception = True
        v2_interceptor = self.get_interceptor(
            scenario.map,
            scenario.general,
            scenario.enemy_general,
            useDebugLogging=False)
        max_depth = v2_interceptor._get_max_interception_search_depth(
            v1_plan.threats)
        allowed_search_region = (
            v2_interceptor.v2.build_allowed_search_region(v1_plan))
        choke_search_depths = (
            v2_interceptor.v2.resolve_choke_search_depths(
                v1_plan,
                v1_plan.middlest_intercept_tiles,
                False))
        threat_reach = v2_interceptor.v2.build_threat_reach_matrix(
            v1_plan,
            max_depth,
            turns_left_in_cycle,
            choke_search_depths,
            allowed_search_region)
        positions_by_turn = (
            v2_interceptor._build_average_enemy_position_by_turn(
                v1_plan,
                max_depth))
        friendly_reach = v2_interceptor.v2.build_friendly_multi_source_matrix(
            v1_plan,
            threat_reach,
            choke_search_depths,
            positions_by_turn)
        candidates = v2_interceptor.v2.build_intercept_candidates(
            v1_plan,
            threat_reach,
            friendly_reach,
            turns_left_in_cycle,
            choke_search_depths)
        candidate_paths = (
            v2_interceptor.v2.reconstruct_candidate_paths(
                threat_reach,
                friendly_reach,
                candidates))
        return ArmyInterceptionV2WaveInputs(
            scenario=scenario,
            turns_left_in_cycle=turns_left_in_cycle,
            v1_plan=v1_plan,
            best_v1_damage_blocked=best_v1_damage_blocked,
            interceptor=v2_interceptor,
            max_depth=max_depth,
            allowed_search_region=allowed_search_region,
            choke_search_depths=choke_search_depths,
            threat_reach=threat_reach,
            positions_by_turn=positions_by_turn,
            friendly_reach=friendly_reach,
            candidates=candidates,
            candidate_paths=candidate_paths)

    def _assert_v2_scenario_invariants(
        self,
        scenario: ArmyInterceptionV2Scenario,
        require_single_kill_threat: bool = False,
    ) -> None:
        """Compare V1 and V2 plans and validate each V2 search stage."""
        computed = self._compute_v2_wave_inputs(
            scenario,
            require_single_kill_threat)
        self.use_v2_interception = True
        v2_plan = self.get_interception_plan(
            scenario.map,
            scenario.general,
            scenario.enemy_general,
            enTile=scenario.enemy_tile,
            turnsLeftInCycle=computed.turns_left_in_cycle,
            useDebugLogging=False)
        self.assertIsNotNone(v2_plan)
        self.assertTrue(v2_plan.intercept_options)
        best_v1_damage_blocked = computed.best_v1_damage_blocked

        for option in v2_plan.intercept_options.values():
            self.assertTrue(
                scenario.map.is_tile_friendly(option.path.start.tile))
            self.assertIn(
                option.path.tail.tile,
                v2_plan.common_intercept_chokes)
        self.assertGreaterEqual(
            max(
                option.damage_blocked
                for option in v2_plan.intercept_options.values()),
            best_v1_damage_blocked)

        v2_interceptor = computed.interceptor
        v1_plan = computed.v1_plan
        turns_left_in_cycle = computed.turns_left_in_cycle
        max_depth = computed.max_depth
        allowed_search_region = computed.allowed_search_region
        choke_search_depths = computed.choke_search_depths
        threat_reach = computed.threat_reach
        positions_by_turn = computed.positions_by_turn
        friendly_reach = computed.friendly_reach
        candidates = computed.candidates
        candidate_paths = computed.candidate_paths
        self.assertTrue(candidate_paths)
        default_interceptor = ArmyInterceptor(
            scenario.map,
            v2_interceptor.board_analysis,
            useDebugLogging=False)
        self.assertTrue(default_interceptor.use_v2_interception)
        explicit_v1_interceptor = ArmyInterceptor(
            scenario.map,
            v2_interceptor.board_analysis,
            useDebugLogging=False,
            useV2Interception=False)
        self.assertFalse(explicit_v1_interceptor.use_v2_interception)

        for source in threat_reach.candidate_sources:
            self.assertTrue(scenario.map.is_tile_friendly(source))
            self.assertGreaterEqual(source.army, 2)

        for source_index in friendly_reach.selected_source_indices:
            source = friendly_reach.candidate_sources[source_index]
            self.assertGreaterEqual(
                threat_reach.choke_budget.budget[source.tile_index],
                0)

        # Wave state invariants: every kept (tile, depth) slot holds at
        # most one state per source (per-source retention mirrors V1's
        # independent per-source searches — a global top-K starved weak
        # chains), ordered by strongest army-at-arrival first; every
        # state lives inside the choke budget frontier (which also
        # confines it to V1's funnel union region since the budget
        # matrix is only nonzero there); and every state's parent chain
        # walks depth links down to a depth-0 source seed without
        # revisiting a tile.
        source_tile_indexes = {
            source.tile_index
            for source in friendly_reach.candidate_sources}
        states_by_depth = friendly_reach.states_by_depth
        self.assertLessEqual(len(states_by_depth), max_depth + 1)
        for depth, slot_states in enumerate(states_by_depth):
            for tile_index, states in slot_states.items():
                self.assertLessEqual(
                    len(states),
                    len(friendly_reach.candidate_sources))
                self.assertEqual(
                    len({state.source_index for state in states}),
                    len(states))
                self.assertGreaterEqual(
                    threat_reach.choke_budget.budget[tile_index],
                    depth)
                self.assertTrue(
                    allowed_search_region[tile_index],
                    f'state outside allowed region at '
                    f'{scenario.map.get_tile_by_tile_index(tile_index)}')
                for state_index, wave_state in enumerate(states):
                    self.assertEqual(tile_index, wave_state.tile_index)
                    self.assertEqual(depth, wave_state.depth)
                    if state_index > 0:
                        self.assertGreaterEqual(
                            states[state_index - 1].net_army,
                            wave_state.net_army)
                    chain_indices: set[int] = set()
                    cursor = wave_state
                    chain_depth = depth
                    while cursor is not None:
                        self.assertEqual(chain_depth, cursor.depth)
                        self.assertNotIn(
                            cursor.tile_index,
                            chain_indices)
                        chain_indices.add(cursor.tile_index)
                        self.assertIn(
                            cursor,
                            states_by_depth[chain_depth][
                                cursor.tile_index])
                        self.assertEqual(
                            wave_state.source_index,
                            cursor.source_index)
                        if cursor.parent_state is None:
                            # The chain terminates at a depth-0 seed on
                            # its own source's tile.
                            self.assertEqual(0, cursor.depth)
                            self.assertIn(
                                cursor.tile_index,
                                source_tile_indexes)
                            self.assertEqual(
                                friendly_reach.candidate_sources[
                                    wave_state.source_index
                                ].tile_index,
                                cursor.tile_index)
                        cursor = cursor.parent_state
                        chain_depth -= 1
                    self.assertEqual(-1, chain_depth)
                    self.assertIn(
                        wave_state.source_index,
                        range(len(friendly_reach.candidate_sources)))

        # Selected sources are exactly those with at least one
        # candidate-admissible kept state at a searched choke, and every
        # emitted candidate's source is selected.
        candidate_sources_seen = {
            candidate.source_index
            for candidate in candidates}
        self.assertTrue(
            candidate_sources_seen
            <= set(friendly_reach.selected_source_indices))
        for choke_tile, search_depth in choke_search_depths.items():
            choke_index = choke_tile.tile_index
            for depth in range(
                1,
                min(
                    search_depth,
                    max_depth,
                    len(states_by_depth) - 1) + 1):
                for wave_state in states_by_depth[depth].get(
                    choke_index,
                    []):
                    self.assertIn(
                        wave_state.source_index,
                        friendly_reach.selected_source_indices)

        # Every retained state at each common intercept choke produces
        # exactly one candidate (the wave's per-source claim gives each
        # source at most one state per choke, always at its minimum
        # surviving depth).
        choke_state_pairs = {
            (wave_state.source_index, wave_state.depth)
            for choke_tile in choke_search_depths
            for depth in range(
                1,
                min(
                    choke_search_depths[choke_tile],
                    max_depth,
                    len(states_by_depth) - 1) + 1)
            for wave_state in states_by_depth[depth].get(
                choke_tile.tile_index,
                [])}
        candidate_pairs = {
            (candidate.source_index, candidate.depth)
            for candidate in candidates}
        self.assertEqual(choke_state_pairs, candidate_pairs)

        for candidate in candidates:
            intercept_info = v1_plan.common_intercept_chokes[
                candidate.choke_tile]
            limit = min(intercept_info.max_delay_turns, max_depth)
            self.assertLessEqual(candidate.depth, limit)

        self._assert_threat_reach_distances(
            scenario.map,
            v1_plan.target_tile,
            threat_reach.enemy_turn,
            max_depth)
        self._assert_candidate_path_invariants(
            scenario,
            v1_plan,
            threat_reach,
            friendly_reach,
            candidate_paths)

    def _assert_threat_reach_distances(
        self,
        map: MapBase,
        target_tile: Tile,
        enemy_turn: list[int],
        max_depth: int,
    ) -> None:
        """Compare threat BFS distances except where a neutral-city detour applies."""
        distance_matrix = map.distance_mapper.get_tile_dist_matrix(
            target_tile).raw
        neutral_allowed_distances = self._get_distances(
            map,
            target_tile,
            allow_neutral_cities=True)
        tile_count = len(enemy_turn)
        for tile_index in range(tile_count):
            matrix_distance = distance_matrix[tile_index]
            if (
                matrix_distance > max_depth
                or matrix_distance >= 1000
                or enemy_turn[tile_index] == -1
            ):
                continue
            if enemy_turn[tile_index] == matrix_distance:
                continue
            has_neutral_city_detour = (
                neutral_allowed_distances[tile_index] == matrix_distance
                and matrix_distance < enemy_turn[tile_index])
            self.assertTrue(
                has_neutral_city_detour,
                f'threat turn {enemy_turn[tile_index]} != map distance '
                f'{matrix_distance} at tile {map.get_tile_by_tile_index(tile_index)}')

    def _get_distances(
        self,
        map: MapBase,
        start_tile: Tile,
        allow_neutral_cities: bool,
    ) -> list[int]:
        """Build a test-only shortest-distance map with optional neutral cities."""
        tiles = list(map.get_all_tiles())
        distances = [-1] * len(tiles)
        start_index = start_tile.tile_index
        distances[start_index] = 0
        frontier: deque[int] = deque([start_index])
        while frontier:
            tile_index = frontier.popleft()
            current_tile = tiles[tile_index]
            for next_tile in current_tile.movable:
                if next_tile.isObstacle:
                    continue
                if (
                    not allow_neutral_cities
                    and next_tile.isCity
                    and next_tile.isNeutral
                ):
                    continue
                next_index = next_tile.tile_index
                if distances[next_index] != -1:
                    continue
                distances[next_index] = distances[tile_index] + 1
                frontier.append(next_index)
        return distances

    def _assert_candidate_path_invariants(
        self,
        scenario: ArmyInterceptionV2Scenario,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        candidate_paths: list[V2CandidatePath],
    ) -> None:
        """Validate candidate paths and their stored wave army values."""
        for candidate_path in candidate_paths:
            candidate = candidate_path.candidate
            source = friendly_reach.candidate_sources[
                candidate.source_index]
            path_tiles = candidate_path.path.tileList
            self.assertEqual(source, path_tiles[0])
            self.assertEqual(candidate.choke_tile, path_tiles[-1])
            self.assertEqual(
                len(path_tiles),
                len({tile.tile_index for tile in path_tiles}))
            for previous_tile, next_tile in zip(
                path_tiles,
                path_tiles[1:]):
                self.assertIn(next_tile, previous_tile.movable)
            self.assertIn(
                candidate.choke_tile,
                interception.common_intercept_chokes)

            # Wave net_army mirrors V1's prioFunc walk exactly: +(army-1)
            # per friendly-team node and -(army+1) per enemy node over
            # every path node except the choke itself (the departing-tile
            # accumulation includes the source but not the endpoint).
            friendly_army = 0
            for tile in path_tiles[:-1]:
                if scenario.map.is_tile_on_team_with(
                    tile,
                    scenario.map.player_index):
                    friendly_army += tile.army - 1
                else:
                    friendly_army -= tile.army + 1
            self.assertEqual(
                candidate_path.friendly_army_at_choke,
                friendly_army)
            wave_state = candidate.wave_state
            self.assertIsNotNone(wave_state)
            slot_states = friendly_reach.states_by_depth[
                candidate.depth][candidate.choke_tile.tile_index]
            self.assertIn(wave_state, slot_states)
            self.assertEqual(
                candidate_path.friendly_army_at_choke,
                wave_state.net_army)
