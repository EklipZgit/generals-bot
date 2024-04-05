from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class DefenseUnitTests(TestBase):
    def test_does_not_explode_next_to_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ExplodesNextToGeneral.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        # self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        # the initial gather scan was enough to blow up, dont need asserts

    def test_finds_perfect_gather_defense__multi_knapsack_fails(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_MultiKnapsackFailed.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        # self.enable_search_time_limits_and_disable_debug_asserts()
        self.disable_search_time_limits_and_enable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,7->1,6->1,5->1,4->1,3->1,2')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(4, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertGreater(valueGathered, 27)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(4, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)

    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path__greedy(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_no_20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,10->1,9->1,8->1,7->1,6->1,5->1,4->1,3->1,2')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_target_tiles_greedy([enemyGeneral], 0.1, gatherTurns=30, includeGatherTreeNodesThatGatherNegative=True, targetArmy=70)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertGreater(valueGathered, 75)

    def test_should_recognize_threat_over_ally_tiles_as_not_subtracting_by_2_each_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_threat_over_ally_tiles_as_not_subtracting_by_2_each_move___77V8baiqp---3--185.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 185, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=185)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyAllyGen.player, '9,15->8,15->8,13->7,13->7,10->6,10')
        simHost.queue_player_moves_str(allyGen.player, '9,9->9,8->8,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        threat = bot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertGreater(threat.threatValue, 7, 'should have 8 threat')
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)
