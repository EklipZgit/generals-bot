"""
Benchmark tool for CP-SAT configurations.

This script benchmarks all CP-SAT configurations on various maps to compare performance.
It measures both timing and economic value of solutions.

To run this benchmark:
  python -m BenchmarkTools.benchmark_cp_sat_configs

Or run as a unittest:
  python -m unittest BenchmarkTools.benchmark_cp_sat_configs.CpSatConfigBenchmark.test_benchmark_all_cp_sat_configs
"""

import gc
import random
import time
import typing
from collections import deque
from BotModules.BotExpansionOps import BotExpansionOps

import logbook

import Gather
import SearchUtils
from Algorithms import TileIslandBuilder
from Army import Army
from ArmyAnalyzer import ArmyAnalyzer
from ArmyEngine import ArmyEngine
from ArmyInterceptionUnitTests import ArmyInterceptionUnitTests
from ArmyTracker import ArmyTracker
from BehaviorAlgorithms import FlowExpansion
from BehaviorAlgorithms.Flow import FlowDirectionFinderABC
from BehaviorAlgorithms.Flow.FlowGraphModels import IslandMaxFlowGraph
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from BoardAnalyzer import BoardAnalyzer
from BotModules.BotExpansionOps import BotExpansionOps
from CityAnalyzer import CityAnalyzer
from CityContestor import CityContestor
from CityExpander import CityExpander
from Communication import CoordinatedDefense
from DangerAnalyzer import DangerAnalyzer
from DebugHelper import DebugHelper
from Directives import Directives
from EarlyExpandUtils import EarlyExpandUtils
from ExpandUtils import ExpandUtils
from Gather.CpSatParameterConfigs import ALL_CONFIGS, CpSatConfig
from History import History
from KnapsackUtils import KnapsackUtils
from MapMatrix import MapMatrix
from PerformanceTimer import PerformanceTimer
from Path import Path
from SearchUtils import SearchUtils
from Sim.GameSimulatorHost import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from StrategyModels.ExpansionPotential import ExpansionPotential
from StrategyModels.OpponentTrackerModels import OpponentTracker
from Territory import Territory
from Tests.TestBase import TestBase
from Utils.ScaleUtils import ScaleUtils
from Viewer.ViewerProcessHost import ViewerProcessHost


class CpSatConfigBenchmark(TestBase):
    """Benchmark all CP-SAT configurations on various maps to compare performance."""

    def test_benchmark_all_cp_sat_configs(self):
        """Benchmark all CP-SAT configs on various maps to compare performance."""

        """
========================================================================================================================
SUMMARY - Sorted by Total Time (ascending)
========================================================================================================================
aggressive_speed                Total Time:  1458.07ms  Total Econ:  2283.97
1_wrker_aggressive_presolve     Total Time:  1465.14ms  Total Econ:  2283.95
1_wrker                         Total Time:  1474.98ms  Total Econ:  2283.40
1_wrker_no_presolve             Total Time:  1479.95ms  Total Econ:  2284.00
1_wrker_branching_automatic     Total Time:  1496.64ms  Total Econ:  2283.12
1_wrker_linearization_full      Total Time:  1498.88ms  Total Econ:  2283.97
1_wrker_branching_portfolio     Total Time:  1547.83ms  Total Econ:  2282.93
two_workers                     Total Time:  1735.97ms  Total Econ:  2283.16
balanced_performance            Total Time:  1787.50ms  Total Econ:  2283.91
branching_automatic             Total Time:  1819.35ms  Total Econ:  2283.76
baseline                        Total Time:  1826.25ms  Total Econ:  2283.01
branching_portfolio             Total Time:  1828.79ms  Total Econ:  2283.40
linearization_partial           Total Time:  1839.09ms  Total Econ:  2283.51
linearization_full              Total Time:  1857.70ms  Total Econ:  2284.84
aggressive_presolve             Total Time:  1867.63ms  Total Econ:  2283.03
branching_fixed                 Total Time:  1881.09ms  Total Econ:  2283.30
linearization_none              Total Time:  1975.58ms  Total Econ:  2283.86
no_presolve                     Total Time:  2116.52ms  Total Econ:  2283.36
========================================================================================================================
        """
        # Maps to test - a selection of different scenarios from existing tests
        test_maps = [
            'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap',
            'GameContinuationEntries/should_not_fail_to_find_flow_expansion_routes__what_the_fuck___fHjzkD6XM---0--484.txtmap',
            'GameContinuationEntries/a_more_open_normal_map___VY49QNB72---1--250.txtmap',
            'GameContinuationEntries/should_use_all_of_your_fucking_army_round_2_electric_boogaloo_2_electric_boogaloo___AKbuZXaBX---1--76.txtmap',
            'GameContinuationEntries/should_use_all_of_your_fucking_army_what_the_actual_fucking_fuck___fjsd8Ttie---1--126.txtmap',
            'GameContinuationEntries/should_handle_expanding_behind_choke_effectively_rather_than_crossing_choke_boundary_into_obvious_recap___J09nXVIEh---1--121.txtmap',
            # Army interception scenarios
            'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap',
            'GameContinuationEntries/should_not_value_pointless_intercepts___Human.exe-TEST__bee0a7ef-ea4e-4234-aba2-4d8c5384d938---0--141.txtmap',
            'GameContinuationEntries/should_continue_to_intercept_army___HO8rgeNt7---0--140.txtmap',
            'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap',
            'GameContinuationEntries/should_split_to_deal_with_incoming_army_dance___JFUcRsunT---0--130.txtmap',
            'GameContinuationEntries/should_not_override_defense_with_intercept_for_wrong_army_lol___ObO-Yfd3_---0--629.txtmap',
            'GameContinuationEntries/should_intercept_preventing_massive_damage___TbmnknZ-M---1--136.txtmap',
            'GameContinuationEntries/should_not_allow_runaround_to_kill_general___4bhqHLlOh---1--335.txtmap',
            'GameContinuationEntries/should_not_override_defense_when_gets_self_killed___4blcspk3P---1--612.txtmap',
            'GameContinuationEntries/should_not_intercept_inbound_threats_as_defense_intercepts_with_the_tile_being_threatened___x8KSpOZGG---0--353.txtmap',
            'GameContinuationEntries/should_intercept_when_better_than_taking_neutrals_wtf___ouF0W0tnh---1--92.txtmap',
            'GameContinuationEntries/should_not_play_weird_intercept_moves_over_just_capturing_threat___ouF0W0tnh---1--322.txtmap',
            'GameContinuationEntries/should_correctly_value_intercept_from_general___jzXGxMXQl---1--323.txtmap',
            'GameContinuationEntries/should_do_something_with_400_army_this_round_holy_shit___fHjzkD6XM---0--521.txtmap',
            'GameContinuationEntries/should_fucking_intercept_and_finish_out_the_round_normally___DXpYdlvhe---1--83.txtmap',
            'GameContinuationEntries/should_not_allow_enemy_to_dodge_back_away_from_general_without_countercapping___xow-pf3Af---0--290.txtmap',
            'GameContinuationEntries/should_not_wastefully_intercept_early_in_the_round___sTDj-LVHp---1--300.txtmap',
            'GameContinuationEntries/should_not_wiggle_around_intercepting_army_when_should_just_cap_tiles___LLuhlaLoz---1--354.txtmap',
            'GameContinuationEntries/should_not_take_literal_lifetimes_to_load_intercepts___nyeEPub4n---7--1165.txtmap',
            'GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap',
            'GameContinuationEntries/should_complete_city_capture___00lfFVqib---0--518.txtmap',
        ]

        # Number of runs per config per map for averaging
        runs_per_config = 5

        # Store results: {map_file: {config_name: {'avg_time': float, 'avg_econ': float, 'runs': list, 'econ_runs': list}}}
        results: dict[str, dict[str, dict]] = {}

        # Initialize results structure
        for map_file in test_maps:
            results[map_file] = {}

        # Loop maps outer, configs inner for fairer testing and better GC
        print('\n' + '=' * 120)
        print('BENCHMARKING CP-SAT CONFIGS (maps outer, configs inner for fairer testing)')
        print('=' * 120)

        for map_file in test_maps:
            print(f'\nProcessing map: {map_file.split("/")[-1]}')

            # Load and set up map
            map, general, enemyGeneral = self.load_map_and_generals(map_file, 250, fill_out_tiles=True)
            rawMap, _ = self.load_map_and_general(map_file, respect_undiscovered=True, turn=250)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            bot = self.get_debug_render_bot(simHost, general.player)
            bot.flow_expander.log_debug = False
            self.stop_capturing_logging()
            self.enable_search_time_limits_and_disable_debug_asserts()

            # Run for 1 turn to let bot initialize and get all options
            winner = simHost.run_sim(run_real_time=False, turn_time=0.25, turns=0)
            simHost.reset_move_queue()

            # Shuffle configs for this map to reduce ordering bias
            shuffled_configs = ALL_CONFIGS.copy()
            random.shuffle(shuffled_configs)

            # Test each config on this map
            for config in shuffled_configs:
                config_name = config.name
                print(f'  Testing config: {config_name}')

                map_results = []
                map_econ_values = []

                # Temporarily set the config
                original_config = FlowExpansion.CP_SAT_CONFIG_NAME
                FlowExpansion.CP_SAT_CONFIG_NAME = config_name
                # print(config_name)  # uncomment if a config starts hanging and you need to see which is causing it.

                # Time just the flow expansion (not construction)
                gc.collect()

                for run in range(runs_per_config):
                    try:
                        start_time = time.perf_counter()

                        # Use bot's expansion method to get all options including intercept and city capture options
                        expansionPlan = BotExpansionOps.build_expansion_plan(
                            bot=bot,
                            timeLimit=10.0,
                            expansionNegatives=set(),
                            pathColor=(0, 0, 0),
                            overrideTurns=50,
                            includeExtraGenAndCityArmy=True,
                            skip_remaining_time_check=True,
                        )

                        elapsed = time.perf_counter() - start_time

                        # Calculate total econ value from the expansion plan
                        total_econ = expansionPlan.cumulative_econ_value

                        map_results.append(elapsed)
                        map_econ_values.append(total_econ)

                    except Exception as e:
                        logbook.error(f'Config {config_name} on map {map_file} run {run} failed: {e}')
                        map_results.append(float('inf'))
                        map_econ_values.append(0.0)

                # Restore original config
                FlowExpansion.CP_SAT_CONFIG_NAME = original_config

                # Calculate averages
                avg_time = sum(map_results) / len(map_results) if map_results else float('inf')
                avg_econ = sum(map_econ_values) / len(map_econ_values) if map_econ_values else 0.0

                results[map_file][config_name] = {
                    'avg_time': avg_time,
                    'avg_econ': avg_econ,
                    'runs': map_results,
                    'econ_runs': map_econ_values,
                }

            # Let this map/bot garbage collect before next map
            del map, general, enemyGeneral, rawMap, simHost, bot
            gc.collect()

        # Print results with maps as columns
        print('\n' + '=' * 120)
        print('CP-SAT CONFIG BENCHMARK RESULTS')
        print('=' * 120)
        print(f'Tested {len(ALL_CONFIGS)} configs on {len(test_maps)} maps ({runs_per_config} runs each)')
        print('=' * 120)
        print('\nTIMING (ms) - Maps as columns:')
        print('-' * 120)

        # Print header row with map names
        header = f'{"Config":<30}'
        for map_file in test_maps:
            map_name = map_file.split("/")[-1][:25]
            header += f'  {map_name:>20}'
        print(header)
        print('-' * 120)

        # Print timing results
        for config_name in sorted(results[list(test_maps)[0]].keys()):
            row = f'{config_name:<30}'
            for map_file in test_maps:
                result = results[map_file][config_name]
                row += f'  {result["avg_time"]*1000:>20.1f}'
            print(row)

        print('\n' + '-' * 120)
        print('ECON VALUE - Maps as columns:')
        print('-' * 120)

        # Print header row with map names
        print(header)
        print('-' * 120)

        # Print econ results
        for config_name in sorted(results[list(test_maps)[0]].keys()):
            row = f'{config_name:<30}'
            for map_file in test_maps:
                result = results[map_file][config_name]
                row += f'  {result["avg_econ"]:>25.2f}'
            print(row)

        print('\n' + '=' * 120)
        print('SUMMARY - Sorted by Total Time (ascending)')
        print('=' * 120)

        config_totals = []
        for config_name in sorted(results[list(test_maps)[0]].keys()):
            total_time = sum(results[mf][config_name]['avg_time'] for mf in test_maps)
            total_econ = sum(results[mf][config_name]['avg_econ'] for mf in test_maps)
            config_totals.append((config_name, total_time, total_econ))

        config_totals.sort(key=lambda x: x[1])  # Sort by time

        for config_name, total_time, total_econ in config_totals:
            print(f'{config_name:30s}  Total Time: {total_time*1000:8.2f}ms  Total Econ: {total_econ:8.2f}')

        print('=' * 120 + '\n')
