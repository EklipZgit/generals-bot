import random
import time
import typing
from collections import deque
from queue import PriorityQueue
from timeit import timeit

import logbook

import SearchUtils
from DistanceMapperImpl import DistanceMapperImpl
from MapMatrix import MapMatrix, MapMatrixFlat, MapMatrixSet
from Tests.TestBase import TestBase
from ViewInfo import PathColorer
from base.client.map import Tile


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
                    matrix: MapMatrix[int] = MapMatrix(map, 1)
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

    def test_benchmark_mapmatrix_n_retrievals_should_be_faster_than_flat(self):
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
                flatTotalDuration = 0.0
                last = map.generals[map.player_index]

                for i in range(5000):
                    val = 0
                    start = time.perf_counter()
                    matrix: MapMatrix[int] = MapMatrix(map, 1)
                    for tile1 in map.pathableTiles:
                        val += matrix[last] - matrix[tile1]
                        last = tile1
                    mapMatrixDuration = time.perf_counter() - start
                    mapMatrixTotalDur += mapMatrixDuration

                    val = 0
                    start = time.perf_counter()
                    mapMatrixFlat: MapMatrixFlat[int] = MapMatrixFlat(map, 1)
                    for tile1 in map.pathableTiles:
                        val += mapMatrixFlat[last] - mapMatrixFlat[tile1]
                        last = tile1
                    flatDuration = time.perf_counter() - start
                    flatTotalDuration += flatDuration

                logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs flat duration {flatTotalDuration:.4f}')

                self.assertLess(mapMatrixTotalDur, flatTotalDuration, 'mapMatrix should be faster in N scenarios')

    def test_benchmark_mapmatrix__find_point_where_2d_matrix_faster_than_flat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                50000,
                2000,
                1000,
                500,
                300,
                250,
                200,
                150,
                125,
                100,
                75
            ]:
                with self.subTest(mapSize=mapSize, accesses=accesses):
                    if mapSize == 'large':
                        mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                    else:
                        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                    map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                    self.begin_capturing_logging()

                    mapMatrixTotalDur = 0.0
                    flatTotalDuration = 0.0
                    last = map.generals[map.player_index]

                    runs = 5000
                    if accesses >= 10000:
                        runs = 500

                    for i in range(runs):
                        val = 0
                        iterLeft = accesses // 2  # we do 2 accesses per iter
                        start = time.perf_counter()
                        matrix: MapMatrix[int] = MapMatrix(map, 1)
                        while iterLeft > 0:
                            for tile1 in map.pathableTiles:
                                val += matrix[last] - matrix[tile1]
                                last = tile1
                                iterLeft -= 1
                                if iterLeft == 0:
                                    break
                        mapMatrixDuration = time.perf_counter() - start
                        mapMatrixTotalDur += mapMatrixDuration

                        val = 0
                        iterLeft = accesses // 2  # we do 2 accesses per iter
                        start = time.perf_counter()
                        mapMatrixFlat: MapMatrixFlat[int] = MapMatrixFlat(map, 1)
                        while iterLeft > 0:
                            for tile1 in map.pathableTiles:
                                val += mapMatrixFlat[last] - mapMatrixFlat[tile1]
                                last = tile1
                                iterLeft -= 1
                                if iterLeft == 0:
                                    break
                        flatDuration = time.perf_counter() - start
                        flatTotalDuration += flatDuration

                    logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs flat duration {flatTotalDuration:.4f} for accesses {accesses}')

                    self.assertLess(mapMatrixTotalDur, flatTotalDuration, f'mapMatrix was not faster for {accesses}')

    def test_benchmark_mapmatrix__compare_initialize_with_flat_matrix(self):
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
                flatTotalDuration = 0.0
                last = map.generals[map.player_index]

                for i in range(5000):
                    start = time.perf_counter()
                    matrix: MapMatrix[int] = MapMatrix(map, 1)
                    mapMatrixDuration = time.perf_counter() - start
                    mapMatrixTotalDur += mapMatrixDuration

                    start = time.perf_counter()
                    mapMatrixFlat: MapMatrixFlat[int] = MapMatrixFlat(map, 1)
                    flatDuration = time.perf_counter() - start
                    flatTotalDuration += flatDuration

                logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs flat duration {flatTotalDuration:.4f}')

                self.assertGreater(mapMatrixTotalDur, flatTotalDuration, f'mapMatrix should never be faster to initialize')

    def test_benchmark_mapmatrix__assign_plus_retrieve__find_point_where_dict_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for iterations in [
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
                with self.subTest(mapSize=mapSize, iterations=iterations):
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
                        val = 0
                        itrLeft = iterations // 2
                        start = time.perf_counter()
                        matrix: MapMatrix[int] = MapMatrix(map, 1)
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

                        itrLeft = iterations // 2
                        while itrLeft > 0:
                            for tile in map.pathableTiles:
                                val += dictLookup.get(last, -1) - dictLookup.get(tile, 0)
                                last = tile
                                itrLeft -= 1
                                if itrLeft == 0:
                                    break
                        dictDuration = time.perf_counter() - start
                        dictTotalDuration += dictDuration

                    logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at assignments {min(len(allTiles), iterations)} + retrievals {iterations}')

                    self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrix stopped being faster at assignments {min(len(allTiles), iterations)} + retrievals {iterations}')

    def test_benchmark_mapmatrix__assign_plus_retrieve__find_point_where_set_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for numInSet in [
                5,
                10,
                15,
                20,
                30,
                50,
                100,
                200,
                400,
            ]:

                for accesses in [
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
                    with self.subTest(mapSize=mapSize, numInSet=numInSet, accesses=accesses):
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
                            randTiles = random.choices(allTiles, k=numInSet)
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

                        logbook.info(f'mapMatrix duration {mapMatrixTotalDur:.4f} vs set duration {setTotalDuration:.4f} at num "added" {min(len(allTiles), numInSet)} + retrievals {accesses}')

                        self.assertLess(mapMatrixTotalDur, setTotalDuration, f'mapMatrix stopped being faster at num "added" {min(len(allTiles), numInSet)} + retrievals {accesses}')

    def test_benchmark_mapmatrix_flat__assign_plus_retrieve__find_point_where_dict_is_better(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize in [
            'small',
            'large'
        ]:
            for iterations in [
                300,
                200,
                100,
                50,
                20,
                15,
                13,
                10,
                7,
                4,
                2,
            ]:
                with self.subTest(mapSize=mapSize, iterations=iterations):
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
                        val = 0
                        itrLeft = iterations // 2
                        start = time.perf_counter()
                        matrix: MapMatrixFlat[int] = MapMatrixFlat(map, 1)
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

                        itrLeft = iterations // 2
                        while itrLeft > 0:
                            for tile in map.pathableTiles:
                                val += dictLookup.get(last, -1) - dictLookup.get(tile, 0)
                                last = tile
                                itrLeft -= 1
                                if itrLeft == 0:
                                    break
                        dictDuration = time.perf_counter() - start
                        dictTotalDuration += dictDuration

                    logbook.info(f'mapMatrixFlat duration {mapMatrixTotalDur:.4f} vs dict duration {dictTotalDuration:.4f} at assignments {min(len(allTiles), iterations)} + retrievals {iterations}')

                    self.assertLess(mapMatrixTotalDur, dictTotalDuration, f'mapMatrixFlat stopped being faster at assignments {min(len(allTiles), iterations)} + retrievals {iterations}')

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
                        matrix: MapMatrix[int] = MapMatrix(map, 1)
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

    def test_benchmark_mapmatrix_flat__copy__find_size_where_dict_is_better(self):
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
                        matrix: MapMatrixFlat[int] = MapMatrixFlat(map, 1)
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
                        matrix: MapMatrixFlat[int] = MapMatrixFlat(map, 1)
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
                        matrix: MapMatrix[int] = MapMatrix(map, 1)
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