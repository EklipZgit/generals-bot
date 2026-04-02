#!/usr/bin/env python3
"""
Script to remove self-imports from BotModules files.
"""

import re
from pathlib import Path

def remove_self_imports(file_path):
    """Remove self-imports from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Get the file name without extension
        file_name = file_path.stem  # e.g., BotCityOps.py -> BotCityOps
        
        # Remove self-import pattern
        pattern = rf'from BotModules\.{file_name} import {file_name}'
        content = re.sub(pattern, '', content)
        
        # Clean up any extra empty lines left behind
        content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
        
        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return True
        
    except Exception as e:
        print(f"Error fixing {file_path}: {e}")
        return False

def main():
    print("🔧 Removing self-imports...")
    
    # Fix all BotModules files
    botmodules_dir = Path('BotModules')
    if botmodules_dir.exists():
        for py_file in sorted(botmodules_dir.glob('*.py')):
            print(f"  📄 {py_file.name}...")
            if remove_self_imports(py_file):
                print(f"     ✅ Removed self-imports")
    
    print("\n✅ Self-imports removed!")

if __name__ == "__main__":
    main()
