"""Material accounting for economic FFA kills, separate from expansion utility."""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass

import logbook

from DistanceMapperImpl import DistanceMapperImpl
from Models import GatherTreeNode
from Models.Move import Move
from base.client.map import MapBase
from base.client.tile import Tile


@dataclass(slots=True, frozen=True)
class FfaKillValue:
    """Recurring capture income and the separate, one-off queued-army transfer."""

    tiles: int
    city_income: int
    queued_army: int

    @property
    def total(self) -> int:
        """Return the utility requested for comparison with flow expansion."""
        return self.tiles + self.city_income + self.queued_army


@dataclass(slots=True, frozen=True)
class FfaKillProjection:
    """A conservative material certificate for a concrete gather and hunt."""

    gather_turns: int
    route_turns: int
    launch_army: int
    route_cost: int
    enemy_standing: int
    enemy_city_growth: int
    enemy_tile_growth: int
    defender_army: int
    margin: int
    rounds: float
    certified: bool
    enemy_free_pool: int
    enemy_ordinary_gather: int


@dataclass(slots=True, frozen=True)
class FfaGatherPosition:
    """Projected material and ownership, without mutating the live map."""

    turn: int
    armies: tuple[int, ...]
    owners: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class FfaGatherForecast:
    """Concrete delivery and enemy army already paid for while gathering."""

    launch_army: int
    paid_enemy_standing: int
    paid_ordinary_armies: tuple[int, ...]
    captured_tile_indexes: tuple[int, ...]
    position: FfaGatherPosition
    launch_tile_index: int


@dataclass(slots=True, frozen=True)
class FfaSafeFrontForecast:
    """A surviving forward head and its correlated enemy standing reserve."""

    safety: FfaKillProjection
    position: FfaGatherPosition
    enemy_standing: int
    head_tile_index: int


@dataclass(slots=True, frozen=True)
class FfaKillScenario:
    """One general hypothesis and its complete reveal-then-finish route."""

    hypothesis_index: int
    route_tile_indexes: tuple[int, ...]


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# general/city armies are annihilated, not transfer rewards. Callers supply ONLY
# OpponentTracker's ordinary fog-tile queue, never a fog-defense or city pool.
def calculate_kill_value(
    tile_count: int,
    city_count: int,
    queued_tile_armies: list[int],
    cycle_turns: int = 50,
) -> FfaKillValue:
    """Value a capture; each queued tile retains its own leave-one deduction."""
    return FfaKillValue(
        tiles=tile_count,
        city_income=city_count * (cycle_turns // 2),
        queued_army=sum(army // 2 - 1 for army in queued_tile_armies))


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# unlike a utility-valued gather, this simulates the actual friendly-only move
# order, including cities that should move late. No hypothetical expansion or
# growth on a city after its army has already left is credited to the head.
def project_gather_launch_army(
    game_map: MapBase,
    moves: list[Move],
    launch_tile: Tile,
    player_index: int,
    cycle_turns: int = 50,
) -> int | None:
    """Replay an owned-tile gather without mutating the map; reject invalid plans.

    Uses ordinary game's move-then-growth order. Callers must exclude unusual
    growth modifiers, deserts and swamps before using this projection.
    """
    owned = {
        tile.tile_index
        for tile in game_map.players[player_index].tiles
        if tile.player == player_index}
    if launch_tile.tile_index not in owned:
        return None
    armies = [tile.army for tile in game_map.tiles_by_index]
    cities = [
        index for index in owned
        if game_map.tiles_by_index[index].isCity
        or game_map.tiles_by_index[index].isGeneral]
    for offset, move in enumerate(moves, start=1):
        source = move.source.tile_index
        dest = move.dest.tile_index
        if source not in owned or dest not in owned:
            return None
        if move.dest not in move.source.movable or armies[source] <= 1:
            return None
        sent = armies[source] // 2 if move.move_half else armies[source] - 1
        armies[source] -= sent
        armies[dest] += sent
        update_turn = game_map.turn + offset
        if update_turn % 2 == 0:
            for index in cities:
                armies[index] += 1
        if update_turn % cycle_turns == 0:
            for index in owned:
                armies[index] += 1
    return armies[launch_tile.tile_index]


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# forward gathers may need to connect through a neutral or a weak target tile;
# forbid economic detours, not the connective moves that deliver a kill stack.
def project_forward_gather(
    game_map: MapBase,
    moves: list[Move],
    launch_tile: Tile,
    player_index: int,
    enemy_index: int,
    cycle_turns: int = 50,
) -> FfaGatherForecast | None:
    """Replay a concrete gather with normal growth and no third-party captures.

    Known target armies paid on the way must not also defend the general. If
    they instead withdrew during defensive gathering, our actual head saves the
    same army they moved to defense, preserving the material margin. Future
    growth paid on the way is not credited against initial standing army.
    This accounting assumes defensive play, not hostile interceptions of
    independent gather branches; callers must reserve threatening source tiles.
    """
    armies = [max(0, tile.army) for tile in game_map.tiles_by_index]
    owners = [tile.player for tile in game_map.tiles_by_index]
    paid: set[int] = set()
    captured: set[int] = set()
    paid_standing = 0
    paid_ordinary: list[int] = []
    for offset, move in enumerate(moves, start=1):
        source = move.source.tile_index
        dest = move.dest.tile_index
        if owners[source] != player_index or armies[source] <= 1:
            return None
        if move.dest not in move.source.movable or move.dest.isNotPathable:
            return None
        if owners[dest] >= 0 and owners[dest] not in (player_index, enemy_index):
            return None
        sent = armies[source] // 2 if move.move_half else armies[source] - 1
        armies[source] -= sent
        if owners[dest] == player_index:
            armies[dest] += sent
        else:
            if sent <= armies[dest]:
                return None
            armies[dest] = sent - armies[dest]
            if owners[dest] == enemy_index and dest not in paid:
                initial = game_map.tiles_by_index[dest]
                paid_standing += max(0, initial.army - 1)
                if not initial.isCity and not initial.isGeneral:
                    paid_ordinary.append(initial.army)
                paid.add(dest)
            owners[dest] = player_index
            captured.add(dest)
        update_turn = game_map.turn + offset
        for index, tile in enumerate(game_map.tiles_by_index):
            if owners[index] < 0:
                continue
            if update_turn % 2 == 0 and (tile.isCity or tile.isGeneral):
                armies[index] += 1
            if update_turn % cycle_turns == 0:
                armies[index] += 1
    if owners[launch_tile.tile_index] != player_index:
        return None
    return FfaGatherForecast(
        launch_army=armies[launch_tile.tile_index],
        paid_enemy_standing=paid_standing,
        paid_ordinary_armies=tuple(paid_ordinary),
        captured_tile_indexes=tuple(sorted(captured)),
        position=FfaGatherPosition(
            turn=game_map.turn + len(moves),
            armies=tuple(armies),
            owners=tuple(owners)),
        launch_tile_index=launch_tile.tile_index)


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# require every hypothesis to finish within two cycles, not necessarily the
# first wave. A strictly surviving forward head can receive a certified second
# gather; it must never be fed into a general that the first wave cannot beat.
def project_safe_front(
    game_map: MapBase,
    gather: FfaGatherForecast,
    route: list[Tile],
    player_index: int,
    enemy_index: int,
    enemy_standing: int,
    enemy_tile_count: int,
    enemy_city_count: int,
    cycle_turns: int = 50,
) -> FfaSafeFrontForecast | None:
    """Certify and project a known-field prefix against ALL enemy standing army.

    Enemy ordinary surplus is modeled as withdrawn into its global reserve.
    If E of that surplus instead defends the prefix, both the surviving head
    and the remaining enemy reserve decrease by E. A subsequent gather rooted
    ON THIS HEAD therefore has the same material margin for every E. The
    all-standing safety bound guarantees the head survives even the worst E.

    Callers must keep this root stationary throughout the second gather, price
    its full literal schedule and finishing routes, and honor the original
    two-cycle deadline. This does not itself certify the second gather.
    Prefixes may not cross unknown terrain, third parties, or enemy cities.
    """
    if not route or gather.position.turn < game_map.turn:
        logbook.info(
            f"FFA SAFE-FRONT-REJECT reason=empty_or_past route={len(route)} "
            f"gatherTurn={gather.position.turn} mapTurn={game_map.turn}")
        return None
    armies = list(gather.position.armies)
    owners = list(gather.position.owners)
    start = route[0].tile_index
    if (
            start != gather.launch_tile_index or owners[start] != player_index
            or armies[start] != gather.launch_army):
        logbook.info(
            f"FFA SAFE-FRONT-REJECT reason=start_mismatch start={start} "
            f"launch={gather.launch_tile_index} owner={owners[start]} "
            f"army={armies[start]} launchArmy={gather.launch_army}")
        return None
    for source, dest in zip(route, route[1:]):
        if dest not in source.movable or dest.isNotPathable:
            logbook.info(
                f"FFA SAFE-FRONT-REJECT reason=not_movable "
                f"src={source.tile_index} dest={dest.tile_index}")
            return None
        owner = owners[dest.tile_index]
        if owner not in (-1, player_index, enemy_index):
            logbook.info(
                f"FFA SAFE-FRONT-REJECT reason=third_party dest={dest.tile_index} "
                f"owner={owner}")
            return None
        if owner != player_index and (
                not dest.discovered or dest.isCity or dest.isGeneral):
            logbook.info(
                f"FFA SAFE-FRONT-REJECT reason=uncertain_tile "
                f"dest={dest.tile_index} disc={dest.discovered} "
                f"city={dest.isCity} gen={dest.isGeneral}")
            return None
    cost = calculate_route_cost(
        game_map, route, player_index, enemy_index,
        gather_captured_tiles=gather.captured_tile_indexes)
    if cost is None:
        logbook.info(
            f"FFA SAFE-FRONT-REJECT reason=route_cost route={[t.tile_index for t in route]}")
        return None
    # Only army that can physically reach the prefix during the gather+walk may
    # intercept the head; provably-unreachable visible stacks are priced out
    # while all unseen standing remains fully charged.
    bounded = bounded_defensive_pool(
        game_map, enemy_index, route,
        gather.position.turn - game_map.turn + len(route) - 1,
        enemy_standing)
    adjusted_standing = max(0, bounded - gather.paid_enemy_standing)
    safety = certify_kill(
        start_turn=game_map.turn,
        gather_turns=gather.position.turn - game_map.turn,
        route_turns=len(route) - 1,
        launch_army=gather.launch_army,
        route_cost=cost,
        enemy_standing=adjusted_standing,
        enemy_tile_count=enemy_tile_count,
        enemy_city_count=enemy_city_count,
        cycle_turns=cycle_turns)
    if not safety.certified:
        logbook.info(
            f"FFA SAFE-FRONT-REJECT reason=safety_uncertified "
            f"launch={gather.launch_army} cost={cost} "
            f"adjStanding={adjusted_standing} defender={safety.defender_army} "
            f"margin={safety.margin} duration={safety.gather_turns}+{safety.route_turns} "
            f"cityGrowth={safety.enemy_city_growth} tileGrowth={safety.enemy_tile_growth}")
        return None
    for offset, (source_tile, dest_tile) in enumerate(zip(route, route[1:]), start=1):
        source = source_tile.tile_index
        dest = dest_tile.tile_index
        if owners[source] != player_index or armies[source] <= 1:
            logbook.info(
                f"FFA SAFE-FRONT-REJECT reason=walk_source src={source} "
                f"owner={owners[source]} army={armies[source]} step={offset}")
            return None
        sent = armies[source] - 1
        armies[source] = 1
        if owners[dest] == player_index:
            armies[dest] += sent
        else:
            # All target surplus stays in the enemy reserve. Neutral defenders
            # have no such reserve and must be paid in full.
            defender = 1 if owners[dest] == enemy_index else armies[dest]
            if sent <= defender:
                logbook.info(
                    f"FFA SAFE-FRONT-REJECT reason=walk_outmatched src={source} "
                    f"dest={dest} sent={sent} defender={defender} step={offset}")
                return None
            armies[dest] = sent - defender
            owners[dest] = player_index
        update_turn = gather.position.turn + offset
        for index, tile in enumerate(game_map.tiles_by_index):
            if owners[index] < 0:
                continue
            if update_turn % 2 == 0 and (tile.isCity or tile.isGeneral):
                armies[index] += 1
            if update_turn % cycle_turns == 0:
                armies[index] += 1
    return FfaSafeFrontForecast(
        safety=safety,
        position=FfaGatherPosition(
            turn=gather.position.turn + len(route) - 1,
            armies=tuple(armies),
            owners=tuple(owners)),
        enemy_standing=(
            adjusted_standing + safety.enemy_city_growth + safety.enemy_tile_growth),
        head_tile_index=route[-1].tile_index)


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# second-gather construction needs the projected owned corridor and the actual
# remaining home armies, not a fresh copy of the original standing army.
def materialize_gather_position(
    game_map: MapBase,
    position: FfaGatherPosition,
    player_index: int,
) -> MapBase:
    """Make an isolated planning map for an already certified material position.

    Enemy scoreboard counts remain conservative source data: fogged ownership
    is not fully represented by Tile objects. The caller supplies the separately
    certified enemy standing bound, never derives it from these partial lists.
    """
    if len(position.armies) != len(game_map.tiles_by_index) or len(position.owners) != len(position.armies):
        raise ValueError("FFA projected position size does not match its map")
    result = pickle.loads(pickle.dumps(game_map, protocol=pickle.HIGHEST_PROTOCOL))
    for tile, army, owner in zip(result.tiles_by_index, position.armies, position.owners):
        tile.army = army
        tile.player = owner
    result.turn = position.turn
    for player in result.players:
        player.tiles = [tile for tile in player.tiles if tile.player == player.index]
    own = result.players[player_index]
    own.tiles = [tile for tile in result.tiles_by_index if tile.player == player_index]
    own.cities = [tile for tile in own.tiles if tile.isCity or tile.isGeneral]
    own.tileCount = len(own.tiles)
    own.cityCount = len(own.cities)
    own.score = sum(tile.army for tile in own.tiles)
    own.standingArmy = own.score - own.tileCount
    result.scores[player_index].tiles = own.tileCount
    result.scores[player_index].total = own.score
    # MapBase.__getstate__ omits this cache; every planning clone needs its own.
    result.distance_mapper = DistanceMapperImpl(result)
    return result


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# only remove queue sources actually paid in the concrete forward gather.
def remaining_ordinary_sources(
    ordinary_armies: list[int],
    paid_armies: tuple[int, ...],
) -> list[int]:
    """Return an independent source list without mutating OpponentTracker."""
    remaining = ordinary_armies.copy()
    for army in paid_armies:
        if army in remaining:
            remaining.remove(army)
    return remaining


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# first-wave feasibility and a retained-head continuation must price the same
# literal routes, paid gather armies, normal growth, and absolute deadline.
def certify_gather_scenarios(
    game_map: MapBase,
    gather: FfaGatherForecast,
    scenarios: list[FfaKillScenario],
    player_index: int,
    enemy_index: int,
    enemy_standing: int,
    enemy_tile_count: int,
    enemy_city_count: int,
    absolute_deadline_turn: int,
    enemy_ordinary_armies: list[int] | None = None,
    cycle_turns: int = 50,
) -> tuple[FfaKillProjection, ...] | None:
    """Price every supplied hypothesis; never certify an empty/partial set.

    Negative margins are returned for diagnostics and conditional planning.
    Invalid geometry or a route missing the absolute deadline rejects the
    whole batch. The caller must require certified=True for every case on any
    unconditional kill path.
    """
    if not scenarios or gather.position.turn < game_map.turn:
        return None
    gather_turns = gather.position.turn - game_map.turn
    sources = (
        remaining_ordinary_sources(enemy_ordinary_armies, gather.paid_ordinary_armies)
        if enemy_ordinary_armies is not None else None)
    projections: list[FfaKillProjection] = []
    for scenario in scenarios:
        indexes = scenario.route_tile_indexes
        if (
                not indexes or indexes[0] != gather.launch_tile_index
                or indexes[-1] != scenario.hypothesis_index):
            return None
        if gather.position.turn + len(indexes) - 1 > absolute_deadline_turn:
            return None
        route = [game_map.tiles_by_index[i] for i in indexes]
        hypothesis = game_map.tiles_by_index[scenario.hypothesis_index]
        cost = calculate_route_cost(
            game_map, route, player_index, enemy_index,
            hypothesized_general=hypothesis,
            gather_captured_tiles=gather.captured_tile_indexes)
        if cost is None:
            return None
        # Only army able to physically reach the general before the attack
        # lands may defend it; provably-unreachable visible stacks are priced
        # out while all unseen standing remains fully charged.
        bounded = bounded_defensive_pool(
            game_map, enemy_index, [hypothesis],
            gather_turns + len(indexes) - 1, enemy_standing)
        adjusted = max(0, bounded - gather.paid_enemy_standing)
        projections.append(certify_kill(
            start_turn=game_map.turn,
            gather_turns=gather_turns,
            route_turns=len(indexes) - 1,
            launch_army=gather.launch_army,
            route_cost=cost,
            enemy_standing=adjusted,
            enemy_tile_count=enemy_tile_count,
            enemy_city_count=enemy_city_count,
            cycle_turns=cycle_turns,
            enemy_ordinary_armies=sources))
    return tuple(projections)


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# a cheap first reveal is permitted only with a fully certified second gather
# for every remaining hypothesis; all enemy standing is immediately available.
def certify_retained_head_continuation(
    projected_map: MapBase,
    front: FfaSafeFrontForecast,
    gather_moves: list[Move],
    scenarios: list[FfaKillScenario],
    player_index: int,
    enemy_index: int,
    enemy_tile_count: int,
    enemy_city_count: int,
    absolute_deadline_turn: int,
    cycle_turns: int = 50,
) -> tuple[FfaKillProjection, ...] | None:
    """Certify an owned-only regather rooted on the stationary surviving head.

    projected_map must materialize front.position. Enemy surplus spent on the
    initial prefix reduces this head and the enemy reserve equally; keeping the
    root stationary preserves that correlation across the entire second gather.
    No instant-gather or ordinary-source discount is applied to future defense.
    """
    if (
            projected_map.turn != front.position.turn
            or tuple(t.army for t in projected_map.tiles_by_index) != front.position.armies
            or tuple(t.player for t in projected_map.tiles_by_index) != front.position.owners):
        raise ValueError("FFA continuation map does not materialize its safe-front position")
    if not front.safety.certified:
        return None
    head = projected_map.tiles_by_index[front.head_tile_index]
    for move in gather_moves:
        if move.source.tile_index == front.head_tile_index:
            return None
        if (
                projected_map.tiles_by_index[move.source.tile_index].player != player_index
                or projected_map.tiles_by_index[move.dest.tile_index].player != player_index):
            return None
    forecast = project_forward_gather(
        projected_map, gather_moves, head, player_index, enemy_index, cycle_turns)
    if forecast is None:
        return None
    return certify_gather_scenarios(
        projected_map, forecast, scenarios, player_index, enemy_index,
        front.enemy_standing, enemy_tile_count, enemy_city_count,
        absolute_deadline_turn, cycle_turns=cycle_turns)


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# a static tree's normal move order may donate a city early and strand its next
# ten ticks of production. Schedule cities late, then certify the literal order.
def city_late_gather_schedules(
    root_nodes: list[GatherTreeNode],
    player_index: int,
) -> list[list[Move]]:
    """Build two legal child-before-parent orders, favoring late city donations.

    Reverse scheduling makes parent edges available before child edges. Walk to
    each city before unrelated branches, placing its move as late as precedence
    permits. Try both near-first and far-first city orders; callers replay the
    results and select by actual delivered army, never by speculative prizes.
    This does not claim global schedule optimality for arbitrary many cities.
    """
    nodes: dict[Tile, GatherTreeNode] = {}
    parents: dict[Tile, Tile] = {}
    depths: dict[Tile, int] = {}
    pending = [(root, 0) for root in root_nodes]
    roots = {node.tile for node in root_nodes}
    while pending:
        node, depth = pending.pop()
        nodes[node.tile] = node
        depths[node.tile] = depth
        for child in node.children:
            parents[child.tile] = node.tile
            pending.append((child, depth + 1))
    cities = sorted(
        (
            tile for tile in nodes
            if tile not in roots and tile.player == player_index
            and (tile.isCity or tile.isGeneral)
        ),
        key=lambda tile: (depths[tile], tile.tile_index))
    schedules: list[list[Move]] = []
    for city_order in (cities, list(reversed(cities))):
        visited = set(roots)
        reverse_edges: list[Tile] = []
        for city in city_order:
            path: list[Tile] = []
            current = city
            while current not in visited:
                path.append(current)
                current = parents[current]
            for tile in reversed(path):
                reverse_edges.append(tile)
                visited.add(tile)
        remaining = sorted(
            (tile for tile in nodes if tile not in visited),
            key=lambda tile: (depths[tile], tile.tile_index))
        reverse_edges.extend(remaining)
        schedules.append([
            Move(tile, parents[tile], nodes[tile].half)
            for tile in reversed(reverse_edges)])
    return schedules


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# reserve ALL enemy movable army, with free instantaneous defensive gathering,
# plus every future generation tick. Econ advantage alone never certifies a kill.
def certify_kill(
    start_turn: int,
    gather_turns: int,
    route_turns: int,
    launch_army: int,
    route_cost: int,
    enemy_standing: int,
    enemy_tile_count: int,
    enemy_city_count: int,
    cycle_turns: int = 50,
    enemy_ordinary_armies: list[int] | None = None,
) -> FfaKillProjection:
    """Certify a strictly winning attack within two cycles under defensive play.

    Standing army excludes one per owned tile. The defender gets its general's
    one back here; route_cost additionally charges movement and non-general
    garrisons. If ordinary source tiles are supplied, each needs at least one
    move to gather: give defense the best sources first with zero travel cost.
    All unlocated/current city army and all future growth are freely available
    to defense, including the final update's growth (a conservative extra tick).
    Ordinary sources must exclude cities/generals and must not duplicate fog
    queue entries with visible tiles. This is a certificate against the supplied
    tracker model, not a claim that uncertain fog predictions are ground truth.
    """
    duration = gather_turns + route_turns
    end_turn = start_turn + duration
    city_growth = enemy_city_count * (end_turn // 2 - start_turn // 2)
    tile_growth = enemy_tile_count * (
        end_turn // cycle_turns - start_turn // cycle_turns)
    standing = max(0, enemy_standing)
    free_pool = standing
    ordinary_gather = 0
    if enemy_ordinary_armies is not None:
        ordinary = sorted((max(0, army - 1) for army in enemy_ordinary_armies), reverse=True)
        # An unseen general/city must not accidentally become a cheap ordinary
        # source. Keep at most the scoreboard's non-city source count.
        ordinary = ordinary[:max(0, enemy_tile_count - enemy_city_count)]
        known_ordinary = min(standing, sum(ordinary))
        free_pool = standing - known_ordinary
        ordinary_gather = min(known_ordinary, sum(ordinary[:duration]))
    defender = free_pool + ordinary_gather + 1 + city_growth + tile_growth
    margin = launch_army - route_cost - defender
    return FfaKillProjection(
        gather_turns=gather_turns,
        route_turns=route_turns,
        launch_army=launch_army,
        route_cost=route_cost,
        enemy_standing=enemy_standing,
        enemy_city_growth=city_growth,
        enemy_tile_growth=tile_growth,
        defender_army=defender,
        margin=margin,
        rounds=duration / cycle_turns,
        certified=0 < duration <= 2 * cycle_turns and margin > 0,
        enemy_free_pool=free_pool,
        enemy_ordinary_gather=ordinary_gather)


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible_vs_defender20
# (and _vs_defender34): the certificate's worst case prices EVERY unseen army as
# able to reinforce the target, which is deliberately conservative but can be
# wrong by a real fraction of the attacking force. The committed-plan abort
# therefore leaves a buffer of this fraction of the launch army against the fog
# assumption before it treats a negative margin as a failed certificate.
CERT_FOG_MARGIN_FRACTION = 0.10


def fog_margin_buffer(launch_army: int) -> int:
    """Negative-margin tolerance: 10% of the attacking force (minimum 1)."""
    return max(1, math.ceil(launch_army * CERT_FOG_MARGIN_FRACTION))


def fog_buffered_certified(projection: FfaKillProjection) -> bool:
    """Certified, or inside the abort's fog-error buffer.

    Strict `projection.certified` (margin > 0) still governs plan SELECTION;
    this looser gate is only for abort decisions on an already-committed plan,
    where a small negative margin must not release the attack. The duration
    bound is not a fog assumption, so it is never buffered.
    """
    if projection.certified:
        return True
    return (0 < projection.rounds <= 2
            and projection.margin >= -fog_margin_buffer(projection.launch_army))


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible_vs_defender34:
# the all-standing bound counts a 50-army stack two tiles from the revealed
# general as if it could reinforce a one-turn attack - physically impossible.
def bounded_defensive_pool(
    game_map: MapBase,
    enemy_index: int,
    target_tiles: list[Tile],
    turns: int,
    enemy_standing: int,
) -> int:
    """Standing army able to reach ANY defense target within `turns` moves.

    Manhattan distance is a hard lower bound on every orthogonal grid path, so
    a CURRENTLY-VISIBLE enemy stack farther than `turns` from every target tile
    provably cannot reinforce/intercept before the attack lands; its surplus is
    excluded from the defense pool. All unseen standing stays fully counted:
    fog may hide a stack adjacent to the target. This is strictly tighter than
    the all-standing bound and still conservative in the same direction. The
    caller supplies the standing total because projected maps may carry a
    separately certified reserve instead of the live scoreboard value.
    """
    enemy = game_map.players[enemy_index]
    visible_surplus = 0
    reachable = 0
    for tile in enemy.tiles:
        surplus = tile.army - 1
        if surplus <= 0 or not tile.visible:
            continue
        visible_surplus += surplus
        for target in target_tiles:
            if abs(tile.x - target.x) + abs(tile.y - target.y) <= turns:
                reachable += surplus
                break
    unseen = max(0, enemy_standing - visible_surplus)
    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_
    # possible_vs_defender{20,34}: unseen standing can only reinforce the attack
    # zone if it could physically be hiding inside it. When every tile within
    # `turns` of a target is visible to us, no enemy army can exist there, so
    # unseen standing provably sits farther out than the attack window and
    # contributes nothing. A fogged general hypothesis is itself non-visible,
    # so unseen always counts in full for search scenarios - this only relaxes
    # the pool when the attack target area is fully observed.
    unseen_reachable = False
    if unseen > 0:
        for tile in game_map.tiles_by_index:
            if tile.visible or tile.isMountain:
                continue
            for target in target_tiles:
                if abs(tile.x - target.x) + abs(tile.y - target.y) <= turns:
                    unseen_reachable = True
                    break
            if unseen_reachable:
                break
    bound = (unseen if unseen_reachable else 0) + reachable
    # Diagnostic for Tests/test_FFA.py defender20/defender34 continuations: only
    # log when the bound changes the answer or the attack is imminent (turns<=3),
    # otherwise this fires hundreds of times per turn during gather scenarios.
    if bound < enemy_standing or turns <= 3:
        logbook.info(
            f"FFA BOUNDED-POOL enemy=p{enemy_index} standing={enemy_standing} "
            f"visSurplus={visible_surplus} reachable={reachable} unseen={unseen} "
            f"unseenReachable={unseen_reachable} bound={bound} "
            f"targets={[t.tile_index for t in target_tiles]} turns={turns}")
    return bound


# Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
# route tolls reserve baseline garrisons, not a second copy of standing army.
def calculate_route_cost(
    game_map: MapBase,
    route: list[Tile],
    player_index: int,
    enemy_index: int,
    hypothesized_general: Tile | None = None,
    gather_captured_tiles: tuple[int, ...] = (),
) -> int | None:
    """Reserve route tolls without counting enemy standing army twice.

    Every step leaves one. First entry into an enemy tile also pays its baseline
    one; all army above that is already reserved by certify_kill. Known neutral
    defenders cost their full army; unknown land reserves at least one garrison.
    Friendly pickup and future growth on captured route tiles are ignored.
    A route through another player or an uncertain city cannot certify a kill.
    The last tile may be a fog general hypothesis: in that particular scenario
    it necessarily belongs to the victim, not its stale predicted fog owner.
    This exception never licenses execution onto a revealed third-party tile.
    """
    if not route:
        return None
    captured = set(gather_captured_tiles)
    cost = 0
    for source, dest in zip(route, route[1:]):
        is_hypothesis = (
            dest == hypothesized_general
            and dest == route[-1]
            and not dest.visible)
        if dest not in source.movable or dest.isNotPathable:
            return None
        if dest.player >= 0 and dest.player not in (player_index, enemy_index) and not is_hypothesis:
            return None
        if dest.isCity and not dest.discovered and not is_hypothesis:
            return None
        cost += 1
        if dest.tile_index in captured or dest.player == player_index:
            continue
        captured.add(dest.tile_index)
        if dest.player == enemy_index or is_hypothesis:
            # The final general's baseline one is already in defender_army.
            if dest != hypothesized_general or dest != route[-1]:
                cost += 1
        else:
            cost += max(0 if dest.discovered else 1, dest.army)
    return cost
