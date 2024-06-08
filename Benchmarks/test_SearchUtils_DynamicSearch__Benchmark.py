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
from base.client.tile import Tile


class SearchUtils_DynamicSearch_BenchmarkTests(TestBase):
    def run_shortest_path_algo_comparison(self, map, ranges, skipFloyd: bool = True):
        points = list(map.pathable_tiles)
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

    # def test_benchmark_dynamic_algo_times_via_dynamic_search(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
    #     mapFile = 'GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap'
    #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 708, fill_out_tiles=True)
    #
    #     startTiles = [map.GetTile(23, 4)]
    #
    #     SearchUtils.breadth_first_dynamic_max(
    #         map,
    #
    #     )
    #
    # def test_benchmark_gather_times(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
    #     mapFile = 'GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap'
    #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 708, fill_out_tiles=True)
    #
    #     startTiles = [map.GetTile(23, 4)]
    #
    #     SearchUtils.breadth_first_dynamic_max(
    #         map,
    #
    #     )