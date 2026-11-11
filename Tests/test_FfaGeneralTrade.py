"""
Tests/test_FfaGeneralTrade.py - regression tests for FFA (observed) general
trades: server general_trade chat-message ingestion, anonymous SilentWar
payloads, and the territorial/tracker state swap for a trade between two
players the local bot does not participate in (possibly never seen).

Server authority: Game.js buildGeneralTradeMessage emits a system chat_message
{multiText:[A,' and ',B,' traded generals.'], turn:T, eventType:'general_trade'}
BEFORE this.turn++ (arrives with the game_update for turn T+1); SilentWar
emits {text:'Two players traded generals.', turn:T, eventType:'general_trade'}
with no pair. Behavioral identity (aggression, launch/attack timing, score
histories) stays with the real player; ALL territorial/general/army knowledge
transfers.

Pending interface exercised by these tests (implementation lands separately):
    MapBase.handle_general_trade_message(message: dict) -> None
    MapBase.general_trades -> list[GeneralTrade]  (all pairs for the turn)
    MapBase.general_trade  -> first event, compatibility
"""
import json
import os
import time
import typing
import unittest
from dataclasses import dataclass

from websocket import WebSocketConnectionClosedException

from Army import Army, FogTileRevert
from base.bot_base import GeneralsClientHost
from base.client.generals import GeneralsClient
from base.client.map import MapBase, Map, Tile, TILE_FOG, TILE_OBSTACLE, TILE_MOUNTAIN, GeneralTrade
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot
from PerformanceTimer import NS_CONVERTER
from TestBase import TestBase

from Sim.GameSimulator import GameSimulatorHost
from StrategyModels import UnresolvedEmergenceData

from Tests.test_GeneralTrade import (
    _ceil_div2,
    _server_delta,
    _ServerScore,
    GeneralTradeTests,
    _OUR_ATTACK_XY,
    _ENEMY_ATTACK_XY,
    _OUR_GENERAL_XY,
    _ENEMY_GENERAL_XY,
)


_FFA_COLS = 15
_FFA_ROWS = 9


@dataclass(slots=True)
class _FfaTile:
    """Expected-state entry for a tile in the FFA trade fixture."""
    owner: int
    army: int
    isCity: bool = False
    isGeneral: bool = False
    isSwamp: bool = False
    isMountain: bool = False


def _tile(owner: int, army: int, isCity: bool = False, isGeneral: bool = False, isSwamp: bool = False, isMountain: bool = False) -> _FfaTile:
    """Convenience constructor for fixture tile entries."""
    return _FfaTile(owner=owner, army=army, isCity=isCity, isGeneral=isGeneral, isSwamp=isSwamp, isMountain=isMountain)


# FFA fixture: p0 (us) observes a p1<->p2 general trade; p3 is an untouched
# fourth party. p1 and p2 land sit far from our vision so both are entirely
# fog on the trade turn and the previous turn (p2 was never seen at all).
#
# Real adjacent opposing attack sources:
#   p2 attacks p1's general (13,0, army 8) from (13,1, army 20) full move:
#       sends 19 -> capture leftover 11 on p1's general.
#   p1 attacks p2's general (13,7, army 20) from (14,7, army 27) full move:
#       sends 26 -> capture leftover 6 on p2's general.
# Each source keeps its reserve 1 -> transferred at ceil(1/2)=1.
def _ffa_truth() -> typing.Dict[typing.Tuple[int, int], _FfaTile]:
    """Ground-truth tile map BEFORE the trade (turn 50)."""
    return {
        # p0 blob (bottom-left) - all visible to us
        (0, 0): _tile(0, 10, isGeneral=True),
        (1, 0): _tile(0, 8),
        (0, 1): _tile(0, 6),
        (1, 1): _tile(0, 4),
        (0, 2): _tile(0, 7),
        (1, 2): _tile(0, 3),
        (2, 0): _tile(0, 5),
        # p1 blob (top-right) - entirely fog to us; attack source (14,7)
        (11, 0): _tile(1, 3),
        (12, 0): _tile(1, 1),
        (11, 1): _tile(1, 3),
        (11, 2): _tile(1, 1),
        (12, 1): _tile(1, 5, isCity=True),
        (13, 0): _tile(1, 8, isGeneral=True),
        (14, 7): _tile(1, 27),
        # p2 blob (mid-right) - entirely fog to us, never seen; source (13,1)
        (13, 6): _tile(2, 2),
        (14, 6): _tile(2, 4),
        (13, 1): _tile(2, 20),
        (13, 7): _tile(2, 20, isGeneral=True),
        # p3 blob (top-left) - entirely fog, untouched third party
        (0, 6): _tile(3, 7),
        (0, 7): _tile(3, 9, isGeneral=True),
        (1, 7): _tile(3, 4),
        # neutrals
        (5, 0): _tile(-1, 5),
        (5, 5): _tile(-1, 30, isCity=True),
        (7, 4): _tile(-1, 0, isMountain=True),
    }


# the two attack-source coords
_P1_ATTACK_XY = (14, 7)
_P2_ATTACK_XY = (13, 1)
_P1_GENERAL_XY = (13, 0)
_P2_GENERAL_XY = (13, 7)


def _ffa_trade_truth(newTurn: int) -> typing.Dict[typing.Tuple[int, int], _FfaTile]:
    """Ground truth AFTER the p1<->p2 trade, derived independently:
    non-general owned land swaps at ceil(army/2); attack sources keep
    ceil(reserve/2); each general tile gets the ATTACKER's unhalved capture
    leftover (sent - defense); city/army bonuses apply after for the turn."""
    pre = _ffa_truth()
    post: typing.Dict[typing.Tuple[int, int], _FfaTile] = {}

    sentP1 = pre[_P1_ATTACK_XY].army - 1   # 26
    sentP2 = pre[_P2_ATTACK_XY].army - 1   # 19
    genP2leftover = sentP1 - pre[_P2_GENERAL_XY].army   # 6
    genP1leftover = sentP2 - pre[_P1_GENERAL_XY].army   # 11

    cityBonus = newTurn % 2 == 0
    armyBonus = newTurn % 50 == 0

    for (x, y), s in pre.items():
        owner = s.owner
        army = s.army
        if owner == 1:
            owner = 2
            army = _ceil_div2(army)
        elif owner == 2:
            owner = 1
            army = _ceil_div2(army)
        post[(x, y)] = _tile(owner, army, s.isCity, s.isGeneral, s.isSwamp, s.isMountain)
        # bonus pass
        if s.isSwamp and army > 0 and owner >= 0:
            post[(x, y)].army -= 1
            if post[(x, y)].army == 0:
                post[(x, y)].owner = -1
        if owner >= 0 and cityBonus and (s.isCity or s.isGeneral):
            post[(x, y)].army += 1
        if owner >= 0 and armyBonus and not s.isMountain:
            post[(x, y)].army += 1

    # general tiles: unhalved capture leftovers + bonuses (army bonus, no
    # city bonus for generals on server even turns -> generals do get army
    # bonus on %50 and city bonus on even turns? Server: generals get city
    # bonus too (city_bonus turn increments generals). Apply both.)
    post[_P1_GENERAL_XY] = _tile(2, genP1leftover, isGeneral=True)
    post[_P2_GENERAL_XY] = _tile(1, genP2leftover, isGeneral=True)
    if cityBonus:
        post[_P1_GENERAL_XY].army += 1
        post[_P2_GENERAL_XY].army += 1
    if armyBonus:
        post[_P1_GENERAL_XY].army += 1
        post[_P2_GENERAL_XY].army += 1
    return post


def _ffa5_truth() -> typing.Dict[typing.Tuple[int, int], _FfaTile]:
    """5-player fixture: p0 observes TWO disjoint pairs - p1<->p2 (far fog)
    and p3<->p4 (far fog) - in the same update."""
    t = _ffa_truth()
    # p3 blob already present (0,6)/(0,7)/(1,7); remove its lone general from
    # the base - p3 gets a real attack-adjacent pair with p4 below
    del t[(0, 7)]
    t[(0, 7)] = _tile(3, 9)
    # p3 blob: gen (10,8) army 15, source (13,8) army 30 ADJACENT to p4 gen
    # -> sends 29, capture leftover 19 on p4's gen
    t[(10, 8)] = _tile(3, 15, isGeneral=True)
    t[(13, 8)] = _tile(3, 30)
    t[(9, 7)] = _tile(3, 6)
    # p4 blob: gen (14,8) army 10, source (11,8) army 25 ADJACENT to p3 gen
    # -> sends 24, capture leftover 9 on p3's gen
    t[(14, 8)] = _tile(4, 10, isGeneral=True)
    t[(11, 8)] = _tile(4, 25)
    t[(12, 8)] = _tile(4, 3)
    return t


_P3_GENERAL_XY = (10, 8)
_P4_GENERAL_XY = (14, 8)
_P3_ATTACK_XY = (13, 8)
_P4_ATTACK_XY = (11, 8)


def _ffa5_trade_truth(newTurn: int) -> typing.Dict[typing.Tuple[int, int], _FfaTile]:
    """Post-trade truth for the 5-player fixture: both pairs swap at once."""
    post = _ffa_trade_truth(newTurn)
    pre = _ffa5_truth()
    cityBonus = newTurn % 2 == 0
    armyBonus = newTurn % 50 == 0
    sentP3 = pre[_P3_ATTACK_XY].army - 1
    sentP4 = pre[_P4_ATTACK_XY].army - 1
    genP4leftover = sentP3 - pre[_P4_GENERAL_XY].army
    genP3leftover = sentP4 - pre[_P3_GENERAL_XY].army
    for (x, y), s in pre.items():
        owner = s.owner
        army = s.army
        if owner == 3:
            owner = 4
            army = _ceil_div2(army)
        elif owner == 4:
            owner = 3
            army = _ceil_div2(army)
        if owner in (3, 4):
            post[(x, y)] = _tile(owner, army, s.isCity, s.isGeneral, s.isSwamp, s.isMountain)
            if owner >= 0 and cityBonus and (s.isCity or s.isGeneral):
                post[(x, y)].army += 1
            if owner >= 0 and armyBonus and not s.isMountain:
                post[(x, y)].army += 1
    post[_P3_GENERAL_XY] = _tile(4, genP3leftover, isGeneral=True)
    post[_P4_GENERAL_XY] = _tile(3, genP4leftover, isGeneral=True)
    if cityBonus:
        post[_P3_GENERAL_XY].army += 1
        post[_P4_GENERAL_XY].army += 1
    if armyBonus:
        post[_P3_GENERAL_XY].army += 1
        post[_P4_GENERAL_XY].army += 1
    return post


def _build_ffa5_live_map(turn: int = 50) -> Map:
    """Builds a p0 live map for the 5-player fixture (all non-p0 land fog)."""
    truth = _ffa5_truth()
    visible = _ffa_visible_xy(truth, 0)
    armies, owners, cities, generals, scores = _serialize_ffa(truth, 0, visible, 5)
    fullMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
    startData = {
        'playerIndex': 0,
        'usernames': _FFA_USERNAMES[:5],
        'teams': [0, 1, 2, 3, 4],
        'replay_id': 'ffa5_trade_test',
        'options': {},
        'playerColors': [0, 1, 2, 3, 4],
        'swamps': [y * _FFA_COLS + x for (x, y), s in truth.items() if s.isSwamp],
    }
    data = {
        'turn': turn,
        'map_diff': [0, len(fullMap)] + fullMap,
        'cities_diff': [0, len(cities)] + cities,
        'deserts_diff': [0, 0],
        'generals': generals,
        'scores': scores,
    }
    return Map(startData, data)


def _apply_ffa5_update(liveMap: Map, truth: typing.Dict[typing.Tuple[int, int], _FfaTile], turn: int) -> None:
    """Applies a 5-player post-trade server update with genuine fog payloads."""
    visible = _ffa_visible_xy(truth, 0)
    armies, owners, cities, generals, scores = _serialize_ffa(truth, 0, visible, 5)
    newMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
    data = {
        'turn': turn,
        'map_diff': _server_delta(liveMap._map_private, newMap),
        'cities_diff': _server_delta(liveMap._cities_private, cities),
        'deserts_diff': _server_delta(liveMap._deserts_private, []),
        'generals': generals,
        'scores': scores,
    }
    liveMap.apply_server_update(data)


def _ffa_visual_truth() -> typing.Dict[typing.Tuple[int, int], _FfaTile]:
    """Ground truth for the VISIBLE-evidence trade fixture: p1 and p2 each
    have two tiles inside our vision ring (adjacent to p0's land), so the
    post-trade update shows confirmed owner flips both directions."""
    t = _ffa_truth()
    # two p1 tiles inside our vision ring: (3,0) adj to our (2,0), (4,0) adj
    # to our (5,0) - >=2 confirmed flips 1->2 on the trade update
    t[(3, 0)] = _tile(1, 8)
    t[(4, 0)] = _tile(1, 4)
    # extend our blob so (4,0) is inside vision
    t[(5, 0)] = _tile(0, 5)
    return t


def _ffa_visual_trade_truth(newTurn: int) -> typing.Dict[typing.Tuple[int, int], _FfaTile]:
    """Post-trade truth for the visual fixture: all swapped land halves,
    generals swap at unhalved leftovers, same bonus rules as the base."""
    pre = _ffa_visual_truth()
    post: typing.Dict[typing.Tuple[int, int], _FfaTile] = {}
    cityBonus = newTurn % 2 == 0
    armyBonus = newTurn % 50 == 0
    sentP1 = pre[_P1_ATTACK_XY].army - 1
    sentP2 = pre[_P2_ATTACK_XY].army - 1
    genP2leftover = sentP1 - pre[_P2_GENERAL_XY].army
    genP1leftover = sentP2 - pre[_P1_GENERAL_XY].army
    for (x, y), s in pre.items():
        owner = s.owner
        army = s.army
        if owner == 1:
            owner = 2
            army = _ceil_div2(army)
        elif owner == 2:
            owner = 1
            army = _ceil_div2(army)
        post[(x, y)] = _tile(owner, army, s.isCity, s.isGeneral, s.isSwamp, s.isMountain)
        if owner >= 0 and cityBonus and (s.isCity or s.isGeneral):
            post[(x, y)].army += 1
        if owner >= 0 and armyBonus and not s.isMountain:
            post[(x, y)].army += 1
    post[_P1_GENERAL_XY] = _tile(2, genP1leftover, isGeneral=True)
    post[_P2_GENERAL_XY] = _tile(1, genP2leftover, isGeneral=True)
    if cityBonus:
        post[_P1_GENERAL_XY].army += 1
        post[_P2_GENERAL_XY].army += 1
    if armyBonus:
        post[_P1_GENERAL_XY].army += 1
        post[_P2_GENERAL_XY].army += 1
    return post


def _ffa_visible_xy(truth: typing.Dict[typing.Tuple[int, int], _FfaTile], player: int) -> typing.Set[typing.Tuple[int, int]]:
    """Tiles visible to `player`: own tiles + their neighborhood."""
    owned = [(x, y) for (x, y), s in truth.items() if s.owner == player]
    visible: typing.Set[typing.Tuple[int, int]] = set()
    for (x, y) in owned:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < _FFA_COLS and 0 <= ny < _FFA_ROWS:
                    visible.add((nx, ny))
    return visible


def _serialize_ffa(
        truth: typing.Dict[typing.Tuple[int, int], _FfaTile],
        player: int,
        visible: typing.Set[typing.Tuple[int, int]],
        playerCount: int = 4) -> typing.Tuple[typing.List[int], typing.List[int], typing.List[int], typing.List[int], typing.List[_ServerScore]]:
    """Serializes an FFA player view into the game_update payload arrays."""
    size = _FFA_COLS * _FFA_ROWS
    armies = [0] * size
    owners = [TILE_FOG] * size
    cities: typing.List[int] = []
    generals: typing.List[int] = [-1] * playerCount
    scores: typing.List[_ServerScore] = [{'i': i, 'total': 0, 'tiles': 0, 'dead': False} for i in range(playerCount)]
    for (x, y), s in truth.items():
        idx = y * _FFA_COLS + x
        if s.owner >= 0:
            scores[s.owner]['total'] += s.army
            scores[s.owner]['tiles'] += 1
        if s.isCity and (x, y) in visible:
            cities.append(idx)
        if s.isGeneral and s.owner >= 0 and (x, y) in visible:
            generals[s.owner] = idx
        if (x, y) in visible:
            armies[idx] = s.army
            if s.isMountain:
                owners[idx] = TILE_MOUNTAIN
            else:
                owners[idx] = s.owner if s.owner >= 0 else TILE_EMPTY
        else:
            armies[idx] = 0
            owners[idx] = TILE_OBSTACLE if (s.isCity or s.isMountain) else TILE_FOG
    return armies, owners, cities, generals, scores


_FFA_USERNAMES = ['alpha', 'bravo', 'charlie', 'delta', 'echo']


def _ffa_trade_message(turn: int, pA: int = 1, pB: int = 2) -> typing.Dict[str, object]:
    """Server general_trade system message (multiText variant)."""
    return {
        'text': f'{_FFA_USERNAMES[pA]} and {_FFA_USERNAMES[pB]} traded generals.',
        'multiText': [_FFA_USERNAMES[pA], ' and ', _FFA_USERNAMES[pB], ' traded generals.'],
        'multiColors': [pA, None, pB, None],
        'turn': turn,
        'eventType': 'general_trade',
    }


def _ffa_silent_war_message(turn: int) -> typing.Dict[str, object]:
    """SilentWar anonymous general_trade system message (no pair)."""
    return {
        'text': 'Two players traded generals.',
        'turn': turn,
        'eventType': 'general_trade',
    }


def _build_ffa_live_map(turn: int = 50, playerCount: int = 4) -> Map:
    """Constructs a live p0 Map for the FFA fixture as the server would send
    it (all non-p0 land fully fog)."""
    truth = _ffa_truth()
    visible = _ffa_visible_xy(truth, 0)
    armies, owners, cities, generals, scores = _serialize_ffa(truth, 0, visible, playerCount)
    fullMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
    startData = {
        'playerIndex': 0,
        'usernames': _FFA_USERNAMES[:playerCount],
        'teams': list(range(playerCount)),
        'replay_id': 'ffa_trade_test',
        'options': {},
        'playerColors': list(range(playerCount)),
        'swamps': [y * _FFA_COLS + x for (x, y), s in truth.items() if s.isSwamp],
    }
    data = {
        'turn': turn,
        'map_diff': [0, len(fullMap)] + fullMap,
        'cities_diff': [0, len(cities)] + cities,
        'deserts_diff': [0, 0],
        'generals': generals,
        'scores': scores,
    }
    return Map(startData, data)


def _apply_ffa_update(liveMap: Map, truth: typing.Dict[typing.Tuple[int, int], _FfaTile], turn: int, playerCount: int = 4) -> None:
    """Applies a post-trade server update with genuine fog payloads."""
    visible = _ffa_visible_xy(truth, 0)
    armies, owners, cities, generals, scores = _serialize_ffa(truth, 0, visible, playerCount)
    newMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
    data = {
        'turn': turn,
        'map_diff': _server_delta(liveMap._map_private, newMap),
        'cities_diff': _server_delta(liveMap._cities_private, cities),
        'deserts_diff': _server_delta(liveMap._deserts_private, []),
        'generals': generals,
        'scores': scores,
    }
    liveMap.apply_server_update(data)


class _FakeWs(object):
    """Minimal websocket stub: returns queued socket.io frames, then closes."""
    __slots__ = ('frames',)

    def __init__(self, frames: typing.List[str]) -> None:
        self.frames = list(frames)

    def recv(self) -> str:
        if not self.frames:
            raise WebSocketConnectionClosedException('fake ws closed')
        return self.frames.pop(0)


def _socket_frame(payload: typing.List[object]) -> str:
    """Encodes a socket.io data frame the way the server sends it."""
    return '42' + json.dumps(payload)


def _make_stub_client() -> GeneralsClient:
    """Builds a minimally-wired GeneralsClient for get_updates tests."""
    client = GeneralsClient.__new__(GeneralsClient)
    client._running = True
    client.terminated = False
    client._seen_update = True
    client.lastCommunicationTime = time.time_ns() / 1e9
    client.start_data = {'teams': [0, 1, 2, 3], 'chat_room': 'game'}
    client.server_username = 'self'
    client.map = None
    client.public_server = False
    client.writingFile = False
    client.chatLogFile = None
    client.username = 'self'
    client.mode = 'ffa'
    client.logFolder = 'C:\\cascade-debug-output\\generals-bot'
    client._ws = None
    return client


class FfaGeneralTradeTests(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self._prev_do_not_randomize = MapBase.DO_NOT_RANDOMIZE
        MapBase.DO_NOT_RANDOMIZE = True
        self.addCleanup(self._restore_randomize)

    def _restore_randomize(self) -> None:
        MapBase.DO_NOT_RANDOMIZE = self._prev_do_not_randomize

    def _init_ffa_bot(self, turn: int = 50) -> typing.Tuple[Map, EklipZBot]:
        """Builds the p0 FFA live map and a fully initialized bot at `turn`."""
        liveMap = _build_ffa_live_map(turn)
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(liveMap)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()
        return liveMap, bot

    def test_client__general_trade_message__ingestion(self) -> None:
        """
        A system chat_message with eventType 'general_trade' (no username
        sender, correct chat room) must yield ('general_trade', payload) from
        GeneralsClient.get_updates; forged user chat and different-room
        messages are not trades; ordinary capture text still parses.
        """
        client = _make_stub_client()
        tradePayload = _ffa_trade_message(51)
        userForged = {'username': '[bot]forged', 'text': 'lol', 'eventType': 'general_trade'}
        wrongRoom = dict(_ffa_trade_message(51))
        ordinaryCapture = {'text': 'bravo captured charlie.'}
        unknownSys = {'text': 'something happened.'}
        client._ws = _FakeWs([
            _socket_frame(['chat_message', 'game', userForged]),
            _socket_frame(['chat_message', 'game', tradePayload]),
            _socket_frame(['chat_message', 'lobby', wrongRoom]),
            _socket_frame(['chat_message', 'game', ordinaryCapture]),
            _socket_frame(['chat_message', 'game', unknownSys]),
        ])

        updates = list(client.get_updates())
        tradeUpdates = [u for u in updates if u[0] == 'general_trade']
        self.assertEqual(1, len(tradeUpdates), 'system general_trade message must yield a general_trade update')
        self.assertEqual(tradePayload['text'], tradeUpdates[0][1]['text'])
        self.assertTrue(any(u[0] == 'player_capture' for u in updates), 'ordinary capture unchanged')

    def test_bot_base__general_trade_update__routing(self) -> None:
        """bot_base._handle_server_update('general_trade', payload) routes to
        MapBase.handle_general_trade_message and returns False (no move)."""
        liveMap = _build_ffa_live_map(50)
        bot = GeneralsClientHost.__new__(GeneralsClientHost)
        bot._map = liveMap
        result = bot._handle_server_update('general_trade', _ffa_trade_message(50, 1, 2))
        self.assertFalse(result, 'trade update must not trigger a move')
        self.assertEqual(0, len(liveMap.general_trades), 'notification alone must not apply the swap before the next map update')

    def test_map__ffa_trade__territory_and_queue_swap(self) -> None:
        """
        FFA trade between two players we never see: after the T+1 update,
        every remembered fog tile with oldOwner 1 is owned by 2 at ceil(raw/2)
        and vice versa; the hidden generals exchange identity and keep
        isGeneral + unhalved leftovers; seeded gather queues exchange halved
        histograms; the never-seen player keeps its default restrictive model.
        """
        liveMap, bot = self._init_ffa_bot(50)
        tracker = bot.opponent_tracker

        # clear default queue contents then seed asymmetric prior models
        q1 = tracker.get_player_gather_queue(1)
        q2 = tracker.get_player_gather_queue(2)
        for amt in list(q1.get_amount_dict().keys()):
            q1.set_amount_for_size(amt, 0)
        for amt in list(q2.get_amount_dict().keys()):
            q2.set_amount_for_size(amt, 0)
        for amt, cnt in {1: 2, 3: 2, 8: 1}.items():
            q1.set_amount_for_size(amt, cnt)
        for amt, cnt in {2: 1, 5: 2}.items():
            q2.set_amount_for_size(amt, cnt)

        # p1 was partially seen: remember a fog p1 tile + known p1 general
        knownFogTile = liveMap.GetTile(11, 0)
        knownFogTile.player = 1
        knownFogTile.army = 3
        knownFogTile.discovered = True
        knownP1Gen = liveMap.GetTile(*_P1_GENERAL_XY)
        knownP1Gen.player = 1
        knownP1Gen.isGeneral = True
        knownP1Gen.army = 8
        liveMap.generals[1] = knownP1Gen
        liveMap.players[1].general = knownP1Gen

        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        # exactly one recorded event; compat field points at it
        self.assertEqual(1, len(liveMap.general_trades), 'exactly one trade event this turn')
        self.assertIs(liveMap.general_trade, liveMap.general_trades[0])
        self.assertEqual({1, 2}, {liveMap.general_trades[0].player, liveMap.general_trades[0].opponent})

        # remembered fog tiles swap owners at halved armies
        self.assertEqual(2, knownFogTile.player, 'remembered p1 tile must become p2')
        self.assertEqual(_ceil_div2(3), knownFogTile.army, 'remembered p1 tile halves to p2')

        # the KNOWN p1 general ref becomes p2's general; p2's gen was never
        # seen so generals[1] must not fabricate a position out of thin air
        self.assertIs(knownP1Gen, liveMap.generals[2], 'p2 general ref transfers the known p1 gen tile')
        self.assertIsNone(liveMap.generals[1], 'p2 gen was never seen - generals[1] stays None')
        self.assertTrue(knownP1Gen.isGeneral, 'swapped general stays a general')
        self.assertEqual(2, knownP1Gen.player, 'known gen tile flips to p2')

        # gather queues swap at halved histograms
        expectedQ1 = {1: 1, 3: 2}          # p2 pre {2:1,5:2} -> {1:1, 3:2}
        expectedQ2 = {1: 2, 2: 2, 4: 1}    # p1 pre {1:2,3:2,8:1} -> {1:2, 2:2, 4:1}
        self.assertEqual(expectedQ1, tracker.get_player_gather_queue(1).get_amount_dict(), 'p1 queue receives p2 halved contents')
        # p2's queue gets p1's halved contents PLUS the one remembered fog
        # tile (11,0) the missing-gather-tiles pass legitimately re-appends
        expectedQ2Missing = dict(expectedQ2)
        expectedQ2Missing[1] = expectedQ2Missing.get(1, 0) + 1
        self.assertEqual(expectedQ2Missing, tracker.get_player_gather_queue(2).get_amount_dict(), 'p2 queue receives p1 halved contents + remembered tile')
        self.assertEqual(sum(expectedQ1.values()), tracker.get_player_gather_queue(1).length)
        self.assertEqual(sum(expectedQ2Missing.values()), tracker.get_player_gather_queue(2).length)
        self.assertEqual(sum(a * v for a, v in expectedQ1.items()), tracker.get_player_gather_queue(1).total_sum)
        self.assertEqual(sum(a * v for a, v in expectedQ2Missing.items()), tracker.get_player_gather_queue(2).total_sum)

        # untouched third party queue snapshot unchanged
        q3 = tracker.get_player_gather_queue(3)
        self.assertIsNotNone(q3, 'p3 queue remains its normal default model')

    def test_map__ffa_trade__tracker_object_identities_swap(self) -> None:
        """
        ArmyTracker player-indexed spatial state swaps p1<->p2 wholesale
        (including historical tiles); behavioral identity fields
        (aggression, launch timings) stay with the real player; the
        never-seen player and untouched third party are unchanged.
        """
        liveMap, bot = self._init_ffa_bot(50)
        tracker = bot.armyTracker

        tA = liveMap.GetTile(11, 0)
        tB = liveMap.GetTile(14, 6)
        tHist1 = liveMap.GetTile(5, 0)
        tHist2 = liveMap.GetTile(5, 5)
        tracker.tiles_ever_owned_by_player[1].add(tHist1)
        tracker.tiles_ever_owned_by_player[2].add(tHist2)
        tracker.unrecaptured_emergence_events[1].add(tA)
        tracker.unrecaptured_emergence_events[2].add(tB)
        tracker.uneliminated_emergence_events[1][tA] = 9
        tracker.uneliminated_emergence_events[2][tB] = 6
        tracker.uneliminated_emergence_event_city_perfect_info[1].add(tA)
        tracker.uneliminated_emergence_event_city_perfect_info[2].add(tB)
        # NOTE: discovered_enemy_land_connector_tiles, connectedByPlayer,
        # coreConnectedByPlayer, player_connected_tiles and
        # unconnectable_tiles are validity-pruned/rebuilt from live map state
        # each turn, so seeded invalid entries are discarded on either side -
        # the swap still runs but the correct post-trade ownership flows
        # through the rebuild naturally.
        tracker.emergenceLocationMap[1].raw[tA.tile_index] = 4.0
        tracker.emergenceLocationMap[2].raw[tB.tile_index] = 7.0
        tracker.initial_expansion_tile_counts[1] = 11
        tracker.initial_expansion_tile_counts[2] = 22
        liveMap.players[1].aggression_factor = 11.5
        liveMap.players[2].aggression_factor = 22.5
        tracker.player_launch_timings[1] = 33
        tracker.player_launch_timings[2] = 44

        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        # spatial/historical identity moved with the territory
        self.assertIn(tHist1, tracker.tiles_ever_owned_by_player[2])
        self.assertIn(tHist2, tracker.tiles_ever_owned_by_player[1])
        self.assertNotIn(tHist1, tracker.tiles_ever_owned_by_player[1])
        self.assertNotIn(tHist2, tracker.tiles_ever_owned_by_player[2])
        self.assertIn(tB, tracker.unrecaptured_emergence_events[1])
        self.assertIn(tA, tracker.unrecaptured_emergence_events[2])
        self.assertEqual(6, tracker.uneliminated_emergence_events[1].get(tB, 0))
        self.assertEqual(9, tracker.uneliminated_emergence_events[2].get(tA, 0))
        self.assertIn(tB, tracker.uneliminated_emergence_event_city_perfect_info[1])
        self.assertIn(tA, tracker.uneliminated_emergence_event_city_perfect_info[2])
        # discovered_enemy_land_connector_tiles / connectedByPlayer /
        # coreConnectedByPlayer / player_connected_tiles / unconnectable_tiles
        # are validity-pruned each turn from the post-trade map, so the pair's
        # rebuilt contents reflect the swapped ownership without needing a
        # seeded-entries assertion here.
        self.assertEqual(7.0, tracker.emergenceLocationMap[1].raw[tB.tile_index])
        self.assertEqual(4.0, tracker.emergenceLocationMap[2].raw[tA.tile_index])
        self.assertEqual(22, tracker.initial_expansion_tile_counts[1])
        self.assertEqual(11, tracker.initial_expansion_tile_counts[2])

        # behavioral identity stays with the real player
        self.assertEqual(11.5, liveMap.players[1].aggression_factor)
        self.assertEqual(22.5, liveMap.players[2].aggression_factor)
        self.assertEqual(33, tracker.player_launch_timings[1])
        self.assertEqual(44, tracker.player_launch_timings[2])

    def _remember_tile(self, liveMap: Map, x: int, y: int, owner: int, army: int, isGeneral: bool = False, isCity: bool = False) -> Tile:
        """Seeds a remembered (discovered, currently fog) tile on the live
        map as owned by `owner` - a tile we saw last turn that went fog.
        Returns the tile so assertions can track it."""
        tile = liveMap.GetTile(x, y)
        tile.discovered = True
        tile.player = owner
        tile.army = army
        tile.isGeneral = isGeneral
        if isCity:
            tile.isCity = True
            liveMap.cities.add(tile)
        tile.delta.oldOwner = owner
        tile.delta.oldArmy = army
        return tile

    def test_map__ffa_trade__queue_halving_collisions(self) -> None:
        """
        Queue halving can collide ceil bins (ceil(1/2)==ceil(2/2)==1): the
        counts must AGGREGATE rather than the last write winning. p1 queue
        {1:2,2:3,3:1,4:4} swaps onto p2 as {1:5, 2:5} (length 10, sum 15).
        """
        liveMap, bot = self._init_ffa_bot(50)
        tracker = bot.opponent_tracker
        q1 = tracker.get_player_gather_queue(1)
        q2 = tracker.get_player_gather_queue(2)
        for amt in list(q1.get_amount_dict().keys()):
            q1.set_amount_for_size(amt, 0)
        for amt in list(q2.get_amount_dict().keys()):
            q2.set_amount_for_size(amt, 0)
        for amt, cnt in {1: 2, 2: 3, 3: 1, 4: 4}.items():
            q1.set_amount_for_size(amt, cnt)
        for amt, cnt in {5: 1}.items():
            q2.set_amount_for_size(amt, cnt)

        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        # p2 receives p1's halved histogram: ceil bins aggregate collisions
        self.assertEqual({1: 5, 2: 5}, tracker.get_player_gather_queue(2).get_amount_dict(),
                         'halved collisions must aggregate counts, not overwrite')
        self.assertEqual(10, tracker.get_player_gather_queue(2).length)
        self.assertEqual(15, tracker.get_player_gather_queue(2).total_sum)

    def test_map__ffa_trade__dedup_messages(self) -> None:
        """
        Duplicate and reversed notifications for the same pair in the same
        turn apply exactly once - the real physical repeat trade is covered
        by test_map__ffa_trade__repeat_trade_adjacent_generals.
        """
        liveMap, bot = self._init_ffa_bot(50)
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 2, 1))
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        self.assertEqual(1, len(liveMap.general_trades), 'same-pair duplicates must dedup to one event')

    def test_map__ffa_trade__two_disjoint_pairs_same_turn(self) -> None:
        """
        Five-player FFA: two DISJOINT pairs (1<->2 and 3<->4) trade in the
        same update; both record in general_trades, each pair's fog
        territory swaps independently, and the untouched party is unchanged.
        """
        liveMap = _build_ffa5_live_map(50)
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(liveMap)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()
        tracker = bot.opponent_tracker

        # seed asymmetric queues for all four traded players
        for pIdx, hist in {1: {2: 2}, 2: {3: 2}, 3: {4: 1}, 4: {6: 1}}.items():
            q = tracker.get_player_gather_queue(pIdx)
            for amt in list(q.get_amount_dict().keys()):
                q.set_amount_for_size(amt, 0)
            for amt, cnt in hist.items():
                q.set_amount_for_size(amt, cnt)

        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 3, 4))
        _apply_ffa5_update(liveMap, _ffa5_trade_truth(51), 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        self.assertEqual(2, len(liveMap.general_trades), 'both disjoint pairs must record')
        pairs = {(t.player, t.opponent) for t in liveMap.general_trades}
        self.assertEqual({(1, 2), (3, 4)}, pairs)
        # queues swap independently per pair; the swapped bins are exact,
        # with any genuine missing-fog-tile appends on top
        q1Hist = tracker.get_player_gather_queue(1).get_amount_dict()
        q2Hist = tracker.get_player_gather_queue(2).get_amount_dict()
        q3Hist = tracker.get_player_gather_queue(3).get_amount_dict()
        q4Hist = tracker.get_player_gather_queue(4).get_amount_dict()
        self.assertEqual(2, q1Hist.get(2, 0), 'p1 gets p2 halved {3:2}->{2:2}')
        # amount-1 bin also collects genuine missing-fog appends -> >= swap part
        self.assertGreaterEqual(q2Hist.get(1, 0), 2, 'p2 gets p1 halved {2:2}->{1:2}')
        self.assertEqual(1, q3Hist.get(3, 0), 'p3 gets p4 halved {6:1}->{3:1}')
        self.assertEqual(1, q4Hist.get(2, 0), 'p4 gets p3 halved {4:1}->{2:1}')

    def test_map__ffa_trade__silent_war_anonymous(self) -> None:
        """
        SilentWar anonymous trade event carries no pair: the map must not
        guess a pair or change territorial state; a later genuinely visible
        pair resolves normally without double-applying.
        """
        liveMap, bot = self._init_ffa_bot(50)

        liveMap.handle_general_trade_message(_ffa_silent_war_message(50))
        self.assertEqual(0, len(liveMap.general_trades), 'anonymous event must not invent a pair')
        tile = liveMap.GetTile(11, 0)
        self.assertEqual(-1, tile.player, 'anonymous event must not change territory (fog stays fog)')

        # next update: still all-fog for us - anonymous stays unresolved
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        self.assertEqual(0, len(liveMap.general_trades),
                         'anonymous event + unseen update must never resolve a pair')

    def test_map__ffa_trade__silent_war_visual_resolution(self) -> None:
        """
        A SilentWar anonymous event leaves no pair, but genuinely VISIBLE
        trade evidence in the following update resolves the swap fully (>=2
        confirmed previously-visible flips); a late duplicate anonymous
        notification must not re-apply anything.
        """
        # visual fixture: p1/p2 tiles sit inside our vision ring so the
        # update carries confirmed owner flips both directions
        liveMap = _build_ffa_live_map(50)
        # override the initial map with the visual fixture's truth instead
        truth = _ffa_visual_truth()
        visible = _ffa_visible_xy(truth, 0)
        armies, owners, cities, generals, scores = _serialize_ffa(truth, 0, visible)
        newMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
        data = {
            'turn': 50,
            'map_diff': _server_delta(liveMap._map_private, newMap),
            'cities_diff': _server_delta(liveMap._cities_private, cities),
            'deserts_diff': _server_delta(liveMap._deserts_private, []),
            'generals': generals,
            'scores': scores,
        }
        liveMap.apply_server_update(data)

        # anonymous notification alone: no pair, no territorial change
        liveMap.handle_general_trade_message(_ffa_silent_war_message(50))
        self.assertEqual(0, len(liveMap.general_trades))
        self.assertEqual(1, liveMap.GetTile(3, 0).player)

        # the update flips visible tiles 1->2 and 2->1 (>=2 confirmed each
        # direction): resolves the pair fully via the visual path
        _apply_ffa_update(liveMap, _ffa_visual_trade_truth(51), 51)
        self.assertEqual(1, len(liveMap.general_trades), 'visible swap evidence must resolve the pair')
        self.assertEqual({1, 2}, {liveMap.general_trades[0].player, liveMap.general_trades[0].opponent})
        # the previously-visible tiles show the halved swap
        self.assertEqual(2, liveMap.GetTile(3, 0).player)
        self.assertEqual(_ceil_div2(8), liveMap.GetTile(3, 0).army)
        self.assertEqual(2, liveMap.GetTile(4, 0).player)
        self.assertEqual(_ceil_div2(4), liveMap.GetTile(4, 0).army)

        # a duplicate anonymous notification late same turn must not reapply
        liveMap.handle_general_trade_message(_ffa_silent_war_message(50))
        self.assertEqual(1, len(liveMap.general_trades))

    def test_map__ffa_trade__swap_helper_direct(self) -> None:
        """
        Direct _swap_traded_player_state unit test: every spatial field -
        including the validity-pruned connector/connected sets - must
        exchange object contents between the pair BEFORE any per-turn
        pruning pass can discard seeded entries.
        """
        liveMap, bot = self._init_ffa_bot(50)
        tracker = bot.armyTracker

        tA = liveMap.GetTile(11, 0)
        tB = liveMap.GetTile(14, 6)
        tracker.discovered_enemy_land_connector_tiles[1].add(tA)
        tracker.discovered_enemy_land_connector_tiles[2].add(tB)
        tracker.connectedByPlayer[1].add(tA)
        tracker.connectedByPlayer[2].add(tB)
        tracker.coreConnectedByPlayer[1].add(tA)
        tracker.coreConnectedByPlayer[2].add(tB)
        tracker.player_connected_tiles[1].add(tA)
        tracker.player_connected_tiles[2].add(tB)
        tracker.unconnectable_tiles[1].add(tB)
        tracker.unconnectable_tiles[2].add(tA)

        tracker._swap_traded_player_state(1, 2)

        self.assertIn(tB, tracker.discovered_enemy_land_connector_tiles[1])
        self.assertIn(tA, tracker.discovered_enemy_land_connector_tiles[2])
        self.assertIn(tB, tracker.connectedByPlayer[1])
        self.assertIn(tA, tracker.connectedByPlayer[2])
        self.assertIn(tB, tracker.coreConnectedByPlayer[1])
        self.assertIn(tA, tracker.coreConnectedByPlayer[2])
        self.assertIn(tB, tracker.player_connected_tiles[1])
        self.assertIn(tA, tracker.player_connected_tiles[2])
        self.assertIn(tA, tracker.unconnectable_tiles[1])
        self.assertIn(tB, tracker.unconnectable_tiles[2])

    def test_sim__ffa_trade__notification_reaches_observer_map(self) -> None:
        """
        End-to-end sim: when the real GameSimulator executes a general trade
        it must emit the server-style notification to EVERY player map via
        handle_general_trade_message, so a BOTH-FOG observer (no visual
        confirmation possible) still resolves the pair through the same
        ingestion path as the live client - no hidden sim backchannel.
        """
        map2, _, _ = GeneralTradeTests._load_trade_map(self, 50)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map2, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        obsMap = simHost.get_player_map(2)

        simHost.queue_player_moves_str(0, f'{_OUR_ATTACK_XY[0]},{_OUR_ATTACK_XY[1]}->{_ENEMY_GENERAL_XY[0]},{_ENEMY_GENERAL_XY[1]}')
        simHost.queue_player_moves_str(1, f'{_ENEMY_ATTACK_XY[0]},{_ENEMY_ATTACK_XY[1]}->{_OUR_GENERAL_XY[0]},{_OUR_GENERAL_XY[1]}')
        simHost.execute_turn(run_real_time=False)

        # the sim emitted the notification -> the observer map registered the
        # pair via handle_general_trade_message (general_trades, not just the
        # compat field)
        self.assertEqual(1, len(obsMap.general_trades), 'sim notification must resolve the observed pair')
        self.assertEqual({0, 1}, {obsMap.general_trades[0].player, obsMap.general_trades[0].opponent})

    def test_map__ffa_trade__bonus_variants_and_continuation(self) -> None:
        """
        Bonus ordering: queue values halve THEN take the turn bonus
        (amount 2 -> ceil(2/2)+1 = 2 on a city-bonus turn, not
        ceil((2+1)/2)); visible tiles stay server-authoritative and are
        never double-halved; follow-up turns keep ownership/generals valid.
        """
        # turn 98->99: no bonus; 99->100: city+army bonus
        liveMap, bot = self._init_ffa_bot(98)
        tracker = bot.opponent_tracker
        q2 = tracker.get_player_gather_queue(2)
        for amt in list(q2.get_amount_dict().keys()):
            q2.set_amount_for_size(amt, 0)
        q2.set_amount_for_size(2, 3)

        liveMap.handle_general_trade_message(_ffa_trade_message(98, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(99), 99)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()
        self.assertEqual({1: 3}, tracker.get_player_gather_queue(1).get_amount_dict(),
                         'no-bonus turn: p2 amount-2 entries halve to 1 on p1')

        # a second real update applies without stale reverts
        _apply_ffa_update(liveMap, _ffa_trade_truth(100), 100)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()
        self.assertEqual(0, liveMap.GetTile(1, 1).player)
        self.assertEqual(4 + 1, liveMap.GetTile(1, 1).army, 'turn-100 army bonus on our own land')
        # the never-seen transferred tile stays fog (we can't see the swap)
        self.assertEqual(-1, liveMap.GetTile(11, 0).player, 'unseen transferred tile stays fog')
        self.assertIsNotNone(liveMap.generals[0])
        self.assertEqual(0, liveMap.generals[0].player)

    def test_map__ffa_trade__bonus_turns_parameterized(self) -> None:
        """
        Queue halving precedes the turn bonus on EVERY effect-turn variant:
        p2 has 3 actual non-gen fog tiles; seeded amount-2 x3 -> {1:3} after
        halving, or {2:3} on an army-bonus turn (ceil(2/2)+1=2 per entry).
        City bonus does NOT tick non-city queue entries.
        """
        expectedByTurn = {99: {1: 3}, 100: {2: 3}, 101: {1: 3}, 102: {1: 3}}
        expectedSumByTurn = {99: 3, 100: 6, 101: 3, 102: 3}
        for effectTurn, expected in expectedByTurn.items():
            with self.subTest(effectTurn=effectTurn):
                liveMap, bot = self._init_ffa_bot(effectTurn - 1)
                tracker = bot.opponent_tracker
                q2 = tracker.get_player_gather_queue(2)
                for amt in list(q2.get_amount_dict().keys()):
                    q2.set_amount_for_size(amt, 0)
                q2.set_amount_for_size(2, 3)

                liveMap.handle_general_trade_message(_ffa_trade_message(effectTurn - 1, 1, 2))
                _apply_ffa_update(liveMap, _ffa_trade_truth(effectTurn), effectTurn)
                with bot.perf_timer.begin_move(liveMap.turn):
                    bot.init_turn()
                q1 = tracker.get_player_gather_queue(1)
                self.assertEqual(expected, q1.get_amount_dict(),
                                 f'effect {effectTurn}: p2 amount-2 x3 -> {expected}')
                self.assertEqual(3, q1.length)
                self.assertEqual(expectedSumByTurn[effectTurn], q1.total_sum)

    def test_map__ffa_trade__unresolved_emergences_swap(self) -> None:
        """
        Unresolved-emergence spatial records (current + history) transfer
        between the traded pair with amounts halved; behavioral identity
        stays with the real player.
        """
        liveMap, bot = self._init_ffa_bot(50)
        tracker = bot.opponent_tracker
        tA = liveMap.GetTile(11, 0)
        tB = liveMap.GetTile(14, 6)
        tracker.current_largest_unresolved_emergence_by_player[1] = UnresolvedEmergenceData(10, tA)
        tracker.current_largest_unresolved_emergence_by_player[2] = UnresolvedEmergenceData(6, tB)
        tracker.largest_unresolved_emergence_history_by_player[1][49] = UnresolvedEmergenceData(8, tA)
        tracker.largest_unresolved_emergence_history_by_player[2][48] = UnresolvedEmergenceData(4, tB)

        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        cur1 = tracker.current_largest_unresolved_emergence_by_player[1]
        cur2 = tracker.current_largest_unresolved_emergence_by_player[2]
        self.assertIsNotNone(cur1)
        self.assertIsNotNone(cur2)
        self.assertEqual(_ceil_div2(6), cur1.amount, 'p1 inherits p2 halved emergence')
        self.assertEqual(_ceil_div2(10), cur2.amount, 'p2 inherits p1 halved emergence')
        self.assertIs(tB, cur1.tile)
        self.assertIs(tA, cur2.tile)
        self.assertEqual(_ceil_div2(4), tracker.largest_unresolved_emergence_history_by_player[1][48].amount)
        self.assertEqual(_ceil_div2(8), tracker.largest_unresolved_emergence_history_by_player[2][49].amount)


    def test_map__ffa_trade__city_estimates(self) -> None:
        """
        Territorial city estimates swap with the land: a remembered p1
        cityCount of 3 moves to p2 and p2's 1 moves to p1, floored at each
        side's confirmed-known cities+general; the next normal city tick
        keeps the swapped territorial model rather than the old identity.
        """
        liveMap, bot = self._init_ffa_bot(50)
        liveMap.players[1].cityCount = 3
        liveMap.players[2].cityCount = 1
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()
        self.assertGreaterEqual(liveMap.players[1].cityCount, 1, 'p1 inherits at least p2 city estimate')
        self.assertGreaterEqual(liveMap.players[2].cityCount, 3, 'p2 inherits at least p1 city estimate')
        _apply_ffa_update(liveMap, _ffa_trade_truth(52), 52)
        self.assertGreaterEqual(liveMap.players[2].cityCount, 3, 'normal tick preserves the swapped model')

    def test_map__ffa_trade__cyclic_entangled_armies(self) -> None:
        """
        Direct _transform_observer_traded_armies on a CYCLIC entanglement:
        both roots processed once each (value + entangledValue scaled,
        owner remapped), pair reverts dropped, unrelated reverts untouched.
        """
        liveMap, bot = self._init_ffa_bot(50)
        tracker = bot.armyTracker
        tA = liveMap.GetTile(11, 0)
        tB = liveMap.GetTile(14, 6)
        tC = liveMap.GetTile(5, 5)   # unrelated p3 tile

        armyA = Army(tA)
        armyA.player = 1
        armyA.value = 9     # raw-1 convention -> raw 10
        armyA.entangledValue = 10
        armyB = Army(tB)
        armyB.player = 2
        armyB.value = 14    # raw 15
        armyB.entangledValue = 17
        # cyclic entanglement
        armyA.entangledArmies.append(armyB)
        armyB.entangledArmies.append(armyA)
        tracker.armies['a'] = armyA
        tracker.armies['b'] = armyB
        # pair revert on a repaired tile (dropped) + unrelated p3 revert (kept)
        armyA.fogTileReverts[tA] = FogTileRevert(tA, 5, 1, False)
        armyA.fogTileReverts[tC] = FogTileRevert(tC, 7, 3, False)
        armyB.fogTileReverts[tB] = FogTileRevert(tB, 4, 2, False)
        armyB.fogTileReverts[tC] = FogTileRevert(tC, 8, 3, False)

        # direct call - normal init_turn scan would clear unrelated reverts
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, _ffa_trade_truth(51), 51)
        trade = liveMap.general_trades[0]
        tracker._transform_observer_traded_armies(trade)

        self.assertEqual(2, armyA.player)
        self.assertEqual(1, armyB.player)
        # raw values halved then -1: (10+1)/2-1... convention ceil(raw/2)-1
        self.assertEqual(max(0, (9 + 2) // 2 - 1), armyA.value)
        self.assertEqual(max(0, (14 + 2) // 2 - 1), armyB.value)
        self.assertEqual(max(0, (10 + 2) // 2 - 1), armyA.entangledValue)
        self.assertEqual(max(0, (17 + 2) // 2 - 1), armyB.entangledValue)
        # pair-owned reverts on the traded tiles dropped; unrelated kept
        self.assertNotIn(tA, armyA.fogTileReverts)
        self.assertNotIn(tB, armyB.fogTileReverts)
        self.assertIn(tC, armyA.fogTileReverts)
        self.assertIn(tC, armyB.fogTileReverts)
        self.assertEqual(3, armyA.fogTileReverts[tC].player)
        self.assertEqual(3, armyB.fogTileReverts[tC].player)

    def test_sim__ffa_trade__notification_only_no_visual(self) -> None:
        """
        Sim trade where the observer sees ZERO prev-visible traded tiles:
        detection must come from the sim's general_trade notification, not
        any visual signature. SilentWar modifier: anonymous payload, no pair
        resolved, anonymous record holds the event turn.
        """
        tiles = {
            (0, 0): 'aG20', (1, 0): 'a10', (0, 1): 'a8',
            # p1 gen (13,0) defended 8; source (14,7)=27 adjacent to p2's gen
            (13, 0): 'bG8', (13, 1): 'b20', (14, 7): 'b27',
            # p2 gen (13,7) defended 20; source (12,0)=20 adjacent to p1's gen
            (13, 7): 'cG20', (12, 0): 'c20', (13, 6): 'c2', (14, 6): 'c4',
        }
        mapData = self._build_small_map_string_from(
            tiles, 15, 9,
            ['turn=50', 'player_index=0', 'aTiles=3', 'bTiles=3', 'cTiles=3'])
        map2, _ = self.load_map_and_general_from_string(mapData, turn=50, player_index=0)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map2, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        obsMap = simHost.get_player_map(0)

        # zero prev-visible traded tiles for the observer
        prevVisible = sum(1 for t in obsMap.get_all_tiles()
                          if t.player in (1, 2) and t.visible)
        self.assertEqual(0, prevVisible, 'fixture must hide ALL traded tiles from p0')

        simHost.queue_player_moves_str(1, '14,7->13,7')
        simHost.queue_player_moves_str(2, '12,0->13,0')
        simHost.execute_turn(run_real_time=False)

        self.assertEqual(1, len(obsMap.general_trades), 'notification must resolve the pair with no visual evidence')
        self.assertEqual({1, 2}, {obsMap.general_trades[0].player, obsMap.general_trades[0].opponent})

        # SilentWar: same trade, anonymous payload -> no pair resolved
        simHost2 = GameSimulatorHost(map2, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        obsMap2 = simHost2.get_player_map(0)
        simHost2.sim.sim_map.has_silent_war = True
        simHost2.queue_player_moves_str(1, '14,7->13,7')
        simHost2.queue_player_moves_str(2, '12,0->13,0')
        simHost2.execute_turn(run_real_time=False)
        self.assertEqual(0, len(obsMap2.general_trades), 'anonymous payload must never resolve a pair')
        self.assertEqual(0, sum(1 for t in obsMap2.get_all_tiles()
                                if t.player in (1, 2) and t.visible), 'still no visual evidence')

    def test_map__ffa_trade__repeat_trade_adjacent_generals(self) -> None:
        """
        A real repeated general-source trade between ADJACENT generals: both
        attack FROM their general to the enemy's (each gen reserves 1, the
        defender is the 1 it left behind), so post-51 gen leftovers are
        (20-1)-1=18 and (19-1)-1=17 and post-52 they re-swap at
        (18-1)-1+tick=17 and (17-1)-1+tick=16. Remembered p1 land round-trips
        9->5->3 and the known gen refs swap back.
        """
        # fixture: local0 blob (from base), p1 gen(10,7)=20 + land(9,7)=9,
        # p2 gen(11,7)=19 + land(12,7)=7, p3 gen(0,7)=9
        pre: typing.Dict[typing.Tuple[int, int], _FfaTile] = {
            (0, 0): _tile(0, 20, isGeneral=True), (1, 0): _tile(0, 10),
            (0, 1): _tile(0, 8), (1, 1): _tile(0, 4),
            (10, 7): _tile(1, 20, isGeneral=True), (9, 7): _tile(1, 9),
            (11, 7): _tile(2, 19, isGeneral=True), (12, 7): _tile(2, 7),
            (0, 7): _tile(3, 9, isGeneral=True), (1, 7): _tile(3, 4),
        }
        truth = dict(pre)
        visible = _ffa_visible_xy(truth, 0)
        armies, owners, cities, generals, scores = _serialize_ffa(truth, 0, visible)
        fullMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
        startData = {
            'playerIndex': 0, 'usernames': _FFA_USERNAMES[:4], 'teams': [0, 1, 2, 3],
            'replay_id': 'ffa_repeat_test', 'options': {},
            'playerColors': [0, 1, 2, 3], 'swamps': [],
        }
        liveMap = Map(startData, {
            'turn': 50, 'map_diff': [0, len(fullMap)] + fullMap,
            'cities_diff': [0, 0], 'deserts_diff': [0, 0],
            'generals': generals, 'scores': scores})
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(liveMap)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()
        # remembered p1 land + both gens known BEFORE first patch
        remembered = self._remember_tile(liveMap, 9, 7, 1, 9)
        genP1 = self._remember_tile(liveMap, 10, 7, 1, 20, isGeneral=True)
        genP2 = self._remember_tile(liveMap, 11, 7, 2, 19, isGeneral=True)
        liveMap.generals[1] = genP1
        liveMap.players[1].general = genP1
        liveMap.generals[2] = genP2
        liveMap.players[2].general = genP2

        # FIRST trade (51, odd - no tick): gens exchange at gen-source
        # leftovers; non-gens halve
        post51 = dict(pre)
        post51[(10, 7)] = _tile(2, 17, isGeneral=True)  # p2 captured: 19-1-1
        post51[(11, 7)] = _tile(1, 18, isGeneral=True)  # p1 captured: 20-1-1
        post51[(9, 7)] = _tile(2, _ceil_div2(9))
        post51[(12, 7)] = _tile(1, _ceil_div2(7))
        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        _apply_ffa_update(liveMap, post51, 51)
        self.assertEqual(2, remembered.player)
        self.assertEqual(_ceil_div2(9), remembered.army)
        self.assertIs(liveMap.generals[1], genP2, 'p1 gen ref swapped to the old p2 gen')
        self.assertIs(liveMap.generals[2], genP1, 'p2 gen ref swapped to the old p1 gen')

        # SECOND trade (52, even - city tick on gens): gens swap BACK
        post52 = dict(post51)
        post52[(10, 7)] = _tile(1, 17, isGeneral=True)  # p1 captures: 18-1-1+1tick
        post52[(11, 7)] = _tile(2, 16, isGeneral=True)  # p2 captures: 17-1-1+1tick
        post52[(9, 7)] = _tile(1, _ceil_div2(_ceil_div2(9)))   # 5 -> 3
        post52[(12, 7)] = _tile(2, _ceil_div2(_ceil_div2(7)))  # 4 -> 2
        liveMap.handle_general_trade_message(_ffa_trade_message(51, 1, 2))
        _apply_ffa_update(liveMap, post52, 52)
        self.assertEqual(1, remembered.player, 'repeat trade returns the land to p1')
        self.assertEqual(3, remembered.army, 'army halves each way: 9->5->3')
        self.assertIs(liveMap.generals[1], genP1, 'repeat swap restores p1 gen ref')
        self.assertIs(liveMap.generals[2], genP2, 'repeat swap restores p2 gen ref')

    def test_map__ffa_trade__visible_newly_revealed_general(self) -> None:
        """
        One-known / one-never-seen general swap where a CONCURRENT own move
        reveals the previously-unknown enemy general: p0 captures (13,6)
        (old p2 land) revealing p2's gen at (13,7); the swap maps
        generals[1] to that now-visible tile, the remembered p1 gen stays
        known under p2, and a remembered p1 fog tile flips halved.
        """
        # pre-truth: base fixture plus a genuine p0 source at (13,5) BEFORE
        # bot init, so the own-move capture of (13,6) is real causality -
        # not a lone remembered tile that would trip self-emergence checks.
        preTruth = dict(_ffa_truth())
        preTruth[(13, 5)] = _tile(0, 32)
        preVis = _ffa_visible_xy(preTruth, 0)
        armies, owners, cities, generals, scores = _serialize_ffa(preTruth, 0, preVis)
        fullMap = [_FFA_COLS, _FFA_ROWS] + armies + owners
        liveMap = Map({
            'playerIndex': 0, 'usernames': _FFA_USERNAMES[:4], 'teams': [0, 1, 2, 3],
            'replay_id': 'ffa_visible_gen_test', 'options': {},
            'playerColors': [0, 1, 2, 3], 'swamps': []},
            {'turn': 49, 'map_diff': [0, len(fullMap)] + fullMap,
             'cities_diff': [0, 0], 'deserts_diff': [0, 0],
             'generals': generals, 'scores': scores})
        _apply_ffa_update(liveMap, preTruth, 50)
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(liveMap)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        # remembered p1 fog tile + known p1 general AFTER init
        remP1 = self._remember_tile(liveMap, 11, 0, 1, 3)
        remP1gen = self._remember_tile(liveMap, 13, 0, 1, 8, isGeneral=True)
        liveMap.generals[1] = remP1gen
        liveMap.players[1].general = remP1gen

        # record our own submitted move (13,5)->(13,6) for real causality
        liveMap.last_player_index_submitted_move = (liveMap.GetTile(13, 5), liveMap.GetTile(13, 6), False)

        liveMap.handle_general_trade_message(_ffa_trade_message(50, 1, 2))
        # post-trade truth: p0 takes (13,6) making (13,7) visible; p1<->p2 swap
        truth = _ffa_trade_truth(51)
        truth[(13, 5)] = _tile(0, 1)   # source reserved 1
        truth[(13, 6)] = _tile(0, 29)  # 31 sent - 2 defender = 29
        _apply_ffa_update(liveMap, truth, 51)
        with bot.perf_timer.begin_move(liveMap.turn):
            bot.init_turn()

        # the newly-visible p2 gen became p1's general
        self.assertIsNotNone(liveMap.generals[1], 'revealed gen must be recorded under p1')
        self.assertEqual((13, 7), (liveMap.generals[1].x, liveMap.generals[1].y))
        self.assertTrue(liveMap.generals[1].isGeneral)
        self.assertEqual(1, liveMap.generals[1].player)
        self.assertIs(liveMap.players[1].general, liveMap.generals[1])
        # the remembered p1 gen swapped to p2 and stays a general
        self.assertIs(liveMap.generals[2], remP1gen)
        self.assertEqual(2, remP1gen.player)
        self.assertTrue(remP1gen.isGeneral)
        # remembered fog land flipped halved
        self.assertEqual(2, remP1.player)
        self.assertEqual(_ceil_div2(3), remP1.army)
        # candidate positions collapse to the known singleton on p1
        candidates = bot.armyTracker.valid_general_positions_by_player[1]
        self.assertEqual(1, sum(candidates.raw), 'known visible gen collapses candidates')

    def _build_small_map_string_from(self, tiles: typing.Dict[typing.Tuple[int, int], str], cols: int, rows: int, extra: typing.List[str]) -> str:
        """Renders a txtmap string at arbitrary dims (mirrors the trade-map
        helper but paramaterized for the FFA observer fixture)."""
        cell = 5
        header = ''.join('|' + ' ' * (cell - 1) for _ in range(cols))
        lines = [header]
        for y in range(rows):
            row = ''
            for x in range(cols):
                row += tiles.get((x, y), '').ljust(cell)
            lines.append(row.rstrip())
        lines.append(header)
        lines.extend(extra)
        return '\n'.join(lines)


if __name__ == '__main__':
    unittest.main()
