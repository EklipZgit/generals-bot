from __future__ import annotations

import typing
from dataclasses import dataclass

import logbook

from DangerAnalyzer import ThreatObj, ThreatType
from Interfaces import MapMatrixInterface, TilePlanInterface
from Interfaces.TilePlanInterface import PathMove
from Models import Move
from Path import Path
from base.client.map import Tile

# TODO remove me once things fixed
DEBUG_BYPASS_BAD_INTERCEPTIONS = True

# Note this is increased by 0.05 over the baseline expansion target cap value in order to slightly prioritize making efficient move use.
# Important for passing tests like test_should_intercept_early_game_near_collision_when_have_too_much_to_spend_rest_of_round_capping etc.
TARGET_CAP_VALUE = 2.1
OTHER_PARTY_CAP_VALUE = 0.5
NEUTRAL_CAP_VALUE = 1.0
GENERAL_CAP_VALUE = 8.0
OWNED_CITY_CAP_VALUE_BONUS = 5
# needs to be high enough to outperform normal expand, or normal expand will try to skip the intercept in favor of dodging the army for captures lmao
RECAPTURE_VALUE = 2.1


class ThreatValueInfo(object):
    __slots__ = (
        'threat',
        'econ_value',
        'turns_used_by_enemy',
        'econ_value_per_turn',
        'positive_subsegment_tileset',
    )

    def __init__(self, threat: ThreatObj, econValue: float, turns: int, positive_subsegment_tileset: set[Tile]):
        self.threat: ThreatObj = threat
        self.econ_value: float = econValue
        self.turns_used_by_enemy: int = turns
        self.econ_value_per_turn: float = econValue / max(1, turns)
        self.positive_subsegment_tileset: set[Tile] = positive_subsegment_tileset

    def __str__(self):
        return f'Threat {self.threat.path.start.tile}-->{self.threat.path.tail.tile} (econ {self.econ_value:.2f}, turns {self.turns_used_by_enemy}, vt {self.econ_value_per_turn:.2f}) {self.threat}'

    def __repr__(self):
        return str(self)


class ThreatBlockInfo(object):
    __slots__ = (
        'tile',
        'amount_needed_to_block',
        'blocked_destinations',
    )

    def __init__(self, tile: Tile, amount_needed_to_block: int):
        self.tile: Tile = tile
        self.amount_needed_to_block: int = amount_needed_to_block
        # list, not set, because set is slower to check than list for small numbers of entries, and we can never have more than 4
        self.blocked_destinations: typing.List[Tile] = []

    def add_blocked_destination(self, tile: Tile):
        if tile not in self.blocked_destinations:
            self.blocked_destinations.append(tile)

    def __str__(self) -> str:
        return f'{str(self.tile)}:{str(self.amount_needed_to_block)}@{"|".join([str(t) for t in self.blocked_destinations])}'


@dataclass(slots=True)
class InterceptCollisionResult:
    turns_left: int
    friendly_army_at_intercept: int
    best_case_intercept_turn: int
    worst_case_intercept_turn: int
    enemy_intercept_point_node: PathMove
    enemy_physical_army_at_intercept: int


class InterceptPointTileInfo(object):
    __slots__ = (
        'tile',
        'max_delay_turns',
        'max_extra_moves_to_capture',
        'max_choke_width',
        'max_intercept_turn_offset',
        'max_search_dist',
    )

    def __init__(self, tile: Tile, maxDelayTurns: int, maxExtraMoves: int, maxChokeWidth: int, maxInterceptTurnOffset: int):
        self.tile: Tile = tile

        self.max_delay_turns: int = maxDelayTurns
        """The latest turns in the future that this tile must be reached in order to prevent subsequent damage in the worst case scenarios."""

        self.max_extra_moves_to_capture: int = maxExtraMoves
        """The maximum worst case number of moves that will be wasted to complete an intercept capture from this tile if reached by the min_delay_turns turn."""

        self.max_choke_width: int = maxChokeWidth
        """The width of the max choke. Informational only?"""

        self.max_intercept_turn_offset: int = maxInterceptTurnOffset
        """Mostly useless? The max offset based on chokewidths and distances to chokes, used to calculate the max_delay_turns"""

        self.max_search_dist: int = 30
        """Used to limit time spent searching mediocre intercept points."""

    def __str__(self) -> str:
        return f'{self.tile} - it{self.max_delay_turns}, cw{self.max_choke_width}, ic{self.max_intercept_turn_offset}, im{self.max_extra_moves_to_capture}'

    def __repr__(self) -> str:
        return str(self)


class InterceptionOptionInfo(TilePlanInterface):
    __slots__ = (
        'path',
        'econValue',
        'turns',
        'damage_blocked',
        'intercepting_army_remaining',
        'recapture_turns',
        'best_case_intercept_moves',
        'worst_case_intercept_moves',
        'requiredDelay',
        'friendly_army_reaching_intercept',
        'intercept',
    )

    def __init__(
            self,
            path: Path,
            econValue: float,
            turns: int,
            damageBlocked: float,
            interceptingArmyRemaining: int,
            bestCaseInterceptMoves: int,
            worstCaseInterceptMoves: int,
            recaptureTurns: int,
            requiredDelay: int,
            friendlyArmyReachingIntercept: int,
    ):
        self.path: Path = path
        if path is None or path.start is None:
            raise Exception(f"Wtf, dont pass interception a bad path :V {path}")

        self.econValue: float = econValue
        self.turns: int = turns
        self.damage_blocked: float = damageBlocked
        """The economic damage prevented by this intercept."""
        self.intercepting_army_remaining: int = interceptingArmyRemaining
        """The amount of the attacking army that will likely be remaining after the intercept completes AT the intercept point."""

        self.recapture_turns: int = recaptureTurns
        """Number of turns AVAILABLE to recapture at round end that have NOT been included already in the option, based on army left over at intercept."""

        self.best_case_intercept_moves: int = bestCaseInterceptMoves
        """Best case turns-to-intercept, if they walk right towards our army."""

        self.worst_case_intercept_moves: int = worstCaseInterceptMoves
        """Worst case turns-to-intercept"""

        self.requiredDelay: int = requiredDelay

        self.friendly_army_reaching_intercept: int = friendlyArmyReachingIntercept
        """
        The amount of friendly army that reaches the destination tile EXCLUDING friendly army that is already on the destination tile if the destination tile is on the threat path.
        """

        self.intercept: ArmyInterception | None = None
        self._tileSet: set[Tile] | None = None
        self._tileList: list[Tile] | None = None

    @property
    def post_intercept_implied_moves(self) -> int:
        """
        Number of moves we expect to spend recapturing after the intercept path completes.

        Note 1 move may be wasted chasing if the intercept happens adjacently on a non-priority move, so factor in that this could be over-shooting the number of available recapture turns by 1.
        """
        return self.turns - self.path.length

    @property
    def length(self) -> int:
        return max(self.turns, self.path.length + self.recapture_turns, self.best_case_intercept_moves)

    def __iter__(self) -> typing.Iterator[PathMove]:
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
            self._tileList.append(self.intercept.target_tile)
        return self._tileList


    def get_move_list(self) -> typing.List[Move]:
        return self.path.get_move_list()

    def get_first_move(self) -> Move:
        return self.path.get_first_move()

    def pop_first_move(self) -> Move:
        return self.path.pop_first_move()

    def __str__(self):
        return f'int {self.str_start()}: {self.econValue:.2f}v/{self.turns}t ({self.econValue / max(1, self.turns):.2f}vt), {self.str_details()}'

    def str_start(self):
        tgTile = 'NONE'
        if self.intercept is not None:
            tgTile = str(self.intercept.target_tile)
        return f'{self.path.tileList[0]}>{self.path.tileList[1]}..{self.path.tail.tile}@{tgTile}'

    def str_details(self):
        return f'del{self.requiredDelay}, rc{self.recapture_turns}, blk{self.damage_blocked:.1f}, ear{self.intercepting_army_remaining}, bct{self.best_case_intercept_moves}, wct{self.worst_case_intercept_moves}'

    def str_no_vals(self):
        return f'{self.str_start()}: {self.str_details()}'

    def __repr__(self):
        return f'{str(self)}, path {self.path}'

    def clone(self) -> InterceptionOptionInfo:
        clone = InterceptionOptionInfo(
            self.path.clone(),
            self.econValue,
            self.turns,
            self.damage_blocked,
            self.intercepting_army_remaining,
            self.best_case_intercept_moves,
            self.worst_case_intercept_moves,
            self.recapture_turns,
            self.requiredDelay,
            self.friendly_army_reaching_intercept)
        clone.intercept = self.intercept
        clone._tileList = self._tileList
        clone._tileSet = self._tileSet
        return clone


class ArmyInterception(object):
    __slots__ = (
        'threat_values',
        'threats',
        'ignored_threats',
        'base_threat_army',
        'common_intercept_chokes',
        'middlest_intercept_tiles',
        'furthest_common_intercept_distances',
        'target_tile',
        'kill_enemy_threat',
        'best_enemy_threat',
        'distance_from_threat_to_contestable_en_city',
        'intercept_options',
        'positive_threat_subsegment_negative_tile_indexes',
        'sparse_recapture_bonus',
    )

    def __init__(
        self,
        threats: typing.List[ThreatValueInfo],
        ignoredThreats: typing.List[ThreatObj]
    ):
        self.threat_values: typing.List[ThreatValueInfo] = threats
        self.threats: typing.List[ThreatObj] = [t.threat for t in threats]

        self.ignored_threats: typing.List[ThreatObj] = ignoredThreats

        self.base_threat_army: int = 0
        self.common_intercept_chokes: typing.Dict[Tile, InterceptPointTileInfo] = {}
        self.middlest_intercept_tiles: typing.Set[Tile] = set()
        self.furthest_common_intercept_distances: MapMatrixInterface[int] = None
        self.target_tile: Tile = threats[0].threat.path.start.tile

        self.sparse_recapture_bonus: float = 1.0
        """EG in early game intercepts in round 2 for example, not only are we blocking the opp from doing damage but we're forcing extra retraversals out of them from their general for at least 4+ bonus damage vs just trade-capturing, in many cases."""

        maxValPerTurn = -100000
        maxThreatInfo = None
        isMaxThreatKill = False

        killThreats = []
        # check kill threats first
        for threatInfo in threats:
            if threatInfo.threat.threatType != ThreatType.Kill or threatInfo.threat.threatValue < 0:
                continue

            killThreats.append(threatInfo)

            val = threatInfo.econ_value
            valPerTurn = threatInfo.econ_value_per_turn
            if valPerTurn == maxValPerTurn and threatInfo.threat.path.length < maxThreatInfo.threat.path.length:
                maxValPerTurn -= 1

            if valPerTurn > maxValPerTurn:
                maxValPerTurn = valPerTurn
                maxThreatInfo = threatInfo
                isMaxThreatKill = True

        self.kill_enemy_threat: ThreatValueInfo = maxThreatInfo
        """The highest econ kill threat, should one exist."""

        self.positive_threat_subsegment_negative_tile_indexes: set[Tile] = set()

        # check non-kill threats second
        for threatInfo in threats:
            self.positive_threat_subsegment_negative_tile_indexes.update(threatInfo.positive_subsegment_tileset)
            if threatInfo in killThreats:
                continue

            val = threatInfo.econ_value
            valPerTurn = threatInfo.econ_value_per_turn

            if valPerTurn > maxValPerTurn or (valPerTurn == maxValPerTurn and threatInfo.threat.path.length > maxThreatInfo.threat.path.length and not isMaxThreatKill):
                if isMaxThreatKill:
                    logbook.warning(f'WARNING: replacing best_enemy_threat kill threat with non-kill:\r\nreplacing: {maxThreatInfo.threat}\r\nwith: {threatInfo.threat}')
                isMaxThreatKill = False
                maxValPerTurn = valPerTurn
                maxThreatInfo = threatInfo

        self.best_enemy_threat: ThreatValueInfo = maxThreatInfo
        """The highest econ value per turn threat. MAY NOT BE A KILL THREAT WHILE A KILL THREAT EXISTS."""
        if self.kill_enemy_threat is None:
            self.kill_enemy_threat = self.best_enemy_threat

        self.distance_from_threat_to_contestable_en_city: int = -1

        self.intercept_options: typing.Dict[int, InterceptionOptionInfo] = {}
        """turnsToIntercept -> econValueOfIntercept, interceptPath"""

    def get_intercept_plan_values_by_path(self, path: Path) -> typing.Tuple[int | None, float | None]:
        """returns distance, value"""
        for dist, optionInfo in self.intercept_options.items():
            val = optionInfo.econValue
            p = optionInfo.path
            if p.start.tile == path.start.tile and p.tail.tile == path.tail.tile:
                return dist, val

        return None, None

    def get_intercept_option_by_path(self, path: Path | TilePlanInterface) -> InterceptionOptionInfo | None:
        """returns distance, value"""
        if isinstance(path, InterceptionOptionInfo):
            return path

        if not isinstance(path, Path):
            return None

        for dist, optionInfo in self.intercept_options.items():
            p = optionInfo.path
            if p.start.tile == path.start.tile and p.tail.tile == path.tail.tile:
                return optionInfo

        return None
