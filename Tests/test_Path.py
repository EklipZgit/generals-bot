import inspect
import unittest

from Path import Path
from Tests.TestBase import TestBase
from base.client.map import Tile, TILE_EMPTY
from base.viewer import GeneralsViewer
from dangerAnalyzer import DangerAnalyzer


class PathTests(TestBase):

    def test_calculates_short_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(3)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 9

                map = self.get_test_map(board, turn=turn)
                path = Path(value=-42)
                path.add_next(threatTile)
                path.add_next(board[1][0])
                path.add_next(general)

                val = path.calculate_value(forPlayer=1)
                self.assertEquals(1, val)
                self.assertEquals(1, path.value)

    def test_calculates_longer_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 27

                map = self.get_test_map(board, turn=turn)
                path = Path(value=-42)
                for i in range(10):
                    path.add_next(board[9 - i][0])

                val = path.calculate_value(forPlayer=1)
                self.assertEquals(1, val)
                self.assertEquals(1, path.value)

    def test_calculates_short_path_values_correctly__targeting_normal_tile(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(3)]
                target = board[0][0]
                target.army = 5

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 9

                map = self.get_test_map(board, turn=turn)
                path = Path(value=-42)
                path.add_next(threatTile)
                path.add_next(board[1][0])
                path.add_next(target)

                val = path.calculate_value(forPlayer=1)
                self.assertEquals(1, val)
                self.assertEquals(1, path.value)

    def test_calculates_short_path_values_correctly__move_half(self):
        # test both odd and even turns
        testCases = [(2, 1), (3, 1), (4, 2)]
        for tileArmy, expectedVal in testCases:
            with self.subTest(tileArmy=tileArmy, expectedVal=expectedVal):
                board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(2)]
                target = board[0][0]

                threatTile = board[1][0]
                threatTile.player = 0
                threatTile.army = tileArmy

                map = self.get_test_map(board, turn=1)
                path = Path(value=-42)
                path.add_next(threatTile)
                path.add_next(target, move_half=True)

                val = path.calculate_value(forPlayer=0)
                self.assertEquals(expectedVal, val)
                self.assertEquals(expectedVal, path.value)

    def test_calculates_longer_path_values_correctly__targeting_normal_tile(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
                target = board[0][0]
                target.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. So to kill tile @ 5 it takes 18 + 5 = 23
                threatTile.army = 23

                map = self.get_test_map(board, turn=turn)
                path = Path(value=-42)
                for i in range(10):
                    path.add_next(board[9 - i][0])

                val = path.calculate_value(forPlayer=1)
                self.assertEquals(1, val)
                self.assertEquals(1, path.value)

    def test_calculates_longer_path_values_correctly__targeting_empty_tile_length_1(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=TILE_EMPTY, army=0, player=-1) for x in range(1)] for y in range(2)]
                target = board[0][0]

                threatTile = board[1][0]
                threatTile.player = 0
                # 2 army lost per move, 9 moves. So to kill tile @ 5 it takes 18 + 5 = 23
                threatTile.army = 2

                map = self.get_test_map(board, turn=turn)
                path = Path(value=-42)
                path.add_next(threatTile)
                path.add_next(target)

                val = path.calculate_value(forPlayer=0)
                self.assertEquals(1, val)
                self.assertEquals(1, path.value)