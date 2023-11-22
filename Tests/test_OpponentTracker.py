import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class OpponentTrackerTests(TestBase):    
    def test_should_convert_city_capture_into_lost_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_convert_city_capture_into_lost_army___4r4HqWsPJ---0--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=388)
        rawMap.GetTile(0, 11).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(0, 10).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '0,10->0,11')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.assertEqual(190, bot.opponent_tracker.current_team_cycle_stats[1].approximate_fog_army_available_total)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
        self.assertLess(bot.opponent_tracker.current_team_cycle_stats[1].approximate_fog_army_available_total, 144)
    
    def test_should_load_map_data(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_load_map_data___P0YO4V4u8---0--111.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 111, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=111)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.assertEqual(50, bot.opponent_tracker.team_score_data_history[0][50].score)
        self.assertEqual(50, bot.opponent_tracker.team_score_data_history[1][50].score)

        self.assertEqual(80, bot.opponent_tracker.team_score_data_history[0][100].score)
        self.assertEqual(82, bot.opponent_tracker.team_score_data_history[1][100].score)

        self.assertEqual(24, bot.opponent_tracker.team_score_data_history[0][50].tileCount)
        self.assertEqual(24, bot.opponent_tracker.team_score_data_history[1][50].tileCount)

        self.assertEqual(37, bot.opponent_tracker.team_score_data_history[0][100].tileCount)
        self.assertEqual(39, bot.opponent_tracker.team_score_data_history[1][100].tileCount)

        self.assertEqual(1, bot.opponent_tracker.team_score_data_history[0][50].cityCount)
        self.assertEqual(1, bot.opponent_tracker.team_score_data_history[1][50].cityCount)

        self.assertEqual(1, bot.opponent_tracker.team_score_data_history[0][100].cityCount)
        self.assertEqual(2, bot.opponent_tracker.team_score_data_history[1][100].cityCount)

        self.assertEqual(38, len(bot.opponent_tracker._gather_queues_by_player[1]))
        counts = bot.opponent_tracker.get_player_fog_tile_count_dict()
        self.assertEqual(27, counts[1][2])
        self.assertEqual(11, counts[1][1])
    
    def test_should_not_count_discovered_tile_towards_fog_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_count_discovered_tile_towards_fog_army___jXow3ven_---1--80.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)
        rawMap.GetTile(5, 5).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(6, 5).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(5, 6).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(6, 6).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '8,6->7,6->6,6')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertEqual(6, bot.get_opponent_cycle_stats().approximate_fog_army_available_total)

    def test_should_count_collision_from_fog_against_army_fog_total(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_count_collision_from_fog_against_army_fog_total___xvLQPd3SW---1--72.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 72, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=72)
        rawMap.GetTile(3, 10).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,10->4,10')
        simHost.queue_player_moves_str(general.player, '5,10->4,10')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertEqual(18, bot.get_opponent_cycle_stats().approximate_fog_army_available_total)
    
    def test_should_full_reset_fog_army_based_on_close_emergence(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_full_reset_fog_army_based_on_close_emergence___xvLQPd3SW---1--80.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)
        rawMap.GetTile(4, 13).army = 1
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,13->4,12')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertLess(bot.get_opponent_cycle_stats().approximate_fog_army_available_total, 5)
        self.assertLess(bot.get_opponent_cycle_stats().approximate_fog_city_army, 5)
    
    def test_should_gracefully_handle_larger_emergences_than_available_est_fog_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gracefully_handle_larger_emergences_than_available_est_fog_army___8OjOsTNaW---0--180.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 180, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=180)
        rawMap.GetTile(7, 8).army = 1
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '7,6->7,7')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertEqual(0, bot.get_opponent_cycle_stats().approximate_fog_army_available_total)
        self.assertLess(bot.get_opponent_cycle_stats().approximate_fog_city_army, 5)
        self.assertGreater(bot.get_opponent_cycle_stats().approximate_fog_city_army, 0)
    
    def test_should_recognize_gather_differential_and_defend_large_push(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_differential_and_defend_large_push___eECnJGq78---1--77.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 77, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=77)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        ogTileDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        endTileDiff = self.get_tile_differential(simHost)
        self.assertLess(endTileDiff, ogTileDiff + 6)

    def test_should_continue_defending_based_on_cycle_army_incoming(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_defending_based_on_cycle_army_incoming___eMaQzjAw6---0--222.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 222, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=222)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        ogDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=22)
        self.assertIsNone(winner)

        self.assertLess(self.get_tile_differential(simHost), ogDiff + 5)
    
    def test_should_keep_gathering_defensively_when_opp_obviously_all_inning(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_keep_gathering_defensively_when_opp_obviously_all_inning___T60rbPlAO---0--168.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 168, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=168)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)
        bot.locked_launch_point = bot.general
        bot.target_player_gather_path = None

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=22)
        self.assertIsNone(winner)

        self.assertLess(playerMap.players[general.player].tileCount, 53)

    def test_should_not_go_defensive_too_early(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_go_defensive_too_early___9gaR3CZwL---1--132.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=132)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_not_over_reduce_fog_army_on_move_half_chase(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_over_reduce_fog_army_on_move_half_chase___reD-mBF46---1--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=181)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,4->8,5z  8,4->8,5->8,6')
        simHost.queue_player_moves_str(general.player, '8,5->8,6->8,7->7,7')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        enStats = bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player)
        sumFogStuff = enStats.approximate_fog_army_available_total + enStats.approximate_fog_city_army

        self.assertGreater(sumFogStuff, 12)

        self.assertLess(sumFogStuff, 16)
    
    def test_should_gather_maximally_from_edges_while_defending_econ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_maximally_from_edges_while_defending_econ___dD6E59lT7---1--300.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 300, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=300)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        matrix = bot.get_gather_tiebreak_matrix()
        # these should all be 'out of play' gather tiles, and should ALWAYS be rewarded for gathering.
        self.assertGreater(matrix[playerMap.GetTile(5, 7)], 0.1)
        self.assertGreater(matrix[playerMap.GetTile(4, 7)], 0.1)
        self.assertGreater(matrix[playerMap.GetTile(3, 7)], 0.1)
        self.assertGreater(matrix[playerMap.GetTile(3, 8)], 0.1)
        self.assertGreater(matrix[playerMap.GetTile(3, 6)], 0.1)
        self.assertGreater(matrix[playerMap.GetTile(3, 5)], 0.1)
        self.assertGreater(matrix[playerMap.GetTile(4, 6)], 0.1)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=39)
        self.assertIsNone(winner)

        self.assertGreater(bot.sum_player_army_near_or_on_tiles(bot.target_player_gather_path.tileList, distance=3), 130)
