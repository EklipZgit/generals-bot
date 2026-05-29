import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
import SearchUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.tile import TILE_MOUNTAIN, TILE_EMPTY
from base.client.map import MapBase


class BoardAnalyzerUnitTests(TestBase):
    def test_should_evaluate_wall_breach_accurately__shortens__shortest_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
               aG1

          M    M    M

               bG1D
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, respect_player_vision=True)

        rawMap, _ = self.load_map_and_general_from_string(testData, respect_undiscovered=True, turn=1)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        boardAnalyzer = BoardAnalyzer(playerMap, general)
        boardAnalyzer.rebuild_intergeneral_analysis(enemyGeneral)

        # from 8 down to 4
        self.assertEqual(4, boardAnalyzer.enemy_wall_breach_scores[playerMap.GetTile(3, 2)])

    def test_should_evaluate_wall_breach_accurately__lightly_shortens__shortest_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
               aG1

               M

               bG1D
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, respect_player_vision=True)

        rawMap, _ = self.load_map_and_general_from_string(testData, respect_undiscovered=True, turn=1)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        boardAnalyzer = BoardAnalyzer(playerMap, general)
        boardAnalyzer.rebuild_intergeneral_analysis(enemyGeneral)
        # self.render_map(playerMap)

        # from 6 down to 4
        self.assertEqual(2, boardAnalyzer.enemy_wall_breach_scores[playerMap.GetTile(3, 2)])

    def test_should_evaluate_wall_breach_accurately__shortens__side_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
          M    bG1
          M
          M

               aG1D
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, respect_player_vision=True)

        rawMap, _ = self.load_map_and_general_from_string(testData, respect_undiscovered=True, turn=1)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        boardAnalyzer = BoardAnalyzer(playerMap, general)
        boardAnalyzer.rebuild_intergeneral_analysis(enemyGeneral)

        # skips 6 moves
        self.assertEqual(6, boardAnalyzer.enemy_wall_breach_scores[playerMap.GetTile(2, 0)])
        self.assertEqual(0, boardAnalyzer.friendly_wall_breach_scores[playerMap.GetTile(2, 0)])

    def test_should_evaluate_wall_breach_accurately__lightly_shortens__side_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |
          M    bG1



               aG1D
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, respect_player_vision=True)

        rawMap, _ = self.load_map_and_general_from_string(testData, respect_undiscovered=True, turn=1)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        boardAnalyzer = BoardAnalyzer(playerMap, general)
        boardAnalyzer.rebuild_intergeneral_analysis(enemyGeneral)
        # self.render_map(playerMap)

        # from X down to X - 2
        self.assertEqual(2, boardAnalyzer.enemy_wall_breach_scores[playerMap.GetTile(2, 0)])
        self.assertEqual(0, boardAnalyzer.friendly_wall_breach_scores[playerMap.GetTile(2, 0)])

    def test_should_track_largest_and_furthest_large_ungathered_player_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |
aG1                                                    bG1






|    |    |    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, respect_player_vision=True)

        rawMap, _ = self.load_map_and_general_from_string(testData, respect_undiscovered=True, turn=1)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        boardAnalyzer = BoardAnalyzer(playerMap, general)

        player = playerMap.players[playerMap.player_index]
        cityOne = playerMap.GetTile(1, 0)
        cityTwo = playerMap.GetTile(2, 0)
        cityThree = playerMap.GetTile(3, 0)
        for city in [cityOne, cityTwo, cityThree]:
            city.isCity = True
            city.player = general.player
        player.cities = [cityOne, cityTwo, cityThree]

        configuredTiles = [
            ((0, 0), 108),
            ((1, 0), 43),
            ((2, 0), 25),
            ((3, 0), 21),
            ((4, 0), 20),
            ((0, 1), 7),
            ((1, 1), 7),
            ((2, 1), 7),
            ((3, 1), 7),
            ((11, 6), 7),
            ((10, 6), 6),
            ((9, 6), 5),
            ((8, 6), 4),
            ((7, 6), 3),
        ]

        ownedTiles = []
        for (x, y), army in configuredTiles:
            tile = playerMap.GetTile(x, y)
            tile.player = general.player
            tile.army = army
            ownedTiles.append(tile)
        player.tiles = ownedTiles

        boardAnalyzer.rebuild_intergeneral_analysis(enemyGeneral)

        self.assertEqual([108, 43, 25, 21, 20], [tile.army for tile in boardAnalyzer.largest_player_tiles])
        self.assertTrue(all(tile.army <= 7 for tile in boardAnalyzer.furthest_large_ungathered_player_tiles))
        self.assertEqual(9, len(boardAnalyzer.furthest_large_ungathered_player_tiles))

        expectedCandidateTiles = sorted(
            ownedTiles[5:],
            key=lambda tile: tile.army,
            reverse=True,
        )[:10]
        expectedDistances = SearchUtils.build_distance_map_matrix(
            playerMap,
            [tile for tile in playerMap.pathable_tiles if boardAnalyzer.extended_play_area_matrix.raw[tile.tile_index]],
        )
        expectedOrder = sorted(
            expectedCandidateTiles,
            key=lambda tile: (expectedDistances.raw[tile.tile_index], tile.army, tile.tile_index),
            reverse=True,
        )
        self.assertEqual(expectedOrder, boardAnalyzer.furthest_large_ungathered_player_tiles)
        self.assertEqual(playerMap.GetTile(11, 6), boardAnalyzer.furthest_large_ungathered_player_tiles[0])
