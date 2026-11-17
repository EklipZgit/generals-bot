import typing
import unittest
from dataclasses import dataclass, field
from unittest.mock import patch

import SearchUtils
from BotModules.BotStateQueries import BotStateQueries
from TestBase import TestBase


@dataclass(slots=True)
class _FakeTile:
    x: int
    y: int
    tile_index: int
    player: int = -1
    army: int = 0
    isGeneral: bool = False
    visible: bool = True
    discovered: bool = True


@dataclass(slots=True)
class _FakeStats:
    standingArmy: int


@dataclass(slots=True)
class _FakePlayer:
    index: int
    tiles: typing.List[_FakeTile] = field(default_factory=list)
    dead: bool = False
    aggression_factor: int = 0
    knowsKingLocation: bool = False


@dataclass(slots=True)
class _FakeMap:
    players: typing.List[_FakePlayer]
    generals: typing.List[_FakeTile | None]
    player_index: int
    teammates: typing.Set[int]
    usernames: typing.List[str]

    def get_team_stats(self, playerIndex: int) -> _FakeStats:
        return _FakeStats(sum(t.army for t in self.players[playerIndex].tiles))

    def get_distance_between(self, a: _FakeTile, b: _FakeTile) -> int:
        return abs(a.x - b.x) + abs(a.y - b.y)

    def get_distance_between_or_none(self, a: _FakeTile, b: _FakeTile) -> int | None:
        if not (0 <= a.x < 25 and 0 <= a.y < 26 and 0 <= b.x < 25 and 0 <= b.y < 26):
            return None
        return abs(a.x - b.x) + abs(a.y - b.y)


@dataclass(slots=True)
class _FakeArmyTracker:
    valid_general_positions_by_player: typing.Dict[int, typing.List[_FakeTile]]


@dataclass(slots=True)
class _FakeOpponentTracker:
    riskNow: int
    riskLater: int

    def get_approximate_fog_army_risk(self, playerIndex: int, inTurns: int = 0) -> int:
        return self.riskNow if inTurns == 0 else self.riskLater


@dataclass(slots=True)
class _FakeBot:
    _map: _FakeMap
    general: _FakeTile
    armyTracker: _FakeArmyTracker
    opponent_tracker: _FakeOpponentTracker
    ffa_exclusive_target_lock: int = -1
    targetPlayer: int = -1


@dataclass(slots=True)
class _FakePath:
    length: int
    value: float
    tileList: typing.List[_FakeTile]


def _tile(x: int, y: int, index: int, player: int = -1, army: int = 0, isGeneral: bool = False) -> _FakeTile:
    """Builds a minimal map tile for the typed fake-bot fixture."""
    return _FakeTile(x=x, y=y, tile_index=index, player=player, army=army, isGeneral=isGeneral)


class FfaClearKillTests(TestBase):
    """
    UnitTests for BotStateQueries inferred-general FFA clear-kill evaluation added for
    Tests/test_FFA.py::test_should_snap_kill_nearby_ffa_general_after_enemy_army_loss.
    """
    __slots__ = ()

    def _makeBot(
        self,
        candidates: typing.List[_FakeTile],
        riskNow: int = 1,
        riskLater: int = 0,
        enemyTiles: int = 5,
        knownGeneral: _FakeTile | None = None,
        enemyStandingArmy: int = 10,
    ) -> _FakeBot:
        """Builds the typed fake bot: us (p3) with a 28-stack at (10,4), seen p4, and
        seen p5 whose only valid-general candidates are the supplied tiles."""
        ourGeneral = _tile(13, 0, 0, player=3, army=7, isGeneral=True)
        ourStack = _tile(10, 4, 1, player=3, army=28)
        players = [
            _FakePlayer(index=0),
            _FakePlayer(index=1),
            _FakePlayer(index=2),
            _FakePlayer(index=3, tiles=[ourGeneral, ourStack]),
            _FakePlayer(index=4, tiles=[_tile(20, 20, 40, player=4, army=enemyStandingArmy)] * enemyTiles),
            _FakePlayer(index=5, tiles=[_tile(9, 5, 50, player=5, army=2)] * enemyTiles),
        ]
        generals = [None, None, None, ourGeneral, knownGeneral, None]
        map_ = _FakeMap(
            players=players,
            generals=generals,
            player_index=3,
            teammates=set(),
            usernames=['a', 'b', 'c', 'us', 'd', 'pink'])
        validPositions = {i: (list(candidates) if i == 5 else []) for i in range(8)}
        tracker = _FakeArmyTracker(valid_general_positions_by_player=validPositions)
        opponent = _FakeOpponentTracker(riskNow=riskNow, riskLater=riskLater)
        return _FakeBot(
            _map=map_,
            general=ourGeneral,
            armyTracker=tracker,
            opponent_tracker=opponent)

    def test_compact_viable_inferred_target_is_admitted(self) -> None:
        """p5-like compact region near a real path qualifies as an inferred clear kill."""
        candidates = [_tile(x, y, 100 + y * 10 + x) for x in (6, 7, 8) for y in (4, 5)]
        candidates += [_tile(8, 6, 999), _tile(8, 7, 998)]
        path = _FakePath(length=2, value=24.0, tileList=[_tile(10, 4, 1), _tile(9, 4, 2), _tile(8, 4, 3)])
        bot = self._makeBot(candidates, riskNow=1, riskLater=9)
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=path):
            result = BotStateQueries.get_ffa_clear_kill_enemy_player(bot)
        self.assertEqual(5, result)

    def test_high_projected_defense_rejects_inferred_target(self) -> None:
        """Pre-loss strong p5 (fog risk 50 at hunt turns) must not qualify."""
        candidates = [_tile(x, y, 100 + y * 10 + x) for x in (6, 7, 8) for y in (4, 5)]
        candidates += [_tile(8, 6, 999), _tile(8, 7, 998)]
        path = _FakePath(length=2, value=24.0, tileList=[_tile(10, 4, 1), _tile(9, 4, 2), _tile(8, 4, 3)])
        bot = self._makeBot(candidates, riskNow=1, riskLater=50)
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=path):
            result = BotStateQueries.get_ffa_clear_kill_enemy_player(bot)
        self.assertEqual(-1, result)

    def test_no_local_stack_rejects_inferred_target(self) -> None:
        """Without a friendly stack >5 near the region, no inferred kill."""
        candidates = [_tile(20, 20, 300), _tile(21, 20, 301)]
        path = _FakePath(length=2, value=24.0, tileList=[_tile(19, 20, 1), _tile(20, 20, 2)])
        bot = self._makeBot(candidates)
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=path):
            result = BotStateQueries._eval_inferred_general_clear_kill(bot, 5)
        self.assertIsNone(result)

    def test_no_reachable_path_rejects_inferred_target(self) -> None:
        """DBFT returning no path means no viable inferred kill."""
        candidates = [_tile(6, 4, 100), _tile(7, 4, 101)]
        bot = self._makeBot(candidates)
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=None):
            result = BotStateQueries._eval_inferred_general_clear_kill(bot, 5)
        self.assertIsNone(result)

    def test_too_many_candidates_rejects_inferred_target(self) -> None:
        """A >12-tile valid-general region is too speculative to qualify."""
        candidates = [_tile(x, y, 400 + y * 30 + x) for y in range(5) for x in range(3)]
        path = _FakePath(length=2, value=24.0, tileList=[_tile(10, 4, 1), _tile(9, 4, 2), _tile(8, 4, 3)])
        bot = self._makeBot(candidates[:13])
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=path):
            result = BotStateQueries._eval_inferred_general_clear_kill(bot, 5)
        self.assertIsNone(result)

    def test_dispersed_region_beyond_hunt_budget_rejects(self) -> None:
        """Candidates too far off the path push huntTurns past 10 -> reject."""
        candidates = [_tile(6, 4, 100), _tile(8, 7, 101), _tile(6, 20, 102)]
        path = _FakePath(length=2, value=24.0, tileList=[_tile(10, 4, 1), _tile(9, 4, 2), _tile(8, 4, 3)])
        bot = self._makeBot(candidates)
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=path):
            result = BotStateQueries._eval_inferred_general_clear_kill(bot, 5)
        self.assertIsNone(result)

    def test_known_general_branch_keeps_priority_over_inferred(self) -> None:
        """A seen enemy with a known general and army advantage wins over inferred p5."""
        candidates = [_tile(x, y, 100 + y * 10 + x) for x in (6, 7, 8) for y in (4, 5)]
        candidates += [_tile(8, 6, 999), _tile(8, 7, 998)]
        path = _FakePath(length=2, value=24.0, tileList=[_tile(10, 4, 1), _tile(9, 4, 2), _tile(8, 4, 3)])
        knownGen = _tile(18, 4, 200, player=4, army=1, isGeneral=True)
        bot = self._makeBot(candidates, knownGeneral=knownGen, enemyStandingArmy=2)
        with patch.object(SearchUtils, 'dest_breadth_first_target', return_value=path):
            result = BotStateQueries.get_ffa_clear_kill_enemy_player(bot)
        self.assertEqual(4, result)

    def test_sticky_attacker_lock_is_preserved(self) -> None:
        """An existing exclusive lock is not re-evaluated while the player lives."""
        bot = self._makeBot([])
        bot.ffa_exclusive_target_lock = 4
        bot._map.players[4].dead = False
        with patch.object(BotStateQueries, 'is_ffa_exclusive_targeting_active', return_value=True), \
                patch.object(BotStateQueries, 'get_ffa_clear_kill_enemy_player') as clearKill:
            BotStateQueries.update_ffa_exclusive_target_lock(bot)
        self.assertEqual(4, bot.ffa_exclusive_target_lock)
        clearKill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
