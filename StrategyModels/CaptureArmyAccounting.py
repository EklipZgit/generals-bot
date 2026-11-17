from __future__ import annotations

import typing
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CaptureArmyLossEstimate:
    """Conservative capture-combat loss interval, including score-consistency evidence."""

    minimum: int
    maximum: int
    assumed: int
    consistent: bool


@dataclass(frozen=True, slots=True)
class CaptureFogPoolTransfer:
    """Surviving fog pools after combat and the amounts inherited after halving."""

    cityArmyLost: int
    gatheredArmyLost: int
    cityArmyTransferred: int
    gatheredArmyTransferred: int
    gatheredArmyTrueTransferred: int


def estimate_capture_army_loss(
        victimScore: int,
        victimTiles: int,
        killerScoreBefore: int,
        killerScoreAfter: int,
        killerIncome: int,
        visibleDefense: int,
        otherPlayerArmyLossBudget: int = 0,
        killerIncomeUpper: int | None = None) -> CaptureArmyLossEstimate:
    """
    Bound pairwise combat loss D without treating per-tile ceil-halving as combat.

    With no unaccounted third-party score changes, deltaK = transfer - D and
    2*transfer = victimScore - D + oddSurvivingTiles. The captured general is
    destroyed, not inherited, so 0 <= oddSurvivingTiles <= victimTiles - 1.
    Consequently 3*D = victimScore - 2*deltaK + oddSurvivingTiles. Income is
    generated after the capture and must be removed from the killer's delta.
    Third-party losses can mask either participant's losses. If their total
    possible combat loss is X, widen both numerators by 2*X. Hidden city counts
    also require an income interval rather than treating an estimate as exact.
    visibleDefense is a proven physical loss floor, NOT the previous visible
    general stack: a victim can move that stack off its general before dying.
    Inconsistent evidence is explicitly flagged and does not invent fog loss.
    """
    delta = killerScoreAfter - killerScoreBefore - killerIncome
    upperIncome = killerIncome if killerIncomeUpper is None else killerIncomeUpper
    upperDelta = killerScoreAfter - killerScoreBefore - upperIncome
    numerator = victimScore - 2 * delta
    lowerNumerator = numerator - 2 * otherPlayerArmyLossBudget
    upperNumerator = victimScore - 2 * upperDelta + 2 * otherPlayerArmyLossBudget
    lower = max(0, visibleDefense, -(-lowerNumerator // 3))
    upper = min(victimScore, (upperNumerator + max(0, victimTiles - 1)) // 3)
    if lower > upper:
        known = min(victimScore, max(0, visibleDefense))
        return CaptureArmyLossEstimate(known, victimScore, known, False)
    return CaptureArmyLossEstimate(lower, upper, lower, True)


@dataclass(frozen=True, slots=True)
class CaptureScoreUncertainty:
    """Score-only uncertainty from hidden income and simultaneous third-party combat."""

    killerIncomeMinimum: int
    killerIncomeMaximum: int
    otherPlayerArmyLossBudget: int


@dataclass(frozen=True, slots=True)
class CapturePlayerScoreSnapshot:
    """Primitive scoreboard + visibility fields for one player at a capture boundary."""

    score: int
    tiles: int
    cities: int
    visibleGeneralArmy: int
    visibleOwnedTiles: int
    fogCityCount: int

    def to_dict(self) -> dict[str, int]:
        """Serializes this snapshot to a plain dict for the ot_capture_state JSON boundary."""
        return {
            'score': self.score,
            'tiles': self.tiles,
            'cities': self.cities,
            'visibleGeneralArmy': self.visibleGeneralArmy,
            'visibleOwnedTiles': self.visibleOwnedTiles,
            'fogCityCount': self.fogCityCount,
        }

    @staticmethod
    def from_dict(data: dict[str, typing.Any]) -> CapturePlayerScoreSnapshot:
        """Rebuilds a snapshot from its ot_capture_state dict representation."""
        return CapturePlayerScoreSnapshot(
            score=int(data['score']),
            tiles=int(data['tiles']),
            cities=int(data['cities']),
            visibleGeneralArmy=int(data['visibleGeneralArmy']),
            visibleOwnedTiles=int(data['visibleOwnedTiles']),
            fogCityCount=int(data['fogCityCount']))


def get_capture_score_uncertainty(
        previousScores: tuple[CapturePlayerScoreSnapshot, ...],
        finalScores: tuple[CapturePlayerScoreSnapshot, ...],
        captureTurn: int,
        victim: int,
        killer: int) -> CaptureScoreUncertainty:
    """
    Bound unobserved income and combat without using hidden estimated city counts.

    Income occurs after all moves. Every owned tile could be a city, so its
    tile count bounds both city and land generation. Third-party score deficits
    bound their possible attacks on either participant, including neutral
    costs conservatively. Multiple deaths can hide deficits behind another
    inheritance: in that case use the entire pre-update army plus possible
    generation as the external budget instead of assuming a single capture.
    """
    incomeTicks = int(captureTurn % 2 == 0) + int(captureTurn % 50 == 0)
    maximumKillerIncome = finalScores[killer].tiles * incomeTicks
    otherLossBudget = 0
    deaths = 0
    for index, (previous, final) in enumerate(zip(previousScores, finalScores, strict=True)):
        if previous.tiles > 0 and final.tiles == 0:
            deaths += 1
        if index in (victim, killer):
            continue
        maximumIncome = final.tiles * incomeTicks
        otherLossBudget += max(0, previous.score + maximumIncome - final.score)
    if deaths > 1:
        otherLossBudget = sum(
            previous.score + final.tiles * incomeTicks
            for previous, final in zip(previousScores, finalScores, strict=True))
    return CaptureScoreUncertainty(0, maximumKillerIncome, otherLossBudget)


@dataclass(frozen=True, slots=True)
class CaptureFogSnapshot:
    """Frozen pre-zero fog accounting for a player whose scoreboard hit 0/0 before capture text arrived."""

    captureTurn: int
    team: int
    queueAmounts: dict[int, int]
    fogArmy: int
    fogArmyTrue: int
    fogCityArmy: int
    fogCityCount: int
    previousScores: tuple[CapturePlayerScoreSnapshot, ...]
    finalScores: tuple[CapturePlayerScoreSnapshot, ...]

    def to_dict(self) -> dict[str, typing.Any]:
        """Serializes this snapshot to a plain dict for the ot_capture_state JSON boundary."""
        return {
            'captureTurn': self.captureTurn,
            'team': self.team,
            'queueAmounts': {str(size): count for size, count in self.queueAmounts.items()},
            'fogArmy': self.fogArmy,
            'fogArmyTrue': self.fogArmyTrue,
            'fogCityArmy': self.fogCityArmy,
            'fogCityCount': self.fogCityCount,
            'previousScores': [score.to_dict() for score in self.previousScores],
            'finalScores': [score.to_dict() for score in self.finalScores],
        }

    @staticmethod
    def from_dict(data: dict[str, typing.Any]) -> CaptureFogSnapshot:
        """Rebuilds a snapshot from its ot_capture_state dict representation."""
        return CaptureFogSnapshot(
            captureTurn=int(data['captureTurn']),
            team=int(data['team']),
            queueAmounts={int(size): int(count) for size, count in data['queueAmounts'].items()},
            fogArmy=int(data['fogArmy']),
            fogArmyTrue=int(data['fogArmyTrue']),
            fogCityArmy=int(data['fogCityArmy']),
            fogCityCount=int(data['fogCityCount']),
            previousScores=tuple(CapturePlayerScoreSnapshot.from_dict(score) for score in data['previousScores']),
            finalScores=tuple(CapturePlayerScoreSnapshot.from_dict(score) for score in data['finalScores']))


def get_capture_fog_pool_transfer(
        fogArmy: int,
        fogArmyTrue: int,
        fogCityArmy: int,
        annihilatedArmy: int,
        visibleDefense: int) -> CaptureFogPoolTransfer:
    """
    Remove combat before halving, without charging a visible general to fog.

    Hidden general/city army pays first; excess burns both estimates of the
    gathered fog army. Queue entries are independently halved per tile by the
    caller and are never combined into one aggregate rounding operation.
    """
    hiddenLoss = max(0, annihilatedArmy - visibleDefense)
    cityLoss = min(max(0, fogCityArmy), hiddenLoss)
    gatheredLoss = hiddenLoss - cityLoss
    remainingCity = max(0, fogCityArmy - cityLoss)
    remainingFog = max(0, fogArmy - gatheredLoss)
    remainingTrueFog = max(0, fogArmyTrue - gatheredLoss)
    return CaptureFogPoolTransfer(
        cityArmyLost=cityLoss,
        gatheredArmyLost=gatheredLoss,
        cityArmyTransferred=(remainingCity + 1) // 2,
        gatheredArmyTransferred=(remainingFog + 1) // 2,
        gatheredArmyTrueTransferred=(remainingTrueFog + 1) // 2)
