from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class ArmyAnalyzerTests(TestBase):
    def render_army_analyzer(self, map: MapBase, analyzer: ArmyAnalyzer):
        viewInfo = ViewInfo(0, map.cols, map.rows)
        board = BoardAnalyzer(map, analyzer.tileA, None)
        board.rebuild_intergeneral_analysis(analyzer.tileB)
        board.rescan_chokes()

        for tile in map.get_all_tiles():
            tileData = []
            pathWay = analyzer.pathWayLookupMatrix[tile]
            baPw = board.intergeneral_analysis.pathWayLookupMatrix[tile]
            if pathWay is None:
                if baPw is not None:
                    raise AssertionError(f'board pathway for {str(tile)} did not match og analysis pathway. board {str(baPw)} vs {str(pathWay)}')
                viewInfo.topRightGridText[tile.x][tile.y] = 'NONE'
                viewInfo.midRightGridText[tile.x][tile.y] = 'NONE'
            else:
                if baPw is None:
                    raise AssertionError(f'board pathway for {str(tile)} did not match og analysis pathway. board {str(baPw)} vs {str(pathWay)}')
                # viewInfo.midRightGridText[tile.x][tile.y] = f'pd{pathWay.distance}'
                # viewInfo.topRightGridText[tile.x][tile.y] = f'pc{len(pathWay.tiles)}'
            # viewInfo.midLeftGridText[tile.x][tile.y] = f'ad{analyzer.aMap[tile.x][tile.y]}'
            # viewInfo.bottomLeftGridText[tile.x][tile.y] = f'bd{analyzer.bMap[tile.x][tile.y]}'

            if tile in analyzer.chokeWidths:
                viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'cw{analyzer.chokeWidths[tile]}'

            if tile in analyzer.interceptChokes:
                viewInfo.bottomMidLeftGridText[tile.x][tile.y] = f'ic{analyzer.interceptChokes[tile]}'

            if tile in analyzer.pathChokes:
                if tile not in board.intergeneral_analysis.pathChokes:
                    raise AssertionError(
                        f'board choke mismatch for {str(tile)}. board False vs True')
                tileData.append('C')
            else:
                if tile in board.intergeneral_analysis.pathChokes:
                    raise AssertionError(
                        f'board choke mismatch for {str(tile)}. board False vs True')

            if board.outerChokes[tile.x][tile.y]:
                tileData.append('O')

            if board.innerChokes[tile.x][tile.y]:
                tileData.append('I')

            if len(tileData) > 0:
                viewInfo.bottomRightGridText[tile.x][tile.y] = ''.join(tileData)

        board.intergeneral_analysis = analyzer
        viewInfo.board_analysis = board
        self.render_view_info(map, viewInfo, 'xd')

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