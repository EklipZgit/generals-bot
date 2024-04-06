import time

from Algorithms import TileIslandBuilder
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

        return bot

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
        builder.recalculate_tile_islands(enemyGeneral)

        if debugMode:
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

    def test_should_group_by_army_values(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)
        #
        # if debugMode:
        #     self.render_map(map)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        if debugMode:
            self.render_tile_islands(map, builder)

        twoIsland1 = builder.tile_island_lookup[map.GetTile(11, 0)]

        twoIsland2 = builder.tile_island_lookup[map.GetTile(10, 1)]

        threeIsland1 = builder.tile_island_lookup[map.GetTile(11, 2)]

        threeIsland2 = builder.tile_island_lookup[map.GetTile(12, 4)]

        self.assertEqual(twoIsland1, twoIsland2, 'these 2 tiles should be grouped in the same island')
        self.assertEqual(threeIsland1, threeIsland2, 'these 3 tiles should be grouped in the same island')
        self.assertNotEqual(threeIsland1, twoIsland1, '2s and 3s should be separate islands')

    def render_tile_islands(self, map: MapBase, builder: TileIslandBuilder):
        viewInfo = self.get_renderable_view_info(map)
        colors = PLAYER_COLORS
        i = 0
        for island in sorted(builder.all_tile_islands, key=lambda i: (i.team, str(i.name))):
            color = colors[i]

            viewInfo.add_map_zone(island.tile_set, color, alpha=80)
            viewInfo.add_map_division(island.tile_set, color, alpha=200)
            if island.name:
                for tile in island.tile_set:
                    if viewInfo.bottomRightGridText[tile]:
                        viewInfo.midRightGridText[tile] = island.name
                    else:
                        viewInfo.bottomRightGridText[tile] = island.name

            viewInfo.add_info_line_no_log(f'{island.team}: island {island.name} - {island.sum_army}a/{island.tile_count}t ({island.sum_army_all_adjacent_friendly}a/{island.tile_count_all_adjacent_friendly}t) {str(island.tile_set)}')

            i += 1
            if i >= len(colors):
                i = 0

        self.render_view_info(map, viewInfo)


