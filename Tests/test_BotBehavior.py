import logging

import SearchUtils
from Path import Path
from SearchUtils import Counter
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile


class BotBehaviorTests(TestBase):
    
    def test_should_continue_gathering_due_to_out_of_play_area_tiles(self):
        debugMode = TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_gathering_due_to_out_of_play_area_tiles_Bgb_HS_h2---b--264.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 264, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.sim.players[enemyGeneral.player].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
        simHost.sim.players[general.player].map.update_visible_tile(enemyGeneral.x, enemyGeneral.y, enemyGeneral.player, enemyGeneral.army, is_city=False, is_general=True)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=60)

        # TODO TEST, bot died because it executed a short gather timing cycle and left all its army on the left of the map expanding

    def test_army_tracker_should_not_keep_seeing_city_as_moving_back_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/army_tracker_should_not_keep_seeing_city_as_moving_back_into_fog___SxnQ2Hun2---b--413.txtmap'
        for afk in [True, False]:
            with self.subTest(afk=afk):
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 413, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                # simHost = GameSimulatorHost(map)
                rawMap, _ = self.load_map_and_general(mapFile, 242)
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=afk)
                # alert both players of each others general
                simHost.sim.players[enemyGeneral.player].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
                simHost.sim.players[general.player].map.update_visible_tile(enemyGeneral.x, enemyGeneral.y, enemyGeneral.player, enemyGeneral.army, is_city=False, is_general=True)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=50)
                self.assertIsNone(winner)
                self.assertNoRepetition(simHost, minForRepetition=2)

    def test_should_not_sit_there_and_die_when_enemy_army_around_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general___HgFB_1ohh---b--242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 242)

        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap)

        # alert enemy of the player general
        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        startTurn = simHost.sim.turn
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=80)
        logging.info(f'game over after {simHost.sim.turn - startTurn} turns')
        self.assertIsNotNone(winner)
        self.assertEqual(map.player_index, winner)

    def test_should_intercept_army_and_kill_incoming_before_it_does_damage(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_army_and_kill_incoming_before_it_does_damage___rliiLZ7ph---b--238.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 238, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 238)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.bot_hosts[general.player].eklipz_bot.next_scrimming_army_tile = self.get_player_tile(10, 13, simHost.sim, general.player)
        simHost.sim.ignore_illegal_moves = True
        # some of these will be illegal if the bot does its thing and properly kills the inbound army
        simHost.queue_player_moves_str(enemyGeneral.player, '12,12 -> 11,12 -> 10,12 -> 9,12 -> 8,12 -> 7,12')

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=3)
        self.assertIsNone(winner)
        self.assertPlayerTileCount(simHost, enemyGeneral.player, 66)
    
    def test_should_never_still_think_enemy_general_is_away_from_visible_enemy_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_never_still_think_enemy_general_is_away_from_visible_enemy_tile___Hg5aAap2n---a--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 50)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        self.begin_capturing_logging()
        bot = simHost.bot_hosts[general.player].eklipz_bot
        # should ABSOLUTELY think the enemy general is right around 12,6 in this situation
        self.assertLess(bot.distance_from_opp(map.GetTile(12, 16)), 3)
    
    def test_should_not_think_defending_economy_against_fog_player(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_think_defending_economy_against_fog_player___HltY61xph---b--143.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 143, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 143)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.sim.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=30)

        self.assertIsNone(winner)
        # should have captured tiles.
        self.assertGreater(simHost.sim.players[general.player].map.players[general.player].tileCount, 75)

    def test_kill_path__should_intercept_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_scrim_against_incoming_army__turn_241.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 241)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=10)
        self.assertIsNone(winner)
    
    def test_army_should_not_duplicate_backwards_on_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/army_should_not_duplicate_backwards_on_capture___Bgb7Eiba2---a--399.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 399, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 399)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=10)
        self.assertIsNone(winner)

        # TODO add asserts for army_should_not_duplicate_backwards_on_capture
    
    def test_when_all_in_with_large_tile_should_keep_attacking_effectively(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/when_all_in_with_large_tile_should_keep_attacking_effectively___rgKAG2M6n---b--299.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 299, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 299)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=25)
        self.assertEqual(map.player_index, winner)
    
    def test_should_intercept_and_kill_threats_before_exploring_or_expanding(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_and_kill_threats_before_exploring_or_expanding___SebV_WNpn---b--288.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 288, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 288)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_intercept_and_kill_threats_before_exploring_or_expanding
    
    def test_should_intercept_army_and_not_loop_on_threatpath(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_army_and_not_loop_on_threatpath___SxxfQENp2---b--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 426)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_intercept_army_and_not_loop_on_threatpath
    
    def test_should_not_panic_gather_and_complete_the_general_search_kill(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_panic_gather_and_complete_the_general_search_kill___SgBVnDtph---b--893.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 893, fill_out_tiles=True)
        genPlayer = general.player

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 893)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,7->3,8->3,9->3,10->3,11->4,11->5,11->5,12')
        simHost.bot_hosts[enemyGeneral.player].eklipz_bot.allIn = True
        simHost.bot_hosts[enemyGeneral.player].eklipz_bot.all_in_counter = 200
        simHost.bot_hosts[general.player].eklipz_bot.armyTracker.emergenceLocationMap[enemyGeneral.player][0][3] = 150
        simHost.bot_hosts[general.player].eklipz_bot.armyTracker.emergenceLocationMap[enemyGeneral.player][0][8] = 100
        # simHost.bot_hosts[general.player].eklipz_bot.all_in_counter = 200

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        # simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=150)
        self.assertEqual(winner, genPlayer)
    
    def test_should_begin_killing_enemy_territory_nearby_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        cases = [
            ('GameContinuationEntries/should_begin_killing_enemy_territory_nearby_general__v2___HeTmhYF6h---b--450.txtmap', 450, 7),
            ('GameContinuationEntries/should_begin_killing_enemy_territory_nearby_general__v3___HeTmhYF6h---b--600.txtmap', 600, 9),
            ('GameContinuationEntries/should_begin_killing_enemy_territory_nearby_general___HeTmhYF6h---b--300.txtmap', 300, 5),
        ]
        for mapName, turn, requireCapturedTilesNearGen in cases:
            with self.subTest(mapName=mapName.split('/')[1], turn=turn):
                map, general, enemyGeneral = self.load_map_and_generals(mapName, turn, fill_out_tiles=True)
                enTiles = [
                    (8,15),
                    (8,16),
                    (8,14),
                    (9,16),
                    (10,15),
                    (10,16),
                    (10,17),
                ]

                for x, y in enTiles:
                    tile = map.GetTile(x, y)
                    tile.player = enemyGeneral.player
                    tile.army = 2

                self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapName, turn)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

                for x, y in enTiles:
                    simHost.sim.set_tile_vision(playerToRevealTo=general.player, x=x, y=y, hidden=True, undiscovered=True)

                # simHost.make_player_afk(enemyGeneral.player)

                # alert enemy of the player general
                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=50)
                self.assertIsNone(winner)
                # there will be 1 army bonus so the avg army will be at least 2.
                self.assertGatheredNear(simHost, general.player, x=15, y=12, radius=4, requiredAvgTileValue=3.0)
                self.assertCleanedUpTilesNear(simHost, general.player, x=9, y=14, radius=4, capturedWithinLastTurns=39, requireCountCapturedInWindow=requireCapturedTilesNearGen)
                self.assertNoRepetition(simHost, minForRepetition=1)
    
    def test_should_not_go_fog_diving_at_8_12__should_intercept_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_go_fog_diving_at_8_12__should_intercept_army___BlfAnK5ah---a--78.txtmap'
        map, general = self.load_map_and_general(mapFile, 78)
        enemyGeneral = map.GetTile(15, 3)
        enemyGeneral.isGeneral = True
        enemyGeneral.player = (general.player + 1) & 1
        self.ensure_player_tiles_and_scores(map, general, 25, 59, enemyGeneral=enemyGeneral, enemyGeneralTileCount=31, enemyGeneralTargetScore=59)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 78)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,11->4,10->3,10->2,10->1,10->1,11->1,12->1,13')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=6)
        self.assertIsNone(winner)
    
    def test_should_recapture_city_instantly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recapture_city_instantly___SxnWy0963---b--516.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 516, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 516)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)
        city = self.get_player_tile(16, 4, simHost.sim, map.player_index)
        self.assertEqual(map.player_index, city.player)
    
    def test_should_not_find_no_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_find_no_moves___SlmKICqa3---a--300.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 300, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 300)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        bot = simHost.get_bot(general.player)
        bot.targetPlayerExpectedGeneralLocation = self.get_player_tile(16, 20, simHost.sim, general.player)
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][16][20] = 200

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=50)
        self.assertIsNone(winner)

    def test_should_not_incorrectly_dive_enemy_king_in_repetition_with_not_enough_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_incorrectly_dive_enemy_king___Bxpq_9pa2---b--437.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 437, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 437)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=1)

    def test_should_not_keep_moving_back_to_general_and_take_the_fucking_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_the_fucking_city___SxwaZRG0h---b--330.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 330, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 330)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost)

    def test_should_plan_through_neutral_city_quick_kill_flank(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_plan_through_neutral_city_quick_kill_flank___BxU_GGgA3---a--583.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 583, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 583)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_plan_through_neutral_city_quick_kill_flank

    def test_should_not_make_silly_threat_killer_move__when_already_safe_4_8__5_8(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_back_into_fog_on_small_player_intersection___HeEzmHU03---0--350.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 350, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 350)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,9->5,8')
        move = simHost.get_bot(general.player).find_move()
        self.assertNotEqual(self.get_player_tile(5, 8, simHost.sim, general.player), move.dest)
    
    def test_should_complete_danger_tile_kill(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_complete_danger_tile_kill___Bgk8TIUR2---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 108)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=4)
        self.assertIsNone(winner)

        tile = self.get_player_tile(2, 12, simHost.sim, general.player)
        self.assertEqual(general.player, tile.player)
        self.assertNoRepetition(simHost)
    
    def test_should_not_failed_defense_king_kill_against_undisc_king_when_can_still_save(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_failed_defense_king_kill_against_undisc_king_when_can_still_save___HxJcBYIC3---1--456.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 456, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 456)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,9->13,9->14,9->14,8->15,8->15,7->16,7->16,6->16,5->15,5')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_immediately_stop_capturing_city_path_when_enemy_kill_threat_on_board(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_immediately_stop_capturing_city_path_when_enemy_kill_threat_on_board___7QbjJj-_e---1--284.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 284, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 284)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)
        bot.curPath = Path()
        bot.curPath.add_next(self.get_player_tile(14, 5, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(13, 5, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(13, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(12, 4, simHost.sim, general.player))
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->8,5->9,5->10,5->10,6->10,7->11,7->12,7->13,7->14,7->15,7->15,6->15,5->16,5')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_kill_enemy_with_long_path_because_enemy_doesnt_know_gen_location(self):
        """
        We expect because the enemy doesn't know the players general,
        and the player has the 21,19 tile that can add to the kill, we
        would expect the bot to dive the enemy general with the 21,19 tile.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_enemy_with_long_path_because_enemy_doesnt_know_gen_location___EKs6kvfAx---4--278.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 278, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 278)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        shouldKillEnemyGen = self.get_player_tile(24, 13, simHost.sim, general.player)
        simHost.queue_player_moves_str(shouldKillEnemyGen.player, '24,19->24,20->24,21->24,22->25,22->25,23->25,24->24,24->23,24->22,24->22,23->21,23')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=15)
        self.assertIsNone(winner)
        self.assertEqual(general.player, shouldKillEnemyGen.player)
    
    def test_should_kill_enemy_general_when_visible_and_clear_kill(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_enemy_general_when_visible_and_clear_kill___gt42fVaoA---1--204.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 204, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 204)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertEqual(general.player, winner)
    
    def test_should_defend_attack_and_then_gather_faraway_army_to_defend_king_instead_of_explore(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_attack_and_then_gather_faraway_army_to_defend_king_instead_of_explore___rEHnyqePg---5--326.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 326, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 326)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '21,16->21,15->21,14->21,13->21,12->21,11->22,11->22,10->23,10->23,9->23,8->23,7->23,6->23,5->23,4->23,3->23,2')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player, hidden=True)
        simHost.sim.set_tile_vision(general.player, 21, 16, undiscovered=True, hidden=True)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.525, turns=120)
        self.assertNotEqual(enemyGeneral.player, winner)
        expectGathered = [
            self.get_player_tile(2, 18, simHost.sim, general.player),
            self.get_player_tile(9, 25, simHost.sim, general.player),
            self.get_player_tile(11, 20, simHost.sim, general.player),
            self.get_player_tile(6, 16, simHost.sim, general.player),
            self.get_player_tile(6, 8, simHost.sim, general.player),
            self.get_player_tile(13, 3, simHost.sim, general.player),
        ]

        for tile in expectGathered:
            self.assertLess(tile.army, 50, f'should have gathered {str(tile)}, instead found {tile.army} army')

        bot = simHost.get_bot(general.player)
        armyNear = bot.sum_player_army_near_or_on_tiles(bot.target_player_gather_path.tileList, distance=4)
        self.assertGreater(armyNear, 350)

    def test_should_not_vacate_general_with_army_scrim(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_vacate_general_with_army_scrim___tsOrHo4fQ---3--326.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 326, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 326)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,9->14,9->14,10')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=3)
        self.assertIsNone(winner)

    
    def test_should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile___qA8EaWOHA---0--204.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 204, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 204)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile
    
    def test_should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile___---unk--.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, , fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, )
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile