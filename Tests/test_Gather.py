import logging

import GatherUtils
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class GatherTests(TestBase):
    def test_should_gather_from_less_useful_parts_of_the_map(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/should_gather_from_less_useful_parts_of_the_map___Bgw4Yc5n2---a--650.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 650, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=100)
        self.assertIsNone(winner)

    def test_gather_value_estimates_should_be_correct(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        rawMap, _ = self.load_map_and_general(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # Grant the general the same fog vision they had at the turn the map was exported
        # simHost.make_player_afk(enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, gatherMax=True)

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = gatherNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(8, valueGathered)
        self.assertEqual(7, turnsUsed)


    def test_gather_prune_produces_correct_values(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # Grant the general the same fog vision they had at the turn the map was exported
        # simHost.make_player_afk(enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, gatherMax=True)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(8, valueGathered)
        self.assertEqual(7, turnsUsed)

        sumVal = 0
        sumTurns = 0
        for node in gatherNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns
        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        postPruneNodes = GatherUtils.prune_mst_to_turns(gatherNodes, turnsUsed, general.player, ekBot.viewInfo, noLog=False)

        sumVal = 0
        sumTurns = 0
        for node in postPruneNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = postPruneNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        logging.info(
            f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

    def test_gather_prune_less_produces_correct_length_plan(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # Grant the general the same fog vision they had at the turn the map was exported
        # simHost.make_player_afk(enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, gatherMax=True)
        #
        # viewInfo = ekBot.viewInfo
        # viewInfo.gatherNodes = gatherNodes
        # if debugMode:
        #     self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(7, turnsUsed)
        self.assertEqual(8, valueGathered)

        sumVal = 0
        sumTurns = 0
        for node in gatherNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns
        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        postPruneNodes = GatherUtils.prune_mst_to_turns(gatherNodes, turnsUsed - 1, general.player, ekBot.viewInfo, noLog=False)

        sumVal = 0
        sumTurns = 0
        for node in postPruneNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns

        self.assertEqual(valueGathered - 1, sumVal)
        self.assertEqual(turnsUsed - 1, sumTurns)

        logging.info(
            f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = postPruneNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

    def test_gather_prune_to_zero_produces_correct_values(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # Grant the general the same fog vision they had at the turn the map was exported
        # simHost.make_player_afk(enemyGeneral.player)

        ekBot = simHost.bot_hosts[general.player].eklipz_bot

        threat = ekBot.threat
        self.assertIsNotNone(threat)
        self.assertEqual(7, threat.turns)

        self.begin_capturing_logging()
        move, valueGathered, turnsUsed, gatherNodes = ekBot.get_gather_to_threat_path(threat, gatherMax=True)

        self.assertIsNotNone(move)
        self.assertIsNotNone(gatherNodes)
        self.assertNotEqual(0, len(gatherNodes))
        self.assertEqual(8, valueGathered)
        self.assertEqual(7, turnsUsed)

        pruneNearZeroMovesCases = [-1, 0, 1]
        for pruneNearZeroMovesCase in pruneNearZeroMovesCases:
            with self.subTest(pruneNearZeroMovesCase=pruneNearZeroMovesCase):
                toPrune = [node.deep_clone() for node in gatherNodes]
                postPruneNodes = GatherUtils.prune_mst_to_turns(toPrune, pruneNearZeroMovesCase, general.player, ekBot.viewInfo, noLog=False)
                sumVal = 0
                for node in postPruneNodes:
                    sumVal += node.value

                if pruneNearZeroMovesCase == 1:
                    self.assertEqual(1, sumVal)
                else:
                    self.assertEqual(0, sumVal)

                logging.info(
                    f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

                viewInfo = ekBot.viewInfo
                viewInfo.gatherNodes = postPruneNodes
                if debugMode:
                    self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")
    
    def test_going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.reveal_player_general(enemyGeneral.player, general.player, hidden=True)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.31, turns=80)
        self.assertEqual(general.player, winner)
        self.assertNoRepetition(simHost, minForRepetition=1, msg="should not re-gather cities or explore innefficiently. There should be zero excuse for ANY tile to be move source more than once in this sim.")
    
    def test_random_large_gather_test(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/random_large_gather_test___reOqoXEp2---g--864.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 864, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 864)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for random_large_gather_test

    def test_should_not_produce_invalid_path_during_gather(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/should_not_produce_invalid_path_during_gather___b-TEST__10ec1926-ef6a-4efb-a6e6-d7a3a9017f00---b--553.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 560, fill_out_tiles=True)

        # self.disable_search_time_limits_and_enable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 560)

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=25)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=1)
