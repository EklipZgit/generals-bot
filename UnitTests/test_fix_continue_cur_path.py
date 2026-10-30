"""
Regression tests for the live-game crash in BotPathingUtils.continue_cur_path:
AssertionError('bitch, what you doin?') was thrown when a stored bot.curPath
needed more than 20 stale head-move pops in a single call (observed in 4 FFA
logs around turns 75-77, where every remaining move in the stored path sourced
from a tile that now had 0/1 army or was enemy-owned, so the whole path was
consumed by the stale-move skip loop and then the guard assert fired).
"""
import typing
import unittest
from types import SimpleNamespace

from base.client.tile import Tile
from Models.Move import Move
from Path import MoveListPath, Path
from BotModules.BotPathingUtils import BotPathingUtils


def _make_tile(x: int, y: int, army: int, player: int) -> Tile:
    """Builds a plain real Tile with the given army/owner for path tests.
    Tile.__eq__/__hash__ use tile_index only, so every tile needs a unique one."""
    return Tile(x, y, army=army, player=player, tileIndex=y * 1000 + x)


def _link_line(tiles: typing.List[Tile]) -> None:
    """Wires movable/adjacents for a straight line of tiles so the
    'nextMove.source not in nextMove.dest.movable' validity check passes."""
    for i, tile in enumerate(tiles):
        neighbors = []
        if i > 0:
            neighbors.append(tiles[i - 1])
        if i < len(tiles) - 1:
            neighbors.append(tiles[i + 1])
        tile.movable = neighbors
        tile.adjacents = list(neighbors)


def _build_path(tiles: typing.List[Tile]) -> Path:
    path = Path()
    for tile in tiles:
        path.add_next(tile)
    return path


def _build_bot(curPath: Path, playerIndex: int = 0) -> SimpleNamespace:
    """Builds the minimal fake bot surface that continue_cur_path touches."""
    general = Tile(40, 40, army=10, player=playerIndex, isGeneral=True, tileIndex=40040)
    return SimpleNamespace(
        expansion_plan=SimpleNamespace(includes_intercept=False),
        curPath=curPath,
        curPathPrio=3,
        general=general,
        targetingArmy=None,
        _map=SimpleNamespace(
            player_index=playerIndex,
            turn=75,
            last_player_index_submitted_move=None),
        history=SimpleNamespace(move_history={}, droppedHistory={}),
        armyTracker=SimpleNamespace(armies={}),
        viewInfo=SimpleNamespace(
            add_info_line=lambda value: None,
            color_path=lambda value: None),
        info=lambda value: None)


class ContinueCurPathStalePathTests(unittest.TestCase):
    def test_long_fully_stale_path_is_abandoned_instead_of_asserting(self):
        """Repro of the live crash: a stored Path longer than the stale-pop
        guard where EVERY move's source now has 1 army (the planned army-flow
        never executed). Must not raise; the dead path must be abandoned so the
        caller falls through to fresh planning."""
        tiles = [_make_tile(x, 0, army=1, player=0) for x in range(30)]
        _link_line(tiles)
        bot = _build_bot(_build_path(tiles))

        shouldUseMove, move = BotPathingUtils.continue_cur_path(bot, None, set())

        self.assertFalse(shouldUseMove)
        self.assertIsNone(move)
        self.assertIsNone(bot.curPath)
        self.assertEqual(-1, bot.curPathPrio)

    def test_long_fully_stale_move_list_path_is_abandoned_instead_of_asserting(self):
        """Same crash repro but through a MoveListPath (explicit move list),
        which is the other TilePlanInterface stored in bot.curPath."""
        tiles = [_make_tile(x, 5, army=1, player=0) for x in range(26)]
        _link_line(tiles)
        moves = [Move(tiles[i], tiles[i + 1]) for i in range(len(tiles) - 1)]
        bot = _build_bot(MoveListPath(moves))

        shouldUseMove, move = BotPathingUtils.continue_cur_path(bot, None, set())

        self.assertFalse(shouldUseMove)
        self.assertIsNone(move)
        self.assertIsNone(bot.curPath)
        self.assertEqual(-1, bot.curPathPrio)

    def test_long_enemy_owned_path_is_abandoned_instead_of_asserting(self):
        """The stale loop also fires when path tiles got recaptured by an
        enemy mid-plan (source.player != our index). >20 of those must abandon
        the path rather than assert."""
        tiles = [_make_tile(x, 10, army=5, player=1) for x in range(30)]
        _link_line(tiles)
        bot = _build_bot(_build_path(tiles))

        shouldUseMove, move = BotPathingUtils.continue_cur_path(bot, None, set())

        self.assertFalse(shouldUseMove)
        self.assertIsNone(move)
        self.assertIsNone(bot.curPath)
        self.assertEqual(-1, bot.curPathPrio)

    def test_short_stale_prefix_is_skipped_and_valid_move_returned(self):
        """A couple of stale head moves is the legit case the skip loop exists
        for: the next tile independently holds enough army, so the surviving
        tail of the path should still produce its move."""
        tiles = [
            _make_tile(0, 20, army=1, player=0),
            _make_tile(1, 20, army=1, player=0),
            _make_tile(2, 20, army=8, player=0),
            _make_tile(3, 20, army=1, player=0),
            _make_tile(4, 20, army=1, player=-1),
        ]
        _link_line(tiles)
        bot = _build_bot(_build_path(tiles))

        shouldUseMove, move = BotPathingUtils.continue_cur_path(bot, None, set())

        self.assertTrue(shouldUseMove)
        self.assertIsNotNone(move)
        self.assertIs(tiles[2], move.source)
        self.assertIs(tiles[3], move.dest)
        self.assertIsNotNone(bot.curPath)

    def test_fully_stale_path_under_pop_limit_returns_no_move(self):
        """A short stale path that is entirely consumed below the guard limit
        returns (False, None) so the caller replans; behavior is unchanged by
        the fix and is pinned here for coverage."""
        tiles = [_make_tile(x, 30, army=1, player=0) for x in range(5)]
        _link_line(tiles)
        bot = _build_bot(_build_path(tiles))

        shouldUseMove, move = BotPathingUtils.continue_cur_path(bot, None, set())

        self.assertFalse(shouldUseMove)
        self.assertIsNone(move)


if __name__ == '__main__':
    unittest.main()
