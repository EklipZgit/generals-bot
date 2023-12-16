import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class ArmyInterceptionTests(TestBase):
    def test_should_intercept_army_that_is_one_tile_kill_and_city_threat_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(10):
            with self.subTest(i=i):
                mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=307)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)
                playerMap.GetTile(7, 14).lastMovedTurn = map.turn

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
                self.assertIsNone(winner)

                self.assertEqual(general.player, playerMap.GetTile(7, 14).player)
    
    def test_should_continue_to_intercept_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_intercept_army___HO8rgeNt7---0--140.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 140, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=140)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,8->7,8->7,12->8,12->8,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)
        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, 0)

    def test_should_just_cap_tiles_when_inbound_army_isnt_kill_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        """
        at the start of that round I'm up 4 lands, at the end of the round I'm up 24 and it's because of these wasted moves
        
        proper response is probably take 50-100 troops and try to spend every move capturing my land
        
        so going bottom left is probably best
        
        or even take this 17 and 28 and take all the 2s here (turn 336)
        """
        mapFile = 'GameContinuationEntries/should_just_cap_tiles_when_inbound_army_isnt_kill_threat___50vyo-z9H---1--671.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 671, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=671)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,7->7,7->7,9->9,9->9,12->16,12->16,11->12,11->12,10->14,10  5,17->6,17  1,15->2,15  7,6->6,6  11,7->10,7  9,6->9,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        tileDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=29)
        self.assertIsNone(winner)

        finalTileDiff = self.get_tile_differential(simHost)
        self.assertGreater(finalTileDiff - tileDiff, -8)
    
    def test_should_prevent_run_around_general__stop_multi_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for enPath, genPathFollowUp in [
            ('8,8->7,8->7,10->6,10->6,12->3,12->3,13->4,13->4,16', None),
            ('8,8->5,8->5,9->3,9->3,10->1,10->1,7->2,7->2,5', '5,7->5,9'),
            ('8,8->6,8->6,4->2,4->2,7', '5,7->6,7->6,6'),
            ('8,8->5,8->5,12->3,12->3,13->4,13->4,16', '5,7->5,9'),
        ]:
            with self.subTest(enPath=enPath):
                mapFile = 'GameContinuationEntries/should_prevent_run_around_general___qiPZUGWpC---1--135.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 135, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=135)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                # TODO what the bot SHOULD do, uncomment to see
                # if genPathFollowUp:
                #     simHost.queue_player_moves_str(general.player, '3,7->5,7  5,9->5,8')
                #     simHost.queue_player_moves_str(general.player, genPathFollowUp)

                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
                self.assertIsNone(winner)

                tileDiff = self.get_tile_differential(simHost)
                self.assertGreater(tileDiff, -1, 'should not have allowed opp free reign :(')
    
    def test_should_split_and_cap_1s(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_and_cap_1s___qiPZUGWpC---1--141.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 141, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=141)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,9->3,10->1,10->1,7->2,7->2,5')
        # simHost.queue_player_moves_str(general.player, '4,7->5,7z->5,8->8,8  4,7->3,7->2,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, -3, 'should split and cap up the line of 1s while defending at home with the split, uncomment general moves above for proof')
    
    def test_should_intercept_with_large_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_large_tile___qWwqozFbe---1--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=138)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,9->9,9z->7,9  10,9->10,11  12,9->14,9->14,12  7,9->7,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertIsNone(winner)

        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, 1)

    def test_should_split_when_chasing_threat_around_obstacle(self):
        for i in range(4):
            with self.subTest(i=i):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_split_when_chasing_threat_around_obstacle___67Nv7tPW1---0--205.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 205, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=205)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
                self.assertIsNone(winner)

                self.assertNoRepetition(simHost)

                enTile = playerMap.GetTile(8, 18)

                if enTile.player != general.player:
                    self.assertLess(enTile.army, 5)

    def test_should_intercept_at_inbound_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_allow_opp_to_walk_all_over_territory___Hn8ec1Na9---0--283.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=283)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,11->1,11->1,8->2,8->2,7->4,7->4,6->5,6->5,3->6,3->6,2->5,2')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.info_render_board_analysis_choke_widths = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        chokeTile = playerMap.GetTile(2, 7)
        self.assertEqual(general.player, chokeTile.player)
        self.assertGreater(chokeTile.army, 19, "should have met the army at the choke")

    def test_should_not_allow_opp_to_walk_all_over_territory(self):
        for enPath in [
            '4,11->1,11->1,8->2,8->2,7->4,7->4,6->5,6->5,3->6,3->6,2->5,2',
            '4,11->1,11->1,8->6,8->6,7->5,7z->4,7->4,6->5,6->5,3->6,3->6,2->5,2',
        ]:
            with self.subTest(enPath=enPath):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_not_allow_opp_to_walk_all_over_territory___Hn8ec1Na9---0--283.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=283)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                bot = self.get_debug_render_bot(simHost, general.player)
                bot.info_render_board_analysis_choke_widths = True
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
                self.assertIsNone(winner)

                self.assertGreater(self.get_tile_differential(simHost), 0, "should have intercepted and then caught up on tiles")
    
    def test_should_only_intercept_threats_that_are_moving_the_correct_direction(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_only_intercept_threats_that_are_moving_the_correct_direction___ej-YIq-8I---1--223.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=223)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)

    def test_should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns(self):
        for enPath in [
            '8,5->8,4->9,4->9,3->14,3->14,2',
            '8,5->8,6->14,6',
            '8,5->8,6->9,6->9,3->11,3->11,4'
        ]:
            with self.subTest(enPath=enPath):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 16)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=181)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '4,8->4,6->6,6->6,5->8,5')
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=19)
                self.assertIsNone(winner)

                self.assertGreater(self.get_tile_differential(simHost), 10)

# 22-12 with everything bad
# 11f 19p - hacked defense intercept
# 10-20 with defense -1 instead of -2
