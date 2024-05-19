import time
from collections import deque

import logbook

from Algorithms import TileIslandBuilder
from Algorithms.TileIslandBuilder import IslandBuildMode
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot


class TileIslandBuilderUnitTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True
        bot.info_render_tile_islands = True

        return bot

    def assertAllIslandsContiguous(self, builder: TileIslandBuilder, debugMode: bool = False):
        q = deque()
        missed = set()
        for island in builder.all_tile_islands:
            missing = island.tile_set.copy()
            visited = set()
            tile = next(iter(island.tile_set))
            q.append(tile)

            while q:
                tile = q.popleft()

                if tile in visited:
                    continue

                visited.add(tile)
                missing.discard(tile)

                for t in tile.movable:
                    if t in missing:
                        q.append(t)

            if len(missing) > 0:
                missed.update(missing)

        if missed:
            err = f'The following non-contiguous tiles were found: {" | ".join([str(t) + " (" + str(builder.tile_island_lookup[t].name) + ")" for t in missed])}'
            if debugMode:
                def viMod(v: ViewInfo):
                    for t in missed:
                        v.add_targeted_tile(t)

                logbook.error(err)

                self.render_tile_islands(builder.map, builder, viewInfoMod=viMod)

            self.fail(err)

    def test_tile_islands_land_count_matches_tile_count(self):
        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        self.assertNotEqual(0, len(builder.all_tile_islands))

        for island in builder.all_tile_islands:
            self.assertEqual(island.tile_count, len(island.tile_set))

    def test_build_tile_islands__should_be_fast(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for mapSize, maxDuration in [
            ('small', 0.0003),
            ('large', 0.002)
        ]:
            with self.subTest(mapSize=mapSize):
                if mapSize == 'large':
                    mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
                else:
                    mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                if debugMode:
                    self.render_map(map)

                self.begin_capturing_logging()
                builder = TileIslandBuilder(map)

                start = time.perf_counter()
                builder.recalculate_tile_islands(enemyGeneral)
                self.assertAllIslandsContiguous(builder, debugMode)
                duration = time.perf_counter() - start
                self.assertLess(duration, maxDuration, 'should not take ages to build tile islands')

    def test_builds_tile_islands(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
        #
        # if debugMode:
        #     self.render_map(map)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        self.assertAllIslandsContiguous(builder, debugMode)

        bottomLeftNeutIsland = builder.tile_island_lookup[map.GetTile(1, 19)]
        self.assertEqual(12, bottomLeftNeutIsland.tile_count)
        self.assertEqual(0, bottomLeftNeutIsland.sum_army)

        enSmall1 = builder.tile_island_lookup[map.GetTile(17, 11)]
        self.assertEqual(2, enSmall1.tile_count)
        self.assertEqual(2, enSmall1.sum_army)

        enSmall2 = builder.tile_island_lookup[map.GetTile(17, 14)]
        self.assertEqual(2, enSmall2.tile_count)
        self.assertEqual(4, enSmall2.sum_army)

        playerCoreIsland = builder.tile_island_lookup[map.GetTile(1, 12)]

        playerEnIsland = builder.tile_island_lookup[map.GetTile(15, 12)]

        enCoreIsland = builder.tile_island_lookup[map.GetTile(12, 16)]

        enGenIsland = builder.tile_island_lookup[map.GetTile(14, 19)]

    def test_should_break_large_islands_up_by_area(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)
        #
        # if debugMode:
        #     self.render_map(map)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.BuildByDistance)
        self.assertAllIslandsContiguous(builder, debugMode)

        if debugMode:
            self.render_map(map)
            self.render_tile_islands(map, builder)

        topLeftEnIsland = builder.tile_island_lookup[map.GetTile(0, 0)]

        midLeftEnIsland = builder.tile_island_lookup[map.GetTile(0, 9)]

        bottomLeftEnIsland = builder.tile_island_lookup[map.GetTile(1, 15)]

        bottomRightEnIsland = builder.tile_island_lookup[map.GetTile(1, 15)]

        all = set()
        all.add(topLeftEnIsland)
        all.add(midLeftEnIsland)
        all.add(bottomLeftEnIsland)
        all.add(bottomRightEnIsland)
        self.assertEqual(4, len(all), 'should be distinct islands')

        # TODO assert stuff like including the joined-en-land-total-area

        self.assertEqual(69, topLeftEnIsland.tile_count_all_adjacent_friendly)

        self.assertEqual(244-3-3-3-3-3-3-2-2-2-3-2-2-2, topLeftEnIsland.sum_army_all_adjacent_friendly)

    def test_should_be_consistent_between_map_loads(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for mode in [IslandBuildMode.GroupByArmy, IslandBuildMode.BuildByDistance]:
            with self.subTest(mode=mode):
                mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'

                mapA, generalA, enemyGeneralA = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

                mapB, generalB, enemyGeneralB = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

                self.begin_capturing_logging()
                builderA = TileIslandBuilder(mapA)
                builderA.recalculate_tile_islands(enemyGeneralA, mode=mode)
                self.assertAllIslandsContiguous(builderA)

                builderB = TileIslandBuilder(mapB)
                builderB.recalculate_tile_islands(enemyGeneralB, mode=mode)
                self.assertAllIslandsContiguous(builderB)

                mismatches = set()

                # for islandA in builderA.all_tile_islands:
                #     sampleTile = next(iter(islandA.tile_set))
                #     islandB = builderB.tile_island_lookup[mapB.GetTile(sampleTile.x, sampleTile.y)]
                #
                #     for tile in islandA.tile_set:
                #         shouldAlsoBeIslandB = builderB.tile_island_lookup[mapB.GetTile(tile.x, tile.y)]
                #         if islandB is not shouldAlsoBeIslandB:
                #             mismatches.add(tile)

                for islandB in builderB.all_tile_islands:
                    sampleTile = next(iter(islandB.tile_set))
                    islandA = builderA.tile_island_lookup[mapA.GetTile(sampleTile.x, sampleTile.y)]

                    for tile in islandB.tile_set:
                        tileA = mapA.GetTile(tile.x, tile.y)
                        shouldAlsoBeIslandA = builderA.tile_island_lookup[tileA]
                        if islandA is not shouldAlsoBeIslandA:
                            mismatches.add(tileA)

                if mismatches:
                    if debugMode:
                        def markMismatches(viewInfo: ViewInfo):
                            for tile in mismatches:
                                viewInfo.add_targeted_tile(tile)
                        self.render_tile_islands(mapA, builderA, viewInfoMod=markMismatches)
                        self.render_tile_islands(mapB, builderB, viewInfoMod=markMismatches)

                    self.fail(f'The following mismatches were found between multiple load/runs: {" | ".join([str(t) for t in mismatches])}')

    def test_should_be_consistent_between_runs_on_same_map(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for mode in [IslandBuildMode.GroupByArmy, IslandBuildMode.BuildByDistance]:
            with self.subTest(mode=mode):
                mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'

                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

                self.begin_capturing_logging()
                builderA = TileIslandBuilder(map)
                builderA.recalculate_tile_islands(enemyGeneral, mode=mode)
                self.assertAllIslandsContiguous(builderA)

                builderB = TileIslandBuilder(map)
                builderB.recalculate_tile_islands(enemyGeneral, mode=mode)
                self.assertAllIslandsContiguous(builderB)

                mismatches = set()

                # for islandA in builderA.all_tile_islands:
                #     sampleTile = next(iter(islandA.tile_set))
                #     islandB = builderB.tile_island_lookup[mapA.GetTile(sampleTile.x, sampleTile.y)]
                #
                #     for tile in islandA.tile_set:
                #         shouldAlsoBeIslandB = builderB.tile_island_lookup[mapA.GetTile(tile.x, tile.y)]
                #         if islandB is not shouldAlsoBeIslandB:
                #             mismatches.add(tile)

                for islandB in builderB.all_tile_islands:
                    sampleTile = next(iter(islandB.tile_set))
                    islandA = builderA.tile_island_lookup[map.GetTile(sampleTile.x, sampleTile.y)]

                    for tile in islandB.tile_set:
                        tileA = map.GetTile(tile.x, tile.y)
                        shouldAlsoBeIslandA = builderA.tile_island_lookup[tileA]
                        if islandA is not shouldAlsoBeIslandA:
                            mismatches.add(tileA)

                if mismatches:
                    if debugMode:
                        def markMismatches(viewInfo: ViewInfo):
                            for tile in mismatches:
                                viewInfo.add_targeted_tile(tile)
                        self.render_tile_islands(map, builderA, viewInfoMod=markMismatches)
                        self.render_tile_islands(map, builderB, viewInfoMod=markMismatches)

                    self.fail(f'The following mismatches were found between multiple runs: {" | ".join([str(t) for t in mismatches])}')

    def test_should_group_by_army_values(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)
        #
        # if debugMode:
        #     self.render_map(map)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)

        if debugMode:
            self.render_tile_islands(map, builder)

        twoIsland1 = builder.tile_island_lookup[map.GetTile(11, 0)]

        twoIsland2 = builder.tile_island_lookup[map.GetTile(10, 1)]

        threeIsland1 = builder.tile_island_lookup[map.GetTile(11, 2)]

        threeIsland2 = builder.tile_island_lookup[map.GetTile(12, 4)]

        self.assertEqual(twoIsland1, twoIsland2, 'these 2 tiles should be grouped in the same island')
        self.assertEqual(threeIsland1, threeIsland2, 'these 3 tiles should be grouped in the same island')
        self.assertNotEqual(threeIsland1, twoIsland1, '2s and 3s should be separate islands')

    def test_builds_does_not_over_split_islands(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1                                
                    a3   a3   a3  
a20                 b1              
                    b1              
                    b1              
a2                                
                              bG1
|    |    |    |    | 
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        if debugMode:
            self.render_tile_islands(map, builder)

        island = builder.tile_island_lookup[map.GetTile(4, 1)]
        self.assertEqual(3, island.tile_count)
        self.assertEqual(9, island.sum_army)

    def test_builds_respecting_split_threshold(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1                                
                    a3   a3   a3  
a20                 b1              
                    b1              
                    b1              
a2                                
                              bG1
|    |    |    |    | 
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        if debugMode:
            self.render_tile_islands(map, builder)

        self.assertEqual(4, len(builder.tile_islands_by_player[enemyGeneral.player]))
