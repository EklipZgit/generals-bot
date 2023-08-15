import inspect
import os
import pathlib
import time
import typing
import unittest

import EarlyExpandUtils
import SearchUtils
from Sim.TextMapLoader import TextMapLoader
from Tests.TestBase import TestBase
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase


class EarlyExpandUtilsTests(TestBase):
    def test_takes_1_move_final_move(self):
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
        # self.render_expansion_plan(map, plan)
        self.assertEqual(3, plan.tile_captures)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(3, value)
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_waits_a_move_when_optimal__turn_43(self):
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
        self.render_expansion_plan(map, plan)
        self.assertEqual(5, plan.tile_captures)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(5, value)
        # specifically, because this should cap the least tiles near general, we expect it to find the 1 path result
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))


    def test_waits_a_move_when_optimal__turn_45(self):
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
        # self.render_expansion_plan(map, plan)
        self.assertEqual(4, plan.tile_captures)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(4, value)
        # specifically, because this should cap the least tiles near general, we expect it to find the 1 path result
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
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)

        # self.render_expansion_plan(map, plan)

        self.assertEqual(5, value)
        self.assertEqual(4, len(paths))

    def test_does_something_near_end_of_turn_45(self):
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

        # self.render_expansion_plan(map, plan)

        # 45 down 1
        # 46 down 1 (cap 2,0 -- 3)
        # 47 right 1 (cap 2,1 -- 4)
        # 48 gen 2 right 1 (cap 1,0 -- 5)
        # 49 no op

        self.assertEqual(5, value)
        self.assertEqual(2, len(paths))

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
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=False)
        paths = plan.plan_paths

        # self.render_expansion_plan(map, plan)

        self.assertEqual(4, plan.tile_captures)
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_does_something_near_end_of_turn_48(self):
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

        # self.render_expansion_plan(map, plan)

        self.assertEqual(3, value)
        self.assertEqual(1, SearchUtils.count(paths, lambda path: path is not None))

    def test_finds_optimal__empty_board__middle(self):
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
                # self.render_expansion_plan(map, plan)
                value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
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
        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        # self.render_expansion_plan(map, plan)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo(self):
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
        # self.render_expansion_plan(map, plan)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, turn, paths, noLog=False)
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo__force_11_launch(self):
        turn = 20
        board = TextMapLoader.load_map_from_file("EarlyExpandUtilsTestMaps/forced_corner_combo")
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 11

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)

        distToGenMap = SearchUtils.build_distance_map(map, [general])

        paths = EarlyExpandUtils._sub_optimize_first_25(
            map,
            general,
            11,
            distToGenMap,
            weightMap,
            turn=turn,
            prune_below=0,
            allow_wasted_moves=6,
            no_log=False)

        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)

        # self.render_paths(map, paths, str(value))
        self.assertEqual(25, value)

    def test_finds_optimal__empty_board__corner__forced_corner_combo__10_launch_should_wait_till_11(self):
        turn = 18
        board = TextMapLoader.load_map_from_file("EarlyExpandUtilsTestMaps/forced_corner_combo")
        general = board[0][0]
        general.isGeneral = True
        general.player = 0
        general.army = 10

        map = self.get_test_map(board, turn=turn)
        weightMap = self.get_opposite_general_distance_map(map, general)

        distToGenMap = SearchUtils.build_distance_map(map, [general])

        paths = EarlyExpandUtils._sub_optimize_first_25(
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

                    paths = EarlyExpandUtils._sub_optimize_first_25(
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

                    # self.render_expansion_plan(map, plan)
                    self.assertEqual(20, plan.launch_turn)
                    self.assertEqual(25, plan.tile_captures)


    def test_finds_optimal__suboptimal_cramped_spawn(self):
        map, general = self.load_turn_1_map_and_general("EarlyExpandUtilsTestMaps/suboptimal_cramped_spawn")
        # Ginger: off the top of my head I would go 11 straight left, then move the 6 units 5 tiles and go down, then 6 units 3 tiles down then whatever is left
        weightMap = self.get_opposite_general_distance_map(map, general)

        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        # self.render_expansion_plan(map, plan)
        self.assertGreater(plan.tile_captures, 22)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
        # 23 is possible, https://generals.io/replays/ta0ZuXvBq
        # 11 launch left,
        # 6 launch left down
        # 6 launch up left up left
        # 4 (offtiming) launch up for 2 more tiles, why can't the bot see this...?
        self.assertGreater(value, 22)

    def test_does_not_find__expansion_plan_longer_than_50_turns(self):
        map, general = self.load_turn_1_map_and_general("EarlyExpandUtilsTestMaps/expansion_plan_longer_than_50_turns")

        weightMap = self.get_opposite_general_distance_map(map, general)

        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        paths = plan.plan_paths
        # self.render_expansion_plan(map, plan)
        value = EarlyExpandUtils.get_start_expand_value(map, general, general.army, map.turn, paths, noLog=False)
        # we must be able to do better than 22...
        # indeed! Found a 23 :D
        self.assertGreaterEqual(value, 23)

    def test_invalid_plan_that_thought_it_had_more_army(self):
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/produced_invalid_plan_01')
        # self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test_cramped_plan_performance__cramped_should_find_better_than_22(self):
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/cramped_should_find_better_than_22')
        # self.render_expansion_plan(map, plan)
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
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/exploded_turn_19')
        # self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test__only_got_24_when_seems_easy_25__turn50(self):
        map, plan = self.check_does_not_produce_invalid_plan('EarlyExpandUtilsTestMaps/only_got_24_when_seems_easy_25__turn50')
        # self.render_expansion_plan(map, plan)
        self.assertEqual(plan.tile_captures, 25)

    def test_produces_plans_as_good_or_better_than_historical(self):
        projRoot = pathlib.Path(__file__).parent
        folderWithHistoricals = projRoot / f'../Tests/EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat'
        files = os.listdir(folderWithHistoricals)
        for file in files:
            map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{file}', turn=50)
            if SearchUtils.count(map.pathableTiles, lambda tile: tile.player >= 0 and not tile.player == general.player) > 0:
                # remove maps where we ran into another player, those aren't fair tests
                safeFile = file.split('.')[0] + '.txtmap'
                toRemove = projRoot / f'../Tests/EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{safeFile}'
                os.remove(toRemove)
                continue

            with self.subTest(file=file.split('.')[0]):
                playerTilesToMatchOrExceed = self.get_tiles_capped_on_50_count_and_reset_map(map, general)

                weightMap = self.get_opposite_general_distance_map(map, general)
                timeStart = time.perf_counter()
                plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
                timeSpent = time.perf_counter() - timeStart
                self.assertLessEqual(timeSpent, 3.0, 'took longer than we consider safe for finding starts')
                self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)
                if plan.tile_captures > playerTilesToMatchOrExceed:
                    self.skipTest(f"Produced a BETTER plan than original, {plan.tile_captures} vs {playerTilesToMatchOrExceed}")
    #
    # def test_check_forced_variations_against_historical_bests(self):
    #     projRoot = pathlib.Path(__file__).parent
    #     folderWithHistoricals = projRoot / f'../Tests/EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat'
    #     files = os.listdir(folderWithHistoricals)
    #     for file in files:
    #         map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{file}', turn=50)
    #         if SearchUtils.count(map.pathableTiles, lambda tile: tile.player >= 0 and not tile.player == general.player) > 0:
    #             # skip maps where we ran into another player, those aren't fair tests
    #             continue
    #
    #         with self.subTest(file=file.split('.')[0]):
    #             playerTilesToMatchOrExceed = self.get_tiles_capped_on_50_count_and_reset_map(map, general)
    #
    #             weightMap = self.get_opposite_general_distance_map(map, general)
    #             timeStart = time.perf_counter()
    #             plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
    #             timeSpent = time.perf_counter() - timeStart
    #             self.assertLessEqual(timeSpent, 3.0, 'took longer than we consider safe for finding starts')
    #             self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)
    #             if plan.tile_captures > playerTilesToMatchOrExceed:
    #                 self.skipTest(f"Produced a BETTER plan than original, {plan.tile_captures} vs {playerTilesToMatchOrExceed}")

    def test__debug_targeted_historical(self):
        file = 'BgRfjvS3h.txtmap'
        map, general = self.load_map_and_general(f'EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat/{file}', turn=50)
        playerTilesToMatchOrExceed = self.get_tiles_capped_on_50_count_and_reset_map(map, general)

        weightMap = self.get_opposite_general_distance_map(map, general)
        plan = EarlyExpandUtils.optimize_first_25(map, general, weightMap, no_log=True)
        self.assertGreaterEqual(plan.tile_captures, playerTilesToMatchOrExceed)
        # self.render_expansion_plan(map, plan)
        if plan.tile_captures > playerTilesToMatchOrExceed:
            self.skipTest(f"Produced a BETTER plan than original, {plan.tile_captures} vs {playerTilesToMatchOrExceed}")


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

        return playerTilesToMatchOrExceed

    def render_expansion_plan(self, map: MapBase, plan: EarlyExpandUtils.ExpansionPlan):
        self.render_paths(map, plan.plan_paths, f'{str(plan.tile_captures)}')