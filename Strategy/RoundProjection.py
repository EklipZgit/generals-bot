import typing
from dataclasses import dataclass

from Interfaces.TilePlanInterface import TilePlanInterface
from StrategyModels.ExpansionPotential import ExpansionPotential
from base.client.map import MapBase, TeamStats
from base.client.tile import Tile


@dataclass(slots=True)
class RoundPlanProjection:
    """
    A physically projected end-of-round state for one side. Unlike the
    heuristic econValue utilities, these are material quantities: tile and city
    counts, a standing-army estimate for the end of the cycle, and recurring
    income for the next cycle. Used by WinConditionAnalyzer's projected-round-loss
    check and the neutral-city opportunity-cost check in build_expansion_plan
    (see Tests/test_CityRoundDecisions.py).
    """
    tile_count: int
    city_count: int
    army: float
    next_cycle_income: float


@dataclass(slots=True)
class RoundOutcomeProjection:
    """Projected end-of-round states for us and the target enemy team."""
    friendly: RoundPlanProjection
    enemy: RoundPlanProjection


def _count_city_ticks(startTurn: int, endTurn: int) -> int:
    """Cities produce +1 army every other turn; count production ticks in (startTurn, endTurn]."""
    return endTurn // 2 - startTurn // 2


def _ordered_completable_options(
        potential: ExpansionPotential,
        remainingCycleTurns: int) -> typing.List[typing.Tuple[TilePlanInterface, int]]:
    """
    Deduplicated options from an ExpansionPotential: selected_option first, then every
    all_paths entry that isn't the same option. Each option's completion time is the
    cumulative max(previousCompletion, requiredDelay) + length; options that cannot
    finish inside the cycle are excluded (they buy nothing this round).
    """
    options: typing.List[TilePlanInterface] = []
    if potential.selected_option is not None:
        options.append(potential.selected_option)
    for option in potential.all_paths:
        if not any(option is o for o in options):
            options.append(option)

    completable: typing.List[typing.Tuple[TilePlanInterface, int]] = []
    previousCompletion = 0
    for option in options:
        completion = max(previousCompletion, option.requiredDelay) + option.length
        previousCompletion = completion
        if completion <= remainingCycleTurns:
            completable.append((option, completion))
    return completable


def _project_side(
        sidePlayers: typing.Set[int],
        enemyPlayers: typing.Set[int],
        potential: ExpansionPotential,
        enemyPotential: ExpansionPotential,
        teamStats: TeamStats,
        turn: int,
        remainingCycleTurns: int,
        cycleTurns: int) -> typing.Tuple[RoundPlanProjection, int]:
    """
    Project one side's end-of-round state. Returns the projection plus this side's
    share of the shared enemy-combat cost (armies on tiles taken from the opposing
    team by this side's plan), which the caller applies to BOTH sides symmetrically.
    """
    completable = _ordered_completable_options(potential, remainingCycleTurns)

    capturedTiles: typing.Set[Tile] = set()
    neutralCost = 0
    combatCost = 0
    capturedCityTicks = 0
    capturedCityCount = 0
    capturedDeserts = 0
    for option, completion in completable:
        for tile in option.tileSet:
            # isNotPathable (mountain / undiscovered obstacle / override) skips real
            # blockers only; a known costly neutral city IS pathable and must count.
            if tile in capturedTiles or tile.isNotPathable:
                continue
            # only tiles initially owned by someone else count as captures for this side
            if tile.player in sidePlayers:
                continue
            # never project a general kill as a new city
            if tile.isGeneral:
                continue
            capturedTiles.add(tile)
            if tile.player == -1:
                neutralCost += max(0, tile.army)
            elif tile.player in enemyPlayers:
                combatCost += max(0, tile.army)
            if tile.isCity:
                capturedCityCount += 1
                # captured cities tick on the capture update itself when completion
                # is even: (turn+completion-1, turn+remaining] per the live server.
                capturedCityTicks += (turn + remainingCycleTurns) // 2 - (turn + completion - 1) // 2
            if tile.isDesert:
                capturedDeserts += 1

    # enemy captures of OUR tiles reduce our count; their army cost is part of the
    # shared combat pool accounted by the caller, not here.
    lostTileSet: typing.Set[Tile] = set()
    lostCityCount = 0
    lostCityTicks = 0
    lostDeserts = 0
    for option, completion in _ordered_completable_options(enemyPotential, remainingCycleTurns):
        for tile in option.tileSet:
            if tile in lostTileSet or tile.isNotPathable or tile.isGeneral:
                continue
            if tile.player not in sidePlayers:
                continue
            lostTileSet.add(tile)
            if tile.isCity:
                lostCityCount += 1
                lostCityTicks += (turn + remainingCycleTurns) // 2 - (turn + completion - 1) // 2
            if tile.isDesert:
                lostDeserts += 1

    endTurn = turn + remainingCycleTurns
    baseCityTicks = _count_city_ticks(turn, endTurn)

    projectedTileCount = teamStats.tileCount + len(capturedTiles) - len(lostTileSet)
    projectedCityCount = teamStats.cityCount + capturedCityCount - lostCityCount
    projectedDeserts = teamStats.deserts + capturedDeserts - lostDeserts

    # owned-tile bonus income cancels against the standing-army deduction for
    # owned tiles, leaving current score + city growth - purchase costs.
    army = (
        teamStats.score
        + teamStats.cityCount * baseCityTicks
        + capturedCityTicks
        - lostCityTicks
        - neutralCost
        - projectedDeserts)

    nextCycleIncome = projectedTileCount - projectedDeserts + projectedCityCount * (cycleTurns // 2)

    return (
        RoundPlanProjection(
            tile_count=projectedTileCount,
            city_count=projectedCityCount,
            army=army,
            next_cycle_income=nextCycleIncome),
        combatCost)


def project_round_outcome(
        map: MapBase,
        ourTeamStats: TeamStats,
        enemyTeamStats: TeamStats,
        ourExpansionPotential: ExpansionPotential,
        enemyExpansionPotential: ExpansionPotential,
        cycleTurns: int) -> RoundOutcomeProjection:
    """
    Project the end-of-round material state for us and the target enemy team from
    each side's ExpansionPotential. Pure estimate from the plans' real tiles and
    timing; no opponent-momentum extrapolation, no speculative extra captures, and
    no heuristic econValue used as physical income. Diagnostics should treat this
    as projected, not an exact simulation.
    """
    remainingCycleTurns = cycleTurns - (map.turn % cycleTurns)
    ourPlayers = set(ourTeamStats.teamPlayers)
    enemyPlayers = set(enemyTeamStats.teamPlayers)

    friendly, friendlyCombatCost = _project_side(
        ourPlayers, enemyPlayers, ourExpansionPotential, enemyExpansionPotential,
        ourTeamStats, map.turn, remainingCycleTurns, cycleTurns)
    enemy, enemyCombatCost = _project_side(
        enemyPlayers, ourPlayers, enemyExpansionPotential, ourExpansionPotential,
        enemyTeamStats, map.turn, remainingCycleTurns, cycleTurns)

    # tiles taken from the opposing team by either side's plan cost both sides
    # the defender's army; apply the shared cost symmetrically.
    sharedCombatCost = friendlyCombatCost + enemyCombatCost
    friendly.army -= sharedCombatCost
    enemy.army -= sharedCombatCost

    return RoundOutcomeProjection(friendly=friendly, enemy=enemy)
