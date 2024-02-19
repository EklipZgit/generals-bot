import inspect
import logbook
import os
import pathlib
import time
import traceback
import typing
import unittest

import EarlyExpandUtils
import SearchUtils
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from Tests.TestBase import TestBase
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase
from bot_ek0x45 import EklipZBot


class EarlyExpandUtilsTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_expansion_matrix_values = True
        bot.info_render_general_undiscovered_prediction_values = True
        bot.info_render_leaf_move_values = True

        return bot

    def check_does_not_produce_invalid_plan(
            self,
            mapFileName: str,
            turn: int = 1,
            noLog: bool = True
    ) -> typing.Tuple[MapBase, EarlyExpandUtils.ExpansionPlan]:
        map, general = self.load_turn_1_map_and_general(mapFileName)

        self.get_tiles_capped_on_50_count_and_reset_map(map, general)

        weightMap = self.get_opposite_general_distance_map(map, general)
        if turn != 1:
            map.turn = turn
            general.army = turn // 2 + 1

        EarlyExpandUtils.DEBUG_ASSERTS = True

        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=noLog)
        paths = plan.plan_paths
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)

        self.assertEqual(plan.tile_captures, value)
        return map, plan

    def get_tiles_capped_on_50_count_and_reset_map(self, map, general) -> int:
        playerTilesToMatchOrExceed = SearchUtils.count(map.pathableTiles, lambda tile: tile.player == general.player)
        map.turn = 1
        for tile in map.pathableTiles:
            if tile.isGeneral:
                tile.army = 1
            else:
                tile.army = 0
                tile.player = -1
        map.update()

        EarlyExpandUtils.DEBUG_ASSERTS = True

        return playerTilesToMatchOrExceed

    def render_expansion_plan(self, map: MapBase, plan: EarlyExpandUtils.ExpansionPlan):
        self.render_paths(map, plan.plan_paths, f'{str(plan.tile_captures)}')

    def test_takes_1_move_final_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 49
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        self.assertEqual(1, len(paths))
        path = paths[0]
        self.assertEqual(1, path.length)

    def test_get_start_expand_value__throws_on_invalid_plan_length__None(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 49
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        plan.plan_paths.append(None)
        threw = False
        try:
            value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, plan.plan_paths)
        except AssertionError:
            threw = True

        self.assertTrue(threw)

    def test_get_start_expand_value__throws_on_invalid_plan_length__Path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 49
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        plan.plan_paths[-1].add_next(plan.plan_paths[-1].tail.tile.movable[0])
        threw = False
        try:
            value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, plan.plan_paths)
        except AssertionError:
            threw = True

        self.assertTrue(threw)

    def test_takes_2_move_final_move_through_friendly_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 48
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        underTile = board[1][0]
        underTile.player = 0
        underTile.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        self.assertEqual(1, len(paths))
        path = paths[0]
        self.assertEqual(2, path.length)

    def test_waits_a_move_when_optimal_shorter(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 46
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(4)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(3, plan.tile_captures)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(3, value)
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_waits_a_move_when_optimal__turn_43(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 43
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(5)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 4

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(5, plan.tile_captures)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(5, value)
        # specifically, because this should cap the least tiles near general, we expect it to find the 1 path result
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))


    def test_waits_a_move_when_optimal__turn_45(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 45
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(4)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 3

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(4, plan.tile_captures)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(4, value)
        # specifically, because this should cap the least tiles near general, we expect it to find the 1 path result
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_does_something_near_end_of_turn_43(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # test both odd and even turns
        turn = 43
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(2)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        underTile = board[1][0]
        underTile.player = 0
        underTile.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        if debugMode:
            self.render_expansion_plan(map, plan)

        self.assertEqual(5, value)

    def test_does_something_near_end_of_turn_45(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # test both odd and even turns
        turn = 45
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(2)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 3

        underTile = board[1][0]
        underTile.player = 0
        underTile.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        if debugMode:
            self.render_expansion_plan(map, plan)

        # 45 down 1
        # 46 down 1 (cap 2,0 -- 3)
        # 47 right 1 (cap 2,1 -- 4)
        # 48 gen 2 right 1 (cap 1,0 -- 5)
        # 49 no op

        self.assertEqual(5, value)
        self.assertEqual(2, len(paths))

    def test_does_something_near_end_of_turn_47(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # test both odd and even turns
        turn = 47
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(2)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        underTile = board[1][0]
        underTile.player = 0
        underTile.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths

        if debugMode:
            self.render_expansion_plan(map, plan)

        self.assertEqual(4, plan.tile_captures)

    def test_does_something_near_end_of_turn_48(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # test both odd and even turns

        turn = 48
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(2)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 3

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        if debugMode:
            self.render_expansion_plan(map, plan)

        self.assertEqual(3, value)

    def test_finds_optimal__empty_board__middle(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
        general = board[12][12]
        general.isGeneral = True
        general.player = 0
        general.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__wall(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        walls = [(12, 0), (12, 24), (24, 12), (0, 12)]
        for xWall, yWall in walls:
            with self.subTest(xWall=xWall, yWall=yWall):
                board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
                general = board[yWall][xWall]
                general.isGeneral = True
                general.player = 0
                general.army = 1

                map = self.get_test_map(board, turn=turn)
                weightMap = self.get_opposite_general_distance_map(map, general)
                plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
                paths = plan.plan_paths
                value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
                self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner_1_from_edge(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        walls = [(0, 1), (0, 23), (24, 1), (24, 23), (1, 0), (1, 24), (23, 0), (23, 24)]
        for xWall, yWall in walls:
            with self.subTest(corner=(xWall, yWall)):
                board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
                general = board[yWall][xWall]
                general.isGeneral = True
                general.player = 0
                general.army = 1

                map = self.get_test_map(board, turn=turn)
                weightMap = self.get_opposite_general_distance_map(map, general)
                plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
                paths = plan.plan_paths
                if debugMode:
                    self.render_expansion_plan(map, plan)
                value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
                self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner_1_from_edge___1_0_failure(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        xWall = 1
        yWall = 0
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
        general = board[yWall][xWall]
        general.isGeneral = True
        general.player = 0
        general.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        board = TextMapLoader.load_map_from_file("EarlyExpandUtilsTestMaps/forced_corner_combo")
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)

        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo__force_11_launch(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        turn = 20
        board = TextMapLoader.load_map_from_file("EarlyExpandUtilsTestMaps/forced_corner_combo")
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 11

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)

        distToGenMap = SearchUtils.build_distance_map(map, [general])

        paths = EarlyExpandUtils._sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            11,
            distToGenMap,
            weightMap,
            turn=turn,
            prune_below=0,
            allow_wasted_moves=6,
            no_log=True)

        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=True)
        if debugMode:
            self.render_paths(map, paths, str(value))
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo__10_launch_should_wait_till_11(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 18
        board = TextMapLoader.load_map_from_file("EarlyExpandUtilsTestMaps/forced_corner_combo")
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 10

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)

        distToGenMap = SearchUtils.build_distance_map(map, [general])

        paths = EarlyExpandUtils._sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            10,
            distToGenMap,
            weightMap,
            turn=turn,
            prune_below=0,
            allow_wasted_moves=8,
            dont_force_first=True,
            no_log=True)

        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)

        # self.render_paths(map, paths, str(value))
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__force_11_launch(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        walls = [0, 24]
        for xWall in walls:
            for yWall in walls:
                with self.subTest(corner=(xWall, yWall)):
                    board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
                    general = board[yWall][xWall]
                    general.isGeneral = True
                    general.player = 0
                    general.army = 1

                    map = self.get_test_map(board, turn=turn)
                    weightMap = self.get_opposite_general_distance_map(map, general)

                    distToGenMap = SearchUtils.build_distance_map(map, [general])

                    launchTurn = 20

                    paths = EarlyExpandUtils._sub_optimize_remaining_cycle_expand_from_cities(
                        map,
                        general,
                        11,
                        distToGenMap,
                        weightMap,
                        prune_below=0,
                        turn=launchTurn,
                        allow_wasted_moves=6)

                    for _ in range(map.turn, launchTurn):
                        paths.insert(0, None)

                    value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
                    # self.render_paths(map, paths, str(value))
                    self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__full_optimize(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        walls = [0, 24]
        for xWall in walls:
            for yWall in walls:
                with self.subTest(corner=(xWall, yWall)):
                    board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
                    general = board[yWall][xWall]
                    general.isGeneral = True
                    general.player = 0
                    general.army = 1

                    map = self.get_test_map(board, turn=turn)
                    weightMap = self.get_opposite_general_distance_map(map, general)
                    plan = EarlyExpandUtils.optimize_first_25(
                        map,
                        general,
                        weightMap)

                    if debugMode:
                        self.render_expansion_plan(map, plan)
                    self.assertEqual(20, plan.launch_turn)
                    self.assertEqual(25, plan.tile_captures)


    def test_finds_optimal__suboptimal_cramped_spawn(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general = self.load_turn_1_map_and_general("EarlyExpandUtilsTestMaps/suboptimal_cramped_spawn")
        # Ginger: off the top of my head I would go 11 straight left, then move the 6 units 5 tiles and go down, then 6 units 3 tiles down then whatever is left
        weightMap = self.get_opposite_general_distance_map(map, general)

        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertGreater(plan.tile_captures, 22)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
        # 23 is possible, https://generals.io/replays/ta0ZuXvBq
        # 11 launch left,
        # 6 launch left down
        # 6 launch up left up left
        # 4 (offtiming) launch up for 2 more tiles, why can't the bot see this...?
        self.assertGreater(value, 22)

    def test_does_not_find__expansion_plan_longer_than_50_turns(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general = self.load_turn_1_map_and_general("EarlyExpandUtilsTestMaps/expansion_plan_longer_than_50_turns")

        weightMap = self.get_opposite_general_distance_map(map, general)

        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        if debugMode:
            self.render_expansion_plan(map, plan)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
        # we must be able to do better than 22...
        # indeed! Found a 23 :D
        self.assertGreaterEqual(value, 23)

    def test_invalid_plan_that_thought_it_had_more_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/produced_invalid_plan_01')
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test_cramped_plan_performance__cramped_should_find_better_than_22(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/cramped_should_find_better_than_22')
        if debugMode:
            self.render_expansion_plan(map, plan)
        # 23 possible here: https://generals.io/replays/ZBdIA5bge
        #  and here: https://generals.io/replays/ptHf8lX8V
        # Basically, 13 launch hugging wall to preserve as much CONTIGUOUS space next to initial path as possible,
        #  second path utilizes that space, ezpz from there.
        # Need to find a way to search for path 1 and 2 together at the same time in cramped spawns, maybe...?
        #  I don't see a heuristic that can get path 1 right from the start since in this spawn the path the algo takes
        #  and the optimal path both cross the same key tiles at various points, meaning by that point the first half of
        #  the path is already locked in, I think? Maybe track TWO sets of adjacents, one that is adjLeft and one adjRight
        #  and take the max of the two when prioing the long path(s)? I still think that has same problem as above...
        self.assertGreater(plan.tile_captures, 22)

    def test_finds_optimal__empty_board__one_in_from_corner(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        turn = 1
        walls = [1, 23]
        for xWall in walls:
            for yWall in walls:
                with self.subTest(corner=(xWall, yWall)):
                    board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
                    general = board[yWall][xWall]
                    general.isGeneral = True
                    general.player = 0
                    general.army = 1

                    map = self.get_test_map(board, turn=turn)
                    weightMap = self.get_opposite_general_distance_map(map, general)
                    plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
                    paths = plan.plan_paths
                    value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
                    self.assertEqual(25, value)

    def test_does_not_explode__exploded_turn_19(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/exploded_turn_19')
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test__only_got_24_when_seems_easy_25__V1__turn50(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/only_got_24_when_seems_easy_25__V1__turn50')
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test__only_got_24_when_seems_easy_25__V2__turn50(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/only_got_24_when_seems_easy_25__V2__turn50')
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test__only_got_24_when_seems_easy_25__V2__turn50__force_11_launch(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        map, general = self.load_turn_1_map_and_general('EarlyExpandUtilsTestMaps/only_got_24_when_seems_easy_25__V2__turn50')
        self.reset_map_to_just_generals(map, turn=1)
        weightMap = self.get_opposite_general_distance_map(map, general)

        # TODO this one fails because it doesn't preserve contiguous space adjacent to general.
        #  If the 3rd arm went down along the mountains, I think it could get 25 easily.
        distToGenMap = SearchUtils.build_distance_map(map, [general])

        launchTurn = 20

        paths = EarlyExpandUtils._sub_optimize_remaining_cycle_expand_from_cities(
            map,
            general,
            11,
            distToGenMap,
            weightMap,
            prune_below=0,
            turn=launchTurn,
            allow_wasted_moves=6,
            no_log=False)

        for _ in range(map.turn, launchTurn):
            paths.insert(0, None)

        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
        if debugMode:
            self.render_paths(map, paths, str(value))
        self.assertEqual(25, value)

    def test_produces_plans_as_good_or_better_than_historical(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        projRoot = pathlib.Path(__file__).parent
        folderWithHistoricals = projRoot / f'../Tests/EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat'
        files = os.listdir(folderWithHistoricals)
        joined = '\n'.join(files)
        self.begin_capturing_logging()
        logbook.info(f'files:\n{joined}')
        for file in files:
            with self.subTest(file=file.split('.')[0]):
                map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{file}', turn=50)
                if SearchUtils.count(map.pathableTiles, lambda tile: tile.player >= 0 and not tile.player == general.player) > 0:
                    # remove maps where we ran into another player, those aren't fair tests
                    safeFile = file.split('.')[0] + '.txtmap'
                    toRemove = projRoot / f'../Tests/EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{safeFile}'
                    os.remove(toRemove)
                    continue

                playerTilesToMatchOrExceed = self.get_tiles_capped_on_50_count_and_reset_map(map, general)

                weightMap = self.get_opposite_general_distance_map(map, general)
                timeStart = time.perf_counter()
                plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
                timeSpent = time.perf_counter() - timeStart
                if debugMode:
                    self.render_expansion_plan(map, plan)
                self.assertLessEqual(timeSpent, 3.0, 'took longer than we consider safe for finding starts')
                self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)
                if plan.tile_captures > playerTilesToMatchOrExceed:
                    self.skipTest(f"Produced a BETTER plan than original, {plan.tile_captures} vs {playerTilesToMatchOrExceed}")

    def test__debug_targeted_historical(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        file = 'BgRfjvS3h.txtmap'
        map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{file}', turn=50)
        playerTilesToMatchOrExceed = self.get_tiles_capped_on_50_count_and_reset_map(map, general)

        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)
        if debugMode:
            self.render_expansion_plan(map, plan)
        if plan.tile_captures > playerTilesToMatchOrExceed:
            self.skipTest(f"Produced a BETTER plan than original, {plan.tile_captures} vs {playerTilesToMatchOrExceed}")

    def test__st418_map_1(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        file = 'cramped_from_St418__1.txtmap'
        map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/{file}', turn=1)
        playerTilesToMatchOrExceed = 20  # st418 finds, 8

        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)
        if plan.tile_captures > playerTilesToMatchOrExceed:
            self.skipTest(f"Produced a BETTER plan than original, {plan.tile_captures} vs {playerTilesToMatchOrExceed}")

    def test__st418_map_2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        file = 'cramped_from_St418__2.txtmap'
        map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/{file}', turn=50)
        playerTilesToMatchOrExceed = self.get_tiles_capped_on_50_count_and_reset_map(map, general)

        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)

    def test_shouldnt_hang_13_seconds(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, plan = self.check_does_not_produce_invalid_plan('GameContinuationEntries/shouldnt_hang_13_seconds___SxauNnYTh---a--20.txtmap')
        if debugMode:
            self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 22)
    
    def test_should_expand_away_from_allied_general_2v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_expand_away_from_allied_general_2v2___z9F5n27D7---3--2.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 2, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=2)
        visEnGen = rawMap.GetTile(enemyGeneral.x, enemyGeneral.y)
        visEnGen.isGeneral = False
        visEnGen.army = 0
        visEnGen.player = -1
        rawMap.generals[enemyGeneral.player] = None
        rawMap.players[enemyGeneral.player].general = None

        visEnAllyGen = rawMap.GetTile(enemyAllyGen.x, enemyAllyGen.y)
        visEnAllyGen.isGeneral = False
        visEnAllyGen.army = 0
        visEnAllyGen.player = -1
        rawMap.generals[enemyAllyGen.player] = None
        rawMap.players[enemyAllyGen.player].general = None

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=50)
        self.assertNoFriendliesKilled(map, general, allyGen)
    
    def test_should_be_capable_of_expanding_out_of_stupid_spawn_near_ally(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_be_capable_of_expanding_out_of_stupid_spawn_near_ally___S1yUekSXM---2--2.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 2, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=2)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=48)
        self.assertNoFriendliesKilled(map, general, allyGen)

    def test_should_respect_time_limit_when_doing_city_exp_piggyback(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_respect_time_limit_when_doing_city_exp_piggyback___vzijdfmWf---1--82.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 82, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=82)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        simHost.respect_turn_time_limit = True
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertEqual(0, simHost.dropped_move_counts_by_player[general.player])
    
    def test_should_use_general_army_effectively_with_early_expand_piggyback(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_use_general_army_effectively_with_early_expand_piggyback___W-GNJ-jH4---0--86.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 86, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=86)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=14)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 47, '?')
    
    def test_should_branch_towards_multiple_possible_opp_spawns_1v1(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_branch_towards_multiple_possible_opp_spawns_1v1___SlGQiHT4p---1--20.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 16, fill_out_tiles=True)
        self.reset_map_to_just_generals(map, turn=16)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=34)
        self.assertIsNone(winner)

        self.assertEqual(25, playerMap.players[general.player].tileCount)

    def test_should_handle_lag_gracefully(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # for lagTurn in [44, 48]:
        for lagTurn in range(24, 50):
            with self.subTest(lagTurn=lagTurn):
                mapFile = 'GameContinuationEntries/should_branch_towards_multiple_possible_opp_spawns_1v1___SlGQiHT4p---1--20.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 16, fill_out_tiles=True)
                self.reset_map_to_just_generals(map, turn=16)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                self.add_lag_on_turns(simHost, [lagTurn])
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.05, turns=34)
                self.assertIsNone(winner)

                self.assertGreater(playerMap.players[general.player].tileCount, 23)

    def test_should_be_capable_of_handling_2v2_lag(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        for lagTurn in range(24, 50):
            with self.subTest(lagTurn=lagTurn):
                mapFile = 'GameContinuationEntries/should_expand_away_from_allied_general_2v2__modified___z9F5n27D7---3--2.txtmap'
                map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 16, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=16)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                self.add_lag_on_turns(simHost, [lagTurn], general.player)
                self.add_lag_on_turns(simHost, [lagTurn], allyGen.player)
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=34)
                self.assertNoFriendliesKilled(map, general, allyGen)

                self.assertGreater(playerMap.players[general.player].tileCount, 21)
                self.assertGreater(playerMap.players[allyGen.player].tileCount, 23)

    def test_should_handle_two_lag_turns_in_row_gracefully(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # for lagTurn in [44, 48]:
        for lagTurn in range(24, 50):
            with self.subTest(lagTurn=lagTurn):
                mapFile = 'GameContinuationEntries/should_branch_towards_multiple_possible_opp_spawns_1v1___SlGQiHT4p---1--20.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 16, fill_out_tiles=True)
                self.reset_map_to_just_generals(map, turn=16)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                self.add_lag_on_turns(simHost, [lagTurn, lagTurn + 1])
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.05, turns=34)
                self.assertIsNone(winner)

                self.assertGreater(playerMap.players[general.player].tileCount, 22)

    def test_should_handle_three_lag_turns_in_row_gracefully(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # for lagTurn in [44, 48]:
        for lagTurn in range(24, 50):
            with self.subTest(lagTurn=lagTurn):
                mapFile = 'GameContinuationEntries/should_branch_towards_multiple_possible_opp_spawns_1v1___SlGQiHT4p---1--20.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 16, fill_out_tiles=True)
                self.reset_map_to_just_generals(map, turn=16)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                self.add_lag_on_turns(simHost, [lagTurn, lagTurn + 1, lagTurn + 2])
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.05, turns=34)
                self.assertIsNone(winner)

                self.assertGreater(playerMap.players[general.player].tileCount, 22)