from Sim.TextMapLoader import TextMapLoader
from Tests.TestBase import TestBase


class TextMapLoaderTests(TestBase):
    def test_loads_general(self):
        data = """
|   |   |   |
aG10
"""
        map = TextMapLoader.load_map_from_string(data, split_every=4)
        self.assertTrue(map[0][0].isGeneral)
        self.assertEqual(10, map[0][0].army)
        self.assertEqual(0, map[0][0].player)

    def test_loads_cities(self):
        data = """
|   |   |   |
a1  b4
a0
C43
"""
        map = TextMapLoader.load_map_from_string(data, split_every=4)
        self.assertEqual(-1, map[2][0].player)
        self.assertEqual(43, map[2][0].army)
        self.assertTrue(map[2][0].isCity)

    def test_loads_mountain(self):
        data = """
|   |   |   |
    M
"""
        map = TextMapLoader.load_map_from_string(data, split_every=4)
        self.assertEqual(-1, map[0][1].player)
        self.assertEqual(0, map[0][1].army)
        self.assertTrue(map[0][1].mountain)

    def test_loads_neutral_army(self):
        data = """
|   |   |   |
    N100
"""
        map = TextMapLoader.load_map_from_string(data, split_every=4)
        self.assertEqual(-1, map[0][1].player)
        self.assertEqual(100, map[0][1].army)
        self.assertFalse(map[0][1].mountain)
        self.assertFalse(map[0][1].isCity)

    def test_loads_players(self):
        data = """
|   |   |   |
a1  b4
a0
C43
"""
        map = TextMapLoader.load_map_from_string(data, split_every=4)
        self.assertEqual(0, map[0][0].player)
        self.assertEqual(1, map[0][0].army)
        self.assertEqual(1, map[0][1].player)
        self.assertEqual(4, map[0][1].army)

    def test_ignores_trailing_pipes_and_newlines(self):
        data = """
|   |   |   |
    M

|   |   |   |
"""
        map = TextMapLoader.load_map_from_string(data, split_every=4)
        self.assertEqual(2, len(map))
        self.assertEqual(4, len(map[0]))

    def test_dump_map_writes_general(self):
        data = """
|   |   |   |
aG10
|   |   |   |
"""
        board = TextMapLoader.load_map_from_string(data, split_every=4)
        map = self.get_test_map(board, turn=1)

        reStr = TextMapLoader.dump_map_to_string(map, split_every=4)
        self.assertEqual(data.strip(), reStr.strip())

    def test_dump_map_writes_cities(self):
        data = """
|   |   |   |
a1  b4
a0
C43
|   |   |   |
"""
        board = TextMapLoader.load_map_from_string(data, split_every=4)
        map = self.get_test_map(board, turn=1)

        reStr = TextMapLoader.dump_map_to_string(map, split_every=4)
        self.assertEqual(data.strip(), reStr.strip())

    def test_dump_map_writes_mountain(self):
        data = """
|   |   |   |
    M
|   |   |   |
"""
        board = TextMapLoader.load_map_from_string(data, split_every=4)
        map = self.get_test_map(board, turn=1)

        reStr = TextMapLoader.dump_map_to_string(map, split_every=4)
        self.assertEqual(data.strip(), reStr.strip())

    def test_dump_map_writes_neutral_army(self):
        data = """
|   |   |   |
    N100
|   |   |   |
"""
        board = TextMapLoader.load_map_from_string(data, split_every=4)
        map = self.get_test_map(board, turn=1)

        reStr = TextMapLoader.dump_map_to_string(map, split_every=4)
        self.assertEqual(data.strip(), reStr.strip())

    def test_dump_map_writes_players(self):
        data = """
|   |   |   |
a1  b4
a0
C43
|   |   |   |
"""
        board = TextMapLoader.load_map_from_string(data, split_every=4)
        map = self.get_test_map(board, turn=1)

        reStr = TextMapLoader.dump_map_to_string(map, split_every=4)
        self.assertEqual(data.strip(), reStr.strip())

    def test_dump_map_ignores_trailing_pipes_and_newlines(self):
        data = """
|   |   |   |
    M

|   |   |   |
"""
        board = TextMapLoader.load_map_from_string(data, split_every=4)
        map = self.get_test_map(board, turn=1)

        reStr = TextMapLoader.dump_map_to_string(map, split_every=4)
        self.assertEqual(data.strip(), reStr.strip())

    def test_reads_test_files(self):
        map = TextMapLoader.load_map_from_file("EarlyExpandUtilsTestMaps/forced_corner_combo")
        self.assertTrue(map[0][0].isGeneral)
        self.assertEqual(1, map[0][0].army)
        self.assertEqual(0, map[0][0].player)

        self.assertFalse(map[0][1].isGeneral)
        self.assertEqual(0, map[0][1].army)
        self.assertEqual(-1, map[0][1].player)
