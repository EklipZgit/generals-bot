import logging
import typing
import unittest

import ExpandUtils
import ExpandUtilsTests
import SearchUtils
from Path import Path
from ViewInfo import ViewInfo, PathColorer
from base.client.map import MapBase, Tile, Score
from base.viewer import GeneralsViewer
from bot_ek0x45 import EklipZBot


class TestBase(unittest.TestCase):
    # __test__ = False
    def _set_up_log_stream(self):
        logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    def _initialize(self):
        self._set_up_log_stream()
        SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = True
        ExpandUtils.DEBUG_ASSERTS = True

    def get_test_map(self, tiles: typing.List[typing.List[Tile]], turn: int = 1, player_index: int = 0, dont_set_seen_visible_discovered: bool = False) -> MapBase:
        self._initialize()
        if not dont_set_seen_visible_discovered:
            for row in tiles:
                for tile in row:
                    tile.lastSeen = turn
                    tile.visible = True
                    tile.discovered = True

        map = MapBase(player_index=player_index, teams=None, user_names=['a', 'b'], turn=turn, map_grid_y_x=tiles, replay_url='42069')
        map.update_scores([Score(0, 100, 100, False), Score(1, 100, 100, False)])
        map.update_turn(turn)
        map.update()
        return map

    def get_empty_weight_map(self, map: MapBase):
        return [[0 for y in map.grid] for x in map.grid[0]]

    def get_from_general_weight_map(self, map: MapBase, general: Tile, negate: bool = False):
        distMap = SearchUtils.build_distance_map(map, [general])
        if negate:
            for x in range(len(distMap)):
                for y in range(len(distMap[0])):
                    distMap[x][y] = 0 - distMap[x][y]
        return distMap

    def render_plan(self, map: MapBase, plan: ExpandUtils.ExpansionPlan):
        self.render_paths(map, plan.plan_paths, f'{str(plan.tile_captures)}')

    def render_paths(self, map: MapBase, paths: typing.List[typing.Union[None, Path]], infoStr: str):
        viewer = GeneralsViewer(infoStr)
        viewer.ekBot = EklipZBot(10)
        viewer.ekBot._map = map
        viewer.updateGrid(map, infoStr)
        viewer.ekBot.viewInfo = ViewInfo(1, map.cols, map.rows)
        viewer.ekBot.viewInfo.readyToDraw = True
        for path in paths:
            if path is not None:
                viewer.ekBot.viewInfo.paths.appendleft(
                    PathColorer(path, 0, 0, 0, alpha=255, alphaDecreaseRate=5, alphaMinimum=100))
        viewer.run_main_viewer_loop()
