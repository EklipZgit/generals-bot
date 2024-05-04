import random
import time
import typing
from collections import deque
from queue import PriorityQueue
from timeit import timeit

import logbook

import SearchUtils
from DistanceMapperImpl import DistanceMapperImpl
from MapMatrix import MapMatrix, MapMatrixSet  #, MapMatrixSetWithLength, MapMatrixSetWithLengthAndTiles
from Tests.TestBase import TestBase
from ViewInfo import PathColorer
from base.client.tile import Tile


class MapMatrixBenchmarkTests(TestBase):
    def test_benchmark_mapmatrix_nSquared_retrievals_should_be_faster_than_dict(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            with self.subTest(mapSize=mapSize):
                if mapSize == 'large':
                    mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                else:
                    mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                self.begin_capturing_logging()

                mapMatrixTotalDur = 0.0
                dictTotalDuration = 0.0

                for i in range(50):
                    val = 0
                    start = time.perf_counter()
                    matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
                    for tile1 in map.pathableTiles:
                        for tile2 in map.pathableTiles:
                            val += matrix[tile2] - matrix[tile1]
                    mapMatrixDuration = time.perf_counter() - start
                    mapMatrixTotalDur += mapMatrixDuration

                    val = 0
                    start = time.perf_counter()
                    dictLookup: typing.Dict[Tile, int] = {}
                    for tile in map.pathableTiles:
                        dictLookup[tile] = 1
                    for tile1 in map.pathableTiles:
                        for tile2 in map.pathableTiles:
                            val += dictLookup[tile2] - dictLookup[tile1]
                    dictDuration = time.perf_counter() - start
                    dictTotalDuration += dictDuration

                logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f}')

                self.assertLess(mapMatrixTotalDur, dictTotalDuration, 'mapMatrix should be faster in N^2 scenarios')

    # def test_benchmark_mapmatrix_n_retrievals_should_be_faster_than_flat(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #
    #     for mapSize in [
    #         'small',
    #         'large'
    #     ]:
    #         for accesses in [
    #             10000,
    #             5000,
    #             2000,
    #             1000,
    #             500,
    #             300,
    #             250,
    #             200,
    #             150,
    #             125,
    #             100,
    #             75
    #         ]:
    #             with self.subTest(mapSize=mapSize, accesses=accesses):
    #                 if mapSize == 'large':
    #                     mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
    #                 else:
    #                     mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
    #
    #                 map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
    #
    #                 self.begin_capturing_logging()
    #
    #                 mapMatrixTotalDur = 0.0
    #                 flatTotalDuration = 0.0
    #                 last = map.generals[map.player_index]
    #
    #                 for i in range(1000):
    #                     val = 0
    #                     iter = accesses // 2
    #                     start = time.perf_counter()
    #                     matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
    #                     while iter > 0:
    #                         for tile1 in map.pathableTiles:
    #                             val += matrix[last] - matrix[tile1]
    #                             last = tile1
    #                             iter -= 1
    #                             if iter == 0:
    #                                 break
    #                     mapMatrixDuration = time.perf_counter() - start
    #                     mapMatrixTotalDur += mapMatrixDuration
    #
    #                     val = 0
    #                     iter = accesses // 2
    #                     start = time.perf_counter()
    #                     mapMatrixFlat: MapMatrixSmall[int] = MapMatrixSmall(map, 1)
    #                     while iter > 0:
    #                         for tile1 in map.pathableTiles:
    #                             val += mapMatrixFlat[last] - mapMatrixFlat[tile1]
    #                             last = tile1
    #                             iter -= 1
    #                             if iter == 0:
    #                                 break
    #                     flatDuration = time.perf_counter() - start
    #                     flatTotalDuration += flatDuration
    #
    #                 logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs flat duration {flatTotalDuration:.4f} for {accesses} accesses (ratio {mapMatrixTotalDur / flatTotalDuration:.3f})')
    #
    #                 self.assertLess(mapMatrixTotalDur, flatTotalDuration, f'mapMatrix should be faster in {accesses} scenarios')

    # def test_benchmark_mapmatrix__find_point_where_2d_matrix_faster_than_flat(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #
    #     for mapSize in [
    #         'small',
    #         'large'
    #     ]:
    #         for accesses in [
    #             50000,
    #             2000,
    #             1000,
    #             500,
    #             300,
    #             250,
    #             200,
    #             150,
    #             125,
    #             100,
    #             75
    #         ]:
    #             with self.subTest(mapSize=mapSize, accesses=accesses):
    #                 if mapSize == 'large':
    #                     mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
    #                 else:
    #                     mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
    #
    #                 map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
    #
    #                 self.begin_capturing_logging()
    #
    #                 mapMatrixTotalDur = 0.0
    #                 flatTotalDuration = 0.0
    #                 last = map.generals[map.player_index]
    #
    #                 runs = 5000
    #                 if accesses >= 10000:
    #                     runs = 500
    #
    #                 for i in range(runs):
    #                     val = 0
    #                     iterLeft = accesses // 2  # we do 2 accesses per iter
    #                     start = time.perf_counter()
    #                     matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
    #                     while iterLeft > 0:
    #                         for tile1 in map.pathableTiles:
    #                             val += matrix[last] - matrix[tile1]
    #                             last = tile1
    #                             iterLeft -= 1
    #                             if iterLeft == 0:
    #                                 break
    #                     mapMatrixDuration = time.perf_counter() - start
    #                     mapMatrixTotalDur += mapMatrixDuration
    #
    #                     val = 0
    #                     iterLeft = accesses // 2  # we do 2 accesses per iter
    #                     start = time.perf_counter()
    #                     mapMatrixFlat: MapMatrixSmall[int] = MapMatrixSmall(map, 1)
    #                     while iterLeft > 0:
    #                         for tile1 in map.pathableTiles:
    #                             val += mapMatrixFlat[last] - mapMatrixFlat[tile1]
    #                             last = tile1
    #                             iterLeft -= 1
    #                             if iterLeft == 0:
    #                                 break
    #                     flatDuration = time.perf_counter() - start
    #                     flatTotalDuration += flatDuration
    #
    #                 logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs flat duration {flatTotalDuration:.4f} for accesses {accesses}')
    #
    #                 self.assertLess(mapMatrixTotalDur, flatTotalDuration, f'mapMatrix was not faster for {accesses}')
    #
    # def test_benchmark_mapmatrix__compare_initialize_with_flat_matrix(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #
    #     for mapSize in [
    #         'small',
    #         'large'
    #     ]:
    #         with self.subTest(mapSize=mapSize):
    #             if mapSize == 'large':
    #                 mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
    #             else:
    #                 mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
    #
    #             map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
    #
    #             self.begin_capturing_logging()
    #
    #             mapMatrixTotalDur = 0.0
    #             flatTotalDuration = 0.0
    #             last = map.generals[map.player_index]
    #
    #             for i in range(5000):
    #                 start = time.perf_counter()
    #                 matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
    #                 mapMatrixDuration = time.perf_counter() - start
    #                 mapMatrixTotalDur += mapMatrixDuration
    #
    #                 start = time.perf_counter()
    #                 mapMatrixFlat: MapMatrixSmall[int] = MapMatrixSmall(map, 1)
    #                 flatDuration = time.perf_counter() - start
    #                 flatTotalDuration += flatDuration
    #
    #             logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs flat duration {flatTotalDuration:.4f}')
    #
    #             self.assertGreater(mapMatrixTotalDur, flatTotalDuration, f'mapMatrix should never be faster to initialize')

    def test_benchmark_mapmatrix__assign_plus_retrieve__find_point_where_dict_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                5000,
                750,
                500,
                300,
                200,
                120,
                100,
                90,
                80,
                70,
                60,
                50,
                40,
                35,
                20,
                5,
                1,
            ]:
                for numInSet in [
                    5000,
                    750,
                    500,
                    300,
                    200,
                    120,
                    100,
                    90,
                    80,
                    70,
                    60,
                    50,
                    40,
                    35,
                    20,
                    5,
                    1,
                ]:
                    with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numInSet):
                        if mapSize == 'large':
                            mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                        else:
                            mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        self.begin_capturing_logging()

                        mapMatrixTotalDur = 0.0
                        dictTotalDuration = 0.0

                        last = map.generals[map.player_index]

                        for i in range(500):
                            randTiles = [random.choice(allTiles) for t in range(numInSet)]
                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            matrix: MapMatrixInterface[int] = MapMatrix(map, 0, emptyVal=None)
                            for tile in randTiles:
                                matrix.add(tile, 1)
                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    val += matrix[last] - matrix[tile]
                                    itrLeft -= 1
                                    last = tile
                                    if itrLeft == 0:
                                        break

                            mapMatrixDuration = time.perf_counter() - start
                            mapMatrixTotalDur += mapMatrixDuration

                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            dictLookup: typing.Dict[Tile, int] = {last: 1}
                            # dict only gets
                            for tile in randTiles:
                                dictLookup[tile] = 1

                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    val += dictLookup.get(last, -1) - dictLookup.get(tile, 0)
                                    last = tile
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            dictDuration = time.perf_counter() - start
                            dictTotalDuration += dictDuration

                        logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at num "added" {numInSet} + retrievals {accesses} (ratio {dictTotalDuration / mapMatrixTotalDur:.3f})')

                        self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at num "added" {numInSet} + retrievals {accesses}')

    def test_benchmark_mapmatrix__assign_plus_retrieve__find_point_where_dict_getitem_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                5000,
                750,
                500,
                300,
                200,
                120,
                100,
                90,
                80,
                70,
                60,
                50,
                40,
                35,
                20,
                5,
                1,
            ]:
                for numInSet in [
                    5000,
                    750,
                    500,
                    300,
                    200,
                    120,
                    100,
                    90,
                    80,
                    70,
                    60,
                    50,
                    40,
                    35,
                    20,
                    5,
                    1,
                ]:
                    with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numInSet):
                        if mapSize == 'large':
                            mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                        else:
                            mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        self.begin_capturing_logging()

                        mapMatrixTotalDur = 0.0
                        dictTotalDuration = 0.0

                        last = map.generals[map.player_index]

                        for i in range(100):
                            randTiles = [random.choice(allTiles) for t in range(numInSet)]
                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            matrix: MapMatrixInterface[int] = MapMatrix(map, 0, emptyVal=None)
                            for tile in randTiles:
                                matrix[tile] = 1
                            while itrLeft > 0:
                                for tile in randTiles:
                                    val += matrix[last] - matrix[tile]
                                    itrLeft -= 1
                                    last = tile
                                    if itrLeft == 0:
                                        break

                            mapMatrixDuration = time.perf_counter() - start
                            mapMatrixTotalDur += mapMatrixDuration

                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            dictLookup: typing.Dict[Tile, int] = {last: 1}
                            # dict only gets
                            for tile in randTiles:
                                dictLookup[tile] = 1
                            last = randTiles[0]
                            while itrLeft > 0:
                                for tile in randTiles:
                                    val += dictLookup[last] - dictLookup[tile]
                                    last = tile
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            dictDuration = time.perf_counter() - start
                            dictTotalDuration += dictDuration

                        logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at num "added" {numInSet} + retrievals {accesses} (ratio {dictTotalDuration / mapMatrixTotalDur:.3f})')

                        self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at num "added" {numInSet} + retrievals {accesses}')

    def test_benchmark_mapmatrix__direct_access__assign_plus_retrieve__find_point_where_dict_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                5000,
                750,
                500,
                300,
                200,
                120,
                100,
                90,
                80,
                70,
                60,
                50,
                40,
                35,
                20,
                5,
                1,
            ]:
                for numInSet in [
                    5000,
                    1500,
                    750,
                    400,
                    200,
                    100,
                    50,
                    30,
                    20,
                    15,
                    10,
                    7,
                    5,
                    1,
                ]:
                    with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numInSet):
                        if mapSize == 'large':
                            mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                        else:
                            mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        self.begin_capturing_logging()

                        mapMatrixTotalDur = 0.0
                        dictTotalDuration = 0.0

                        last = map.generals[map.player_index]

                        for i in range(500):
                            randTiles = [random.choice(allTiles) for t in range(numInSet)]
                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            matrix: MapMatrixInterface[int] = MapMatrix(map, 0)
                            for tile in randTiles:
                                matrix.raw[tile.tile_index] = 1
                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    val += matrix.raw[last.tile_index] - matrix.raw[tile.tile_index]
                                    itrLeft -= 1
                                    last = tile
                                    if itrLeft == 0:
                                        break

                            mapMatrixDuration = time.perf_counter() - start
                            mapMatrixTotalDur += mapMatrixDuration

                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            dictLookup: typing.Dict[Tile, int] = {last: 1}
                            # dict only gets
                            for tile in randTiles:
                                dictLookup[tile] = 1

                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    val += dictLookup.get(last, -1) - dictLookup.get(tile, 0)
                                    last = tile
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            dictDuration = time.perf_counter() - start
                            dictTotalDuration += dictDuration

                        logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs set duration {dictTotalDuration:.4f} at num "added" {numInSet} + retrievals {accesses} (ratio {dictTotalDuration / mapMatrixTotalDur:.3f})')

                        self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at num "added" {numInSet} + retrievals {accesses}')

    def test_benchmark_mapmatrix__direct_access__assign_plus_retrieve__find_point_where_dict_getitem_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                5000,
                750,
                500,
                300,
                200,
                120,
                100,
                90,
                80,
                70,
                60,
                50,
                40,
                35,
                20,
                5,
                1,
            ]:
                for numInSet in [
                    5000,
                    1500,
                    750,
                    400,
                    200,
                    100,
                    50,
                    30,
                    20,
                    15,
                    10,
                    7,
                    5,
                    1,
                ]:
                    with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numInSet):
                        if mapSize == 'large':
                            mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                        else:
                            mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        self.begin_capturing_logging()

                        mapMatrixTotalDur = 0.0
                        dictTotalDuration = 0.0

                        last = map.generals[map.player_index]

                        for i in range(500):
                            randTiles = [random.choice(allTiles) for t in range(numInSet)]
                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            matrix: MapMatrixInterface[int] = MapMatrix(map, 0)
                            for tile in randTiles:
                                matrix.raw[tile.tile_index] = 1
                            while itrLeft > 0:
                                for tile in randTiles:
                                    val += matrix.raw[last.tile_index] - matrix.raw[tile.tile_index]
                                    itrLeft -= 1
                                    last = tile
                                    if itrLeft == 0:
                                        break

                            mapMatrixDuration = time.perf_counter() - start
                            mapMatrixTotalDur += mapMatrixDuration

                            val = 0
                            itrLeft = accesses // 2
                            start = time.perf_counter()
                            dictLookup: typing.Dict[Tile, int] = {last: 1}
                            # dict only gets
                            for tile in randTiles:
                                dictLookup[tile] = 1

                            while itrLeft > 0:
                                for tile in randTiles:
                                    val += dictLookup[last] - dictLookup[tile]
                                    last = tile
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            dictDuration = time.perf_counter() - start
                            dictTotalDuration += dictDuration

                        logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs set duration {dictTotalDuration:.4f} at num "added" {numInSet} + retrievals {accesses} (ratio {dictTotalDuration / mapMatrixTotalDur:.3f})')

                        self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at num "added" {numInSet} + retrievals {accesses}')

    def test_benchmark_mapmatrixset__assign_plus_retrieve__find_point_where_set_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                5000,
                750,
                500,
                300,
                200,
                140,
                120,
                110,
                100,
                90,
                80,
                70,
                60,
                50,
                40,
                35,
                20,
                10,
                5,
                2
            ]:
                for numAdds in [
                    5000,
                    1500,
                    750,
                    300,
                    200,
                    150,
                    120,
                    110,
                    100,
                    85,
                    75,
                    50,
                    40,
                    30,
                    20,
                    10,
                    2,
                ]:
                    with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numAdds):
                        if mapSize == 'large':
                            mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                        else:
                            mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        self.begin_capturing_logging()

                        mapMatrixTotalDur = 0.0
                        setTotalDuration = 0.0

                        for i in range(100):
                            randTiles = [random.choice(allTiles) for i in range(numAdds)]
                            val = 0
                            itrLeft = accesses
                            start = time.perf_counter()
                            matrix: MapMatrixSet = MapMatrixSet(map)
                            for tile in randTiles:
                                matrix.add(tile)
                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    if tile in matrix:
                                        val += 1
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            mapMatrixDuration = time.perf_counter() - start
                            mapMatrixTotalDur += mapMatrixDuration

                            val = 0
                            start = time.perf_counter()
                            setLookup: typing.Set[Tile] = set()
                            # set only gets
                            for tile in randTiles:
                                setLookup.add(tile)

                            itrLeft = accesses
                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    if tile in setLookup:
                                        val += 1
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            setDuration = time.perf_counter() - start
                            setTotalDuration += setDuration

                        logbook.info(f'mapMatrixSet duration {mapMatrixTotalDur:.4f} vs set duration {setTotalDuration:.4f} at num "added" {numAdds} + retrievals {accesses} (ratio {setTotalDuration / mapMatrixTotalDur:.3f})')

                        self.assertLess(mapMatrixTotalDur, setTotalDuration, f'mapMatrixSet stopped being faster at num "added" {numAdds} + retrievals {accesses}')

    def test_benchmark_mapmatrixset__direct_access__assign_plus_retrieve__find_point_where_set_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                5000,
                750,
                500,
                300,
                200,
                140,
                120,
                110,
                100,
                90,
                80,
                70,
                60,
                50,
                40,
                35,
                20,
                10,
                7,
                2
            ]:
                for numAdds in [
                    5000,
                    1500,
                    750,
                    300,
                    200,
                    150,
                    120,
                    110,
                    100,
                    85,
                    75,
                    65,
                    50,
                    40,
                    30,
                    20,
                    10,
                    5,
                    2,
                ]:
                    with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numAdds):
                        if mapSize == 'large':
                            mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                        else:
                            mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        self.begin_capturing_logging()

                        mapMatrixTotalDur = 0.0
                        setTotalDuration = 0.0

                        for i in range(100):
                            randTiles = [random.choice(allTiles) for i in range(numAdds)]
                            val = 0
                            itrLeft = accesses
                            start = time.perf_counter()
                            matrix: MapMatrixSet = MapMatrixSet(map)
                            for tile in randTiles:
                                matrix.raw[tile.tile_index] = True
                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    if matrix.raw[tile.tile_index]:
                                        val += 1
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            mapMatrixDuration = time.perf_counter() - start
                            mapMatrixTotalDur += mapMatrixDuration

                            val = 0
                            start = time.perf_counter()
                            setLookup: typing.Set[Tile] = set()
                            # set only gets
                            for tile in randTiles:
                                setLookup.add(tile)

                            itrLeft = accesses
                            while itrLeft > 0:
                                for tile in map.pathableTiles:
                                    if tile in setLookup:
                                        val += 1
                                    itrLeft -= 1
                                    if itrLeft == 0:
                                        break
                            setDuration = time.perf_counter() - start
                            setTotalDuration += setDuration

                        logbook.info(f'mapMatrixSet direct access duration {mapMatrixTotalDur:.4f} vs set duration {setTotalDuration:.4f} at num "added" {numAdds} + retrievals {accesses} (ratio {setTotalDuration / mapMatrixTotalDur:.3f})')

                        self.assertLess(mapMatrixTotalDur, setTotalDuration, f'mapMatrixSet direct access stopped being faster at num "added" {numAdds} + retrievals {accesses}')
    #
    # def test_benchmark_mapmatrixsetwithlength__assign_plus_retrieve__find_point_where_set_is_better(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #
    #     for mapSize in [
    #         'small',
    #         'large'
    #     ]:
    #         for accesses in [
    #             5000,
    #             750,
    #             300,
    #             200,
    #             150,
    #             100,
    #             75,
    #             50,
    #             20,
    #             10,
    #             2,
    #         ]:
    #             for numAdds in [
    #                 5000,
    #                 1500,
    #                 750,
    #                 300,
    #                 200,
    #                 150,
    #                 120,
    #                 100,
    #                 75,
    #                 50,
    #                 40,
    #                 30,
    #                 20,
    #                 10,
    #                 2,
    #             ]:
    #                 with self.subTest(mapSize=mapSize, accesses=accesses, numInSet=numAdds):
    #                     if mapSize == 'large':
    #                         mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
    #                     else:
    #                         mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
    #
    #                     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
    #
    #                     allTiles = list(map.get_all_tiles())
    #
    #                     self.begin_capturing_logging()
    #
    #                     mapMatrixTotalDur = 0.0
    #                     setTotalDuration = 0.0
    #
    #                     for i in range(100):
    #                         randTiles = [random.choice(allTiles) for i in range(numAdds)]
    #                         val = 0
    #                         itrLeft = accesses
    #                         start = time.perf_counter()
    #                         matrix: MapMatrixSetWithLength = MapMatrixSetWithLength(map)
    #                         for tile in randTiles:
    #                             matrix.add(tile)
    #                         while itrLeft > 0:
    #                             for tile in map.pathableTiles:
    #                                 if tile in matrix:
    #                                     val += 1
    #                                 itrLeft -= 1
    #                                 if itrLeft == 0:
    #                                     break
    #                         mapMatrixDuration = time.perf_counter() - start
    #                         mapMatrixTotalDur += mapMatrixDuration
    #
    #                         val = 0
    #                         start = time.perf_counter()
    #                         setLookup: typing.Set[Tile] = set()
    #                         # set only gets
    #                         for tile in randTiles:
    #                             setLookup.add(tile)
    #
    #                         itrLeft = accesses
    #                         while itrLeft > 0:
    #                             for tile in map.pathableTiles:
    #                                 if tile in setLookup:
    #                                     val += 1
    #                                 itrLeft -= 1
    #                                 if itrLeft == 0:
    #                                     break
    #                         setDuration = time.perf_counter() - start
    #                         setTotalDuration += setDuration
    #
    #                     logbook.info(f'mapMatrixWithLength duration {mapMatrixTotalDur:.4f} vs set duration {setTotalDuration:.4f} at num "added" {numAdds} + retrievals {accesses} (ratio {setTotalDuration / mapMatrixTotalDur:.3f})')
    #
    #                     self.assertLess(mapMatrixTotalDur, setTotalDuration, f'mapMatrix stopped being faster at num "added" {numAdds} + retrievals {accesses}')
    # #
    # def test_benchmark_mapmatrixsetwithlengthandtiles__assign_plus_retrieve__find_point_where_set_is_better(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #
    #     for mapSize in [
    #         'small',
    #         'large'
    #     ]:
    #         for accesses in [
    #             5000,
    #             750,
    #             500,
    #             300,
    #             250,
    #             200,
    #             175,
    #             150,
    #             120,
    #             100,
    #             75,
    #             50,
    #             20,
    #             10,
    #             1
    #         ]:
    #             for numAdds in [
    #                 5000,
    #                 1500,
    #                 750,
    #                 500,
    #                 300,
    #                 250,
    #                 200,
    #                 175,
    #                 150,
    #                 120,
    #                 100,
    #                 75,
    #                 50,
    #                 10,
    #                 1
    #             ]:
    #                 with self.subTest(mapSize=mapSize, accesses=accesses, numAdds=numAdds):
    #                     if mapSize == 'large':
    #                         mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
    #                     else:
    #                         mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
    #
    #                     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
    #
    #                     allTiles = list(map.get_all_tiles())
    #
    #                     self.begin_capturing_logging()
    #
    #                     mapMatrixTotalDur = 0.0
    #                     setTotalDuration = 0.0
    #
    #                     for i in range(100):
    #                         randTiles = [random.choice(allTiles) for i in range(numAdds)]
    #                         val = 0
    #                         itrLeft = accesses
    #                         start = time.perf_counter()
    #                         matrix: MapMatrixSetWithLengthAndTiles = MapMatrixSetWithLengthAndTiles(map)
    #                         for tile in randTiles:
    #                             matrix.add(tile)
    #                         while itrLeft > 0:
    #                             for tile in map.pathableTiles:
    #                                 if tile in matrix:
    #                                     val += 1
    #                                 itrLeft -= 1
    #                                 if itrLeft == 0:
    #                                     break
    #                         mapMatrixDuration = time.perf_counter() - start
    #                         mapMatrixTotalDur += mapMatrixDuration
    #
    #                         val = 0
    #                         itrLeft = accesses
    #                         start = time.perf_counter()
    #                         setLookup: typing.Set[Tile] = set()
    #                         # set only gets
    #                         for tile in randTiles:
    #                             setLookup.add(tile)
    #
    #                         while itrLeft > 0:
    #                             for tile in map.pathableTiles:
    #                                 if tile in setLookup:
    #                                     val += 1
    #                                 itrLeft -= 1
    #                                 if itrLeft == 0:
    #                                     break
    #                         setDuration = time.perf_counter() - start
    #                         setTotalDuration += setDuration
    #
    #                     logbook.info(f'mapMatrixWithLengthAndTiles duration {mapMatrixTotalDur:.4f} vs set duration {setTotalDuration:.4f} at num "added" {min(len(randTiles), numAdds)} + retrievals {accesses} (ratio {setTotalDuration / mapMatrixTotalDur:.3f})')
    #
    #                     self.assertLess(mapMatrixTotalDur, setTotalDuration, f'mapMatrixWithLengthAndTiles stopped being faster at num "added" {min(len(randTiles), numAdds)} + retrievals {accesses}')

    # def test_benchmark_mapmatrix_numericsmall__assign_plus_retrieve__find_point_where_dict_is_better(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #
    #     for mapSize in [
    #         'small',
    #         'large'
    #     ]:
    #         for iterations in [
    #             5000,
    #             300,
    #             200,
    #             150,
    #             125,
    #             100,
    #             75,
    #             50,
    #             20,
    #             15,
    #             13,
    #             10,
    #             7,
    #             5,
    #             4,
    #             3,
    #             2,
    #             1,
    #         ]:
    #             with self.subTest(mapSize=mapSize, iterations=iterations):
    #                 if mapSize == 'large':
    #                     mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
    #                 else:
    #                     mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
    #
    #                 map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
    #
    #                 allTiles = list(map.get_all_tiles())
    #
    #                 self.begin_capturing_logging()
    #
    #                 mapMatrixTotalDur = 0.0
    #                 dictTotalDuration = 0.0
    #
    #                 last = map.generals[map.player_index]
    #
    #                 for i in range(100):
    #                     val = 0.0
    #                     itrLeft = iterations // 2
    #                     start = time.perf_counter()
    #                     matrix: MapMatrixNumericSmall = MapMatrixNumericSmall(map, 1.0)
    #                     while itrLeft > 0:
    #                         for tile in map.pathableTiles:
    #                             val += matrix[last] - matrix[tile]
    #                             last = tile
    #                             itrLeft -= 1
    #                             if itrLeft == 0:
    #                                 break
    #                     mapMatrixDuration = time.perf_counter() - start
    #                     mapMatrixTotalDur += mapMatrixDuration
    #
    #                     val = 0.0
    #                     itrLeft = iterations
    #                     start = time.perf_counter()
    #                     dictLookup: typing.Dict[Tile, float] = {last: 1.0}
    #                     # dict only gets
    #                     for tile in map.pathableTiles:
    #                         dictLookup[tile] = 1.0
    #                         itrLeft -= 1
    #                         if itrLeft == 0:
    #                             break
    #
    #                     itrLeft = iterations // 2
    #                     while itrLeft > 0:
    #                         for tile in map.pathableTiles:
    #                             val += dictLookup.get(last, -1.0) - dictLookup.get(tile, 0.0)
    #                             last = tile
    #                             itrLeft -= 1
    #                             if itrLeft == 0:
    #                                 break
    #                     dictDuration = time.perf_counter() - start
    #                     dictTotalDuration += dictDuration
    #
    #                 logbook.info(f'mapMatrixNumericSmall duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at assignments {min(len(allTiles), iterations)} + retrievals {iterations}')
    #
    #                 self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrixNumericSmall stopped being faster at assignments {min(len(allTiles), iterations)} + retrievals {iterations}')

    def test_benchmark_mapmatrix__copy__find_size_where_dict_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for size in [
                5000,
                750,
                500,
                300,
                200,
                100,
                50,
                20,
                15,
                13,
                10,
                7,
                5,
            ]:
                if mapSize == 'large':
                    mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                else:
                    mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                allTiles = list(map.get_all_tiles())

                size = min(size, len(allTiles))

                with self.subTest(mapSize=mapSize, size=size):
                    self.begin_capturing_logging()

                    mapMatrixTotalDur = 0.0
                    dictTotalDuration = 0.0

                    for i in range(5000):
                        matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
                        start = time.perf_counter()
                        matrix2 = matrix.copy()
                        mapMatrixDuration = time.perf_counter() - start
                        mapMatrixTotalDur += mapMatrixDuration

                        itrLeft = size
                        dictLookup: typing.Dict[Tile, int] = {}
                        # dict only gets
                        for tile in map.pathableTiles:
                            dictLookup[tile] = 1
                            itrLeft -= 1
                            if itrLeft == 0:
                                break
                        start = time.perf_counter()
                        dictLookup2 = dictLookup.copy()
                        dictDuration = time.perf_counter() - start
                        dictTotalDuration += dictDuration

                    logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at size {size}')

                    self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at size {size}')

    def test_benchmark_mapmatrix__initialize__check_dict_node_count_assignments(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'large',
            'small',
        ]:
            for dictNodeCount in [
                1000,
                750,
                500,
                300,
                200,
                100,
                50,
                40,
                30,
                20,
                10,
                7,
                5
            ]:
                with self.subTest(mapSize=mapSize, dictNodeCount=dictNodeCount):
                    if mapSize == 'large':
                        mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                    else:
                        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                    self.begin_capturing_logging()

                    mapMatrixTotalDur = 0.0
                    dictTotalDuration = 0.0

                    for i in range(5000):
                        start = time.perf_counter()
                        matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
                        mapMatrixDuration = time.perf_counter() - start
                        mapMatrixTotalDur += mapMatrixDuration

                        itrLeft = dictNodeCount
                        start = time.perf_counter()
                        dictLookup: typing.Dict[Tile, int] = {}
                        # dict only gets
                        for tile in map.pathableTiles:
                            dictLookup[tile] = 1
                            itrLeft -= 1
                            if itrLeft == 0:
                                break
                        dictDuration = time.perf_counter() - start
                        dictTotalDuration += dictDuration

                    logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at {dictNodeCount} tiles added to dict')

                    self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix initialization stopped being faster at dictNodeCount {dictNodeCount}')

    def test_benchmark_mapmatrix__retrieve__large_access_counts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for iterations in [
                100000,
                50000,
                10000
            ]:
                with self.subTest(mapSize=mapSize, iterations=iterations):
                    if mapSize == 'large':
                        mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                    else:
                        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                    self.begin_capturing_logging()

                    mapMatrixTotalDur = 0.0
                    dictTotalDuration = 0.0

                    last = map.generals[map.player_index]

                    for i in range(50):
                        val = 0
                        itrLeft = iterations
                        start = time.perf_counter()
                        matrix: MapMatrixInterface[int] = MapMatrix(map, 1)
                        while itrLeft > 0:
                            for tile in map.pathableTiles:
                                val += matrix[last] - matrix[tile]
                                last = tile
                                itrLeft -= 1
                                if itrLeft == 0:
                                    break
                        mapMatrixDuration = time.perf_counter() - start
                        mapMatrixTotalDur += mapMatrixDuration

                        val = 0
                        itrLeft = iterations
                        start = time.perf_counter()
                        dictLookup: typing.Dict[Tile, int] = {last: 1}
                        # dict only gets
                        for tile in map.pathableTiles:
                            dictLookup[tile] = 1
                            itrLeft -= 1
                            if itrLeft == 0:
                                break

                        itrLeft = iterations
                        while itrLeft > 0:
                            for tile in map.pathableTiles:
                                val += dictLookup.get(last, -1) - dictLookup.get(tile, 0)
                                last = tile
                                itrLeft -= 1
                                if itrLeft == 0:
                                    break
                        dictDuration = time.perf_counter() - start
                        dictTotalDuration += dictDuration

                    logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f}')

                    self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at iterations {iterations}')