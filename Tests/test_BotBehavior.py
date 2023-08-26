import logging

from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class BotBehaviorTests(TestBase):
    
    def test_should_continue_gathering_due_to_out_of_play_area_tiles(self):
        mapFile = 'GameContinuationEntries/should_continue_gathering_due_to_out_of_play_area_tiles_Bgb_HS_h2---b--264.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 264)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.sim.players[enemyGeneral.player].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
        simHost.sim.players[general.player].map.update_visible_tile(enemyGeneral.x, enemyGeneral.y, enemyGeneral.player, enemyGeneral.army, is_city=False, is_general=True)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=True, turn_time=0.5)

        # TODO TEST, bot died because it executed a short gather timing cycle and left all its army on the left of the map expanding

    
    def test_army_tracker_should_not_keep_seeing_city_as_moving_back_into_fog(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/army_tracker_should_not_keep_seeing_city_as_moving_back_into_fog___SxnQ2Hun2---b--413.txtmap'
        for afk in [True, False]:
            with self.subTest(afk=afk):
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 413)

                self.enable_search_time_limits_and_disable_debug_asserts()

                # simHost = GameSimulatorHost(map)
                rawMap, _ = self.load_map_and_general(mapFile, 242)
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptViewer=afk)
                # alert both players of each others general
                simHost.sim.players[enemyGeneral.player].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
                simHost.sim.players[general.player].map.update_visible_tile(enemyGeneral.x, enemyGeneral.y, enemyGeneral.player, enemyGeneral.army, is_city=False, is_general=True)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=100)
                self.assertIsNone(winner)

    
    def test_should_not_sit_there_and_die_when_enemy_army_around_general(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_not_sit_there_and_die_when_enemy_army_around_general___Sx5e6iFnh---b--406.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 406, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 406)
        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, playerMapVision=rawMap, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=150)

    def test_going_all_in_on_army_advantage_should_gather_at_the_opp_general(self):
        debugMode = False
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general___HgFB_1ohh---b--242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 242)

        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        startTurn = simHost.sim.turn
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=80)
        logging.info(f'game over after {simHost.sim.turn - startTurn} turns')
        self.assertIsNotNone(winner)
        self.assertEqual(general.player, winner)

    def test_should_intercept_army_and_kill_incoming_before_it_does_damage(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_intercept_army_and_kill_incoming_before_it_does_damage___rliiLZ7ph---b--238.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 238, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 238)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptViewer=True)
        simHost.bot_hosts[general.player].eklipz_bot.next_scrimming_army_tile = self.get_player_tile(10, 13, simHost.sim, general.player)
        simHost.sim.ignore_illegal_moves = True
        # some of these will be illegal if the bot does its thing and properly kills the inbound army
        simHost.queue_player_moves_str(enemyGeneral.player, '12,12 -> 11,12 -> 10,12 -> 9,12 -> 8,12 -> 7,12')

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=3)
        self.assertIsNone(winner)
        self.assertPlayerTileCount(simHost, enemyGeneral.player, 66)
    
    def test_should_never_still_think_enemy_general_is_away_from_visible_enemy_tile(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_never_still_think_enemy_general_is_away_from_visible_enemy_tile___Hg5aAap2n---a--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 50)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        self.begin_capturing_logging()
        bot = simHost.bot_hosts[general.player].eklipz_bot
        # should ABSOLUTELY think the enemy general is right around 12,6 in this situation
        self.assertLess(bot.distance_from_opp(map.GetTile(12, 16)), 3)
    
    def test_should_not_think_defending_economy_against_fog_player(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_not_think_defending_economy_against_fog_player___HltY61xph---b--143.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 143)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 143)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.sim.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=2.0)

        # TODO add asserts for should_not_think_defending_economy_against_fog_player

    def test_kill_path__should_intercept_path(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_scrim_against_incoming_army__turn_241.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 241)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=15.0, turns=10)

        # simHost.bot_hosts[enemyGeneral.player].make_move()

        # TODO add asserts for test_kill_path__should_intercept_path
    
    def test_army_should_not_duplicate_backwards_on_capture(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/army_should_not_duplicate_backwards_on_capture___Bgb7Eiba2---a--399.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 399)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 399)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=10)
        self.assertIsNone(winner)

        # TODO add asserts for army_should_not_duplicate_backwards_on_capture
    
    def test_when_all_in_with_large_tile_should_keep_attacking_effectively(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/when_all_in_with_large_tile_should_keep_attacking_effectively___rgKAG2M6n---b--299.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 299)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 299)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for when_all_in_with_large_tile_should_keep_attacking_effectively
    
    def test_should_intercept_and_kill_threats_before_exploring_or_expanding(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_intercept_and_kill_threats_before_exploring_or_expanding___SebV_WNpn---b--288.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 288)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 288)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_intercept_and_kill_threats_before_exploring_or_expanding
    
    def test_should_intercept_army_and_not_loop_on_threatpath(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_intercept_army_and_not_loop_on_threatpath___SxxfQENp2---b--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 426)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_intercept_army_and_not_loop_on_threatpath
