import time

import networkx as nx

import DebugHelper
import Gather
from Algorithms import WatchmanRouteUtils, TravelingSalesmanUtils
from Models import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import TargetStyle, PathColorer
from base.client.map import MapBase
from base.client.tile import TILE_MOUNTAIN, TILE_EMPTY
from bot_ek0x45 import EklipZBot


class WatchmanRouteUtilsTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.info_render_centrality_distances = True
        Gather.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True
        bot.info_render_expansion_matrix_values = True
        # bot.info_render_general_undiscovered_prediction_values = True
        bot.info_render_leaf_move_values = True

        return bot
    
    def test_a_star_watchman_route_problem_should_produce_optimal_result(self):
        # Bot needs to comprehend that moving down wins the race
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_dive_corner_for_near_100_percent_kill_chance_instead_of_dying___XWHQOYv7I---1--480.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 480, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=480)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  5,14->7,14->7,10->10,10->10,9->11,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        #
        # self.begin_capturing_logging()
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

        startTile = self.get_player_largest_tile(simHost.sim, general.player)
        toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.1)

        self.begin_capturing_logging()
        startTime = time.perf_counter()
        astar_wrp = WatchmanRouteUtils.BasicAStarWRP(startTile, playerMap, set(toReveal))
        tilePath = astar_wrp.solve()
        completedTime = time.perf_counter() - startTime

        path = Path()
        for t in tilePath:
            path.add_next(t)

        if debugMode:
            # vi = self.get_renderable_view_info(playerMap)
            vi = bot.viewInfo
            for t in toReveal:
                vi.add_targeted_tile(t, TargetStyle.GREEN)

            vi.color_path(PathColorer(path, 255, 255, 0, 255, alphaDecreaseRate=0))

            self.render_view_info(playerMap, vi, f'WRP PATH LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}')

        self.assertLess(completedTime, 0.004, 'shouldnt take TOO long to run for such a small input')
        self.assertEqual(10, path.length, 'optimally the path shouldnt need to be longer than this!')

    def test_a_star_should_find_optimal_route_on_larger_search_area(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 62 seconds for 20
        for i in range(20):
            MapBase.DO_NOT_RANDOMIZE = False
            mapFile = 'GameContinuationEntries/should_find_optimal_route_on_larger_search_area___oB7buwxvM---1--343.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            # self.begin_capturing_logging()
            # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

            startTile = self.get_player_largest_tile(simHost.sim, general.player)
            toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.1)

            self.begin_capturing_logging()
            startTime = time.perf_counter()
            aStarWrp = WatchmanRouteUtils.BasicAStarWRP(startTile, playerMap, set(toReveal))
            path = aStarWrp.solve()
            completedTime = time.perf_counter() - startTime

            try:
                self.assertEqual(25, path.length, 'optimally the path shouldnt need to be longer than this! Refer to the dumb A Star test above this one that outputs the true optimal 25 len path.')
                self.assertLess(completedTime, 5.004, 'shouldnt take TOO long to run for such a large input')
            except Exception as ex:
                if debugMode:
                    # vi = self.get_renderable_view_info(playerMap)
                    vi = bot.viewInfo
                    for t in toReveal:
                        vi.add_targeted_tile(t, TargetStyle.GREEN)

                    vi.color_path(PathColorer(path, 255, 255, 0, 255, alphaDecreaseRate=0))

                    self.render_view_info(playerMap, vi, f'WRP A STAR LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}')
                raise
            self.stop_capturing_logging()

    def test_a_star_should_find_optimal_route_on_larger_search_area__single(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_optimal_route_on_larger_search_area___oB7buwxvM---1--343.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        #
        # self.begin_capturing_logging()
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

        startTile = self.get_player_largest_tile(simHost.sim, general.player)
        toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.1)

        self.begin_capturing_logging()
        startTime = time.perf_counter()
        astar_wrp = WatchmanRouteUtils.BasicAStarWRP(startTile, playerMap, set(toReveal))
        path = astar_wrp.solve()
        completedTime = time.perf_counter() - startTime

        if debugMode:
            # vi = self.get_renderable_view_info(playerMap)
            vi = bot.viewInfo
            for t in toReveal:
                vi.add_targeted_tile(t, TargetStyle.GREEN)

            vi.color_path(PathColorer(path, 255, 255, 0, 255, alphaDecreaseRate=0))

            self.render_view_info(playerMap, vi, f'WRP A STAR LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}')

        self.assertLess(completedTime, 5.004, 'shouldnt take TOO long to run for such a large input')
        self.assertEqual(25, path.length, 'optimally the path shouldnt need to be longer than this!')

    def test_seiraf_should_find_optimal_route_on_larger_search_area(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(20):
            MapBase.DO_NOT_RANDOMIZE = False
            mapFile = 'GameContinuationEntries/should_find_optimal_route_on_larger_search_area___oB7buwxvM---1--343.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            # self.begin_capturing_logging()
            # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

            startTile = self.get_player_largest_tile(simHost.sim, general.player)
            toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.1)

            self.begin_capturing_logging()
            startTime = time.perf_counter()
            pivot_wrp = WatchmanRouteUtils.PivotWRP(startTile, playerMap, set(toReveal))
            path = pivot_wrp.solve()
            completedTime = time.perf_counter() - startTime

            try:
                self.assertNotIn(playerMap.GetTile(7, 0), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')
                self.assertNotIn(playerMap.GetTile(6, 1), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')

                self.assertLess(completedTime, 5.004, 'shouldnt take TOO long to run for such a large input')
                self.assertEqual(25, path.length, 'optimally the path shouldnt need to be longer than this! Refer to the dumb A Star test above this one that outputs the true optimal 25 len path.')
            except Exception as ex:
                if debugMode:
                    infoString = f'ERR PivotWRP LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}'
                    self.render_pivot_wrp(bot, pivot_wrp, infoString, path)
                raise
            self.stop_capturing_logging()

    def test_seiraf_should_find_optimal_route_on_larger_search_area__single(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_optimal_route_on_larger_search_area___oB7buwxvM---1--343.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # self.begin_capturing_logging()
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

        startTile = self.get_player_largest_tile(simHost.sim, general.player)
        toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.1)

        self.begin_capturing_logging()
        startTime = time.perf_counter()
        pivot_wrp = WatchmanRouteUtils.PivotWRP(startTile, playerMap, set(toReveal))
        path = pivot_wrp.solve()
        completedTime = time.perf_counter() - startTime

        self.assertNotIn(playerMap.GetTile(7, 0), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')
        self.assertNotIn(playerMap.GetTile(6, 1), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')

        if debugMode:
            infoString = f'PivotWRP LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}'
            self.render_pivot_wrp(bot, pivot_wrp, infoString, path)

        self.assertLess(completedTime, 5.004, 'shouldnt take TOO long to run for such a large input')
        self.assertEqual(25, path.length, 'optimally the path shouldnt need to be longer than this! Refer to the dumb A Star test above this one that outputs the true optimal 25 len path.')

    def test_seiraf_should_respect_cutoff_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_optimal_route_on_larger_search_area___oB7buwxvM---1--343.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        #
        # self.begin_capturing_logging()
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

        startTile = self.get_player_largest_tile(simHost.sim, general.player)
        toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.01)

        self.begin_capturing_logging()
        startTime = time.perf_counter()
        pivot_wrp = WatchmanRouteUtils.PivotWRP(startTile, playerMap, set(toReveal))
        path = pivot_wrp.solve(cutoffTime=startTime + 0.02)
        completedTime = time.perf_counter() - startTime

        self.assertNotIn(playerMap.GetTile(7, 0), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')
        self.assertNotIn(playerMap.GetTile(6, 1), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')

        if debugMode:
            # vi = self.get_renderable_view_info(playerMap)
            vi = bot.viewInfo
            for t in toReveal:
                vi.add_targeted_tile(t, TargetStyle.GREEN)
            for t in pivot_wrp.pivot_set:
                vi.add_targeted_tile(t, TargetStyle.RED, radiusReduction=8)
            for t in pivot_wrp.frontiers:
                vi.add_targeted_tile(t, TargetStyle.YELLOW, radiusReduction=10)
            # for t in pivot_wrp.mst_set:
            #     vi.add_map_zone(pivot_wrp.mst_set, color=(150, 150, 255), alpha=60)
                # vi.add_targeted_tile(t, TargetStyle.YELLOW, radiusReduction=10)

            vi.color_path(PathColorer(path, 255, 255, 0, 255, alphaDecreaseRate=0))

            self.render_view_info(playerMap, vi, f'PivotWRP LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}')

        self.assertLess(completedTime, 5.004, 'shouldnt take TOO long to run for such a large input')
        self.assertEqual(25, path.length, 'optimally the path shouldnt need to be longer than this! Refer to the dumb A Star test above this one that outputs the true optimal 25 len path.')

    def test_iterative_backoff_should_find_optimal_route_on_larger_search_area(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for i in range(20):
            MapBase.DO_NOT_RANDOMIZE = False
            mapFile = 'GameContinuationEntries/should_find_optimal_route_on_larger_search_area___oB7buwxvM---1--343.txtmap'
            map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            simHost.queue_player_moves_str(enemyGeneral.player, 'None')
            bot = self.get_debug_render_bot(simHost, general.player)
            playerMap = simHost.get_player_map(general.player)

            # self.begin_capturing_logging()
            # winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)

            startTile = self.get_player_largest_tile(simHost.sim, general.player)
            toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=0.1)

            timeLimit = 0.525

            self.begin_capturing_logging()
            startTime = time.perf_counter()
            pivot_wrp = WatchmanRouteUtils.PivotIterativeWRP(startTile, playerMap, set(toReveal))
            path = pivot_wrp.solve(cutoffTime=startTime + timeLimit)
            completedTime = time.perf_counter() - startTime

            nonIterStartTime = time.perf_counter()
            nonIterPivot_wrp = WatchmanRouteUtils.PivotWRP(startTile, playerMap, set(toReveal))
            nonIterPath = nonIterPivot_wrp.solve(cutoffTime=nonIterStartTime + timeLimit)
            nonIterCompletedTime = time.perf_counter() - nonIterStartTime

            try:
                self.assertNotIn(playerMap.GetTile(7, 0), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')
                self.assertNotIn(playerMap.GetTile(6, 1), pivot_wrp.frontiers, 'Must have gone through 7,1 already to reach this, it can be pruned.')

                self.assertLess(completedTime, 5.004, 'shouldnt take TOO long to run for such a large input')
                self.assertEqual(25, path.length, 'optimally the path shouldnt need to be longer than this! Refer to the dumb A Star test above this one that outputs the true optimal 25 len path.')
            except Exception as ex:
                if debugMode:
                    infoString = f'ERR PivotIterativeWRP LENGTH {path.length} FOUND IN {completedTime:.4f}s! {path}'
                    self.render_pivot_wrp(bot, pivot_wrp, infoString, path)
                raise
            self.stop_capturing_logging()

    def render_pivot_wrp(self, bot: EklipZBot, pivot_wrp: WatchmanRouteUtils.PivotWRP, infoString: str, path: Path | None = None):
        map = bot._map
        # vi = self.get_renderable_view_info(playerMap)
        vi = bot.viewInfo
        for t in pivot_wrp.to_discover:
            vi.add_targeted_tile(t, TargetStyle.GREEN)
        for t in pivot_wrp.pivot_set:
            vi.add_targeted_tile(t, TargetStyle.RED, radiusReduction=8)
        for t in pivot_wrp.frontiers:
            vi.add_targeted_tile(t, TargetStyle.YELLOW, radiusReduction=10)
        # for t in pivot_wrp.mst_set:
        #     vi.add_map_zone(pivot_wrp.mst_set, color=(150, 150, 255), alpha=60)
        # for t in pivot_wrp.tsp_set:
        #     vi.add_map_zone(pivot_wrp.tsp_set, color=(150, 150, 255), alpha=60)
        # vi.add_targeted_tile(t, TargetStyle.YELLOW, radiusReduction=10)

        if path:
            vi.color_path(PathColorer(path, 255, 255, 0, 255, alphaDecreaseRate=0))

        # start = time.perf_counter()
        # nodes = [n.tile_index for n in pivot_wrp.pivot_set]
        # nodes.append(pivot_wrp.start.tile_index)
        # steiner: nx.Graph = nx.approximation.steiner_tree(pivot_wrp.nxGraph, nodes, method='mehlhorn')
        # totalWeight = steiner.size(weight='weight')
        # vi.add_info_line(f'steiner weight {totalWeight} in {time.perf_counter() - start:.5f}')

        # # for edge in pivot_wrp.nxGraph.edges(data=True):
        # for edge in steiner.edges(data=True):
        #     fromIdx, toIdx, data = edge
        #     fromTile = map.get_tile_by_tile_index(fromIdx)
        #     toTile = map.get_tile_by_tile_index(toIdx)
        #     weight = data["weight"]
        #
        #     vi.draw_diagonal_arrow_between(fromTile, toTile, f'{weight}', color=hash(f'{fromTile}{toTile}{weight}'), alpha=100, bidir=True, colorFloor=100)

        # Testing arrow render
        # vi.draw_diagonal_arrow_between(bot.general, bot.targetPlayerExpectedGeneralLocation, f'down to up')
        # vi.draw_diagonal_arrow_between(map.GetTile(11, 2), map.GetTile(14, 14), f'up to down')
        # vi.draw_diagonal_arrow_between(map.GetTile(12, 14), map.GetTile(17, 13), f'left to right')
        # vi.draw_diagonal_arrow_between(map.GetTile(17, 16), map.GetTile(12, 18), f'right to left')

        # tspPath = pivot_wrp.get_tsp_path()
        #
        # vi.color_path(PathColorer(tspPath, 0, 255, 0, 150, alphaDecreaseRate=0))

        self.render_view_info(map, vi, infoString)
