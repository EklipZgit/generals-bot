"""Stealth flank gather and watchman-route attack planning."""

from __future__ import annotations

import pickle
import time
from collections import deque
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import logbook

import Gather
import SearchUtils
from Algorithms import WatchmanRouteUtils
from BotModules.BotCombatOps import BotCombatOps
from BotModules.BotDefense import BotDefense
from BotModules.BotRepetition import BotRepetition
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotTargeting import BotTargeting
from BotModules.BotTimings import BotTimings
from DangerAnalyzer import ThreatObj, ThreatType
from DistanceMapperImpl import DistanceMapperImpl
from Interfaces import MapMatrixInterface, TileSet
from MapMatrix import MapMatrix
from Models import Move
from Path import Path
from Sim.TextMapLoader import TextMapLoader
from BotModules.WrpWorkerProcess import (
    WrpRequest,
    WrpResult,
    WrpWorkerProcess,
)
from base.client.map import MapBase, Tile

if TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot


@dataclass(slots=True)
class StealthWrpJob:
    """Background watchman-route work and its index-only result."""

    generation: int
    start_tile_index: int
    done: bool
    result_tile_indexes: list[int] | None
    target_tile_indexes: list[int]
    initial_army: int
    time_limit: float
    duration_sec: float | None = None
    background_process: bool = False
    pickle_duration_sec: float = 0.0
    payload_bytes: int = 0


@dataclass(slots=True)
class StealthAllInState:
    """Gather, flank, and WRP route state for one losing-all-in target."""

    launch_tile: Tile
    entry_tile: Tile
    flank_path: Path
    launch_turn: int
    wrp_job: StealthWrpJob | None
    committed_route: Path | None
    committed_turn: int
    last_route_move: Move | None
    used_normal_gather_fallback_turns: int
    generation: int = 0
    is_undefendable_hunt: bool = False
    is_truncated_front: bool = False
    """True while committed_route is a truncated safe-front segment that must re-check on completion."""
    is_desperation_dive: bool = False
    """True when this plan gave up verifying the kill and committed the route anyway (losing all-in)."""


# Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend
# and test_should_stealth_flank_all_in_when_enemy_general_unknown: expose route defense moves to assertions.
@dataclass(slots=True)
class StealthRouteDefenseInterrupt:
    """The defense move that interrupted one committed stealth route step."""

    turn: int
    move: Move
    generation: int
    launch_tile_index: int
    aborted_route: bool


@dataclass(slots=True)
class StealthCandidateSafety:
    """Remaining army and reachable visible defense for one revealed candidate."""

    tile_index: int
    reveal_turns: int
    remaining_army: int
    enemy_defense: int
    required_army: float


@dataclass(slots=True)
class StealthRouteSafetyEstimate:
    """Per-candidate remaining army and visible defense at each reveal."""

    min_army_at_reveal: int | None
    max_enemy_defense: int
    safe_at_every_reveal: bool
    candidate_results: list[StealthCandidateSafety]


# Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
# keep hidden gathering separate from existing all-in behavior until a WRP route commits.
class BotStealthAllIn:
    """Build stealth paths, gather at hidden launch tiles, then execute WRP routes."""

    __slots__ = ()

    # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
    # consecutive turns a single uncommitted plan may fail the launch kill-check before the
    # losing all-in stops demanding safety and dives the assembled stack at the candidates.
    CANNOT_KILL_GATHER_TURNS_BEFORE_DIVE = 6

    # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
    # a hidden flank only earns its delay when it denies the enemy warning turns before we reach
    # their general; each warning turn saved is worth ~3 extra route turns, so candidate plans are
    # scored routeLen + 3 * warningTurns and the flank must beat the best direct attack route.
    SURPRISE_TURNS_PER_DELAY = 3
    MAX_FLANK_ROUTE_EVALUATIONS = 4
    DIRECT_ROUTE_EVALUATION_ARMY_TILES = 4
    DIRECT_PREFERRED_REPLAN_TURNS = 5

    @staticmethod
    def is_stealth_all_in_active(bot: EklipZBot) -> bool:
        """Return whether the bot is in the settled stealth-losing-all-in mode (requires bot.enable_stealth_all_in)."""
        return (
            bot.enable_stealth_all_in
            and bot.is_all_in_losing
            and not bot.targetPlayerExpectedGeneralLocation.isGeneral
            and not bot.is_all_in_army_advantage
            and bot.targetPlayer != -1
            and not BotStateQueries.is_still_ffa_and_non_dominant(bot))

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # allow an undefendable WRP attack outside the losing-all-in mode.
    @staticmethod
    def is_undefendable_hunt_active(bot: EklipZBot) -> bool:
        """Return whether an unknown-general hunt is in scope outside losing all-in (requires bot.enable_stealth_all_in)."""
        return (
            bot.enable_stealth_all_in
            and not bot.is_all_in_losing
            and not bot.targetPlayerExpectedGeneralLocation.isGeneral
            and not bot.is_all_in_army_advantage
            and bot.targetPlayer != -1
            and not BotStateQueries.is_still_ffa_and_non_dominant(bot))

    @staticmethod
    def clear_pending_hunt_job(bot: EklipZBot) -> None:
        """Discard uncommitted hunt work after its target becomes ineligible."""
        bot.stealth_hunt_job = None
        bot.stealth_hunt_target_player = -1
        bot.stealth_hunt_last_evaluation_turn = -1
        bot.stealth_hunt_last_evaluated_army = 0
        bot.stealth_hunt_render_path = None

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # evaluate the shared fog-defense estimate only after a cloned-map WRP job completes.
    @staticmethod
    def get_undefendable_hunt_move(
        bot: EklipZBot,
        threat: ThreatObj | None,
        defense_critical_tiles: set[Tile],
        king_kill_path: Path | None,
        race_chance: float,
    ) -> Move | None:
        """Commit a WRP hunt only when its predicted reveal army beats fog defense."""
        BotStealthAllIn.poll_wrp_worker_results(bot)
        if not BotStealthAllIn.is_undefendable_hunt_active(bot):
            BotStealthAllIn.clear_pending_hunt_job(bot)
            return None
        if (bot.stealth_all_in is not None
                and bot.stealth_all_in.committed_route is not None):
            return None
        # Tests/test_GeneralHunting.py::GeneralPredictionTests.test_should_keep_diving_when_all_in_and_not_much_left_to_search_regardless_of_opp_army
        # and test_should_not_dive_few_fog_tiles_when_cannot_kill: under a live general-kill threat,
        # a fresh hunt commits only to be defense-interrupted every turn (commit/abort loop that
        # displaces the dive); the same condition that interrupts a committed route gates starting one.
        if (threat is not None
                and threat.threatType == ThreatType.Kill
                and threat.path.tail.tile.isGeneral):
            return None

        turn = bot._map.turn
        if bot.stealth_hunt_last_evaluation_turn == turn:
            return None
        enemy_player = bot.targetPlayer
        job = bot.stealth_hunt_job
        candidates: list[Tile] | None = None
        if job is None:
            bot.stealth_hunt_render_path = None
            # Tests/test_BotBehavior.py::BotBehaviorTests.test_should_not_defensive_gather_into_oblivion_when_just_need_to_keep_up_on_tiles:
            # the full eval sorts candidates + scans fog defense every turn even when no army can
            # qualify; one tile scan + a 5-turn/1.2x hysteresis keeps that cost off unviable turns.
            largest_army = 0
            for tile in bot._map.get_all_tiles():
                if (tile.player == bot.general.player
                        and tile.army > largest_army):
                    largest_army = tile.army
            if (bot.stealth_hunt_last_evaluation_turn >= 0
                    and turn - bot.stealth_hunt_last_evaluation_turn < 5
                    and largest_army < bot.stealth_hunt_last_evaluated_army * 1.2):
                return None
            bot.stealth_hunt_last_evaluation_turn = turn
            bot.stealth_hunt_last_evaluated_army = largest_army
            candidates = BotTargeting.get_target_player_possible_general_location_tiles_sorted(
                bot,
                elimNearbyRange=0,
                player=enemy_player,
                cutoffEmergenceRatio=0.3)
            # Tests/test_GeneralHunting.py::GeneralPredictionTests.test_should_not_dive_few_fog_tiles_when_cannot_kill:
            # a WRP 'hunt' over a couple of candidates is just a dive, which quick-kill already
            # declined - only run the hunt when there is a real search space to route through.
            if len(candidates) < 3:
                return None
            fog_defense = max(
                1,
                BotCombatOps.get_fog_defense_amount_available_for_tiles(
                    bot,
                    bot.alt_en_gen_positions[enemy_player],
                    enemy_player,
                    fog_defense_turns=0,
                    fog_reach_turns=5))
            army_tile = BotStealthAllIn._get_hunt_army_tile(
                bot,
                threat,
                fog_defense * 1.2 + 2,
                bot.stealth_hunt_excluded_start_tile_indexes)
            if not candidates or army_tile is None:
                logbook.info(
                    f"STEALTH_ALLIN_HUNT_EVAL turn={turn} "
                    f"armyTile={army_tile} army={army_tile.army if army_tile else 0} "
                    f"enemyDefense={fog_defense} routeLen=0 "
                    f"minArmyAtReveal=None commit=False reason=no_candidate_or_army")
                return None

            pre_gate_path = BotStealthAllIn._get_shortest_path_to_candidate(
                bot,
                army_tile,
                candidates)
            if pre_gate_path is None or pre_gate_path.tail is None:
                logbook.info(
                    f"STEALTH_ALLIN_HUNT_EVAL turn={turn} "
                    f"armyTile={army_tile.x},{army_tile.y} army={army_tile.army} "
                    f"enemyDefense={fog_defense} routeLen=0 "
                    f"minArmyAtReveal=None commit=False reason=pregate")
                return None

            pre_gate_length = pre_gate_path.length
            pre_gate_safety = BotStealthAllIn._evaluate_route_safety(
                bot,
                pre_gate_path,
                [pre_gate_path.tail.tile],
                army_tile.army,
                enemy_player,
                distance_offset=0)
            if not pre_gate_safety.safe_at_every_reveal:
                logbook.info(
                    f"STEALTH_ALLIN_HUNT_EVAL turn={turn} "
                    f"armyTile={army_tile.x},{army_tile.y} army={army_tile.army} "
                    f"enemyDefense={pre_gate_safety.max_enemy_defense} "
                    f"routeLen={pre_gate_length} "
                    f"minArmyAtReveal={pre_gate_safety.min_army_at_reveal} "
                    f"candidateResults={BotStealthAllIn._format_candidate_safety_results(pre_gate_safety)} "
                    f"commit=False reason=pregate")
                return None

            bot.stealth_all_in_generation += 1
            bot.stealth_hunt_target_player = enemy_player
            job = BotStealthAllIn.start_wrp_job(
                bot,
                army_tile,
                candidates,
                army_tile.army,
                bot.stealth_all_in_generation)
            bot.stealth_hunt_job = job
            if not job.done:
                return None
        elif bot.stealth_hunt_target_player != enemy_player:
            BotStealthAllIn.clear_pending_hunt_job(bot)
            return None
        elif not job.done:
            BotStealthAllIn._raise_if_pending_wrp_worker_exited(bot)
            return None

        bot.stealth_hunt_last_evaluation_turn = turn
        army_tile = bot._map.tiles_by_index[job.start_tile_index]
        wrp_path = BotStealthAllIn.convert_wrp_job_result(bot._map, job)
        candidates = [
            bot._map.tiles_by_index[tile_index]
            for tile_index in job.target_tile_indexes]
        route_length = wrp_path.length if wrp_path is not None else 0
        route_safety = (
            BotStealthAllIn._evaluate_route_safety(
                bot,
                wrp_path,
                candidates,
                army_tile.army,
                enemy_player)
            if wrp_path is not None
            else StealthRouteSafetyEstimate(
                None,
                1,
                False,
                []))
        bot.stealth_hunt_render_path = wrp_path
        commit = (
            wrp_path is not None
            and wrp_path.length > 0
            and wrp_path.start is not None
            and wrp_path.start.tile.tile_index == army_tile.tile_index
            and army_tile.player == bot.general.player
            and army_tile.army > 1
            and route_safety.safe_at_every_reveal)
        logbook.info(
            f"STEALTH_ALLIN_HUNT_EVAL turn={turn} "
            f"armyTile={army_tile.x},{army_tile.y} army={army_tile.army} "
            f"enemyDefense={route_safety.max_enemy_defense} "
            f"routeLen={route_length} "
            f"minArmyAtReveal={route_safety.min_army_at_reveal} "
            f"candidateResults={BotStealthAllIn._format_candidate_safety_results(route_safety)} "
            f"commit={commit}")
        bot.stealth_hunt_last_evaluated_army = army_tile.army
        bot.stealth_hunt_job = None
        bot.stealth_hunt_target_player = -1
        if not commit or wrp_path is None:
            return None

        flank_path = Path()
        flank_path.add_next(army_tile)
        bot.stealth_all_in = StealthAllInState(
            launch_tile=army_tile,
            entry_tile=army_tile,
            flank_path=flank_path,
            launch_turn=turn,
            wrp_job=job,
            committed_route=wrp_path,
            committed_turn=turn,
            last_route_move=None,
            used_normal_gather_fallback_turns=0,
            generation=job.generation,
            is_undefendable_hunt=True)
        bot.stealth_hunt_render_path = None
        bot.curPath = None
        bot.curPathPrio = -1
        logbook.info(
            f"STEALTH_ALLIN_COMMIT turn={turn} routeLen={wrp_path.length} "
            f"headArmy={army_tile.army}")
        return BotStealthAllIn.get_committed_route_move(
            bot,
            threat,
            defense_critical_tiles,
            king_kill_path,
            race_chance)

    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # verify the enemy-vision matrix includes the target's diagonal visibility.
    @staticmethod
    def build_enemy_vision_matrix(bot: EklipZBot) -> MapMatrixInterface[bool]:
        """Mark tiles the target can currently see from its owned tiles."""
        enemy_vision = MapMatrix(bot._map, False)
        for tile in bot._map.get_all_tiles():
            enemy_vision.raw[tile.tile_index] = (
                bot._map.is_tile_enemy(tile)
                or any(bot._map.is_tile_enemy(adjacent) for adjacent in tile.adjacents))
        vision_tile_count = sum(1 for visible in enemy_vision.raw if visible)
        logbook.info(
            f"STEALTH_ALLIN_VISION turn={bot._map.turn} visionTiles={vision_tile_count}")
        return enemy_vision

    @staticmethod
    def find_stealth_flank_path(
        bot: EklipZBot,
        enemy_vision: MapMatrixInterface[bool],
    ) -> Path | None:
        """Find the best hidden owned-tile flank route, or None when the direct attack is better."""
        if bot._map.turn < bot.stealth_all_in_direct_preferred_until_turn:
            return None
        candidates = BotTargeting.get_target_player_possible_general_location_tiles_sorted(
            bot,
            elimNearbyRange=0,
            cutoffEmergenceRatio=0.3)
        if not candidates:
            return None
        candidate_distances = SearchUtils.build_distance_map_matrix(bot._map, candidates)
        safe_starts = [
            tile for tile in bot._map.get_all_tiles()
            if tile.player == bot.general.player
            and BotStealthAllIn._is_safe_flank_tile(tile, enemy_vision)
        ]
        if not safe_starts:
            return None
        # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
        # when routes tie on distance and length, prefer a launch root with more starting army.
        safe_starts.sort(key=lambda tile: (-tile.army, tile.tile_index))

        distances: dict[int, int] = {}
        parents: dict[int, int | None] = {}
        launch_indexes: dict[int, int] = {}
        frontier: deque[Tile] = deque()
        for start_tile in safe_starts:
            tile_index = start_tile.tile_index
            if tile_index in distances:
                continue
            distances[tile_index] = 0
            parents[tile_index] = None
            launch_indexes[tile_index] = tile_index
            frontier.append(start_tile)

        # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
        # rank frontier entries by the 3:1 surprise-vs-delay cost model (walk + 4 * candidateDist
        # approximates routeLen + 3 * warningTurns) and exact-evaluate only the best few.
        frontier_options: list[tuple[int, int, int, int]] = []
        while frontier:
            current = frontier.popleft()
            current_index = current.tile_index
            current_distance = distances[current_index]
            has_visible_frontier = any(
                enemy_vision.raw[adjacent.tile_index]
                for adjacent in current.movable)
            if has_visible_frontier:
                launch_index = launch_indexes[current_index]
                proxy_cost = (
                    current_distance
                    + (BotStealthAllIn.SURPRISE_TURNS_PER_DELAY + 1)
                    * candidate_distances.raw[current_index])
                frontier_options.append((
                    proxy_cost,
                    -bot._map.tiles_by_index[launch_index].army,
                    launch_index,
                    current_index))
            for adjacent in current.movable:
                adjacent_index = adjacent.tile_index
                if adjacent_index in distances:
                    continue
                if not BotStealthAllIn._is_safe_flank_tile(adjacent, enemy_vision):
                    continue
                distances[adjacent_index] = current_distance + 1
                parents[adjacent_index] = current_index
                launch_indexes[adjacent_index] = launch_indexes[current_index]
                frontier.append(adjacent)

        if not frontier_options:
            return None
        frontier_options.sort()

        best_path: Path | None = None
        best_cost: int | None = None
        for option in frontier_options[:BotStealthAllIn.MAX_FLANK_ROUTE_EVALUATIONS]:
            end_index = option[3]
            path = BotStealthAllIn._reconstruct_flank_path(bot, parents, end_index)
            if (path.start is None or path.tail is None
                    or path.tail.tile == path.start.tile
                    and enemy_vision.raw[path.start.tile.tile_index]):
                continue
            tail_path = BotStealthAllIn._get_shortest_path_to_candidate(
                bot,
                path.tail.tile,
                candidates)
            if tail_path is None or tail_path.tail is None:
                continue
            # the warning clock starts the first step the route army sits on a tile the enemy
            # can see; everything after that is turns the opponent has to defend with.
            route_cost = BotStealthAllIn._compute_route_cost(
                enemy_vision,
                path.tileList + tail_path.tileList[1:])
            if best_cost is None or route_cost < best_cost:
                best_cost = route_cost
                best_path = path

        if best_path is None or best_cost is None:
            return None

        direct_cost = BotStealthAllIn._get_best_direct_route_cost(
            bot,
            candidates,
            enemy_vision)
        if direct_cost is not None and best_cost >= direct_cost:
            # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
            # a 20-turn detour that only saves a few warning turns is strictly worse than all-inning
            # along the short direct path; reject the flank so the normal all-in takes the direct route.
            bot.stealth_all_in_direct_preferred_until_turn = (
                bot._map.turn + BotStealthAllIn.DIRECT_PREFERRED_REPLAN_TURNS)
            logbook.info(
                f"STEALTH_ALLIN_DIRECT_PREFERRED turn={bot._map.turn} "
                f"flankCost={best_cost} directCost={direct_cost} "
                f"launch={best_path.start.tile.x},{best_path.start.tile.y} "
                f"entry={best_path.tail.tile.x},{best_path.tail.tile.y} "
                f"flankLen={best_path.length}")
            return None
        logbook.info(
            f"STEALTH_ALLIN_FLANK_CHOSEN turn={bot._map.turn} "
            f"flankCost={best_cost} directCost={direct_cost} "
            f"launch={best_path.start.tile.x},{best_path.start.tile.y} "
            f"entry={best_path.tail.tile.x},{best_path.tail.tile.y} "
            f"flankLen={best_path.length}")
        return best_path

    # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
    # rebuild one BFS solution path from its frontier tile back to its hidden launch tile.
    @staticmethod
    def _reconstruct_flank_path(
        bot: EklipZBot,
        parents: dict[int, int | None],
        end_index: int,
    ) -> Path:
        """Rebuild a hidden flank path from the BFS parent map."""
        path_indexes: list[int] = []
        current_index: int | None = end_index
        while current_index is not None:
            path_indexes.append(current_index)
            current_index = parents[current_index]
        path_indexes.reverse()
        path = Path()
        for tile_index in path_indexes:
            path.add_next(bot._map.tiles_by_index[tile_index])
        return path

    # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
    # route cost = routeLen + SURPRISE_TURNS_PER_DELAY * warningTurns, where warningTurns counts the
    # steps after the first enemy-visible route tile until the route reaches the general area.
    @staticmethod
    def _compute_route_cost(
        enemy_vision: MapMatrixInterface[bool],
        route_tiles: list[Tile],
    ) -> int:
        """Score a route as length + 3 * turns-spent-visible before the end."""
        moves = len(route_tiles) - 1
        first_visible = moves
        for i, tile in enumerate(route_tiles):
            if i > 0 and enemy_vision.raw[tile.tile_index]:
                first_visible = i
                break
        warning_turns = moves - first_visible
        return moves + BotStealthAllIn.SURPRISE_TURNS_PER_DELAY * warning_turns

    # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
    # the flank must beat the best direct attack route, not just exist: evaluate the shortest
    # candidate-reaching path from each of our largest stacks on the same cost model, since the
    # normal all-in charges along the direct route through (and capturing) enemy land.
    @staticmethod
    def _get_best_direct_route_cost(
        bot: EklipZBot,
        candidates: list[Tile],
        enemy_vision: MapMatrixInterface[bool],
    ) -> int | None:
        """Return the cheapest routeLen + 3*warningTurns direct attack cost, if any route exists."""
        army_tiles = [
            tile for tile in bot._map.get_all_tiles()
            if tile.player == bot.general.player and tile.army > 1]
        army_tiles.sort(key=lambda tile: (-tile.army, tile.tile_index))
        best_cost: int | None = None
        for army_tile in army_tiles[:BotStealthAllIn.DIRECT_ROUTE_EVALUATION_ARMY_TILES]:
            direct_path = BotStealthAllIn._get_shortest_path_to_candidate(
                bot,
                army_tile,
                candidates,
                skip_undiscovered_cities=False)
            if direct_path is None or direct_path.tail is None:
                continue
            route_cost = BotStealthAllIn._compute_route_cost(
                enemy_vision,
                direct_path.tileList)
            if best_cost is None or route_cost < best_cost:
                best_cost = route_cost
        return best_cost

    @staticmethod
    def start_wrp_job(
        bot: EklipZBot,
        start_tile: Tile,
        to_discover: list[Tile],
        initial_army: int,
        generation: int,
    ) -> StealthWrpJob:
        """Run simulator WRP inline or submit a pickled live-map snapshot to a process."""
        target_tile_indexes = [tile.tile_index for tile in to_discover]
        if bot.run_background_work_synchronously:
            cloned_map = BotStealthAllIn._clone_map_for_wrp(bot)
            return BotStealthAllIn._start_wrp_job_on_clone(
                bot,
                cloned_map,
                start_tile.tile_index,
                target_tile_indexes,
                initial_army,
                generation,
                1.0)

        pickle_start = time.perf_counter()
        map_payload = pickle.dumps(bot._map, protocol=pickle.HIGHEST_PROTOCOL)
        pickle_duration = time.perf_counter() - pickle_start
        if bot.wrp_worker_process is None:
            bot.wrp_worker_process = WrpWorkerProcess()
        job = StealthWrpJob(
            generation=generation,
            start_tile_index=start_tile.tile_index,
            done=False,
            result_tile_indexes=None,
            target_tile_indexes=target_tile_indexes,
            initial_army=initial_army,
            time_limit=3.0,
            background_process=True,
            pickle_duration_sec=pickle_duration,
            payload_bytes=len(map_payload))
        request = WrpRequest(
            generation=generation,
            map_payload=map_payload,
            start_tile_index=start_tile.tile_index,
            target_tile_indexes=target_tile_indexes,
            initial_army=initial_army,
            time_limit=3.0)
        bot.wrp_worker_process.submit(request)
        logbook.info(
            f"STEALTH_ALLIN_WRP_START turn={bot._map.turn} "
            f"generation={generation} start={start_tile.tile_index} "
            f"targets={len(target_tile_indexes)} initialArmy={initial_army} "
            f"timeLimit=3.000 process=True "
            f"pickleSec={pickle_duration:.4f} payloadBytes={len(map_payload)}")
        return job

    @staticmethod
    def poll_wrp_worker_results(bot: EklipZBot) -> None:
        """Drain process results and apply only results for currently pending jobs."""
        worker = bot.wrp_worker_process
        if worker is None:
            return
        pending_jobs: list[StealthWrpJob] = []
        if bot.stealth_hunt_job is not None and not bot.stealth_hunt_job.done:
            pending_jobs.append(bot.stealth_hunt_job)
        state = bot.stealth_all_in
        if (state is not None
                and state.wrp_job is not None
                and not state.wrp_job.done):
            pending_jobs.append(state.wrp_job)

        for result in worker.get_results_nowait():
            for job in pending_jobs:
                if job.generation != result.generation or job.done:
                    continue
                job.result_tile_indexes = result.tile_indexes
                job.duration_sec = result.duration_sec
                job.done = True
                result_length = (
                    len(result.tile_indexes)
                    if result.tile_indexes is not None
                    else 0)
                logbook.info(
                    f"STEALTH_ALLIN_WRP_DONE generation={result.generation} "
                    f"start={job.start_tile_index} len={result_length} "
                    f"durationSec={result.duration_sec:.4f} "
                    f"process=True")
                break

        if pending_jobs and not worker.is_alive():
            raise RuntimeError(
                "WRP worker process exited with pending route work")

    @staticmethod
    def _raise_if_pending_wrp_worker_exited(bot: EklipZBot) -> None:
        """Fail clearly rather than leave a route waiting on a dead process."""
        worker = bot.wrp_worker_process
        if worker is None or not worker.is_alive():
            raise RuntimeError(
                "WRP worker process exited before publishing a pending result")

    @staticmethod
    def _start_wrp_job_on_clone(
        bot: EklipZBot,
        cloned_map: MapBase,
        start_tile_index: int,
        target_tile_indexes: list[int],
        initial_army: int,
        generation: int,
        time_limit: float,
    ) -> StealthWrpJob:
        """Run a WRP job synchronously on a caller-created private map clone."""
        job = StealthWrpJob(
            generation=generation,
            start_tile_index=start_tile_index,
            done=False,
            result_tile_indexes=None,
            target_tile_indexes=target_tile_indexes,
            initial_army=initial_army,
            time_limit=time_limit,
            background_process=False)
        logbook.info(
            f"STEALTH_ALLIN_WRP_START turn={bot._map.turn} "
            f"generation={generation} start={start_tile_index} "
            f"targets={len(target_tile_indexes)} initialArmy={initial_army} "
            f"timeLimit={time_limit:.3f} process=False")
        BotStealthAllIn._run_wrp_job(job, cloned_map)
        return job

    @staticmethod
    def convert_wrp_job_result(map: MapBase, job: StealthWrpJob) -> Path | None:
        """Convert a completed job's stable tile indexes to a route on the live map."""
        if not job.done:
            raise RuntimeError("Cannot convert an unfinished stealth WRP job")
        if job.result_tile_indexes is None:
            return None
        path = Path()
        for tile_index in job.result_tile_indexes:
            path.add_next(map.tiles_by_index[tile_index])
        return path

    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # compare stealth and normal gathers at the same hidden launch root and horizon.
    @staticmethod
    def get_stealth_all_in_move(
        bot: EklipZBot,
        defense_critical_tiles: set[Tile],
    ) -> Move | None:
        """Plan a hidden flank, gather there, and commit the assembled attack route."""
        if not BotStealthAllIn.is_stealth_all_in_active(bot):
            BotStealthAllIn.clear_uncommitted_state(bot)
            return None

        enemy_vision = BotStealthAllIn.build_enemy_vision_matrix(bot)
        vision_tile_count = sum(1 for visible in enemy_vision.raw if visible)
        state = bot.stealth_all_in
        pending_state_before_replan = state
        if state is not None and state.committed_route is not None:
            return None

        candidates = BotTargeting.get_target_player_possible_general_location_tiles_sorted(
            bot,
            elimNearbyRange=0,
            cutoffEmergenceRatio=0.3)
        # Tests/test_GeneralHunting.py::GeneralPredictionTests.test_should_keep_diving_when_all_in_and_not_much_left_to_search_regardless_of_opp_army:
        # with no unknown general tiles left there is nothing to stealth-route; bail without
        # wiping curPath, which the endgame dive may still be executing.
        if not candidates:
            if state is not None:
                bot.stealth_all_in = None
            return None
        # frontier-rebased states use a degenerate single-tile flank path whose head is already
        # inside enemy vision on purpose; only replan real flank paths that became visible.
        needs_replan = (
            state is None
            or state.launch_tile.player != bot.general.player
            or (state.flank_path.length > 0
                and any(
                    enemy_vision.raw[tile.tile_index]
                    for tile in state.flank_path.tileList)))
        if needs_replan:
            candidates = BotTargeting.get_target_player_possible_general_location_tiles_sorted(
                bot,
                elimNearbyRange=0,
                cutoffEmergenceRatio=0.3)
            flank_path = BotStealthAllIn.find_stealth_flank_path(bot, enemy_vision)
            if flank_path is None or flank_path.start is None or flank_path.tail is None:
                bot.stealth_all_in = None
                # only clear curPath when it is a gather this planner installed; a live dive path
                # belongs to other logic and must not be wiped by a failed stealth replan.
                if isinstance(bot.curPath, Gather.GatherCapturePlan):
                    bot.curPath = None
                logbook.info(
                    f"STEALTH_ALLIN_PLAN turn={bot._map.turn} launch=None entry=None "
                    f"flankLen=0 visionTiles={vision_tile_count} "
                    f"candidates={len(candidates)} launchTurn=None")
                return None

            bot.stealth_all_in_generation += 1
            state = StealthAllInState(
                launch_tile=flank_path.start.tile,
                entry_tile=flank_path.tail.tile,
                flank_path=flank_path,
                launch_turn=(
                    bot._map.turn
                    + BotCombatOps.get_all_in_hit_general_turns(bot)),
                wrp_job=None,
                committed_route=None,
                committed_turn=-1,
                last_route_move=None,
                used_normal_gather_fallback_turns=0,
                generation=bot.stealth_all_in_generation)
            bot.stealth_all_in = state
            # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
            # a rebuilt plan starts its own gather budget; consecutive kill-check failures are
            # only meaningful while they all hit the same launch plan.
            bot.stealth_all_in_cannot_kill_counter = 0
            logbook.info(
                f"STEALTH_ALLIN_PLAN turn={bot._map.turn} "
                f"launch={state.launch_tile.x},{state.launch_tile.y} "
                f"entry={state.entry_tile.x},{state.entry_tile.y} "
                f"flankLen={state.flank_path.length} visionTiles={vision_tile_count} "
                f"candidates={len(candidates)} launchTurn={state.launch_turn}")

        if state is None:
            raise AssertionError("Stealth plan creation must produce state")
        if candidates is None:
            candidates = BotTargeting.get_target_player_possible_general_location_tiles_sorted(
                bot,
                elimNearbyRange=0,
                cutoffEmergenceRatio=0.3)

        remaining_turns = max(1, state.launch_turn - bot._map.turn)
        move_time_remaining = max(0.0, BotTimings.get_remaining_move_time(bot))
        gather_time_limit = min(0.05, move_time_remaining)
        normal_negatives = set(defense_critical_tiles)
        stealth_negatives = set(normal_negatives)
        stealth_negatives.update(
            tile for tile in bot._map.get_all_tiles()
            if tile.player == bot.general.player
            and enemy_vision.raw[tile.tile_index])
        # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
        # hold the root and horizon constant for the settled 70% gather comparison.
        stealth_plan = Gather.gather_approximate_turns_to_tiles(
            bot._map,
            rootTiles=[state.launch_tile],
            approximateTargetTurns=remaining_turns,
            asPlayer=bot.general.player,
            gatherMatrix=None,
            captureMatrix=None,
            negativeTiles=stealth_negatives,
            prioritizeCaptureHighArmyTiles=False,
            skipTiles=None,
            useTrueValueGathered=True,
            includeGatherPriorityAsEconValues=True,
            includeCapturePriorityAsEconValues=True,
            logDebug=False,
            timeLimit=gather_time_limit,
            viewInfo=bot.viewInfo if bot.info_render_gather_values else None)
        normal_plan = Gather.gather_approximate_turns_to_tiles(
            bot._map,
            rootTiles=[state.launch_tile],
            approximateTargetTurns=remaining_turns,
            asPlayer=bot.general.player,
            gatherMatrix=None,
            captureMatrix=None,
            negativeTiles=normal_negatives,
            prioritizeCaptureHighArmyTiles=False,
            skipTiles=None,
            useTrueValueGathered=True,
            includeGatherPriorityAsEconValues=True,
            includeCapturePriorityAsEconValues=True,
            logDebug=False,
            timeLimit=gather_time_limit,
            viewInfo=bot.viewInfo if bot.info_render_gather_values else None)
        stealth_army = stealth_plan.gathered_army if stealth_plan is not None else 0
        normal_army = normal_plan.gathered_army if normal_plan is not None else 0
        used_normal_fallback = (
            normal_plan is not None
            and (stealth_plan is None or stealth_army < normal_army * 0.7))
        gather_plan = normal_plan if used_normal_fallback else stealth_plan
        if used_normal_fallback:
            state.used_normal_gather_fallback_turns += 1

        gather_move = gather_plan.get_first_move() if gather_plan is not None else None
        if gather_plan is None:
            bot.curPath = None
            bot.gatherNodes = None
        else:
            bot.curPath = gather_plan
            bot.gatherNodes = gather_plan.root_nodes
        logbook.info(
            f"STEALTH_ALLIN_GATHER turn={bot._map.turn} "
            f"stealthArmy={stealth_army} normalArmy={normal_army} "
            f"usedFallback={used_normal_fallback} move={gather_move}")

        # Tests/test_AllIn.py::AllInTests.test_should_stop_allinning_and_city_after_failed_attack__long
        # and test_should_stealth_flank_all_in_when_enemy_general_unknown:
        # do not consume normal all-in fallback turns when the projected launch cannot kill.
        pre_gate_path = BotStealthAllIn._get_shortest_path_to_candidate(
            bot,
            state.entry_tile,
            candidates)
        projected_launch_army = (
            (gather_plan.gathered_army if gather_plan is not None else 0)
            + state.launch_tile.army
            - state.flank_path.length)
        route_safety = (
            BotStealthAllIn._evaluate_route_safety(
                bot,
                pre_gate_path,
                [pre_gate_path.tail.tile],
                projected_launch_army,
                bot.targetPlayer,
                distance_offset=state.flank_path.length)
            if pre_gate_path is not None and pre_gate_path.tail is not None
            else StealthRouteSafetyEstimate(None, 1, False, []))
        required_launch_army = route_safety.max_enemy_defense * 1.2 + 2
        # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
        # the gather projection only says the stack WILL be at the launch tile; the real head army
        # decides whether we can launch right now. When it already can, skip the rest of the gather
        # window and commit immediately. When the gather window has already ended but the head
        # still cannot execute the route, that is a cannot-kill tick as well (the gather never
        # materialized), which both keeps gathering and drives the desperation dive on schedule.
        # This stops the t459 commit that sent a 4-army head down an 8-tile front of enemy tiles.
        head_route_safety = (
            BotStealthAllIn._evaluate_route_safety(
                bot,
                pre_gate_path,
                [pre_gate_path.tail.tile],
                state.launch_tile.army - state.flank_path.length,
                bot.targetPlayer,
                distance_offset=state.flank_path.length)
            if pre_gate_path is not None and pre_gate_path.tail is not None
            else StealthRouteSafetyEstimate(None, 1, False, []))
        head_ready_now = head_route_safety.safe_at_every_reveal
        if not head_ready_now and (
                projected_launch_army < required_launch_army
                or not route_safety.safe_at_every_reveal):
            bot.stealth_all_in_cannot_kill_counter += 1
            if (bot.stealth_all_in_cannot_kill_counter
                    < BotStealthAllIn.CANNOT_KILL_GATHER_TURNS_BEFORE_DIVE):
                # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
                # the old abort wiped the plan and curPath every turn, so each turn replanned a
                # different launch tile and the stack scattered via whatever fallback move ran
                # instead; keep the plan alive and run the stealth gather for real so the
                # projected launch army can actually materialize at a stable launch tile.
                logbook.info(
                    f"STEALTH_ALLIN_WAIT turn={bot._map.turn} reason=cannot_kill "
                    f"projectedArmy={projected_launch_army} "
                    f"enemyDefense={route_safety.max_enemy_defense} "
                    f"minArmyAtReveal={route_safety.min_army_at_reveal} "
                    f"routeLen={pre_gate_path.length if pre_gate_path else 0} "
                    f"candidateResults={BotStealthAllIn._format_candidate_safety_results(route_safety)} "
                    f"required={required_launch_army} "
                    f"counter={bot.stealth_all_in_cannot_kill_counter}")
                if gather_move is not None:
                    return gather_move
                return None
            # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
            # when the enemy fog-defense estimate grows faster than the stack can ever gather,
            # the kill-check can never pass and the losing all-in stalls forever while the
            # enemy wins on economy; after enough consecutive failures commit the route anyway
            # because a losing all-in has to gamble rather than never attack.
            state.is_desperation_dive = True
            # The hidden launch tile cannot be used for the dive: the gather has only had a few
            # of its planned turns, so the launch tile still holds ~1-2 army while the real
            # stack sits elsewhere (a desperate route committed from an empty launch tile just
            # dies broken_head next turn). Relaunch the dive from the largest friendly stack.
            dive_start_tile = BotStealthAllIn._get_desperation_dive_start_tile(bot)
            if dive_start_tile is not None and dive_start_tile is not state.launch_tile:
                state.launch_tile = dive_start_tile
                state.entry_tile = dive_start_tile
                state.flank_path = Path()
                state.flank_path.add_next(dive_start_tile)
                state.wrp_job = None
            logbook.info(
                f"STEALTH_ALLIN_DESPERATE turn={bot._map.turn} "
                f"projectedArmy={projected_launch_army} "
                f"enemyDefense={route_safety.max_enemy_defense} "
                f"required={required_launch_army} "
                f"consecutiveFails={bot.stealth_all_in_cannot_kill_counter} "
                f"diveStart={state.launch_tile.x},{state.launch_tile.y} "
                f"diveStartArmy={state.launch_tile.army}")
        else:
            bot.stealth_all_in_cannot_kill_counter = 0

        if state.wrp_job is None:
            # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
            # a desperation dive routes with the stack's real current army, not the gather
            # projection that the launch tile will never see.
            initial_army = (
                state.launch_tile.army
                if state.is_desperation_dive
                else (stealth_plan.gathered_army - state.flank_path.length
                      if stealth_plan is not None
                      else state.launch_tile.army))
            state.wrp_job = BotStealthAllIn.start_wrp_job(
                bot,
                state.entry_tile,
                candidates,
                initial_army,
                state.generation)

        # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
        # a desperation dive skips the launch-turn gather wait; every extra turn of gathering
        # lets the enemy defense estimate outgrow the stack further.
        # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
        # a head that can already execute the route also skips the wait; gathering longer only
        # delays the kill past the 32-turn window the top all-in should comfortably meet.
        if (bot._map.turn < state.launch_turn
                and gather_move is not None
                and not state.is_desperation_dive
                and not head_ready_now):
            return gather_move

        wrp_path = BotStealthAllIn._get_wrp_path(bot, state)
        if wrp_path is None:
            BotStealthAllIn.clear_uncommitted_state(bot)
            return None
        route = BotStealthAllIn._combine_routes(
            state.flank_path,
            state.entry_tile,
            wrp_path)
        if route.length == 0:
            bot.stealth_all_in = None
            bot.curPath = None
            logbook.info(
                f"STEALTH_ALLIN_ABORT turn={bot._map.turn} reason=route_complete")
            return None
        # Tests/test_AllIn.py::AllInTests.test_should_stop_allinning_and_city_after_failed_attack__long:
        # leave legacy fallback available when the hidden launch root cannot move even one army.
        if route.start is None or route.start.tile.army <= 1:
            BotStealthAllIn._abort_committed_route(bot, "broken_head")
            return None

        # Safe-front commit (losing all-in only; hunts stay strict in get_undefendable_hunt_move):
        # evaluate the whole combined route over all WRP candidates. If a later reveal is unsafe,
        # commit only the prefix that ends one step before the first unsafe reveal, then re-check
        # from the frontier when the segment completes (frontier rebase in get_committed_route_move).
        # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
        # a desperation dive deliberately skips this safety evaluation entirely; it exists
        # precisely because the safety check can never pass in the current game state.
        state.is_truncated_front = False
        route_safety = (
            StealthRouteSafetyEstimate(None, 1, True, [])
            if state.is_desperation_dive
            else BotStealthAllIn._evaluate_route_safety(
                bot,
                route,
                [
                    bot._map.tiles_by_index[tile_index]
                    for tile_index in state.wrp_job.target_tile_indexes],
                route.start.tile.army,
                bot.targetPlayer))
        if not route_safety.safe_at_every_reveal:
            first_unsafe_reveal = min(
                (result.reveal_turns
                 for result in route_safety.candidate_results
                 if result.remaining_army < result.required_army),
                default=0)
            if first_unsafe_reveal <= 1:
                logbook.info(
                    f"STEALTH_ALLIN_ABORT turn={bot._map.turn} reason=no_safe_front "
                    f"firstUnsafeReveal={first_unsafe_reveal} routeLen={route.length} "
                    f"candidateResults={BotStealthAllIn._format_candidate_safety_results(route_safety)}")
                BotStealthAllIn.clear_uncommitted_state(bot)
                return None
            full_route_length = route.length
            route = route.get_subsegment(first_unsafe_reveal - 1)
            state.is_truncated_front = True
            logbook.info(
                f"STEALTH_ALLIN_SAFE_FRONT turn={bot._map.turn} "
                f"frontLen={route.length} fullLen={full_route_length} "
                f"firstUnsafeReveal={first_unsafe_reveal} "
                f"candidateResults={BotStealthAllIn._format_candidate_safety_results(route_safety)}")

        # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
        # never commit a segment the head stack cannot physically survive walking. The pre-gate
        # shortest path is only an approximation of the WRP route, so verify the real combined
        # route (or truncated front) before locking in. A too-weak head ticks the cannot-kill
        # counter and keeps gathering, exactly like the pre-launch cannot-kill wait turns.
        if not state.is_desperation_dive:
            remaining_army = route.start.tile.army
            head_survivable = True
            for step_index, tile in enumerate(route.tileList):
                if step_index == 0:
                    continue
                if not bot._map.is_tile_on_team_with(
                        tile,
                        bot.general.player):
                    remaining_army -= tile.army + 1
                if remaining_army < 1:
                    head_survivable = False
                    break
            if not head_survivable:
                # Tests/test_Flank.py::FlankTests.test_should_not_loop_on_proactive_flank_vision_defense:
                # do NOT tick the cannot-kill counter here — a weak head usually means the gather
                # is still converging on the launch tile, and counting these as failures fires the
                # desperation dive ~6 turns early (t301 in that test), which commits a 24-step
                # backtracking WRP route that trips the no-repetition guard. The desperation dive
                # is only for projected-impossibility, which the pre-gate eval still counts.
                logbook.info(
                    f"STEALTH_ALLIN_WAIT turn={bot._map.turn} reason=head_too_weak "
                    f"headArmy={route.start.tile.army} routeLen={route.length} "
                    f"counter={bot.stealth_all_in_cannot_kill_counter}")
                if gather_move is not None:
                    return gather_move
                return None

        state.committed_route = route
        state.committed_turn = bot._map.turn
        bot.curPath = None
        bot.curPathPrio = -1
        logbook.info(
            f"STEALTH_ALLIN_COMMIT turn={bot._map.turn} routeLen={route.length} "
            f"headArmy={route.start.tile.army} truncated={state.is_truncated_front} "
            f"desperate={state.is_desperation_dive}")
        return None

    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # keep the committed route in control across turns except for explicit terminal conditions.
    @staticmethod
    def get_committed_route_move(
        bot: EklipZBot,
        threat: ThreatObj | None,
        defense_critical_tiles: set[Tile],
        king_kill_path: Path | None,
        race_chance: float,
    ) -> Move | None:
        """Execute one committed route step, allowing only specified interruptions."""
        state = bot.stealth_all_in
        if state is None or state.committed_route is None:
            return None
        bot.last_stealth_route_defense_interrupt = None
        if bot.targetPlayerExpectedGeneralLocation.isGeneral:
            route = state.committed_route
            direct_move = route.get_first_move()
            known_general = bot.targetPlayerExpectedGeneralLocation
            # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
            # hand an immediately capturable revealed general to the existing direct-attack flow.
            if (
                direct_move is not None
                and direct_move.dest.tile_index == known_general.tile_index
                and direct_move.dest.isGeneral
                and direct_move.dest.player == bot.targetPlayer
                and BotStealthAllIn._is_owned_by_bot(bot, direct_move.source)
                and direct_move.source.army > direct_move.dest.army + 1
                and direct_move.dest in direct_move.source.movable
            ):
                BotStealthAllIn._abort_committed_route(bot, "general_known")
                logbook.info(
                    f"STEALTH_ALLIN_GENERAL_KNOWN_HANDOFF turn={bot._map.turn} "
                    f"move={direct_move} sourceArmy={direct_move.source.army} "
                    f"generalArmy={direct_move.dest.army}")
                return direct_move
            BotStealthAllIn._abort_committed_route(bot, "general_known")
            return None

        route = state.committed_route
        if route.length == 0 or route.start is None:
            # Safe-front re-check: a truncated front segment ends one step before an unsafe reveal,
            # so rebase the plan at the frontier head and let planning re-evaluate from there.
            if (state.is_truncated_front
                    and not state.is_undefendable_hunt
                    and route.start is not None
                    and BotStealthAllIn._is_owned_by_bot(bot, route.start.tile)):
                head_tile = route.start.tile
                bot.stealth_all_in_generation += 1
                state.launch_tile = head_tile
                state.entry_tile = head_tile
                state.flank_path = Path()
                state.flank_path.add_next(head_tile)
                state.wrp_job = None
                state.committed_route = None
                state.launch_turn = bot._map.turn
                state.committed_turn = -1
                state.last_route_move = None
                state.is_truncated_front = False
                state.generation = bot.stealth_all_in_generation
                bot.curPath = None
                bot.curPathPrio = -1
                logbook.info(
                    f"STEALTH_ALLIN_FRONT_REBASE turn={bot._map.turn} "
                    f"head={head_tile.x},{head_tile.y} army={head_tile.army}")
                return None
            BotStealthAllIn._abort_committed_route(bot, "route_complete")
            return None

        head_tile = route.start.tile
        last_route_move = state.last_route_move
        if (
            last_route_move is not None
            and BotStealthAllIn._is_owned_by_bot(bot, last_route_move.source)
            and last_route_move.source.army > 1
            and not BotStealthAllIn._is_owned_by_bot(bot, last_route_move.dest)
            and BotRepetition.dropped_move(bot)
        ):
            logbook.info(
                f"STEALTH_ALLIN_ROUTE_MOVE turn={bot._map.turn} "
                f"move={last_route_move} remaining={route.length} replay=True")
            return last_route_move

        if not BotStealthAllIn._is_owned_by_bot(bot, head_tile) or head_tile.army <= 1:
            BotStealthAllIn._abort_committed_route(bot, "broken_head")
            return None
        next_move = route.get_first_move()
        if (next_move is None
                or next_move.source != head_tile
                or next_move.dest not in head_tile.movable):
            BotStealthAllIn._abort_committed_route(bot, "broken_next_move")
            return None

        # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
        # preserve lethal general-defense interruptions while executing the committed route.
        if (threat is not None
                and threat.threatType == ThreatType.Kill
                and threat.path.tail.tile.isGeneral):
            defense_move, _ = BotDefense.get_defense_moves(
                bot,
                defense_critical_tiles,
                king_kill_path,
                race_chance)
            if defense_move is not None:
                aborted_route = defense_move.source == head_tile
                bot.last_stealth_route_defense_interrupt = (
                    StealthRouteDefenseInterrupt(
                        turn=bot._map.turn,
                        move=defense_move,
                        generation=state.generation,
                        launch_tile_index=state.launch_tile.tile_index,
                        aborted_route=aborted_route))
                logbook.info(
                    f"STEALTH_ALLIN_DEFENSE_INTERRUPT turn={bot._map.turn} "
                    f"move={defense_move} routeHead={head_tile} "
                    f"threatPlayer={threat.threatPlayer} threatTurns={threat.turns} "
                    f"threatStart={threat.path.start.tile} threatTail={threat.path.tail.tile}")
                if aborted_route:
                    if state.is_undefendable_hunt:
                        bot.stealth_hunt_excluded_start_tile_indexes.update({
                            state.launch_tile.tile_index,
                            head_tile.tile_index,
                            defense_move.dest.tile_index})
                    bot.stealth_all_in = None
                    bot.curPath = None
                    bot.curPathPrio = -1
                return defense_move

        state.last_route_move = next_move
        route.remove_start()
        bot.curPath = None
        bot.curPathPrio = -1
        logbook.info(
            f"STEALTH_ALLIN_ROUTE_MOVE turn={bot._map.turn} "
            f"move={next_move} remaining={route.length} replay=False")
        return next_move

    @staticmethod
    def clear_uncommitted_state(bot: EklipZBot) -> None:
        """Clear pending stealth gathers without interrupting committed routes."""
        state = bot.stealth_all_in
        if state is not None and state.committed_route is None:
            bot.stealth_all_in = None
            bot.curPath = None
            bot.curPathPrio = -1
        # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
        # the fail counter belongs to the abandoned uncommitted plan; a fresh plan must get a
        # fresh gather budget before its own desperation dive is allowed.
        bot.stealth_all_in_cannot_kill_counter = 0

    # Tests/test_AllIn.py resume support: rebuild committed-route state from a mid-all-in txtmap so
    # the bot keeps executing the route it committed to live instead of replanning.
    @staticmethod
    def load_committed_route_from_resume_data(bot: EklipZBot, resume_data: dict[str, str]) -> None:
        """Restore a committed stealth/WRP route saved into a txtmap, if present."""
        if 'bot_stealth_committed_route' not in resume_data:
            return
        committed_route = TextMapLoader.parse_path(
            bot._map, resume_data['bot_stealth_committed_route'])
        if committed_route is None or committed_route.length == 0 or committed_route.start is None:
            logbook.warn(
                f'STEALTH_ALLIN_RESUME turn={bot._map.turn} could not parse committed route, '
                'dropping persisted stealth state')
            return
        launch_tile = BotStateQueries.parse_tile_str(bot, resume_data['bot_stealth_launch_tile'])
        entry_tile = BotStateQueries.parse_tile_str(bot, resume_data['bot_stealth_entry_tile'])
        flank_path = TextMapLoader.parse_path(
            bot._map, resume_data.get('bot_stealth_flank_path', 'None'))
        if flank_path is None or flank_path.length == 0:
            flank_path = Path()
            flank_path.add_next(entry_tile)
        generation = int(resume_data['bot_stealth_generation'])
        # Post-resume WRP jobs must not collide with generations that produced this route.
        bot.stealth_all_in_generation = max(
            bot.stealth_all_in_generation,
            int(resume_data.get('bot_stealth_all_in_generation', str(generation))))
        bot.stealth_all_in = StealthAllInState(
            launch_tile=launch_tile,
            entry_tile=entry_tile,
            flank_path=flank_path,
            launch_turn=int(resume_data['bot_stealth_launch_turn']),
            wrp_job=None,
            committed_route=committed_route,
            committed_turn=int(resume_data['bot_stealth_committed_turn']),
            last_route_move=None,
            used_normal_gather_fallback_turns=int(
                resume_data.get('bot_stealth_gather_fallback_turns', '0')),
            generation=generation,
            is_undefendable_hunt=BotStateQueries.parse_bool(
                bot, resume_data['bot_stealth_is_undefendable_hunt']),
            is_truncated_front=BotStateQueries.parse_bool(
                bot, resume_data.get('bot_stealth_is_truncated_front', 'False')),
            is_desperation_dive=BotStateQueries.parse_bool(
                bot, resume_data.get('bot_stealth_is_desperation_dive', 'False')))
        logbook.info(
            f'STEALTH_ALLIN_RESUME turn={bot._map.turn} restored committed route '
            f'remaining={committed_route.length} launch={launch_tile.x},{launch_tile.y} '
            f'generation={generation} isHunt={bot.stealth_all_in.is_undefendable_hunt}')

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend
    # and Tests/test_GeneralHunting.py::GeneralPredictionTests.test_should_not_dive_few_fog_tiles_when_cannot_kill:
    # find the nearest possible-general candidate without paying for a WRP clone.
    @staticmethod
    def _get_shortest_path_to_candidate(
        bot: EklipZBot,
        start_tile: Tile,
        candidates: list[Tile],
        skip_undiscovered_cities: bool = True,
    ) -> Path | None:
        """Return a shortest map path from a launch tile to the first candidate."""
        candidate_indexes = {tile.tile_index for tile in candidates}
        # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
        # WRP routes treat undiscovered predicted cities as walls (a committed all-in broke trying
        # to path through fog city 14,9), so route estimates must skip them the same way. Direct
        # attack estimates opt out because the real all-in charges through and captures them.
        skip_tiles: TileSet | None = None
        if (skip_undiscovered_cities
                and not bot._map.is_walled_city_game
                and not bot._map.is_low_cost_city_game):
            skip_tiles = {
                tile for tile in bot._map.get_all_tiles()
                if tile.isCity
                and not tile.discovered
                and tile.tile_index not in candidate_indexes}
        return SearchUtils.breadth_first_dynamic(
            bot._map,
            [start_tile],
            partial(
                BotStealthAllIn._is_hunt_candidate_goal,
                candidate_indexes=candidate_indexes),
            maxDepth=bot._map.cols * bot._map.rows,
            noNeutralCities=False,
            skipTiles=skip_tiles,
            searchingPlayer=bot.general.player,
            noLog=True,
            noVal=True)

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # keep the shortest-path goal predicate typed and reusable with a bound candidate set.
    @staticmethod
    def _is_hunt_candidate_goal(
        tile: Tile,
        priority_object: tuple[object, ...],
        candidate_indexes: set[int],
    ) -> bool:
        """Return whether a shortest-path search has reached a candidate tile."""
        return tile.tile_index in candidate_indexes

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend
    # and Tests/test_GeneralHunting.py::GeneralPredictionTests.test_should_not_dive_few_fog_tiles_when_cannot_kill:
    # use QK fog defense plus visible enemy stacks near the candidate.
    @staticmethod
    def _get_enemy_defense_estimate(
        bot: EklipZBot,
        enemy_player: int,
        nearest_candidate: Tile,
        route_length: int,
    ) -> int:
        """Estimate QK fog defense plus visible enemy armies within route reach."""
        fog_defense = max(
            1,
            BotCombatOps.get_fog_defense_amount_available_for_tiles(
                bot,
                bot.alt_en_gen_positions[enemy_player],
                enemy_player,
                fog_defense_turns=0,
                fog_reach_turns=5))
        visible_defense = sum(
            tile.army - 1
            for tile in bot._map.get_all_tiles()
            if tile.visible
            and tile.player == enemy_player
            and tile.army >= 3
            and bot._map.get_distance_between(tile, nearest_candidate) <= route_length)
        return fog_defense + visible_defense

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # use a stable nearest candidate for route-reach visible-defense estimates.
    @staticmethod
    def _get_nearest_candidate(
        bot: EklipZBot,
        start_tile: Tile,
        candidates: list[Tile],
    ) -> Tile | None:
        """Return the candidate with the shortest map distance from a launch tile."""
        if not candidates:
            return None
        nearest_candidate = candidates[0]
        nearest_distance = bot._map.get_distance_between(start_tile, nearest_candidate)
        for candidate in candidates[1:]:
            distance = bot._map.get_distance_between(start_tile, candidate)
            if (distance < nearest_distance
                    or (distance == nearest_distance
                        and candidate.tile_index < nearest_candidate.tile_index)):
                nearest_candidate = candidate
                nearest_distance = distance
        return nearest_candidate

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # use a large non-general army unless the unthreatened general is the only strong launch tile.
    @staticmethod
    def _get_hunt_army_tile(
        bot: EklipZBot,
        threat: ThreatObj | None,
        minimum_army: float,
        excluded_tile_indexes: set[int],
    ) -> Tile | None:
        """Choose the largest eligible friendly launch tile for an undefendable hunt."""
        non_general_tiles = [
            tile for tile in bot._map.get_all_tiles()
            if tile.player == bot.general.player
            and not tile.isGeneral
            and tile.army > 1
            and tile.tile_index not in excluded_tile_indexes]
        big_non_general_tiles = [
            tile for tile in non_general_tiles
            if tile.army >= minimum_army]
        if big_non_general_tiles:
            return max(
                big_non_general_tiles,
                key=lambda tile: (tile.army, -tile.tile_index))
        if (threat is None
                and bot.general.tile_index not in excluded_tile_indexes
                and bot.general.army >= minimum_army):
            return bot.general
        return None

    # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
    # a desperation dive must start from the army that actually exists, not the hidden launch
    # tile whose gather has barely begun; the general itself never dives (losing it ends the
    # game outright).
    @staticmethod
    def _get_desperation_dive_start_tile(bot: EklipZBot) -> Tile | None:
        """Return the largest non-general friendly tile to launch a desperation dive from."""
        best_tile: Tile | None = None
        for tile in bot._map.get_all_tiles():
            if (tile.player != bot.general.player
                    or tile.isGeneral
                    or tile.army <= 1):
                continue
            if best_tile is None or tile.army > best_tile.army:
                best_tile = tile
        return best_tile

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # subtract predicted capture costs before checking every newly revealed candidate.
    @staticmethod
    def _get_min_army_at_candidate_reveal(
        bot: EklipZBot,
        route: Path,
        candidates: list[Tile],
        initial_army: int,
    ) -> int | None:
        """Return the minimum remaining army when a route reveals a candidate."""
        candidate_indexes = {tile.tile_index for tile in candidates}
        if route.start is None or not candidate_indexes:
            return None
        remaining_army = initial_army
        min_army_at_reveal: int | None = None
        for step_index, tile in enumerate(route.tileList):
            if (step_index > 0
                    and not bot._map.is_tile_on_team_with(
                        tile,
                        bot.general.player)):
                remaining_army -= tile.army + 1
            if (tile.tile_index in candidate_indexes
                    or any(
                        adjacent.tile_index in candidate_indexes
                        for adjacent in tile.adjacents)):
                min_army_at_reveal = (
                    remaining_army
                    if min_army_at_reveal is None
                    else min(min_army_at_reveal, remaining_army))
        return min_army_at_reveal

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend
    # and test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # count only visible defenders that can reach a candidate by its reveal turn.
    @staticmethod
    def _evaluate_route_safety(
        bot: EklipZBot,
        route: Path,
        candidates: list[Tile],
        initial_army: int,
        enemy_player: int,
        distance_offset: int = 0,
    ) -> StealthRouteSafetyEstimate:
        """Check capture costs and reachable visible defense at candidate reveals."""
        fog_defense = max(
            1,
            BotCombatOps.get_fog_defense_amount_available_for_tiles(
                bot,
                bot.alt_en_gen_positions[enemy_player],
                enemy_player,
                fog_defense_turns=0,
                fog_reach_turns=5))
        visible_enemy_tiles = [
            tile for tile in bot._map.get_all_tiles()
            if tile.visible and tile.player == enemy_player and tile.army >= 3]
        candidate_indexes = {tile.tile_index for tile in candidates}
        if route.start is None or not candidate_indexes:
            return StealthRouteSafetyEstimate(None, fog_defense, False, [])

        remaining_army = initial_army
        min_army_at_reveal: int | None = None
        max_enemy_defense = fog_defense
        safe_at_every_reveal = True
        candidate_results: list[StealthCandidateSafety] = []
        revealed_candidates: set[int] = set()
        for step_index, tile in enumerate(route.tileList):
            if (step_index > 0
                    and not bot._map.is_tile_on_team_with(
                        tile,
                        bot.general.player)):
                remaining_army -= tile.army + 1
            for candidate in candidates:
                if (candidate.tile_index in revealed_candidates
                        or (candidate.tile_index != tile.tile_index
                            and candidate not in tile.adjacents)):
                    continue
                revealed_candidates.add(candidate.tile_index)
                reveal_turns = distance_offset + step_index
                enemy_defense = fog_defense + sum(
                    enemy_tile.army - 1
                    for enemy_tile in visible_enemy_tiles
                    if bot._map.get_distance_between(
                        enemy_tile,
                        candidate) <= reveal_turns)
                required_army = enemy_defense * 1.2 + 2
                candidate_results.append(StealthCandidateSafety(
                    tile_index=candidate.tile_index,
                    reveal_turns=reveal_turns,
                    remaining_army=remaining_army,
                    enemy_defense=enemy_defense,
                    required_army=required_army))
                max_enemy_defense = max(max_enemy_defense, enemy_defense)
                min_army_at_reveal = (
                    remaining_army
                    if min_army_at_reveal is None
                    else min(min_army_at_reveal, remaining_army))
                if remaining_army < required_army:
                    safe_at_every_reveal = False

        return StealthRouteSafetyEstimate(
            min_army_at_reveal,
            max_enemy_defense,
            safe_at_every_reveal and min_army_at_reveal is not None,
            candidate_results)

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend
    # and test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # keep failed route safety decisions attributable to individual candidate reveals.
    @staticmethod
    def _format_candidate_safety_results(
        estimate: StealthRouteSafetyEstimate,
    ) -> str:
        """Format per-candidate values at the logging boundary."""
        return str([
            (
                result.tile_index,
                result.reveal_turns,
                result.remaining_army,
                result.enemy_defense,
                result.required_army)
            for result in estimate.candidate_results])

    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # MapBase.__getstate__ removes its distance mapper, which the WRP heuristic needs on the clone.
    @staticmethod
    def _clone_map_for_wrp(bot: EklipZBot) -> MapBase:
        """Clone on the caller thread and restore the clone-local distance cache."""
        cloned_map = bot._map.clone()
        cloned_map.distance_mapper = DistanceMapperImpl(cloned_map)
        return cloned_map

    @staticmethod
    def _is_safe_flank_tile(
        tile: Tile,
        enemy_vision: MapMatrixInterface[bool],
    ) -> bool:
        """Return whether a flank tile is hidden and traversable under stealth rules."""
        return (
            not enemy_vision.raw[tile.tile_index]
            and not tile.isObstacle
            and not (tile.isCity and tile.isNeutral)
            and not tile.isSwamp
            and not tile.isDesert)

    @staticmethod
    def _combine_routes(
        flank_path: Path,
        entry_tile: Tile,
        wrp_path: Path,
    ) -> Path:
        """Join a hidden flank and WRP route while keeping the shared entry once."""
        route = Path()
        for tile in flank_path.tileList:
            route.add_next(tile)
        wrp_tiles = wrp_path.tileList
        if wrp_tiles and wrp_tiles[0] != entry_tile:
            raise AssertionError("WRP result must begin at its requested entry tile")
        for tile in wrp_tiles[1:]:
            route.add_next(tile)
        return route

    @staticmethod
    def _run_wrp_job(job: StealthWrpJob, cloned_map: MapBase) -> None:
        """Compute WRP on a private cloned map and publish tile indexes when done."""
        start_time = time.perf_counter()
        start_tile = cloned_map.tiles_by_index[job.start_tile_index]
        to_discover = [
            cloned_map.tiles_by_index[tile_index]
            for tile_index in job.target_tile_indexes]
        wrp_path = WatchmanRouteUtils.get_watchman_path(
            cloned_map,
            start_tile,
            to_discover,
            timeLimit=job.time_limit,
            initialArmy=job.initial_army)
        job.result_tile_indexes = (
            [tile.tile_index for tile in wrp_path.tileList]
            if wrp_path is not None
            else None)
        job.duration_sec = time.perf_counter() - start_time
        job.done = True
        result_length = (
            len(job.result_tile_indexes)
            if job.result_tile_indexes is not None
            else 0)
        logbook.info(
            f"STEALTH_ALLIN_WRP_DONE generation={job.generation} "
            f"start={job.start_tile_index} len={result_length} "
            f"durationSec={job.duration_sec:.4f} "
            f"process=False")

    @staticmethod
    def _get_wrp_path(
        bot: EklipZBot,
        state: StealthAllInState,
    ) -> Path | None:
        """Get a completed WRP route or finish it synchronously at launch time."""
        job = state.wrp_job
        if job is None:
            return None
        BotStealthAllIn.poll_wrp_worker_results(bot)
        if not job.done:
            if not job.background_process:
                raise RuntimeError("Synchronous WRP job failed to publish a result")
            BotStealthAllIn._raise_if_pending_wrp_worker_exited(bot)
            time_remaining = max(0.0, BotTimings.get_remaining_move_time(bot))
            fallback_time_limit = min(0.03, time_remaining)
            if fallback_time_limit <= 0.0:
                return None
            bot.stealth_all_in_generation += 1
            state.generation = bot.stealth_all_in_generation
            fallback_map = BotStealthAllIn._clone_map_for_wrp(bot)
            job = BotStealthAllIn._start_wrp_job_on_clone(
                bot,
                fallback_map,
                state.entry_tile.tile_index,
                job.target_tile_indexes,
                job.initial_army,
                state.generation,
                fallback_time_limit)
            state.wrp_job = job
        return BotStealthAllIn.convert_wrp_job_result(bot._map, job)

    @staticmethod
    def _abort_committed_route(bot: EklipZBot, reason: str) -> None:
        """Log and clear a committed route after a permitted terminal condition."""
        state = bot.stealth_all_in
        logbook.info(
            f"STEALTH_ALLIN_ABORT turn={bot._map.turn} reason={reason}")
        if state is not None and state.is_undefendable_hunt:
            bot.stealth_hunt_excluded_start_tile_indexes.add(
                state.launch_tile.tile_index)
            if (state.committed_route is not None
                    and state.committed_route.start is not None):
                bot.stealth_hunt_excluded_start_tile_indexes.add(
                    state.committed_route.start.tile.tile_index)
        bot.stealth_all_in = None
        if state is not None and state.is_undefendable_hunt:
            bot.stealth_hunt_render_path = None
        bot.curPath = None
        bot.curPathPrio = -1
        # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
        # a finished/failed committed route ends the dive episode; the next plan re-earns its
        # gather turns before another desperation dive may commit.
        bot.stealth_all_in_cannot_kill_counter = 0

    @staticmethod
    def _is_owned_by_bot(bot: EklipZBot, tile: Tile) -> bool:
        """Return whether a tile still belongs to the current bot player."""
        return tile.player == bot.general.player
