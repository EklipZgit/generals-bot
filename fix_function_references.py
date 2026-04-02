#!/usr/bin/env python3
"""
Automated script to fix function references using the parsed mappings.
"""

import re
from pathlib import Path

def load_function_mappings():
    """Load function mappings from the parsed file."""
    mappings = {}

    with open('function_mappings.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines[1:]:  # Skip header
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

def fix_file(file_path, mappings):
    """Fix all function references in a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        changes_made = 0

        # Fix self.function_name( -> Module.function_name(self,
        for func_name, mapping in mappings.items():
            pattern = rf'self\.{re.escape(func_name)}\('
            replacement = f"{mapping['module']}.{mapping['target']}(self, "

            matches = re.findall(pattern, content)
            if matches:
                content = re.sub(pattern, replacement, content)
                changes_made += len(matches)
                print(f"  Fixed {len(matches)} instances of self.{func_name}(")

        # Fix bot.function_name( -> Module.function_name(bot,
        for func_name, mapping in mappings.items():
            pattern = rf'bot\.{re.escape(func_name)}\('
            replacement = f"{mapping['module']}.{mapping['target']}(bot, "

            matches = re.findall(pattern, content)
            if matches:
                content = re.sub(pattern, replacement, content)
                changes_made += len(matches)
                print(f"  Fixed {len(matches)} instances of bot.{func_name}(")

        # Only write if changes were made
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return changes_made
        else:
            return 0

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return 0

def main():
    print("🔧 Fixing function references automatically...")
    mappings = load_function_mappings()
    print(f"Loaded {len(mappings)} function mappings")

    total_changes = 0

    # Fix bot_ek0x45.py first
    bot_file = Path('bot_ek0x45.py')
    if bot_file.exists():
        print(f"\n📁 Fixing {bot_file}...")
        changes = fix_file(bot_file, mappings)
        total_changes += changes
        if changes > 0:
            print(f"   ✅ Fixed {changes} references")

    # Fix BotModules directory
    botmodules_dir = Path('BotModules')
    if botmodules_dir.exists():
        print(f"\n📁 Fixing BotModules directory...")
        for py_file in sorted(botmodules_dir.glob('*.py')):
            print(f"  📄 {py_file.name}...")
            changes = fix_file(py_file, mappings)
            total_changes += changes
            if changes > 0:
                print(f"     ✅ Fixed {changes} references")

    print(f"\n🎉 Total fixes applied: {total_changes}")

    if total_changes > 0:
        print("\n✅ All function references have been updated!")
        print("💡 You may want to run the test again to see if it passes now.")
    else:
        print("\nℹ️  No changes were needed.")

if __name__ == "__main__":
    main()
