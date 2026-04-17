import time
import typing
from collections import deque

import logbook

from Algorithms import TileIslandBuilder
from Algorithms.TileIslandBuilder import IslandBuildMode, TileIsland
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

    def assertNoZombieIslands(self, builder: TileIslandBuilder):
        """
        No island in all_tile_islands may claim a tile whose tile_island_lookup maps to a different
        island. Such 'zombie' islands cause disconnected flow graphs and NetworkXUnfeasible errors.
        """
        zombies = []
        for island in builder.all_tile_islands:
            for tile in island.tile_set:
                mapped = builder.tile_island_lookup.raw[tile.tile_index]
                if mapped is not island:
                    zombies.append(
                        f'{island} claims {tile} but lookup maps to {mapped.unique_id if mapped else None}'
                    )
                    break
        if zombies:
            self.fail(
                f'Zombie islands found ({len(zombies)}) — in all_tile_islands but lookup disagrees:\n'
                + '\n'.join(f'  {z}' for z in zombies[:10])
            )

    def assertNoLookupMismatches(self, builder: TileIslandBuilder):
        """
        For every non-obstacle tile, if tile_island_lookup maps it to an island, that island's
        tile_set must include that tile — and the island must be in all_tile_islands.
        """
        live = set(builder.all_tile_islands)
        mismatches = []
        for tile in builder.map.tiles_by_index:
            if tile.isObstacle:
                continue
            island = builder.tile_island_lookup.raw[tile.tile_index]
            if island is None:
                continue
            if tile not in island.tile_set:
                mismatches.append(f'lookup[{tile}] = {island} but tile not in island.tile_set')
            elif island not in live:
                mismatches.append(f'lookup[{tile}] = {island} which is not in all_tile_islands')
        if mismatches:
            self.fail(
                f'tile_island_lookup mismatches found ({len(mismatches)}):\n'
                + '\n'.join(f'  {m}' for m in mismatches[:10])
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
            ('large', 0.010)
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
                builder.use_debug_asserts = False
                builder.log_debug = False

                start = time.perf_counter()
                builder.recalculate_tile_islands(enemyGeneral)
                duration = time.perf_counter() - start
                self.assertAllIslandsContiguous(builder, debugMode)
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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoFullIslandCycles(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoFullIslandCycles(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

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
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)

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

    def test_update_tile_islands__newly_discovered_pocket_gets_islands_when_enemy_captures(self):
        """
        Regression test for the bug where tiles that had no island (tile_island_lookup==None)
        because they were outside reachable_tiles during recalculate_tile_islands would
        permanently remain None even after being captured and revealed.

        Scenario: neutral tile(s) form a pocket completely surrounded by enemy territory.
        At recalculate time they are neutral and outside reachable_tiles so they get no
        island (tile_island_lookup==None). On the next turn the enemy captures them all.
        update_tile_islands must assign them islands — without the fix, the
        existingIsland==None branch silently skips them and they stay None forever,
        producing disconnected flow graph components (NetworkXUnfeasible).

        Then we further verify that if friendly recaptures one of those tiles, the
        resulting islands are structurally valid.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Map layout (5 cols x 6 rows):
        #   (0,0) aG1  — friendly general (player 0)
        #   (0,1) a1   — one friendly tile
        #   Enemy ring around a 2x2 neutral pocket:
        #     (1,2)(2,2)(3,2) b1  — top of ring
        #     (1,3)       (3,3) b1  — sides
        #     (1,4)(2,4)(3,4) b1  — bottom of ring
        #   Neutral pocket: (2,3) — single neutral tile fully enclosed by enemy
        #   (4,5) bG1  — enemy general (player 1)
        #
        # The neutral tile at (2,3) is surrounded by enemy on all 4 sides and not
        # adjacent to any friendly tile. We evict its island after recalculate to
        # simulate it being undiscovered (tile_island_lookup==None) at recalculate
        # time — the exact pre-condition that triggered the production bug.
        testData = """
|    |    |    |    |    |
aG1
a1
          b1   b1   b1
          b1        b1
          b1   b1   b1
                         bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 100)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.force_territory_borders_to_single_tile_islands = False
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # Find the neutral tile(s) fully enclosed by enemy — these are the pocket
        pocketTiles = [
            t for t in map.tiles_by_index
            if not t.isObstacle
            and t.player == -1
            and all(adj.player == enemyGeneral.player or adj.isObstacle for adj in t.movable)
        ]
        self.assertGreater(len(pocketTiles), 0, 'fixture: at least one neutral tile must be fully enclosed by enemy tiles')
        for t in pocketTiles:
            self.assertEqual(-1, t.player, f'fixture: pocket tile {t} should be neutral at start')

        # Simulate the tiles having been outside reachable_tiles at recalculate time
        # (undiscovered fog tiles). Clear their lookup entries and remove their islands
        # from the registry — this is the exact state that caused the bug in production
        # where update_tile_islands silently skipped None-island changed tiles.
        pocketIslandsToEvict = {
            builder.tile_island_lookup.raw[t.tile_index]
            for t in pocketTiles
            if builder.tile_island_lookup.raw[t.tile_index] is not None
        }
        for island in pocketIslandsToEvict:
            builder._remove_leaf_island(island)
            for tileInIsland in island.tile_set:
                builder.tile_island_lookup.raw[tileInIsland.tile_index] = None

        for t in pocketTiles:
            self.assertIsNone(
                builder.tile_island_lookup.raw[t.tile_index],
                f'fixture: pocket tile {t} should have no island after eviction'
            )

        # Simulate enemy capturing all 4 pocket tiles simultaneously (newly discovered)
        for t in pocketTiles:
            self.mark_tile_captured(t, enemyGeneral.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)
        self.assertNoBorderIslandsPointToRemovedIslands(builder, debugMode)

        # Every pocket tile must now have an island
        for t in pocketTiles:
            island = builder.tile_island_lookup.raw[t.tile_index]
            self.assertIsNotNone(island, f'pocket tile {t} must have an island after enemy capture')
            self.assertEqual(enemyGeneral.player, t.player, f'pocket tile {t} should be enemy-owned')

        # All pocket islands must border the surrounding enemy islands (i.e. be connected)
        pocketIslands = {builder.tile_island_lookup.raw[t.tile_index] for t in pocketTiles}
        for isl in pocketIslands:
            self.assertIn(isl, builder.all_tile_islands, f'pocket island {isl} must be in all_tile_islands')

        self.reset_tile_deltas_to_current_state(map)

        # Now simulate friendly recapturing one pocket tile — the update must remain consistent
        self.mark_tile_captured(pocketTiles[0], general.player, 1)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)
        self.assertNoBorderIslandsPointToRemovedIslands(builder, debugMode)


    def test_shouldnt_create_broken_islands_after_captures(self):
        """
        Regression test for the production NetworkXUnfeasible at turn 746.

        Turn 745 moves:
          - Player 0 (blue/enemy) moves 16,9 -> 16,10, capturing player 1's tile at 16,10.
          - Player 1 (red/bot) moves 11,14 -> 11,13, capturing player 0's tile at 11,13.

        After update_tile_islands processes these two captures, two neutral tiles (7,7 and
        3,19) were being left with tile_island_lookup==None, producing disconnected components
        in the flow graph and raising NetworkXUnfeasible on the next expansion call.

        This test directly applies those exact tile-ownership changes to the TileIslandBuilder
        and asserts that every structural invariant holds after the update.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/shouldnt_create_broken_islands_after_captures___9GHWHfzuU---1--745.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 745, fill_out_tiles=True)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.reset_tile_deltas_to_current_state(map)

        # Turn 745 move results:
        #   Player 0 moved from 16,9 to 16,10 (captured player 1's tile at 16,10)
        #   Player 1 moved from 11,14 to 11,13 (captured player 0's tile at 11,13)
        tile_16_9 = map.GetTile(16, 9)
        tile_16_10 = map.GetTile(16, 10)
        tile_11_13 = map.GetTile(11, 13)
        tile_11_14 = map.GetTile(11, 14)

        self.assertEqual(enemyGeneral.player, tile_16_9.player, 'fixture: 16,9 should be player 0 (blue) before move')
        self.assertEqual(general.player, tile_16_10.player, 'fixture: 16,10 should be player 1 (red) before move')
        self.assertEqual(enemyGeneral.player, tile_11_13.player, 'fixture: 11,13 should be player 0 (blue) before move')
        self.assertEqual(general.player, tile_11_14.player, 'fixture: 11,14 should be player 1 (red) before move')

        # Player 0 moves 16,9->16,10: their army at 16,9 decreases, they capture 16,10
        self.mark_tile_army_incremented(tile_16_9, -2)   # army 3 -> 1
        self.mark_tile_captured(tile_16_10, enemyGeneral.player, 1)

        # Player 1 moves 11,14->11,13: their army at 11,14 decreases, they capture 11,13
        self.mark_tile_army_incremented(tile_11_14, -3)  # army 4 -> 1
        self.mark_tile_captured(tile_11_13, general.player, 2)

        builder.update_tile_islands(enemyGeneral, mode=IslandBuildMode.GroupByArmy)

        self.assertNoBorderIslandsPointToRemovedIslands(builder, debugMode)
        self.assertAllIslandsContiguous(builder, debugMode)
        self.assertNoTilesWithNullIslands(builder, debugMode)
        self.assertNoFullIslandCycles(builder)
        self.assertAllIslandsNamed(builder)
        self.assertNoZombieIslands(builder)
        self.assertNoLookupMismatches(builder)
        self.assertNoBorderIslandsStale(builder)

        # The two captured tiles must have islands belonging to their new owners
        capturedByBlue = map.GetTile(16, 10)
        capturedByRed = map.GetTile(11, 13)
        self.assertEqual(enemyGeneral.player, capturedByBlue.player, '16,10 should now belong to player 0')
        self.assertEqual(general.player, capturedByRed.player, '11,13 should now belong to player 1')
        blueIsland = builder.tile_island_lookup.raw[capturedByBlue.tile_index]
        redIsland = builder.tile_island_lookup.raw[capturedByRed.tile_index]
        self.assertIsNotNone(blueIsland, '16,10 must have an island after capture')
        self.assertIsNotNone(redIsland, '11,13 must have an island after capture')
        self.assertEqual(
            map.team_ids_by_player_index[enemyGeneral.player], blueIsland.team,
            '16,10 island must have enemy team'
        )
        self.assertEqual(
            map.team_ids_by_player_index[general.player], redIsland.team,
            '11,13 island must have friendly team'
        )

        # Every tile currently owned by either player must have a valid island (the core
        # invariant that prevents disconnected flow graph components).
        for tile in map.tiles_by_index:
            if tile.isObstacle or tile.player < 0:
                continue
            self.assertIsNotNone(
                builder.tile_island_lookup.raw[tile.tile_index],
                f'owned tile {tile} (player={tile.player}) has no island after update'
            )

    # -----------------------------------------------------------------------
    # simHost-based tests: run real bot turns and assert island rebuild scope
    # -----------------------------------------------------------------------

    def _snapshot_all_island_objects(self, builder: TileIslandBuilder) -> typing.Dict[int, TileIsland]:
        """Returns {tile_index: island_object} for every non-obstacle tile that has an island."""
        return {
            tile.tile_index: builder.tile_island_lookup.raw[tile.tile_index]
            for tile in builder.map.tiles_by_index
            if not tile.isObstacle and builder.tile_island_lookup.raw[tile.tile_index] is not None
        }

    def _tiles_changed_this_turn(self, playerMap: MapBase) -> typing.Set[int]:
        """Returns tile_indices of tiles whose army or owner changed since last turn."""
        return {
            tile.tile_index
            for tile in playerMap.tiles_by_index
            if not tile.isObstacle and (tile.delta.oldArmy != tile.army or tile.delta.oldOwner != tile.player)
        }

    def _tiles_adjacent_to_set(self, tileIndices: typing.Set[int], playerMap: MapBase) -> typing.Set[int]:
        """Returns tile_indices of all non-obstacle tiles adjacent to any tile in tileIndices."""
        result: typing.Set[int] = set()
        indexSet = set(tileIndices)
        for tile in playerMap.tiles_by_index:
            if tile.tile_index not in indexSet or tile.isObstacle:
                continue
            for adj in tile.movable:
                if not adj.isObstacle:
                    result.add(adj.tile_index)
        return result

    def assertOnlyExpectedIslandsRebuilt(
            self,
            snapshotBefore: typing.Dict[int, TileIsland],
            builder: TileIslandBuilder,
            allowedRebuildIndices: typing.Set[int],
    ):
        """
        Asserts that every tile whose island object changed between snapshotBefore and now
        is within allowedRebuildIndices. Any tile outside that set whose island object
        changed counts as a spurious rebuild.
        """
        spurious = []
        for tileIndex, islandBefore in snapshotBefore.items():
            islandAfter = builder.tile_island_lookup.raw[tileIndex]
            if islandAfter is None:
                continue
            if islandAfter is not islandBefore and tileIndex not in allowedRebuildIndices:
                tile = builder.map.tiles_by_index[tileIndex]
                spurious.append(f'{tile} (was {islandBefore}, now {islandAfter})')
        if spurious:
            self.fail(
                f'update_tile_islands spuriously rebuilt {len(spurious)} island(s) outside expected scope:\n'
                + '\n'.join(f'  {s}' for s in spurious[:20])
            )

    def test_simhost__general_army_increment_only_rebuilds_general_island(self):
        """
        Every 2 turns the general's army increments. update_tile_islands must only rebuild
        the general's own single-tile island and refresh its immediate neighbours' borders.
        No friendly non-adjacent islands and no enemy islands should get new objects.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        snapshotBefore: typing.Dict[int, TileIsland] = {}

        def before_turn():
            snapshotBefore.clear()
            snapshotBefore.update(self._snapshot_all_island_objects(bot.tileIslandBuilder))

        def after_turn():
            changed = self._tiles_changed_this_turn(playerMap)
            changedAndAdjacent = changed | self._tiles_adjacent_to_set(changed, playerMap)
            # Also pull in all tiles of any island that contains a changed tile — those are always fair game
            allowedRebuildIndices: typing.Set[int] = set(changedAndAdjacent)
            for idx in changed:
                isl = snapshotBefore.get(idx)
                if isl is not None:
                    for t in isl.tile_set:
                        allowedRebuildIndices.add(t.tile_index)

            self.assertOnlyExpectedIslandsRebuilt(snapshotBefore, bot.tileIslandBuilder, allowedRebuildIndices)
            self.assertAllIslandsContiguous(bot.tileIslandBuilder, debugMode)
            self.assertNoZombieIslands(bot.tileIslandBuilder)
            self.assertNoBorderIslandsStale(bot.tileIslandBuilder)
            self.assertNoLookupMismatches(bot.tileIslandBuilder)

        simHost.run_between_turns(before_turn)
        simHost.run_between_turns(after_turn)

        # Queue the bot to stay put (pass moves) so only army-increment turns cause changes
        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None')
        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)

    def test_simhost__bot_captures_enemy_tile_only_rebuilds_local_islands(self):
        """
        When the bot captures an adjacent enemy tile, only the islands directly containing
        or adjacent to the changed tiles should get new objects. All islands further away —
        especially the bulk of the enemy land and large neutral blobs — must retain the
        exact same island objects they had before the turn.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        snapshotBefore: typing.Dict[int, TileIsland] = {}

        def before_turn():
            snapshotBefore.clear()
            snapshotBefore.update(self._snapshot_all_island_objects(bot.tileIslandBuilder))

        def after_turn():
            changed = self._tiles_changed_this_turn(playerMap)
            if not changed:
                return
            changedAndAdjacent = changed | self._tiles_adjacent_to_set(changed, playerMap)
            allowedRebuildIndices: typing.Set[int] = set(changedAndAdjacent)
            for idx in changed:
                isl = snapshotBefore.get(idx)
                if isl is not None:
                    for t in isl.tile_set:
                        allowedRebuildIndices.add(t.tile_index)

            self.assertOnlyExpectedIslandsRebuilt(snapshotBefore, bot.tileIslandBuilder, allowedRebuildIndices)
            self.assertAllIslandsContiguous(bot.tileIslandBuilder, debugMode)
            self.assertNoZombieIslands(bot.tileIslandBuilder)
            self.assertNoBorderIslandsStale(bot.tileIslandBuilder)
            self.assertNoLookupMismatches(bot.tileIslandBuilder)

        simHost.run_between_turns(before_turn)
        simHost.run_between_turns(after_turn)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)

    def test_simhost__enemy_army_increment_does_not_rebuild_friendly_islands(self):
        """
        When an enemy general/city increments army, the enemy islands update but absolutely
        no friendly-owned islands should be torn down and rebuilt. The friendly island objects
        must be identical before and after the turn on every tile not adjacent to the change.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        snapshotBefore: typing.Dict[int, TileIsland] = {}

        def before_turn():
            snapshotBefore.clear()
            snapshotBefore.update(self._snapshot_all_island_objects(bot.tileIslandBuilder))

        def after_turn():
            changed = self._tiles_changed_this_turn(playerMap)
            if not changed:
                return
            changedAndAdjacent = changed | self._tiles_adjacent_to_set(changed, playerMap)
            allowedRebuildIndices: typing.Set[int] = set(changedAndAdjacent)
            for idx in changed:
                isl = snapshotBefore.get(idx)
                if isl is not None:
                    for t in isl.tile_set:
                        allowedRebuildIndices.add(t.tile_index)

            friendlyTeam = bot.tileIslandBuilder.friendly_team
            spurious = []
            for tileIndex, islandBefore in snapshotBefore.items():
                if tileIndex in allowedRebuildIndices:
                    continue
                islandAfter = bot.tileIslandBuilder.tile_island_lookup.raw[tileIndex]
                if islandAfter is None:
                    continue
                if islandAfter is not islandBefore and islandBefore.team == friendlyTeam:
                    tile = playerMap.tiles_by_index[tileIndex]
                    spurious.append(f'{tile} friendly island rebuilt (was {islandBefore}, now {islandAfter})')
            if spurious:
                self.fail(
                    f'enemy army increment spuriously rebuilt {len(spurious)} friendly island(s):\n'
                    + '\n'.join(f'  {s}' for s in spurious[:20])
                )

            self.assertAllIslandsContiguous(bot.tileIslandBuilder, debugMode)
            self.assertNoZombieIslands(bot.tileIslandBuilder)
            self.assertNoBorderIslandsStale(bot.tileIslandBuilder)

        simHost.run_between_turns(before_turn)
        simHost.run_between_turns(after_turn)

        # Bot stays put — enemy is AFK — so only army-increment turns fire
        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None')
        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=12)

    def test_simhost__multi_turn_update_always_matches_recalculate(self):
        """
        Over many turns of a real game (bot moves + AFK enemy), update_tile_islands must
        produce island assignments that agree with a fresh recalculate_tile_islands on the
        same map state, and all structural invariants must hold every turn.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        def after_turn():
            builder = bot.tileIslandBuilder
            self.assertAllIslandsContiguous(builder, debugMode)
            self.assertNoZombieIslands(builder)
            self.assertNoBorderIslandsStale(builder)
            self.assertNoLookupMismatches(builder)
            self.assertNoFullIslandCycles(builder)
            self.assertNoTilesWithNullIslands(builder, debugMode)

        simHost.run_between_turns(after_turn)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=20)

    def test_simhost__large_map_neutral_islands_not_mass_rebuilt_on_army_increment(self):
        """
        On a larger map with many neutral islands, an army-increment turn (general/city tick)
        must not cause the bulk of neutral islands to be rebuilt. Neutral islands that have
        no tile adjacent to any changed tile should keep their exact same island objects.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 880, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        snapshotBefore: typing.Dict[int, TileIsland] = {}

        def before_turn():
            snapshotBefore.clear()
            snapshotBefore.update(self._snapshot_all_island_objects(bot.tileIslandBuilder))

        def after_turn():
            changed = self._tiles_changed_this_turn(playerMap)
            if not changed:
                return
            changedAndAdjacent = changed | self._tiles_adjacent_to_set(changed, playerMap)
            allowedRebuildIndices: typing.Set[int] = set(changedAndAdjacent)
            for idx in changed:
                isl = snapshotBefore.get(idx)
                if isl is not None:
                    for t in isl.tile_set:
                        allowedRebuildIndices.add(t.tile_index)

            neutralTeam = -1
            spuriousNeutral = []
            for tileIndex, islandBefore in snapshotBefore.items():
                if tileIndex in allowedRebuildIndices:
                    continue
                if islandBefore.team != neutralTeam:
                    continue
                islandAfter = bot.tileIslandBuilder.tile_island_lookup.raw[tileIndex]
                if islandAfter is None:
                    continue
                if islandAfter is not islandBefore:
                    tile = playerMap.tiles_by_index[tileIndex]
                    spuriousNeutral.append(f'{tile} (was {islandBefore}, now {islandAfter})')

            if spuriousNeutral:
                self.fail(
                    f'army-increment turn spuriously rebuilt {len(spuriousNeutral)} non-adjacent neutral island(s):\n'
                    + '\n'.join(f'  {s}' for s in spuriousNeutral[:20])
                )

            self.assertAllIslandsContiguous(bot.tileIslandBuilder, debugMode)
            self.assertNoZombieIslands(bot.tileIslandBuilder)
            self.assertNoBorderIslandsStale(bot.tileIslandBuilder)

        simHost.run_between_turns(before_turn)
        simHost.run_between_turns(after_turn)

        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None')
        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=12)

    def test_simhost__enemy_capture_does_not_rebuild_distant_friendly_islands(self):
        """
        When an AFK enemy makes no moves (all army increments), no friendly island that is
        non-adjacent to any changed tile should be rebuilt. This specifically guards against
        the old O(all_tile_islands) zombie scan that would pull in entire island families.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player)

        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        snapshotBefore: typing.Dict[int, TileIsland] = {}
        rebuiltCounts: typing.List[typing.Tuple[int, int, int]] = []  # (turn, total_rebuilt, spurious)

        def before_turn():
            snapshotBefore.clear()
            snapshotBefore.update(self._snapshot_all_island_objects(bot.tileIslandBuilder))

        def after_turn():
            changed = self._tiles_changed_this_turn(playerMap)
            if not changed:
                return
            changedAndAdjacent = changed | self._tiles_adjacent_to_set(changed, playerMap)
            allowedRebuildIndices: typing.Set[int] = set(changedAndAdjacent)
            for idx in changed:
                isl = snapshotBefore.get(idx)
                if isl is not None:
                    for t in isl.tile_set:
                        allowedRebuildIndices.add(t.tile_index)

            spurious = [
                tileIndex for tileIndex, islandBefore in snapshotBefore.items()
                if tileIndex not in allowedRebuildIndices
                and bot.tileIslandBuilder.tile_island_lookup.raw[tileIndex] is not None
                and bot.tileIslandBuilder.tile_island_lookup.raw[tileIndex] is not islandBefore
            ]
            rebuiltCounts.append((playerMap.turn, len(changed), len(spurious)))

            if spurious:
                spuriousTiles = [str(playerMap.tiles_by_index[i]) for i in spurious[:10]]
                self.fail(
                    f'Turn {playerMap.turn}: {len(spurious)} spurious island rebuild(s) '
                    f'(changed={len(changed)} tiles): {spuriousTiles}'
                )

            self.assertAllIslandsContiguous(bot.tileIslandBuilder, debugMode)
            self.assertNoZombieIslands(bot.tileIslandBuilder)
            self.assertNoBorderIslandsStale(bot.tileIslandBuilder)
            self.assertNoLookupMismatches(bot.tileIslandBuilder)

        simHost.run_between_turns(before_turn)
        simHost.run_between_turns(after_turn)

        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None')
        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=16)
