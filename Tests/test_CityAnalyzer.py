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
        tileScores = []
        enemyTileScores = []
        for tile in map.get_all_tiles():
            score = None
            if tile in cityAnalysis.city_scores:
                score = cityAnalysis.city_scores[tile]
            if tile in cityAnalysis.enemy_city_scores:
                score = cityAnalysis.enemy_city_scores[tile]
            if tile in cityAnalysis.player_city_scores:
                score = cityAnalysis.player_city_scores[tile]
            if tile in cityAnalysis.undiscovered_mountain_scores:
                score = cityAnalysis.undiscovered_mountain_scores[tile]

            if score is None:
                continue

            viewInfo.topRightGridText[tile.x][tile.y] = f'r{f"{score.city_relevance_score:.2f}".strip("0")}'
            viewInfo.midRightGridText[tile.x][tile.y] = f'e{f"{score.city_expandability_score:.2f}".strip("0")}'
            viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'd{f"{score.city_defensability_score:.2f}".strip("0")}'
            viewInfo.bottomRightGridText[tile.x][tile.y] = f'g{f"{score.city_general_defense_score:.2f}".strip("0")}'

            if tile.player >= 0:
                scoreVal = score.get_weighted_enemy_capture_value()
                viewInfo.bottomLeftGridText[tile.x][tile.y] = f'e{f"{scoreVal:.2f}".strip("0")}'
                enemyTileScores.append((scoreVal, tile))
            else:
                scoreVal = score.get_weighted_neutral_value()
                viewInfo.bottomLeftGridText[tile.x][tile.y] = f'n{f"{scoreVal:.2f}".strip("0")}'
                tileScores.append((scoreVal, tile))

        tileScores = cityAnalysis.get_sorted_neutral_scores()
        enemyTileScores = cityAnalysis.get_sorted_enemy_scores()

        for i, ts in enumerate(tileScores):
            tile, cityScore = ts
            viewInfo.midLeftGridText[tile.x][tile.y] = f'c{i}'

        for i, ts in enumerate(enemyTileScores):
            tile, cityScore = ts
            viewInfo.midLeftGridText[tile.x][tile.y] = f'm{i}'

        self.render_view_info(map, viewInfo, 'whatever')
