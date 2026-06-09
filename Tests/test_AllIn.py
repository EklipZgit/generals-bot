import logbook
import time
import typing

import DebugHelper
import Gather
import SearchUtils
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot


class AllInTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.gather_use_pcst = True
        # bot.info_render_centrality_distances = True

        return bot

    def test_should_execute_the_full_all_in(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_execute_the_full_all_in___ESW_l8ssb---1--358.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 358, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=358)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=75)
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(general.player, winner)

    def test_should_not_make_unsafe_winning_all_in_plans(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO should just keep some army near general? As much as 30 turn attack risk?
        #  Or, should make sure to launch attacks down the straight line path?
        mapFile = 'GameContinuationEntries/should_not_make_unsafe_winning_all_in_plans___f1tVhCbAr---1--458.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 458, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=458)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=55)
        self.assertNoFriendliesKilled(map, general)

    def test_should_stop_allinning_and_city_after_failed_attack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_stop_allinning_and_city_after_failed_attack___AANZekIm8---1--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->16,13')
        simHost.queue_player_moves_str(general.player, '16,14->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.is_all_in_losing = True
        bot.all_in_losing_counter = 136
        bot.all_in_army_advantage_counter = 23
        bot.all_in_army_advantage_cycle = 35
        bot.timings.launchTiming = 5
        bot.timings.splitTurns = 2
        bot.targetingArmy = bot.get_army_at(simHost.get_player_map(general.player).GetTile(9, 3))
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)
        self.assertFalse(bot.is_all_in_losing)
        self.assertEqual(0, bot.all_in_losing_counter)
        self.assertFalse(bot.is_all_in_army_advantage)
        self.assertFalse(bot.all_in_city_behind)

    def test_should_stop_allinning_and_city_after_failed_attack__long(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_stop_allinning_and_city_after_failed_attack___AANZekIm8---1--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->16,13')
        simHost.queue_player_moves_str(general.player, '16,14->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.is_all_in_losing = True
        bot.all_in_losing_counter = 136
        bot.all_in_army_advantage_counter = 23
        bot.all_in_army_advantage_cycle = 35
        bot.timings.launchTiming = 5
        bot.timings.splitTurns = 2
        bot.targetingArmy = bot.get_army_at(simHost.get_player_map(general.player).GetTile(9, 3))
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=35)
        self.assertNoFriendliesKilled(map, general)
        self.assertFalse(bot.is_all_in_losing)
        self.assertEqual(0, bot.all_in_losing_counter)
        self.assertFalse(bot.is_all_in_army_advantage)
        self.assertFalse(bot.all_in_city_behind)

        self.assertOwnedXY(2, 17)

    def test_should_stop_allinning_and_city_after_failed_attack__no_flags_450_repro(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_stop_allinning_and_city_after_failed_attack___AANZekIm8---1--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->16,13')
        simHost.queue_player_moves_str(general.player, '16,14->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.targetingArmy = bot.get_army_at(simHost.get_player_map(general.player).GetTile(9, 3))
        playerMap = simHost.get_player_map(general.player)

        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=45)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwnedXY(2, 17)