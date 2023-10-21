from Communication import TeammateCommunicator, TileCompressor
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class TeamCommunicatorTests(TestBase):
    def test_team_communicator_recognizes_bots(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_ally_in_2v2___brs1WYHiG---0--132.txtmap'
        map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=132)

        compressor = TileCompressor(rawMap)
        com = TeammateCommunicator(rawMap, compressor)

        self.assertTrue(com.is_2v2)
        self.assertTrue(com.is_teammate_coordinated_bot)
        self.assertTrue(com.is_team_lead)

    def test_team_communicator_communicates_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_ally_in_2v2___brs1WYHiG---0--132.txtmap'
        map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=132)
        # give blue ~ 40 army worth of gatherable defense
        map.GetTile(10, 7).army = 10
        rawMap.GetTile(10, 7).army = 10
        map.GetTile(11, 9).army = 10
        rawMap.GetTile(11, 9).army = 10

        # give red a smaller tile to help defend with so it can leave the 60 for recapturing
        map.GetTile(8, 7).army = 20
        rawMap.GetTile(8, 7).army = 20
        map.GetTile(8, 7).player = 0
        rawMap.GetTile(8, 7).player = 0

        map.GetTile(16, 8).army = 60
        rawMap.GetTile(16, 8).army = 60

        compressor = TileCompressor(rawMap)
        com = TeammateCommunicator(rawMap, compressor, boardAnalysis=None)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enAllyGen.player, '16,8->15,8->14,8->13,8->12,8->11,8->10,8')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.assertIsNotNone(bot.threat)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=8)
        self.assertNoFriendliesKilled(map, general, allyGen)

        shouldCapWith60_1 = self.get_player_tile(7, 9, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_1.player)
        shouldCapWith60_2 = self.get_player_tile(7, 10, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_2.player)
        shouldCapWith60_3 = self.get_player_tile(8, 10, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_3.player)
        self.assertGreater(shouldCapWith60_3.army, 50, "should not have used the 60 tile on defense, given the 20 tile in range.")

    def test_team_communicator_communicates_defense__blue(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_ally_in_2v2___brs1WYHiG---0--132.txtmap'
        map, general, allyGen, enemyGeneral, enAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=132)
        # give blue ~ 40 army worth of gatherable defense
        map.GetTile(10, 7).army = 10
        rawMap.GetTile(10, 7).army = 10
        map.GetTile(11, 9).army = 10
        rawMap.GetTile(11, 9).army = 10

        # give red a smaller tile to help defend with so it can leave the 60 for recapturing
        map.GetTile(8, 7).army = 20
        rawMap.GetTile(8, 7).army = 20
        map.GetTile(8, 7).player = 0
        rawMap.GetTile(8, 7).player = 0

        # give red a smaller tile to help defend with so it can leave the 60 for recapturing
        map.GetTile(14, 9).army = 10
        rawMap.GetTile(14, 9).army = 10
        map.GetTile(14, 9).player = 1
        rawMap.GetTile(14, 9).player = 1

        # give red a smaller tile to help defend with so it can leave the 60 for recapturing
        map.GetTile(14, 12).army = 20
        rawMap.GetTile(14, 12).army = 20
        map.GetTile(14, 12).player = 1
        rawMap.GetTile(14, 12).player = 1

        map.GetTile(16, 8).army = 60
        rawMap.GetTile(16, 8).army = 60

        compressor = TileCompressor(rawMap)
        com = TeammateCommunicator(rawMap, compressor, boardAnalysis=None)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=allyGen.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enAllyGen.player, '16,8->15,8->14,8->13,8->12,8->11,8->10,8')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        self.assertIsNotNone(bot.threat)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=8)
        self.assertNoFriendliesKilled(map, general, allyGen)

        shouldCapWith60_1 = self.get_player_tile(7, 9, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_1.player)
        shouldCapWith60_2 = self.get_player_tile(7, 10, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_2.player)
        shouldCapWith60_3 = self.get_player_tile(8, 10, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_3.player)
        self.assertGreater(shouldCapWith60_3.army, 50, "should not have used the 60 tile on defense, given the 20 tile in range.")
    
    def test_should_coordinate_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_coordinate_defense___VCeF4MjuX---3--184.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 184, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=184)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        self.set_general_emergence_around(7, 22, simHost, general.player, emergencePlayer=enemyGeneral.player, emergenceAmt=33)
        self.set_general_emergence_around(7, 22, simHost, allyGen.player, emergencePlayer=enemyGeneral.player, emergenceAmt=33)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=10.0, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)

        self.fail("TODO add asserts for should_coordinate_defense")
    
    def test_should_coordinate_defense_on_close_spawns(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_coordinate_defense___1sM7IUnt5---3--133.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 133, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=133)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,16->15,16->15,17->15,18->15,19->14,19->13,19->12,19->11,19->10,19->9,19->8,19->8,20')
        simHost.queue_player_moves_str(general.player, '15,16->15,15')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=15)
        self.assertNoFriendliesKilled(map, general, allyGen)

