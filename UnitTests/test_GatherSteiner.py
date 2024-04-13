import random
import time

import logbook

import GatherSteiner
import GatherUtils
from Algorithms import TileIslandBuilder, MapSpanningUtils
from MapMatrix import MapMatrix, MapMatrixSet
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import ViewInfo, TargetStyle
from base.client.map import MapBase
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot


class GatherSteinerUnitTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_should_build_steiner_price_collection(self):
        """
        This algo seems useless.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        steinerMatrix = GatherSteiner.build_prize_collecting_steiner_tree(map, general.player)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_zone(steinerMatrix, (0, 255, 255), 150)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_price_collection_at_enemy_general(self):
        """
        This algo seems useless, but more useful than no-enemy-territory.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        steinerMatrix = GatherSteiner.steiner_tree_gather(map, general.player, enemyGeneral)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_zone(steinerMatrix, (0, 255, 255), 150)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        tiles = [
            map.GetTile(10, 5),
            map.GetTile(5, 3),
            map.GetTile(13, 4),
            map.GetTile(13, 1),
            map.GetTile(10, 0),
            map.GetTile(9, 15),
            map.GetTile(1, 16),
            map.GetTile(9, 7),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
        ]

        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_zone(steinerMatrix, (0, 255, 255), 150)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_respecting_value_matrix(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        tiles = [
            map.GetTile(10, 5),
            map.GetTile(5, 3),
            map.GetTile(13, 4),
            map.GetTile(13, 1),
            map.GetTile(10, 0),
            map.GetTile(9, 15),
            map.GetTile(1, 16),
            map.GetTile(9, 7),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
            # map.GetTile(),
        ]

        weightMod = MapMatrix(map, 0)
        for t in map.get_all_tiles():
            # if map.is_tile_friendly(t):
            weightMod[t] -= t.army
            # else:
            #     weightMod -= t.army
        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player, weightMod=weightMod, baseWeight=1000)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        GatherUtils.convert_contiguous_tiles_to_gather_tree_nodes_with_values()

        viewInfo = self.get_renderable_view_info(map)
        viewInfo.add_map_zone(steinerMatrix, (0, 255, 255), 150)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_respecting_large_amount_of_subtree_nodes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        viewInfo = self.get_renderable_view_info(map)

        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        tiles = []
        for island in random.sample(builder.tile_islands_by_player[general.player], 7):
            tiles.extend(island.tile_set)

        ourLargestTile = max(map.players[general.player].tiles, key=lambda t: t.army)
        ourSecondLargestTiles = max([t for t in map.players[general.player].tiles if t != ourLargestTile], key=lambda t: t.army)

        tiles.append(enemyGeneral)
        tiles.append(general)
        tiles.append(ourLargestTile)
        tiles.append(ourSecondLargestTiles)

        weightMod = MapMatrix(map, 0)
        for t in map.get_all_tiles():
            # if map.is_tile_friendly(t):
            weightMod[t] -= t.army
            # else:
            #     weightMod -= t.army

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)
        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player, weightMod=weightMod, baseWeight=1000)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        viewInfo.add_map_zone(steinerMatrix, (150, 255, 150), 90)
        self.render_view_info(map, viewInfo, 'steiner???')

    def test_should_build_steiner_tree__mimicking_what_i_want_gather_to_do(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # self.render_map(map)
        self.begin_capturing_logging()

        viewInfo = self.get_renderable_view_info(map)

        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        ourCity = map.GetTile(7, 4)

        tiles = []
        for island in [
            builder.tile_island_lookup[map.GetTile(3, 5)],

            builder.tile_island_lookup[map.GetTile(1, 0)],

            builder.tile_island_lookup[map.GetTile(11, 0)],

            builder.tile_island_lookup[map.GetTile(12, 2)],

            builder.tile_island_lookup[map.GetTile(11, 3)]
        ]:
            # for island in random.sample(builder.tile_islands_by_player[general.player], 7):
            tiles.extend(island.tile_set)

        ourLargestTile = max(map.players[general.player].tiles, key=lambda t: t.army)
        ourSecondLargestTiles = max([t for t in map.players[general.player].tiles if t != ourLargestTile], key=lambda t: t.army)

        # tiles.append(enemyGeneral)
        tiles.append(general)
        tiles.append(map.GetTile(7, 4))
        tiles.append(ourLargestTile)
        tiles.append(ourCity)
        tiles.append(ourSecondLargestTiles)

        weightMod = MapMatrix(map, 0)
        for t in map.get_all_tiles():
            # if map.is_tile_friendly(t):
            weightMod[t] -= t.army
            # else:
            #     weightMod -= t.army

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)
        steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, general.player, weightMod=weightMod, baseWeight=1000)
        steinerMatrix = MapMatrixSet(map, steinerNodes)

        viewInfo.add_map_zone(steinerMatrix, (150, 255, 150), 90)
        self.render_view_info(map, viewInfo, 'steiner???')

        viewInfo = self.get_renderable_view_info(map)

        for t in tiles:
            viewInfo.add_targeted_tile(t, TargetStyle.GREEN)
        start = time.perf_counter()
        connectedTiles, missingRequired = MapSpanningUtils.get_spanning_tree_from_tile_lists(map, tiles, bannedTiles=set())
        logbook.info(f'MY steiner tree builder took {time.perf_counter() - start:.5f}s')
        steinerMatrix = MapMatrixSet(map, connectedTiles)
        viewInfo.add_map_zone(steinerMatrix, (150, 255, 150), 90)
        self.render_view_info(map, viewInfo, 'Mine???')


