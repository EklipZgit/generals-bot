import logbook

import SearchUtils
from Directives import Timings
from Path import Path
from SearchUtils import Counter
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class FFATests(TestBase):
    def test_should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos___j4GQjpuy4---0--379.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 379, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 20)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=379)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,6->9,4->14,4->14,5->15,5->15,6->17,6->17,5->20,5->20,4->22,4->22,7->21,7->21,8->10,8')
        bot = self.get_debug_render_bot(simHost, general.player)

        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=100)
        self.assertIsNone(winner)

    def test_should_find_kill_in_ffa_position(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_kill_in_ffa_position___eW64nZ8rZ---2--69.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 69, fill_out_tiles=True)
        enemyGeneral.army = 10

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=69)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertEqual(general.player, enemyGeneral.player, 'should have captured fincher')

    # 0f 2p
    def test_should_not_time_out_on_win_condition_in_ffa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_time_out_on_win_condition_in_ffa___uu_dzfs6v---1--1275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1275, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1275)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '17,21->18,21->18,17->20,17->20,6->18,6->18,4->20,4->20,0->21,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=35)
        self.assertIsNone(winner)

    def test_should_gather_for_large_attacks_out_of_vision_range_in_rounds(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_for_large_attacks_out_of_vision_range_in_rounds___EklipZ_ai-SUlNa6E3r---7--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        bot.timings = None
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=15)
        # 12 moves minimum to gather out of vision
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(1, playerMap.GetTile(23, 15).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22,15).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22,16).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22, 17).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22, 18).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 17).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 18).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 20).army, 'should have gathered everything')
        self.assertEqual(15, playerMap.players[general.player].tileCount, "should not have captured land")


    def test_should_not_attack_unprovoked_enemies_in_early_ffa(self):
        """
        Live repro: Human.exe-ffa-2026-11-13_04-17-56---IPhAP7nUw turn 45.
        Multiple enemy players were revealed early (c and g border us, others in fog),
        nobody had attacked us, yet the bot captured player d's tile at 10,19 on t47
        while nominally targeting g. When multiple enemies are revealed in a
        non-dominant FFA and nobody is attacking us, we must refuse to attack any of them.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_attack_unprovoked_ffa_players___IPhAP7nUw---0--45.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 45, fill_out_tiles=True)

        # Arm our frontier so captures into revealed enemy land are immediately
        # available: player c owns 6,11 / 6,12 and player g owns 15,15. Without the
        # fix the bot eats them opportunistically within a few turns.
        # Keep each tile at exactly 3 (enough to take the adjacent 1-army enemy
        # tiles): inflating our total score too far flips
        # is_still_ffa_and_non_dominant to dominant, which legitimately disables
        # the pacifism gate. In the live game our score was ~equal to everyone.
        map.GetTile(7, 11).army = 3
        map.GetTile(7, 12).army = 3
        map.GetTile(7, 13).army = 3
        map.GetTile(14, 16).army = 3

        ownersBefore = [t.player for t in map.tiles_by_index]

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=45)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        violations = []
        for t in map.tiles_by_index:
            oldOwner = ownersBefore[t.tile_index]
            if oldOwner >= 0 and oldOwner != general.player and t.player == general.player:
                violations.append((t.x, t.y, oldOwner))
        self.assertEqual([], violations, 'unprovoked FFA bot must not capture tiles of players that are not attacking us')

        # player.tileCount / player.tiles are not maintained on the sim ground-truth
        # map; count live ownership through tiles_by_index instead.
        ourTileCount = sum(1 for t in map.tiles_by_index if t.player == general.player)
        self.assertGreater(ourTileCount, 20, 'bot should still be expanding into neutral land')

    def test_should_exclusively_attack_player_that_attacks_us_in_early_ffa(self):
        """
        Same live repro state. When an enemy player attacks us in a non-dominant FFA
        with multiple revealed enemies, we must lock onto that player exclusively and
        must not take tiles owned by any other player.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_attack_unprovoked_ffa_players___IPhAP7nUw---0--45.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 45, fill_out_tiles=True)

        # player 2 (c) borders us at 6,11 / 6,12. Beef it up so its queued attack
        # can actually overrun a big chunk of our territory and cross the
        # aggression_factor > 120 provocation threshold.
        map.GetTile(6, 11).army = 45
        map.GetTile(6, 12).army = 45

        ownersBefore = [t.player for t in map.tiles_by_index]

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=45)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(
            enemyGeneral.player,
            '6,11->7,11->7,12->7,13->7,14->7,15->6,15->6,16->5,16->4,16  6,12->7,12->7,13->7,14->8,14->8,15->9,15->10,15->10,16->11,16->12,16->13,16->14,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=40)

        self.assertGreater(playerMap.players[enemyGeneral.player].aggression_factor, 0, 'player c overran our territory and should be flagged as the aggressor')
        self.assertEqual(enemyGeneral.player, bot.targetPlayer, 'the player attacking us must become our exclusive target')

        violations = []
        for t in map.tiles_by_index:
            oldOwner = ownersBefore[t.tile_index]
            if oldOwner >= 0 and oldOwner != general.player and oldOwner != enemyGeneral.player and t.player == general.player:
                violations.append((t.x, t.y, oldOwner))
        self.assertEqual([], violations, 'after locking onto the aggressor we must not capture tiles of other players')

    def test_should_not_ffg_forever(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_ffg_forever___ZEaJK2oWZ---2--359.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 359, fill_out_tiles=False)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=359)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=25)
        self.assertNoFriendliesKilled(map, general)
