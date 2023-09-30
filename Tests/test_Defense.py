from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import TILE_MOUNTAIN


class DefenseTests(TestBase):

    def test_finds_perfect_gather_defense_in_previously_failed_scenario(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, player_index=1)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=False)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

    def test_should_not_spin_on_defense_gathers_against_sitting_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_spin_on_defense_gathers_against_sitting_cities___BelzKSdhh---b--275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 275)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=150)
        self.assertNoRepetition(simHost)

    def test_finds_perfect_gather_defense__small_moves_into_path__against_threat_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(6, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(6, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for finds_perfect_gather_defense__small_moves_into_path__against_threat_path

    def test_finds_perfect_gather_defense__small_moves_into_path__lower_value_final_move__against_threat_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__Smaller_final_move.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(6, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(6, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)


    def test_finds_perfect_gather_defense__small_moves_into_path__knapsack_gather_breaks(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__KnapsackGatherBreaks.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(2, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(2, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)


    def test_finds_perfect_gather_defense__small_moves_into_path__knapsack_gather_breaks_simpler(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__KnapsackGatherBreaks_Simpler.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        # self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(2, threat.turns)

        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        self.begin_capturing_logging()
        # move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path_greedy(
        #     threat,
        #     gatherMax=True,
        #     shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=10)
        self.assertIsNone(winner)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(2, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)


    def test_finds_perfect_gather_defense__small_moves_into_path__knapsack_gather_breaks_simpler_with_enemy(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__KnapsackGatherBreaks_Simpler_WithEnemy.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(3, threat.turns)

        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        self.begin_capturing_logging()
        # move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path_greedy(
        #     threat,
        #     gatherMax=True,
        #     shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=10)
        self.assertIsNone(winner)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(3, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)

    def test_does_not_explode_next_to_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/GatherScenarios/ExplodesNextToGeneral.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        # self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        # the initial gather scan was enough to blow up, dont need asserts


    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        self.assertGreater(valueGathered, 54)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(7, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

    def test_finds_perfect_gather_defense__multi_knapsack_fails(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_MultiKnapsackFailed.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        # self.enable_search_time_limits_and_disable_debug_asserts()
        self.disable_search_time_limits_and_enable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        #
        # if debugMode:
        #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.1, turns=15)
        #     self.assertIsNone(winner)

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


    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path__no_20(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_no_20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
            threat,
            gatherMax=True,
            shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(7, turnsUsed)
        self.assertGreaterEqual(valueGathered, threat.threatValue)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=10)
        self.assertIsNone(winner)

    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path__greedy(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_no_20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

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
    
    def test__should_realize_it_can_save__exact_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/does_not_fail_defense___BgVc48Chn---b--792.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 792)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=792)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,6->16,6->16,5->16,4->16,3->16,2->16,1->15,1')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes

        self.assertGreater(valueGathered, threat.threatValue)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=8)
        self.assertIsNone(winner)

    def test__should_realize_it_can_save_one_move_behind(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/does_not_fail_defense___BgVc48Chn---b--792.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 793)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=793)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,6->16,6->16,5->16,4->16,3->16,2->16,1->15,1')
        simHost.queue_player_moves_str(general.player, '16,1->15,1')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes

        self.assertGreater(valueGathered, threat.threatValue)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=13)
        self.assertIsNone(winner)

    def test__should_realize_it_can_save_one_move_behind__blocked_main_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/does_not_fail_defense___BgVc48Chn---b--792.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 793)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=793)
        rawMap.convert_tile_to_mountain(rawMap.GetTile(14, 1))
        map.convert_tile_to_mountain(map.GetTile(14, 1))

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,6->16,6->16,5->16,4->16,3->16,2->16,1->15,1')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.engine_army_nearby_tiles_range = 8

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)

        self.begin_capturing_logging()

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=10)
        self.assertIsNone(winner)

    def test_should_detect_chase_kill_defense_with_scrim__passes_actual_threat_value_through_scrim(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_detect_chase_kill_defense_with_scrim___Blsh62-p3---b--641.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 641)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=641)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,2->6,1->6,0->5,0')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)

    def test_should_detect_chase_kill_defense_with_scrim(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_detect_chase_kill_defense_with_scrim___Blsh62-p3---b--641.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 641)
        # HACK general army higher than the real test because currently we dont pass the actual threat value through the scrim engine so force it to recognize that the chase is valid save
        general.army += 2

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=641)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_threat_killer_move_and_then_not_perform_the_second_priority_threat_killer_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/Should_not_threat_killer_move_and_then_not_perform_the_second_priority_threat_killer_move___rl9fntGT3---b--298.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 298)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=298)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        #19,15, 19,16, 20,16
        simHost.queue_player_moves_str(enemyGeneral.player, "19,15 -> 19,16 -> 20,16")

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

    def test_should_detect_enemy_kill_threat__2_6__at__4_5(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_detect_enemy_kill_threat__2_5__at__4_5___BxBqC4YT3---b--807.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 807, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=807)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '2,6->2,5->2,4->2,3->2,2->2,1->2,0')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_detect_enemy_kill_threat__2_5__at__4_5
    
    def test_should_not_loop_forever_defense_gathering(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_loop_forever_defense_gathering___EklipZ_ai-rx8fCvt63---b--216.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 216, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=216)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=25)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=2)
    
    def test_should_defend_self(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_self___Sgc9eptT3---a--343.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,14->8,14->8,15->7,15->7,16->6,16->5,16->4,16')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=50)
        self.assertIsNone(winner)

        # TODO add asserts for should_defend_self
    
    
    def test_should_not_sit_and_die_against_incoming_attack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_sit_and_die_against_incoming_attack___Hex3iUqpn---a--478.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 478, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=478)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, "9,7->9,8->9,9->9,10->9,11->9,12->9,13->8,13->7,13->7,14->7,15->7,16->7,17->7,18")
        # this expansion move is what gets it killed kinda, but it should still save. Ideally it should never make this move, but force it to to repro the death.
        simHost.queue_player_moves_str(general.player, '10,12->11,12')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        self.get_player_tile(general.x, general.y, simHost.sim, enemyGeneral.player).army = 2

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=50)
        self.assertIsNone(winner)
    
    def test_should_barely_save_against_no_known_king_loc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_barely_save_against_no_known_king_loc___SepnLTq6h---b--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,8->5,8->4,8->4,7->3,7->3,8->2,8')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_make_nonsense_scrim_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_make_nonsense_scrim_move___Hxp3ym3Th---b--383.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 383, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=383)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,5->6,6->6,7->6,8->6,9->6,10->6,11->6,12->6,13')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_make_nonsense_scrim_move
    
    def test_should_always_make_furthest_defense_gather_move_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_always_make_furthest_defense_gather_move_first___HgshlO-0n---b--441.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 441, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=441)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_allow_army_to_pass(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_allow_army_to_pass___uOUignesH---0--280.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 280, fill_out_tiles=True)
        enemyGeneral.isGeneral = False
        oldArmy = enemyGeneral.army
        enemyGeneral.army = 1
        enemyGeneral = map.GetTile(3, 16)
        enemyGeneral.player = (general.player + 1) % 2
        enemyGeneral.isGeneral = True
        enemyGeneral.army = oldArmy
        map.generals[enemyGeneral.player] = enemyGeneral

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=282)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,11->6,11->5,11->5,10->5,9->5,8->5,7->5,6->4,6->3,6->3,5->3,4')
        simHost.queue_player_moves_str(general.player, '6,11->6,10')

        t1 = self.get_player_tile(8,13, simHost.sim, general.player)
        t2 = self.get_player_tile(9,13, simHost.sim, general.player)
        t1.player = enemyGeneral.player
        t2.player = enemyGeneral.player

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.1, turns=15)
        self.assertIsNone(winner)
    
    def test_should_gather__5_14__into_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather__5_14__into_threat___XwyNqjQpO---1--341.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 341, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=341)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,13->5,14->5,15->5,16->6,16->7,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=6)
        self.assertIsNone(winner)

    def test_should_quickly_recapture_city_after_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather__5_14__into_threat___XwyNqjQpO---1--341.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 341, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=341)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,13->5,14->5,15->5,16->6,16->7,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=12)
        self.assertIsNone(winner)

        city = self.get_player_tile(5, 12, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)


    def test_should_correctly_gather_outer_edges_and_should_not_include_impossible_gather_combination(self):
        # shouldn't move that 3 tile first, needs to detect that the opp can kill from left side of general instead of just top and see it has less moves than it thinks...?
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_die___8_9nCLDQr---1--432.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 432, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=432)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,12->11,12->11,13->11,14->11,15->12,15->13,15->13,16->13,17->14,17')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_still_catch_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_still_catch_threat___tuG18hO5s---0--288.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 288, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=288)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,2->10,2->10,1->11,1')
        # simHost.queue_player_moves_str(general.player, '10,4->10,3->10,2->10,1')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=5)
        self.assertIsNone(winner)
    
    def test_should_be_able_to_retake_cities_despite_spawning_in_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_be_able_to_retake_cities_despite_spawning_in_choke___Wn-dFE3e9---0--262.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 262, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=262)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=10)
        self.assertIsNone(winner)

        otherSideOfChokeCity = self.get_player_tile(13, 1, simHost.sim, general.player)
        self.assertEqual(general.player, otherSideOfChokeCity.player)
    
    def test_should_attempt_to_finish_threat_gath_at_distance(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attempt_to_finish_threat_gath_at_distance___pCCBjXEVT---0--247.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 247, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=247)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,10->6,10->6,11->6,12->6,13->6,14->6,15')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=10)
        self.assertIsNone(winner)
