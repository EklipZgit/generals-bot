import random
import time

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from Behavior.ArmyInterceptor import ArmyInterceptor, TARGET_CAP_VALUE
from BotModules.BotDefense import BotDefense
from BotModules.BotTimings import BotTimings
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot


# TESTS FOR VETTING THAT THE BOT SPLITS LARGE ARMIES IN VARIOUS SITUATIONS WHERE IT SHOULD
class SplitsTests(TestBase):
    def __init__(self, methodName: str = ...):
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_intercept_data = True
        bot.info_render_board_analysis_choke_widths = False
        bot.info_render_army_emergence_values = False
        bot.army_interceptor.log_debug = True
        bot.army_interceptor.log_eval_debug = True

        return bot

    def test_when_ahead_should_split_army_to_take_land_near_contestable_city_rather_than_bouncing_300_back_and_forth_against_a_60(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/when_ahead_should_split_army_to_take_land_near_contestable_city_rather_than_bouncing_300_back_and_forth_against_a_60___eML12_ZSN---0--686.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 686, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=686)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for when_ahead_should_split_army_to_take_land_near_contestable_city_rather_than_bouncing_300_back_and_forth_against_a_60")
