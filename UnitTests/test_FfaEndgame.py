import math
import typing
import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import patch

import Gather
import SearchUtils
from BotModules import BotFfaEndgame
from BotModules.BotFfaEndgame import FfaEndgameDecision, FfaEndgameMode, FfaEndgameState, FfaGeneralReserve
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotTargeting import BotTargeting
from BotModules.BotTimings import BotTimings
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotCityOps import BotCityOps
from BotModules.BotCombatOps import BotCombatOps
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotStealthAllIn import BotStealthAllIn
from bot_ek0x45 import EklipZBot
from DangerAnalyzer import ThreatType
from Models.Move import Move
from base.client.map import Score


@dataclass(slots=True, eq=False)
class _FakeTile:
    x: int
    y: int
    player: int = -1
    isGeneral: bool = False
    army: int = 0
    tile_index: int = 0
    visible: bool = True
    discovered: bool = True
    isCity: bool = False
    isPathable: bool = True
    isObstacle: bool = False
    movable: typing.List['_FakeTile'] = field(default_factory=list)


@dataclass(slots=True)
class _FakePlayer:
    index: int
    tileCount: int = 0
    cityCount: int = 1
    standingArmy: int = 0
    dead: bool = False
    leftGame: bool = False
    capturedBy: int | None = None
    has_kill: bool | None = None
    aggression_factor: int = 0
    tiles: typing.List[_FakeTile] = field(default_factory=list)


@dataclass(slots=True)
class _FakeMap:
    players: typing.List[_FakePlayer]
    is_2v2: bool = False
    teammates: typing.Set[int] = field(default_factory=set)
    team_ids_by_player_index: typing.List[int] = field(default_factory=list)
    generals: typing.List[_FakeTile | None] = field(default_factory=list)
    turn: int = 100
    player_index: int = 0
    remainingPlayers: int = 3
    tiles: typing.List[_FakeTile] = field(default_factory=list)
    usernames: typing.List[str] = field(default_factory=list)

    def euclidDist(self, x: float, y: float, x2: float, y2: float) -> float:
        return math.hypot(x - x2, y - y2)

    def get_all_tiles(self) -> typing.Iterator[_FakeTile]:
        return iter(self.tiles)

    def is_tile_on_team_with(self, tile: _FakeTile, playerIndex: int) -> bool:
        return tile.player == playerIndex


@dataclass(slots=True)
class _FakePathTail:
    tile: _FakeTile


@dataclass(slots=True)
class _FakePath:
    tail: _FakePathTail
    length: int = 1
    start: object | None = None


@dataclass(slots=True)
class _FakeThreatObj:
    threatType: object
    threatPlayer: int
    path: _FakePath


@dataclass(slots=True)
class _FakeGatherPlan:
    firstMove: object | None
    root_nodes: typing.List[object] = field(default_factory=list)

    def get_first_move(self):
        return self.firstMove


@dataclass(slots=True)
class _FakeStealthState:
    committed_route: object | None = None
    is_undefendable_hunt: bool = False
    launch_tile: object | None = None


@dataclass(slots=True)
class _FakeMove:
    source: _FakeTile
    dest: _FakeTile


@dataclass(slots=True)
class _FakeViewInfo:
    """Typed ViewInfo double recording the FFA3 reserve info/stats lines."""
    info_lines: typing.List[str] = field(default_factory=list)
    stats_lines: typing.List[str] = field(default_factory=list)

    def add_info_line(self, line: str) -> None:
        self.info_lines.append(line)

    def add_stats_line(self, line: str) -> None:
        self.stats_lines.append(line)


@dataclass(slots=True)
class _FakeDistanceMap:
    """Distance-map double for update_general_reserve: per-tile BFS distance, 1000 = unreachable."""
    dist: typing.Dict[_FakeTile, int] = field(default_factory=dict)

    def __getitem__(self, tile: _FakeTile) -> int:
        return self.dist.get(tile, 1000)


class FfaEndgameTests(unittest.TestCase):
    """
    UnitTests for BotModules/BotFfaEndgame.py covering the 3-player solo-FFA endgame
    policy: economy dominance, weaker-player all-in, turtle-after-kill, retaliation,
    unattackable restriction, and txtmap serialization of the retaliation target.
    """
    __slots__ = ()

    def _econ(self, tileCount: int, cityCount: int = 1) -> int:
        return tileCount + 25 * cityCount

    def _makeBot(
            self,
            players: typing.List[_FakePlayer],
            selfIndex: int = 0,
            generalPos: typing.Tuple[int, int] = (20, 20),
            enemyGenerals: typing.Dict[int, _FakeTile] | None = None,
            mapTiles: typing.List[_FakeTile] | None = None,
            is2v2: bool = False,
            teammates: typing.Set[int] | None = None,
            teams: typing.List[int] | None = None,
            turn: int = 100) -> EklipZBot:
        """Builds a real EklipZBot shell with typed fakes for map/players/tiles."""
        bot = EklipZBot()
        ourGeneral = _FakeTile(x=generalPos[0], y=generalPos[1], player=selfIndex, isGeneral=True, army=30)
        generals: typing.List[_FakeTile | None] = [None] * len(players)
        generals[selfIndex] = ourGeneral
        if enemyGenerals is not None:
            for idx, tile in enemyGenerals.items():
                generals[idx] = tile
        map_ = _FakeMap(
            players=players,
            is_2v2=is2v2,
            teammates=teammates if teammates is not None else set(),
            team_ids_by_player_index=teams if teams is not None else list(range(len(players))),
            generals=generals,
            turn=turn,
            player_index=selfIndex,
            tiles=mapTiles if mapTiles is not None else [],
            usernames=[f'p{i}' for i in range(len(players))])
        bot._map = map_
        bot.general = ourGeneral
        bot.viewInfo = _FakeViewInfo()
        bot.generalApproximations = [[float(generalPos[0]), float(generalPos[1]), 1, None] for _ in players]
        bot.ffa_exclusive_target_lock = -1
        bot.dangerAnalyzer = SimpleNamespace(fastestThreat=None)
        bot.shortest_path_to_target_player = None
        bot.cityAnalyzer = None
        # retaliation target sync calls the real target-reset/path seams; unit tests stub them so
        # the policy can be exercised without a full map/recorder. Tests that assert the sync
        # override these with recording versions.
        bot.opponent_tracker = SimpleNamespace(targetPlayer=-1)
        bot.recalculate_player_paths = lambda force=False: None
        bot._reset_all_in_state_after_target_player_change = lambda oldTarget, newTarget: None
        return bot

    def _threePlayerSet(
            self,
            ourEconTiles: int,
            ourCities: int,
            e1EconTiles: int,
            e1Cities: int,
            e2EconTiles: int,
            e2Cities: int,
            **kwargs) -> EklipZBot:
        """us(p0) vs e1(p1) vs e2(p2), all living, solo FFA teams."""
        players = [
            _FakePlayer(index=0, tileCount=ourEconTiles, cityCount=ourCities, standingArmy=30),
            _FakePlayer(index=1, tileCount=e1EconTiles, cityCount=e1Cities, standingArmy=10),
            _FakePlayer(index=2, tileCount=e2EconTiles, cityCount=e2Cities, standingArmy=20),
        ]
        return self._makeBot(players, **kwargs)

    def _gen(self, x: int, y: int, player: int) -> _FakeTile:
        return _FakeTile(x=x, y=y, player=player, isGeneral=True, army=1)

    # ---------- mode selection ----------

    def test_economy_when_own_above_combined_enemy_economy(self) -> None:
        """own econ > e1+e2 => ECONOMY, no forced target, no all-in flag."""
        bot = self._threePlayerSet(200, 4, 50, 1, 60, 1)  # 300 vs 75+85=160
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ECONOMY, decision.mode)
        self.assertEqual(-1, decision.target_player)
        self.assertFalse(bot.is_all_in_losing)
        self.assertFalse(BotFfaEndgame.is_forced_all_in(bot))

    def test_all_in_middle_closest_general_when_no_aggressor_or_lock(self) -> None:
        """own > each but <= sum => ALL_IN; no lock/aggressor => closest known general."""
        bot = self._threePlayerSet(150, 2, 50, 1, 100, 1, enemyGenerals={1: self._gen(5, 5, 1), 2: self._gen(19, 19, 2)})
        # us=200, e1=75, e2=125 -> own>each, own<=sum(200)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ALL_IN, decision.mode)
        self.assertEqual('all_in_middle', decision.reason)
        self.assertEqual(2, decision.target_player)  # (19,19) is closer to our (20,20) gen than (5,5)
        self.assertTrue(bot.is_all_in_losing)
        self.assertTrue(BotFfaEndgame.is_forced_all_in(bot))

    def test_all_in_middle_prefers_serious_aggressor_over_closest(self) -> None:
        """aggressor >120 beats a closer passive enemy for the rule-2 target."""
        players = [
            _FakePlayer(index=0, tileCount=150, cityCount=2, standingArmy=30),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10, aggression_factor=130),
            _FakePlayer(index=2, tileCount=100, cityCount=1, standingArmy=20),
        ]
        bot = self._makeBot(players, enemyGenerals={1: self._gen(5, 5, 1), 2: self._gen(19, 19, 2)})
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        self.assertEqual(1, bot.ffa_endgame.decision.target_player)

    def test_all_in_middle_prefers_live_exclusive_lock(self) -> None:
        """a live exclusive lock is preferred for the rule-2 target."""
        bot = self._threePlayerSet(150, 2, 50, 1, 100, 1, enemyGenerals={1: self._gen(5, 5, 1), 2: self._gen(19, 19, 2)})
        bot.ffa_exclusive_target_lock = 1
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(1, bot.ffa_endgame.decision.target_player)

    def test_all_in_weaker_despite_strong_aggressor_and_old_lock(self) -> None:
        """own > one but not both => ALL_IN the weaker enemy even vs aggressor/old lock."""
        players = [
            _FakePlayer(index=0, tileCount=97, cityCount=3, standingArmy=30),   # econ 172
            _FakePlayer(index=1, tileCount=74, cityCount=1, standingArmy=5, aggression_factor=200),  # econ 99 (weaker)
            _FakePlayer(index=2, tileCount=167, cityCount=10, standingArmy=140),  # econ 417 (stronger)
        ]
        bot = self._makeBot(players, enemyGenerals={1: self._gen(1, 5, 1), 2: self._gen(8, 13, 2)})
        bot.ffa_exclusive_target_lock = 2
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ALL_IN, decision.mode)
        self.assertEqual('all_in_weaker', decision.reason)
        self.assertEqual(1, decision.target_player)
        self.assertTrue(bot.is_all_in_losing)

    def test_turtle_when_smallest_with_direct_kill(self) -> None:
        """own <= both and we hold a direct kill (dead player's capturedBy == us) => TURTLE."""
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
            _FakePlayer(index=3, tileCount=0, cityCount=1, standingArmy=0, dead=True, capturedBy=0),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.TURTLE, decision.mode)
        self.assertEqual(-1, decision.target_player)
        self.assertFalse(bot.is_all_in_losing)
        self.assertTrue(BotStateQueries.is_still_ffa_and_non_dominant(bot))

    def test_all_in_weakest_when_smallest_without_kill(self) -> None:
        """own <= both with no direct kill => ALL_IN the weaker enemy (conservative)."""
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ALL_IN, decision.mode)
        self.assertEqual('all_in_weakest', decision.reason)
        self.assertEqual(1, decision.target_player)

    # ---------- credited-kill (authoritative has_kill) ----------

    def test_turtle_after_credited_kill_without_captured_by(self) -> None:
        """authoritative has_kill=True with NO capturedBy evidence => TURTLE (surrender/left kill)."""
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30, has_kill=True),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.TURTLE, decision.mode)
        self.assertEqual('turtle_after_credited_kill', decision.reason)
        self.assertEqual(-1, decision.target_player)

    def test_explicit_has_kill_false_ignores_stale_direct_kill(self) -> None:
        """authoritative has_kill=False must NOT be overridden by a stale capturedBy record."""
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30, has_kill=False),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
            _FakePlayer(index=3, tileCount=0, cityCount=1, standingArmy=0, dead=True, capturedBy=0),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ALL_IN, decision.mode)
        self.assertEqual('all_in_weakest', decision.reason)
        self.assertEqual(1, decision.target_player)

    def test_omitted_has_kill_falls_back_to_legacy_direct_kill(self) -> None:
        """has_kill=None (SilentWar/legacy payload) keeps the capturedBy fallback => TURTLE."""
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30, has_kill=None),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
            _FakePlayer(index=3, tileCount=0, cityCount=1, standingArmy=0, dead=True, capturedBy=0),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.TURTLE, decision.mode)
        self.assertEqual('turtle_after_credited_kill', decision.reason)

    def test_has_kill_true_to_false_transition_releases_turtle(self) -> None:
        """a later authoritative has_kill=False releases TURTLE back to weakest all-in."""
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30, has_kill=True),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)
        bot._map.players[0].has_kill = False
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ALL_IN, decision.mode)
        self.assertEqual(1, decision.target_player)

    def test_score_from_server_scores_parses_has_kill_three_valued(self) -> None:
        """leaderboard scores keep has_kill True/False and leave omitted fields None (unknown)."""
        entries = [
            {'i': 0, 'total': 10, 'tiles': 5, 'dead': False, 'has_kill': True},
            {'i': 1, 'total': 8, 'tiles': 4, 'dead': False},
            {'i': 2, 'total': 6, 'tiles': 3, 'dead': True, 'has_kill': False},
        ]
        scores = Score.from_server_scores(entries)
        self.assertIs(True, scores[0].has_kill)
        self.assertIsNone(scores[1].has_kill)
        self.assertIs(False, scores[2].has_kill)

    def test_sum_equality_is_not_dominant(self) -> None:
        """own == e1+e2 must not claim ECONOMY; falls into the all-in rules."""
        bot = self._threePlayerSet(150, 2, 50, 1, 100, 1)  # us=200, e1=75, e2=125, sum=200
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)

    def test_individual_equality_is_conservative_all_in(self) -> None:
        """own == one enemy individually is not 'own > at least one' => weaker all-in."""
        players = [
            _FakePlayer(index=0, tileCount=50, cityCount=1, standingArmy=30),   # econ 75
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),   # econ 75 (tie)
            _FakePlayer(index=2, tileCount=150, cityCount=1, standingArmy=20),  # econ 175
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.ALL_IN, decision.mode)
        self.assertEqual(1, decision.target_player)  # weaker-by-economy tie -> army -> distance -> index

    # ---------- context gating ----------

    def test_dead_players_excluded_from_living_count(self) -> None:
        """a dead fourth player does not break the 3-player context."""
        players = [
            _FakePlayer(index=0, tileCount=97, cityCount=3, standingArmy=30),
            _FakePlayer(index=1, tileCount=74, cityCount=1, standingArmy=5),
            _FakePlayer(index=2, tileCount=167, cityCount=10, standingArmy=140),
            _FakePlayer(index=3, tileCount=500, cityCount=10, standingArmy=999, dead=True),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        self.assertEqual(1, bot.ffa_endgame.decision.target_player)

    def test_four_living_players_is_inactive(self) -> None:
        """more than two living enemies => policy inactive."""
        players = [
            _FakePlayer(index=0, tileCount=97, cityCount=3, standingArmy=30),
            _FakePlayer(index=1, tileCount=74, cityCount=1, standingArmy=5),
            _FakePlayer(index=2, tileCount=167, cityCount=10, standingArmy=140),
            _FakePlayer(index=3, tileCount=10, cityCount=1, standingArmy=1),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.INACTIVE, bot.ffa_endgame.decision.mode)

    def test_afk_and_unseen_enemies_still_count(self) -> None:
        """leftGame/unseen (zero-tile) enemies are not excluded from the 3-player count."""
        players = [
            _FakePlayer(index=0, tileCount=97, cityCount=3, standingArmy=30),
            _FakePlayer(index=1, tileCount=74, cityCount=1, standingArmy=5, leftGame=True, tiles=[]),
            _FakePlayer(index=2, tileCount=167, cityCount=10, standingArmy=140, tiles=[]),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        self.assertEqual(1, bot.ffa_endgame.decision.target_player)

    def test_2v2_and_shared_enemy_teams_are_inactive(self) -> None:
        """2v2 flag or enemies sharing a team disable the solo-FFA policy."""
        players = [
            _FakePlayer(index=0, tileCount=97, cityCount=3, standingArmy=30),
            _FakePlayer(index=1, tileCount=74, cityCount=1, standingArmy=5),
            _FakePlayer(index=2, tileCount=167, cityCount=10, standingArmy=140),
        ]
        bot = self._makeBot(players, is2v2=True)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.INACTIVE, bot.ffa_endgame.decision.mode)

        bot2 = self._makeBot(players, teams=[0, 1, 1])
        BotFfaEndgame.update_policy(bot2)
        self.assertEqual(FfaEndgameMode.INACTIVE, bot2.ffa_endgame.decision.mode)

        bot3 = self._makeBot(players, teammates={2})
        BotFfaEndgame.update_policy(bot3)
        self.assertEqual(FfaEndgameMode.INACTIVE, bot3.ffa_endgame.decision.mode)

    def test_single_enemy_is_inactive(self) -> None:
        """a 1v1 (only one living enemy) never engages the 3-player policy."""
        players = [
            _FakePlayer(index=0, tileCount=97, cityCount=3, standingArmy=30),
            _FakePlayer(index=1, tileCount=74, cityCount=1, standingArmy=5),
            _FakePlayer(index=2, tileCount=0, cityCount=1, standingArmy=0, dead=True),
        ]
        bot = self._makeBot(players)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.INACTIVE, bot.ffa_endgame.decision.mode)

    # ---------- retaliation ----------

    def _turtleBot(self, aggressorFactor: int = 0) -> EklipZBot:
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10, aggression_factor=aggressorFactor),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
            _FakePlayer(index=3, tileCount=0, cityCount=1, standingArmy=0, dead=True, capturedBy=0),
        ]
        return self._makeBot(players)

    def test_turtle_escalates_to_retaliate_on_serious_aggressor(self) -> None:
        """TURTLE + enemy aggression_factor > 120 => RETALIATE latched on that enemy."""
        bot = self._turtleBot(aggressorFactor=130)
        BotFfaEndgame.update_policy(bot)
        decision = bot.ffa_endgame.decision
        self.assertEqual(FfaEndgameMode.RETALIATE, decision.mode)
        self.assertEqual(1, decision.target_player)
        self.assertEqual(1, bot.ffa_endgame.retaliation_target)
        self.assertTrue(bot.is_all_in_losing)
        self.assertTrue(BotFfaEndgame.is_retaliating(bot))
        self.assertFalse(BotStateQueries.is_still_ffa_and_non_dominant(bot))

    def test_turtle_stays_turtle_below_aggression_threshold(self) -> None:
        """aggression_factor <= 120 does not escalate TURTLE."""
        bot = self._turtleBot(aggressorFactor=120)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)
        self.assertEqual(-1, bot.ffa_endgame.retaliation_target)

    def _killThreat(self, aggressor: int, ourGeneral: _FakeTile) -> _FakeThreatObj:
        return _FakeThreatObj(
            threatType=ThreatType.Kill,
            threatPlayer=aggressor,
            path=_FakePath(tail=_FakePathTail(tile=ourGeneral)))

    def test_turtle_escalates_on_true_general_kill_threat(self) -> None:
        """a concrete ThreatType.Kill whose path tail is OUR general escalates TURTLE."""
        bot = self._turtleBot()
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)
        bot.dangerAnalyzer.fastestThreat = self._killThreat(1, bot.general)
        # orchestrator regression: the retaliation sync must retarget the live bot state to the
        # offender (targetPlayer/targetPlayerObj/opponent_tracker) via the real reset/recalc seams
        # before any attack helper runs on the same turn.
        resetCalls: typing.List[typing.Tuple[int, int]] = []
        recalcCalls: typing.List[bool] = []
        bot._reset_all_in_state_after_target_player_change = lambda old, new: resetCalls.append((old, new))
        bot.recalculate_player_paths = lambda force=False: recalcCalls.append(force)
        BotFfaEndgame.update_retaliation(bot)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)
        self.assertEqual(1, bot.ffa_endgame.retaliation_target)
        self.assertTrue(bot.is_all_in_losing)
        self.assertEqual(1, bot.targetPlayer)
        self.assertEqual(1, bot.targetPlayerObj.index)
        self.assertEqual(1, bot.opponent_tracker.targetPlayer)
        self.assertEqual([(-1, 1)], resetCalls)
        self.assertEqual([True], recalcCalls)

    def test_turtle_does_not_escalate_on_vision_or_non_general_threats(self) -> None:
        """Vision threats and Kill threats not ending on our general must not escalate."""
        bot = self._turtleBot()
        BotFfaEndgame.update_policy(bot)
        enemyGen = self._gen(5, 5, 1)
        bot.dangerAnalyzer.fastestThreat = _FakeThreatObj(
            threatType=ThreatType.Vision, threatPlayer=1,
            path=_FakePath(tail=_FakePathTail(tile=bot.general)))
        BotFfaEndgame.update_retaliation(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)

        bot.dangerAnalyzer.fastestThreat = _FakeThreatObj(
            threatType=ThreatType.Kill, threatPlayer=1,
            path=_FakePath(tail=_FakePathTail(tile=enemyGen)))
        BotFfaEndgame.update_retaliation(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)

        bot.dangerAnalyzer.fastestThreat = _FakeThreatObj(
            threatType=ThreatType.Kill, threatPlayer=1,
            path=_FakePath(tail=_FakePathTail(tile=_FakeTile(x=20, y=20, player=1, isGeneral=False))))
        BotFfaEndgame.update_retaliation(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)

    def test_retaliation_latches_after_aggression_decays(self) -> None:
        """once latched, RETALIATE persists even when aggression_factor decays."""
        bot = self._turtleBot(aggressorFactor=130)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)
        bot._map.players[1].aggression_factor = 0
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)
        self.assertEqual(1, bot.ffa_endgame.decision.target_player)
        self.assertEqual(1, bot.ffa_endgame.retaliation_target)

    def test_retaliation_clears_on_target_death_and_on_1v1(self) -> None:
        """retaliation_target clears when the offender dies or the game leaves 3-player."""
        bot = self._turtleBot(aggressorFactor=130)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)
        bot._map.players[1].dead = True
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(-1, bot.ffa_endgame.retaliation_target)
        self.assertNotEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)

        bot2 = self._turtleBot(aggressorFactor=130)
        BotFfaEndgame.update_policy(bot2)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot2.ffa_endgame.decision.mode)
        bot2._map.players[2].dead = True  # only one enemy left => 1v1
        BotFfaEndgame.update_policy(bot2)
        self.assertEqual(FfaEndgameMode.INACTIVE, bot2.ffa_endgame.decision.mode)
        self.assertEqual(-1, bot2.ffa_endgame.retaliation_target)

    def test_retaliation_target_serialization_round_trip(self) -> None:
        """save_state->load_state->update_policy preserves the latched target across a real
        serialization round trip; old fixtures without the keys default to -1/empty."""
        bot = self._turtleBot(aggressorFactor=130)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)
        self.assertEqual(1, bot.ffa_endgame.retaliation_target)
        data = BotFfaEndgame.save_state(bot)
        self.assertEqual('1', data['bot_ffa_endgame_retaliation_target'])

        bot2 = self._turtleBot()
        BotFfaEndgame.load_state(bot2, data)
        self.assertEqual(1, bot2.ffa_endgame.retaliation_target)
        BotFfaEndgame.update_policy(bot2)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot2.ffa_endgame.decision.mode)
        self.assertEqual(1, bot2.ffa_endgame.decision.target_player)

        bot3 = self._turtleBot()
        BotFfaEndgame.load_state(bot3, {})
        self.assertEqual(-1, bot3.ffa_endgame.retaliation_target)
        self.assertEqual(frozenset(), bot3.ffa_endgame.direct_kill_targets)

    def test_direct_kill_history_survives_txtmap_import(self) -> None:
        """a serialized direct kill keeps TURTLE after capturedBy is lost on txtmap import."""
        bot = self._turtleBot()
        data = BotFfaEndgame.save_state(bot)
        self.assertEqual('3', data['bot_ffa_endgame_direct_kill_targets'])
        bot2 = self._turtleBot()
        bot2._map.players[3].capturedBy = None  # txtmap import drops runtime capturedBy
        BotFfaEndgame.load_state(bot2, data)
        BotFfaEndgame.update_policy(bot2)
        self.assertEqual(FfaEndgameMode.TURTLE, bot2.ffa_endgame.decision.mode)

    # ---------- unattackable restriction ----------

    def test_unattackable_players_restricts_to_policy_target(self) -> None:
        """ALL_IN makes every non-target enemy unattackable, including unseen players."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        unattackable = BotStateQueries.get_ffa_unattackable_players(bot)
        self.assertIsNotNone(unattackable)
        self.assertEqual({2}, unattackable)  # p1 is the weaker target, p2 (leader) is unattackable

    def test_unattackable_players_turtle_blocks_both_enemies(self) -> None:
        """TURTLE makes both living enemies unattackable."""
        bot = self._turtleBot()
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)
        unattackable = BotStateQueries.get_ffa_unattackable_players(bot)
        self.assertIsNotNone(unattackable)
        self.assertEqual({1, 2}, unattackable)

    # ---------- targeting / all-in gates ----------

    def test_calculate_target_player_returns_policy_decision(self) -> None:
        """calculate_target_player early-returns the forced target / -1 for TURTLE."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(1, BotTargeting.calculate_target_player(bot))

        turtleBot = self._turtleBot()
        BotFfaEndgame.update_policy(turtleBot)
        self.assertEqual(-1, BotTargeting.calculate_target_player(turtleBot))

    def test_check_should_be_all_in_losing_respects_policy(self) -> None:
        """forced ALL_IN re-asserts the flag past the target==-1 gate; TURTLE suppresses."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        bot.targetPlayer = -1  # policy must override even this gate
        self.assertTrue(BotCombatOps.check_should_be_all_in_losing(bot))
        self.assertTrue(bot.is_all_in_losing)

        turtleBot = self._turtleBot()
        BotFfaEndgame.update_policy(turtleBot)
        turtleBot.is_all_in_losing = True
        self.assertFalse(BotCombatOps.check_should_be_all_in_losing(turtleBot))
        self.assertFalse(turtleBot.is_all_in_losing)

    def test_cyclic_winning_gather_viable_false_under_forced_all_in(self) -> None:
        """the target-only cyclic winning gather must not defer a forced all-in."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertFalse(BotStateQueries.is_cyclic_winning_gather_viable(bot))

    def test_determine_should_winning_all_in_suppressed_during_city_priority(self) -> None:
        """army-advantage all-in stays disabled while ECONOMY prioritizes a neutral city."""
        bot = self._threePlayerSet(200, 4, 50, 1, 60, 1)
        bot.ffa_endgame = FfaEndgameState(decision=FfaEndgameDecision(
            mode=FfaEndgameMode.ECONOMY, target_player=-1, our_economy=300,
            enemy_economy_total=160, reason='economy_dominant', prioritizing_neutral_city=True))
        self.assertFalse(BotCombatOps.determine_should_winning_all_in(bot))
        self.assertTrue(BotFfaEndgame.is_prioritizing_neutral_city(bot))

    def test_economy_city_priority_flag_from_policy(self) -> None:
        """update_policy marks prioritizing_neutral_city when a reachable neutral city exists."""
        bot = self._threePlayerSet(200, 4, 50, 1, 60, 1)
        bot.shortest_path_to_target_player = object()
        bot.cityAnalyzer = object()
        with patch.object(BotCityOps, 'find_neutral_city_path', return_value=object()) as findPath:
            BotFfaEndgame.update_policy(bot)
        findPath.assert_called_once_with(bot)
        self.assertTrue(bot.ffa_endgame.decision.prioritizing_neutral_city)

    # ---------- retarget plan clearing ----------

    def test_retarget_aborts_committed_stealth_route_and_clears_curpath(self) -> None:
        """a policy retarget discards the old target's committed stealth route + curPath."""
        bot = self._threePlayerSet(150, 2, 50, 1, 100, 1, enemyGenerals={1: self._gen(5, 5, 1), 2: self._gen(19, 19, 2)})
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(2, bot.ffa_endgame.decision.target_player)
        bot.stealth_all_in = _FakeStealthState(committed_route=object())
        bot.curPath = object()
        bot.curPathPrio = 3
        # retarget: shift economies and general positions so the policy picks p1 instead of p2.
        bot._map.players[1].tileCount = 120  # e1 econ 145
        bot._map.players[2].tileCount = 40   # e2 econ 65
        bot._map.generals[1] = self._gen(19, 19, 1)
        bot._map.generals[2] = self._gen(5, 5, 2)
        BotFfaEndgame.update_policy(bot)
        newTarget = bot.ffa_endgame.decision.target_player
        self.assertNotEqual(2, newTarget)
        self.assertIsNone(bot.stealth_all_in)
        self.assertIsNone(bot.curPath)
        self.assertEqual(-1, bot.curPathPrio)

    # ---------- get_move: TURTLE ----------

    def _turtleMoveBot(self) -> typing.Tuple[EklipZBot, _FakeGatherPlan, dict, typing.Callable, object]:
        players = [
            _FakePlayer(index=0, tileCount=25, cityCount=1, standingArmy=30),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10),
            _FakePlayer(index=2, tileCount=100, cityCount=2, standingArmy=20),
            _FakePlayer(index=3, tileCount=0, cityCount=1, standingArmy=0, dead=True, capturedBy=0),
        ]
        ourTile = _FakeTile(x=20, y=20, player=0, army=5)
        enemyTile = _FakeTile(x=5, y=5, player=1, army=9)
        neutralTile = _FakeTile(x=10, y=10, player=-1, army=4)
        otherEnemyTile = _FakeTile(x=15, y=15, player=2, army=7)
        bot = self._makeBot(players, mapTiles=[ourTile, enemyTile, neutralTile, otherEnemyTile])
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.TURTLE, bot.ffa_endgame.decision.mode)
        sentinelMove = object()
        plan = _FakeGatherPlan(firstMove=sentinelMove, root_nodes=[object()])
        captured: dict = {}

        def fakeGather(map_, **kwargs):
            captured.update(kwargs)
            return plan

        return bot, plan, captured, fakeGather, sentinelMove

    def test_turtle_get_move_is_owned_only_gather_to_general(self) -> None:
        """TURTLE gathers only through player-owned tiles toward our general."""
        bot, plan, captured, fakeGather, sentinelMove = self._turtleMoveBot()
        with patch.object(Gather, 'gather_approximate_turns_to_tiles', side_effect=fakeGather), \
                patch.object(BotGatherOps, 'get_gather_tiebreak_matrix', return_value=None), \
                patch.object(BotTimings, 'get_remaining_move_time', return_value=1.0):
            move = BotFfaEndgame.get_move(bot)
        self.assertIs(sentinelMove, move)
        self.assertIs(plan, bot.curPath)
        self.assertEqual([bot.general], captured['rootTiles'])
        self.assertEqual(50, captured['approximateTargetTurns'])
        self.assertIsNone(captured['captureMatrix'])
        self.assertFalse(captured['prioritizeCaptureHighArmyTiles'])
        self.assertFalse(captured['includeCapturePriorityAsEconValues'])
        skipTiles = captured['skipTiles']
        for tile in bot._map.tiles:
            if tile.player == 0:
                self.assertNotIn(tile, skipTiles, f'own tile {tile.x},{tile.y} must not be skipped')
            else:
                self.assertIn(tile, skipTiles, f'non-owned tile {tile.x},{tile.y} must be skipped')

    def test_turtle_get_move_never_invokes_attack_or_econ_helpers(self) -> None:
        """TURTLE move selection cannot call city capture or attack helpers."""
        bot, plan, captured, fakeGather, sentinelMove = self._turtleMoveBot()
        with patch.object(Gather, 'gather_approximate_turns_to_tiles', side_effect=fakeGather), \
                patch.object(BotGatherOps, 'get_gather_tiebreak_matrix', return_value=None), \
                patch.object(BotTimings, 'get_remaining_move_time', return_value=1.0), \
                patch.object(BotCityOps, 'capture_cities', side_effect=AssertionError('econ invoked')), \
                patch.object(BotCombatOps, 'get_all_in_move', side_effect=AssertionError('attack invoked')), \
                patch.object(BotStealthAllIn, 'get_stealth_all_in_move', side_effect=AssertionError('stealth invoked')):
            move = BotFfaEndgame.get_move(bot)
        self.assertIs(sentinelMove, move)

    def test_turtle_get_move_returns_none_for_deliberate_pass(self) -> None:
        """when the owned-only gather finds no plan, TURTLE passes instead of attacking."""
        bot, plan, captured, fakeGather, sentinelMove = self._turtleMoveBot()
        with patch.object(Gather, 'gather_approximate_turns_to_tiles', return_value=None), \
                patch.object(BotGatherOps, 'get_gather_tiebreak_matrix', return_value=None), \
                patch.object(BotTimings, 'get_remaining_move_time', return_value=1.0):
            self.assertIsNone(BotFfaEndgame.get_move(bot))

    # ---------- get_move: ECONOMY neutral city ----------

    def _economyCityBot(self, prioritizing: bool = True, mapTiles: typing.List[_FakeTile] | None = None) -> EklipZBot:
        bot = self._threePlayerSet(200, 4, 50, 1, 60, 1, mapTiles=mapTiles)
        bot.ffa_endgame = FfaEndgameState(decision=FfaEndgameDecision(
            mode=FfaEndgameMode.ECONOMY, target_player=-1, our_economy=300,
            enemy_economy_total=160, reason='economy_dominant',
            prioritizing_neutral_city=prioritizing))
        return bot

    def test_economy_get_move_returns_capture_cities_move(self) -> None:
        """a ready neutral-city capture move is returned before any gather fallback."""
        bot = self._economyCityBot()
        cityTile = _FakeTile(x=10, y=10, player=-1, isCity=True)
        sentinelMove = _FakeMove(source=bot.general, dest=cityTile)
        with patch.object(BotCityOps, 'capture_cities_with_plan_option', return_value=(None, sentinelMove, None)) as captureCities, \
                patch.object(BotCityOps, 'find_neutral_city_path', side_effect=AssertionError('should not search')):
            move = BotFfaEndgame.get_move(bot)
        self.assertIs(sentinelMove, move)
        captureCities.assert_called_once()
        self.assertEqual(set(), captureCities.call_args[0][1])
        self.assertTrue(captureCities.call_args[1]['forceNeutralCapture'])

    def test_economy_get_move_uses_returned_capture_path(self) -> None:
        """when capture_cities yields a path but no move, its first path move is used."""
        bot = self._economyCityBot()
        cityTile = _FakeTile(x=10, y=10, player=-1, isCity=True)
        sentinelMove = object()
        fakePath = _FakePath(tail=_FakePathTail(tile=cityTile), length=3)
        with patch.object(BotCityOps, 'capture_cities_with_plan_option', return_value=(fakePath, None, None)), \
                patch.object(BotPathingUtils, 'get_first_path_move', return_value=sentinelMove) as firstPathMove:
            move = BotFfaEndgame.get_move(bot)
        self.assertIs(sentinelMove, move)
        firstPathMove.assert_called_once_with(bot, fakePath)

    def test_economy_get_move_gathers_to_city_without_enemy_transit(self) -> None:
        """unready city => gather toward it; enemy tiles are skipped, neutral/own are not."""
        cityTile = _FakeTile(x=10, y=10, player=-1, isCity=True)
        enemyTile = _FakeTile(x=5, y=5, player=1, army=9)
        ourTile = _FakeTile(x=20, y=20, player=0, army=5)
        bot = self._economyCityBot(mapTiles=[cityTile, enemyTile, ourTile])
        neutPath = _FakePath(tail=_FakePathTail(tile=cityTile), length=4)
        sentinelMove = object()
        plan = _FakeGatherPlan(firstMove=sentinelMove)
        captured: dict = {}

        def fakeGather(map_, **kwargs):
            captured.update(kwargs)
            return plan

        with patch.object(BotCityOps, 'capture_cities_with_plan_option', return_value=(None, None, None)), \
                patch.object(BotCityOps, 'find_neutral_city_path', return_value=neutPath), \
                patch.object(Gather, 'gather_approximate_turns_to_tiles', side_effect=fakeGather), \
                patch.object(BotGatherOps, 'get_gather_tiebreak_matrix', return_value=None), \
                patch.object(BotTimings, 'get_remaining_move_time', return_value=1.0):
            move = BotFfaEndgame.get_move(bot)
        self.assertIs(sentinelMove, move)
        self.assertEqual([cityTile], captured['rootTiles'])
        self.assertEqual(4, captured['approximateTargetTurns'])
        self.assertIsNone(captured['captureMatrix'])
        skipTiles = captured['skipTiles']
        self.assertIn(enemyTile, skipTiles)
        self.assertNotIn(cityTile, skipTiles)
        self.assertNotIn(ourTile, skipTiles)

    def test_economy_get_move_returns_none_without_city_or_for_other_modes(self) -> None:
        """no reachable neutral city => None (caller falls through); non-ECONOMY => None."""
        bot = self._economyCityBot()
        with patch.object(BotCityOps, 'capture_cities_with_plan_option', return_value=(None, None, None)), \
                patch.object(BotCityOps, 'find_neutral_city_path', return_value=None):
            self.assertIsNone(BotFfaEndgame.get_move(bot))

        enemyCityPath = _FakePath(tail=_FakePathTail(tile=_FakeTile(x=1, y=1, player=1, isCity=True)), length=3)
        bot2 = self._economyCityBot()
        with patch.object(BotCityOps, 'capture_cities_with_plan_option', return_value=(None, None, None)), \
                patch.object(BotCityOps, 'find_neutral_city_path', return_value=enemyCityPath):
            self.assertIsNone(BotFfaEndgame.get_move(bot2))

        allInBot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(allInBot)
        self.assertIsNone(BotFfaEndgame.get_move(allInBot))

    # ---------- get_retaliate_move / get_attack_move ----------

    def _retaliateBot(self) -> EklipZBot:
        bot = self._turtleBot(aggressorFactor=130)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.RETALIATE, bot.ffa_endgame.decision.mode)
        return bot

    def test_retaliate_move_suppresses_defense_inputs(self) -> None:
        """retaliation calls committed-route/stealth helpers with threat=None and no negs."""
        bot = self._retaliateBot()
        sentinelMove = object()
        capturedArgs: dict = {}

        def fakeCommitted(botArg, threat, defenseTiles, kingKillPath, raceChance):
            capturedArgs['threat'] = threat
            capturedArgs['defenseTiles'] = defenseTiles
            capturedArgs['kingKillPath'] = kingKillPath
            capturedArgs['raceChance'] = raceChance
            return sentinelMove

        with patch.object(BotStealthAllIn, 'get_committed_route_move', side_effect=fakeCommitted):
            move = BotFfaEndgame.get_retaliate_move(
                bot, threat=object(), kingKillPath=object(), raceChance=0.9,
                defenseCriticalTileSet={_FakeTile(x=1, y=1)})
        self.assertIs(sentinelMove, move)
        self.assertIsNone(capturedArgs['threat'])
        self.assertEqual(set(), capturedArgs['defenseTiles'])
        self.assertIsNone(capturedArgs['kingKillPath'])
        self.assertEqual(0.0, capturedArgs['raceChance'])

    def test_retaliate_move_falls_through_attack_helpers_to_gather(self) -> None:
        """with no committed/stealth/curPath plan, retaliation gathers toward the target."""
        bot = self._retaliateBot()
        bot.curPath = None
        targetTile = _FakeTile(x=5, y=5, player=1, isGeneral=True)
        bot.target_player_gather_targets = {targetTile}
        bot.targetPlayerExpectedGeneralLocation = targetTile
        sentinelMove = object()
        plan = _FakeGatherPlan(firstMove=sentinelMove)

        def fakeGather(map_, **kwargs):
            return plan

        with patch.object(BotStealthAllIn, 'get_committed_route_move', return_value=None), \
                patch.object(BotStealthAllIn, 'get_stealth_all_in_move', return_value=None), \
                patch.object(BotPathingUtils, 'continue_cur_path', return_value=(False, None)), \
                patch.object(BotFfaEndgame, '_get_forward_fallback_move', return_value=None), \
                patch.object(BotCombatOps, 'get_all_in_move', return_value=None), \
                patch.object(Gather, 'gather_approximate_turns_to_tiles', side_effect=fakeGather), \
                patch.object(BotGatherOps, 'get_gather_tiebreak_matrix', return_value=None), \
                patch.object(BotTimings, 'get_remaining_move_time', return_value=1.0), \
                patch.object(BotCombatOps, 'get_all_in_hit_general_turns', return_value=10), \
                patch.object(BotCombatOps, '_get_all_in_attack_route_skips', return_value=set()):
            move = BotFfaEndgame.get_retaliate_move(
                bot, threat=None, kingKillPath=None, raceChance=0.0, defenseCriticalTileSet=set())
        self.assertIs(sentinelMove, move)

    def test_attack_move_uses_real_defense_params_and_never_calls_city_ops(self) -> None:
        """ordinary ALL_IN attack keeps lethal-defense params and skips city/econ helpers."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        sentinelMove = object()
        threatObj = object()
        defCrit = {_FakeTile(x=2, y=2)}
        kingKill = object()
        captured: dict = {}

        def fakeAllIn(botArg, defenseTiles):
            captured['defenseTiles'] = defenseTiles
            return sentinelMove

        with patch.object(BotStealthAllIn, 'get_committed_route_move', return_value=None), \
                patch.object(BotStealthAllIn, 'get_stealth_all_in_move', return_value=None), \
                patch.object(BotCombatOps, 'get_all_in_move', side_effect=fakeAllIn), \
                patch.object(BotCityOps, 'capture_cities', side_effect=AssertionError('city invoked')):
            move = BotFfaEndgame.get_attack_move(
                bot, threat=threatObj, defenseCriticalTileSet=defCrit,
                kingKillPath=kingKill, raceChance=0.4)
        self.assertIs(sentinelMove, move)
        self.assertIs(defCrit, captured['defenseTiles'])


    # ---------- general reserve (FfaGeneralReserve / reconcile) ----------

    def _injectReserve(self, bot: EklipZBot, requiredArmy: int) -> None:
        """Caches a synthetic reserve for the current turn so reconcile skips recompute."""
        bot.ffa_endgame.reserve = FfaGeneralReserve(
            required_army=requiredArmy, satisfied=bot.general.army >= requiredArmy)
        bot.ffa_endgame.reserve_turn = bot._map.turn
        bot.viewInfo = _FakeViewInfo()

    def test_update_general_reserve_defaults_for_non_all_in_modes(self) -> None:
        """non-ALL_IN modes reset the reserve to the safe default without map work."""
        for mode in (FfaEndgameMode.INACTIVE, FfaEndgameMode.ECONOMY, FfaEndgameMode.TURTLE):
            bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
            bot.ffa_endgame = FfaEndgameState(decision=FfaEndgameDecision(
                mode=mode, target_player=-1, our_economy=0,
                enemy_economy_total=0, reason='x', prioritizing_neutral_city=False))
            bot.viewInfo = _FakeViewInfo()
            BotFfaEndgame.update_general_reserve(bot)
            reserve = BotFfaEndgame.get_general_reserve(bot)
            self.assertEqual(1, reserve.required_army, mode)
            self.assertTrue(reserve.satisfied, mode)
            self.assertEqual(-1, reserve.non_target_player, mode)
            self.assertEqual(0, reserve.fog_risk, mode)
            self.assertEqual(0, reserve.local_threat, mode)

    def test_update_general_reserve_middle_fog_arithmetic(self) -> None:
        """all_in_middle bounds the non-target's fog inbound army: exact mocked horizon/risk math."""
        players = [
            _FakePlayer(index=0, tileCount=150, cityCount=2, standingArmy=30),
            _FakePlayer(index=1, tileCount=50, cityCount=1, standingArmy=10, aggression_factor=130),
            _FakePlayer(index=2, tileCount=100, cityCount=1, standingArmy=300),
        ]
        bot = self._makeBot(players, enemyGenerals={1: self._gen(19, 19, 1), 2: self._gen(5, 5, 2)})
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        self.assertEqual('all_in_middle', bot.ffa_endgame.decision.reason)
        self.assertEqual(1, bot.ffa_endgame.decision.target_player)  # p1 is the serious aggressor
        bot.general.army = 30
        # non-target p2 frontier tiles at distances 4 and 6 -> horizon = min = 4
        p2a = _FakeTile(x=1, y=1, player=2, army=5)
        p2b = _FakeTile(x=2, y=2, player=2, army=5)
        bot._map.players[2].tiles = [p2a, p2b]
        distMap = _FakeDistanceMap(dist={p2a: 4, p2b: 6})
        fogCalls: typing.List[typing.Tuple[int, int, str]] = []

        def fakeFogRisk(playerIndex: int, inTurns: int, logContext: str) -> int:
            fogCalls.append((playerIndex, inTurns, logContext))
            return 50

        bot.opponent_tracker = SimpleNamespace(
            targetPlayer=-1, get_approximate_fog_army_risk=fakeFogRisk)
        bot.viewInfo = _FakeViewInfo()
        with patch.object(SearchUtils, 'build_distance_map_matrix_with_skip', return_value=distMap):
            BotFfaEndgame.update_general_reserve(bot)
        reserve = BotFfaEndgame.get_general_reserve(bot)
        self.assertEqual(2, reserve.non_target_player)
        self.assertEqual(4, fogCalls[0][1])
        self.assertEqual('ffa_endgame_reserve', fogCalls[0][2])
        self.assertEqual(50, reserve.fog_risk)  # min(50, standingArmy 300 + incomeBound)
        self.assertEqual(0, reserve.local_threat)  # frontier tiles are beyond 2 moves
        # required = fog_risk - horizon - horizon//2 + 1 = 50 - 4 - 2 + 1 = 45
        self.assertEqual(45, reserve.required_army)
        self.assertFalse(reserve.satisfied)  # held 30 < required 45

    def test_general_reserve_nearby_enemy_full_move_becomes_half(self) -> None:
        """general 100 vs an adjacent 7-stack: required>=7 and a full move splits to a half."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual('all_in_weaker', bot.ffa_endgame.decision.reason)
        bot.general.army = 100
        threatTile = _FakeTile(x=21, y=20, player=1, army=7)
        bot._map.tiles = [threatTile]
        distMap = _FakeDistanceMap(dist={threatTile: 1})
        bot.viewInfo = _FakeViewInfo()
        with patch.object(SearchUtils, 'build_distance_map_matrix_with_skip', return_value=distMap):
            BotFfaEndgame.update_general_reserve(bot)
            reserve = BotFfaEndgame.get_general_reserve(bot)
            result = BotFfaEndgame.reconcile_general_reserve_move(
                bot, Move(bot.general, _FakeTile(x=19, y=20, player=-1, army=0)))
        self.assertEqual(-1, reserve.non_target_player)  # all_in_weaker has no fog reserve
        self.assertGreaterEqual(reserve.local_threat, 7)
        self.assertGreaterEqual(reserve.required_army, 7)
        self.assertTrue(reserve.satisfied)  # 100 held >= ~7 required
        self.assertIsNotNone(result)
        self.assertTrue(result.move_half)
        self.assertEqual((100 - 1) // 2, result.army_moved)

    def test_update_general_reserve_caches_within_turn(self) -> None:
        """a same-turn update is a cache hit: the stored reserve is returned untouched."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        sentinel = FfaGeneralReserve(required_army=777, satisfied=False)
        bot.ffa_endgame.reserve = sentinel
        bot.ffa_endgame.reserve_turn = bot._map.turn
        bot.viewInfo = _FakeViewInfo()
        # no distance map is patched: a recompute would crash, so surviving proves the cache hit.
        BotFfaEndgame.update_general_reserve(bot)
        self.assertIs(sentinel, BotFfaEndgame.get_general_reserve(bot))
        self.assertEqual(777, BotFfaEndgame.get_general_reserve(bot).required_army)
        # a non-ALL_IN mode resets to the default reserve without touching the map
        bot.ffa_endgame.decision = FfaEndgameDecision(
            mode=FfaEndgameMode.TURTLE, target_player=-1, our_economy=0,
            enemy_economy_total=0, reason='turtle', prioritizing_neutral_city=False)
        BotFfaEndgame.update_general_reserve(bot)
        reset = BotFfaEndgame.get_general_reserve(bot)
        self.assertEqual(1, reset.required_army)
        self.assertTrue(reset.satisfied)
        self.assertEqual(-1, reset.non_target_player)

    def test_update_general_reserve_recomputes_on_new_turn(self) -> None:
        """a stale reserve_turn forces recompute; the fresh value replaces the sentinel."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        sentinel = FfaGeneralReserve(required_army=777, satisfied=False)
        bot.ffa_endgame.reserve = sentinel
        bot.ffa_endgame.reserve_turn = bot._map.turn - 1  # stale
        bot._map.turn += 1
        bot.viewInfo = _FakeViewInfo()
        with patch.object(SearchUtils, 'build_distance_map_matrix_with_skip', return_value=_FakeDistanceMap()):
            BotFfaEndgame.update_general_reserve(bot)
        fresh = BotFfaEndgame.get_general_reserve(bot)
        self.assertIsNot(sentinel, fresh)
        self.assertEqual(1, fresh.required_army)  # empty fake map -> no local threats
        self.assertEqual(bot._map.turn, bot.ffa_endgame.reserve_turn)

    def test_reconcile_general_reserve_half_boundary_allowed(self) -> None:
        """general 14 reserve 8: full leaves 1, half retains exactly 8 -> the half is allowed."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        bot.general.army = 14
        self._injectReserve(bot, requiredArmy=8)
        result = BotFfaEndgame.reconcile_general_reserve_move(
            bot, Move(bot.general, _FakeTile(x=19, y=20, player=-1, army=0)))
        self.assertIsNotNone(result)
        self.assertTrue(result.move_half)
        self.assertEqual((14 - 1) // 2, result.army_moved)  # 6 moved -> 8 retained

    def test_reconcile_general_reserve_half_below_reserve_rejected(self) -> None:
        """general 12 reserve 8: half would retain only 7 -> reject and clear the stale path."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        bot.general.army = 12
        self._injectReserve(bot, requiredArmy=8)
        bot.curPath = object()
        bot.curPathPrio = 5
        result = BotFfaEndgame.reconcile_general_reserve_move(
            bot, Move(bot.general, _FakeTile(x=19, y=20, player=-1, army=0)))
        self.assertIsNone(result)
        self.assertIsNone(bot.curPath)
        self.assertEqual(-1, bot.curPathPrio)

    def test_reconcile_general_reserve_retaliate_never_constrains(self) -> None:
        """RETALIATE ignores the reserve entirely: the full general move is returned as-is."""
        bot = self._retaliateBot()
        bot.general.army = 12
        move = Move(bot.general, _FakeTile(x=19, y=20, player=1, army=3))
        self.assertIs(move, BotFfaEndgame.reconcile_general_reserve_move(bot, move))
        self.assertFalse(move.move_half)

    def test_reconcile_general_reserve_passthrough_non_general_none_and_inactive(self) -> None:
        """non-general sources, a None move, and non-ALL_IN modes pass through untouched."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        stack = _FakeTile(x=20, y=21, player=0, army=50)
        stackMove = Move(stack, _FakeTile(x=19, y=21, player=-1, army=0))
        self.assertIs(stackMove, BotFfaEndgame.reconcile_general_reserve_move(bot, stackMove))
        self.assertIsNone(BotFfaEndgame.reconcile_general_reserve_move(bot, None))
        turtleBot = self._turtleBot()
        BotFfaEndgame.update_policy(turtleBot)
        turtleMove = Move(turtleBot.general, _FakeTile(x=19, y=20, player=-1, army=0))
        self.assertIs(turtleMove, BotFfaEndgame.reconcile_general_reserve_move(turtleBot, turtleMove))

    # ---------- get_attack_move forward priority / sentinel ----------

    def test_attack_move_continues_policy_curpath_before_fresh_stealth_and_generic(self) -> None:
        """a committed policy curPath is continued before any fresh stealth/generic gather."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        curPathMove = object()
        stealthMove = object()
        allInMove = object()
        with patch.object(BotStealthAllIn, 'get_committed_route_move', return_value=None), \
                patch.object(BotStealthAllIn, 'get_stealth_all_in_move', return_value=stealthMove), \
                patch.object(BotPathingUtils, 'continue_cur_path', return_value=(True, curPathMove)), \
                patch.object(BotCombatOps, 'get_all_in_move', return_value=allInMove):
            move = BotFfaEndgame.get_attack_move(
                bot, threat=None, defenseCriticalTileSet=set(), kingKillPath=None, raceChance=0.0)
        self.assertIs(curPathMove, move)

    def test_attack_move_ready_forward_advance_beats_rear_gather(self) -> None:
        """a viable forward advance is chosen before the rear/general gather fallback."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        self.assertEqual(FfaEndgameMode.ALL_IN, bot.ffa_endgame.decision.mode)
        forwardMove = object()
        gatherMove = object()
        with patch.object(BotStealthAllIn, 'get_committed_route_move', return_value=None), \
                patch.object(BotStealthAllIn, 'get_stealth_all_in_move', return_value=None), \
                patch.object(BotPathingUtils, 'continue_cur_path', return_value=(False, None)), \
                patch.object(BotCombatOps, 'get_all_in_move', return_value=None), \
                patch.object(BotFfaEndgame, '_gather_forward_to_target', return_value=gatherMove) as gather, \
                patch.object(BotFfaEndgame, '_get_forward_fallback_move', return_value=forwardMove):
            move = BotFfaEndgame.get_attack_move(
                bot, threat=None, defenseCriticalTileSet=set(), kingKillPath=None, raceChance=0.0)
        self.assertIs(forwardMove, move)
        gather.assert_not_called()

    def test_collect_target_frontier_roots_rejects_own_general_sentinel(self) -> None:
        """targetPlayerExpectedGeneralLocation pointing at OUR general is never a frontier root."""
        bot = self._threePlayerSet(97, 3, 74, 1, 167, 10)
        BotFfaEndgame.update_policy(bot)
        target = bot.ffa_endgame.decision.target_player
        self.assertNotEqual(-1, target)
        targetTile = _FakeTile(x=5, y=5, player=target, army=3)
        bot._map.tiles = [targetTile]
        bot.alt_en_gen_positions = [[] for _ in bot._map.players]
        bot.targetPlayerExpectedGeneralLocation = bot.general  # own-general sentinel
        roots = BotFfaEndgame._collect_target_frontier_roots(bot)
        self.assertIn(targetTile, roots)
        self.assertNotIn(bot.general, roots)
        for root in roots:
            self.assertNotEqual(bot.general.player, root.player)


if __name__ == '__main__':
    unittest.main()
