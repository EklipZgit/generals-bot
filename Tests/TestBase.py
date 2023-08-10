import logging
import typing
import unittest

import EarlyExpandUtils
import SearchUtils
from Path import Path
from Sim.TextMapLoader import TextMapLoader
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
        EarlyExpandUtils.DEBUG_ASSERTS = True

    def load_turn_1_map_and_general(self, mapFileName: str) -> typing.Tuple[MapBase, Tile]:
        turn = 1
        board = TextMapLoader.load_map_from_file(f"{mapFileName}")

        map = self.get_test_map(board, turn=turn)
        general = next(t for t in map.pathableTiles if t.isGeneral)
        general.army = 1
        map.player_index = general.player
        map.generals[general.player] = general

        return map, general

    def load_map_and_general(self, mapFilePath: str, turn: int, player_index: int = -1) -> typing.Tuple[MapBase, Tile]:
        board = TextMapLoader.load_map_from_file(mapFilePath)

        map = self.get_test_map(board, turn=turn)
        general = next(t for t in map.pathableTiles if t.isGeneral and (t.player == player_index or player_index == -1))
        map.player_index = general.player
        map.generals[general.player] = general

        return map, general

    def get_test_map(self, tiles: typing.List[typing.List[Tile]], turn: int = 1, player_index: int = 0, dont_set_seen_visible_discovered: bool = False, num_players: int = -1) -> MapBase:
        self._initialize()
        figureOutPlayerCount = num_players == -1
        num_players = max(num_players, 2)
        if not dont_set_seen_visible_discovered:
            for row in tiles:
                for tile in row:
                    tile.lastSeen = turn
                    tile.visible = True
                    tile.discovered = True
                    if figureOutPlayerCount:
                        num_players = max(num_players, tile.player + 1)

        fakeScores = [Score(n, 100, 100, False) for n in range(0, num_players)]

        usernames = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

        map = MapBase(player_index=player_index, teams=None, user_names=usernames[0:num_players], turn=turn, map_grid_y_x=tiles, replay_url='42069')
        map.update_scores(fakeScores)
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

    def get_opposite_general_distance_map(self, map: MapBase, general: Tile, negate: bool = False):
        distMap = SearchUtils.build_distance_map(map, [general])
        maxDist = 0
        furthestTile: Tile = None
        for tile in map.pathableTiles:
            tileDist = distMap[tile.x][tile.y]
            if tileDist > maxDist:
                maxDist = tileDist
                furthestTile = tile

        furthestMap = SearchUtils.build_distance_map(map, [furthestTile])
        if negate:
            for x in range(len(furthestMap)):
                for y in range(len(furthestMap[0])):
                    furthestMap[x][y] = 0 - furthestMap[x][y]

        return furthestMap

    def render_plan(self, map: MapBase, plan: EarlyExpandUtils.ExpansionPlan):
        self.render_paths(map, plan.plan_paths, f'{str(plan.tile_captures)}')

    def render_paths(self, map: MapBase, paths: typing.List[typing.Union[None, Path]], infoStr: str):
        viewer = GeneralsViewer(infoStr)
        viewer.ekBot = EklipZBot(10)
        viewer.ekBot._map = map
        viewer.updateGrid(map, infoStr)
        viewer.ekBot.viewInfo = ViewInfo(1, map.cols, map.rows)
        viewer.ekBot.viewInfo.readyToDraw = True
        r = 255
        g = 0
        b = 0
        encounteredFirst = False
        for path in paths:
            if path is not None:
                encounteredFirst = True
                viewer.ekBot.viewInfo.paths.appendleft(
                    PathColorer(path, r, g, b, alpha=10, alphaDecreaseRate=5, alphaMinimum=10))
            elif encounteredFirst:
                b += 50
            else:
                continue
            r -= 40
            g += 40
            g = min(255, g)
            r = max(0, r)
            b = min(255, b)
        viewer.run_main_viewer_loop()
