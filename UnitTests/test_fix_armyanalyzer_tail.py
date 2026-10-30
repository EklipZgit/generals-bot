import unittest

from ArmyAnalyzer import ArmyAnalyzer
from Path import Path
from TestBase import TestBase
from base.client.tile import Tile, TILE_EMPTY


class ArmyAnalyzerTailFixTests(TestBase):
    """
    Repro for live FFA crash t3Ka00FzQ turn 485:
        AttributeError: 'NoneType' object has no attribute 'tile'
        at ArmyAnalyzer.build_from_path -> `tileA = path.tail.tile`

    Call chain was:
        BotCombatOps.kill_threat ->
            threat.path.get_subsegment(threat.path.length // 2)  # == get_subsegment(0) for a length-1 path
        -> kill_enemy_paths -> ArmyAnalyzer.build_from_path(map, threatPath)

    get_subsegment's contract is "count moves long, count+1 TILES long", so
    get_subsegment(0) must return a 1-tile degenerate path, not a 0-tile
    empty Path with tail=None.
    """

    def _build_test_map(self, width: int, height: int, turn: int = 1):
        """Builds a small open map with valid tileIndex values (required by MapBase.clear_deltas)."""
        board = [
            [Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * width + x) for x in range(width)]
            for y in range(height)
        ]
        map = self.get_test_map(board, turn=turn)
        return map, board

    def test_get_subsegment__zero_count_returns_single_tile_start_segment(self):
        map, board = self._build_test_map(2, 5)
        board[1][0].player = 0
        board[1][0].army = 20
        board[4][0].player = 1
        board[4][0].army = 9

        path = Path()
        for y in (4, 3, 2, 1, 0):
            path.add_next(board[y][0])

        self.assertEqual(4, path.length)

        subsegment = path.get_subsegment(0)

        self.assertIsNotNone(subsegment.tail, 'a 0-move subsegment must still contain its 1 tile per the count+1 tiles contract')
        self.assertIsNotNone(subsegment.start)
        self.assertEqual(0, subsegment.length)
        self.assertEqual([path.start.tile], subsegment.tileList)
        self.assertEqual(path.start.tile, subsegment.tail.tile)
        self.assertEqual(path.start.tile, subsegment.start.tile)
        # subsegments must be copies, not references to the original path
        self.assertIsNot(subsegment, path)
        self.assertEqual(4, path.length, 'get_subsegment must not mutate the original path')

    def test_get_subsegment__zero_count_end_returns_single_tile_tail_segment(self):
        map, board = self._build_test_map(2, 5)
        path = Path()
        for y in (4, 3, 2, 1, 0):
            path.add_next(board[y][0])

        subsegment = path.get_subsegment(0, end=True)

        self.assertIsNotNone(subsegment.tail)
        self.assertIsNotNone(subsegment.start)
        self.assertEqual(0, subsegment.length)
        self.assertEqual([path.tail.tile], subsegment.tileList)
        self.assertEqual(path.tail.tile, subsegment.start.tile)

    def test_get_subsegment__negative_count_still_returns_empty_path(self):
        """Negative counts are invalid input; the empty-Path (start=None) sentinel is retained
        for backwards compatibility with callers that check `path.start is None`."""
        map, board = self._build_test_map(2, 5)
        path = Path()
        for y in (4, 3, 2, 1, 0):
            path.add_next(board[y][0])

        subsegment = path.get_subsegment(-1)

        self.assertIsNone(subsegment.start)
        self.assertIsNone(subsegment.tail)

    def test_build_from_path__handles_degenerate_half_subsegment_of_length_one_threat_path(self):
        """Exact repro of the t3Ka00FzQ crash: kill_threat passes
        threat.path.get_subsegment(threat.path.length // 2) which is get_subsegment(0)
        for a length-1 threat path."""
        map, board = self._build_test_map(2, 3)
        threatTile = board[1][0]
        threatTile.player = 1
        threatTile.army = 9
        ourTile = board[0][0]
        ourTile.player = 0
        ourTile.army = 30

        threatPath = Path()
        threatPath.add_next(threatTile)
        threatPath.add_next(ourTile)
        self.assertEqual(1, threatPath.length)

        # this is the exact call BotCombatOps.kill_threat makes
        halfSubsegment = threatPath.get_subsegment(threatPath.length // 2)
        self.assertEqual(0, halfSubsegment.length)

        # crashed pre-fix with AttributeError: 'NoneType' object has no attribute 'tile'
        analysis = ArmyAnalyzer.build_from_path(map, halfSubsegment)

        self.assertEqual(threatTile, analysis.tileA)
        self.assertEqual(threatTile, analysis.tileB)
        self.assertIn(threatTile, analysis.shortestPathWay.tiles)

    def test_build_from_path__raises_value_error_on_empty_path(self):
        """A path with zero tiles has nothing to analyze; fail loudly with a clear
        error instead of AttributeError on path.tail."""
        map, board = self._build_test_map(2, 3)

        with self.assertRaises(ValueError):
            ArmyAnalyzer.build_from_path(map, Path())

    def test_get_subsegment__zero_count_on_empty_path_still_empty(self):
        """A 0-tile path cannot produce a 1-tile subsegment; it stays empty
        (which build_from_path then rejects with ValueError)."""
        emptyPath = Path()
        subsegment = emptyPath.get_subsegment(0)
        self.assertIsNone(subsegment.start)
        self.assertIsNone(subsegment.tail)

    def test_get_positive_subsegment__still_returns_empty_path_when_army_dies_immediately(self):
        """When the army cannot even begin the path without going non-positive,
        get_positive_subsegment must keep returning the empty-path sentinel
        (start=None) that DangerAnalyzer threat filtering relies on -- it must
        NOT return the new single-tile 0-move subsegment."""
        map, board = self._build_test_map(2, 4)
        dyingArmyTile = board[3][0]
        dyingArmyTile.player = 1
        dyingArmyTile.army = 2
        blockerTile = board[2][0]
        blockerTile.player = 0
        blockerTile.army = 50
        board[0][0].player = 0

        path = Path()
        path.add_next(dyingArmyTile)
        path.add_next(blockerTile)
        path.add_next(board[1][0])
        path.add_next(board[0][0])

        sub = path.get_positive_subsegment(forPlayer=1, teams=map.team_ids_by_player_index)

        self.assertIsNone(sub.start, 'army dying on the first move must keep producing the empty sentinel, not a 1-tile path')
        self.assertIsNone(sub.tail)


if __name__ == '__main__':
    unittest.main()
