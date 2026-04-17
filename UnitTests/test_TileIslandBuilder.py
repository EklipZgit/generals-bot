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

    def mark_tile_army_incremented(self, tile, amount: int = 1):
        tile.army += amount
        tile.delta.oldArmy = tile.army - amount
        tile.delta.oldOwner = tile.player
        tile.delta.newOwner = tile.player

    def reset_tile_deltas_to_current_state(self, map):
        for tile in map.tiles_by_index:
            tile.delta.oldArmy = tile.army
            tile.delta.oldOwner = tile.player
            tile.delta.newOwner = tile.player

    def assertTilesRemainOnSameIslands(self, builder: TileIslandBuilder, tilesToIslands):
        for tile, island in tilesToIslands.items():
            self.assertIs(island, builder.tile_island_lookup[tile], f'{tile} should remain on the same island object after update')

    def assertNoFullIslandCycles(self, builder: TileIslandBuilder):
        seenIslands = set(builder.all_tile_islands)
        seenIslands.update(builder.tile_islands_by_unique_id.values())
        for island in seenIslands:
            self.assertIsNot(island.full_island, island, f'{island} should not reference itself as full_island')

            walked = set()
            cur = island
            while cur is not None:
                self.assertNotIn(cur.unique_id, walked, f'full_island chain should not cycle for {island}')
                walked.add(cur.unique_id)
                parent = cur.full_island
                if parent is not None:
                    self.assertIsNot(parent, cur, f'{cur} should not self-reference as full_island')
                    self.assertIsNotNone(parent.child_islands, f'full island parent {parent} should have child_islands')
                    self.assertIn(cur, parent.child_islands, f'child island {cur} should appear in parent.child_islands for {parent}')
                cur = parent

    def assertNoBorderIslandsStale(self, builder: TileIslandBuilder):
        """
        Every island in border_islands of every registered island must itself be registered
        in all_tile_islands (i.e. not a stale reference to a torn-down or replaced island).
        """
        registeredIds = {isl.unique_id for isl in builder.all_tile_islands}
        for island in builder.all_tile_islands:
            for border in island.border_islands:
                self.assertIn(
                    border.unique_id,
                    registeredIds,
                    f'island {island} has stale border_island reference to {border} '
                    f'(unique_id={border.unique_id}) which is not in all_tile_islands'
                )

    def assertAllIslandsNamed(self, builder: TileIslandBuilder):
        seenIslands = set(builder.all_tile_islands)
        seenIslands.update(builder.tile_islands_by_unique_id.values())
        for island in seenIslands:
            self.assertIsNotNone(island.name, f'{island} should have a name set')
            self.assertNotEqual('', island.name, f'{island} should have a non-empty name set')

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
            ('small', 0.005),
            ('large', 0.02)
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
                logbook.info(f'took {duration:.4f}')

    def test_builds_tile_islands(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)
        #
        # if debugMode:
        #     self.render_map(map)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.break_apart_neutral_islands = False
        builder.recalculate_tile_islands(enemyGeneral)
        # self.render_tile_islands(map, builder)
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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

        bottomRightEnIsland = builder.tile_island_lookup[map.GetTile(3, 12)]

        all = set()
        all.add(topLeftEnIsland)
        all.add(midLeftEnIsland)
        all.add(bottomLeftEnIsland)
        all.add(bottomRightEnIsland)
        self.assertEqual(4, len(all), 'should be distinct islands')

        # TODO assert stuff like including the joined-en-land-total-area

        self.assertEqual(66, topLeftEnIsland.tile_count_all_adjacent_friendly)

        self.assertEqual(182, topLeftEnIsland.sum_army_all_adjacent_friendly)

    def test_should_be_consistent_between_map_loads(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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

    def test_update_tile_islands__city_army_increment_keeps_adjacent_islands_stable(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        city = map.GetTile(7, 4)
        self.assertTrue(city.isCity)

        cityIsland = builder.tile_island_lookup[city]
        unchangedAroundCity = {
            adj: builder.tile_island_lookup[adj]
            for adj in city.movable
            if not adj.isObstacle and builder.tile_island_lookup[adj] is not None and builder.tile_island_lookup[adj] is not cityIsland
        }

        self.assertGreaterEqual(len(unchangedAroundCity), 1, 'test should verify at least one adjacent island exists around the city')

        self.mark_tile_army_incremented(city, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)

        self.assertIs(cityIsland, builder.tile_island_lookup[city], 'city island should keep the same object when only its army changes')
        self.assertTilesRemainOnSameIslands(builder, unchangedAroundCity)
        self.assertAllIslandsNamed(builder)

        for adj, island in unchangedAroundCity.items():
            self.assertIsNotNone(builder.tile_island_lookup[adj], f'adjacent tile {adj} should still belong to an island after update')
            self.assertIs(island, builder.tile_island_lookup[adj], f'adjacent tile {adj} should keep the same island object after update')

    def test_update_tile_islands__unaffected_tiles_keep_same_island_objects(self):
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
        self.assertAllIslandsContiguous(builder, debugMode)

        changedTile = map.GetTile(4, 1)
        unaffectedFriendlyTiles = [map.GetTile(0, 1), map.GetTile(0, 5)]
        unchangedTiles = {tile: builder.tile_island_lookup[tile] for tile in unaffectedFriendlyTiles}
        self.assertTrue(all(builder.tile_island_lookup[tile] is not None for tile in unaffectedFriendlyTiles), 'unaffected friendly tiles should each belong to an island before update')

        self.mark_tile_army_incremented(changedTile, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertTilesRemainOnSameIslands(builder, unchangedTiles)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__city_army_increment_does_not_create_full_island_cycles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        city = map.GetTile(7, 4)
        self.mark_tile_army_incremented(city, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__army_increment_joins_adjacent_matching_island_up_to_four_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |    |    |    |    |
aG1
                                        a2   a2   a2
                                             a1


                                             bG1
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        matchingArmyTiles = [tile for tile in map.tiles_by_index if tile.player == general.player and tile.army == 2]
        changedTile = next(tile for tile in map.tiles_by_index if tile.player == general.player and tile.army == 1 and not tile.isGeneral)
        adjacentIslandTile = next(tile for tile in matchingArmyTiles if builder.tile_island_lookup[tile] is not None and builder.tile_island_lookup[tile].tile_count == 3)
        largeIslandBefore = builder.tile_island_lookup[adjacentIslandTile]

        self.assertIsNotNone(largeIslandBefore, 'adjacent matching island should exist before update')
        self.assertEqual(3, largeIslandBefore.tile_count, 'fixture should start with a 3-tile matching adjacent island')
        self.assertTrue(any(adj in largeIslandBefore.tile_set for adj in changedTile.movable), 'changed tile should border the 3-tile matching island in the fixture')

        self.mark_tile_army_incremented(changedTile, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        changedIslandAfter = builder.tile_island_lookup[changedTile]
        largeIslandAfter = builder.tile_island_lookup[adjacentIslandTile]

        self.assertIsNotNone(changedIslandAfter, 'changed tile should belong to an island after update')
        self.assertIsNotNone(largeIslandAfter, 'adjacent island should still exist after update')
        self.assertIs(changedIslandAfter, largeIslandAfter, 'changed tile should join the adjacent matching island when it is size 3 before the update')
        self.assertEqual(4, changedIslandAfter.tile_count, 'changed tile should grow the adjacent matching island from size 3 to size 4')
        self.assertEqual(4, largeIslandAfter.tile_count, 'adjacent matching island should absorb the changed tile up to size 4')

    def test_should_group_by_army_values(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)
        #
        # if debugMode:
        #     self.render_map(map)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
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
        builder.force_territory_borders_to_single_tile_islands = False
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
        builder.force_territory_borders_to_single_tile_islands = False
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        if debugMode:
            self.render_tile_islands(map, builder)

        self.assertEqual(4, len(builder.tile_islands_by_player[enemyGeneral.player]))

    def mark_tile_captured(self, tile, newPlayer: int, newArmy: int):
        """Simulates a tile changing ownership (e.g. captured by newPlayer)."""
        tile.delta.oldOwner = tile.player
        tile.delta.newOwner = newPlayer
        tile.delta.oldArmy = tile.army
        tile.player = newPlayer
        tile.tile = newPlayer
        tile.army = newArmy

    def assertNoTilesWithNullIslands(self, builder: TileIslandBuilder, debugMode: bool = False):
        """Asserts that every non-obstacle tile that is owned (player >= 0) has a non-None island in tile_island_lookup."""
        nullTiles = [
            tile
            for tile in builder.map.tiles_by_index
            if not tile.isObstacle and tile.player >= 0 and builder.tile_island_lookup.raw[tile.tile_index] is None
        ]
        if nullTiles:
            err = f'The following owned non-obstacle tiles have None island after update: {" | ".join([str(t) for t in nullTiles])}'
            if debugMode:
                def viMod(v: ViewInfo):
                    for t in nullTiles:
                        v.add_targeted_tile(t)
                self.render_tile_islands(builder.map, builder, viewInfoMod=viMod)
            self.fail(err)

    def assertUpdateMatchesRecalculate(self, map: MapBase, builder: TileIslandBuilder, enemyGeneral, mode: IslandBuildMode, debugMode: bool = False):
        """Builds a fresh recalculate on the same map state and checks every tile lands in the same island group."""
        freshBuilder = TileIslandBuilder(map)
        freshBuilder.force_territory_borders_to_single_tile_islands = builder.force_territory_borders_to_single_tile_islands
        freshBuilder.break_apart_neutral_islands = builder.break_apart_neutral_islands
        freshBuilder.desired_tile_island_size = builder.desired_tile_island_size
        freshBuilder.recalculate_tile_islands(enemyGeneral, mode=mode)

        mismatches = []
        for tile in map.tiles_by_index:
            if tile.isObstacle:
                continue
            updatedIsland = builder.tile_island_lookup.raw[tile.tile_index]
            freshIsland = freshBuilder.tile_island_lookup.raw[tile.tile_index]
            # Both should be None (e.g. neutral obstacle) or both non-None belonging to the same team
            if (updatedIsland is None) != (freshIsland is None):
                mismatches.append((tile, updatedIsland, freshIsland))
            elif updatedIsland is not None and freshIsland is not None:
                if updatedIsland.team != freshIsland.team:
                    mismatches.append((tile, updatedIsland, freshIsland))

        if mismatches:
            err = f'update_tile_islands disagrees with recalculate on {len(mismatches)} tile(s): ' + ' | '.join(
                f'{t} updated={u} fresh={f}' for t, u, f in mismatches[:10]
            )
            if debugMode:
                self.render_tile_islands(map, builder)
                self.render_tile_islands(map, freshBuilder)
            self.fail(err)

    def assertNoBorderIslandsPointToRemovedIslands(self, builder: TileIslandBuilder, debugMode: bool = False):
        """Asserts that no island's border_islands set contains an island that is no longer in all_tile_islands."""
        liveIslands = set(builder.all_tile_islands)
        staleRefs = []
        for island in liveIslands:
            for border in island.border_islands:
                if border not in liveIslands:
                    staleRefs.append((island, border))
        if staleRefs:
            err = 'Islands have border_islands pointing to removed (stale) island objects:\n' + '\n'.join(
                f'  {live} -> stale border {stale}' for live, stale in staleRefs[:10]
            )
            if debugMode:
                self.render_tile_islands(builder.map, builder)
            self.fail(err)

    def test_update_tile_islands__capture_of_large_island_clears_stale_border_refs_on_distant_neutral(self):
        """
        Regression test for stale border_islands reference bug.

        Scenario: a neutral island N borders the FAR end of a large enemy island E.
        When a tile at the NEAR end of E is captured, E is removed and rebuilt as E'.
        N is more than one tile-step away from the captured tile, so it is NOT included
        in refreshIslands. After the update N.border_islands still contains the dead E
        object (not in all_tile_islands), which causes NetworkXUnfeasible when building
        the flow graph because edges point to ghost nodes.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Map layout (columns 0-7, rows 0-4):
        #   row 0: aG1 at (0,0)
        #   row 1: a2 at (0,1)
        #   row 2: a2(0,2) b2(1,2) b2(2,2) b2(3,2) b2(4,2)  — enemy strip
        #   row 3: N40 at (3,3)  — neutral bordering far end of enemy strip
        #   row 4: bG1 at (6,4)
        #
        # After capturing (1,2):
        #   refreshTiles = {(1,2)} ∪ movable = {(0,2),(2,2),(1,1),(1,3)}
        #   Island for tiles (2,2)..(4,2) is the far part of the old enemy strip
        #   Neutral N at (3,3) borders (3,2) — which is 2 tile-steps from (1,2)
        #   The neutral island's tiles are NOT in refreshTiles → stale border ref survives
        testData = """
|    |    |    |    |    |    |    |    |
aG1
a2
a2   b2   b2   b2   b2
               N5
                         bG1
|    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # The neutral tile at (3,3) should border the large enemy island before capture
        neutralTile = map.GetTile(3, 3)
        neutralIsland = builder.tile_island_lookup[neutralTile]
        self.assertIsNotNone(neutralIsland, 'neutral island should exist before capture')
        self.assertTrue(neutralIsland.team == -1, 'fixture: (3,3) should be a neutral-team island')

        # Capture the tile at (1,2) — the near end of the enemy strip, 2 steps from the neutral
        capturedTile = map.GetTile(1, 2)
        self.assertEqual(enemyGeneral.player, capturedTile.player, 'fixture: (1,2) should be enemy-owned')
        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        self.assertNoBorderIslandsPointToRemovedIslands(builder, debugMode)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__army_increment_clears_stale_border_refs_on_distant_island(self):
        """
        Same stale border_islands bug triggered by an army increment instead of a capture.

        When a tile's army changes, its island is impacted and rebuilt. An island that only
        borders the changed island at a distance > 1 tile from the changed tile will not be
        in refreshIslands and will retain stale border_islands references to the removed island.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Map layout:
        #   row 0: aG1 at (0,0)
        #   row 1: a2(0,1) a2(1,1) a2(2,1) a2(3,1) a2(4,1)  — friendly strip
        #   row 2: N40 at (4,2)  — neutral bordering far end of friendly strip
        #   row 3: bG1 at (6,3)
        #
        # After incrementing (0,1):
        #   (0,1) army changes → its island is impacted
        #   refreshTiles = {(0,1)} ∪ movable = {(1,1),(0,0),(0,2)}
        #   The whole strip (0..4,1) is one island, so that island is impacted
        #   Neutral N at (4,2) borders (4,1) — but N's tile is NOT in refreshTiles
        #   (refreshTiles only goes one step past the changed tile, not the island boundary)
        #   → neutral island NOT rebuilt → stale border ref survives if island rebuilt
        testData = """
|    |    |    |    |    |    |    |    |
aG1
a2   a2   a2   a2   a2
                    N5
                         bG1
|    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # The neutral tile at (4,2) borders the far end of the friendly strip
        neutralTile = map.GetTile(4, 2)
        neutralIsland = builder.tile_island_lookup[neutralTile]
        self.assertIsNotNone(neutralIsland, 'neutral island should exist before update')
        self.assertTrue(neutralIsland.team == -1, 'fixture: (4,2) should be a neutral-team island')

        # Increment the tile at (0,1) — the near end of the friendly strip, 4 steps from neutralTile
        changedTile = map.GetTile(0, 1)
        self.assertEqual(general.player, changedTile.player, 'fixture: (0,1) should be friendly')
        self.assertFalse(changedTile.isGeneral, 'fixture: (0,1) should not be the general (which is solo and would not impact a strip island)')
        self.mark_tile_army_incremented(changedTile, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        self.assertNoBorderIslandsPointToRemovedIslands(builder, debugMode)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__tile_capture_leaves_no_null_island_assignments(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1
a2   a2   a2
a2   a2   a2   b2
               b2
               b2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        capturedTile = map.GetTile(3, 3)
        self.assertEqual(enemyGeneral.player, capturedTile.player, 'fixture: tile should start as enemy-owned')

        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        self.assertIsNotNone(builder.tile_island_lookup[capturedTile], 'captured tile should belong to an island after update')
        self.assertEqual(general.player, capturedTile.player, 'captured tile should now belong to general.player')
        capturedIsland = builder.tile_island_lookup[capturedTile]
        self.assertEqual(builder.map.team_ids_by_player_index[general.player], capturedIsland.team, 'captured tile island should have friendly team')

    def test_update_tile_islands__tile_capture_matches_recalculate(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1
a2   a2   a2
a2   a2   a2   b2
               b2
               b2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        capturedTile = map.GetTile(3, 3)
        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertUpdateMatchesRecalculate(map, builder, enemyGeneral, IslandBuildMode.GroupByArmy, debugMode)

    def test_update_tile_islands__multiple_captures_leave_no_null_island_assignments(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1
a2   a2   a2
a2   a2   a2   b2   b2
               b2   b2
               b2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # Simulate two enemy tiles captured in the same turn
        cap1 = map.GetTile(3, 3)
        cap2 = map.GetTile(4, 3)
        self.mark_tile_captured(cap1, general.player, 1)
        self.mark_tile_captured(cap2, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__ownership_change_splits_enemy_island_correctly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |    |
aG1
                    b2   b2   b2   b2
                    b2   b2   b2   b2
                                   bG1
|    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # Capture a tile in the middle of enemy territory, potentially splitting it
        midTile = map.GetTile(4, 2)
        self.assertEqual(enemyGeneral.player, midTile.player, 'fixture: mid tile should be enemy-owned')

        self.mark_tile_captured(midTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        # Every tile that used to be in the same enemy island must still have a valid island
        for tile in map.tiles_by_index:
            if tile.player == enemyGeneral.player:
                self.assertIsNotNone(builder.tile_island_lookup[tile], f'enemy tile {tile} should still belong to an island after update')

    def test_update_tile_islands__ownership_change_on_real_map_leaves_no_null_islands(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # Find an enemy tile adjacent to a friendly tile and capture it
        capturedTile = next(
            t for t in map.tiles_by_index
            if t.player == enemyGeneral.player
            and not t.isCity and not t.isGeneral
            and any(adj.player == general.player for adj in t.movable)
        )
        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__ownership_change_on_real_map_matches_recalculate(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        capturedTile = next(
            t for t in map.tiles_by_index
            if t.player == enemyGeneral.player
            and not t.isCity and not t.isGeneral
            and any(adj.player == general.player for adj in t.movable)
        )
        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertUpdateMatchesRecalculate(map, builder, enemyGeneral, IslandBuildMode.GroupByArmy, debugMode)

    def test_update_tile_islands__army_increment_then_capture_leaves_no_null_islands(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1
a2   a2   a2
a2   a2   a2   b3
               b3
               b3
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # First simulate an army increment (turn N)
        armyTile = map.GetTile(3, 3)
        self.mark_tile_army_incremented(armyTile, 1)
        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # Then simulate a capture on the same tile (turn N+1)
        self.mark_tile_captured(armyTile, general.player, 1)
        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

    def test_update_tile_islands__stale_islands_not_in_all_tile_islands_after_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |
aG1
a2   a2   a2
a2   a2   a2   b2
               b2
               b2
                              bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 102)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        capturedTile = map.GetTile(3, 3)
        islandBeforeCapture = builder.tile_island_lookup[capturedTile]
        self.assertIsNotNone(islandBeforeCapture, 'tile should have an island before capture')

        self.mark_tile_captured(capturedTile, general.player, 1)

        oldTeam = islandBeforeCapture.team

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        # The captured tile should now have a friendly-team island in the lookup
        islandAfterCapture = builder.tile_island_lookup[capturedTile]
        self.assertIsNotNone(islandAfterCapture, 'captured tile should belong to an island after update')
        self.assertNotEqual(oldTeam, islandAfterCapture.team, 'island for captured tile should now have friendly team, not the old enemy team')

        # The enemy team's island list should not contain an island that still claims the captured tile
        for enemyIsland in builder.tile_islands_by_team_id[oldTeam]:
            self.assertNotIn(capturedTile, enemyIsland.tile_set, f'enemy island {enemyIsland} should not still claim the captured tile {capturedTile}')

    def test_update_tile_islands__ownership_change_does_not_tear_down_sibling_leaf_islands(self):
        """
        When a tile changes ownership inside a broken-up neutral region (where recalculate split the
        large neutral blob into many leaf islands under one full_island), update_tile_islands must only
        tear down the specific leaf island containing the changed tile — NOT all sibling leaf islands
        under the same full_island parent.

        Bug: _get_leaf_islands_for_island was called on the changed tile's existingIsland, which walked
        to full_island and returned ALL child_islands, causing every sibling neutral leaf to be torn down
        and rebuilt as one giant island.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Large open neutral map with a wide neutral corridor that recalculate will split into
        # many leaf islands (~27) under one full_island. Enemy general is far bottom-right.
        testData = """
|    |    |    |    |    |    |    |    |    |    |
aG1
a1
a1
a1
a1



                                             bG1
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 50)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)

        # Pick a neutral tile to capture and record all OTHER neutral leaf islands (siblings)
        capturedTile = map.GetTile(5, 5)
        capturedIslandBefore = builder.tile_island_lookup[capturedTile]
        self.assertIsNotNone(capturedIslandBefore, 'captured tile should belong to an island before update')
        self.assertEqual(-1, capturedIslandBefore.team, 'captured tile should be neutral before update')

        # All neutral leaf islands that do NOT contain the captured tile are "siblings" — they must survive
        siblingIslandsBefore = {
            isl for isl in builder.all_tile_islands
            if isl.team == -1 and capturedTile not in isl.tile_set
        }
        self.assertGreater(len(siblingIslandsBefore), 1, 'fixture should have multiple neutral leaf islands')
        siblingIslandObjects = {isl: frozenset(isl.tile_set) for isl in siblingIslandsBefore}

        self.reset_tile_deltas_to_current_state(map)
        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        # Sibling neutral leaf islands must be the SAME objects with SAME tiles — they were not touched
        for siblingIsland, tilesBefore in siblingIslandObjects.items():
            currentIsland = builder.tile_island_lookup[next(iter(tilesBefore))]
            self.assertIs(
                siblingIsland, currentIsland,
                f'sibling neutral leaf island {siblingIsland} should be the same object after update '
                f'(only the directly-changed leaf should be torn down)'
            )
            self.assertEqual(
                tilesBefore, frozenset(siblingIsland.tile_set),
                f'sibling neutral leaf island {siblingIsland} tile_set should be unchanged after update'
            )

    def test_update_tile_islands__ownership_change_only_rebuilds_affected_leaf_and_its_borders(self):
        """
        When a tile changes ownership, update_tile_islands should rebuild:
          - The leaf island(s) directly containing the changed tile
          - Border islands of those leaf islands (border refresh only, not full teardown)
        Islands further away should not be touched at all.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |    |    |    |    |
aG1
a1
a1
a1
a1



                                             bG1
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 50)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)

        capturedTile = map.GetTile(5, 5)
        capturedIslandBefore = builder.tile_island_lookup[capturedTile]

        # Islands not adjacent to the captured tile's island should be completely untouched
        adjacentIslandsBefore = set(capturedIslandBefore.border_islands)
        remoteNeutralIslands = {
            isl: frozenset(isl.tile_set)
            for isl in builder.all_tile_islands
            if isl.team == -1
            and capturedTile not in isl.tile_set
            and isl not in adjacentIslandsBefore
        }
        self.assertGreater(len(remoteNeutralIslands), 0, 'fixture should have neutral islands not adjacent to the captured tile')

        self.reset_tile_deltas_to_current_state(map)
        self.mark_tile_captured(capturedTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        for remoteIsland, tilesBefore in remoteNeutralIslands.items():
            sampleTile = next(iter(tilesBefore))
            currentIsland = builder.tile_island_lookup[sampleTile]
            self.assertIs(
                remoteIsland, currentIsland,
                f'remote neutral island {remoteIsland} (not adjacent to changed tile) '
                f'should be the same object after update'
            )
            self.assertEqual(
                tilesBefore, frozenset(remoteIsland.tile_set),
                f'remote neutral island {remoteIsland} tile_set should be unchanged'
            )

    def test_update_tile_islands__large_neutral_sibling_leaves_stay_broken_apart_after_ownership_change(self):
        """
        Regression: when recalculate_tile_islands correctly splits a large neutral blob into many small
        leaf islands, a subsequent ownership change on ONE tile inside that blob must not cause
        update_tile_islands to merge all the remaining neutral tiles back into one giant island.

        Root cause: _get_leaf_islands_for_island walked to full_island and returned ALL child_islands,
        causing the entire neutral blob to be torn down and rebuilt without _break_apart_island_if_too_large.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        testData = """
|    |    |    |    |    |    |    |    |    |    |
aG1
a1
a1
a1
a1



                                             bG1
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 50)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)

        cutoff = int(builder.desired_tile_island_size * 1.5)
        largestNeutAfterRecalc = max(
            (isl for isl in builder.all_tile_islands if isl.team == -1),
            key=lambda isl: isl.tile_count
        )
        self.assertLessEqual(
            largestNeutAfterRecalc.tile_count, cutoff,
            f'precondition: recalculate_tile_islands must split large neutral blobs; '
            f'largest was {largestNeutAfterRecalc.tile_count} (cutoff={cutoff})'
        )

        self.reset_tile_deltas_to_current_state(map)
        self.mark_tile_captured(map.GetTile(5, 5), general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        largestNeutAfterUpdate = max(
            (isl for isl in builder.all_tile_islands if isl.team == -1),
            key=lambda isl: isl.tile_count
        )
        self.assertLessEqual(
            largestNeutAfterUpdate.tile_count, cutoff,
            f'update_tile_islands must not merge sibling neutral leaf islands back into one giant island; '
            f'largest was {largestNeutAfterUpdate.tile_count} tiles (cutoff={cutoff})'
        )
        self.assertNoBorderIslandsStale(builder)

    def test_update_tile_islands__no_stale_border_island_references_after_neutral_rebuild_and_split(self):
        """
        When update_tile_islands rebuilds a neutral leaf island that gets split by
        _break_apart_island_if_too_large, ALL islands bordering ANY of the new child islands must
        have their border_islands refreshed to point to the new children — even if those bordering
        islands are not adjacent to the tile that triggered the ownership change.

        Root cause of the original bug: refreshIslands was pre-populated before the rebuild from
        tile_island_lookup (which still had old mappings). Neighbors of the far edges of the split
        blob weren't adjacent to changedTiles so they never entered refreshTiles, leaving their
        border_islands pointing to the now-dead pre-split island object.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Map: player owns top-left corner. Large open neutral area in the middle.
        # Friendly tile at (0,5) borders the neutral blob. Enemy general bottom-right.
        # We capture a neutral tile at (5,3) — far from (0,5).
        # After update: (0,5) still owns its island, but its border_islands must point to the
        # NEW child neutral islands produced by _break_apart_island_if_too_large, not the old object.
        testData = """
|    |    |    |    |    |    |    |    |    |    |
aG1
a1
a1
a1
a1
a1




                                             bG1
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 50)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoBorderIslandsStale(builder)

        # Verify the neutral blob was split into multiple leaf islands (precondition for the bug)
        cutoff = int(builder.desired_tile_island_size * 1.5)
        neutralIslands = [isl for isl in builder.all_tile_islands if isl.team == -1]
        self.assertGreater(len(neutralIslands), 1, 'fixture must have multiple neutral leaf islands for split to be meaningful')

        # Find a friendly island that borders a neutral island, and a neutral tile far from it to capture
        friendlyIslandBorderingNeut = next(
            isl for isl in builder.all_tile_islands
            if isl.team == general.player and any(b.team == -1 for b in isl.border_islands)
        )
        # Pick any neutral tile that is NOT directly adjacent to the friendly island
        friendlyTiles = friendlyIslandBorderingNeut.tile_set
        farNeutralTile = next(
            t for t in map.tiles_by_index
            if builder.tile_island_lookup.raw[t.tile_index] is not None
            and builder.tile_island_lookup.raw[t.tile_index].team == -1
            and all(adj not in friendlyTiles for adj in t.movable)
        )

        self.reset_tile_deltas_to_current_state(map)
        self.mark_tile_captured(farNeutralTile, general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)

        # THE CRITICAL ASSERTION: no island must have a stale border_islands reference
        # to an island that was torn down and not re-registered.
        self.assertNoBorderIslandsStale(builder)

        # Additionally verify the friendly island's border_islands only contain live islands
        updatedFriendlyIsland = builder.tile_island_lookup[next(iter(friendlyIslandBorderingNeut.tile_set))]
        registeredIds = {isl.unique_id for isl in builder.all_tile_islands}
        for borderIsland in updatedFriendlyIsland.border_islands:
            self.assertIn(
                borderIsland.unique_id,
                registeredIds,
                f'friendly island {updatedFriendlyIsland} has stale border reference to '
                f'{borderIsland} (id={borderIsland.unique_id}) not in all_tile_islands after update+split'
            )

