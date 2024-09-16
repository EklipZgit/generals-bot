import DebugHelper
import Gather
from Gather import GatherDebug
from MapMatrix import MapMatrixSet, MapMatrix
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.tile import TILE_MOUNTAIN, TILE_EMPTY
from bot_ek0x45 import EklipZBot


class DefenseTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        bot.info_render_centrality_distances = True
        Gather.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True

        return bot

    def test_finds_perfect_gather_defense_in_previously_failed_scenario(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, player_index=1)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,10->6,9->7,9->7,8->8,8')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

    def test_should_not_spin_on_defense_gathers_against_sitting_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_spin_on_defense_gathers_against_sitting_cities___BelzKSdhh---b--275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 275, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=20)
        self.assertNoRepetition(simHost, minForRepetition=3)

    def test_finds_perfect_gather_defense__small_moves_into_path__knapsack_gather_breaks_simpler_with_enemy(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__KnapsackGatherBreaks_Simpler_WithEnemy.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,6->1,5->1,4->1,3->1,2')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=5)
        self.assertIsNone(winner)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(3, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
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
        simHost.queue_player_moves_str(enemyGeneral.player, '1,5->1,4->1,3->1,2')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=5)
        self.assertIsNone(winner)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(2, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)

    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,10->1,9->1,8->1,7->1,6->1,5->1,4->1,3->1,2')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=12)
        self.assertIsNone(winner)

    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path__no_20(self): # INT BREAKS
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_no_20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,10->1,9->1,8->1,7->1,6->1,5->1,4->1,3->1,2')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

    def test_finds_perfect_gather_defense__small_moves_into_path__against_threat_path(self): # INT BREAKS
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

        simHost.queue_player_moves_str(enemyGeneral.player, '1,9->1,8->1,7->1,6->1,5->1,4->1,3->1,2')
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=15)
        self.assertIsNone(winner)

    def test_finds_perfect_gather_defense__small_moves_into_path__lower_value_final_move__against_threat_path(self):  # INT BREAKS
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__Smaller_final_move.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

        simHost.queue_player_moves_str(enemyGeneral.player, '1,9->1,8->1,7->1,6->1,5->1,4->1,3->1,2')
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
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,5->1,4->1,3->1,2')

        ekBot = simHost.bot_hosts[general.player].eklipz_bot
        ekBot.select_move()

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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=5)
        self.assertIsNone(winner)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)

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
        ekBot.select_move()

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
        ekBot.select_move()

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
        ekBot.select_move()
        ekBot.engine_army_nearby_tiles_range = 8

        threat = ekBot.dangerAnalyzer.fastestThreat
        self.assertIsNotNone(threat)

        self.begin_capturing_logging()

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=10)
        self.assertIsNone(winner)

    def test_should_detect_chase_kill_defense_with_scrim__passes_actual_threat_value_through_scrim(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_detect_chase_kill_defense_with_scrim___Blsh62-p3---b--641.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 641)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=641)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,2->6,1->6,0->5,0')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=5)
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
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,2->6,1->6,0->5,0')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=5)
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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=5)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=8)
        self.assertIsNone(winner)
    
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=20)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=2)
    
    def test_should_defend_self(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_defend_self___Sgc9eptT3---a--343.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,14->8,14->8,15->7,15->7,16->6,16->5,16->4,16')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_defend_self")

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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)
    
    def test_should_barely_save_against_no_known_king_loc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_barely_save_against_no_known_king_loc___SepnLTq6h---b--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,8->5,8->4,8->4,7->3,7->3,8->2,8')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)
    
    def test_should_always_make_furthest_defense_gather_move_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for has2_14Interceptable in [True, False]:
            with self.subTest(has2_14Interceptable=has2_14Interceptable):
                mapFile = 'GameContinuationEntries/should_always_make_furthest_defense_gather_move_first___HgshlO-0n---b--441.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 441, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=441)
                if has2_14Interceptable:
                    map.GetTile(1, 14).army = 6
                    rawMap.GetTile(1, 14).army = 6

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '6,15->0,15')

                # alert enemy of the player general
                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=7)
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_gather__5_14__into_threat___XwyNqjQpO---1--341.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 341, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=341)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,13->5,14->5,15->5,16->6,16->7,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=6)
        self.assertIsNone(winner)

    def test_should_quickly_recapture_city_after_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_gather__5_14__into_threat___XwyNqjQpO---1--341.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 341, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=341)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,13->5,14->5,15->5,16->6,16->7,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=12)
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
        simHost.queue_player_moves_str(enemyGeneral.player, '10,12->11,12->11,13->11,14->11,15->12,15->13,15->13,16->14,16->14,17')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=11)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=5)
        self.assertIsNone(winner)
    
    def test_should_be_able_to_retake_cities_despite_spawning_in_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_attempt_to_finish_threat_gath_at_distance___pCCBjXEVT---0--247.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 247, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=247)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,10->6,10->6,11->6,12->6,13->6,14->6,15')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 70)
    
    def test_should_not_sit_and_die_with_defendable_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_sit_and_die_with_defendable_path___nobTnyanX---0--127.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 127, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=127)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,8->13,9->13,10->13,11->14,11->15,11->16,11->16,12->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

    def test_should_not_crash_for_some_weird_reason(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_crash_for_some_weird_reason___vCc5mMfvX---0--225.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 225, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=225)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,7->0,7->0,8->0,9->0,10->0,11->0,12->0,13->0,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.curPath = Path()
        playerMap = simHost.get_player_map(general.player)
        bot.curPath.add_next(playerMap.GetTile(1, 14))
        bot.curPath.add_next(playerMap.GetTile(1, 13))

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=10)
        self.assertIsNone(winner)
    
    def test_should_protect_city_not_just_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_gather_into_threat___XAIaeetAk---0--383.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 383, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=383)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,13->9,13->8,13->7,13->6,13->6,14->5,14->4,14->3,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=8)
        self.assertIsNone(winner)
        city = self.get_player_tile(5, 14, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_make_move_away_from_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_make_move_away_from_threat___Jl-05WKs2---0--654.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 655, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=655)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,8->6,8->7,8->8,8->9,8->10,8->10,7->10,6->10,5->11,5->11,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=11)
        self.assertIsNone(winner)
    
    def test_should_lock_tiles_that_intercept_threat_early_because_moving_them_will_still_result_in_death(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_lock_tiles_that_intercept_threat_early_because_moving_them_will_still_result_in_death___k6dXS2cLO---unk--89.txtmap'
        map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=89)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_lock_tiles_that_intercept_threat_early_because_moving_them_will_still_result_in_death")
    
    def test_should_defend_self_against_threat_closer_to_teammate(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for threatAttacksSelf in [False, True]:
            for mountainOn11_15 in [True, False]:
                with self.subTest(threatAttacksSelf=threatAttacksSelf, mountainOn11_15=mountainOn11_15):
                    mapFile = 'GameContinuationEntries/should_defend_self_against_threat_closer_to_teammate___eAI-LARB8---3--140.txtmap'
                    map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=140)

                    if not mountainOn11_15:
                        m = map.GetTile(11, 15)
                        m2 = rawMap.GetTile(11, 15)
                        m.isMountain = False
                        m2.isMountain = False
                        m.tile = TILE_EMPTY
                        m2.tile = TILE_EMPTY

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                    if threatAttacksSelf:
                        if mountainOn11_15:
                            simHost.queue_player_moves_str(enemyGeneral.player, '13,12->12,12->11,12->11,13->11,14->12,14->12,15->12,16->11,16->11,17->10,17')
                        else:
                            simHost.queue_player_moves_str(enemyGeneral.player, '13,12->12,12->11,12->11,13->11,14->11,15->11,16->11,17->10,17')
                    else:
                        simHost.queue_player_moves_str(enemyGeneral.player, '13,12->12,12->11,12->11,13->10,13->9,13->8,13')
                    bot = self.get_debug_render_bot(simHost, general.player)
                    bot.no_file_logging = False
                    playerMap = simHost.get_player_map(general.player)

                    # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=10)
                    self.assertNoFriendliesKilled(map, general, allyGen=allyGen)
    
    def test_should_defend_ally_in_2v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_defend_ally_in_2v2___brs1WYHiG---0--132.txtmap'
        map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=132)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enAllyGen.player, '16,8->15,8->14,8->13,8->12,8->11,8->10,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=12)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_against_defensable_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_defend_against_defensable_threat___mSR6Tg1Wg---2--586.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 586, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=586)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,10->10,10->11,10->12,10->13,10->13,11->13,12->14,12->15,12->16,12->16,13->16,14->17,14->18,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=13)
        self.assertIsNone(winner)
    
    def test_should_just_go_intercept_army_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for shouldMove in [False, True]:
            for isOppositeMountain in [False, True]:
                with self.subTest(shouldMove=shouldMove, isOppositeMountain=isOppositeMountain):
                    mapFile = 'GameContinuationEntries/should_just_go_intercept_army_wtf___Sg9Q6gUZa---1--186.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 186, fill_out_tiles=True)

                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=186)
                    if not isOppositeMountain:
                        map.GetTile(10, 6).army = 1
                        map.GetTile(10, 5).army = 51
                        rawMap.GetTile(10, 6).army = 1
                        rawMap.GetTile(10, 5).army = 51

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                    if shouldMove:
                        moves = '10,5->10,4->10,3->9,3'
                        if isOppositeMountain:
                            moves = f'10,6->{moves}'
                        simHost.queue_player_moves_str(enemyGeneral.player, moves)
                    else:
                        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=14)
                    self.assertIsNone(winner)

                    self.assertPlayerTileCountGreater(simHost, general.player, tileCountLessThanPlayers=56)
                    enTile = self.get_player_tile(10, 5, simHost.sim, general.player)
                    self.assertEqual(general.player, enTile.player)

    def test_should_not_defense_loop_let_army_engine_make_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_defense_loop_let_army_engine_make_moves___aasv_D-jf---1--550.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 550, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=550)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost, minForRepetition=3)
    
    def test_should_not_over_delay_defense_when_intercepting_near_threat_tile_itself(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_over_delay_defense_when_intercepting_near_threat_tile_itself___Powxzahpv---0--132.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=132)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,3->15,3->15,2->15,1->14,1->14,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=10)
        self.assertIsNone(winner)
    
    def test_should_gather_tiles_in_the_right_order_to_save__cities_last_and_choke_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_tiles_in_the_right_order_to_save__cities_last_and_choke_first___BlHzb_IZa---0--292.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 292, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=292)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,3->7,3->7,0->8,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)
    
    def test_should_commit_to_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_commit_to_defense___wIG-a2l63---0--282.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 282, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=282)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,8->10,8->10,8->10,7->9,7  None  None  None  9,7->10,7->10,8->11,8->12,8->12,9->11,9->11,10->10,10->9,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.curPath = Path()
        playerMap = simHost.get_player_map(general.player)
        bot.curPath.add_next(playerMap.GetTile(9, 15))
        bot.curPath.add_next(playerMap.GetTile(8, 15))
        bot.curPath.add_next(playerMap.GetTile(7, 15))

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=18)
        self.assertIsNone(winner)
        self.assertPlayerTileCountGreater(simHost, general.player, 72)
        self.assertLess(playerMap.players[enemyGeneral.player].score, 180, "should have captured the enemy tile costing opp 70 army (they gain 70 from turn 300)")
    
    def test_should_not_do_dumb_threat_killer_move_but_also_defend(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_do_dumb_threat_killer_move_but_also_defend___SxAsLDP-6---1--676.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 676, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=676)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,8->10,9->9,9->9,10->8,10->7,10->7,11->7,12->7,13->6,13->5,13->5,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 109)

    def test_should_not_kill_vision_threat_with_general_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_kill_vision_threat_with_general_lol___fHVoYEYIm---2--281.txtmap'

        for i in range(5):
            map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 281, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=281)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, '18,6->17,6->17,5')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=4)
            self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_not_early_gather_defense_leaf_dist_move__should_intercept_fog_threat_runaround(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_early_gather_defense_leaf_dist_move___FzaOG3k1f---0--410.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 410, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=410)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,1->9,0->8,0->7,0->6,0->5,0->4,0->3,0->3,1->3,2->3,3->3,4->3,5->3,6->3,7->3,8->4,8->4,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=20)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_not_defense_loop(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_defense_loop___5v5zuNmVX---3--266.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 266, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=266)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
        self.assertNoFriendliesKilled(map, general, allyGen)

        city = self.get_player_tile(20, 9, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)

    def test_should_not_gather_city_too_early(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_gather_city_too_early___Bq7qaO0OI---0--437.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 437, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=437)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '19,13->18,13->18,14->18,15->18,16->18,17')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=10)
        self.assertIsNone(winner)

    def test_should_abandon_defense_when_opp_knows_king_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_abandon_defense_when_opp_knows_king_location___Bq7qaO0OI---0--432.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 432, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=432)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '20,9->19,9->19,10->19,11->19,12->19,13->18,13->18,14->18,15->18,16->18,17')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        genPlayer = general.player
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=10)
        self.assertEqual(genPlayer, winner)

    def test_should_not_loop_defense_gather_just_capture_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_defense_gather_just_capture_city___Sg19XabzT---0--710.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 710, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=710)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=6)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
        city = self.get_player_tile(7, 16, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_loop_just_intercept_army_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_loop_just_intercept_army_wtf___fQA15Ee2k---0--241.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=241)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.targetingArmy = bot.get_army_at_x_y(1, 4)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=5)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
    
    def test_should_not_loop_defense_vs_city_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_defense_vs_city_capture___8nlMn9w_f---0--408.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 408, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=408)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.50, turns=10)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
    
    def test_should_not_wait_to_defend_and_attack_with_late_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_wait_to_defend_and_attack_with_late_tiles___rTXxWmNy0---1--177.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 177, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=177)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,8->13,8->12,8->11,8->10,8->9,8->8,8->7,8->6,8->5,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=10)
        self.assertIsNone(winner)
    
    def test_should_not_loop_in_front_of_en_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_in_front_of_en_city___dq3qt0vH7---0--533.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 533, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=533)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
    
    def test_should_defend_critical_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_critical_cities___XXMw2d0tO---0--191.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 191, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=191)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_defend_critical_cities")
    
    def test_should_not_wait_to_pull_backward_army_on_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_wait_to_pull_backward_army_on_defense___Bggjt8HEa---1--484.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 484, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=484)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,10->16,13->15,13->15,17->13,17')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)
    
    def test_should_not_die_after_planning_impossible_gather_sequence(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_die_after_planning_impossible_gather_sequence___Sl4jmdHEp---1--236.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 236, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=236)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,7->11,3->7,3->7,2->6,2->6,1')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertIsNone(winner)
    
    def test_should_defend_city_and_intercept_army_not_expand(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_and_intercept_army_not_expand___5h3DK65bX---1--330.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 330, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=330)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '2,13->1,13->1,11->2,11->2,8->3,8->3,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        city = playerMap.GetTile(3, 7)
        self.assertEqual(general.player, city.player)

    def test_should_defend_self_and_forward_city_against_incoming_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for takesCity in [True, False]:
            for attackGenLeft in [True, False, None]:
                if not takesCity and attackGenLeft is None:
                    continue

                with self.subTest(takesCity=takesCity, attackGenLeft=attackGenLeft):
                    mapFile = 'GameContinuationEntries/should_defend_forward_city_against_incoming_threat___SejdBT5Vp---1--370.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 370, fill_out_tiles=True)

                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=370)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                    if takesCity:
                        simHost.queue_player_moves_str(enemyGeneral.player, '11,4->11,6->6,6->6,8->4,8->4,9')
                        if attackGenLeft:
                            simHost.queue_player_moves_str(enemyGeneral.player, '4,9->3,9->3,8->1,8->1,13')
                        elif attackGenLeft is not None:
                            simHost.queue_player_moves_str(enemyGeneral.player, '4,9->5,9->5,12->1,12->1,13')
                    elif attackGenLeft:
                        simHost.queue_player_moves_str(enemyGeneral.player, '11,4->11,6->6,6->6,8->3,8->1,8->1,13')
                    elif attackGenLeft is not None:
                        simHost.queue_player_moves_str(enemyGeneral.player, '11,4->11,6->6,6->6,8->5,8->5,12->1,12->1,13')

                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    city = playerMap.GetTile(4, 9)

                    self.begin_capturing_logging()
                    simHost.run_between_turns(lambda: self.assertEqual(general.player, city.player, 'should never lose control of the city.'))
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
                    self.assertIsNone(winner)

    def test_should_be_able_to_complete_city_capture_against_non_moving_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for enMoves in [False, True]:
            with self.subTest(enMoves=enMoves):
                mapFile = 'GameContinuationEntries/should_be_able_to_complete_city_capture_against_non_moving_threat___SejdBT5Vp---1--392.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 392, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=392)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                if enMoves:
                    simHost.queue_player_moves_str(enemyGeneral.player, '4,9->4,8->1,8->1,13')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
                self.assertIsNone(winner)

                city = playerMap.GetTile(4, 9)
                self.assertEqual(general.player, city.player)
                self.assertNoRepetition(simHost)

    def test_should_defend_city_from_central_launch_point(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_from_central_launch_point___mEG6AMNX----1--283.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=283)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,6->13,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        city = playerMap.GetTile(13, 10)
        self.assertEqual(general.player, city.player)

    def test_should_not_pull_back_when_can_intercept_army_at_chokes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_pull_back_when_can_intercept_army_at_chokes___EklipZ_ai-TEST__56f1941c-213a-46f3-880d-05d1db0559e5---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,6->6,6->6,8->1,8->1,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        army = bot.armyTracker.get_or_create_army_at(playerMap.GetTile(3, 12))

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        tile = playerMap.GetTile(5, 9)
        self.assertEqual(tile, army.tile)
        self.assertGreater(tile.army, 100)

    def test_should_defend_and_retake_city_and_not_get_weird_trunkvalue_zeros(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_and_not_get_weird_trunkvalue_zeros___74QU5HBYT---1--479.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 479, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=479)

        self.enable_search_time_limits_and_disable_debug_asserts()
        # Gather.USE_DEBUG_ASSERTS = True
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->13,13->13,12->11,12->11,9->9,9->9,3->7,3')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=18)
        self.assertIsNone(winner)

        c1 = playerMap.GetTile(10, 9)
        c2 = playerMap.GetTile(11, 10)

        self.assertEqual(general.player, c1.player)
        self.assertEqual(general.player, c2.player)

    def test_should_not_wait_on_necessary_defense_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_wait_on_necessary_defense_move___atTOZgR22---1--379.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 379, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=379)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_wait_on_necessary_defense_move")
    
    def test_should_not_die_weirdly_to_delayed_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_die_weirdly_to_delayed_defense___fKHLA84Q_---1--974.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 974, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=974)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_die_weirdly_to_delayed_defense")
    
    def test_should_not_defense_loop_against_fog_army__intercept_instead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_defense_loop_against_fog_army__intercept_instead___eyWugBXu8---1--417.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 417, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=417)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        enTile = playerMap.GetTile(16, 16)
        self.assertEqual(general.player, enTile.player)
    
    def test_should_path_large_tile_through_flank_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_path_large_tile_through_flank_cities____H2EL3yXK---1--952.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 952, fill_out_tiles=True)
        map.GetTile(4, 15).army = 100

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=952)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,16->4,16->4,14->2,14->2,12->1,12->1,10->0,10->0,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=19)
        self.assertIsNone(winner)
    
    def test_should_try_to_gain_vision_of_potential_wall_break_flanks(self):
        # TODO gather to the wall after recognizing it is a severe wall break flank risk
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_try_to_gain_vision_of_potential_wall_break_flanks___cHIFiv4HU---0--328.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 328, fill_out_tiles=True)
        # city.isCity = True
        # city.player = enemyGeneral.player
        # city.army = 150

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=328)
        city = rawMap.GetTile(11, 0)
        city.reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(17, 1).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(17, 1).isGeneral = False
        rawMap.GetTile(13, 2).army = 55
        rawMap.generals[enemyGeneral.player] = None
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  None  None  None  None  None  None  11,0->9,0->9,1->5,1->5,3->3,3')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=22)
        self.assertIsNone(winner)
    
    def test_should_not_loop_on_wait_gathDef_vs_city_contest(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_on_wait_gathDef_vs_city_contest___SaRQmDLde---0--436.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 436, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=436)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)

# 31f - 62p - 4skip
    
    def test_should_gather_to_obvious_attack_path_to_hold_defensively(self):
        # the problem here is it was underestimating the fog risk, and also does not include the non-shortest-route attack path potential by looping up through the 3's, and fails defense
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_to_obvious_attack_path_to_hold_defensively__real___DaQ8qgZt2---0--302.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 302, fill_out_tiles=False)
        enemyGeneral.army = 14

        mapFile = 'GameContinuationEntries/should_gather_to_obvious_attack_path_to_hold_defensively___DaQ8qgZt2---0--302.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=302)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  17,17->16,17->16,16  17,16->15,16  17,15->15,15  17,14->15,14  13,16->15,16->15,13->11,13->11,12->10,12->10,10->8,10->8,9->4,9->4,10->0,10->0,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=36)
        self.assertIsNone(winner)
    
    def test_should_not_pull_random_2s_in_instead_of_intercepting_and_killing_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_pull_random_2s_in_instead_of_intercepting_and_killing_army___iL5WmojH_---1--134.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 134, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=134)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,13->16,14->15,14->15,18')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost), 6)
    
    def test_should_defend_city_and_not_move_stuff_off_city(self):
        for i in range(32):
            debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
            mapFile = 'GameContinuationEntries/should_defend_city_and_not_move_stuff_off_city___iL5WmojH_---1--332.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 332, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=332)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, '13,7->14,7->14,10->17,10->17,12  16,12->17,12')
            bot = self.get_debug_render_bot(simHost, general.player)
            bot.timings = bot.get_timings()
            bot.timings.launchTiming = 37
            bot.timings.splitTurns = 37
            playerMap = simHost.get_player_map(general.player)

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
            self.assertIsNone(winner)

            city = playerMap.GetTile(17, 12)
            self.assertEqual(general.player, city.player, 'should have held city')

    def test_should_go_for_kill_instead_of_attempting_defense_when_cannot_defend(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_intercept___GaUZiDSCr---1--568.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 568, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=568)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,13->10,12->10,11->9,11->9,10->8,10->8,7->9,7->9,4->7,4->7,0->8,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertEqual(general.player, winner)

    def test_should_not_do_weird_flank_vision_thing_when_opp_clearly_going_to_nuke_up_the_middle(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_do_weird_flank_vision_thing_when_opp_clearly_going_to_nuke_up_the_middle___gbd4mui8Z---1--111.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 111, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=111)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)

        self.assertGreater(bot.sum_player_standing_army_near_or_on_tiles(bot.shortest_path_to_target_player.tileList, distance=0, player=general.player), 37)

    def test_should_consider_long_attack_a_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_consider_long_attack_a_threat___aXropQVFj---0--428.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 428, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=428)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,11->8,11->8,8->9,8->9,7->11,7->11,4->15,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)
    
    def test_should_defend_city_efficiently_not_gather_extra_3s_over_1s(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_efficiently_not_gather_extra_3s_over_1s___lc6hX8gL6---1--237.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 237, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=237)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,12->8,15->9,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        city = playerMap.GetTile(9, 15)
        self.assertOwned(general.player, city, 'should have defended the city')
    
    def test_should_not_do_dumb_shit_with_flank_vision_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_do_dumb_shit_with_flank_vision_defense___HiDCxRjvu---1--200.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 200, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=200)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)

    def test_should_king_race_when_it_is_a_win(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for turn, isWinRaw in [
            (244, False),
            (243, True),
        ]:
            for addlArmy, canKill in [
                (0, True),
                (2, True),
                (3, True),
                (4, True),
                (5, False),
                (7, False),
            ]:
                for generalVisible in [True, False]:
                    isWin = isWinRaw and canKill
                    with self.subTest(turn=turn, extraArmy=addlArmy, generalVisible=generalVisible, isWin=isWin):
                        self._run_king_kill_race_test(debugMode, addlArmy, generalVisible, isWin, turn)

    def test_should_king_race_when_it_is_a_win__specific_scenario(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        turn = 243
        extraArmy = 4
        generalVisible = False
        isWin = True
        self._run_king_kill_race_test(debugMode, extraArmy, generalVisible, isWin, turn)

    def _run_king_kill_race_test(self, debugMode: bool, addlArmy: int, generalVisible: bool, isWin: bool, turn: int):
        mapFile = 'GameContinuationEntries/should_king_race_when_it_is_a_win___HiDCxRjvu---1--244.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)
        self.update_tile_army_in_place(map, enemyGeneral, enemyGeneral.army + addlArmy)
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)
        if not generalVisible:
            self.reset_general(rawMap, enemyGeneral)
        else:
            rawMap.GetTile(enemyGeneral.x, enemyGeneral.y).army = enemyGeneral.army

        if not isWin:
            map.GetTile(16, 10).army = 2
            rawMap.GetTile(16, 10).army = 2

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,11->16,11')
        # # proof
        # if isWin:
        #     simHost.queue_player_moves_str(general.player, '5,9->4,9->4,7->2,7')
        # else:
        #     simHost.queue_player_moves_str(general.player, '11,12->11,11  17,9->16,9->16,11')

        bot = self.get_debug_render_bot(simHost, general.player)
        bot.opponent_tracker.current_team_cycle_stats[enemyGeneral.player].approximate_fog_city_army += addlArmy
        playerMap = simHost.get_player_map(general.player)
        self.begin_capturing_logging()
        turnsToRun = 5
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=turnsToRun)
        if isWin:
            self.assertEqual(map.player_index, winner, "expected a dive kill on priority")
        else:
            self.assertIsNone(winner, 'expected defense as dive kill not safe')
    
    def test_should_not_fail_to_find_simple_defense__questionmark(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_fail_to_find_simple_defense__questionmark___scZzgZ9NX---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,7->12,9->15,9')
        #proof
        # simHost.queue_player_moves_str(general.player, '14,6->14,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

    def test_should_respect_and_defend_defenseless_modifier(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for mustDefend in [True, False]:
            with self.subTest(mustDefend=mustDefend):
                mapFile = 'GameContinuationEntries/should_respect_and_defend_defenseless_modifier___2v3zDUjUn---1--73.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 73, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=73)
                if mustDefend:
                    map.GetTile(18, 11).army = 1
                    rawMap.GetTile(18, 11).army = 1
                    map.GetTile(13, 10).army = 26
                    rawMap.GetTile(13, 10).army = 26

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '14,9->18,9->18,11')
                # simHost.queue_player_moves_str(general.player, '12,10->18,10')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
                self.assertIsNone(winner)
                self.assertOwned(general.player, playerMap.GetTile(18, 10), 'should not have let the opp reach this tile (which would be kill with defenseless modifier)')
    
    def test_should_defend_2v2_ally(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_2v2_ally___FRAa_4Nfr---2--189.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 189, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=189)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyAllyGen.player, '12,6->14,6->14,8->15,8->15,9->17,9')
        simHost.queue_player_moves_str(allyGen.player, '14,8->15,8  None  None  14,10->15,10->15,9  17,10->17,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_self_from_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_self_from_threat___BXxbd90_o---1--228.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 228, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=228)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyAllyGen.player, '11,10->11,8->15,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_self_from_threat_with_extra_chase_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_self_from_threat_with_extra_chase_move___BXxbd90_o---1--228.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 228, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=228)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyAllyGen.player, '11,10->11,8->15,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.disable_engine = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_self_from_threat_with_extra_chase_move__short(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_self_from_threat_with_extra_chase_move__short___BXxbd90_o---1--231.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 231, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=231)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyAllyGen.player, '12,8->15,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.disable_engine = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_ally_not_do_weird_intercept_stuff(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_ally_not_do_weird_intercept_stuff___yWJMLHjZn---0--236.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 236, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=236)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,9->11,15->10,15->10,16')
        simHost.queue_player_moves_str(allyGen.player, '5,11->6,11->6,12->7,12->7,13->9,13->9,15')
        simHost.queue_player_moves_str(general.player, '10,12->11,12')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_against_threat_that_actually_moves_towards_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_against_threat_that_actually_moves_towards_gen___eHIEvb2B2---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,4->16,1->11,1')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_not_use_interception_delayed_tile_for_other_purposes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_use_interception_delayed_tile_for_other_purposes___UuMAEsbxV---0--431.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 431, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=431)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,14->13,14->13,15->14,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=4)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_defend_city_not_do_wrong_defense_move_based_on_leafDist(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_not_do_wrong_defense_move_based_on_leafDist___7JqWi0Wj0---0--342.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 342, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=342)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,8->13,9->14,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)
        self.assertOwned(general.player, playerMap.GetTile(14, 9))

    def test_should_not_think_has_extra_priority_move_to_defend(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_think_has_extra_priority_move_to_defend___uJ_Avq2Zz---1--129.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 129, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=129)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,7->18,7->18,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_gather_adj_to_threat_first__i_thought_i_already_fixed_thisssss(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '11,7->11,9->12,9->12,12->13,12->13,13',
            '11,7->11,9->12,9->12,12->12,13->13,13'
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/should_gather_adj_to_threat_first__i_thought_i_already_fixed_thisssss___igX7EXz65---1--126.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 126, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=126)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                #proof
                # simHost.queue_player_moves_str(general.player, '12,7->11,7')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
                self.assertNoFriendliesKilled(map, general)

    def test_should_gather_adj_to_threat_first__i_thought_i_already_fixed_thisssss__slightly_longer(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '10,7->11,7->11,9->12,9->12,12->13,12->13,13',
            '10,7->11,7->11,9->12,9->12,12->12,13->13,13'
        ]:
            for fakeTurn in [125, 126]:
                with self.subTest(path=path, fakeTurn=fakeTurn):
                    mapFile = 'GameContinuationEntries/should_gather_adj_to_threat_first__i_thought_i_already_fixed_thisssss__slightly_longer___igX7EXz65---1--125.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, fakeTurn, fill_out_tiles=True)

                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=fakeTurn)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                    simHost.queue_player_moves_str(enemyGeneral.player, path)
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
                    self.assertNoFriendliesKilled(map, general)
    
    def test_should_gather_adj_to_threat_first__i_thought_i_already_fixed_thisssss__longer(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '6,7->11,7->11,9->12,9->12,12->13,12->13,13',
            '6,7->11,7->11,9->12,9->12,12->12,13->13,13'
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/should_gather_adj_to_threat_first__i_thought_i_already_fixed_thisssss__longer___igX7EXz65---1--121.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 121, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=121)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=13)
                self.assertNoFriendliesKilled(map, general)

    def test_should_wait_to_gather_tiles_that_are_in_the_shortest_pathway_for_last(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '6,10->6,7->5,7',
            '6,10->6,9->5,9->5,7'
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/should_wait_to_gather_tiles_that_are_in_the_shortest_pathway_for_last___GIghDuWWN---1--437.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 437, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=437)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                # proof:
                # simHost.queue_player_moves_str(general.player, '3,7->5,7')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
                self.assertNoFriendliesKilled(map, general)
    
    def test_should_defend_city_what_the_fuck(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_what_the_fuck___nWAqZP0Om---1--295.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 295, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=295)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,14->1,15->5,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertNoFriendliesKilled(map, general)

        city = playerMap.GetTile(5, 15)
        self.assertOwned(general.player, city)
    
    def test_should_not_let_runaround_mountain_kill_with_wonky_defense_gather_calc_that_doesnt_even_save(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_let_runaround_mountain_kill_with_wonky_defense_gather_calc_that_doesnt_even_save___2a6P3AjJp---1--80.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,9->6,8->9,8->9,11->8,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertNoFriendliesKilled(map, general)

    def test_should_not_dead_explore_for_threats_against_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dead_explore_for_threats_against_cities___am36fHtj9---0--268.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 268, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=268)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,9->16,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(42, playerMap.GetTile(17, 9).army)
    
    def test_defense_should_kick_in_at_the_point_of_death_what_the_fuck(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/defense_should_kick_in_at_the_point_of_death_what_the_fuck___G3AsU8h9C---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=289)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,2->3,2->3,3')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_never_be_able_to_gather_to_the_tile_the_threat_came_from(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_never_be_able_to_gather_to_the_tile_the_threat_came_from___2GnaZ00Oh---1--191.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 191, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=191)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,4->13,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertGreater(playerMap.GetTile(11, 6).army, 47, 'should have moved army down, i dont understand how we could ever gather upwards')
    
    def test_should_defend_city_cluster_adequately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_cluster_adequately___FAG8TLWJt---0--308.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 308, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=308)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '2,13->1,13->1,15->2,15->2,16->8,16->8,15->12,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        Gather.USE_DEBUG_ASSERTS = False
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertNoFriendliesKilled(map, general)

        city = playerMap.GetTile(12, 15)
        self.assertOwned(general.player, city)

    def test_shouldnt_fucking_gather_enemy_tiles_as_defense__the_fuck(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path, turns, expectWinner in [
            ('14,9->14,11->11,11->11,14->16,14->16,15->17,15', 14, 1),
            ('14,9->15,9->15,15->17,15', 9, None),
            ('14,9->14,12->15,12->15,15->17,15', 9, None),
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/shouldnt_fucking_gather_enemy_tiles_as_defense__the_fuck___ntZFlj5Kh---1--185.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 185, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=185)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=turns)
                self.assertNoFriendliesKilled(map, general)
                self.assertEqual(expectWinner, winner)

    def test_should_make_defense_moves_in_correct_order(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '14,4->15,4->16,4->16,7->17,7',
            '14,4->15,4->17,4->17,7',
            '14,4->15,4->15,5->16,5->16,7->17,7',
            '14,4->15,4->15,5->17,5->17,7',
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/should_make_defense_moves_in_correct_order___mTnwfCy48---1--146.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 143, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=143)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
                self.assertNoFriendliesKilled(map, general)

    def test_should_understand_can_pull_line_of_high_value_tiles_from_top_to_intercept(self):
        # Note here we make it so we can't dive the en general
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying___XWHQOYv7I---1--480.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)

        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 3, 19)

        turns = 15

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)
        map.GetTile(2, 12).army = 1
        rawMap.GetTile(2, 12).army = 1
        map.GetTile(2, 7).army = 201
        rawMap.GetTile(2, 7).army = 201

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,14->7,14->7,10->9,10->9,9->11,9')
        # proof
        # simHost.queue_player_moves_str(general.player, '6,3->6,7->7,7->7,9->11,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        playerMap.GetTile(5, 14).lastMovedTurn = playerMap.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=turns)
        self.assertNoFriendliesKilled(map)

    def test_should_be_capable_of_understanding_defense_one_move_behind(self):
        # Note that we force the enemy general positions to be everywhere enemy that we can't see for this test, so that we cant safely dive.
        # we also force a gather from top left through city to not work for defense by reducing the city value.

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying___XWHQOYv7I---1--480.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)

        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 3, 19)
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)

        map.GetTile(6, 7).army = 10
        rawMap.GetTile(6, 7).army = 10

        turns = 15

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,14->7,14->7,10->9,10->9,9->11,9')
        # proof
        # simHost.queue_player_moves_str(general.player, '2,12->2,11->9,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        bot.armyTracker.update_fog_prediction(enemyGeneral.player, bot.opponent_tracker.get_player_fog_tile_count_dict(enemyGeneral.player), bot.targetPlayerExpectedGeneralLocation, force=True)
        bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player] = MapMatrixSet(playerMap, (t for t in playerMap.pathable_tiles if not t.visible))
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player] = MapMatrix(playerMap, 1.0)
        playerMap.GetTile(5, 14).lastMovedTurn = playerMap.turn

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=turns)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_just_intercept__not_die_lmao__why_is_defense_preventing_intercept_here(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_just_intercept__not_die_lmao__why_is_defense_preventing_intercept_here___9kQJij1tZ---1--275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 275, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=275)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,15->7,16->6,16->6,17->5,17')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_defend_i_guess__lol__how_did_i_break_depth_search_so_badly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_i_guess__lol__how_did_i_break_depth_search_so_badly___5J5nzUsKl---0--487.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 487, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=487)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,1->2,1->2,0->4,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

    def test_should_defend_i_guess__lol__how_did_i_break_depth_search_so_badly__longer(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_i_guess__lol__how_did_i_break_depth_search_so_badly__longer___5J5nzUsKl---0--485.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 485, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=485)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,3->1,1->2,1->2,0->4,0')
        # proof
        # simHost.queue_player_moves_str(general.player, '4,4->4,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        GatherDebug.USE_DEBUG_ASSERTS = True
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_not_literally_kill_self_in_2v2_by_preventing_ally_from_saving(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_literally_kill_self_in_2v2_by_preventing_ally_from_saving___55XCt3qlT---0--177.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 177, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=177)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyGeneral.player, '17,10->17,9->16,9->16,8')
        simHost.queue_player_moves_str(allyGen.player, '16,10->17,10->17,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_defend_ally_from_straightforward_attack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_ally_from_straightforward_attack___piCvrHURN---3--378.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 378, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=378)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,20->6,20')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)

    def test_should_not_consider_self_dead_when_trivially_obviously_not_dead_at_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_consider_self_dead_when_trivially_obviously_not_dead_at_choke___f1tVhCbAr---1--479.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 479, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=479)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '2,10->2,9->6,9->6,2->7,2')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=13)
        self.assertNoFriendliesKilled(map, general)

    # 36-69-5 as of tweaking chokes and honoring allowNonChoke
    # 31-74-5 reverted chokeWidth reduction to -2 from -1, which i'm like 100% sure is wrong but it makes the 'one too far' tests pass, lmao.
    # 50-55 if i switch to gathering to shortest pathway tiles with pathwidth offset
    # 34-71
    # 57-49 with chokewidth -1 instead of -2 and the choke defense changes in place
    # 53-53
    # 63f-26p-9skip after everything fucked by intercept
    # 44f-45p-5skip fixed assertion float rounding failures by casting to int lol
    # 59f 66p 5s with i think broken stuff as far as priority offset goes
    # 58f, 72p, 5s with fix to intercept overriding defense
    # 56f, 74p, 5s with another ^
    # 53f, 77p, 5s still more tweaks to ^
    # 58f, 72p, 5s LITERALLY THE SAME CODE AS ^
    # 77f, 64p, 5s after fucking with the intercept instead of chokewidth in distDict and changing the gather-leaf-defense-move-priority-order which needs to be fixed,
    #         see test test_should_wait_to_gather_tiles_that_are_in_the_shortest_pathway_for_last (?) above. TODO
    # 88f, 60p, 2s after hating my life. Intercept still fucking things up pretty sure
    # 97f, 54p, 5s after still hating my life, un-broke the threat dist stuff (but it may be wrong).
    # 94f, 57p, 5s
    # 82f, 74p, 5s after preventing gather
    # 91f, 68p, 4s after fixing iterative gather bug? lol? wtf?
    # 73f, 91p, 5s after idk things that have happened and adding 5 new tests. Also pruning the bad distDict entries that one would never want to gather to, I guess
    
    def test_should_not_allow_moves_that_get_bot_killed(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_allow_moves_that_get_bot_killed___l0BMWz6mu---1--347.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 347, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=347)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,11->11,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        bot.curPath = TextMapLoader.parse_path(playerMap, '12,14->12,10')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertLess(playerMap.GetTile(11, 15).army, 3, 'should ABSOLUTELY NOT have just allowed this tile movement to happen and die. The defense wait-move analysis should be flagging this tile as DO NOT MOVE')
    
    def test_should_defend_city_and_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_city_and_choke___sRNXwEvtD---0--431.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 431, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=431)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,13->6,11->3,11->4,11->4,10->2,10->2,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertNoFriendliesKilled(map, general)

        city = playerMap.GetTile(2, 7)
        self.assertOwned(general.player, city, 'fucking defend, bro')
    
    def test_should_defend_by_slamming_large_army_into_threat_not_letting_it_run(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_by_slamming_large_army_into_threat_not_letting_it_run___fbCglC49i---1--486.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 486, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=486)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,9->12,6')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general)

        self.assertLess(playerMap.GetTile(12, 6).army, 150)

    def test_should_defend_by_slamming_large_army_into_threat_not_letting_it_run__full(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_by_slamming_large_army_into_threat_not_letting_it_run___fbCglC49i---1--486.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 486, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=486)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,9->12,6->14,6->14,3->20,3->20,2->21,2')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_not_skip_defense_move_and_die(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_skip_defense_move_and_die____HgP1xF6h---0--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=388)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,2->15,2')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertNoFriendliesKilled(map, general)

    def test_should_not_faff_about_and_should_successfully_defend__start_move_drop(self): # INT BREAKS
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_faff_about_and_should_successfully_defend___YAZlmHb12---0--474.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 474, fill_out_tiles=True)
        general.army += 3

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=474)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  5,4->5,8->6,8->6,18->6,19')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertNoFriendliesKilled(map, general)

    def test_should_not_faff_about_and_should_successfully_defend(self): # INT BREAKS
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_faff_about_and_should_successfully_defend___YAZlmHb12---0--474.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 474, fill_out_tiles=True)
        general.army += 3

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=474)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,4->5,8->6,8->6,18  None  6,18->6,19')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertNoFriendliesKilled(map, general)

# 78f 92p with the flipThingy - 0 instead of - 1, hybrid int, new defense move prio (with root dist base)
# 76f 94p ^ but with flipThingy = 1
# 82f 88p ^ with intercept def hybrid fixed so it actually triggers
# 85f 85p ^ but flipthingy 0 again
# 82f 88p ^ reverted
