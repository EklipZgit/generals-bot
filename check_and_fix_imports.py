#!/usr/bin/env python3
"""
Script to check and fix missing imports for the BotModules that are now being used.
"""

import re
from pathlib import Path
from collections import defaultdict

def load_function_mappings():
    """Load function mappings to determine which modules are needed."""
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

def get_used_modules(file_path, mappings):
    """Get which BotModules are being used in a file."""
    used_modules = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for BotModule.function_name patterns
        for func_name, mapping in mappings.items():
            pattern = rf'{mapping["module"]}\.{mapping["target"]}\('
            if re.search(pattern, content):
                used_modules.add(mapping['module'])
    
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    
    return used_modules

def get_existing_imports(file_path):
    """Get existing BotModule imports from a file."""
    existing_imports = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for "from BotModules.ModuleName import"
        pattern = r'from BotModules\.(\w+) import'
        matches = re.findall(pattern, content)
        existing_imports.update(matches)
    
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    
    return existing_imports

def add_missing_imports(file_path, missing_modules):
    """Add missing imports to a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Find the last existing BotModule import
        last_botmodule_import_line = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('from BotModules.') and 'import' in line:
                last_botmodule_import_line = i
        
        # Add missing imports after the last BotModule import
        if last_botmodule_import_line >= 0:
            insert_pos = last_botmodule_import_line + 1
        else:
            # If no BotModule imports, add after the regular imports
            insert_pos = 0
            for i, line in enumerate(lines):
                if line.strip() and not line.strip().startswith('#') and not line.strip().startswith('import') and not line.strip().startswith('from'):
                    insert_pos = i
                    break
        
        # Insert the missing imports
        new_lines = []
        for module in sorted(missing_modules):
            class_name = module  # BotRepetition -> BotRepetition
            new_lines.append(f'from BotModules.{module} import {class_name}\n')
        
        lines[insert_pos:insert_pos] = new_lines
        
        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        return len(new_lines)
    
    except Exception as e:
        print(f"Error updating {file_path}: {e}")
        return 0

def main():
    print("🔍 Checking missing BotModule imports...")
    mappings = load_function_mappings()
    
    # Check key files
    files_to_check = [
        Path('bot_ek0x45.py'),
    ]
    
    # Add all BotModules files
    botmodules_dir = Path('BotModules')
    if botmodules_dir.exists():
        files_to_check.extend(botmodules_dir.glob('*.py'))
    
    total_imports_added = 0
    
    for file_path in files_to_check:
        if not file_path.exists():
            continue
            
        print(f"\n📁 Checking {file_path.name}...")
        
        used_modules = get_used_modules(file_path, mappings)
        existing_imports = get_existing_imports(file_path)
        missing_modules = used_modules - existing_imports
        
        if missing_modules:
            print(f"   Missing imports: {', '.join(sorted(missing_modules))}")
            imports_added = add_missing_imports(file_path, missing_modules)
            total_imports_added += imports_added
            if imports_added > 0:
                print(f"   ✅ Added {imports_added} imports")
        else:
            print(f"   ✅ All required imports present")
    
    print(f"\n🎉 Total imports added: {total_imports_added}")
    
    if total_imports_added > 0:
        print("\n✅ All missing imports have been added!")
        print("💡 The code should now work without ImportError issues.")
    else:
        print("\nℹ️  No missing imports found.")

if __name__ == "__main__":
    main()
