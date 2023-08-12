import inspect
import unittest

from SearchUtils import dest_breadth_first_target
from Tests.TestBase import TestBase
from base.client.map import Tile
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


class SearchUtilsTests(TestBase):


    def test_dest_breadth_first_target__calculates_short_path_values_correctly__normal_tile(self):
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
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[target],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_path_values_correctly__targeting_normal_tile(self):
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
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[target],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_short_path_values_correctly__targeting_general(self):
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
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_odd_path_values_correctly__targeting_general(self):
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
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_even_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(11)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[10][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 29

                map = self.get_test_map(board, turn=turn)
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=12,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

