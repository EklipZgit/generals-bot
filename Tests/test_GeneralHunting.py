import time
import typing

from Algorithms import WatchmanRouteUtils
from Path import Path
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
        for genDist in ['worstCase', 'short', 'shortPocket', 'medium']:
            with self.subTest(genDist=genDist):
                mapFile = 'GameContinuationEntries/should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying___XWHQOYv7I---1--480.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)
                turns = 3
                if genDist == 'shortPocket':
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 0, 13)
                    turns = 5
                elif genDist == 'medium':
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 0, 19)
                    turns = 11
                elif genDist == 'worstCase':
                    enemyGeneral = self.move_enemy_general(map, enemyGeneral, 3, 19)
                    turns = 15

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None  5,14->7,14->7,10->9,10->9,9->11,9')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)
                playerMap.GetTile(5, 14).lastMovedTurn = playerMap.turn

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=turns)
                self.assertEqual(map.player_index, winner)

    def test_should_dive_when_obviously_correct_to_do_so(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_dive_when_obviously_correct_to_do_so___Human.exe-TEST__c6fb898f-aadf-40f7-a9c7-381f04ad6258---1--482.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 482, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=482)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertGreater(playerMap.GetTile(1, 14).army, 185)

    def test_should_dive_when_obviously_correct_to_do_so__complete(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_dive_when_obviously_correct_to_do_so___Human.exe-TEST__c6fb898f-aadf-40f7-a9c7-381f04ad6258---1--482.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 482, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 2, 19)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=482)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,14->7,14->7,10->10,10->10,9->11,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
        self.assertEqual(winner, map.player_index)
    
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
        simHost.queue_player_moves_str(enemyGeneral.player, '8,7->8,6  8,8->10,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.info_render_expansion_matrix_values = True
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
        bot.info_render_expansion_matrix_values = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(2, 6), 'should expand away from general, not into it')
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(3, 6), 'should expand away from general, not into it')


# 11f, 65p
# 7f, 72p
# 9f, 70p
# 9f, 71p
# 8f, 73p
# 17f, 73p after making lots of fixes for adding more emergence events
# 15f, 79p after fixing the ever_owned_by_player order issue with drop_chained_bad_fog on tile-discovered-as-neutral
# 15f, 90p after adding limits for emergences from obvious locations based on pure, raw unfettered standing army.

# TODO also need to fix where they launch in a straight line only from like, 17, and then launch in a straight line again for round 2 and wrap the whole map emerging somewhere totally unexpected at like turn 80.    
    def test_should_dive_when_dead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(10):
            mapFile = 'GameContinuationEntries/should_dive_when_dead___ZAYWfdQDk---1--146.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 146, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=146)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, '2,4->2,3->5,3')
            # proof
            # simHost.queue_player_moves_str(general.player, '3,12->2,12->2,13->1,13')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
            self.assertNoFriendliesKilled(map, general)
            self.assertEqual(winner, map.player_index)
            debugMode = False

    def test_should_dive_when_dead__longer_mistake(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(10):
            mapFile = 'GameContinuationEntries/should_dive_when_dead___ZAYWfdQDk---1--146.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 146, fill_out_tiles=True)
            enemyGeneral = self.move_enemy_general(map, enemyGeneral, 3, 16)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=146)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, '2,4->1,4->1,3->5,3')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
            self.assertNoFriendliesKilled(map, general)
            self.assertEqual(winner, map.player_index)
            debugMode = False
    
    def test_should_not_dive_when_dies(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dive_when_dies___xv8It9CZ7---0--782.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 782, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 0, 13)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=782)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,2->10,2->10,4->12,4->12,6->13,6')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertNoFriendliesKilled(map, general)
    
    def test_should_keep_diving_when_all_in_and_not_much_left_to_search_regardless_of_opp_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for newX, newY in [
            (4, 9),
            (9, 5),
        ]:
            with self.subTest(genPos=(newX, newY)):
                mapFile = 'GameContinuationEntries/should_keep_diving_when_all_in_and_not_much_left_to_search_regardless_of_opp_army___LmJprxSTZ---0--300.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 300, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, newX, newY)
                self.update_tile_army_in_place(map, enemyGeneral, 27)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=300)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
                self.assertEqual(general.player, winner)

    def test_quick_kill_should_not_find_ridiculous_paths_and_override_defense_with_long_kills(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/quick_kill_should_not_find_ridiculous_paths_and_override_defense_with_long_kills___eUM0gp3BQ---0--1034.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1034, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1034)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,8->5,8->5,7->3,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
        self.assertNoFriendliesKilled(map, general)


# 8f, 6p, 0s After splitting tests out from our dear friend GeneralPrediction tests.
# 1f, 17p, 0s After making defense take kill probability into account for death-races, and never chosing worse-but-shorter kill-chance king-kill-paths in the race searcher.
    
    def test_should_not_miscalculate_the_max_distance_to_kill_for_double_back_paths(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_miscalculate_the_max_distance_to_kill_for_double-back_paths___k3lQmUUTN---0--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 7, 12)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,13->15,13->15,5->16,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        path = Path.from_string(playerMap, '9,6->9,7->9,8->9,9->8,9->7,9->7,10->6,10->6,11')

        # chance = bot.get_kill_race_chance(path, enGenProbabilityCutoff=0.0, turnsToDeath=10, cutoffKillArmy=6, againstPlayer=enemyGeneral.player)

        toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=enemyGeneral.player, cutoffEmergenceRatio=0.0, includeCities=False)
        revealedCount, maxKillTurns, minKillTurns, avgKillTurns, rawKillDistByTileMatrix, bestRevealedPath = WatchmanRouteUtils.get_revealed_count_and_max_kill_turns_and_positive_path(playerMap, path, toReveal, cutoffKillArmy=9)
        self.assertEqual(10, maxKillTurns, 'having to doubleback from the left means it takes 10t to reach bottom. Not 8...')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertEqual(map.player_index, winner)
