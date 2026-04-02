#!/usr/bin/env python3
"""
Enhanced script to scan for bot.method_name calls where the method doesn't exist in bot_ek0x45.py
This version checks if the method exists in BotModules and categorizes the results.
"""

import os
import re
import ast
from typing import Set, List, Tuple, Dict

def get_bot_methods(bot_file_path: str) -> Set[str]:
    """Extract all method names from the bot class"""
    methods = set()
    
    try:
        with open(bot_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the AST to find method definitions
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == 'EklipZBot':
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.add(item.name)
                break
    
    except Exception as e:
        print(f"Error parsing {bot_file_path}: {e}")
        # Fallback to regex parsing
        try:
            with open(bot_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find method definitions in the EklipZBot class
            class_match = re.search(r'class EklipZBot.*?(?=\nclass|\Z)', content, re.DOTALL)
            if class_match:
                class_content = class_match.group(0)
                method_matches = re.findall(r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', class_content)
                methods.update(method_matches)
        except Exception as e2:
            print(f"Fallback parsing also failed: {e2}")
    
    return methods

def get_botmodule_methods(directory: str) -> Dict[str, str]:
    """Get all static methods from BotModules and their module locations"""
    methods = {}
    
    botmodules_dir = os.path.join(directory, "BotModules")
    if not os.path.exists(botmodules_dir):
        return methods
    
    for file in os.listdir(botmodules_dir):
        if file.endswith('.py') and file.startswith('Bot'):
            file_path = os.path.join(botmodules_dir, file)
            module_name = file[:-3]  # Remove .py extension
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find static method definitions
                static_method_matches = re.findall(r'@staticmethod\s*\n\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', content)
                for method_name in static_method_matches:
                    methods[method_name] = module_name
                
                # Also find regular methods (in case they're called statically)
                method_matches = re.findall(r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', content)
                for method_name in method_matches:
                    if method_name not in methods:
                        methods[method_name] = module_name
                        
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
    
    return methods

def find_bot_method_calls(directory: str) -> List[Tuple[str, int, str]]:
    """Find all bot.method_name calls in Python files"""
    calls = []
    
    # Pattern to match bot.method_name( or bot.method_name (
    pattern = re.compile(r'bot\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')
    
    for root, dirs, files in os.walk(directory):
        # Skip _OLD files and common non-source directories
        dirs[:] = [d for d in dirs if not d.startswith('_') and d not in ['__pycache__', '.git', 'node_modules']]
        
        for file in files:
            if file.endswith('.py') and not file.endswith('_OLD.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Find all matches with line numbers
                    for match in pattern.finditer(content):
                        line_num = content[:match.start()].count('\n') + 1
                        method_name = match.group(1)
                        
                        # Skip common bot attributes that aren't methods
                        if method_name in [
                            'info', 'debug', 'viewInfo', '_map', 'general', 'player', 'targetPlayer',
                            'targetPlayerObj', 'targetPlayerExpectedGeneralLocation', 'enemy_general',
                            'teammate_general', 'teammate', 'opponent_tracker', 'armyTracker',
                            'board_analysis', 'territories', 'expansion_plan', 'curPath',
                            'leafMoves', 'gatherNodes', 'intercept_plans', 'next_scrimming_army_tile',
                            'completed_first_100', 'is_all_in_losing', 'is_all_in', 'engine_use_mcts',
                            'engine_force_multi_tile_mcts', 'engine_army_nearby_tiles_range',
                            'engine_mcts_scrim_armies_per_player_limit', 'engine_always_include_last_move_tile_in_scrims',
                            'mcts_engine', 'perf_timer', 'timings', 'history', 'logDirectory',
                            'info_render_gather_values', 'engine_include_path_pre_expansion',
                            'self_destruct', 'enemy_attack_path', 'shortest_path_to_target_player',
                            'alt_en_gen_positions', '_alt_en_gen_position_distances', 'repetition_map',
                            'friendly_army_nearby_tiles', 'enemy_army_nearby_tiles', 'scrim_moves',
                            'last_move', 'surrender_func', 'cities', 'generals', 'armies_moved_this_turn',
                            'should_launch', 'launch_turn', 'last_gather_turn', 'last_expansion_turn',
                            'last_interception_turn', 'last_defense_turn', 'last_quick_kill_turn',
                            'last_cycle_turn', 'current_cycle_turn', 'cycle_start_turn', 'cycle_end_turn',
                            'fog_army_increment_turn', 'last_fog_army_increment_turn', 'last_turn_captured_city',
                            'last_turn_lost_general', 'last_turn_killed_general', 'last_turn_captured_enemy_general',
                            'last_turn_lost_city', 'last_turn_destroyed_enemy_city', 'last_turn_saw_enemy_general',
                            'last_turn_saw_enemy_city', 'last_turn_saw_enemy_army', 'last_turn_saw_enemy_territory',
                            'last_turn_moved_general', 'last_turn_moved_army', 'last_turn_moved_city',
                            'last_turn_moved_territory', 'last_turn_scanned_map', 'last_turn_analyzed_map',
                            'last_turn_analyzed_enemy', 'last_turn_analyzed_friendly', 'last_turn_analyzed_neutral',
                            'last_turn_analyzed_unknown', 'last_turn_analyzed_all', 'last_turn_analyzed_visible',
                            'last_turn_analyzed_invisible', 'last_turn_analyzed_discovered', 'last_turn_analyzed_undiscovered'
                        ]:
                            continue
                        
                        calls.append((file_path, line_num, method_name))
                        
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
    
    return calls

def main():
    """Main function to scan for missing methods"""
    print("🔍 Enhanced scan for bot.method_name calls...")
    print()
    
    # Get bot methods
    bot_file = "bot_ek0x45.py"
    if not os.path.exists(bot_file):
        print(f"❌ Error: {bot_file} not found")
        return
    
    print(f"📖 Analyzing {bot_file}...")
    bot_methods = get_bot_methods(bot_file)
    print(f"✅ Found {len(bot_methods)} methods in EklipZBot class")
    
    # Get BotModule methods
    print(f"📚 Analyzing BotModules...")
    botmodule_methods = get_botmodule_methods(".")
    print(f"✅ Found {len(botmodule_methods)} methods in BotModules")
    print()
    
    # Find all bot.method calls
    print("🔍 Scanning for bot.method_name calls...")
    calls = find_bot_method_calls(".")
    print(f"✅ Found {len(calls)} bot.method_name calls")
    print()
    
    # Categorize calls
    in_bot = []
    in_botmodules = []
    missing = []
    
    for file_path, line_num, method_name in calls:
        rel_path = os.path.relpath(file_path, ".")
        
        if method_name in bot_methods:
            in_bot.append((rel_path, line_num, method_name))
        elif method_name in botmodule_methods:
            in_botmodules.append((rel_path, line_num, method_name, botmodule_methods[method_name]))
        else:
            missing.append((rel_path, line_num, method_name))
    
    # Report results
    print(f"📊 Results Summary:")
    print(f"   - Methods in bot class: {len(in_bot)}")
    print(f"   - Methods in BotModules: {len(in_botmodules)}")
    print(f"   - Missing methods: {len(missing)}")
    print(f"   - Success rate: {((len(in_bot) + len(in_botmodules)) / len(calls) * 100):.1f}%")
    print()
    
    # Show missing methods (these are the problematic ones)
    if missing:
        print(f"❌ MISSING METHODS (these will cause AttributeError):")
        print()
        
        # Group by file
        by_file = {}
        for file_path, line_num, method_name in missing:
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append((line_num, method_name))
        
        for file_path in sorted(by_file.keys()):
            if not file_path.startswith('Tests/') and not file_path.startswith('UnitTests/'):
                print(f"📁 {file_path}:")
                for line_num, method_name in sorted(by_file[file_path]):
                    print(f"   Line {line_num}: bot.{method_name}")
                print()
        
        print(f"📝 Test files with missing methods (count: {sum(len(v) for k, v in by_file.items() if k.startswith('Tests/') or k.startswith('UnitTests/'))}):")
        for file_path in sorted([k for k in by_file.keys() if k.startswith('Tests/') or k.startswith('UnitTests/')]):
            print(f"   {file_path}: {len(by_file[file_path])} calls")
        print()
    
    # Show methods that need to be refactored (in BotModules but called as bot.method)
    if in_botmodules:
        print(f"🔧 METHODS NEEDING REFACTORING (exist in BotModules but called as bot.method):")
        print()
        
        # Group by file and module
        by_file = {}
        for file_path, line_num, method_name, module_name in in_botmodules:
            if file_path not in by_file:
                by_file[file_path] = {}
            if module_name not in by_file[file_path]:
                by_file[file_path][module_name] = []
            by_file[file_path][module_name].append((line_num, method_name))
        
        for file_path in sorted(by_file.keys()):
            if not file_path.startswith('Tests/') and not file_path.startswith('UnitTests/'):
                print(f"📁 {file_path}:")
                for module_name in sorted(by_file[file_path].keys()):
                    print(f"   Module: {module_name}")
                    for line_num, method_name in sorted(by_file[file_path][module_name]):
                        print(f"     Line {line_num}: bot.{method_name} -> {module_name}.{method_name}")
                print()
    
    print("✅ Scan complete!")

if __name__ == "__main__":
    main()
