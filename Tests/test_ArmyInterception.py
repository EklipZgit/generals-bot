import random
import time
import typing

import logbook

import ExpandUtils
import SearchUtils
import base.viewer
from ArmyAnalyzer import ArmyAnalyzer
from ArmyTracker import ArmyTracker
from Behavior.ArmyInterceptor import ArmyInterceptor, ArmyInterception
from BoardAnalyzer import BoardAnalyzer
from DangerAnalyzer import ThreatObj, DangerAnalyzer, ThreatType
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo, TargetStyle, PathColorer
from base.client.map import TILE_MOUNTAIN, TILE_EMPTY, MapBase, Tile
from bot_ek0x45 import EklipZBot


class ArmyInterceptionTests(TestBase):
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

    def get_interceptor(self, map: MapBase, general: Tile, enemyGeneral: Tile, useDebugLogging: bool = True) -> ArmyInterceptor:
        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral)

        self.begin_capturing_logging()
        interceptor = ArmyInterceptor(map, analysis, useDebugLogging=useDebugLogging)
        return interceptor

    def get_interception_plan(self, map: MapBase, general: Tile, enemyGeneral: Tile, enTile: Tile | None = None, turnsLeftInCycle: int = -1, useDebugLogging: bool = True, additionalPath: str | None = None) -> ArmyInterception:
        interceptor = self.get_interceptor(
            map,
            general,
            enemyGeneral,
            useDebugLogging)

        if turnsLeftInCycle == -1:
            turnsLeftInCycle = 50 - map.turn % 50

        addlPath = None
        if additionalPath is not None:
            addlPath = Path.from_string(map, additionalPath)

        if enTile is None:
            enTile = max(map.get_all_tiles(), key=lambda t: t.army if t.player == enemyGeneral.player else 0)

        # dangerAnalyzer = DangerAnalyzer(map)
        # dangerAnalyzer.analyze([general], 40, {})

        targets = [general]
        targets.extend(map.players[general.player].cities)
        threats = []
        negs = set(targets)
        # allow pathing through our tiles
        for tile in map.get_all_tiles():
            if map.is_tile_friendly(tile) and tile.army > 10:
                negs.add(tile)

        for target in targets:
            threatPath = SearchUtils.dest_breadth_first_target(map, [target], maxDepth=40, searchingPlayer=enemyGeneral.player, negativeTiles=negs)

            if threatPath is not None and threatPath.start.tile == enTile:
                analysis = ArmyAnalyzer(map, threatPath.tail.tile, threatPath.start.tile)
                saveTile = None
                if len(threatPath.tileList) > 1 and threatPath.tail.prev.tile in analysis.pathChokes:
                    saveTile = threatPath.tail.prev.tile
                threats.append(ThreatObj(threatPath.length - 1, threatPath.value, threatPath, ThreatType.Kill, saveTile, analysis))

        path = ArmyTracker.get_expected_enemy_expansion_path(map, enTile, general)

        if addlPath is not None:
            analysis = ArmyAnalyzer(map, addlPath.tail.tile, addlPath.start.tile)
            saveTile = None
            if len(addlPath.tileList) > 1 and addlPath.tail.prev.tile in analysis.pathChokes:
                saveTile = addlPath.tail.prev.tile
            threats.append(ThreatObj(addlPath.length - 1, addlPath.value, addlPath, ThreatType.Econ, saveTile, analysis))

        if path is not None:
            analysis = ArmyAnalyzer(map, path.tail.tile, path.start.tile)
            saveTile = None
            if len(path.tileList) > 1 and path.tail.prev.tile in analysis.pathChokes:
                saveTile = path.tail.prev.tile
            threats.append(ThreatObj(path.length - 1, path.value, path, ThreatType.Econ, saveTile, analysis))

        self.assertGreater(len(threats), 0)

        plan = interceptor.get_interception_plan(threats, turnsLeftInCycle=turnsLeftInCycle)

        return plan

    def get_best_intercept_option(self, plan: ArmyInterception, maxDepth=200) -> typing.Tuple[int, int, Path] | None:
        """Returns value, effectiveTurns, path"""
        bestOpt = None
        bestOptAmt = 0
        bestOptDist = 0
        bestVt = 0
        for dist, option in plan.intercept_options.items():
            if dist > maxDepth:
                continue
            val, path = option
            vt = val/dist
            if vt > bestVt:
                logbook.info(f'NEW BEST INTERCEPT OPT {val}/{dist} -- {str(path)}')
                bestOpt = path
                bestOptAmt = val
                bestOptDist = dist
                bestVt = vt

        if bestOpt is None:
            return None

        return bestOptAmt, bestOptDist, bestOpt

    def get_interceptor_path(self, plan: ArmyInterception, xStart: int, yStart: int, xEnd: int, yEnd: int) -> typing.Tuple[Path | None, int, int]:
        """
        Returns Path, value, turnsUsed if a path is found that starts and ends at those positions

        @param plan:
        @param xStart:
        @param yStart:
        @param xEnd:
        @param yEnd:
        @return:
        """

        bestOpt = None
        bestOptAmt = 0
        bestOptDist = 0
        maxVt = 0

        for dist, option in plan.intercept_options.items():
            val, path = option
            if path.start.tile.x == xStart and path.start.tile.y == yStart and path.tail.tile.x == xEnd and path.tail.tile.y == yEnd:
                vt = val/dist
                if vt > maxVt:
                    logbook.info(f'NEW BEST INTERCEPT OPT {val}/{dist} -- {str(path)}')
                    bestOpt = path
                    bestOptAmt = val
                    bestOptDist = dist
                    maxVt = vt

        return bestOpt, bestOptAmt, bestOptDist

    def render_intercept_plan(self, map: MapBase, plan: ArmyInterception, colorIndex: int = 0):
        viewInfo = self.get_renderable_view_info(map)
        targetStyle = TargetStyle(colorIndex + 2)

        for tile, iw in plan.common_intercept_chokes.items():
            viewInfo.add_targeted_tile(tile, targetStyle, radiusReduction=11 - colorIndex)
            viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'iw{iw}'

        for i, threat in enumerate(plan.threats):
            color = ViewInfo.get_color_from_target_style(TargetStyle.YELLOW)
            viewInfo.color_path(PathColorer(
                threat.path,
                color[0] + 20 * i,
                90 - 10 * i,
                121 + 15 * i,
            ))

        maxValPerTurn = 0
        maxValTurnPath = None
        maxVal = 0
        maxTurn = 0
        for dist, (val, path) in plan.intercept_options.items():
            valPerTurn = val / dist
            maxStr = ''
            if valPerTurn > maxValPerTurn:
                maxValPerTurn = valPerTurn
                maxValTurnPath = path
                maxStr = 'NEW MAX '
                maxVal = val
                maxTurn = dist
            viewInfo.color_path(PathColorer(
                path,
                255,
                255,
                255,
            ))

            logbook.info(f'{maxStr}intercept plan {plan.target_tile} dist {dist}: {val:.2f} {path}')

        if maxValTurnPath is not None:
            viewInfo.color_path(PathColorer(
                maxValTurnPath,
                155,
                255,
                155,
            ))
        self.render_view_info(map, viewInfo, f'intercept {maxVal:.2f}/{maxTurn}={maxValPerTurn:.2f} - {str(maxValTurnPath)}')

    def assertInterceptChokeTileMoves(self, plan: ArmyInterception, map: MapBase, x: int, y: int, w: int):
        tile = map.GetTile(x, y)
        self.assertIn(tile, plan.common_intercept_chokes, f'Expected {str(tile)} to be in chokes, but wasnt.')
        val = plan.common_intercept_chokes[tile]
        self.assertEqual(w, val, f'Expected choke {str(tile)} to be {w} but was {val}')

    def assertNotInterceptChoke(self, plan: ArmyInterception, map: MapBase, x: int, y: int):
        tile = map.GetTile(x, y)
        val = plan.common_intercept_chokes.get(tile, -10)
        if val != -10:
            self.fail(f'Expected {str(tile)} NOT to be in chokes, instead found val {val}.')

    def test_should_intercept_army_that_is_one_tile_kill_and_city_threat_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(6):
            mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=307)
            rawMap.GetTile(7, 14).lastMovedTurn = map.turn - 1

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)
            playerMap.GetTile(7, 14).lastMovedTurn = map.turn - 1
            army = bot.get_army_at_x_y(7, 14)
            army.last_moved_turn = map.turn - 1

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
            self.assertIsNone(winner)

            self.assertEqual(general.player, playerMap.GetTile(7, 14).player)

    def test_should_intercept_army_that_is_one_tile_kill_and_city_threat_lol__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 307, fill_out_tiles=True)
        enTile = map.GetTile(7, 14)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        value, turns, bestOpt = self.get_best_intercept_option(plan)
        self.assertEqual(1, bestOpt.length)
        self.assertEqual(enTile, bestOpt.tail.tile)

    def test_should_continue_to_intercept_army__unit_test_should_not_value_pointless_intercepts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_value_pointless_intercepts___Human.exe-TEST__bee0a7ef-ea4e-4234-aba2-4d8c5384d938---0--141.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 141, fill_out_tiles=True)

        plan = self.get_interception_plan(map, general, enemyGeneral)
        opt = self.get_best_intercept_option(plan)

        if debugMode:
            self.render_intercept_plan(map, plan)
    
    def test_should_continue_to_intercept_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_continue_to_intercept_army___HO8rgeNt7---0--140.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 140, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=140)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,8->7,8->7,12->8,12->8,10')
        bot = self.get_debug_render_bot(simHost, general.player, clearCurPath=False)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)
        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, 0)

    def test_should_just_cap_tiles_when_inbound_army_isnt_kill_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        """
        at the start of that round I'm up 4 lands, at the end of the round I'm up 24 and it's because of these wasted moves
        
        proper response is probably take 50-100 troops and try to spend every move capturing my land
        
        so going bottom left is probably best
        
        or even take this 17 and 28 and take all the 2s here (turn 336)
        """
        mapFile = 'GameContinuationEntries/should_just_cap_tiles_when_inbound_army_isnt_kill_threat___50vyo-z9H---1--671.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 671, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=671)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,7->7,7->7,9->9,9->9,12->16,12->16,11->12,11->12,10->14,10  5,17->6,17  1,15->2,15  7,6->6,6  11,7->10,7  9,6->9,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        tileDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=29)
        self.assertIsNone(winner)

        finalTileDiff = self.get_tile_differential(simHost)
        self.assertGreater(finalTileDiff - tileDiff, -8)
    
    def test_should_prevent_run_around_general__stop_multi_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for enPath, genPathFollowUp in [
            ('8,8->7,8->7,10->6,10->6,12->3,12->3,13->4,13->4,16', None),
            ('8,8->5,8->5,9->3,9->3,10->1,10->1,7->2,7->2,5', '5,7->5,9'),
            ('8,8->6,8->6,4->2,4->2,7', '5,7->6,7->6,6'),
            ('8,8->5,8->5,12->3,12->3,13->4,13->4,16', '5,7->5,9'),
        ]:
            with self.subTest(enPath=enPath):
                mapFile = 'GameContinuationEntries/should_prevent_run_around_general___qiPZUGWpC---1--135.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 135, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=135)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                # TODO what the bot SHOULD do, uncomment to see
                # if genPathFollowUp:
                #     simHost.queue_player_moves_str(general.player, '3,7->5,7  5,9->5,8')
                #     simHost.queue_player_moves_str(general.player, genPathFollowUp)

                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=15)
                self.assertIsNone(winner)

                tileDiff = self.get_tile_differential(simHost)
                self.assertGreater(tileDiff, -1, 'should not have allowed opp free reign :(')

    def test_should_prevent_run_around_general__correctly_analyze_intercept_value_addons(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_correctly_analyze_intercept_values___Human.exe-TEST__3c8fbffc-3762-4a68-a059-27bf06366d28---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)

        # rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)

        plan = self.get_interception_plan(map, general, enemyGeneral) #, additionalPath='7,9->7,10->6,10->6,11->5,11->5,9')

        if debugMode:
            self.render_intercept_plan(map, plan)

        val, turns, bestOpt = self.get_best_intercept_option(plan)

        self.assertEqual(general, bestOpt.start.tile)
    
    def test_should_split_and_cap_1s(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_split_and_cap_1s___qiPZUGWpC---1--141.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 141, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=141)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '3,9->3,10->1,10->1,7->2,7->2,5')
        # simHost.queue_player_moves_str(general.player, '4,7->5,7z->5,8->8,8  4,7->3,7->2,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, -3, 'should split and cap up the line of 1s while defending at home with the split, uncomment general moves above for proof')

    def test_should_intercept_with_large_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_large_tile___qWwqozFbe---1--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=138)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,9->9,9z->7,9  10,9->10,11  12,9->14,9->14,12  7,9->7,11')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertIsNone(winner)

        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, 1)

    def test_should_intercept_with_large_tile__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_with_large_tile___qWwqozFbe---1--138.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 138, fill_out_tiles=True)

        # enTile = map.GetTile(12, 9)
        enTile = map.GetTile(10, 9)

        self.begin_capturing_logging()
        analysis = ArmyAnalyzer(map, map.GetTile(10, 14), enTile)
        if debugMode:
            self.render_army_analyzer(map, analysis)

        plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)
        # plan = self.get_interception_plan(map, general, enemyGeneral, enTile=enTile)

        if debugMode:
            self.render_intercept_plan(map, plan)

        path, value, turnsUsed = self.get_interceptor_path(plan, 10, 13, 10, 15)
        if path is not None:
            self.assertLess(value, 2, "should not have found a path just heading back to general")
        path, value, turnsUsed = self.get_interceptor_path(plan, 10, 11, 10, 14)
        if path is not None:
            self.assertLess(value, 2, "should not have found a path just heading back to general")
        path, value, turnsUsed = self.get_interceptor_path(plan, 10, 10, 10, 14)
        if path is not None:
            self.assertLess(value, 2, "should not have found a path just heading back to general")

    def test_should_split_when_chasing_threat_around_obstacle(self):
        for i in range(4):
            debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
            mapFile = 'GameContinuationEntries/should_split_when_chasing_threat_around_obstacle___67Nv7tPW1---0--205.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 205, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=205)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            self.begin_capturing_logging()
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
            self.assertIsNone(winner)

            self.assertNoRepetition(simHost)

            enTile = playerMap.GetTile(8, 18)

            if enTile.player != general.player:
                self.assertLess(enTile.army, 5)

    def test_should_intercept_at_inbound_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_allow_opp_to_walk_all_over_territory___Hn8ec1Na9---0--283.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=283)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,11->1,11->1,8->2,8->2,7->4,7->4,6->5,6->5,3->6,3->6,2->5,2')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.info_render_board_analysis_choke_widths = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        chokeTile = playerMap.GetTile(2, 7)
        self.assertEqual(general.player, chokeTile.player)
        self.assertGreater(chokeTile.army, 19, "should have met the army at the choke")

    def test_should_not_allow_opp_to_walk_all_over_territory(self):
        for enPath in [
            '4,11->1,11->1,8->2,8->2,7->4,7->4,6->5,6->5,3->6,3->6,2->5,2',
            '4,11->1,11->1,8->6,8->6,7->5,7z->4,7->4,6->5,6->5,3->6,3->6,2->5,2',
        ]:
            with self.subTest(enPath=enPath):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_not_allow_opp_to_walk_all_over_territory___Hn8ec1Na9---0--283.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=283)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                bot = self.get_debug_render_bot(simHost, general.player)
                bot.info_render_board_analysis_choke_widths = True
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
                self.assertIsNone(winner)

                self.assertGreater(self.get_tile_differential(simHost), 0, "should have intercepted and then caught up on tiles")
    
    def test_should_only_intercept_threats_that_are_moving_the_correct_direction(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_only_intercept_threats_that_are_moving_the_correct_direction___ej-YIq-8I---1--223.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=223)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)

# 22-12 with everything bad
# 11f 19p - hacked defense intercept
# 10-20 with defense -1 instead of -2
    
    def test_should_intercept_not_loop(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_not_loop___s7T8wCUyU---1--404.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 404, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=404)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)

        city = playerMap.GetTile(7, 11)
        self.assertEqual(general.player, city.player)

    def test_should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns(self):
        for enPath in [
            '8,5->8,4->9,4->9,3->14,3->14,2',
            '8,5->8,6->14,6',
            '8,5->8,6->9,6->9,3->11,3->11,4'
        ]:
            with self.subTest(enPath=enPath):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/should_intercept_inbound_army_on_edge_when_would_have_10_recapture_turns___l7Y-HnzES---0--181.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 181, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 16)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=181)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '4,8->4,6->6,6->6,5->8,5')
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=19)
                self.assertIsNone(winner)

                self.assertGreater(self.get_tile_differential(simHost), 10)

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

        val, turnsUsed = interceptor._get_path_value(path, searchingPlayer=general.player, targetPlayer=enemyGeneral.player, turnsLeftInCycle=19, includeRecaptureEffectiveStartDist=1)
        # we move 6 to intercept, they move 6 forward to 7,5. No collision yet.
        # We collide with over 30 more army with them, giving us full recapture turns.
        self.assertEqual(19, turnsUsed)

        # Since we captured 0 other tiles, the value of the intercept should equal number of remaining recapture turns * 2, which should be 22
        self.assertGreater(val, 21)

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

        self.assertEqual(map.GetTile(14, 6), plan.best_enemy_threat.path.tail.tile)

    def test_should_identify_best_meeting_point_in_intercept_options(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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

        bestOpt = None
        bestOptAmt = 0
        gatherDepth = 20
        for turn, option in plan.intercept_options.items():
            val, path = option
            if path.length < gatherDepth and val > bestOptAmt:
                logbook.info(f'NEW BEST INTERCEPT OPT {val} -- {str(path)}')
                bestOpt = path
                bestOptAmt = val

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
        self.assertEqual(2, len(plan.threats))

        if debugMode:
            self.render_intercept_plan(rawMap, plan)

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
            logbook.info(f'NEW BEST INTERCEPT OPT {val} -- {str(path)}')
            bestOpt = path
            bestOptAmt = val

        self.assertEqual(map.GetTile(2, 7), bestOpt.tail.tile)

    def test_should_recognize_multi_threat_and_intercept_at_choke(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)
        map.GetTile(1, 8).army = 1
        map.GetTile(1, 8).player = 0
        map.GetTile(1, 9).army = 75
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=289)
        rawMap.GetTile(1, 8).army = 1
        rawMap.GetTile(1, 8).player = 0
        rawMap.GetTile(1, 9).army = 75

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,9->1,8->2,8->2,7')
        # simHost.queue_player_moves_str(general.player, '2,5->2,8') # proof

        bot = self.get_debug_render_bot(simHost, general.player)
        bot.targetingArmy = bot.get_army_at_x_y(1, 9)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        self.assertEqual(playerMap.GetTile(2, 7).player, general.player)

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

        path, val, turns = self.get_interceptor_path(interception, 2, 5, 2, 8)

        self.assertEqual(1, interception.common_intercept_chokes[map.GetTile(2, 7)], 'all routes can be intercepted in one extra move from this point')
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        # the raw econ differential from this play is +14 econ (-9 -> +5) however it prevents a huge amount of enemy damage as well, so should be calculated as blocking 20 additional econ damage from opponent
        # 14 + 20 should be a value of 36
        self.assertEqual(34, val, 'prevents 20 enemy damage and also recaptures 14 econ worth of tiles')
        # TODO CONTINUE

    def test_should_recognize_multi_threat_and_intercept_at_choke__prevent_right_and_up(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=289)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '1,8->6,8->6,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertEqual(playerMap.GetTile(6, 7).player, general.player)

    def test_should_recognize_multi_threat_and_intercept_at_choke__unit_test_does_not_value_incoming_collisions_that_dont_prevent_caps_to_round_end(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_multi_threat_and_intercept_at_choke___Human.exe-TEST__efebcb16-d770-4d80-ac54-b9c37c8e7bea---0--289.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 289, fill_out_tiles=True)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        path, val, turns = self.get_interceptor_path(interception, 0, 8, 1, 8)

        if path is not None:  # not even finding this as an intercept is also valid, so only fail if it is found AND its value isn't 0
            self.assertEqual(0, val, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path(interception, 2, 5, 2, 7)
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

        path, val, turns = self.get_interceptor_path(interception, 0, 8, 1, 8)

        if path is not None:  # not even finding this as an intercept is also valid, so only fail if it is found AND its value isn't 0
            self.assertEqual(0, val, 'does not prevent enemy from recapturing till end of cycle so slamming a 3 into the tile does nothing this cycle.')

        path, val, turns = self.get_interceptor_path(interception, 2, 5, 2, 7)
        self.assertIsNotNone(path)
        self.assertEqual(11, turns, 'max value per turn should be the full turns')
        self.assertEqual(18, val, 'prevents enemy damage and also recaptures')

    def test_should_defend_forward_city_against_incoming_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        mapFile = 'GameContinuationEntries/should_defend_forward_city_against_incoming_threat___SejdBT5Vp---1--370.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 370, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=370)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,4->11,6->6,6->6,8->4,8->4,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        city = playerMap.GetTile(4, 9)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertEqual(general.player, city.player, 'should never lose control of the city.'))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

    def test_should_kill_point_blank_army_lul(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=133)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,6->7,7->7,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertEqual(general.player, playerMap.GetTile(7, 7).player)

    def test_should_recognize_diverging_path_around_mountain_as_non_intercept_chokes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=False)

        # map.GetTile(6, 7).isMountain = False
        # map.update_reachable()

        analysis = ArmyAnalyzer(map, map.GetTile(5, 17), map.GetTile(7, 6))
        analysis.scan()
        if debugMode:
            self.render_army_analyzer(map, analysis)
        interceptWidth = analysis.interceptChokes.get(map.GetTile(6, 6), None)
        # self.assertEqual(4, interceptWidth)

        interception = self.get_interception_plan(map, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(map, interception)

        value, turns, bestPath = self.get_best_intercept_option(interception)
        self.assertEqual(6, bestPath.start.tile.x)
        self.assertEqual(6, bestPath.start.tile.y)

        path, val, turns = self.get_interceptor_path(interception, 6, 6, 7, 6)
        self.assertIsNotNone(path)

        path, val, turns = self.get_interceptor_path(interception, 5, 6, 7, 6)
        self.assertIsNone(path)

        self.assertNotInterceptChoke(interception, map, 6, 6)
        self.assertNotInterceptChoke(interception, map, 7, 7)

    def test_should_not_blow_up(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_blow_up___U7l4Nbv2D---1--124.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 124, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=124)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_return_to_save_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_return_to_save_general___DiPqVAsND---0--282.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 283, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=283)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,7->1,7->1,8')
        # simHost.queue_player_moves_str(general.player, '4,9->1,9->1,8')  # saves
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=4)
        self.assertIsNone(winner)
    
    def test_should_not_chase_when_gets_self_killed(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_chase_when_gets_self_killed___DiPqVAsND---0--281.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 281, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=281)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,8->4,7->1,7->1,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_one_move_intercept_to_prevent_expansion_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_one_move_intercept_to_prevent_expansion_threat___DiPqVAsND---0--280.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 280, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=280)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,9->4,7->1,7->1,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        self.assertEqual(general.player, playerMap.GetTile(4, 7).player)

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
    
    def test_should_intercept_large_incoming_at_choke_even_with_not_quite_enough(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_large_incoming_at_choke_even_with_not_quite_enough___DiPqVAsND---0--273.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 273, fill_out_tiles=True)
        enemyGeneral.army = 20

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=273)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,10->7,10->7,9->5,9->5,3->2,3->2,8->1,8  12,7->12,8  8,12->7,12  8,4->8,2->6,2')
        # simHost.queue_player_moves_str(general.player, '4,4->5,4  3,9->6,9')  # proof this is doable

        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=27)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost), 20, "should not have lost a ton of econ by letting enemy walk around")
    
    def test_should_block_to_the_left(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_block_to_the_left__ideally_with_move_half___xv-dhECnq---0--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,8->13,8->13,14->12,14->12,16')
        # simHost.queue_player_moves_str(general.player, '15,9->14,9z->13,9')  # proof this works
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        tile = playerMap.GetTile(13, 12)
        self.assertEqual(general.player, tile.player)

        self.assertEqual(6, self.get_tile_differential(simHost), "should have spent 2 turns blocking with a move-half, then spent the rest of the time capturing")

    def test_should_block_to_the_left__with_move_half(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_block_to_the_left__ideally_with_move_half___xv-dhECnq---0--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,8->13,8->13,14->12,14->12,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)

        tile = playerMap.GetTile(13, 12)
        self.assertLess(tile.army, 4)
        self.assertGreater(playerMap.GetTile(15, 9).army, 35, "should have move-halfed")

#17f 18p - initial intercept/expand impl
    def test_should_not_intercept_when_more_economic_to_just_keep_expanding__unit_test(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gracefully_handle_deviating_en_expansion_path___YuXhnQtCE---1--142.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 142, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=False, turn=142)
        self.reset_general(rawMap, enemyGeneral)

        plan = self.get_interception_plan(rawMap, general, enemyGeneral)

        if debugMode:
            self.render_intercept_plan(rawMap, plan)

        self.assertEqual(1, len(plan.threats), "only econ threat")

        bestVal, bestTurns, bestPath = self.get_best_intercept_option(plan)
        self.assertLess(bestVal, 7, "should not overvalue any of these intercepts")
        self.assertLess(bestVal/bestTurns, 0.5, 'should not think any of these have great value per turn.')

        self.assertEqual(map.GetTile(9, 8), bestPath.tail.tile)

    def test_should_not_intercept_when_more_economic_to_just_keep_expanding(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gracefully_handle_deviating_en_expansion_path___YuXhnQtCE---1--142.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 142, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=142)
        self.reset_general(rawMap, enemyGeneral)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,8->13,8->13,9->12,9->12,8->11,8')
        # proof
        # simHost.queue_player_moves_str(general.player, '6,6->6,5->15,5')  # THIS gets 20
        # BAD simHost.queue_player_moves_str(general.player, '6,6->6,8->13,8')  # THIS only gets 15
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(19, simHost)
    
    def test_should_not_override_defense_with_intercept_for_wrong_army_lol(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_override_defense_with_intercept_for_wrong_army_lol___ObO-Yfd3_---0--629.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 629, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=629)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,6->8,6->8,3->7,3->7,2->4,2->4,3')
        simHost.sim.ignore_illegal_moves = True
        bot = self.get_debug_render_bot(simHost, general.player)
        army = bot.get_army_at_x_y(19, 12)
        army.expectedPaths.append(Path.from_string(rawMap, '19,12->17,12->17,10->15,10->15,11->12,11->12,10->11,10->11,8->8,8->8,5->7,5->7,4->6,4->6,2->4,2->4,3'))
        army.expectedPaths.append(Path.from_string(rawMap, '19,12->17,12->17,7->16,7->16,6->14,6->14,4->13,4->13,2->12,2->12,1->6,1'))
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_override_defense_with_intercept_for_wrong_army_lol__longer(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_override_defense_with_intercept_for_wrong_army_lol___ObO-Yfd3_---0--624.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 624, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=624)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        ArmyInterceptor.DEBUG_BYPASS_BAD_INTERCEPTIONS = True
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,10->11,6->10,6->8,6->8,3->7,3->7,2->4,2->4,3')
        simHost.queue_player_moves_str(general.player, '6,1->9,1')
        simHost.sim.ignore_illegal_moves = True
        bot = self.get_debug_render_bot(simHost, general.player)
        army = bot.get_army_at_x_y(19, 12)
        army.expectedPaths.append(Path.from_string(bot._map, '19,12->17,12->17,10->15,10->15,11->12,11->12,10->11,10->11,8->8,8->8,5->7,5->7,4->6,4->6,2->4,2->4,3'))
        army.expectedPaths.append(Path.from_string(bot._map, '19,12->17,12->17,10->15,10->15,11->12,11->12,10->11,10->11,8->8,8->8,5->7,5->7,4->6,4->6,2->5,2->5,1->3,1->3,0->2,0'))
        army.expectedPaths.append(Path.from_string(bot._map, '19,12->17,12->17,7->16,7->16,6->14,6->14,4->13,4->13,2->12,2->12,1->6,1'))

        army2 = bot.get_army_at_x_y(11, 10)
        army2.expectedPaths.append(Path.from_string(bot._map, '11,10->11,6->10,6->8,6->8,3->7,3->7,2->6,2->6,1'))
        army2.expectedPaths.append(Path.from_string(bot._map, '11,10->11,6->10,6->8,6->8,3->7,3->7,2->4,2->4,3'))
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
        self.assertIsNone(winner)
    
    def test_should_not_use_defensive_intercept_tile_for_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_use_defensive_intercept_tile_for_expansion___cnRTRKwkJ---1--238.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 238, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=238)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,1->6,1->6,2->5,2->5,5->9,5->9,6->7,6->7,7->9,7->9,8->7,8->8,8->8,9->7,9->7,10->10,10->10,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=32)
        self.assertIsNone(winner)
    
    def test_should_not_take_longer_intercept_than_necessary_defense_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for shortenDist in [True, False]:
            with self.subTest(shortenDist=shortenDist):
                mapFile = 'GameContinuationEntries/should_not_take_longer_intercept_than_necessary_defense_moves___zBpkynBBC---1--301.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 301, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=301)

                if shortenDist:
                    map.GetTile(15, 7).army = 14
                    map.GetTile(14, 7).army = 1
                    rawMap.GetTile(15, 7).army = 14
                    rawMap.GetTile(14, 7).army = 1

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '15,6->17,6->17,7')
                simHost.queue_player_moves_str(general.player, '17,7->16,7')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
                self.assertIsNone(winner)
