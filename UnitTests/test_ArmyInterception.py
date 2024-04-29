import time

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from Behavior.ArmyInterceptor import TARGET_CAP_VALUE
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from bot_ek0x45 import EklipZBot


class ArmyInterceptionUnitTests(TestBase):
    def __init__(self, methodName: str = ...):
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2, clearCurPath: bool = True) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_intercept_data = True
        bot.info_render_board_analysis_choke_widths = True
        bot.info_render_army_emergence_values = False
        bot.army_interceptor.log_debug = True
        if clearCurPath:
            bot.curPath = None

        return bot

    def test_should_intercept_army_that_is_one_tile_kill_and_city_threat_lol__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)
        enTile = map.GetTile(7, 14)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertEqual(1, bestOpt.length)
        self.assertEqual(enTile, bestOpt.tail.tile)

    def test_should_continue_to_intercept_army__unit_test_should_not_value_pointless_intercepts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_value_pointless_intercepts___Human.exe-TEST__bee0a7ef-ea4e-4234-aba2-4d8c5384d938---0--141.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 141, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)
        opt = self.get_best_intercept_option_path_values(plan)

        if debugMode:
            self.render_intercept_plan(map, plan)

    def test_should_prevent_run_around_general__correctly_analyze_intercept_value_addons(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_analyze_intercept_values___Human.exe-TEST__3c8fbffc-3762-4a68-a059-27bf06366d28---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        # rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)

        plan = self.get_interception_plan(map, general, enemyGeneral) #, additionalPath='7,9->7,10->6,10->6,11->5,11->5,9')

        if debugMode:
            self.render_intercept_plan(map, plan)

        val, turns, bestOpt = self.get_best_intercept_option_path_values(plan)

        self.assertEqual(general, bestOpt.start.tile)

    def test_should_intercept_with_large_tile__should_intercept_despite_leftward_unpreventable_option__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_large_tile___qWwqozFbe---1--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        # enTile = map.GetTile(12, 9)
        enTile = map.GetTile(10, 9)

        self.begin_capturing_logging()
        analysis = ArmyAnalyzer(map, map.GetTile(10, 14), enTile)
        # if debugMode:
        #     self.render_army_analyzer(map, analysis)

        # this is NOT a shortest path to the target tile, is found naturally because the 18 runs out before reaching it if it goes straight down but in theory we could always find a path like this anyway even if the 13 to the right wasn't there.
        addlPath = '10,9->14,9->14,15->13,15'
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile, additionalPath=addlPath)
        # plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        self.assertNotIn(map.GetTile(9, 10), plan.common_intercept_chokes)

        self.assert_no_intercept_option_by_coords(plan, 10, 13, 10, 15, "should not have found a path just heading back to general")
        self.assert_no_intercept_option_by_coords(plan, 10, 14, 10, 15, "should not have found a path just heading back to general")
        self.assert_no_intercept_option_by_coords(plan, 10, 11, 10, 14, "should not have found a path just heading back to general")
        self.assert_no_intercept_option_by_coords(plan, 10, 10, 10, 14, "should not have found a path just heading back to general")

        val, turns, bestPath = self.get_best_intercept_option_path_values(plan)
        self.assertLess(bestPath.tail.tile.y, 12)

    def test_should_value_recaptures_properly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        interceptor = self.get_interceptor(map, general, enemyGeneral)
        path = Path()
        path.add_next(map.GetTile(14, 6))
        path.add_next(map.GetTile(13, 6))
        path.add_next(map.GetTile(12, 6))
        path.add_next(map.GetTile(11, 6))
        path.add_next(map.GetTile(10, 6))
        path.add_next(map.GetTile(10, 5))
        path.add_next(map.GetTile(9, 5))

        val, turnsUsed = interceptor._get_path_econ_values_for_player(path, searchingPlayer=general.player, targetPlayer=enemyGeneral.player, turnsLeftInCycle=19, includeRecaptureEffectiveStartDist=1)
        # we move 6 to intercept, they move 6 forward to 7,5. No collision yet.
        # We collide with over 30 more army with them, giving us full recapture turns.
        self.assertEqual(19, turnsUsed)

        # Since we captured 0 other tiles, the value of the intercept should equal number of remaining recapture turns * 2, which should be 22
        self.assertGreater(val, 10.5 * TARGET_CAP_VALUE)

    def test_should_identify_multi_threat_chokes_in_defense_plan(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)
        self.assertEqual(2, len(plan.threats))

        self.assertInterceptChokeTileMoves(plan, map, x=8, y=5, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=9, y=5, w=1)
        self.assertNotInterceptChoke(plan, map, x=10, y=5)
        self.assertNotInterceptChoke(plan, map, x=9, y=4)
        self.assertNotInterceptChoke(plan, map, x=10, y=6)

        self.assertEqual(map.GetTile(14, 6), plan.best_enemy_threat.threat.path.tail.tile)

    def test_should_identify_best_meeting_point_in_intercept_options(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)
        notCity = map.GetTile(14, 6)
        notCity.isCity = False
        map.players[general.player].cities.remove(notCity)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan)

        self.assertEqual(2, len(plan.threats))

        self.assertInterceptChokeTileMoves(plan, map, x=8, y=5, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=9, y=5, w=1)
        self.assertInterceptChokeTileMoves(plan, map, x=13, y=3, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=14, y=3, w=0)
        self.assertInterceptChokeTileMoves(plan, map, x=9, y=4, w=0)
        self.assertNotInterceptChoke(plan, map, x=10, y=5)
        self.assertNotInterceptChoke(plan, map, x=10, y=6)

        val, turns, bestOpt = self.get_best_intercept_option_path_values(plan)

        self.assertEqual(map.GetTile(9, 5), bestOpt.tail.tile)

# TODO still need an open-map wide choke example to test finding mid-choke-points on. 3 or wider choke required.
# TODO what about threats where the chokes diverge super early from the threat? Need intercept chokes that are NOT on the shortest path, and find the lowest common denominator between them still?
# TODO ^ also needs to detect when the path SPLITS vs lines on opposite sides of the same choke where an army could stage in the middle, vs being unable to stage in the middle due to blockage by mountains or pure split scenario.    
    def test_should_recognize_multi_threat_and_intercept_at_choke__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=289)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        self.assertEqual(2, len(plan.threats))
        self.assertInterceptChokeTileMoves(plan, map, x=2, y=7, w=1)
        self.assertNotInterceptChoke(plan, map, x=5, y=7)
        self.assertNotInterceptChoke(plan, map, x=1, y=5)
        self.assertNotInterceptChoke(plan, map, x=1, y=6)
        self.assertNotInterceptChoke(plan, map, x=1, y=7)
        self.assertNotInterceptChoke(plan, map, x=2, y=8)
        self.assertNotInterceptChoke(plan, map, x=3, y=8)
        self.assertNotInterceptChoke(plan, map, x=4, y=8)

        bestOpt = None
        bestOptAmt = 0
        gatherDepth = 20
        option = plan.intercept_options[3]
        val, path = option
        if path.length < gatherDepth and val > bestOptAmt:
            logbook.info(f'NEW BEST INTERCEPT OPT {val:.2f} -- {str(path)}')
            bestOpt = path
            bestOptAmt = val

        self.assertEqual(map.GetTile(2, 7), bestOpt.tail.tile)

    def test_should_recognize_multi_threat_and_intercept_at_choke__correctly_values_intercept_from_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)
        map.GetTile(1, 8).army = 1
        map.GetTile(1, 8).player = 0
        map.GetTile(1, 9).army = 75

        interception = self.get_interception_plan(map, general, enemyGeneral, additionalPath='1,9->1,8->6,8')

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 8)

        self.assertEqual(1, interception.common_intercept_chokes[map.GetTile(2, 7)], 'all routes can be intercepted in one extra move from this point')
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        # the raw econ differential from this play is +14 econ (-9 -> +5) however it prevents a huge amount of enemy damage as well, so should be calculated as blocking 20 additional econ damage from opponent
        # 14 + 20 should be a value of 36
        self.assertEqual(34, val, 'prevents 20 enemy damage and also recaptures 14 econ worth of tiles')
        # TODO CONTINUE

    def test_should_recognize_multi_threat_and_intercept_at_choke__unit_test_does_not_value_incoming_collisions_that_dont_prevent_caps_to_round_end(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 0, 8, 1, 8)

        if path is not None:  # not even finding this as an intercept is also valid, so only fail if it is found AND its value isn't 0
            self.assertEqual(0, val, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_recognize_multi_threat_and_cannot_fully_intercept_at_choke__unit_recognizes_can_only_block_along_bottom_if_goes_right(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 0, 8, 1, 8)

        if path is not None:  # not even finding this as an intercept is also valid, so only fail if it is found AND its value isn't 0
            self.assertEqual(0, val, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_recognize_multi_threat_and_cannot_fully_intercept_at_choke__unit_recognizes_can_only_block_along_bottom_if_goes_right__including_over_top(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral, additionalPath='1,8->1,4->5,4->5,1')

        if debugMode:
            self.render_intercept_plan(map, interception)

        self.assert_no_intercept_option_by_coords(interception, 0, 8, 1, 8, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path_by_coords(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_intercept_large_incoming_at_choke_even_with_not_quite_enough__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_large_incoming_at_choke_even_with_not_quite_enough___DiPqVAsND---0--273.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 273, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=273)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)
        self.assertEqual(2, len(plan.threats))

        self.assertNotEqual(0, len(plan.intercept_options))
        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        paths = SearchUtils.where(plan.intercept_options.values(), lambda p: p[1].start.tile.x == 3 and p[1].start.tile.y == 9 and p[1].tail.tile.x == 7 and p[1].tail.tile.y == 9)
        self.assertEqual(1, len(paths))

    def test_should_not_intercept_when_more_economic_to_just_keep_expanding__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gracefully_handle_deviating_en_expansion_path___YuXhnQtCE---1--142.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 142, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=142)
        self.reset_general(rawMap, enemyGeneral)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        # self.assertEqual(1, len(plan.threats), "only econ threat")

        bestVal, bestTurns, bestPath = self.get_best_intercept_option_path_values(plan)
        self.assertLess(bestVal, 7, "should not overvalue any of these intercepts")
        self.assertLess(bestVal/bestTurns, 0.5, 'should not think any of these have great value per turn.')

        self.assertEqual(map.GetTile(9, 8), bestPath.tail.tile)
    
    def test_should_not_do_infinite_intercepts_costing_tons_of_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 708, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=708)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()

        if debugMode:
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
            self.assertIsNone(winner)

        start = time.perf_counter()
        ArmyAnalyzer.reset_times()
        with bot.perf_timer.begin_move(map.turn):
            bot.build_intercept_plans()
            done = time.perf_counter() - start
        timings = '\r\n'.join(bot.perf_timer.current_move.get_events_organized_longest_to_shortest(25))
        ArmyAnalyzer.dump_times()
        self.assertLess(done, 0.05, f'should spent no more than 50ms on intercepts, \r\n{timings}')

    def test_should_see_split_path_blocker_as_mid_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_see_split_path_blocker_as_mid_choke___Human.exe-TEST__0ec78983-f5c3-4648-a5a6-d1d6ac807db9---0--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        enTile = map.GetTile(14, 8)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.GetTile(14, 9), bestOpt.tileList)

    def test_should_meet_to_defend_multi_choke__when_can_reach_not_one_behind(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   a40  b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.GetTile(2, 9), bestOpt.tileList)

    def test_should_meet_to_defend_multi_choke__when_can_reach_one_behind(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
a40  b1   b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.GetTile(2, 9), bestOpt.tileList)
    
    def test_should_not_take_literal_lifetimes_to_load_intercepts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_literal_lifetimes_to_load_intercepts___nyeEPub4n---7--1165.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1165, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1165)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        start = time.perf_counter()
        ArmyAnalyzer.reset_times()
        with bot.perf_timer.begin_move(map.turn):
            bot.build_intercept_plans()
            done = time.perf_counter() - start
        timings = '\r\n'.join(bot.perf_timer.current_move.get_events_organized_longest_to_shortest(25))
        ArmyAnalyzer.dump_times()
        self.assertLess(done, 0.04, f'should spent no more than 40ms on intercepts, \r\n{timings}')
    
    def test_should_kill_one_away_armies_that_can_do_real_damage_immediately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_kill_one_away_armies_that_can_do_real_damage_immediately___Human.exe-TEST__665a5e30-6063-4675-bff6-61edf7423b72---1--386.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 386, fill_out_tiles=True)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.GetTile(10, 11), bestOpt.tileList)
        self.assertIn(map.GetTile(10, 12), bestOpt.tileList)
    
    def test_should_not_miss_intercept_because_of_enemy_expansion_plan_that_is_short_and_irrelevant(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_miss_intercept_for_unknown_reason___Human.exe-TEST__7eae0a59-1775-4864-a321-282de6ef2c4d---0--182.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 182, fill_out_tiles=True)

        enTile = None
        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile, additionalPath='4,7->4,6')

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
        self.assertIn(map.GetTile(10, 6), bestOpt.tileList)

    # TODO this is important test map scenario
    def test_should_recognize_diverging_path_around_mountain_as_non_intercept_chokes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=False)

        # map.GetTile(6, 7).isMountain = False
        # map.update_reachable()

        analysis = ArmyAnalyzer(map, map.GetTile(5, 17), map.GetTile(7, 6))
        analysis.scan()
        # if debugMode:
        #     self.render_army_analyzer(map, analysis)
        interceptWidth = analysis.interceptChokes.get(map.GetTile(6, 6), None)
        # TODO
        # self.assertEqual(4, interceptWidth)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        value, turns, bestPath = self.get_best_intercept_option_path_values(interception)
        self.assertEqual(6, bestPath.start.tile.x)
        self.assertEqual(6, bestPath.start.tile.y)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 6, 6, 7, 6)
        self.assertIsNotNone(path)

        path, val, turns = self.get_interceptor_path_by_coords(interception, 5, 6, 7, 6)
        self.assertIsNone(path)

        self.assertNotInterceptChoke(interception, map, 6, 6)
        self.assertNotInterceptChoke(interception, map, 7, 7)

    def test_should_intercept_one_late_at_midpoint_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for includeThirdOpt in [False, True]:
            with self.subTest(includeThirdOpt=includeThirdOpt):
                mapFile = 'GameContinuationEntries/should_intercept_one_late_at_midpoint_choke___Human.exe-TEST__7548ab1f-0519-41ce-a83c-785a43ba5915---0--289.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

                paths = [
                    '1,9->1,4->3,4->3,5',
                    '1,9->1,8->4,8->4,7->5,7->5,2',
                ]
                if includeThirdOpt:
                    paths.append('1,9->1,8->3,8->3,9->5,9->5,8->6,8->6,7->8,7')

                plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, paths)

                if debugMode:
                    self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

                value, turns, bestOpt = self.get_best_intercept_option_path_values(plan)
                self.assertIn(map.GetTile(2, 6), bestOpt.tileList)

    def test_should_understand_can_intercept_army_against_corner(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        data = """
|    |    |    |    |    |    |
a1   a1   a1   aG1  a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
a1   a1   M    a1   M    a1   a1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   b1   M    b1   M    b1   b1
b1   a40  b1   b1   b1   b1   b1
b1   b1   b1   b1   b1   b1   b1
b1   b1   b1   b40  b1   b1   bG1
|    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 181)
        enTile = map.GetTile(3, 11)
        # frTile = map.GetTile(6, 0)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=True)

        canInterceptStillTile = map.GetTile(2, 9)
        self.assertEqual(2, plan.common_intercept_chokes[canInterceptStillTile].max_delay_turns, 'can intercept from this tile 1 turn from now by chasing to the right for 4 moves max')
        self.assertEqual(4, plan.common_intercept_chokes[canInterceptStillTile].max_extra_moves_to_capture, 'can intercept from this tile by chasing to the right for 4 moves max')

    def test_should_split_upwards_to_guarantee_damage_control(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_upwards_to_guarantee_damage_control___Human.exe-TEST__a0054186-be26-4c65-90be-ab546e3cc541---1--347.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 347, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=347)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)
    
    def test_should_find_interception_from_4_moves_away(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_interception_from_4_moves_away___Human.exe-TEST__7f68e044-60e0-4a38-9ae8-47af7df82c85---1--346.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 344, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, additionalPath='9,6->8,6->8,7->6,7->6,8->4,8', turnsLeftInCycle= 15)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
    
    def test_should_delay_intercept_when_enemy_army_is_cornered__maybe_split_half(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_delay_intercept_when_enemy_army_is_cornered__maybe_split_half___13nFmhR-q---0--444.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 444, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
        bestOpt = self.get_best_intercept_option(plan)

        self.assertTrue(bestOpt.path.start.move_half or bestOpt.requiredDelay > 0, 'should EITHER delay or move half TODO figure out which is optimal?')
    
    def test_should_intercept_with_further_large_tile_when_possible_not_closer_small_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_further_large_tile_when_possible_not_closer_small_tile___Human.exe-TEST__713fc243-c4e6-4f75-8ec6-38e4b0887581---1--188.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 188, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
        bestOpt = self.get_best_intercept_option(plan)

        self.assertTrue(bestOpt.path.start.move_half or bestOpt.requiredDelay > 0, 'should EITHER delay or move half TODO figure out which is optimal?')

    def test_should_not_mis_evaluate_intercept_value_blocked_damage(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_mis_evaluate_intercept_value_blocked_damage___Human.exe-TEST__f7bcf26d-70ff-4e1e-9c87-e0022affe96f---1--348.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 348, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
        bestOpt = self.assert_no_best_intercept_option(plan)

    # def test_should_not_mis_evaluate_intercept_value_blocked_damage__true_unit(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
    #     mapFile = 'GameContinuationEntries/should_not_mis_evaluate_intercept_value_blocked_damage___Human.exe-TEST__f7bcf26d-70ff-4e1e-9c87-e0022affe96f---1--348.txtmap'
    #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 348, fill_out_tiles=True)
    #
    #     plan = self.get_interception_plan(map, general, enemyGeneral)
    #
    #     if debugMode:
    #         self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)
    #     bestOpt = self.get_best_intercept_option(plan)
    #
    #     path = Path.from_string(map, '8,8->8,9')
    #     plan.
    #
    #     self.assertTrue(bestOpt.path.start.move_half or bestOpt.requiredDelay > 0, 'should EITHER delay or move half TODO figure out which is optimal?')
    
    def test_should_not_split_randomly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_split_randomly___-Zrosee5X---0--81.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 81, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)

        bestOpt = self.get_best_intercept_option(plan)

        self.assertIn(map.GetTile(13, 10), bestOpt.tileList)

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        path = self.get_interceptor_option_by_coords_or_none(plan, 13, 9, 12, 9)
        if path is not None:
            self.assertFalse(path.path.start.move_half)

    def test_should_respect_and_defend_defenseless_modifier(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for mustDefend in [False, True]:
            with self.subTest(mustDefend=mustDefend):
                mapFile = 'GameContinuationEntries/should_respect_and_defend_defenseless_modifier___2v3zDUjUn---1--73.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 73, fill_out_tiles=True)
                if mustDefend:
                    map.GetTile(18, 11).army = 1
                    map.GetTile(13, 10).army = 26

                plan = self.get_interception_plan(map, general, enemyGeneral)

                if debugMode:
                    self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

                self.assert_no_intercept_option_by_coords(plan, 12, 10, message='shouldnt even have an option that wastes intercept time regardless of general death')
                bestOpt = self.get_best_intercept_option(plan)

                self.assertIsNotNone(bestOpt, 'should have found an intercept move to the right, though')
                self.assertNotIn(map.GetTile(12, 10), bestOpt.tileList, 'shouldnt delay and let general die')

    def test_should_intercept_obvious_intercept_use_case(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_obvious_intercept_use_case___wQ-7lZL7d---0--131.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 131, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.GetTile(11, 10), fromTile=map.GetTile(10, 10))

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)

        self.assertEqual((12, 6), bestOpt.path.start.tile.coords)
        self.assertCoordsInPath((12, 8), bestOpt.path)

        # if path is not None:
        #     self.assertFalse(path.path.start.move_half)

    def test_should_evaluate_simple_threat_intercept_correctly__single_threat(self):
        # ref test_should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment for proof of values asserted here
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment___xBu7OEmps---1--185.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 185, fill_out_tiles=True)

        plan = self.get_interception_plan_from_paths(map, general, enemyGeneral, ['9,6->9,5->12,5->12,4->15,4->15,3->17,3->17,2'])

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)

        with self.subTest(baseAssumptions=True):
            self.assertEqual((18, 7), bestOpt.path.start.tile.coords)
            self.assertCoordsInPath((14, 7), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
            self.assertCoordsInPath((14, 6), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
            # if intercept gets revamped to include the recapture path, drop this assert since the above is here.
            self.assertEqual((14, 5), bestOpt.path.tail.tile.coords)

        with self.subTest(damageBlocked=True):
            # 24 total damage by opponent (up top), we block 6 tiles in, so we block 12
            # So assert we block somewhere in that range...
            self.assertGreater(bestOpt.damage_blocked, 5 * TARGET_CAP_VALUE)
            self.assertLess(bestOpt.damage_blocked, 7 * TARGET_CAP_VALUE)

        with self.subTest(recapTurns=True):
            # we recapture 1 post-block tile, so the full econ value should be one more target tile than the raw econ damage blocked
            self.assertEqual(1, bestOpt.recapture_turns)

        with self.subTest(econValue=True):
            # we recapture 1 post-block tile, so the full econ value should be one more target tile than the raw econ damage blocked
            self.assertGreater(bestOpt.econValue, 6 * TARGET_CAP_VALUE)
            self.assertLess(bestOpt.econValue, 8 * TARGET_CAP_VALUE)

        with self.subTest(remainingArmy=True):
            # TODO not sure yet
            self.assertEqual(-1, bestOpt.intercepting_army_remaining)

    def test_should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment(self):
        # ref test_should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment for proof of values asserted here
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_instead_of_eating_damage_on_late_attacks_after_defensive_gather_timing_increment___xBu7OEmps---1--185.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 185, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=map.GetTile(9, 6), fromTile=map.GetTile(9, 7))

        if debugMode:
            self.render_intercept_plan(map, plan, renderIndividualAnalysis=False)

        bestOpt = self.get_best_intercept_option(plan)
        self.assertIsNotNone(bestOpt)

        self.assertEqual((18, 7), bestOpt.path.start.tile.coords)
        self.assertCoordsInPath((14, 7), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
        self.assertCoordsInPath((14, 6), bestOpt.path, 'should have included the high value army tiles in the intercept path for as long as possible before shifting upward')
        # if intercept gets revamped to include the recapture path, drop this assert since the above is here.
        self.assertEqual((14, 6), bestOpt.path.tail.tile.coords)

        # bestOpt.intercept.best_enemy_threat

        # 24 total damage by opponent (up top), we block / recapture all but 10 of it, so we block ~ 14 econ damage. 15.4 damage if we do 2.2 damage per tile as calculation.
        # 31.5 damage by opponent (down right), we block recapture all but 10 of it, so we block ~21 econ damage.
        # So assert we block somewhere in that range...
        self.assertGreater(bestOpt.damage_blocked, 13)
        self.assertLess(bestOpt.damage_blocked, 22)

        # self.assertEqual(0, bestOpt.intercepting_army_remaining, 'or should we actually declare how negative the path value ends up being, like we do now?')
        self.assertLessEqual(bestOpt.intercepting_army_remaining, 0, 'Or, should we return 0 when the path goes negative?')

# 18f, 17p, 0s
# 19f, 17p, 0s  before fixing  test_should_intercept_obvious_intercept_use_case
# 26f, 17p, 0s  after reworking a bunch of stuff and better unit testing. Prior to fixing other tests that may be asserting incorrectly. Broke splitting and started disregarding tile-blocking, for now.
