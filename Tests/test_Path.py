import inspect
import unittest

from Path import Path
from Tests.TestBase import TestBase
from base.client.tile import Tile, TILE_EMPTY, MapBase
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


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
                path = Path(armyRemaining=-42)
                path.add_next(threatTile)
                path.add_next(board[1][0])
                path.add_next(general)

                val = path.calculate_value(forPlayer=1, teams=map._teams)
                self.assertEqual(1, val)
                self.assertEqual(1, path.value)

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
                path = Path(armyRemaining=-42)
                for i in range(10):
                    path.add_next(board[9 - i][0])

                val = path.calculate_value(forPlayer=1, teams=map._teams)
                self.assertEqual(1, val)
                self.assertEqual(1, path.value)

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
                path = Path(armyRemaining=-42)
                path.add_next(threatTile)
                path.add_next(board[1][0])
                path.add_next(target)

                val = path.calculate_value(forPlayer=1, teams=map._teams)
                self.assertEqual(1, val)
                self.assertEqual(1, path.value)

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
                path = Path(armyRemaining=-42)
                path.add_next(threatTile)
                path.add_next(target, move_half=True)

                val = path.calculate_value(forPlayer=0, teams=map._teams)
                self.assertEqual(expectedVal, val)
                self.assertEqual(expectedVal, path.value)

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
                path = Path(armyRemaining=-42)
                for i in range(10):
                    path.add_next(board[9 - i][0])

                val = path.calculate_value(forPlayer=1, teams=map._teams)
                self.assertEqual(1, val)
                self.assertEqual(1, path.value)

    def test_get_subsegment__count_means_length__start(self):
        turn = 1
        # test both odd and even turns
        board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
        target = board[0][0]
        target.army = 5

        threatTile = board[9][0]
        threatTile.player = 1
        threatTile.army = 23

        map = self.get_test_map(board, turn=turn)
        path = Path(armyRemaining=-42)
        for i in range(10):
            path.add_next(board[9 - i][0])

        self.assertEqual(path.length, 9)
        subsegment = path.get_subsegment(3)

        self.assertEqual(subsegment.length, 3)
        self.assertEqual(subsegment.start.tile, path.start.tile)
        self.assertEqual(subsegment.tail.tile, board[6][0])

    def test_get_subsegment__count_means_length__end(self):
        turn = 1
        # test both odd and even turns
        board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
        target = board[0][0]
        target.army = 5

        threatTile = board[9][0]
        threatTile.player = 1
        threatTile.army = 23

        map = self.get_test_map(board, turn=turn)
        path = Path(armyRemaining=-42)
        for i in range(10):
            path.add_next(board[9 - i][0])

        self.assertEqual(path.length, 9)
        subsegment = path.get_subsegment(3, end=True)

        self.assertEqual(subsegment.length, 3)
        self.assertEqual(subsegment.tail.tile, path.tail.tile)
        self.assertEqual(subsegment.start.tile, board[3][0])

    def test_subsegment_with_own_length_returns_copy(self):
        turn = 1
        # test both odd and even turns
        board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
        target = board[0][0]
        target.army = 5

        threatTile = board[9][0]
        threatTile.player = 1
        threatTile.army = 23

        map = self.get_test_map(board, turn=turn)
        path = Path(armyRemaining=-42)
        for i in range(10):
            path.add_next(board[9 - i][0])

        self.assertEqual(path.length, 9)
        copyBySubsegment = path.get_subsegment(path.length)
        self.assertEqual(copyBySubsegment.length, path.length)
        self.assertEqual(copyBySubsegment.value, path.value)
        self.assertEqual(copyBySubsegment.start.tile, path.start.tile)
        self.assertEqual(copyBySubsegment.tail.tile, path.tail.tile)

    def test_break_overflow_into_one_move_path_subsegments__handles_short_path(self):
        turn = 1
        # test both odd and even turns
        board = [[Tile(x, y) for x in range(1)] for y in range(10)]

        threatTile = board[9][0]
        threatTile.player = 1
        threatTile.army = 23

        map = self.get_test_map(board, turn=turn)
        path = Path(armyRemaining=-42)
        for i in range(10):
            path.add_next(board[9 - i][0])

        self.assertEqual(path.length, 9)
        subsegmentList = path.break_overflow_into_one_move_path_subsegments(lengthToKeepInOnePath=13)
        self.assertEqual(len(subsegmentList), 1)
        self.assertEqual(subsegmentList[0].length, path.length)
        self.assertEqual(subsegmentList[0].start.tile, path.start.tile)
        self.assertEqual(subsegmentList[0].tail.tile, path.tail.tile)
        self.assertEqual(subsegmentList[0].value, path.value)

    def test_break_overflow_into_one_move_path_subsegments__breaks_up_long_path(self):
        turn = 1
        # test both odd and even turns
        board = [[Tile(x, y) for x in range(1)] for y in range(10)]

        threatTile = board[9][0]
        threatTile.player = 1
        threatTile.army = 23

        map = self.get_test_map(board, turn=turn)
        path = Path(armyRemaining=-42)
        for i in range(10):
            path.add_next(board[9 - i][0])

        self.assertEqual(path.length, 9)
        subsegmentList = path.break_overflow_into_one_move_path_subsegments(lengthToKeepInOnePath=4)
        # expect one length 4, and 5 length 1
        self.assertEqual(len(subsegmentList), 6)

        self.assertEqual(subsegmentList[0].length, 4)
        self.assertEqual(subsegmentList[1].length, 1)
        self.assertEqual(subsegmentList[2].length, 1)
        self.assertEqual(subsegmentList[3].length, 1)
        self.assertEqual(subsegmentList[4].length, 1)
        self.assertEqual(subsegmentList[5].length, 1)

        self.assertEqual(subsegmentList[0].start.tile, path.start.tile)

        prev = None
        for subsegment in subsegmentList:
            if prev is not None:
                self.assertEqual(subsegment.start.tile, prev.tail.tile)
            prev = subsegment

        self.assertEqual(subsegmentList[5].tail.tile, path.tail.tile)

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
                path = Path(armyRemaining=-42)
                path.add_next(threatTile)
                path.add_next(target)

                val = path.calculate_value(forPlayer=0, teams=map._teams)
                self.assertEqual(1, val)
                self.assertEqual(1, path.value)

    def test_get_positive_subsegment__prunes_negative_end(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_intercept_armies_that_have_no_movement_choices_left___zkv9Q0x9h---1--236.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 236, fill_out_tiles=True)

        path = Path.from_string(map, '12,11->12,10->11,10')
        sub = path.get_positive_subsegment(enemyGeneral.player, MapBase.get_teams_array(map))

        self.assertEqual(2, path.length)
        self.assertEqual(1, sub.value, 'have 1 army on final tile which should be 12,10')
        self.assertEqual(1, sub.length)
        self.assertEqual(map.GetTile(12, 10), sub.tail.tile)