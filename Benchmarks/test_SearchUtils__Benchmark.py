import random
import time
from collections import deque
from queue import PriorityQueue
from timeit import timeit

import heap_class
import logbook

import SearchUtils
from DistanceMapperImpl import DistanceMapperImpl
from Tests.TestBase import TestBase
from ViewInfo import PathColorer
from base.client.map import Tile


class SearchUtilsBenchmarkTests(TestBase):
    def test_benchmark_distmap_algos_ranges(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=False)

        ranges = [2, 4, 7, 10, 12, 15, 20, 25, 30, 35, 40]
        """
        [2024-02-20 23:38:08.605379] INFO: Generic: 0-2, iters 328: floyd 0.000 vs dumbass 0.082 vs distMapper 0.025 vs PQ 0.045 vs HQ 0.019 vs find 0.008 vs aStar 0.004 vs aStarMatrix 0.005 vs aStarDist 0.002, vs bfsFindDist 0.002
        [2024-02-20 23:38:09.183220] INFO: Generic: 2-4, iters 730: floyd 0.000 vs dumbass 0.082 vs distMapper 0.027 vs PQ 0.278 vs HQ 0.188 vs find 0.038 vs aStar 0.019 vs aStarMatrix 0.019 vs aStarDist 0.012, vs bfsFindDist 0.017
        [2024-02-20 23:38:12.189060] INFO: Generic: 4-7, iters 1542: floyd 0.000 vs dumbass 0.082 vs distMapper 0.029 vs PQ 1.556 vs HQ 1.062 vs find 0.139 vs aStar 0.068 vs aStarMatrix 0.060 vs aStarDist 0.042, vs bfsFindDist 0.068
        [2024-02-20 23:38:17.489574] INFO: Generic: 7-10, iters 1968: floyd 0.000 vs dumbass 0.082 vs distMapper 0.031 vs PQ 2.965 vs HQ 1.610 vs find 0.270 vs aStar 0.119 vs aStarMatrix 0.101 vs aStarDist 0.077, vs bfsFindDist 0.144
        [2024-02-20 23:38:21.692343] INFO: Generic: 10-12, iters 1410: floyd 0.000 vs dumbass 0.082 vs distMapper 0.033 vs PQ 2.314 vs HQ 1.202 vs find 0.255 vs aStar 0.111 vs aStarMatrix 0.094 vs aStarDist 0.074, vs bfsFindDist 0.141
        [2024-02-20 23:38:27.695381] INFO: Generic: 12-15, iters 1866: floyd 0.000 vs dumbass 0.082 vs distMapper 0.036 vs PQ 3.234 vs HQ 1.664 vs find 0.407 vs aStar 0.181 vs aStarMatrix 0.152 vs aStarDist 0.120, vs bfsFindDist 0.230
        [2024-02-20 23:38:35.872423] INFO: Generic: 15-20, iters 2390: floyd 0.000 vs dumbass 0.082 vs distMapper 0.040 vs PQ 4.250 vs HQ 2.184 vs find 0.607 vs aStar 0.301 vs aStarMatrix 0.250 vs aStarDist 0.208, vs bfsFindDist 0.359
        [2024-02-20 23:38:40.242203] INFO: Generic: 20-25, iters 1172: floyd 0.000 vs dumbass 0.082 vs distMapper 0.041 vs PQ 2.188 vs HQ 1.108 vs find 0.344 vs aStar 0.204 vs aStarMatrix 0.166 vs aStarDist 0.141, vs bfsFindDist 0.209
        [2024-02-20 23:38:42.083059] INFO: Generic: 25-30, iters 462: floyd 0.000 vs dumbass 0.082 vs distMapper 0.042 vs PQ 0.882 vs HQ 0.445 vs find 0.147 vs aStar 0.108 vs aStarMatrix 0.087 vs aStarDist 0.077, vs bfsFindDist 0.090
        [2024-02-20 23:38:42.566719] INFO: Generic: 30-35, iters 118: floyd 0.000 vs dumbass 0.082 vs distMapper 0.042 vs PQ 0.227 vs HQ 0.115 vs find 0.040 vs aStar 0.030 vs aStarMatrix 0.024 vs aStarDist 0.021, vs bfsFindDist 0.024
        [2024-02-20 23:38:42.584201] INFO: Generic: 35-40, iters 4: floyd 0.000 vs dumbass 0.082 vs distMapper 0.042 vs PQ 0.008 vs HQ 0.004 vs find 0.001 vs aStar 0.001 vs aStarMatrix 0.001 vs aStarDist 0.001, vs bfsFindDist 0.001
        """

        self.run_shortest_path_algo_comparison(map, ranges)

    def test_benchmark_distmap_algos_ranges__large_map(self):
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

    def test_benchmark_distmap_algos(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_kill_point_blank_army_lul___ffrBNaR9l---0--133.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 133, fill_out_tiles=False)

        ranges = [70]
        """
        [2024-02-20 23:38:08.605379] INFO: Generic: 0-2, iters 328: floyd 0.000 vs dumbass 0.082 vs distMapper 0.025 vs PQ 0.045 vs HQ 0.019 vs find 0.008 vs aStar 0.004 vs aStarMatrix 0.005 vs aStarDist 0.002, vs bfsFindDist 0.002
        [2024-02-20 23:38:09.183220] INFO: Generic: 2-4, iters 730: floyd 0.000 vs dumbass 0.082 vs distMapper 0.027 vs PQ 0.278 vs HQ 0.188 vs find 0.038 vs aStar 0.019 vs aStarMatrix 0.019 vs aStarDist 0.012, vs bfsFindDist 0.017
        [2024-02-20 23:38:12.189060] INFO: Generic: 4-7, iters 1542: floyd 0.000 vs dumbass 0.082 vs distMapper 0.029 vs PQ 1.556 vs HQ 1.062 vs find 0.139 vs aStar 0.068 vs aStarMatrix 0.060 vs aStarDist 0.042, vs bfsFindDist 0.068
        [2024-02-20 23:38:17.489574] INFO: Generic: 7-10, iters 1968: floyd 0.000 vs dumbass 0.082 vs distMapper 0.031 vs PQ 2.965 vs HQ 1.610 vs find 0.270 vs aStar 0.119 vs aStarMatrix 0.101 vs aStarDist 0.077, vs bfsFindDist 0.144
        [2024-02-20 23:38:21.692343] INFO: Generic: 10-12, iters 1410: floyd 0.000 vs dumbass 0.082 vs distMapper 0.033 vs PQ 2.314 vs HQ 1.202 vs find 0.255 vs aStar 0.111 vs aStarMatrix 0.094 vs aStarDist 0.074, vs bfsFindDist 0.141
        [2024-02-20 23:38:27.695381] INFO: Generic: 12-15, iters 1866: floyd 0.000 vs dumbass 0.082 vs distMapper 0.036 vs PQ 3.234 vs HQ 1.664 vs find 0.407 vs aStar 0.181 vs aStarMatrix 0.152 vs aStarDist 0.120, vs bfsFindDist 0.230
        [2024-02-20 23:38:35.872423] INFO: Generic: 15-20, iters 2390: floyd 0.000 vs dumbass 0.082 vs distMapper 0.040 vs PQ 4.250 vs HQ 2.184 vs find 0.607 vs aStar 0.301 vs aStarMatrix 0.250 vs aStarDist 0.208, vs bfsFindDist 0.359
        [2024-02-20 23:38:40.242203] INFO: Generic: 20-25, iters 1172: floyd 0.000 vs dumbass 0.082 vs distMapper 0.041 vs PQ 2.188 vs HQ 1.108 vs find 0.344 vs aStar 0.204 vs aStarMatrix 0.166 vs aStarDist 0.141, vs bfsFindDist 0.209
        [2024-02-20 23:38:42.083059] INFO: Generic: 25-30, iters 462: floyd 0.000 vs dumbass 0.082 vs distMapper 0.042 vs PQ 0.882 vs HQ 0.445 vs find 0.147 vs aStar 0.108 vs aStarMatrix 0.087 vs aStarDist 0.077, vs bfsFindDist 0.090
        [2024-02-20 23:38:42.566719] INFO: Generic: 30-35, iters 118: floyd 0.000 vs dumbass 0.082 vs distMapper 0.042 vs PQ 0.227 vs HQ 0.115 vs find 0.040 vs aStar 0.030 vs aStarMatrix 0.024 vs aStarDist 0.021, vs bfsFindDist 0.024
        [2024-02-20 23:38:42.584201] INFO: Generic: 35-40, iters 4: floyd 0.000 vs dumbass 0.082 vs distMapper 0.042 vs PQ 0.008 vs HQ 0.004 vs find 0.001 vs aStar 0.001 vs aStarMatrix 0.001 vs aStarDist 0.001, vs bfsFindDist 0.001
        """

        self.run_shortest_path_algo_comparison(map, ranges)

    def test_benchmark_distmap_algos__large_map(self):
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

        ranges = [70]

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
        distance_mapper = DistanceMapperImpl(map)
        sumDistMapperTime = time.perf_counter() - start

        start = time.perf_counter()
        distance_mapper_dual_cache = DistanceMapperImpl(map)
        sumDualCacheDistMapperTime = time.perf_counter() - start

        totalSumPQTime = 0.0
        totalSumHQTime = 0.0
        totalSumAStarTime = 0.0
        totalSumAStarDistTime = 0.0
        totalSumAStarMatrixTime = 0.0
        totalSumBfsFindTime = 0.0
        totalSumBfsFindDistTime = 0.0
        totalSumBfsFindDistNoNeutTime = 0.0

        lastRange = 0
        for r in ranges:
            sumPQTime = 0.0
            sumHQTime = 0.0
            sumAStarTime = 0.0
            sumAStarDistTime = 0.0
            sumAStarMatrixTime = 0.0
            sumBfsFindTime = 0.0
            sumBfsFindDistTime = 0.0
            sumBfsFindDistNoNeutTime = 0.0
            iters = 0

            for pointA in points:
                for pointB in points:
                    if pointA == pointB:
                        continue

                    manhattanDist = abs(pointA.x - pointB.x) + abs(pointA.y - pointB.y)
                    if not (r >= manhattanDist > lastRange):
                        continue

                    iters += 1

                    # start = time.perf_counter()
                    # pPq = SearchUtils.bidirectional_a_star_pq(pointA, pointB)
                    # sumPQTime += time.perf_counter() - start

                    # start = time.perf_counter()
                    # pHq = SearchUtils.bidirectional_a_star(pointA, pointB)
                    # sumHQTime += time.perf_counter() - start

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

                    # start = time.perf_counter()
                    # SearchUtils.breadth_first_foreach_dist_fast_no_neut_cities(map, [pointA], 100, findFunc)
                    # sumBfsFindDistNoNeutTime += time.perf_counter() - start

                    start = time.perf_counter()
                    distMapperDist = distance_mapper.get_distance_between(pointA, pointB)
                    sumDistMapperTime += time.perf_counter() - start

                    start = time.perf_counter()
                    dualCacheDistMapperDist = distance_mapper_dual_cache.get_distance_between_dual_cache(pointA, pointB)
                    sumDualCacheDistMapperTime += time.perf_counter() - start

                    if (
                            # pHq.length != pPq.length
                            # or pHq.length != pAStar.length
                            pFind.length != pAStar.length
                            or pAStar.length != pAStar.length
                            or pAStarDist != pAStar.length
                            or pFindDist != pAStar.length
                            or pAStarMatrix.length != pAStar.length
                    ):
                        vi = self.get_renderable_view_info(map)
                        # vi.color_path(PathColorer(
                        #     pPq, 0, 255, 255
                        # ))
                        # vi.color_path(PathColorer(
                        #     pHq, 255, 0, 255
                        # ))
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

                    if not skipFloyd and pAStar.length != floydDists[pointA][pointB]:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pAStar, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch floyd {floydDists[pointA][pointB]} vs {pAStar.length}")

                    if pAStar.length != dumbassDistDists[pointA][pointB]:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pAStar, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch dumbass {dumbassDistDists[pointA][pointB]} vs {pAStar.length}")

                    if pAStar.length != distMapperDist:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pAStar, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch distmapper {distMapperDist} vs {pAStar.length}")

                    if pAStar.length != dualCacheDistMapperDist:
                        vi = self.get_renderable_view_info(map)

                        vi.color_path(PathColorer(
                            pAStar, 0, 255, 255
                        ))
                        self.render_view_info(map, vi, f"mismatch distmapper (dual cache) {dualCacheDistMapperDist} vs {pAStar.length}")

            logbook.info(
                f'{lastRange}-{r}, iters {iters}: floyd {floydTime:.5f} vs dumbass {dumbassDistTime:.5f} vs distMapper {sumDistMapperTime:.5f} vs distMapperDual {sumDualCacheDistMapperTime:.5f} vs PQ {sumPQTime:.5f} vs HQ {sumHQTime:.5f} vs find {sumBfsFindTime:.5f} vs aStar {sumAStarTime:.5f} vs aStarMatrix {sumAStarMatrixTime:.5f} vs aStarDist {sumAStarDistTime:.5f}, vs bfsFindDist {sumBfsFindDistTime:.5f}')
            lastRange = r

            totalSumPQTime += sumPQTime
            totalSumHQTime += sumHQTime
            totalSumAStarTime += sumAStarTime
            totalSumAStarDistTime += sumAStarDistTime
            totalSumAStarMatrixTime += sumAStarMatrixTime
            totalSumBfsFindTime += sumBfsFindTime
            totalSumBfsFindDistTime += sumBfsFindDistTime
            totalSumBfsFindDistNoNeutTime += sumBfsFindDistNoNeutTime
        logbook.info(
            f'FINAL RESULTS floyd {floydTime:.5f} vs dumbass {dumbassDistTime:.5f} vs distMapper {sumDistMapperTime:.5f} vs distMapperDual {sumDualCacheDistMapperTime:.5f} vs PQ {totalSumPQTime:.5f} vs HQ {totalSumHQTime:.5f} vs find {totalSumBfsFindTime:.5f} vs aStar {totalSumAStarTime:.5f} vs aStarMatrix {totalSumAStarMatrixTime:.5f} vs aStarDist {totalSumAStarDistTime:.5f}, vs bfsFindDist {totalSumBfsFindDistTime:.5f}')

        def test_bench_set_empty_checking_perf(self):
            numPops = 500000000
            self.begin_capturing_logging()
            for numChecks in [20, 100, 500, 2000]:
                with self.subTest(numChecks=numChecks):
                    numRuns = numPops // numChecks
                    # benchmark the task
                    result = timeit(
                        '''
    while mySet:
        mySet.pop()
                        ''',
                        setup=f'''
    mySet = set(range(0, {numChecks}))
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numChecks}: while mySet: {result:.3f} seconds')

                    result = timeit(
                        '''
    while len(mySet) > 0:
        mySet.pop()
                        ''',
                        setup=f'''
    mySet = set(range(0, {numChecks}))
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numChecks}: while len(mySet) > 0: {result:.3f} seconds')

                    result = timeit(
                        '''
    while mySet != emptySet:
        mySet.pop()
                        ''',
                        setup=f'''
    emptySet = set()
    mySet = set(range(0, {numChecks}))
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numChecks}: while mySet != emptySet: {result:.3f} seconds')

                    result = timeit(
                        '''
    while emptySet != mySet:
        mySet.pop()
                        ''',
                        setup=f'''
    emptySet = set()
    mySet = set(range(0, {numChecks}))
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numChecks}: while emptySet != mySet: {result:.3f} seconds')

                    result = timeit(
                        '''
    try:
        while True:
            mySet.pop()
    except:
        pass
                        ''',
                        setup=f'''
    mySet = set(range(0, {numChecks}))
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numChecks}: while True try except: {result:.3f} seconds')
    def test_bench_deque_empty_checking_perf(self):
        numPops = 500000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # d = deque()
                # self.assertFalse(bool(d))
                # d.append(1)
                # self.assertTrue(bool(d))

                # benchmark the task
                result = timeit(
                    '''
while myDeque:
    myDeque.pop()
                    ''',
                    setup=f'''
from collections import deque                    
myDeque = deque(range(0, {numChecks}))
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while myDeque: {result:.3f} seconds')

                result = timeit(
                    '''
while myDeque:
    myDeque.pop()
                    ''',
                    setup=f'''
from collections import deque                    
myDeque = deque(range(0, {numChecks}))
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while myDeque: {result:.3f} seconds')

                result = timeit(
                    '''
while len(myDeque) > 0:
    myDeque.pop()
                    ''',
                    setup=f'''
from collections import deque                    
myDeque = deque(range(0, {numChecks}))
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while len(myDeque) > 0: {result:.3f} seconds')

                result = timeit(
                    '''
while myDeque != emptyDeque:
    myDeque.pop()
                    ''',
                    setup=f'''
from collections import deque                    
emptyDeque = deque()
myDeque = deque(range(0, {numChecks}))
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while myDeque != emptyDeque: {result:.3f} seconds')

                result = timeit(
                    '''
while emptyDeque != myDeque:
    myDeque.pop()
                    ''',
                    setup=f'''
from collections import deque                    
emptyDeque = deque()
myDeque = deque(range(0, {numChecks}))
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while emptyDeque != myDeque: {result:.3f} seconds')

                result = timeit(
                    '''
try:
    while True:
        myDeque.pop()
except:
    pass
                    ''',
                    setup=f'''
from collections import deque                    
myDeque = deque(range(0, {numChecks}))
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while True try except: {result:.3f} seconds')

    def test_bench_priority_queue_empty_checking_perf(self):
        """
        20: while q: 0.3683 seconds
        20: while len(q) != 0: 0.5021 seconds
        20: while myDeque.queue: 0.2808 seconds
        20: while len(myDeque.queue) != 0: 0.4320 seconds
        20: while True try except: 16.8902 seconds
        20: while not myDeque.empty(): 3.5556 seconds
        20: while myDeque.qsize() != 0: 3.6573 seconds
        100: while q: 0.0774 seconds
        100: while len(q) != 0: 0.1194 seconds
        100: while myDeque.queue: 0.0622 seconds
        100: while len(myDeque.queue) != 0: 0.0870 seconds
        100: while True try except: 3.3733 seconds
        100: while not myDeque.empty(): 0.7240 seconds
        100: while myDeque.qsize() != 0: 0.7198 seconds
        500: while q: 0.0158 seconds
        500: while len(q) != 0: 0.0209 seconds
        500: while myDeque.queue: 0.0117 seconds
        500: while len(myDeque.queue) != 0: 0.0173 seconds
        500: while True try except: 0.6754 seconds
        500: while not myDeque.empty(): 0.1477 seconds
        500: while myDeque.qsize() != 0: 0.1487 seconds
        2000: while q: 0.0049 seconds
        2000: while len(q) != 0: 0.0063 seconds
        2000: while myDeque.queue: 0.0042 seconds
        2000: while len(myDeque.queue) != 0: 0.0055 seconds
        2000: while True try except: 0.1748 seconds
        2000: while not myDeque.empty(): 0.0397 seconds
        @return:
        """
        numPops = 500000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                q = PriorityQueue()
                # q.qsize()

                # benchmark the task
                result = timeit(
                    '''
q = myDeque.queue
while q:
    myDeque.get()
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while q: {result:.4f} seconds')

                # benchmark the task
                result = timeit(
                    '''
q = myDeque.queue
while len(q) != 0:
    myDeque.get()
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while len(q) != 0: {result:.4f} seconds')
                # q.qsize()

                # benchmark the task
                result = timeit(
                    '''
while myDeque.queue:
    myDeque.get()
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while myDeque.queue: {result:.4f} seconds')

                result = timeit(
                    '''
while len(myDeque.queue) != 0:
    myDeque.get()
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while len(myDeque.queue) != 0: {result:.4f} seconds')

                result = timeit(
                    '''
try:
    while True:
        myDeque.get_nowait()
except:
    pass
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while True try except: {result:.4f} seconds')

                result = timeit(
                    '''
while not myDeque.empty():
    myDeque.get()
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while not myDeque.empty(): {result:.4f} seconds')

                result = timeit(
                    '''
while myDeque.qsize() != 0:
    myDeque.get()
                    ''',
                    setup=f'''
from queue import PriorityQueue
myDeque = PriorityQueue()
for i in range(0, {numChecks}):
    myDeque.put_nowait(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while myDeque.qsize() != 0: {result:.4f} seconds')

    def test_bench_heap_queue_empty_checking_perf(self):
        numPops = 500000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()

                # benchmark the task
                result = timeit(
                    '''
while bool(myDeque.queue):
    myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
myDeque = HeapQueue()
for i in range(0, {numChecks}):
    myDeque.put(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while bool(myDeque.queue): {result:.3f} seconds')

                result = timeit(
                    '''
while myDeque.queue:
    myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
myDeque = HeapQueue()
for i in range(0, {numChecks}):
    myDeque.put(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while myDeque.queue: {result:.3f} seconds')

                result = timeit(
                    '''
while len(myDeque.queue) != 0:
    myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
myDeque = HeapQueue()
for i in range(0, {numChecks}):
    myDeque.put(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while len(myDeque.queue) != 0: {result:.3f} seconds')

                result = timeit(
                    '''
try:
    while True:
        myDeque.get()
except:
    pass
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
myDeque = HeapQueue()
for i in range(0, {numChecks}):
    myDeque.put(i)
                    ''',
                    number=numRuns)

                # report the result
                logbook.info(f'{numChecks}: while True try except: {result:.3f} seconds')

    def test_bench_priority_queue_insert_pop_checking_perf(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                import random
                toInsert = list(range(0, numChecks))
                random.shuffle(toInsert)
                # q.qsize()

                # benchmark the task
                result = timeit(
                    '''
myDeque = PriorityQueue()
for i in toInsert:
    myDeque.put_nowait(i)
while myDeque.queue:
    myDeque.get_nowait()
                    ''',
                    setup=f'''
from queue import PriorityQueue
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: PriorityQueue {result:.3f} seconds')

    def test_bench_heap_queue_insert_pop_checking_perf(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert = list(range(0, numChecks))
                random.shuffle(toInsert)

                # benchmark the task
                result = timeit(
                    '''
myDeque = HeapQueue()
for i in toInsert:
    myDeque.put(i)
while myDeque.queue:
    myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapQueue {result:.3f} seconds')

    """
    [2024-03-28 19:44:36.552731] INFO: Generic: 20: PriorityQueue 6.436 seconds
    [2024-03-28 19:44:41.952864] INFO: Generic: 100: PriorityQueue 5.399 seconds
    [2024-03-28 19:44:47.422303] INFO: Generic: 500: PriorityQueue 5.469 seconds
    [2024-03-28 19:44:53.048489] INFO: Generic: 2000: PriorityQueue 5.626 seconds
    """
    def test_bench_priority_queue_insert_pop_checking_perf__interspersed_gets(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                import random
                toInsert = list(range(0, numChecks))
                random.shuffle(toInsert)
                # q.qsize()

                # benchmark the task
                result = timeit(
                    '''
myDeque = PriorityQueue()
for i in toInsert:
    myDeque.put_nowait(i)
    if i & 1 == 0:
        myDeque.get_nowait()
while myDeque.queue:
    myDeque.get_nowait()
                    ''',
                    setup=f'''
from queue import PriorityQueue
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: PriorityQueue {result:.3f} seconds')

    """
    20: HeapQueue 0.646 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueue 0.707 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueue 0.912 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueue 1.034 seconds (2500 runs of 2000 pushes + pops)
    """
    def test_bench_heap_queue_insert_pop_checking_perf__interspersed_gets(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert = list(range(0, numChecks))
                random.shuffle(toInsert)

                # benchmark the task
                result = timeit(
                    '''
myDeque = HeapQueue()
for i in toInsert:
    myDeque.put(i)
    if i & 1 == 0:
        myDeque.get()
while myDeque.queue:
    myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapQueue {result:.3f} seconds ({numRuns} runs of {numChecks} pushes + pops)')

    """
    20: HeapQueueMax 1.306 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueueMax 1.707 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueueMax 2.026 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueueMax 2.411 seconds (2500 runs of 2000 pushes + pops)
    """
    def test_bench_heap_queue_max_insert_pop_checking_perf__interspersed_gets(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert = list(range(0, numChecks))
                random.shuffle(toInsert)

                # benchmark the task
                result = timeit(
                    '''
myDeque = HeapQueueMax()
for i in toInsert:
    myDeque.put(i)
    if i & 1 == 0:
        myDeque.get()
while myDeque.queue:
    myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueueMax
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapQueueMax {result:.3f} seconds ({numRuns} runs of {numChecks} pushes + pops)')

    """
    20: HeapQueue 0.727 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueue 0.898 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueue 1.264 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueue 1.551 seconds (2500 runs of 2000 pushes + pops)
    """
    def test_bench_heap_queue_insert_pop_checking_perf__interspersed_gets__complex_objects(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert1 = list(i for i in range(0, numChecks))
                toInsert2 = list(i for i in range(0, numChecks))
                random.shuffle(toInsert1)
                random.shuffle(toInsert2)

                toInsert = []
                for i in range(0, numChecks - 1):
                    toInsert.append(((toInsert2[i] & 1) == 0, toInsert1[i] ^ toInsert2[i], toInsert1[i] * 0.1 + toInsert2[i - 1], toInsert1[i]))

                # benchmark the task
                result = timeit(
                    '''
myDeque = HeapQueue()
val = None
for i in toInsert:
    myDeque.put(i)
    if i[0]:
        val = myDeque.get()
while myDeque.queue:
    val = myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueue
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapQueue {result:.3f} seconds ({numRuns} runs of {numChecks} pushes + pops)')

    """
    20: HeapQueueMax 1.498 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueueMax 1.975 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueueMax 2.494 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueueMax 3.026 seconds (2500 runs of 2000 pushes + pops)
    """
    def test_bench_heap_queue_max_insert_pop_checking_perf__interspersed_gets__complex_objects(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert1 = list(i for i in range(0, numChecks))
                toInsert2 = list(i for i in range(0, numChecks))
                random.shuffle(toInsert1)
                random.shuffle(toInsert2)

                toInsert = []
                for i in range(0, numChecks - 1):
                    toInsert.append(((toInsert2[i] & 1) == 0, toInsert1[i] ^ toInsert2[i], toInsert1[i] * 0.1 + toInsert2[i - 1], toInsert1[i]))

                # benchmark the task
                result = timeit(
                    '''
myDeque = HeapQueueMax()
val = None
for i in toInsert:
    myDeque.put(i)
    if i[0]:
        val = myDeque.get()
while myDeque.queue:
    val = myDeque.get()
                    ''',
                    setup=f'''
from SearchUtils import HeapQueueMax
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapQueueMax {result:.3f} seconds ({numRuns} runs of {numChecks} pushes + pops)')


    """
    Sadly, slower than even the python impl heapmax even though this is supposed to be full C
    20: HeapClass(min) 1.309 seconds (250000 runs of 20 pushes + pops)
    100: HeapClass(min) 1.569 seconds (50000 runs of 100 pushes + pops)
    500: HeapClass(min) 1.852 seconds (10000 runs of 500 pushes + pops)
    2000: HeapClass(min) 2.129 seconds (2500 runs of 2000 pushes + pops)
    """
    def test_bench_heap_class_insert_pop_checking_perf__interspersed_gets__complex_objects(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert1 = list(i for i in range(0, numChecks))
                toInsert2 = list(i for i in range(0, numChecks))
                random.shuffle(toInsert1)
                random.shuffle(toInsert2)

                toInsert = []
                for i in range(0, numChecks - 1):
                    toInsert.append(((toInsert2[i] & 1) == 0, toInsert1[i] ^ toInsert2[i], toInsert1[i] * 0.1 + toInsert2[i - 1], toInsert1[i]))
                # h = heap_class.Heap()
                # benchmark the task
                result = timeit(
                    '''
myDeque = Heap(max=False)
val = None
for i in toInsert:
    myDeque.push(i)
    if i[0]:
        val = myDeque.pop()
while len(myDeque):
    val = myDeque.pop()
                    ''',
                    setup=f'''
from heap_class import Heap
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapClass(min) {result:.3f} seconds ({numRuns} runs of {numChecks} pushes + pops)')

    """
    Sadly, slower than even the python impl heapmax even though this is supposed to be full C
    20: HeapClass(max) 2.141 seconds (250000 runs of 20 pushes + pops)
    100: HeapClass(max) 2.552 seconds (50000 runs of 100 pushes + pops)
    500: HeapClass(max) 3.051 seconds (10000 runs of 500 pushes + pops)
    2000: HeapClass(max) 3.652 seconds (2500 runs of 2000 pushes + pops)
    """
    def test_bench_heap_class_max_insert_pop_checking_perf__interspersed_gets__complex_objects(self):
        numPops = 5000000
        self.begin_capturing_logging()
        for numChecks in [20, 100, 500, 2000]:
            with self.subTest(numChecks=numChecks):
                numRuns = numPops // numChecks
                # q.qsize()
                import random
                toInsert1 = list(i for i in range(0, numChecks))
                toInsert2 = list(i for i in range(0, numChecks))
                random.shuffle(toInsert1)
                random.shuffle(toInsert2)

                toInsert = []
                for i in range(0, numChecks - 1):
                    toInsert.append(((toInsert2[i] & 1) == 0, toInsert1[i] ^ toInsert2[i], toInsert1[i] * 0.1 + toInsert2[i - 1], toInsert1[i]))

                # benchmark the task
                result = timeit(
                    '''
myDeque = Heap(max=True)
val = None
for i in toInsert:
    myDeque.push(i)
    if i[0]:
        val = myDeque.pop()
while len(myDeque) > 0:
    val = myDeque.pop()
                    ''',
                    setup=f'''
from heap_class import Heap
                    ''',
                    number=numRuns,
                    globals=locals())

                # report the result
                logbook.info(f'{numChecks}: HeapClass(max) {result:.3f} seconds ({numRuns} runs of {numChecks} pushes + pops)')
