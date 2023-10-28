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
        com = TeammateCommunicator(rawMap, compressor, None)

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
        simHost.run_between_turns(lambda: self.assertCoordinatedDefenseMatches(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=8)
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
        simHost.run_between_turns(lambda: self.assertCoordinatedDefenseMatches(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=8)
        self.assertNoFriendliesKilled(map, general, allyGen)

        shouldCapWith60_1 = self.get_player_tile(7, 9, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_1.player)
        shouldCapWith60_2 = self.get_player_tile(7, 10, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_2.player)
        shouldCapWith60_3 = self.get_player_tile(8, 10, simHost.sim, general.player)
        self.assertEqual(general.player, shouldCapWith60_3.player)
        self.assertGreater(shouldCapWith60_3.army, 50, "should not have used the 60 tile on defense, given the 20 tile in range.")

    def assertCoordinatedDefenseMatches(self, simHost: GameSimulatorHost):
        genBot = simHost.get_bot(simHost.sim.sim_map.player_index)
        allyBot = None
        for teammate in simHost.sim.sim_map.teammates:
            allyBot = simHost.get_bot(teammate)

        if simHost.sim.players[genBot.player.index].dead:
            self.fail('bot died')
        if simHost.sim.players[allyBot.player.index].dead:
            self.fail('ally died')

        if allyBot is None:
            self.fail('unable to find ally bot, is this a 2v2 with alive teammate whose bot is running???')

        if genBot.teammate_communicator is None:
            self.fail('genBot had no teammate_communicator, is this a 2v2 with alive teammate who is a coordinating bot?')

        if allyBot.teammate_communicator is None:
            self.fail('allyBot had no teammate_communicator, is this a 2v2 with alive teammate who is a coordinating bot?')

        lead = allyBot
        follower = genBot
        if genBot.teammate_communicator.is_defense_lead:
            lead = genBot
            follower = allyBot

        failures = []

        missingFollower = []
        for tile in lead.teammate_communicator.coordinated_defense.last_blocked_tiles_by_us:
            if tile not in follower.teammate_communicator.coordinated_defense.blocked_tiles:
                missingFollower.append(tile)

        minMatch = min(len(lead.teammate_communicator.coordinated_defense.last_blocked_tiles_by_us), 15)
        if len(missingFollower) > len(lead.teammate_communicator.coordinated_defense.last_blocked_tiles_by_us) - minMatch:
            failures.append(f'follower was missing {len(missingFollower)} blocked tiles {"|".join([str(t) for t in missingFollower])}')

        missingLeader = []
        for tile in follower.teammate_communicator.coordinated_defense.last_blocked_tiles_by_us:
            if tile not in lead.teammate_communicator.coordinated_defense.blocked_tiles:
                missingLeader.append(tile)

        minMatch = min(len(follower.teammate_communicator.coordinated_defense.last_blocked_tiles_by_us), 15)
        if len(missingLeader) > len(follower.teammate_communicator.coordinated_defense.last_blocked_tiles_by_us) - minMatch:
            failures.append(f'lead was missing {len(missingLeader)} blocked tiles {"|".join([str(t) for t in missingLeader])}')

        if len(failures) > 0:
            msg = f'LEAD p{lead.player.index}: {str(lead.teammate_communicator)}\nFOLLOWER p{follower.player.index}: {str(follower.teammate_communicator)}'
            combinedFailures = "\n".join(failures)
            self.fail(f'\n{msg}\n{combinedFailures}')
    
    def test_should_coordinate_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for attacksSelf in [False, True, None]:
            with self.subTest(attacksSelf=attacksSelf):
                mapFile = 'GameContinuationEntries/should_coordinate_defense___VCeF4MjuX---3--184.txtmap'
                map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 184, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=184)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
                if attacksSelf is None:
                    simHost.queue_player_moves_str(enemyAllyGen.player, 'None')
                elif attacksSelf:
                    simHost.queue_player_moves_str(enemyAllyGen.player, '5,11->5,10->5,9->6,9->7,9->8,9->9,9->10,9->10,10')
                else:
                    simHost.queue_player_moves_str(enemyAllyGen.player, '5,11->5,10->5,9->6,9->7,9->8,9->9,9->9,8->9,7->9,6->10,6->11,6')
                bot = simHost.get_bot(general.player)
                self.set_general_emergence_around(7, 22, simHost, general.player, emergencePlayer=enemyGeneral.player, emergenceAmt=33)
                self.set_general_emergence_around(7, 22, simHost, allyGen.player, emergencePlayer=enemyGeneral.player, emergenceAmt=33)
                playerMap = simHost.get_player_map(general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                simHost.run_between_turns(lambda: self.assertCoordinatedDefenseMatches(simHost))
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=12)
                self.assertNoFriendliesKilled(map, general, allyGen)
    
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
        simHost.run_between_turns(lambda: self.assertCoordinatedDefenseMatches(simHost))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertNoFriendliesKilled(map, general, allyGen)

    
    def test_should_not_loop_on_2v2_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_on_2v2_defense___2J0rKDuFG---3--131.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 131, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=131)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,11->15,12->15,13->16,13->16,14->17,14->17,15->17,16->17,17->17,18->17,19->17,20->18,20')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_not_pull_back_army_when_cannot_defend_teammate__all_in_attacker_instead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_pull_back_army_when_cannot_defend_teammate__all_in_attacker_instead___W9ueAfLB----2--201.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 201, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=201)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,11->8,11->8,12->8,13->8,14->7,14->6,14->5,14->4,14->4,15->4,16')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=11)
        self.assertNoFriendliesKilled(map, general, allyGen)
