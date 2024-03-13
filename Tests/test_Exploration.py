import typing

import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class ExplorationTests(TestBase):
    
    def test_shouldnt_make_nonsense_exploration_path_15_6__15_5__15_4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/shouldnt_make_nonsense_exploration_path_15_6__15_5__15_4___HlRRkn923---b--543.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 543)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=543)
        simHost.apply_map_vision(general.player, rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        # simHost.bot_hosts[general.player].eklipz_bot.allIn = True
        # simHost.bot_hosts[general.player].eklipz_bot.all_in_counter = 500

        simHost.bot_hosts[general.player].eklipz_bot.finishing_exploration = True

        if debugMode:
            simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=30)

            self.assertNoRepetition(simHost, 3)

        negTiles = set()
        for city in map.players[general.player].cities:
            negTiles.add(city)
        negTiles.add(general)

        self.begin_capturing_logging()
        badPathStartTile = self.get_player_tile(15, 6, simHost.sim, general.player)
        path = simHost.bot_hosts[general.player].eklipz_bot.explore_target_player_undiscovered(negTiles)

        if path is not None:
            self.assertNotEquals(badPathStartTile, path.start.tile)

    def test_should_not_loop_back_and_forth_exploring_stupid_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_loop_back_and_forth_exploring_stupid_fog___Hx2Nw8WTh---e--490.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 490, player_index=4)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=490, player_index=4)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=30)
        self.assertNoRepetition(simHost, minForRepetition=1)
        self.assertEqual(4, winner)
    
    def test_should_not_explore_when_nothing_to_search_for(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_explore_when_nothing_to_search_for___58Kyitswi---1--245.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 245, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=245)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertEqual(general.player, winner, "should have just killed opp")

    def test_should_not_explore_instead_of_expand_end_of_cycle(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_explore_instead_of_expand_end_of_cycle___S-oHcT3cW---0--146.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 146, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=146)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=4)
        self.assertIsNone(winner)

        self.assertPlayerTileCount(simHost, general.player, 45, "should have capped tiles not explored")

        self.assertPlayerTileCount(simHost, enemyGeneral.player, 46, "should have capped tiles not explored")
    
    def test_should_all_in_at_predicted_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_at_predicted_location___NXe16_WTd---1--368.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 368, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=368)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertEqual(general.player, winner)

    def test_should_king_race_when_definitely_dead_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_king_race_when_definitely_dead_lol___NE41D7V1----0--256.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 256, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=256)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_king_race_when_definitely_dead_lol")
    
    def test_should_not_time_out_on_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_time_out_on_move___U7l4Nbv2D---1--406.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 406, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=406)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        simHost.respect_turn_time_limit = True
        simHost.player_move_cutoff_time = 0.3

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertEqual(0, simHost.dropped_move_counts_by_player[general.player])
    
    def test_should_split_to_explore_full_fog_when_knows_opp_cant_defend_either_half_of_split(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_to_explore_full_fog_when_knows_opp_cant_defend_either_half_of_split___taVsbP1C2---0--614.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 614, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=614)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_split_to_explore_full_fog_when_knows_opp_cant_defend_either_half_of_split")
    
    def test_should_all_in_general_hunt_efficiently_when_going_to_die(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_general_hunt_efficiently_when_going_to_die___d4rqG3XjS---1--297.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 297, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=297)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        # TODO need to just run explore, take into account probable army on general based on opptracker gathers, and maximally explore the remaining general space in the time before death. Shouldn't be hard.

        self.skipTest("TODO add asserts for should_all_in_general_hunt_efficiently_when_going_to_die")
    
    def test_should_not_interupt_king_safety_gather_with_crappy_explore_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_interupt_king_safety_gather_with_crappy_explore_moves___o-nxZ1Aue---0--211.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 211, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=211)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=21)
        self.assertIsNone(winner)

        self.assertGreater(general.army, 55)
    
    def test_should_recognize_has_100_percent_kill_explore_chance(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for isGeneralFar in [True, False]:
            with self.subTest(isGeneralFar=isGeneralFar):
                mapFile = 'GameContinuationEntries/should_recognize_has_100_percent_kill_explore_chance___DX6yGfVZV---1--243.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

                if isGeneralFar:
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 12)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=18)
                self.assertEqual(general.player, winner)


