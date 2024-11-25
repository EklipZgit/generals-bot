import logbook
import time
import typing

import DebugHelper
import Gather
import SearchUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot


class GatherTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.gather_use_pcst = True
        # bot.info_render_centrality_distances = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True

        return bot

    def test_should_gather_from_less_useful_parts_of_the_map(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

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
        self.assertEqual(8, round(valueGathered))
        self.assertEqual(7, turnsUsed)

    def test_gather_prune_produces_correct_values(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

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
        self.assertEqual(8, round(valueGathered))
        self.assertEqual(7, turnsUsed)

        sumVal = 0
        sumTurns = 0
        for node in gatherNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns
        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        postPruneNodes = Gather.prune_mst_to_turns(gatherNodes, turnsUsed, general.player, viewInfo=ekBot.viewInfo, noLog=False)

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

        logbook.info(
            f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

    def test_gather_prune_less_produces_correct_length_plan(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

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
        self.assertEqual(8, round(valueGathered))

        sumVal = 0
        sumTurns = 0
        for node in gatherNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns
        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        postPruneNodes = Gather.prune_mst_to_turns(gatherNodes, turnsUsed - 1, general.player, viewInfo=ekBot.viewInfo, noLog=False)

        sumVal = 0
        sumTurns = 0
        for node in postPruneNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns

        self.assertEqual(valueGathered - 1, round(sumVal))
        self.assertEqual(turnsUsed - 1, sumTurns)

        logbook.info(
            f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

        viewInfo = ekBot.viewInfo
        viewInfo.gatherNodes = postPruneNodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")

    def test_gather_prune_to_zero_produces_correct_values(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/gather_value_estimates_should_be_correct___rghT7Cq23---b--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

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
        self.assertEqual(8, round(valueGathered))
        self.assertEqual(7, turnsUsed)

        pruneNearZeroMovesCases = [-1, 0, 1]
        for pruneNearZeroMovesCase in pruneNearZeroMovesCases:
            with self.subTest(pruneNearZeroMovesCase=pruneNearZeroMovesCase):
                toPrune = [node.deep_clone() for node in gatherNodes]
                postPruneNodes = Gather.prune_mst_to_turns(toPrune, pruneNearZeroMovesCase, general.player, viewInfo=ekBot.viewInfo, noLog=False)
                sumVal = 0
                for node in postPruneNodes:
                    sumVal += node.value

                if pruneNearZeroMovesCase == 1:
                    self.assertEqual(1, round(sumVal))
                else:
                    self.assertEqual(0, round(sumVal))

                logbook.info(
                    f'{str(move)} Final panic gather value {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns}')

                viewInfo = ekBot.viewInfo
                viewInfo.gatherNodes = postPruneNodes
                if debugMode:
                    self.render_view_info(map, viewInfo, f"valueGath {valueGathered}")
    
    def test_going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        cases = [
            True,
            False,
        ]
        for shouldAssert in cases:
            with self.subTest(shouldAssert=shouldAssert):
                mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527)

                if shouldAssert:
                    self.disable_search_time_limits_and_enable_debug_asserts()
                else:
                    self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)
                botEnGen = rawMap.GetTile(enemyGeneral.x, enemyGeneral.y)
                botEnGen.army = 0
                botEnGen.isGeneral = False
                botEnGen.player = -1
                botEnGen.tile = TILE_EMPTY
                rawMap.generals[enemyGeneral.player] = None
                rawMap.players[enemyGeneral.player].general = None

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                bot = simHost.get_bot(general.player)
                bot.is_all_in_army_advantage = True
                bot.is_winning_gather_cyclic = True
                self.set_general_emergence_around(17, 5, simHost, general.player, enemyGeneral.player, 20)
                self.set_general_emergence_around(16, 7, simHost, general.player, enemyGeneral.player, 30)
                #
                # bot.info_render_gather_values = False
                # GatherDebug.USE_DEBUG_ASSERTS = False
                # DebugHelper.IS_DEBUGGING = False
                # self.begin_capturing_logging()
                # _, _, _, gathers = bot.get_gather_to_target_tiles([enemyGeneral], 0.2, gatherTurns=73)
                #
                # viewInfo = self.get_renderable_view_info(map)
                # # viewInfo.bottomLeftGridText = gatherMatrix
                # # viewInfo.bottomRightGridText = captureMatrix
                # viewInfo.gatherNodes = gathers
                # self.render_view_info(map, viewInfo, 'not steiner???')

                # self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=80)
                self.assertEqual(general.player, enemyGeneral.player, "should have captured enemy general")

                # this assert no longer relevant now that all in gathers are max-value-per-turn
                # self.assertGreater(cappedTile.army, 440, "should not have dropped the cities at the leaves during the gather phase.")
                self.assertNoRepetition(simHost, minForRepetition=1,
                                        msg="should not re-gather cities or explore inefficiently. There should be zero excuse for ANY tile to be move source more than once in this sim.")

    def test_random_large_gather_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/random_large_gather_test___reOqoXEp2---g--864.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 864, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=864)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)
        # bot.timings = bot.get_timings()
        # bot.timings.splitTurns = 25

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts")  #  for random_large_gather_test

    def test_should_not_produce_invalid_path_during_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_produce_invalid_path_during_gather___b-TEST__10ec1926-ef6a-4efb-a6e6-d7a3a9017f00---b--553.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 560, fill_out_tiles=True)

        # self.disable_search_time_limits_and_enable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=560)

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=25)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=1)

    def test_gather_and_prune_should_not_produce_stupid_prune(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |
aG1  a1   a1   a1   a1   a1   a1   
a1   b1   b1   a1   a2   a2   a3  
a20  a1   a1   a1   b1   b1   b1  
a1   a1   a1   b1   b1   b1   b1  
a1   a1   b1   b1   b1   b1   b1  
a2   b1   b1   b1   b1   b1   b1  
b1   b1   b1   b1   b1   b1   bG1
|    |    |    |    | 
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        # self.disable_search_time_limits_and_enable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general_from_string(testData, 102)

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        bot = simHost.bot_hosts[general.player].eklipz_bot
        targets = [bot._map.GetTile(0, 1), bot._map.GetTile(1, 1), bot._map.GetTile(2, 1)]
        move, valGathered, turnsUsed, nodes = bot.get_gather_to_target_tiles(targets, 0.1, 6, shouldLog=True)

        viewInfo = bot.viewInfo
        viewInfo.gatherNodes = nodes
        if debugMode:
            self.render_view_info(map, viewInfo, f"valueGath {valGathered}")

        self.assertEqual(23, valGathered)
        self.assertEqual(5, turnsUsed)

    def test_should_not_poor_gather_turns_4(self):
        mapFile = 'GameContinuationEntries/should_not_poor_gather_turns_4___HgSVtA0p2---a--321.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 321, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=321)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        m = simHost.get_player_map(general.player)
        self.begin_capturing_logging()

        bot = self.get_debug_render_bot(simHost, general.player)
        # bot.timings.launchTiming = rawMap.turn + 4
        # bot.timings.splitTurns = rawMap.turn + 4
        prioTiles = set()
        # prioTiles.add(m.GetTile(7,12))
        # prioTiles.add(m.GetTile(5,7))
        # bot.timing_gather(bot.target_player_gather_path.tileList, skipTiles=None, skipTiles=None, force=True, priorityTiles=prioTiles, targetTurns=4)

        skipFunc = None
        if m.remainingPlayers > 2:
            # avoid gathering to undiscovered tiles when there are third parties on the map
            skipFunc = lambda tile, tilePriorityObject: not tile.discovered

        enemyDistanceMap = bot.board_analysis.intergeneral_analysis.bMap
        value, usedTurns, nodes = Gather.knapsack_depth_gather_with_values(
            m,
            bot.target_player_gather_path.tileList,
            4,
            negativeTiles=None,
            searchingPlayer=general.player,
            skipFunc=skipFunc,
            viewInfo=bot.viewInfo,
            skipTiles=None,
            distPriorityMap=enemyDistanceMap,
            priorityTiles=None,
            includeGatherTreeNodesThatGatherNegative=True,
            incrementBackward=False)
        bot.viewInfo.gatherNodes = nodes
        # self.render_view_info(m, bot.viewInfo, f"ur mum {value}")
        # 26 from top, plus the 9 that it can grab below.
        self.assertEqual(35, value)
    
    def test_should_not_generate_too_large_an_input_to_knapsack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_generate_too_large_an_input_to_knapsack___PFKmbadYE---0--477.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 477, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=477)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_get_errors_about_nodes_missing_from_tree(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_get_errors_about_nodes_missing_from_tree___nY3K5KoTe---1--267.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 267, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=267)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
        self.assertIsNone(winner)
    
    def test_should_find_gather_in_2v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_gather_in_2v2___MCevHMnq----1--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts")  #  for should_find_gather_in_2v2
    
    def test_should_not_have_no_gather_found(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_have_no_gather_found___Teammate.exe-1Yd71gW48---2--204.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 204, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=204)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts")  #  for should_not_have_no_gather_found
    
    def test_should_not_crash_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_crash_defense___Slz-t4I-a---1--337.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 337, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=337)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)
    
    def test_should_not_divide_by_zero(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_divide_by_zero___wpQIlrcjn---1--201.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 201, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=201)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=16)
        self.assertIsNone(winner)
        city = playerMap.GetTile(21, 1)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_prune_to_less_than_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_prune_to_less_than_threat___hjwxdn1qF---1--90.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 90, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 13, 19)
        enemyAllyGen = self.move_enemy_general(map, enemyAllyGen, 10, 23)
        # self.render_map(map)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=90)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)
        self.assertNoRepetition(simHost, minForRepetition=3)

    def test_should_not_leave_all_its_army_on_edge_when_out_of_play_gathering(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_leave_all_its_army_on_edge_when_out_of_play_gathering___gUX8yTL0J---1--600.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 600, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=600)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_leave_all_its_army_on_edge_when_out_of_play_gathering")
    
    def test_should_gather_far_non_leaves_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_far_non_leaves_first___9gaR3CZwL---1--132.txtmap'
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

        self.skipTest("TODO add asserts for should_gather_far_non_leaves_first")
    
    def test_should_gather_far_non_leaves_first__2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_far_non_leaves_first___9gaR3CZwL---1--157.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 157, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=157)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_gather_far_non_leaves_first")
    
    def test_should_gather_useless_back_corner_tiles_and_not_do_final_3_move_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_useless_back_corner_tiles_and_not_do_final_3_move_gather___XXMw2d0tO---0--176.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 176, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=176)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.launchTiming = 29
        bot.timings.splitTurns = 29
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.assertEqual(1, playerMap.GetTile(19, 5).army)
        self.assertEqual(1, playerMap.GetTile(19, 4).army)
        self.assertEqual(1, playerMap.GetTile(18, 4).army)
        self.assertEqual(1, playerMap.GetTile(16, 3).army)
        self.assertEqual(1, playerMap.GetTile(15, 3).army)
        self.assertEqual(1, playerMap.GetTile(15, 4).army)

    def test_should_not_leave_tiles_behind_gathering(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_leave_tiles_behind_gathering___THq1ygSqm---0--218.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 218, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=218)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.launchTiming = 36
        bot.timings.splitTurns = 36
        playerMap = simHost.get_player_map(general.player)
        bot.cities_gathered_this_cycle.add(playerMap.GetTile(5, 9))

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.assertGreater(bot.sum_friendly_army_near_or_on_tiles([playerMap.GetTile(2, 7)]), 15)

    def test_should_not_produce_missing_tree_node(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_neut_city_quickly___PHkfTkNU7---0--249.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 249, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=249)

        map.GetTile(19, 6).player = -1
        map.GetTile(19, 6).isCity = False
        map.GetTile(19, 6).isMountain = True
        map.GetTile(19, 6).army = 0

        rawMap.GetTile(19, 6).player = -1
        rawMap.GetTile(19, 6).isCity = False
        rawMap.GetTile(19, 6).isMountain = True
        rawMap.GetTile(19, 6).army = 0

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=11)
        self.assertIsNone(winner)
        city = self.get_player_tile(17, 10, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
        self.assertLess(city.turn_captured, 259)
    
    def test_should_not_drop_gather_moves_weirdly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for i in range(5):
            mapFile = 'GameContinuationEntries/should_not_drop_gather_moves_weirdly___fXx2Wf3_D---0--223.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=223)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)
            self.mark_armies_as_entangled(bot, playerMap.GetTile(12, 10), [playerMap.GetTile(8, 6), playerMap.GetTile(12, 10)])
            # army = bot.armyTracker.armies[playerMap.GetTile(8, 6)]
            # army.expectedPaths.append(Path.from_string(playerMap, '8,6->11,6->11,5->12,5->12,4->16,4->16,3->17,3->17,1->19,1->19,0->20,0'))

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
            self.assertIsNone(winner)

            self.assertEqual(11, playerMap.GetTile(7, 2).army)
            debugMode = False

    def test_should_not_find_missing_node(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_find_missing_node___uY5YnPrx_---0--362.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 362, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=362)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_not_pull_tiles_from_enemy_territory(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_pull_tiles_from_enemy_territory___N-66i9Hg_---0--201.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 201, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=201)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_pull_tiles_from_enemy_territory")

# 11f 14p 6s    
    def test_should_pull_from_backwards_tiles_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_pull_from_backwards_tiles_first___ocPjZe5c----1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings.splitTurns = 30
        bot.timings.launchTiming = 32
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=27)
        self.assertNoFriendliesKilled(map, general)

        for tile in [
            # playerMap.GetTile(6, 8),  # its reasonable to leave this one out there to expand later.
            # playerMap.GetTile(5, 8),  # its reasonable to leave this one out there to expand later.
            playerMap.GetTile(5, 9),
            playerMap.GetTile(6, 9),
            playerMap.GetTile(4, 10),
            playerMap.GetTile(5, 10),
            playerMap.GetTile(6, 11),
            playerMap.GetTile(5, 11),
            playerMap.GetTile(5, 12),
            playerMap.GetTile(0, 14),
            # playerMap.GetTile(2, 16),  # its reasonable to leave this one out there to expand later.
            playerMap.GetTile(2, 15),
            playerMap.GetTile(0, 13),
            playerMap.GetTile(1, 13),
            playerMap.GetTile(1, 11),
            playerMap.GetTile(2, 12),
            playerMap.GetTile(3, 12),
        ]:
            self.assertEqual(1, tile.army, f'tile {tile} should have been gathered or expanded, but its army was {tile.army}')
    
    def test_should_not_drop_obvious_gather_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_drop_obvious_gather_tile___cIm1H61C5---0--122.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 122, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=122)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertNoFriendliesKilled(map, general)

        tilesShouldHaveGathered = [playerMap.GetTile(x, 3) for x in range(4, 13)]
        tilesUngathered = [t for t in tilesShouldHaveGathered if t.army > 1]
        self.assertEqual(0, len(tilesUngathered), f'should have gathered {" | ".join([str(t) for t in tilesUngathered])}')

    def test_should_not_drop_obvious_gather_tile__short(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_drop_obvious_gather_tile___cIm1H61C5---0--122.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 122, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=122)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertNoFriendliesKilled(map, general)

        tilesShouldHaveGathered = [playerMap.GetTile(x, 3) for x in range(10, 13)]
        tilesUngathered = [t for t in tilesShouldHaveGathered if t.army > 1]
        self.assertEqual(0, len(tilesUngathered), f'should have gathered {" | ".join([str(t) for t in tilesUngathered])}')
    
    def test_should_not_do_horrible_things_when_trying_to_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_do_horrible_things_when_trying_to_gather___BpSFwcjC4---1--273.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 273, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=273)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_not_do_horrible_things_when_trying_to_gather")
    
    def test_shouldnt_throw_errors_doing_max_set_gath(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_throw_errors_doing_max_set_gath___R9ItulheP---0--409.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 409, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=409)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for shouldnt_throw_errors_doing_max_set_gath")
    
    def test_gather_should_not_crash_in_2v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/gather_should_not_crash_in_2v2___wy2MPWkXM---2--68.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 68, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=68)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        simHost.reveal_player_general(enemyGeneral.player, general.player, hidden=True)
        simHost.reveal_player_general(enemyAllyGen.player, general.player, hidden=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general, allyGen)

        self.skipTest("TODO add asserts for gather_should_not_crash_in_2v2")
    
    def test_pcst_gather_should_not_try_to_warp_between_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/pcst_gather_should_not_try_to_warp_between_tiles___63A1QDrpm---1--455.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 455, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=455)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        # good enough that it doesn't crash
    
    def test_should_gather_backwards_tiles_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_backwards_tiles_first___SeEsqyvhl---0--200.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 200, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=200)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertNoFriendliesKilled(map, general)

        self.assertGatheredNear(simHost, general.player, 4, 15, 3, requiredAvgTileValue=1.4)
