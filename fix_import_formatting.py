#!/usr/bin/env python3
"""
Script to fix import formatting in BotModules files.
"""

import re
from pathlib import Path

def fix_import_formatting(file_path):
    """Fix import formatting in a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        new_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                new_lines.append(lines[i])
                i += 1
                continue
            
            # Handle import statements
            if line.startswith('import ') or line.startswith('from '):
                # Add the import line
                new_lines.append(lines[i])
                i += 1
                
                # Look for additional import lines and group them
                while i < len(lines):
                    next_line = lines[i].strip()
                    if next_line.startswith('import ') or next_line.startswith('from '):
                        new_lines.append(lines[i])
                        i += 1
                    else:
                        break
                
                # Add empty line after imports if next line is not an import
                if i < len(lines) and not lines[i].strip().startswith(('import ', 'from ')):
                    new_lines.append('')
            else:
                new_lines.append(lines[i])
                i += 1
        
        # Remove excessive empty lines (more than 2 in a row)
        final_lines = []
        empty_count = 0
        for line in new_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:  # Allow max 2 empty lines
                    final_lines.append(line)
            else:
                empty_count = 0
                final_lines.append(line)
        
        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_lines))
        
        return True
        
    except Exception as e:
        print(f"Error fixing {file_path}: {e}")
        return False

def main():
    print("🔧 Fixing import formatting...")
    
    # Fix all BotModules files
    botmodules_dir = Path('BotModules')
    if botmodules_dir.exists():
        for py_file in sorted(botmodules_dir.glob('*.py')):
            print(f"  📄 {py_file.name}...")
            if fix_import_formatting(py_file):
                print(f"     ✅ Fixed formatting")
    
    # Also fix bot_ek0x45.py
    bot_file = Path('bot_ek0x45.py')
    if bot_file.exists():
        print(f"  📄 {bot_file.name}...")
        if fix_import_formatting(bot_file):
            print(f"     ✅ Fixed formatting")
    
    print("\n✅ Import formatting fixed!")

if __name__ == "__main__":
    main()
