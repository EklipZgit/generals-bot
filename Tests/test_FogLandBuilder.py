import time
from Algorithms import MapSpanningUtils
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from bot_ek0x45 import EklipZBot


class FogLandBuilderTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_tile_deltas = True
        bot.info_render_army_emergence_values = True
        # bot.info_render_
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_should_drop_bad_fog_predictions_after_discovering_army_came_from_different_direction(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_drop_bad_fog_predictions_after_discovering_army_came_from_different_direction___lUHbWMb9w---2--211.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 211, fill_out_tiles=True)

        goodTiles = [
            map.GetTile(10, 15),
            map.GetTile(11, 15),
            map.GetTile(12, 15),
            map.GetTile(13, 15),
            map.GetTile(14, 15),
            map.GetTile(13, 16),
            map.GetTile(13, 17),
        ]
        badTiles = [
            map.GetTile(8, 15),
            map.GetTile(8, 16),
            map.GetTile(7, 16),
            map.GetTile(6, 16),
            map.GetTile(5, 16),
            map.GetTile(4, 16),
            map.GetTile(3, 16),
            map.GetTile(3, 15),
            map.GetTile(3, 14),
            map.GetTile(3, 13),
            map.GetTile(4, 13),
            map.GetTile(6, 13),
            map.GetTile(6, 12),
        ]
        for tile in goodTiles:
            tile.player = enemyGeneral.player
            tile.army = 2
        for tile in badTiles:
            tile.army = 0
            tile.player = -1

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=211)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(general.player, '9,13->9,14->9,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        for tile in goodTiles:
            playerTile = playerMap.GetTile(tile.x, tile.y)
            self.assertEqual(-1, playerTile.player)

        for tile in badTiles:
            playerTile = playerMap.GetTile(tile.x, tile.y)
            self.assertEqual(enemyGeneral.player, playerTile.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general, allyGen)

        for tile in badTiles:
            playerTile = playerMap.GetTile(tile.x, tile.y)
            self.assertEqual(-1, playerTile.player)

    def test_should_build_land_between_known_emergences(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49_actual_spawn.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 49, fill_out_tiles=True)

        ogFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49.txtmap'
        rawMap, _ = self.load_map_and_general(ogFile, respect_undiscovered=True, turn=49)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->9,3  5,11->6,11->7,11->8,11->9,11->10,11->11,11->12,11->13,11  5,11->5,10->5,9->4,9->4,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 34
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)

        self.assertGreater(len(playerMap.players[enemyGeneral.player].tiles), 16)
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(10, 8))
        self.assertTileIn(playerMap.GetTile(11, 11), bot.armyTracker.player_connected_tiles[enemyGeneral.player])
        self.assertTileXYIn(playerMap, 10, 7, bot.armyTracker.player_connected_tiles[enemyGeneral.player])
        self.assertTileXYIn(playerMap, 8, 6, bot.armyTracker.player_connected_tiles[enemyGeneral.player])
        self.assertTileXYIn(playerMap, 10, 11, bot.armyTracker.player_connected_tiles[enemyGeneral.player])

    def test_should_build_land_between_known_emergences__single_emergence(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49_actual_spawn.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 49, fill_out_tiles=True)

        ogFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49.txtmap'
        rawMap, _ = self.load_map_and_general(ogFile, respect_undiscovered=True, turn=49)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->9,3  5,11->6,11->7,11->8,11->9,11->10,11->11,11->12,11->13,11  5,11->5,10->5,9->4,9->4,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 34
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=3)
        self.assertIsNone(winner)

        self.assertGreater(len(playerMap.players[enemyGeneral.player].tiles), 10)

    def test_should_set_emergence_around_uncovered_initial_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_set_emergence_around_uncovered_initial_tiles___gUX8yTL0J---1--194.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 194, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=194)
        rawMap.GetTile(17, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(18, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(19, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(19, 16).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(20, 16).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(20, 15).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertTrue(bot.euclidDist(20, 14, bot.targetPlayerExpectedGeneralLocation.x, bot.targetPlayerExpectedGeneralLocation.y) < 5)

    def test_should_not_overcreate_fog_land_when_army_moves_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_track_army_into_the_fog___J2DCEX-R3---1--570.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 570, fill_out_tiles=True)
        map.GetTile(9, 11).army = 3

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=570)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,9->7,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest('need to add new assertions for the fog land builder specifically')
    
    def test_fog_land_builder_should_not_take_ages_to_build__when_just_one_big_massive_emergence_set_from_ffa_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 880, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=880)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        start = time.perf_counter()
        MapSpanningUtils.LOG_VERBOSE = True
        bot.armyTracker.build_fog_prediction(enemyGeneral.player, bot.opponent_tracker.get_player_fog_tile_count_dict(enemyGeneral.player), bot.targetPlayerExpectedGeneralLocation, force=True)
        duration = time.perf_counter() - start
        self.assertLess(duration, 0.003, 'should not take ages to build fog land')
    
    def test_shouldnt_over_build_fog_land_on_vision_loss__when_enemy_out_of_cave_tiles_but_has_wallbreak_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_over_build_fog_land_on_vision_loss_and_fog_adjacent_captures___oNee0ECyL---0--206.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 206, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=206)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,16->15,16->15,17->7,17')
        simHost.queue_player_moves_str(general.player, 'None  None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general)
        self.assertOwned(-1, playerMap.GetTile(18, 17), 'this OBVIOUSLY was not captured, at no point could it have been')
        self.assertOwned(-1, playerMap.GetTile(17, 16), 'this OBVIOUSLY was not captured, at no point could it have been')
        self.assertOwned(-1, playerMap.GetTile(16, 17), 'this OBVIOUSLY was not captured, at no point could it have been')
        self.assertOwned(-1, playerMap.GetTile(15, 18), 'this OBVIOUSLY was not captured, at no point could it have been')

    def test_shouldnt_over_build_fog_land_on_vision_loss_and_fog_adjacent_captures(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_over_build_fog_land_on_vision_loss_and_fog_adjacent_captures___oNee0ECyL---0--206.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 206, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=206)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,16->15,16->15,17->7,17')
        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertNoFriendliesKilled(map, general)
        self.assertOwned(-1, playerMap.GetTile(9, 17), 'this cannot have been captured yet. Fog land builder should expand armies in the fog before rebuilding and redistributing.')
    
    def test_shouldnt_pick_wonky_far_city_just_because_wall_breach(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_pick_wonky_far_city_just_because_wall_breach___C2LBGDHPN---0--179.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 179, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=179)
        rawMap.GetTile(19, 11).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwned(-1, playerMap.GetTile(19, 11))