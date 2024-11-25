import logbook

import SearchUtils
from Directives import Timings
from Path import Path
from SearchUtils import Counter
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class FFATests(TestBase):
    def test_should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos___j4GQjpuy4---0--379.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 379, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 20)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=379)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,6->9,4->14,4->14,5->15,5->15,6->17,6->17,5->20,5->20,4->22,4->22,7->21,7->21,8->10,8')
        bot = self.get_debug_render_bot(simHost, general.player)

        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=100)
        self.assertIsNone(winner)
    
    def test_should_find_kill_in_ffa_position(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_kill_in_ffa_position___eW64nZ8rZ---2--69.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 69, fill_out_tiles=True)
        enemyGeneral.army = 10

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=69)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertEqual(general.player, enemyGeneral.player, 'should have captured fincher')

    # 0f 2p    
    def test_should_not_time_out_on_win_condition_in_ffa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_time_out_on_win_condition_in_ffa___uu_dzfs6v---1--1275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1275, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1275)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '17,21->18,21->18,17->20,17->20,6->18,6->18,4->20,4->20,0->21,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertIsNone(winner)

    def test_should_gather_for_large_attacks_out_of_vision_range_in_rounds(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_for_large_attacks_out_of_vision_range_in_rounds___EklipZ_ai-SUlNa6E3r---7--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        bot.timings = None
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        # 12 moves minimum to gather out of vision
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(1, playerMap.GetTile(23, 15).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22,15).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22,16).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22, 17).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22, 18).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 17).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 18).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 20).army, 'should have gathered everything')
        self.assertEqual(15, playerMap.players[general.player].tileCount, "should not have captured land")

