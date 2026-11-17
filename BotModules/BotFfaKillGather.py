"""FFA (>2 living teams) economic kill-gather expansion option.

Evaluates whether a certified gather-then-kill against a nearby enemy general
beats ordinary flow expansion, offers at most one certified option into the
normal expansion knapsack, and - once that option is selected - commits the
bot to a literal gather/launch/search/finish schedule with defense priority.

Correctness of the kill certificate lives in Strategy/FfaKillGatherMath.py;
this module owns eligibility, candidate search, gather/route construction,
commit state, execution, serialization, and diagnostics. It never weakens the
certificate, never commits on a partial candidate set, and keeps the feature
flag FALSE until explicitly enabled for tests/live.
"""

from __future__ import annotations

import pickle
import time
import typing
from collections import deque
from dataclasses import dataclass

import logbook

from Algorithms import WatchmanRouteUtils
from BotModules.WrpWorkerProcess import WrpRequest, WrpWorkerProcess
from DistanceMapperImpl import DistanceMapperImpl
from Gather.GatherCapturePlan import GatherCapturePlan
from Gather.GatherPrune import prune_mst_to_turns
from Gather.GatherUtils import gather_approximate_turns_to_tiles
from MapMatrix import MapMatrix
from Models import GatherTreeNode
from Models.Move import Move
from Path import MoveListPath
from Strategy.FfaKillGatherMath import (
    FfaGatherForecast,
    FfaKillProjection,
    FfaKillScenario,
    FfaKillValue,
    FfaSafeFrontForecast,
    bounded_defensive_pool,
    calculate_kill_value,
    calculate_route_cost,
    certify_gather_scenarios,
    certify_kill,
    certify_retained_head_continuation,
    city_late_gather_schedules,
    fog_buffered_certified,
    fog_margin_buffer,
    materialize_gather_position,
    project_forward_gather,
    project_safe_front,
    remaining_ordinary_sources,
)
from base.client.map import MapBase
from base.client.tile import Tile

if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot
    from StrategyModels.ExpansionPotential import ExpansionPotential

# Feature flag. Kept FALSE in the live tree; tests patch it True only inside the
# test process via the exact runner the lead provided. The real behavioral gate
# is the >2-living-teams FFA check inside _is_ffa_kill_gather_active.
FFA_KILL_GATHER_ENABLED: bool = False

# Hard caps from the settled design.
_MAX_GENERAL_HYPOTHESES: int = 64
_MAX_LAUNCH_ROOTS: int = 4
_MAX_REACH_TURNS: int = 25
_GATHER_TIME_LIMIT: float = 0.01
_WRP_LIVE_TIME_LIMIT: float = 1.0
_WRP_SYNC_TIME_LIMIT: float = 0.03
_PREPARE_TIME_BUDGET: float = 0.20


def _vinfo(bot: "EklipZBot", line: str) -> None:
    """Emit a committed-plan DECISION line to logbook AND the viewInfo pane.

    .windsurfrules: verdicts that can override moves another system already
    logged (cert aborts/slams vetoing a QK-advertised kill, phase transitions,
    offer-vs-executed reconciles) must be visible in viewInfo, not only in the
    text log - otherwise the turn log shows e.g. a 100% QK kill and then
    silently no attack. add_info_line logbook.infos for us, so the text log is
    unchanged; falls back to logbook-only when viewInfo is not up yet.
    """
    if bot.viewInfo is not None:
        bot.viewInfo.add_info_line(line)
    else:
        logbook.info(line)


class FfaKillGatherOption(MoveListPath):
    """A single certified FFA kill-gather plan offered to flow expansion.

    `length` reserves the WHOLE gather + worst per-hypothesis hunt/finish window
    so flow resource accounting cannot double-book the cycle. The move list is a
    coherent representative: literal gather moves followed by real hunt/finish
    route steps (never None padding), so tileSet/resources cover the attack
    corridor. `clone` preserves the subtype and certificate metadata.
    """

    __slots__ = (
        "enemy_index",
        "launch_tile",
        "gather_moves",
        "hunt_route_tiles",
        "hunt_moves",
        "candidates",
        "projection",
        "kill_value",
        "gather_turns",
        "route_turns",
        "deadline_turn",
        "certificate_turns",
        "reserved_turns",
        # Composite safe-front metadata (R7). first_kill_turns is the earliest
        # first-vantage capture time; guaranteed_turns is the full all-hypothesis
        # horizon (may exceed one cycle). safe_front_hunt_cursor >=0 marks a
        # composite plan whose hunt must pause at that cursor for the stored
        # secondary gather; continuation_gather_moves is that owned-only backup.
        "first_kill_turns",
        "guaranteed_turns",
        "safe_front_hunt_cursor",
        "continuation_gather_moves",
    )

    def __init__(
        self,
        moves: list[Move | None],
        enemy_index: int,
        launch_tile: Tile,
        gather_moves: list[Move],
        hunt_route_tiles: list[Tile],
        hunt_moves: list[Move],
        candidates: list[Tile],
        projection: FfaKillProjection,
        kill_value: FfaKillValue,
        gather_turns: int,
        route_turns: int,
        deadline_turn: int,
        reserved_turns: int,
        first_kill_turns: int | None = None,
        guaranteed_turns: int | None = None,
        safe_front_hunt_cursor: int = -1,
        continuation_gather_moves: list[Move] | None = None,
    ) -> None:
        super().__init__(moves)
        self.enemy_index: int = enemy_index
        self.launch_tile: Tile = launch_tile
        self.gather_moves: list[Move] = gather_moves
        self.hunt_route_tiles: list[Tile] = hunt_route_tiles
        self.hunt_moves: list[Move] = hunt_moves
        self.candidates: list[Tile] = candidates
        self.projection: FfaKillProjection = projection
        self.kill_value: FfaKillValue = kill_value
        self.gather_turns: int = gather_turns
        self.route_turns: int = route_turns
        self.deadline_turn: int = deadline_turn
        self.certificate_turns: int = gather_turns + route_turns
        self.reserved_turns: int = reserved_turns
        # Ordinary single-wave plans default to a same-cycle certificate; a
        # composite safe-front option overrides these with its split horizon.
        self.first_kill_turns: int = (
            first_kill_turns if first_kill_turns is not None else self.certificate_turns)
        self.guaranteed_turns: int = (
            guaranteed_turns if guaranteed_turns is not None else self.certificate_turns)
        self.safe_front_hunt_cursor: int = safe_front_hunt_cursor
        self.continuation_gather_moves: list[Move] = (
            list(continuation_gather_moves) if continuation_gather_moves is not None else [])
        self.econValue = float(kill_value.total)

    def clone(self) -> FfaKillGatherOption:
        """Return a copy preserving the FFA subtype and certificate metadata."""
        cloned = FfaKillGatherOption(
            moves=list(self.get_move_list()),
            enemy_index=self.enemy_index,
            launch_tile=self.launch_tile,
            gather_moves=list(self.gather_moves),
            hunt_route_tiles=list(self.hunt_route_tiles),
            hunt_moves=list(self.hunt_moves),
            candidates=list(self.candidates),
            projection=self.projection,
            kill_value=self.kill_value,
            gather_turns=self.gather_turns,
            route_turns=self.route_turns,
            deadline_turn=self.deadline_turn,
            reserved_turns=self.reserved_turns,
            first_kill_turns=self.first_kill_turns,
            guaranteed_turns=self.guaranteed_turns,
            safe_front_hunt_cursor=self.safe_front_hunt_cursor,
            continuation_gather_moves=list(self.continuation_gather_moves),
        )
        cloned.econValue = self.econValue
        return cloned


class FfaKillGatherState:
    """Committed kill-gather execution state persisted across turns/resume.

    The gather schedule is a literal ordered move list; the hunt is a WRP tile
    route with an explicit cursor (never re-derived by army) plus a finishing
    path used once the real general is revealed. `pending_offered` records the
    exact move offered last turn so reconciliation consumes it only when the
    bot actually executed it.
    """

    __slots__ = (
        "enemy_index",
        "launch_tile_index",
        "gather_moves",
        "gather_cursor",
        "hunt_route_tile_indexes",
        "hunt_cursor",
        "head_tile_index",
        "finishing_route_tile_indexes",
        "candidates",
        "created_turn",
        "deadline_turn",
        "kill_value_total",
        "projection_margin",
        "pending_offered_key",
        "pending_offered_turn",
        "pending_offered_half",
        "pending_offered_dest_index",
        "owns_exclusive_lock",
        "phase",
        # Transient PREMOVE preimage recorded at consume time so save_state can
        # serialize the instruction aligned with the not-yet-applied board. Never
        # persisted as its own keys and never restored by load_state (the writer
        # already emits aligned values); last_consumed_turn=-1 default prevents a
        # double rewind when no same-turn consume happened.
        "last_consumed_turn",
        "pre_consume_gather_cursor",
        "pre_consume_hunt_cursor",
        "pre_consume_head_tile_index",
        "pre_consume_phase",
        # Composite safe-front continuation (R7). safe_front_hunt_cursor is the
        # hunt-cursor value at which the surviving head reaches the certified
        # safe-front tile (-1 = ordinary single-wave plan). continuation_gather_
        # moves is the stored owned-only secondary gather delivered to that
        # stationary head; spans_cycles marks a plan whose guaranteed horizon
        # crosses the current 50-turn cycle so recertification uses the ABSOLUTE
        # deadline rather than the remaining-cycle remainder.
        "safe_front_hunt_cursor",
        "continuation_gather_moves",
        "spans_cycles",
    )

    def __init__(
        self,
        enemy_index: int,
        launch_tile_index: int,
        gather_moves: list[Move],
        hunt_route_tile_indexes: list[int],
        candidates: list[int],
        created_turn: int,
        deadline_turn: int,
        kill_value_total: float,
        projection_margin: int,
        owns_exclusive_lock: bool,
    ) -> None:
        self.enemy_index: int = enemy_index
        self.launch_tile_index: int = launch_tile_index
        self.gather_moves: list[Move] = gather_moves
        self.gather_cursor: int = 0
        self.hunt_route_tile_indexes: list[int] = hunt_route_tile_indexes
        self.hunt_cursor: int = 0
        self.head_tile_index: int = launch_tile_index
        self.finishing_route_tile_indexes: list[int] = []
        self.candidates: list[int] = candidates
        self.created_turn: int = created_turn
        self.deadline_turn: int = deadline_turn
        self.kill_value_total: float = kill_value_total
        self.projection_margin: int = projection_margin
        self.pending_offered_key: str = ""
        self.pending_offered_turn: int = -1
        self.pending_offered_half: bool = False
        self.pending_offered_dest_index: int = -1
        self.owns_exclusive_lock: bool = owns_exclusive_lock
        self.phase: str = "gather"
        # Transient PREMOVE preimage (see __slots__): safe defaults so a fresh or
        # resumed state never triggers the save_state rewind path.
        self.last_consumed_turn: int = -1
        self.pre_consume_gather_cursor: int = 0
        self.pre_consume_hunt_cursor: int = 0
        self.pre_consume_head_tile_index: int = launch_tile_index
        self.pre_consume_phase: str = "gather"
        # Composite safe-front continuation defaults (ordinary plan: no safe
        # front, no stored secondary gather, single-cycle deadline).
        self.safe_front_hunt_cursor: int = -1
        self.continuation_gather_moves: list[Move] = []
        self.spans_cycles: bool = False


class FfaKillGatherCommittedMove:
    """Typed result of get_committed_move: handled flag plus optional move."""

    __slots__ = ("handled", "move", "reason")

    def __init__(self, handled: bool, move: Move | None, reason: str) -> None:
        self.handled: bool = handled
        self.move: Move | None = move
        self.reason: str = reason


class FfaKillGatherJob:
    """One in-flight WRP route request owned by this feature's worker."""

    __slots__ = (
        "generation",
        "enemy_index",
        "launch_tile_index",
        "candidate_tile_indexes",
        "cache_key",
        "done",
        "result_tile_indexes",
        "duration_sec",
        "time_limit",
    )

    def __init__(
        self,
        generation: int,
        enemy_index: int,
        launch_tile_index: int,
        candidate_tile_indexes: list[int],
        cache_key: tuple[int, int, tuple[int, ...], tuple[int, ...]],
        time_limit: float,
    ) -> None:
        self.generation: int = generation
        self.enemy_index: int = enemy_index
        self.launch_tile_index: int = launch_tile_index
        self.candidate_tile_indexes: list[int] = candidate_tile_indexes
        self.cache_key: tuple[int, int, tuple[int, ...], tuple[int, ...]] = cache_key
        self.done: bool = False
        self.result_tile_indexes: list[int] | None = None
        self.duration_sec: float = 0.0
        self.time_limit: float = time_limit


class FfaKillGatherCandidate:
    """Diagnostic record for one A+B-eligible victim (never spammed otherwise)."""

    __slots__ = (
        "enemy_index",
        "eligible",
        "reject_reason",
        "standing_army",
        "econ_value",
        "queue_armies",
        "free_pool",
        "hypothesis_count",
        "launch_roots",
        "gather_turns",
        "route_turns",
        "launch_army",
        "route_cost",
        "enemy_defense",
        "margin",
        "value_total",
        "certified",
        "chosen",
        "saw_projection",
    )

    def __init__(self, enemy_index: int) -> None:
        self.enemy_index: int = enemy_index
        self.eligible: bool = False
        self.reject_reason: str = ""
        self.standing_army: int = 0
        self.econ_value: int = 0
        self.queue_armies: list[int] = []
        self.free_pool: int = 0
        self.hypothesis_count: int = 0
        self.launch_roots: int = 0
        self.gather_turns: int = 0
        self.route_turns: int = 0
        self.launch_army: int = 0
        self.route_cost: int = 0
        self.enemy_defense: int = 0
        self.margin: int = 0
        self.value_total: float = 0.0
        self.certified: bool = False
        self.chosen: bool = False
        self.saw_projection: bool = False


class FfaKillGatherCache:
    """Per-bot cached search artifacts to avoid recomputing every tick."""

    __slots__ = (
        "wrp_worker",
        "wrp_generation",
        "pending_job",
        "route_cache",
        "option_cache",
        "last_prepare_turn",
        "candidates",
        "best_failed",
        "root_cursor",
    )

    def __init__(self) -> None:
        self.wrp_worker: WrpWorkerProcess | None = None
        self.wrp_generation: int = 0
        self.pending_job: FfaKillGatherJob | None = None
        self.route_cache: dict[tuple[int, int, tuple[int, ...], tuple[int, ...]], list[int] | None] = {}
        self.option_cache: FfaKillGatherOption | None = None
        self.last_prepare_turn: int = -1
        self.candidates: dict[int, FfaKillGatherCandidate] = {}
        self.best_failed: FfaKillGatherCandidate | None = None
        # Round-robin cursor so deferred launch roots get evaluated on later
        # prepare calls instead of the same leading roots starving the budget.
        self.root_cursor: int = 0


def _get_cache(bot: EklipZBot) -> FfaKillGatherCache:
    """Return the feature cache stored on the bot (created in the constructor)."""
    return bot._ffa_kill_gather_cache


def is_committed(bot: EklipZBot) -> bool:
    """Return whether a certified kill-gather is currently committed.

    Clears invalid scope/deadline/target state safely BEFORE the early-offense
    gates read this, so a stale commit cannot suppress legitimate nondefensive
    returns. A still-valid commit keeps the flag set so committed execution (and
    its defense-priority ordering) stays active. Flag-off is a zero-cost no-op.
    """
    if not FFA_KILL_GATHER_ENABLED:
        return False
    # FFA-end cleanup: once the game drops to <=2 living teams the feature's
    # worker/cache/state/lock are released here rather than lingering until game
    # over. Runs before the state check so a worker/cache left by an uncommitted
    # search is also released; a cheap no-op while the game is still a >2-team FFA.
    shutdown_if_not_ffa(bot)
    state = bot.ffa_kill_gather_state
    if state is None:
        return False
    game_map = bot._map
    if not _is_ffa_kill_gather_active(bot):
        _abort(bot, "scope_not_ffa")
        return False
    if not _score_alive(bot, state.enemy_index):
        _abort(bot, "target_gone")
        return False
    if game_map.turn > state.deadline_turn:
        _abort(bot, "deadline_passed")
        return False
    return True


def poll_wrp_worker(bot: EklipZBot) -> None:
    """Drain the feature's private WRP worker once per move (top of move loop)."""
    if not FFA_KILL_GATHER_ENABLED:
        return
    _poll_wrp(bot._ffa_kill_gather_cache)


def _living_team_count(bot: EklipZBot) -> int:
    """Count distinct living team ids from the fresh scoreboard.

    Uses map.scores (dead/tiles) so remote unseen living enemies still count;
    len(player.tiles) is unreliable because unseen land has no Tile objects and
    a captured player's dead flag can lag.
    """
    game_map = bot._map
    living: set[int] = set()
    for score in game_map.scores:
        if score.dead or score.tiles <= 0:
            continue
        living.add(game_map.team_ids_by_player_index[score.player])
    return len(living)


def _score_alive(bot: EklipZBot, player_index: int) -> bool:
    """Return whether a player is alive on the fresh scoreboard."""
    score = bot._map.scores[player_index]
    return not score.dead and score.tiles > 0


def _econ_value(player) -> int:
    """Economic strength proxy: tiles + 25 per city (settled gate metric)."""
    return player.tileCount + 25 * player.cityCount


def _econ_ahead(bot: EklipZBot, enemy_index: int) -> bool:
    """True while we strictly lead the victim economically (slam gate)."""
    return _econ_value(bot.player) > _econ_value(bot._map.players[enemy_index])


def _slam_capable(bot: EklipZBot, state: FfaKillGatherState) -> Tile | None:
    """The confirmed general a committed plan may slam, or None.

    Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_
    possible_vs_defender20/34: FFA slam mode ignores the kill certificate once
    the plan is committed - while we still lead the victim economically we keep
    throwing waves at the confirmed general until it dies, because every enemy
    tile and half their standing is recovered on the capture anyway. Only a
    CONFIRMED general qualifies (a hypothesis cannot be slammed), and only
    while the economy lead holds.
    """
    if not _econ_ahead(bot, state.enemy_index):
        return None
    return _known_general_tile(bot, state.enemy_index)


def _is_ffa_kill_gather_active(bot: EklipZBot) -> bool:
    """True only for a real FFA: more than two living teams.

    Deliberately independent of targetPlayer: a targetless board can still have
    a nearby kill-gather victim, and the targetless admission failure must not
    recur. >2 players in a 2v2 is NOT an FFA (two living teams).
    """
    if not FFA_KILL_GATHER_ENABLED:
        return False
    return _living_team_count(bot) > 2


def _enemy_is_eligible(bot: EklipZBot, enemy_index: int) -> tuple[bool, str]:
    """Cheap per-victim eligibility gates before any expensive search."""
    game_map = bot._map
    if enemy_index == bot.player.index or enemy_index in game_map.teammates:
        return False, "self_or_teammate"
    if not _score_alive(bot, enemy_index):
        return False, "enemy_dead"
    enemy = game_map.players[enemy_index]
    # Respect an existing exclusive lock: never steal a different committed target.
    if bot.ffa_exclusive_target_lock != -1 and bot.ffa_exclusive_target_lock != enemy_index:
        return False, "exclusive_lock_other"
    # Strict material lead: standing AND economy must strictly exceed the enemy's.
    if bot.player.standingArmy <= enemy.standingArmy:
        return False, "standing_not_greater"
    if _econ_value(bot.player) <= _econ_value(enemy):
        return False, "econ_not_greater"
    # Refuse when any other living enemy is highly aggressive.
    for player in game_map.players:
        if player.index in (enemy_index, bot.player.index) or player.index in game_map.teammates:
            continue
        if not _score_alive(bot, player.index):
            continue
        if player.aggression_factor > 120:
            return False, "third_party_aggression"
    return True, ""


def _general_hypotheses(bot: EklipZBot, enemy_index: int) -> list[Tile] | None:
    """All plausible enemy-general positions, or None when the set is uncertain.

    Union of: the confirmed known general (isGeneral + owned by the victim), the
    armyTracker valid-general-position matrix, and the flat alt_en_gen_positions
    list. Deduped by tile_index; MORE than _MAX_GENERAL_HYPOTHESES rejects the
    victim outright (a partial candidate set can never certify).
    """
    game_map = bot._map
    enemy = game_map.players[enemy_index]
    gen = enemy.general
    if gen is not None and gen.isGeneral and gen.player == enemy_index:
        # A CONFIRMED real general makes every inferred alt/tracker candidate a
        # phantom - return it as the sole hypothesis immediately rather than
        # unioning positions that can no longer be the hiding spot.
        return [gen]

    hypotheses: list[Tile] = []
    seen: set[int] = set()

    def _add(tile: Tile | None) -> None:
        if tile is None or tile.tile_index in seen:
            return
        seen.add(tile.tile_index)
        hypotheses.append(tile)

    valid_mat = bot.armyTracker.valid_general_positions_by_player[enemy_index]
    for tile in game_map.tiles_by_index:
        if valid_mat.raw[tile.tile_index]:
            _add(tile)

    for tile in bot.alt_en_gen_positions[enemy_index]:
        _add(tile)

    if len(hypotheses) > _MAX_GENERAL_HYPOTHESES:
        return None
    return hypotheses


def _restricted_distances(
    game_map: MapBase,
    start: Tile,
    player_index: int,
    enemy_index: int,
    blocked: set[Tile],
    allowed_endpoint_indexes: set[int] | None = None,
) -> dict[int, int]:
    """BFS distances over own/neutral/victim land only (no third-party crossing).

    Own 1-tiles remain valid connectors. `allowed_endpoint_indexes` carries the
    current general-hypothesis tile indexes: a fog tile predicted to a THIRD party
    can still be APPROACHED/revealed as a hypothesis endpoint (the same exception
    _finish_path and calculate_route_cost grant), so it must not make a nearby
    victim look unreachable at the proximity gate. Returns tile_index -> distance.
    """
    endpoints = allowed_endpoint_indexes if allowed_endpoint_indexes is not None else set()
    distances: dict[int, int] = {start.tile_index: 0}
    queue: deque[Tile] = deque([start])
    while queue:
        tile = queue.popleft()
        dist = distances[tile.tile_index]
        for nxt in _ordered_neighbors(tile, player_index):
            if nxt.tile_index in distances or nxt in blocked or nxt.isNotPathable:
                continue
            owner = nxt.player
            is_endpoint = nxt.tile_index in endpoints
            if owner >= 0 and owner not in (player_index, enemy_index) and not is_endpoint:
                continue
            distances[nxt.tile_index] = dist + 1
            # A third-party hypothesis ENDPOINT is marked reachable (so proximity
            # sees it) but must NOT be enqueued/expanded through - it is a reveal
            # target, not a corridor. Own/neutral/victim tiles always expand.
            forbidden_endpoint = is_endpoint and owner >= 0 and owner not in (player_index, enemy_index)
            if not forbidden_endpoint:
                queue.append(nxt)
    return distances


def _ordered_neighbors(tile: Tile, player_index: int) -> list[Tile]:
    """Stable own-first neighbor ordering for deterministic BFS tie-breaks."""
    neighbors = list(tile.movable)
    neighbors.sort(key=lambda t: (0 if t.player == player_index else 1, t.tile_index))
    return neighbors


def _reachable_within(
    distances: dict[int, int],
    targets: list[Tile],
    max_distance: int,
) -> bool:
    """True when every target is within max_distance of the BFS source."""
    for target in targets:
        if distances.get(target.tile_index, 1 << 30) > max_distance:
            return False
    return True


def _ordinary_queue_sources(bot: EklipZBot, enemy_index: int) -> list[int]:
    """RAW fog-queue ordinary armies only (the capture-reward input).

    Visible ordinary tiles are defense inputs, NOT reward inputs, so they are
    deliberately excluded here; _visible_ordinary_sources handles defense.
    """
    queue = bot.opponent_tracker.get_player_gather_queue(enemy_index)
    return list(queue.as_tile_list(includeOnesAndZeros=True))


def _visible_ordinary_sources(bot: EklipZBot, enemy_index: int) -> list[int]:
    """VISIBLE non-city/non-general victim tile armies (defense inputs only)."""
    armies: list[int] = []
    for tile in bot._map.tiles_by_index:
        if tile.player != enemy_index or not tile.visible:
            continue
        if tile.isCity or tile.isGeneral:
            continue
        armies.append(tile.army)
    return armies


def _all_ordinary_sources(bot: EklipZBot, enemy_index: int) -> list[int]:
    """Combined ordinary defender sources = raw queue + visible ordinary tiles."""
    return _ordinary_queue_sources(bot, enemy_index) + _visible_ordinary_sources(bot, enemy_index)


def _enemy_counts(bot: EklipZBot, enemy_index: int) -> tuple[int, int]:
    """Return (tile_count, city_count) for the enemy from the player record."""
    enemy = bot._map.players[enemy_index]
    return enemy.tileCount, enemy.cityCount


def _finish_path(
    game_map: MapBase,
    start: Tile,
    end: Tile,
    player_index: int,
    enemy_index: int,
    max_distance: int = 200,
) -> list[Tile] | None:
    """Shortest legal finishing route start->end without third-party land.

    Mirrors the lead probe finish_path: own/neutral/victim land plus the single
    fog-hypothesis exception (the END tile only, and only when it is an
    undiscovered fog tile). Undiscovered non-endpoint cities are blocked. This
    exception is hypothetical-only; actual execution never uses it to enter a
    revealed third-party tile.
    """
    if start == end:
        return [start]
    parents: dict[int, Tile | None] = {start.tile_index: None}
    # Genuine BFS depth per node - max_distance bounds path LENGTH, not the
    # number of tiles visited (an arbitrary visited cutoff could truncate a
    # legitimately long but shallow finish).
    queue: deque[tuple[Tile, int]] = deque([(start, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_distance:
            continue
        for neighbor in _ordered_neighbors(current, player_index):
            if neighbor.tile_index in parents or neighbor.isNotPathable:
                continue
            is_hypothesis_end = neighbor == end and not end.visible
            if neighbor.player not in (-1, player_index, enemy_index) and not is_hypothesis_end:
                continue
            if neighbor.isCity and not neighbor.discovered and not is_hypothesis_end:
                continue
            parents[neighbor.tile_index] = current
            if neighbor == end:
                path = [neighbor]
                cur = neighbor
                while parents[cur.tile_index] is not None:
                    cur = parents[cur.tile_index]
                    path.append(cur)
                return list(reversed(path))
            queue.append((neighbor, depth + 1))
    return None


def _finishing_route(
    game_map: MapBase,
    wrp_tiles: list[Tile],
    hypothesis: Tile,
    player_index: int,
    enemy_index: int,
) -> tuple[list[Tile], int] | None:
    """Prefix-to-first-reveal + restricted direct finish for one hypothesis.

    Finds the FIRST WRP tile whose 3x3 vision reaches the hypothesis
    (Chebyshev <= 1), then appends the legal finishing route. Does NOT reserve a
    full WRP-then-return; execution hands off as soon as the real general shows.
    """
    reveal_index = -1
    for i, tile in enumerate(wrp_tiles):
        if max(abs(tile.x - hypothesis.x), abs(tile.y - hypothesis.y)) <= 1:
            reveal_index = i
            break
    if reveal_index < 0:
        return None
    prefix = wrp_tiles[: reveal_index + 1]
    finish = _finish_path(game_map, prefix[-1], hypothesis, player_index, enemy_index)
    if finish is None:
        return None
    full = prefix + finish[1:]
    return full, len(full) - 1


def _build_tree(
    game_map: MapBase,
    root: Tile,
    player_index: int,
    budget: int,
    blocked: set[Tile],
) -> list[GatherTreeNode]:
    """Owned-tile BFS gather tree with city-income-aware leaf pruning.

    Exact port of the lead probe build_tree: BFS over own tiles only (own 1s are
    valid connectors), then repeatedly remove the lowest-priority leaf while the
    node count exceeds `budget`. Leaf priority = army - 1 + future city/general
    income (max(0, budget - depth)//2), tie-broken by -depth then tile_index.
    Future city prizes rank branches only; they never become certified army.
    `blocked` (defense-critical/garrison tiles) is excluded structurally so the
    gather can neither source from nor route army through a tile defense needs.
    """
    nodes: dict[int, GatherTreeNode] = {root.tile_index: GatherTreeNode(root, None)}
    tile_by_index: dict[int, Tile] = {root.tile_index: root}
    depths: dict[int, int] = {root.tile_index: 0}
    parents: dict[int, GatherTreeNode] = {}
    queue: deque[Tile] = deque([root])
    while queue:
        current = queue.popleft()
        for neighbor in _ordered_neighbors(current, player_index):
            if neighbor.player != player_index or neighbor.tile_index in nodes or neighbor in blocked:
                continue
            node = GatherTreeNode(neighbor, current)
            nodes[current.tile_index].children.append(node)
            nodes[neighbor.tile_index] = node
            tile_by_index[neighbor.tile_index] = neighbor
            parents[neighbor.tile_index] = nodes[current.tile_index]
            depths[neighbor.tile_index] = depths[current.tile_index] + 1
            queue.append(neighbor)
    while len(nodes) - 1 > budget:
        leaves = [
            node for idx, node in nodes.items()
            if idx != root.tile_index and not node.children]
        if not leaves:
            break

        def _priority(node: GatherTreeNode) -> tuple[int, int, int]:
            tile = node.tile
            future = (
                max(0, budget - depths[tile.tile_index]) // 2
                if tile.isCity or tile.isGeneral else 0)
            return tile.army - 1 + future, -depths[tile.tile_index], tile.tile_index

        chosen = min(leaves, key=_priority)
        parents[chosen.tile.tile_index].children.remove(chosen)
        del nodes[chosen.tile.tile_index]
    return [nodes[root.tile_index]]


def _illegal_forward_tiles(
    game_map: MapBase,
    player_index: int,
    enemy_index: int,
    defense_negatives: set[Tile],
) -> set[Tile]:
    """Tiles a forward gather must never path through or source from.

    Third-party land, defense-critical tiles, neutral cities, and victim tiles
    that are cities or field armies > 2 (strong enough to fight, not a free
    connector). Weak victim tiles (army <= 2, non-city) stay legal connectors.
    """
    illegal: set[Tile] = set(defense_negatives)
    for tile in game_map.tiles_by_index:
        owner = tile.player
        if owner >= 0 and owner not in (player_index, enemy_index):
            illegal.add(tile)
            continue
        if owner == -1 and tile.isCity:
            illegal.add(tile)
            continue
        if owner == enemy_index and (tile.isCity or tile.army > 2):
            illegal.add(tile)
    return illegal


@dataclass(slots=True)
class _GatherPlanSource:
    """One gather plan source tagged by variant kind for per-budget handling.

    kind == 'owned' rebuilds its city-aware _build_tree per budget (the owned
    tree's leaf pruning already scores city/general income, so a generic
    value-prune of the max-budget tree would wrongly drop high-value city
    branches). kind == 'pcst' clones+prunes the forward PCST tree per budget.
    """
    kind: str
    plan: GatherCapturePlan


def _gather_candidate_plans(
    bot: EklipZBot,
    launch_tile: Tile,
    defense_negatives: set[Tile],
    gather_budget: int,
    enemy_index: int,
    kind: str = "all",
) -> list[_GatherPlanSource]:
    """Build the requested owned/forward sources without eagerly running PCST.

    Three sources per the settled design: (a) owned BFS tree -> GCP, (b) forward
    true-value PCST with city prizes (gatherMatrix = budget/2 on own
    cities/generals), (c) same without city prizes. Each returns a full-budget
    GatherCapturePlan whose root_nodes are later cloned+pruned per smaller budget
    by _schedule_for_budget - real smaller gather-to-root plans, never prefixes.
    The enemy index is threaded explicitly - no mutable scratch state on the bot.
    """
    game_map = bot._map
    player_index = bot.player.index
    sources: list[_GatherPlanSource] = []

    if kind not in ("all", "owned", "pcst"):
        raise ValueError(f"Unknown FFA gather source kind: {kind}")
    if kind in ("all", "owned"):
        owned_roots = _build_tree(game_map, launch_tile, player_index, gather_budget, defense_negatives)
        sources.append(_GatherPlanSource('owned', GatherCapturePlan.build_from_root_nodes(
            game_map, owned_roots, defense_negatives, player_index,
            onlyCalculateFriendlyArmy=False, cloneNodes=True)))
    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
    # PCST setup must not exhaust the search budget before the owned gather pass.
    if kind == "owned" or gather_budget <= 0:
        return sources

    illegal = _illegal_forward_tiles(game_map, player_index, enemy_index, defense_negatives)
    for city_bonus in (False, True):
        prizes = MapMatrix(game_map, 0.0)
        if city_bonus:
            for tile in game_map.players[player_index].tiles:
                if tile.isCity or tile.isGeneral:
                    prizes.raw[tile.tile_index] = gather_budget / 2
        forward = gather_approximate_turns_to_tiles(
            game_map, [launch_tile], gather_budget, player_index,
            maxTurns=gather_budget, minTurns=0, skipTiles=illegal,
            negativeTiles=defense_negatives, useTrueValueGathered=True,
            includeCapturePriorityAsEconValues=False,
            gatherMatrix=prizes, timeLimit=_GATHER_TIME_LIMIT)
        if forward is not None:
            sources.append(_GatherPlanSource('pcst', forward))

    return sources


def _prune_empty_owned_leaves(nodes: list[GatherTreeNode], player_index: int) -> None:
    """Remove empty ordinary donor leaves, retaining roots and useful connectors."""
    for node in nodes:
        _prune_empty_owned_leaves(node.children, player_index)
        node.children = [
            child for child in node.children
            if child.children or child.tile.player != player_index
            or child.tile.army > 1 or child.tile.isCity or child.tile.isGeneral]


def _schedule_for_budget(
    game_map: MapBase,
    source: _GatherPlanSource,
    launch_tile: Tile,
    player_index: int,
    enemy_index: int,
    defense_negatives: set[Tile],
    budget: int,
) -> list[Move]:
    """Best literal gather order for a plan pruned to `budget` gather turns.

    budget <= 0 yields the zero-gather (empty) schedule, which must still be
    evaluated. The 'owned' source rebuilds its city-aware _build_tree at exactly
    this budget so city/general income keeps ranking branches (a generic
    value-prune of the max-budget tree would drop high-value city branches);
    'pcst' sources clone+prune_mst_to_turns the forward tree. A sub-plan is
    rebuilt and the highest-delivery order (base vs the two city_late schedules)
    is chosen by ACTUAL project_forward_gather launch army. Real, smaller
    gather-to-root plans - never a move-list prefix.
    """
    if budget <= 0:
        return []
    if source.kind == 'owned':
        nodes = _build_tree(game_map, launch_tile, player_index, budget, defense_negatives)
    else:
        nodes = GatherTreeNode.clone_nodes(source.plan.root_nodes)
        nodes = prune_mst_to_turns(nodes, budget, player_index, noLog=True)
    if not nodes:
        return []
    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
    # An owned one is a valid connector, but an empty leaf cannot donate an army.
    _prune_empty_owned_leaves(nodes, player_index)
    sub_plan = GatherCapturePlan.build_from_root_nodes(
        game_map, nodes, defense_negatives, player_index,
        onlyCalculateFriendlyArmy=False, cloneNodes=True)
    return _best_order_for_plan(sub_plan, launch_tile, player_index, enemy_index, game_map)


def _best_order_for_plan(
    plan: GatherCapturePlan,
    launch_tile: Tile,
    player_index: int,
    enemy_index: int,
    game_map: MapBase,
) -> list[Move]:
    """Return the highest-delivery literal order for one gather plan.

    Compares the plan's own move order against the two city_late schedules by
    ACTUAL project_forward_gather launch army (never a heuristic prize). The
    enemy index is an explicit parameter; nothing is stashed on the bot.
    """
    base_moves = plan.get_move_list()
    base_forecast = project_forward_gather(game_map, base_moves, launch_tile, player_index, enemy_index)
    best_moves = base_moves
    best_army = base_forecast.launch_army if base_forecast is not None else -1
    for schedule in city_late_gather_schedules(plan.root_nodes, player_index):
        forecast = project_forward_gather(game_map, schedule, launch_tile, player_index, enemy_index)
        if forecast is not None and forecast.launch_army > best_army:
            best_army = forecast.launch_army
            best_moves = schedule
    return best_moves


def build_owned_gather_schedule(
    bot: EklipZBot,
    root: Tile,
    blocked: set[Tile],
    budget: int,
    enemy_index: int,
) -> list[Move]:
    """Public owned-only gather schedule for BotGeneralSafety's reserve gather.

    Pure helper with no feature-flag check (the caller owns gating). Reuses the
    same owned-tree candidate plans and per-budget literal scheduling as the
    FFA kill gather, returning the best-order literal Move list for `budget`
    gather turns (empty when no owned plan exists at that budget).
    """
    if budget <= 0:
        return []
    sources = _gather_candidate_plans(
        bot, root, blocked, budget, enemy_index, kind="owned")
    owned = next((s for s in sources if s.kind == "owned"), None)
    if owned is None:
        return []
    return _schedule_for_budget(
        bot._map, owned, root, bot.player.index, enemy_index, blocked, budget)


def _build_restricted_map(game_map: MapBase, player_index: int, enemy_index: int) -> MapBase:
    """Clone the live map and wall off third-party land for the WRP search.

    The real owner is PRESERVED (never faked to -2). WRP and DistanceMapperImpl
    gate passability on `isObstacle`, so each third-party tile is walled by
    setting `isMountain=True` (forces isObstacle) together with
    `overridePathable=False` (forces isNotPathable/isPathable False), then
    `_recalc_derived()` so ALL cached derived flags stay consistent. The clone is
    discarded after routing; the live map is never mutated. DistanceMapper is
    rebuilt only AFTER the walls are in place.
    """
    cloned = pickle.loads(pickle.dumps(game_map, protocol=pickle.HIGHEST_PROTOCOL))
    for tile in cloned.tiles_by_index:
        owner = tile.player
        if owner >= 0 and owner not in (player_index, enemy_index):
            tile.overridePathable = False
            tile.isMountain = True
            tile._recalc_derived()
    cloned.distance_mapper = DistanceMapperImpl(cloned)
    return cloned


def _route_has_no_third_party(
    game_map: MapBase,
    player_index: int,
    enemy_index: int,
    route_tiles: list[Tile],
) -> bool:
    """True when every route tile is own / neutral / victim land (no third party)."""
    for tile in route_tiles:
        if tile.player >= 0 and tile.player not in (player_index, enemy_index):
            return False
    return True


def _route_cache_key(
    enemy_index: int,
    launch_tile_index: int,
    hypothesis_indexes: tuple[int, ...],
    topology_signature: tuple[int, ...],
) -> tuple[int, int, tuple[int, ...], tuple[int, ...]]:
    """Route cache key includes a topology signature so stale geometry can't hit."""
    return (enemy_index, launch_tile_index, hypothesis_indexes, topology_signature)


def _topology_signature(game_map: MapBase, player_index: int, enemy_index: int) -> tuple[int, ...]:
    """Cheap signature of the restricted-land topology for cache invalidation."""
    signature: list[int] = []
    for tile in game_map.tiles_by_index:
        owner = tile.player
        # Undiscovered cities are uncertain walls (_finish_path blocks them) so
        # their discovery state must participate in the signature - otherwise a
        # route cached while a city was fogged could be reused after it is seen.
        uncertain_city = tile.isCity and not tile.discovered
        passable = (owner in (-1, player_index, enemy_index)
                    and not tile.isNotPathable
                    and not uncertain_city)
        signature.append(1 if passable else 0)
    return tuple(signature)


def _route_for_hypotheses(
    bot: EklipZBot,
    cache: FfaKillGatherCache,
    launch_tile: Tile,
    enemy_index: int,
    hypotheses: list[Tile],
    initial_army: int,
    time_limit: float,
) -> list[Tile] | None:
    """Return WRP route tiles covering every hypothesis, or None (pending/none).

    Live mode submits ONE background job to the feature-owned worker and returns
    None until it completes (nonblocking). Synchronous mode (tests) runs the
    cloned-map WRP inline. Results are cached under a key that includes launch,
    the hypothesis set, AND a topology signature; a completed job is stored under
    its OWN key so a mismatched victim/root never poisons another cache entry.
    """
    game_map = bot._map
    player_index = bot.player.index
    hyp_indexes = tuple(sorted(h.tile_index for h in hypotheses))
    topo = _topology_signature(game_map, player_index, enemy_index)
    cache_key = _route_cache_key(enemy_index, launch_tile.tile_index, hyp_indexes, topo)
    if cache_key in cache.route_cache:
        cached = cache.route_cache[cache_key]
        if cached is None:
            return None
        return [game_map.tiles_by_index[i] for i in cached]

    _poll_wrp(cache)
    job = cache.pending_job
    if job is not None and not job.done:
        if not cache.wrp_worker.is_alive():
            raise RuntimeError("FFA kill-gather WRP worker exited with pending route work")
        return None
    if job is not None and job.done:
        cache.pending_job = None
        # Store under the job's OWN key; a None (failed/timed-out) result is NEVER
        # cached so it is retried rather than permanently blacklisted. A route that
        # crosses third-party land is likewise rejected, not stored.
        if job.result_tile_indexes is not None:
            job_tiles = [game_map.tiles_by_index[i] for i in job.result_tile_indexes]
            # Validate against the JOB's enemy (its restricted map walled every
            # OTHER third party), not the current query's - a p7 route stored
            # under a p7 key must not be discarded just because p1 is queried.
            if _route_has_no_third_party(game_map, player_index, job.enemy_index, job_tiles):
                cache.route_cache[job.cache_key] = job.result_tile_indexes
        if job.cache_key == cache_key:
            if job.result_tile_indexes is None:
                return None
            tiles = [game_map.tiles_by_index[i] for i in job.result_tile_indexes]
            if not _route_has_no_third_party(game_map, player_index, enemy_index, tiles):
                return None
            return tiles
        # Mismatched completed job: fall through and submit for THIS key.

    if bot.run_background_work_synchronously:
        cloned = _build_restricted_map(game_map, player_index, enemy_index)
        path = WatchmanRouteUtils.get_watchman_path(
            cloned, cloned.tiles_by_index[launch_tile.tile_index],
            [cloned.tiles_by_index[h.tile_index] for h in hypotheses],
            timeLimit=time_limit, initialArmy=initial_army)
        if path is None:
            # Failure is intentionally NOT cached - a timed-out WRP is retried.
            return None
        indexes = [t.tile_index for t in path.tileList]
        tiles = [game_map.tiles_by_index[i] for i in indexes]
        if not _route_has_no_third_party(game_map, player_index, enemy_index, tiles):
            return None
        cache.route_cache[cache_key] = indexes
        return tiles

    if cache.wrp_worker is None:
        cache.wrp_worker = WrpWorkerProcess()
    cloned = _build_restricted_map(game_map, player_index, enemy_index)
    map_payload = pickle.dumps(cloned, protocol=pickle.HIGHEST_PROTOCOL)
    cache.wrp_generation += 1
    gen = cache.wrp_generation
    cache.wrp_worker.submit(WrpRequest(
        generation=gen, map_payload=map_payload,
        start_tile_index=launch_tile.tile_index,
        target_tile_indexes=[h.tile_index for h in hypotheses],
        initial_army=initial_army, time_limit=time_limit))
    cache.pending_job = FfaKillGatherJob(
        gen, enemy_index, launch_tile.tile_index,
        [h.tile_index for h in hypotheses], cache_key, time_limit)
    return None


def _poll_wrp(cache: FfaKillGatherCache) -> None:
    """Drain the feature worker and mark the pending job done."""
    worker = cache.wrp_worker
    # Finalize an async FFA-end close requested on the move hot path: poll_close
    # is non-blocking and only completes once the daemon worker has self-exited
    # after its current ~1s job. A still-running worker keeps its reference.
    if worker is not None and worker.close_requested and worker.poll_close():
        cache.wrp_worker = None
        worker = None
    job = cache.pending_job
    if worker is None or job is None or job.done:
        return
    for result in worker.get_results_nowait():
        if result.generation == job.generation:
            job.result_tile_indexes = result.tile_indexes
            job.duration_sec = result.duration_sec
            job.done = True
            return


def _remaining_cycle_turns(bot: EklipZBot) -> int:
    """Turns left in the current 50-turn cycle."""
    return 50 - (bot._map.turn % 50)


def _launch_roots(
    bot: EklipZBot,
    hypotheses: list[Tile],
    defense_negatives: set[Tile],
    general_distances: dict[int, int],
    hypothesis_distances: list[dict[int, int]],
) -> list[Tile]:
    """Up to _MAX_LAUNCH_ROOTS own launch tiles nearest the hypothesis set.

    Uses RESTRICTED BFS distance fields (own/neutral/victim land only, no
    third-party crossing) computed once per prepare: `general_distances` is the
    field from our general and `hypothesis_distances[i]` is the field from
    hypothesis i. Ranked by sum-of-hypothesis-distances, own distance from the
    general, -army, tile_index. Own 1-tiles ARE valid launch roots: the root is
    the gather DESTINATION that receives the converging stack, so it does not
    need to hold army itself (an army>1 filter wrongly rejected them). ALL
    returned roots are evaluated by the caller - none are silently dropped.
    """
    game_map = bot._map
    player_index = bot.player.index
    candidates: list[tuple[tuple[int, int, int, int], Tile]] = []
    for tile in game_map.players[player_index].tiles:
        if tile.player != player_index or tile.army < 1:
            continue
        if tile in defense_negatives or tile.isCity or tile.isGeneral:
            continue
        own_dist = general_distances.get(tile.tile_index)
        if own_dist is None:
            continue
        hyp_sum = 0
        reachable = True
        for field in hypothesis_distances:
            d = field.get(tile.tile_index)
            if d is None:
                reachable = False
                break
            hyp_sum += d
        if not reachable:
            continue
        candidates.append(((hyp_sum, own_dist, -tile.army, tile.tile_index), tile))
    candidates.sort(key=lambda pair: pair[0])
    return [tile for _, tile in candidates[:_MAX_LAUNCH_ROOTS]]


def _certify_schedule(
    bot: EklipZBot,
    enemy_index: int,
    launch_tile: Tile,
    gather_moves: list[Move],
    scenarios: list[tuple[Tile, list[Tile], int]],
    wrp_tiles: list[Tile],
    remaining_cycle_turns: int,
) -> tuple[FfaKillGatherOption | None, FfaKillProjection | None]:
    """Certify one concrete gather schedule against ALL hypothesis scenarios.

    scenarios = (hypothesis, full_route_tiles, route_turns) per hypothesis. Every
    scenario must certify with strict positive margin; returns the option plus the
    worst-margin projection, or (None, None). `wrp_tiles` is the ORIGINAL full
    watchman route covering every hypothesis - it is stored on the option/state as
    the EXECUTION hunt route (the per-scenario prefix+finish routes are certificate
    geometry only). The option's representative move list is the literal gather
    moves followed by the worst-case scenario's hunt steps so flow sees a coherent
    plan covering the reserved window; execution never follows that representative.
    """
    game_map = bot._map
    player_index = bot.player.index
    gather_turns = len(gather_moves)

    forecast = project_forward_gather(game_map, gather_moves, launch_tile, player_index, enemy_index)
    if forecast is None:
        return None, None

    enemy = game_map.players[enemy_index]
    enemy_standing = enemy.standingArmy
    enemy_tile_count, enemy_city_count = _enemy_counts(bot, enemy_index)
    queue_sources = _ordinary_queue_sources(bot, enemy_index)
    all_ordinary = _all_ordinary_sources(bot, enemy_index)
    remaining = remaining_ordinary_sources(all_ordinary, forecast.paid_ordinary_armies)

    # Evaluate EVERY hypothesis scenario (never admit a partial candidate set).
    # Track the minimum-margin projection so a rejected schedule still reports the
    # best failed certificate for diagnostics instead of silently returning None.
    worst_route_turns = 0
    worst_projection: FfaKillProjection | None = None
    all_certified = True
    for _hypothesis, route_tiles, route_turns in scenarios:
        cost = calculate_route_cost(
            game_map, route_tiles, player_index, enemy_index,
            hypothesized_general=_hypothesis,
            gather_captured_tiles=forecast.captured_tile_indexes)
        if cost is None:
            all_certified = False
            continue
        # Only army able to reach the hypothesis before the attack lands may
        # defend it; see bounded_defensive_pool (sound Manhattan lower bound).
        bounded = bounded_defensive_pool(
            game_map, enemy_index, [_hypothesis],
            gather_turns + route_turns, enemy_standing)
        projection = certify_kill(
            start_turn=game_map.turn,
            gather_turns=gather_turns,
            route_turns=route_turns,
            launch_army=forecast.launch_army,
            route_cost=cost,
            enemy_standing=max(0, bounded - forecast.paid_enemy_standing),
            enemy_tile_count=enemy_tile_count,
            enemy_city_count=enemy_city_count,
            enemy_ordinary_armies=remaining)
        worst_route_turns = max(worst_route_turns, route_turns)
        if worst_projection is None or projection.margin < worst_projection.margin:
            worst_projection = projection
        if not projection.certified:
            all_certified = False

    total_turns = gather_turns + worst_route_turns
    if not all_certified or total_turns > remaining_cycle_turns or total_turns > 100 or worst_projection is None:
        # Return the worst-margin projection (when one exists) so the caller can
        # record the best failed certificate margin for diagnostics.
        return None, worst_projection

    # Capture reward uses ONLY the raw fog queue (never visible tiles).
    kill_value = calculate_kill_value(enemy_tile_count, enemy_city_count, queue_sources)

    # Representative move list for FLOW: literal gather moves then real hunt steps
    # along the worst-case scenario so tileSet/resources cover the attack corridor.
    # This is display/planning geometry ONLY - execution follows the full WRP.
    worst_scenario = max(scenarios, key=lambda s: s[2])
    hunt_tiles = worst_scenario[1]
    hunt_moves = _tiles_to_moves(hunt_tiles)
    moves: list[Move | None] = list(gather_moves) + list(hunt_moves)
    # Pad to reserved_turns only if the representative is shorter than the window.
    while len(moves) < total_turns:
        moves.append(None)

    option = FfaKillGatherOption(
        moves=moves, enemy_index=enemy_index, launch_tile=launch_tile,
        gather_moves=list(gather_moves), hunt_route_tiles=list(wrp_tiles),
        hunt_moves=hunt_moves, candidates=[h for h, _r, _t in scenarios],
        projection=worst_projection, kill_value=kill_value,
        gather_turns=gather_turns, route_turns=worst_route_turns,
        deadline_turn=game_map.turn + total_turns, reserved_turns=total_turns)
    return option, worst_projection


def _first_reveal_cursor(route_tiles: list[Tile], hypothesis: Tile) -> int:
    """First WRP index whose 3x3 vision reaches the hypothesis, else -1."""
    for i, tile in enumerate(route_tiles):
        if max(abs(tile.x - hypothesis.x), abs(tile.y - hypothesis.y)) <= 1:
            return i
    return -1


def _certify_composite_option(
    bot: EklipZBot,
    enemy_index: int,
    launch_tile: Tile,
    gather_moves: list[Move],
    wrp_tiles: list[Tile],
    hypotheses: list[Tile],
    enemy_standing: int,
    enemy_tile_count: int,
    enemy_city_count: int,
    queue_sources: list[int],
    all_ordinary: list[int],
    remaining_cycle_turns: int,
    defense_negatives: set[Tile],
    start_time: float,
    first_scenarios: list[FfaKillScenario],
) -> FfaKillGatherOption | None:
    """Certify a composite safe-front kill: cheap first reveal + certified regather.

    Used only when the ordinary one-wave certificate fails (some hypothesis
    cannot finish inside the current cycle). Requires EVERY hypothesis revealed
    at the earliest WRP vantage to hold a positive first-kill certificate, a
    strictly-surviving project_safe_front prefix with no general endpoint, and a
    fully certified owned-only stationary-head continuation for ALL hypotheses
    within the original <=100-turn horizon. Numerical decisions are delegated
    to the lead Math helpers; this function only wires geometry and budgets.
    Returns None on any unmet requirement (never a partial/weak plan).
    """
    game_map = bot._map
    player_index = bot.player.index
    gather_turns = len(gather_moves)

    forecast = project_forward_gather(
        game_map, gather_moves, launch_tile, player_index, enemy_index)
    if forecast is None:
        return None

    # Geometry is shared by every primary budget for this launch root.
    if not first_scenarios:
        return None

    # certify_gather_scenarios subtracts forecast.paid_ordinary_armies itself, so
    # pass the FULL all_ordinary list - pre-subtracting here would double-pay.
    # Batch first-wave projections under the full <=100 horizon so every case
    # margin is available for the conditional analysis (never a partial set).
    first_certs = certify_gather_scenarios(
        game_map, forecast, first_scenarios, player_index, enemy_index,
        enemy_standing, enemy_tile_count, enemy_city_count,
        game_map.turn + 100, enemy_ordinary_armies=all_ordinary)
    if first_certs is None:
        return None
    # If every case already certifies within the current cycle this is an
    # ordinary one-wave plan - leave it to _certify_schedule.
    if all(c.certified for c in first_certs) and all(
            c.gather_turns + c.route_turns <= remaining_cycle_turns for c in first_certs):
        return None

    # Earliest first-reveal WRP cursor across ALL hypotheses.
    reveal_indexes = [_first_reveal_cursor(wrp_tiles, h) for h in hypotheses]
    if any(idx < 0 for idx in reveal_indexes):
        return None
    safe_cursor = min(reveal_indexes)
    if safe_cursor < 1:
        return None
    first_vantage = [
        h for h, idx in zip(hypotheses, reveal_indexes) if idx <= safe_cursor]
    if not first_vantage:
        return None

    # Every hypothesis revealed at the first vantage must hold a positive
    # first-kill certificate; map projection -> hypothesis via scenario order.
    cert_by_hyp: dict[int, FfaKillProjection] = {
        s.hypothesis_index: c for s, c in zip(first_scenarios, first_certs)}
    first_kill_turns = 0
    for hypothesis in first_vantage:
        cert = cert_by_hyp.get(hypothesis.tile_index)
        if cert is None or not cert.certified:
            return None
        first_kill_turns = max(first_kill_turns, cert.gather_turns + cert.route_turns)

    # Safe-front prefix must contain no possible general endpoint and survive
    # ALL enemy standing; project_safe_front enforces both.
    prefix_tiles = wrp_tiles[: safe_cursor + 1]
    front = project_safe_front(
        game_map, forecast, prefix_tiles, player_index, enemy_index,
        enemy_standing, enemy_tile_count, enemy_city_count)
    if front is None or not front.safety.certified:
        return None

    # Materialize the certified front position ONCE for all continuation work.
    projected_map = materialize_gather_position(game_map, front.position, player_index)
    head_proj = projected_map.tiles_by_index[front.head_tile_index]

    # Complete post-front cases: original WRP suffix -> reveal -> finish, all
    # hypotheses, evaluated on the virtual map (never a partial set).
    suffix_indexes = [t.tile_index for t in wrp_tiles[safe_cursor:]]
    suffix_proj = [projected_map.tiles_by_index[i] for i in suffix_indexes]
    continuation_scenarios: list[FfaKillScenario] = []
    max_suffix_turns = 0
    for hypothesis in hypotheses:
        hyp_proj = projected_map.tiles_by_index[hypothesis.tile_index]
        case = _case_route_for_hypothesis(
            projected_map, suffix_proj, hyp_proj, player_index, enemy_index)
        if case is None:
            return None
        route_tiles, route_turns = case
        continuation_scenarios.append(FfaKillScenario(
            hypothesis_index=hypothesis.tile_index,
            route_tile_indexes=tuple(t.tile_index for t in route_tiles)))
        max_suffix_turns = max(max_suffix_turns, route_turns)
    if not continuation_scenarios:
        return None

    # Secondary owned-only gather on the stationary front head. blocked mirrors
    # defense-critical live tiles by index onto the virtual map.
    defense_indexes = {t.tile_index for t in defense_negatives}
    blocked_proj = {
        projected_map.tiles_by_index[i]
        for i in defense_indexes
        if 0 <= i < len(projected_map.tiles_by_index)}
    owned_count = sum(
        1 for t in projected_map.tiles_by_index if t.player == player_index) - 1
    front_elapsed = front.position.turn - game_map.turn
    # The secondary gather plus the worst finish must still fit the <=100
    # horizon measured from the original plan start.
    max_budget = min(
        100 - front_elapsed - max_suffix_turns, owned_count, 100)
    if max_budget < 0:
        return None

    absolute_deadline = game_map.turn + 100
    best_moves: list[Move] | None = None
    best_certs: tuple[FfaKillProjection, ...] | None = None
    best_len = 1 << 30

    def _probe(budget: int) -> tuple[list[Move], tuple[FfaKillProjection, ...]] | None:
        """Literal owned gather for `budget` + full continuation certificate."""
        if time.perf_counter() - start_time > _PREPARE_TIME_BUDGET:
            return None
        if budget <= 0:
            moves: list[Move] = []
        else:
            nodes = _build_tree(
                projected_map, head_proj, player_index, budget, blocked_proj)
            if not nodes:
                return None
            _prune_empty_owned_leaves(nodes, player_index)
            sub_plan = GatherCapturePlan.build_from_root_nodes(
                projected_map, nodes, blocked_proj, player_index,
                onlyCalculateFriendlyArmy=False, cloneNodes=True)
            moves = _best_order_for_plan(
                sub_plan, head_proj, player_index, enemy_index, projected_map)
        certs = certify_retained_head_continuation(
            projected_map, front, moves, continuation_scenarios,
            player_index, enemy_index, enemy_tile_count, enemy_city_count,
            absolute_deadline)
        if certs is None or not all(c.certified for c in certs):
            return None
        return moves, certs

    # Evaluate the max budget first; then binary-probe smaller budgets and keep
    # the shortest literally-certified schedule (approximate candidate search,
    # never a weakened certificate). Retain the best found on budget expiry.
    lo, hi = 0, max_budget
    probe_max = _probe(hi)
    if probe_max is not None:
        best_moves, best_certs = probe_max
        best_len = len(probe_max[0])
        hi = hi - 1
    # Binary search for a smaller certified budget (monotonicity NOT assumed;
    # this only brackets candidates and every accepted schedule is certified).
    while lo <= hi and time.perf_counter() - start_time <= _PREPARE_TIME_BUDGET:
        mid = (lo + hi) // 2
        result = _probe(mid)
        if result is not None and len(result[0]) < best_len:
            best_moves, best_certs = result
            best_len = len(result[0])
            hi = mid - 1
        elif result is not None:
            hi = mid - 1
        else:
            lo = mid + 1
    # Descend from the chosen budget while still certified to drop local excess.
    if best_moves is not None:
        b = best_len - 1
        while b > 0 and time.perf_counter() - start_time <= _PREPARE_TIME_BUDGET:
            result = _probe(b)
            if result is None:
                break
            best_moves, best_certs = result
            best_len = len(result[0])
            b -= 1
    if best_moves is None or best_certs is None:
        return None

    # Guaranteed horizon = worst-case all-hypothesis completion from plan start.
    worst_finish = max(c.gather_turns + c.route_turns for c in best_certs)
    guaranteed_turns = max(
        first_kill_turns, front_elapsed + worst_finish)
    if guaranteed_turns > 100:
        return None

    kill_value = calculate_kill_value(enemy_tile_count, enemy_city_count, queue_sources)

    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
    # Reserve a literal worst branch, including its finish, not padded no-ops.
    prefix_moves = _tiles_to_moves(prefix_tiles)
    reservation = min(remaining_cycle_turns, guaranteed_turns)
    worst_case = max(continuation_scenarios, key=lambda case: len(case.route_tile_indexes))
    finish_moves = _tiles_to_moves([
        projected_map.tiles_by_index[i] for i in worst_case.route_tile_indexes])
    representative: list[Move | None] = (
        list(gather_moves) + list(prefix_moves) + list(best_moves) + finish_moves)[:reservation]

    # .projection is the safe-front survival certificate; gather/route turns
    # describe the primary phase so the viewer can split firstKill/front/
    # guaranteed/reserve distinctly.
    option = FfaKillGatherOption(
        moves=representative, enemy_index=enemy_index, launch_tile=launch_tile,
        gather_moves=list(gather_moves), hunt_route_tiles=list(wrp_tiles),
        hunt_moves=list(prefix_moves) + finish_moves,
        candidates=[h for h in hypotheses],
        projection=front.safety, kill_value=kill_value,
        gather_turns=gather_turns, route_turns=safe_cursor,
        deadline_turn=game_map.turn + guaranteed_turns,
        reserved_turns=reservation,
        first_kill_turns=first_kill_turns,
        guaranteed_turns=guaranteed_turns,
        safe_front_hunt_cursor=safe_cursor,
        continuation_gather_moves=list(best_moves))
    return option


def _tiles_to_moves(tiles: list[Tile]) -> list[Move]:
    """Convert a tile route into Moves between consecutive tiles."""
    moves: list[Move] = []
    for a, b in zip(tiles, tiles[1:]):
        moves.append(Move(a, b))
    return moves


def _option_rank(option: FfaKillGatherOption) -> tuple[float, float, int, int, int]:
    """Lead-authored ranking: aggressive earliest-first-vantage under <=100t safety.

    ratio uses first_kill_turns (not the full guaranteed horizon) so a cheap
    conditional 34t first-kill outranks a conservative 40t one-wave option even
    though its reserved flow duration is the larger guaranteed window.
    """
    ratio = option.kill_value.total / max(1, option.first_kill_turns)
    return (-ratio, -option.kill_value.total, option.first_kill_turns, option.enemy_index, option.launch_tile.tile_index)


def prepare_options(bot: EklipZBot, defense_negatives: set[Tile]) -> list[FfaKillGatherOption]:
    """Return at most one certified FFA kill-gather option for flow expansion.

    Runs the full eligibility + candidate + gather + certify pipeline under a
    hard time budget. Returns [] when the gate is off, the game is not a >2-team
    FFA, no victim is eligible, a WRP job is pending, or nothing certifies.
    Diagnostics for every A+B-eligible victim are recorded on the cache.

    The active gate runs BEFORE any bot-field access: with FFA_KILL_GATHER_ENABLED
    False it short-circuits inside _is_ffa_kill_gather_active without touching
    _map/_ffa_kill_gather_cache, so lightweight/mock bots and non-FFA games are
    completely unaffected (UnitTests.test_BotExpansionOps regression guard).
    """
    if not _is_ffa_kill_gather_active(bot):
        return []
    cache = bot._ffa_kill_gather_cache
    game_map = bot._map
    # Never search for a NEW kill plan while one is already committed/executing;
    # the committed schedule owns the move stream until it finishes or aborts.
    if bot.ffa_kill_gather_state is not None:
        return []
    if game_map.turn < 30:
        return []
    # Forecasts assume normal growth only; skip unusual growth/city-state maps.
    if game_map.has_city_state or game_map.swamps or game_map.deserts:
        return []
    # Same-turn cache hit returns BEFORE clearing candidate diagnostics so a
    # second prepare call this turn cannot wipe the stats that were just recorded.
    if cache.last_prepare_turn == game_map.turn:
        return [cache.option_cache] if cache.option_cache is not None else []
    cache.candidates = {}
    cache.best_failed = None

    start_time = time.perf_counter()
    remaining_cycle_turns = _remaining_cycle_turns(bot)
    best: FfaKillGatherOption | None = None
    best_diag: FfaKillGatherCandidate | None = None

    for enemy_index in range(len(game_map.players)):
        if time.perf_counter() - start_time > _PREPARE_TIME_BUDGET:
            break
        eligible, reason = _enemy_is_eligible(bot, enemy_index)
        diag = FfaKillGatherCandidate(enemy_index)
        diag.eligible = eligible
        diag.reject_reason = reason
        cache.candidates[enemy_index] = diag
        # Only A+B-eligible victims get a logbook line; unqualified enemies are
        # silently skipped so an FFA board cannot spam per-enemy diagnostics.
        if eligible:
            _vinfo(
                bot,
                f"FFA Kill Gather ELIGIBLE turn={game_map.turn} enemy=p{enemy_index} "
                f"ourStanding={bot.player.standingArmy} ourEcon={_econ_value(bot.player)} "
                f"enemyStanding={game_map.players[enemy_index].standingArmy} "
                f"enemyEcon={_econ_value(game_map.players[enemy_index])} "
                f"lock={bot.ffa_exclusive_target_lock}")
        if not eligible:
            continue
        enemy = game_map.players[enemy_index]
        diag.standing_army = enemy.standingArmy
        diag.econ_value = _econ_value(enemy)
        queue_sources = _ordinary_queue_sources(bot, enemy_index)
        diag.queue_armies = list(queue_sources)

        hypotheses = _general_hypotheses(bot, enemy_index)
        if hypotheses is None:
            diag.reject_reason = "too_many_hypotheses"
            continue
        diag.hypothesis_count = len(hypotheses)
        if not hypotheses:
            diag.reject_reason = "no_hypotheses"
            continue

        # Restricted reachability: BFS fields over own/neutral/victim land only.
        # general_distances proves every hypothesis is <= _MAX_REACH_TURNS from
        # our general; hypothesis_distances ranks launch roots by true restricted
        # distance to each hypothesis (no third-party crossing priced in).
        blocked = set(defense_negatives)
        hypothesis_endpoint_indexes = {h.tile_index for h in hypotheses}
        general_distances = _restricted_distances(
            game_map, bot.general, bot.player.index, enemy_index, blocked,
            allowed_endpoint_indexes=hypothesis_endpoint_indexes)
        if not _reachable_within(general_distances, hypotheses, _MAX_REACH_TURNS):
            diag.reject_reason = "hypothesis_too_far"
            continue
        hypothesis_distances = [
            _restricted_distances(game_map, h, bot.player.index, enemy_index, blocked)
            for h in hypotheses]

        roots = _launch_roots(
            bot, hypotheses, defense_negatives, general_distances, hypothesis_distances)
        diag.launch_roots = len(roots)
        if not roots:
            diag.reject_reason = "no_launch_roots"
            continue

        enemy_standing = enemy.standingArmy
        initial_army = sum(t.army for t in bot.player.tiles)

        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
        # A launch near the enemy can have a very long owned gather approach.
        # Try source-accessible roots first, before spending time on forward PCST.
        owned_distances: dict[int, int] = {bot.general.tile_index: 0}
        pending_owned: deque[Tile] = deque([bot.general])
        while pending_owned:
            current = pending_owned.popleft()
            for neighbor in current.movable:
                if (neighbor.player != bot.player.index or neighbor in defense_negatives
                        or neighbor.tile_index in owned_distances):
                    continue
                owned_distances[neighbor.tile_index] = owned_distances[current.tile_index] + 1
                pending_owned.append(neighbor)
        owned_roots = sorted(roots, key=lambda tile: (
            owned_distances.get(tile.tile_index, 1 << 30),
            sum(field.get(tile.tile_index, 1 << 30) for field in hypothesis_distances),
            tile.tile_index))
        enemy_tile_count, enemy_city_count = _enemy_counts(bot, enemy_index)
        all_ordinary = _all_ordinary_sources(bot, enemy_index)
        roots_completed = 0
        for kind in ("owned", "pcst"):
            pass_roots = owned_roots if kind == "owned" else roots
            start_idx = cache.root_cursor % len(pass_roots)
            ordered_roots = pass_roots[start_idx:] + pass_roots[:start_idx]
            for launch in ordered_roots:
                if time.perf_counter() - start_time > _PREPARE_TIME_BUDGET:
                    if not diag.certified:
                        diag.reject_reason = "pending_budget"
                    break
                wrp_tiles = _route_for_hypotheses(
                    bot, cache, launch, enemy_index, hypotheses,
                    initial_army=max(1, initial_army),
                    time_limit=_WRP_SYNC_TIME_LIMIT if bot.run_background_work_synchronously else _WRP_LIVE_TIME_LIMIT)
                if wrp_tiles is None:
                    diag.reject_reason = "wrp_pending_or_none"
                    continue
                roots_completed += 1
                scenarios: list[tuple[Tile, list[Tile], int]] = []
                for hypothesis in hypotheses:
                    finish = _finishing_route(game_map, wrp_tiles, hypothesis, bot.player.index, enemy_index)
                    if finish is None:
                        break
                    route_tiles, route_turns = finish
                    scenarios.append((hypothesis, route_tiles, route_turns))
                if len(scenarios) != len(hypotheses):
                    diag.reject_reason = "no_finish_route"
                    continue
                first_scenarios = [
                    FfaKillScenario(h.tile_index, tuple(tile.tile_index for tile in route_tiles))
                    for h, route_tiles, _turns in scenarios]
                max_route_turns = max(s[2] for s in scenarios)
                gather_budget = max(0, min(
                    remaining_cycle_turns - max_route_turns, 100 - max_route_turns))
                seen_orders: set[tuple[tuple[int, int, bool], ...]] = set()
                for source in _gather_candidate_plans(
                        bot, launch, defense_negatives, gather_budget, enemy_index, kind):
                    # Real smaller gathers, not prefixes of a maximal schedule.
                    for budget in range(gather_budget + 1):
                        if time.perf_counter() - start_time > _PREPARE_TIME_BUDGET:
                            if not diag.certified:
                                diag.reject_reason = "pending_budget"
                            break
                        gather_moves = _schedule_for_budget(
                            game_map, source, launch, bot.player.index,
                            enemy_index, defense_negatives, budget)
                        order_key = tuple(
                            (m.source.tile_index, m.dest.tile_index, m.move_half)
                            for m in gather_moves)
                        if order_key in seen_orders:
                            continue
                        seen_orders.add(order_key)
                        option, projection = _certify_schedule(
                            bot, enemy_index, launch, gather_moves, scenarios,
                            wrp_tiles, remaining_cycle_turns)
                        if projection is not None and (
                                not diag.saw_projection or projection.margin > diag.margin):
                            diag.saw_projection = True
                            diag.margin = projection.margin
                            diag.launch_army = projection.launch_army
                            diag.route_cost = projection.route_cost
                            diag.enemy_defense = projection.defender_army
                            diag.gather_turns = projection.gather_turns
                            diag.route_turns = projection.route_turns
                        composite = _certify_composite_option(
                            bot, enemy_index, launch, gather_moves, wrp_tiles,
                            hypotheses, enemy_standing, enemy_tile_count, enemy_city_count,
                            queue_sources, all_ordinary, remaining_cycle_turns,
                            defense_negatives, start_time, first_scenarios)
                        if composite is not None and (
                                option is None or _option_rank(composite) < _option_rank(option)):
                            option = composite
                        if option is None:
                            continue
                        projection = option.projection
                        diag.gather_turns = option.gather_turns
                        diag.route_turns = option.route_turns
                        diag.launch_army = projection.launch_army
                        diag.route_cost = projection.route_cost
                        diag.enemy_defense = projection.defender_army
                        diag.margin = projection.margin
                        diag.value_total = option.kill_value.total
                        diag.certified = True
                        diag.reject_reason = ""
                        if best is None or _option_rank(option) < _option_rank(best):
                            best = option
                            best_diag = diag
                        break

        # Advance the round-robin root cursor past the roots that completed a
        # route+gather evaluation so deferred roots lead the next prepare call.
        if roots_completed > 0:
            cache.root_cursor = (cache.root_cursor + roots_completed) % len(roots)
        if best is not None and best.enemy_index == enemy_index:
            break  # already have a certified option for the best-ranked victim so far

    # One detailed completion line per ELIGIBLE candidate (never for unqualified
    # enemies), emitted after the whole enemy pass so early rejects are covered.
    for diag in cache.candidates.values():
        if not diag.eligible:
            continue
        _vinfo(
            bot,
            f"FFA Kill Gather ENEMY-DONE turn={game_map.turn} enemy=p{diag.enemy_index} "
            f"reason={diag.reject_reason or '-'} hypotheses={diag.hypothesis_count} "
            f"roots={diag.launch_roots} certified={diag.certified} "
            f"margin={diag.margin} gather={diag.gather_turns} route={diag.route_turns} "
            f"launch={diag.launch_army} defense={diag.enemy_defense} value={diag.value_total:.0f}")
        # Required main-info fields for an eligible completed candidate.
        bot.info(
            f"FFA Kill Gather p{diag.enemy_index} {diag.reject_reason or 'certified' if not diag.certified else 'certified'} "
            f"margin={diag.margin} gather={diag.gather_turns}t route={diag.route_turns}t "
            f"launch={diag.launch_army} cost={diag.route_cost} defense={diag.enemy_defense} "
            f"value={diag.value_total:.0f} hyp={diag.hypothesis_count} roots={diag.launch_roots}")

    cache.last_prepare_turn = game_map.turn
    cache.option_cache = best
    if best is not None:
        # 'chosen' is set ONLY in process_selected_plan when flow actually selects
        # the option; offering it here must not mark it chosen.
        cache.best_failed = None
    else:
        # Retain the eligible candidate with the best (highest) failed margin that
        # actually produced a certificate projection - never just the first index.
        projected = [d for d in cache.candidates.values() if d.eligible and d.saw_projection]
        if projected:
            cache.best_failed = max(projected, key=lambda d: d.margin)
        else:
            eligible_diags = [d for d in cache.candidates.values() if d.eligible]
            cache.best_failed = eligible_diags[0] if eligible_diags else None
    return [best] if best is not None else []


def process_selected_plan(bot: EklipZBot, expansion_plan: ExpansionPotential) -> None:
    """Commit the FFA kill-gather option chosen by the FINAL expansion plan.

    Called on the constructed ExpansionPotential AFTER selected_option/all_paths
    are formed and all legitimate plan filtering has run. A plan 'chooses' the
    option when it appears in all_paths (the cycle's selected set); we then
    promote it to selected_option and commit THIS turn so same-turn execution
    follows. Only flow-selected options commit - an offered-but-unchosen option
    never does.
    """
    if not _is_ffa_kill_gather_active(bot) or bot.ffa_kill_gather_state is not None:
        return
    chosen: FfaKillGatherOption | None = None
    selected = expansion_plan.selected_option
    if isinstance(selected, FfaKillGatherOption):
        chosen = selected
    else:
        for path in expansion_plan.all_paths:
            if isinstance(path, FfaKillGatherOption):
                chosen = path
                break
    if chosen is None:
        return
    if selected is not chosen:
        expansion_plan.selected_option = chosen
    _commit_option(bot, chosen)


def _commit_option(bot: EklipZBot, option: FfaKillGatherOption) -> None:
    """Build committed execution state from a selected option."""
    game_map = bot._map
    had_lock = bot.ffa_exclusive_target_lock == option.enemy_index
    bot.ffa_kill_gather_state = FfaKillGatherState(
        enemy_index=option.enemy_index,
        launch_tile_index=option.launch_tile.tile_index,
        gather_moves=list(option.gather_moves),
        hunt_route_tile_indexes=[t.tile_index for t in option.hunt_route_tiles],
        candidates=[t.tile_index for t in option.candidates],
        created_turn=game_map.turn,
        deadline_turn=option.deadline_turn,
        kill_value_total=option.kill_value.total,
        projection_margin=option.projection.margin,
        owns_exclusive_lock=not had_lock)
    state = bot.ffa_kill_gather_state
    state.safe_front_hunt_cursor = option.safe_front_hunt_cursor
    state.continuation_gather_moves = list(option.continuation_gather_moves)
    state.spans_cycles = option.guaranteed_turns > _remaining_cycle_turns(bot)
    if not had_lock:
        bot.ffa_exclusive_target_lock = option.enemy_index
    # Mark the diagnostic candidate chosen ONLY now that flow has actually
    # selected the option (offering it earlier must never set this flag).
    diag = bot._ffa_kill_gather_cache.candidates.get(option.enemy_index)
    if diag is not None:
        diag.chosen = True
    _vinfo(
        bot,
        f"FFA Kill Gather COMMIT turn={game_map.turn} enemy=p{option.enemy_index} "
        f"launch={option.launch_tile} gatherMoves={len(option.gather_moves)} "
        f"routeTurns={option.route_turns} margin={option.projection.margin} "
        f"value={option.kill_value.total} deadline={option.deadline_turn}")
    bot.info(
        f"FFA Kill Gather committed p{option.enemy_index} "
        f"gather={len(option.gather_moves)}t route={option.route_turns}t "
        f"margin={option.projection.margin} value={option.kill_value.total}")
    # Post-commit selection stats under EXP AVAIL (process_selected_plan runs
    # after the EXP AVAIL line is emitted, so this lands below it in the viewer).
    bot.viewInfo.add_stats_line(
        f"FFA Kill Gather CHOSEN p{option.enemy_index} "
        f"gather={len(option.gather_moves)}t route={option.route_turns}t "
        f"margin={option.projection.margin} value={option.kill_value.total:.0f} "
        f"hyp={len(option.candidates)} deadline={option.deadline_turn}")


def _move_key(move: Move) -> str:
    """Stable key (source>dest:half) for reconciling offered vs executed moves."""
    return f"{move.source.tile_index}>{move.dest.tile_index}:{int(move.move_half)}"


def note_final_move(bot: EklipZBot, move: Move | None) -> None:
    """Consume the pending kill-gather offer iff the bot actually executed it.

    Called once per select_move with the REAL returned move (post split-hint and
    holding-clear). The schedule cursor advances ONLY on a confirmed match
    (source+dest+half, with half-tolerance for a legitimate threat-block split);
    a defense preemption, pass, or unrelated move leaves the cursor untouched so
    the same step is re-offered next non-defense turn. Offers are never popped
    speculatively - consumption happens here, on confirmed execution. Flag-off
    and no-commit are both zero-cost no-ops.
    """
    if not FFA_KILL_GATHER_ENABLED:
        return
    state = bot.ffa_kill_gather_state
    if state is None:
        return
    if state.pending_offered_turn >= 0:
        if move is not None and state.pending_offered_turn == bot._map.turn:
            last_key = _move_key(move)
            if last_key == state.pending_offered_key:
                _consume_offered(bot, state, move)
                return
            # Half-tolerance: same endpoints means the step executed but was
            # halved by the threat-block split hint; consume to avoid an
            # infinite re-offer loop.
            offered_base = state.pending_offered_key.rsplit(":", 1)[0]
            last_base = f"{move.source.tile_index}>{move.dest.tile_index}"
            if last_base == offered_base:
                _vinfo(
                    bot,
                    f"FFA Kill Gather reconcile half-mismatch turn={bot._map.turn} "
                    f"offered={state.pending_offered_key} executed={last_key}")
                _consume_offered(bot, state, move)
                return
        # Stale offer, a pass/hold, or a different move entirely: the offer did
        # not execute; leave the cursor, clear the pending, and fall through to
        # resync for an unoffered identical execution.
        state.pending_offered_turn = -1
        state.pending_offered_key = ""
        state.pending_offered_dest_index = -1
    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible_vs_defender34:
    # A defense branch preempted the committed return but still executed the exact
    # next scheduled step (the hunt step onto the threat saveTile). Resync the
    # schedule to the executed step or the head/cursor desync aborts next turn.
    if move is not None and _matches_next_step(state, move):
        _vinfo(
            bot,
            f"FFA Kill Gather resync turn={bot._map.turn} "
            f"phase={state.phase} executed={_move_key(move)}")
        _consume_offered(bot, state, move)


def _matches_next_step(state: FfaKillGatherState, move: Move) -> bool:
    """True when move executes the immediate next scheduled step, offer or not.

    Gather compares against gather_moves[cursor] (forecast-tile indexes are map-
    independent); hunt compares against head -> hunt_route[hunt_cursor+1]. Finish
    is excluded (its path is recomputed per turn, so an unoffered lookalike is
    ambiguous).
    """
    if state.phase == "gather" and state.gather_cursor < len(state.gather_moves):
        scheduled = state.gather_moves[state.gather_cursor]
        return (move.source.tile_index == scheduled.source.tile_index
                and move.dest.tile_index == scheduled.dest.tile_index)
    if state.phase == "hunt" and state.hunt_cursor + 1 < len(state.hunt_route_tile_indexes):
        return (move.source.tile_index == state.head_tile_index
                and move.dest.tile_index == state.hunt_route_tile_indexes[state.hunt_cursor + 1])
    return False


def _consume_offered(bot: EklipZBot, state: FfaKillGatherState, move: Move) -> None:
    """Advance the schedule cursor and head for a confirmed executed move."""
    # Snapshot the PRE-consume instruction + the map turn it was decided on. The
    # live move is applied asynchronously AFTER select_move returns while
    # save_txtmap serializes the still-pre-move board, so save_state uses this
    # preimage to emit the cursor/head/phase that still points at the step the
    # serialized (pre-move) map expects - keeping resume recertification aligned.
    state.last_consumed_turn = bot._map.turn
    state.pre_consume_gather_cursor = state.gather_cursor
    state.pre_consume_hunt_cursor = state.hunt_cursor
    state.pre_consume_head_tile_index = state.head_tile_index
    state.pre_consume_phase = state.phase
    if state.phase == "gather":
        state.gather_cursor += 1
    elif state.phase == "hunt":
        state.hunt_cursor += 1
    if state.phase in ("hunt", "finish"):
        # The attack-stack head is wherever the last confirmed step landed.
        state.head_tile_index = move.dest.tile_index
    elif state.phase == "slam":
        # Tests/test_FFA.py defender20/34: a slam only advances the head when
        # the step actually captured on the pre-move board; a losing attrition
        # slam leaves the head stack at its source with one army behind.
        state.head_tile_index = (
            move.dest.tile_index
            if move.source.army - 1 > move.dest.army
            else move.source.tile_index)
    state.pending_offered_key = ""
    state.pending_offered_turn = -1
    state.pending_offered_dest_index = -1


def _offer(bot: EklipZBot, state: FfaKillGatherState, move: Move, phase: str) -> FfaKillGatherCommittedMove:
    """Record the offer (with dest for head tracking) WITHOUT consuming schedule."""
    state.phase = phase
    state.pending_offered_key = _move_key(move)
    state.pending_offered_turn = bot._map.turn
    state.pending_offered_half = move.move_half
    state.pending_offered_dest_index = move.dest.tile_index
    return FfaKillGatherCommittedMove(True, move, phase)


def _known_general_tile(bot: EklipZBot, enemy_index: int) -> Tile | None:
    """Return the victim's confirmed general tile if it is currently known."""
    enemy = bot._map.players[enemy_index]
    gen = enemy.general
    if gen is not None and gen.isGeneral and gen.player == enemy_index:
        return gen
    return None


def _current_hypotheses(
    bot: EklipZBot,
    state: FfaKillGatherState,
    known_gen: Tile | None,
) -> list[Tile] | None:
    """Currently-valid general hypotheses for remaining-plan recertification.

    A confirmed real general makes every inferred candidate irrelevant, so only
    [known_gen] is returned. Otherwise the hypothesis union is filtered to drop
    any tile now VISIBLE and confirmed NOT to be the victim's general (a newly
    revealed non-general or third-party tile can no longer be the hiding spot).
    Returns None when the surviving set is too uncertain to certify (>64).
    """
    if known_gen is not None:
        return [known_gen]
    hypotheses = _general_hypotheses(bot, state.enemy_index)
    if hypotheses is None:
        return None
    enemy_index = state.enemy_index
    return [
        h for h in hypotheses
        if not (h.visible and not (h.isGeneral and h.player == enemy_index))]


def _case_route_for_hypothesis(
    game_map: MapBase,
    suffix_tiles: list[Tile],
    hypothesis: Tile,
    player_index: int,
    enemy_index: int,
) -> tuple[list[Tile], int] | None:
    """Remaining WRP-sweep route covering one hypothesis, or None if uncoverable.

    Finds the FIRST suffix tile whose 3x3 vision reaches the hypothesis
    (Chebyshev <= 1), then appends the restricted direct finish - the same
    prefix-to-first-reveal + finish geometry used at certification time. The
    route always starts on the stored WRP (suffix_tiles[0] is the current head),
    so execution can follow it via the hunt cursor. A hypothesis whose reveal
    point is no longer reachable in the suffix cannot be certified -> None.
    """
    reveal_index = -1
    for i, tile in enumerate(suffix_tiles):
        if max(abs(tile.x - hypothesis.x), abs(tile.y - hypothesis.y)) <= 1:
            reveal_index = i
            break
    if reveal_index < 0:
        return None
    prefix = suffix_tiles[: reveal_index + 1]
    finish = _finish_path(game_map, prefix[-1], hypothesis, player_index, enemy_index)
    if finish is None:
        return None
    full = prefix + finish[1:]
    return full, len(full) - 1


def _composite_continuation_scenarios(
    projected_map: MapBase,
    safe_cursor: int,
    route_indexes: list[int],
    hypotheses: list[Tile],
    player_index: int,
    enemy_index: int,
) -> list[FfaKillScenario] | None:
    """Complete post-front WRP-suffix cases for every current hypothesis."""
    suffix_proj = [
        projected_map.tiles_by_index[i]
        for i in route_indexes[safe_cursor:]]
    scenarios: list[FfaKillScenario] = []
    for hypothesis in hypotheses:
        hyp_proj = projected_map.tiles_by_index[hypothesis.tile_index]
        case = _case_route_for_hypothesis(
            projected_map, suffix_proj, hyp_proj, player_index, enemy_index)
        if case is None:
            return None
        route_tiles, _route_turns = case
        scenarios.append(FfaKillScenario(
            hypothesis_index=hypothesis.tile_index,
            route_tile_indexes=tuple(t.tile_index for t in route_tiles)))
    return scenarios if scenarios else None


def _recertify_composite_primary(
    bot: EklipZBot,
    state: FfaKillGatherState,
    known_gen: Tile | None,
    hypotheses: list[Tile],
    enemy_standing: int,
    enemy_tile_count: int,
    enemy_city_count: int,
    all_ordinary: list[int],
) -> str:
    """Recertify a composite safe-front plan's remaining primary wave.

    Reconstructs the certified front on the CURRENT map: remaining primary
    gather (or empty from the actual hunt head) projected through the stored
    WRP prefix up to safe_front_hunt_cursor via project_safe_front, materialized
    once, then the STORED continuation gather + complete current-case suffix
    finishes certified under the ORIGINAL absolute deadline. A confirmed general
    gets an immediate certified direct finish; an unmet certificate aborts
    explicitly - never a relaxed or fabricated backup.
    """
    game_map = bot._map
    player_index = bot.player.index
    enemy_index = state.enemy_index
    safe_cursor = state.safe_front_hunt_cursor
    route_indexes = state.hunt_route_tile_indexes
    head = game_map.tiles_by_index[state.head_tile_index]
    launch = game_map.tiles_by_index[state.launch_tile_index]

    if game_map.turn > state.deadline_turn and _slam_capable(bot, state) is None:
        _abort(bot, "deadline_passed")
        return "abort"

    # Confirmed general: immediate certified direct finish from the ACTUAL head;
    # otherwise keep the safe plan (never force a weak finish).
    if known_gen is not None:
        head_forecast = project_forward_gather(
            game_map, [], head, player_index, enemy_index)
        finish = _finish_path(game_map, head, known_gen, player_index, enemy_index)
        if head_forecast is not None and finish is not None and len(finish) >= 2:
            remaining_sources = remaining_ordinary_sources(
                all_ordinary, head_forecast.paid_ordinary_armies)
            finish_scen = [FfaKillScenario(
                hypothesis_index=known_gen.tile_index,
                route_tile_indexes=tuple(t.tile_index for t in finish))]
            finish_certs = certify_gather_scenarios(
                game_map, head_forecast, finish_scen, player_index, enemy_index,
                enemy_standing, enemy_tile_count, enemy_city_count,
                state.deadline_turn, enemy_ordinary_armies=remaining_sources)
            # Tests/test_FFA.py defender20/34: the abort leaves a 10%-of-launch
            # buffer against the fog assumption (fog_buffered_certified).
            if finish_certs is not None and all(
                    fog_buffered_certified(c) for c in finish_certs):
                return "finish"
            _vinfo(bot, 
                f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                f"stage=safe_finish_cert head={head.tile_index}/{head.army} "
                f"knownGen={known_gen.tile_index} standing={enemy_standing} "
                f"fcTurn={head_forecast.position.turn} "
                f"fcLaunch={head_forecast.launch_tile_index} "
                f"finish={[t.tile_index for t in finish]} "
                f"deadline={state.deadline_turn} certificates={finish_certs}")
            # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_
            # fast_as_possible_vs_defender20/34: an uncertified finish does NOT
            # release a committed FFA kill while the economy lead holds - the
            # slam handler keeps grinding the confirmed general wave after wave.
            if _econ_ahead(bot, enemy_index):
                return "slam"

    # Reconstruct forecast + remaining prefix route for the current phase.
    if state.gather_cursor < len(state.gather_moves):
        forecast = project_forward_gather(
            game_map, state.gather_moves[state.gather_cursor:], launch,
            player_index, enemy_index)
        prefix_route = [
            game_map.tiles_by_index[i] for i in route_indexes[: safe_cursor + 1]]
        next_mode = "gather"
    elif state.hunt_cursor < safe_cursor:
        forecast = project_forward_gather(
            game_map, [], head, player_index, enemy_index)
        prefix_route = [
            game_map.tiles_by_index[i]
            for i in route_indexes[state.hunt_cursor: safe_cursor + 1]]
        next_mode = "hunt"
    else:
        # At the certified safe head with no immediate known-gen kill: require a
        # FRESH full continuation certificate on the current map, then switch to
        # the stored secondary gather (same lock/deadline, no replan gap).
        head_forecast = project_forward_gather(
            game_map, [], head, player_index, enemy_index)
        if head_forecast is None:
            _vinfo(bot, 
                f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                f"stage=safe_head_forecast head={head.tile_index} "
                f"army={head.army} safeCursor={safe_cursor}")
            _abort(bot, "recert_failed")
            return "abort"
        projected_map = materialize_gather_position(
            game_map, head_forecast.position, player_index)
        head_proj = projected_map.tiles_by_index[head.tile_index]
        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible_vs_defender34:
        # a resynced/executed head may sit PAST safe_cursor; rooting the suffix
        # at the stale cursor produced scenarios starting one tile behind the
        # head (indexes[0] != launch) which always structurally rejected.
        scenarios = _composite_continuation_scenarios(
            projected_map, state.hunt_cursor, route_indexes, hypotheses,
            player_index, enemy_index)
        forecast2 = project_forward_gather(
            projected_map, state.continuation_gather_moves, head_proj,
            player_index, enemy_index)
        if scenarios is None or forecast2 is None:
            _vinfo(bot, 
                f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                f"stage=safe_continuation_inputs scenarios={scenarios is not None} "
                f"forecast={forecast2 is not None} head={head.tile_index} "
                f"safeCursor={safe_cursor} backupTurns={len(state.continuation_gather_moves)} "
                f"hypotheses={[h.tile_index for h in hypotheses]}")
            _abort(bot, "recert_failed")
            return "abort"
        certs = certify_gather_scenarios(
            projected_map, forecast2, scenarios, player_index, enemy_index,
            enemy_standing, enemy_tile_count, enemy_city_count,
            state.deadline_turn, enemy_ordinary_armies=None)
        # Tests/test_FFA.py defender20/34: buffered margin (10% of launch) on
        # the abort gate, matching the ordinary recert path.
        if certs is None or not all(fog_buffered_certified(c) for c in certs):
            _vinfo(bot, 
                f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                f"stage=safe_continuation_cert head={head.tile_index}/{head.army} "
                f"backupTurns={len(state.continuation_gather_moves)} "
                f"deadline={state.deadline_turn} standing={enemy_standing} "
                f"hypotheses={[h.tile_index for h in hypotheses]} certificates={certs} "
                f"projTurn={projected_map.turn} fcTurn={forecast2.position.turn} "
                f"fcLaunch={forecast2.launch_tile_index} "
                f"scenarios={[(s.hypothesis_index, s.route_tile_indexes[0], s.route_tile_indexes[-1], len(s.route_tile_indexes)) for s in scenarios]}")
            _abort(bot, "recert_failed")
            return "abort"
        # Transition: stored secondary gather to the stationary safe head, hunt
        # becomes the original WRP suffix from that head. Deadline/lock/spans
        # persist; safe cursor + continuation are consumed.
        state.gather_moves = list(state.continuation_gather_moves)
        state.gather_cursor = 0
        state.launch_tile_index = head.tile_index
        state.hunt_route_tile_indexes = list(route_indexes[safe_cursor:])
        state.hunt_cursor = 0
        state.phase = "gather" if state.gather_moves else "hunt"
        state.safe_front_hunt_cursor = -1
        state.continuation_gather_moves = []
        _vinfo(bot, 
            f"FFA Kill Gather SAFE-FRONT transition turn={game_map.turn} "
            f"enemy=p{enemy_index} head={head.tile_index} "
            f"secondaryGather={len(state.gather_moves)}")
        return state.phase

    if forecast is None:
        _vinfo(bot, 
            f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} stage=primary_forecast "
            f"cursor={state.gather_cursor} head={head.tile_index}/{head.army} "
            f"standing={enemy_standing}")
        _abort(bot, "recert_failed")
        return "abort"
    front = project_safe_front(
        game_map, forecast, prefix_route, player_index, enemy_index,
        enemy_standing, enemy_tile_count, enemy_city_count)
    # Tests/test_FFA.py defender20/34: buffered margin (10% of launch) on the
    # safe-front abort gate, matching the other recert certificate gates.
    if front is None or not fog_buffered_certified(front.safety):
        _vinfo(bot, 
            f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} stage=safe_front "
            f"cursor={state.gather_cursor} hunt={state.hunt_cursor} "
            f"head={head.tile_index}/{head.army} standing={enemy_standing} "
            f"forecastArmy={forecast.launch_army} forecastTurn={forecast.position.turn} "
            f"front={front.safety if front is not None else None} "
            f"prefix={[(t.tile_index, t.player, t.army, t.isCity, t.isGeneral, t.discovered) for t in prefix_route]}")
        _abort(bot, "recert_failed")
        return "abort"
    projected_map = materialize_gather_position(
        game_map, front.position, player_index)
    scenarios = _composite_continuation_scenarios(
        projected_map, safe_cursor, route_indexes, hypotheses,
        player_index, enemy_index)
    if scenarios is None:
        _vinfo(bot, 
            f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} stage=continuation_geometry "
            f"hypotheses={[h.tile_index for h in hypotheses]} route={route_indexes}")
        _abort(bot, "recert_failed")
        return "abort"
    certs = certify_retained_head_continuation(
        projected_map, front, state.continuation_gather_moves, scenarios,
        player_index, enemy_index, enemy_tile_count, enemy_city_count,
        state.deadline_turn)
    # Tests/test_FFA.py defender20/34: buffered margin (10% of launch) on the
    # abort gate, matching the ordinary recert path.
    if certs is None or not all(fog_buffered_certified(c) for c in certs):
        bad_moves = [
            (m.source.tile_index, m.dest.tile_index)
            for m in state.continuation_gather_moves
            if (m.source.tile_index == front.head_tile_index
                or projected_map.tiles_by_index[m.source.tile_index].player != player_index
                or projected_map.tiles_by_index[m.dest.tile_index].player != player_index)]
        _vinfo(bot, 
            f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} stage=continuation_certificate "
            f"cursor={state.gather_cursor} hunt={state.hunt_cursor} "
            f"head={head.tile_index}/{head.army} standing={enemy_standing} "
            f"frontArmy={front.position.armies[front.head_tile_index]} "
            f"frontStanding={front.enemy_standing} frontTurn={front.position.turn} "
            f"backupTurns={len(state.continuation_gather_moves)} deadline={state.deadline_turn} "
            f"hypotheses={[h.tile_index for h in hypotheses]} certificates={certs} "
            f"badMoves={bad_moves} "
            f"scenarios={[(s.hypothesis_index, s.route_tile_indexes[0], s.route_tile_indexes[-1], len(s.route_tile_indexes)) for s in scenarios]}")
        _abort(bot, "recert_failed")
        return "abort"
    return next_mode


def _recertify_remaining(bot: EklipZBot, state: FfaKillGatherState) -> str:
    """Recertify the ENTIRE remaining committed plan on the current map.

    Mandatory before every offered move (all defense gates already had priority).
    Uses the SAME lead forecast/certify pipeline as initial certification:
      - gather remaining: project gather_moves[cursor:] to launch, case routes
        derived from the original full WRP for currently-valid hypotheses.
      - hunt: no gather, current head army, original WRP suffix from hunt_cursor.
      - known-gen: no gather + the actual direct finish as the sole case.
    remaining_cycle_turns = min(deadline-turn, 50-turn%50) and margins stay
    strict; the original deadline is never extended. Defense that changed the
    head/resources simply fails the certificate -> explicit abort, never an
    unsafe 'rejoin'. Returns 'finish'/'gather'/'hunt' for the viable mode, or
    'abort' after _abort when no safe remaining plan exists.
    """
    game_map = bot._map
    player_index = bot.player.index
    enemy_index = state.enemy_index
    enemy = game_map.players[enemy_index]

    # A spans-cycle plan (composite safe-front) honors its ORIGINAL absolute
    # deadline across the 50-turn boundary rather than the cycle remainder.
    if state.spans_cycles:
        remaining_cycle = state.deadline_turn - game_map.turn
    else:
        remaining_cycle = min(state.deadline_turn - game_map.turn, 50 - game_map.turn % 50)
    if remaining_cycle <= 0:
        # Tests/test_FFA.py defender20/34: a live slam ignores the certified
        # window entirely - the grind continues until the enemy dies or the
        # economy lead is gone.
        if _slam_capable(bot, state) is None:
            _abort(bot, "no_cycle_left")
            return "abort"
        remaining_cycle = 0

    known_gen = _known_general_tile(bot, enemy_index)
    hypotheses = _current_hypotheses(bot, state, known_gen)
    if hypotheses is None:
        _abort(bot, "hypotheses_uncertain")
        return "abort"
    if not hypotheses:
        _abort(bot, "no_valid_hypotheses")
        return "abort"

    enemy_standing = enemy.standingArmy
    enemy_tile_count, enemy_city_count = _enemy_counts(bot, enemy_index)
    all_ordinary = _all_ordinary_sources(bot, enemy_index)

    head = game_map.tiles_by_index[state.head_tile_index]
    launch = game_map.tiles_by_index[state.launch_tile_index]
    remaining_gather = state.gather_moves[state.gather_cursor:]
    suffix_tiles = [
        game_map.tiles_by_index[i]
        for i in state.hunt_route_tile_indexes[state.hunt_cursor:]]

    # Composite safe-front primary wave uses its own dedicated recertification
    # (project_safe_front + materialize + stored continuation + absolute
    # deadline); it is dispatched before the ordinary gather/hunt path.
    if state.safe_front_hunt_cursor >= 0:
        return _recertify_composite_primary(
            bot, state, known_gen, hypotheses, enemy_standing,
            enemy_tile_count, enemy_city_count, all_ordinary)

    def _certify_plan(
        gather_moves: list[Move],
        proj_launch: Tile,
        scenario_routes: list[tuple[Tile, list[Tile], int]],
    ) -> bool:
        """Run the lead forecast + per-case route-cost + certify pipeline."""
        forecast = project_forward_gather(
            game_map, gather_moves, proj_launch, player_index, enemy_index)
        if forecast is None:
            _vinfo(bot, 
                f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                f"stage=forecast launch={proj_launch.tile_index} "
                f"army={proj_launch.army} gatherLeft={len(gather_moves)}")
            return False
        gather_turns = len(gather_moves)
        remaining_sources = remaining_ordinary_sources(
            all_ordinary, forecast.paid_ordinary_armies)
        worst_route_turns = 0
        for hypothesis, route_tiles, route_turns in scenario_routes:
            cost = calculate_route_cost(
                game_map, route_tiles, player_index, enemy_index,
                hypothesized_general=hypothesis,
                gather_captured_tiles=forecast.captured_tile_indexes)
            if cost is None:
                _vinfo(bot, 
                    f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                    f"stage=route_cost hyp={hypothesis.tile_index} "
                    f"routeTurns={route_turns} launch={forecast.launch_army}")
                return False
            bounded = bounded_defensive_pool(
                game_map, enemy_index, [hypothesis],
                gather_turns + route_turns, enemy_standing)
            bounded_standing = max(0, bounded - forecast.paid_enemy_standing)
            projection = certify_kill(
                start_turn=game_map.turn,
                gather_turns=gather_turns,
                route_turns=route_turns,
                launch_army=forecast.launch_army,
                route_cost=cost,
                enemy_standing=bounded_standing,
                enemy_tile_count=enemy_tile_count,
                enemy_city_count=enemy_city_count,
                enemy_ordinary_armies=remaining_sources)
            # Tests/test_FFA.py defender20/34: the abort tolerates up to 10% of
            # the attacking force against the certificate's fog worst-case
            # (fog_buffered_certified); the strict margin>0 flag still logs.
            if not fog_buffered_certified(projection):
                _vinfo(bot, 
                    f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                    f"stage=certify hyp={hypothesis.tile_index} "
                    f"launch={forecast.launch_army} routeTurns={route_turns} "
                    f"cost={cost} enemyStanding={bounded_standing} "
                    f"enTiles={enemy_tile_count} enCities={enemy_city_count} "
                    f"margin={projection.margin} "
                    f"buffer={fog_margin_buffer(projection.launch_army)}")
                return False
            worst_route_turns = max(worst_route_turns, route_turns)
        total_turns = gather_turns + worst_route_turns
        ok = total_turns <= remaining_cycle and total_turns <= 100
        if not ok:
            _vinfo(bot, 
                f"FFA Kill Gather RECERT-FAIL turn={game_map.turn} "
                f"stage=deadline total={total_turns} "
                f"remainingCycle={remaining_cycle} gather={gather_turns} "
                f"routeTurns={worst_route_turns}")
        return ok

    # Known general revealed: prefer an immediate certified finish from the
    # ACTUAL assembled head; otherwise keep the still-certified gather; else abort.
    if known_gen is not None:
        finish_from_head = _finish_path(game_map, head, known_gen, player_index, enemy_index)
        if finish_from_head is not None and len(finish_from_head) >= 2:
            if _certify_plan([], head, [(known_gen, finish_from_head, len(finish_from_head) - 1)]):
                return "finish"
        if remaining_gather:
            finish_from_launch = _finish_path(game_map, launch, known_gen, player_index, enemy_index)
            if finish_from_launch is not None and len(finish_from_launch) >= 2:
                if _certify_plan(
                        remaining_gather, launch,
                        [(known_gen, finish_from_launch, len(finish_from_launch) - 1)]):
                    return "gather"
        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_
        # possible_vs_defender20/34: an uncertified finish does NOT release a
        # committed FFA kill while the economy lead holds - the slam handler
        # keeps grinding the confirmed general wave after wave.
        if _econ_ahead(bot, enemy_index):
            return "slam"
        _abort(bot, "finish_uncertified")
        return "abort"

    if not suffix_tiles:
        _abort(bot, "route_exhausted")
        return "abort"

    scenario_routes: list[tuple[Tile, list[Tile], int]] = []
    for hypothesis in hypotheses:
        case = _case_route_for_hypothesis(
            game_map, suffix_tiles, hypothesis, player_index, enemy_index)
        if case is None:
            _abort(bot, "hypothesis_unreachable")
            return "abort"
        scenario_routes.append((hypothesis, case[0], case[1]))

    if remaining_gather:
        if _certify_plan(remaining_gather, launch, scenario_routes):
            return "gather"
    else:
        if _certify_plan([], head, scenario_routes):
            return "hunt"
    _abort(bot, "recert_failed")
    return "abort"


def get_committed_move(bot: EklipZBot, defense_critical_tiles: set[Tile]) -> FfaKillGatherCommittedMove:
    """Return the next literal gather/launch/search/finish move while committed.

    Reached only after every defense gate has had priority. Validates scope,
    target liveness, deadline, move legality (ownership/adjacency/army/third-party
    destination), and defense-critical endpoints before offering any offense.
    The schedule cursor advances only via note_final_move on confirmed execution;
    nothing is popped here. Aborts with an explicit reason on any invalidity.
    Flag-off is a zero-cost no-op.
    """
    if not FFA_KILL_GATHER_ENABLED:
        return FfaKillGatherCommittedMove(False, None, "disabled")
    state = bot.ffa_kill_gather_state
    if state is None:
        return FfaKillGatherCommittedMove(False, None, "not_committed")
    game_map = bot._map
    player_index = bot.player.index

    # --- abort gates ---------------------------------------------------------
    if not _is_ffa_kill_gather_active(bot):
        _abort(bot, "scope_not_ffa")
        return FfaKillGatherCommittedMove(False, None, "scope_not_ffa")
    if not _score_alive(bot, state.enemy_index):
        _abort(bot, "target_gone")
        return FfaKillGatherCommittedMove(False, None, "target_gone")
    # Tests/test_FFA.py defender20/34: a live slam persists past the certified
    # window - it ends only on target death or a lost economy lead.
    if game_map.turn > state.deadline_turn and _slam_capable(bot, state) is None:
        _abort(bot, "deadline_passed")
        return FfaKillGatherCommittedMove(False, None, "deadline_passed")

    # Mandatory FULL remaining-plan recertification before ANY offer. Defense has
    # already had priority; this re-runs the lead forecast/certify pipeline on the
    # current head/remaining gather/updated map and aborts explicitly when the
    # remaining schedule can no longer certify (weakened head, lost route, missed
    # deadline, eliminated hypotheses). It also picks the viable mode: an early
    # certified finish once the real general is known, else the literal gather,
    # else the WRP hunt.
    mode = _recertify_remaining(bot, state)
    if mode == "abort":
        return FfaKillGatherCommittedMove(False, None, "recert_failed")

    if mode == "finish":
        known_gen = _known_general_tile(bot, state.enemy_index)
        if known_gen is None:
            _abort(bot, "finish_gen_lost")
            return FfaKillGatherCommittedMove(False, None, "finish_gen_lost")
        return _committed_finish_move(bot, state, known_gen, defense_critical_tiles)

    # Tests/test_FFA.py defender20/34: uncertified but economically winning
    # committed FFA kills slam the confirmed general until it dies.
    if mode == "slam":
        slam_gen = _slam_capable(bot, state)
        if slam_gen is None:
            _abort(bot, "slam_econ_lost")
            return FfaKillGatherCommittedMove(False, None, "slam_econ_lost")
        return _committed_slam_move(bot, state, slam_gen, defense_critical_tiles)

    # mode == "gather": offer the next literal gather move (peek cursor; the
    # confirmed-execution consume happens in note_final_move, not here).
    if mode == "gather":
        scheduled = state.gather_moves[state.gather_cursor]
        move = _validate_gather_move(bot, state, scheduled, defense_critical_tiles)
        if move is None:
            _abort(bot, "gather_move_invalid")
            return FfaKillGatherCommittedMove(False, None, "gather_move_invalid")
        return _offer(bot, state, move, "gather")

    # mode == "hunt": advance the explicit WRP cursor.
    state.phase = "hunt"
    return _committed_hunt_move(bot, state, defense_critical_tiles)


def _validate_gather_move(
    bot: EklipZBot,
    state: FfaKillGatherState,
    scheduled: Move,
    defense_critical_tiles: set[Tile],
) -> Move | None:
    """Re-validate a scheduled gather move against the CURRENT map.

    Returns a fresh Move only when source is ours, adjacent, has army > 1, dest
    is movable and not third-party, and the SOURCE is not defense-critical.
    A defense-critical DESTINATION is allowed: critical marks "do not drain this
    tile", and a gather step moving army INTO it only reinforces the very tile
    defense wants held.
    """
    player_index = bot.player.index
    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible:
    # Backup moves originate on a forecast map; validate and dispatch LIVE tiles.
    source = bot._map.tiles_by_index[scheduled.source.tile_index]
    dest = bot._map.tiles_by_index[scheduled.dest.tile_index]
    if source.player != player_index or source.army <= 1:
        _vinfo(bot, 
            f"FFA Kill Gather gather-move invalid turn={bot._map.turn} "
            f"reason=source_not_ours_or_depleted src={source.tile_index} "
            f"player={source.player} army={source.army} dest={dest.tile_index}")
        return None
    if dest not in source.movable or dest.isNotPathable:
        _vinfo(bot, 
            f"FFA Kill Gather gather-move invalid turn={bot._map.turn} "
            f"reason=dest_unreachable src={source.tile_index} dest={dest.tile_index}")
        return None
    if dest.player >= 0 and dest.player not in (player_index, state.enemy_index):
        _vinfo(bot, 
            f"FFA Kill Gather gather-move invalid turn={bot._map.turn} "
            f"reason=dest_third_party src={source.tile_index} dest={dest.tile_index} "
            f"owner={dest.player}")
        return None
    # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible_vs_defender20:
    # only the SOURCE may not be drained - the active-defender fixture marks the
    # launch/chokepoint defense-critical and the final gather step delivers INTO
    # it, which is exactly the reinforcement defense wants.
    if source in defense_critical_tiles:
        _vinfo(bot, 
            f"FFA Kill Gather gather-move invalid turn={bot._map.turn} "
            f"reason=source_defense_critical src={source.tile_index} dest={dest.tile_index}")
        return None
    return Move(source, dest, scheduled.move_half)


def _committed_hunt_move(
    bot: EklipZBot,
    state: FfaKillGatherState,
    defense_critical_tiles: set[Tile],
) -> FfaKillGatherCommittedMove:
    """Advance the explicit WRP cursor for the hunt phase.

    hunt_cursor is the authoritative position index into hunt_route_tile_indexes
    (route[0] == launch == initial head). head_tile_index is the validated actual
    stack tile; the two must agree or we rejoin via a restricted BFS. The route
    may revisit tiles, so position is the cursor, never tile-index lookup.
    """
    game_map = bot._map
    player_index = bot.player.index
    route_indexes = state.hunt_route_tile_indexes
    if not route_indexes:
        _abort(bot, "empty_route")
        return FfaKillGatherCommittedMove(False, None, "empty_route")

    head = game_map.tiles_by_index[state.head_tile_index]
    if head.player != player_index or head.army <= 1:
        _abort(bot, "head_invalid")
        return FfaKillGatherCommittedMove(False, None, "head_invalid")

    # Position on the route is the cursor; verify head still sits there. There is
    # NO unpriced rejoin: if a defense move or half-step left the head off the
    # stored cursor the remaining plan cannot be trusted to resume mid-route, so
    # abort explicitly (a fresh plan may be offered later). The route may revisit
    # tiles, so position is the cursor index, never a tile-index lookup.
    on_route = (
        state.hunt_cursor < len(route_indexes)
        and route_indexes[state.hunt_cursor] == state.head_tile_index)
    if not on_route:
        _abort(bot, "head_off_route")
        return FfaKillGatherCommittedMove(False, None, "head_off_route")

    if state.hunt_cursor + 1 >= len(route_indexes):
        _abort(bot, "route_exhausted")
        return FfaKillGatherCommittedMove(False, None, "route_exhausted")
    nxt = game_map.tiles_by_index[route_indexes[state.hunt_cursor + 1]]
    if not _hunt_step_legal(bot, state, head, nxt, defense_critical_tiles):
        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible_vs_defender34:
        # the legality result is a bare bool, so log which gate fired before aborting.
        _vinfo(bot, 
            f"FFA Kill Gather hunt-step reject turn={game_map.turn} "
            f"head={head.tile_index}/{head.army} headCrit={head in defense_critical_tiles} "
            f"nxt={nxt.tile_index} movable={nxt in head.movable} "
            f"pathable={not nxt.isNotPathable} nxtPlayer={nxt.player} "
            f"nxtArmy={nxt.army} disc={nxt.discovered} "
            f"cursor={state.hunt_cursor}")
        _abort(bot, "hunt_step_illegal")
        return FfaKillGatherCommittedMove(False, None, "hunt_step_illegal")
    return _offer(bot, state, Move(head, nxt), "hunt")


def _hunt_step_legal(
    bot: EklipZBot,
    state: FfaKillGatherState,
    head: Tile,
    nxt: Tile,
    defense_critical_tiles: set[Tile],
) -> bool:
    """Validate one hunt step: adjacency, pathability, ownership, combat, critical.

    The destination must be reachable, not walled, and owned by us / the victim /
    neutral fog - never a third party (a fog tile predicted to a third party may
    only be entered in the hypothetical certificate, never in actual execution).
    A defense-critical head is refused (draining a required garrison), and an
    enemy-owned destination must be small enough for the head stack to actually
    capture: a FULL move sends head.army-1 (one stays behind), so capture needs
    head.army-1 > nxt.army. A defense-critical DESTINATION is allowed - stepping
    the head onto it reinforces the tile defense wants held. The per-turn
    recertification independently re-prices the whole route.
    """
    player_index = bot.player.index
    if head in defense_critical_tiles:
        return False
    if nxt not in head.movable or nxt.isNotPathable:
        return False
    if nxt.player >= 0 and nxt.player not in (player_index, state.enemy_index):
        return False
    if nxt.player == state.enemy_index and head.army - 1 <= nxt.army:
        return False
    return True


def _committed_finish_move(
    bot: EklipZBot,
    state: FfaKillGatherState,
    known_gen: Tile,
    defense_critical_tiles: set[Tile],
) -> FfaKillGatherCommittedMove:
    """Hand off to a certified shortest finish once the real general is known.

    Recomputes the restricted finish from the CURRENT head each turn (the stack
    may have been repositioned by defense), so the path is always legal and
    shortest. Never continues the WRP sweep once the general is revealed.
    """
    game_map = bot._map
    player_index = bot.player.index
    head = game_map.tiles_by_index[state.head_tile_index]
    # Tests/test_FFA.py defender20/34: when the confirmed general may still be
    # slammed (economy lead holds), a certified finish that is not executable
    # THIS turn defers to the slam handler (regather/attrition) instead of
    # releasing the committed kill.
    slam_gen = _slam_capable(bot, state)
    if head.player != player_index or head.army <= 1:
        if slam_gen is not None:
            return _committed_slam_move(bot, state, slam_gen, defense_critical_tiles)
        _abort(bot, "finish_head_invalid")
        return FfaKillGatherCommittedMove(False, None, "finish_head_invalid")
    if head in defense_critical_tiles:
        _abort(bot, "finish_head_defense_critical")
        return FfaKillGatherCommittedMove(False, None, "finish_head_defense_critical")
    path = _finish_path(game_map, head, known_gen, player_index, state.enemy_index)
    if path is None or len(path) < 2:
        if slam_gen is not None:
            return _committed_slam_move(bot, state, slam_gen, defense_critical_tiles)
        _abort(bot, "finish_no_path")
        return FfaKillGatherCommittedMove(False, None, "finish_no_path")
    nxt = path[1]
    if nxt not in head.movable or nxt.isNotPathable:
        if slam_gen is not None:
            return _committed_slam_move(bot, state, slam_gen, defense_critical_tiles)
        _abort(bot, "finish_step_illegal")
        return FfaKillGatherCommittedMove(False, None, "finish_step_illegal")
    if nxt.player >= 0 and nxt.player not in (player_index, state.enemy_index):
        _abort(bot, "finish_third_party")
        return FfaKillGatherCommittedMove(False, None, "finish_third_party")
    # Combat sanity for an enemy-owned step (incl. the general capture): the head
    # stack must actually outnumber the destination or the move just feeds it.
    if nxt.player == state.enemy_index and head.army <= nxt.army:
        if slam_gen is not None:
            return _committed_slam_move(bot, state, slam_gen, defense_critical_tiles)
        _abort(bot, "finish_step_outmatched")
        return FfaKillGatherCommittedMove(False, None, "finish_step_outmatched")
    return _offer(bot, state, Move(head, nxt), "finish")


def _committed_slam_move(
    bot: EklipZBot,
    state: FfaKillGatherState,
    known_gen: Tile,
    defense_critical_tiles: set[Tile],
) -> FfaKillGatherCommittedMove:
    """FFA attrition slam against a CONFIRMED general.

    Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_
    possible_vs_defender20/34: a committed FFA kill does not release on an
    uncertified margin. While the economy lead holds we hit the general as fast
    as we can - a capture kills, a loss removes that much garrison for the next
    wave. The victim's non-general land is never attacked: their tiles (and half
    their remaining standing) come to us on the capture, so taking land early
    just annihilates army we would have won. Releases only when the economy
    lead is gone or no slam force can be fielded.
    """
    game_map = bot._map
    player_index = bot.player.index
    enemy_index = state.enemy_index
    if not _econ_ahead(bot, enemy_index):
        _abort(bot, "slam_econ_lost")
        return FfaKillGatherCommittedMove(False, None, "slam_econ_lost")
    head = game_map.tiles_by_index[state.head_tile_index]
    step = None
    if (head.player == player_index and head.army > 1
            and head not in defense_critical_tiles):
        path = _finish_path(game_map, head, known_gen, player_index, enemy_index)
        if path is not None and len(path) >= 2:
            candidate = path[1]
            if (candidate in head.movable and not candidate.isNotPathable
                    and (candidate.player < 0
                         or candidate.player in (player_index, enemy_index))):
                step = candidate
    # A step that visibly captures (or IS the general we can take) fires now.
    if step is not None and (
            (step is known_gen and head.army - 1 > known_gen.army)
            or (step is not known_gen
                and (step.player == player_index or head.army - 1 > step.army))):
        _vinfo(bot, 
            f"FFA Kill Gather SLAM turn={game_map.turn} "
            f"head={head.tile_index}/{head.army} step={step.tile_index}/{step.army} "
            f"gen={known_gen.tile_index}/{known_gen.army} "
            f"econ={_econ_value(bot.player)}>{_econ_value(game_map.players[enemy_index])}")
        return _offer(bot, state, Move(head, step), "slam")
    move = _slam_gather_move(bot, state, known_gen, defense_critical_tiles)
    if move is not None:
        return _offer(bot, state, move, "gather")
    # No gatherable wave left: attrition-slam. The general step is always taken;
    # an enemy-owned route step may also be ground down, never a neutral tile
    # (a lost neutral attack destroys the wave for zero damage).
    head = game_map.tiles_by_index[state.head_tile_index]
    if (head.player == player_index and head.army > 1
            and head not in defense_critical_tiles):
        path = _finish_path(game_map, head, known_gen, player_index, enemy_index)
        if path is not None and len(path) >= 2:
            candidate = path[1]
            if (candidate in head.movable and not candidate.isNotPathable
                    and (candidate is known_gen or candidate.player == enemy_index
                         or candidate.player == player_index
                         or (candidate.player < 0 and head.army - 1 > candidate.army))):
                _vinfo(bot, 
                    f"FFA Kill Gather SLAM-ATTRITION turn={game_map.turn} "
                    f"head={head.tile_index}/{head.army} "
                    f"step={candidate.tile_index}/{candidate.army} "
                    f"gen={known_gen.tile_index}/{known_gen.army}")
                return _offer(bot, state, Move(head, candidate), "slam")
    _abort(bot, "slam_starved")
    return FfaKillGatherCommittedMove(False, None, "slam_starved")


def _slam_gather_move(
    bot: EklipZBot,
    state: FfaKillGatherState,
    known_gen: Tile,
    defense_critical_tiles: set[Tile],
) -> Move | None:
    """Next gather move building the next slam wave, or None when none exists.

    Continues the in-flight owned-only schedule while it validates; once spent,
    rebuilds a fresh schedule onto the slam root (strongest owned tile adjacent
    to the general, else the current head) sized to outnumber the visible
    garrison. The victim's land is never a gather source or destination.
    """
    game_map = bot._map
    player_index = bot.player.index
    while state.gather_cursor < len(state.gather_moves):
        scheduled = state.gather_moves[state.gather_cursor]
        move = _validate_gather_move(bot, state, scheduled, defense_critical_tiles)
        if move is not None:
            return move
        # Stale step (source drained/lost) - the rest of this schedule is
        # untrusted; fall through to a fresh replan on the CURRENT map.
        state.gather_cursor += 1
    root = _slam_root(bot, state, known_gen)
    if root is None:
        return None
    needed = known_gen.army + 2 - root.army
    if needed <= 0:
        # The root already outnumbers the garrison; retarget the wave head onto
        # it and let the slam legality checks fire the capture this turn.
        state.head_tile_index = root.tile_index
        return None
    budget = min(needed + 6, 40)
    schedule = build_owned_gather_schedule(
        bot, root, set(defense_critical_tiles), budget, state.enemy_index)
    if not schedule:
        return None
    state.gather_moves = schedule
    state.gather_cursor = 0
    state.launch_tile_index = root.tile_index
    state.head_tile_index = root.tile_index
    _vinfo(bot,
        f"FFA Kill Gather SLAM-REGATHER turn={game_map.turn} "
        f"root={root.tile_index}/{root.army} gen={known_gen.tile_index}/{known_gen.army} "
        f"budget={budget} moves={len(schedule)}")
    return _validate_gather_move(bot, state, schedule[0], defense_critical_tiles)


def _slam_root(
    bot: EklipZBot,
    state: FfaKillGatherState,
    known_gen: Tile,
) -> Tile | None:
    """Wave root for the next slam: strongest owned tile adjacent to the
    confirmed general (shortest possible delivery), else the current head."""
    game_map = bot._map
    player_index = bot.player.index
    best = None
    for neighbor in known_gen.movable:
        if neighbor.player == player_index and (best is None or neighbor.army > best.army):
            best = neighbor
    if best is not None:
        return best
    head = game_map.tiles_by_index[state.head_tile_index]
    return head if head.player == player_index else None


def _abort(bot: EklipZBot, reason: str) -> None:
    """Clear committed state with an explicit logged reason.

    Only releases the exclusive lock when THIS feature created it; a pre-existing
    same-target lock is left intact.
    """
    state = bot.ffa_kill_gather_state
    if state is not None:
        _vinfo(bot, f"FFA Kill Gather ABORT turn={bot._map.turn} reason={reason} enemy=p{state.enemy_index}")
        if state.owns_exclusive_lock and bot.ffa_exclusive_target_lock == state.enemy_index:
            bot.ffa_exclusive_target_lock = -1
    bot.ffa_kill_gather_state = None


def add_stats(bot: EklipZBot) -> None:
    """Emit FFA Kill Gather diagnostics for A+B-eligible victims only.

    No line at all when there is no eligible victim (avoids FFA spam). Detailed
    math goes to logbook/bot.info; the viewer gets one compact line under
    EXP AVAIL with standing/econ, queue, candidate confidence, turns, launch,
    cost, enemy growth/defense, margin, value, and phase/offered/chosen/reason.
    """
    if not _is_ffa_kill_gather_active(bot):
        return
    cache = bot._ffa_kill_gather_cache
    eligible = [d for d in cache.candidates.values() if d.eligible]
    if not eligible:
        return
    state = bot.ffa_kill_gather_state
    parts: list[str] = []
    if state is not None:
        parts.append(
            f"committed p{state.enemy_index} {state.phase} "
            f"margin={state.projection_margin} gatherLeft={len(state.gather_moves) - state.gather_cursor}")
    else:
        best = cache.option_cache
        if best is not None:
            parts.append(
                f"offered p{best.enemy_index} gather={best.gather_turns}t route={best.route_turns}t "
                f"margin={best.projection.margin} value={best.kill_value.total:.0f}")
        elif cache.best_failed is not None:
            d = cache.best_failed
            parts.append(
                f"p{d.enemy_index} uncertified margin={d.margin} defense={d.enemy_defense} "
                f"launch={d.launch_army} cost={d.route_cost} reason={d.reject_reason}")
        else:
            for d in eligible:
                parts.append(f"p{d.enemy_index} {d.reject_reason or 'evaluated'}")
                break
    bot.viewInfo.add_stats_line("FFA Kill Gather " + " | ".join(parts))


# ------------------------------ serialization ------------------------------

def _serialize_moves(moves: list[Move]) -> str:
    """Encode a move list as 'src>dst:half;...' for the txtmap boundary."""
    return ";".join(f"{m.source.tile_index}>{m.dest.tile_index}:{int(m.move_half)}" for m in moves)


def _deserialize_moves(bot: EklipZBot, raw: str) -> list[Move]:
    """Decode 'src>dst:half;...' back into Moves on the live map."""
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


def save_state(bot: EklipZBot) -> dict[str, str]:
    """Serialize committed state to a txtmap block dict (dict only at boundary)."""
    data: dict[str, str] = {"bot_ffa_kill_active": "0"}
    if not FFA_KILL_GATHER_ENABLED:
        return data
    state = bot.ffa_kill_gather_state
    if state is None:
        return data
    data["bot_ffa_kill_active"] = "1"
    data["bot_ffa_kill_enemy"] = str(state.enemy_index)
    data["bot_ffa_kill_launch"] = str(state.launch_tile_index)
    data["bot_ffa_kill_created"] = str(state.created_turn)
    data["bot_ffa_kill_deadline"] = str(state.deadline_turn)
    data["bot_ffa_kill_margin"] = str(state.projection_margin)
    data["bot_ffa_kill_value"] = str(state.kill_value_total)
    # PREMOVE alignment: note_final_move/_consume_offered advances the live
    # cursor/head/phase during select_move, but save_txtmap serializes the board
    # BEFORE the async move is applied. When the confirmed consume belongs to
    # the CURRENT map turn, the serialized map is still pre-move, so emit the
    # pre-consume instruction (same gather/route lists) - a resume then points at
    # the step the pre-move map actually expects instead of skipping it. On any
    # later turn (last_consumed_turn != map.turn, incl. receive_update_no_move)
    # the board already reflects the move, so the live post-consume values are
    # correct and are written unchanged. Deadline/lock/value are never rewound.
    if state.last_consumed_turn == bot._map.turn:
        phase_out = state.pre_consume_phase
        gather_cursor_out = state.pre_consume_gather_cursor
        hunt_cursor_out = state.pre_consume_hunt_cursor
        head_out = state.pre_consume_head_tile_index
    else:
        phase_out = state.phase
        gather_cursor_out = state.gather_cursor
        hunt_cursor_out = state.hunt_cursor
        head_out = state.head_tile_index
    data["bot_ffa_kill_phase"] = phase_out
    data["bot_ffa_kill_gather_cursor"] = str(gather_cursor_out)
    data["bot_ffa_kill_hunt_cursor"] = str(hunt_cursor_out)
    data["bot_ffa_kill_head"] = str(head_out)
    data["bot_ffa_kill_pending_key"] = state.pending_offered_key
    data["bot_ffa_kill_pending_turn"] = str(state.pending_offered_turn)
    data["bot_ffa_kill_pending_half"] = str(int(state.pending_offered_half))
    data["bot_ffa_kill_pending_dest"] = str(state.pending_offered_dest_index)
    data["bot_ffa_kill_owns_lock"] = str(int(state.owns_exclusive_lock))
    # Serialize the FULL gather list plus the absolute cursor so the two stay
    # aligned on load (cursor indexes into the full list; consumed prefix is kept
    # for reference but never re-executed). Serializing only the remaining moves
    # while keeping the absolute cursor would misalign and drop a pending step.
    data["bot_ffa_kill_gather_moves"] = _serialize_moves(state.gather_moves)
    data["bot_ffa_kill_route"] = ",".join(str(i) for i in state.hunt_route_tile_indexes)
    data["bot_ffa_kill_route_cursor_base"] = str(hunt_cursor_out)
    data["bot_ffa_kill_finish"] = ",".join(str(i) for i in state.finishing_route_tile_indexes)
    data["bot_ffa_kill_candidates"] = ",".join(str(i) for i in state.candidates)
    # Composite safe-front continuation fields (R7); absent keys default to the
    # ordinary single-wave plan on load.
    data["bot_ffa_kill_safe_front_cursor"] = str(state.safe_front_hunt_cursor)
    data["bot_ffa_kill_spans_cycles"] = str(int(state.spans_cycles))
    data["bot_ffa_kill_continuation_moves"] = _serialize_moves(state.continuation_gather_moves)
    return data


def load_state(bot: EklipZBot, resume_data: dict[str, str]) -> None:
    """Restore committed state from resume_data; default inactive when absent.

    Restores the literal remaining gather moves (no half-executed step is lost),
    the explicit hunt cursor/head, the pending offer for reconciliation, the
    finishing route, and whether this feature owns the exclusive lock.
    """
    if not FFA_KILL_GATHER_ENABLED or resume_data.get("bot_ffa_kill_active", "0") != "1":
        bot.ffa_kill_gather_state = None
        return
    game_map = bot._map
    gather_moves = _deserialize_moves(bot, resume_data.get("bot_ffa_kill_gather_moves", ""))
    route_indexes = [int(x) for x in resume_data.get("bot_ffa_kill_route", "").split(",") if x]
    finish_indexes = [int(x) for x in resume_data.get("bot_ffa_kill_finish", "").split(",") if x]
    candidate_indexes = [int(x) for x in resume_data.get("bot_ffa_kill_candidates", "").split(",") if x]
    state = FfaKillGatherState(
        enemy_index=int(resume_data["bot_ffa_kill_enemy"]),
        launch_tile_index=int(resume_data["bot_ffa_kill_launch"]),
        gather_moves=gather_moves,
        hunt_route_tile_indexes=route_indexes,
        candidates=candidate_indexes,
        created_turn=int(resume_data["bot_ffa_kill_created"]),
        deadline_turn=int(resume_data["bot_ffa_kill_deadline"]),
        kill_value_total=float(resume_data["bot_ffa_kill_value"]),
        projection_margin=int(resume_data["bot_ffa_kill_margin"]),
        owns_exclusive_lock=bool(int(resume_data.get("bot_ffa_kill_owns_lock", "0"))))
    state.gather_cursor = int(resume_data.get("bot_ffa_kill_gather_cursor", "0"))
    state.hunt_cursor = int(resume_data.get("bot_ffa_kill_route_cursor_base", "0"))
    state.head_tile_index = int(resume_data.get("bot_ffa_kill_head", str(state.launch_tile_index)))
    state.finishing_route_tile_indexes = finish_indexes
    state.pending_offered_key = resume_data.get("bot_ffa_kill_pending_key", "")
    state.pending_offered_turn = int(resume_data.get("bot_ffa_kill_pending_turn", "-1"))
    state.pending_offered_half = bool(int(resume_data.get("bot_ffa_kill_pending_half", "0")))
    state.pending_offered_dest_index = int(resume_data.get("bot_ffa_kill_pending_dest", "-1"))
    state.phase = resume_data.get("bot_ffa_kill_phase", "gather")
    state.safe_front_hunt_cursor = int(resume_data.get("bot_ffa_kill_safe_front_cursor", "-1"))
    state.spans_cycles = bool(int(resume_data.get("bot_ffa_kill_spans_cycles", "0")))
    state.continuation_gather_moves = _deserialize_moves(
        bot, resume_data.get("bot_ffa_kill_continuation_moves", ""))
    bot.ffa_kill_gather_state = state
    # Restore the exclusive lock only if this feature owns it.
    if state.owns_exclusive_lock:
        bot.ffa_exclusive_target_lock = state.enemy_index


def shutdown(bot: EklipZBot, timeout_sec: float = 30.0, block_worker: bool = True) -> None:
    """Release the feature worker, invalidate its cache, and drop committed state.

    Releases ONLY a lock this feature created (state.owns_exclusive_lock), never
    a pre-existing same-target exclusive lock. Invalidates route/option/candidate
    search artifacts so a later FFA cannot reuse stale geometry.

    block_worker=True (game over / test cleanup) joins the worker synchronously
    up to timeout_sec. block_worker=False (FFA-end on the move hot path) issues
    a NON-blocking request_close instead - the daemon worker finishes its
    current ~1s job and self-terminates, and _poll_wrp finalizes via poll_close
    on a later move, so no join ever blocks move selection.
    """
    cache = bot._ffa_kill_gather_cache
    state = bot.ffa_kill_gather_state
    if (state is not None and state.owns_exclusive_lock
            and bot.ffa_exclusive_target_lock == state.enemy_index):
        bot.ffa_exclusive_target_lock = -1
    bot.ffa_kill_gather_state = None
    cache.pending_job = None
    cache.route_cache.clear()
    cache.option_cache = None
    cache.candidates.clear()
    cache.best_failed = None
    if cache.wrp_worker is not None:
        if block_worker:
            cache.wrp_worker.close(timeout_sec=timeout_sec)
            cache.wrp_worker = None
        else:
            cache.wrp_worker.request_close()


def shutdown_if_not_ffa(bot: EklipZBot) -> None:
    """Release feature resources once the game is no longer a >2-team FFA.

    Wired into is_committed so FFA-end cleanup runs on the move path without
    waiting for game over. Uses the NON-blocking worker close (request_close +
    deferred poll_close) so no join ever stalls move selection; while still FFA
    this is a cheap no-op.
    """
    if not FFA_KILL_GATHER_ENABLED:
        return
    if not _is_ffa_kill_gather_active(bot):
        shutdown(bot, block_worker=False)
