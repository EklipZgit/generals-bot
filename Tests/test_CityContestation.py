from BoardAnalyzer import BoardAnalyzer
from CityAnalyzer import CityAnalyzer
from Sim.GameSimulator import GameSimulatorHost
from Strategy.WinConditionAnalyzer import WinCondition
from TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot


class CityContestationTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_centrality_distances = True
        bot.info_render_city_priority_debug_info = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_should_gather_at_enemy_city_in_sane_way(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,14')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(enemyGeneral.player, general.player, hidden=True)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=40)
        self.assertEqual(map.player_index, winner)
        self.assertNoRepetition(simHost)
        city1 = self.get_player_tile(16, 14, simHost.sim, general.player)
        city2 = self.get_player_tile(16, 15, simHost.sim, general.player)

        self.assertEqual(general.player, city1.player)
        self.assertEqual(general.player, city2.player)

    def test_should_gather_at_enemy_city__should_use_large_tiles__all_armies_off_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way__all_armies_off_cities___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,14')
        simHost.reveal_player_general(enemyGeneral.player, general.player, hidden=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=40)
        self.assertEqual(map.player_index, winner)
        self.assertNoRepetition(simHost)
        city1 = self.get_player_tile(16, 14, simHost.sim, general.player)
        city2 = self.get_player_tile(16, 15, simHost.sim, general.player)

        self.assertEqual(general.player, city1.player)
        self.assertEqual(general.player, city2.player)
        largest = self.get_player_largest_tile(simHost.sim, general.player)
        self.assertGreater(largest.army, 150, "should have gathered big boy army to hold the cities")

    def test_should_immediately_recapture_capturable_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_recapture_capturable_cities___Human.exe-TEST__90ca68f5-d013-41a2-b2b6-eb17e96c814a---1--490.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 490, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=490)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        c1 = playerMap.GetTile(10, 9)
        c2 = playerMap.GetTile(11, 10)

        self.assertEqual(general.player, c1.player)
        self.assertEqual(general.player, c2.player)
    
    def test_should_choose_city_recapture_over_defense_of_further_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_choose_city_recapture_over_defense_of_further_city___Human.exe-TEST__e31e12e0-6703-47b7-80e9-a7b5ad623338---1--491.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 491, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=491)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,7->9,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        c1 = playerMap.GetTile(10, 9)
        c2 = playerMap.GetTile(11, 10)
        c3 = playerMap.GetTile(9, 4)

        self.assertEqual(general.player, c1.player)
        self.assertEqual(general.player, c2.player)
        self.assertEqual(general.player, c3.player)

    def test_should_contest_city_with_no_looping(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_city_with_no_looping___8GfB5bKu6---1--1424.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1424, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1424)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
    
    def test_should_just_immediately_attack_city_or_expand(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_just_immediately_attack_city_or_expand___ov_IgHZBM---0--189.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 189, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=189)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)

    def test_should_immediately_gather_and_hold_this_city_before_exploring_probably(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_consider_this_defending_a_friendly_contested_city_i_think___rETyBtOqf---0--281.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 281, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 9, 1)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=281)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        city = playerMap.GetTile(3, 5)
        city.turn_captured = map.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=26)
        self.assertIsNone(winner)

        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([playerMap.GetTile(3, 8)], distance=3, player=general.player), 120, "should pre-gather at least to the closest point in the fog to bait a recapture and keep gather-prepping")
    
    def test_should_immediately_all_in_gather_hold_one_of_the_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_all_in_gather_hold_one_of_the_cities___rETyBtOqf---0--295.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 295, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 9, 1)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=295)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,3->7,5->8,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        c1 = playerMap.GetTile(3, 5)
        c2 = playerMap.GetTile(8, 5)
        c1.turn_captured = map.turn
        c2.turn_captured = map.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)

        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([playerMap.GetTile(3, 6)], distance=3, player=general.player), 80, "should pre-gather at least to the closest point in the fog to bait a recapture and keep gather-prepping")

    def test_should_intercept_51_plus_42_at_the_target_city_not_defend_2_11(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_51_plus_42_at_the_target_city_not_defend_2_11___rETyBtOqf---0--316.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 316, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=316)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->7,4->3,4->3,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        city = playerMap.GetTile(3, 5)

        self.assertEqual(general.player, city.player)

    def test_should_intercept_51_plus_42_at_the_target_city_not_defend_2_11__longer_capture_other(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_51_plus_42_at_the_target_city_not_defend_2_11___rETyBtOqf---0--316.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 316, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=316)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->7,4->3,4->3,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=14)
        self.assertIsNone(winner)

        city = playerMap.GetTile(3, 5)
        c2 = playerMap.GetTile(1, 4)

        self.assertEqual(general.player, city.player)
        self.assertEqual(general.player, c2.player)

    def test_should_intercept_51_plus_42_at_the_target_city_not_defend_2_11__longer_capture_all_3_longest(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_51_plus_42_at_the_target_city_not_defend_2_11___rETyBtOqf---0--316.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 316, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=316)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->7,4->3,4->3,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        city = playerMap.GetTile(3, 5)
        c2 = playerMap.GetTile(1, 4)
        c3 = playerMap.GetTile(8, 5)

        self.assertEqual(general.player, city.player)
        self.assertEqual(general.player, c2.player)
        self.assertEqual(general.player, c3.player)
    
    def test_should_reveal_fog_risks_while_loading_up_contested_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for enemyIndicatesTheyAreAttemptingFlank in [False, True]:
            with self.subTest(enemyIndicatesTheyAreAttemptingFlank=enemyIndicatesTheyAreAttemptingFlank):
                mapFile = 'GameContinuationEntries/should_reveal_fog_risks_while_loading_up_contested_cities___2zboMAEbs---1--311.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 311, fill_out_tiles=True)
                map.GetTile(8, 11).reset_wrong_undiscovered_fog_guess()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=311)

                if not enemyIndicatesTheyAreAttemptingFlank:
                    map.GetTile(11, 9).player = enemyGeneral.player
                    map.GetTile(11, 8).player = enemyGeneral.player
                    rawMap.GetTile(11, 9).player = enemyGeneral.player
                    rawMap.GetTile(11, 8).player = enemyGeneral.player

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '3,8->3,7->4,7->5,7->5,6')
                if enemyIndicatesTheyAreAttemptingFlank:
                    simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  10,9->11,9->11,8->11,7')

                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
                self.assertIsNone(winner)

                self.assertEqual(general.player, playerMap.GetTile(8, 11).player, 'should probe the fog while contesting the cities')


    
    def test_should_not_keep_trying_to_take_more_cities__just_defend_the_ones_you_have(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_keep_trying_to_take_more_cities__just_defend_the_ones_you_have___XDtLwOsSk---0--1062.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1062, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1062)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_keep_trying_to_take_more_cities__just_defend_the_ones_you_have")
    
    def test_should_not_loop_on_flank_defense_against_far_flank(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_on_flank_defense_against_far_flank____H2EL3yXK---1--566.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 566, fill_out_tiles=True)
        for i in range(14):
            t = map.GetTile(i, 17)
            if not t.isMountain:
                t.player = enemyGeneral.player
                t.army = 3

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=566)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        playerMap.GetTile(15, 14).turn_captured = map.turn
        playerMap.GetTile(9, 12).turn_captured = map.turn
        bot.cityAnalyzer.owned_contested_cities.add(playerMap.GetTile(15, 14))
        bot.cityAnalyzer.owned_contested_cities.add(playerMap.GetTile(9, 12))

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=50)

        self.assertNoRepetition(simHost)
    
    def test_should_recapture_city_when_enemy_runs_from_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recapture_city_when_enemy_runs_from_it___yXvXtstCP---0--249.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 249, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=249)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '18,11->18,10->15,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        city = playerMap.GetTile(19, 12)
        self.assertEqual(general.player, city.player)
    
    def test_should_defend_forward_contested_en_city_while_capping_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_forward_contested_en_city_while_capping_tiles___yXvXtstCP---0--408.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 408, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=408)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=42)
        self.assertIsNone(winner)

        city = playerMap.GetTile(14, 10)
        city2 = playerMap.GetTile(19, 12)
        city3 = playerMap.GetTile(21, 10)
        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([city, city2, city3], distance=4, player=general.player), 135)
        self.assertPlayerTileCountGreater(simHost, general.player, 100)
    
    def test_should_instantly_all_in_for_city_contestation(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_instantly_all_in_for_city_contestation___OGhsl6UbO---0--176.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 176, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=176)
        rawMap.GetTile(12, 12).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(15, 14).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(15, 16).reset_wrong_undiscovered_fog_guess()
        rawMap.generals[enemyGeneral.player] = None

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertIsNone(winner)
    
    def test_should_all_in_gather_to_hold_the_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for timespan, expectedArmy in ((35, 45), (20, 20), (30, 33)):
            with self.subTest(timespan=timespan):
                mapFile = 'GameContinuationEntries/should_all_in_gather_to_hold_the_city___ZrBVa2ccE---1--149.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 149, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, 3, 16)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=149)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=timespan)
                self.assertIsNone(winner)

                city = playerMap.GetTile(10, 14)

                self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([city], distance=7, player=general.player), expectedArmy)
    
    def test_should_not_play_city_defense_when_city_right_by_general_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_play_city_defense_when_city_right_by_general_wtf___tlcZQJVRh---1--161.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 161, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=161)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        city = playerMap.GetTile(2, 13)
        city.turn_captured = map.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertNotIn(city, bot.win_condition_analyzer.defend_cities)
    
    def test_should_not_all_in_when_superior_to_just_capture_neutral(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_all_in_when_superior_to_just_capture_neutral___Bc8hJdbOH---1--128.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 128, fill_out_tiles=True)
        enemyGeneral.army = 0

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=128)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=13)
        self.assertIsNone(winner)

        city = playerMap.GetTile(0, 11)

        self.assertEqual(general.player, city.player)

    def test_should_defend_city_after_recapture(self):
        for opponentExpands in [True, False]:
            with self.subTest(opponentExpands=opponentExpands):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_defend_city_after_recapture___glKjUk9Yo---1--149.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 149, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=149)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '7,4->7,3')
                if opponentExpands:
                    simHost.queue_player_leafmoves(enemyGeneral.player)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
                self.assertIsNone(winner)

                if not opponentExpands:
                    self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([playerMap.GetTile(7, 3)], distance=6, player=general.player), 45, "should have built up a 30 army defense of this city by this point.")
                else:
                    self.assertGreater(playerMap.players[general.player].tileCount, 55, "should have expanded to match")
    
    def test_should_not_loop_defense_wait_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_defense_wait_move___EzGh3A9qs---0--530.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 530, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=530)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        city = playerMap.GetTile(11, 9)
        self.assertEqual(general.player, city.player)

        # self.assertNoRepetition(simHost)
    
    def test_should_contest_far_city_on_nearly_even_econ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_contest_this_city_through_fog_en_tiles___SaRQmDLde---0--384.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 384, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=384)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        city = playerMap.GetTile(10, 19)
        self.assertIn(WinCondition.ContestEnemyCity, bot.win_condition_analyzer.viable_win_conditions)
        self.assertIn(city, bot.win_condition_analyzer.contestable_cities)

    def test_should_continue_to_contest_this_city_through_fog_en_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_contest_this_city_through_fog_en_tiles___SaRQmDLde---0--384.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 384, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=384)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=50)
        self.assertIsNone(winner)

        city = playerMap.GetTile(10, 19)
        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles([city], distance=4), 250)
        self.assertIn(WinCondition.ContestEnemyCity, bot.win_condition_analyzer.viable_win_conditions)
        self.assertIn(city, bot.win_condition_analyzer.contestable_cities)
        self.assertPlayerTileCountGreater(simHost, general.player, 116)
    
    def test_should_hold_enough_on_cities_to_not_lose_group(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_hold_enough_on_cities_to_not_lose_group___SIA0U-TNH---1--259.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 259, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=259)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,5->5,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        # turn 276 100 army exactly emerges from fog to take cities
        self.assertGreater(bot.sum_friendly_army_near_or_on_tiles([playerMap.GetTile(4, 5), playerMap.GetTile(5, 4)], distance=3), 100)

# 18f 13p skip1
    
    def test_should_not_attack_neutral_city_on_discover(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_attack_neutral_city_on_discover___a1fytF7_J---0--294.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 294, fill_out_tiles=True)

        map.GetTile(13, 3).army = 0
        map.GetTile(13, 3).player = -1
        map.GetTile(13, 3).army = 45
        map.GetTile(11, 3).reset_wrong_undiscovered_fog_guess()
        map.GetTile(12, 3).reset_wrong_undiscovered_fog_guess()
        map.GetTile(11, 1).reset_wrong_undiscovered_fog_guess()
        map.GetTile(10, 2).reset_wrong_undiscovered_fog_guess()
        map.GetTile(11, 2).reset_wrong_undiscovered_fog_guess()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=294)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertEqual(45, map.GetTile(13, 3).army)
    
    def test_should_not_loop_on_city_contest_offensive(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_on_city_contest_offensive___a1fytF7_J---0--465.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 465, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=465)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
    
    def test_should_not_loop_on_city_contest_offensive__v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_on_city_contest_offensive__v2___a1fytF7_J---0--474.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 474, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=474)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
    
    def test_should_not_loop_on_not_recently_captured_mid_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_to_hold_large_contestation___reoSs8lSW---0--501.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 501, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=501)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        cities = [
            playerMap.GetTile(13, 9),
            playerMap.GetTile(17, 9),
            playerMap.GetTile(19, 9),
            playerMap.GetTile(21, 6),
        ]
        # for city in cities:
        #     city.turn_captured = map.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=30)
        self.assertIsNone(winner)
        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles(cities), 300)

        self.assertNoRepetition(simHost)

    def test_should_gather_to_hold_large_contestation(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_to_hold_large_contestation___reoSs8lSW---0--501.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 501, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=501)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        cities = [
            playerMap.GetTile(13, 9),
            playerMap.GetTile(17, 9),
            playerMap.GetTile(19, 9),
            playerMap.GetTile(21, 6),
        ]
        for city in cities:
            city.turn_captured = map.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=30)
        self.assertIsNone(winner)
        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles(cities), 300)
    
    def test_should_not_defend_preemptive_when_would_be_behind_on_econ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_defend_preemptive_when_would_be_behind_on_econ___F-bhF7SYZ---1--185.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 185, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=185)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(-6, simHost)

    def test_should_not_pull_forward_armies_back_to_cities__esp_when_not_winning_on_economy(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_pull_forward_armies_back_to_cities__esp_when_not_winning_on_economy___b4ucQw2N6---1--453.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 453, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 1, 14)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=453)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        point = playerMap.GetTile(17, 7)
        # self.assertEqual(bot.locked_launch_point, point, "17,7 should become the launch point despite the backwards cities and general that are all fully safe behind the choke.")

        self.assertEqual(107, playerMap.players[general.player].tileCount, "should have capped tiles the whole time...")

    def test_should_not_gather_small_attacks_to_unknown_offensive_targets(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_gather_small_attacks_to_unknown_offensive_targets___Hn8ec1Na9---0--280.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 280, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=280)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost), 24, 'should have expanded mainly')
    
    def test_should_just_kill_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_just_kill_city___HoN_D3CTW---0--326.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 326, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=326)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        cityA = playerMap.GetTile(12, 17)
        cityB = playerMap.GetTile(14, 17)

        self.assertOwned(general.player, cityA)
        self.assertOwned(general.player, cityB)
    
    def test_should_contest_city_not_intercept_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_city_not_intercept_it___sOP9TRWO6---0--467.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 467, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=467)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=18)
        self.assertIsNone(winner)

        city = playerMap.GetTile(4, 9)
        self.assertOwned(general.player, city)

    def test_should_instantly_all_in_cities_in_this_position_out_of_necessity(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_instantly_all_in_cities_in_this_position_out_of_necessity___oN-qqacaD---0--214.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 214, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 16, 14)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=214)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.curPath = None
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertIsNone(winner)

        self.assertGreater(playerMap.players[general.player].cityCount, 4)
        self.assertLess(playerMap.players[enemyGeneral.player].cityCount, 4)

    def test_should_make_one_move_city_capture_when_no_instant_recap(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_make_one_move_city_capture_when_no_instant_recap___1_HRYfRkx---1--204.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 204, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=204)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        city = playerMap.GetTile(5, 8)
        army = bot.get_army_at(city)
        army.last_moved_turn = 198
        army.expectedPaths = []

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertOwned(general.player, city)

    def test_should_sit_on_economic_lead_city_contest(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_sit_on_economic_lead_city_contest___sw1XyL-vy---0--307.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=307)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
        city = playerMap.GetTile(13, 6)

        self.assertGreater(city.army, 100)

# 22f 18p
# 21f 20p
# 18f 23p
# 21f 21p
# 21f 22p
# 28f 16p (interception breaking things probably)
    
    def test_should_gather_to_potentially_holdable_contested_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_to_potentially_holdable_contested_city___fgExr3xbL---0--536.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 536, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=536)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_gather_to_potentially_holdable_contested_city")
    
    def test_shouldnt_gather_at_unholdable_city_in_even_game(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_gather_at_unholdable_city_in_even_game___wCipq_zxN---0--978.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 978, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=978)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertNotIn('GC 12,2', bot.viewInfo.infoText)

    def test_should_continue_to_contest_all_the_way_to_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_contest_all_the_way_to_capture___3wy8nY6CJ---0--293.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 293, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=293)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,16->6,17  4,11->4,10->6,10->6,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertNoFriendliesKilled(map, general)

        city = playerMap.GetTile(4, 11)
        self.assertOwned(general.player, city)
    
    def test_should_contest_en_city_but_then_immediately_recapture_own_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_en_city_but_then_immediately_recapture_own_city___pRJvM4wa2---1--228.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 228, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=228)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,6->10,3->12,3->12,2->15,2->15,3')
        simHost.queue_player_moves_str(general.player, '13,13->12,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        cityA = playerMap.GetTile(12, 13)

        def betweenTurnCheck():
            if playerMap.turn > 229:
                self.assertOwned(general.player, cityA)

        simHost.run_between_turns(betweenTurnCheck)
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertNoFriendliesKilled(map, general)

        cityB = playerMap.GetTile(15, 3)
        self.assertOwned(general.player, cityB)

    def test_should_continue_to_contest_top_city_as_it_is_far_from_enemy_general_and_should_retake_the_land(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_contest_top_city_as_it_is_far_from_enemy_general_and_should_retake_the_land___g8BCWKV3x---0--640.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 640, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=640)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_continue_to_contest_top_city_as_it_is_far_from_enemy_general_and_should_retake_the_land")
    
    def test_should_continue_to_contest_cities_or_kill_rapidly_in_massive_army_lead_but_econ_deficit(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_contest_cities_or_kill_rapidly_in_massive_army_lead_but_econ_deficit___B9nnAUGi_---0--339.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 339, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=339)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '2,11->3,11')
        simHost.queue_player_moves_str(general.player, '9,8->8,8')
        simHost.queue_player_moves_str(enemyGeneral.player, '0,12->1,12->1,11->2,11->2,10->3,10->3,11  4,14->4,14->3,14->3,11')
        # proof
        # simHost.queue_player_moves_str(general.player, '8,8->7,8->7,11->3,11')

        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_defend_city_in_advance_despite_general_threat_overriding(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_in_advance_despite_general_threat_overriding___ukTs1b7Ls---0--386.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 386, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=386)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_defend_city_in_advance_despite_general_threat_overriding")
    
    def test_should_be_able_to_recapture_painfully_fine_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_able_to_recapture_painfully_fine_city___A9vJhurgf---0--209.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 209, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=209)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,8->9,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertNoFriendliesKilled(map, general)

        city = playerMap.GetTile(9, 9)
        self.assertOwned(general.player, city, 'should immediately recapture this not loop')
    
    def test_should_contest_over_taking_super_unsafe_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_over_taking_super_unsafe_city___rNZUzIzDB---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_contest_over_taking_super_unsafe_city")
    
    def test_should_prep_for_the_inevitable_attack_on_at_risk_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prep_for_the_inevitable_attack_on_at_risk_city___rNZUzIzDB---1--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=250)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_prep_for_the_inevitable_attack_on_at_risk_city")
