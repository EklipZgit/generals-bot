import EarlyExpandUtils
from BotHost import BotHostBase
from DataModels import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class ExplorationTests(TestBase):
    
    def test_shouldnt_make_nonsense_exploration_path_15_6__15_5__15_4(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/shouldnt_make_nonsense_exploration_path_15_6__15_5__15_4___HlRRkn923---b--543.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 543)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=-2)

        rawMap, _ = self.load_map_and_general(mapFile, 543)
        simHost.apply_map_vision(general.player, rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.bot_hosts[general.player].eklipz_bot.allIn = True
        simHost.bot_hosts[general.player].eklipz_bot.all_in_counter = 500

        simHost.bot_hosts[general.player].eklipz_bot.finishingExploration = True

        negTiles = set()
        for city in map.players[general.player].cities:
            negTiles.add(city)
        negTiles.add(general)
        #
        # simHost.run_sim(run_real_time=debugMode, turn_time=10, turns=30)

        self.begin_capturing_logging()
        badPathStartTile = self.get_player_tile(15,6, simHost.sim, general.player)
        path = simHost.bot_hosts[general.player].eklipz_bot.explore_target_player_undiscovered(negTiles)

        self.assertIsNotNone(path)
        self.assertNotEquals(badPathStartTile, path.start.tile)

        # TODO add asserts for shouldnt_make_nonsense_exploration_path_15_6__15_5__15_4
