import inspect
import random
import time
import unittest

import logbook

import SearchUtils
from DistanceMapperImpl import DistanceMapperImpl
from SearchUtils import dest_breadth_first_target
from Tests.TestBase import TestBase
from ViewInfo import PathColorer
from base.client.map import Tile
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


class SearchUtilsTests(TestBase):
    def test_dest_breadth_first_target__calculates_short_path_values_correctly__normal_tile(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(3)]
                target = board[0][0]
                target.army = 5

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 9

                map = self.get_test_map(board, turn=turn)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[target],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)


    def test_dest_breadth_first_target__calculates_longer_path_values_correctly__targeting_normal_tile(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
                target = board[0][0]
                target.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. So to kill tile @ 5 it takes 18 + 5 = 23
                threatTile.army = 23

                map = self.get_test_map(board, turn=turn)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[target],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_short_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(3)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 9

                map = self.get_test_map(board, turn=turn)
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_odd_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 27

                map = self.get_test_map(board, turn=turn)
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_even_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(11)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[10][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 29

                map = self.get_test_map(board, turn=turn)
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=12,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_bfs_find_queue_returns_path(self):
        mapFile = 'GameContinuationEntries/should_complete_danger_tile_kill___Bgk8TIUR2---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)
        startTile = map.GetTile(2, 12)
        midTile = map.GetTile(2, 15)

        def pathToGenFunc(current: Tile, curArmyAmt: int, distance: int) -> bool:
            if current == general:
                return True
            return False

        path = SearchUtils.breadth_first_find_queue(map, [startTile], pathToGenFunc, noNeutralCities = True, searchingPlayer = startTile.player)

        self.assertIsNotNone(path)
        self.assertEqual(4, path.length)

    def test_bfs_find_queue_returns_path_despite_army_blocking(self):
        mapFile = 'GameContinuationEntries/should_complete_danger_tile_kill___Bgk8TIUR2---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)
        startTile = map.GetTile(2, 12)
        midTile = map.GetTile(2, 14)
        midTile.army = 14

        def pathToGenFunc(current: Tile, curArmyAmt: int, distance: int) -> bool:
            if current == general:
                return True
            return False

        path = SearchUtils.breadth_first_find_queue(map, [startTile], pathToGenFunc, noNeutralCities = True, searchingPlayer = startTile.player)

        self.assertIsNotNone(path)
        self.assertEqual(4, path.length)

    def test_benchmark_bidir_a_star(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=False)

        ranges = [2, 4, 7, 10, 12, 15, 20, 25, 30, 35, 40]

        self.run_shortest_path_algo_comparison(map, ranges)

    def test_benchmark_bidir_a_star__large_map(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/large_map_test___EjibXeerX---2--2.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 2, fill_out_tiles=False)
        #
        # points = [
        #     map.GetTile(7, 6),
        #     map.GetTile(16, 9),
        #     map.GetTile(0, 4),
        #     map.GetTile(7, 18),
        #     map.GetTile(12, 11),
        #     map.GetTile(9, 16),
        #     map.GetTile(2, 1),
        #     map.GetTile(11, 3),
        #     map.GetTile(9, 10),
        #     map.GetTile(5, 2),
        #     map.GetTile(7, 2),
        #     map.GetTile(13, 9),
        #     map.GetTile(7, 2),
        #     map.GetTile(11, 8),
        # ]

        ranges = [2, 4, 7, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70]

        self.run_shortest_path_algo_comparison(map, ranges)

    def run_shortest_path_algo_comparison(self, map, ranges, skipFloyd: bool = True):
        points = list(map.pathableTiles)
        random.shuffle(points)
        points = points[0:110]

        self.begin_capturing_logging()

        start = time.perf_counter()
        if not skipFloyd:
            floydDists = SearchUtils.floydWarshall(map)
        floydTime = time.perf_counter() - start

        start = time.perf_counter()
        dumbassDistDists = SearchUtils.dumbassDistMatrix(map)
        dumbassDistTime = time.perf_counter() - start

        start = time.perf_counter()
        map.distance_mapper = DistanceMapperImpl(map)
        sumDistMapperTime = time.perf_counter() - start

        lastRange = 0
        for r in ranges:
            sumPQTime = 0.0
            sumHQTime = 0.0
            sumAStarTime = 0.0
            sumAStarDistTime = 0.0
            sumAStarMatrixTime = 0.0
            sumBfsFindTime = 0.0
            sumBfsFindDistTime = 0.0
            iters = 0

            for pointA in points:
                for pointB in points:
                    if pointA == pointB:
                        continue

                    manhattanDist = abs(pointA.x - pointB.x) + abs(pointA.y - pointB.y)
                    if not (r >= manhattanDist > lastRange):
                        continue

                    iters += 1

                    start = time.perf_counter()
                    pPq = SearchUtils.bidirectional_a_star_pq(pointA, pointB)
                    sumPQTime += time.perf_counter() - start

                    start = time.perf_counter()
                    pHq = SearchUtils.bidirectional_a_star(pointA, pointB)
                    sumHQTime += time.perf_counter() - start

                    start = time.perf_counter()
                    pAStar = SearchUtils.a_star_find([pointA], pointB, noLog=True)
                    sumAStarTime += time.perf_counter() - start

                    start = time.perf_counter()
                    pAStarDist = SearchUtils.a_star_find_dist([pointA], pointB, noLog=True)
                    sumAStarDistTime += time.perf_counter() - start

                    start = time.perf_counter()
                    pAStarMatrix = SearchUtils.a_star_find_matrix(map, [pointA], pointB, noLog=True)
                    sumAStarMatrixTime += time.perf_counter() - start

                    def findFunc(tile: Tile, a: int, dist: int = 0) -> bool:
                        return tile == pointB

                    start = time.perf_counter()
                    pFind = SearchUtils.breadth_first_find_queue(map, [pointA], findFunc, noNeutralCities=True, noLog=True)
                    sumBfsFindTime += time.perf_counter() - start

                    start = time.perf_counter()
                    pFindDist = SearchUtils.breadth_first_find_dist_queue([pointA], findFunc, noNeutralCities=True, noLog=True)
                    sumBfsFindDistTime += time.perf_counter() - start

                    start = time.perf_counter()
                    distMapperDist = map.get_distance_between(pointA, pointB)
                    sumDistMapperTime += time.perf_counter() - start

                    if (
                            pHq.length != pPq.length
                            or pHq.length != pHq.length
                            or pFind.length != pHq.length
                            or pAStar.length != pHq.length
                            or pAStarDist != pHq.length
                            or pFindDist != pHq.length
                            or pAStarMatrix.length != pHq.length
                    ):
                        vi = self.get_renderable_view_info(map)
                        vi.color_path(PathColorer(
                            pPq, 0, 255, 255
                        ))
                        vi.color_path(PathColorer(
                            pHq, 255, 0, 255
                        ))
                        vi.color_path(PathColorer(
                            pFind, 255, 255, 255
                        ))
                        vi.color_path(PathColorer(
                            pAStar, 0, 0, 0
                        ))
                        vi.color_path(PathColorer(
                            pAStarMatrix, 0, 0, 0
                        ))
                        self.render_view_info(map, vi, "mismatch")

                    if not skipFloyd and pHq.length != floydDists[pointA][pointB]:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pHq, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch floyd {floydDists[pointA][pointB]} vs {pHq.length}")

                    if pHq.length != dumbassDistDists[pointA][pointB]:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pHq, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch dumbass {dumbassDistDists[pointA][pointB]} vs {pHq.length}")

                    if pHq.length != distMapperDist:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pHq, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch distmapper {distMapperDist} vs {pHq.length}")

            logbook.info(
                f'{lastRange}-{r}, iters {iters}: floyd {floydTime:.3f} vs dumbass {dumbassDistTime:.3f} vs distMapper {sumDistMapperTime:.3f} vs PQ {sumPQTime:.3f} vs HQ {sumHQTime:.3f} vs find {sumBfsFindTime:.3f} vs aStar {sumAStarTime:.3f} vs aStarMatrix {sumAStarMatrixTime:.3f} vs aStarDist {sumAStarDistTime:.3f}, vs bfsFindDist {sumBfsFindDistTime:.3f}')
            lastRange = r
