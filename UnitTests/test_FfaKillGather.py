import typing
import unittest
from dataclasses import dataclass, field
from unittest.mock import patch

from BotModules import BotFfaKillGather
from BotModules.BotFfaKillGather import (
    FfaKillGatherCandidate,
    FfaKillGatherCommittedMove,
    FfaKillGatherOption,
    FfaKillGatherState,
)
from Models.Move import Move
from Strategy.FfaKillGatherMath import FfaKillProjection, FfaKillValue
from TestBase import TestBase


@dataclass(slots=True, eq=False)
class _FakeTile:
    x: int
    y: int
    tile_index: int
    player: int = -1
    army: int = 0
    isGeneral: bool = False
    isCity: bool = False
    isNotPathable: bool = False
    visible: bool = True
    discovered: bool = True
    movable: typing.Set = field(default_factory=set)


@dataclass(slots=True)
class _FakePlayer:
    index: int
    tiles: typing.List[_FakeTile] = field(default_factory=list)
    standingArmy: int = 0
    tileCount: int = 0
    cityCount: int = 0
    dead: bool = False
    aggression_factor: int = 0
    general: _FakeTile | None = None
    score: int = 0


@dataclass(slots=True)
class _FakeScore:
    player: int
    dead: bool
    tiles: int
    total: int = 0


@dataclass(slots=True)
class _FakeMap:
    players: typing.List[_FakePlayer]
    scores: typing.List[_FakeScore]
    team_ids_by_player_index: typing.List[int]
    tiles_by_index: typing.List[_FakeTile]
    teammates: typing.Set[int]
    turn: int = 100
    has_city_state: bool = False
    swamps: bool = False
    deserts: bool = False
    generals: typing.List[_FakeTile | None] = field(default_factory=list)


@dataclass(slots=True)
class _FakeGeneralPositions:
    raw: typing.List[bool]

    def keys(self):
        return [i for i, v in enumerate(self.raw) if v]


@dataclass(slots=True)
class _FakeArmyTracker:
    valid_general_positions_by_player: typing.Dict[int, _FakeGeneralPositions]


@dataclass(slots=True)
class _FakeQueue:
    amounts: typing.List[int]

    def as_tile_list(self, includeOnesAndZeros: bool = False):
        return list(self.amounts)


@dataclass(slots=True)
class _FakeOpponentTracker:
    queues: typing.Dict[int, _FakeQueue]

    def get_player_gather_queue(self, playerIndex: int):
        return self.queues.get(playerIndex, _FakeQueue([]))


@dataclass(slots=True)
class _FakeViewInfo:
    stats_lines: typing.List[str] = field(default_factory=list)
    info_lines: typing.List[str] = field(default_factory=list)

    def add_stats_line(self, line: str) -> None:
        self.stats_lines.append(line)

    def add_info_line(self, line: str) -> None:
        self.info_lines.append(line)


@dataclass(slots=True)
class _FakeBot:
    _map: _FakeMap
    player: _FakePlayer
    general: _FakeTile
    armyTracker: _FakeArmyTracker
    opponent_tracker: _FakeOpponentTracker
    alt_en_gen_positions: typing.List[typing.List[_FakeTile]]
    ffa_exclusive_target_lock: int = -1
    targetPlayer: int = -1
    ffa_kill_gather_state: FfaKillGatherState | None = None
    _ffa_kill_gather_cache: BotFfaKillGather.FfaKillGatherCache = field(
        default_factory=BotFfaKillGather.FfaKillGatherCache)
    _ffa_kill_gather_enemy: int = -1
    run_background_work_synchronously: bool = True
    last_move: Move | None = None
    viewInfo: _FakeViewInfo = field(default_factory=_FakeViewInfo)

    def info(self, line: str) -> None:
        pass


def _tile(x: int, y: int, index: int, player: int = -1, army: int = 0, **kw) -> _FakeTile:
    return _FakeTile(x=x, y=y, tile_index=index, player=player, army=army, **kw)


def _wire_movable(tiles: typing.List[_FakeTile]) -> None:
    for t in tiles:
        t.movable = {n for n in tiles if n is not t}


def _make_bot(
    enemy_count: int = 4,
    living: typing.List[int] | None = None,
    enemy_standing: int = 40,
    enemy_econ_tiles: int = 30,
    enemy_econ_cities: int = 0,
    our_standing: int = 80,
    our_econ_tiles: int = 80,
    our_econ_cities: int = 1,
    team_ids: typing.List[int] | None = None,
) -> _FakeBot:
    """Builds a fake >2-team FFA board: us p0 plus enemy_count-1 living enemies."""
    living = living if living is not None else list(range(1, enemy_count))
    players: typing.List[_FakePlayer] = []
    scores: typing.List[_FakeScore] = []
    team_ids_local: typing.List[int] = []
    tiles_by_index: typing.List[_FakeTile] = []
    idx = 0
    our_general = _tile(0, 0, idx, player=0, army=5, isGeneral=True)
    idx += 1
    our_tiles = [our_general, _tile(1, 0, idx, player=0, army=10)]
    idx += 1
    players.append(_FakePlayer(
        index=0, tiles=our_tiles, standingArmy=our_standing,
        tileCount=our_econ_tiles, cityCount=our_econ_cities, general=our_general))
    scores.append(_FakeScore(player=0, dead=False, tiles=our_econ_tiles + our_econ_cities))
    team_ids_local.append(0)
    for p in range(1, enemy_count):
        is_living = p in living
        gen = _tile(10 + p, 10, idx, player=p, army=3, isGeneral=True) if is_living else None
        tiles = [gen] if gen is not None else []
        if is_living:
            idx += 1
            tiles.append(_tile(10 + p, 11, idx, player=p, army=2))
            idx += 1
        players.append(_FakePlayer(
            index=p, tiles=tiles, standingArmy=enemy_standing if is_living else 0,
            tileCount=enemy_econ_tiles if is_living else 0,
            cityCount=enemy_econ_cities if is_living else 0,
            dead=not is_living, general=gen))
        scores.append(_FakeScore(player=p, dead=not is_living, tiles=enemy_econ_tiles if is_living else 0))
        team_ids_local.append(p)
    all_tiles = our_tiles + [t for pl in players[1:] for t in pl.tiles]
    _wire_movable(all_tiles)
    # Dense index->tile map: enemy tile indices are allocated sequentially so
    # every slot 0..max_index is a real Tile (MapBase.tiles_by_index contract).
    max_index = max(t.tile_index for t in all_tiles)
    tiles_by_index: typing.List[_FakeTile] = [None] * (max_index + 1)  # type: ignore[list-item]
    for t in all_tiles:
        tiles_by_index[t.tile_index] = t
    m = _FakeMap(
        players=players, scores=scores, team_ids_by_player_index=(team_ids if team_ids is not None else team_ids_local),
        tiles_by_index=tiles_by_index, teammates=set(), generals=[our_general] + [p.general for p in players[1:]])
    bot = _FakeBot(
        _map=m, player=players[0], general=our_general,
        armyTracker=_FakeArmyTracker({p: _FakeGeneralPositions([False] * len(tiles_by_index)) for p in range(enemy_count)}),
        opponent_tracker=_FakeOpponentTracker({}),
        alt_en_gen_positions=[[] for _ in range(enemy_count)])
    return bot


def _cursor_recert(bot: _FakeBot, state: FfaKillGatherState) -> str:
    """Isolate offer/consume cursor mechanics from the math recertification.

    _recertify_remaining runs the real project_forward_gather/certify_kill
    pipeline over live Tile objects; these _FakeTile fixtures cannot satisfy it.
    This stub returns the mode the real recert would pick for a still-valid
    schedule (gather while moves remain, else hunt) so the cursor/reconcile
    logic is exercised without the math layer.
    """
    return "gather" if state.gather_cursor < len(state.gather_moves) else "hunt"


class FfaKillGatherStateTests(TestBase):
    """Unit coverage for BotModules/BotFfaKillGather.py state machine, gates,
    serialization, and option cloning (Tests/test_FFA.py t100/t146 seams)."""
    __slots__ = ()

    def _state(self, bot: _FakeBot, gather: list[Move] | None = None,
               route: list[int] | None = None) -> FfaKillGatherState:
        return FfaKillGatherState(
            enemy_index=1, launch_tile_index=1,
            gather_moves=gather or [], hunt_route_tile_indexes=route or [1, 2, 3],
            candidates=[4], created_turn=100, deadline_turn=135,
            kill_value_total=64.0, projection_margin=1, owns_exclusive_lock=True)

    def test_flag_off_is_committed_and_prepare_are_inert(self) -> None:
        """With the module flag False every public entry point is a no-op."""
        bot = _make_bot()
        bot.ffa_kill_gather_state = self._state(bot)
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', False):
            self.assertFalse(BotFfaKillGather.is_committed(bot))
            self.assertEqual([], BotFfaKillGather.prepare_options(bot, set()))
            res = BotFfaKillGather.get_committed_move(bot, set())
            self.assertFalse(res.handled)
            BotFfaKillGather.note_final_move(bot, None)
            BotFfaKillGather.poll_wrp_worker(bot)
            BotFfaKillGather.add_stats(bot)
        # state untouched by the inert calls
        self.assertIsNotNone(bot.ffa_kill_gather_state)

    def test_is_committed_clears_dead_target(self) -> None:
        """is_committed aborts safely when the target's scoreboard says dead."""
        bot = _make_bot()
        bot.ffa_kill_gather_state = self._state(bot)
        bot._map.scores[1].dead = True
        bot._map.scores[1].tiles = 0
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            self.assertFalse(BotFfaKillGather.is_committed(bot))
        self.assertIsNone(bot.ffa_kill_gather_state)
        # feature-owned lock released on abort
        self.assertEqual(-1, bot.ffa_exclusive_target_lock)

    def test_living_team_count_uses_scoreboard_and_2v2_is_not_ffa(self) -> None:
        """>2 living TEAMS required; two teams (2v2) must not count as FFA even
        with >2 player objects, and remote unseen living enemies still count."""
        bot = _make_bot(enemy_count=4)
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            self.assertTrue(BotFfaKillGather._is_ffa_kill_gather_active(bot))
        # TRUE 2v2: FOUR living players but only TWO teams (team_ids=[0,0,1,1]
        # -> p0+p1 on team0, p2+p3 on team1). >2 players is NOT an FFA.
        bot2 = _make_bot(enemy_count=4, living=[1, 2, 3], team_ids=[0, 0, 1, 1])
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            self.assertFalse(BotFfaKillGather._is_ffa_kill_gather_active(bot2))
        # sanity: the same 4 players on 4 distinct teams IS an FFA (>2 teams)
        bot2b = _make_bot(enemy_count=4, living=[1, 2, 3], team_ids=[0, 1, 2, 3])
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            self.assertTrue(BotFfaKillGather._is_ffa_kill_gather_active(bot2b))
        # remote unseen living enemy: p2 has zero known Tile objects but a live
        # scoreboard entry -> still counts as a living team.
        bot3 = _make_bot(enemy_count=4)
        bot3._map.players[2].tiles = []
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            self.assertTrue(BotFfaKillGather._is_ffa_kill_gather_active(bot3))

    def test_enemy_eligibility_compares_standing_and_econ_separately(self) -> None:
        """Standing army AND tileCount+25*cityCount must BOTH strictly exceed the
        victim's; raw player.score is NOT the economic gate."""
        bot = _make_bot()
        # p1: standing 40, econ tiles 30 cities 0 -> econ 30. We have 80/81.
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            ok, reason = BotFfaKillGather._enemy_is_eligible(bot, 1)
            self.assertTrue(ok, reason)
        # give p1 a huge econ via cities so econ gate fails even though standing ok
        bot._map.players[1].cityCount = 5  # econ 30 + 125 = 155 > ours 81
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            ok, reason = BotFfaKillGather._enemy_is_eligible(bot, 1)
            self.assertFalse(ok)
            self.assertEqual('econ_not_greater', reason)

    def test_general_hypotheses_flat_alt_and_cap(self) -> None:
        """A CONFIRMED general is the sole hypothesis immediately; with the
        general UNKNOWN, alt_en_gen_positions[p] (a FLAT list[Tile]) unions with
        the tracker matrix, dedupes, and >64 rejects instead of slicing."""
        bot = _make_bot(enemy_count=3)
        known = bot._map.players[1].general
        # confirmed general -> exactly [known], phantom alt/tracker ignored
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            hyps = BotFfaKillGather._general_hypotheses(bot, 1)
        self.assertIsNotNone(hyps)
        assert hyps is not None
        self.assertEqual([known.tile_index], [h.tile_index for h in hyps])

        # general UNKNOWN -> union flat alt + tracker matrix with dedupe
        bot._map.players[1].general = None
        shared = bot._map.players[1].tiles[1]
        alt_tiles = [shared, _tile(20, 20, 1000, player=1), _tile(21, 20, 1001, player=1)]
        bot.alt_en_gen_positions[1] = alt_tiles  # flat list of Tiles (not groups)
        n = len(bot._map.tiles_by_index)
        raw = [False] * n
        raw[shared.tile_index] = True  # tracker sees the same tile as the alt list
        bot.armyTracker.valid_general_positions_by_player[1] = _FakeGeneralPositions(raw)
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            hyps = BotFfaKillGather._general_hypotheses(bot, 1)
        self.assertIsNotNone(hyps)
        assert hyps is not None
        idxs = {h.tile_index for h in hyps}
        # shared(deduped across tracker+alt) + 2 pure-alt = 3 unique hypotheses
        self.assertEqual({shared.tile_index, 1000, 1001}, idxs)
        # over-cap: 65 flat alt positions -> reject (None), never silently slice
        bot.alt_en_gen_positions[1] = [_tile(30 + i, 30, 2000 + i, player=1) for i in range(65)]
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            self.assertIsNone(BotFfaKillGather._general_hypotheses(bot, 1))

    def test_offer_then_matching_move_consumes_gather_cursor(self) -> None:
        """get_committed_move offers WITHOUT consuming; note_final_move consumes
        only when the actual returned move matches (incl. move_half)."""
        bot = _make_bot()
        bot._map.players[1].general = None  # target general unknown -> gather phase
        src = bot.player.tiles[1]  # our army-10 tile (player 0); also the hunt head
        dst = bot.player.tiles[0]  # our general tile (player 0)
        # _wire_movable already links every tile, so src.movable contains both the
        # gather dest AND the hunt route's next tile - no manual restriction needed.
        state = self._state(bot, gather=[Move(src, dst, False)])
        bot.ffa_kill_gather_state = state
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, '_recertify_remaining', side_effect=_cursor_recert):
            res = BotFfaKillGather.get_committed_move(bot, set())
            self.assertTrue(res.handled)
            self.assertIsNotNone(res.move)
            self.assertEqual(0, state.gather_cursor)  # offered, not consumed
            # actual executed move matches -> consume
            BotFfaKillGather.note_final_move(bot, Move(src, dst, False))
            self.assertEqual(1, state.gather_cursor)
            # gather schedule exhausted -> next call enters hunt phase
            res2 = BotFfaKillGather.get_committed_move(bot, set())
            self.assertTrue(res2.handled, f'reason={res2.reason}')
            self.assertEqual('hunt', res2.reason)

    def test_defense_pause_does_not_consume_gather_step(self) -> None:
        """A defense preemption (different move / pass) leaves the cursor so the
        same gather step is re-offered next non-defense turn."""
        bot = _make_bot()
        bot._map.players[1].general = None  # target general unknown -> gather phase
        src = bot.player.tiles[1]  # our army-10 tile (player 0)
        dst = bot.player.tiles[0]  # our general tile (player 0)
        src.movable = {dst}
        state = self._state(bot, gather=[Move(src, dst, False)])
        bot.ffa_kill_gather_state = state
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, '_recertify_remaining', side_effect=_cursor_recert):
            BotFfaKillGather.get_committed_move(bot, set())
            # defense returns a DIFFERENT move -> offer not consumed
            other = bot._map.tiles_by_index[0]
            BotFfaKillGather.note_final_move(bot, Move(other, other, False))
            self.assertEqual(0, state.gather_cursor)
            # next turn re-offers the SAME gather step
            res = BotFfaKillGather.get_committed_move(bot, set())
            self.assertEqual(src.tile_index, res.move.source.tile_index)
            self.assertEqual(dst.tile_index, res.move.dest.tile_index)

    def test_half_move_still_consumes_via_endpoint_match(self) -> None:
        """A threat-block split that halves the offered move still counts as
        executed (same endpoints) so the schedule does not loop forever."""
        bot = _make_bot()
        bot._map.players[1].general = None  # target general unknown -> gather phase
        src = bot.player.tiles[1]  # our army-10 tile (player 0)
        dst = bot.player.tiles[0]  # our general tile (player 0)
        src.movable = {dst}
        state = self._state(bot, gather=[Move(src, dst, False)])
        bot.ffa_kill_gather_state = state
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, '_recertify_remaining', side_effect=_cursor_recert):
            BotFfaKillGather.get_committed_move(bot, set())
            BotFfaKillGather.note_final_move(bot, Move(src, dst, True))  # halved
            self.assertEqual(1, state.gather_cursor)

    def test_abort_preserves_preexisting_same_target_lock(self) -> None:
        """Abort releases the exclusive lock ONLY when this feature created it;
        a pre-existing same-target lock is left intact."""
        bot = _make_bot()
        state = self._state(bot)
        state.owns_exclusive_lock = False  # lock predates this feature
        bot.ffa_exclusive_target_lock = 1   # same target, pre-existing
        bot.ffa_kill_gather_state = state
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            BotFfaKillGather._abort(bot, 'test')
        self.assertIsNone(bot.ffa_kill_gather_state)
        self.assertEqual(1, bot.ffa_exclusive_target_lock)  # preserved

    def test_serialize_roundtrip_preserves_cursor_head_route_lock(self) -> None:
        """save_state/load_state round-trips the half-executed gather cursor, the
        explicit hunt cursor/head, pending offer, finishing route, and lock owner."""
        bot = _make_bot()
        src = bot.player.tiles[1]  # our army-10 tile (player 0)
        dst = bot.player.tiles[0]  # our general tile (player 0)
        gather = [Move(src, dst, False), Move(src, dst, True)]
        state = self._state(bot, gather=gather, route=[1, 2, 3, 2])  # revisit tile 2
        state.gather_cursor = 1
        state.hunt_cursor = 2
        state.head_tile_index = 2
        state.phase = 'hunt'
        state.pending_offered_key = f"{src.tile_index}>{dst.tile_index}:0"
        state.pending_offered_turn = 105
        state.pending_offered_dest_index = dst.tile_index
        bot.ffa_kill_gather_state = state
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            data = BotFfaKillGather.save_state(bot)
            self.assertEqual('1', data['bot_ffa_kill_active'])
            bot2 = _make_bot()
            bot2._map = bot._map
            BotFfaKillGather.load_state(bot2, data)
        s2 = bot2.ffa_kill_gather_state
        self.assertIsNotNone(s2)
        assert s2 is not None
        self.assertEqual(1, s2.gather_cursor)
        self.assertEqual(2, s2.hunt_cursor)
        self.assertEqual(2, s2.head_tile_index)
        self.assertEqual([1, 2, 3, 2], s2.hunt_route_tile_indexes)  # revisit kept
        self.assertEqual('hunt', s2.phase)
        self.assertEqual(state.pending_offered_key, s2.pending_offered_key)
        self.assertEqual(105, s2.pending_offered_turn)
        self.assertEqual(dst.tile_index, s2.pending_offered_dest_index)
        self.assertTrue(s2.owns_exclusive_lock)
        self.assertEqual(1, bot2.ffa_exclusive_target_lock)
        # full gather list round-trips with absolute cursor: index `cursor` is the
        # next unconsumed step (the half=True move), nothing half-executed lost.
        self.assertEqual(2, len(s2.gather_moves))
        self.assertEqual(1, s2.gather_cursor)
        self.assertTrue(s2.gather_moves[s2.gather_cursor].move_half)
        self.assertEqual(dst.tile_index, s2.gather_moves[s2.gather_cursor].dest.tile_index)

    def test_hunt_off_route_head_aborts_without_rejoin(self) -> None:
        """A head/cursor mismatch in the hunt phase is an explicit abort - there
        is NO unpriced BFS rejoin that could skip/reverse route positions."""
        bot = _make_bot()
        state = self._state(bot, gather=[], route=[5, 6, 7])
        state.phase = 'hunt'
        state.head_tile_index = 1   # our army tile; route[0]=5 -> off-route
        state.hunt_cursor = 0
        bot.ffa_kill_gather_state = state

        def _hunt_mode(_bot, _state):
            return 'hunt'

        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, '_recertify_remaining', side_effect=_hunt_mode):
            res = BotFfaKillGather.get_committed_move(bot, set())
            self.assertFalse(res.handled)
            self.assertEqual('head_off_route', res.reason)
        # explicit abort cleared committed state (and released feature lock)
        self.assertIsNone(bot.ffa_kill_gather_state)
        self.assertEqual(-1, bot.ffa_exclusive_target_lock)

    def test_recert_abort_clears_committed_state(self) -> None:
        """When full remaining-plan recertification fails, the commit aborts and
        releases its feature-owned exclusive lock rather than continuing unsafe."""
        bot = _make_bot()
        src = bot.player.tiles[1]
        dst = bot.player.tiles[0]
        state = self._state(bot, gather=[Move(src, dst, False)])
        bot.ffa_kill_gather_state = state
        bot.ffa_exclusive_target_lock = 1  # feature-owned (owns_exclusive_lock=True)

        def _fail_recert(_bot, _state):
            BotFfaKillGather._abort(_bot, 'recert_failed')
            return 'abort'

        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, '_recertify_remaining', side_effect=_fail_recert):
            res = BotFfaKillGather.get_committed_move(bot, set())
            self.assertFalse(res.handled)
            self.assertEqual('recert_failed', res.reason)
        self.assertIsNone(bot.ffa_kill_gather_state)
        self.assertEqual(-1, bot.ffa_exclusive_target_lock)

    def test_option_clone_preserves_subtype_and_metadata(self) -> None:
        """clone() keeps the FfaKillGatherOption subtype, enemy, candidates, and
        certificate fields so flow can promote a non-first selected option."""
        bot = _make_bot()
        src = bot._map.tiles_by_index[1]
        dst = bot._map.tiles_by_index[0]
        opt = FfaKillGatherOption(
            moves=[Move(src, dst, False)], enemy_index=1, launch_tile=src,
            gather_moves=[Move(src, dst, False)], hunt_route_tiles=[src, dst],
            hunt_moves=[Move(src, dst, False)], candidates=[dst],
            projection=_proj(), kill_value=_val(),
            gather_turns=3, route_turns=4, deadline_turn=130, reserved_turns=7)
        clone = opt.clone()
        self.assertIsInstance(clone, FfaKillGatherOption)
        self.assertEqual(1, clone.enemy_index)
        self.assertEqual(3, clone.gather_turns)
        self.assertEqual(4, clone.route_turns)
        self.assertEqual(7, clone.certificate_turns)
        self.assertEqual(opt.kill_value.total, clone.kill_value.total)


def _proj() -> FfaKillProjection:
    return FfaKillProjection(
        gather_turns=3, route_turns=4, launch_army=60, route_cost=10,
        enemy_standing=40, enemy_city_growth=0, enemy_tile_growth=0,
        defender_army=50, margin=0, rounds=0.14, certified=False,
        enemy_free_pool=40, enemy_ordinary_gather=0)


def _val() -> FfaKillValue:
    return FfaKillValue(tiles=39, city_income=25, queued_army=0)


if __name__ == '__main__':
    unittest.main()
