"""
Strategic general-trade tests: the bot should WANT a mutual general capture
when the opponent holds the economy advantage, should NOT proactively trade
at neutral/reverse utility, and keeps an unfavorable mutual capture as the
survival fallback. Tests exercise the BotCombatOps adapter and the
get_kill_race_chance same-turn gate against real Map/Path/ThreatObj
objects (fixture from test_GeneralTrade).
"""

import typing
import unittest

from Path import Path
from DangerAnalyzer import ThreatObj, ThreatType
from BotModules.BotCombatOps import BotCombatOps
from Models.Move import Move
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from bot_ek0x45 import EklipZBot
from base.client.map import Tile, MapBase

from TestBase import TestBase
# module import only - importing the GeneralTradeTests CLASS here would let
# unittest discover its 12 methods a second time inside this module
from Tests import test_GeneralTrade
from Tests.test_GeneralTrade import _TRADE_TILES, _build_trade_map_string, _OUR_ATTACK_XY, _ENEMY_ATTACK_XY, _OUR_GENERAL_XY, _ENEMY_GENERAL_XY


class GeneralTradeStrategyTests(TestBase):
    """Adapter + race-caller coverage for the strategic trade evaluation."""

    def _load_bot(self, turn: int = 49) -> typing.Tuple[MapBase, EklipZBot]:
        """Loads the trade fixture ground-truth map and returns
        (map, initializedBot) with a ready bot state."""
        map, general, enemyGeneral = test_GeneralTrade.GeneralTradeTests._load_trade_map(self, turn)
        # the ground-truth fixture leaves scoreboard totals as placeholders;
        # derive the real army/tile counts from the board for the evaluator
        for p in range(len(map.players)):
            map.scores[p].total = sum(t.army for t in map.get_all_tiles() if t.player == p)
            map.scores[p].tiles = sum(1 for t in map.get_all_tiles() if t.player == p)
        self.enable_search_time_limits_and_disable_debug_asserts()
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(map)
        with bot.perf_timer.begin_move(map.turn):
            bot.init_turn()
        return map, bot

    def _make_trade_paths(self, map: MapBase, our_half: bool = False, enemy_half: bool = False) -> typing.Tuple[Path, ThreatObj]:
        """Builds (ourAttackPath, threatObj) for the mutual capture: our
        source -> enemy gen and enemy source -> our gen, both length 1."""
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        ourPath = Path()
        ourPath.add_next(map.GetTile(*_OUR_ATTACK_XY))
        ourPath.add_next(map.GetTile(*_ENEMY_GENERAL_XY), our_half)
        ourPath.calculate_value(map.player_index, teams)
        threatPath = Path()
        threatPath.add_next(map.GetTile(*_ENEMY_ATTACK_XY))
        threatPath.add_next(map.GetTile(*_OUR_GENERAL_XY), enemy_half)
        threatPath.calculate_value(1, teams)
        threat = ThreatObj(threatPath.length - 1, threatPath.value, threatPath, ThreatType.Kill, None)
        return ourPath, threat

    def _load_bot_with_overrides(
            self,
            overrides: typing.Dict[typing.Tuple[int, int], str],
            tile_counts: typing.Tuple[str, str, str] = ('aTiles=24', 'bTiles=31', 'cTiles=4'),
            turn: int = 49) -> typing.Tuple[MapBase, EklipZBot]:
        """Like _load_bot but applies tile-string overrides before loading."""
        tiles = dict(_TRADE_TILES)
        tiles.update(overrides)
        extra = ['turn=' + str(turn), 'player_index=0'] + list(tile_counts)
        mapData = _build_trade_map_string(tiles, extra)
        map, general = self.load_map_and_general_from_string(mapData, turn=turn, player_index=0)
        for p in range(len(map.players)):
            map.scores[p].total = sum(t.army for t in map.get_all_tiles() if t.player == p)
            map.scores[p].tiles = sum(1 for t in map.get_all_tiles() if t.player == p)
        self.enable_search_time_limits_and_disable_debug_asserts()
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(map)
        with bot.perf_timer.begin_move(map.turn):
            bot.init_turn()
        return map, bot

    def test__adapter__half_move_sends_floor_not_ceil(self) -> None:
        """
        A half move sends floor(army/2) and reserves ceil(army/2): an odd
        61-army source sends 30 (not 31), so against the 25-def enemy
        general our new general lands at 5, never 6.
        """
        map, bot = self._load_bot_with_overrides({
            _OUR_ATTACK_XY: 'a61',
            _ENEMY_ATTACK_XY: 'bS51',  # still captures our 20-gen
        }, turn=50)
        ourPath, threat = self._make_trade_paths(map, our_half=True)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertEqual(30 - 25, ev.our_new_general_army, 'half move sends floor(61/2)=30, not ceil')
        # sim truth: same half-move trade on the real simulator (lands odd 51 - no bonus)
        sim = GameSimulator(map)
        simMap = sim.sim_map
        sim.set_next_move(0, Move(simMap.GetTile(*_OUR_ATTACK_XY), simMap.GetTile(*_ENEMY_GENERAL_XY), True))
        sim.set_next_move(1, Move(simMap.GetTile(*_ENEMY_ATTACK_XY), simMap.GetTile(*_OUR_GENERAL_XY), False))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)
        # turn 50 lands the trade on odd 51 (no bonus): new gen = exactly sent-def
        self.assertEqual(30 - 25, simMap.GetTile(*_ENEMY_GENERAL_XY).army, 'sim must agree the odd half sends 30')

    def test__adapter__enemy_half_move_sends_floor(self) -> None:
        """The enemy's odd half move follows the same floor rule: their
        51-army half move sends 25, landing a 5-army new general on ours."""
        map, bot = self._load_bot_with_overrides({
            _OUR_ATTACK_XY: 'a60',
            _ENEMY_ATTACK_XY: 'bS51',
        }, turn=50)
        ourPath, threat = self._make_trade_paths(map, enemy_half=True)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertEqual(25 - 20, ev.opponent_new_general_army, 'enemy half move sends floor(51/2)=25')
        sim = GameSimulator(map)
        simMap = sim.sim_map
        sim.set_next_move(0, Move(simMap.GetTile(*_OUR_ATTACK_XY), simMap.GetTile(*_ENEMY_GENERAL_XY), False))
        sim.set_next_move(1, Move(simMap.GetTile(*_ENEMY_ATTACK_XY), simMap.GetTile(*_OUR_GENERAL_XY), True))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)
        self.assertEqual(25 - 20, simMap.GetTile(*_OUR_GENERAL_XY).army, 'sim must agree the enemy odd half sends 25')

    def test__adapter__strict_tie_is_not_a_capture(self) -> None:
        """sent == defense is NOT a capture: both directions of the tie
        must return None rather than a fabricated trade."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 26  # sends 25 == their 25-def gen
        map.GetTile(*_ENEMY_ATTACK_XY).army = 51
        ourPath, threat = self._make_trade_paths(map)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1),
                          'sent == enemy gen defense is not a capture')
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        map.GetTile(*_ENEMY_ATTACK_XY).army = 21  # sends 20 == our 20-def gen
        ourPath, threat = self._make_trade_paths(map)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1),
                          'enemy sent == our gen defense is not a capture')

    def test__adapter__immobile_source_rejected(self) -> None:
        """A source with army <= 1 cannot move: reject cleanly with None
        before the pure evaluator sees a -1 sent army."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 0  # full move sends -1 -> ValueError without the guard
        map.GetTile(*_ENEMY_ATTACK_XY).army = 51
        ourPath, threat = self._make_trade_paths(map)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1))
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 1
        map.GetTile(*_ENEMY_ATTACK_XY).army = 51
        ourPath, threat = self._make_trade_paths(map)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1))
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        map.GetTile(*_ENEMY_ATTACK_XY).army = 1
        ourPath, threat = self._make_trade_paths(map)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1))

    def test__adapter__general_source_full_and_half(self) -> None:
        """
        When the attack source IS the general, the general's defense is the
        reserve it leaves behind (flag stays on the tile), and the sent army
        follows the same full/half rules. Our gen relocates onto (13,6) for
        this fixture so it sits adjacent to the enemy gen.
        """
        # full move off a 61-gen: sends 60, reserve 1 defends our old gen
        map, bot = self._load_bot_with_overrides({
            _OUR_GENERAL_XY: 'a1',
            _OUR_ATTACK_XY: 'aG61',
            (12, 6): 'b80',
        })
        ourPath = Path()
        ourPath.add_next(map.GetTile(*_OUR_ATTACK_XY))
        ourPath.add_next(map.GetTile(*_ENEMY_GENERAL_XY))
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        ourPath.calculate_value(map.player_index, teams)
        threatPath = Path()
        threatPath.add_next(map.GetTile(12, 6))
        threatPath.add_next(map.GetTile(*_OUR_ATTACK_XY))
        threatPath.calculate_value(1, teams)
        threat = ThreatObj(threatPath.length - 1, threatPath.value, threatPath, ThreatType.Kill, None)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertEqual(60 - 25, ev.our_new_general_army, 'full move off the gen sends army-1')
        self.assertEqual(79 - 1, ev.opponent_new_general_army, 'our gen defense is its reserve of 1')
        # half move off the same gen: sends 30, reserve 31 defends
        ourPathHalf = Path()
        ourPathHalf.add_next(map.GetTile(*_OUR_ATTACK_XY))
        ourPathHalf.add_next(map.GetTile(*_ENEMY_GENERAL_XY), True)
        ourPathHalf.calculate_value(map.player_index, teams)
        evHalf = BotCombatOps.evaluate_general_trade(bot, ourPathHalf, threat, 1)
        self.assertIsNotNone(evHalf)
        self.assertEqual(30 - 25, evHalf.our_new_general_army, 'half move off the gen sends floor(61/2)')
        self.assertEqual(79 - 31, evHalf.opponent_new_general_army, 'our gen defense is the ceil(61/2)=31 reserve')

    def test__adapter__enemy_general_source(self) -> None:
        """Both generals as attack sources: each side's defense is the
        reserve its own general leaves behind."""
        map, bot = self._load_bot_with_overrides({
            _OUR_GENERAL_XY: 'a1',
            _OUR_ATTACK_XY: 'aG61',
            _ENEMY_GENERAL_XY: 'bG60',
        })
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        ourPath = Path()
        ourPath.add_next(map.GetTile(*_OUR_ATTACK_XY))  # our gen, full move
        ourPath.add_next(map.GetTile(*_ENEMY_GENERAL_XY))
        ourPath.calculate_value(map.player_index, teams)
        threatPath = Path()
        threatPath.add_next(map.GetTile(*_ENEMY_GENERAL_XY))  # their gen, half move
        threatPath.add_next(map.GetTile(*_OUR_ATTACK_XY), True)
        threatPath.calculate_value(1, teams)
        threat = ThreatObj(threatPath.length - 1, threatPath.value, threatPath, ThreatType.Kill, None)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertEqual(60 - 30, ev.our_new_general_army, 'their gen half-reserve (60-30=30) is the defense')
        self.assertEqual(30 - 1, ev.opponent_new_general_army, 'their gen sends floor(60/2)=30 vs our reserve 1')

    def test__adapter__required_delay_rejected(self) -> None:
        """A path that must WAIT (requiredDelay) is not projectable as a
        same-turn trade: each side's growth window is keyed to its own path
        length, so a delayed arrival would be priced against the wrong
        capture turn. Rejects both directions cleanly."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        map.GetTile(*_ENEMY_ATTACK_XY).army = 51
        ourPath, threat = self._make_trade_paths(map)
        ourPath.requiredDelay = 1
        # a threat whose real capture turn matches our delayed arrival
        delayedThreat = ThreatObj(threat.path.length, threat.path.value, threat.path, ThreatType.Kill, None)
        self.assertEqual(ourPath.length + ourPath.requiredDelay, delayedThreat.turns + 1)
        self.assertIsNone(
            BotCombatOps.evaluate_general_trade(bot, ourPath, delayedThreat, 1),
            'waiting paths are not projectable')
        # a delay on the THREAT path is likewise rejected
        map, bot = self._load_bot(49)
        ourPath2, threat2 = self._make_trade_paths(map)
        threat2.path.requiredDelay = 1
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath2, threat2, 1))

    def test__adapter__multiturn_source_half_rejected(self) -> None:
        """A half move off the SOURCE of a multi-turn path cannot be
        inverted exactly from Path.value (its half rounding plus source
        growth) - reject, never estimate. Direct length-1 halves stay
        supported (test__adapter__half_move_sends_floor_not_ceil)."""
        map, bot = self._two_step_bot(50)
        ourPath, threat = self._two_step_paths(map)
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        ourHalfPath = Path()
        ourHalfPath.add_next(map.GetTile(10, 3))
        ourHalfPath.add_next(map.GetTile(10, 2), True)
        ourHalfPath.add_next(map.GetTile(10, 1))
        ourHalfPath.calculate_value(map.player_index, teams)
        self.assertIsNone(
            BotCombatOps.evaluate_general_trade(bot, ourHalfPath, threat, 1),
            'source half move on a multi-turn path must reject')
        enHalfPath = Path()
        enHalfPath.add_next(map.GetTile(1, 3))
        enHalfPath.add_next(map.GetTile(1, 2), True)
        enHalfPath.add_next(map.GetTile(1, 1))
        enHalfPath.calculate_value(1, teams)
        enThreat = ThreatObj(enHalfPath.length - 1, enHalfPath.value, enHalfPath, ThreatType.Kill, None)
        self.assertIsNone(
            BotCombatOps.evaluate_general_trade(bot, ourPath, enThreat, 1),
            'enemy source half move on a multi-turn path must reject')

    def test__adapter__stale_forecast_rejected(self) -> None:
        """A scoreboard stale relative to the armies the fog map actually
        shows (fog-owned predictions / over-estimated defenders) must not
        leak a negative total or tile count into the pure model - the
        candidate rejects cleanly, no ValueError, no clamp."""
        map, bot = self._two_step_bot(50)
        map.GetTile(10, 3).army = 600      # stack must still take the endpoint
        map.GetTile(10, 2).player = 1
        map.GetTile(10, 2).army = 500      # big defender consumed mid-path
        map.scores[0].total = 5            # stale: far below reality
        ourPath, threat = self._two_step_paths(map)
        self.assertGreater(ourPath.value, 0, 'the stack genuinely captures the endpoint')
        self.assertIsNone(
            BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1),
            'negative derived total must reject, not propagate')

    def _two_step_map_data(self, turn: int) -> str:
        """The settled two-step regression fixture: our gen aG10@(1,1) with
        source a50@(10,3) through own a3@(10,2) onto bG8@(10,1); enemy source
        b40@(1,3) through own b1@(1,2) onto our gen. Both paths length 2."""
        tiles = {
            (0, 0): 'cG10',
            (1, 1): 'aG10',
            (10, 3): 'a50', (10, 2): 'a3',
            (10, 1): 'bG8',
            (1, 3): 'b40', (1, 2): 'b1',
        }
        extra = ['turn=' + str(turn), 'player_index=0', 'aTiles=3', 'bTiles=3', 'cTiles=1']
        return _build_trade_map_string(tiles, extra)

    def _two_step_bot(self, turn: int) -> typing.Tuple[MapBase, EklipZBot]:
        map, general = self.load_map_and_general_from_string(
            self._two_step_map_data(turn), turn=turn, player_index=0)
        for p in range(len(map.players)):
            map.scores[p].total = sum(t.army for t in map.get_all_tiles() if t.player == p)
            map.scores[p].tiles = sum(1 for t in map.get_all_tiles() if t.player == p)
        self.enable_search_time_limits_and_disable_debug_asserts()
        bot = EklipZBot()
        bot.initialize_from_map_for_first_time(map)
        with bot.perf_timer.begin_move(map.turn):
            bot.init_turn()
        return map, bot

    def test__adapter__massive_enemy_survivor_blocks_trade_despite_econ_lead(self) -> None:
        """A real enemy economy lead (perceived cityCount) but the enemy's
        attack stack is so massive their new general lands huge: the trade
        is unfavorable on survivor strength alone. (This small fixture
        cannot simultaneously defend bS300 and keep the trade valid - a
        viable defense would cap their new gen at the ~8-army reinforce -
        so this lives at adapter level over the real map/player objects,
        paired with the pure survivor-swing test.)"""
        map, bot = self._load_bot_with_overrides({
            _OUR_ATTACK_XY: 'a60',
            _ENEMY_ATTACK_XY: 'bS300',  # sent 299 -> new gen 279
        })
        map.players[1].cityCount += 4  # real perceived economy lead
        ourPath, threat = self._make_trade_paths(map)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertGreater(ev.economy_gain, 0.0, 'the enemy genuinely holds the economy lead here')
        self.assertFalse(ev.favorable, 'massive enemy survivor must override the economy lead')

    def _two_step_paths(self, map: MapBase) -> typing.Tuple[Path, ThreatObj]:
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        ourPath = Path()
        ourPath.add_next(map.GetTile(10, 3))
        ourPath.add_next(map.GetTile(10, 2))
        ourPath.add_next(map.GetTile(10, 1))
        ourPath.calculate_value(map.player_index, teams)
        threatPath = Path()
        threatPath.add_next(map.GetTile(1, 3))
        threatPath.add_next(map.GetTile(1, 2))
        threatPath.add_next(map.GetTile(1, 1))
        threatPath.calculate_value(1, teams)
        threat = ThreatObj(threatPath.length - 1, threatPath.value, threatPath, ThreatType.Kill, None)
        return ourPath, threat

    def _run_two_step_sim(self, turn: int) -> GameSimulator:
        """Runs the real two-turn mutual capture on a fresh ground-truth map."""
        map, general = self.load_map_and_general_from_string(
            self._two_step_map_data(turn), turn=turn, player_index=0)
        sim = GameSimulator(map)
        simMap = sim.sim_map
        sim.set_next_move(0, Move(simMap.GetTile(10, 3), simMap.GetTile(10, 2)))
        sim.set_next_move(1, Move(simMap.GetTile(1, 3), simMap.GetTile(1, 2)))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)
        sim.set_next_move(0, Move(simMap.GetTile(10, 2), simMap.GetTile(10, 1)))
        sim.set_next_move(1, Move(simMap.GetTile(1, 2), simMap.GetTile(1, 1)))
        sim.set_next_move(2, None)
        sim.execute_turn(dont_require_all_players_to_move=True)
        return sim

    def test__adapter__two_step_projection__t50(self) -> None:
        """
        T50 two-step fixture: first effect lands on odd 51 (no bonus), the
        capture lands on 52 BEFORE the city tick. Ours sends 49+2=51 vs def 8
        -> 43; enemy sends 39+0=39 vs def 10 -> 29. Each side's two path
        tiles hold reserve 1 -> halved 1 each: post armies 45 vs 31.
        """
        map, bot = self._two_step_bot(50)
        ourPath, threat = self._two_step_paths(map)
        self.assertEqual(2, ourPath.length)
        self.assertEqual(43, ourPath.value, 'path value is the net leftover on the endpoint, not the sent army')
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertEqual(51 - 8, ev.our_new_general_army, 'sent = 49 (source) + 2 (mid) = 51, minus gen def 8')
        self.assertEqual(39 - 10, ev.opponent_new_general_army, 'enemy sent = 39 (mid 1 keeps none), minus def 10')
        # each side: two path tiles (source + mid) hold reserve 1 -> halved 1 each
        self.assertEqual(43 + 1 + 1, ev.our_post_army)
        self.assertEqual(29 + 1 + 1, ev.opponent_post_army)
        # sim truth: trade lands on 52 then the city bonus ticks new gens +1
        sim = self._run_two_step_sim(50)
        simMap = sim.sim_map
        self.assertEqual(43 + 1, simMap.GetTile(10, 1).army, 'sim: our new gen = 43 leftover + turn-52 city tick')
        self.assertEqual(29 + 1, simMap.GetTile(1, 1).army, 'sim: their new gen = 29 leftover + turn-52 city tick')
        self.assertEqual(1, simMap.GetTile(10, 3).army, 'halved source reserve')
        self.assertEqual(1, simMap.GetTile(10, 2).army, 'halved mid reserve')
        self.assertFalse(sim.players[0].dead)
        self.assertFalse(sim.players[1].dead)

    def test__adapter__two_step_projection__t51(self) -> None:
        """
        T51 variant: the turn-52 city tick lands between the gather and the
        capture, growing both general defenses to 11 and 9. Sent is
        unchanged (51/39): nets 42/28, post armies 44 vs 30. Total armies
        get exactly +1 pre-capture production each - no fake unknown pool.
        """
        map, bot = self._two_step_bot(51)
        ourPath, threat = self._two_step_paths(map)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertEqual(51 - 9, ev.our_new_general_army, 'enemy gen grew +1 on the turn-52 city tick')
        self.assertEqual(39 - 11, ev.opponent_new_general_army, 'our gen grew +1 on the turn-52 city tick')
        self.assertEqual(42 + 1 + 1, ev.our_post_army)
        self.assertEqual(28 + 1 + 1, ev.opponent_post_army)
        # sim truth: capture lands on 53 (odd, no bonus) -> leftover is exact
        sim = self._run_two_step_sim(51)
        simMap = sim.sim_map
        self.assertEqual(42, simMap.GetTile(10, 1).army, 'sim: our new gen = 51 - 9 (def ticked before capture)')
        self.assertEqual(28, simMap.GetTile(1, 1).army, 'sim: their new gen = 39 - 11')
        self.assertFalse(sim.players[0].dead)
        self.assertFalse(sim.players[1].dead)

    def test__adapter__favorable_trade_when_enemy_econ_leads(self) -> None:
        """
        Enemy holds the economy lead we acquire: the trade evaluates
        favorable. Fixture: enemy b has ~31 tiles vs our ~24 and more cities,
        our 60-army source captures their 25-def gen while their 22-army
        source captures our 20-def gen.
        """
        map, bot = self._load_bot(49)
        # give our source enough to capture their 25-def gen
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        # give the enemy a real economy advantage (more cities -> higher
        # production value we acquire in the trade)
        map.players[1].cityCount += 4
        ourPath, threat = self._make_trade_paths(map)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev, 'valid bilateral same-turn capture must evaluate')
        self.assertTrue(ev.favorable, f'econ gain {ev.economy_gain} must make the trade favorable')
        self.assertEqual(60 - 1 - 25, ev.our_new_general_army)
        self.assertEqual(22 - 1 - 20, ev.opponent_new_general_army)

    def test__adapter__unfavorable_when_we_hold_lead(self) -> None:
        """If the opponent has no econ advantage the trade is not proactive."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        # force enemy economy below ours
        for tile in map.get_all_tiles():
            if tile.player == 1 and not tile.isGeneral:
                tile.player = 2
        ourPath, threat = self._make_trade_paths(map)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        if ev is not None:
            self.assertFalse(ev.favorable, 'no econ advantage -> never a proactive trade')

    def test__adapter__rejects_wrong_tail(self) -> None:
        """Path ending on a non-general (or wrong-player general) is not a
        valid mutual capture -> None, never a guess."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        ourPath, threat = self._make_trade_paths(map)
        badPath = Path()
        badPath.add_next(map.GetTile(*_OUR_ATTACK_XY))
        badPath.add_next(map.GetTile(*_OUR_GENERAL_XY))  # ends on OUR gen
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, badPath, threat, 1))
        # third-party threat is not bilateral
        thirdThreat = ThreatObj(0, 0, threat.path, ThreatType.Econ, None)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, thirdThreat, 1))

    def test__adapter__rejects_mismatched_arrival(self) -> None:
        """Our kill arriving BEFORE the threat's capture turn is an outright
        kill, not a trade -> the trade adapter returns None."""
        map, bot = self._load_bot(49)
        ourPath, threat = self._make_trade_paths(map)
        # fabricate a threat that lands a turn later than our kill
        lateThreat = ThreatObj(threat.path.length, threat.path.value, threat.path, ThreatType.Kill, None)
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, ourPath, lateThreat, 1))

    def test__race__same_turn_favorable_returns_one(self) -> None:
        """get_kill_race_chance must return 1.0 on a same-turn FAVORABLE
        mutual capture (not the legacy 'we lose' 0.0 for equal arrivals)."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        map.players[1].cityCount += 4
        ourPath, threat = self._make_trade_paths(map)
        chance = BotCombatOps.get_kill_race_chance(
            bot, ourPath, enGenProbabilityCutoff=0.0, turnsToDeath=threat.turns + 1,
            againstPlayer=1, threat=threat)
        self.assertEqual(1.0, chance, 'favorable same-turn trade must win the race')

    def test__race__earlier_kill_still_one(self) -> None:
        """Arriving before the threat's real capture turn stays a plain
        1.0 kill regardless of the trade economics."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        ourPath, threat = self._make_trade_paths(map)
        # report the threat as one turn slower than our 1-length path
        lateThreat = ThreatObj(threat.path.length, threat.path.value, threat.path, ThreatType.Kill, None)
        chance = BotCombatOps.get_kill_race_chance(
            bot, ourPath, enGenProbabilityCutoff=0.0, turnsToDeath=lateThreat.turns + 1,
            againstPlayer=1, threat=lateThreat)
        self.assertEqual(1.0, chance)

    def test__race__third_party_threat_keeps_legacy(self) -> None:
        """A threat from a third party (or no valid bilateral pair) keeps
        the legacy strict-inequality race semantics: equal arrival -> 0."""
        map, bot = self._load_bot(49)
        ourPath, threat = self._make_trade_paths(map)
        # third-party threat source: c-player path to our gen
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        cPath = Path()
        cPath.add_next(map.GetTile(1, 0))
        cPath.add_next(map.GetTile(*_OUR_GENERAL_XY))
        cPath.calculate_value(2, teams)
        thirdThreat = ThreatObj(cPath.length - 1, cPath.value, cPath, ThreatType.Kill, None)
        chance = BotCombatOps.get_kill_race_chance(
            bot, ourPath, enGenProbabilityCutoff=0.0, turnsToDeath=thirdThreat.turns + 1,
            againstPlayer=1, threat=thirdThreat)
        self.assertEqual(0.0, chance, 'non-bilateral equal-arrival stays 0')

    def _make_late_trade_path(self, map: MapBase) -> Path:
        """A 3-length detour onto the enemy general: arrives AFTER the
        threat's real capture turn."""
        detour = Path()
        detour.add_next(map.GetTile(*_OUR_ATTACK_XY))
        detour.add_next(map.GetTile(12, 6))
        detour.add_next(map.GetTile(12, 5))
        detour.add_next(map.GetTile(*_ENEMY_GENERAL_XY))
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        detour.calculate_value(map.player_index, teams)
        return detour

    def test__race__late_kill_returns_zero(self) -> None:
        """Arriving after the threat's real capture turn is a loss -> 0,
        and stays 0 even when turnsToDeath carries priority padding."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 90
        map.players[1].cityCount += 4
        ourPath, threat = self._make_trade_paths(map)
        latePath = self._make_late_trade_path(map)
        self.assertGreater(latePath.length + latePath.requiredDelay, threat.turns + 1)
        chance = BotCombatOps.get_kill_race_chance(
            bot, latePath, enGenProbabilityCutoff=0.0, turnsToDeath=threat.turns + 1 + 3,
            againstPlayer=1, threat=threat)
        self.assertEqual(0.0, chance, 'a late mutual-capture path can never trade')

    def test__race__unfavorable_same_turn_returns_zero(self) -> None:
        """A valid same-turn mutual capture that is NOT favorable stays 0 -
        the path is only ever a survival fallback, never proactive."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        ourPath, threat = self._make_trade_paths(map)
        ev = BotCombatOps.evaluate_general_trade(bot, ourPath, threat, 1)
        self.assertIsNotNone(ev)
        self.assertFalse(ev.favorable, 'fixture without an enemy econ lead must be unfavorable')
        chance = BotCombatOps.get_kill_race_chance(
            bot, ourPath, enGenProbabilityCutoff=0.0, turnsToDeath=threat.turns + 1,
            againstPlayer=1, threat=threat)
        self.assertEqual(0.0, chance, 'unfavorable same-turn trade must not win the race')

    def test__race__uses_against_player_not_target_player(self) -> None:
        """The bilateral check must key on the againstPlayer argument (the
        player this path actually targets), not bot.targetPlayer."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        map.players[1].cityCount += 4
        ourPath, threat = self._make_trade_paths(map)
        bot.targetPlayer = 2  # hunt a different player than our trade partner
        chance = BotCombatOps.get_kill_race_chance(
            bot, ourPath, enGenProbabilityCutoff=0.0, turnsToDeath=threat.turns + 1,
            againstPlayer=1, threat=threat)
        self.assertEqual(1.0, chance, 'againstPlayer=1 must evaluate the trade even with targetPlayer=2')
        # a mismatched againstPlayer never becomes a bilateral trade
        mismatched = BotCombatOps.get_kill_race_chance(
            bot, ourPath, enGenProbabilityCutoff=0.0, turnsToDeath=threat.turns + 1,
            againstPlayer=2, threat=threat)
        self.assertEqual(0.0, mismatched, 'path tail p1 vs againstPlayer=2 is not bilateral -> stays 0')

    def test__race__fog_unknown_general_no_invention(self) -> None:
        """When the enemy general location is NOT known (tail not a known
        isGeneral), the same-turn path must not be invented into a
        favorable trade."""
        map, bot = self._load_bot(49)
        map.GetTile(*_OUR_ATTACK_XY).army = 60
        map.players[1].cityCount += 4
        ourPath, threat = self._make_trade_paths(map)
        # a same-length path that ends on an enemy NON-general tile is not a
        # general capture at all: no trade invention, legacy 0 on tie
        nonGenPath = Path()
        nonGenPath.add_next(map.GetTile(*_OUR_ATTACK_XY))
        nonGenPath.add_next(map.GetTile(12, 6))  # b8, not a general
        teams = map.teams if map.teams is not None else list(range(len(map.players)))
        nonGenPath.calculate_value(map.player_index, teams)
        chance = BotCombatOps.get_kill_race_chance(
            bot, nonGenPath, enGenProbabilityCutoff=0.0, turnsToDeath=threat.turns + 1,
            againstPlayer=1, threat=threat)
        self.assertEqual(0.0, chance, 'a path not ending on the known enemy gen cannot trade')
        self.assertIsNone(BotCombatOps.evaluate_general_trade(bot, nonGenPath, threat, 1))


class GeneralTradeStrategyE2ETests(TestBase):
    """End-to-end decision tests: a REAL bot on a real simulator must pick
    the mutual-capture move when the trade is favorable, pick defense when
    it is unfavorable and defense is viable, and only fall back to the
    unfavorable trade when no adequate defense exists."""

    def _build_strategy_map(
            self,
            overrides: typing.Dict[typing.Tuple[int, int], str],
            turn: int = 49) -> MapBase:
        """Clones the trade fixture, applies tile-string overrides, and loads
        the ground-truth map."""
        tiles = dict(_TRADE_TILES)
        tiles.update(overrides)
        extra = ['turn=' + str(turn), 'player_index=0', 'aTiles=24', 'bTiles=31', 'cTiles=4']
        mapData = _build_trade_map_string(tiles, extra)
        map, general = self.load_map_and_general_from_string(mapData, turn=turn, player_index=0)
        return map

    def _run_bot_decision(
            self,
            overrides: typing.Dict[typing.Tuple[int, int], str],
            enemy_move: str = '3,5->2,5',
            turn: int = 49,
            perceived_enemy_city_count: int | None = None) -> typing.Tuple[GameSimulatorHost, EklipZBot]:
        """Builds the sim host (real bot on p0, afk opponents), queues the
        enemy's capture move on our general, and executes exactly one turn
        so moves_history[-1][0] is the bot's own decision.

        perceived_enemy_city_count seeds players[1].cityCount on the BOT's
        fog map before the turn - enemy cityCount is normally inferred from
        score-history city production over observed turns, so a fresh map
        cannot credit cities the enemy already owns. This models the state
        the bot would hold after watching their production."""
        map = self._build_strategy_map(overrides, turn)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=0, allAfkExceptMapPlayer=True)
        bot: EklipZBot = simHost.get_bot(0)
        if perceived_enemy_city_count is not None:
            simHost.get_player_map(0).players[1].cityCount = perceived_enemy_city_count
        simHost.queue_player_moves_str(1, enemy_move)
        simHost.queue_player_moves_str(2, 'None')
        simHost.execute_turn(run_real_time=False)
        return simHost, bot

    @staticmethod
    def _is_trade_move(move: Move | None) -> bool:
        """True when `move` is the mutual general capture (13,6)->(13,5)."""
        return (move is not None
                and (move.source.x, move.source.y) == _OUR_ATTACK_XY
                and (move.dest.x, move.dest.y) == _ENEMY_GENERAL_XY)

    # the fixture's bS22 source only models as a -1 non-lethal POTENTIAL
    # threat (swamp decays to 21 sending 20 vs our gen ticked to 21). bS26
    # is genuinely lethal (+3 net) yet still defendable by the aE9 desert
    # reinforce (gen ~29 vs 24 incoming). bS500 leaves no defense at all.
    _LETHAL_SOURCE = 'bS26'
    _OVERWHELMING_SOURCE = 'bS500'

    def test__e2e__favorable_trade_chosen_despite_viable_defense(self) -> None:
        """Enemy holds the economy lead and we have a viable defense (the
        aE9 desert tile can reinforce our 20-gen above the incoming 24):
        the bot must still prefer the FAVORABLE same-turn trade."""
        overrides = {
            _OUR_ATTACK_XY: 'a60',
            _ENEMY_ATTACK_XY: self._LETHAL_SOURCE,
        }
        simHost, bot = self._run_bot_decision(overrides, perceived_enemy_city_count=3)
        simMap = simHost.sim.sim_map
        ourMove = simHost.sim.moves_history[-1][0]
        self.assertTrue(
            self._is_trade_move(ourMove),
            f'favorable trade must be picked over viable defense, bot moved {ourMove}')
        # the atomic trade resolved: both survive and generals swap
        self.assertFalse(simHost.sim.players[0].dead, 'we survive the trade')
        self.assertFalse(simHost.sim.players[1].dead, 'enemy survives the trade')
        self.assertEqual(_ENEMY_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y))
        self.assertEqual(_OUR_GENERAL_XY, (simMap.generals[1].x, simMap.generals[1].y))

    def test__e2e__unfavorable_trade_defends_when_viable(self) -> None:
        """No enemy economy lead + a viable defense: the bot must NOT burn
        the mutual capture proactively - it defends instead."""
        simHost, bot = self._run_bot_decision({
            _OUR_ATTACK_XY: 'a60',
            _ENEMY_ATTACK_XY: self._LETHAL_SOURCE,
        })
        simMap = simHost.sim.sim_map
        ourMove = simHost.sim.moves_history[-1][0]
        self.assertFalse(
            self._is_trade_move(ourMove),
            f'unfavorable trade must not be proactive while defense is viable, bot moved {ourMove}')
        # we survived the incoming capture attempt without trading
        self.assertFalse(simHost.sim.players[0].dead, 'viable defense must keep us alive')
        self.assertNotEqual(
            _ENEMY_GENERAL_XY,
            (simMap.generals[0].x, simMap.generals[0].y),
            'no trade happened: our general must not relocate to the enemy gen')

    def test__e2e__unfavorable_trade_forced_survival_fallback(self) -> None:
        """No enemy economy lead and NO adequate defense (a 500-army source
        cannot be intercepted or out-defended): the bot must still use the
        unfavorable mutual capture as the survival fallback - it is the
        only line where both players live."""
        overrides = {
            _OUR_ATTACK_XY: 'a60',
            _ENEMY_ATTACK_XY: self._OVERWHELMING_SOURCE,
        }
        simHost, bot = self._run_bot_decision(overrides)
        simMap = simHost.sim.sim_map
        ourMove = simHost.sim.moves_history[-1][0]
        self.assertTrue(
            self._is_trade_move(ourMove),
            f'forced-survival fallback must still submit the trade move, bot moved {ourMove}')
        # the trade kept both players alive when defending was hopeless
        self.assertFalse(simHost.sim.players[0].dead, 'the trade is the only survival line')
        self.assertFalse(simHost.sim.players[1].dead, 'enemy survives the trade')
        self.assertEqual(_ENEMY_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y))
        self.assertEqual(_OUR_GENERAL_XY, (simMap.generals[1].x, simMap.generals[1].y))

    def test__e2e__all_in_losing_still_defends_unfavorable(self) -> None:
        """is_all_in_losing must not bypass the defense search for an
        unfavorable mutual capture: when a viable defense exists the bot
        defends even though the all-in classifier says we are losing.
        Only the classifier seam is pinned - the movement/defense search
        itself runs for real."""
        realClassifier = BotCombatOps.check_should_be_all_in_losing

        def _force_all_in_losing(b: EklipZBot) -> bool:
            """Pins ONLY the all-in-losing classifier seam: the flag is set
            and reported true while the movement and defense searches
            underneath run for real."""
            b.is_all_in_losing = True
            return True

        BotCombatOps.check_should_be_all_in_losing = _force_all_in_losing
        try:
            simHost, bot = self._run_bot_decision({
                _OUR_ATTACK_XY: 'a60',
                _ENEMY_ATTACK_XY: self._LETHAL_SOURCE,
            })
        finally:
            BotCombatOps.check_should_be_all_in_losing = realClassifier
        simMap = simHost.sim.sim_map
        ourMove = simHost.sim.moves_history[-1][0]
        self.assertFalse(
            self._is_trade_move(ourMove),
            f'all-in-losing must not skip a viable defense for an unfavorable trade, bot moved {ourMove}')
        self.assertFalse(simHost.sim.players[0].dead, 'the viable defense must keep us alive')
        self.assertNotEqual(
            _ENEMY_GENERAL_XY,
            (simMap.generals[0].x, simMap.generals[0].y),
            'no trade should have happened')

    def test__e2e__survival_fallback_preserves_half_move(self) -> None:
        """The forced-survival fallback must submit the EXACT evaluated
        move - a half-move trade sends a different stack than a full move
        and was priced accordingly. Only the king-kill search seam is
        pinned (the returned backup path is a real half-move path); the
        trade evaluation and the (hopeless) defense search run for real."""
        realCheck = BotCombatOps.check_for_king_kills_and_races

        def _half_backup_check(b: EklipZBot, threat: ThreatObj | None, force: bool = False) -> typing.Tuple[Move | None, Path | None, float]:
            """Pins only the king-kill search seam: returns a real
            half-move mutual-capture path as the chance-0 backup."""
            halfPath = Path()
            halfPath.add_next(b._map.GetTile(*_OUR_ATTACK_XY))
            halfPath.add_next(b._map.GetTile(*_ENEMY_GENERAL_XY), True)
            return None, halfPath, 0.0

        BotCombatOps.check_for_king_kills_and_races = _half_backup_check
        try:
            simHost, bot = self._run_bot_decision({
                _OUR_ATTACK_XY: 'a60',
                _ENEMY_ATTACK_XY: self._OVERWHELMING_SOURCE,
            })
        finally:
            BotCombatOps.check_for_king_kills_and_races = realCheck
        simMap = simHost.sim.sim_map
        ourMove = simHost.sim.moves_history[-1][0]
        self.assertTrue(
            self._is_trade_move(ourMove),
            f'expected the survival trade move, got {ourMove}')
        self.assertTrue(ourMove.move_half, 'the half-move flag must survive the fallback')
        # the half-move trade still resolved: both survive, generals swap
        self.assertFalse(simHost.sim.players[0].dead)
        self.assertFalse(simHost.sim.players[1].dead)
        self.assertEqual(_ENEMY_GENERAL_XY, (simMap.generals[0].x, simMap.generals[0].y))

if __name__ == '__main__':
    unittest.main()
