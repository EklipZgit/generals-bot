"""Material and timing envelopes for an unseen attack after a general reveal."""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class EnemyAllInWave:
    """One possible launch, with separate preparation and visible-response time."""

    gather_turns: int
    attack_turns: int
    warning_turns: int
    launch_turn: int
    arrival_turn: int
    ready_turn: int
    launch_army: int
    bank_army: int
    ordinary_army: int
    city_growth: int
    tile_growth: int


@dataclass(slots=True, frozen=True)
class EnemyAllInDefense:
    """One independent enemy's wave plus material excluded from its fog bank."""

    wave: EnemyAllInWave
    other_attack_surplus: int
    route_cost: int


# UnitTests/test_AnticipatedAllIn.py::test_round_bonus_requires_real_collection_moves:
# A round bonus cannot teleport every ordinary tile's new army into a launch.
# Unlike a stationary general's defensive reserve, an outgoing wave must collect
# those sources before launching; already-drained tiles can be revisited.
def forecast_enemy_all_in(
    start_turn: int,
    gather_turns: int,
    attack_turns: int,
    warning_turns: int,
    bank_army: int,
    standing_cap: int,
    ordinary_armies: tuple[int, ...],
    ordinary_tile_count: int,
    city_count: int,
    cycle_turns: int = 50,
) -> EnemyAllInWave:
    """Upper-bound an outgoing stack under the supplied tracker material model.

    Bank and standing inputs use movable-surplus units. Ordinary sources contain
    raw tile armies, including the one that must remain. The caller excludes
    visible armies already priced as separate current threats from both the
    standing cap and these sources. Missing ordinary sources start at one, not
    an invented surplus. Source travel is free, at most one source is collected
    per move, and all city income is available without a collection move.

    City income includes the launch tick. Ordinary growth can be collected only
    on a subsequent available gathering move; the retained head receives each
    round bonus too. One head garrison is added after capping old material.
    These deliberately optimistic enemy assumptions must not be mistaken for
    evidence that an unseen opponent actually chose to gather.
    """
    if (
        start_turn < 0
        or gather_turns < 0
        or attack_turns < 1
        or not 0 <= warning_turns <= attack_turns
        or ordinary_tile_count < 0
        or city_count < 0
        or cycle_turns < 1
    ):
        raise ValueError("Invalid anticipated all-in timing or source counts")

    cap = max(0, standing_cap)
    bank = min(cap, max(0, bank_army))
    sources = sorted(
        (max(0, army - 1) for army in ordinary_armies),
        reverse=True,
    )[:ordinary_tile_count]
    sources.extend([0] * (ordinary_tile_count - len(sources)))
    growth = [0] * len(sources)
    ordinary_collected = 0
    growth_collected = 0

    for offset in range(gather_turns):
        move_turn = start_turn + offset
        if move_turn > start_turn and move_turn % cycle_turns == 0:
            growth = [army + 1 for army in growth]
        if not sources:
            continue
        source = max(
            range(len(sources)),
            key=lambda index: sources[index] + growth[index],
        )
        ordinary_collected += min(
            sources[source],
            cap - bank - ordinary_collected,
        )
        growth_collected += growth[source]
        sources[source] = 0
        growth[source] = 0

    launch_turn = start_turn + gather_turns
    city_growth = city_count * (launch_turn // 2 - start_turn // 2)
    head_growth = launch_turn // cycle_turns - start_turn // cycle_turns
    tile_growth = head_growth + growth_collected
    arrival_turn = launch_turn + attack_turns
    return EnemyAllInWave(
        gather_turns=gather_turns,
        attack_turns=attack_turns,
        warning_turns=warning_turns,
        launch_turn=launch_turn,
        arrival_turn=arrival_turn,
        ready_turn=max(start_turn, arrival_turn - warning_turns - 1),
        launch_army=bank + ordinary_collected + city_growth + tile_growth + 1,
        bank_army=bank,
        ordinary_army=ordinary_collected,
        city_growth=city_growth,
        tile_growth=tile_growth,
    )


# UnitTests/test_AnticipatedAllIn.py::test_donating_general_does_not_create_free_defense:
# Moving the existing garrison onto a neighboring tile is not reinforcement.
# Price the garrison left by the literal gather and the separate visible threat
# together, rather than letting the same army cover both waves independently.
def minimum_mobile_army(
    wave: EnemyAllInWave,
    at_turn: int,
    general_army: int,
    other_attack_surplus: int,
    route_cost: int,
    deployment_turns: int,
    cycle_turns: int = 50,
) -> int:
    """Reserve a mobile stack after accounting for the remaining home garrison.

    ``general_army`` is read from the candidate gather's projected end position,
    not from the original board. The general then stays home until arrival.
    ``other_attack_surplus`` is army excluded from the wave's bank/standing cap
    that could join it, including any separately forecast growth. It is charged
    once; route_cost contains movement and irreducible tolls, never our mobile
    reserve again. Only one returning reserve and one retained general are
    credited, so disconnected nominal defense cannot satisfy this calculation.
    """
    if at_turn < 0 or deployment_turns < 0 or route_cost < 0 or cycle_turns < 1:
        raise ValueError("Invalid reserve deployment inputs")
    arrival = max(at_turn, wave.arrival_turn)
    retained_general = (
        max(0, general_army)
        + arrival // 2 - at_turn // 2
        + arrival // cycle_turns - at_turn // cycle_turns
    )
    incoming = max(0, wave.launch_army + max(0, other_attack_surplus) - route_cost)
    return max(
        wave.launch_army,
        incoming - retained_general + deployment_turns + 1,
    )


# UnitTests/test_AnticipatedAllIn.py::test_independent_enemies_share_only_one_home_garrison:
# Concurrent enemies cannot each receive credit for our entire home garrison.
def minimum_combined_mobile_army(
    enemies: tuple[EnemyAllInDefense, ...],
    at_turn: int,
    general_army: int,
    deployment_turns: int,
    cycle_turns: int = 50,
) -> int:
    """Cover one alternative wave per enemy, without double-crediting defense.

    A single enemy gets the time-aware calculation above. For concurrent enemies
    require the whole mobile stack before the earliest deployment deadline and
    conservatively omit future home income: this covers arbitrary arrival order
    without pretending we receive the same garrison or future income repeatedly.
    Fast and delayed alternatives for the SAME enemy must not be passed together.
    """
    if at_turn < 0 or deployment_turns < 0 or cycle_turns < 1:
        raise ValueError("Invalid combined reserve deployment inputs")
    if not enemies:
        return 0
    if any(enemy.route_cost < 0 for enemy in enemies):
        raise ValueError("An incoming route cannot have a negative cost")
    if len(enemies) == 1:
        enemy = enemies[0]
        return minimum_mobile_army(
            enemy.wave,
            at_turn,
            general_army,
            enemy.other_attack_surplus,
            enemy.route_cost,
            deployment_turns,
            cycle_turns,
        )
    incoming = sum(
        max(
            0,
            enemy.wave.launch_army
            + max(0, enemy.other_attack_surplus)
            - enemy.route_cost,
        )
        for enemy in enemies
    )
    return max(
        sum(enemy.wave.launch_army for enemy in enemies),
        incoming - max(0, general_army) + deployment_turns + 1,
    )
