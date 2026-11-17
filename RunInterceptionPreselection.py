"""Offline full-scoring versus bounded-preselection experiment; defaults unchanged."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path[0:0] = [str(ROOT), str(ROOT / 'Tests')]
os.environ['bypass_ui'] = 'True'
os.environ['PYTHONPATH'] = os.pathsep.join((str(ROOT), str(ROOT / 'Tests')))

import logbook

from Behavior.ArmyInterceptionPreselection import PreselectionStats
from Behavior.ArmyInterceptionProxy import (
    ProxyOptionSnapshot,
    _best_value_per_turn,
    _ordered_table,
    _snapshot,
)
from Behavior.ArmyInterceptorV2 import (
    ArmyInterceptorV2,
    ArmyInterceptorV1Protocol,
    V2NativeCandidateEval,
    V2NativeOptionEntry,
    V2_SKIP_V1_WINNER_REEVAL,
    V2_USE_V1_EXACT_SEARCH,
)
from RunInterceptionProxyShadow import (
    ExperimentResult,
    ExperimentState,
    source_fingerprints,
)


@dataclass(slots=True)
class NativeCounts:
    """Count actual collision/economic evaluations, including hidden retries."""

    full: int = 0
    probes: int = 0


@dataclass(slots=True)
class PreselectionComparison:
    """Same-input table/route comparison, separate from behavioral test outcomes."""

    same_table: bool
    missing_keys: tuple[int, ...]
    lower_value_keys: tuple[int, ...]
    higher_value_keys: tuple[int, ...]
    changed_rows: tuple[int, ...]
    baseline_best: ProxyOptionSnapshot | None
    shortlist_best: ProxyOptionSnapshot | None
    same_best_value_per_turn: bool
    same_first_move: bool


@dataclass(slots=True)
class PreselectionCall:
    """One timed native-stage invocation, optionally with an independent shadow."""

    test_id: str
    turn: int
    tiles: int
    mode: str
    baseline_seconds: float | None
    shortlist_seconds: float | None
    baseline_full_evals: int | None
    baseline_probes: int | None
    shortlist_full_evals: int | None
    stats: PreselectionStats | None
    comparison: PreselectionComparison | None
    pipeline_seconds: float = 0.0


def compare_tables(
    baseline: dict[int, V2NativeOptionEntry],
    baseline_evals: list[V2NativeCandidateEval],
    shortlist: dict[int, V2NativeOptionEntry],
    shortlist_evals: list[V2NativeCandidateEval],
) -> PreselectionComparison:
    """Compare complete route/half/score snapshots, not just source and endpoint."""
    before = _ordered_table(baseline, baseline_evals)
    after = _ordered_table(shortlist, shortlist_evals)
    changed = tuple(
        key for key in sorted(set(before) | set(after))
        if (
            (_snapshot(before[key]) if key in before else None)
            != (_snapshot(after[key]) if key in after else None)))
    best_before = _best_value_per_turn(before)
    best_after = _best_value_per_turn(after)
    return PreselectionComparison(
        same_table=not changed and list(before) == list(after),
        missing_keys=tuple(sorted(set(before) - set(after))),
        lower_value_keys=tuple(
            key for key in before
            if key in after and after[key].this_value < before[key].this_value),
        higher_value_keys=tuple(
            key for key in after
            if key in before and after[key].this_value > before[key].this_value),
        changed_rows=changed,
        baseline_best=best_before,
        shortlist_best=best_after,
        same_best_value_per_turn=best_before == best_after,
        same_first_move=(
            (best_before.first_move if best_before is not None else None)
            == (best_after.first_move if best_after is not None else None)))


def fingerprints(manifest: Path | None) -> dict[str, str]:
    """Support a frozen worktree snapshot without creating or staging a git repo."""
    if manifest is None:
        return source_fingerprints()
    names: list[str] = json.loads(manifest.read_text(encoding='utf-8-sig'))
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(names)}


def main() -> int:
    """Enable the replacement only inside this standalone unittest process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--mode', choices=('baseline', 'shadow', 'shortlist'), required=True)
    parser.add_argument('--target', action='append', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--source-manifest', type=Path)
    parser.add_argument(
        '--output-dir', type=Path,
        default=Path(r'C:\cascade-debug-output\generals-bot'))
    args = parser.parse_args()
    assert args.output_dir.is_dir()
    assert V2_SKIP_V1_WINNER_REEVAL and not V2_USE_V1_EXACT_SEARCH
    sources_before = fingerprints(args.source_manifest)
    state = ExperimentState(mode=args.mode)
    counts = NativeCounts()
    records: list[PreselectionCall] = []
    pending: dict[int, PreselectionCall] = {}
    original_init = ArmyInterceptorV2.__init__
    original_evaluate = ArmyInterceptorV2.evaluate_candidates_native
    original_native = ArmyInterceptorV2._evaluate_candidate_native
    original_options = ArmyInterceptorV2.get_intercept_plan_options

    def experiment_init(
        self: ArmyInterceptorV2, v1: ArmyInterceptorV1Protocol,
    ) -> None:
        """Do not enable the earlier additive proxy in this replacement experiment."""
        original_init(self, v1)
        self.preselection_enabled = state.mode == 'shortlist'
        self.proxy_shadow_enabled = False

    def counted_native(
        self: ArmyInterceptorV2, *call_args: Any, **kwargs: Any,
    ) -> V2NativeCandidateEval:
        """Include every full evaluation and continuation probe in measured work."""
        probe = kwargs.get(
            'probe_only', call_args[3] if len(call_args) > 3 else False)
        if probe:
            counts.probes += 1
        else:
            counts.full += 1
        return original_native(self, *call_args, **kwargs)

    def experiment_evaluate(
        self: ArmyInterceptorV2, *call_args: Any, **kwargs: Any,
    ) -> dict[int, V2NativeOptionEntry]:
        """Shadow uses the same inputs; active shortlist never runs the full scorer."""
        full_start, probe_start = counts.full, counts.probes
        started = time.perf_counter()
        table = original_evaluate(self, *call_args, **kwargs)
        elapsed = time.perf_counter() - started
        record = PreselectionCall(
            test_id=state.current_test,
            turn=self.v1.map.turn,
            tiles=len(self.v1.map.tiles_by_index),
            mode=state.mode,
            baseline_seconds=elapsed if state.mode != 'shortlist' else None,
            shortlist_seconds=elapsed if state.mode == 'shortlist' else None,
            baseline_full_evals=(
                counts.full - full_start if state.mode != 'shortlist' else None),
            baseline_probes=(
                counts.probes - probe_start if state.mode != 'shortlist' else None),
            shortlist_full_evals=(
                counts.full - full_start if state.mode == 'shortlist' else None),
            stats=(
                self.last_preselection.stats
                if self.last_preselection is not None else None),
            comparison=None)
        if state.mode == 'shadow':
            incumbent_evals = self.last_native_evals
            incumbent_cache = dict(self.damage_estimate_cache)
            self.preselection_enabled = True
            full_start = counts.full
            started = time.perf_counter()
            shortlist_table = original_evaluate(self, *call_args, **kwargs)
            record.shortlist_seconds = time.perf_counter() - started
            record.shortlist_full_evals = counts.full - full_start
            result = self.last_preselection
            assert result is not None
            record.stats = result.stats
            record.comparison = compare_tables(
                table, incumbent_evals, shortlist_table, self.last_native_evals)
            self.preselection_enabled = False
            self.last_native_evals = incumbent_evals
            self.damage_estimate_cache.clear()
            self.damage_estimate_cache.update(incumbent_cache)
        if record.stats is not None:
            assert record.shortlist_full_evals == record.stats.native_evaluations
            assert record.shortlist_full_evals <= 12
        records.append(record)
        pending[id(self)] = record
        return table

    def experiment_options(
        self: ArmyInterceptorV2, *call_args: Any, **kwargs: Any,
    ) -> Any:
        """Measure complete option generation; structured logging is outside timing."""
        pending.pop(id(self), None)
        started = time.perf_counter()
        options = original_options(self, *call_args, **kwargs)
        elapsed = time.perf_counter() - started
        record = pending.pop(id(self), None)
        if record is not None:
            record.pipeline_seconds = elapsed
            logbook.info(
                'INTERCEPT_PRESELECTION ' + json.dumps(
                    asdict(record), sort_keys=True, separators=(',', ':')))
        return options

    def result_factory(
        stream: Any, descriptions: bool, verbosity: int,
    ) -> ExperimentResult:
        """Reuse the method/subtest-aware result recorder from the earlier runner."""
        return ExperimentResult(stream, descriptions, verbosity, state)

    with (
        patch.object(ArmyInterceptorV2, '__init__', experiment_init),
        patch.object(
            ArmyInterceptorV2, 'evaluate_candidates_native', experiment_evaluate),
        patch.object(
            ArmyInterceptorV2, '_evaluate_candidate_native', counted_native),
        patch.object(
            ArmyInterceptorV2, 'get_intercept_plan_options', experiment_options),
    ):
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.target)
        result = unittest.TextTestRunner(
            verbosity=2, resultclass=result_factory).run(suite)
    output = {
        'mode': args.mode,
        'root': str(ROOT),
        'targets': args.target,
        'tests_run': result.testsRun,
        'statuses': state.statuses,
        'sources_before': sources_before,
        'sources_after': fingerprints(args.source_manifest),
        'calls': [asdict(record) for record in records],
        'failures': [
            {'test': test.id(), 'traceback': message}
            for test, message in result.failures],
        'errors': [
            {'test': test.id(), 'traceback': message}
            for test, message in result.errors],
    }
    (args.output_dir / f'{args.name}.json').write_text(
        json.dumps(output, indent=2), encoding='utf-8')
    (args.output_dir / f'{args.name}_summary.txt').write_text(
        '\n'.join(
            f'{status}\t{name}'
            for name, status in sorted(state.statuses.items())) + '\n',
        encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
