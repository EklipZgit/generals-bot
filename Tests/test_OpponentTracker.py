import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.tile import Tile_MOUNTAIN, TILE_EMPTY, MapBase


class OpponentTrackerTests(TestBase):
    def test_should_convert_city_capture_into_lost_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_convert_city_capture_into_lost_army___4r4HqWsPJ---0--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=388)
        rawMap.GetTile(0, 11).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(0, 10).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '0,10->0,11')
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        counts = bot.opponent_tracker.get_all_player_fog_tile_count_dict()
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        ogTileDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        endTileDiff = self.get_tile_differential(simHost)
        self.assertLess(endTileDiff, ogTileDiff + 8)

    def test_should_continue_defending_based_on_cycle_army_incoming(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_defending_based_on_cycle_army_incoming___eMaQzjAw6---0--222.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 222, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=222)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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
        bot = self.get_debug_render_bot(simHost, general.player)
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

        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles(bot.target_player_gather_path.tileList, distance=3), 130)
    
    def test_should_acknowledge_serious_enemy_attack_path_threat_and_defense_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_acknowledge_serious_enemy_attack_path-threat_and_defense_gather___Sl1-YUT46---1--267.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 267, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=267)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=33)
        self.assertIsNone(winner)
    
    def test_should_not_reduce_enemy_army_while_capturing_visible_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_reduce_enemy_army_while_capturing_visible_tiles___futhAqN24---1--339.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 339, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=339)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,14->13,14')
        simHost.queue_player_leafmoves(enemyGeneral.player, num_moves=7)
        simHost.queue_player_moves_str(general.player, '14,14->10,14->10,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        enStats = bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player)
        self.assertEqual(9, enStats.approximate_fog_city_army)
        self.assertEqual(0, enStats.approximate_fog_army_available_total)
        counts = bot.opponent_tracker.get_all_player_fog_tile_count_dict()
        self.assertEqual(9, counts[enemyGeneral.player][2], "should have used 2's under the fog when expanding")
    
    def test_should_not_launch_instead_of_leaf_moves_when_opponent_hasnt_shown_intentions(self):
        # TODO not sure if I really do want do have it move the top left tiles first. Definitely shouldn't launch, though.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_instead_of_leaf_moves_when_opponent_hasnt_shown_intentions___atTOZgR22---1--125.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 125, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=125)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.launchTiming = 25
        bot.timings.splitTurns = 25
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.assertEqual(0, bot.sum_player_standing_army_near_or_on_tiles([playerMap.GetTile(2, 11)], distance=6, player=general.player), "should have used all the tiles in the top left")
    
    def test_should_be_greedy_when_recognizing_greedy_buffer_against_gathering_opponent(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_greedy_when_recognizing_greedy_buffer___ZsyD7bgAv---0--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertIsNone(winner)

        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([general], distance=2), 60)
        self.assertPlayerTileCountGreater(simHost, general.player, 52)
        self.assertPlayerTileCountLess(simHost, general.player, 57)

    def test_should_be_extremely_greedy_when_recognizing_greedy_buffer_against_expanding_opponent(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_greedy_when_recognizing_greedy_buffer___ZsyD7bgAv---0--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertIsNone(winner)

        self.assertLess(bot.sum_player_standing_army_near_or_on_tiles([general], distance=2), 45)
        self.assertPlayerTileCountGreater(simHost, general.player, 60)
        self.assertPlayerTileCountLess(simHost, general.player, 70)

    def test_should_correctly_reduce_en_fog_army_even_when_visible_tile_captured(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_reduce_en_fog_army_even_when_visible_tile_captured__real_map___glKjUk9Yo---1--129.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 129, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_correctly_reduce_en_fog_army_even_when_visible_tile_captured___glKjUk9Yo---1--129.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=129)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,10->4,9  4,8->4,9')
        simHost.queue_player_moves_str(general.player, '13,4->13,3  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        stats = bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player)

        with self.subTest(mainAsserts=True):
            self.assertGreater(stats.approximate_fog_army_available_total + stats.approximate_fog_city_army, 11)
            self.assertLess(stats.approximate_fog_army_available_total + stats.approximate_fog_city_army, 14)
        with self.subTest(mainAsserts=False):
            # 2 on main city, 9 on new city, one 2 left on board see https://generals.io/replays/glKjUk9Yo turn 65.5
            self.assertEqual(12, stats.approximate_fog_army_available_total + stats.approximate_fog_city_army)

    def test_should_not_load_map_and_double_increment_the_fog_tile_values(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_take_city_because_recognize_long_spawn_and_two_useful_cities___LjdcE2CJ9---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=0)
        self.assertIsNone(winner)

        lookup = bot.opponent_tracker.get_player_fog_tile_count_dict(enemyGeneral.player)
        self.assertNotIn(3, lookup)
        stats = bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player)
        self.assertEqual(7, stats.approximate_fog_city_army)
        self.assertEqual(5, stats.approximate_fog_army_available_total)
    
    def test_should_play_defensively_immediately_and_gather_far_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_play_defensively_immediately_and_gather_far_first__actual___ccd80U77c---0--150.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 150, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_play_defensively_immediately_and_gather_far_first___ccd80U77c---0--150.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=150)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  None  None  None  None  None  None  5,0->5,1  6,0->6,1  1,1->6,1->6,2->8,2->8,9->9,9->9,13->12,13->12,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=36)
        self.assertIsNone(winner)
    
    def test_should_infer_inbound_kill_attempt_and_defend_aggressively_after_taking_unmatched_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_infer_inbound_kill_attempt_and_defend_aggressively_after_taking_unmatched_city__attack_prepped___fMT8JMYpR---0--500.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 500, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_infer_inbound_kill_attempt_and_defend_aggressively_after_taking_unmatched_city___fMT8JMYpR---0--500.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=500)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        for i in range(35):
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        simHost.queue_player_moves_str(enemyGeneral.player, '3,9->3,13->4,13->4,14->5,14->5,16->6,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=45)
        self.assertIsNone(winner)
    
    def test_should_prevent_city_capture_when_expecting_inbound_kill_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prevent_city_capture_when_expecting_inbound_kill_threat___fMT8JMYpR---0--484.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 484, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=484)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        bot.locked_launch_point = playerMap.GetTile(9, 14)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)

        city = playerMap.GetTile(6, 13)
        self.assertOwned(-1, city, "should not be taking cities with this sketchy inbound attack line.")
    
    def test_should_not_trigger_all_in_in_unsafe_position(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_trigger_all_in_in_unsafe_position___o-nxZ1Aue---0--400.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 400, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=400)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=30)
        self.assertIsNone(winner)

        self.assertMinArmyNear(playerMap, general, general.player, minArmyAmount=70, distance=4)