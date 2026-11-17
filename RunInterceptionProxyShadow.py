"""Controlled test-only interception proxy experiment; never a live launcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path[0:0] = [str(ROOT), str(ROOT / 'Tests')]
os.environ['bypass_ui'] = 'True'
os.environ['PYTHONPATH'] = os.pathsep.join((str(ROOT), str(ROOT / 'Tests')))

from Behavior.ArmyInterceptionProxy import ProxyComparison
from Behavior.ArmyInterceptorV2 import (
    ArmyInterceptorV2,
    ArmyInterceptorV1Protocol,
    V2NativeOptionEntry,
    V2_SKIP_V1_WINNER_REEVAL,
    V2_USE_V1_EXACT_SEARCH,
)
from base.client.map import MapBase


@dataclass(slots=True)
class ProxyCallRecord:
    """One diagnostic native-table comparison associated with its test."""

    test_id: str
    call_index: int
    comparison: ProxyComparison


@dataclass(slots=True)
class ExperimentState:
    """Run-local test identity, statuses, and captured diagnostics."""

    mode: str
    current_test: str = ''
    statuses: dict[str, str] = field(default_factory=dict)
    calls: list[ProxyCallRecord] = field(default_factory=list)


class ExperimentResult(unittest.TextTestResult):
    """Record method-level outcomes without losing failed subtests."""

    __slots__ = ('state',)

    def __init__(
        self,
        stream: Any,
        descriptions: bool,
        verbosity: int,
        state: ExperimentState,
    ) -> None:
        """Bind outcome recording to the isolated experiment process."""
        super().__init__(stream, descriptions, verbosity)
        self.state = state

    def startTest(self, test: unittest.TestCase) -> None:
        """Use stable tile ordering in both arms, not randomized island IDs."""
        self.state.current_test = test.id()
        MapBase.DO_NOT_RANDOMIZE = True
        super().startTest(test)

    def addSuccess(self, test: unittest.TestCase) -> None:
        """Record success only if no failed subtest already set a failure."""
        self.state.statuses.setdefault(test.id(), 'PASS')
        super().addSuccess(test)

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        """Record an assertion failure under its containing method."""
        if self.state.statuses.get(test.id()) != 'ERROR':
            self.state.statuses[test.id()] = 'FAIL'
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        """Preserve runtime errors as errors, never as an ordinary failure."""
        self.state.statuses[test.id()] = 'ERROR'
        super().addError(test, err)

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        """Keep skipped tests distinct from behavioral passes."""
        self.state.statuses.setdefault(test.id(), 'SKIP')
        super().addSkip(test, reason)

    def addSubTest(
        self,
        test: unittest.TestCase,
        subtest: unittest.TestCase,
        err: Any | None,
    ) -> None:
        """Fold all failed sub-scenarios into the containing method status."""
        if err is not None:
            status = (
                'FAIL' if issubclass(err[0], test.failureException) else 'ERROR')
            if self.state.statuses.get(test.id()) != 'ERROR':
                self.state.statuses[test.id()] = status
        super().addSubTest(test, subtest, err)


def source_fingerprints() -> dict[str, str]:
    """Record Python worktree identity so concurrent edits cannot look like gains."""
    files = subprocess.run(
        [
            'git', 'ls-files', '--cached', '--others', '--exclude-standard',
            '--', '*.py',
        ],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(files))
        if (ROOT / name).is_file()
    }


def main() -> int:
    """Run current selection or the proposal in an explicit offline test process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--mode', choices=('baseline', 'shadow', 'proposal'), default='shadow')
    parser.add_argument('--target', action='append', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument(
        '--output-dir', type=Path,
        default=Path(r'C:\cascade-debug-output\generals-bot'))
    args = parser.parse_args()
    assert args.output_dir.is_dir(), 'Create/verify the output directory first'
    assert V2_SKIP_V1_WINNER_REEVAL and not V2_USE_V1_EXACT_SEARCH
    sources_before = source_fingerprints()
    state = ExperimentState(mode=args.mode)
    original_init = ArmyInterceptorV2.__init__
    original_evaluate = ArmyInterceptorV2.evaluate_candidates_native
    original_options = ArmyInterceptorV2.get_intercept_plan_options

    def experiment_init(
        self: ArmyInterceptorV2,
        v1: ArmyInterceptorV1Protocol,
    ) -> None:
        """Enable diagnostics only on instances constructed by this test runner."""
        original_init(self, v1)
        self.preselection_enabled = False
        self.proxy_shadow_enabled = state.mode != 'baseline'

    def experiment_evaluate(
        self: ArmyInterceptorV2,
        *call_args: Any,
        **kwargs: Any,
    ) -> dict[int, V2NativeOptionEntry]:
        """Only the explicit proposal arm substitutes the detached shadow table."""
        baseline = original_evaluate(self, *call_args, **kwargs)
        diagnostic = self.last_proxy_shadow
        if state.mode == 'proposal' and diagnostic is not None:
            self.last_native_evals = list(diagnostic.proposed_evals)
            return dict(diagnostic.proposed_table)
        return baseline

    def experiment_options(
        self: ArmyInterceptorV2, *call_args: Any, **kwargs: Any,
    ) -> Any:
        """Attach diagnostic calls to tests without changing the emitted options."""
        options = original_options(self, *call_args, **kwargs)
        diagnostic = self.last_proxy_shadow
        if diagnostic is not None:
            state.calls.append(ProxyCallRecord(
                test_id=state.current_test,
                call_index=len(state.calls),
                comparison=diagnostic.comparison))
        return options

    def result_factory(
        stream: Any,
        descriptions: bool,
        verbosity: int,
    ) -> ExperimentResult:
        """Construct the normal unittest result with shared experiment records."""
        return ExperimentResult(stream, descriptions, verbosity, state)

    # Only this standalone test process can activate the proposal; production
    # ArmyInterceptorV2 always returns its incumbent table, even in shadow mode.
    with (
        patch.object(ArmyInterceptorV2, '__init__', experiment_init),
        patch.object(
            ArmyInterceptorV2, 'evaluate_candidates_native', experiment_evaluate),
        patch.object(
            ArmyInterceptorV2, 'get_intercept_plan_options', experiment_options),
    ):
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.target)
        result = unittest.TextTestRunner(
            verbosity=2, resultclass=result_factory).run(suite)
    output = {
        'mode': state.mode,
        'targets': args.target,
        'deterministic_tile_order': True,
        'sources_before': sources_before,
        'sources_after': source_fingerprints(),
        'tests_run': result.testsRun,
        'statuses': state.statuses,
        'failures': [
            {'test': test.id(), 'traceback': message}
            for test, message in result.failures],
        'errors': [
            {'test': test.id(), 'traceback': message}
            for test, message in result.errors],
        'calls': [asdict(call) for call in state.calls],
        'interpretation': (
            'best_value_per_turn is a table diagnostic, not the full bot '
            'move selector. Behavioral conclusions require comparing method '
            'assertions across shadow/proposal runs; timing gates remain live.'),
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
