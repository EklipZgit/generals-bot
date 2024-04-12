import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


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
