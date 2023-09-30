import logging
import time
import typing

import GatherUtils
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
        self.assertEqual(general.player, winner)
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
        self.assertEqual(general.player, winner)
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
        self.assertEqual(general.player, winner)
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
