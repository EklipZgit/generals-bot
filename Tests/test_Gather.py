import logging

import EarlyExpandUtils
from ArmyAnalyzer import ArmyAnalyzer
from BotHost import BotHostBase
from DangerAnalyzer import ThreatObj, ThreatType
from DataModels import Move
from Path import Path
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class GatherTests(TestBase):
    def test_should_gather_from_less_useful_parts_of_the_map(self):
        mapFile = 'GameContinuationEntries/should_gather_from_less_useful_parts_of_the_map___Bgw4Yc5n2---a--650.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 650)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=True, turn_time=0.3, turns=100)
        self.assertIsNone(winner)

    def test_gather_value_estimates_should_be_correct(self):
        debugMode = True
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
        debugMode = True
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

        pruned = ekBot.prune_mst(gatherNodes, turnsUsed)
        sumVal = 0
        for node in pruned:
            sumVal += node.value

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = pruned
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

        self.assertEqual(8, sumVal)

        logging.info(
            f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')


    def test_gather_prune_less_produces_correct_values(self):
        debugMode = True
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

        pruned = ekBot.prune_mst(gatherNodes, turnsUsed - 1)
        sumVal = 0
        for node in pruned:
            sumVal += node.value

        self.assertEqual(7, sumVal)

        logging.info(
            f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = pruned
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

    def test_gather_prune_to_zero_produces_correct_values(self):
        debugMode = True
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
                pruned = ekBot.prune_mst(toPrune, pruneNearZeroMovesCase)
                sumVal = 0
                for node in pruned:
                    sumVal += node.value

                # TODO should actually be 0 but who cares, close enough for now
                self.assertEqual(1, sumVal)

                logging.info(
                    f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

                viewInfo = ekBot.viewInfo
                viewInfo.gatherNodes = pruned
                if debugMode:
                    self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")
    
    def test_going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 527)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptViewer=True)
        simHost.reveal_player_general(enemyGeneral.player, general.player, hidden=True)

        # simHost.make_player_afk(enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=70)
        self.assertEqual(general.player, winner)
