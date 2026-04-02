#!/usr/bin/env python3
"""
Parse git diff to extract function mappings and create an optimized checker.
"""

import re
from pathlib import Path

def parse_function_mappings():
    """Parse the git diff to extract function -> module mappings."""
    mappings = {}
    
    with open('git_diff_detailed.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for removed function definitions
        if line.startswith('-    def '):
            func_name = line.replace('-    def ', '').split('(')[0]
            
            # Look at the next few lines for the return statement
            j = i + 1
            while j < len(lines) and j < i + 5:  # Check next 5 lines max
                next_line = lines[j].strip()
                if 'return ' in next_line and '.' in next_line:
                    # Extract module and function from return statement
                    # Pattern: return ModuleName.function_name(self, ...)
                    match = re.search(r'return (\w+)\.(\w+)\(self', next_line)
                    if match:
                        module = match.group(1)
                        mappings[func_name] = {
                            'module': module,
                            'target_function': match.group(2),
                            'return_line': next_line.strip()
                        }
                        break
                j += 1
        i += 1
    
    return mappings

def write_function_mappings():
    """Write the function mappings to files."""
    mappings = parse_function_mappings()
    
    # Write just function names (for backwards compatibility)
    with open('removed_functions_clean.txt', 'w', encoding='utf-8') as f:
        for func_name in sorted(mappings.keys()):
            f.write(f"{func_name}\n")
    
    # Write detailed mappings
    with open('function_mappings.txt', 'w', encoding='utf-8') as f:
        f.write("function_name,module_name,target_function,return_line\n")
        for func_name, info in sorted(mappings.items()):
            f.write(f"{func_name},{info['module']},{info['target_function']},\"{info['return_line']}\"\n")
    
    print(f"Parsed {len(mappings)} function mappings")
    return mappings

if __name__ == "__main__":
    write_function_mappings()
