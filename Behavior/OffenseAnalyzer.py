from __future__ import annotations

import heapq
import typing
from collections import deque
from dataclasses import dataclass

import logbook

from Army import Army
from BoardAnalyzer import BoardAnalyzer
from Interfaces import MapMatrixInterface, TilePlanInterface
from MapMatrix import MapMatrix, MapMatrixSet
from Path import Path
from PerformanceTimer import PerformanceTimer
import SearchUtils
from Strategy import OpponentTracker
from ArmyTracker import ArmyTracker
from ViewInfo import TargetStyle
from base.client.map import MapBase, Tile
from Models import Move


class OffensiveThreatOptionInfo(TilePlanInterface):
    __slots__ = (
        'path',
        'econValue',
        'turns',
        'chance_of_interception',
        'forced_army_info_by_tile_index',
        'damage_prevented',
        'is_kill_threat',
        'is_city_threat',
        'raw_capture_econ_value',
        'forcing_turns',
        'target_pivot_tile',
        'split_sub_option',
        'double_back_path',
        'probable_capture_tiles',
        '_tileSet',
        '_tileList',
        'requiredDelay',
    )

    def __init__(
            self,
            path: Path,
            chance_of_interception: float,
            forced_army_info_by_tile_index: dict[int, tuple[Army, Tile, int]],
            damage_prevented: float,
            is_kill_threat: bool,
            is_city_threat: bool,
            forcing_turns: int,
            target_pivot_tile: Tile,
            split_sub_option: OffensiveThreatOptionInfo | None = None,
            double_back_path: Path | None = None,
            probable_capture_tiles: set[Tile] | None = None,
            requiredDelay: int = 0,
    ):
        self.path: Path = path
        if path is None or path.start is None:
            raise Exception(f"Wtf, dont pass offensive threat a bad path :V {path}")

        self.econValue: float = 0.0
        self.turns: int = 0
        self.chance_of_interception: float = chance_of_interception
        """
        between 0 and 1. How likely we think the enemy is to be able to intercept our offense without us having the chance to dodge 
        (or our dodge leaving nowhere to go but somewhere not capturing enemy tiles).
        """

        self.forced_army_info_by_tile_index: dict[int, tuple[Army, Tile, int]] = forced_army_info_by_tile_index
        """
        the lookup table from tile_index of the Army's CURRENT tile mapped to the army object, the tile we believe we'll force it onto 
        before we need to give up the threat (the tile we expect it to be on at the end of executing this options path), 
        and the number of turns of forced moves we forced out of that army.
        """

        self.damage_prevented: float = damage_prevented
        """
        similar to ArmyInterceptionOptions damage blocked, this is the amount of the econValue of this plan that we expect to come from 
        forcing the enemy to waste moves traversing their own land (or neutral land) rather than capturing our land 
        (or neutral land, if forcing them to move over their own tiles).
        """

        self.is_kill_threat: bool = is_kill_threat
        """
        if true, means that if the enemy ignores this threat with the armies_forced, then we expect to be able to kill the enemy due to 
        their other armies / general amount being out of position / knowably too small to defend
        """

        self.is_city_threat: bool = is_city_threat
        """
        if true, means that if the enemy ignores this threat then we will capture their city for some amount of time. 
        If both this and is_kill_threat are false, then our threat is simply an econ damage threat - EG
        """

        self.raw_capture_econ_value: float = 0.0
        """
        the raw econ value of the captures we expect to make in this threat (some of which will be from a concrete path, 
        and some of which may be fuzzy flow-island-style army sink assumed captures like we do with FlowExpands gather capture planning)
        """

        self.forcing_turns: int = forcing_turns
        """
        the number of turns down the path this threat can make while still generating a valid threat against the target. 
        Once we reach a point where we've burned enough army that we couldn't turn to attack the target and capture it successfully, 
        we are no longer forcing the opponent to chase and they can resume capturing our tiles and trade capture-for-capture with us 
        as we no longer generate a threat stronger than captures. 
        This is useful for calculating how much defensive time we can buy with a threat etc.
        """

        self.target_pivot_tile: Tile = target_pivot_tile
        """
        the threat point that this offensive plan revolves around. For example if we're going to run around a mountain range to circle 
        long-way to their general on the other side, in order to force their army to retraverse their own tiles to defend the general 
        on a shorter path than our long-threat, then this pivot tile would be their general. 
        If we're doing something similar but feinting towards a city / dodge-circling-for a city, then that city would be the pivot point. 
        Pivot points are almost always high value targets. Occasionally you might pivot around enemy land to force an enemy army to stop 
        capturing neutrals while dodging their army, I suppose, but that seems contrived.
        """

        self.split_sub_option: OffensiveThreatOptionInfo | None = split_sub_option
        """
        If path contains a move_half, then this should be the expected threat+path of the splits remaining army (acting as though we 
        continued moving this army while enemy chases instead of them chasing the other path). We will use splits when there are multiple 
        threat generating options and the threat can be generated. Because these are a threat generated later by the first threat they 
        are not options on their own, but can be threatening a different target than the parent offensive threat (but generally will still 
        be dodging the same forced_armies). offensive threats that have a split will generally also have the option not to split, 
        so both variants of the top level option (one with sub option and the other without) may be generated.
        """

        self.double_back_path: Path | None = double_back_path
        """
        if by the end of our initial path we still have army left, this is the continued-capture option that we have 
        (generally 90 degree'ing away from the enemy-army-forced-to-tile and then doubling back along any remaining uncaptured enemy land, 
        continuing to move away from that end-location).
        """

        self.probable_capture_tiles: set[Tile] = probable_capture_tiles if probable_capture_tiles is not None else set()
        """
        The set of tiles we think we might capture approximately as part of this offensive plan. Will be some grouping of tiles that 
        continues to receed from the armies we are dodging, probably usually in the reverse direction from the path, since the path should 
        go until the move before that path is expected to be intercepted. These tiles would then be the potential double back path 
        while still maintaining a threatening distance to the target_pivot_tile. These may be more than the amount of moves in the plan. 
        Path + these tiles should equal the length of the offensive plan. Placeholder for now, may not end up used.
        """

        self.requiredDelay: int = requiredDelay
        self._tileSet: set[Tile] | None = None
        self._tileList: list[Tile] | None = None

        self.recalculate_values()

    def recalculate_values(self) -> None:
        """
        Recalculates the econ values for this threat option.
        Sets raw_capture_econ_value = self.path.econValue + self.double_back_path?.econValue ?? 0
        Sets econValue to be raw_capture_econ_value + damage_prevented
        """
        self.raw_capture_econ_value = self.path.econValue
        if self.double_back_path is not None:
            self.raw_capture_econ_value += self.double_back_path.econValue

        self.econValue = self.raw_capture_econ_value + self.damage_prevented
        self.turns = self.path.length
        if self.double_back_path is not None:
            self.turns += self.double_back_path.length

    @property
    def length(self) -> int:
        return self.turns


    def __iter__(self) -> typing.Iterator:
        return iter(self.path)

    @property
    def tiles(self) -> typing.Iterable[Tile]:
        return iter(self.path.tiles)

    @property
    def tileSet(self) -> typing.Set[Tile]:
        if self._tileSet is None:
            self._tileSet = set(self.tileList)
        return self._tileSet

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = self.path.tileList.copy()
            if self.double_back_path is not None:
                self._tileList.extend(self.double_back_path.tileList)
        return self._tileList


    def get_move_list(self) -> typing.List[Move]:
        return self.path.get_move_list()

    def get_first_move(self) -> Move:
        return self.path.get_first_move()

    def pop_first_move(self) -> Move:
        return self.path.pop_first_move()

    def __str__(self):
        return f'off {self.str_start()}: {self.econValue:.2f}v/{self.turns}t ({self.econValue / max(1, self.turns):.2f}vt), {self.str_details()}'

    def str_start(self):
        return f'{self.path.tileList[0]}>{self.path.tileList[1] if len(self.path.tileList) > 1 else "?"}..{self.path.tail.tile}@{self.target_pivot_tile}'

    def str_details(self):
        return f'int%{self.chance_of_interception:.2f}, dmg{self.damage_prevented:.1f}, kill{self.is_kill_threat}, city{self.is_city_threat}, force{self.forcing_turns}'

    def str_no_vals(self):
        return f'{self.str_start()}: {self.str_details()}'

    def __repr__(self):
        return f'{str(self)}, path {self.path}'

    def clone(self) -> OffensiveThreatOptionInfo:
        clone = OffensiveThreatOptionInfo(
            self.path.clone(),
            self.chance_of_interception,
            dict(self.forced_army_info_by_tile_index),
            self.damage_prevented,
            self.is_kill_threat,
            self.is_city_threat,
            self.forcing_turns,
            self.target_pivot_tile,
            self.split_sub_option.clone() if self.split_sub_option is not None else None,
            self.double_back_path.clone() if self.double_back_path is not None else None,
            set(self.probable_capture_tiles),
            self.requiredDelay,
        )
        clone.econValue = self.econValue
        clone.turns = self.turns
        clone.raw_capture_econ_value = self.raw_capture_econ_value
        clone._tileList = self._tileList
        clone._tileSet = self._tileSet
        return clone


class OffenseAnalyzerPolicy:
    """
    Tunable constants for the offense analyzer.
    Defaults were confirmed by the prompter.
    """
    # Section A
    FOG_CANDIDATE_PLAY_AREA = 'core'  # use board_analysis.core_play_area_matrix
    MIN_FOG_SOURCE_SEPARATION = 5  # path-tile distance each purple fog source must be from every other selected source.
    FOG_ARMY_ASSOCIATION_DISTANCE = MIN_FOG_SOURCE_SEPARATION  # locked to the source separation constant for now.

    # Section B
    REVERSE_THREAT_BASE_CAPTURE_COST = 1  # base army at pivot is pivot.army + REVERSE_THREAT_BASE_CAPTURE_COST.

    # Section D
    FRIENDLY_COUNTER_USE_PLAYER_ONLY = False  # count all teammate tiles as friendly_tiles_traversed.

    # Section E
    STAGE_ONE_ECON_VALUE_INCLUDES_DAMAGE_PREVENTED = True  # econValue = raw_capture_econ_value + enemy_forced_damage.


@dataclass(slots=True)
class AnticipatedFogDistanceData:
    anticipated_army_value: float
    distance_matrix: MapMatrixInterface[int]


@dataclass(slots=True)
class PivotDistanceData:
    distance_matrix: MapMatrixInterface[int]
    army_needed_to_maintain_threat: MapMatrixInterface[float]


@dataclass(slots=True)
class FriendlyArmyDistData:
    distance_matrix: MapMatrixInterface[int]
    enemy_capture_count_matrix: MapMatrixInterface[int]
    army_remaining_matrix: MapMatrixInterface[int]


@dataclass(slots=True)
class CollectiveState:
    current_tile: Tile
    original_team_id: int
    source_tile: Tile
    distance: int
    army_remaining: float
    neutral_tiles_captured: int
    target_player_tiles_traversed: int
    friendly_tiles_traversed: int
    neutral_tiles_traversed: int

    def __lt__(self, other: CollectiveState) -> bool:
        return (
            self.distance,
            self.source_tile.tile_index,
            self.current_tile.tile_index,
        ) < (
            other.distance,
            other.source_tile.tile_index,
            other.current_tile.tile_index,
        )


@dataclass(slots=True, eq=False)
class StageOneState:
    current_tile: Tile
    previous_tile: Tile | None
    source_tile: Tile
    distance_from_start: int
    friendly_army_remaining: float
    target_player_tiles_traversed: int
    neutral_tiles_traversed: int
    pivot_tile: Tile
    parent: StageOneState | None


class OffenseAnalyzer(object):
    __slots__ = (
        'map',
        'board_analysis',
        'army_tracker',
        'opponent_tracker',
        'timer',
        'log_debug',
        'target_player',
        'target_player_expected_general_location',
        'friendly_team_id',
        'target_team_id',
        'anticipated_fog_armies',
        'all_en_armies_distance_matrix',
        'pivot_distances_by_tile_map',
        'all_pivots_distance_matrix',
        'friendly_army_dist_data',
        'offensive_tile_team_matrix',
        'offensive_tile_army_source_matrix',
        'offensive_tile_army_value_matrix',
        'offensive_num_friendly_traversed_matrix',
        'offensive_num_target_traversed_matrix',
        'offensive_num_neutral_traversed_matrix',
        'offensive_tile_distance_matrix',
    )

    def __init__(
            self,
            map: MapBase,
            boardAnalysis: BoardAnalyzer,
            armyTracker: ArmyTracker,
            opponentTracker: OpponentTracker,
            timer: PerformanceTimer,
            useDebugLogging: bool = False,
    ):
        self.map: MapBase = map
        self.board_analysis: BoardAnalyzer = boardAnalysis
        self.army_tracker: ArmyTracker = armyTracker
        self.opponent_tracker: OpponentTracker = opponentTracker
        self.timer: PerformanceTimer = timer
        self.log_debug: bool = useDebugLogging

        self.target_player: int = -1
        self.target_player_expected_general_location: Tile | None = None
        self.friendly_team_id: int = -1
        self.target_team_id: int = -1
        self.anticipated_fog_armies: dict[Tile, AnticipatedFogDistanceData] = {}
        self.all_en_armies_distance_matrix: MapMatrixInterface[int] | None = None
        self.pivot_distances_by_tile_map: dict[Tile, PivotDistanceData] = {}
        self.all_pivots_distance_matrix: MapMatrixInterface[int] | None = None
        self.friendly_army_dist_data: dict[Tile, FriendlyArmyDistData] = {}
        self.offensive_tile_team_matrix: MapMatrixInterface[int] | None = None
        self.offensive_tile_army_source_matrix: MapMatrixInterface[int | None] | None = None
        self.offensive_tile_army_value_matrix: MapMatrixInterface[float] | None = None
        self.offensive_num_friendly_traversed_matrix: MapMatrixInterface[int] | None = None
        self.offensive_num_target_traversed_matrix: MapMatrixInterface[int] | None = None
        self.offensive_num_neutral_traversed_matrix: MapMatrixInterface[int] | None = None
        self.offensive_tile_distance_matrix: MapMatrixInterface[int] | None = None

    def get_offense_options(
            self,
            bot,
            turns_left_in_cycle: int,
    ) -> list[OffensiveThreatOptionInfo]:
        """
        Returns a list of offensive threat options for the given bot state.
        """
        self._reset_analysis_state()
        self.target_player = bot.targetPlayer
        self.target_player_expected_general_location = bot.targetPlayerExpectedGeneralLocation
        self.friendly_team_id = self.map.team_ids_by_player_index[self.map.player_index]

        if self.target_player == -1:
            return []

        self.target_team_id = self.map.team_ids_by_player_index[self.target_player]

        with self.timer.begin_move_event('OffenseAnalyzer anticipated fog armies'):
            self._build_anticipated_fog_armies(bot)
        with self.timer.begin_move_event('OffenseAnalyzer all enemy armies distance matrix'):
            self._build_all_en_armies_distance_matrix()
        with self.timer.begin_move_event('OffenseAnalyzer pivot distances'):
            self._build_pivot_distances()
        with self.timer.begin_move_event('OffenseAnalyzer all pivots distance matrix'):
            self._build_all_pivots_distance_matrix()
        with self.timer.begin_move_event('OffenseAnalyzer friendly army dist'):
            self._build_friendly_army_dist()
        with self.timer.begin_move_event('OffenseAnalyzer collective offensive space'):
            self._build_collective_offensive_space()
        with self.timer.begin_move_event('OffenseAnalyzer stage-one interception paths'):
            return self._build_stage_one_interception_paths()

    def _reset_analysis_state(self) -> None:
        """
        Reset all per-call analysis state so stale data can never survive into a later turn.
        """
        self.target_player = -1
        self.target_player_expected_general_location = None
        self.friendly_team_id = -1
        self.target_team_id = -1
        self.anticipated_fog_armies = {}
        self.all_en_armies_distance_matrix = None
        self.pivot_distances_by_tile_map = {}
        self.all_pivots_distance_matrix = None
        self.friendly_army_dist_data = {}
        self.offensive_tile_team_matrix = None
        self.offensive_tile_army_source_matrix = None
        self.offensive_tile_army_value_matrix = None
        self.offensive_num_friendly_traversed_matrix = None
        self.offensive_num_target_traversed_matrix = None
        self.offensive_num_neutral_traversed_matrix = None
        self.offensive_tile_distance_matrix = None

    def _get_play_area_matrix(self) -> MapMatrixInterface[bool] | None:
        """
        Returns the play-area matrix used to scope fog candidate selection.
        """
        if OffenseAnalyzerPolicy.FOG_CANDIDATE_PLAY_AREA == 'extended':
            return self.board_analysis.extended_play_area_matrix
        return self.board_analysis.core_play_area_matrix

    def _is_valid_fog_candidate(self, tile: Tile) -> bool:
        """
        Determines whether an undiscovered tile is a plausible enemy fog army source.
        Mirrors the predicate used by BotTargeting.get_target_player_possible_general_location_tiles_sorted.
        """
        if tile.discovered or tile.isObstacle or tile.isGeneral:
            return False
        if not self.map.is_player_on_team_with(tile.player, self.target_player):
            return False
        if not self.army_tracker.valid_general_positions_by_player[self.target_player].raw[tile.tile_index]:
            return False
        return True

    def _build_anticipated_fog_armies(self, bot) -> None:
        """
        Section A: select up to 3 well-separated, friendly-side-close fog tiles as anticipated fog armies,
        include visible enemy general armies and the top 3 largest tracked enemy armies, and subtract
        tracked fog armies from anticipated fog sources within a deterministically chosen distance.
        """
        self.anticipated_fog_armies = {}
        if self.target_player == -1:
            return

        play_area_matrix = self._get_play_area_matrix()
        if play_area_matrix is None:
            if self.log_debug:
                logbook.warn('OffenseAnalyzer._build_anticipated_fog_armies: no play area matrix, aborting Section A')
            return

        # Candidate emergence values, starting with raw emergenceLocationMap values.
        candidate_emergence: dict[Tile, float] = {}
        for tile in self.map.get_all_tiles():
            if not play_area_matrix.raw[tile.tile_index]:
                continue
            if not self._is_valid_fog_candidate(tile):
                continue
            emergence = self.army_tracker.get_tile_emergence_for_player(tile, self.target_player)
            if emergence > 0:
                candidate_emergence[tile] = emergence

        # Also fold in recent explicit emergence locations from the opponent tracker so historical
        # emergence points survive even when the map's current top values have moved or decayed.
        for entry in self.opponent_tracker.get_last_attacked_from_locations(self.target_player, lastNRounds=3):
            if entry is None:
                continue
            amount, tile = entry
            if not play_area_matrix.raw[tile.tile_index]:
                continue
            if not self._is_valid_fog_candidate(tile):
                continue
            candidate_emergence[tile] = max(candidate_emergence.get(tile, 0.0), float(amount))

        # Build a friendly-side distance map for the closeness metric.
        friendly_dist_map = SearchUtils.build_distance_map_matrix(
            self.map,
            self.map.get_all_tiles_for_team(self.friendly_team_id),
        )

        # Select up to 3 sources. Prefer sources closest to the friendly side, using emergence
        # and tile_index as deterministic tie-breakers. Enforce a minimum separation by extending
        # a distance map from each selected source.
        selected_fog_sources: list[Tile] = []
        selected_separation_map: MapMatrixInterface[int] | None = None
        min_sep = OffenseAnalyzerPolicy.MIN_FOG_SOURCE_SEPARATION
        for tile in sorted(candidate_emergence.keys(), key=lambda t: (friendly_dist_map.raw[t.tile_index], -candidate_emergence[t], t.tile_index)):
            if len(selected_fog_sources) >= 3:
                break
            if selected_separation_map is not None and selected_separation_map.raw[tile.tile_index] < min_sep:
                continue
            selected_fog_sources.append(tile)
            if selected_separation_map is None:
                selected_separation_map = SearchUtils.build_distance_map_matrix(self.map, [tile])
            else:
                SearchUtils.extend_distance_map_matrix(self.map, [tile], selected_separation_map)

        # Determine the anticipated army value for each purple source from the opponent's immediate
        # fog risk, reduced by the path distance from that source to the predicted enemy general.
        predicted_general = self.target_player_expected_general_location
        city_spanning_tree = bot.friendly_city_spanning_tree
        city_spanning_tree_tile_count = 0 if city_spanning_tree is None else len(city_spanning_tree)
        immediate_fog_risk = self.opponent_tracker.get_immediate_fog_risk(self.target_player, city_spanning_tree_tile_count)[0]

        for tile in selected_fog_sources:
            if self.log_debug:
                logbook.info(f'OffenseAnalyzer anticipated fog source {tile} for p{self.target_player}')
            bot.viewInfo.add_targeted_tile(tile, TargetStyle.PURPLE, radiusReduction=-8)
            dist_matrix = self.map.distance_mapper.get_tile_dist_matrix(tile)
            if predicted_general is None:
                distance_to_general = 0
            else:
                distance_to_general = self.map.distance_mapper.get_distance_between(tile, predicted_general)
            anticipated_value = max(0.0, immediate_fog_risk - distance_to_general)
            self.anticipated_fog_armies[tile] = AnticipatedFogDistanceData(
                anticipated_army_value=anticipated_value,
                distance_matrix=dist_matrix,
            )

        # Include visible enemy general armies as concrete sources.
        visible_enemy_general = self.map.generals[self.target_player]
        if (
                visible_enemy_general is not None
                and visible_enemy_general.visible
                and visible_enemy_general.player == self.target_player
                and visible_enemy_general.army > 0
                and visible_enemy_general not in self.anticipated_fog_armies
        ):
            self.anticipated_fog_armies[visible_enemy_general] = AnticipatedFogDistanceData(
                anticipated_army_value=float(visible_enemy_general.army),
                distance_matrix=self.map.distance_mapper.get_tile_dist_matrix(visible_enemy_general),
            )

        # Keep the three largest tracked enemy armies as concrete sources.
        tracked_enemy_armies = [
            army for army in self.army_tracker.armies.values()
            if army.player == self.target_player
            or (army.player != -1 and self.map.is_player_on_team_with(army.player, self.target_player))
        ]
        tracked_enemy_armies.sort(key=lambda a: (-a.value, a.tile.tile_index))
        for army in tracked_enemy_armies[:3]:
            if army.tile in self.anticipated_fog_armies:
                continue
            self.anticipated_fog_armies[army.tile] = AnticipatedFogDistanceData(
                anticipated_army_value=float(army.value),
                distance_matrix=self.map.distance_mapper.get_tile_dist_matrix(army.tile),
            )

        # Subtract tracked fog armies from the matching selected purple source, using the nearest
        # selected source (tile_index tie-break) within the association distance.
        association_distance = OffenseAnalyzerPolicy.FOG_ARMY_ASSOCIATION_DISTANCE
        for army in tracked_enemy_armies[:3]:
            if army.tile.visible:
                continue
            nearest_source: Tile | None = None
            nearest_dist = 1000
            for source in selected_fog_sources:
                dist = self.anticipated_fog_armies[source].distance_matrix.raw[army.tile.tile_index]
                if dist > association_distance:
                    continue
                if nearest_source is None or dist < nearest_dist or (dist == nearest_dist and source.tile_index < nearest_source.tile_index):
                    nearest_source = source
                    nearest_dist = dist
            if nearest_source is not None:
                data = self.anticipated_fog_armies[nearest_source]
                data.anticipated_army_value = max(0.0, data.anticipated_army_value - army.value)

    def _build_all_en_armies_distance_matrix(self) -> None:
        """
        Aggregate all enemy army distance matrices into a single min-distance matrix.
        """
        if not self.anticipated_fog_armies:
            self.all_en_armies_distance_matrix = MapMatrix(self.map, 1000)
            return

        all_dist = MapMatrix(self.map, 1000)
        for data in self.anticipated_fog_armies.values():
            dist_matrix = data.distance_matrix
            for idx, dist in enumerate(dist_matrix.raw):
                if dist < all_dist.raw[idx]:
                    all_dist.raw[idx] = dist
        self.all_en_armies_distance_matrix = all_dist

    def _build_pivot_distances(self) -> None:
        """
        Section B: build per-pivot distance and reverse threat requirement matrices.
        Pivots are the target player's general and cities. The reverse threat matrix
        answers: starting at a tile, how much army is needed to reach this pivot while
        maintaining a real threat.
        """
        self.pivot_distances_by_tile_map = {}
        if self.target_player == -1:
            return

        target_player = self.map.players[self.target_player]
        pivot_tiles: list[Tile] = []
        for city in target_player.cities:
            if city is not None and city not in pivot_tiles:
                pivot_tiles.append(city)
        enemy_general = self.map.generals[self.target_player]
        if enemy_general is not None and enemy_general not in pivot_tiles:
            pivot_tiles.append(enemy_general)

        for pivot in pivot_tiles:
            dist_matrix = self.map.distance_mapper.get_tile_dist_matrix(pivot)
            army_needed = self._build_reverse_threat_matrix(pivot)
            self.pivot_distances_by_tile_map[pivot] = PivotDistanceData(
                distance_matrix=dist_matrix,
                army_needed_to_maintain_threat=army_needed,
            )

    def _build_reverse_threat_matrix(self, pivot: Tile) -> MapMatrixInterface[float]:
        """
        Reverse, target-outward search from a single pivot.  The matrix stores the
        minimum starting army required at each tile to reach the pivot while keeping
        the pivot under a real threat.
        """
        army_needed = MapMatrix(self.map, 1000.0)
        base = float(pivot.army + OffenseAnalyzerPolicy.REVERSE_THREAT_BASE_CAPTURE_COST)
        army_needed.raw[pivot.tile_index] = base

        # Use a simple queue and allow re-relaxation because friendly tiles reduce
        # the required army (negative edge weights). The graph is small; this is fine.
        queue = deque([pivot])
        best = {pivot.tile_index: base}

        while queue:
            current = queue.popleft()
            current_value = best[current.tile_index]
            current_depth = self.map.distance_mapper.get_distance_between(pivot, current)
            for nxt in current.movable:
                if nxt.isMountain or nxt.isNotPathable or nxt.isCostlyNeutral:
                    continue
                if not nxt.discovered and nxt.isUndiscoveredObstacle:
                    continue

                new_depth = current_depth + 1
                production = 1 if ((self.map.turn + new_depth) & 1) == 0 else 0
                if self.map.is_player_on_team_with(current.player, self.friendly_team_id):
                    cost = 1 - current.army
                else:
                    cost = current.army + 1
                new_value = current_value + cost + production

                # The pivot's own required capture cost is fixed; never let cycles through
                # friendly tiles reduce it below the base.  All other tiles floor at 0,
                # preventing negative cycles from large adjacent friendly armies.
                if nxt == pivot:
                    new_value = max(base, new_value)
                else:
                    new_value = max(0.0, new_value)

                if new_value < best.get(nxt.tile_index, 1000.0):
                    best[nxt.tile_index] = new_value
                    army_needed.raw[nxt.tile_index] = new_value
                    queue.append(nxt)

        return army_needed

    def _build_all_pivots_distance_matrix(self) -> None:
        """
        Aggregate all pivot distance matrices into a single min-distance matrix.
        """
        if not self.pivot_distances_by_tile_map:
            self.all_pivots_distance_matrix = MapMatrix(self.map, 1000)
            return

        all_dist = MapMatrix(self.map, 1000)
        for data in self.pivot_distances_by_tile_map.values():
            dist_matrix = data.distance_matrix
            for idx, dist in enumerate(dist_matrix.raw):
                if dist < all_dist.raw[idx]:
                    all_dist.raw[idx] = dist
        self.all_pivots_distance_matrix = all_dist

    def _build_friendly_army_dist(self) -> None:
        """
        Section C: for each friendly large army that is closer to an enemy pivot than to our own
        general, run a dedicated priority-queue route search and store the resulting matrices.
        """
        self.friendly_army_dist_data = {}
        if self.target_player == -1:
            return
        if self.all_pivots_distance_matrix is None:
            return
        if self.board_analysis.intergeneral_analysis is None:
            return

        pivot_dist = self.all_pivots_distance_matrix
        general_dist = self.board_analysis.intergeneral_analysis.aMap
        for source in self.board_analysis.largest_player_tiles:
            if pivot_dist.raw[source.tile_index] < general_dist.raw[source.tile_index]:
                self.friendly_army_dist_data[source] = self._build_friendly_army_dist_data(source)

    def _build_friendly_army_dist_data(self, source: Tile) -> FriendlyArmyDistData:
        """
        One priority-queue route search from a single friendly source.  Returns the distance,
        enemy-capture-count, and army-remaining matrices for that source.
        """
        dist_matrix = MapMatrix(self.map, 1000)
        captures_matrix = MapMatrix(self.map, 0)
        remaining_matrix = MapMatrix(self.map, 0)

        start_army = source.army - 1
        dist_matrix.raw[source.tile_index] = 0
        remaining_matrix.raw[source.tile_index] = start_army

        heap = [(0, 0, -start_army, source.tile_index, source)]
        settled = set()

        while heap:
            dist, neg_captures, neg_remaining, tile_idx, current = heapq.heappop(heap)
            if tile_idx in settled:
                continue
            settled.add(tile_idx)
            dist_matrix.raw[tile_idx] = dist
            captures_matrix.raw[tile_idx] = -neg_captures
            remaining_matrix.raw[tile_idx] = -neg_remaining
            # do not continue from a tile where the moving army has been exhausted
            if -neg_remaining <= 0:
                continue
            for nxt in current.movable:
                if nxt.isMountain or nxt.isNotPathable or nxt.isCostlyNeutral:
                    continue
                if self.map.is_player_on_team_with(nxt.player, self.friendly_team_id):
                    new_remaining = -neg_remaining + nxt.army - 1
                else:
                    new_remaining = -neg_remaining - (nxt.army + 1)
                if new_remaining < 0:
                    continue
                new_captures = -neg_captures
                if self.map.is_player_on_team_with(nxt.player, self.target_team_id) and nxt.player != -1:
                    new_captures += 1
                new_dist = dist + 1
                heapq.heappush(heap, (new_dist, -new_captures, -new_remaining, nxt.tile_index, nxt))

        return FriendlyArmyDistData(
            distance_matrix=dist_matrix,
            enemy_capture_count_matrix=captures_matrix,
            army_remaining_matrix=remaining_matrix,
        )

    def _build_collective_offensive_space(self) -> None:
        """
        Section D: one combined priority-queue search over all friendly large-army seeds
        and all target-player enemy/fog seeds.  Produces the collective ownership,
        army-value, source, and traversal-count matrices.
        """
        self.offensive_tile_team_matrix = MapMatrix(self.map, -1)
        self.offensive_tile_army_source_matrix = MapMatrix(self.map, None)
        self.offensive_tile_army_value_matrix = MapMatrix(self.map, 0.0)
        self.offensive_num_friendly_traversed_matrix = MapMatrix(self.map, 0)
        self.offensive_num_target_traversed_matrix = MapMatrix(self.map, 0)
        self.offensive_num_neutral_traversed_matrix = MapMatrix(self.map, 0)
        self.offensive_tile_distance_matrix = MapMatrix(self.map, 1000)

        seeds: dict[Tile, tuple[int, float]] = {}

        for source in self.friendly_army_dist_data.keys():
            seeds[source] = (self.friendly_team_id, float(source.army - 1))

        for tile, data in self.anticipated_fog_armies.items():
            if tile in seeds:
                continue
            seeds[tile] = (self.target_team_id, data.anticipated_army_value)

        visible_enemy_general = self.map.generals[self.target_player]
        if (
                visible_enemy_general is not None
                and visible_enemy_general.visible
                and visible_enemy_general.player == self.target_player
                and visible_enemy_general.army > 0
        ):
            seeds[visible_enemy_general] = (self.target_team_id, float(visible_enemy_general.army))

        tracked_enemy_armies = [
            army for army in self.army_tracker.armies.values()
            if army.player == self.target_player
            or (army.player != -1 and self.map.is_player_on_team_with(army.player, self.target_player))
        ]
        tracked_enemy_armies.sort(key=lambda a: (-a.value, a.tile.tile_index))
        for army in tracked_enemy_armies[:3]:
            seeds[army.tile] = (self.target_team_id, float(army.value))

        heap: list[CollectiveState] = []
        settled: set[int] = set()

        for tile, (team_id, army_value) in seeds.items():
            state = CollectiveState(
                current_tile=tile,
                original_team_id=team_id,
                source_tile=tile,
                distance=0,
                army_remaining=army_value,
                neutral_tiles_captured=0,
                target_player_tiles_traversed=0,
                friendly_tiles_traversed=0,
                neutral_tiles_traversed=0,
            )
            heapq.heappush(heap, state)

        while heap:
            state = heapq.heappop(heap)
            tile_idx = state.current_tile.tile_index
            if tile_idx in settled:
                settled_dist = self.offensive_tile_distance_matrix.raw[tile_idx]
                if state.distance < settled_dist:
                    continue
                if state.distance == settled_dist:
                    settled_team = self.offensive_tile_team_matrix.raw[tile_idx]
                    if state.original_team_id != settled_team and settled_team != -1:
                        self.offensive_tile_team_matrix.raw[tile_idx] = -1
                        self.offensive_tile_army_source_matrix.raw[tile_idx] = None
                continue

            settled.add(tile_idx)
            self.offensive_tile_distance_matrix.raw[tile_idx] = state.distance
            self.offensive_tile_team_matrix.raw[tile_idx] = state.original_team_id
            self.offensive_tile_army_source_matrix.raw[tile_idx] = state.source_tile.tile_index
            self.offensive_tile_army_value_matrix.raw[tile_idx] = state.army_remaining
            self.offensive_num_friendly_traversed_matrix.raw[tile_idx] = state.friendly_tiles_traversed
            self.offensive_num_target_traversed_matrix.raw[tile_idx] = state.target_player_tiles_traversed
            self.offensive_num_neutral_traversed_matrix.raw[tile_idx] = state.neutral_tiles_traversed

            if state.army_remaining <= 0:
                continue

            for nxt in state.current_tile.movable:
                if nxt.isMountain or nxt.isNotPathable or nxt.isCostlyNeutral:
                    continue
                if not nxt.discovered and nxt.isUndiscoveredObstacle:
                    continue

                is_same_team = nxt.player != -1 and self.map.is_player_on_team_with(nxt.player, state.original_team_id)
                if is_same_team:
                    new_army_remaining = state.army_remaining + nxt.army - 1
                else:
                    new_army_remaining = state.army_remaining - (nxt.army + 1)
                if new_army_remaining < 0:
                    continue

                new_friendly = state.friendly_tiles_traversed
                new_target = state.target_player_tiles_traversed
                new_neutral = state.neutral_tiles_traversed
                new_neutral_captured = state.neutral_tiles_captured

                if nxt.player == -1:
                    new_neutral += 1
                    new_neutral_captured += 1
                elif self.map.is_player_on_team_with(nxt.player, self.friendly_team_id):
                    if not OffenseAnalyzerPolicy.FRIENDLY_COUNTER_USE_PLAYER_ONLY or nxt.player == self.map.player_index:
                        new_friendly += 1
                elif nxt.player == self.target_player:
                    new_target += 1

                new_state = CollectiveState(
                    current_tile=nxt,
                    original_team_id=state.original_team_id,
                    source_tile=state.source_tile,
                    distance=state.distance + 1,
                    army_remaining=new_army_remaining,
                    neutral_tiles_captured=new_neutral_captured,
                    target_player_tiles_traversed=new_target,
                    friendly_tiles_traversed=new_friendly,
                    neutral_tiles_traversed=new_neutral,
                )
                heapq.heappush(heap, new_state)

    def _build_stage_one_interception_paths(self) -> list[OffensiveThreatOptionInfo]:
        """
        Section E: run an independent max-path-per-distance search for each friendly large
        army and produce stage-one OffensiveThreatOptionInfo objects.  A path may enter the
        first enemy-controlled or tied collective-space tile but cannot continue beyond it.
        """
        options: list[OffensiveThreatOptionInfo] = []

        if not self.friendly_army_dist_data or not self.pivot_distances_by_tile_map:
            return options

        if (
                self.offensive_tile_team_matrix is None
                or self.offensive_num_target_traversed_matrix is None
                or self.offensive_num_neutral_traversed_matrix is None
                or self.all_en_armies_distance_matrix is None
                or self.all_pivots_distance_matrix is None
        ):
            return options

        max_depth = 20
        max_iterations = 1000
        pivot_data_list = list(self.pivot_distances_by_tile_map.values())

        for source in self.friendly_army_dist_data.keys():
            start_pivot, start_needed = self._stage_one_select_viable_pivot(source, source.army - 1, pivot_data_list)
            if start_pivot is None:
                continue

            start_state = StageOneState(
                current_tile=source,
                previous_tile=None,
                source_tile=source,
                distance_from_start=0,
                friendly_army_remaining=float(source.army - 1),
                target_player_tiles_traversed=0,
                neutral_tiles_traversed=0,
                pivot_tile=start_pivot,
                parent=None,
            )

            heap: list[tuple[tuple, int, StageOneState]] = []
            heapq.heappush(heap, (self._stage_one_priority_tuple(start_state), id(start_state), start_state))

            best_by_distance: dict[int, tuple[tuple[float, float], OffensiveThreatOptionInfo]] = {}
            iterations = 0

            while heap and iterations < max_iterations:
                iterations += 1
                _, _, state = heapq.heappop(heap)
                current_team = self.offensive_tile_team_matrix.raw[state.current_tile.tile_index]

                if current_team != self.friendly_team_id:
                    value_tuple = self._stage_one_value_tuple(state)
                    if value_tuple is not None:
                        dist = state.distance_from_start
                        existing = best_by_distance.get(dist)
                        if existing is None or value_tuple > existing[0]:
                            best_by_distance[dist] = (value_tuple, self._stage_one_option_from_state(state))
                    continue

                if state.distance_from_start >= max_depth:
                    continue

                for nxt in state.current_tile.movable:
                    if nxt.isMountain or nxt.isNotPathable or nxt.isCostlyNeutral:
                        continue
                    if not nxt.discovered and nxt.isUndiscoveredObstacle:
                        continue

                    is_same_team = nxt.player != -1 and self.map.is_player_on_team_with(nxt.player, self.friendly_team_id)
                    if is_same_team:
                        new_remaining = state.friendly_army_remaining + nxt.army - 1
                    else:
                        new_remaining = state.friendly_army_remaining - (nxt.army + 1)
                    if new_remaining < 0:
                        continue

                    new_target = state.target_player_tiles_traversed
                    new_neutral = state.neutral_tiles_traversed
                    if nxt.player == -1:
                        new_neutral += 1
                    elif nxt.player == self.target_player:
                        new_target += 1

                    pivot, needed = self._stage_one_select_viable_pivot(nxt, new_remaining, pivot_data_list)
                    if pivot is None:
                        continue

                    new_state = StageOneState(
                        current_tile=nxt,
                        previous_tile=state.current_tile,
                        source_tile=source,
                        distance_from_start=state.distance_from_start + 1,
                        friendly_army_remaining=new_remaining,
                        target_player_tiles_traversed=new_target,
                        neutral_tiles_traversed=new_neutral,
                        pivot_tile=pivot,
                        parent=state,
                    )
                    heapq.heappush(heap, (self._stage_one_priority_tuple(new_state), id(new_state), new_state))

            options.extend(option for _, option in best_by_distance.values())

        return self._stage_one_deduplicate_options(options)

    def _stage_one_select_viable_pivot(
            self,
            tile: Tile,
            army_remaining: float,
            pivot_data_list: list[PivotDistanceData],
    ) -> tuple[Tile | None, float]:
        """
        Return the pivot with the lowest army-needed-to-maintain-threat at the given tile
        that is still within the remaining army.  If none, return (None, 1000.0).
        """
        best_pivot: Tile | None = None
        best_needed = 1000.0
        for data in pivot_data_list:
            needed = data.army_needed_to_maintain_threat.raw[tile.tile_index]
            if needed < best_needed:
                best_needed = needed
                best_pivot = data.distance_matrix  # placeholder; replaced below
                # Find the pivot tile associated with this distance matrix.
                for pivot, pivot_data in self.pivot_distances_by_tile_map.items():
                    if pivot_data is data:
                        best_pivot = pivot
                        break

        if best_pivot is None or best_needed > army_remaining:
            return None, best_needed
        return best_pivot, best_needed

    def _stage_one_priority_tuple(self, state: StageOneState) -> tuple:
        return (
            state.distance_from_start,
            self.all_pivots_distance_matrix.raw[state.current_tile.tile_index],
            -state.target_player_tiles_traversed,
            -state.friendly_army_remaining,
            state.source_tile.tile_index,
            state.current_tile.tile_index,
        )

    def _stage_one_value_tuple(self, state: StageOneState) -> tuple[float, float] | None:
        """
        Compute the comparable value for a non-friendly endpoint.  Returns None if the
        endpoint has no concrete target-team enemy context.
        """
        current_team = self.offensive_tile_team_matrix.raw[state.current_tile.tile_index]
        if current_team == self.friendly_team_id:
            return None

        enemy_context = self._stage_one_select_enemy_context_tile(state.current_tile)
        if enemy_context is None:
            return None

        enemy_forced_damage = (
            2 * self.offensive_num_target_traversed_matrix.raw[enemy_context.tile_index]
            + self.offensive_num_neutral_traversed_matrix.raw[enemy_context.tile_index]
        )
        friendly_pressure = (
            2 * state.target_player_tiles_traversed
            + state.neutral_tiles_traversed
        )
        stage_one_econ_value = enemy_forced_damage + friendly_pressure
        return stage_one_econ_value, state.friendly_army_remaining

    def _stage_one_select_enemy_context_tile(self, current: Tile) -> Tile | None:
        """
        For a target-owned endpoint, the context is the endpoint itself.  For a tied
        endpoint, choose the target-team movable with the lowest all_en_armies_distance
        value, using tile_index as the tie-breaker.
        """
        current_team = self.offensive_tile_team_matrix.raw[current.tile_index]
        if current_team == self.target_team_id:
            return current

        if current_team != -1:
            return None

        best: Tile | None = None
        best_dist = 1000
        for nxt in current.movable:
            if nxt.isMountain or nxt.isNotPathable or nxt.isCostlyNeutral:
                continue
            if self.offensive_tile_team_matrix.raw[nxt.tile_index] != self.target_team_id:
                continue
            dist = self.all_en_armies_distance_matrix.raw[nxt.tile_index]
            if dist < best_dist or (dist == best_dist and nxt.tile_index < best.tile_index):
                best_dist = dist
                best = nxt
        return best

    def _stage_one_option_from_state(self, state: StageOneState) -> OffensiveThreatOptionInfo:
        """
        Reconstruct the path from the source to the current state and wrap it in an
        OffensiveThreatOptionInfo with stage-one economic metadata.
        """
        tiles: list[Tile] = []
        s: StageOneState | None = state
        while s is not None:
            tiles.append(s.current_tile)
            s = s.parent
        tiles.reverse()

        path = Path(armyRemaining=state.friendly_army_remaining)
        path.add_start(tiles[0])
        for tile in tiles[1:]:
            path.add_next(tile)

        enemy_context = self._stage_one_select_enemy_context_tile(state.current_tile)
        if enemy_context is None:
            enemy_forced_damage = 0.0
        else:
            enemy_forced_damage = (
                2 * self.offensive_num_target_traversed_matrix.raw[enemy_context.tile_index]
                + self.offensive_num_neutral_traversed_matrix.raw[enemy_context.tile_index]
            )
        friendly_pressure = (
            2 * state.target_player_tiles_traversed
            + state.neutral_tiles_traversed
        )
        path.econValue = friendly_pressure

        return OffensiveThreatOptionInfo(
            path=path,
            chance_of_interception=0.0,
            forced_army_info_by_tile_index={},
            damage_prevented=enemy_forced_damage,
            is_kill_threat=False,
            is_city_threat=False,
            forcing_turns=0,
            target_pivot_tile=state.pivot_tile,
        )

    def _stage_one_deduplicate_options(self, options: list[OffensiveThreatOptionInfo]) -> list[OffensiveThreatOptionInfo]:
        """
        Deduplicate options by source tile, endpoint tile, selected pivot, and path tile
        sequence.  Retain the higher economic value, then the higher endpoint army.
        """
        best: dict[tuple[int, int, int, tuple[int, ...]], OffensiveThreatOptionInfo] = {}
        for option in options:
            if option.path.start is None or option.path.tail is None:
                continue
            source = option.path.tileList[0]
            endpoint = option.path.tail.tile
            pivot = option.target_pivot_tile
            path_key = tuple(t.tile_index for t in option.path.tileList)
            key = (source.tile_index, endpoint.tile_index, pivot.tile_index, path_key)
            existing = best.get(key)
            if existing is None or (option.econValue, option.path.value) > (existing.econValue, existing.path.value):
                best[key] = option
        return list(best.values())
