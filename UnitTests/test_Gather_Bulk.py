import logbook
import time
import typing

import DebugHelper
import GatherUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot


class GatherBulkTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        bot.info_render_centrality_distances = True
        GatherUtils.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True

        return bot

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
            playerIndex: int = 0
    ):
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testMapStr, 102, player_index=playerIndex)
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
            debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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
                (22, 142),
                (23, 146),
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
                            targetsAreEnemy=targetsAreEnemy,  # whether tiles are friendly or enemy should not matter to the amount gathered
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

    def test_gather__adversarial_large_gather__big_map(self):
        """
        Same as test_gather__adversarial_far_tiles_to_gather, except must also break through a line of enemy tiles
        that divides the high value gather cluster from the low value cluster.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = TextMapLoader.get_map_raw_string_from_file('GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap')
        cases = [
            35,
            45,
            55,
            65,
            75,
            85,
        ]

        targetXYs = [
            (23, 4),
        ]

        inclNegative = False
        useTrueVal = True

        for depth in cases:
            with self.subTest(depth=depth):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather=None,
                    inclNegative=inclNegative,
                    useTrueVal=useTrueVal,
                    targetsAreEnemy=True,
                    testTiming=True,
                    debugMode=debugMode,
                    playerIndex=1,
                )