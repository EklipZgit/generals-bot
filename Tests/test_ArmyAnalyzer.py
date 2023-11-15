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
                viewInfo.midRightGridText[tile.x][tile.y] = f'pd{pathWay.distance}'
                viewInfo.topRightGridText[tile.x][tile.y] = f'pc{len(pathWay.tiles)}'
            viewInfo.midLeftGridText[tile.x][tile.y] = f'ad{analyzer.aMap[tile.x][tile.y]}'
            viewInfo.bottomLeftGridText[tile.x][tile.y] = f'bd{analyzer.bMap[tile.x][tile.y]}'

            if tile in analyzer.chokeWidths:
                viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'w{analyzer.chokeWidths[tile]}'

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

