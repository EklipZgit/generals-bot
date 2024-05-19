import SearchUtils
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class OffensiveMicroTests(TestBase):
    def test_should_avoid_army_by_looping_downward_and_right(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_avoid_army_by_looping_downward_and_right___TooE-srNn---1--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        self.skipTest("TODO add asserts for should_avoid_army_by_looping_downward_and_right")

    def test_should_not_prefer_intercept_when_can_just_tile_trade_while_ahead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for enPath, proof in [
            ('12,5->11,5->11,6  19,5->19,6  11,6->12,6->12,7->11,7', '11,7->12,7->12,8z  12,7->12,6  12,8->16,8'),
            ('12,5->11,5->11,6->11,7->12,7->12,8', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
            ('12,5->8,5->8,10', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
            ('12,5->11,5->11,7->12,7->12,8->14,8', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
        ]:
            with self.subTest(enPath=enPath):
                mapFile = 'GameContinuationEntries/should_not_prefer_intercept_when_can_just_tile_trade_while_ahead___TooE-srNn---1--145.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 145, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=145)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                simHost.queue_player_moves_str(general.player, proof)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
                self.assertIsNone(winner)

                self.assertTileDifferentialGreaterThan(3, simHost)

    def test_should_split_to_guarantee_territory_capture_to_end_of_round(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_to_guarantee_territory_capture_to_end_of_round___aKuLkFq66---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertGreaterEqual(12, playerMap.GetTile(12, 11).army, 'should have split to cap land even at slight econ loss when ahead on round caps')
        self.assertGreaterEqual(12, playerMap.GetTile(11, 11).army, 'should have split to cap land even at slight econ loss when ahead on round caps')

    def test_should_not_split_randomly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_split_randomly___-Zrosee5X---0--81.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 81, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

    def test_should_race_when_cant_defend_and_high_kill_probability(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_race_when_cant_defend_and_high_kill_probability___1lZK5xvmU---1--342.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 342, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=342)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_race_when_cant_defend_and_high_kill_probability")
    
    def test_should_not_dive_general_instead_of_capturing_cities_when_very_unlikely_to_kill(self):
        # TODO: shift finding king-kills out into something that gets shoved in the RoundPlanner
        # TODO: king kill dives should include a kill likelihood, which heavily weights their perceived econValue (especially given that if they dont kill they allow recaptures and should be negatively weighted as such).
        # TODO: enemy cities defensability should be calculated by WinConditionAnalyzer, and we should know these two cities are harder for opp to defend based on his general position.
        # TODO: city quick-kills should also be shoved into the round planner. In this case we should clearly see that the expected payoff for holding two cities far from the players other cities is much higher than the expected payoff from a general dive.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dive_general_instead_of_capturing_cities_when_very_unlikely_to_kill___9fI5z--ww---0--510.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 510, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=510)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        army = bot.armyTracker.armies[playerMap.GetTile(16, 5)]
        army.expectedPaths.append(SearchUtils.a_star_find([army.tile], general))

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        city1 = playerMap.GetTile(10, 6)
        city2 = playerMap.GetTile(10, 4)

        self.assertOwned(general.player, city1)
        self.assertOwned(general.player, city2)
    
    def test_should_not_dive_general_instead_of_capturing_cities_when_very_unlikely_to_kill__longer(self):
        # TODO why the f is this not reproducing...?
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dive_general_instead_of_capturing_cities_when_very_unlikely_to_kill__longer___9fI5z--ww---0--509.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 509, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=509)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,5->4,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        # bot.opponent_tracker.current_team_cycle_stats[enemyGeneral.player].approximate_fog_city_army -= 10
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        city1 = playerMap.GetTile(10, 6)
        city2 = playerMap.GetTile(10, 4)

        self.assertOwned(general.player, city1)
        self.assertOwned(general.player, city2)
    
    def test_should_not_find_illegitimate_depth_increasing_killpaths(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for genReduction in [1, 0]:
            with self.subTest(genReduction=genReduction):
                mapFile = 'GameContinuationEntries/should_not_find_illegitimate_depth_increasing_killpaths___Zf2sQKKX0---1--150.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 150, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=150)
                enemyGeneral.army -= genReduction
                rawMap.GetTile(enemyGeneral.x, enemyGeneral.y).army -= genReduction

                self.begin_capturing_logging()
                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)
                killMove, kingKillPath = bot.check_for_king_kills_and_races(bot.threat)

                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
                self.assertNoFriendliesKilled(map, general)

                self.assertIsNone(killMove, 'should not have found a depth increasing killpath that does not kill....')
                self.assertIsNone(kingKillPath, 'should not have found a depth increasing killpath that does not kill....')
