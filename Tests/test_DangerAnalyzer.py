import inspect
import unittest

from Tests.TestBase import TestBase
from base.client.tile import Tile
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


class DangerAnalyzerTests(TestBase):
    # OF NOTE: Captures happen BEFORE city / general increments.

    def test_finds_short_threats_when_exactly_lethal(self):
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

                # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                dangerAnalyzer = DangerAnalyzer(map)
                dangerAnalyzer.analyze(general, 11, {})

                self.assertIsNotNone(dangerAnalyzer.fastestThreat)
                self.assertEquals(1, dangerAnalyzer.fastestThreat.turns)
                self.assertEquals(1, dangerAnalyzer.fastestThreat.threatValue)

    def test_finds_short_threats_when_exactly_lethal__failed_live(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=2, player=0) for x in range(1)] for y in range(3)]

                general = board[0][0]
                general.isGeneral = True
                general.army = 17

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 22

                map = self.get_test_map(board, turn=turn)

                # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                dangerAnalyzer = DangerAnalyzer(map)
                dangerAnalyzer.analyze(general, 10, {})

                self.assertIsNotNone(dangerAnalyzer.fastestThreat)
                self.assertEquals(1, dangerAnalyzer.fastestThreat.turns)
                self.assertEquals(1, dangerAnalyzer.fastestThreat.threatValue)

    def test_finds_long_threats_when_exactly_lethal(self):
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
                threatTile.army = 27

                map = self.get_test_map(board, turn=turn)

                # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                dangerAnalyzer = DangerAnalyzer(map)
                dangerAnalyzer.analyze(general, 11, {})

                self.assertIsNotNone(dangerAnalyzer.fastestThreat)
                self.assertEquals(8, dangerAnalyzer.fastestThreat.turns)
                self.assertEquals(1, dangerAnalyzer.fastestThreat.threatValue)

    def test_finds_long_larger_threats(self):
        armySizes = [27, 28, 29, 30, 31, 32, 35, 40, 50, 100, 10_000]
        for armySize in armySizes:
            with self.subTest(armySize=armySize):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]

                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                threatTile.army = armySize

                map = self.get_test_map(board, turn=1)

                # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                dangerAnalyzer = DangerAnalyzer(map)
                dangerAnalyzer.analyze(general, 11, {})

                self.assertIsNotNone(dangerAnalyzer.fastestThreat)
                self.assertEquals(8, dangerAnalyzer.fastestThreat.turns)

    def test_finds_no_short_threats_when_exactly_nonlethal(self):
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
                threatTile.army = 8

                map = self.get_test_map(board, turn=turn)

                # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                dangerAnalyzer = DangerAnalyzer(map)
                dangerAnalyzer.analyze(general, 11, {})

                self.assertIsNone(dangerAnalyzer.fastestThreat)

    def test_finds_no_long_threats_when_exactly_nonlethal(self):
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
                threatTile.army = 26

                map = self.get_test_map(board, turn=turn)

                # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                dangerAnalyzer = DangerAnalyzer(map)
                dangerAnalyzer.analyze(general, 11, {})

                self.assertIsNone(dangerAnalyzer.fastestThreat)

    def test_finds_no_long_threats_when_nonlethal(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]

        # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
        armyAmountsToTest = [26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12]
        for turn in turnsToTest:
            for armyAmount in armyAmountsToTest:
                with self.subTest(turn=turn, armyAmount=armyAmount):
                    board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]

                    general = board[0][0]
                    general.isGeneral = True
                    general.army = 5

                    threatTile = board[9][0]
                    threatTile.player = 1
                    threatTile.army = armyAmount

                    map = self.get_test_map(board, turn=turn)

                    # viewer = GeneralsViewer(name=inspect.stack()[0][3])
                    dangerAnalyzer = DangerAnalyzer(map)
                    dangerAnalyzer.analyze(general, 11, {})

                    self.assertIsNone(dangerAnalyzer.fastestThreat)

    def test_finds_threat_on_unfriendly_turn(self):
        turn = 197
        map, general = self.load_map_and_general('DangerAnalyzerTestMaps/missed_defense_by_one_turn_197', turn=turn, player_index=1)

        # viewer = GeneralsViewer(name=inspect.stack()[0][3])
        dangerAnalyzer = DangerAnalyzer(map)
        dangerAnalyzer.analyze(general, 11, {})

        self.assertIsNotNone(dangerAnalyzer.fastestThreat)
        self.assertEquals(1, dangerAnalyzer.fastestThreat.threatValue)