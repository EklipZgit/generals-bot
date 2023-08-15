import logging
import os
import pathlib

import EarlyExpandUtils
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from BotHost import BotHostBase
from CityAnalyzer import CityAnalyzer
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase, Tile, Score
from bot_ek0x45 import EklipZBot


class CityAnalyzerTests(TestBase):

    def test_analyzes_cities__produces_expandability(self):
        map, general = self.load_map_and_general(f'WonFullMapVisionSampleMaps/Be72k28nn---b--552.txtmap', turn=5)

        enemyGen = self.generate_opposite_general_and_give_tiles(map, general, tileAmount=45, armyOnTiles=3)

        analyzer = CityAnalyzer(map, general)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        analyzer.re_scan(boardAnalysis)

        # self.render_city_analysis_main_scores(map, boardAnalysis, analyzer)

        cityList = analyzer.get_sorted_neutral_scores()
        self.assertEqual(map.GetTile(14,6), cityList[0][0])
        self.assertEqual(map.GetTile(16,11), cityList[1][0])
        self.assertEqual(map.GetTile(12,3), cityList[2][0])
        self.assertEqual(map.GetTile(11,4), cityList[3][0])
        self.assertEqual(map.GetTile(13,11), cityList[4][0])
        self.assertEqual(map.GetTile(15,17), cityList[5][0])
        self.assertEqual(map.GetTile(5,0), cityList[6][0])
        self.assertEqual(map.GetTile(11,13), cityList[7][0])
        self.assertEqual(map.GetTile(7,7), cityList[8][0])


    def test_analyzes_cities__takes_city_behind_general_in_pocket(self):
        map, general = self.load_map_and_general(f'WonFullMapVisionSampleMaps/BeeYqbhU23---c--350.txtmap', turn=5)

        enemyGen = self.generate_opposite_general_and_give_tiles(map, general, tileAmount=75, armyOnTiles=3)

        analyzer = CityAnalyzer(map, general)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        analyzer.re_scan(boardAnalysis)

        # self.render_city_analysis_main_scores(map, boardAnalysis, analyzer)

        cityList = analyzer.get_sorted_neutral_scores()
        self.assertEqual(map.GetTile(0,13), cityList[0][0])
        self.assertEqual(map.GetTile(6,18), cityList[1][0])
        self.assertEqual(map.GetTile(7,17), cityList[2][0])
        self.assertEqual(map.GetTile(0,9), cityList[3][0])
        self.assertEqual(map.GetTile(5,9), cityList[4][0])


    def test_analyzes_cities__takes_cities_in_line_with_agressive_pathing(self):
        map, general = self.load_map_and_general(f'WonFullMapVisionSampleMaps/BemI6cUn2---a--80.txtmap', turn=5)

        enemyGen = self.generate_opposite_general_and_give_tiles(map, general, tileAmount=100, armyOnTiles=3)

        analyzer = CityAnalyzer(map, general)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        analyzer.re_scan(boardAnalysis)

        # self.render_city_analysis_main_scores(map, boardAnalysis, analyzer)

        cityList = analyzer.get_sorted_neutral_scores()
        self.assertEqual(map.GetTile(8,21), cityList[0][0])
        self.assertEqual(map.GetTile(10,18), cityList[1][0])
        self.assertEqual(map.GetTile(7,15), cityList[2][0])
        self.assertEqual(map.GetTile(2,18), cityList[3][0])
        self.assertEqual(map.GetTile(9,13), cityList[4][0])


    def test_analyzes_cities__enemy_city_analysis_makes_sense(self):
        map, general = self.load_map_and_general(f'WonFullMapVisionSampleMaps/Be72k28nn---b--552.txtmap', turn=5)

        enemyGen = self.generate_opposite_general_and_give_tiles(map, general, tileAmount=45, armyOnTiles=3)
        tilesToMakeEnemyCities = [
            map.GetTile(0, 10),
            map.GetTile(0, 4),
            map.GetTile(7, 7),
            map.GetTile(16, 11)
        ]

        for tile in tilesToMakeEnemyCities:
            map.update_visible_tile(tile.x, tile.y, tile_type=enemyGen.player, tile_army=tile.army, is_city=True, is_general=False)

        analyzer = CityAnalyzer(map, general)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        analyzer.re_scan(boardAnalysis)

        # self.render_city_analysis_main_scores(map, boardAnalysis, analyzer)

        cityList = analyzer.get_sorted_enemy_scores()
        self.assertEqual(map.GetTile(16,11), cityList[0][0])
        self.assertEqual(map.GetTile(7,7), cityList[1][0])
        # could go either way
        self.assertEqual(map.GetTile(0,4), cityList[2][0])
        self.assertEqual(map.GetTile(0,10), cityList[3][0])

    # def test_produces_plans_as_good_or_better_than_historical(self):
    #     projRoot = pathlib.Path(__file__).parent
    #     folderWithHistoricals = projRoot / f'../Tests/WonFullMapVisionSampleMaps'
    #     files = os.listdir(folderWithHistoricals)
    #     for file in files:
    #         map, general = self.load_map_and_general(f'WonFullMapVisionSampleMaps/{file}', turn=50)
    #
    #         with self.subTest(file=file.split('.')[0]):
    #             enemyGen = self.generate_opposite_general_and_give_tiles(map, general, tileAmount=100, armyOnTiles=3)
    #
    #             analyzer = CityAnalyzer(map, general)
    #
    #             boardAnalysis = BoardAnalyzer(map, general)
    #             boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
    #
    #             analyzer.re_scan(boardAnalysis)
    #
    #             self.render_city_analysis_main_scores(map, boardAnalysis, analyzer)

    def render_city_analysis_main_scores(self, map: MapBase, boardAnalysis: BoardAnalyzer, cityAnalysis: CityAnalyzer):
        viewInfo = self.get_view_info(map)
        tileScores = cityAnalysis.get_sorted_neutral_scores()
        enemyTileScores = cityAnalysis.get_sorted_enemy_scores()

        for i, ts in enumerate(tileScores):
            tile, cityScore = ts
            viewInfo.midLeftGridText[tile.x][tile.y] = f'c{i}'
            EklipZBot.add_city_score_to_view_info(cityScore, viewInfo)

        for i, ts in enumerate(enemyTileScores):
            tile, cityScore = ts
            viewInfo.midLeftGridText[tile.x][tile.y] = f'm{i}'
            EklipZBot.add_city_score_to_view_info(cityScore, viewInfo)

        self.render_view_info(map, viewInfo, 'whatever')
