import logging
import typing

from ArmyEngine import ArmyEngine, ArmySimResult
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile, MapBase


class ArmyEngineGameTests(TestBase):
    def test_should_scrim_against_incoming_army__long_dist(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_scrim_against_incoming_army___BlzKXZ-pn---b--238.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 238)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 238)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=10)

        # TODO add asserts for should_scrim_against_incoming_army

    def test_should_scrim_against_incoming_army(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_scrim_against_incoming_army___b-TEST__fcb6b723-0f6d-4f85-a465-62c0f4081d7d-----241.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 241)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=2.0)

        # TODO add asserts for should_scrim_against_incoming_army
    
    def test_army_scrim_defense_should_not_avoid_kill_threat(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/army_scrim_defense_should_not_avoid_kill_threat___rgNPA7Zan---b--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 388)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for army_scrim_defense_should_not_avoid_kill_threat


    def test_army_scrim_defense_should_still_save_out_of_range(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/army_scrim_defense_should_not_avoid_kill_threat___rgNPA7Zan__Modified_range.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 389)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 389)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.5, turns=15)
        self.assertIsNone(winner)
    
    def test_should_intercept_correctly(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_intercept_correctly___BegNpvZT3---a--246.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 246)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 246)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_intercept_correctly
    
    def test_should_not_cycle_sideways(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_not_cycle_sideways___rlgSxdZ62---b--423.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 423)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 423)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_cycle_sideways
    
    def test_should_not_let_general_die_scrim_path(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_not_let_general_die_scrim_path___HeTqrYFT3---a--740.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 740, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 740)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.01, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_let_general_die_scrim_path__turn_before(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_not_let_general_die_scrim_path__turn_before___HeTqrYFT3---a--739.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 739, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 739)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.01, turns=15)
        self.assertIsNone(winner)
