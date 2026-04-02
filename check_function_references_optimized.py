#!/usr/bin/env python3
"""
Optimized script to check and fix function references using the parsed mappings.
"""

import os
import re
from pathlib import Path

def load_function_mappings():
    """Load function mappings from the parsed file."""
    mappings = {}
    
    with open('function_mappings.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Skip header
    for line in lines[1:]:
        if line.strip():
            parts = line.strip().split(',')
            if len(parts) >= 3:
                func_name = parts[0]
                module_name = parts[1]
                target_function = parts[2]
                mappings[func_name] = {
                    'module': module_name,
                    'target': target_function
                }
    
    return mappings

def check_references_fast():
    """Fast check for unresolved references."""
    mappings = load_function_mappings()
    
    # Focus on key files first (bot_ek0x45.py and BotModules)
    key_files = [
        'bot_ek0x45.py',
        'BotModules/'
    ]
    
    issues_found = []
    
    # Check bot_ek0x45.py first (most likely to have issues)
    bot_file = Path('bot_ek0x45.py')
    if bot_file.exists():
        print(f"Checking {bot_file}...")
        issues = check_file(bot_file, mappings)
        issues_found.extend(issues)
    
    # Check BotModules directory
    botmodules_dir = Path('BotModules')
    if botmodules_dir.exists():
        print(f"Checking BotModules directory...")
        for py_file in botmodules_dir.glob('*.py'):
            print(f"  Checking {py_file.name}...")
            issues = check_file(py_file, mappings)
            issues_found.extend(issues)
    
    return issues_found

def check_file(file_path, mappings):
    """Check a single file for unresolved references."""
    issues_found = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
            
            for line_num, line in enumerate(lines, 1):
                # Skip lines that are already correct
                if 'return ' in line and any(module in line for module in ['BotRepetition', 'BotDefense', 'BotCityOps', 'BotExpansionOps', 'BotCombatOps', 'BotGatherOps', 'BotPathingUtils', 'BotTargeting', 'BotTimings', 'BotStateQueries', 'BotRendering', 'BotComms', 'BotEventHandlers', 'BotLifecycle', 'BotSerialization']):
                    continue
                
                # Look for self.function_name( patterns
                for func_name, mapping in mappings.items():
                    pattern = rf'self\.{re.escape(func_name)}\('
                    if re.search(pattern, line):
                        issues_found.append({
                            'file': str(file_path),
                            'line': line_num,
                            'content': line.strip(),
                            'function': func_name,
                            'module': mapping['module'],
                            'target': mapping['target'],
                            'suggested_fix': f"{mapping['module']}.{mapping['target']}(self"
                        })
                
                # Look for bot.function_name( patterns
                for func_name, mapping in mappings.items():
                    pattern = rf'bot\.{re.escape(func_name)}\('
                    if re.search(pattern, line):
                        issues_found.append({
                            'file': str(file_path),
                            'line': line_num,
                            'content': line.strip(),
                            'function': func_name,
                            'module': mapping['module'],
                            'target': mapping['target'],
                            'suggested_fix': f"{mapping['module']}.{mapping['target']}(bot"
                        })
    
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    
    return issues_found

def main():
    print("🔍 Checking function references...")
    issues = check_references_fast()
    
    if issues:
        print(f"\n❌ Found {len(issues)} unresolved references:")
        print("=" * 100)
        
        # Group by file for easier fixing
        by_file = {}
        for issue in issues:
            file_path = issue['file']
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(issue)
        
        for file_path, file_issues in sorted(by_file.items()):
            print(f"\n📁 {file_path} ({len(file_issues)} issues):")
            for issue in file_issues:
                print(f"   Line {issue['line']}: {issue['content']}")
                print(f"   Function: {issue['function']} -> {issue['suggested_fix']}(...)")
                print()
        
        print(f"🔧 Total issues to fix: {len(issues)}")
        
        # Generate fix commands
        print(f"\n🛠️  Suggested fixes:")
        for file_path, file_issues in sorted(by_file.items()):
            print(f"\n# Fix {file_path}:")
            for issue in file_issues[:5]:  # Show first 5 per file
                old_pattern = f"self.{issue['function']}("
                new_pattern = f"{issue['module']}.{issue['target']}(self"
                print(f"# Replace: {old_pattern} -> {new_pattern}")
            if len(file_issues) > 5:
                print(f"# ... and {len(file_issues) - 5} more")
                
    else:
        print("✅ All function references have been properly updated!")

if __name__ == "__main__":
    main()
