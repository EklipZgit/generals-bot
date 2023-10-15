from BoardAnalyzer import BoardAnalyzer
from CityAnalyzer import CityAnalyzer
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase
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
        viewInfo = self.get_renderable_view_info(map)
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
    
    def test_should_take_city_as_quick_as_possible(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_city_as_quick_as_possible___HltY61xph---b--100.txtmap'
        map, general, enemyGen = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGen.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=20)
    
    def test_should_not_take_city_in_middle_of_map_right_in_front_of_enemy_army_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_in_middle_of_map_right_in_front_of_enemy_army_lol___Se6KaySp2---a--186.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 186)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=186)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=10)
        self.assertIsNone(winner)
        city = self.get_player_tile(11, 12, simHost.sim, general.player)
        self.assertTrue(city.isNeutral)

    def test_should_never_take_city_so_far_from_play_area__should_contest_red_city_instead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_never_take_city_so_far_from_play_area__should_contest_red_city_instead___BlFGDfup2---b--510.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 510, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=510)
        
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=45)
        self.assertIsNone(winner)
        badCity = self.get_player_tile(13,5, simHost.sim, general.player)
        self.assertEqual(-1, badCity.player)

        enemyCityToContest = self.get_player_tile(12, 11, simHost.sim, general.player)
        self.assertGreater(enemyCityToContest.turn_captured, 520, 'should have tried to contest the city, if not own it outright')
    
    def test_should_choose_the_city_between_players(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_choose_the_city_between_players___0Z_4Pw4rv---1--151.txtmap'
        map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 151, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=151)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        bot = simHost.get_bot(general.player)
        scores = bot.cityAnalyzer.get_sorted_neutral_scores()
        topCity, topScore = scores[0]

        if debugMode:
            simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=30)

        self.assertEqual(topCity, simHost.get_player_map(general.player).GetTile(21, 9))

