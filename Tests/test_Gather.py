import logging
import time
import typing

import GatherUtils
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import TILE_EMPTY


class GatherTests(TestBase):
    def run_adversarial_gather_test_all_algorithms(
            self,
            testMapStr: str,
            targetXYs: typing.List[typing.Tuple[int, int]],
            depth: int,
            expectedGather: int | None,
            inclNegative: bool,
            useTrueVal: bool = False,
            targetsAreEnemy: bool | None = None,
            testTiming: bool = False,
            debugMode: bool = False,
            incGreedy: bool = True,
            incRecurse: bool = True,
    ):
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testMapStr, 102, player_index=0)
        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general_from_string(testMapStr, 102)
        if targetsAreEnemy is not None:
            tgPlayer = general.player
            if targetsAreEnemy:
                tgPlayer = enemyGeneral.player
            for x, y in targetXYs:
                mapTg = map.GetTile(x, y)
                rawMapTg = rawMap.GetTile(x, y)
                mapTg.player = tgPlayer
                rawMapTg.player = tgPlayer

        self.begin_capturing_logging()
        self.disable_search_time_limits_and_enable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        if testTiming:
            # dont skew the timing with the expensive debug asserts.
            GatherUtils.USE_DEBUG_ASSERTS = False
        else:
            GatherUtils.USE_DEBUG_ASSERTS = True

        bot = simHost.bot_hosts[general.player].eklipz_bot

        targets = [bot._map.GetTile(x, y) for x, y in targetXYs]

        start = time.perf_counter()
        move, valGathered, turnsUsed, nodes = bot.get_gather_to_target_tiles(
            targets,
            0.1,
            depth,
            shouldLog=False,
            useTrueValueGathered=useTrueVal,
            includeGatherTreeNodesThatGatherNegative=inclNegative)
        dur = time.perf_counter() - start

        for n in nodes:
            n.strip_all_prunes()

        viewInfo = bot.viewInfo
        if debugMode:
            viewInfo.gatherNodes = nodes
            self.render_view_info(map, viewInfo, f"ITER {valGathered} / {expectedGather},  {turnsUsed} / {depth}")

        if incGreedy:
            greedyStart = time.perf_counter()
            greedyValGathered, greedyTurnsUsed, greedyNodes = GatherUtils.greedy_backpack_gather_values(
                map,
                startTiles=targets,
                turns=depth,
                searchingPlayer=general.player,
                useTrueValueGathered=useTrueVal,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                shouldLog=False)
            greedyDur = time.perf_counter() - greedyStart
            for n in greedyNodes:
                n.strip_all_prunes()

            if debugMode:
                viewInfo.gatherNodes = greedyNodes
                self.render_view_info(map, viewInfo,
                                      f"GREED {greedyValGathered} / {expectedGather},  {greedyTurnsUsed} / {depth}")
        if incRecurse:
            recurseStart = time.perf_counter()
            recurseValGathered, recurseNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
                map,
                startTiles=targets,
                turns=depth,
                searchingPlayer=general.player,
                useTrueValueGathered=useTrueVal,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                ignoreStartTile=True,
                shouldLog=False,
                useRecurse=True
            )
            recurseDur = time.perf_counter() - recurseStart
            recurseTurnsUsed = 0
            for n in recurseNodes:
                n.strip_all_prunes()
                recurseTurnsUsed += n.gatherTurns

            if debugMode:
                viewInfo.gatherNodes = recurseNodes
                self.render_view_info(map, viewInfo,
                                      f"RECUR {recurseValGathered} / {expectedGather},  {recurseTurnsUsed} / {depth}")

        if not testTiming:
            if incRecurse and recurseValGathered > valGathered:
                self.fail(f'gather depth {depth} gathered {valGathered} compared to recurse {recurseValGathered}')

            if incGreedy and greedyValGathered > valGathered:
                self.fail(f'gather depth {depth} gathered {valGathered} compared to greedy {greedyValGathered}')
            if expectedGather is not None:
                self.assertEqual(expectedGather, valGathered)
            self.assertEqual(depth, turnsUsed)

        if testTiming:
            if incRecurse and dur > recurseDur:
                self.fail(f'gather depth {depth} took {dur:.3f} compared to recurse {recurseDur:.3f}')

            if incGreedy and dur > greedyDur:
                self.fail(f'gather depth {depth} took {dur:.3f} compared to greedy {greedyDur:.3f}')

            if dur > 0.05:
                self.fail(f'gather depth {depth} took {dur:.3f}')

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
        self.assertEqual(8, valueGathered)
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
        self.assertEqual(8, valueGathered)
        self.assertEqual(7, turnsUsed)

        sumVal = 0
        sumTurns = 0
        for node in gatherNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns
        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        postPruneNodes = GatherUtils.prune_mst_to_turns(gatherNodes, turnsUsed, general.player, viewInfo=ekBot.viewInfo, noLog=False)

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
        self.assertEqual(8, valueGathered)

        sumVal = 0
        sumTurns = 0
        for node in gatherNodes:
            sumVal += node.value
            sumTurns += node.gatherTurns
        self.assertEqual(valueGathered, sumVal)
        self.assertEqual(turnsUsed, sumTurns)

        postPruneNodes = GatherUtils.prune_mst_to_turns(gatherNodes, turnsUsed - 1, general.player, viewInfo=ekBot.viewInfo, noLog=False)

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
        self.assertEqual(8, valueGathered)
        self.assertEqual(7, turnsUsed)

        pruneNearZeroMovesCases = [-1, 0, 1]
        for pruneNearZeroMovesCase in pruneNearZeroMovesCases:
            with self.subTest(pruneNearZeroMovesCase=pruneNearZeroMovesCase):
                toPrune = [node.deep_clone() for node in gatherNodes]
                postPruneNodes = GatherUtils.prune_mst_to_turns(toPrune, pruneNearZeroMovesCase, general.player, viewInfo=ekBot.viewInfo, noLog=False)
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
                self.set_general_emergence_around(17, 5, simHost, general.player, enemyGeneral.player, 20)
                self.set_general_emergence_around(16, 7, simHost, general.player, enemyGeneral.player, 30)

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

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts")  #  for random_large_gather_test

    def test_should_not_produce_invalid_path_during_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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

        bot = simHost.get_bot(general.player)
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
        value, nodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
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

    def test_gather__adversarial_to_large_iterative_gather_to_small_tileset(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |    |
aG1  a11  a2   a3   a2   a3   a1   a21
a21  a21  a2   a2   a2   a1   a1   a1  
a21  b1   b1   b1   b1   b1   a2   a3  
a21  a21  a2   a2   a2   a1   a2   a1  
a11  a21  a2   a3   a2   a6   a2   a21
a2   a2   a2   a3   a1   a1   a1   b1  
a2   a2   a2   a23  a15  b1   b1   b1  
a2   a3   a2   a3   b1   b1   b1   b1  
a2   a2   a1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a1   b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (2, 40),
            (1, 20),
            (3, 60),
            (4, 80),
            (5, 100),
            (6, 120),
            (7, 130),  # now we run out of 21 tiles within 1 extension, next best is a 10 @ 1,0 or 0,4
            (8, 140),  # ditto, other one
            (9, 141),  # next best is just a 2 (1)
            (10, 147),  # grab the 23 on 3,6 in place of the 11s
            (11, 161),  # add on the 4,6 15
            (12, 171),  # add the 11 back in
            (13, 181),  # add other 11 back in
            (14, 183),  # add a 3
            (15, 187),  # swap the 3 for 6 + 2 (so 183 - 2 + 6)
            (16, 197),  # swap the 11 for reaching for 21 + 2.  198 is possible but bot prioritizes returning to trunk, which is desireable, so i wont assert the 198.
            (17, 207),  # add the 11 back in. 208 ditto above
            (18, 214),
            (19, 224),
            (20, 226),
            (21, 230),
            (22, 232),
            (23, 233),
            (24, 235),
            (25, 236),
            (26, 237),
            (27, 238),
            (28, 239),
            (29, 240),
        ]

        targetsAreEnemyCases = [
            False,
            True,
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]

        inclNegative = False

        for depth, expectedGather in cases:
            if depth > 10:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, expectedGather=expectedGather, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        expectedGather,
                        inclNegative,
                        targetsAreEnemy=targetsAreEnemy,
                        testTiming=False,
                        debugMode=debugMode)

            with self.subTest(depth=depth, expectedGather=expectedGather, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather,
                    inclNegative,
                    testTiming=True,
                    debugMode=False)

    def test_gather__basic_gather_all_combinations_of_true_val_neg_val(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |    |
aG1  a1   a2   a3   a2   a3   a1   a11
a1   a1   a1   a1   a1   a1   a1   a1  
a1   N10  N10  N10  N10  N10  a1   a3  
a2   a2                                
a2   a2   a2   a3   a2   a6   a2   a11
a2   a2   a2   a3   a1   a1   a1   b1  
a2   a2   a2   a23  a15  b1   b1   b1  
a2   a3   a2   a3   b1   b1   b1   b1  
a2   a2   a1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b2   b2   b2  
a1   b1   b1   b1   b1   b2   bG70 b2
|    |    |    |    | 
player_index=0
"""
        cases = [
            (3, 4),
            (1, 1),
            (2, 2),
            (4, 4),
            (5, 5),
            (6, 6),
            (7, 7),
            (8, 8),
            (9, 9),
            (10, 10),
            (11, 11),
            (12, 12),
            (13, 13),
            (14, 14),
            (15, 15),
            (16, 16),
            (17, 17),
            (18, 18),
            (19, 19),
            (20, 20),
            (21, 21),
            (22, 22),
            (23, 23),
            (24, 24),
            (25, 25),
            (26, 26),
            (27, 27),
            (28, 28),
            (29, 29),
        ]

        targetsAreEnemyCases = [
            False,
            True,
            None,
        ]

        incNegCases = [
            False,
            True
        ]

        trueValCases = [
            False,
            True
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for depth, expectedGather in cases:
            if depth > 6:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
            for targetsAreEnemy in targetsAreEnemyCases:
                for useTrueGatherVal in trueValCases:
                    for incNegative in incNegCases:
                        with self.subTest(
                                depth=depth,
                                # expectedGather=expectedGather,
                                incNegative=incNegative,
                                useTrueGatherVal=useTrueGatherVal,
                                targetsAreEnemy=targetsAreEnemy
                        ):
                            self.run_adversarial_gather_test_all_algorithms(
                                testData,
                                targetXYs,
                                depth,
                                None,
                                inclNegative=incNegative,
                                useTrueVal=useTrueGatherVal,
                                targetsAreEnemy=targetsAreEnemy,
                                testTiming=False,
                                debugMode=debugMode,
                                # incGreedy=False,
                                # incRecurse=False,
                            )

    def test_gather__adversarial_far_tiles_to_gather(self):
        """
        Test which represents a scenario where all of the players army is far from the main gather path, but is all clustered.
        Ideally the algo should find an optimal path to the cluster and then produce the main tree within the cluster, rather than producing suboptimal paths to the cluster.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |
aG1  a2   a2   a2   a2   a2   a2   a2 
a2   a2   a2   a2   a2   a2   a2   a2  
a2   b1   b1   b1   b1   b1   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2 
a2   a2   a2   a2   a2   a2   a2   a2  
a2   a2   a2   a2   a2   a2   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a1   a2   a2   a1   a1   a1  
a10  a5   a5   a4   a5   a5   a5   a10
a10  a5   a5   a5   a5   a5   a10  a15
a15  a5   b5   b5   b5   b5   b5   a25
a20  b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (24, 147),
            (1, 1),
            (2, 2),
            (3, 3),
            (4, 4),
            (5, 5),
            (6, 6),
            (7, 7),
            (8, 11),  # we can pick up our first 10
            (9, 17),  # our 5 and 10
            (10, 26),  # grab the 23 on 3,6 in place of the 11s
            (11, 40),
            (12, 59),  # 61 poss
            (13, 63),  # 65 poss
            (14, 67),  # 69 poss
            (15, 83),  # 83 if you switch to right side gather
            (16, 83),  #
            (17, 87),  #
            (18, 92),
            (19, 106),
            (20, 126),
            # for these higher ones, iterative produces two branches.
            # Need to implement a mid-tree disconnect-prune-reconnect approach to have it iteratively build a maximum connection in the tree
            (21, 135),
            (22, 139),
            (23, 143),
            (24, 147),
            (25, 151),
            (26, 165),
            (27, 169),
            (28, 173),
        ]

        targetsAreEnemyCases = [
            False,
            True,
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]
        inclNegative = True

        for depth, expectedGather in cases:
            if depth > 24:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, expectedGather=expectedGather, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        expectedGather,
                        inclNegative,
                        targetsAreEnemy=targetsAreEnemy,
                        testTiming=False,
                        debugMode=debugMode,
                        # incGreedy=False,
                        # incRecurse=False
                    )

            with self.subTest(depth=depth, expectedGather=expectedGather, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather,
                    inclNegative,
                    testTiming=True,
                    debugMode=False)

    def test_gather__adversarial_far_tiles_to_gather__through_enemy_lines(self):
        """
        Same as test_gather__adversarial_far_tiles_to_gather, except must also break through a line of enemy tiles
        that divides the high value gather cluster from the low value cluster.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |    |
aG1  a2   a2   a2   a2   a2   a2   a2 
a2   a2   a2   a2   a2   a2   a2   a2  
a2   b1   b1   b1   b1   b1   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2 
b3   b3   b3   b3   b3   b3   b3   b3  
a2   a2   a2   a2   a2   a2   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a1   a2   a2   a1   a1   a1  
a10  a5   a5   a4   a5   a5   a5   a10
a10  a5   a5   a5   a5   a5   a10  a15
a15  a5   b5   b5   b5   b5   b5   a25
a20  b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (8, 9),
            (1, 1),
            (2, 2),
            (3, 3),
            (4, 4),
            (5, 5),
            (6, 6),
            (7, 7),
            (9, 17 - 2),  # our 5 and 10
            (10, 26 - 2),  # grab the 23 on 3,6 in place of the 11s
            (11, 40 - 2),
            (12, 59 - 2),  # 61 poss
            (13, 63 - 2),  # 65 poss
            (14, 67 - 2),  # 69 poss
            (15, 83 - 2),  # 83 if you switch to right side gather
            (16, 83 - 2),  #
            (17, 87 - 2),  #
            (18, 92 - 2),
            (19, 106 - 2),
            (20, 126 - 2),
            # for these higher ones, iterative produces two branches.
            # Need to implement a mid-tree disconnect-prune-reconnect approach to have it iteratively build a maximum connection in the tree
            (21, 135 - 4),
            (22, 139 - 4),
            (23, 143 - 4),
            (24, 147 - 4),
            (25, 151 - 4),
            (26, 165 - 4),
            (27, 169 - 4),
            (28, 173 - 4),
        ]

        targetsAreEnemyCases = [
            False,
            True,
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]

        inclNegative = True
        useTrueVal = False

        for depth, expectedGather in cases:
            for targetsAreEnemy in targetsAreEnemyCases:
                if depth > 7:
                    debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
                with self.subTest(depth=depth, expectedGather=expectedGather, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        expectedGather,
                        inclNegative,
                        useTrueVal=useTrueVal,
                        targetsAreEnemy=targetsAreEnemy, # whether tiles are friendly or enemy should not matter to the amount gathered
                        testTiming=False,
                        debugMode=debugMode,
                    )

            with self.subTest(depth=depth, expectedGather=expectedGather, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather,
                    inclNegative,
                    useTrueVal=useTrueVal,
                    targetsAreEnemy=True,
                    testTiming=True,
                    debugMode=False,
                )
    
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=90)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_gather_far_non_leaves_first")
    
    def test_should_gather_far_non_leaves_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_far_non_leaves_first___9gaR3CZwL---1--157.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 157, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=157)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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