import typing
import unittest

from base.client.map import MapBase, Tile, Score


class TestBase(unittest.TestCase):
    # __test__ = False
    def get_test_map(self, rows: int = 12, cols: int = 12, turn: int = 1) -> MapBase:
        tiles = [[Tile(x, y) for x in range(cols)] for y in range(rows)]

        for row in tiles:
            for tile in row:
                tile.lastSeen = turn
                tile.visible = True
                tile.discovered = True

        map = MapBase(0, teams=None, user_names=['a', 'b'], turn=turn, map_grid_y_x=tiles, replay_url='42069')
        map.update_scores([Score(0, 100, 100, False), Score(1, 100, 100, False)])
        map.update_turn(turn)
        map.update()
        return map

    def get_test_map(self, tiles: typing.List[typing.List[Tile]], turn: int = 1, player_index: int = 0, dont_set_seen_visible_discovered: bool = False) -> MapBase:
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
