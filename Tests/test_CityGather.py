import logbook
import time
import typing

import GatherUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from bot_ek0x45 import EklipZBot


class CityGatherTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_centrality_distances = True
        bot.info_render_city_priority_debug_info = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_should_capture_nearby_neutral_city_quickly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

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
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=14)
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_neutral_city_quickly__messed_up_gather__longer_gen___a-TEST__f338583c-59cb-494c-9808-04b5b8a264d9---0--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=207)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        # beyond 14 turns its clearly screwing up
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=8)
        self.assertIsNone(winner)
        city = self.get_player_tile(12, 6, simHost.sim, map.player_index)
        self.assertEqual(general.player, city.player)
        self.assertNoRepetition(simHost)

    def test_should_gather_at_enemy_city__should_use_large_tiles(self):
        # TODO this test should pass, we need to take into account that we're waaaay ahead on army and that we can contest near-enemy-gen cities.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=4)
        self.assertIsNone(winner)
        city = self.get_player_tile(6, 7, simHost.sim, general.player)
        self.assertTrue(city.isNeutral)
    
    def test_should_capture_neut_city_quickly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=11)
                self.assertIsNone(winner)
                city = self.get_player_tile(17, 10, simHost.sim, general.player)
                self.assertEqual(general.player, city.player)
                self.assertLess(city.turn_captured, 259)
    
    def test_should_not_move_tiny_tiles_at_enemy_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_move_tiny_tiles_at_enemy_city___A95VaqHXU---0--410.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 410, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=410)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=9)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        city = self.get_player_tile(19, 13, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
    
    def test_should_capture_city_instead_of_wobbling_around_it_with_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_city_instead_of_wobbling_around_it_with_army___xrYw4Oioy---0--372.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 372, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=372)

        self.enable_search_time_limits_and_disable_debug_asserts()
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=10)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=30)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost, 3)
    
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=4)
        self.assertIsNone(winner)

        misAttackedCity = self.get_player_tile(3, 12, simHost.sim, general.player)
        self.assertEqual(general.player, misAttackedCity.player)
    
    def test_should_capture_city_without_leaving_it_at_0__longer(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_city_without_leaving_it_at_0__longer___VMdrjWFo2---0--167.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 157, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=157)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=9)
        self.assertIsNone(winner)

        misAttackedCity = self.get_player_tile(3, 12, simHost.sim, general.player)
        self.assertEqual(general.player, misAttackedCity.player)
    
    def test_should_contest_cities_over_looping_neutral(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.curPath = Path()
        playerMap = simHost.get_player_map(general.player)
        bot.curPath.add_next(playerMap.GetTile(14, 3))
        bot.curPath.add_next(playerMap.GetTile(15, 3))

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
        self.assertIsNone(winner)

        self.assertIn(bot.locked_launch_point, [playerMap.GetTile(general.x, general.y), playerMap.GetTile(9, 1)])
    
    def test_should_not_take_city_when_infinitely_ahead_and_also_opp_all_in_and_also_80_army_barreling_towards_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_when_infinitely_ahead_and_also_opp_all_in_and_also_80_army_barreling_towards_gen___9r7SwJVlM---unk--309.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 309, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=309)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_take_city_when_infinitely_ahead_and_also_opp_all_in_and_also_80_army_barreling_towards_gen")
    
    def test_should_not_take_neutral_cities_when_ally_is_in_short_spawns_and_under_attack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_neutral_cities_when_ally_is_in_short_spawns_and_under_attack___HdGXbeKzC---2--150.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 150, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=150)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_take_neutral_cities_when_ally_is_in_short_spawns_and_under_attack")
    
    def test_should_not_take_city_with_incoming_threat_and_not_enough_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_with_incoming_threat_and_not_enough_defense___V8kD0SKcI---1--178.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 178, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=178)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)

        self.skipTest("TODO add asserts for should_not_take_city_with_incoming_threat_and_not_enough_defense")
    
    def test_should_take_city_rapidly_when_behind_on_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_city_rapidly_when_behind_on_cities___3fZGacFN2---1--350.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 350, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=350)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=6)
        self.assertIsNone(winner)

        neutCity = self.get_player_tile(21, 14, simHost.sim, general.player)
        self.assertEqual(general.player, neutCity.player, "should capture the city in just 5 moves, the threat is not real.")
    
    def test_should_build_consistent_plan_when_other_en_cities_near_target_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_build_consistent_plan_when_other_en_cities_near_target_city___WaeMrE9dh---7--190.txtmap'

        for turn in [199, 190]:
            with self.subTest(turn=turn):
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=20)
                self.assertIsNone(winner)
                neutCity = self.get_player_tile(25, 6, simHost.sim, general.player)
                neutCity2 = self.get_player_tile(25, 7, simHost.sim, general.player)
                self.assertEqual(general.player, neutCity.player, "should capture the city with a reasonable plan.")
                self.assertEqual(general.player, neutCity2.player, "should capture the city with a reasonable plan.")
    
    def test_should_capture_neutrals_as_part_of_neutral_city_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_neutrals_as_part_of_neutral_city_capture___089dxyou6---0--128.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 128, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=128)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=8)
        self.assertIsNone(winner)

        city = self.get_player_tile(7, 14, simHost.sim, general.player)
        self.assertEqual(general.player, city.player)
        self.assertPlayerTileCountGreater(simHost, general.player, 52)
    
    def test_should_find_neutral_city_plan_in_2v2(self):
        for includeThreat in [True, False]:
            with self.subTest(includeThreat=includeThreat):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_find_neutral_city_plan_in_2v2___vNT0pIjQh---1--152.txtmap'
                map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 152, fill_out_tiles=True)
                if not includeThreat:
                    map.GetTile(7, 9).army = 3

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=152)
                if not includeThreat:
                    rawMap.GetTile(7, 9).army = 3

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=16)
                self.assertNoFriendliesKilled(map, general, allyGen)

                city = self.get_player_tile(0, 17, simHost.sim, general.player)
                self.assertEqual(general.player, city.player)
    
    def test_should_take_city_immediately_when_army_already_available(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_city_immediately_when_army_already_available___MlbMS86zL---0--221.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 221, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=221)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_take_city_immediately_when_army_already_available")
    
    def test_should_lock_contest_city_hold(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_lock_contest_city_hold___fPr-_oVde---0--365.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 365, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=365)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_lock_contest_city_hold")
    
    def test_should_perform_longer_gather_to_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_perform_longer_gather_to_cities___brrUpq8hx---4--677.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 677, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=677)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=40)
        self.assertIsNone(winner)

        cities = [
            playerMap.GetTile(16, 22),
            playerMap.GetTile(17, 22),
            playerMap.GetTile(18, 22),
            playerMap.GetTile(16, 23),
        ]

        sumArmy = 0
        for city in cities:
            self.assertEqual(general.player, city.player)
            sumArmy += city.army

        self.assertGreater(sumArmy, 300)

    def test_should_capture_low_cost_neut_cities_always_when_in_territory(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_capture_low_cost_neut_cities_always_when_in_territory___nkMvOkJbO---1--164.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 164, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=164)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        city = playerMap.GetTile(17, 20)
        self.assertEqual(general.player, city.player)
    
    def test_should_fully_capture_neutral_city_when_half_gather_capped(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_fully_capture_neutral_city_when_half_gather_capped___wFQ2UmoQ6---0--165.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 165, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=165)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

        city = playerMap.GetTile(5, 13)
        self.assertEqual(general.player, city.player)
    
    def test_should_prefer_cities_with_lower_army_nearby(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prefer_cities_with_lower_army_nearby___wFQ2UmoQ6---0--166.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 166, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=166)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)

        city = playerMap.GetTile(5, 13)
        self.assertEqual(general.player, city.player)
    
    def test_should_prioritize_city_next_to_ally_in_2v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prioritize_city_next_to_ally_in_2v2___V0Wzs1v8F---3--167.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 167, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=167)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertNoFriendliesKilled(map, general, allyGen)

        city = playerMap.GetTile(2, 14)
        self.assertEqual(general.player, city.player)
    
    def test_should_complete_city_capture_on_two_part_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_complete_city_capture_on_two_part_capture___tE-bn_163---1--169.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 169, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=169)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        city = playerMap.GetTile(15, 1)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_take_city_when_already_clearly_winning_and_dangerous_path_leading_to_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_when_already_clearly_winning_and_dangerous_path_leading_to_general___xzuEAS2wv---0--257.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 257, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=257)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=22)
        self.assertIsNone(winner)

        city = playerMap.GetTile(9, 2)
        self.assertGreater(bot.sum_player_army_near_or_on_tiles([playerMap.GetTile(9, 3)], distance=5, player=general.player), 50)
        self.assertEqual(-1, city.player)
    
    def test_should_not_explode(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_explode___Kj2jWIDxL---1--301.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 301, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=301)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        city = playerMap.GetTile(6, 15)
        self.assertEqual(general.player, city.player)
    
    def test_should_immediately_take_neut_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_take_neut_city___dq3qt0vH7---0--364.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 364, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=364)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        cities = playerMap.players[general.player].cityCount
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertEqual(cities + 1, playerMap.players[general.player].cityCount)

    
    def test_should_kill_city_through_pot_threat_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_city_through_pot_threat_army___cRk3OleD_---1--447.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 447, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=447)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        city = playerMap.GetTile(11, 12)
        self.assertEqual(general.player, city.player)
    
    def test_should_still_hunt_for_neut_cities_on_wall(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_still_hunt_for_neut_cities_on_wall___x3dzbS3PR---1--255.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 255, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=255)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        self.set_general_emergence_around(3, 5, simHost, general.player, enemyGeneral.player, 20)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)

        for tile in [
            playerMap.GetTile(18, 5),
            playerMap.GetTile(16, 3),
            playerMap.GetTile(13, 6),
            playerMap.GetTile(9, 8),
        ]:
            self.assertTrue(tile.visible, f"should have made sure {str(tile)} was not a neutral city before all-inning")

    def test_should_include_general_increment_in_city_gather_plan(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_include_general_increment_in_city_gather_plan___tS4MlQCW----1--151.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 151, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=151)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)

        city = playerMap.GetTile(17,15)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_take_city_when_it_will_immediately_get_captured_by_inbound_army__intercept_instead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_when_it_will_immediately_get_captured_by_inbound_army__intercept_instead___zH6C8UTDp---0--301.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 301, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=301)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_take_city_when_it_will_immediately_get_captured_by_inbound_army__intercept_instead")
    
    def test_should_take_into_account_ALL_nearby_increments_when_recapturing(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_into_account_ALL_nearby_increments_when_recapturing___zH6C8UTDp---0--312.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 312, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=312)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_take_into_account_ALL_nearby_increments_when_recapturing")
    
    def test_should_take_cities___why_didnt_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_cities___why_didnt_it___z3syA4nz7---0--356.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 356, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=356)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)

        self.assertEqual(2, playerMap.players[general.player].cityCount)
    
    def test_should_contest_en_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_en_city___Be7wPfd4p---1--343.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        city = playerMap.GetTile(12, 9)
        self.assertEqual(general.player, city.player)

    def test_should_contest_en_city_large_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_en_city_large_army___Be7wPfd4p---1--294.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 294, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=294)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        city = playerMap.GetTile(12, 9)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_take_city_way_out_of_play_when_winning(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_way_out_of_play_when_winning___PdWWtSIji---1--182.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 182, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=182)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        city1 = playerMap.GetTile(15, 7)
        city2 = playerMap.GetTile(9, 9)

        self.assertTrue(city1.isNeutral)
        self.assertTrue(city2.isNeutral)
    
    def test_should_find_neutral_city_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_neutral_city_path___sPHQbQG0c---1--200.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 200, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=200)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        city = playerMap.GetTile(6, 15)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_prune_useful_forward_moving_gather_tiles_when_taking_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_prune_useful_forward_moving_gather_tiles_when_taking_city___mEG6AMNX----1--176.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 176, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=176)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
        self.assertIsNone(winner)

        city = playerMap.GetTile(12, 15)
        self.assertEqual(general.player, city.player, "should have still taken the city")

        self.assertMinArmyNear(playerMap, playerMap.GetTile(12, 15), general.player, minArmyAmount=15)
    
    def test_should_take_full_army_to_en_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_full_army_to_en_city___HeMrKllS6---1--449.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 449, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=449)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=18)
        self.assertIsNone(winner)

        c1 = playerMap.GetTile(16, 11)
        c2 = playerMap.GetTile(16, 14)

        self.assertEqual(general.player, c1.player)
        self.assertEqual(general.player, c2.player)
    
    def test_should_kill_threat_city_before_other_one(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_threat_city_before_other_one___EklipZ_ai-TEST__f1240198-940f-454c-abe4-e440057de3ad---1--463.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 463, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=463)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        c1 = playerMap.GetTile(16, 11)
        c2 = playerMap.GetTile(16, 14)

        self.assertEqual(general.player, c1.player)
        self.assertEqual(general.player, c2.player)
    
    def test_should_take_city_that_gets_found_during_city_search(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_city_that_gets_found_during_city_search___a5JCyZHf4---0--202.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 202, fill_out_tiles=True)
        map.GetTile(10, 17).reset_wrong_undiscovered_fog_guess()
        map.GetTile(10, 17).isCity = True
        map.GetTile(10, 17).isMountain = False
        map.GetTile(10, 17).army = 45

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=202)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(general.player, '8,18->9,18')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        city = playerMap.GetTile(10, 17)
        self.assertEqual(general.player, city.player)

    def test_should_not_miscount_gather_prune_at_neut_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_miscount_gather_prune_at_neut_city___a5JCyZHf4---0--306.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 306, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=306)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        city = playerMap.GetTile(10, 17)
        self.assertEqual(general.player, city.player)

    # 14 fail - 38 pass - 6 skip
    
    def test_should_keep_expanding_until_cycle_end(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_keep_expanding_until_cycle_end___OGhsl6UbO---0--147.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 147, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=147)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 57)

    def test_should_immediately_take_city_after_cycle_end(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_keep_expanding_until_cycle_end___OGhsl6UbO---0--147.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 147, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=147)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertIsNone(winner)

        city = playerMap.GetTile(10, 4)
        self.assertEqual(general.player, city.player)

    def test_should_correctly_calculate_city_recapture_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_calculate_city_recapture_gather___Iqjw4Uqb9---0--268.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 268, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=268)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        city = playerMap.GetTile(14, 19)
        self.assertEqual(general.player, city.player)
    
    def test_should_immediately_choose_to_take_low_army_city_near_gen_because_plenty_to_defend(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_choose_to_take_low_army_city_near_gen_because_plenty_to_defend___50vyo-z9H---1--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=250)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertEqual(4, playerMap.players[general.player].cityCount, "should immediately take a city and see what opp does, because it is safe to take city.")
    
    def test_should_be_able_to_recapture_large_city_cluster(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_able_to_recapture_large_city_cluster___SIA0U-TNH---1--280.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 280, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=280)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,5->4,5->5,5->5,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)

        cities = [
            playerMap.GetTile(4, 5),
            playerMap.GetTile(5, 5),
            playerMap.GetTile(5, 4),
        ]

        for city in cities:
            self.assertEqual(general.player, city.player)
    
    def test_should_take_a_city_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_a_city_wtf___GdMxKwwYg---1--222.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 222, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=222)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        city = playerMap.GetTile(2, 6)
        self.assertEqual(general.player, city.player)
    
    def test_should_not_go_all_in_so_early(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_go_all_in_so_early____5kMDUymF---0--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=207)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        city = playerMap.GetTile(12, 19)
        self.assertEqual(general.player, city.player)

    def test_should_keep_up_on_city_quickly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_keep_up_on_city_quickly____5kMDUymF---0--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,7->10,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=19)
        self.assertIsNone(winner)

        city = playerMap.GetTile(12, 19)
        self.assertEqual(general.player, city.player)

# 21f 36p 6s
# 28f 32p
    
    def test_should_take_city_successfully(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_city_successfully___LhI9vx7IM---0--205.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 205, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=205)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        city = playerMap.GetTile(18, 8)
        self.assertEqual(general.player, city.player)
    
    def test_should_prioritize_city_capture_over_continuing_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prioritize_city_capture_over_continuing_expansion___7WHOMEi14---0--221.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 221, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=221)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        city = playerMap.GetTile(5, 15)
        self.assertEqual(general.player, city.player)

    def test_should_not_take_city_right_in_front_of_enemy_army__obviously(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_city_right_in_front_of_enemy_army__obviously___NTIkjrCqy---0--282.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 282, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=282)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_take_city_right_in_front_of_enemy_army__obviously")
    
    def test_should_immediately_take_city_because_recognize_long_spawn_and_two_useful_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_take_city_because_recognize_long_spawn_and_two_useful_cities___LjdcE2CJ9---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        city = playerMap.GetTile(14, 11)
        self.assertEqual(general.player, city.player)
    
    def test_should_complete_city_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_complete_city_capture___AXNDhHg4Q---1--171.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 171, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=171)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        city = playerMap.GetTile(19, 5)
        self.assertOwned(general.player, city)

    def test_should_not_hit_city_with_army_earlier_than_few_moves_away(self):
        for turns, shouldCap in [(2, False), (10, True)]:
            with self.subTest(turns=turns):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_not_hit_city_with_army_earlier_than_few_moves_away___zQ7JGZWHJ---0--261.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 261, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=261)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                # simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                simHost.queue_player_leafmoves(enemyGeneral.player)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=turns)
                self.assertIsNone(winner)

                city = playerMap.GetTile(2, 1)
                if shouldCap:
                    self.assertOwned(general.player, city)
                else:
                    self.assertEqual(44, city.army)

