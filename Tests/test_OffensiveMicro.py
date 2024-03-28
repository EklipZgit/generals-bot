from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class OffensiveMicroTests(TestBase):
    def test_should_avoid_army_by_looping_downward_and_right(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_avoid_army_by_looping_downward_and_right___TooE-srNn---1--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        self.skipTest("TODO add asserts for should_avoid_army_by_looping_downward_and_right")

    def test_should_not_prefer_intercept_when_can_just_tile_trade_while_ahead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for enPath, proof in [
            ('12,5->11,5->11,6  19,5->19,6  11,6->12,6->12,7->11,7', '11,7->12,7->12,8z  12,7->12,6  12,8->16,8'),
            ('12,5->11,5->11,6->11,7->12,7->12,8', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
            ('12,5->8,5->8,10', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
            ('12,5->11,5->11,7->12,7->12,8->14,8', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
        ]:
            with self.subTest(enPath=enPath):
                mapFile = 'GameContinuationEntries/should_not_prefer_intercept_when_can_just_tile_trade_while_ahead___TooE-srNn---1--145.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 145, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=145)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                simHost.queue_player_moves_str(general.player, proof)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
                self.assertIsNone(winner)

                self.assertTileDifferentialGreaterThan(3, simHost)

    def test_should_split_to_guarantee_territory_capture_to_end_of_round(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_to_guarantee_territory_capture_to_end_of_round___aKuLkFq66---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)

        self.assertGreaterEqual(12, playerMap.GetTile(12, 11).army, 'should have split to cap land even at slight econ loss when ahead on round caps')
        self.assertGreaterEqual(12, playerMap.GetTile(11, 11).army, 'should have split to cap land even at slight econ loss when ahead on round caps')
