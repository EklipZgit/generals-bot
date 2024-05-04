import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Strategy.WinConditionAnalyzer import WinCondition
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.tile import Tile_MOUNTAIN, TILE_EMPTY, MapBase


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
    
    def test_should_not_be_all_inning_without_econ_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_be_all_inning_without_econ_capture___6uPEgrHKz---0--192.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 192, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=192)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_not_be_all_inning_cities_when_not_necessary(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_be_all_inning_cities_when_not_necessary___2JFC3tJRJ---1--217.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 217, fill_out_tiles=True)
        # enemyGeneral = self.move_enemy_general(map, enemyGeneral, 2, 14)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=217)
        self.reset_general(rawMap, enemyGeneral)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)
    
    def test_should_not_blow_up_on_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_blow_up_on_gather___2JFC3tJRJ---1--286.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 286, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=286)
        # rawMap.pathableTiles.discard(rawMap.GetTile(0, 15))

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_not_switch_into_defending_economy_when_not_really_necessary_yet(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_switch_into_defending_economy_and_should_take_city_with_army_on_gen___lJYWPyU3u---0--127.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 127, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=127)
        self.reset_general(rawMap, enemyGeneral)
        rawMap.GetTile(9, 14).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(10, 14).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  9,14->10,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertEqual(False, bot.defend_economy)

    def test_should_not_tick_all_in_counter_when_opp_just_took_city_and_can_retake(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_switch_into_defending_economy_and_should_take_city_with_army_on_gen___lJYWPyU3u---0--127.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 127, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=127)
        self.reset_general(rawMap, enemyGeneral)
        rawMap.GetTile(9, 14).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(10, 14).reset_wrong_undiscovered_fog_guess()

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  9,14->10,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        self.assertEqual(0, bot.all_in_losing_counter)

    def test_should_not_switch_into_defending_economy_and_should_take_city_with_army_on_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_switch_into_defending_economy_and_should_take_city_with_army_on_gen___lJYWPyU3u---0--127.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 127, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=127)
        self.reset_general(rawMap, enemyGeneral)
        rawMap.GetTile(9, 14).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(10, 14).reset_wrong_undiscovered_fog_guess()

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  9,14->10,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=23)
        self.assertIsNone(winner)

        self.assertEqual(2, len(bot.player.cities), "this is a position where it economically makes sense to try to take the neut city at end of round, because its expansion plan is so poop with so much army on general")
    
    def test_should_not_defend_contested_city_when_city_not_contested_and_also_not_winning_lmao(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_defend_contested_city_when_city_not_contested_and_also_not_winning_lmao___S9_cf7cME---1--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=207)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertNotIn(WinCondition.DefendContestedFriendlyCity, bot.win_condition_analyzer.viable_win_conditions)

    def test_should_not_randomly_start_saying_contest_enemy_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_randomly_start_saying_contest_enemy_cities___9Qt4IOU3s---1--242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=242)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        # if it was this before, it should be this after
        self.assertNotIn(WinCondition.ContestEnemyCity, bot.win_condition_analyzer.viable_win_conditions)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        self.assertIn(WinCondition.WinOnEconomy, bot.win_condition_analyzer.viable_win_conditions)
        # self.assertNotIn(WinCondition.ContestEnemyCity, bot.win_condition_analyzer.viable_win_conditions)

        self.assertEqual(90, playerMap.players[general.player].tileCount)

# 3f, 8p, 0s
