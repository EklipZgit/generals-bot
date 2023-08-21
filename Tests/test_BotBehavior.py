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
        mapFile = 'GameContinuationEntries/army_tracker_should_not_keep_seeing_city_as_moving_back_into_fog___SxnQ2Hun2---b--413.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 413)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=-2)
        # alert both players of each others general
        simHost.sim.players[enemyGeneral.player].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
        simHost.sim.players[general.player].map.update_visible_tile(enemyGeneral.x, enemyGeneral.y, enemyGeneral.player, enemyGeneral.army, is_city=False, is_general=True)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=True, turn_time=0.5)
        # TODO fix fog increment shit
        # TODO ok its fixed, write asserts to verify it doesn't come back lol
        # TODO need 'make other player afk' option in sim host

    
    def test_should_not_sit_there_and_die_when_enemy_army_around_general(self):
        mapFile = 'GameContinuationEntries/should_not_sit_there_and_die_when_enemy_army_around_general___Sx5e6iFnh---b--406.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 406)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=True, turn_time=0.5)

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
