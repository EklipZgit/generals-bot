#!/usr/bin/env python3
"""
Script to check that all references to removed functions have been updated to use BotModules static methods.
"""

import os
import re
from pathlib import Path

# Read the list of removed functions
with open('removed_functions_clean.txt', 'r') as f:
    removed_functions = [line.strip() for line in f if line.strip()]

print(f"Checking {len(removed_functions)} removed functions...")

# Common patterns to look for
patterns = [
    r'self\.({func})\(',  # self.function_name(
    r'bot\.({func})\(',   # bot.function_name(
    r'\.({func})\(',     # .function_name(
]

# Files to check (exclude __pycache__ and test files for now)
def check_files():
    root_dir = Path('.')
    issues_found = []

    for py_file in root_dir.rglob('*.py'):
        # Skip __pycache__, .git, and test files for initial check
        if any(skip in str(py_file) for skip in ['__pycache__', '.git', '.venv']):
            continue

        print(f"File: {py_file}")
        # continue

        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')

                for line_num, line in enumerate(lines, 1):
                    for func in removed_functions:
                        for pattern in patterns:
                            matches = re.finditer(pattern.format(func=func), line)
                            for match in matches:
                                issues_found.append({
                                    'file': str(py_file),
                                    'line': line_num,
                                    'content': line.strip(),
                                    'function': func,
                                    'match': match.group(0)
                                })
        except Exception as e:
            print(f"Error reading {py_file}: {e}")

    return issues_found

def main():
    issues = check_files()

    if issues:
        print(f"\n❌ Found {len(issues)} unresolved references:")
        print("=" * 80)

        for issue in issues:
            print(f"\n📁 {issue['file']}")
            print(f"   Line {issue['line']}: {issue['content']}")
            print(f"   Function: {issue['function']}")
            print(f"   Match: {issue['match']}")

        print(f"\n🔧 Total issues to fix: {len(issues)}")

        # Group by function for easier fixing
        by_function = {}
        for issue in issues:
            func = issue['function']
            if func not in by_function:
                by_function[func] = []
            by_function[func].append(issue)

        print(f"\n📊 Issues by function:")
        for func, func_issues in sorted(by_function.items()):
            print(f"   {func}: {len(func_issues)} issues")

    else:
        print("✅ All function references have been properly updated!")

if __name__ == "__main__":
    main()
