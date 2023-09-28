import logging

import SearchUtils
from Directives import Timings
from Path import Path
from SearchUtils import Counter
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile, MapBase


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
                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=242)
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=406)
        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, playerMapVision=rawMap, player_with_viewer=general.player)
        # alert both players of each others general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=150)

    def test_going_all_in_on_army_advantage_should_gather_at_the_opp_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general___HgFB_1ohh---b--242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=242)

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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=238)

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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)

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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=143)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.sim.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=30)

        self.assertIsNone(winner)
        # should have captured tiles.
        self.assertGreater(simHost.sim.players[general.player].map.players[general.player].tileCount, 75)

    def test_kill_path__should_intercept_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_scrim_against_incoming_army__turn_241.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=241)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)
    
    def test_when_all_in_with_large_tile_should_keep_attacking_effectively(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/when_all_in_with_large_tile_should_keep_attacking_effectively___rgKAG2M6n---b--299.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 299, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=299)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=30)
        self.assertEqual(map.player_index, winner)
    
    def test_should_intercept_and_kill_threats_before_exploring_or_expanding(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_and_kill_threats_before_exploring_or_expanding___SebV_WNpn---b--288.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 288, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=288)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_panic_gather_and_complete_the_general_search_kill(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_panic_gather_and_complete_the_general_search_kill___SgBVnDtph---b--893.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 893, fill_out_tiles=True)
        genPlayer = general.player

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=893)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
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
                rawMap, _ = self.load_map_and_general(mapName, respect_undiscovered=True, turn=turn)

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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=78)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=516)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=300)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=437)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=330)

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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=583)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=350)

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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=108)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=456)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=284)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=278)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=204)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=326)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=326)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,9->14,9->14,10')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=3)
        self.assertIsNone(winner)

    
    def test_should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile(self):
        for moveCombo in ['16,7->16,6->17,6', '16,7->17,7->17,6']:
            with self.subTest(moveCombo=moveCombo):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_not_dodge_off_general_into_death_with_depth_2_kill_on_danger_tile___qA8EaWOHA---0--204.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 204, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=204)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, moveCombo)

                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=3)
                self.assertIsNone(winner)

    def test_shouldnt_loop_killing_gen_adjacent_vision_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_loop_killing_gen_adjacent_vision_army___JLO-6iSbd---1--290.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 290, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=290)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,4->3,5->3,4->3,5->3,4->3,5->3,4->3,5->3,4->3,5')
        simHost.sim.ignore_illegal_moves = True

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=20)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, repetitionPlayer=general.player, minForRepetition=2)
    
    def test_should_not_repetition_killing_danger_tile_part2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_repetition_killing_danger_tile_part2___JLO-6iSbd---1--301.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 301, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=301)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, repetitionPlayer=general.player)
    
    def test_should_gather_in_this_position__not_expand_or_take_neut_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_in_this_position__not_expand_or_take_neut_city___W1-GU94LD---0--423.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 423, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=423)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,1->11,1->10,1->9,1->8,1->7,1->6,1->5,1->5,2->4,2->4,3->3,3->3,4->2,4->2,5->2,6->2,7->2,8->3,8')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=21)
        self.assertIsNone(winner)
    
    def test_should_not_loop_trying_to_take_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_loop_trying_to_take_city___og1Mc5U9k---1--282.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 282, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=282)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost)
    
    def test_should_spend_nearly_full_cycle_gathering_out_of_play_armies(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_spend_nearly_full_cycle_gathering_out_of_play_armies___Nw5bXrfqz---0--102.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 102, fill_out_tiles=True, respect_player_vision=True)
        for x in range(5, 15):
            y = 6
            tile = map.GetTile(x, y)
            tile.army = 0
            tile.player = -1
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 2, 2)

        def update_player(t: Tile):
            t.player = enemyGeneral.player
            t.army = 2

        SearchUtils.breadth_first_foreach(map, [enemyGeneral], 3, update_player)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=102)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)
        bot.targetPlayerExpectedGeneralLocation = self.get_player_tile(14, 5, simHost.sim, general.player)
        bot.armyTracker.emergenceLocationMap = [[[0 for y in range(map.rows)] for x in range(map.cols)] for p in map.players]
        bot.timings = Timings(50, 5, 20, 31, 0, 0, disallowEnemyGather=False)
        bot.behavior_out_of_play_defense_threshold = 0.3

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.7, turns=75)
        self.assertIsNone(winner)

        sumArmyNear = bot.sum_player_army_near_or_on_tiles(bot.shortest_path_to_target_player.tileList, distance=3)
        self.assertGreater(sumArmyNear, 60)
    
    def test_should_not_leave_large_tile_in_middle_of_territory__should_continue_attack__dies_to_completely_inefficient_flank_all_the_way_around_right_side_due_to_sitting_on_71_in_middle(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_leave_large_tile_in_middle___tcponLahM---1--284.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 284, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=284)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_leave_large_tile_in_middle_of_territory__should_continue_attack__dies_to_completely_inefficient_flank_all_the_way_around_right_side_due_to_sitting_on_71_in_middle
    
    def test_should_treat_edge_flanks_as_danger_potential_and_tendril_outwards(self):
        # See test above this one,
        #  test_should_not_leave_large_tile_in_middle_of_territory__should_continue_attack__dies_to_completely_inefficient_flank_all_the_way_around_right_side_due_to_sitting_on_71_in_middle
        #  same map file.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_treat_edge_flanks_as_danger_potential_and_tendril_outwards___tcponLahM---1--284.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 284, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=284)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_treat_edge_flanks_as_danger_potential_and_tendril_outwards
    
    def test_should_not_go_hunting_in_stupid_scenarios_while_quick_kill_gathering(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_go_hunting_in_stupid_scenarios_while_quick_kill_gathering___Jaq8EdMtO---0--180.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 180, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=180)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)
        bot.all_in_army_advantage = True
        bot.all_in_army_advantage_counter = 33
        bot.all_in_army_advantage_cycle = 75

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertEqual(general.player, winner)

    def test_should_not_dodge_off_general_and_die(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dodge_off_general_and_die___LpxIND79i---1--215.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 215, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=215)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,13->9,13->9,14')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_gather_from_out_of_play_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_from_out_of_play_tiles___sN_jR1oaU---0--200.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 200, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=200)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_gather_from_out_of_play_tiles
    
    def test_should_not_expand_past_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_expand_past_threat___D4vFUocUu---1--130.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 130, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=130)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,11->9,11->10,11->11,11->12,11')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=5)
        self.assertIsNone(winner)
        shouldNotBeEnemy = self.get_player_tile(12, 11, simHost.sim, general.player)
        self.assertEqual(general.player, shouldNotBeEnemy.player)
    
    def test_should_enter_rapid_city_expansion_massive_map_mode(self):
        # Bot should see that it has lots of army advantage and lots of available cities and enemy general has not
        # explored its space, and it should convert the army into all neutral cities available to it immediately.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_enter_rapid_city_expansion_massive_map_mode___-zS5mB7xt---3--444.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 444, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=444)
        
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=False)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=100)
        self.assertIsNone(winner)
        player_map = simHost.get_player_map(general.player)
        self.assertGreater(player_map.players[general.player].cityCount, 12)
    
    def test_should_leave_200_army_near_general_as_anti_fog_abuse_in_winning_game(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_leave_200_army_near_general_as_anti_fog_abuse_in_winning_game___7V34R1hBO---0--500.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 500, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=500)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=100)
        self.assertIsNone(winner)

        playerArmyNear = bot.sum_player_army_near_or_on_tiles([general], distance=6, player=general.player),
        self.assertGreater(playerArmyNear, 190)
    
    def test_should_not_failed_defense_altKingKillPath_unnecessarily(self):
        # TODO gather defense isn't gathering towards the skinniest part of the shortest pathway tileset, and
        #  the result is inconsistent defensive gather predictions when the attack doesn't take the anticipated path.
        #  gathering to the closest tiles to the threat, or to the skinniest tiles in the threat pathway would result
        #  in much more consistent gathers.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_failed_defense_altKingKillPath_unnecessarily___tFjnTXPts---0--377.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 377, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=377)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,11->11,12->10,12->9,12->8,12->7,12->7,13->6,13->6,14->5,14->5,15->5,16->4,16->3,16->2,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=20)
        self.assertIsNone(winner)
    
    def test_should_all_in_enemy_general_since_no_meaningful_defense(self):
        # exploration is a bit random, run the test a bunch to make sure its consistent.
        for i in range(10):
            with self.subTest(i=i):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
                mapFile = 'GameContinuationEntries/should_all_in_enemy_general_since_no_meaningful_defense___SRrkSRhku---0--187.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 187, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, 15, 0)
                enemyGeneral.army = 4

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=187)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '14,13->13,13->12,13  None  12,13->11,13->10,13->9,13  None  9,13->8,13->8,12->8,11->8,10->8,11->9,11')
                bot = simHost.get_bot(general.player)
                bot.armyTracker.new_army_emerged(bot._map.GetTile(14, 4), 40)
                # SPECIFICALLY NOT REVEALED, BOT SHOULD KNOW IT HAS AN EXPLORATION RACE
                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                genPlayer = general.player
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=14)
                self.assertEqual(genPlayer, winner)
    
    def test_should_contest_cities_when_all_in_gathering_at_opp(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_contest_cities_when_all_in_gathering_at_opp___n35SxPk5n---0--235.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 235, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 5, 10)
        enemyGeneral.army = 35

        # self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=235)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        bot = simHost.get_bot(general.player)
        bot.finishing_exploration = True
        bot.all_in_army_advantage = True
        bot.all_in_army_advantage_counter = 15
        bot.all_in_army_advantage_cycle = 50
        bot.armyTracker.new_army_emerged(bot._map.GetTile(8, 12), 50)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=3)
        self.assertIsNone(winner)
        city = self.get_player_tile(7, 10, simHost.sim, general.player)
        self.assertGreater(city.army, 30, 'should not abandon contested city when contesting it guarantees an army+economy win condition.')
    
    def test_should_rapid_city_expand_in_unexplored_ffa_situation(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_rapid_city_expand_in_unexplored_ffa_situation___pt9T7lYGI---1--370.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 370, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 4, 20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=370)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        genMap = simHost.get_player_map(general.player)
        genPlayer = genMap.players[general.player]
        targPlayer = genMap.players[enemyGeneral.player]
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=150)
        self.assertIsNone(winner)

        cityDiff = genPlayer.cityCount - targPlayer.cityCount

        self.assertGreater(cityDiff, 7, 'should switch to rapid city expand mode because no player aggression')

    def test_should_stop_rapid_expanding_when_attacked_in_unexplored_ffa_situation(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_rapid_city_expand_in_unexplored_ffa_situation___pt9T7lYGI---1--370.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 370, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 4, 20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=370)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        bBot = simHost.get_bot(enemyGeneral.player)
        bBot.all_in_counter = 200
        bBot.allIn = True
        # 50 turns to rapid expand before other player starts attacking. Other bot will gather for ~50 turns

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        aBot = simHost.get_bot(general.player)
        # make it so A doesn't know B knows its gen location. Just telling b its gen location to trigger aggression from B, not actually relevant to the test.
        aBot._map.players[enemyGeneral.player].knowsKingLocation = False

        self.begin_capturing_logging()
        genMap = simHost.get_player_map(general.player)
        genPlayer = genMap.players[general.player]
        targPlayer = genMap.players[enemyGeneral.player]

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=150)
        if winner is not None:
            self.assertEqual(genPlayer.index, winner)

        cityDiff = genPlayer.cityCount - targPlayer.cityCount

        self.assertGreater(cityDiff, 4, 'should have taken at least some cities before switching gears to defense')
        self.assertLess(cityDiff, 9, 'should not have kept up the rapid city taking once dominating econ and under attack')
