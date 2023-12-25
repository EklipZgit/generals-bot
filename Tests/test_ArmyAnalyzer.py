from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class ArmyAnalyzerTests(TestBase):
    def test_builds_correct_pathways(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'Defense/FailedToFindPlannedDefensePathForNoReason_Turn243/242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, player_index=1)

        enTile = map.GetTile(6, 10)
        analyzer = ArmyAnalyzer(map, general, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        self.assertNotIn(map.GetTile(7, 10), analyzer.pathChokes)
        self.assertNotIn(map.GetTile(6, 9), analyzer.pathChokes)
        self.assertNotIn(map.GetTile(7, 9), analyzer.pathChokes)
        self.assertNotIn(map.GetTile(6, 8), analyzer.pathChokes)

        self.assertIn(map.GetTile(6, 10), analyzer.pathChokes, 'threat itself should be in chokes')
        self.assertIn(map.GetTile(7, 8), analyzer.pathChokes, 'the choke in front of the general should be in chokes')
        self.assertIn(map.GetTile(8, 8), analyzer.pathChokes, 'the general itself should be in chokes')

        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(6, 9)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(7, 9)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(6, 9)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(6, 8)])
        self.assertEqual(2, analyzer.chokeWidths[map.GetTile(7, 10)])

    def test_should_recognize_inbound_choke_points(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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

        self.assertNotIn(map.GetTile(0, 7), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(0, 8), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(3, 7), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(3, 8), analyzer.interceptChokes)
        self.assertNotIn(allyTile, analyzer.interceptChokes, 'the tiles themselves should not be a choke (?)')
        self.assertNotIn(enTile, analyzer.interceptChokes, 'the tiles themselves should not be a choke (?)')
        self.assertIn(defensePoint, analyzer.interceptChokes)
        icw = analyzer.interceptChokes[defensePoint]
        self.assertEqual(1, icw)

        innerChoke0 = map.GetTile(1, 8)
        self.assertIn(innerChoke0, analyzer.interceptChokes)
        icw0 = analyzer.interceptChokes[innerChoke0]
        self.assertEqual(0, icw0, "should be a zero move intercept once we're here because it full blocks a choke.")

    def test_should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        allyTile = map.GetTile(14, 2)
        enTile = map.GetTile(4, 8)
        analyzer = ArmyAnalyzer(map, allyTile, enTile)

        if debugMode:
            self.render_army_analyzer(map, analyzer)

        defensePoint = map.GetTile(2, 7)
        self.assertIn(defensePoint, analyzer.chokeWidths)

        cw = analyzer.chokeWidths[defensePoint]
        self.assertEqual(2, cw)

        self.assertNotIn(map.GetTile(0, 7), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(0, 8), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(3, 7), analyzer.interceptChokes)
        self.assertNotIn(map.GetTile(3, 8), analyzer.interceptChokes)
        self.assertNotIn(allyTile, analyzer.interceptChokes, 'the tiles themselves should not be a choke (?)')
        self.assertNotIn(enTile, analyzer.interceptChokes, 'the tiles themselves should not be a choke (?)')
        self.assertIn(defensePoint, analyzer.interceptChokes)
        icw = analyzer.interceptChokes[defensePoint]
        self.assertEqual(1, icw)