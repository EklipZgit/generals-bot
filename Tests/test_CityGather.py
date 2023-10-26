import logging
import time
import typing

import GatherUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class CityGatherTests(TestBase):
    def test_should_capture_neutral_city_quickly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # it can cap in 14 turns with 2 extra army, so try  reducing the army in the final tile by 1
        # repeatedly twice to see if it will cap with perfect army.

        for armyReduction in [2, 1, 0]:
            with self.subTest(armyReduction=armyReduction):
                mapFile = 'GameContinuationEntries/should_capture_neutral_city___EklipZ_ai-BxOfVysTh---a--201.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 201, fill_out_tiles=True)
                tile = map.GetTile(18, 5)
                tile.army -= armyReduction

                self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=201)

                self.begin_capturing_logging()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

                # alert enemy of the player general
                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                # beyond 14 turns its clearly screwing up
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=14)
                self.assertIsNone(winner)
                city = self.get_player_tile(12, 6, simHost.sim, map.player_index)
                self.assertEqual(general.player, city.player)
                self.assertNoRepetition(simHost)

    def test_should_capture_neutral_city_quickly__messed_up_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_neutral_city_quickly__messed_up_gather___a-TEST__f338583c-59cb-494c-9808-04b5b8a264d9---0--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=207)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        # beyond 14 turns its clearly screwing up
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.5, turns=8)
        self.assertIsNone(winner)
        city = self.get_player_tile(12, 6, simHost.sim, map.player_index)
        self.assertEqual(general.player, city.player)
        self.assertNoRepetition(simHost)

    def test_should_capture_neutral_city_quickly__messed_up_gather__gen_1_further(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_neutral_city_quickly__messed_up_gather__longer_gen___a-TEST__f338583c-59cb-494c-9808-04b5b8a264d9---0--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=207)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        # beyond 14 turns its clearly screwing up
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.5, turns=8)
        self.assertIsNone(winner)
        city = self.get_player_tile(12, 6, simHost.sim, map.player_index)
        self.assertEqual(general.player, city.player)
        self.assertNoRepetition(simHost)

    def test_should_gather_at_enemy_city_in_sane_way(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,14')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=40)
        self.assertEqual(map.player_index, winner)
        self.assertNoRepetition(simHost)
        city1 = self.get_player_tile(16, 14, simHost.sim, general.player)
        city2 = self.get_player_tile(16, 15, simHost.sim, general.player)

        self.assertEqual(general.player, city1.player)
        self.assertEqual(general.player, city2.player)

    def test_should_gather_at_enemy_city__should_use_large_tiles__all_armies_off_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way__all_armies_off_cities___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,14')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=40)
        self.assertEqual(map.player_index, winner)
        self.assertNoRepetition(simHost)
        city1 = self.get_player_tile(16, 14, simHost.sim, general.player)
        city2 = self.get_player_tile(16, 15, simHost.sim, general.player)

        self.assertEqual(general.player, city1.player)
        self.assertEqual(general.player, city2.player)
        largest = self.get_player_largest_tile(simHost.sim, general.player)
        self.assertGreater(largest.army, 150, "should have gathered big boy army to hold the cities")

    def test_should_gather_at_enemy_city__should_use_large_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=537)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,14')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=40)
        self.assertEqual(map.player_index, winner)
        self.assertNoRepetition(simHost)
        city1 = self.get_player_tile(16, 14, simHost.sim, general.player)
        city2 = self.get_player_tile(16, 15, simHost.sim, general.player)

        self.assertEqual(general.player, city1.player)
        self.assertEqual(general.player, city2.player)
        largest = self.get_player_largest_tile(simHost.sim, general.player)
        self.assertGreater(largest.army, 150, "should have gathered big boy army to hold the cities")
    
    def test_should_not_capture_enemy_cities_through_neutral_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_capture_enemy_cities_through_neutral_cities___1sjqfLDV7---0--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToRevealTo=general.player, playerToReveal=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=16)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=2)
        targCity = self.get_player_tile(8, 6, simHost.sim, general.player)
        neutCity = self.get_player_tile(9, 6, simHost.sim, general.player)

        self.assertEqual(general.player, targCity.player)
        self.assertEqual(-1, neutCity.player, 'should not have attacked target city through neutral city wtf')
    
    def test_should_not_take_city_literally_2_inches_from_enemy_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_take_city_literally_2_inches_from_enemy_army___XZvpx_iVk---1--196.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 196, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=196)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=4)
        self.assertIsNone(winner)
        city = self.get_player_tile(6, 7, simHost.sim, general.player)
        self.assertTrue(city.isNeutral)
    
    def test_should_capture_neut_city_quickly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        for allow_19_6_to_be_city in [False, True]:
            with self.subTest(allow_19_6_to_be_city=allow_19_6_to_be_city):
                mapFile = 'GameContinuationEntries/should_capture_neut_city_quickly___PHkfTkNU7---0--249.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 249, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=249)

                if not allow_19_6_to_be_city:
                    map.GetTile(19, 6).player = -1
                    map.GetTile(19, 6).isCity = False
                    map.GetTile(19, 6).isMountain = True
                    map.GetTile(19, 6).army = 0

                    rawMap.GetTile(19, 6).player = -1
                    rawMap.GetTile(19, 6).isCity = False
                    rawMap.GetTile(19, 6).isMountain = True
                    rawMap.GetTile(19, 6).army = 0

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=11)
                self.assertIsNone(winner)
                city = self.get_player_tile(17, 10, simHost.sim, general.player)
                self.assertEqual(general.player, city.player)
                self.assertLess(city.turn_captured, 259)
    
    def test_should_not_move_tiny_tiles_at_enemy_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_move_tiny_tiles_at_enemy_city___A95VaqHXU---0--410.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 410, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=410)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=9)
        self.assertIsNone(winner)

        city = self.get_player_tile(14, 19, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
    
    def test_should_retake_city_rapidly_and_not_throw_small_armies_at_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_retake_city_rapidly_and_not_throw_small_armies_at_it___t0hg-eIwL---1--329.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 329, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=329)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=35)
        self.assertIsNone(winner)

        city = self.get_player_tile(10, 11, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_fucking_sit_and_watch_itself_die_while_opponent_sits_on_distant_but_defensable_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_fucking_sit_and_watch_itself_die_while_opponent_sits_on_distant_but_defensable_city___gxNegaHi4---0--502.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 502, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=502)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_fucking_sit_and_watch_itself_die_while_opponent_sits_on_distant_but_defensable_city
    
    def test_should_capture_city_instead_of_wobbling_around_it_with_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_city_instead_of_wobbling_around_it_with_army___xrYw4Oioy---0--372.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 372, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=372)

        self.enable_search_time_limits_and_disable_debug_asserts()
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=28)
        self.assertIsNone(winner)

        city = self.get_player_tile(12, 6, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_gather_loop(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_gather_loop___uHdn3ev7Q---0--532.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 532, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=532)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=3.0, turns=10)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_gather_loop
    
    def test_should_capture_city_without_leaving_it_at_0(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_city_without_leaving_it_at_0___VMdrjWFo2---0--172.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 172, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=172)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=4)
        self.assertIsNone(winner)

        misAttackedCity = self.get_player_tile(3, 12, simHost.sim, general.player)
        self.assertEqual(general.player, misAttackedCity.player)
    
    def test_should_capture_city_without_leaving_it_at_0__longer(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_city_without_leaving_it_at_0__longer___VMdrjWFo2---0--167.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 167, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=167)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=9)
        self.assertIsNone(winner)

        misAttackedCity = self.get_player_tile(3, 12, simHost.sim, general.player)
        self.assertEqual(general.player, misAttackedCity.player)
    
    def test_should_contest_cities_over_looping_neutral(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_cities_over_looping_neutral___EklipZ_ai-Bl_nov1Wp---0--523.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 523, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=523)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        self.set_general_emergence_around(3, 15, simHost, general.player, enemyGeneral.player, 42)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=20)
        self.assertIsNone(winner)

        problemCity = self.get_player_tile(8, 4, simHost.sim, general.player)
        shouldCap1 = self.get_player_tile(14, 6, simHost.sim, general.player)
        shouldCap2 = self.get_player_tile(13, 9, simHost.sim, general.player)

        self.assertEqual(-1, problemCity.player)
        self.assertEqual(general.player, shouldCap1.player)
        self.assertEqual(general.player, shouldCap2.player)
    
    def test_should_defend_general_when_taking_pretty_safe_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_general_when_taking_pretty_safe_city___relAW4M-T---1--309.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 309, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=309)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        bot.curPath = Path()
        playerMap = simHost.get_player_map(general.player)
        bot.curPath.add_next(playerMap.GetTile(14, 3))
        bot.curPath.add_next(playerMap.GetTile(15, 3))

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=2)
        self.assertIsNone(winner)

        self.assertEqual(playerMap.GetTile(general.x, general.y), bot.locked_launch_point)
    
    def test_should_not_take_city_when_infinitely_ahead_and_also_opp_all_in_and_also_80_army_barreling_towards_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_when_infinitely_ahead_and_also_opp_all_in_and_also_80_army_barreling_towards_gen___9r7SwJVlM---unk--309.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 309, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=309)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_take_city_when_infinitely_ahead_and_also_opp_all_in_and_also_80_army_barreling_towards_gen
    
    def test_should_not_take_neutral_cities_when_ally_is_in_short_spawns_and_under_attack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_neutral_cities_when_ally_is_in_short_spawns_and_under_attack___HdGXbeKzC---2--150.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 150, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=150)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_take_neutral_cities_when_ally_is_in_short_spawns_and_under_attack
    
    def test_should_not_take_city_with_incoming_threat_and_not_enough_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_with_incoming_threat_and_not_enough_defense___V8kD0SKcI---1--178.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 178, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=178)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)

        self.fail("TODO add asserts for should_not_take_city_with_incoming_threat_and_not_enough_defense")
