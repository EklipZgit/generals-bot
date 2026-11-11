from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import logbook

from Behavior.ArmyInterceptionModels import (
    GENERAL_CAP_VALUE,
    NEUTRAL_CAP_VALUE,
    OTHER_PARTY_CAP_VALUE,
    OWNED_CITY_CAP_VALUE_BONUS,
    RECAPTURE_VALUE,
    TARGET_CAP_VALUE,
    ArmyInterception,
    InterceptPointTileInfo,
    InterceptionOptionInfo,
    ThreatBlockInfo,
)
from DangerAnalyzer import ThreatObj, ThreatType
from Path import Path
from Strategy import OpponentTracker
from base.client.map import MapBase, Tile


V2_MAX_OWNERSHIP_SOURCES = 3
V2_MAX_LARGEST_ARMY_SOURCES = 2
V2_PATH_SLACK = 2
V2_MAX_EVALUATED_CANDIDATES = 24


class V2ThreatDamageMode(Enum):
    THREAT_PATHS = 'threat_paths'
    UNRESTRICTED = 'unrestricted'


V2_THREAT_DAMAGE_MODE: V2ThreatDamageMode = V2ThreatDamageMode.THREAT_PATHS
UNREACHABLE_DISTANCE = 1000
UNREACHED_ARMY = -1_000_000_000
NO_PARENT = -1


class ArmyInterceptorV1Protocol(Protocol):
    __slots__ = ()

    map: MapBase
    log_debug: bool

    def _get_max_interception_search_depth(
        self,
        threats: list[ThreatObj],
    ) -> int:
        """Return the V1 threat-dependent search depth."""
        ...

    def _build_average_enemy_position_by_turn(
        self,
        interception: ArmyInterception,
        maxDepth: int,
    ) -> list[tuple[float, float] | None]:
        """Build average enemy positions by turn."""
        ...

    def _evaluate_intercept_path_into_table(
        self,
        interception: ArmyInterception,
        interceptInfo: InterceptPointTileInfo,
        path: Path,
        turnsLeftInCycle: int,
        opponentTracker: OpponentTracker,
        otherThreatsBlockingTiles: dict[Tile, ThreatBlockInfo] | None,
        averageEnemyPositionByTurn: list[tuple[float, float] | None],
        bestInterceptTable: dict[int, InterceptionOptionInfo],
    ) -> bool:
        """Evaluate a single path with the V1 option scorer."""
        ...


@dataclass(slots=True)
class ChokeBudgetMatrix:
    budget: list[int]


@dataclass(slots=True)
class ChokeBudgetBuildResult:
    matrix: ChokeBudgetMatrix
    candidate_sources: list[Tile]


@dataclass(slots=True)
class ArmyStepDeltaMatrix:
    friendly_step_delta: list[int]
    enemy_step_delta: list[int]
    friendly_tile_mask: bytearray
    negative_tile_mask: bytearray


@dataclass(slots=True)
class ThreatReachMatrix:
    tiles_by_index: list[Tile]
    max_depth: int
    enemy_turn: list[int]
    enemy_army: list[int]
    threat_path_mask: list[int]
    downstream_damage: list[float]
    choke_budget: ChokeBudgetMatrix
    step_deltas: ArmyStepDeltaMatrix
    candidate_sources: list[Tile]
    blocking_sources: list[Tile]


@dataclass(slots=True)
class FriendlyMultiSourceMatrix:
    candidate_sources: list[Tile]
    turns: list[int]
    army_at_arrival: list[int]
    source_index: list[int]
    ownership_scores: list[float]
    selected_source_indices: list[int]


@dataclass(slots=True)
class SourceLayeredReach:
    source_index: int
    source_tile: Tile
    max_depth: int
    states_by_depth: list[dict[int, tuple[int, int]]]


@dataclass(slots=True)
class V2InterceptCandidate:
    source_index: int
    layer_index: int
    choke_tile: Tile
    depth: int
    friendly_army: int
    prescreen_value: float


@dataclass(slots=True)
class V2CandidatePath:
    candidate: V2InterceptCandidate
    path: Path
    friendly_army_at_choke: int


@dataclass(slots=True)
class V2StageTimings:
    stage_a_seconds: float = 0.0
    stage_b_seconds: float = 0.0
    stage_c_seconds: float = 0.0
    stage_d_seconds: float = 0.0
    stage_e_seconds: float = 0.0


class ArmyInterceptorV2:
    __slots__ = ('v1', 'last_stage_timings')

    v1: ArmyInterceptorV1Protocol
    last_stage_timings: V2StageTimings

    def __init__(self, v1: ArmyInterceptorV1Protocol) -> None:
        """Initialize V2 with the V1 surface it reuses."""
        self.v1 = v1
        self.last_stage_timings = V2StageTimings()

    def get_intercept_plan_options(
        self,
        interception: ArmyInterception,
        turnsLeftInCycle: int,
        opponentTracker: OpponentTracker,
        otherThreatsBlockingTiles: dict[Tile, ThreatBlockInfo] | None,
    ) -> dict[int, InterceptionOptionInfo]:
        """Find a bounded set of V2 candidate paths and score them with V1."""
        max_depth = min(
            self.v1._get_max_interception_search_depth(interception.threats),
            turnsLeftInCycle)
        self.last_stage_timings = V2StageTimings()
        if not interception.common_intercept_chokes or max_depth <= 0:
            return {}

        stages_started_at = time.perf_counter()
        threat_reach = self.build_threat_reach_matrix(
            interception,
            max_depth,
            turnsLeftInCycle)
        stage_a_seconds = time.perf_counter() - stages_started_at

        stage_started_at = time.perf_counter()
        friendly_reach = self.build_friendly_multi_source_matrix(
            interception,
            threat_reach)
        stage_b_seconds = time.perf_counter() - stage_started_at

        stage_started_at = time.perf_counter()
        layered_reaches = [
            self.build_source_layered_reach(
                threat_reach,
                source_index)
            for source_index in friendly_reach.selected_source_indices
        ]
        stage_c_seconds = time.perf_counter() - stage_started_at

        stage_started_at = time.perf_counter()
        candidates = self.build_intercept_candidates(
            interception,
            threat_reach,
            friendly_reach,
            layered_reaches,
            turnsLeftInCycle)
        stage_d_seconds = time.perf_counter() - stage_started_at

        stage_started_at = time.perf_counter()
        average_enemy_position_by_turn = (
            self.v1._build_average_enemy_position_by_turn(
                interception,
                max_depth))
        best_intercept_table: dict[int, InterceptionOptionInfo] = {}
        candidate_paths = self.reconstruct_candidate_paths(
            threat_reach,
            friendly_reach,
            layered_reaches,
            candidates)
        for candidate_path in candidate_paths:
            candidate = candidate_path.candidate
            intercept_info = interception.common_intercept_chokes[
                candidate.choke_tile]
            self.v1._evaluate_intercept_path_into_table(
                interception,
                intercept_info,
                candidate_path.path,
                turnsLeftInCycle,
                opponentTracker,
                otherThreatsBlockingTiles,
                average_enemy_position_by_turn,
                best_intercept_table)
        stage_e_seconds = time.perf_counter() - stage_started_at
        self.last_stage_timings = V2StageTimings(
            stage_a_seconds=stage_a_seconds,
            stage_b_seconds=stage_b_seconds,
            stage_c_seconds=stage_c_seconds,
            stage_d_seconds=stage_d_seconds,
            stage_e_seconds=stage_e_seconds)

        if self.v1.log_debug:
            selected_source_summary = ', '.join(
                f'{friendly_reach.candidate_sources[source_index]} '
                f'ownership={friendly_reach.ownership_scores[source_index]:.2f} '
                f'army={friendly_reach.candidate_sources[source_index].army}'
                for source_index in friendly_reach.selected_source_indices)
            candidate_summary = ', '.join(
                f'{candidate.choke_tile} from '
                f'{friendly_reach.candidate_sources[candidate.source_index]} '
                f'at d{candidate.depth} score={candidate.prescreen_value:.2f}'
                for candidate in candidates)
            layered_state_count = sum(
                len(depth_states)
                for source_reach in layered_reaches
                for depth_states in source_reach.states_by_depth)
            logbook.info(
                f'ArmyInterceptorV2 matrices: tiles={len(threat_reach.tiles_by_index)}, '
                f'enemyReached={sum(1 for turn in threat_reach.enemy_turn if turn >= 0)}, '
                f'sources={len(threat_reach.candidate_sources)}, '
                f'blockingSources={len(threat_reach.blocking_sources)}, '
                f'selectedSources={len(friendly_reach.selected_source_indices)}, '
                f'layeredStates={layered_state_count}, candidates={len(candidates)}')
            logbook.info(
                f'ArmyInterceptorV2 selected sources: {selected_source_summary}')
            logbook.info(
                f'ArmyInterceptorV2 kept candidates: {candidate_summary}')
            logbook.info(
                f'ArmyInterceptorV2 stage seconds: '
                f'A={stage_a_seconds:.6f}, B={stage_b_seconds:.6f}, '
                f'C={stage_c_seconds:.6f}, D={stage_d_seconds:.6f}, '
                f'E={stage_e_seconds:.6f}, '
                f'total={time.perf_counter() - stages_started_at:.6f}')

        return best_intercept_table

    def build_threat_reach_matrix(
        self,
        interception: ArmyInterception,
        max_depth: int,
        turns_left_in_cycle: int,
    ) -> ThreatReachMatrix:
        """Build threat reach, army, threat-path, damage, and source arrays."""
        tiles_by_index = list(self.v1.map.get_all_tiles())
        tile_count = len(tiles_by_index)
        step_deltas = self._build_army_step_deltas(
            interception,
            tiles_by_index)
        enemy_turn = [-1] * tile_count
        enemy_army = [0] * tile_count
        threat_path_mask = [0] * tile_count

        for threat_index, threat in enumerate(interception.threats):
            path_bit = 1 << threat_index
            for node in threat.path:
                threat_path_mask[node.tile.tile_index] |= path_bit

        target_index = interception.target_tile.tile_index
        enemy_turn[target_index] = 0
        enemy_army[target_index] = step_deltas.enemy_step_delta[target_index]
        frontier: deque[int] = deque([target_index])
        while frontier:
            tile_index = frontier.popleft()
            current_turn = enemy_turn[tile_index]
            current_tile = tiles_by_index[tile_index]
            if current_turn >= max_depth:
                continue
            for next_tile in current_tile.movable:
                if next_tile.isObstacle or (
                    next_tile.isCity and next_tile.isNeutral):
                    continue
                next_index = next_tile.tile_index
                next_turn = current_turn + 1
                next_army = (
                    enemy_army[tile_index]
                    + step_deltas.enemy_step_delta[next_index])
                if enemy_turn[next_index] == -1:
                    enemy_turn[next_index] = next_turn
                    enemy_army[next_index] = next_army
                    frontier.append(next_index)
                elif enemy_turn[next_index] == next_turn:
                    enemy_army[next_index] = max(
                        enemy_army[next_index],
                        next_army)

        downstream_damage = [0.0] * tile_count
        if V2_THREAT_DAMAGE_MODE == V2ThreatDamageMode.THREAT_PATHS:
            self._build_threat_path_downstream_damage(
                interception,
                turns_left_in_cycle,
                step_deltas,
                downstream_damage)
        else:
            self._build_unrestricted_downstream_damage(
                interception,
                turns_left_in_cycle,
                enemy_turn,
                enemy_army,
                tiles_by_index,
                downstream_damage)

        budget_result = self.build_choke_budget_matrix(
            interception,
            max_depth,
            tiles_by_index,
            threat_path_mask,
            step_deltas)
        choke_budget = budget_result.matrix
        candidate_sources = budget_result.candidate_sources
        blocking_sources = [
            tile
            for tile in candidate_sources
            if enemy_turn[tile.tile_index] != -1
            and enemy_army[tile.tile_index] <= tile.army
        ]
        return ThreatReachMatrix(
            tiles_by_index=tiles_by_index,
            max_depth=max_depth,
            enemy_turn=enemy_turn,
            enemy_army=enemy_army,
            threat_path_mask=threat_path_mask,
            downstream_damage=downstream_damage,
            choke_budget=choke_budget,
            step_deltas=step_deltas,
            candidate_sources=candidate_sources,
            blocking_sources=blocking_sources,
        )

    def build_choke_budget_matrix(
        self,
        interception: ArmyInterception,
        max_depth: int,
        tiles_by_index: list[Tile],
        threat_path_mask: list[int],
        step_deltas: ArmyStepDeltaMatrix,
    ) -> ChokeBudgetBuildResult:
        """Build choke slack and collect candidate sources in one offset BFS."""
        choke_limits = [
            (tile, min(info.max_delay_turns, max_depth))
            for tile, info in interception.common_intercept_chokes.items()
            if not (tile.isCity and tile.isNeutral)
        ]
        tile_count = len(tiles_by_index)
        if not choke_limits:
            return ChokeBudgetBuildResult(
                matrix=ChokeBudgetMatrix(budget=[-1] * tile_count),
                candidate_sources=[])

        max_limit = max(limit for _, limit in choke_limits)
        bfs_dist = [UNREACHABLE_DISTANCE] * tile_count
        frontier: deque[tuple[int, int]] = deque()
        for choke_tile, limit in sorted(
            choke_limits,
            key=lambda choke_and_limit: max_limit - choke_and_limit[1]):
            offset = max_limit - limit
            choke_index = choke_tile.tile_index
            if bfs_dist[choke_index] <= offset:
                continue
            bfs_dist[choke_index] = offset
            frontier.append((choke_index, offset))

        full_path_mask = (1 << len(interception.threats)) - 1
        candidate_sources: list[Tile] = []
        candidate_source_seen = bytearray(tile_count)
        while frontier:
            tile_index, dist = frontier.popleft()
            if bfs_dist[tile_index] != dist or dist > max_limit:
                continue
            tile = tiles_by_index[tile_index]
            if (
                max_limit - dist >= 0
                and step_deltas.friendly_tile_mask[tile_index]
                and tile.army >= 2
            ):
                is_source = True
                if step_deltas.negative_tile_mask[tile_index]:
                    if threat_path_mask[tile_index] == full_path_mask:
                        is_source = False
                    else:
                        source_distances = (
                            self.v1.map.distance_mapper.get_tile_dist_matrix(
                                tile).raw)
                        nearest_choke_distance = min(
                            (
                                source_distances[choke_tile.tile_index]
                                for choke_tile, _ in choke_limits
                            ),
                            default=UNREACHABLE_DISTANCE)
                        if nearest_choke_distance >= UNREACHABLE_DISTANCE:
                            is_source = False
                        else:
                            minimum_army = (
                                interception.base_threat_army
                                * (nearest_choke_distance + 1)
                            ) // (nearest_choke_distance + 2)
                            if tile.army < minimum_army:
                                is_source = False
                if is_source and not candidate_source_seen[tile_index]:
                    candidate_source_seen[tile_index] = 1
                    candidate_sources.append(tile)

            if dist >= max_limit:
                continue
            new_dist = dist + 1
            for neighbor in tile.movable:
                if neighbor.isObstacle or (
                    neighbor.isCity and neighbor.isNeutral):
                    continue
                neighbor_index = neighbor.tile_index
                if new_dist >= bfs_dist[neighbor_index]:
                    continue
                bfs_dist[neighbor_index] = new_dist
                frontier.append((neighbor_index, new_dist))

        budget = [
            max_limit - dist
            if dist < UNREACHABLE_DISTANCE and dist <= max_limit
            else -1
            for dist in bfs_dist
        ]
        return ChokeBudgetBuildResult(
            matrix=ChokeBudgetMatrix(budget=budget),
            candidate_sources=candidate_sources)

    def _build_army_step_deltas(
        self,
        interception: ArmyInterception,
        tiles_by_index: list[Tile],
    ) -> ArmyStepDeltaMatrix:
        """Precompute friendly and threat-team army deltas for this plan."""
        threat_players = self.v1.map.get_teammates(
            interception.threats[0].threatPlayer)
        friendly_step_delta: list[int] = []
        enemy_step_delta: list[int] = []
        friendly_tile_mask = bytearray(len(tiles_by_index))
        negative_tile_mask = bytearray(len(tiles_by_index))
        negative_tiles = (
            interception.positive_threat_subsegment_negative_tile_indexes)
        for tile in tiles_by_index:
            tile_index = tile.tile_index
            is_friendly = self.v1.map.is_tile_friendly(tile)
            is_negative = tile in negative_tiles
            if is_friendly:
                friendly_tile_mask[tile_index] = 1
            if is_negative:
                negative_tile_mask[tile_index] = 1
                friendly_step_delta.append(-1)
            elif is_friendly:
                friendly_step_delta.append(tile.army - 1)
            else:
                friendly_step_delta.append(-tile.army - 1)
            if tile.player in threat_players:
                enemy_step_delta.append(tile.army - 1)
            else:
                enemy_step_delta.append(-tile.army - 1)
        return ArmyStepDeltaMatrix(
            friendly_step_delta=friendly_step_delta,
            enemy_step_delta=enemy_step_delta,
            friendly_tile_mask=friendly_tile_mask,
            negative_tile_mask=negative_tile_mask)

    def build_friendly_multi_source_matrix(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
    ) -> FriendlyMultiSourceMatrix:
        """Run one best-army, minimum-turn BFS from every candidate source."""
        tile_count = len(threat_reach.tiles_by_index)
        candidate_sources = threat_reach.candidate_sources
        choke_budget = threat_reach.choke_budget.budget
        friendly_step_delta = (
            threat_reach.step_deltas.friendly_step_delta)
        turns = [-1] * tile_count
        army_at_arrival = [UNREACHED_ARMY] * tile_count
        source_index = [-1] * tile_count
        frontier: deque[int] = deque()

        for candidate_index, source in enumerate(candidate_sources):
            tile_index = source.tile_index
            if choke_budget[tile_index] < 0:
                continue
            source_army = friendly_step_delta[tile_index]
            turns[tile_index] = 0
            army_at_arrival[tile_index] = source_army
            source_index[tile_index] = candidate_index
            frontier.append(tile_index)

        while frontier:
            tile_index = frontier.popleft()
            current_turn = turns[tile_index]
            if (
                current_turn >= threat_reach.max_depth
                or current_turn > choke_budget[tile_index]
            ):
                continue
            next_turn = current_turn + 1
            current_tile = threat_reach.tiles_by_index[tile_index]
            for next_tile in current_tile.movable:
                if next_tile.isObstacle or (
                    next_tile.isCity and next_tile.isNeutral):
                    continue
                next_index = next_tile.tile_index
                if next_turn > choke_budget[next_index]:
                    continue
                next_army = (
                    army_at_arrival[tile_index]
                    + friendly_step_delta[next_index])
                if turns[next_index] == -1 or next_turn < turns[next_index]:
                    turns[next_index] = next_turn
                    army_at_arrival[next_index] = next_army
                    source_index[next_index] = source_index[tile_index]
                    frontier.append(next_index)
                elif (
                    next_turn == turns[next_index]
                    and next_army > army_at_arrival[next_index]
                ):
                    army_at_arrival[next_index] = next_army
                    source_index[next_index] = source_index[tile_index]
                    frontier.append(next_index)

        ownership_scores = [0.0] * len(candidate_sources)
        for choke_tile, intercept_info in interception.common_intercept_chokes.items():
            choke_index = choke_tile.tile_index
            owner_index = source_index[choke_index]
            if owner_index == -1:
                continue
            if turns[choke_index] > intercept_info.max_delay_turns:
                continue
            enemy_army = max(1, threat_reach.enemy_army[choke_index])
            ownership_scores[owner_index] += (
                threat_reach.downstream_damage[choke_index]
                * min(1.0, army_at_arrival[choke_index] / enemy_army))

        selected_source_indices: list[int] = []
        ownership_order = sorted(
            range(len(candidate_sources)),
            key=lambda index: (ownership_scores[index], -index),
            reverse=True)
        for candidate_index in ownership_order:
            if ownership_scores[candidate_index] <= 0:
                continue
            selected_source_indices.append(candidate_index)
            if len(selected_source_indices) >= V2_MAX_OWNERSHIP_SOURCES:
                break

        reachability_by_source = [
            choke_budget[source.tile_index] >= 0
            for source in candidate_sources]

        largest_army_order = sorted(
            (
                index
                for index, source in enumerate(candidate_sources)
                if reachability_by_source[index]
            ),
            key=lambda index: (
                candidate_sources[index].army,
                -index),
            reverse=True)
        for candidate_index in largest_army_order[
            :V2_MAX_LARGEST_ARMY_SOURCES]:
            if candidate_index not in selected_source_indices:
                selected_source_indices.append(candidate_index)

        source_index_by_tile = [-1] * tile_count
        for candidate_index, source in enumerate(candidate_sources):
            source_index_by_tile[source.tile_index] = candidate_index
        for blocking_source in threat_reach.blocking_sources:
            candidate_index = source_index_by_tile[blocking_source.tile_index]
            if (
                candidate_index != -1
                and reachability_by_source[candidate_index]
                and candidate_index not in selected_source_indices
            ):
                selected_source_indices.append(candidate_index)

        return FriendlyMultiSourceMatrix(
            candidate_sources=candidate_sources,
            turns=turns,
            army_at_arrival=army_at_arrival,
            source_index=source_index,
            ownership_scores=ownership_scores,
            selected_source_indices=selected_source_indices,
        )

    def build_source_layered_reach(
        self,
        threat_reach: ThreatReachMatrix,
        source_index: int,
    ) -> SourceLayeredReach:
        """Build bounded army states from one source to threat-relevant tiles."""
        source_tile = threat_reach.candidate_sources[source_index]
        distance_matrix = self.v1.map.distance_mapper.get_tile_dist_matrix(
            source_tile)
        shortest_dist = distance_matrix.raw
        choke_budget = threat_reach.choke_budget.budget
        friendly_step_delta = (
            threat_reach.step_deltas.friendly_step_delta)
        max_depth = threat_reach.max_depth
        source_tile_index = source_tile.tile_index
        if choke_budget[source_tile_index] < 0:
            raise ValueError(
                f'V2 selected unreachable source {source_tile}')
        states_by_depth: list[dict[int, tuple[int, int]]] = [
            {}
            for _ in range(max_depth + 1)
        ]
        states_by_depth[0][source_tile_index] = (
            friendly_step_delta[source_tile_index],
            NO_PARENT)
        state_frontier: deque[tuple[int, int]] = deque([
            (source_tile_index, 0)
        ])
        while state_frontier:
            tile_index, depth = state_frontier.popleft()
            if depth >= max_depth:
                continue
            next_depth = depth + 1
            current_army, parent_tile_index = (
                states_by_depth[depth][tile_index])
            current_tile = threat_reach.tiles_by_index[tile_index]
            for next_tile in current_tile.movable:
                if next_tile.isObstacle or (
                    next_tile.isCity and next_tile.isNeutral):
                    continue
                next_index = next_tile.tile_index
                shortest_distance = shortest_dist[next_index]
                if (
                    shortest_distance < 0
                    or shortest_distance >= UNREACHABLE_DISTANCE
                    or next_depth > shortest_distance + V2_PATH_SLACK
                    or next_depth > choke_budget[next_index]
                ):
                    continue
                # Grid cycles are at least 4 moves; with immediate backtracking
                # banned, any revisit needs slack >= 4.
                if next_index == parent_tile_index:
                    continue

                next_army = (
                    current_army + friendly_step_delta[next_index])
                current_best_state = states_by_depth[next_depth].get(
                    next_index)
                if (
                    current_best_state is not None
                    and next_army <= current_best_state[0]
                ):
                    continue
                states_by_depth[next_depth][next_index] = (
                    next_army,
                    tile_index)
                state_frontier.append((next_index, next_depth))

        return SourceLayeredReach(
            source_index=source_index,
            source_tile=source_tile,
            max_depth=max_depth,
            states_by_depth=states_by_depth,
        )

    def build_intercept_candidates(
        self,
        interception: ArmyInterception,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        layered_reaches: list[SourceLayeredReach],
        turns_left_in_cycle: int,
    ) -> list[V2InterceptCandidate]:
        """Retain per-source lengths, all length winners, and top scores."""
        candidates: list[V2InterceptCandidate] = []
        best_candidate_by_source_and_depth: dict[
            tuple[int, int],
            V2InterceptCandidate,
        ] = {}
        best_candidate_by_depth: dict[int, V2InterceptCandidate] = {}
        for layer_index, source_reach in enumerate(layered_reaches):
            source_index = source_reach.source_index
            for choke_tile, intercept_info in interception.common_intercept_chokes.items():
                if choke_tile.isCity and choke_tile.isNeutral:
                    continue
                choke_index = choke_tile.tile_index
                max_candidate_depth = min(
                    intercept_info.max_delay_turns,
                    source_reach.max_depth)
                for depth in range(1, max_candidate_depth + 1):
                    state = source_reach.states_by_depth[depth].get(
                        choke_index)
                    if state is None:
                        continue
                    friendly_army = state[0]
                    if threat_reach.enemy_turn[choke_index] != -1:
                        enemy_army = max(
                            1,
                            threat_reach.enemy_army[choke_index])
                    else:
                        enemy_army = max(1, interception.base_threat_army)
                    turns_left = (
                        turns_left_in_cycle
                        - depth
                        - intercept_info.max_extra_moves_to_capture)
                    prescreen_value = (
                        threat_reach.downstream_damage[choke_index]
                        * min(1.0, friendly_army / enemy_army)
                        + RECAPTURE_VALUE
                        * max(
                            0,
                            min(
                                turns_left,
                                (friendly_army - enemy_army) // 2))
                        - 0.06 * depth)
                    candidate = V2InterceptCandidate(
                        source_index=source_index,
                        layer_index=layer_index,
                        choke_tile=choke_tile,
                        depth=depth,
                        friendly_army=friendly_army,
                        prescreen_value=prescreen_value,
                    )
                    candidates.append(candidate)
                    source_depth_key = (source_index, depth)
                    current_best = (
                        best_candidate_by_source_and_depth.get(
                            source_depth_key))
                    if (
                        current_best is None
                        or self._candidate_sort_key(candidate)
                        < self._candidate_sort_key(current_best)
                    ):
                        best_candidate_by_source_and_depth[
                            source_depth_key] = candidate
                    current_depth_best = best_candidate_by_depth.get(depth)
                    if (
                        current_depth_best is None
                        or self._candidate_sort_key(candidate)
                        < self._candidate_sort_key(current_depth_best)
                    ):
                        best_candidate_by_depth[depth] = candidate

        kept_candidates = list(
            best_candidate_by_source_and_depth.values())
        included_candidate_keys = {
            self._candidate_key(candidate)
            for candidate in kept_candidates
        }
        for candidate in best_candidate_by_depth.values():
            candidate_key = self._candidate_key(candidate)
            if candidate_key in included_candidate_keys:
                continue
            kept_candidates.append(candidate)
            included_candidate_keys.add(candidate_key)

        for candidate in sorted(candidates, key=self._candidate_sort_key):
            if len(kept_candidates) >= V2_MAX_EVALUATED_CANDIDATES:
                break
            candidate_key = self._candidate_key(candidate)
            if candidate_key in included_candidate_keys:
                continue
            kept_candidates.append(candidate)
            included_candidate_keys.add(candidate_key)
        return kept_candidates

    def reconstruct_candidate_paths(
        self,
        threat_reach: ThreatReachMatrix,
        friendly_reach: FriendlyMultiSourceMatrix,
        layered_reaches: list[SourceLayeredReach],
        candidates: list[V2InterceptCandidate],
    ) -> list[V2CandidatePath]:
        """Reconstruct each retained layered state as a forward Path."""
        candidate_paths: list[V2CandidatePath] = []
        for candidate in candidates:
            source_reach = layered_reaches[candidate.layer_index]
            if (
                source_reach.source_tile
                != friendly_reach.candidate_sources[candidate.source_index]
            ):
                raise ValueError(
                    f'V2 candidate source mismatch for '
                    f'{source_reach.source_tile}')
            tile_indices = [candidate.choke_tile.tile_index]
            current_index = candidate.choke_tile.tile_index
            for depth in range(candidate.depth, 0, -1):
                current_state = source_reach.states_by_depth[depth].get(
                    current_index)
                if current_state is None:
                    raise ValueError(
                        f'No V2 parent for source {source_reach.source_tile}, '
                        f'choke {candidate.choke_tile}, depth {candidate.depth}')
                parent_index = current_state[1]
                if parent_index == NO_PARENT:
                    raise ValueError(
                        f'No V2 parent for source {source_reach.source_tile}, '
                        f'choke {candidate.choke_tile}, depth {candidate.depth}')
                current_index = parent_index
                tile_indices.append(current_index)
            if current_index != source_reach.source_tile.tile_index:
                raise ValueError(
                    f'V2 path did not reconstruct to source '
                    f'{source_reach.source_tile}')
            tile_indices.reverse()
            path = Path()
            for tile_index in tile_indices:
                path.add_next(
                    threat_reach.tiles_by_index[tile_index])
            candidate_paths.append(
                V2CandidatePath(
                    candidate=candidate,
                    path=path,
                    friendly_army_at_choke=source_reach.states_by_depth[
                        candidate.depth][candidate.choke_tile.tile_index][0],
                ))
        return candidate_paths

    def _build_threat_path_downstream_damage(
        self,
        interception: ArmyInterception,
        turns_left_in_cycle: int,
        step_deltas: ArmyStepDeltaMatrix,
        downstream_damage: list[float],
    ) -> None:
        """Accumulate maximum strictly downstream damage along threat paths."""
        for threat_value in interception.threat_values:
            threat = threat_value.threat
            threat_players = self.v1.map.get_teammates(threat.threatPlayer)
            path_tiles = [node.tile for node in threat.path]
            cap_values = [0.0] * len(path_tiles)
            enemy_army = 0
            for path_index, tile in enumerate(path_tiles):
                enemy_army += step_deltas.enemy_step_delta[tile.tile_index]
                if enemy_army > 0 and path_index < turns_left_in_cycle:
                    cap_values[path_index] = self._get_cap_value(
                        tile,
                        threat.threatType,
                        turns_left_in_cycle - path_index,
                        threat_players)

            suffix_damage = 0.0
            for path_index in range(len(path_tiles) - 1, -1, -1):
                tile_index = path_tiles[path_index].tile_index
                downstream_damage[tile_index] = max(
                    downstream_damage[tile_index],
                    suffix_damage)
                suffix_damage += cap_values[path_index]

    def _build_unrestricted_downstream_damage(
        self,
        interception: ArmyInterception,
        turns_left_in_cycle: int,
        enemy_turn: list[int],
        enemy_army: list[int],
        tiles_by_index: list[Tile],
        downstream_damage: list[float],
    ) -> None:
        """Use reverse dynamic programming over the threat-reach DAG."""
        kill_threat_players = self.v1.map.get_teammates(
            interception.threats[0].threatPlayer)
        has_kill_threat = any(
            threat.threatType == ThreatType.Kill
            for threat in interception.threats)
        threat_type = (
            ThreatType.Kill
            if has_kill_threat
            else interception.threats[0].threatType)
        for depth in range(
            min(turns_left_in_cycle, max(enemy_turn, default=-1)),
            -1,
            -1):
            for tile_index, enemy_turn_value in enumerate(enemy_turn):
                if enemy_turn_value != depth:
                    continue
                tile = tiles_by_index[tile_index]
                tile_damage = 0.0
                if enemy_army[tile_index] > 0:
                    remaining_turns = turns_left_in_cycle - depth
                    tile_damage = self._get_cap_value(
                        tile,
                        threat_type,
                        remaining_turns,
                        kill_threat_players)
                max_child_damage = 0.0
                for child_tile in tile.movable:
                    if child_tile.isObstacle or (
                        child_tile.isCity and child_tile.isNeutral):
                        continue
                    child_index = child_tile.tile_index
                    if enemy_turn[child_index] == depth + 1:
                        max_child_damage = max(
                            max_child_damage,
                            downstream_damage[child_index])
                downstream_damage[tile_index] = (
                    tile_damage + max_child_damage)

    def _get_cap_value(
        self,
        tile: Tile,
        threat_type: ThreatType,
        remaining_turns: int,
        threat_players: list[int],
    ) -> float:
        """Return the V1-style economic value of capturing one tile."""
        if tile.player in threat_players:
            return 0.0
        if self.v1.map.is_tile_friendly(tile):
            value = TARGET_CAP_VALUE
            if tile.isCity:
                value += OWNED_CITY_CAP_VALUE_BONUS + max(
                    0,
                    remaining_turns)
            if tile.isGeneral and threat_type == ThreatType.Kill:
                value += GENERAL_CAP_VALUE
            return value
        if tile.player >= 0:
            return NEUTRAL_CAP_VALUE
        return OTHER_PARTY_CAP_VALUE

    def _candidate_sort_key(
        self,
        candidate: V2InterceptCandidate,
    ) -> tuple[float, int, int, int]:
        """Sort higher prescreen values first with stable tile/depth ties."""
        return (
            -candidate.prescreen_value,
            candidate.source_index,
            candidate.choke_tile.tile_index,
            candidate.depth,
        )

    def _candidate_key(
        self,
        candidate: V2InterceptCandidate,
    ) -> tuple[int, int, int]:
        """Return the unique source/choke/depth identity for a candidate."""
        return (
            candidate.source_index,
            candidate.choke_tile.tile_index,
            candidate.depth,
        )
