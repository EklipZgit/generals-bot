import argparse
import importlib
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path(r'D:\2019_reformat_Backup\cascade-debug-output\generals-bot')


def _discover_test_methods(target: str) -> list[str]:
    module_name = target
    class_name = None
    if '.' in target:
        possible_module, possible_class = target.rsplit('.', 1)
        try:
            module = importlib.import_module(possible_module)
            test_class = getattr(module, possible_class)
            return sorted(
                name
                for name, value in inspect.getmembers(test_class)
                if name.startswith('test_') and callable(value)
            )
        except (ImportError, AttributeError):
            module_name = target
    module = importlib.import_module(module_name)
    test_methods: list[str] = []
    for _, value in inspect.getmembers(module, inspect.isclass):
        for name, method in inspect.getmembers(value):
            if name.startswith('test_') and callable(method):
                test_methods.append(name)
    return sorted(set(test_methods))


def _parse_failure_statuses(raw_output: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for kind, name in re.findall(r'^(FAIL|ERROR):\s+([^\s]+)\s+\(', raw_output, re.MULTILINE):
        results[name] = kind
    return results


def _write_summary(raw_path: Path, summary_path: Path, target: str, return_code: int) -> None:
    raw_output = raw_path.read_text(errors='replace')
    discovered_tests = _discover_test_methods(target)
    failure_statuses = _parse_failure_statuses(raw_output)

    results: dict[str, str] = {}
    for name in discovered_tests:
        results[name] = failure_statuses.get(name, 'PASS')

    for name, status in failure_statuses.items():
        if name not in results:
            results[name] = status

    pass_count = sum(1 for status in results.values() if status == 'PASS')
    fail_count = sum(1 for status in results.values() if status == 'FAIL')
    error_count = sum(1 for status in results.values() if status == 'ERROR')

    lines: list[str] = []
    lines.append(f'TARGET={target}')
    lines.append(f'RAW_OUTPUT={raw_path}')
    lines.append(f'RETURN_CODE={return_code}')
    lines.append(f'TOTAL_DISCOVERED={len(results)}')
    lines.append(f'PASS_COUNT={pass_count}')
    lines.append(f'FAIL_COUNT={fail_count}')
    lines.append(f'ERROR_COUNT={error_count}')
    lines.append('')
    lines.append('RESULTS:')
    for name in sorted(results):
        lines.append(f'{results[name]}\t{name}')

    lines.append('')
    lines.append('FAILING_OR_ERROR_TESTS:')
    for name in sorted(results):
        if results[name] in {'FAIL', 'ERROR'}:
            lines.append(f'{results[name]}\t{name}')

    summary_path.write_text('\n'.join(lines) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument('--summary-path', default=None)
    parser.add_argument('--python-exe', default=sys.executable)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f'{args.name}_raw.txt'
    summary_path = Path(args.summary_path) if args.summary_path is not None else output_dir / f'{args.name}_summary.txt'
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    repo_root = Path.cwd()
    tests_path = repo_root / 'Tests'
    existing_pythonpath = env.get('PYTHONPATH')
    pythonpath_entries = [str(tests_path), str(repo_root)]
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    env['PYTHONPATH'] = os.pathsep.join(pythonpath_entries)
    env['bypass_ui'] = 'True'

    command = [args.python_exe, '-m', 'unittest', '-v', args.target]
    with raw_path.open('w', encoding='utf-8', errors='replace') as raw_file:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=env,
            stdout=raw_file,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    _write_summary(raw_path, summary_path, args.target, completed.returncode)
    print(f'RAW_OUTPUT={raw_path}')
    print(f'SUMMARY={summary_path}')
    print(f'RETURN_CODE={completed.returncode}')
    return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())
