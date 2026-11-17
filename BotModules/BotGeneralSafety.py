"""General-reveal defense reservation against anticipated enemy all-ins.

When an enemy visibly discovers our general (Player.king_location_revealed_turn)
and then goes quiet, it may be staging a hidden all-in. This module freezes a
typed episode per qualifying enemy, forecasts fast (immediate bank) and slow
(growing gather) outgoing waves with Strategy.AnticipatedAllIn, reserves a
stable owned anchor next to our general, and executes a literal owned-only
gather schedule that certifies - via Strategy.FfaKillGatherMath - delivery of
enough mobile army before each wave's deployment deadline.

Correctness of the material/timing envelopes lives in
Strategy/AnticipatedAllIn.py; gather construction reuses BotFfaKillGather's
owned-tree helpers through the public build_owned_gather_schedule wrapper.
The feature flag stays FALSE in the live tree; tests patch it True only
inside the test process. Flag-off is a zero-cost no-op everywhere.
"""

from __future__ import annotations

import typing
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import logbook

from BotModules.BotFfaKillGather import build_owned_gather_schedule
from Models.Move import Move
from Strategy.AnticipatedAllIn import (
    EnemyAllInDefense,
    EnemyAllInWave,
    forecast_enemy_all_in,
    minimum_combined_mobile_army,
)
from Strategy.FfaKillGatherMath import project_forward_gather
from base.client.map import MapBase
from base.client.tile import Tile

if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot

# Feature flag. Kept FALSE in the live tree; tests patch it True only inside
# the helper that runs the t179 general-safety acceptance cases.
GENERAL_SAFETY_ENABLED: bool = False

# One-round response window: a NEW episode only triggers while the reveal is
# this fresh (the 1v1 exception uses the same conservative bound). Live
# episodes may persist past it for the duration of their wave.
_REVEAL_WINDOW_TURNS: int = 50
# Slow-wave gather horizon floor; quiet episodes grow it via max(25, elapsed).
_SLOW_GATHER_FLOOR: int = 25
# Owned-gather budget cap (mirrors the FFA kill-gather search bound).
_MAX_GATHER_BUDGET: int = 25
_MAX_GENERAL_HYPOTHESES: int = 64


class GeneralSafetyPhase(Enum):
    """Reservation lifecycle for the shared literal gather schedule."""

    IDLE = 0
    WATCH = 1
    GATHER_FAST = 2
    GATHER_SLOW = 3
    READY = 4


@dataclass(slots=True, frozen=True)
class _FrozenEpisodeInputs:
    """Tracker-derived forecast inputs captured once at episode creation."""

    bank_army: int
    standing_cap: int
    ordinary_armies: tuple[int, ...]
    ordinary_tile_count: int
    visible_ordinary_count: int
    excluded_visible_ordinary_surplus: int
    city_count: int
    route_cost: int


@dataclass(slots=True)
class GeneralSafetyEpisode:
    """One enemy's frozen reveal/forecast inputs plus its live wave pair.

    All tracker inputs are captured once at creation so per-turn re-evaluation
    never re-reads drifting source queues or moves the absolute input clock;
    only the slow wave's gather horizon grows with observed quiet elapsed.
    """

    enemy_index: int
    reveal_turn: int
    quiet_start_turn: int
    created_turn: int
    initial_bank_army: int
    standing_cap: int
    ordinary_armies: tuple[int, ...]
    ordinary_tile_count: int
    visible_ordinary_count: int
    excluded_visible_ordinary_surplus: int
    city_count: int
    risk_route_tile_indexes: tuple[int, ...]
    attack_turns: int
    fast_warning_turns: int
    slow_warning_turns: int
    route_cost: int
    deployment_turns: int
    fast_wave: EnemyAllInWave
    slow_wave: EnemyAllInWave
    last_seen_move_turn: int
    last_move_signature: str
    cancelled: bool = False


@dataclass(slots=True)
class GeneralSafetyState:
    """Bot-owned reservation state persisted across turns/resume."""

    anchor_tile_index: int = -1
    episodes: dict[int, GeneralSafetyEpisode] = field(default_factory=dict)
    phase: GeneralSafetyPhase = GeneralSafetyPhase.IDLE
    gather_moves: list[Move] = field(default_factory=list)
    gather_cursor: int = 0
    schedule_phase: GeneralSafetyPhase = GeneralSafetyPhase.IDLE
    pending_offered_key: str = ""
    pending_offered_turn: int = -1
    required_army: int = 0
    stage_goal_army: int = 0
    stage_deadline_turn: int = -1
    last_update_turn: int = -1
    schedule_dirty: bool = False
    # Transient PREMOVE preimage recorded at consume time so save_state can
    # serialize the instruction aligned with the not-yet-applied board (same
    # contract as BotFfaKillGather.FfaKillGatherState).
    last_consumed_turn: int = -1
    pre_consume_gather_cursor: int = 0
    pre_consume_phase: GeneralSafetyPhase = GeneralSafetyPhase.IDLE


@dataclass(slots=True)
class GeneralSafetyMoveResult:
    """Typed result of get_move: handled flag plus optional move."""

    handled: bool
    move: Move | None
    reason: str


def _move_key(move: Move) -> str:
    """Stable key (source>dest:half) for reconciling offered vs executed moves."""
    return f"{move.source.tile_index}>{move.dest.tile_index}:{int(move.move_half)}"


def _living_team_count(bot: EklipZBot) -> int:
    """Distinct living team ids from the fresh scoreboard (scores, not tiles)."""
    living: set[int] = set()
    for score in bot._map.scores:
        if score.dead or score.tiles <= 0:
            continue
        living.add(bot._map.team_ids_by_player_index[score.player])
    return len(living)


def _living_player_count(bot: EklipZBot) -> int:
    """Distinct living player indices from the fresh scoreboard."""
    return sum(
        1 for score in bot._map.scores
        if not score.dead and score.tiles > 0)


def _score_alive(bot: EklipZBot, player_index: int) -> bool:
    score = bot._map.scores[player_index]
    return not score.dead and score.tiles > 0


def _econ_value(player) -> int:
    """Economic strength proxy: tiles + 25 per city (settled gate metric)."""
    return player.tileCount + 25 * player.cityCount


def _scope_kind(bot: EklipZBot) -> str:
    """Classify the game scope for general-safety episodes.

    'ffa' = more than two distinct living teams (an explicit team array does
    NOT disqualify a real >2-team FFA). 'duel' = exactly two living players in
    a non-2v2 game (genuine 1v1 only; 2-team multiplayer 2v2/2v1 never
    qualifies). '' = out of scope.
    """
    game_map = bot._map
    if game_map.is_2v2:
        return ""
    living_teams = _living_team_count(bot)
    if living_teams > 2:
        return "ffa"
    if living_teams == 2 and _living_player_count(bot) == 2:
        return "duel"
    return ""


def _enemy_qualifies(bot: EklipZBot, enemy_index: int, scope: str) -> tuple[bool, str]:
    """Per-enemy scope/economy/alive gates (reveal freshness is caller-side).

    Used both for NEW episode creation and for keeping LIVE episodes: a live
    episode may persist past the 1v1 reveal window for the duration of its
    wave, so the window is only enforced by the creation gate in update().
    """
    game_map = bot._map
    if enemy_index == bot.player.index or enemy_index in game_map.teammates:
        return False, "self_or_teammate"
    if not _score_alive(bot, enemy_index):
        return False, "enemy_dead"
    enemy = game_map.players[enemy_index]
    our_econ = _econ_value(bot.player)
    enemy_econ = _econ_value(enemy)
    if scope == "ffa":
        if our_econ <= enemy_econ:
            return False, "econ_not_leading"
    elif scope == "duel":
        if our_econ - enemy_econ < 25:
            return False, "econ_lead_under_25"
        if enemy.king_location_revealed_turn < 0:
            return False, "reveal_unset"
    else:
        return False, "out_of_scope"
    return True, ""


def _ordered_neighbors(tile: Tile, player_index: int) -> list[Tile]:
    """Stable own-first neighbor ordering for deterministic BFS tie-breaks."""
    neighbors = list(tile.movable)
    neighbors.sort(key=lambda t: (0 if t.player == player_index else 1, t.tile_index))
    return neighbors


def _general_hypotheses(bot: EklipZBot, enemy_index: int) -> list[Tile]:
    """Plausible enemy-general positions for the bounded route fallback."""
    game_map = bot._map
    enemy = game_map.players[enemy_index]
    gen = enemy.general
    if gen is not None and gen.isGeneral and gen.player == enemy_index:
        return [gen]
    hypotheses: list[Tile] = []
    seen: set[int] = set()

    def _add(tile: Tile | None) -> None:
        if tile is None or tile.tile_index in seen:
            return
        seen.add(tile.tile_index)
        hypotheses.append(tile)

    if enemy_index < len(bot.alt_en_gen_positions):
        for tile in bot.alt_en_gen_positions[enemy_index]:
            _add(tile)
    if (enemy_index < len(bot.armyTracker.valid_general_positions_by_player)):
        valid = bot.armyTracker.valid_general_positions_by_player[enemy_index]
        for tile in game_map.tiles_by_index:
            if valid.raw[tile.tile_index]:
                _add(tile)
            if len(hypotheses) >= _MAX_GENERAL_HYPOTHESES:
                break
    return hypotheses[:_MAX_GENERAL_HYPOTHESES]


def _route_cost_for(game_map: MapBase, player_index: int, route_tiles: list[Tile]) -> int:
    """Movement edges plus one toll per own baseline non-general tile on route.

    Every own non-general tile on the route costs the attacker one capture
    move, mobile reserve tiles included; the reserve's army value itself is
    never added here (the reserve math prices it separately).
    """
    edges = max(0, len(route_tiles) - 1)
    own_tiles = sum(
        1 for tile in route_tiles
        if tile.player == player_index and not tile.isGeneral)
    return edges + own_tiles


def _visible_warning_suffix(bot: EklipZBot, route_tiles: list[Tile]) -> int:
    """Consecutive visible tiles walking the route backward from our general."""
    count = 0
    for tile in reversed(route_tiles):
        if not tile.visible:
            break
        count += 1
    return min(count, max(0, len(route_tiles) - 1))


def _risk_route(bot: EklipZBot, enemy_index: int) -> list[Tile] | None:
    """Enemy->our-general approach route, or None when no direct route exists.

    Uses bot.enemy_attack_path only when it belongs to this enemy and ends at
    our general; otherwise a bounded deterministic BFS from our general over
    own/neutral/this-enemy land (third-party players excluded) to the nearest
    inferred general hypothesis, choosing the SHORTEST possible approach. Our
    own tiles are passable for the attacker (it must capture through them);
    each such tile on the final route is priced by route_cost, not here.
    """
    game_map = bot._map
    general = bot.general
    if general is None:
        return None
    if (enemy_index == bot.targetPlayer and bot.enemy_attack_path is not None
            and len(bot.enemy_attack_path.tileList) > 1):
        tiles = list(bot.enemy_attack_path.tileList)
        if tiles[-1].tile_index == general.tile_index:
            return tiles
    player_index = bot.player.index
    passable_owners = {-1, enemy_index, player_index}
    hypotheses = _general_hypotheses(bot, enemy_index)
    hyp_indexes = {t.tile_index for t in hypotheses}
    parents: dict[int, Tile | None] = {general.tile_index: None}
    depths: dict[int, int] = {general.tile_index: 0}
    queue: deque[Tile] = deque([general])
    best_hyp: Tile | None = None
    while queue:
        current = queue.popleft()
        depth = depths[current.tile_index]
        if current != general and current.tile_index in hyp_indexes:
            best_hyp = current
            break
        for neighbor in _ordered_neighbors(current, player_index):
            if neighbor.tile_index in parents or neighbor.isNotPathable:
                continue
            if neighbor.player not in passable_owners:
                continue
            parents[neighbor.tile_index] = current
            depths[neighbor.tile_index] = depth + 1
            queue.append(neighbor)
    if best_hyp is None:
        return None
    path = [best_hyp]
    cur = best_hyp
    while parents[cur.tile_index] is not None:
        cur = parents[cur.tile_index]
        path.append(cur)
    path.reverse()
    # path is general -> hypothesis; the risk route is hypothesis -> general.
    return list(reversed(path))


def _episode_inputs(bot: EklipZBot, enemy_index: int, route_tiles: list[Tile]) -> _FrozenEpisodeInputs:
    """Freeze the tracker-derived forecast inputs for one episode."""
    game_map = bot._map
    enemy = game_map.players[enemy_index]
    stats = bot.opponent_tracker.get_current_cycle_stats_by_player(enemy_index)
    fog_army = 0
    fog_city = 0
    if stats is not None:
        fog_army = max(0, stats.approximate_fog_army_available_total)
        fog_city = max(0, stats.approximate_fog_city_army)
    city_gen_surplus = 0
    visible_ordinary_armies: list[int] = []
    for tile in game_map.tiles_by_index:
        if tile.player != enemy_index or not tile.visible:
            continue
        if tile.isCity or tile.isGeneral:
            city_gen_surplus += max(0, tile.army - 1)
        else:
            visible_ordinary_armies.append(tile.army)
    visible_ordinary_surplus = sum(max(0, army - 1) for army in visible_ordinary_armies)
    bank_army = fog_army + fog_city + city_gen_surplus
    standing_cap = max(0, enemy.standingArmy - visible_ordinary_surplus)
    queue = bot.opponent_tracker.get_player_gather_queue(enemy_index)
    ordinary_armies = tuple(queue.as_tile_list(includeOnesAndZeros=True))
    ordinary_tile_count = max(
        0, enemy.tileCount - enemy.cityCount - len(visible_ordinary_armies))
    return _FrozenEpisodeInputs(
        bank_army=bank_army,
        standing_cap=standing_cap,
        ordinary_armies=ordinary_armies,
        ordinary_tile_count=ordinary_tile_count,
        visible_ordinary_count=len(visible_ordinary_armies),
        excluded_visible_ordinary_surplus=visible_ordinary_surplus,
        city_count=enemy.cityCount,
        route_cost=_route_cost_for(game_map, bot.player.index, route_tiles))


def _other_attack_surplus(episode: GeneralSafetyEpisode, wave: EnemyAllInWave) -> int:
    """Visible ordinary surplus excluded from the wave cap, plus its growth.

    The initial excluded surplus could still join the incoming wave; each
    visible ordinary tile also earns one army per crossed 50-turn cycle
    between the episode's quiet start and this wave's arrival.
    """
    cycles = wave.arrival_turn // 50 - episode.quiet_start_turn // 50
    return (
        episode.excluded_visible_ordinary_surplus
        + episode.visible_ordinary_count * max(0, cycles))


def _build_episode(
    bot: EklipZBot,
    enemy_index: int,
    route_tiles: list[Tile],
    deployment_turns: int,
) -> GeneralSafetyEpisode | None:
    """Create a frozen-input episode with fast/slow forecast waves."""
    game_map = bot._map
    enemy = game_map.players[enemy_index]
    reveal_turn = enemy.king_location_revealed_turn
    quiet_start = enemy.last_seen_move_turn if enemy.last_seen_move_turn > 0 else reveal_turn
    inputs = _episode_inputs(bot, enemy_index, route_tiles)
    attack_turns = max(1, len(route_tiles) - 1)
    visible_warning = _visible_warning_suffix(bot, route_tiles)
    fast_warning = min(7, visible_warning)
    slow_warning = min(5, visible_warning)
    elapsed = max(0, game_map.turn - quiet_start)
    slow_gather = max(_SLOW_GATHER_FLOOR, elapsed)
    fast_wave = forecast_enemy_all_in(
        quiet_start, 0, attack_turns, fast_warning,
        inputs.bank_army, inputs.standing_cap, inputs.ordinary_armies,
        inputs.ordinary_tile_count, inputs.city_count)
    slow_wave = forecast_enemy_all_in(
        quiet_start, slow_gather, attack_turns, slow_warning,
        inputs.bank_army, inputs.standing_cap, inputs.ordinary_armies,
        inputs.ordinary_tile_count, inputs.city_count)
    logbook.info(
        f"GENERAL SAFETY episode-inputs turn={game_map.turn} enemy=p{enemy_index} "
        f"quiet={quiet_start} elapsed={elapsed} slowGather={slow_gather} "
        f"attackTurns={attack_turns} fastWarn={fast_warning} slowWarn={slow_warning} "
        f"bank={inputs.bank_army} standing={inputs.standing_cap} "
        f"ordCount={inputs.visible_ordinary_count} ordTiles={inputs.ordinary_tile_count} "
        f"ordArmies={inputs.ordinary_armies} city={inputs.city_count} "
        f"routeCost={inputs.route_cost} "
        f"fLaunch={fast_wave.launch_army}@{fast_wave.arrival_turn} "
        f"sLaunch={slow_wave.launch_army}@{slow_wave.arrival_turn}")
    move_sig = _move_signature(enemy.last_move)
    return GeneralSafetyEpisode(
        enemy_index=enemy_index,
        reveal_turn=reveal_turn,
        quiet_start_turn=quiet_start,
        created_turn=game_map.turn,
        initial_bank_army=inputs.bank_army,
        standing_cap=inputs.standing_cap,
        ordinary_armies=inputs.ordinary_armies,
        ordinary_tile_count=inputs.ordinary_tile_count,
        visible_ordinary_count=inputs.visible_ordinary_count,
        excluded_visible_ordinary_surplus=inputs.excluded_visible_ordinary_surplus,
        city_count=inputs.city_count,
        risk_route_tile_indexes=tuple(t.tile_index for t in route_tiles),
        attack_turns=attack_turns,
        fast_warning_turns=fast_warning,
        slow_warning_turns=slow_warning,
        route_cost=inputs.route_cost,
        deployment_turns=deployment_turns,
        fast_wave=fast_wave,
        slow_wave=slow_wave,
        last_seen_move_turn=enemy.last_seen_move_turn,
        last_move_signature=move_sig)


def _refresh_slow_wave(bot: EklipZBot, episode: GeneralSafetyEpisode) -> None:
    """Regrow the slow wave's gather horizon with observed quiet elapsed.

    Frozen inputs are reused verbatim; only gather_turns (= max(25, elapsed))
    and the derived wave move. The peak (max launch_army) is retained so the
    requirement never shrinks while the enemy stays quiet.
    """
    game_map = bot._map
    elapsed = max(0, game_map.turn - episode.quiet_start_turn)
    slow_gather = max(_SLOW_GATHER_FLOOR, elapsed)
    if slow_gather == episode.slow_wave.gather_turns:
        return
    wave = forecast_enemy_all_in(
        episode.quiet_start_turn, slow_gather, episode.attack_turns,
        episode.slow_warning_turns, episode.initial_bank_army,
        episode.standing_cap, episode.ordinary_armies,
        episode.ordinary_tile_count, episode.city_count)
    if wave.launch_army >= episode.slow_wave.launch_army:
        episode.slow_wave = wave


def _move_signature(move_tuple) -> str:
    """Compact src>dst:half signature for a Player.last_move tuple."""
    if move_tuple is None or move_tuple[0] is None or move_tuple[1] is None:
        return ""
    return (
        f"{move_tuple[0].tile_index}>{move_tuple[1].tile_index}:"
        f"{int(bool(move_tuple[2]))}")


def _is_incoming_evidence(bot: EklipZBot, episode: GeneralSafetyEpisode, move_tuple) -> bool:
    """True when a visible enemy move is actual approach, not a cancel.

    Incoming evidence = the move captures our land (dest.delta.oldOwner is
    ours) OR its destination progresses toward our general along the stored
    risk route (enemy -> general ordered, larger index = closer). Evidence is
    logged as suspected/unobserved - never treated as certain intent.
    """
    if move_tuple is None or move_tuple[0] is None or move_tuple[1] is None:
        return False
    src, dest, _ = move_tuple
    if dest.delta is not None and dest.delta.oldOwner == bot.player.index:
        return True
    route_indexes = episode.risk_route_tile_indexes
    if not route_indexes:
        return False
    try:
        dest_pos = route_indexes.index(dest.tile_index)
    except ValueError:
        return False
    try:
        src_pos = route_indexes.index(src.tile_index)
    except ValueError:
        # Off-route source landing on the stored approach route is itself
        # approach evidence (joining the path toward our general).
        return True
    return dest_pos > src_pos


def _process_enemy_evidence(bot: EklipZBot, episode: GeneralSafetyEpisode) -> None:
    """Advance/cancel the quiet clock from the enemy's latest visible move."""
    enemy = bot._map.players[episode.enemy_index]
    if enemy.last_seen_move_turn == episode.last_seen_move_turn:
        return
    move_tuple = enemy.last_move
    sig = _move_signature(move_tuple)
    # The triggering reveal move on the reveal turn is not a cancellation.
    if (enemy.last_seen_move_turn == episode.reveal_turn
            and sig == episode.last_move_signature):
        episode.last_seen_move_turn = enemy.last_seen_move_turn
        episode.last_move_signature = sig
        return
    if _is_incoming_evidence(bot, episode, move_tuple):
        # Actual approach: preserve the episode and refresh the seen marker;
        # the wave forecast already prices the arrival, defense stays hot.
        episode.last_seen_move_turn = enemy.last_seen_move_turn
        episode.last_move_signature = sig
        logbook.info(
            f"GENERAL SAFETY incoming evidence p{episode.enemy_index} "
            f"turn={bot._map.turn} move={sig} (suspected approach, unobserved intent)")
        return
    # Other visible move (neutral expansion elsewhere, retreat, or an
    # unparseable move we cannot prove is approach): the enemy is not quietly
    # gathering - cancel this episode's quiet clock. A later quiet stretch may
    # form a fresh episode on a subsequent update within the reveal window.
    episode.cancelled = True
    logbook.info(
        f"GENERAL SAFETY cancel p{episode.enemy_index} turn={bot._map.turn} "
        f"visibleMove={sig or 'unknown'} lastSeen={enemy.last_seen_move_turn} "
        f"(suspected non-approach, not certain)")


def _owned_bfs_distance(bot: EklipZBot, source: Tile, target: Tile) -> int:
    """Owned-tile BFS distance source->target (deployment turns for anchor)."""
    player_index = bot.player.index
    if source.tile_index == target.tile_index:
        return 0
    seen = {source.tile_index}
    queue: deque[tuple[Tile, int]] = deque([(source, 0)])
    while queue:
        current, depth = queue.popleft()
        for neighbor in _ordered_neighbors(current, player_index):
            if neighbor.tile_index in seen or neighbor.isNotPathable:
                continue
            if neighbor.player != player_index:
                continue
            if neighbor.tile_index == target.tile_index:
                return depth + 1
            seen.add(neighbor.tile_index)
            queue.append((neighbor, depth + 1))
    return 1 << 20


def _owned_bfs_within(bot: EklipZBot, source: Tile, max_dist: int) -> list[Tile]:
    """Owned tiles within max_dist owned-BFS hops of source (incl. source)."""
    player_index = bot.player.index
    found: list[Tile] = []
    seen = {source.tile_index}
    queue: deque[tuple[Tile, int]] = deque([(source, 0)])
    while queue:
        current, depth = queue.popleft()
        found.append(current)
        if depth >= max_dist:
            continue
        for neighbor in _ordered_neighbors(current, player_index):
            if neighbor.tile_index in seen or neighbor.isNotPathable:
                continue
            if neighbor.player != player_index:
                continue
            seen.add(neighbor.tile_index)
            queue.append((neighbor, depth + 1))
    return found


def _owned_bfs_distances(bot: EklipZBot, source: Tile, max_dist: int) -> dict[int, int]:
    """Owned-BFS hop distance from source to each owned tile within max_dist."""
    player_index = bot.player.index
    distances: dict[int, int] = {source.tile_index: 0}
    queue: deque[tuple[Tile, int]] = deque([(source, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_dist:
            continue
        for neighbor in _ordered_neighbors(current, player_index):
            if neighbor.tile_index in distances or neighbor.isNotPathable:
                continue
            if neighbor.player != player_index:
                continue
            distances[neighbor.tile_index] = depth + 1
            queue.append((neighbor, depth + 1))
    return distances


def _select_anchor(bot: EklipZBot, state: GeneralSafetyState, episodes: list[GeneralSafetyEpisode]) -> Tile | None:
    """Pick the stable owned non-general anchor next to our general.

    Candidates are owned non-general tiles adjacent (movable) to the general;
    the current anchor is kept while valid (no pivoting on one-army
    fluctuations). Otherwise prefer the largest existing non-general home
    head, then the tile safest/rearmost relative to the first risk-route
    approach, then the lowest stable tile index. Falls back to owned
    non-general tiles within min(5, warning) when no adjacent exists. An
    enemy-captured tile can never satisfy the defense gather.
    """
    game_map = bot._map
    general = bot.general
    if general is None:
        return None
    player_index = bot.player.index
    # Tiles on any live episode's stored enemy approach route can never be the
    # anchor: massing the reserve on the path the wave must walk feeds the
    # attack before it ever reaches the general (the rear-side preference
    # below cannot outweigh an outright route tile). Tests:
    # Tests/test_FFA.py::FFATests.test_should_reserve_nearby_defense_after_enemy_finds_general
    route_blocked = {
        index
        for episode in episodes
        for index in episode.risk_route_tile_indexes}
    current = (
        game_map.tiles_by_index[state.anchor_tile_index]
        if 0 <= state.anchor_tile_index < len(game_map.tiles_by_index) else None)
    fallback_radius = min(5, max(1, max(
        (ep.fast_warning_turns for ep in episodes), default=5)))
    distances = _owned_bfs_distances(bot, general, fallback_radius)
    # Tests/test_FFA.py::FFATests.test_should_reserve_nearby_defense_after_enemy_finds_general
    # and ::test_should_reinforce_nearby_defense_for_delayed_all_in: anchor
    # distance is stage-aware. While the fast wave's staging deadline is still
    # open the reserve must arrive on the shortest owned path, so an adjacent
    # anchor is required for delivery. Once that deadline closes the delayed
    # wave's generous deadline affords a non-general tile several owned-BFS
    # hops out: urgent threat defense consolidates an adjacent reserve stack
    # back to the general the turn after each donation lands (the garrison
    # donation that builds the reserve also drops the general under the threat
    # value, which re-arms that defense), whereas a tile 3+ hops away survives
    # several pulls and donated stacks accumulate instead of being consolidated
    # away. The deadline is monotone in `now`, so this cannot oscillate.
    prefer_distant = (
        game_map.turn > _stage_deadline(episodes, GeneralSafetyPhase.GATHER_FAST))
    current_dist = (
        distances.get(current.tile_index, 1 << 20)
        if current is not None else 1 << 20)
    if (current is not None and current.player == player_index
            and not current.isGeneral and current.tile_index not in route_blocked
            and current_dist <= fallback_radius
            and (not prefer_distant or current_dist >= 2)):
        return current
    nearby = [
        tile for tile in _owned_bfs_within(bot, general, fallback_radius)
        if tile.player == player_index and not tile.isGeneral
        and tile.tile_index not in route_blocked
        and tile.tile_index != general.tile_index]
    approach = None
    for episode in episodes:
        route = [game_map.tiles_by_index[i] for i in episode.risk_route_tile_indexes]
        if len(route) >= 2:
            approach = (general.x - route[-2].x, general.y - route[-2].y)
            break

    def _rear(tile: Tile) -> int:
        if approach is None or approach == (0, 0):
            return 0
        ax, ay = approach
        return -((tile.x - general.x) * ax + (tile.y - general.y) * ay)

    if prefer_distant:
        non_adjacent = [
            tile for tile in nearby
            if distances.get(tile.tile_index, 1 << 20) >= 2]
        # Three hops buys enough consolidation runway to accumulate yet stays
        # inside the bounded radius for a usable relay; the closest qualifying
        # tile keeps delivery fast (t179_diag18: the farthest tile starved the
        # relay at ~23 army). Two hops still lets threat defense consolidate a
        # donated stack in a couple of pulls (t179_diag17: 78 -> 4 collapse).
        far_enough = [
            tile for tile in non_adjacent
            if distances[tile.tile_index] >= 3]
        pool = far_enough if far_enough else non_adjacent
        if pool:
            pool.sort(
                key=lambda t: (
                    distances[t.tile_index], _rear(t), -t.army, t.tile_index))
            logbook.info(
                f"GENERAL SAFETY anchor-candidates turn={game_map.turn} "
                f"general={general.x},{general.y} approach={approach} "
                f"preferDistant nonAdjacent={[(t.x, t.y, t.tile_index, t.army, distances[t.tile_index]) for t in pool[:8]]}")
            return pool[0]
        # No non-adjacent owned tile: fall through to the adjacent pool.
    candidates = [
        tile for tile in general.movable
        if tile.player == player_index and not tile.isGeneral
        and tile.tile_index not in route_blocked]
    if not candidates:
        # No adjacent owned non-general tile: nearest owned non-general within
        # the bounded radius, still never an enemy capture or route tile.
        candidates = [
            tile for tile in nearby
            if tile.tile_index != general.tile_index]
    if not candidates:
        return None
    logbook.info(
        f"GENERAL SAFETY anchor-candidates turn={game_map.turn} "
        f"general={general.x},{general.y} approach={approach} "
        f"cands={[(t.x, t.y, t.tile_index, t.army, t.player) for t in candidates]}")
    # Rear score is negative for tiles on the far side of the general from the
    # first route approach, so ascending order prefers the safe rear side.
    candidates.sort(key=lambda t: (-t.army, _rear(t), t.tile_index))
    return candidates[0]


def _stage_wave(episode: GeneralSafetyEpisode, phase: GeneralSafetyPhase) -> EnemyAllInWave:
    """The single phase alternative used for this enemy's current requirement.

    Fast and delayed alternatives for the SAME enemy are never summed - the
    stage picks exactly one. GATHER_SLOW/READY price the delayed peak.
    """
    if phase in (GeneralSafetyPhase.GATHER_SLOW, GeneralSafetyPhase.READY):
        return episode.slow_wave
    return episode.fast_wave


def _episode_defense(episode: GeneralSafetyEpisode, phase: GeneralSafetyPhase) -> EnemyAllInDefense:
    """One EnemyAllInDefense: the stage wave plus its excluded-surplus growth."""
    wave = _stage_wave(episode, phase)
    return EnemyAllInDefense(
        wave=wave,
        other_attack_surplus=_other_attack_surplus(episode, wave),
        route_cost=episode.route_cost)


def _combined_required_at(
    bot: EklipZBot,
    episodes: list[GeneralSafetyEpisode],
    phase: GeneralSafetyPhase,
    at_turn: int,
    general_army: int,
    deployment_turns: int,
) -> int:
    """minimum_combined_mobile_army over one phase wave per independent enemy.

    Multiple independent enemies SUM their net incoming requirements while the
    home general is credited exactly once (the authored math handles both the
    single-enemy time-aware case and the conservative multi-enemy bound).
    """
    defenses = tuple(
        _episode_defense(episode, phase)
        for episode in episodes if not episode.cancelled)
    if not defenses:
        return 0
    return minimum_combined_mobile_army(
        defenses, at_turn, general_army, deployment_turns)


def _update_required_and_stage(
    bot: EklipZBot,
    state: GeneralSafetyState,
    episodes: list[GeneralSafetyEpisode],
    anchor: Tile | None,
) -> None:
    """Refresh required_army/stage goal and advance the gather phase.

    The stage goal is ALWAYS recomputed with the current board's general
    garrison (never a static pre-gather goal): fast stage uses the fast wave
    set, slow stage the slow peak, READY requires both stage requirements met.
    """
    live = [ep for ep in episodes if not ep.cancelled]
    general = bot.general
    if not live or anchor is None or general is None:
        state.required_army = 0
        state.stage_goal_army = 0
        if state.phase != GeneralSafetyPhase.IDLE:
            state.phase = GeneralSafetyPhase.IDLE
            state.gather_moves = []
            state.gather_cursor = 0
        return
    deployment = _owned_bfs_distance(bot, anchor, general)
    for episode in live:
        episode.deployment_turns = deployment
    now = bot._map.turn
    anchor_army = anchor.army if anchor.player == bot.player.index else 0
    fast_required = _combined_required_at(
        bot, live, GeneralSafetyPhase.GATHER_FAST, now, general.army, deployment)
    slow_required = _combined_required_at(
        bot, live, GeneralSafetyPhase.GATHER_SLOW, now, general.army, deployment)
    phase = state.phase
    if phase in (GeneralSafetyPhase.IDLE, GeneralSafetyPhase.WATCH):
        phase = GeneralSafetyPhase.GATHER_FAST
    fast_deadline = _stage_deadline(live, GeneralSafetyPhase.GATHER_FAST)
    # Tests/test_FFA.py::FFATests.test_should_reinforce_nearby_defense_for_delayed_all_in:
    # once the fast wave's staging deadline has passed the fast window is closed -
    # the wave either arrived and the garrison absorbed it or never materialized -
    # so gathering must advance to the delayed-wave stage instead of stalling in
    # GATHER_FAST forever against an expired deadline.
    if (phase == GeneralSafetyPhase.GATHER_FAST
            and (anchor_army >= fast_required or now > fast_deadline)):
        phase = GeneralSafetyPhase.GATHER_SLOW
        logbook.info(
            f"GENERAL SAFETY fast stage ready turn={now} "
            f"anchor={anchor} army={anchor_army} required={fast_required} "
            f"deadline={fast_deadline}")
    if phase == GeneralSafetyPhase.GATHER_SLOW and anchor_army >= max(fast_required, slow_required):
        phase = GeneralSafetyPhase.READY
        state.gather_moves = []
        state.gather_cursor = 0
        logbook.info(
            f"GENERAL SAFETY slow stage ready turn={now} "
            f"anchor={anchor} army={anchor_army} required={max(fast_required, slow_required)}")
    state.phase = phase
    if phase == GeneralSafetyPhase.GATHER_FAST:
        state.required_army = fast_required
        state.stage_goal_army = fast_required
    elif phase == GeneralSafetyPhase.GATHER_SLOW:
        state.required_army = max(fast_required, slow_required)
        state.stage_goal_army = state.required_army
    else:
        state.required_army = max(fast_required, slow_required)
        state.stage_goal_army = state.required_army


def _stage_deadline(episodes: list[GeneralSafetyEpisode], phase: GeneralSafetyPhase) -> int:
    """Latest turn our gathered head must be staged: arrival - deploy - 1."""
    deadlines = []
    for episode in episodes:
        if episode.cancelled:
            continue
        wave = _stage_wave(episode, phase)
        deadlines.append(wave.arrival_turn - episode.deployment_turns - 1)
    return min(deadlines) if deadlines else -1


def _half_general_sources(moves: list[Move], player_index: int) -> list[Move]:
    """Rebuild general-sourced moves as half moves (garrison preservation).

    The safety gather may draw on the general, but never strip its garrison:
    every general-sourced step is converted to a half move so the literal
    forecast and the minimum_mobile_army retained-general credit stay honest.
    """
    out: list[Move] = []
    for move in moves:
        if (move.source.isGeneral and move.source.player == player_index
                and not move.move_half):
            out.append(Move(move.source, move.dest, True))
        else:
            out.append(move)
    return out


def _evaluate_schedule(
    bot: EklipZBot,
    moves: list[Move],
    anchor: Tile,
    episodes: list[GeneralSafetyEpisode],
    phase: GeneralSafetyPhase,
    forecast_enemy_index: int,
) -> tuple[int, bool] | None:
    """Projected anchor delivery plus whether it meets the stage requirement.

    Uses project_forward_gather on the CURRENT board; the candidate head at the
    anchor must reach minimum_combined_mobile_army evaluated at the projected
    completion turn with the projected general garrison (the authored math
    already folds in the raw phase wave launch floor, so no separate max is
    needed). The forecast enemy is the earliest-deadline episode's enemy -
    third-party captures by the gather are rejected by the projection itself.
    Returns (launch_army, certified) or None when the projection fails.
    """
    forecast = project_forward_gather(
        bot._map, moves, anchor, bot.player.index, forecast_enemy_index)
    if forecast is None:
        return None
    projected_gen = forecast.position.armies[bot.general.tile_index]
    deployment = episodes[0].deployment_turns if episodes else 1
    required = _combined_required_at(
        bot, episodes, phase, forecast.position.turn, projected_gen, deployment)
    certified = forecast.launch_army >= required
    if not certified:
        logbook.info(
            f"GENERAL SAFETY certify-short turn={bot._map.turn} "
            f"phase={phase.name} launch={forecast.launch_army} "
            f"required={required} projectedGen={projected_gen} "
            f"forecastTurn={forecast.position.turn}")
    return forecast.launch_army, certified


def _certify_schedule(
    bot: EklipZBot,
    moves: list[Move],
    anchor: Tile,
    episodes: list[GeneralSafetyEpisode],
    phase: GeneralSafetyPhase,
    forecast_enemy_index: int,
) -> bool:
    """Whether the literal schedule's projected delivery meets the stage goal."""
    evaluated = _evaluate_schedule(
        bot, moves, anchor, episodes, phase, forecast_enemy_index)
    return evaluated is not None and evaluated[1]


def _find_safe_schedule(
    bot: EklipZBot,
    state: GeneralSafetyState,
    episodes: list[GeneralSafetyEpisode],
    anchor: Tile,
    blocked: set[Tile],
    phase: GeneralSafetyPhase,
) -> list[Move] | None:
    """Search actual gather budgets ascending for the first certified schedule.

    Budgets run 1..min(25, deadline-now); each literal schedule is validated by
    project_forward_gather delivery (never a prefix of the max budget). The
    FIRST schedule meeting the stage goal wins - the shortest safe gather.
    Returns None when no safe schedule exists (caller passes deliberately,
    never silently converts to neutral expansion).
    """
    game_map = bot._map
    live = [ep for ep in episodes if not ep.cancelled]
    if not live:
        return None
    deployment = live[0].deployment_turns
    deadline = _stage_deadline(live, phase)
    if deadline < 0:
        return None
    max_budget = min(_MAX_GATHER_BUDGET, deadline - game_map.turn)
    forecast_enemy = min(
        live, key=lambda e: _stage_wave(e, phase).arrival_turn)
    empty_budgets = 0
    best_moves: list[Move] | None = None
    best_launch = -1
    for budget in range(1, max_budget + 1):
        moves = build_owned_gather_schedule(
            bot, anchor, blocked, budget, forecast_enemy.enemy_index)
        if not moves:
            empty_budgets += 1
            continue
        moves = _half_general_sources(moves, bot.player.index)
        evaluated = _evaluate_schedule(
            bot, moves, anchor, live, phase, forecast_enemy.enemy_index)
        certified = evaluated is not None and evaluated[1]
        logbook.info(
            f"GENERAL SAFETY schedule-candidate turn={game_map.turn} "
            f"phase={phase.name} budget={budget} moves={len(moves)} "
            f"certified={certified}")
        if evaluated is not None and evaluated[0] > best_launch:
            best_launch = evaluated[0]
            best_moves = moves
        if certified:
            state.stage_deadline_turn = deadline
            # Front-load the reserve: when one gather turn of headroom remains,
            # prepend a HALF general->anchor donation so the mobile stack is
            # already massed next to the general while the rest of the literal
            # plan keeps delivering. The enlarged plan is re-certified as a
            # whole - the projected garrison still covers the retained half,
            # so this never double-counts the donation.
            if budget < max_budget:
                early = _with_early_anchor_donation(bot, moves, anchor)
                if early is not None and _certify_schedule(
                        bot, early, anchor, live, phase,
                        forecast_enemy.enemy_index):
                    logbook.info(
                        f"GENERAL SAFETY early-donation schedule turn={game_map.turn} "
                        f"phase={phase.name} moves={len(early)}")
                    return early
            return moves

    # Tests/test_FFA.py::FFATests.test_should_reinforce_nearby_defense_for_delayed_all_in:
    # the delayed all-in forecast can price a requirement beyond what the local
    # owned economy can stage by the deadline (the conservative launch floor
    # grows with quiet elapsed). Refusing to gather at all then leaves the
    # general with no mobile reserve even though a large literal plan still
    # delivers a useful stack; gather the maximum-delivery owned schedule
    # instead of passing, since every step is owned-only and defensible.
    if best_moves is not None:
        logbook.info(
            f"GENERAL SAFETY best-effort schedule turn={game_map.turn} "
            f"phase={phase.name} moves={len(best_moves)} launch={best_launch}")
        state.stage_deadline_turn = deadline
        return best_moves
    logbook.info(
        f"GENERAL SAFETY schedule-search exhausted turn={game_map.turn} "
        f"phase={phase.name} maxBudget={max_budget} emptyBudgets={empty_budgets} "
        f"blocked={len(blocked)}")
    return None


def _with_early_anchor_donation(
    bot: EklipZBot,
    moves: list[Move],
    anchor: Tile,
) -> list[Move] | None:
    """Front-load garrison->anchor donations in a certified gather plan.

    Prepends a HALF general->anchor donation when geometrically legal, then
    pulls every remaining general->anchor donation in the plan up behind it.
    Urgent defense legitimately reclaims the anchor stack (threatdef priority
    is untouched), so donations scheduled only at the tail leave the reserve
    unbuilt when the wave arrives; front-loading lets the plan re-donate on
    the next turn. The caller re-certifies the enlarged literal plan as a
    whole - the projected garrison still covers every retained half, so this
    never double-counts a donation.
    """
    general = bot.general
    if general is None or general.army <= 1:
        return None
    player_index = bot.player.index
    if (anchor.player != player_index or anchor.isGeneral
            or anchor not in general.movable):
        return None
    donations = [
        move for move in moves
        if (move.dest.tile_index == anchor.tile_index
            and move.source.tile_index == general.tile_index)]
    rest = [
        move for move in moves
        if move not in donations]
    # Spread pulled donations through the plan instead of stacking them behind
    # the prepend: urgent threat defense legitimately reclaims the anchor stack
    # for a turn or two, so a donation parked at the tail arrives only after the
    # wave window while one parked mid-plan re-masses the reserve while the
    # relay is still delivering. Even spacing keeps literal order valid - the
    # caller re-certifies the whole enlarged plan before use.
    spaced: list[Move] = []
    slots = max(1, (len(rest) + 1) // max(1, len(donations) + 1))
    donation_index = 0
    for index, move in enumerate(rest):
        spaced.append(move)
        if ((index + 1) % slots == 0 and donation_index < len(donations)):
            spaced.append(donations[donation_index])
            donation_index += 1
    while donation_index < len(donations):
        spaced.append(donations[donation_index])
        donation_index += 1
    return [Move(general, anchor, True)] + spaced


def _validate_gather_move(
    bot: EklipZBot,
    scheduled: Move,
    defense_critical_tiles: set[Tile],
) -> Move | None:
    """Re-validate a scheduled gather move against the CURRENT map."""
    player_index = bot.player.index
    source = bot._map.tiles_by_index[scheduled.source.tile_index]
    dest = bot._map.tiles_by_index[scheduled.dest.tile_index]
    if source.player != player_index or source.army <= 1:
        return None
    if dest not in source.movable or dest.isNotPathable:
        return None
    if dest.player >= 0 and dest.player != player_index:
        return None
    if source in defense_critical_tiles or dest in defense_critical_tiles:
        return None
    return Move(source, dest, scheduled.move_half)


def _recertify_remaining(
    bot: EklipZBot,
    state: GeneralSafetyState,
    anchor: Tile,
    episodes: list[GeneralSafetyEpisode],
    phase: GeneralSafetyPhase,
) -> bool:
    """Full remaining-owned forecast on the current board before any offer."""
    live = [ep for ep in episodes if not ep.cancelled]
    if state.gather_cursor >= len(state.gather_moves) or not live:
        return False
    remaining = state.gather_moves[state.gather_cursor:]
    if not remaining:
        return False
    forecast_enemy = min(
        live, key=lambda e: _stage_wave(e, phase).arrival_turn)
    forecast = project_forward_gather(
        bot._map, remaining, anchor, bot.player.index, forecast_enemy.enemy_index)
    if forecast is None:
        return False
    projected_gen = forecast.position.armies[bot.general.tile_index]
    required = _combined_required_at(
        bot, live, phase, forecast.position.turn, projected_gen,
        forecast_enemy.deployment_turns)
    return forecast.launch_army >= required


def _offer(bot: EklipZBot, state: GeneralSafetyState, move: Move, phase: GeneralSafetyPhase) -> GeneralSafetyMoveResult:
    """Record the offer WITHOUT consuming the schedule (note_final_move does)."""
    state.phase = phase
    state.pending_offered_key = _move_key(move)
    state.pending_offered_turn = bot._map.turn
    return GeneralSafetyMoveResult(True, move, phase.name)


def get_move(bot: EklipZBot, defense_critical_tiles: set[Tile]) -> GeneralSafetyMoveResult:
    """Return the next literal reserve-gather move after all defense gates.

    Reached only after THREAT DEFENSE, survival fallback, DANGER TILES, flank
    defense, and city-preemptive defense have all had priority. While a stage
    is unmet the result is handled (move or deliberate pass) so unrelated
    offense cannot steal the window; READY returns unhandled so normal offense
    resumes with the anchor still protected by negatives + the final guard.
    """
    if not GENERAL_SAFETY_ENABLED:
        return GeneralSafetyMoveResult(False, None, "disabled")
    state = bot.general_safety_state
    if state is None or not state.episodes:
        return GeneralSafetyMoveResult(False, None, "no_episodes")
    game_map = bot._map
    live_episodes = [ep for ep in state.episodes.values() if not ep.cancelled]
    if not live_episodes:
        state.episodes.clear()
        state.phase = GeneralSafetyPhase.IDLE
        return GeneralSafetyMoveResult(False, None, "no_live_episodes")
    anchor = _select_anchor(bot, state, live_episodes)
    if anchor is None:
        return GeneralSafetyMoveResult(False, None, "no_anchor")
    state.anchor_tile_index = anchor.tile_index
    _update_required_and_stage(bot, state, live_episodes, anchor)
    if state.phase == GeneralSafetyPhase.READY:
        return GeneralSafetyMoveResult(False, None, "ready")
    phase = state.phase if state.phase != GeneralSafetyPhase.IDLE else GeneralSafetyPhase.GATHER_FAST
    # Lazily (re)build the literal schedule when missing/dirty, exhausted, or
    # built for a different stage than the current phase.
    need_schedule = (
        state.schedule_dirty
        or state.schedule_phase != phase
        or state.gather_cursor >= len(state.gather_moves)
        or not state.gather_moves)
    if need_schedule:
        state.schedule_dirty = False
        moves = _find_safe_schedule(bot, state, live_episodes, anchor, defense_critical_tiles, phase)
        if moves is None:
            bot.info(
                f"GENERAL SAFETY no safe schedule turn={game_map.turn} "
                f"phase={phase.name} (deliberate pass, not neutral expansion)")
            return GeneralSafetyMoveResult(True, None, "no_safe_schedule")
        state.gather_moves = moves
        state.gather_cursor = 0
        state.schedule_phase = phase
        logbook.info(
            f"GENERAL SAFETY schedule turn={game_map.turn} phase={phase.name} "
            f"moves={len(moves)} deadline={state.stage_deadline_turn} "
            f"required={state.stage_goal_army}")
    if state.gather_cursor >= len(state.gather_moves):
        return GeneralSafetyMoveResult(True, None, "schedule_exhausted")
    scheduled = state.gather_moves[state.gather_cursor]
    # Full remaining-owned forecast on the current board before offering.
    if not _recertify_remaining(bot, state, anchor, live_episodes, phase):
        state.schedule_dirty = True
        state.gather_moves = []
        state.gather_cursor = 0
        bot.info(f"GENERAL SAFETY recert failed turn={game_map.turn} rebuilding")
        return GeneralSafetyMoveResult(True, None, "recert_failed")
    move = _validate_gather_move(bot, scheduled, defense_critical_tiles)
    if move is None:
        state.schedule_dirty = True
        state.gather_moves = []
        state.gather_cursor = 0
        logbook.info(f"GENERAL SAFETY gather move invalid turn={game_map.turn} rebuilding")
        return GeneralSafetyMoveResult(True, None, "gather_move_invalid")
    return _offer(bot, state, move, phase)


def is_reserving(bot: EklipZBot) -> bool:
    """True while a live reservation holds the offense window (not READY)."""
    if not GENERAL_SAFETY_ENABLED:
        return False
    state = bot.general_safety_state
    if state is None:
        return False
    if state.phase in (GeneralSafetyPhase.READY, GeneralSafetyPhase.IDLE):
        return False
    return any(not ep.cancelled for ep in state.episodes.values())


def get_reserved_tiles(bot: EklipZBot) -> set[Tile]:
    """Anchor + remaining owned gather sources for OFFENSIVE negative sets only.

    Defense inputs (defenseCriticalTileSet consumers) must NOT receive these -
    defense is supposed to use the reserved army. Offense plans get them so
    they cannot spend the reservation.
    """
    if not GENERAL_SAFETY_ENABLED:
        return set()
    state = bot.general_safety_state
    if state is None:
        return set()
    reserved: set[Tile] = set()
    if 0 <= state.anchor_tile_index < len(bot._map.tiles_by_index):
        anchor = bot._map.tiles_by_index[state.anchor_tile_index]
        if anchor.player == bot.player.index and not anchor.isGeneral:
            reserved.add(anchor)
    for move in state.gather_moves[state.gather_cursor:]:
        source = bot._map.tiles_by_index[move.source.tile_index]
        if source.player == bot.player.index:
            reserved.add(source)
    return reserved


def offense_negatives(bot: EklipZBot, defense_critical_tiles: set[Tile]) -> set[Tile]:
    """defenseCriticalTileSet union reserved tiles, for offensive consumers."""
    negs = set(defense_critical_tiles)
    negs.update(get_reserved_tiles(bot))
    return negs


def _simulate_post_move_armies(
    bot: EklipZBot,
    move: Move,
    move_half: bool,
) -> tuple[int, int]:
    """(postMoveGeneralArmy, postMoveAnchorArmy) for an ordinary offense move.

    Simulates the actual FULL/HALF retained armies on the two protected tiles
    only; future general income is NOT claimed early - the math prices it.
    """
    game_map = bot._map
    player_index = bot.player.index
    source = move.source
    dest = move.dest
    sent = source.army // 2 if move_half else source.army - 1
    post_source = source.army - sent
    post_dest = dest.army + sent if dest.player == player_index else dest.army
    gen_army = bot.general.army
    anchor_army = 0
    state = bot.general_safety_state
    anchor_index = state.anchor_tile_index if state is not None else -1
    if 0 <= anchor_index < len(game_map.tiles_by_index):
        anchor = game_map.tiles_by_index[anchor_index]
        if anchor.player == player_index and not anchor.isGeneral:
            anchor_army = anchor.army
    if source.tile_index == bot.general.tile_index:
        gen_army = post_source
    elif dest.tile_index == bot.general.tile_index:
        gen_army = post_dest
    if state is not None and source.tile_index == anchor_index:
        anchor_army = post_source
    elif state is not None and dest.tile_index == anchor_index:
        anchor_army = post_dest
    return gen_army, anchor_army


def _guard_requirement(
    bot: EklipZBot,
    episodes: list[GeneralSafetyEpisode],
    phase: GeneralSafetyPhase,
    gen_army: int,
    deployment_turns: int,
) -> int:
    """minimum_combined_mobile_army for the final-move guard (current board)."""
    return _combined_required_at(
        bot, episodes, phase, bot._map.turn, gen_army, deployment_turns)


def _restore_blocked_stealth_step(bot: EklipZBot, blocked_move: Move) -> None:
    """Rewind a committed stealth route step the reserve guard rejected.

    BotStealthAllIn.get_committed_route_move pops the route head BEFORE the
    final-move guard runs; returning None here would leave the persisted route
    one step ahead of the unexecuted board and the next turn's head check
    would abort it as broken_head. Push the popped start tile back (with its
    original half flag) so the route re-offers the identical step once the
    reserve allows it - the route is never consumed by a blocked move.
    """
    stealth = bot.stealth_all_in
    if stealth is None or stealth.committed_route is None:
        return
    last = stealth.last_route_move
    if last is None:
        return
    if (last.source.tile_index != blocked_move.source.tile_index
            or last.dest.tile_index != blocked_move.dest.tile_index):
        return
    route = stealth.committed_route
    route.add_start(last.source)
    if route.start is not None:
        route.start.move_half = last.move_half
    stealth.last_route_move = None
    logbook.info(
        f"GENERAL SAFETY stealth route step restored turn={bot._map.turn} "
        f"move={last} (blocked move left route unconsumed)")


def reconcile_anchor_move(
    bot: EklipZBot,
    move: Move | None,
    defense_override: bool,
) -> Move | None:
    """Final-move backstop protecting the retained general AND the anchor.

    For ordinary offense sourced from the general or the anchor, simulate the
    actual FULL/HALF retained armies and require the post-move anchor army to
    cover minimum_combined_mobile_army(...) with the post-move general
    garrison. FULL failing but HALF passing offers HALF; otherwise the move is
    blocked. True defense overrides and our own pending safety-gather step are
    allowed (the full remaining literal plan was already certified to deliver
    by arrival-deployment-1, so earlier prefix steps may still be building).
    """
    if not GENERAL_SAFETY_ENABLED or move is None:
        return move
    state = bot.general_safety_state
    if state is None:
        return move
    live = [ep for ep in state.episodes.values() if not ep.cancelled]
    if not live or bot.general is None:
        return move
    if defense_override:
        return move
    # Our own safety gather step is exempt: the whole remaining literal plan
    # was certified up front, so prefix moves may still be building reserve.
    if state.pending_offered_key and _move_key(move) == state.pending_offered_key:
        return move
    anchor = _select_anchor(bot, state, live)
    if anchor is None:
        return move
    is_general_source = move.source.tile_index == bot.general.tile_index
    is_anchor_source = move.source.tile_index == anchor.tile_index
    if not is_general_source and not is_anchor_source:
        return move
    deployment = _owned_bfs_distance(bot, anchor, bot.general)
    # Try the move as offered; a FULL move that fails may still pass as HALF.
    candidates = [move.move_half]
    if not move.move_half:
        candidates.append(True)
    for candidate_half in candidates:
        gen_army, anchor_army = _simulate_post_move_armies(bot, move, candidate_half)
        required = _guard_requirement(bot, live, state.phase, gen_army, deployment)
        if required <= 0 or anchor_army >= required:
            if candidate_half != move.move_half:
                half = Move(move.source, move.dest, True)
                bot.info(
                    f"GENERAL SAFETY retain reserve: split {half} "
                    f"(required={required} anchor={anchor_army})")
                return half
            return move
    bot.info(
        f"GENERAL SAFETY retain reserve: reject {move} "
        f"(required>={state.required_army} anchor protected)")
    _restore_blocked_stealth_step(bot, move)
    return None


def is_pending_gather_move(bot: EklipZBot, move: Move | None) -> bool:
    """True when ``move`` is exactly this turn's certified safety-gather offer.

    The generic find_move isGeneral death-move heuristic evaluates any
    general-source move as a relocation and cannot model a certified HALF
    donation whose retained garrison plus gathered reserve the authored
    all-in math already prices. Only the exact pending key matches, so real
    general escapes and unrelated moves are unaffected.
    """
    if not GENERAL_SAFETY_ENABLED or move is None:
        return False
    state = bot.general_safety_state
    if state is None:
        return False
    return (
        state.pending_offered_turn == bot._map.turn
        and state.pending_offered_key != ""
        and _move_key(move) == state.pending_offered_key)


def note_final_move(bot: EklipZBot, move: Move | None) -> None:
    """Consume the pending safety offer iff the bot actually executed it.

    Only an exact key match advances the gather cursor once per turn; a pass,
    defense preemption, or unrelated move leaves the cursor untouched. A
    same-endpoints/different-half result clears the offer AND marks the
    literal forecast dirty so the next turn re-plans (a half delivers less
    than the certified full step - never assume full army arrived).
    """
    if not GENERAL_SAFETY_ENABLED:
        return
    state = bot.general_safety_state
    if state is None or state.pending_offered_turn < 0:
        return
    if state.pending_offered_turn != bot._map.turn:
        state.pending_offered_turn = -1
        state.pending_offered_key = ""
        return
    if move is None:
        state.pending_offered_turn = -1
        state.pending_offered_key = ""
        return
    last_key = _move_key(move)
    if last_key == state.pending_offered_key:
        _consume_offered(bot, state)
        return
    offered_base = state.pending_offered_key.rsplit(":", 1)[0]
    last_base = f"{move.source.tile_index}>{move.dest.tile_index}"
    if last_base == offered_base:
        logbook.info(
            f"GENERAL SAFETY reconcile half-mismatch turn={bot._map.turn} "
            f"offered={state.pending_offered_key} executed={last_key} replan")
        state.schedule_dirty = True
    state.pending_offered_turn = -1
    state.pending_offered_key = ""


def _consume_offered(bot: EklipZBot, state: GeneralSafetyState) -> None:
    """Advance the gather cursor for a confirmed executed move."""
    state.last_consumed_turn = bot._map.turn
    state.pre_consume_gather_cursor = state.gather_cursor
    state.pre_consume_phase = state.phase
    state.gather_cursor += 1
    state.pending_offered_key = ""
    state.pending_offered_turn = -1


def _resolve_anchor(bot: EklipZBot, state: GeneralSafetyState) -> Tile | None:
    """Return the live anchor tile, reselecting when the stored one is lost."""
    episodes = [ep for ep in state.episodes.values() if not ep.cancelled]
    anchor = _select_anchor(bot, state, episodes)
    if anchor is not None:
        state.anchor_tile_index = anchor.tile_index
    return anchor


def update(bot: EklipZBot) -> None:
    """Refresh episodes, forecasts, anchor, and WCA waves once per turn.

    Called in perform_move_prep AFTER scan_map_for_large_tiles_and_leaf_moves
    so fresh king-location knowledge and opponent-tracker state are current.
    Flag-off is a zero-cost no-op.
    """
    if not GENERAL_SAFETY_ENABLED:
        return
    game_map = bot._map
    state = bot.general_safety_state
    if state is None or bot.general is None:
        return
    state.last_update_turn = game_map.turn
    scope = _scope_kind(bot)
    # Drop dead/scope/econ-invalid episodes and release our reservations only;
    # other features' locks are never touched.
    for enemy_index in list(state.episodes.keys()):
        episode = state.episodes[enemy_index]
        ok, _ = _enemy_qualifies(bot, enemy_index, scope)
        if not ok:
            del state.episodes[enemy_index]
            continue
        _process_enemy_evidence(bot, episode)
        if episode.cancelled:
            del state.episodes[enemy_index]
            continue
        _refresh_slow_wave(bot, episode)
    # Create episodes for newly qualifying revealed enemies. A timestamped
    # reveal triggers IMMEDIATELY (the same prep turn the scan stamps it); the
    # quiet clock is anchored at the enemy's last seen move regardless, so a
    # still-active mover simply forms the episode now and _process_enemy_evidence
    # cancels it on its next unrelated visible move. Baseline fixtures without
    # a timestamp never activate.
    for player in game_map.players:
        enemy_index = player.index
        if enemy_index in state.episodes:
            continue
        if player.king_location_revealed_turn < 0:
            continue
        reveal_age = game_map.turn - player.king_location_revealed_turn
        if reveal_age < 0:
            continue
        # The one-round 50-tick response window gates ONLY the 2-team/1v1
        # exception; >2-team FFA episodes may form on any timestamped reveal.
        if scope == "duel" and reveal_age > _REVEAL_WINDOW_TURNS:
            continue
        ok, _reason = _enemy_qualifies(bot, enemy_index, scope)
        if not ok:
            continue
        route_tiles = _risk_route(bot, enemy_index)
        if route_tiles is None or len(route_tiles) < 2:
            continue
        anchor_tile = _select_anchor(bot, state, [])
        deployment = (
            _owned_bfs_distance(bot, anchor_tile, bot.general)
            if anchor_tile is not None else 1)
        episode = _build_episode(bot, enemy_index, route_tiles, deployment)
        if episode is None:
            continue
        state.episodes[enemy_index] = episode
        logbook.info(
            f"GENERAL SAFETY episode p{enemy_index} turn={game_map.turn} "
            f"reveal={episode.reveal_turn} quiet={episode.quiet_start_turn} "
            f"bank={episode.initial_bank_army} cap={episode.standing_cap} "
            f"fast={episode.fast_wave.launch_army}@{episode.fast_wave.arrival_turn} "
            f"slow={episode.slow_wave.launch_army}@{episode.slow_wave.arrival_turn} "
            f"(suspected hidden all-in, unobserved)")
    # Anchor + required army + phase.
    episodes = [ep for ep in state.episodes.values() if not ep.cancelled]
    anchor = _resolve_anchor(bot, state)
    _update_required_and_stage(bot, state, episodes, anchor)
    # Publish both phase alternatives per live enemy for viewer/analysis
    # (never repurposed WCA conditions); fast and delayed waves stay separate.
    waves: list[EnemyAllInWave] = []
    for episode in episodes:
        waves.append(episode.fast_wave)
        waves.append(episode.slow_wave)
    if bot.win_condition_analyzer is not None:
        bot.win_condition_analyzer.anticipated_all_in_waves = tuple(waves)
    # Compact diagnostic line (qualified enemies only - episodes are the
    # qualified set, so this never spams for ineligible players).
    if episodes:
        parts = []
        for episode in episodes:
            wave = _stage_wave(episode, state.phase)
            parts.append(
                f"p{episode.enemy_index}:rev{episode.reveal_turn}"
                f"/q{episode.quiet_start_turn}"
                f" r{len(episode.risk_route_tile_indexes)}e/w{wave.warning_turns}"
                f" f{episode.fast_wave.launch_army}@{episode.fast_wave.arrival_turn}"
                f" s{episode.slow_wave.launch_army}@{episode.slow_wave.arrival_turn}")
        anchor_desc = str(anchor) if anchor is not None else "none"
        bot.viewInfo.add_stats_line(
            f"GENERAL SAFETY {'; '.join(parts)} "
            f"anchor={anchor_desc} req={state.required_army} "
            f"goal={state.stage_goal_army} phase={state.phase.name} "
            f"cursor={state.gather_cursor}/{len(state.gather_moves)}")
        logbook.info(
            f"GENERAL SAFETY turn={game_map.turn} phase={state.phase.name} "
            f"required={state.required_army} goal={state.stage_goal_army} "
            f"anchor={state.anchor_tile_index} cursor={state.gather_cursor} "
            f"episodes={len(episodes)}")
    else:
        state.phase = GeneralSafetyPhase.IDLE
        state.gather_moves = []
        state.gather_cursor = 0
        state.schedule_phase = GeneralSafetyPhase.IDLE
        state.anchor_tile_index = -1
        state.required_army = 0
        state.stage_goal_army = 0


def _serialize_moves(moves: list[Move]) -> str:
    """Literal schedule as src>dst:half pairs joined by ';' (no '=' chars)."""
    return ";".join(
        f"{m.source.tile_index}>{m.dest.tile_index}:{int(m.move_half)}"
        for m in moves)


def _deserialize_moves(bot: EklipZBot, raw: str) -> list[Move]:
    """Restore literal moves against the freshly loaded map's tiles."""
    game_map = bot._map
    moves: list[Move] = []
    for part in raw.split(";"):
        if not part:
            continue
        src_dst, half = part.rsplit(":", 1)
        src, dst = src_dst.split(">")
        moves.append(Move(
            game_map.tiles_by_index[int(src)],
            game_map.tiles_by_index[int(dst)],
            bool(int(half))))
    return moves


def _wave_to_str(wave: EnemyAllInWave) -> str:
    """EnemyAllInWave as a flat comma list (all ints, fixed field order)."""
    return (
        f"{wave.gather_turns},{wave.attack_turns},{wave.warning_turns},"
        f"{wave.launch_turn},{wave.arrival_turn},{wave.ready_turn},"
        f"{wave.launch_army},{wave.bank_army},{wave.ordinary_army},"
        f"{wave.city_growth},{wave.tile_growth}")


def _wave_from_str(raw: str) -> EnemyAllInWave:
    """Restore an EnemyAllInWave from _wave_to_str output."""
    return EnemyAllInWave(*[int(x) for x in raw.split(",")])


def save_state(bot: EklipZBot) -> dict[str, str]:
    """Serialize reservation state to a txtmap block dict (dict only at boundary)."""
    data: dict[str, str] = {"bot_general_safety_active": "0"}
    if not GENERAL_SAFETY_ENABLED:
        return data
    state = bot.general_safety_state
    if state is None:
        return data
    live = [ep for ep in state.episodes.values() if not ep.cancelled]
    if not live:
        return data
    data["bot_general_safety_active"] = "1"
    data["bot_general_safety_anchor"] = str(state.anchor_tile_index)
    data["bot_general_safety_sched_phase"] = state.schedule_phase.name
    data["bot_general_safety_required"] = str(state.required_army)
    data["bot_general_safety_goal"] = str(state.stage_goal_army)
    data["bot_general_safety_deadline"] = str(state.stage_deadline_turn)
    data["bot_general_safety_last_update"] = str(state.last_update_turn)
    # PREMOVE alignment (same contract as FfaKillGather): when the confirmed
    # consume belongs to the CURRENT map turn the serialized board is still
    # pre-move, so emit the pre-consume cursor AND phase - a resume then points
    # at the step the pre-move map actually expects instead of skipping it.
    # schedule_phase stays live: it names the phase the serialized move list
    # was certified under, which the pre-consume cursor still indexes into.
    if state.last_consumed_turn == bot._map.turn:
        phase_out = state.pre_consume_phase.name
        cursor_out = state.pre_consume_gather_cursor
    else:
        phase_out = state.phase.name
        cursor_out = state.gather_cursor
    data["bot_general_safety_phase"] = phase_out
    data["bot_general_safety_cursor"] = str(cursor_out)
    data["bot_general_safety_pending_key"] = state.pending_offered_key
    data["bot_general_safety_pending_turn"] = str(state.pending_offered_turn)
    data["bot_general_safety_moves"] = _serialize_moves(state.gather_moves)
    # Episodes: one '|'-joined block per enemy, ';'-separated episodes. Every
    # field is int/tuple/wave-string - never contains '=', '|', or ';'.
    ep_blobs = []
    for episode in live:
        ep_blobs.append("|".join([
            str(episode.enemy_index),
            str(episode.reveal_turn),
            str(episode.quiet_start_turn),
            str(episode.created_turn),
            str(episode.initial_bank_army),
            str(episode.standing_cap),
            ",".join(str(a) for a in episode.ordinary_armies),
            str(episode.ordinary_tile_count),
            str(episode.visible_ordinary_count),
            str(episode.excluded_visible_ordinary_surplus),
            str(episode.city_count),
            ",".join(str(i) for i in episode.risk_route_tile_indexes),
            str(episode.attack_turns),
            str(episode.fast_warning_turns),
            str(episode.slow_warning_turns),
            str(episode.route_cost),
            str(episode.deployment_turns),
            _wave_to_str(episode.fast_wave),
            _wave_to_str(episode.slow_wave),
            str(episode.last_seen_move_turn),
            episode.last_move_signature.replace("|", "").replace(";", "").replace("=", ""),
        ]))
    data["bot_general_safety_episodes"] = ";".join(ep_blobs)
    return data


def load_state(bot: EklipZBot, resume_data: dict[str, str]) -> None:
    """Restore reservation state; default inactive when absent/flag-off."""
    state = bot.general_safety_state
    if state is None:
        state = GeneralSafetyState()
        bot.general_safety_state = state
    if (not GENERAL_SAFETY_ENABLED
            or resume_data.get("bot_general_safety_active", "0") != "1"):
        state.episodes.clear()
        state.phase = GeneralSafetyPhase.IDLE
        state.gather_moves = []
        state.gather_cursor = 0
        state.schedule_phase = GeneralSafetyPhase.IDLE
        state.anchor_tile_index = -1
        state.required_army = 0
        state.stage_goal_army = 0
        state.schedule_dirty = False
        return
    state.anchor_tile_index = int(resume_data.get("bot_general_safety_anchor", "-1"))
    state.phase = GeneralSafetyPhase[resume_data.get("bot_general_safety_phase", "IDLE")]
    state.schedule_phase = GeneralSafetyPhase[resume_data.get("bot_general_safety_sched_phase", "IDLE")]
    state.required_army = int(resume_data.get("bot_general_safety_required", "0"))
    state.stage_goal_army = int(resume_data.get("bot_general_safety_goal", "0"))
    state.stage_deadline_turn = int(resume_data.get("bot_general_safety_deadline", "-1"))
    state.last_update_turn = int(resume_data.get("bot_general_safety_last_update", "-1"))
    state.gather_moves = _deserialize_moves(bot, resume_data.get("bot_general_safety_moves", ""))
    # The serialized cursor is the PRE-consume cursor when the save happened
    # on the same turn as a confirmed consume (PREMOVE board alignment).
    state.gather_cursor = int(resume_data.get("bot_general_safety_cursor", "0"))
    state.pending_offered_key = resume_data.get("bot_general_safety_pending_key", "")
    state.pending_offered_turn = int(resume_data.get("bot_general_safety_pending_turn", "-1"))
    state.schedule_dirty = False
    state.episodes.clear()
    for blob in resume_data.get("bot_general_safety_episodes", "").split(";"):
        if not blob:
            continue
        parts = blob.split("|")
        if len(parts) < 21:
            continue
        episode = GeneralSafetyEpisode(
            enemy_index=int(parts[0]),
            reveal_turn=int(parts[1]),
            quiet_start_turn=int(parts[2]),
            created_turn=int(parts[3]),
            initial_bank_army=int(parts[4]),
            standing_cap=int(parts[5]),
            ordinary_armies=tuple(int(x) for x in parts[6].split(",") if x),
            ordinary_tile_count=int(parts[7]),
            visible_ordinary_count=int(parts[8]),
            excluded_visible_ordinary_surplus=int(parts[9]),
            city_count=int(parts[10]),
            risk_route_tile_indexes=tuple(int(x) for x in parts[11].split(",") if x),
            attack_turns=int(parts[12]),
            fast_warning_turns=int(parts[13]),
            slow_warning_turns=int(parts[14]),
            route_cost=int(parts[15]),
            deployment_turns=int(parts[16]),
            fast_wave=_wave_from_str(parts[17]),
            slow_wave=_wave_from_str(parts[18]),
            last_seen_move_turn=int(parts[19]),
            last_move_signature=parts[20])
        state.episodes[episode.enemy_index] = episode
