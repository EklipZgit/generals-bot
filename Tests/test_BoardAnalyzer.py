import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.tile import TILE_MOUNTAIN, TILE_EMPTY, MapBase


class BoardAnalyzerTests(TestBase):    
    def test_should_produce_central_defense_point_on_city_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_produce_central_defense_point_on_city_capture___mEG6AMNX----1--213.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 213, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=213)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertTileNearOtherTile(playerMap, playerMap.GetTile(14, 13), bot.board_analysis.central_defense_point)

        self.assertTileNearOtherTile(playerMap, bot.board_analysis.central_defense_point, bot.locked_launch_point)
    
    def test_should_not_have_empty_pathways_after_city_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_have_empty_pathways_after_city_capture___ZD1xbwlTS---0--321.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 321, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=321)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
