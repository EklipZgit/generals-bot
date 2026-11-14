"""
Unit tests for Strategy/GeneralTradeEvaluator.evaluate_general_trade -
the pure projection of a mutual general capture. Every expected value is
hand-computed from the settled formulas: non-gens halve per-tile (ceil),
new generals land at sent-minus-defense unhalved, unknown armies bound
conservatively (their side LOW, our side HIGH).
"""

import typing
import unittest

from TestBase import TestBase
from Strategy.GeneralTradeEvaluator import GeneralTradeSide, GeneralTradeEvaluation, evaluate_general_trade


def _side(
        total: int,
        genDef: int,
        sent: int,
        nongens: int,
        known: typing.Tuple[int, ...] = (),
        econ: float = 0.0) -> GeneralTradeSide:
    """Convenience constructor - armies are raw values as in the board."""
    return GeneralTradeSide(
        total_army=total,
        general_defense=genDef,
        sent_army=sent,
        non_general_tile_count=nongens,
        known_non_general_armies=known,
        economy_value=econ)


class GeneralTradeEvaluationTests(TestBase):
    def test__both_strict_captures_required(self) -> None:
        """sent <= enemy gen defense -> no trade possible -> None."""
        ours = _side(50, 10, 25, 3, (5, 4, 6), econ=0)
        # ours.sent (25) > opp genDef (10) but opp.sent (10) <= ours genDef (10)
        opp = _side(30, 10, 10, 3, (4, 3, 3), econ=0)
        self.assertIsNone(evaluate_general_trade(ours, opp))

    def test__favorable_economy_lead(self) -> None:
        """
        Opponent holds an economy lead we acquire: p1 total 100 (gen 20, sent
        30, nongens 50 over 5 tiles all known), p2 total 60 (gen 15, sent 25,
        nongens 20 over 4 tiles all known); p2 econ 100 vs p1 econ 0.

        ourNewGen = 30-15 = 15; theirNewGen = 25-20 = 5.
        ourPost = ceil-halved p2 nongens (sum known = 20 -> halved per-tile
          (5,4,6,5) -> 3+2+3+3 = 11) + 15 = 26.
        theirPost = ceil-halved p1 nongens (50 over (10,10,10,10,10) -> 5*5=25)
          + 5 = 30.
        economyGain = 100-0 = 100; currentValue = 100-60-100 = -60;
        postValue = 26-30+100 = 96 > max(0,-60)=0 -> favorable.
        """
        ours = _side(100, 20, 30, 5, (10, 10, 10, 10, 10), econ=0.0)
        opp = _side(60, 15, 25, 4, (5, 4, 6, 5), econ=100.0)
        ev = evaluate_general_trade(ours, opp)
        self.assertIsNotNone(ev)
        self.assertEqual(15, ev.our_new_general_army)
        self.assertEqual(5, ev.opponent_new_general_army)
        self.assertEqual(26, ev.our_post_army)
        self.assertEqual(30, ev.opponent_post_army)
        self.assertEqual(100.0, ev.economy_gain)
        self.assertEqual(-60.0, ev.current_position_value)
        self.assertEqual(96.0, ev.post_position_value)
        self.assertTrue(ev.favorable)

    def test__reverse_economy_lead_avoids(self) -> None:
        """Opponent has no econ advantage (gain <= 0): never favorable."""
        ours = _side(100, 20, 30, 5, (10, 10, 10, 10, 10), econ=100.0)
        opp = _side(60, 15, 25, 4, (5, 4, 6, 5), econ=0.0)
        ev = evaluate_general_trade(ours, opp)
        self.assertIsNotNone(ev)
        self.assertFalse(ev.favorable, 'we already hold the econ lead - trading it away is never proactive')

    def test__huge_enemy_gen_survivor_flips_decision(self) -> None:
        """
        Same econ lead but the enemy's sent army massively survives: their
        new gen lands huge, post value drops below zero -> not favorable.
        """
        ours = _side(100, 20, 30, 5, (10, 10, 10, 10, 10), econ=0.0)
        # opponent sends 60 into ours' 20-def gen -> theirNewGen = 40
        opp = _side(95, 15, 60, 4, (5, 4, 6, 5), econ=100.0)
        ev = evaluate_general_trade(ours, opp)
        self.assertIsNotNone(ev)
        # ourPost = 11 + 15 = 26; theirPost = 25 + 40 = 65
        self.assertEqual(26, ev.our_post_army)
        self.assertEqual(65, ev.opponent_post_army)
        self.assertEqual(26 - 65 + 100, ev.post_position_value)
        # postValue 61 > 0 and econ gain > 0 -> still favorable here; shrink
        # our econ gain below the survivor gap to flip the decision
        self.assertTrue(ev.favorable)
        # with a tiny econ gap the survivor dominates -> unfavorable
        opp2 = _side(95, 15, 60, 4, (5, 4, 6, 5), econ=20.0)
        ev2 = evaluate_general_trade(ours, opp2)
        self.assertIsNotNone(ev2)
        self.assertEqual(26 - 65 + 20, ev2.post_position_value)
        self.assertFalse(ev2.favorable, 'their gen survives huge -> econ gain does not compensate')

    def test__survivor_swing_at_constant_economy(self) -> None:
        """
        Holding the economy gap FIXED (+50), only the size of the enemy's
        surviving attack stack changes: a modest enemy sent leaves the trade
        favorable while a massive one flips it unfavorable - survivor
        strength is weighed, not just production.

        ours: total 100, genDef 20, sent 40, nongens 40 over 5 (2 known 3,5).
        theirs small: total 90, genDef 10, sent 30, nongens 50 over 5 (2 known 2,2), econ +50.
          ourNewGen 40-10=30, theirNewGen 30-20=10.
          ourPost = theirKnownHalved(1+1) + theirUnknownLower((50-4=46)+1)//2=23 + 30 = 55.
          theirPost = ourKnownHalved(2+3=5) + ourUnknownUpper((40-8=32)+3)//2=17 + 10 = 32.
          post = 55-32+50 = 73 > max(0, current=100-90-50=-40) -> favorable.
        theirs big: total 200, sent 150 (theirNewGen 130, remaining 40 same unknowns).
          theirPost = 5+17+130 = 152 -> post = 55-152+50 = -47 <= 0 -> unfavorable.
        """
        ours = _side(100, 20, 40, 5, (3, 5), econ=0.0)
        oppSmall = _side(90, 10, 30, 5, (2, 2), econ=50.0)
        oppBig = _side(200, 10, 150, 5, (2, 2), econ=50.0)
        small = evaluate_general_trade(ours, oppSmall)
        self.assertIsNotNone(small)
        self.assertEqual(55, small.our_post_army)
        self.assertEqual(32, small.opponent_post_army)
        self.assertEqual(50.0, small.economy_gain)
        self.assertTrue(small.favorable, 'modest enemy survivor + econ gain must be favorable')
        big = evaluate_general_trade(ours, oppBig)
        self.assertIsNotNone(big)
        self.assertEqual(130, big.opponent_new_general_army)
        self.assertEqual(152, big.opponent_post_army)
        self.assertEqual(50.0, big.economy_gain, 'same economy gap in both cases')
        self.assertFalse(big.favorable, 'massive enemy survivor flips the decision at the SAME economy gap')

    def test__old_enemy_general_army_annihilated_before_halving(self) -> None:
        """
        A big defending general does NOT halve - its full defense is destroyed
        and the attacker lands sent-minus-defense unhalved as the new gen.
        """
        # enemy general defended 100; we send 30 -> capture fails
        ours = _side(100, 20, 30, 5, (10, 10, 10, 10, 10), econ=0.0)
        oppBig = _side(145, 100, 25, 4, (5, 4, 6, 5), econ=100.0)
        self.assertIsNone(evaluate_general_trade(ours, oppBig))
        # send 130: 130-100 = 30 leftover on their gen
        ours2 = _side(200, 20, 130, 5, (10, 10, 10, 10, 10), econ=0.0)
        ev = evaluate_general_trade(ours2, oppBig)
        self.assertIsNotNone(ev)
        self.assertEqual(30, ev.our_new_general_army, 'our capture remnant is sent-minus-defense, never halved')

    def test__per_tile_halving_not_sum_halving(self) -> None:
        """ceil is applied per tile: (5,3) -> 3+2=5, not ceil(8/2)=4."""
        ours = _side(28, 5, 15, 2, (5, 3), econ=0.0)
        opp = _side(24, 5, 11, 2, (5, 3), econ=60.0)
        ev = evaluate_general_trade(ours, opp)
        self.assertIsNotNone(ev)
        # ourPost = halved(5)+halved(3) + newGen(15-5=10) = 3+2+10 = 15
        self.assertEqual(15, ev.our_post_army)

    def test__unknown_army_bounds_conservative(self) -> None:
        """
        Their unknown tiles assume the LOWER halving bound for our post army;
        ours assume the UPPER bound for theirs.
        """
        # ours: 50 total, gen 10, sent 20 -> nongen remaining 20 over 4 tiles,
        # only 1 known (5) -> unknown 15 over 3 tiles:
        #   upper bound = (15 + min(15,3)) // 2 = 18//2 = 9
        ours = _side(50, 10, 20, 4, (5,), econ=0.0)
        # opp: 40 total, gen 8, sent 15 -> nongen remaining 17 over 5 tiles,
        # none known -> unknown 17 over 5:
        #   lower bound = (17+1)//2 = 9
        opp = _side(40, 8, 15, 5, (), econ=70.0)
        ev = evaluate_general_trade(ours, opp)
        self.assertIsNotNone(ev)
        # ourPost = oppKnown(0) + oppUnknownLower(9) + ourNewGen(20-8=12) = 21
        self.assertEqual(21, ev.our_post_army)
        # theirPost = ourKnownHalved(3) + ourUnknownUpper(9) + theirNewGen(15-10=5) = 17
        self.assertEqual(17, ev.opponent_post_army)

    def test__inconsistent_projection_rejected(self) -> None:
        """knownSum > remaining or count > tile count or leftover army with
        zero unknown tiles -> None, never clamped."""
        # known non-gens (20) exceed remaining (30-5-10=15)
        bad1 = _side(30, 5, 10, 3, (20,), econ=0.0)
        good = _side(40, 8, 15, 5, (), econ=70.0)
        self.assertIsNone(evaluate_general_trade(bad1, good))
        # 4 known tiles but non_general_tile_count claims 3
        bad2 = _side(50, 5, 10, 3, (10, 10, 10, 5), econ=0.0)
        self.assertIsNone(evaluate_general_trade(bad2, good))
        # unknownArmy > 0 with zero unknown tiles
        bad3 = _side(50, 5, 10, 2, (10, 10), econ=0.0)
        self.assertIsNone(evaluate_general_trade(bad3, good))

    def test__neutral_utility_not_eager(self) -> None:
        """Zero econ gain -> postValue > max(0,current) still fails the
        economyGain > 0 gate: neutral trades are never proactive."""
        ours = _side(100, 20, 30, 5, (10, 10, 10, 10, 10), econ=0.0)
        opp = _side(60, 15, 25, 4, (5, 4, 6, 5), econ=0.0)
        ev = evaluate_general_trade(ours, opp)
        self.assertIsNotNone(ev)
        self.assertFalse(ev.favorable, 'no econ advantage -> never a proactive trade')

    def test__negative_inputs_raise(self) -> None:
        """Broken callers surface as ValueError, not silent clamps."""
        ours = _side(50, -1, 20, 4, (5,), econ=0.0)
        opp = _side(40, 8, 15, 5, (), econ=70.0)
        with self.assertRaises(ValueError):
            evaluate_general_trade(ours, opp)


if __name__ == '__main__':
    unittest.main()
