from BoardAnalyzer import BoardAnalyzer
from CityAnalyzer import CityAnalyzer
from Sim.GameSimulator import GameSimulatorHost
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

        self.assertGreater(bot.sum_player_army_near_or_on_tiles([playerMap.GetTile(3, 8)], distance=3, player=general.player), 120, "should pre-gather at least to the closest point in the fog to bait a recapture and keep gather-prepping")
    
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

        self.assertGreater(bot.sum_player_army_near_or_on_tiles([playerMap.GetTile(3, 6)], distance=3, player=general.player), 80, "should pre-gather at least to the closest point in the fog to bait a recapture and keep gather-prepping")

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
        self.assertIsNone(winner)

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
        self.assertGreater(bot.sum_player_army_near_or_on_tiles([city, city2, city3], distance=4, player=general.player), 135)
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
        for timespan, expectedArmy in ((35, 45), (15, 20), (25, 33)):
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

                self.assertGreater(bot.sum_player_army_near_or_on_tiles([city], distance=4, player=general.player), expectedArmy)
