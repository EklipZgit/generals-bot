import inspect
import typing
import unittest

import ExpandUtils
import SearchUtils
from Sim.TextMapLoader import TextMapLoader
from Tests.TestBase import TestBase
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase


class ExpandUtilsTests(TestBase):
    def test_takes_1_move_final_move(self):
        # test both odd and even turns
        turn = 49
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        self.assertEqual(1, len(paths))
        path = paths[0]
        self.assertEqual(1, path.length)

    def test_takes_2_move_final_move_through_friendly_tile(self):
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
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        self.assertEqual(1, len(paths))
        path = paths[0]
        self.assertEqual(2, path.length)

    def test_waits_a_move_when_optimal_shorter(self):
        # test both odd and even turns
        turn = 46
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(4)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        # self.render_plan(map, plan)
        self.assertEqual(3, plan.tile_captures)
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(3, value)
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_waits_a_move_when_optimal(self):
        # test both odd and even turns
        turn = 44
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(4)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 3

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        # self.render_plan(map, plan)
        self.assertEqual(4, plan.tile_captures)
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(4, value)
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_does_something_near_end_of_turn_43(self):
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
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        # self.render_plan(map, plan)

        self.assertEqual(5, value)
        self.assertEqual(4, len(paths))

    def test_does_something_near_end_of_turn_45(self):
        # test both odd and even turns
        turn = 45
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(2)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        underTile = board[1][0]
        underTile.player = 0
        underTile.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        self.render_plan(map, plan)

        self.assertEqual(5, value)
        self.assertEqual(4, len(paths))

    def test_does_something_near_end_of_turn_47(self):
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
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        # self.render_plan(map, plan)

        self.assertEqual(5, value)
        self.assertEqual(4, len(paths))

    def test_does_something_near_end_of_turn_48(self):
        # test both odd and even turns
        turn = 48
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(2)] for y in range(3)]
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 2

        underTile = board[1][0]
        underTile.player = 0
        underTile.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        # self.render_plan(map, plan)

        self.assertEqual(5, value)
        self.assertEqual(4, len(paths))

    def test_finds_optimal__empty_board__middle(self):
        turn = 1
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
        general = board[12][12]
        general.isGeneral = True
        general.player = 0
        general.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__wall(self):
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
                weightMap = self.get_from_general_weight_map(map, general, negate=True)
                plan = ExpandUtils.optimize_first_25(map, general, weightMap)
                paths = plan.plan_paths
                value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
                self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner_1_from_edge(self):
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
                weightMap = self.get_from_general_weight_map(map, general, negate=True)
                plan = ExpandUtils.optimize_first_25(map, general, weightMap)
                paths = plan.plan_paths
                # self.render_plan(map, plan)
                value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
                self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner_1_from_edge___1_0_failure(self):
        turn = 1
        xWall = 1
        yWall = 0
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(25)] for y in range(25)]
        general = board[yWall][xWall]
        general.isGeneral = True
        general.player = 0
        general.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)
        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        # self.render_plan(map, plan)
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner(self):
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
                    weightMap = self.get_from_general_weight_map(map, general, negate=True)

                    distToGenMap = SearchUtils.build_distance_map(map, [general])

                    launchTurn = 21

                    paths = ExpandUtils._sub_optimize_first_25(
                        map,
                        general,
                        11,
                        distToGenMap,
                        weightMap,
                        turn=launchTurn,
                        repeatTiles=6)

                    for _ in range(map.turn, launchTurn - 1):
                        paths.insert(0, None)

                    value = ExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
                    self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo(self):
        turn = 1
        board = TextMapLoader.load_map_from_file("ExpandUtilsTests/ExpandUtilsTestMaps/forced_corner_combo")
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 1

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_from_general_weight_map(map, general, negate=True)

        distToGenMap = SearchUtils.build_distance_map(map, [general])

        launchTurn = 21

        paths = ExpandUtils._sub_optimize_first_25(
            map,
            general,
            11,
            distToGenMap,
            weightMap,
            turn=launchTurn,
            repeatTiles=6)

        for _ in range(map.turn, launchTurn - 1):
            paths.insert(0, None)
        #
        # self.render_plan(map, plan)

        value = ExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
        self.assertEqual(25, value)


    def test_invalid_plan_that_thought_it_had_more_army(self):
        plan = self.check_does_not_produce_invalid_plan('produced_invalid_plan_01')
        self.assertEqual(plan.tile_captures, 25)


    def test_finds_optimal__empty_board__one_in_from_corner(self):
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
                    weightMap = self.get_from_general_weight_map(map, general, negate=True)
                    plan = ExpandUtils.optimize_first_25(map, general, weightMap)
                    paths = plan.plan_paths
                    value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
                    self.assertEqual(25, value)

    def check_does_not_produce_invalid_plan(self, mapFileName: str) -> ExpandUtils.ExpansionPlan:
        turn = 1
        board = TextMapLoader.load_map_from_file(f"ExpandUtilsTests/ExpandUtilsTestMaps/{mapFileName}")

        map = self.get_test_map(board, turn=turn)
        general = next(t for t in map.reachableTiles if t.isGeneral)
        general.army = 1

        weightMap = self.get_from_general_weight_map(map, general, negate=True)

        plan = ExpandUtils.optimize_first_25(map, general, weightMap)
        paths = plan.plan_paths
        value = ExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        # self.render_plan(map, plan)

        self.assertEqual(plan.tile_captures, value)
        return plan
