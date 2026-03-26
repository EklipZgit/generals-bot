import unittest

from CityExpander import find_city_expansion_paths
from Tests.TestBase import TestBase
from base.client.tile import Tile, TILE_EMPTY
from base.client.map import MapBase


class CityExpanderTests(TestBase):
    def __init__(self, methodName: str = ...):
        super().__init__(methodName)
        MapBase.DO_NOT_RANDOMIZE = True

    def assert_start_path(self, paths_by_start, start, expected_move_string: str, expected_value: int, expected_econ_value: float):
        self.assertIn(start, paths_by_start)
        self.assertEqual(1, len(paths_by_start[start]))
        path = paths_by_start[start][0]
        self.assertEqual(expected_move_string, path.to_move_string())
        self.assertEqual(expected_value, path.value)
        self.assertEqual(expected_econ_value, path.econValue)

    def test_finds_paths_for_general_and_city(self):
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * 2 + x) for x in range(2)] for y in range(2)]
        board[0][0].player = 0
        board[0][0].tile = 0
        board[0][0].army = 8
        board[0][0].isGeneral = True
        board[0][1].player = 1
        board[0][1].tile = 1
        board[0][1].army = 1
        board[1][0].player = 0
        board[1][0].tile = 0
        board[1][0].army = 8
        board[1][0].isCity = True
        board[1][1].player = 1
        board[1][1].tile = 1
        board[1][1].army = 1

        map = self.get_test_map(board, turn=1)
        general = map.GetTile(0, 0)
        city = map.GetTile(0, 1)
        map.players[0].general = general
        map.players[0].cities = [city]

        paths_by_start = find_city_expansion_paths(map, searching_player=0, max_range=15)

        self.assertIn(general, paths_by_start)
        self.assertIn(city, paths_by_start)
        self.assertEqual(1, len(paths_by_start[general]))
        self.assertEqual(1, len(paths_by_start[city]))
        self.assertEqual(['0,0', '1,0'], [f'{t.x},{t.y}' for t in paths_by_start[general][0].tileList])
        self.assertEqual(['0,1', '1,1'], [f'{t.x},{t.y}' for t in paths_by_start[city][0].tileList])

    def test_prioritizes_deepest_enemy_path_first_and_discards_fully_overlapped_shallower_paths(self):
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * 4 + x) for x in range(4)] for y in range(1)]
        board[0][0].player = 0
        board[0][0].tile = 0
        board[0][0].army = 10
        board[0][0].isGeneral = True
        board[0][1].player = 1
        board[0][1].tile = 1
        board[0][1].army = 1
        board[0][2].player = 1
        board[0][2].tile = 1
        board[0][2].army = 1
        board[0][3].player = 1
        board[0][3].tile = 1
        board[0][3].army = 1

        map = self.get_test_map(board, turn=1)
        general = map.GetTile(0, 0)
        map.players[0].general = general
        map.players[0].cities = []

        paths_by_start = find_city_expansion_paths(map, searching_player=0, max_range=15)

        self.assertEqual(1, len(paths_by_start[general]))
        self.assertEqual(['0,0', '1,0', '2,0', '3,0'], [f'{t.x},{t.y}' for t in paths_by_start[general][0].tileList])

    def test_claimed_enemy_tiles_are_not_recounted_across_origins(self):
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * 3 + x) for x in range(3)] for y in range(2)]
        board[0][0].player = 0
        board[0][0].tile = 0
        board[0][0].army = 9
        board[0][0].isGeneral = True
        board[0][1].player = 1
        board[0][1].tile = 1
        board[0][1].army = 1
        board[0][2].player = 1
        board[0][2].tile = 1
        board[0][2].army = 1
        board[1][0].player = 0
        board[1][0].tile = 0
        board[1][0].army = 9
        board[1][0].isCity = True
        board[1][1].player = 1
        board[1][1].tile = 1
        board[1][1].army = 1

        map = self.get_test_map(board, turn=1)
        general = map.GetTile(0, 0)
        city = map.GetTile(0, 1)
        map.players[0].general = general
        map.players[0].cities = [city]

        paths_by_start = find_city_expansion_paths(map, searching_player=0, max_range=15)

        self.assertEqual(1, len(paths_by_start[general]))
        self.assertEqual(1, len(paths_by_start[city]))
        self.assertEqual(['0,0', '1,0'], [f'{t.x},{t.y}' for t in paths_by_start[general][0].tileList])
        self.assertEqual(['0,1', '1,1'], [f'{t.x},{t.y}' for t in paths_by_start[city][0].tileList])

    def test_respects_max_range_cap(self):
        board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * 17 + x) for x in range(17)] for y in range(1)]
        board[0][0].player = 0
        board[0][0].tile = 0
        board[0][0].army = 20
        board[0][0].isGeneral = True
        board[0][16].player = 1
        board[0][16].tile = 1
        board[0][16].army = 1

        map = self.get_test_map(board, turn=1)
        general = map.GetTile(0, 0)
        map.players[0].general = general
        map.players[0].cities = []

        paths_by_start = find_city_expansion_paths(map, searching_player=0, max_range=15)

        self.assertEqual([], paths_by_start[general])

    def test_map_case__defending_contested_city__returns_expected_city_and_general_lines(self):
        map_file = 'GameContinuationEntries/should_consider_this_defending_a_friendly_contested_city_i_think___rETyBtOqf---0--281.txtmap'
        map, general, enemy_general = self.load_map_and_generals(map_file, 281, fill_out_tiles=True)

        paths_by_start = find_city_expansion_paths(map, searching_player=general.player, max_range=15)

        self.assertEqual(5, len(paths_by_start))
        self.assert_start_path(paths_by_start, map.GetTile(3, 5), '3,5->3,4->3,3->3,2->3,1', 2, 2.0)
        self.assert_start_path(paths_by_start, map.GetTile(2, 11), '2,11->1,11->1,10->1,9->1,8->0,8->0,7->0,6->0,5->0,4->0,3', 4, 4.0)
        self.assert_start_path(paths_by_start, general, '5,17->4,17->3,17->3,16->2,16->2,15->2,14->2,13->2,12->2,11->1,11->1,10->1,9->1,8->0,8->0,7', 2, 2.0)

    def test_map_case__all_in_city_hold__returns_expected_forward_city_lines(self):
        map_file = 'GameContinuationEntries/should_immediately_all_in_gather_hold_one_of_the_cities___rETyBtOqf---0--295.txtmap'
        map, general, enemy_general = self.load_map_and_generals(map_file, 295, fill_out_tiles=True)

        paths_by_start = find_city_expansion_paths(map, searching_player=general.player, max_range=15)

        self.assertEqual(6, len(paths_by_start))
        self.assert_start_path(paths_by_start, map.GetTile(8, 5), '8,5->7,5->7,4->7,3->6,3->5,3->5,2->4,2->3,2->2,2', 3, 3.0)
        self.assert_start_path(paths_by_start, map.GetTile(2, 11), '2,11->1,11->1,10->1,9->1,8->0,8->0,7->0,6->0,5->0,4->0,3', 4, 4.0)
        self.assert_start_path(paths_by_start, general, '5,17->4,17->3,17->3,16->2,16->2,15->2,14->2,13->2,12->2,11->1,11->1,10->1,9->1,8->0,8->0,7', 2, 2.0)

    def test_map_case__forward_city__returns_deep_enemy_push(self):
        map_file = 'GameContinuationEntries/should_see_city_as_forward_from_central_point___HgAyaVTVa---1--307.txtmap'
        map, general, enemy_general = self.load_map_and_generals(map_file, 307, fill_out_tiles=True)

        paths_by_start = find_city_expansion_paths(map, searching_player=general.player, max_range=15)

        self.assertEqual(3, len(paths_by_start))
        self.assert_start_path(paths_by_start, map.GetTile(6, 14), '6,14->7,14->7,13->7,12->8,12->8,11->8,10->8,9->8,8->9,8->9,7->9,6', 5, 5.0)
        self.assert_start_path(paths_by_start, general, '11,16->10,16->10,15->10,14->10,13->10,12->11,12->11,11->11,10->11,9->10,9->10,8->10,7->10,6', 1, 1.0)

    def test_map_case__general_nearby_enemy_territory__returns_expected_general_line(self):
        map_file = 'GameContinuationEntries/should_begin_killing_enemy_territory_nearby_general___HeTmhYF6h---b--300.txtmap'
        map, general, enemy_general = self.load_map_and_generals(map_file, 300, fill_out_tiles=True)

        paths_by_start = find_city_expansion_paths(map, searching_player=general.player, max_range=15)

        self.assertEqual(1, len(paths_by_start))
        self.assert_start_path(paths_by_start, general, '6,11->7,11->8,11->9,11->9,10->9,9->10,9->10,8->10,7->10,6->10,5', 3, 3.0)


if __name__ == '__main__':
    unittest.main()
