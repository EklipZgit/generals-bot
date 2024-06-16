import random
import time
import typing
import disjoint_set as ds
import scipy
import unionfind as uf

import logbook

from Algorithms import FastDisjointSet
from Tests.TestBase import TestBase
from base.client.tile import Tile


class UnionFindSetBenchmarkTests(TestBase):
    def test_benchmark_____(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # UNIONFOREST RUNTIME IS APPALLING IF using .groups(). If you somehow dont use that, it is slightly faster..
        # SCIPY is slightly slower (x1.28 on large), BUT has a set size? Scipy.subset is not efficient to call repeatedly, does not cache.
        # Scipy is more costly when initializing from the full map. Scipy is cheaper when dynamically .adding nodes before merging them.

        for mapSize in [
            'small',
            'large'
        ]:
            for accesses in [
                # 5000,
                # 750,
                # 500,
                # 300,
                # 200,
                # 120,
                # 100,
                # 90,
                # 80,
                # 70,
                # 60,
                # 50,
                # 40,
                # 35,
                # 20,
                # 5,
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
                            mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'

                        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                        allTiles = list(map.get_all_tiles())

                        # self.render_map(map)

                        # TODO maybe time to learn how to cython shit and impl  https://github.com/eldridgejm/unionfind

                        # playerTilesSorted = sorted(map.players[general.player].tiles, key=lambda t: t.army, reverse=True)
                        # enTilesSorted = sorted(map.players[general.player].tiles, key=lambda t: t.army, reverse=True)

                        self.begin_capturing_logging()

                        # unionForestTotalDur = 0.0
                        disjSetTotalDuration = 0.0
                        sciPyDisjSetTotalDuration = 0.0

                        # last = map.generals[map.player_index]

                        for i in range(500):
                            randTiles = random.choices(allTiles, k=min(len(allTiles), numInSet))

                            start = time.perf_counter()
                            #
                            # # purely int based  https://github.com/SaitoTsutomu/unionfind
                            # ufForest = uf.unionfind(map.rows * map.cols)
                            # # forest = unionfind(3) # There are 3 items.
                            # # forest.unite(0, 2) # Set 0 and 2 to same group.
                            # # forest.issame(1, 2) # Ask "Are 1 and 2 same?"
                            # # forest.groups() # Return groups.
                            #
                            # for t in randTiles:
                            #     found = ufForest.find(t.tile_index)
                            #     for adj in t.movable:
                            #         if adj.player == t.player:
                            #             ufForest.unite(adj.tile_index, t.tile_index)
                            # groups: typing.List[typing.List[int]] = ufForest.groups()
                            # unionForestDuration = time.perf_counter() - start
                            # unionForestTotalDur += unionForestDuration

                            start = time.perf_counter()

                            # int approach with DS  https://github.com/mrapacz/disjoint-set/blob/master/README.md
                            # dsIntForest: ds.DisjointSet[int] = ds.DisjointSet.from_iterable(range(map.rows * map.cols))
                            # dsIntForest: ds.DisjointSet[int] = ds.DisjointSet.from_iterable(t.tile_index for t in randTiles)
                            dsIntForest: ds.DisjointSet[int] = ds.DisjointSet()

                            for t in randTiles:
                                # found = dsIntForest.find(t.tile_index)
                                for adj in t.movable:
                                    if adj.player == t.player:
                                        dsIntForest.union(adj.tile_index, t.tile_index)

                            groupDisjIntSets: typing.List[typing.Set[int]] = list(dsIntForest.itersets())
                            disjSetDuration = time.perf_counter() - start
                            disjSetTotalDuration += disjSetDuration

                            start = time.perf_counter()

                            # int approach with DS  https://github.com/mrapacz/disjoint-set/blob/master/README.md
                            # scipyIntForest: scipy.cluster.hierarchy.DisjointSet = scipy.cluster.hierarchy.DisjointSet(range(map.rows * map.cols))
                            # scipyIntForest: scipy.cluster.hierarchy.DisjointSet = scipy.cluster.hierarchy.DisjointSet()
                            # scipyIntForest: scipy.cluster.hierarchy.DisjointSet = scipy.cluster.hierarchy.DisjointSet(t.tile_index for t in randTiles)
                            scipyIntForest: FastDisjointSet = FastDisjointSet()

                            for t in randTiles:
                                # scipyIntForest.add(t.tile_index)
                                # found = scipyIntForest.subset_size(t.tile_index)
                                # found = scipyIntForest.subset(t.tile_index)
                                # found = scipyIntForest.add(t.tile_index)
                                for adj in t.movable:
                                    if adj.player == t.player:
                                        # scipyIntForest.add(adj.tile_index)
                                        scipyIntForest.merge(adj.tile_index, t.tile_index)
                                        # scipyIntForest.merge_fast(adj.tile_index, t.tile_index)

                            groupScipyDisjIntSets: typing.List[typing.Set[int]] = scipyIntForest.subsets()
                            sciPyDisjSetDuration = time.perf_counter() - start
                            sciPyDisjSetTotalDuration += sciPyDisjSetDuration

                            for scipySet in groupScipyDisjIntSets:
                                tBase = next(iter(scipySet))
                                for tIdx in scipySet:
                                    self.assertTrue(dsIntForest.connected(tBase, tIdx))

                            for dsSet in groupDisjIntSets:
                                if len(dsSet) <= 1:
                                    continue
                                for tIdx in dsSet:
                                    scipySet = scipyIntForest.subset(tIdx)
                                    for otherTIdx in dsSet:
                                        self.assertIn(otherTIdx, scipySet)

                        logbook.info(f'disjSet duration {disjSetTotalDuration:.4f} vs scyPyDisjSet duration {sciPyDisjSetTotalDuration:.4f} at num rand tiles {numInSet} + retrievals {accesses} (ratio {sciPyDisjSetTotalDuration / disjSetTotalDuration:.3f})')

                        # self.assertLess(unionForestTotalDur, disjSetTotalDuration, f'unionForest stopped being faster at num "added" {numInSet} + retrievals {accesses}')
