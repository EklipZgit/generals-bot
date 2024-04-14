import time
import typing

from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from bot_ek0x45 import EklipZBot


class GeneralPredictionTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_tile_deltas = True
        bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def template(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_gather_army_exit_from_fog___BeXQydQAn---b--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        outTile = playerMap.GetTile(14, 15)
        inTile = playerMap.GetTile(15, 16)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][inTile])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][outTile])

    def test_should_limit_ffa_general_location_based_on_player_only_having_15_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_limit_ffa_general_location_based_on_15_tiles___Qlpc07mHW---5--39.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 39, fill_out_tiles=True)
        enemyGeneral = map.generals[3]
        enTile = map.GetTile(10, 25)
        enTile.player = enemyGeneral.player
        enTile.army = 1

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=39)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '9,23->9,24')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        outTile = playerMap.GetTile(14, 15)
        inTile = playerMap.GetTile(15, 16)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][inTile])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][outTile])
    
    def test_should_not_allow_pathing_through_enemy_generals_when_limiting_general_positions(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_allow_pathing_through_enemy_generals_when_limiting_general_positions___UGJKyIutV---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)
        gen1 = self.move_enemy_general(map, map.generals[0], 9, 1)
        gen2 = self.move_enemy_general(map, map.generals[3], 0, 5)
        redTile = map.GetTile(0, 4)

        redTile.player = 0
        redTile.army = 11

        for tile in [
            map.GetTile(1, 1),
            map.GetTile(2, 1),
            map.GetTile(3, 1),
        ]:
            tile.player = 0
            tile.army = 1

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '2,5->1,5')
        simHost.reveal_player_general(2, general.player, hidden=True)
        simHost.reveal_player_general(0, general.player, hidden=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[gen1.player][playerMap.GetTile(gen1.x, gen1.y)])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[gen1.player][playerMap.GetTile(0, 9)])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[gen1.player][playerMap.GetTile(4, 1)])
    
    def test_should_correctly_predict_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_correctly_predict_general_location___1KRpoWTgQ---1--2.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 2, fill_out_tiles=True)
        oldGen = enemyGeneral
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 5)
        oldGen.army = 0
        oldGen.player = -1
        enemyGeneral.army = 2

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=2)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  6,5->5,5->5,6->5,7->5,8->6,8z->7,8->8,8->8,9')
        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  3,17->3,16->3,15->4,15->4,14->4,13->4,12->4,11->4,10->5,10->5,9->6,9->7,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=50)
        self.assertIsNone(winner)

        shouldBe = [
            playerMap.GetTile(6, 5),
            playerMap.GetTile(7, 6),
            playerMap.GetTile(10, 9),
        ]

        shouldNotBe = [
            playerMap.GetTile(4, 3),
            playerMap.GetTile(4, 5),
            playerMap.GetTile(5, 5),
            playerMap.GetTile(2, 5),
            playerMap.GetTile(10, 8),
        ]

        for tile in shouldBe:
            self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should be allowed')
        for tile in shouldNotBe:
            self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should not be allowed')

    def test_should_properly_predict_enemy_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_properly_predict_enemy_general_location___19aFPxtMy---1--62.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 62, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=62)
        rawMap.GetTile(15, 12).reset_wrong_undiscovered_fog_guess()

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # simHost.sim.set_tile_vision(general.player, 15, 12, hidden=True, undiscovered=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,12->15,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 24
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        shouldBe = [
            playerMap.GetTile(14, 18),
            playerMap.GetTile(19, 21),
            playerMap.GetTile(6, 14),
        ]

        shouldNotBe = [
            playerMap.GetTile(3, 6),
            playerMap.GetTile(6, 7),
            playerMap.GetTile(0, 21),
        ]

        for tile in shouldBe:
            self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should be allowed')
        for tile in shouldNotBe:
            self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should not be allowed')

    def test_should_not_under_constrain_enemy_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_under_constrain_enemy_general_location___Kj2jWIDxL---1--75.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 75, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=75)
        rawMap.GetTile(6, 8).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,8->5,8')
        simHost.queue_player_moves_str(general.player, '3,8->4,8->5,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 26
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        shouldBe = [
            playerMap.GetTile(15, 12),
        ]

        shouldNotBe = [
            playerMap.GetTile(20, 19),
        ]

        for tile in shouldBe:
            self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should be allowed')
        for tile in shouldNotBe:
            self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should not be allowed')
    
    def test_should_immediately_re_evaluate_target_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49_actual_spawn.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 49, fill_out_tiles=True)

        ogFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49.txtmap'
        rawMap, _ = self.load_map_and_general(ogFile, respect_undiscovered=True, turn=49)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->9,3')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 34
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        shouldBe = [
            playerMap.GetTile(5, 11),
        ]

        shouldNotBe = [
            playerMap.GetTile(5, 12),
            playerMap.GetTile(0, 11),
        ]

        for tile in shouldBe:
            self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should be allowed')
        for tile in shouldNotBe:
            self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should not be allowed')

        targPath = bot.shortest_path_to_target_player
        endTile = targPath.tail.tile
        emergenceVal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][endTile]

        self.assertGreater(emergenceVal, 10, f'target player path ending in {str(endTile)} did not end at the high emergence new prediction.')

    def test_should_re_evaluate_spawn_as_attacks_opp(self):
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)

        shouldBe = [
            playerMap.GetTile(5, 11),
        ]

        shouldNotBe = [
            playerMap.GetTile(5, 12),
            playerMap.GetTile(0, 11),
            playerMap.GetTile(6, 0),
            playerMap.GetTile(0, 1),
        ]

        shouldNotBeCareLess = [
            playerMap.GetTile(3, 10),  # TECHNICALLY we can tell from the fact that the 9 had to move across friendly tiles that the general is on the right half of the prediction zone, but not that fancy yet.
        ]

        with self.subTest(careLess=False):

            for tile in shouldBe:
                self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should be allowed')
            for tile in shouldNotBe:
                self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should not be allowed')

            targPath = bot.shortest_path_to_target_player
            endTile = targPath.tail.tile
            emergenceVal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][endTile]

            self.assertGreater(emergenceVal, 10, f'target player path ending in {str(endTile)} did not end at the high emergence new prediction.')

        with self.subTest(careLess=True):
            for tile in shouldNotBeCareLess:
                self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile],
                                 f'{str(tile)} should not be allowed')

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

    def test_should_limit_general_to_launch_timing(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_limit_general_to_launch_timing___Hx1ru6UDJ---0--47.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 47, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=47)
        rawMap.GetTile(10, 0).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(6, 13).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(7, 13).reset_wrong_undiscovered_fog_guess()
        # rawMap.GetTile(10, 0).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '6,15->6,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 24
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        shouldBe = [
            playerMap.GetTile(11, 10),
            playerMap.GetTile(12, 6),
            playerMap.GetTile(1, 6),
            playerMap.GetTile(9, 7),  # actual spawn
            playerMap.GetTile(13, 7),
        ]

        shouldNotBe = [
            playerMap.GetTile(1, 5),
            playerMap.GetTile(15, 18),
            playerMap.GetTile(15, 16),
        ]

        for tile in shouldBe:
            self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should be allowed')
        for tile in shouldNotBe:
            self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][tile], f'{str(tile)} should not be allowed')
    
    def test_should_set_emergence_around_uncovered_initial_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_set_emergence_around_uncovered_initial_tiles___gUX8yTL0J---1--194.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 194, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=194)
        rawMap.GetTile(17, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(18, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(19, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(19, 16).reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertTrue(bot.euclidDist(17, 7, bot.targetPlayerExpectedGeneralLocation.x, bot.targetPlayerExpectedGeneralLocation.y) < 5, 'should pick somewhere pretty central to the players tile-mass')

    def test_should_not_over_emerge_initial_trail(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_predict_general_too_deep_in_fog_when_not_initial_trail___tg5Cb-aZW---1--37.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 37, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=37)

        for tile in rawMap.players[enemyGeneral.player].tiles:
            tile.reset_wrong_undiscovered_fog_guess()
            tile.isGeneral = False
        rawMap.generals[enemyGeneral.player] = None

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '11,9->10,9->9,9->8,9->8,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 24
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        farTile = playerMap.GetTile(1, 4)
        realEnGenSpawn = playerMap.GetTile(1, 7)
        closerTile = playerMap.GetTile(0, 8)
        impossibleTile = playerMap.GetTile(3, 0)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][farTile])
        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][realEnGenSpawn])
        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][closerTile])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][impossibleTile])

        emergenceValFar = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][farTile]
        emergenceValReal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][realEnGenSpawn]
        emergenceValClose = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][closerTile]

        self.assertLess(emergenceValReal, 70)
        self.assertLess(emergenceValFar, 70)
        self.assertLess(emergenceValClose, 70)

    def test_should_limit_top_path__when_exploring_branch_in_other_direction(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_predict_general_too_deep_in_fog_when_not_initial_trail___tg5Cb-aZW---1--37.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 37, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=37)

        for tile in rawMap.players[enemyGeneral.player].tiles:
            tile.reset_wrong_undiscovered_fog_guess()
            tile.isGeneral = False
        rawMap.generals[enemyGeneral.player] = None

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '11,9->10,9->9,9->7,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 24
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        farTile = playerMap.GetTile(1, 4)
        realEnGenSpawn = playerMap.GetTile(1, 7)
        closerTile = playerMap.GetTile(0, 8)

        # this is now impossible because we see 4 tiles along the bottom
        impossibleTile = playerMap.GetTile(4, 0)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][farTile])
        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][realEnGenSpawn])
        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][closerTile])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][impossibleTile])

        emergenceValFar = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][farTile]
        emergenceValReal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][realEnGenSpawn]
        emergenceValClose = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][closerTile]

        self.assertLess(emergenceValReal, 70)
        self.assertLess(emergenceValFar, 70)
        self.assertLess(emergenceValClose, 70)

    def test_should_limit_top_path__when_exploring_branch_in_other_direction__find_more_on_trail_limit(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_predict_general_too_deep_in_fog_when_not_initial_trail__alt___tg5Cb-aZW---1--37.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 37, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=37)

        for tile in rawMap.players[enemyGeneral.player].tiles:
            tile.reset_wrong_undiscovered_fog_guess()
            tile.isGeneral = False
        rawMap.generals[enemyGeneral.player] = None

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '11,9->10,9->9,9->7,9  15,8->14,8->14,9->10,9->10,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 24
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=14)
        self.assertIsNone(winner)

        farTile = playerMap.GetTile(1, 4)
        realEnGenSpawn = playerMap.GetTile(1, 7)
        closerTile = playerMap.GetTile(0, 8)

        # this is now impossible because we see 4 tiles along the bottom
        impossibleTile = playerMap.GetTile(8, 0)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][farTile])
        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][realEnGenSpawn])
        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][closerTile])
        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][impossibleTile])

        emergenceValFar = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][farTile]
        emergenceValReal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][realEnGenSpawn]
        emergenceValClose = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][closerTile]

        self.assertLess(emergenceValReal, 70)
        self.assertLess(emergenceValFar, 70)
        self.assertLess(emergenceValClose, 70)

    def test_should_choose_max_locality_from_valid_general_positions(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_choose_max_locality_from_valid_general_positions___t4J6NOKOM---0--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][enemyGeneral] = 0
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertLess(bot.euclidDist(7, 4, bot.targetPlayerExpectedGeneralLocation.x, bot.targetPlayerExpectedGeneralLocation.y), 4)

    def test_should_not_prune_top_map_just_because_fog_discovered_neutral_previously(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_prune_top_map_just_because_fog_discovered_neutral_previously___n86AEbErE---0--151.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 151, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=151)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,11->2,11->2,13->3,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(6, 1)], "should not mis-eliminate the general")

    def test_should_not_mis_predict_general_location_for_weird_start(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for finalPath in [
            '18,12->16,12->16,13->13,13->13,14->8,14->8,12',
            '18,12->16,12->16,13->13,13->13,14->11,14->11,13->8,13'
        ]:
            with self.subTest(finalPath=finalPath):
                mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start__actual___n5lR2mrz----1--44.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1, fill_out_tiles=True)

                mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start___n5lR2mrz----1--44.txtmap'
                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
                gMoves = ('None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                        + '0,13->1,13->1,11->8,11->8,12')

                enMoves = ('None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                        + '18,12->16,12->16,13->14,13->14,14->9,14  '
                        + finalPath)
                simHost.queue_player_moves_str(general.player, gMoves)
                simHost.queue_player_moves_str(enemyGeneral.player, enMoves)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=46)
                self.assertIsNone(winner)

                self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(18, 12)])
                self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(12, 3)])
                self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(20, 11)])

    def test_should_not_mis_predict_general_location_for_abusive_start(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for enStart in [
            'None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  ',
        ]:
            for finalPath, longDist in [
                 ('18,12->16,12->16,13->13,13->13,14->8,14->8,12', False),
                 ('18,12->16,12->16,13->13,13->13,14->11,14->11,13->8,13', True),
            ]:
                with self.subTest(finalPath=finalPath, enStart=enStart):
                    mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start__actual___n5lR2mrz----1--44.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1, fill_out_tiles=True)

                    mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start___n5lR2mrz----1--44.txtmap'
                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
                    gMoves = ('None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                            + '0,13->1,13->1,11->8,11->8,12')

                    enMoves = (enStart
                            + '18,12->16,12->16,13->14,13->14,14->9,14  '
                            + finalPath)
                    simHost.queue_player_moves_str(general.player, gMoves)
                    simHost.queue_player_moves_str(enemyGeneral.player, enMoves)
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=46)
                    self.assertIsNone(winner)

                    self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(18, 12)])
                    self.assertEqual(longDist, bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(20, 11)])
                    self.assertEqual(longDist, bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(12, 3)])
                    self.assertEqual(longDist, bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(13, 2)])
                    self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(13, 1)])

    def test_should_not_mis_predict_general_location_for_abusive_start__first_tendril(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for enStart in [
            'None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  ',
        ]:
            for finalPath in [
                '18,12->16,12->16,13->13,13->13,14->8,14->8,12',
                '18,12->16,12->16,13->13,13->13,14->11,14->11,13->8,13',
            ]:
                with self.subTest(finalPath=finalPath, enStart=enStart):
                    mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start__actual___n5lR2mrz----1--44.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1, fill_out_tiles=True)

                    mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start___n5lR2mrz----1--44.txtmap'
                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
                    gMoves = ('None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                            + '0,13->1,13->1,11->8,11->8,13->9,13->9,14')

                    enMoves = (enStart
                            + '18,12->16,12->16,13->14,13->14,14->9,14  '
                            + finalPath)
                    simHost.queue_player_moves_str(general.player, gMoves)
                    simHost.queue_player_moves_str(enemyGeneral.player, enMoves)
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=38)
                    self.assertIsNone(winner)

                    self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(18, 12)])
                    self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(12, 3)])
                    self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(20, 11)])

    def test_should_not_mis_predict_general_location_for_abusive_start__first_tendril__later_launch(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for enStart in [
            'None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  None  ',
            'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  18,12->16,12  None  None  ',
        ]:
            for finalPath in [
                '18,12->16,12->16,13->13,13->13,14->8,14->8,12',
                '18,12->16,12->16,13->13,13->13,14->11,14->11,13->8,13',
            ]:
                with self.subTest(finalPath=finalPath, enStart=enStart):
                    mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start__actual___n5lR2mrz----1--44.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1, fill_out_tiles=True)

                    mapFile = 'GameContinuationEntries/should_not_mis_predict_general_location_for_weird_start___n5lR2mrz----1--44.txtmap'
                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True, botInitOnly=True)
                    gMoves = ('None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                            + '0,13->1,13->1,11->8,11->8,13->9,13->9,14')

                    enMoves = (enStart
                            + '18,12->16,12->16,13->14,13->14,14->10,14  '
                            + finalPath)
                    simHost.queue_player_moves_str(general.player, gMoves)
                    simHost.queue_player_moves_str(enemyGeneral.player, enMoves)
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=38)
                    self.assertIsNone(winner)

                    self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(18, 12)])
                    self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(12, 3)])
                    self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(20, 11)])
    
    def test_should_convert_final_valid_tile_into_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_convert_final_valid_tile_into_general___ajPs0-Z_w---1--342.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 342, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 2, 12)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=342)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '6,13->6,14->5,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        expectedToBeGeneral = playerMap.GetTile(2, 12)
        self.assertTrue(expectedToBeGeneral.isGeneral)
        self.assertEqual(enemyGeneral.player, expectedToBeGeneral.player)
    
    def test_should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying__first_moves_instant(self):
        # TODO actually what the fuck, the bot totally CAN save here by intercepting one move behind at 9,10->10,9???
        # Bot needs to comprehend that moving down wins the race
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying___XWHQOYv7I---1--480.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  5,14->7,14->7,10->10,10->10,9->11,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertOwned(general.player, playerMap.GetTile(2, 14), 'should instantly dive the gen when dead')

    def test_should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying(self):
        # TODO actually what the fuck, the bot totally CAN save here by intercepting one move behind at 9,10->10,9???
        # Bot needs to comprehend that moving down wins the race
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for genDist in ['short', 'shortPocket', 'medium', 'worstCase']:
            with self.subTest(genDist=genDist):
                mapFile = 'GameContinuationEntries/should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying___XWHQOYv7I---1--480.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)
                if genDist == 'shortPocket':
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 0, 13)
                elif genDist == 'medium':
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 0, 19)
                elif genDist == 'worstCase':
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 3, 19)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None  5,14->7,14->7,10->10,10->10,9->11,9')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
                self.assertEqual(map.player_index, winner)
    
    def test_should_prioritize_things_inside_the_bounds_of_minimum_connected_mst_range(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_eliminate_anything_outside_the_bounds_of_minimum_connected_mst_range__actual__hFVc9L3b2---1--99.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 99, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_eliminate_anything_outside_the_bounds_of_minimum_connected_mst_range___hFVc9L3b2---1--99.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=99)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,11->12,12')
        simHost.queue_player_moves_str(general.player, 'None  13,13->13,12')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        # should keep the emergence we added in the back area.
        self.assertGreater(bot.armyTracker.emergenceLocationMap[enemyGeneral.player][playerMap.GetTile(16, 2)], 9)
        # should have dropped the emergence that was added to the spurious right side after we realized it is unlikely to be valid.
        self.assertLess(bot.armyTracker.emergenceLocationMap[enemyGeneral.player][playerMap.GetTile(17, 9)], 2)

    def test_should_not_mis_predict_general_from_odd_start(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_mis_predict_general_from_odd_start___yEYQfURCl---0--2.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 2, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=2)
        self.reset_general(rawMap, enemyGeneral)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                                                       '8,16->8,21->14,21  8,16->8,19->7,19->7,20->4,20  8,16->8,18->12,18  8,16->7,16->7,15')
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  '
                                                            '4,3->3,3->3,7->2,7->2,15->4,15  4,3->3,3->3,7->2,7->2,15->7,15->7,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.05, turns=68)
        self.assertIsNone(winner)

        self.assertTrue(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(4, 3)])
        # self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(12, 3)])
        # self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(20, 11)])
    
    def test_should_not_keep_bad_general_as_general_after_discovers_not_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_keep_bad_general_as_general_after_discovers_not_general___yEYQfURCl---0--94.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 94, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 4, 3)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=94)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '2,8->2,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        notGen = playerMap.GetTile(2, 6)
        self.assertFalse(notGen.isGeneral)
        self.assertIsNone(playerMap.generals[enemyGeneral.player])
        self.assertNotEqual(notGen, bot.targetPlayerExpectedGeneralLocation)

    def test_should_make_reasonable_general_predictions_based_on_late_far_encounter(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_use_blocking_army_to_expand__actual___o0Re_00zz---1--88.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 88, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_not_use_blocking_army_to_expand___o0Re_00zz---1--88.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=88)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,4->13,4  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 24

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        almostCertainlyNotGeneralEmVal = bot.armyTracker.get_prediction_value_x_y(enemyGeneral.player, 12, 4)
        moreLikelyGeneral = bot.armyTracker.get_prediction_value_x_y(enemyGeneral.player, 4, 9)
        self.assertGreater(moreLikelyGeneral, almostCertainlyNotGeneralEmVal, 'should have lower prediction for tile highly unlikely to be general')
        self.assertGreater(moreLikelyGeneral, 10, 'should have good prediction for tile reasonably into the fog')
        self.assertLess(almostCertainlyNotGeneralEmVal, 5, 'should have lower prediction for tile highly unlikely to be general')
    
    def test_should_keep_diving_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_keep_diving_wtf___77gwInmiz---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 16, 7)
        enemyGeneral.army = 4

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,9->10,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertEqual(map.player_index, winner)
    
    def test_should_not_dive_few_fog_tiles_when_cannot_kill(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dive_few_fog_tiles_when_cannot_kill__actual___Je4XxW4D9---1--77.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 77, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_not_dive_few_fog_tiles_when_cannot_kill___Je4XxW4D9---1--77.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=77)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertOwned(enemyGeneral.player, playerMap.GetTile(2, 6), 'should expand away from general, not into it')
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(3, 6), 'should expand away from general, not into it')
    
    def test_should_not_dive_few_fog_tiles_when_cannot_kill__pre_split(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dive_few_fog_tiles_when_cannot_kill__actual___Je4XxW4D9---1--76.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 76, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_not_dive_few_fog_tiles_when_cannot_kill___Je4XxW4D9---1--76.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=76)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,8->8,7z  8,8->12,8->12,6')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(2, 6), 'should expand away from general, not into it')
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(3, 6), 'should expand away from general, not into it')
    
    def test_should_pick_central_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_pick_central_general_location___PH1_vGrSj---0--71.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 71, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=71)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_pick_central_general_location")
    
    def test_should_not_spend_literal_ages_on_FFA_general_prediction_from_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_spend_literal_ages_on_FFA_general_prediction_from_fog___QVy9h9CfV---5--86.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 86, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=86)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        self.queue_all_other_players_leafmoves(simHost)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()

        start = time.perf_counter()
        bot.last_init_turn = 0
        bot.recalculate_player_paths(force=True)
        duration = time.perf_counter() - start

        self.assertLess(duration, 0.020)

    def test_should_not_spend_literal_ages_on_FFA_general_prediction_from_fog__earlier(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_spend_literal_ages_on_FFA_general_prediction_from_fog__earlier___QVy9h9CfV---5--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        self.queue_all_other_players_leafmoves(simHost)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()

        start = time.perf_counter()
        bot.last_init_turn = 0
        bot.recalculate_player_paths(force=True)
        duration = time.perf_counter() - start

        self.assertLess(duration, 0.020)
    
    def test_shouldnt_mess_up_the_emergence_values_for_no_apparent_reason_after_discovering_expected_1(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/shouldnt_mess_up_the_emergence_values_for_no_apparent_reason_after_discovering_expected_1___B-OhXQP69---1--87.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 87, fill_out_tiles=True)
        map.GetTile(4, 9).army = 1
        map.GetTile(0, 14).army = 2

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=87)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,5->7,5')
        simHost.queue_player_moves_str(general.player, '6,9->5,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)
        goodTile = playerMap.GetTile(0, 8)
        goodTileVal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][goodTile]
        badTiles = [
            playerMap.GetTile(7, 16),
            playerMap.GetTile(6, 17),
            playerMap.GetTile(3, 0),
        ]
        for badTile in badTiles:
            badTileVal = bot.armyTracker.emergenceLocationMap[enemyGeneral.player][badTile]
            self.assertGreater(goodTileVal, badTileVal * 1.5, f'{goodTile} should have had a much better prediction val than {badTile}')
    
    def test_should_eliminate_impossible_spawn_locations_by_bifurcating_map_after_turn_50(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_eliminate_impossible_spawn_locations_by_bifurcating_map_after_turn_50___3t__cnSLF---1--81.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 81, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=81)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '14,7->14,6')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        bot.armyTracker.uneliminated_emergence_events[enemyGeneral.player][playerMap.GetTile(7, 7)] = 25
        bot.armyTracker.uneliminated_emergence_event_city_perfect_info[enemyGeneral.player].add(playerMap.GetTile(7, 7))

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertFalse(bot.armyTracker.valid_general_positions_by_player[enemyGeneral.player][playerMap.GetTile(18, 0)], 'should consider this not possible spawn since left side emergence guarantees no path through mountains')

# 11f, 65p
# 7f, 72p
# 9f, 70p
# 9f, 71p
# 8f, 73p
# 17f, 73p after making lots of fixes for adding more emergence events
