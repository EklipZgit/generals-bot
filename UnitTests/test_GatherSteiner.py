import random
import time

import logbook

import GatherSteiner
import GatherUtils
from Algorithms import TileIslandBuilder, MapSpanningUtils
from Interfaces.MapMatrixInterface import EmptySet
from MapMatrix import MapMatrix, MapMatrixSet
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo, TargetStyle
from base.client.map import MapBase
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot


class GatherSteinerUnitTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True
        bot.info_render_gather_values = True
        bot.info_render_expansion_matrix_values = True
        bot.gather_use_pcst = True

        return bot

    def test_should_build_steiner_prize_collection(self):
        """
        This algo seems useless. Why? Because it pretty much just returns all the nodes in your part of the tree above whatever minimum weight you set, and connects the subtrees if they're not connected (which is super cheap to do ourselves) and costs a lot of compute.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        steinerMatrix = GatherSteiner.get_prize_collecting_gather_mapmatrix(map, general.player)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_division(steinerMatrix, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_prize_collection_at_enemy_general(self):
        """
        This algo currently doesn't output granular node counts.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        steinerMatrix = GatherSteiner.get_prize_collecting_gather_mapmatrix(map, general.player, enemyGeneral, targetTurns=42)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_division(steinerMatrix, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner no weights???')

    def test_should_build_steiner_prize_collection_at_enemy_general__tile_weights(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()

        steinerMatrix = GatherSteiner.get_prize_collecting_gather_mapmatrix(map, general.player, enemyGeneral, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix, targetTurns=28)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.bottomLeftGridText = gatherMatrix
        viewInfo.bottomRightGridText = captureMatrix
        viewInfo.add_map_division(steinerMatrix, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_prize_collection_at_enemy_general__large__tile_weights(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()

        steinerMatrix = GatherSteiner.get_prize_collecting_gather_mapmatrix(map, general.player, enemyGeneral, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix, targetTurns=57)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.bottomLeftGridText = gatherMatrix
        viewInfo.bottomRightGridText = captureMatrix
        viewInfo.add_map_division(steinerMatrix, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_prize_collection_at_enemy_general__large__tile_weights__gatherUtils(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()

        gathPlan = GatherUtils.gather_approximate_turns_to_tiles(map, [enemyGeneral], approximateTargetTurns=57, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.gatherNodes = gathPlan.root_nodes
        viewInfo.bottomLeftGridText = gatherMatrix
        viewInfo.bottomRightGridText = captureMatrix
        viewInfo.add_map_division(gathPlan.tileSet, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_prize_collection_at_enemy_general__large__tile_weights__gatherUtils__multi_tile(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()

        otherTile = playerMap.GetTile(15, 1)
        gathPlan = GatherUtils.gather_approximate_turns_to_tiles(map, [enemyGeneral, otherTile], approximateTargetTurns=57, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.gatherNodes = gathPlan.root_nodes
        viewInfo.bottomLeftGridText = gatherMatrix
        viewInfo.bottomRightGridText = captureMatrix
        viewInfo.add_map_division(gathPlan.tileSet, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_prize_collection_at_enemy_general__large__tile_weights__gatherUtils__multi_tile_short(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()

        otherTile = playerMap.GetTile(15, 1)
        gathPlan = GatherUtils.gather_approximate_turns_to_tiles(map, [enemyGeneral, otherTile], approximateTargetTurns=30, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix)

        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.gatherNodes = gathPlan.root_nodes
            viewInfo.bottomLeftGridText = gatherMatrix
            viewInfo.bottomRightGridText = captureMatrix
            viewInfo.add_map_division(gathPlan.tileSet, (0, 255, 255), 200)
            self.render_view_info(map, viewInfo, 'steiner???')
        self.assertGreaterEqual(gathPlan.gathered_army, 250)

    def test_should_build_steiner_prize_collection_at_enemy_general__large__tile_weights__gatherUtils__multi_tile_short__other(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()

        otherTile = playerMap.GetTile(15, 1)
        gathPlan = GatherUtils.gather_approximate_turns_to_tiles(map, [enemyGeneral, otherTile], approximateTargetTurns=43, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix)

        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.gatherNodes = gathPlan.root_nodes
            viewInfo.bottomLeftGridText = gatherMatrix
            viewInfo.bottomRightGridText = captureMatrix
            viewInfo.add_map_division(gathPlan.tileSet, (0, 255, 255), 200)
            self.render_view_info(map, viewInfo, 'steiner???')
        self.assertGreaterEqual(gathPlan.gathered_army, 250)

    def test_should_build_steiner_prize_collection_at_enemy_general__large__tile_weights__gatherUtils__never_exceed(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general__LARGE_gather___Sl5q9W333---b--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        self.begin_capturing_logging()
        otherTile = playerMap.GetTile(15, 1)

        for targetTurns in range(6, 130, 4):
            for maxTurnOffs in range(0, 10, 2):
                maxTurns = targetTurns + maxTurnOffs

                gathPlan = GatherUtils.gather_approximate_turns_to_tiles(map, [enemyGeneral, otherTile], approximateTargetTurns=targetTurns, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix, maxTurns=maxTurns)
                if gathPlan is None:
                    if targetTurns > 34:
                        self.fail(f'targetTurns {targetTurns}, maxTurns {maxTurns} produced NO gather plan')
                elif gathPlan.length > maxTurns:
                    if debugMode:
                        viewInfo = self.get_renderable_view_info(map)
                        viewInfo.gatherNodes = gathPlan.root_nodes
                        viewInfo.bottomLeftGridText = gatherMatrix
                        viewInfo.bottomRightGridText = captureMatrix
                        viewInfo.add_map_division(gathPlan.tileSet, (0, 255, 255), 200)
                        self.render_view_info(map, viewInfo, 'steiner???')
                    self.fail(f'targetTurns {targetTurns}, maxTurns {maxTurns} returned a gather plan length {gathPlan.length}')

    def test_bench_steiner(self):
        """NetworkX 43 ms here"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        # self.begin_capturing_logging()

        tiles = [
            map.GetTile(10, 5),
            map.GetTile(5, 3),
            map.GetTile(13, 4),
            map.GetTile(13, 1),
            map.GetTile(10, 0),
            map.GetTile(9, 15),
            map.GetTile(1, 16),
            map.GetTile(9, 7),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
        ]

        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        num = 1000

        results = []

        for faster in [True, False]:
            start = time.perf_counter()

            for i in range(num):
                steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player)

            total = time.perf_counter() - start
            results.append(f'faster {faster} took {total:.2f}s (avg {1000 * total / num:.2f}ms)')

        self.begin_capturing_logging()
        for result in results:
            logbook.info(result)

    def test_should_build_steiner(self):
        """NetworkX 43 ms here"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        tiles = [
            map.GetTile(10, 5),
            map.GetTile(5, 3),
            map.GetTile(13, 4),
            map.GetTile(13, 1),
            map.GetTile(10, 0),
            map.GetTile(9, 15),
            map.GetTile(1, 16),
            map.GetTile(9, 7),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
        ]

        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_division(steinerMatrix, (0, 255, 255), 200)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_respecting_value_matrix(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        tiles = [
            map.GetTile(10, 5),
            map.GetTile(5, 3),
            map.GetTile(13, 4),
            map.GetTile(13, 1),
            map.GetTile(10, 0),
            map.GetTile(9, 15),
            map.GetTile(1, 16),
            map.GetTile(9, 7),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
        ]

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        plan = GatherUtils.build_max_value_gather_tree_linking_specific_nodes(
            map,
            [enemyGeneral],
            tiles,
            general.player,
            gatherMatrix=gatherMatrix,
            captureMatrix=captureMatrix,
        )

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_division(plan.tileSet, (0, 255, 255), 200)
        viewInfo.gatherNodes = plan.root_nodes
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_respecting_large_amount_of_subtree_nodes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        viewInfo = self.get_renderable_view_info(map)

        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        tiles = []
        for island in random.sample(builder.tile_islands_by_player[general.player], 5):
            tiles.extend(island.tile_set)

        ourLargestTile = max(map.players[general.player].tiles, key=lambda t: t.army)
        ourSecondLargestTiles = max([t for t in map.players[general.player].tiles if t != ourLargestTile], key=lambda t: t.army)

        tiles.append(enemyGeneral)
        tiles.append(general)
        tiles.append(ourLargestTile)
        tiles.append(ourSecondLargestTiles)

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        steinerGatherStart = time.perf_counter()
        plan = GatherUtils.build_max_value_gather_tree_linking_specific_nodes(
            map,
            [enemyGeneral],
            tiles,
            general.player,
            gatherMatrix=gatherMatrix,
            captureMatrix=captureMatrix,
        )
        steinerGatherTime = time.perf_counter()-steinerGatherStart

        for tile in tiles:
            self.assertIn(tile, plan.tileSet)

        viewInfo.add_map_division(plan.tileSet, (0, 255, 255), 200)
        viewInfo.gatherNodes = plan.root_nodes
        self.render_view_info(map, viewInfo, f'steiner {plan.gather_turns}t in {steinerGatherTime:.5f} with {plan.gathered_army}')

    def test_network_x_steiner_should_be_faster_and_better_than_old_gather(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # viewInfo = self.get_renderable_view_info(map)
        viewInfo = bot.viewInfo

        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        tiles = []

        # force a roughly-best-gather similar to what our normal gather finds.
        tiles.extend(builder.tile_island_lookup[map.GetTile(12, 1)].tile_set)
        tiles.extend(builder.tile_island_lookup[map.GetTile(13, 4)].tile_set)
        tiles.extend(builder.tile_island_lookup[map.GetTile(10, 5)].tile_set)
        tiles.extend(builder.tile_island_lookup[map.GetTile(5, 1)].tile_set)
        tiles.extend(builder.tile_island_lookup[map.GetTile(7, 4)].tile_set)
        # tiles.extend(builder.tile_island_lookup[map.GetTile(6, 4)].tile_set)  # shouldn't need to ell it to include this
        tiles.append(enemyGeneral)

        # random islands
        # for island in random.sample(builder.tile_islands_by_player[general.player], 5):
        #     tiles.extend(island.tile_set)
        #
        # ourLargestTile = max(map.players[general.player].tiles, key=lambda t: t.army)
        # ourSecondLargestTiles = max([t for t in map.players[general.player].tiles if t != ourLargestTile], key=lambda t: t.army)
        #
        # tiles.append(enemyGeneral)
        # tiles.append(general)
        # tiles.append(ourLargestTile)
        # tiles.append(ourSecondLargestTiles)

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()
        equivMatrix = MapMatrix(map, 0.0)
        for t in map.get_all_tiles():
            if map.is_tile_on_team_with(t, general.player):
                equivMatrix.raw[t.tile_index] += gatherMatrix.raw[t.tile_index]
            else:
                equivMatrix.raw[t.tile_index] += captureMatrix.raw[t.tile_index]

        self.enable_search_time_limits_and_disable_debug_asserts()
        # self.render_map(map)
        self.begin_capturing_logging()
        steinerGatherStart = time.perf_counter()
        plan = GatherUtils.build_max_value_gather_tree_linking_specific_nodes(
            map,
            [enemyGeneral],
            tiles,
            general.player,
            gatherMatrix=gatherMatrix,
            captureMatrix=captureMatrix,
            prioritizeCaptureHighArmyTiles=False,
            viewInfo=viewInfo,
        )
        steinerGatherTime = time.perf_counter()-steinerGatherStart

        oldGathViewInfo = self.get_renderable_view_info(map)
        oldGatherStart = time.perf_counter()
        value, oldGatherNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
            map,
            [enemyGeneral],
            turns=plan.length,
            negativeTiles=None,
            searchingPlayer=general.player,
            # skipFunc=skipFunc,
            viewInfo=oldGathViewInfo,
            # skipTiles=skipTiles,
            distPriorityMap=bot.board_analysis.intergeneral_analysis.bMap,
            # priorityTiles=priorityTiles,
            useTrueValueGathered=True,
            includeGatherTreeNodesThatGatherNegative=False,
            incrementBackward=False,
            priorityMatrix=equivMatrix,
            shouldLog=False)
        oldGatherTime = time.perf_counter()-oldGatherStart
        oldPlan = GatherUtils.GatherCapturePlan.build_from_root_nodes(
            map,
            oldGatherNodes,
            negativeTiles=None,
            searchingPlayer=general.player,
            priorityMatrix=equivMatrix,
            includeCapturePriorityAsEconValues=False,
            includeGatherPriorityAsEconValues=False,
            viewInfo=oldGathViewInfo,
            cloneNodes=False
        )
        logbook.info(f'oldGather {oldGatherTime:.5f}s {value:.2f}v vs networkx-steiner-based {steinerGatherTime:.5f}s {plan.gathered_army:.2f}v')

        for tile in tiles:
            self.assertIn(tile, plan.tileSet)

        viewInfo.add_map_division(plan.tileSet, (0, 255, 255), 200)
        viewInfo.gatherNodes = plan.root_nodes
        steinerVt = plan.econValue/plan.length
        self.render_view_info(map, viewInfo, f'steiner {plan.length}t in {steinerGatherTime:.5f} with {plan.gathered_army} ({plan.gather_capture_points:.2f}c, {plan.econValue:.2f}e, {steinerVt:3f}vt)')

        oldGathViewInfo.gatherNodes = oldPlan.root_nodes
        oldPlanVt = oldPlan.econValue/oldPlan.length
        self.render_view_info(map, oldGathViewInfo, f'old {oldPlan.length}t in {oldGatherTime:.5f} with {oldPlan.gathered_army} ({oldPlan.gather_capture_points:.2f}c, {oldPlan.econValue:.2f}e, {oldPlanVt:3f}vt)')

        self.assertLess(steinerGatherTime, oldGatherTime, 'hopefully steiner is faster than old gather')
        self.assertGreaterEqual(steinerVt, oldPlanVt, 'hopefully steiner is SUPERIOR in v/t to old gather as well.')

    def test_should_build_steiner_tree__mimicking_what_i_want_gather_to_do(self):
        """
        my gathmax = 1.7ms
        networkx = 2.5ms
        my no-heap mst = 0.8ms
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=map, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()

        # self.render_map(map)
        self.begin_capturing_logging()

        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        ourCity = map.GetTile(7, 4)

        tiles = []
        for island in [
            builder.tile_island_lookup[map.GetTile(3, 5)],

            builder.tile_island_lookup[map.GetTile(1, 0)],

            builder.tile_island_lookup[map.GetTile(11, 0)],

            builder.tile_island_lookup[map.GetTile(12, 2)],

            builder.tile_island_lookup[map.GetTile(11, 3)]
        ]:
            # for island in random.sample(builder.tile_islands_by_player[general.player], 7):
            tiles.extend(island.tile_set)

        ourLargestTile = max(map.players[general.player].tiles, key=lambda t: t.army)
        ourSecondLargestTiles = max([t for t in map.players[general.player].tiles if t != ourLargestTile], key=lambda t: t.army)

        map.GetTile(9, 8).army = 30

        map.GetTile(8, 6).army = 100

        # tiles.append(enemyGeneral)
        tiles.append(general)
        tiles.append(map.GetTile(7, 4))
        tiles.append(ourLargestTile)
        tiles.append(ourCity)
        tiles.append(ourSecondLargestTiles)

        tiles.append(enemyGeneral)

        weightMod = MapMatrix(map, 0)
        for t in map.get_all_tiles():
            # if map.is_tile_friendly(t):
            weightMod[t] -= t.army
            # else:
            #     weightMod -= t.army

        viewInfo = self.get_renderable_view_info(map)

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)
        start = time.perf_counter()
        connectedTiles, missingRequired = MapSpanningUtils.get_max_gather_spanning_tree_set_from_tile_lists(map, tiles, bannedSet=EmptySet(), negativeTiles=EmptySet(), maxTurns=60, gatherPrioMatrix=gatherMatrix)
        logbook.info(f'GATHMAX mine tree builder took {time.perf_counter() - start:.5f}s')
        steinerMatrix = MapMatrixSet(map, connectedTiles)
        viewInfo.add_map_division(steinerMatrix, (150, 255, 150), 200)
        val = 0
        enVal = 0
        for t in connectedTiles:
            if map.is_tile_friendly(t):
                val += t.army - 1
            else:
                enVal += t.army + 1
        total = val - enVal
        for t in map.get_all_tiles():
            viewInfo.bottomRightGridText.raw[t.tile_index] = f'{gatherMatrix.raw[t.tile_index]:.3f}'
        self.render_view_info(map, viewInfo, f'Mine GATHMAX??? len {len(connectedTiles)} val {val} enVal {enVal} total {total}')

        viewInfo = self.get_renderable_view_info(map)
        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)
        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player, weightMod=weightMod, baseWeight=1000)
        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player, weightMod=weightMod, baseWeight=1000)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        viewInfo.add_map_division(steinerMatrix, (150, 255, 150), 200)
        val = 0
        enVal = 0
        for t in steinerNodes:
            if map.is_tile_friendly(t):
                val += t.army - 1
            else:
                enVal += t.army + 1
        total = val - enVal
        self.render_view_info(map, viewInfo, f'steiner??? len {len(steinerNodes)} val {val} enVal {enVal} total {total}')

        viewInfo = self.get_renderable_view_info(map)

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)
        start = time.perf_counter()
        connectedTiles, missingRequired = MapSpanningUtils.get_spanning_tree_from_tile_lists(map, tiles, bannedTiles=set())
        logbook.info(f'MY steiner tree builder took {time.perf_counter() - start:.5f}s')
        steinerMatrix = MapMatrixSet(map, connectedTiles)
        viewInfo.add_map_division(steinerMatrix, (150, 255, 150), 200)
        val = 0
        enVal = 0
        for t in connectedTiles:
            if map.is_tile_friendly(t):
                val += t.army - 1
            else:
                enVal += t.army + 1
        total = val - enVal
        self.render_view_info(map, viewInfo, f'Mine??? len {len(connectedTiles)} val {val} enVal {enVal} total {total}')


