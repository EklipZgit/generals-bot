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
                rawMap, _ = self.load_map_and_general(mapFile, 201)

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

        rawMap, _ = self.load_map_and_general(mapFile, 207)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        # beyond 14 turns its clearly screwing up
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.5, turns=8)
        self.assertIsNone(winner)
        city = self.get_player_tile(12, 6, simHost.sim, map.player_index)
        self.assertEqual(general.player, city.player)
        self.assertNoRepetition(simHost)

    def test_should_capture_neutral_city_quickly__messed_up_gather__gen_1_further(self):
        # TODO this has an off by one with general distance, explore further
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_neutral_city_quickly__messed_up_gather__longer_gen___a-TEST__f338583c-59cb-494c-9808-04b5b8a264d9---0--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 207)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        # beyond 14 turns its clearly screwing up
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.5, turns=8)
        self.assertIsNone(winner)
        city = self.get_player_tile(12, 6, simHost.sim, map.player_index)
        self.assertEqual(general.player, city.player)
        self.assertNoRepetition(simHost)

    def test_should_gather_at_enemy_city_in_sane_way(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 537)

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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way__all_armies_off_cities___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 537)

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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_at_enemy_city_in_sane_way___SAsqVqIT3---1--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 537)

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
