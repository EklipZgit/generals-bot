from ArmyAnalyzer import ArmyAnalyzer
from TestBase import TestBase


class ArmyAnalyzerUnitTests(TestBase):
    def test_builds_correct_pathways(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, player_index=1)

        enTile = map.GetTile(6, 10)
        analyzer = ArmyAnalyzer(map, general, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        self.assertFalse(analyzer.is_choke(map.GetTile(7, 10)))
        self.assertFalse(analyzer.is_choke(map.GetTile(6, 9)))
        self.assertFalse(analyzer.is_choke(map.GetTile(7, 9)))
        self.assertFalse(analyzer.is_choke(map.GetTile(6, 8)))

        self.assertTrue(analyzer.is_choke(map.GetTile(7, 8)), 'the choke in front of the general should be in chokes')
        self.assertTrue(analyzer.is_choke(map.GetTile(8, 8)), 'the general itself should be in chokes')
        self.assertTrue(analyzer.is_choke(map.GetTile(6, 10)), 'threat itself should be in chokes')

        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(6, 9)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(7, 9)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(6, 9)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(6, 8)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(7, 10)])

    def test_should_recognize_inbound_choke_points(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_allow_opp_to_walk_all_over_territory___Hn8ec1Na9---0--283.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

        allyTile = map.GetTile(2, 5)
        enTile = map.GetTile(4, 11)
        analyzer = ArmyAnalyzer(map, allyTile, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        defensePoint = map.GetTile(2, 7)
        self.assertIn(defensePoint, analyzer.chokeWidths)

        cw = analyzer.chokeWidths[defensePoint]
        self.assertEqual(2, cw)

        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(0, 7)])
        self.assertEqual(0, analyzer.interceptChokes[map.GetTile(0, 8)], 'can hit 1,8 choke from 1 behind')
        self.assertGreaterEqual(analyzer.interceptChokes[map.GetTile(3, 7)], 1, '2 moves to reach 1,7')  # TODO really, this should be 1 still, because we can reach all the tiles nearby in less time than 1,7 even though 1,7 isn't a choke
        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(3, 8)], '2 moves to hit choke, so 1')
        # self.assertNotIn(allyTile, analyzer.interceptChokes, 'the tiles themselves should not be a choke (?)')
        # self.assertNotIn(enTile, analyzer.interceptChokes, 'the tiles themselves should not be a choke (?)')
        self.assertIn(defensePoint, analyzer.interceptChokes)
        icw = analyzer.interceptChokes[defensePoint]
        self.assertEqual(1, icw)

        innerChoke0 = map.GetTile(1, 8)
        self.assertIn(innerChoke0, analyzer.interceptChokes)
        icw0 = analyzer.interceptChokes[innerChoke0]
        self.assertEqual(-1, icw0, "should be a one-move-behind intercept once we're here because it full blocks a choke.")

    def test_should_recognize_inbound_intercept_choke_turns(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_allow_opp_to_walk_all_over_territory___Hn8ec1Na9---0--283.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

        allyTile = map.GetTile(2, 5)
        enTile = map.GetTile(4, 11)
        analyzer = ArmyAnalyzer(map, allyTile, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        self.assertEqual(7, analyzer.interceptTurns[map.GetTile(1, 8)], 'can get here 7 moves in to the intercept, 1 behind opp, and will always still kill in 2 moves.')

        self.assertEqual(6, analyzer.interceptTurns[map.GetTile(2, 8)], 'if we dont get here by turn 6, then opp can have reached 1,7 and the 1 move intercept moves account will be a lie.')

        self.assertEqual(5, analyzer.interceptTurns[map.GetTile(3, 8)], 'if we dont get here by turn 5, then opp can have reached 1,7 and the 2 move intercept moves account will be a lie.')

        self.assertEqual(6, analyzer.interceptTurns[map.GetTile(0, 8)], 'if we dont get here by turn 6, then opp can have reached 1,7 or 2,8 and the 2 move intercept moves account will be a lie.')
        self.assertEqual(7, analyzer.interceptTurns[map.GetTile(2, 7)], 'this is tricky, if we assume opp can capture 1,8->2,8->0,7, then this is a lie. Otherwise if we just assume opp straight-shot-threats, we can get here 7 moves in to the intercept, 1 behind opp, and will always still kill in 2 moves.')
        self.assertEqual(6, analyzer.interceptTurns[map.GetTile(3, 7)], 'this is tricky, if we assume opp can capture 1,8->2,8->0,7, then this is a lie. Otherwise if we just assume opp straight-shot-threats, we can get here 7 moves in to the intercept, 1 behind opp, and will always still kill in 2 moves.')

    def test_should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        allyTile = map.GetTile(14, 2)
        enTile = map.GetTile(4, 8)
        analyzer = ArmyAnalyzer(map, allyTile, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        defensePoint = map.GetTile(2, 7)
        self.assertIn(defensePoint, analyzer.chokeWidths)
        #
        # cw = analyzer.chokeWidths[defensePoint]
        # self.assertEqual(2, cw)

        self.assertNotIn(map.GetTile(0, 7), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(0, 8), analyzer.interceptChokes)
        self.assertIn(map.GetTile(3, 7), analyzer.interceptChokes, 'we should include tiles 1-outside-the-shortest-path in the intercept list since they can all potentially have guaranteed captures still.')
        self.assertIn(map.GetTile(3, 8), analyzer.interceptChokes)
        self.assertEqual(0, analyzer.interceptChokes[map.GetTile(3, 8)], 'tiles just outside the intercept zone ')
        self.assertEqual(1, analyzer.interceptChokes[allyTile], 'generals require two extra intercept moves as they must be arrived at one turn early')
        self.assertEqual(-1, analyzer.interceptChokes[enTile], 'the tiles themselves should be a full-choke (-1)')

    def test_should_intercept_when_moving_around_obstacle(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   b1
a1   a1   a1   M    a1   b1   b1
aG20 a1   a1   M    b1   b1   bG20
a1   a1   b1   M    b1   b1   b1
a1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
|    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181, fill_out_tiles=True)

        analyzer = ArmyAnalyzer(map, general, enemyGeneral)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        self.assertEqual(1, analyzer.interceptChokes[general])
        self.assertEqual(1, analyzer.interceptChokes[enemyGeneral])
        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(1, 3)])
        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(5, 3)])
        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(0, 4)])

    def test_should_see_inside_choke_when_choke_opens_up(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
aG20 a1   a1   M    a1   a1   a1
a1   a1   a1   M    a1   a1   b1
a1   a1   a1   M    a1   b1   b1
a1   a1   a1        b1   b1   b1
a1   a1   b1   M    b1   b1   b1
a1   b1   b1   M    b1   b1   b1
b1   b1   b1   M    b1   b1   bG20
|    |    |    |
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181, fill_out_tiles=True)

        analyzer = ArmyAnalyzer(map, general, enemyGeneral)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        self.assertEqual(1, analyzer.interceptChokes[general])
        self.assertEqual(1, analyzer.interceptChokes[enemyGeneral])
        self.assertEqual(-1, analyzer.interceptChokes[map.GetTile(2, 3)], 'if we get to this tile the same time as opp, we are guaranteed to intercept')
        self.assertEqual(-1, analyzer.interceptChokes[map.GetTile(3, 3)], 'if we get to this tile the same time as opp, we are guaranteed to intercept')
        self.assertEqual(-1, analyzer.interceptChokes[map.GetTile(4, 3)], 'if we get to this tile the same time as opp, we are guaranteed to intercept')

        self.assertEqual(0, analyzer.interceptChokes[map.GetTile(2, 2)], 'if we get to this tile one ahead of when opp could, we are guaranteed to intercept BECAUSE we can catch one move behind')
        self.assertEqual(0, analyzer.interceptChokes[map.GetTile(2, 4)], 'if we get to this tile one ahead of when opp could, we are guaranteed to intercept BECAUSE we can catch one move behind')

        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(5, 4)], 'if we get to this tile one ahead of when opp could, we are guaranteed to intercept immediately. Cannot be less than 1 because a runby on 6,4 is possible.')
        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(5, 5)], '" above, except runby on 6,5.')
        self.assertEqual(1, analyzer.interceptChokes[map.GetTile(1, 2)], 'Like 5,4, 1,2 should be 1 because a runby on 2,2 gets away if we reach 1,3 the same turn the opp could.')

# 0f 5p 0s

    def test_should_meet_to_defend_multi_choke__when_can_reach_not_one_behind(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   a40  b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)
        enTile = map.GetTile(3, 11)
        analyzer = ArmyAnalyzer(map, general, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)
        for y in range(12):
            tile = map.GetTile(3, y)
            self.assertTrue(analyzer.is_choke(tile), 'all tiles down the middle should be full chokes')
            expectedChoke = -1
            if y == 0:
                expectedChoke = 1
            if y == 1:
                expectedChoke = 0

            self.assertEqual(expectedChoke, analyzer.interceptChokes[tile], 'all tiles down the middle should be full chokes. Near gen should be 0, and gen should be 1.')

    def test_should_understand_can_intercept_event_against_corner(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   a40  b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)
        enTile = map.GetTile(3, 11)
        frTile = map.GetTile(6, 0)
        analyzer = ArmyAnalyzer(map, frTile, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        canInterceptStillTile = map.GetTile(2, 9)
        self.assertEqual(1, analyzer.interceptTurns[canInterceptStillTile], 'can intercept from this tile 1 turn from now by chasing to the right for 4 moves max')
        self.assertEqual(4, analyzer.interceptDistances[canInterceptStillTile], 'can intercept from this tile by chasing to the right for 4 moves max')
        self.assertEqual(4, analyzer.interceptDistances[canInterceptStillTile], 'can intercept from this tile by chasing to the right for 4 moves max')
