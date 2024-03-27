import logbook

import SearchUtils
from Directives import Timings
from MapMatrix import MapMatrix
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile, MapBase, TILE_FOG


class BotBehaviorTests(TestBase):
    
    def test_should_continue_gathering_due_to_out_of_play_area_tiles(self):
        debugMode = TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_gathering_due_to_out_of_play_area_tiles_Bgb_HS_h2---b--264.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 264, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # simHost = GameSimulatorHost(map)
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
        # alert both players of each others general
        simHost.sim.players[enemyGeneral.player].map.update_visible_tile(general.x, general.y, general.player, general.army, is_city=False, is_general=True)
        simHost.sim.players[general.player].map.update_visible_tile(enemyGeneral.x, enemyGeneral.y, enemyGeneral.player, enemyGeneral.army, is_city=False, is_general=True)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=30)

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
                self.assertNoRepetition(simHost, minForRepetition=4)

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

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        bot = self.get_debug_render_bot(simHost)

        bot.is_all_in_army_advantage = True

        # alert enemy of the player general
        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        startTurn = simHost.sim.turn
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=80)
        logbook.info(f'game over after {simHost.sim.turn - startTurn} turns')
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
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=30)

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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=30)
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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_intercept_and_kill_threats_before_exploring_or_expanding")
    
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

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
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
        simHost.bot_hosts[enemyGeneral.player].eklipz_bot.is_all_in_losing = True
        simHost.bot_hosts[enemyGeneral.player].eklipz_bot.all_in_losing_counter = 200
        simHost.bot_hosts[general.player].eklipz_bot.armyTracker.emergenceLocationMap[enemyGeneral.player][rawMap.GetTile(0, 3)] = 150
        simHost.bot_hosts[general.player].eklipz_bot.armyTracker.emergenceLocationMap[enemyGeneral.player][rawMap.GetTile(0, 8)] = 100
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
                self.assertGatheredNear(simHost, general.player, x=15, y=12, radius=4, requiredAvgTileValue=3.3)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
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
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.targetPlayerExpectedGeneralLocation = self.get_player_tile(16, 20, simHost.sim, general.player)
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][rawMap.GetTile(16, 20)] = 200

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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_plan_through_neutral_city_quick_kill_flank")

    def test_should_not_make_silly_threat_killer_move__when_already_safe_4_8__5_8(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_back_into_fog_on_small_player_intersection___HeEzmHU03---0--350.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 350, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=350)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,9->5,8')
        move = self.get_debug_render_bot(simHost, general.player).find_move()
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=4)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)
    
    def test_should_immediately_stop_capturing_city_path_when_enemy_kill_threat_on_board(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_immediately_stop_capturing_city_path_when_enemy_kill_threat_on_board___7QbjJj-_e---1--284.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 284, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=284)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.curPath = Path()
        bot.curPath.add_next(self.get_player_tile(14, 5, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(13, 5, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(13, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(12, 4, simHost.sim, general.player))
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->8,5->9,5->10,5->10,6->10,7->11,7->12,7->13,7->14,7->15,7->15,6->15,5->16,5')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
        self.assertEqual(map.player_index, winner)
    
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

        bot = self.get_debug_render_bot(simHost, general.player)
        armyNear = bot.sum_player_standing_army_near_or_on_tiles(bot.target_player_gather_path.tileList, distance=4)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=3)
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
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=3)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=20)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=21)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
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
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.targetPlayerExpectedGeneralLocation = self.get_player_tile(14, 5, simHost.sim, general.player)
        bot.armyTracker.emergenceLocationMap = [MapMatrix(rawMap, 0) for p in map.players]
        bot.timings = Timings(50, 5, 20, 31, 0, 0, disallowEnemyGather=False)
        bot.behavior_out_of_play_defense_threshold = 0.3

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.7, turns=75)
        self.assertIsNone(winner)

        sumArmyNear = bot.sum_player_standing_army_near_or_on_tiles(bot.shortest_path_to_target_player.tileList, distance=3)
        self.assertGreater(sumArmyNear, 60)

    def test_set_all_in_to_hit_with_timings(self):
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
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.targetPlayerExpectedGeneralLocation = self.get_player_tile(14, 5, simHost.sim, general.player)
        bot.armyTracker.emergenceLocationMap = [MapMatrix(rawMap, 0) for p in map.players]
        bot.timings = Timings(50, 5, 20, 31, 0, 0, disallowEnemyGather=False)
        bot.behavior_out_of_play_defense_threshold = 0.3

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=75)
        self.assertIsNone(winner)

        sumArmyNear = bot.sum_player_standing_army_near_or_on_tiles(bot.shortest_path_to_target_player.tileList, distance=3)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_leave_large_tile_in_middle_of_territory__should_continue_attack__dies_to_completely_inefficient_flank_all_the_way_around_right_side_due_to_sitting_on_71_in_middle")
    
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_treat_edge_flanks_as_danger_potential_and_tendril_outwards")
    
    def test_should_not_go_hunting_in_stupid_scenarios_while_quick_kill_gathering(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_go_hunting_in_stupid_scenarios_while_quick_kill_gathering___Jaq8EdMtO---0--180.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 180, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=180)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.all_in_army_advantage_counter = 33
        bot.all_in_army_advantage_cycle = 75

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertEqual(map.player_index, winner)

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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_gather_from_out_of_play_tiles")
    
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
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
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
        bot = self.get_debug_render_bot(simHost, general.player)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=100)
        self.assertIsNone(winner)

        playerArmyNearAmt = bot.sum_player_standing_army_near_or_on_tiles([general], distance=6, player=general.player)
        self.assertGreater(playerArmyNearAmt, 190)
    
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
                bot = self.get_debug_render_bot(simHost, general.player)
                bot.armyTracker.new_army_emerged(bot._map.GetTile(14, 4), 40)
                # SPECIFICALLY NOT REVEALED, BOT SHOULD KNOW IT HAS AN EXPLORATION RACE
                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                genPlayer = general.player
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=14)
                self.assertEqual(genPlayer, winner)
    
    def test_should_contest_cities_when_all_in_gathering_at_opp(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_cities_when_all_in_gathering_at_opp___n35SxPk5n---0--235.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 235, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 5, 10)
        enemyGeneral.army = 35

        # self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=235)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.finishing_exploration = True
        bot.is_all_in_army_advantage = True
        bot.all_in_army_advantage_counter = 15
        bot.all_in_army_advantage_cycle = 50
        bot.armyTracker.new_army_emerged(bot._map.GetTile(8, 12), 50)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=3)
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
        bBot.all_in_losing_counter = 200
        bBot.is_all_in_losing = True
        # 50 turns to rapid expand before other player starts attacking. Other bot will gather for ~50 turns

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        bot = self.get_debug_render_bot(simHost, general.player)
        # make it so A doesn't know B knows its gen location. Just telling b its gen location to trigger aggression from B, not actually relevant to the test.
        bot._map.players[enemyGeneral.player].knowsKingLocation = False

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
    
    def test_should_expand_effectively(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_19_years_to_make_move___HN1IDtUZ4---1--54.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 54, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=54)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=46)
        self.assertIsNone(winner)
        genMap = simHost.get_player_map(general.player)
        self.assertGreater(genMap.players[general.player].tileCount, 50)  # actually can probably capture more than 50...?
    
    def test_should_all_in_general_when_contested_cities_out_of_position_and_knows_no_army_on_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_general_when_contested_cities_out_of_position_and_knows_no_army_on_general___z1yhdwnBO---0--327.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 327, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=327)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_all_in_general_when_contested_cities_out_of_position_and_knows_no_army_on_general")
    
    def test_should_not_try_to_trade_when_not_sure_of_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_try_to_trade_when_not_sure_of_general_location___2WlVf4R5G---0--182.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 182, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=182)

        self.enable_search_time_limits_and_disable_debug_asserts()
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        self.set_general_emergence_around(4, 4, simHost, general.player, enemyGeneral.player)

        simHost.queue_player_moves_str(enemyGeneral.player, '2,8->2,9->2,10->2,11->3,11->4,11->4,12->5,12->6,12->7,12->7,13->8,13->8,14->8,15->9,15->10,15')
        simHost.queue_player_moves_str(general.player, '6,9->5,9')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_fail_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_fail_defense___B3wF_LC3Y---4--599.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 599, fill_out_tiles=True)

        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 23, 6)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=599)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        self.set_general_emergence_around(17, 1, simHost, general.player, enemyGeneral.player)

        simHost.queue_player_moves_str(enemyGeneral.player, '12,8->12,9->12,10->12,11->12,12->12,13->11,13->11,14->11,15->11,16->11,17->11,18->11,19->12,19->12,20->12,21->12,22->12,23->12,24->11,24')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=25)
        self.assertIsNone(winner)
    
    def test_should_prioritize_attack_paths_through_indirect_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prioritize_attack_paths_through_indirect_fog___qEDoraK55---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 17, 18)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        self.set_general_emergence_around(14, 18, simHost, general.player, enemyGeneral.player, emergenceAmt=40)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = None
        bot.recalculate_player_paths(force=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=30)
        self.assertIsNone(winner)
        self.assertIn(bot._map.GetTile(17, 11), bot.target_player_gather_path.tileSet)
        self.assertIn(bot._map.GetTile(17, 12), bot.target_player_gather_path.tileSet)
        self.assertIn(bot._map.GetTile(17, 13), bot.target_player_gather_path.tileSet)
        self.assertGreater(simHost.get_player_map(general.player).players[general.player].tileCount, 50)
    
    def test_should_prepare_for_flanks_the_way_humans_would_plan_them(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prepare_for_flanks_the_way_humans_would_plan_them___tXhUT4E-o---0--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        self.set_general_emergence_around(14, 11, simHost, general.player, enemyGeneral.player, 10)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = None
        # simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=30)
        self.assertIsNone(winner)

        tiles = [
            self.get_player_tile(5, 19, simHost.sim, general.player),
            self.get_player_tile(6, 19, simHost.sim, general.player),
            self.get_player_tile(7, 19, simHost.sim, general.player),
            self.get_player_tile(8, 19, simHost.sim, general.player),
        ]

        for tile in tiles:
            self.assertEqual(general.player, tile.player, "should have gathered to the most obvious human flank path with the most visionless tiles.")
    
    def test_should_continue_attack_over_switching_to_econ_defense_over_large_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_attack_over_switching_to_econ_defense_over_large_tile___SgzO3laga---0--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)
        
        # self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        # self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.5, turns=15)
        self.assertIsNone(winner)

        pMap = simHost.get_player_map(general.player)
        self.assertGreater(pMap.players[general.player].tileCount, 84, "should have captured tiles instead of getting weird and defensive.")
    
    def test_should_not_run_army_away_from_threat_slash_city_gather_stupidly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_run_army_away_from_threat_slash_city_gather_stupidly___FUmJfZrMo---1--440.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 440, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 19, 0)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=440)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        cityA = self.get_player_tile(10, 17, simHost.sim, general.player)
        cityB = self.get_player_tile(11, 16, simHost.sim, general.player)

        self.assertEqual(general.player, cityA.player)
        self.assertEqual(general.player, cityB.player)
    
    def test_should_not_switch_to_all_in_and_time_with_cycle_appropriately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for turn, expectCityTaken in [(199, True), (179, False)]:
            with self.subTest(turn=turn):
                mapFile = 'GameContinuationEntries/should_switch_to_all_in_and_time_with_cycle_appropriately___zXtNQLyfR---1--179.txtmap'
                # has enough army to take city in this variation in both cases
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)
                self.move_enemy_general(map, enemyGeneral, 16, 1)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                self.set_general_emergence_around(13, 5, simHost, general.player, enemyGeneral.player, 8)
                bot = self.get_debug_render_bot(simHost, general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=21)
                self.assertIsNone(winner)

                self.assertNoRepetition(simHost, minForRepetition=2)
                city = self.get_player_tile(15, 12, simHost.sim, general.player)
                if expectCityTaken:
                    self.assertEqual(general.player, city.player)
                else:
                    self.assertGreater(bot._map.players[general.player].tileCount, 65)
                    self.assertEqual(-1, city.player)

                self.assertFalse(bot.is_all_in())

    def test_should_switch_to_all_in_and_time_with_cycle_appropriately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for turn, shouldAllIn, moveEnemyCity, runForTurns in [(200, True, True, 25), (200, True, False, 15), (200, False, True, 10), (225, True, True, 25), (225, True, False, 15), (179, False, True, 15)]:
            with self.subTest(turn=turn, moveEnemyCity=moveEnemyCity):
                mapFile = 'GameContinuationEntries/should_switch_to_all_in_and_time_with_cycle_appropriately___zXtNQLyfR---1--179.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)
                cityToRemove = map.GetTile(15, 12)
                map.convert_tile_to_mountain(cityToRemove)
                enCity = map.GetTile(14, 5)

                if moveEnemyCity:
                    map.convert_tile_to_mountain(enCity)
                    map.players[enemyGeneral.player].cities.remove(enCity)
                    newEnCity = map.GetTile(8, 0)
                    newEnCity.tile = enemyGeneral.player
                    newEnCity.isMountain = False
                    newEnCity.isCity = True
                    newEnCity.army = 2
                    newEnCity.player = enemyGeneral.player
                    enCity = newEnCity
                    map.players[enemyGeneral.player].cities.append(enCity)

                self.move_enemy_general(map, enemyGeneral, 18, 0)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)
                rawMap.convert_tile_to_mountain(rawMap.GetTile(15, 12))

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                self.set_general_emergence_around(13, 5, simHost, general.player, enemyGeneral.player, 12)
                bot = self.get_debug_render_bot(simHost, general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=runForTurns)
                self.assertIsNone(winner)

                city = self.get_player_tile(enCity.x, enCity.y, simHost.sim, general.player)
                if shouldAllIn:
                    if not moveEnemyCity and turn > 210:
                        self.assertEqual(general.player, city.player)
                        self.assertFalse(bot.is_all_in(), "should have immediately found and sat on the enemy city, and stopped all-inning to hold the city instead.")
                        self.assertNoRepetition(simHost, minForRepetition=2)
                    else:
                        self.assertTrue(bot.all_in_city_behind, "should still be all-inning for cities")
                        self.assertTrue(bot.is_all_in(), "should not have immediately found and sat on the enemy city, and still be all-inning")
                else:
                    if runForTurns > 15 or turn > 215:
                        self.assertGreater(bot._map.players[general.player].tileCount, 63)
                        self.assertEqual(-1, city.player)
                    self.assertNoRepetition(simHost, minForRepetition=2)
    
    def test_should_not_intercept_army_when_better_to_keep_expanding(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_intercept_army_when_better_to_keep_expanding___C0hgOAomT---0--145.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 145, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 10, 20)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=145)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,3->5,2->4,2->4,1->3,1->2,1')
        simHost.queue_player_moves_str(general.player, '12,14->12,15')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        pMap = simHost.get_player_map(general.player)
        self.assertEqual(56, pMap.players[general.player].tileCount)
        self.assertEqual(57, pMap.players[enemyGeneral.player].tileCount)
    
    def test_should_swap_timings_off_of_long_econ_defense(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_swap_timings_off_of_long_econ_defense___C0hgOAomT---0--192.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 192, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=192)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_swap_timings_off_of_long_econ_defense")
    
    def test_should_not_waste_rest_of_cycle_after_city_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_waste_rest_of_cycle_after_city_capture___C0hgOAomT---0--186.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 186, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=186)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # simHost.queue_player_moves_str(general.player, '1,3->2,3')

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=14)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 60)
    
    def test_should_drop_defensive_timings_when_opp_takes_a_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_drop_defensive_timings_when_opp_takes_a_city___7GsHdUn99---0--238.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 238, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=238)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        bot._lastTargetPlayerCityCount = 1
        bot.timings = bot.get_timings()
        bot.timings.splitTurns = 42
        bot.timings.launchTiming = 42

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=12)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 76)
    
    def test_should_intercept_army_instead_of_allowing_city_capture(self):
        # ref D:\KeptGeneralsLogs\almostBeatSpraget_Human.exe-1v1-2023-10-09_01-49-26---6ZAGySdUX
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_army_instead_of_allowing_city_capture___6ZAGySdUX---1--201.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 201, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 14, 6)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=201)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->7,4->6,4->5,4->5,3->5,2->4,2->4,1->3,1->2,1')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=9)
        self.assertIsNone(winner)

        city = self.get_player_tile(4, 1, simHost.sim, general.player)
        self.assertEqual(general.player, city.player, "should not have let Spraget capture the city")
    
    def test_should_play_defensive_when_just_recaptured_city(self):
        # ref D:\KeptGeneralsLogs\almostBeatSpraget_Human.exe-1v1-2023-10-09_01-49-26---6ZAGySdUX
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_play_defensive_when_just_recaptured_city___6ZAGySdUX---1--214.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 214, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 14, 6)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=214)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.assertGatheredNear(simHost, general.player, 4, 8, 4, requiredAvgTileValue=1.5)

    def test_should_detect_incoming_all_in_attack_and_maintain_defense_when_up_on_econ_and_opp_keeps_gathering(self):
        # ref D:\KeptGeneralsLogs\almostBeatSpraget_Human.exe-1v1-2023-10-09_01-49-26---6ZAGySdUX
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_play_defensive_when_just_recaptured_city___6ZAGySdUX---1--214.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 214, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 14, 6)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=214)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=36)
        self.assertIsNone(winner)

        self.assertGatheredNear(simHost, general.player, 3, 9, 4, requiredAvgTileValue=1.5)

        botTiles = playerMap.players[general.player].tileCount
        enTiles = playerMap.players[enemyGeneral.player].tileCount

        self.assertGreater(botTiles, enTiles - 6, "Bot should kind of catch up on tiles a little while playing super defensive gatherwise.")
        self.assertCleanedUpTilesNear(simHost, general.player, 6, 3, 4, capturedWithinLastTurns=30, requireCountCapturedInWindow=7)
    
    def test_should_over_gather_when_most_army_out_of_play(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_over_gather_when_most_army_out_of_play___wSZd30ZzN---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=32)
        self.assertIsNone(winner)

        self.assertPlayerTileCountLess(simHost, general.player, 60, "should have spent the whole time gathering defensively")
    
    def test_should_go_all_in_along_existing_path_with_army_on_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_go_all_in_along_existing_path_with_army_on_it___Teammate.exe-7wShG5xG7---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_go_all_in_along_existing_path_with_army_on_it")
    
    def test_should_kill_enemy_general_lmao(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_kill_enemy_general_lmao___b3c0c2OqP---2--232.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 232, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=232)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=2)
        self.assertIsNotNone(winner)
    
    def test_should_attack_with_army_not_hold_on_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attack_with_army_not_hold_on_general___xL_qj5JaU---0--231.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 231, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=231)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=19)
        self.begin_capturing_logging()
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost)
        self.assertPlayerTileCountGreater(simHost, general.player, 73)
    
    def test_should_attack_with_army_not_hold_on_general_v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attack_with_army_not_hold_on_general_v2___xL_qj5JaU---0--272.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 272, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=272)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1, turns=20)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost, minForRepetition=3)
        self.assertPlayerTileCountGreater(simHost, general.player, 80)
    
    def test_should_not_loop_in_front_of_unmoving_smallish_armies(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_in_front_of_unmoving_smallish_armies___wIG-a2l63---0--344.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 344, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=344)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost)

        self.skipTest("TODO add asserts for should_not_loop_in_front_of_unmoving_smallish_armies")
    
    def test_should_not_actively_attack_52_army_but_lock_the_68_for_dealing_with_it_instead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_actively_attack_52_army_but_lock_the_68_for_dealing_with_it_instead___wIG-a2l63---0--300.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 300, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=300)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_actively_attack_52_army_but_lock_the_68_for_dealing_with_it_instead")
    
    def test_should_not_expand_up_into_main_attack_paths_with_tiles_along_them_main_attack_paths(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        """
        though I'll have to rework some stuff, I do know thats a mistake but haven't really been thinking of it as one of the major mistakes the bot is making
so in particular the thing that makes it a mistake is that that is the path that the pushes rally down eventually, and thus these moves are wasted when you come rallying down it and the bot has no response pushing up there
trying to think of how to codify that logically
like, if it were capturing those tiles out near the fringes, it would be fine, right?
in particular out near the fringes where you have less high value tiles nearby
so the data points here are: 
On or near the likely attack path
The army it is using are tiles that are central to the board (where, if the 15 was up above and attacking downwards, that would also be fine, its really just because its pushing the 15 up out of its territory that is going to be on the attack path rather than down from territory that is uncontested / out of play that makes it bad)

and in particular, it is attacking parallel to the generals on that path (in this case towards you, but would also be bad if towards own gen) 
rather than perpendicular, which is a weirdly specific thing to note but I think is actually super relevant. The 15 moving up is fine until the exact moment it starts pushing down towards your gen

Ethryn:
no, it's the fact that pushing the 15 up means that later on, when you're moving troops in that area, you're walking over land that you've already been on*
*i know you go a different route, but imo you'd prefer a bigger attack than taking two routes of land through that area

"""
        mapFile = 'GameContinuationEntries/should_not_expand_up_into_main_attack_paths_with_tiles_along_them_main_attack_paths___wIG-a2l63---0--304.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 304, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=304)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_expand_up_into_main_attack_paths_with_tiles_along_them_main_attack_paths")
    
    def test_should_launch_attack_before_spreading_leaf_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_launch_attack_before_spreading_leaf_moves___wIG-a2l63---0--61.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 61, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=61)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_launch_attack_before_spreading_leaf_moves")
    
    def test_should_prep_attack_through_longest_enemy_tile_path_so_long_as_safe_on_shortest__move_gen_prediction_to_top(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        """
Peacemaker II — Today at 12:27 PM
I go all in @ closest location usually

EklipZ — Today at 12:28 PM
closest as in closest enemy tiles, or closest as in what you assume to be shortest path to enemy gen?
like here, top is technically closest, but bottom is by far closest enemy set of tiles
and bot should probably know top is closest here, too
if I improve the prediction algo

Peacemaker II — Today at 12:30 PM
closest enemy tiles
you don't want to attack close to enemy general ideally, because they have a shorter route to "get rid" of the armies in your general

getting ahead in armies 100% correlates to the amount of extra troops lying on your land/general

whoever has less extra troops will always get ahead
(this is @ the end of a round btw)
"""
        mapFile = 'GameContinuationEntries/should_prep_attack_through_longest_enemy_tile_path_so_long_as_safe_on_shortest__move_gen_prediction_to_top___wIG-a2l63---0--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_prep_attack_through_longest_enemy_tile_path_so_long_as_safe_on_shortest__move_gen_prediction_to_top")
    
    def test_should_not_loop(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop___y8deg9yKB---0--122.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 122, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=122)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_loop")
    
    def test_should_not_loop_intercepting_entangled_armies(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_intercepting_entangled_armies___HlMEz2Wzp---1--223.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=223)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        armyA = bot.get_army_at_x_y(4, 9)
        armyB = bot.get_army_at_x_y(3, 8)
        armyA.entangledArmies.append(armyB)
        armyB.entangledArmies.append(armyA)
        armyB.entangledValue = 25
        armyA.entangledValue = 25
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost, minForRepetition=2)
    
    def test_should_all_in_gen_trade_when_almost_certain_of_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_all_in_gen_trade_when_almost_certain_of_general_location___Qn0ivuj37---1--433.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 433, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=433)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,15->8,14->8,13->9,13->9,12->10,12->11,12->11,11->11,10->12,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        self.set_general_emergence_around(0, 16, simHost, general.player, enemyGeneral.player, 50)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertEqual(map.player_index, winner)
    
    def test_should_not_run_past_enemy_threat_with_small_army_when_cant_defend(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_run_past_enemy_threat_with_small_army_when_cant_defend___mWHfpzgKj---1--129.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 129, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=129)
        enVisionGen = rawMap.GetTile(enemyGeneral.x, enemyGeneral.y)
        enVisionGen.tile = TILE_FOG
        enVisionGen.army = 0
        enVisionGen.isGeneral = False
        enVisionGen.player = -1

        rawMap.generals[enemyGeneral.player] = None
        rawMap.players[enemyGeneral.player].general = None

        enVisionTile = rawMap.GetTile(16, 7)
        enVisionTile.tile = TILE_FOG
        enVisionTile.army = 0
        enVisionTile.isGeneral = False
        enVisionTile.player = -1

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,7->16,6->15,6->14,6->13,6->13,5->13,4->12,4->11,4->11,3->10,3->9,3->8,3->7,3->7,2->7,1->6,1')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.next_scrimming_army_tile = bot._map.GetTile(15, 5)
        self.set_general_emergence_around(20, 7, simHost, general.player, enemyGeneral.player, 5)
        # self.set_general_emergence_around(17, 9, simHost, general.player, enemyGeneral.player, 4)
        # self.set_general_emergence_around(16, 7, simHost, general.player, enemyGeneral.player, 8)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

    def test_should_quickly_recapture_wall_break_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # https://generals.io/replays/089dxyou6
        mapFile = 'GameContinuationEntries/should_immediately_all_in_out_of_position_army_to_hold_wall_break_choke_city_captured_by_opp___089dxyou6---0--524.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 524, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 19, 17)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=524)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        wallBreakCity = self.get_player_tile(12, 11, simHost.sim, general.player)
        self.assertEqual(general.player, wallBreakCity.player)

    def test_should_immediately_all_in_hold_wall_break_by_opp__should_pull_out_of_position_army_to_hold(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # https://generals.io/replays/089dxyou6
        mapFile = 'GameContinuationEntries/should_immediately_all_in_out_of_position_army_to_hold_wall_break_choke_city_captured_by_opp___089dxyou6---0--524.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 524, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 19, 17)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=524)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=75)
        self.assertIsNone(winner)

        wallBreakCity = self.get_player_tile(12, 11, simHost.sim, general.player)
        self.assertEqual(general.player, wallBreakCity.player)
        self.assertGreater(wallBreakCity.army, 300, "should all-in hold city as long as economically ahead.")
    
    def test_should_determine_cannot_safely_hold_out_of_position_top_left_cities_when_middle_wall_break_available_and_hold_wall(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # https://generals.io/replays/089dxyou6
        mapFile = 'GameContinuationEntries/should_determine_cannot_safely_hold_out_of_position_top_left_cities_when_middle_wall_break_available_and_hold_wall___089dxyou6---0--402.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 402, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 19, 17)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=402)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=50)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_determine_cannot_safely_hold_out_of_position_top_left_cities_when_middle_wall_break_available_and_hold_wall")
    
    def test_should_go_upward_to_keep_capturing_tiles_without_allowing_blue_intercept(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_go_upward_to_keep_capturing_tiles_without_allowing_blue_intercept___089dxyou6---0--190.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 190, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=190)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_go_upward_to_keep_capturing_tiles_without_allowing_blue_intercept")

    def test_should_not_run_around_weirdly_as_army_approaches(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_run_around_weirdly_as_army_approaches___ecYjjTXEx---0--178.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 178, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=178)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,11->10,10->11,10->12,10->12,9->13,9->13,8->14,8->15,8->15,7->16,7->16,6->17,6->18,6->18,5->18,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        bot.curPath = Path()
        bot.curPath.add_next(playerMap.GetTile(18, 6))
        bot.curPath.add_next(playerMap.GetTile(17, 6))
        bot.curPath.add_next(playerMap.GetTile(16, 6))
        bot.curPath.add_next(playerMap.GetTile(16, 7))
        bot.curPath.add_next(playerMap.GetTile(16, 8))

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=22)
        self.assertIsNone(winner)

        self.assertPlayerTileCount(simHost.sim, general.player, 81, 'should wait for the incoming army and make leafmoves and stuff.')
    
    def test_should_gather_at_opp_when_winning(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_at_opp_when_winning___zMGHLu9NU---1--480.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=55)
        self.assertIsNone(winner)
    
    def test_should_not_find_no_moves_scrim_when_ought_to_be_gathering(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_find_no_moves_scrim_when_ought_to_be_gathering___hkmuAe_9b---7--54.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 54, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=54)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_find_no_moves_scrim_when_ought_to_be_gathering")
    
    def test_should_not_loop_defending_from_recapturable_cities(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_defending_from_recapturable_cities___JhrO21FsX---7--581.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 581, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=581)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost, 2)
    
    def test_should_leave_kitty_corner_to_en_gen_army_alone_and_not_defend_fake_general_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_leave_kitty_corner_to_en_gen_army_alone_and_not_defend_fake_general_threat___kbTUBKzrZ---3--130.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 130, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=130)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        tile = playerMap.GetTile(16, 13)
        self.assertEqual(16, tile.army)
    
    def test_should_plan_flank_runby_when_knows_gen_location_and_just_expand_with_half_their_standing_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_plan_flank_runby_when_knows_gen_location_and_just_expand_with_half_their_standing_army___zOMqFxODY---0--68.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 68, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=68)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  None  None  None  None  None  None  17,20->18,20->19,20->20,20->21,20->21,21->21,22->22,22->22,23->23,23->23,24')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)

        self.assertEqual(general.player, enemyGeneral.player)
    
    def test_should_not_miscount_en_cities_when_en_caps_ours(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_miscount_en_cities_when_en_caps_ours___P1eLiNeYh---1--301.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 300, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=300)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  8,14->8,13')
        simHost.queue_player_moves_str(general.player, 'None  3,4->4,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        enPlayer = playerMap.players[enemyGeneral.player]
        self.assertEqual(3, enPlayer.cityCount)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertFalse(bot.is_all_in_losing)
        self.assertFalse(bot.is_all_in())
        self.assertEqual(4, enPlayer.cityCount)
    
    def test_should_not_let_en_army_run_around_friendly_territory_due_to_threat_killer_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for itr in range(10):
            for path in [
                '10,16->10,15->9,15->8,15->8,14->7,14->6,14->6,15->5,15->5,14->4,14->3,14->2,14->1,14->1,13',
                '10,16->10,15->9,15->8,15->7,15->6,15->5,15->5,14->4,14->3,14->2,14->1,14->1,13',
                '10,16->10,17->10,18->9,18->8,18->7,18->6,18->5,18->4,18->3,18->2,18->1,18->0,18->0,17',
            ]:
                with self.subTest(itr=itr,path=path):
                    mapFile = 'GameContinuationEntries/should_not_let_en_army_run_around_friendly_territory_due_to_threat_killer_move___Kj2jWIDxL---1--436.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 436, fill_out_tiles=True)

                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=436)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                    simHost.queue_player_moves_str(enemyGeneral.player, path)
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
                    self.assertIsNone(winner)

                    self.assertPlayerTileCountLess(simHost, enemyGeneral.player, 124)

    def test_should_not_kill_threat_path_backwards_lmao(self):
        for armyAmt, expectedCaps in [(57, 48), (50, 44), (67, 52)]:
            with self.subTest(armyAmt=armyAmt):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_not_kill_threat_path_backwards_lmao___W-GNJ-jH4---0--186.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 186, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=186)
                rawMap.GetTile(3, 9).army = armyAmt
                map.GetTile(3, 9).army = armyAmt

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '3,9->3,8->3,7->3,6->4,6->4,7->4,8->5,8->6,8->7,8->7,9')
                bot = self.get_debug_render_bot(simHost, general.player)
                simHost.sim.ignore_illegal_moves = True
                bot.targetingArmy = bot.get_army_at_x_y(3, 9)

                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
                self.assertIsNone(winner)

                self.assertPlayerTileCountLess(simHost, enemyGeneral.player, expectedCaps)
    
    def test_should_all_in_en_gen_when_opp_doesnt_know_our_gen_and_cannot_hold_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_en_gen_when_opp_doesnt_know_our_gen_and_cannot_hold_city___Hx1ru6UDJ---0--284.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 284, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=284)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_all_in_en_gen_when_opp_doesnt_know_our_gen_and_cannot_hold_city")
    
    def test_should_all_in_gather_own_defensive_line_to_en_until_safe(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_gather_own_defensive_line_to_en_until_safe___JZtyCrKWK---4--330.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 330, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=330)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=75)
        self.assertIsNone(winner)

        gatheredNear = bot.sum_player_standing_army_near_or_on_tiles([playerMap.players[general.player].general], distance=10, player=general.player)
        self.assertGreater(gatheredNear, 400)
    
    def test_should_not_infinite_gather_at_continue_army_kill(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_infinite_gather_at_continue_army_kill___tg5Cb-aZW---1--144.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 144, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=144)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        enArmy = playerMap.GetTile(12, 13)
        self.assertEqual(general.player, enArmy.player)

        self.assertNoRepetition(simHost)
        
    def test_should_not_take_forever_on_danger_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_forever_on_danger_tiles___l4G1hfMnK---0--91.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 91, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=91)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_take_forever_on_danger_tiles")
    
    def test_should_be_able_to_expand_through_en_tiles_near_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_able_to_expand_through_en_tiles_near_gen___FZns0waRm---0--83.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 83, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=83)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        ogTileDiff = self.get_tile_differential(simHost)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost), ogTileDiff + 11*2 + 6 - 1)
    
    def test_should_not_launch_attack_without_intercepting_incoming(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_attack_without_intercepting_incoming___FZns0waRm---0--71.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 71, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=71)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,15->20,15->20,11->21,11->21,12')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        ogTileDiff = self.get_tile_differential(simHost)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=29)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost), ogTileDiff - 2 + 11*2 + 6 - 1)

    def test_should_not_dodge_off_general_and_die(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for i in range(3):
            for path in ['16,7->16,6->15,6', '16,7->15,7->15,6']:
                with self.subTest(path=path, i=i):
                    mapFile = 'GameContinuationEntries/should_not_dodge_off_general_and_die___BhG2-SmSG---4--618.txtmap'
                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 618, fill_out_tiles=True)
                    enemyGeneral.army = 500

                    rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=618)

                    self.enable_search_time_limits_and_disable_debug_asserts()
                    simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                    simHost.queue_player_moves_str(enemyGeneral.player, path)
                    bot = self.get_debug_render_bot(simHost, general.player)
                    playerMap = simHost.get_player_map(general.player)

                    self.begin_capturing_logging()
                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
                    self.assertIsNone(winner)

    def test_should_complete_kill_of_en_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_track_moved_army_when_chase_on_priority_loss___POUT9AJJb---1--190.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 190, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=190)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,16->10,16->11,16->12,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        army = bot.get_army_at_x_y(9, 16)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        shouldBe1 = playerMap.GetTile(11, 16)
        self.assertEqual(1, shouldBe1.army)

        shouldBeBots = playerMap.GetTile(12, 16)
        self.assertEqual(general.player, shouldBeBots.player)

    def test_should_kill_enemy_danger_tiles_before_city_cap(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_enemy_danger_tiles_before_city_cap___hLMTJomIL---1--344.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 344, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=344)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_kill_enemy_danger_tiles_before_city_cap")
    
    def test_should_not_dodge_off_general_and_die__2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for i in range(5):
            with self.subTest(i=i):
                mapFile = 'GameContinuationEntries/should_not_dodge_off_general_and_die___oJrpCSQrt---1--466.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 466, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=466)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '2,13->1,13->0,13->0,12')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
                self.assertIsNone(winner)
    
    def test_should_find_one_move_kill_on_enemy_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_one_move_kill_on_enemy_general___X1KecH2XL---1--91.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 91, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=91)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertEqual(general.player, winner)
    
    def test_should_intercept_incoming_army_and_handle_weird_path_splits(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_incoming_army_and_handle_weird_path_splits___gSL0OCHeW---0--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=138)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,8->11,7->10,7->10,6->9,6z->9,7->8,7->8,8->7,8  10,6->9,6->8,6->7,6->7,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        simHost.sim.ignore_illegal_moves = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost), 0, "should be winning this encounter")
    
    def test_should_clear_enemy_vision_around_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_clear_enemy_vision_around_city___4naQiW6K7---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player).approximate_fog_army_available_total = -20
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=30)
        self.assertIsNone(winner)

        for tile in [
            playerMap.GetTile(12,3),
            playerMap.GetTile(13,3),
            playerMap.GetTile(14,3),
            playerMap.GetTile(12,4),
        ]:
            self.assertEqual(general.player, tile.player)

    def test_should_continue_army_intercept(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_army_intercept___gp2JRs-34---0--607.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 607, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=607)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,1->6,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertEqual(general.player, playerMap.GetTile(6, 0).player)
        self.assertNoRepetition(simHost)

    def test_should_not_spend_whole_cycle_gathering_for_out_of_play(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_spend_whole_cycle_gathering_for_out_of_play___Sl1-YUT46---1--103.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 103, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=103)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.defend_economy = True
        bot.is_winning_gather_cyclic = False
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][enemyGeneral] = 0
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertLess(bot.timings.splitTurns, 39)

    def test_should_not_error_on_weird_0_length_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_error_on_weird_0_length_threat___rlYFKD6V6---1--263.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 263, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=263)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_error_on_weird_0_length_threat")
    
    def test_should_not_expose_city_capture_instantly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_expose_city_capture_instantly___PaqeSXMnr---0--192.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 192, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=192)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        city = playerMap.GetTile(12, 3)
        otherSide = playerMap.GetTile(11, 3)
        self.assertEqual(general.player, city.player)
        self.assertEqual(-1, otherSide.player, "should not reveal it has a city when ahead on econ and knows enemy tiles nearby the city and enemy has more army")    

    def test_should_not_go_all_in_so_early(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_go_all_in_so_early____5kMDUymF---0--176.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 176, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=176)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        simHost.sim.ignore_illegal_moves = True
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertEqual(0, bot.all_in_losing_counter)
    
    def test_should_not_let_opp_catch_up_when_going_temp_all_in(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_let_opp_catch_up_when_going_temp_all_in___pPZuQD1Iq---1--541.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 541, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=541)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertEqual(general.player, winner)

    def test_should_not_blow_up_on_interception_expansion_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_blow_up_on_interception_expansion_path___Human.exe-ucs4g_wiy---1--361.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 361, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=361)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
    
    def test_should_not_blow_up_on_other_intercept_plan_stuff(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_blow_up_on_other_intercept_plan_stuff___Human.exe-DCAwIU70t---1--541.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 541, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=541)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
    
    def test_should_defend_inevitably_incoming_kill_threat_with_3s_from_right(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_inevitably_incoming_kill_threat_with_3s_from_right___Ajj9uEj1c---0--325.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 325, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=325)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=16)
        self.assertIsNone(winner)

        numGathed = 0
        for x in range(17, 19):
            for y in range(10, 14):
                tile = playerMap.GetTile(x, y)
                if tile.army == 1:
                    numGathed += 1

        self.assertGreater(numGathed, 3)

        self.assertEqual(1, playerMap.GetTile(13, 12).army)
        self.assertEqual(1, playerMap.GetTile(14, 12).army)
        self.assertEqual(1, playerMap.GetTile(15, 12).army)
    
    def test_should_not_loop_on_threat_killer_move_and_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_loop_on_threat_killer_move_and_expansion___zkv9Q0x9h---1--252.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 252, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 17, 17)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=252)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,16->14,16->15,16->15,15->15,16')
        simHost.queue_player_moves_str(general.player, '14,15->14,14')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost, repetitionPlayer=general.player)
    
    def test_should_only_dive_when_knows_can_kill_in_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for inTime in [True, False]:
            with self.subTest(inTime=inTime):
                mapFile = 'GameContinuationEntries/should_only_dive_when_knows_can_kill_in_time____LU9dFErm---0--143.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 143, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, 15, 14)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=143)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '11,10->10,10->10,6->8,6->8,2->7,2')
                if not inTime:
                    simHost.queue_player_moves_str(general.player, 'None  None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
                if not inTime:
                    self.assertIsNone(winner)
                else:
                    self.assertEqual(map.player_index, winner)

    def test_should_always_take_multi_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_always_take_multi_city___gGf9os0D9---1--402.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 402, fill_out_tiles=True)
        self.update_tile_army_in_place(map, map.GetTile(13, 14), 1)
        self.update_tile_army_in_place(map, map.GetTile(14, 13), 1)
        self.update_tile_army_in_place(map, map.GetTile(14, 14), 1)
        t = map.GetTile(12, 14)
        t.player = enemyGeneral.player
        self.update_tile_army_in_place(map, t, 3)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=402)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,13->12,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        c1 = playerMap.GetTile(12, 13)
        c2 = playerMap.GetTile(13, 13)

        self.assertOwned(general.player, c1)
        self.assertOwned(general.player, c2)

    def test_should_not_greedy_when_need_to_out_of_play_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_greedy_when_need_to_out_of_play_gather___Q_W0EM1f5---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)

        self.assertMinArmyNear(playerMap, playerMap.GetTile(6, 14), general.player, 30)
        self.assertGatheredNear(simHost, general.player, 10, 18, 6, requiredAvgTileValue=1.15)
        self.assertOwned(general.player, playerMap.GetTile(9, 10), 'should have taken this tile for flank defense by now.')

# 101f, 70p, 16s    
    def test_should_not_misplace_army_and_end_up_looping(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '8,9->9,9->9,5->10,5->10,4z->10,2->12,2->12,1->16,1',
            '8,9->9,9->9,5->10,5',
            '8,9->9,9->9,5->10,5->10,4->10,2->12,2->12,1->16,1',
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/should_not_misplace_army_and_end_up_looping___Na1UAThJE---0--274.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 274, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=274)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
                self.assertIsNone(winner)
