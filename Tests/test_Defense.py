import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class DefenseTests(TestBase):

    def test_finds_perfect_gather_defense_in_previously_failed_scenario(self):
        debugMode = False
        mapFile = 'Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, player_index=1)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)


    def test_should_not_spin_on_defense_gathers_against_sitting_cities(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_not_spin_on_defense_gathers_against_sitting_cities___BelzKSdhh---b--275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 275)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.5)

    def test_finds_perfect_gather_defense__small_moves_into_path__against_threat_path(self):
        debugMode = False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
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

        # simHost.run_sim(run_real_time=debugMode, turn_time=2.0)

        # TODO add asserts for finds_perfect_gather_defense__small_moves_into_path__against_threat_path

    def test_finds_perfect_gather_defense__small_moves_into_path__lower_value_final_move__against_threat_path(self):
        debugMode = True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__Smaller_final_move.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
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
            simHost.run_sim(run_real_time=debugMode, turn_time=5.0)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(6, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)


    def test_finds_perfect_gather_defense__small_moves_into_path__knapsack_gather_breaks(self):
        debugMode = True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__KnapsackGatherBreaks.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
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
            simHost.run_sim(run_real_time=debugMode, turn_time=5.0)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(2, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)


    def test_finds_perfect_gather_defense__small_moves_into_path__knapsack_gather_breaks_simpler(self):
        debugMode = True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath__KnapsackGatherBreaks_Simpler.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(2, threat.turns)

        # move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(
        #     threat,
        #     gatherMax=True,
        #     shouldLog=True)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path_greedy(
            threat,
            gatherMax=True,
            shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")
            simHost.run_sim(run_real_time=debugMode, turn_time=5.0)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(2, turnsUsed)
        self.assertGreater(valueGathered, threat.threatValue)
        # self.assertEqual(8, valueGathered)
        # self.assertEqual(7, turnsUsed)


    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path(self):
        debugMode = True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5, turns=15)
        self.assertIsNone(winner)

    def test_finds_perfect_gather_defense__multi_knapsack_fails(self):
        debugMode = True
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_MultiKnapsackFailed.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)


    def test_finds_perfect_gather_defense__one_longer_move_move_into_path__against_threat_path__no_20(self):
        debugMode = False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_no_20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
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
        debugMode = False
        mapFile = 'Defense/GatherScenarios/ManySingleMovesToPath_WithLongerStart_no_20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_target_tiles_greedy([enemyGeneral], 0.1, gatherTurns=30, includeTreeNodesThatGatherNegative=True, targetArmy=70)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertGreater(valueGathered, 75)
    
    def test_does_not_fail_defense(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/does_not_fail_defense___BgVc48Chn---b--792.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 792)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 792)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, afkPlayers=[enemyGeneral.player])

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, shouldLog=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertGreater(valueGathered, threat.threatValue)

        simHost.run_sim(run_real_time=debugMode, turn_time=2.0)

        # TODO add asserts for does_not_fail_defense
