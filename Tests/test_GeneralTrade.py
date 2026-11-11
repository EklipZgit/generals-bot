"""
Regression tests for mutual general captures ("general trades").

Authoritative server semantics (C:\\src\\generals\\shared\\Game.js
getMutualGeneralSwapMoveIndex / executeMutualGeneralSwap, and the mutual swap
integration tests in C:\\src\\generals\\test\\Game.integration.test.js):

- When two players' turn-selected moves would BOTH capture each other's
  general, no capture/death occurs: all non-general owned tiles swap to the
  other player with army = ceil(army / 2), except each attack source tile,
  which keeps only ceil(reserve / 2) where reserve = 1 for a full move or
  ceil(army / 2) for a half move.
- Each captured general tile transfers to the attacker with the FULL leftover
  army (sentArmy - defense), never halved, and keeps isGeneral (no city
  conversion, no death, no capture stats). The generals array entries are
  swapped between the two players.
- Normal city/army/swamp/desert increments are then applied for the new turn.
- The traded-away land loses vision where it is not adjacent to newly-owned
  tiles. An owned swamp attack source that decays to 0 on an even turn
  additionally hides the traded-away general.
"""
import math
import time
import typing
from dataclasses import dataclass

from Models import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase, Map, Tile, TILE_FOG, TILE_OBSTACLE, TILE_MOUNTAIN
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot
from PerformanceTimer import NS_CONVERTER


@dataclass(slots=True)
class _ExpectedTileState:
    """Independent expectation of a tile's post-trade/post-bonus state, computed
    in the test from pre-trade ground truth using settled server semantics
    (never from simulator internals)."""
    owner: int
    army: int
    isCity: bool
    isGeneral: bool
    isSwamp: bool
    isDesert: bool
    isMountain: bool


# Trade fixture. Player 0 (us) holds a deep western blob around aG20 at (2,5)
# with a lone a60 attack source adjacent to the enemy general bG25 at (13,5).
# Player 1 holds an eastern blob plus a row-5 corridor ending in an owned
# swamp bS22 adjacent to our general - that swamp is what lets our traded-away
# general lose vision on even turns (post-trade halved army 1 -> swamp decay
# -> neutral -> no vision of the old general). Player 2 is an untouched third
# party. Includes odd/even/0/1/large armies, an owned city, desert and swamps.
_TRADE_TILES: typing.Dict[typing.Tuple[int, int], str] = {
    (0, 0): 'cG10', (1, 0): 'c2', (0, 1): 'c3', (0, 2): 'c4',
    (5, 0): 'N5', (10, 1): 'C40', (5, 1): 'M', (9, 3): 'M',
    (1, 1): 'a8', (2, 1): 'a3', (3, 1): 'a1',
    (1, 2): 'a6', (2, 2): 'a0', (3, 2): 'aC5',
    (1, 3): 'a2', (2, 3): 'a9', (3, 3): 'a1',
    (1, 4): 'a4', (2, 4): 'a1', (3, 4): 'a4',
    (1, 5): 'aE9', (2, 5): 'aG20',
    (1, 6): 'a4', (2, 6): 'a1', (3, 6): 'a7',
    (1, 7): 'a5', (2, 7): 'aS2', (3, 7): 'a2',
    (1, 8): 'a6', (2, 8): 'a2', (3, 8): 'a1',
    (13, 6): 'a60',
    (3, 5): 'bS22',
    (4, 5): 'b1', (5, 5): 'b1', (6, 5): 'b1', (7, 5): 'b1', (8, 5): 'b1',
    (9, 5): 'b1', (10, 5): 'b1', (11, 5): 'b1', (12, 5): 'b1',
    (13, 5): 'bG25',
    (12, 1): 'b5', (13, 1): 'b7', (14, 1): 'b2',
    (12, 2): 'bC6', (13, 2): 'b9', (14, 2): 'b3',
    (12, 3): 'b3', (13, 3): 'b11', (14, 3): 'b4',
    (12, 4): 'b8', (14, 4): 'b5',
    (14, 5): 'b1',
    (12, 6): 'b8', (14, 6): 'b2',
    (12, 7): 'bS4', (13, 7): 'b6', (14, 7): 'b7',
    (12, 8): 'b7', (13, 8): 'b1', (14, 8): 'b8',
}

_TRADE_COLS = 15
_TRADE_ROWS = 9

_OUR_ATTACK_XY = (13, 6)
"""Our attack source; orthogonally adjacent to the enemy general at (13,5)."""
_ENEMY_ATTACK_XY = (3, 5)
"""Enemy swamp attack source; orthogonally adjacent to our general at (2,5)."""
_OUR_GENERAL_XY = (2, 5)
_ENEMY_GENERAL_XY = (13, 5)


def _ceil_div2(army: int) -> int:
    """JS Math.round(army * 0.5) for non-negative integers == ceil(army / 2)."""
    return (army + 1) // 2


def _build_trade_map_string(tiles: typing.Dict[typing.Tuple[int, int], str], extra_data: typing.List[str] | None = None) -> str:
    """Renders the tile spec into the txtmap format TextMapLoader parses
    (5-char cells, left-aligned content, header/footer pipe rows)."""
    cell = 5
    header = ''.join('|' + ' ' * (cell - 1) for _ in range(_TRADE_COLS))
    lines = [header]
    for y in range(_TRADE_ROWS):
        row = ''
        for x in range(_TRADE_COLS):
            token = tiles.get((x, y), '')
            row += token.ljust(cell)
        lines.append(row.rstrip())
    lines.append(header)
    if extra_data:
        lines.extend(extra_data)
    return '\n'.join(lines)


def _snapshot_expected(map: MapBase) -> typing.Dict[typing.Tuple[int, int], _ExpectedTileState]:
    """Snapshots every tile's trade-relevant state from a ground-truth map."""
    result: typing.Dict[typing.Tuple[int, int], _ExpectedTileState] = {}
    for tile in map.get_all_tiles():
        result[(tile.x, tile.y)] = _ExpectedTileState(
            owner=tile.player,
            army=tile.army,
            isCity=tile.isCity,
            isGeneral=tile.isGeneral,
            isSwamp=tile.isSwamp,
            isDesert=tile.isDesert,
            isMountain=tile.isMountain)
    return result


def _compute_expected_trade(
        preTiles: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
        ourStart: typing.Tuple[int, int],
        enemyStart: typing.Tuple[int, int],
        ourHalf: bool,
        enemyHalf: bool,
        newTurn: int) -> typing.Dict[typing.Tuple[int, int], _ExpectedTileState]:
    """
    Independent reimplementation of Game.js executeMutualGeneralSwap plus the
    end-of-turn city/army/swamp/desert increments, used to assert the
    simulator/bot world state. ourStart/enemyStart are the two attack source
    tiles (ours captures the enemy general, theirs captures ours).

    @param preTiles: snapshot from _snapshot_expected BEFORE the trade turn.
    @param ourStart: our attack source tile coords.
    @param enemyStart: enemy attack source tile coords.
    @param ourHalf: whether our attack was a half move.
    @param enemyHalf: whether the enemy attack was a half move.
    @param newTurn: the turn number the trade resolves onto (bonuses apply for it).
    @return: expected per-tile state for every tile on the map.
    """
    genA = _OUR_GENERAL_XY
    genB = _ENEMY_GENERAL_XY

    startA = preTiles[ourStart]
    startB = preTiles[enemyStart]
    reserveA = math.ceil(startA.army / 2) if ourHalf else 1
    reserveB = math.ceil(startB.army / 2) if enemyHalf else 1
    sentA = startA.army - reserveA
    sentB = startB.army - reserveB

    # defense on the general being attacked: the defender's own move reduces
    # its army only if it started ON that general (reserve left behind),
    # otherwise the general defends with its full army.
    defenseAtGenB = reserveB if enemyStart == genB else preTiles[genB].army
    defenseAtGenA = reserveA if ourStart == genA else preTiles[genA].army
    capturedGenArmyB = max(0, sentA - defenseAtGenB)
    capturedGenArmyA = max(0, sentB - defenseAtGenA)

    result: typing.Dict[typing.Tuple[int, int], _ExpectedTileState] = {}
    for xy, pre in preTiles.items():
        state = _ExpectedTileState(
            owner=pre.owner,
            army=pre.army,
            isCity=pre.isCity,
            isGeneral=pre.isGeneral,
            isSwamp=pre.isSwamp,
            isDesert=pre.isDesert,
            isMountain=pre.isMountain)
        if xy == genA:
            state.owner = 1
            state.army = capturedGenArmyA
        elif xy == genB:
            state.owner = 0
            state.army = capturedGenArmyB
        elif pre.owner == 0:
            state.owner = 1
            state.army = _ceil_div2(reserveA) if xy == ourStart else _ceil_div2(pre.army)
        elif pre.owner == 1:
            state.owner = 0
            state.army = _ceil_div2(reserveB) if xy == enemyStart else _ceil_div2(pre.army)
        result[xy] = state

    # increments applied for the turn the trade resolves onto (after the swap)
    isCityBonus = newTurn & 1 == 0
    isArmyBonus = newTurn % 50 == 0
    for state in result.values():
        if isCityBonus:
            if state.isGeneral or (state.isCity and state.owner >= 0):
                state.army += 1
            if state.isSwamp and state.owner >= 0:
                state.army -= 1
                if state.army == 0:
                    state.owner = -1
        if isArmyBonus and state.owner >= 0 and not state.isDesert:
            state.army += 1

    return result


def _expected_visible_xy(expected: typing.Dict[typing.Tuple[int, int], _ExpectedTileState], player: int) -> typing.Set[typing.Tuple[int, int]]:
    """Tiles visible to player given expected owners: owned tiles plus the 3x3
    around each (server/sim vision semantics)."""
    owned = {xy for xy, s in expected.items() if s.owner == player}
    visible: typing.Set[typing.Tuple[int, int]] = set(owned)
    for (x, y) in owned:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nxy = (x + dx, y + dy)
                if nxy in expected:
                    visible.add(nxy)
    return visible


def _expected_fog_enemy_histogram(
        expected: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
        visible: typing.Set[typing.Tuple[int, int]],
        enemy: int) -> typing.Dict[int, int]:
    """
    The exact OpponentTracker gather-queue histogram for the enemy after a
    perfect-information general trade: every fog non-city non-general enemy
    land tile contributes its exact post-trade army amount.
    """
    amounts: typing.Dict[int, int] = {}
    for xy, state in expected.items():
        if state.owner != enemy or xy in visible or state.isCity or state.isGeneral or state.isMountain:
            continue
        amounts[state.army] = amounts.get(state.army, 0) + 1
    return amounts


def _expected_fog_city_army(
        expected: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
        visible: typing.Set[typing.Tuple[int, int]],
        enemy: int) -> int:
    """Full raw armies of hidden enemy cities+generals (settled design: the
    trade's fog-city pool holds FULL raw armies, not army-minus-one)."""
    total = 0
    for xy, state in expected.items():
        if state.owner != enemy or xy in visible or state.isMountain:
            continue
        if state.isCity or state.isGeneral:
            total += state.army
    return total


class _ServerScore(typing.TypedDict):
    """Serialized scoreboard entry in a real game_update payload."""
    i: int
    total: int
    tiles: int
    dead: bool


def _server_delta(old: typing.List[int], cur: typing.List[int]) -> typing.List[int]:
    """Port of shared/Terrain.js Terrain.delta: [match, mismatch, *values ...]."""
    if not old or len(old) != len(cur):
        return [0, len(cur)] + list(cur)

    out: typing.List[int] = []
    in_match = True
    length = 0
    for i in range(len(cur)):
        if in_match and old[i] != cur[i]:
            out.append(length)
            length = 0
            in_match = False
        elif not in_match and old[i] == cur[i]:
            out.append(length)
            out.extend(cur[i - length:i])
            in_match = True
            length = 0
        length += 1
    out.append(length)
    if not in_match:
        out.extend(cur[len(cur) - length:])
    return out


def _serialize_player_view(
        truth: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
        player: int) -> typing.Tuple[typing.List[int], typing.List[int], typing.List[int], typing.List[int], typing.List[_ServerScore]]:
    """
    Builds the serialized map payload a real server would emit for `player`
    from ground truth: fog-masked armies/tile-owner arrays, visible city index
    list, generals array (-1 for hidden), and scoreboard entries.

    @return: (armies, tileOwners, cities, generals, scores)
    """
    size = _TRADE_COLS * _TRADE_ROWS
    visible = _expected_visible_xy(truth, player)
    armies = [0] * size
    owners = [TILE_FOG] * size
    cities: typing.List[int] = []
    generals: typing.List[int] = [-1, -1, -1]
    scores: typing.List[_ServerScore] = [
        {'i': 0, 'total': 0, 'tiles': 0, 'dead': False},
        {'i': 1, 'total': 0, 'tiles': 0, 'dead': False},
        {'i': 2, 'total': 0, 'tiles': 0, 'dead': False},
    ]
    for (x, y), state in truth.items():
        idx = y * _TRADE_COLS + x
        if state.owner >= 0:
            scores[state.owner]['total'] += state.army
            scores[state.owner]['tiles'] += 1
        if state.isCity:
            # a real server hides unseen cities as fog obstacles; all cities are
            # marked obstacle when fogged, but only visible ones enter cities_diff
            if xy_in(visible, x, y):
                cities.append(idx)
        if state.isGeneral and state.owner >= 0 and xy_in(visible, x, y):
            generals[state.owner] = idx
        if xy_in(visible, x, y):
            armies[idx] = state.army
            if state.isMountain:
                owners[idx] = TILE_MOUNTAIN
            else:
                owners[idx] = state.owner if state.owner >= 0 else TILE_EMPTY
        else:
            armies[idx] = 0
            owners[idx] = TILE_OBSTACLE if (state.isCity or state.isMountain) else TILE_FOG
    return armies, owners, cities, generals, scores


def xy_in(visible: typing.Set[typing.Tuple[int, int]], x: int, y: int) -> bool:
    """Whether (x,y) is in the visible-tile set."""
    return (x, y) in visible


class GeneralTradeTests(TestBase):
    def setUp(self) -> None:
        """Determinism: pin MapBase.DO_NOT_RANDOMIZE for the trade fixtures."""
        super().setUp()
        self._prev_do_not_randomize = MapBase.DO_NOT_RANDOMIZE
        MapBase.DO_NOT_RANDOMIZE = True
        self.addCleanup(self._restore_randomize)

    def _restore_randomize(self) -> None:
        """addCleanup restore of MapBase.DO_NOT_RANDOMIZE."""
        MapBase.DO_NOT_RANDOMIZE = self._prev_do_not_randomize

    def _load_trade_map(self, turn: int = 49, teams: str | None = None) -> typing.Tuple[MapBase, Tile, Tile]:
        """Loads the trade fixture ground-truth map and returns
        (map, ourGeneralTile, enemyGeneralTile)."""
        extra = ['turn=' + str(turn), 'player_index=0', 'aTiles=24', 'bTiles=31', 'cTiles=4']
        if teams is not None:
            extra.append('teams=' + teams)
        mapData = _build_trade_map_string(_TRADE_TILES, extra)
        map, general = self.load_map_and_general_from_string(mapData, turn=turn, player_index=0)
        enemyGeneral = map.generals[1]
        return map, general, enemyGeneral

    def _run_trade_turn_sim(self, turn_load: int, our_half: bool = False, enemy_half: bool = False, our_source_army: int | None = None, enemy_source_army: int | None = None) -> typing.Tuple[GameSimulator, typing.Dict[typing.Tuple[int, int], _ExpectedTileState]]:
        """Runs the trade turn on a plain GameSimulator and returns
        (sim, expectedPostTradeState) computed independently from pre-trade truth."""
        map, general, enemyGeneral = self._load_trade_map(turn_load)
        # optional source-army overrides (for priority parity / half-move variants)
        if our_source_army is not None:
            map.GetTile(*_OUR_ATTACK_XY).army = our_source_army
        if enemy_source_army is not None:
            map.GetTile(*_ENEMY_ATTACK_XY).army = enemy_source_army
        preTiles = _snapshot_expected(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        sim = GameSimulator(map)
        simMap = sim.sim_map
        sim.set_next_move(0, Move(simMap.GetTile(*_OUR_ATTACK_XY), simMap.GetTile(*_ENEMY_GENERAL_XY), our_half))
        sim.set_next_move(1, Move(simMap.GetTile(*_ENEMY_ATTACK_XY), simMap.GetTile(*_OUR_GENERAL_XY), enemy_half))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)

        newTurn = turn_load + 1
        expected = _compute_expected_trade(preTiles, _OUR_ATTACK_XY, _ENEMY_ATTACK_XY, our_half, enemy_half, newTurn)
        return sim, expected

    def _assert_expected_world_state(
            self,
            simMap: MapBase,
            expected: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
            msg: str) -> None:
        """Asserts every tile's owner/army/isGeneral/isCity against the
        independent trade expectation. Tests test_GeneralTrade - this is the
        core world-state verification for the mutual general swap."""
        for (x, y), exp in expected.items():
            tile = simMap.GetTile(x, y)
            self.assertEqual(exp.owner, tile.player, f'{msg}: tile {x},{y} owner {tile.player} != expected {exp.owner}')
            self.assertEqual(exp.army, tile.army, f'{msg}: tile {x},{y} army {tile.army} != expected {exp.army}')
            self.assertEqual(exp.isGeneral, tile.isGeneral, f'{msg}: tile {x},{y} isGeneral {tile.isGeneral} != expected {exp.isGeneral}')
            self.assertEqual(exp.isCity, tile.isCity, f'{msg}: tile {x},{y} isCity {tile.isCity} != expected {exp.isCity}')

    def test_sim__general_trade__world_state(self) -> None:
        """Server: both moves would capture each other's general -> swap, both
        alive, non-gen land halved, generals keep isGeneral + unhalved capture
        leftovers, bonuses applied after the swap for the new turn."""
        cases = [
            # (loadTurn, ourHalf, enemyHalf, ourSrcArmy, enemySrcArmy, label)
            # turn the trade resolves onto is loadTurn+1:
            # 51 = odd/no bonus, 52 = even city+swamp only, 100 = city+army bonus
            (50, False, False, None, None, 'odd_no_bonus'),
            (51, False, False, None, None, 'even_city_bonus'),
            (99, False, False, None, None, 'army_and_city_bonus'),
            # half attacker: our a60 half-move still sends 30 > 25
            (50, True, False, None, None, 'odd_no_bonus__our_half'),
            # enemy half-move: swamp at 42 sends 21 > 20
            (99, False, True, None, 42, 'army_and_city_bonus__enemy_half'),
            # priority parity: enemy source larger so enemy move resolves first
            (50, False, False, None, 70, 'odd_no_bonus__enemy_priority'),
        ]
        for loadTurn, ourHalf, enemyHalf, ourSrcArmy, enemySrcArmy, label in cases:
            with self.subTest(variant=label):
                sim, expected = self._run_trade_turn_sim(loadTurn, our_half=ourHalf, enemy_half=enemyHalf, our_source_army=ourSrcArmy, enemy_source_army=enemySrcArmy)
                simMap = sim.sim_map

                # both players survive a trade; generals swap positions and KEEP
                # isGeneral (no city conversion, no capture/death)
                self.assertFalse(sim.players[0].dead, f'{label}: we should survive the trade')
                self.assertFalse(sim.players[1].dead, f'{label}: enemy should survive the trade')
                self.assertFalse(sim.players[2].dead, f'{label}: third player should be unaffected')
                self.assertEqual(_ENEMY_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y), f'{label}: our general should move to the enemy general tile')
                self.assertEqual(_OUR_GENERAL_XY, (simMap.generals[1].x, simMap.generals[1].y), f'{label}: enemy general should move to our old general tile')

                self._assert_expected_world_state(simMap, expected, label)

                # score/tile totals follow the swapped land + unhalved generals
                for p in (0, 1, 2):
                    expectedScore = sum(s.army for s in expected.values() if s.owner == p)
                    expectedTiles = sum(1 for s in expected.values() if s.owner == p)
                    self.assertEqual(expectedScore, simMap.scores[p].total, f'{label}: p{p} scoreboard total')
                    self.assertEqual(expectedTiles, simMap.scores[p].tiles, f'{label}: p{p} scoreboard tiles')

    def test_sim__general_trade__bot_fog_state(self) -> None:
        """
        Full bot E2E: bot initialized BEFORE the trade, both capture moves
        submitted via normal simHost queues (map.last_player_index_submitted_move
        set), trade resolves, fog updates apply, then bot turn prep runs. Asserts
        the bot's map generals/players/old-tiles/lostSight and the
        OpponentTracker fog accounting all reflect the trade.
        """
        # odd turn: enemy swamp source survives -> our old gen stays visible
        # even turn: swamp decays -> our old gen goes fog (hidden old general)
        # also: turn100 army+city bonus, our half-move, enemy half-move
        cases = [
            # (loadTurn, oldGenHidden, ourHalf, enemyHalf, ourSrcArmy, enemySrcArmy)
            (50, False, False, False, None, None),
            (51, True, False, False, None, None),
            (99, True, False, False, None, None),
            (50, False, True, False, None, None),
            # enemy half-move on swamp 44: reserve 22 stays ours -> gen visible
            (99, False, False, True, None, 44),
        ]
        for loadTurn, oldGenHidden, ourHalf, enemyHalf, ourSrcArmy, enemySrcArmy in cases:
            with self.subTest(loadTurn=loadTurn, oldGenHidden=oldGenHidden, ourHalf=ourHalf, enemyHalf=enemyHalf):
                map, general, enemyGeneral = self._load_trade_map(loadTurn)
                if ourSrcArmy is not None:
                    map.GetTile(*_OUR_ATTACK_XY).army = ourSrcArmy
                if enemySrcArmy is not None:
                    map.GetTile(*_ENEMY_ATTACK_XY).army = enemySrcArmy
                preTiles = _snapshot_expected(map)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
                bot: EklipZBot = simHost.get_bot(0)
                playerMap = simHost.get_player_map(0)

                # seed stale pre-trade enemy queue contents to prove the trade
                # reseeds (replaces) the queue rather than appending to it
                bot.opponent_tracker.get_player_gather_queue(1).set_amount_for_size(37, 2)

                # known capture moves via normal queues -> last_player_index_submitted_move set
                ourMove = f'{_OUR_ATTACK_XY[0]},{_OUR_ATTACK_XY[1]}->{_ENEMY_GENERAL_XY[0]},{_ENEMY_GENERAL_XY[1]}'
                enemyMove = f'{_ENEMY_ATTACK_XY[0]},{_ENEMY_ATTACK_XY[1]}->{_OUR_GENERAL_XY[0]},{_OUR_GENERAL_XY[1]}'
                if ourHalf:
                    ourMove += 'z'
                if enemyHalf:
                    enemyMove += 'z'
                simHost.queue_player_moves_str(0, ourMove)
                simHost.queue_player_moves_str(1, enemyMove)
                simHost.execute_turn(run_real_time=False)

                newTurn = loadTurn + 1
                expected = _compute_expected_trade(preTiles, _OUR_ATTACK_XY, _ENEMY_ATTACK_XY, ourHalf, enemyHalf, newTurn)
                visible = _expected_visible_xy(expected, 0)

                # run bot turn prep on the post-trade map (opponent tracker + map analysis)
                simHost.bot_hosts[0].receive_update_no_move(playerMap, time.time_ns() / NS_CONVERTER)

                self._assert_bot_map_post_trade(playerMap, preTiles, expected, visible, oldGenHidden, f't{loadTurn}')
                self._assert_bot_tracker_post_trade(bot, playerMap, expected, visible, 1, f't{loadTurn}')

    def _assert_bot_map_post_trade(
            self,
            playerMap: MapBase,
            preTiles: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
            expected: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
            visible: typing.Set[typing.Tuple[int, int]],
            oldGenHidden: bool,
            msg: str) -> None:
        """Asserts the bot's fog-of-war map reflects the general trade:
        new/old generals, exact owners+armies on every transferred tile
        (including fogged old land), lostSight flags on newly hidden tiles."""
        # map.generals and players[].general refer to the NEW general identities
        ourGenTile = playerMap.GetTile(*_ENEMY_GENERAL_XY)
        enemyGenTile = playerMap.GetTile(*_OUR_GENERAL_XY)
        self.assertEqual(ourGenTile, playerMap.generals[0], f'{msg}: map.generals[0] should be our NEW general at {_ENEMY_GENERAL_XY}')
        self.assertEqual(ourGenTile, playerMap.players[0].general, f'{msg}: players[0].general should be our NEW general')
        self.assertEqual(enemyGenTile, playerMap.generals[1], f'{msg}: map.generals[1] should be the enemy NEW general at {_OUR_GENERAL_XY}')
        self.assertEqual(enemyGenTile, playerMap.players[1].general, f'{msg}: players[1].general should be the enemy NEW general')

        # our old general is an ENEMY general in fog (or visible when the
        # transferred swamp source survives on odd turns), never a city
        self.assertTrue(enemyGenTile.isGeneral, f'{msg}: old general should still be a general')
        self.assertFalse(enemyGenTile.isCity, f'{msg}: old general must not become a city on trade')
        self.assertEqual(1, enemyGenTile.player, f'{msg}: old general should be enemy-owned')
        self.assertEqual(not oldGenHidden, enemyGenTile.visible, f'{msg}: old general visibility')
        self.assertEqual(expected[_OUR_GENERAL_XY].army, enemyGenTile.army, f'{msg}: old general army')
        # our new general: visible, ours, unhalved capture leftover (+bonus)
        self.assertTrue(ourGenTile.visible, f'{msg}: new general should be visible')
        self.assertTrue(ourGenTile.isGeneral, f'{msg}: new general should still be a general')
        self.assertFalse(ourGenTile.isCity, f'{msg}: new general must not be a city')
        self.assertEqual(0, ourGenTile.player, f'{msg}: new general should be ours')
        self.assertEqual(expected[_ENEMY_GENERAL_XY].army, ourGenTile.army, f'{msg}: new general army')

        # EVERY old owned tile now has the correct enemy owner and EXACT army,
        # even in fog (halved land, attack-source reserve, even/odd halving,
        # post-trade city/army/swamp/desert effects). Tiles that were never
        # ours and are not visible post-trade (unseen neutral/third-party land)
        # carry no information the bot could possibly have, so they are not
        # asserted on army/owner - only their visibility is verified.
        for (x, y), exp in expected.items():
            tile = playerMap.GetTile(x, y)
            shouldBeVisible = (x, y) in visible
            self.assertEqual(shouldBeVisible, tile.visible, f'{msg}: tile {x},{y} visible {tile.visible} != expected {shouldBeVisible}')
            wasOurs = preTiles[(x, y)].owner == 0
            if not shouldBeVisible and not wasOurs:
                continue
            self.assertEqual(exp.owner, tile.player, f'{msg}: tile {x},{y} owner {tile.player} != expected {exp.owner}')
            self.assertEqual(exp.army, tile.army, f'{msg}: tile {x},{y} army {tile.army} != expected {exp.army}')
            self.assertEqual(exp.isGeneral, tile.isGeneral, f'{msg}: tile {x},{y} isGeneral')
            self.assertEqual(exp.isCity, tile.isCity, f'{msg}: tile {x},{y} isCity')
            # tiles that were ours last turn and are now hidden must retain lostSight
            if exp.owner == 1 and not shouldBeVisible:
                self.assertTrue(tile.delta.lostSight, f'{msg}: tile {x},{y} lost vision of traded-away land should retain lostSight')

    def _assert_bot_tracker_post_trade(
            self,
            bot: EklipZBot,
            playerMap: MapBase,
            expected: typing.Dict[typing.Tuple[int, int], _ExpectedTileState],
            visible: typing.Set[typing.Tuple[int, int]],
            enemy: int,
            msg: str) -> None:
        """Asserts the OpponentTracker replaced (not appended) its fog model of
        the enemy with the perfect-information trade outcome: exact gather
        queue histogram of fog noncity/nongen enemy tiles, full raw armies of
        hidden cities+generals in the fog-city pool, and total conservation
        against the enemy scoreboard."""
        queue = bot.opponent_tracker.get_player_gather_queue(enemy)
        expectedHist = _expected_fog_enemy_histogram(expected, visible, enemy)

        # exact histogram - stale pre-trade enemy queue contents were REPLACED
        self.assertEqual(expectedHist, queue.get_amount_dict(), f'{msg}: enemy gather queue histogram')
        self.assertEqual(sum(expectedHist.values()), queue.length, f'{msg}: enemy gather queue length')
        self.assertEqual(sum(v for amt, v in expectedHist.items() if amt > 1), queue.gatherable_length, f'{msg}: enemy gather queue gatherable_length')
        self.assertEqual(sum(amt * v for amt, v in expectedHist.items()), queue.total_sum, f'{msg}: enemy gather queue total_sum')
        for amt, count in queue.get_amount_dict().items():
            self.assertGreaterEqual(count, 0, f'{msg}: negative queue count for amt {amt}')

        # fog-city pool: FULL raw armies + exact count of hidden enemy
        # cities+generals
        enemyStats = bot.opponent_tracker.get_current_cycle_stats_by_player(enemy)
        expectedFogCity = _expected_fog_city_army(expected, visible, enemy)
        expectedFogCityCount = len([1 for (x, y), s in expected.items()
                                    if s.owner == enemy and (x, y) not in visible
                                    and (s.isCity or s.isGeneral)])
        self.assertEqual(expectedFogCity, enemyStats.approximate_fog_city_army, f'{msg}: fog city+gen army pool')
        self.assertEqual(expectedFogCityCount, enemyStats.fog_city_count, f'{msg}: fog city+gen count')

        # total conservation vs the enemy scoreboard: visible raw armies +
        # queue total + fog city pool + fog army available == enemy score
        enemyPlayer = playerMap.players[enemy]
        visibleArmy = sum(t.army for t in enemyPlayer.tiles if t.visible)
        enemyScore = enemyPlayer.score
        self.assertEqual(
            enemyScore,
            visibleArmy + queue.total_sum + enemyStats.approximate_fog_city_army + enemyStats.approximate_fog_army_available_total,
            f'{msg}: tracker conservation vs enemy scoreboard')
        # all enemy fog army is accounted exactly; nothing auto-gathered
        self.assertEqual(0, enemyStats.approximate_fog_army_available_total, f'{msg}: nothing should be auto-gathered in a perfect-info trade')

        # bot identity: bot.general / bot.player refer to the NEW gen/identity
        self.assertEqual(playerMap.generals[0], bot.general, f'{msg}: bot.general should be the NEW general')
        self.assertEqual(0, bot.player.index, f'{msg}: bot.player should still be us')
        # all general-dependent trackers rebound to the NEW general
        self.assertEqual(bot.general, bot.armyTracker.general, f'{msg}: armyTracker.general rebind')
        if bot.cityAnalyzer is not None:
            self.assertEqual(bot.general, bot.cityAnalyzer.general, f'{msg}: cityAnalyzer.general rebind')
        if bot.board_analysis is not None:
            self.assertEqual(bot.general, bot.board_analysis.general, f'{msg}: board_analysis.general rebind')
            self.assertEqual(0, bot.board_analysis.general_distances[bot.general], f'{msg}: new gen distance 0')
        # the traded enemy's gen position is a known singleton now (our old gen)
        enemyGenTile = playerMap.generals[enemy]
        self.assertIsNotNone(enemyGenTile, f'{msg}: enemy general tile should be known')
        validEnemyPositions = bot.armyTracker.valid_general_positions_by_player[enemy]
        for tile in playerMap.get_all_tiles():
            if tile is not enemyGenTile:
                self.assertFalse(validEnemyPositions[tile], f'{msg}: {tile} should not be a valid enemy gen position')
        # the bot's expected enemy gen location re-points to the known tile,
        # not the (now ours) old enemy gen location
        if bot.targetPlayer == enemy:
            self.assertEqual(enemyGenTile, bot.targetPlayerExpectedGeneralLocation, f'{msg}: expected enemy gen location should be the known traded tile')

    def _build_live_map(self, preTiles: typing.Dict[typing.Tuple[int, int], _ExpectedTileState], turn: int, oneVOne: bool = False) -> Map:
        """Constructs a live Map as if the server sent the pre-trade fog game
        state for player 0 (genuine map_diff/cities_diff/generals data)."""
        armies, owners, cities, generals, scores = _serialize_player_view(preTiles, 0)
        if oneVOne:
            generals = generals[:2]
            scores = scores[:2]
        fullMap = [_TRADE_COLS, _TRADE_ROWS] + armies + owners
        startData = {
            'playerIndex': 0,
            'usernames': ['a', 'b'] if oneVOne else ['a', 'b', 'c'],
            'teams': [0, 1] if oneVOne else [0, 1, 2],
            'replay_id': 'general_trade_test',
            'options': {},
            'playerColors': [0, 1] if oneVOne else [0, 1, 2],
            'swamps': [y * _TRADE_COLS + x for (x, y), s in preTiles.items() if s.isSwamp],
        }
        data = {
            'turn': turn,
            'map_diff': [0, len(fullMap)] + fullMap,
            'cities_diff': [0, len(cities)] + cities,
            'deserts_diff': [0, sum(1 for s in preTiles.values() if s.isDesert)] + [y * _TRADE_COLS + x for (x, y), s in preTiles.items() if s.isDesert],
            'generals': generals,
            'scores': scores,
        }
        return Map(startData, data)

    def _apply_trade_server_update(self, liveMap: Map, postTiles: typing.Dict[typing.Tuple[int, int], _ExpectedTileState], turn: int) -> None:
        """Applies a post-trade game_update to the live map with genuine server
        fog data (diffs computed against the previously sent state)."""
        armies, owners, cities, generals, scores = _serialize_player_view(postTiles, 0)
        size = _TRADE_COLS * _TRADE_ROWS
        newMap = [_TRADE_COLS, _TRADE_ROWS] + armies + owners
        data = {
            'turn': turn,
            'map_diff': _server_delta(liveMap._map_private, newMap),
            'cities_diff': _server_delta(liveMap._cities_private, cities),
            'deserts_diff': _server_delta(liveMap._deserts_private, [y * _TRADE_COLS + x for (x, y), s in postTiles.items() if s.isDesert]),
            'generals': generals,
            'scores': scores,
        }
        liveMap.apply_server_update(data)

    def test_live_map__general_trade__apply_server_update(self) -> None:
        """
        Independent live-map regression: a Map driven only by genuine server
        game_update data (map_diff/cities_diff/generals fog payloads - not the
        simulator's omniscient update path) must detect the trade when the old
        general goes fog while the previously-enemy general keeps isGeneral and
        changes to our owner.
        """
        # (loadTurn, oldGenHidden, ourHalf, staleQueue, oneVOne)
        cases = [
            (51, True, False, False, False),
            (50, False, False, False, False),
            (99, True, False, False, False),   # turn100: army+city bonus, swamp hides old gen
            (51, True, True, False, False),    # our half move
            (51, True, False, True, False),    # stale pre-trade enemy queue seed
            (51, True, False, False, True),    # true 1v1 (no third party)
        ]
        for loadTurn, oldGenHidden, ourHalf, staleQueue, oneVOne in cases:
            with self.subTest(loadTurn=loadTurn, oldGenHidden=oldGenHidden, ourHalf=ourHalf, staleQueue=staleQueue, oneVOne=oneVOne):
                if oneVOne:
                    tiles = {xy: tok for xy, tok in _TRADE_TILES.items() if not tok.startswith('c')}
                    mapData = _build_trade_map_string(tiles, ['turn=' + str(loadTurn), 'player_index=0', 'aTiles=23', 'bTiles=24'])
                    map, general = self.load_map_and_general_from_string(mapData, turn=loadTurn, player_index=0)
                    enemyGeneral = map.generals[1]
                else:
                    map, general, enemyGeneral = self._load_trade_map(loadTurn)
                preTiles = _snapshot_expected(map)

                liveMap = self._build_live_map(preTiles, loadTurn, oneVOne=oneVOne)
                ourSrc = liveMap.GetTile(*_OUR_ATTACK_XY)
                ourDst = liveMap.GetTile(*_ENEMY_GENERAL_XY)
                liveMap.last_player_index_submitted_move = (ourSrc, ourDst, ourHalf)

                bot = EklipZBot()
                bot.initialize_from_map_for_first_time(liveMap)
                with bot.perf_timer.begin_move(liveMap.turn):
                    bot.init_turn()

                if staleQueue:
                    bot.opponent_tracker.get_player_gather_queue(1).set_amount_for_size(37, 2)

                newTurn = loadTurn + 1
                expected = _compute_expected_trade(preTiles, _OUR_ATTACK_XY, _ENEMY_ATTACK_XY, ourHalf, False, newTurn)
                visible = _expected_visible_xy(expected, 0)
                self._apply_trade_server_update(liveMap, expected, newTurn)

                with bot.perf_timer.begin_move(liveMap.turn):
                    bot.init_turn()

                self._assert_bot_map_post_trade(liveMap, preTiles, expected, visible, oldGenHidden, f'live t{loadTurn}')
                self._assert_bot_tracker_post_trade(bot, liveMap, expected, visible, 1, f'live t{loadTurn}')
                if oneVOne:
                    # true 1v1: the trade is perfect info, so the EXACT
                    # transferred cities+general count is known on both players
                    expectedCities0 = sum(1 for s in expected.values() if s.owner == 0 and (s.isCity or s.isGeneral))
                    expectedCities1 = sum(1 for s in expected.values() if s.owner == 1 and (s.isCity or s.isGeneral))
                    self.assertEqual(expectedCities0, liveMap.players[0].cityCount, 'transferred city+gen count (us)')
                    self.assertEqual(expectedCities1, liveMap.players[1].cityCount, 'transferred city+gen count (enemy)')
                if staleQueue:
                    self.assertEqual(0, bot.opponent_tracker.get_player_gather_queue(1).get_amount_dict().get(37, 0),
                                     'stale pre-trade queue marker must be replaced by exact reseed')

    def test_sim__general_trade__negative_control_tie_fails(self) -> None:
        """
        Negative control: the enemy's attack only TIES our general's defense
        (sent == defense, not >), so it cannot capture - the only successful
        capture is ours, resolving as an ordinary general kill (enemy dead,
        land halved via normal capture, no swap).
        """
        map, general, enemyGeneral = self._load_trade_map(50)
        preTiles = _snapshot_expected(map)
        # enemy swamp at 21 -> sent 20 == genA defense 20 -> tie, no capture.
        # 21 < our 60 source so our move resolves first regardless of parity.
        enemySrc = map.GetTile(*_ENEMY_ATTACK_XY)
        self.assertEqual(22, enemySrc.army)
        enemySrc.army = 21

        self.enable_search_time_limits_and_disable_debug_asserts()
        sim = GameSimulator(map)
        simMap = sim.sim_map
        sim.set_next_move(0, Move(simMap.GetTile(*_OUR_ATTACK_XY), simMap.GetTile(*_ENEMY_GENERAL_XY)))
        sim.set_next_move(1, Move(simMap.GetTile(*_ENEMY_ATTACK_XY), simMap.GetTile(*_OUR_GENERAL_XY)))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)

        # ordinary capture: we killed the enemy general, they are dead, our
        # general stays put, their land is halved onto us - NO trade/swap
        self.assertTrue(sim.players[1].dead)
        self.assertFalse(sim.players[0].dead)
        self.assertEqual(_OUR_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y))
        # captured general becomes our city, not a swapped general
        self.assertTrue(simMap.GetTile(*_ENEMY_GENERAL_XY).isCity)
        self.assertFalse(simMap.GetTile(*_ENEMY_GENERAL_XY).isGeneral)
        self.assertEqual(0, simMap.GetTile(*_ENEMY_GENERAL_XY).player)
        # our own general was tied at 20 defense but never attacked first, so stays 20
        self.assertEqual(0, simMap.GetTile(*_OUR_GENERAL_XY).player)
        self.assertEqual(20, simMap.GetTile(*_OUR_GENERAL_XY).army)

    def test_sim__general_trade__negative_control_allied(self) -> None:
        """
        Negative control: when the two "attacking" players are teammates their
        general moves are just reinforcements - no trade/swap, no deaths.
        """
        map, general, enemyGeneral = self._load_trade_map(50, teams='1,1,2')

        self.enable_search_time_limits_and_disable_debug_asserts()
        sim = GameSimulator(map)
        simMap = sim.sim_map
        sim.set_next_move(0, Move(simMap.GetTile(*_OUR_ATTACK_XY), simMap.GetTile(*_ENEMY_GENERAL_XY)))
        sim.set_next_move(1, Move(simMap.GetTile(*_ENEMY_ATTACK_XY), simMap.GetTile(*_OUR_GENERAL_XY)))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)

        # allied general attacks merely add the sent army into the allied
        # general - no ownership changes, no swap, nobody dies
        self.assertFalse(sim.players[0].dead)
        self.assertFalse(sim.players[1].dead)
        self.assertEqual(_OUR_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y))
        self.assertEqual(_ENEMY_GENERAL_XY, (simMap.generals[1].x, simMap.generals[1].y))
        self.assertEqual(0, simMap.GetTile(*_OUR_GENERAL_XY).player)
        self.assertEqual(1, simMap.GetTile(*_ENEMY_GENERAL_XY).player)
        self.assertEqual(20 + 21, simMap.GetTile(*_OUR_GENERAL_XY).army)
        self.assertEqual(25 + 59, simMap.GetTile(*_ENEMY_GENERAL_XY).army)
        self.assertEqual(1, simMap.GetTile(*_ENEMY_ATTACK_XY).player)
        self.assertEqual(1, simMap.GetTile(*_ENEMY_ATTACK_XY).army)
        self.assertEqual(1, simMap.GetTile(*_OUR_ATTACK_XY).army)

    def test_sim__general_trade__adjacent_generals_source_moves(self) -> None:
        """
        Dedicated general-source variant: when both moves start ON the
        generals themselves (adjacent generals attacking each other), the
        'defense' each general leaves is only its own move reserve (1 for a
        full move, ceil(army/2) for a half move), and the sent army transfers
        to the captured general UNHALVED minus that reserve - server
        executeMutualGeneralSwap's general-source special case.
        """
        # minimal adjacent-generals fixture: aG30 at (2,2), bG40 at (3,2)
        tiles = {
            (2, 2): 'aG30', (3, 2): 'bG40',
            (1, 2): 'a8', (2, 1): 'a6', (4, 2): 'b5', (3, 1): 'b7',
        }
        mapData = self._build_small_map_string(tiles, 6, 4, ['turn=50', 'player_index=0', 'aTiles=3', 'bTiles=3'])
        for ourHalf, enemyHalf, label in [(False, False, 'full_moves'), (True, False, 'our_half')]:
            with self.subTest(variant=label):
                map, general = self.load_map_and_general_from_string(mapData, turn=50, player_index=0)
                preTiles = _snapshot_expected(map)
                self.enable_search_time_limits_and_disable_debug_asserts()
                sim = GameSimulator(map)
                simMap = sim.sim_map
                sim.set_next_move(0, Move(simMap.GetTile(2, 2), simMap.GetTile(3, 2), ourHalf))
                sim.set_next_move(1, Move(simMap.GetTile(3, 2), simMap.GetTile(2, 2), enemyHalf))
                sim.execute_turn(dont_require_all_players_to_move=True)

                # expected values for the general-source case, computed
                # independently: defense each gen leaves is its own reserve
                resA = (30 + 1) // 2 if ourHalf else 1
                resB = (40 + 1) // 2 if enemyHalf else 1
                sentA = 30 - resA
                sentB = 40 - resB
                capturedA = max(0, sentB - resA)
                capturedB = max(0, sentA - resB)

                self.assertFalse(sim.players[0].dead, f'{label}: we survive')
                self.assertFalse(sim.players[1].dead, f'{label}: enemy survives')
                # both gens exchanged, unhalved capture leftovers, still generals
                genATile = simMap.GetTile(2, 2)
                genBTile = simMap.GetTile(3, 2)
                self.assertEqual(1, genATile.player, f'{label}: our gen tile goes to enemy')
                self.assertEqual(capturedA, genATile.army, f'{label}: enemy gen leftover unhalved')
                self.assertTrue(genATile.isGeneral, f'{label}: stays a general')
                self.assertFalse(genATile.isCity, f'{label}: no city conversion')
                self.assertEqual(0, genBTile.player, f'{label}: enemy gen tile comes to us')
                self.assertEqual(capturedB, genBTile.army, f'{label}: our gen leftover unhalved')
                self.assertTrue(genBTile.isGeneral, f'{label}: stays a general')
                self.assertEqual((genBTile.x, genBTile.y), (simMap.generals[0].x, simMap.generals[0].y))
                self.assertEqual((genATile.x, genATile.y), (simMap.generals[1].x, simMap.generals[1].y))
                # non-gen land still halves+swaps
                self.assertEqual(1, simMap.GetTile(1, 2).player)
                self.assertEqual(4, simMap.GetTile(1, 2).army)
                self.assertEqual(0, simMap.GetTile(4, 2).player)
                self.assertEqual(3, simMap.GetTile(4, 2).army)

        # player-map verification: drive the same general-source swap through a
        # real GameSimulatorHost so the fog update + trade detection paths run
        map2, general2 = self.load_map_and_general_from_string(mapData, turn=50, player_index=0)
        simHost = GameSimulatorHost(map2, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        simHost.queue_player_moves_str(0, '2,2->3,2')
        simHost.queue_player_moves_str(1, '3,2->2,2')
        simHost.execute_turn(run_real_time=False)
        playerMap = simHost.get_player_map(0)
        self.assertEqual((3, 2), (playerMap.generals[0].x, playerMap.generals[0].y), 'player map should show our NEW general on the enemy tile')
        self.assertEqual((2, 2), (playerMap.generals[1].x, playerMap.generals[1].y), 'player map should show the enemy NEW general on our old tile')
        self.assertTrue(playerMap.GetTile(3, 2).isGeneral)
        self.assertTrue(playerMap.GetTile(2, 2).isGeneral)
        self.assertEqual(0, playerMap.GetTile(3, 2).player)
        self.assertEqual(1, playerMap.GetTile(2, 2).player)

    def _build_small_map_string(self, tiles: typing.Dict[typing.Tuple[int, int], str], cols: int, rows: int, extra_data: typing.List[str] | None = None) -> str:
        """Renders an arbitrary small tile spec into txtmap format (same cell
        format as _build_trade_map_string, parameterizable size)."""
        cell = 5
        header = ''.join('|' + ' ' * (cell - 1) for _ in range(cols))
        lines = [header]
        for y in range(rows):
            row = ''
            for x in range(cols):
                token = tiles.get((x, y), '')
                row += token.ljust(cell)
            lines.append(row.rstrip())
        lines.append(header)
        if extra_data:
            lines.extend(extra_data)
        return '\n'.join(lines)

    def test_sim__general_trade__observer_map_and_third_party_move(self) -> None:
        """
        A trade between two OTHER players: the observer's map must detect the
        swap signature (living player whose visible land all flipped to one
        enemy) without rebinding its own general, and an unrelated third-party
        move submitted the same turn must still resolve normally through the
        inference machinery (scoped trade skip, not a whole-turn skip).
        """
        map, general, enemyGeneral = self._load_trade_map(50)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        obsMap = simHost.get_player_map(2)

        simHost.queue_player_moves_str(0, f'{_OUR_ATTACK_XY[0]},{_OUR_ATTACK_XY[1]}->{_ENEMY_GENERAL_XY[0]},{_ENEMY_GENERAL_XY[1]}')
        simHost.queue_player_moves_str(1, f'{_ENEMY_ATTACK_XY[0]},{_ENEMY_ATTACK_XY[1]}->{_OUR_GENERAL_XY[0]},{_OUR_GENERAL_XY[1]}')
        # p2's own independent move on the same turn: capture the neutral (2,0)
        simHost.queue_player_moves_str(2, '1,0->2,0')
        simHost.execute_turn(run_real_time=False)

        # confirm p2 saw >=3 confirmed-visible flips (required for detection)
        confirmedFlips = [t for t in obsMap.get_all_tiles()
                          if t.delta.oldOwner == 0 and t.delta.newOwner == 1 and t.was_visible_last_turn()]
        self.assertGreaterEqual(len(confirmedFlips), 3, 'observer fixture must see >=3 pre-visible flips')

        # p2's real move resolved in the true world state
        self.assertEqual(2, simHost.sim.sim_map.GetTile(2, 0).player, 'third-party move must still execute during a trade turn')
        # and the observer's map still inferred p2's move (not skipped)
        obsMove = obsMap.players[2].last_move
        self.assertIsNotNone(obsMove, 'observer map should record p2\'s move this turn')
        self.assertEqual((1, 0), (obsMove[0].x, obsMove[0].y), 'observer move source')
        self.assertEqual((2, 0), (obsMove[1].x, obsMove[1].y), 'observer move dest')
        self.assertEqual(1, obsMap.GetTile(2, 0).army, 'observer map move dest army')

        # observer detection fired: p2 sees a living player whose visible land
        # all flipped to a single enemy (both scoreboard-alive)
        priorEnemyCityCount = obsMap.players[1].cityCount
        trade = obsMap.general_trade
        if trade is not None:
            self.assertIn(trade.player, (0, 1))
            self.assertIn(trade.opponent, (0, 1))
            # p2's own general is untouched
            self.assertIsNotNone(obsMap.generals[2])
            self.assertEqual(2, obsMap.generals[2].player)
            # an OBSERVED trade lacks perfect info: the enemy's remembered
            # cityCount must not be rewritten to the exact-transfer count
            self.assertEqual(priorEnemyCityCount, obsMap.players[1].cityCount,
                             'observer must not rewrite enemy cityCount from imperfect data')
        else:
            self.fail('observer map should detect the third-party general trade')

    def test_sim__general_trade__observer_no_false_positive(self) -> None:
        """
        Negative regression on a live Map: an observer with STALE fog memory
        (p0-owned tiles last seen long ago, now re-revealed as p1's) must NOT
        promote that to a guaranteed general trade - re-revealed land is not
        was_visible_last_turn evidence and both players stay alive anyway.
        """
        cols, rows = _TRADE_COLS, _TRADE_ROWS
        size = cols * rows
        # p2 live map: player_index 2, stale memory of three a-tiles at (1,1),(1,2),(1,3)
        staleXys = [(1, 1), (1, 2), (1, 3)]

        def buildPayload(turn: int, revealOwner: int | None) -> dict:
            """revealOwner: owner the stale tiles reveal as this turn, or None
            to send them as fog."""
            armies = [0] * size
            owners = [TILE_FOG] * size
            # p2's own little territory stays visible forever
            for (x, y), army in [((0, 0), 10), ((1, 0), 2), ((0, 1), 3), ((0, 2), 4)]:
                owners[y * cols + x] = 2
                armies[y * cols + x] = army
            if revealOwner is not None:
                for (x, y) in staleXys:
                    owners[y * cols + x] = revealOwner
                    armies[y * cols + x] = 5
            scores = [
                {'i': 0, 'total': 500, 'tiles': 20, 'dead': False},
                {'i': 1, 'total': 600, 'tiles': 20, 'dead': False},
                {'i': 2, 'total': 19, 'tiles': 4, 'dead': False},
            ]
            return {
                'turn': turn,
                'map_diff': _server_delta(None, [_TRADE_COLS, _TRADE_ROWS] + armies + owners) if turn == 50 else _server_delta(liveMap._map_private, [_TRADE_COLS, _TRADE_ROWS] + armies + owners),
                'cities_diff': [0, 0],
                'deserts_diff': [0, 0],
                'generals': [-1, -1, 0],
                'scores': scores,
            }

        startData = {
            'playerIndex': 2,
            'usernames': ['a', 'b', 'c'],
            'teams': [0, 1, 2],
            'replay_id': 'obs_fp_test',
            'options': {},
            'playerColors': [0, 1, 2],
            'swamps': [],
        }
        liveMap = Map(startData, buildPayload(50, 0))
        # second update: those tiles go fog (stale p0 memory persists internally)
        liveMap.apply_server_update(buildPayload(51, None))
        # third update: they re-reveal as p1's while BOTH players stay alive
        liveMap.apply_server_update(buildPayload(52, 1))

        for (x, y) in staleXys:
            tile = liveMap.GetTile(x, y)
            self.assertTrue(tile.delta.gainedSight, f'tile {x},{y} must be a gainedSight reveal')
            self.assertEqual(0, tile.delta.oldOwner, f'tile {x},{y} stale memory should read oldOwner=0')
            self.assertEqual(1, tile.player, f'tile {x},{y} now owned by p1')
        # stale-memory re-reveals are NOT a confirmed trade signature
        self.assertIsNone(liveMap.general_trade, 'observer must not detect a trade from stale fog re-reveals')

    def test_sim__general_trade__skip_resume_flag_still_reseeds(self) -> None:
        """
        With OpponentTracker.skip_this_turn set (resume-after-deserialize flag),
        the trade reseed must still run - the bulk swap is real knowledge that
        cannot wait for the resume turn to pass.
        """
        map, general, enemyGeneral = self._load_trade_map(50)
        preTiles = _snapshot_expected(map)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        bot: EklipZBot = simHost.get_bot(0)
        playerMap = simHost.get_player_map(0)

        bot.opponent_tracker.skip_this_turn = True

        simHost.queue_player_moves_str(0, f'{_OUR_ATTACK_XY[0]},{_OUR_ATTACK_XY[1]}->{_ENEMY_GENERAL_XY[0]},{_ENEMY_GENERAL_XY[1]}')
        simHost.queue_player_moves_str(1, f'{_ENEMY_ATTACK_XY[0]},{_ENEMY_ATTACK_XY[1]}->{_OUR_GENERAL_XY[0]},{_OUR_GENERAL_XY[1]}')
        simHost.execute_turn(run_real_time=False)

        newTurn = 51
        expected = _compute_expected_trade(preTiles, _OUR_ATTACK_XY, _ENEMY_ATTACK_XY, False, False, newTurn)
        visible = _expected_visible_xy(expected, 0)
        simHost.bot_hosts[0].receive_update_no_move(playerMap, time.time_ns() / NS_CONVERTER)

        # even with the resume skip, the exact reseed ran
        self._assert_bot_tracker_post_trade(bot, playerMap, expected, visible, 1, 'skip_this_turn')
        self.assertFalse(bot.opponent_tracker.skip_this_turn, 'resume flag should be consumed')

    def test_sim__general_trade__mixed_team_preserves_unaffected(self) -> None:
        """
        Team trade: we (p0) trade generals with p1, who is teamed with p2
        (teams=0,1,1). The reseed must rebuild ONLY p1's exact state - the
        unaffected teammate p2's gather queue and the team's shared fog pools
        must keep their contribution.
        """
        # p2's territory moved far away so it has genuine fog (not all-visible)
        tiles = dict(_TRADE_TILES)
        for xy in [(0, 0), (1, 0), (0, 1), (0, 2)]:
            tiles.pop(xy, None)
        tiles[(8, 0)] = 'cG10'
        tiles[(8, 1)] = 'c3'
        tiles[(7, 0)] = 'c2'
        mapData = _build_trade_map_string(tiles, ['turn=50', 'player_index=0', 'aTiles=23', 'bTiles=24', 'cTiles=3', 'teams=0,1,1'])
        map, general = self.load_map_and_general_from_string(mapData, turn=50, player_index=0)
        preTiles = _snapshot_expected(map)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=0, allAfkExceptMapPlayer=True, botInitOnly=True)
        bot: EklipZBot = simHost.get_bot(0)
        playerMap = simHost.get_player_map(0)

        simHost.queue_player_moves_str(0, f'{_OUR_ATTACK_XY[0]},{_OUR_ATTACK_XY[1]}->{_ENEMY_GENERAL_XY[0]},{_ENEMY_GENERAL_XY[1]}')
        simHost.queue_player_moves_str(1, f'{_ENEMY_ATTACK_XY[0]},{_ENEMY_ATTACK_XY[1]}->{_OUR_GENERAL_XY[0]},{_OUR_GENERAL_XY[1]}')
        simHost.execute_turn(run_real_time=False)

        # a REAL trade happened: pair 0/1, both alive, generals swapped
        self.assertIsNotNone(playerMap.general_trade, 'must detect the p0<->p1 trade')
        self.assertEqual(0, playerMap.general_trade.player)
        self.assertEqual(1, playerMap.general_trade.opponent)
        self.assertEqual(_ENEMY_GENERAL_XY, (playerMap.generals[0].x, playerMap.generals[0].y))
        self.assertEqual(_OUR_GENERAL_XY, (playerMap.generals[1].x, playerMap.generals[1].y))

        # p2 has genuine fog (scoreboard fog tile count > 0)
        fog2 = bot.opponent_tracker.calculate_player_fog_tile_data(2)[0]
        self.assertGreater(fog2, 0, 'p2 must have unknown fog tiles for the mixed-team case')

        # seed distinctive state on the unaffected member then call the reseed
        # helper directly for the SAME trade event: p2's queue + shared pools
        # must be preserved while p1's queue is exactly rebuilt.
        teamStats = bot.opponent_tracker.get_current_cycle_stats_by_player(1)
        p2q = bot.opponent_tracker.get_player_gather_queue(2)
        p2q.set_amount_for_size(37, 2)
        teamStats.approximate_fog_army_available_total = 123
        teamStats.approximate_fog_army_available_total_true = 123
        teamStats.approximate_fog_city_army = 50
        teamStats.fog_city_count = 7
        priorQ2 = dict(p2q.get_amount_dict())
        priorAvail = teamStats.approximate_fog_army_available_total
        priorAvailTrue = teamStats.approximate_fog_army_available_total_true
        priorCityArmy = teamStats.approximate_fog_city_army
        priorCityCount = teamStats.fog_city_count

        bot.opponent_tracker._reseed_general_trade_fog_state(teamStats)

        self.assertEqual(priorQ2, p2q.get_amount_dict(), 'unaffected teammate queue must be untouched')
        self.assertEqual(priorAvail, teamStats.approximate_fog_army_available_total, 'shared available pool preserved for mixed team')
        self.assertEqual(priorAvailTrue, teamStats.approximate_fog_army_available_total_true, 'shared available-true pool preserved')
        self.assertGreaterEqual(teamStats.approximate_fog_city_army, priorCityArmy, 'shared fog-city army must not drop below prior')
        self.assertGreaterEqual(teamStats.fog_city_count, priorCityCount, 'shared fog-city count must not drop below prior')

    def test_sim__general_trade__nonadjacent_move_does_not_trade(self) -> None:
        """An impossible (nonadjacent) "mutual" move must NOT trigger the swap -
        ordinary move resolution applies instead (our attack still lands)."""
        # move our attack source somewhere NOT adjacent to the enemy gen
        tiles = dict(_TRADE_TILES)
        tiles.pop((13, 6), None)
        tiles[(12, 8)] = 'a60'  # a60 now at (12,8), not adjacent to (13,5)
        mapData = _build_trade_map_string(tiles, ['turn=50', 'player_index=0', 'aTiles=23', 'bTiles=24', 'cTiles=3'])
        map, general = self.load_map_and_general_from_string(mapData, turn=50, player_index=0)
        self.enable_search_time_limits_and_disable_debug_asserts()
        sim = GameSimulator(map)
        simMap = sim.sim_map
        # our 'move' from (12,8) onto the enemy gen is nonadjacent/illegal;
        # only the enemy's valid capture (3,5 -> 2,5) resolves
        sim.set_next_move(0, Move(simMap.GetTile(12, 8), simMap.GetTile(13, 5), False))
        sim.set_next_move(1, Move(simMap.GetTile(*_ENEMY_ATTACK_XY), simMap.GetTile(*_OUR_GENERAL_XY), False))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)

        # no swap: our general entry still references our original general
        # tile (a real trade would rebind it to the enemy's general tile) and
        # our old land is not halved-transferred to the enemy.
        self.assertEqual(_OUR_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y),
                         'nonadjacent move must not trigger the swap')
        self.assertEqual(0, simMap.GetTile(2, 3).player, 'our old land must stay ours without a trade')
        self.assertEqual(9, simMap.GetTile(2, 3).army, 'our old land army must not be halved without a trade')

    def test_sim__general_trade__continued_play(self) -> None:
        """
        After the trade resolves correctly, the game continues: bots make real
        moves for several turns, an enemy attack on our new land lands and is
        reconciled visibly, generals stay correct, and the game does not end
        prematurely.
        """
        map, general, enemyGeneral = self._load_trade_map(50)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=0, afkPlayers=[2])

        # trade turn via known queued moves
        simHost.queue_player_moves_str(0, f'{_OUR_ATTACK_XY[0]},{_OUR_ATTACK_XY[1]}->{_ENEMY_GENERAL_XY[0]},{_ENEMY_GENERAL_XY[1]}')
        simHost.queue_player_moves_str(1, f'{_ENEMY_ATTACK_XY[0]},{_ENEMY_ATTACK_XY[1]}->{_OUR_GENERAL_XY[0]},{_OUR_GENERAL_XY[1]}')
        winner = simHost.execute_turn(run_real_time=False)
        self.assertIsNone(winner)

        # an immediate enemy capture of our transferred swamp tile reconciles
        # visibly on our map the following turn: post-trade the enemy owns our
        # old (3,6) tile adjacent to our transferred swamp source (3,5).
        simHost.queue_player_moves_str(1, '3,6->3,5')
        winner = simHost.execute_turn(run_real_time=False)
        self.assertIsNone(winner)
        playerMap = simHost.get_player_map(0)
        contested = playerMap.GetTile(3, 5)
        simContested = simHost.sim.sim_map.GetTile(3, 5)
        self.assertEqual(1, contested.player, 'enemy capture of our transferred tile should reconcile to the enemy owner')
        # our corridor (4,5) stays friendly-adjacent after the enemy recapture,
        # so the contested tile must remain visible with exact truth
        self.assertTrue(contested.visible, 'contested tile adjacent to our owned corridor must stay visible')
        self.assertEqual(simContested.army, contested.army, 'visible contested tile must show the true army')
        self.assertEqual(simContested.player, contested.player)

        for _ in range(8):
            winner = simHost.execute_turn(run_real_time=False)
            self.assertIsNone(winner)
            simMap = simHost.sim.sim_map
            # generals stay correct on both world map and bot map while playing on
            self.assertEqual((simMap.generals[0].x, simMap.generals[0].y), _ENEMY_GENERAL_XY)
            self.assertEqual((simMap.generals[1].x, simMap.generals[1].y), _OUR_GENERAL_XY)
            botMap = simHost.get_player_map(0)
            self.assertEqual(botMap.generals[0], botMap.GetTile(simMap.generals[0].x, simMap.generals[0].y))
            self.assertFalse(simHost.sim.players[0].dead)
            self.assertFalse(simHost.sim.players[1].dead)

        # prove real bot moves actually executed (not lag-Nones): the sim's
        # recorded move history holds per-player Move|None each turn;
        # moves_history[i][0] is player 0's selected move for that turn.
        # Skip history[0] (the forced trade turn).
        p0RealMoves = [moves[0] for moves in simHost.sim.moves_history[1:] if len(moves) > 0 and moves[0] is not None]
        self.assertGreater(len(p0RealMoves), 2, f'expected several real p0 moves post-trade, got {p0RealMoves}')
        # executed moves are already sim-validated as legal (from owned source);
        # assert the geometry is sane
        for move in p0RealMoves:
            self.assertLessEqual(abs(move.source.x - move.dest.x) + abs(move.source.y - move.dest.y), 1, 'real bot move must be orthogonally adjacent')

        self.assertFalse(simHost.sim.is_game_over(), 'game should not end prematurely after a general trade')
