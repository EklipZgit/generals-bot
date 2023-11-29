import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Strategy.WinConditionAnalyzer import WinCondition
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class WinConditionAnalyzerTests(TestBase):    
    def test_should_see_city_as_forward_from_central_point(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=307)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertIn(playerMap.GetTile(6, 14), bot.win_condition_analyzer.defend_cities)
    
    def test_should_consider_econ_win_condition(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_consider_econ_win_condition___futhAqN24---1--101.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 101, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=101)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertIn(WinCondition.WinOnEconomy, bot.win_condition_analyzer.viable_win_conditions)
    
    def test_should_consider_this_defending_a_friendly_contested_city_i_think(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_consider_this_defending_a_friendly_contested_city_i_think___rETyBtOqf---0--281.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 281, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=281)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertIn(WinCondition.ContestEnemyCity, bot.win_condition_analyzer.viable_win_conditions)
        self.assertIn(WinCondition.WinOnEconomy, bot.win_condition_analyzer.viable_win_conditions)
        self.assertIn(WinCondition.DefendContestedFriendlyCity, bot.win_condition_analyzer.viable_win_conditions)
