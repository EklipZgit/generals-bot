"""
Pure strategic evaluation of a mutual general capture ("general trade").

Both generals are captured atomically; every non-gen tile each player owns
transfers to the other side at ceil(army/2), and each new general lands at
the sender's leftover minus the enemy general's defense (UNHALVED - the
server does not halve the capture remnant). This module only decides
whether the exchange is desirable; it never mutates board or path state.

Tests: UnitTests/test_GeneralTradeEvaluation.py
"""

import typing
from dataclasses import dataclass


@dataclass(slots=True)
class GeneralTradeSide:
    """
    Estimated state of one side immediately BEFORE the atomic trade, after
    attack-source reserves are already held back.

    @param total_army: the player's whole army on the score - includes the
        sent force, the general's defense army, and all other land.
    @param general_defense: army currently on that player's general (or its
        reserve when the general itself is the attack source).
    @param sent_army: army actually sent into the enemy general.
    @param non_general_tile_count: tiles the player owns, general excluded
        (scoreboard tileCount - 1).
    @param known_non_general_armies: post-reserve armies of non-gen tiles
        whose state is concretely known; the remainder is inferred from
        the score total.
    @param economy_value: tileCount-deserts + 30*cityCount, the existing
        winning_on_economy convention.
    """
    total_army: int
    general_defense: int
    sent_army: int
    non_general_tile_count: int
    known_non_general_armies: typing.Tuple[int, ...]
    economy_value: float


@dataclass(slots=True)
class GeneralTradeEvaluation:
    """
    Projection of the post-trade position. `our_post_army` is conservative
    GIVEN the caller's input estimates (their unknown tiles assume the LOW
    halving bound, ours assume the HIGH bound); the bounds cover unknown
    per-tile halving rounding only, not fog or combat uncertainty in the
    inputs themselves.
    """
    our_new_general_army: int
    opponent_new_general_army: int
    our_post_army: int
    opponent_post_army: int
    economy_gain: float
    current_position_value: float
    post_position_value: float
    favorable: bool


def evaluate_general_trade(ours: GeneralTradeSide, opponent: GeneralTradeSide) -> GeneralTradeEvaluation | None:
    """
    Projects an atomic mutual general capture and decides whether we want
    it. Returns None when either capture fails or the inputs are
    internally inconsistent (caller could not account for the armies it
    claims to know) - never clamps or fabricates state.

    Tests: UnitTests/test_GeneralTradeEvaluation.py
    """
    for side in (ours, opponent):
        if (side.total_army < 0 or side.general_defense < 0 or side.sent_army < 0
                or side.non_general_tile_count < 0 or any(a < 0 for a in side.known_non_general_armies)):
            raise ValueError(f'negative primitive input in GeneralTradeSide {side}')

    # both captures must actually succeed
    if ours.sent_army <= opponent.general_defense or opponent.sent_army <= ours.general_defense:
        return None

    def sideProjection(side: GeneralTradeSide) -> typing.Tuple[int, int, int] | None:
        """Returns (knownHalvedSum, unknownArmy, unknownTileCount) or None."""
        remaining = side.total_army - side.general_defense - side.sent_army
        knownSum = sum(side.known_non_general_armies)
        knownCount = len(side.known_non_general_armies)
        if remaining < 0 or knownSum > remaining or knownCount > side.non_general_tile_count:
            return None
        unknownArmy = remaining - knownSum
        unknownCount = side.non_general_tile_count - knownCount
        if unknownCount == 0 and unknownArmy > 0:
            return None
        if unknownCount == 0:
            # fully known: exact per-tile ceil sum
            return (sum((n + 1) // 2 for n in side.known_non_general_armies), 0, 0)
        knownHalvedSum = sum((n + 1) // 2 for n in side.known_non_general_armies)
        return (knownHalvedSum, unknownArmy, unknownCount)

    oursProj = sideProjection(ours)
    oppProj = sideProjection(opponent)
    if oursProj is None or oppProj is None:
        return None

    ourKnownHalved, ourUnknownArmy, ourUnknownCount = oursProj
    oppKnownHalved, oppUnknownArmy, oppUnknownCount = oppProj

    # unknown-tile halving bounds: concentrating army minimizes the ceil
    # sum (lower), spreading evenly maximizes it (upper)
    oppUnknownLower = (oppUnknownArmy + 1) // 2
    ourUnknownUpper = (ourUnknownArmy + min(ourUnknownArmy, ourUnknownCount)) // 2

    ourNewGen = ours.sent_army - opponent.general_defense
    theirNewGen = opponent.sent_army - ours.general_defense

    # conservative for OUR selection given these estimates: their side
    # counts at the low bound, our side at the high bound - the bounds
    # cover unknown per-tile halving rounding, not estimation error in the
    # inputs themselves
    ourPost = oppKnownHalved + oppUnknownLower + ourNewGen
    theirPost = ourKnownHalved + ourUnknownUpper + theirNewGen

    economyGain = opponent.economy_value - ours.economy_value
    currentValue = float(ours.total_army - opponent.total_army) - economyGain
    postValue = float(ourPost - theirPost) + economyGain

    favorable = economyGain > 0 and postValue > max(0.0, currentValue)

    return GeneralTradeEvaluation(
        our_new_general_army=ourNewGen,
        opponent_new_general_army=theirNewGen,
        our_post_army=ourPost,
        opponent_post_army=theirPost,
        economy_gain=economyGain,
        current_position_value=currentValue,
        post_position_value=postValue,
        favorable=favorable)
