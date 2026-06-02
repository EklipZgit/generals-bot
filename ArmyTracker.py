"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import annotations

import itertools
import typing

import DebugHelper
import SearchUtils
from Algorithms import MapSpanningUtils
from Army import Army
from BoardAnalyzer import BoardAnalyzer
from Interfaces import TileSet
from Models import Move
from MapMatrix import MapMatrixSet, TileSet
from PerformanceTimer import PerformanceTimer
from SearchUtils import *
from Path import Path
from base.client.map import Tile, TILE_OBSTACLE, TileDelta, Player, MODIFIER_TORUS, MAX_ALLY_SPAWN_DISTANCE, MIN_ALLY_SPAWN_DISTANCE

if typing.TYPE_CHECKING:
    from Strategy.OpponentTracker import OpponentTracker


class PlayerAggressionTracker(object):
    def __init__(self, index):
        self.player = index


class ArmyTracker(object):
    def __init__(self, map: MapBase, perfTimer: PerformanceTimer | None = None, opponentTracker: OpponentTracker | None = None):
        self.connectedByPlayer: typing.List[TileSet] = [set() for p in map.players]
        self.coreConnectedByPlayer: typing.List[TileSet] = [set() for p in map.players]
        """Connected by player except with ends trimmed to just the core of the graph."""

        self.perf_timer: PerformanceTimer = perfTimer
        if self.perf_timer is None:
            self.perf_timer = PerformanceTimer()
        self.player_moves_this_turn: typing.Set[int] = set()
        self.map: MapBase = map
        self.opponent_tracker: OpponentTracker | None = opponentTracker
        self.general: Tile = map.generals[map.player_index]

        self.log_debug = False

        self.armies: typing.Dict[Tile, Army] = {}
        """Actual armies. During a scan, this stores the armies that haven't been dealt with since last turn, still."""

        self.initial_expansion_tile_counts: typing.List[int] = [0 for p in self.map.players]

        self.should_recalc_fog_land_by_player: typing.List[bool] = [True for p in self.map.players]

        self.unaccounted_tile_diffs: typing.Dict[Tile, int] = {}
        """
        Used to keep track of messy army interaction diffs discovered when determining an army didn't
        do exactly what was expected to use to infer what armies on adjacent tiles did.
        Negative numbers mean attacked by opp, (or opp tile attacked by friendly army).
        Positive would mean ally merged with our army (or enemy ally merged with enemy army...?)
        """

        self.valid_general_positions_by_player: typing.List[MapMatrixSet] = [MapMatrixSet(map) for _ in self.map.players]
        """The true/false matrix of valid general positions by player"""
        #
        # self.player_fog_connections: typing.List[typing.Set[Tile]] = [set() for player in self.map.players]
        # """The tiles we assume are connecting """

        self.tiles_ever_owned_by_player: typing.List[typing.Set[Tile]] = [set([t for t in player.tiles if t.visible or t.discovered]) for player in self.map.players]
        """The set of tiles that we've ever seen owned by a player. TODO exclude tiles from player captures...?"""

        self.uneliminated_emergence_events: typing.List[typing.Dict[Tile, int]] = [{} for player in self.map.players]
        """The set of emergence events that have resulted in general location restrictions in the past and have not been dropped in favor of more restrictive restrictions."""

        self.unrecaptured_emergence_events: typing.List[typing.Set[Tile]] = [set() for player in self.map.players]
        """The set of emergence events from which an army emerged and the target player still owns the tile. ONLY counts when we didn't find an obvious emergence path for the player."""

        self.discovered_enemy_land_connector_tiles: typing.List[typing.Set[Tile]] = [set() for player in self.map.players]

        self.uneliminated_emergence_event_city_perfect_info: typing.List[typing.Set[Tile]] = [set() for player in self.map.players]
        """Whether a given emergence event had perfect city info or not."""

        self.pathed_fog_emergence_tiles = set()
        """Tiles that have been pathed successfully with good paths and thus have no emergence associated with them. Reset each turn."""

        self.seen_player_lookup: typing.List[bool] = [False for player in self.map.players]
        """Whether a player has been seen."""

        self.is_long_spawns: bool = len(self.map.players) == 2

        self.min_spawn_distance: int = 9
        if self.is_long_spawns:
            self.min_spawn_distance = 15
        if self.map.is_2v2:
            self.min_spawn_distance = 15

        if self.map.is_custom_map:
            self.min_spawn_distance = 1

        self._initialize_viable_general_positions()

        self.player_launch_timings = [0 for _ in self.map.players]
        self.skip_emergence_tile_pathings = set()

        self.updated_city_tiles: typing.Set[Tile] = set()
        self.unconnectable_tiles: typing.List[typing.Set[Tile]] = [set() for p in self.map.players]
        self.player_connected_tiles: typing.List[typing.Set[Tile]] = [set() for p in self.map.players]
        self.players_with_incorrect_tile_predictions: typing.Set[int] = set()
        """Cities that were revealed or changed players or mountains that were fog-guess-cities will get stuck here during map updates."""

        self.lastMove: Move | None = None
        self.track_threshold: int = 3
        """Minimum tile value required to track an 'army' for performance reasons."""
        self.update_track_threshold()

        self._flipped_tiles: typing.Set[Tile] = set()
        """Tracks any tile that changed players on a given turn"""

        self._flipped_by_army_tracker_this_turn: typing.List[typing.Tuple[int, Tile]] = []
        """The list of all (oldOwner,tile)s that were updated by armyTracker this turn."""

        self.fogPaths = []
        # TODO replace me with mapmatrix, emergenceLocationMap\[([^\]]+).x\]\[[^\]]+.y\]  -> emergenceLocationMap[$1]
        self.emergenceLocationMap: typing.List[MapMatrixInterface[float]] = [MapMatrix(self.map, 0.0) for z in range(len(self.map.players))]
        """List by player of emergence values."""

        self.player_targets: typing.List[Tile] = []
        """The list of tiles we expect an enemy player might be trying to attack."""

        self.notify_unresolved_army_emerged: typing.List[typing.Callable[[Tile], None]] = []
        self.notify_army_moved: typing.List[typing.Callable[[Army], None]] = []

        self.player_aggression_ratings = [PlayerAggressionTracker(z) for z in range(len(self.map.players))]
        self.lastTurn = -1
        self.decremented_fog_tiles_this_turn: typing.Set[Tile] = set()
        self.dropped_fog_tiles_this_turn: typing.Set[Tile] = set()
        self.fog_back_push_touched_tiles_this_turn: typing.Set[Tile] = set()
        self._boardAnalysis: BoardAnalyzer | None = None

    def __getstate__(self):
        state = self.__dict__.copy()

        if 'notify_unresolved_army_emerged' in state:
            del state['notify_unresolved_army_emerged']

        if 'notify_army_moved' in state:
            del state['notify_army_moved']

        if 'perf_timer' in state:
            del state['perf_timer']

        if 'opponent_tracker' in state:
            del state['opponent_tracker']

        # if '_boardAnalysis' in state:
        #     del state['_boardAnalysis']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.notify_unresolved_army_emerged = []
        self.notify_army_moved = []
        self.opponent_tracker = None

        if 'discovered_enemy_land_connector_tiles' not in self.__dict__:
            self.discovered_enemy_land_connector_tiles = [set() for player in self.map.players]

    # distMap used to determine how to move armies under fog
    def scan_movement_and_emergences(
            self,
            lastMove: Move | None,
            turn: int,
            boardAnalysis: BoardAnalyzer
    ):
        self.pathed_fog_emergence_tiles = set()
        self._flipped_by_army_tracker_this_turn = []
        self._boardAnalysis = boardAnalysis
        self.skip_emergence_tile_pathings = set()
        self.lastMove = lastMove
        self.decremented_fog_tiles_this_turn = set()
        self.dropped_fog_tiles_this_turn = set()
        self.fog_back_push_touched_tiles_this_turn = set()
        self.players_with_incorrect_tile_predictions = set()
        for player in self.map.players:
            if self.player_launch_timings[player.index] == 0 and player.tileCount > 1:
                if player.tileCount == 2:
                    self.player_launch_timings[player.index] = self.map.turn - 1
                else:
                    # then this is a unit test or custom map with starting tiles
                    self.player_launch_timings[player.index] = 24

        if self.map.turn == 50 and not self.map.is_low_cost_city_game:
            with self.perf_timer.begin_move_event(f'limiting player spawns by start value'):
                usTeam = self.map.team_ids_by_player_index[self.general.player]
                for player in self.map.players:
                    if player.team != usTeam and player.tileCount >= 22 and player.cityCount < 2:
                        # Then they can't have spawned at any tile with only one liberty.
                        self.limit_player_spawn_by_good_start(player)

        with self.perf_timer.begin_move_event('ArmyTracker neutral discovery'):
            self._pre_army_track_handle_flipped_tiles()

        with self.perf_timer.begin_move_event('ArmyTracker city rescan'):
            self.rescan_city_information()

        self.player_targets = self.map.players[self.map.player_index].cities.copy()
        self.player_targets.append(self.map.generals[self.map.player_index])
        for teammate in self.map.teammates:
            teamPlayer = self.map.players[teammate]
            self.player_targets.extend(teamPlayer.cities)
            self.player_targets.append(teamPlayer.general)

        fogDebugArmiesNearThreat = [
            army for army in self.armies.values()
            if army.tile is not None
        ]
        if self.log_debug:
            logbook.info(
                f'ARMY_TRACKER_SCAN_ENTRY turn={turn} lastTurn={self.lastTurn} armyCount={len(self.armies)} '
                f'fogArmiesNearThreat={[f"{army.tile}:{army.value}/lm{army.last_moved_turn}/ls{army.last_seen_turn}/vis{army.tile.visible}" for army in fogDebugArmiesNearThreat]}')

        advancedTurn = False
        if turn > self.lastTurn:
            advancedTurn = True
            if self.lastTurn == -1:
                logbook.info('armyTracker last turn wasnt set, exclusively scanning for new armies to avoid pushing fog tiles around on the turn the map was loaded up')
                self.lastTurn = turn
                self.find_new_armies()
                return

            self.lastTurn = turn
            self.player_moves_this_turn: typing.Set[int] = set()
        else:
            logbook.info(
                f'ARMY_TRACKER_SCAN_BAIL turn={turn} lastTurn={self.lastTurn} armyCount={len(self.armies)} '
                f'fogArmiesNearThreat={[f"{army.tile}:{army.value}/lm{army.last_moved_turn}/ls{army.last_seen_turn}/vis{army.tile.visible}" for army in fogDebugArmiesNearThreat]}')
            logbook.info(f'army tracker scan ran twice this turn {turn}...? Bailing?')
            return

        # if we have perfect info about a players general / cities, we don't need to track emergence, clear the emergence map
        for player in self.map.players:
            if player.team == self.map.friendly_team:
                continue
            if self.has_perfect_information_of_player_cities_and_general(player.index):
                logbook.info(f'Resetting p{player.index} emergences because we have perfect info at the moment.')
                self._reset_player_emergences(player.index)

        self.fogPaths = []

        with self.perf_timer.begin_move_event('ArmyTracker army movement'):
            self.track_army_movement()

        with self.perf_timer.begin_move_event('ArmyTracker non-neutral flipped tiles'):
            self._post_army_track_handle_flipped_tiles()
        self._flipped_tiles.clear()

        with self.perf_timer.begin_move_event('ArmyTracker find new armies'):
            self.find_new_armies()

        with self.perf_timer.begin_move_event('ArmyTracker fog movement / increment'):
            if advancedTurn:
                fogArmiesPreMove = [army for army in self.armies.values() if not army.tile.visible]
                fogArmiesNearThreatPreMove = fogArmiesPreMove
                if self.log_debug:
                    logbook.info(
                        f'ARMY_TRACKER_FOG_MOVE_STAGE turn={self.map.turn} advancedTurn={advancedTurn} '
                        f'fogArmyCount={len(fogArmiesPreMove)} '
                        f'nearThreat={[f"{army.tile}:{army.value}/lm{army.last_moved_turn}/ls{army.last_seen_turn}/ep{len(army.expectedPaths)}/ent{army.entangledValue}" for army in fogArmiesNearThreatPreMove]}')
                self.move_fogged_army_paths()
                self.increment_fogged_armies()

        for army in self.armies.values():
            if army.tile.visible:
                # logbook.info(f'updating {army}  last seen turn to {self.map.turn}')
                army.last_seen_turn = self.map.turn

        for player in self.map.players:
            if len(player.tiles) > 0:
                self.seen_player_lookup[player.index] = True

        for player in self.map.players:
            general = self.map.generals[player.index]
            if general and general.player != player.index and general.isGeneral:
                self.map.generals[player.index] = None
                general.isGeneral = False
                logbook.info(f'   RESET BAD GENERAL {general}')

    def limit_player_spawn_by_good_start(self, player, debugTile = None):
        if player.cityCount > 1:
            return
        if player.tileCount > 25:
            return
        if player.score > 52:
            return

        depthCheck = 15
        # isPerfect = player.tileCount == 25
        realWastesAllowed = (25 - player.tileCount) * 2
        pIdx = player.index

        tilesWithBarely = []
        tilesCouldntGetBetter = []
        biggestNegative = 0

        for tile in self.map.get_all_tiles():
            if not self.valid_general_positions_by_player[pIdx].raw[tile.tile_index]:
                continue

            wastesAllowed = realWastesAllowed

            foundByRange = [0] * (depthCheck + 1)

            def foreachFunc(t: Tile, d: int):
                if t.visible and t.player != player.index and t not in self.tiles_ever_owned_by_player[player.index]:
                    return True
                foundByRange[d] += 1

            SearchUtils.breadth_first_foreach_dist_fast_no_neut_cities(
                self.map,
                [tile],
                maxDepth=depthCheck,
                foreachFunc=foreachFunc,
            )

            # if isPerfect:
            #     numValid = len(list(tile.movableNoObstacles))
            #     if numValid == 1:
            #         self.valid_general_positions_by_player[pIdx].raw[tile.tile_index] = False
            #         for mv in tile.movableNoObstacles:
            #             if self.valid_general_positions_by_player[pIdx].raw[mv.tile_index]:
            #                 numValid = len(list(mv.movableNoObstacles))
            #                 if numValid <= 2:
            #                     self.valid_general_positions_by_player[pIdx].raw[mv.tile_index] = False

            isDebugTile = debugTile and debugTile.coords == tile.coords
            if isDebugTile:
                pass

            avail = wastesAllowed
            minValid = [1, 1, 4, 7, 10, 13, 15, 17, 19, 20, 21, 22, 23, 24, 24, 24]  # ethryns lower bound for arbitrary graphs (assumes infinite tiles at range 2 are available) -- tweaked to be -1 since counting general
            minValid = [1, 2, 5, 8, 11, 13, 16, 17, 19, 20, 21, 22, 23, 24, 24, 24]  # mine empirical
            minValid = [1, 2, 5, 8, 10, 13, 15, 17, 19, 20, 21, 22, 23, 24, 24, 24]  # with range 4 and range 6 adjusted downwards due to ethryn_hack_4_10__rx07Ek732.txtmap and ethryn_hack_6_15__rx07Ek732.txtmap counter-examples
            elimmed = False

            exactlyMets = 0
            barelyMets = 0
            for i in range(1, depthCheck + 1):
                avail += foundByRange[i]
                cutoff = minValid[i]
                if cutoff > avail:
                    if isDebugTile:
                        logbook.info(f'elimmed {tile} based on {i} min {cutoff} vs found {avail}')
                    elimmed = True
                    self.valid_general_positions_by_player[pIdx].raw[tile.tile_index] = False
                else:
                    if cutoff == avail and i > 2:
                        exactlyMets += 1
                    if cutoff > avail - 4:
                        barelyMets += 1
                    if isDebugTile:
                        logbook.info(f'legal   {tile} based on {i} min {cutoff} vs found {avail}')
            if isDebugTile:
                logbook.info(f'exactlyMets {exactlyMets}, barelyMets {barelyMets}')

            if elimmed:
                continue

            tilesWithBarely.append((exactlyMets, barelyMets, tile))
            if player.tileCount < 25:
                self.emergenceLocationMap[player.index].raw[tile.tile_index] += min(1.5, barelyMets / 2)

            exactPenalty = min(2, exactlyMets / 2)
            if exactPenalty > biggestNegative:
                biggestNegative = exactPenalty
            self.emergenceLocationMap[player.index].raw[tile.tile_index] -= exactPenalty

            if wastesAllowed > 0:
                wastesAllowed -= 2

                avail = wastesAllowed
                for i in range(1, depthCheck + 1):
                    avail += foundByRange[i]
                    cutoff = minValid[i]
                    if cutoff > avail:
                        if isDebugTile:
                            logbook.info(f'r2 elimmed {tile} based on {i} min {cutoff} vs found {avail}')
                        elimmed = True
                    else:
                        if isDebugTile:
                            logbook.info(f'r2 legal   {tile} based on {i} min {cutoff} vs found {avail}')

                if isDebugTile:
                    logbook.info(f'POST better check, elimmed waste {wastesAllowed}: {elimmed}')

                if elimmed:
                    tilesCouldntGetBetter.append(tile)

        # if player.tileCount > 22 and player.tileCount < 25:

        for tile in self.map.pathable_tiles:
            if not self.valid_general_positions_by_player[pIdx].raw[tile.tile_index]:
                continue
            self.emergenceLocationMap[player.index].raw[tile.tile_index] += biggestNegative

        if tilesCouldntGetBetter:
            for tile in tilesCouldntGetBetter:
                self.emergenceLocationMap[player.index].raw[tile.tile_index] += 3


    def update_fog_prediction(
            self,
            playerIndex: int,
            playersExpectedFogTileCounts: typing.Dict[int, int],
            predictedGeneralLocation: Tile | None,
            force: bool = False
    ):
        # TODO really, only REBUILD when player.index in self.players_with_incorrect_tile_predictions
        # Otherwise, just add or subtract one fog tile to match.
        player = self.map.players[playerIndex]
        if self.map.is_player_on_team_with(self.map.player_index, player.index) or (player.tileDelta == 0 and player.index not in self.players_with_incorrect_tile_predictions and not force and not self.should_recalc_fog_land_by_player[player.index] and len(self.map.players[playerIndex].tiles) != 0):
            return

        if self.should_recalc_fog_land_by_player[player.index] or len(self.map.players[playerIndex].tiles) == 0:
            if self.map.turn < 26:
                return
            self._build_fog_prediction_internal(player.index, playersExpectedFogTileCounts, predictedGeneralLocation)
            self.should_recalc_fog_land_by_player[player.index] = False
        else:
            self._inc_slash_dec_fog_prediction_to_get_player_tile_count_right(player.index, playersExpectedFogTileCounts, predictedGeneralLocation)

    def increment_fogged_armies(self):
        if not self.map.is_army_bonus_turn:
            return

        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(f'FOG DEBUG: Incrementing fogged armies for army bonus turn')
            fogArmies = [a for a in self.armies.values() if not a.tile.visible]
            logbook.info(f'FOG DEBUG: Found {len(fogArmies)} fog armies to increment')

        for army in list(self.armies.values()):
            if army.tile.visible:
                continue

            if army.tile.army > army.value + 1 > army.tile.army - 2:
                if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                    logbook.info(f'FOG DEBUG: Incrementing army {str(army)} from {army.value} to {army.value + 1}')
                army.value += 1
            else:
                if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                    logbook.info(f'FOG DEBUG: NOT incrementing army {str(army)} - army.tile.army={army.tile.army}, army.value={army.value}')

    def move_fogged_army_paths(self):
        armyVals = list(a for a in self.armies.values() if not a.tile.visible)
        fogArmiesNearThreat = armyVals
        if self.log_debug:
            logbook.info(
                f'FOG_PATH_TRACE_INVENTORY turn={self.map.turn} fogArmyCount={len(armyVals)} '
                f'nearThreat={[f"{army.tile}:{army.value}/lm{army.last_moved_turn}/ls{army.last_seen_turn}/ep{len(army.expectedPaths)}/ent{army.entangledValue}/player{army.player}" for army in fogArmiesNearThreat]}')
        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(f"FOG DEBUG: Starting move_fogged_army_paths with {len(armyVals)} fog armies")
        for army in armyVals:
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_TRACE_CANDIDATE turn={self.map.turn} army={army} tile={army.tile} '
                    f'value={army.value} tileArmy={army.tile.army} visible={army.tile.visible} '
                    f'player={army.player} isFriendly={army.player == self.map.player_index or army.player in self.map.teammates} '
                    f'playerMovedThisTurn={army.player in self.player_moves_this_turn} '
                    f'lastMoved={army.last_moved_turn} lastSeen={army.last_seen_turn} '
                    f'expectedPathCount={len(army.expectedPaths)} entangledValue={army.entangledValue}')
            if army.player == self.map.player_index or army.player in self.map.teammates:
                self.scrap_army(army, scrapEntangled=False)
                continue
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_TRACE_BEGIN turn={self.map.turn} army={army} tile={army.tile} '
                    f'value={army.value} tileArmy={army.tile.army} lastMoved={army.last_moved_turn} '
                    f'lastSeen={army.last_seen_turn} playerMovedThisTurn={army.player in self.player_moves_this_turn} '
                    f'expectedPathCount={len(army.expectedPaths)} entangledValue={army.entangledValue}')
            if army.last_moved_turn == self.map.turn - 1:
                if self.log_debug:
                    logbook.info(
                        f'FOG_PATH_TRACE_SKIP_ALREADY_MOVED turn={self.map.turn} army={army} tile={army.tile} '
                        f'valueBefore={army.value} tileArmy={army.tile.army} lastMoved={army.last_moved_turn} '
                        f'expectedPaths={[str(path) for path in army.expectedPaths]}')
                if self.log_debug:
                    logbook.info(f'FOG_PATH_SKIP_ALREADY_MOVED turn={self.map.turn} army={army} tileArmy={army.tile.army} entangledValue={army.entangledValue}')
                # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog covers a same-turn fog back-pushed entangled hypothesis whose tile is later contradicted by a low visible/discovered value. Do not turn that hypothesis into a real low-value phantom army; discard just that contradicted branch and let the remaining entangled alternatives survive.
                if army.entangledValue is not None and army.tile.army < max(1, int(army.entangledValue * 0.8)):
                    self.scrap_army(army, scrapEntangled=False)
                    continue
                army.value = army.tile.army - 1
                continue
            if army.player in self.player_moves_this_turn:
                if self.log_debug:
                    logbook.info(
                        f'FOG_PATH_TRACE_SKIP_PLAYER_MOVED turn={self.map.turn} army={army} tile={army.tile} '
                        f'player={army.player} playersMoved={sorted(self.player_moves_this_turn)}')
                if self.log_debug:
                    logbook.info(f'FOG_PATH_SKIP_PLAYER_MOVED turn={self.map.turn} army={army} player={army.player}')
                continue

            if not army.visible and army.last_seen_turn < self.map.turn - 10 and (army.tile.isCity or army.tile.isGeneral):
                logbook.info(f'skipping army {army} as it hasnt moved and is on a city/gen')
                continue

            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_PROCESS turn={self.map.turn} army={army} tile={army.tile} '
                    f'tileArmy={army.tile.army} value={army.value} entangledValue={army.entangledValue} '
                    f'entangled={[str(entangled) for entangled in army.entangledArmies]} '
                    f'paths={[str(path) for path in army.expectedPaths]}')

            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Processing fog army {str(army)} at {army.tile} with value {army.value}')
                logbook.info(f'FOG DEBUG: Army {str(army)} has {len(army.expectedPaths)} expected paths')

            origTile = army.tile
            origTileArmy = army.tile.army

            anyNextVisible = False
            fogPathNexts = {}
            for path in army.expectedPaths:
                if (path is None
                        or path.start is None
                        or path.start.next is None
                        or path.start.next.tile is None
                ):
                    continue
                nextTile = path.start.next.tile
                if nextTile.visible:
                    anyNextVisible = True
                    # can't move out of fog, so will leave tile there
                    nextTile = path.start.tile

                try:
                    nextPaths = fogPathNexts[nextTile]
                except KeyError:
                    nextPaths = []
                    fogPathNexts[nextTile] = nextPaths
                nextPaths.append(path)

            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Army {str(army)} fogPathNexts: {[(str(tile), len(paths)) for tile, paths in fogPathNexts.items()]}')

            # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog covers a split entangled fog army where one expected path is blocked by a visible tile. Moving another split branch in the same pass shuffles the tracked army onto a wrong fog tile, so hold the entangled hypothesis in place.
            # Fix: Filter out expected paths that touch visible tiles before the split-blocking check.
            # This removes stale paths like 3,9->4,9 when 4,9 becomes visible, allowing safe paths like 3,9->2,9 to proceed.
            # UnitTests/test_ArmyTracker.py::ArmyTrackerTests.test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog
            pathsBeforeFilter = len(army.expectedPaths)
            army.expectedPaths = [path for path in army.expectedPaths if path is not None and not any(tile.visible and tile != army.tile for tile in path.tileList)]
            if self.log_debug and pathsBeforeFilter != len(army.expectedPaths):
                logbook.info(
                    f'FOG_PATH_TRACE_FILTER_VISIBLE turn={self.map.turn} army={army} tile={army.tile} '
                    f'pathsBefore={pathsBeforeFilter} pathsAfter={len(army.expectedPaths)}')
            # Rebuild fogPathNexts after filtering
            fogPathNexts = {}
            for path in army.expectedPaths:
                if (path is None
                        or path.start is None
                        or path.start.next is None
                        or path.start.next.tile is None
                ):
                    continue
                nextTile = path.start.next.tile
                if nextTile.visible:
                    anyNextVisible = True
                    # can't move out of fog, so will leave tile there
                    nextTile = path.start.tile

                try:
                    nextPaths = fogPathNexts[nextTile]
                except KeyError:
                    nextPaths = []
                    fogPathNexts[nextTile] = nextPaths
                nextPaths.append(path)

            anySplitPathTouchesVisibleAfterArmy = False
            for path in army.expectedPaths:
                if path is None:
                    continue
                sawArmyTile = False
                for pathTile in path.tileList:
                    if pathTile == army.tile:
                        sawArmyTile = True
                        continue
                    if sawArmyTile and pathTile.visible:
                        anySplitPathTouchesVisibleAfterArmy = True
                        break
                if anySplitPathTouchesVisibleAfterArmy:
                    break
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_TRACE_SPLIT_CHECK turn={self.map.turn} army={army} tile={army.tile} '
                    f'nexts={[(str(tile), len(paths)) for tile, paths in fogPathNexts.items()]} '
                    f'anyNextVisible={anyNextVisible} anySplitPathTouchesVisibleAfterArmy={anySplitPathTouchesVisibleAfterArmy} '
                    f'entangledValue={army.entangledValue}')
            if len(fogPathNexts) > 1 and army.entangledValue is not None and anySplitPathTouchesVisibleAfterArmy:
                if self.log_debug:
                    logbook.info(
                        f'FOG_PATH_TRACE_SPLIT_BLOCKED turn={self.map.turn} army={army} tile={army.tile} '
                        f'reason=entangled_visible_after_army nexts={[(str(tile), len(paths)) for tile, paths in fogPathNexts.items()]}')
                continue

            if len(fogPathNexts) > 1:
                if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                    logbook.info(f'FOG DEBUG: SPLITTING army {str(army)} into {len(fogPathNexts)} paths')
                # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_collide_entangled_and_de_entangle_multiple_armies_correctly covers a small residual fog army created by resolving entanglement, then immediately split across speculative paths. Record the pre-split tile value once so every split clone reverts the original tile to the residual value instead of later clones recording the already-cleared value.
                army.record_fog_tile_revert(army.tile)
                self.armies.pop(army.tile, None)

                nextArmies = army.get_split_for_fog(list(fogPathNexts.keys()))

                for nextTile, paths in fogPathNexts.items():
                    nextArmy = nextArmies.pop()
                    nextArmy.expectedPaths = []

                    if nextTile == origTile:
                        for path in paths:
                            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                                logbook.info(f'for army {str(nextArmy)} ignoring SPLIT fog path move into visible: {str(path)}')
                            nextArmy.include_path(path)

                        if not nextArmy.scrapped:
                            self.armies[nextArmy.tile] = nextArmy

                        continue
                    for path in paths:
                        # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog covers a split clone that collides with an entangled sibling and is scrapped. Do not continue applying more expected paths to that scrapped clone, or a later visible-path stop can erase the tile value and cause a replacement phantom army to be created.
                        if nextArmy.scrapped:
                            if self.log_debug:
                                logbook.info(
                                    f'FOG_SPLIT_BREAK_PRE_SCRAPPED turn={self.map.turn} army={nextArmy} '
                                    f'path={path} tile={nextArmy.tile} value={nextArmy.value}')
                            break
                        # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog covers an entangled split where a clone has already been moved/collided by a previous path. Do not apply a stale split path whose first fog step no longer matches this clone's assigned next tile, or the visible-stop branch can resurrect a contradicted low-value duplicate.
                        if path.start is not None and path.start.next is not None and path.start.next.tile != nextTile:
                            continue
                        nextArmy.include_path(path)
                        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                            logbook.info(f'respecting army {str(nextArmy)} SPLIT fog path: {str(path)}')

                        self._move_fogged_army_along_path(nextArmy, path, armyAlreadyPopped=True)
                        if self.log_debug:
                            logbook.info(
                                f'FOG_SPLIT_MOVE_RESULT turn={self.map.turn} army={nextArmy} path={path} '
                                f'scrapped={nextArmy.scrapped} '
                                f'tile={nextArmy.tile} tileArmy={nextArmy.tile.army} value={nextArmy.value}')
                        if nextArmy.scrapped:
                            if self.log_debug:
                                logbook.info(
                                    f'FOG_SPLIT_BREAK_POST_MOVE turn={self.map.turn} army={nextArmy} path={path} '
                                    f'scrapped={nextArmy.scrapped}')
                            break

                        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                            logbook.info(f'AFTER: army {str(nextArmy)}: {str(nextArmy.expectedPaths)}')
                    if not nextArmy.scrapped:
                        self.armies[nextArmy.tile] = nextArmy

            elif len(fogPathNexts) == 1:
                if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                    logbook.info(f'FOG DEBUG: Army {str(army)} has single path, moving normally')
                for path in army.expectedPaths:
                    if path is not None and path.start.next is not None and path.start.next.tile.visible:
                        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                            logbook.info(f'for army {str(army)} ignoring fog path move into visible: {str(path)}')
                        if path.start.tile == army.tile and army.entangledValue is not None:
                            self.scrap_army(army, scrapEntangled=True)
                        continue

                    if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                        logbook.info(f'respecting army {str(army)} fog path: {str(path)}')

                    self._move_fogged_army_along_path(army, path)

                    if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                        logbook.info(f'AFTER: army {str(army)}: {str(army.expectedPaths)}')

            if anyNextVisible:
                # NEVER modify visible tile army values
                if not origTile.visible:
                    origTile.army = origTileArmy

    def clean_up_armies(self):
        for army in list(self.armies.values()):
            if army is not None and army.tile.visible:
                army.last_seen_turn = self.map.turn

            if army.scrapped:
                logbook.info(f"Army {str(army)} was scrapped last turn, deleting.")
                if army.tile in self.armies and self.armies[army.tile] == army:
                    del self.armies[army.tile]
                continue
            elif (army.player == self.map.player_index or army.player in self.map.teammates) and not army.tile.visible:
                logbook.info(f"Army {str(army)} was ours but under fog now, so was destroyed. Scrapping.")
                self.scrap_army(army, scrapEntangled=True)
            elif army.tile.visible and len(army.entangledArmies) > 0 and army.tile.player == army.player:
                if army.tile.army * 1.2 > army.value > (army.tile.army - 1) * 0.8:
                    # we're within range of expected army value, resolve entanglement :D
                    logbook.info(f"Army {str(army)} was entangled and rediscovered :D disentangling other armies")
                    self.resolve_entangled_armies(army)
                else:
                    logbook.info(
                        f"Army {str(army)} was entangled at this tile, but army value doesn't match expected?\n  - NOT army.tile.army * 1.2 ({army.tile.army * 1.2}) > army.value ({army.value}) > (army.tile.army - 1) * 0.8 ({(army.tile.army - 1) * 0.8})")
                    for entangled in army.entangledArmies:
                        logbook.info(f"    removing {str(army)} from entangled {str(entangled)}")
                        try:
                            entangled.entangledArmies.remove(army)
                        except:
                            pass
                    if army.tile in self.armies and self.armies[army.tile] == army:
                        del self.armies[army.tile]
                continue
            elif army.tile.delta.gainedSight and (
                    army.tile.player == -1 or (army.tile.player != army.player and len(army.entangledArmies) > 0)):
                logbook.info(
                    f"Army {str(army)} just uncovered was an incorrect army prediction. Disentangle and remove from other entangley bois")
                for entangled in army.entangledArmies:
                    logbook.info(f"    removing {str(army)} from entangled {str(entangled)}")
                    try:
                        entangled.entangledArmies.remove(army)
                    except:
                        pass

                if army.tile in self.armies and self.armies[army.tile] == army:
                    del self.armies[army.tile]

    def track_army_movement(self):
        # TODO tile.delta.imperfectArmyDelta

        # for army in list(self.armies.values()):
        #    self.determine_army_movement(army, adjArmies)
        trackingArmies = {}
        skip = set()

        # for tile in self.map.get_all_tiles():
        #     if tile.delta.armyDelta != 0 and not tile.delta.gainedSight and not tile.delta.lostSight:
        #         self.unaccounted_tile_diffs[tile] = tile.delta.armyDelta

        with self.perf_timer.begin_move_event('ArmyTracker move respect'):
            if self.lastMove is not None:
                playerMoveArmy = self.get_or_create_army_at(self.lastMove.source)
                playerMoveArmy.player = self.map.player_index
                playerMoveArmy.value = self.lastMove.source.delta.oldArmy - 1
                self.try_track_own_move(playerMoveArmy, skip, trackingArmies)

            for player in self.map.players:
                if player.index == self.map.player_index:
                    continue
                if player.last_move is not None:
                    src: Tile
                    dest: Tile
                    src, dest, movedHalf = player.last_move

                    try:
                        armyAtSrc = self.armies[src]
                    except KeyError:
                        continue

                    if armyAtSrc.player == player.index:
                        logbook.info(f'RESPECTING MAP DETERMINED PLAYER MOVE {str(src)}->{str(dest)} BY p{player.index} FOR ARMY {str(armyAtSrc)}')
                        self.army_moved(armyAtSrc, dest, trackingArmies, dontUpdateOldFogArmyTile=True)  # map already took care of this for us
                        skip.add(src)
                        # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_duplicate_army_out_of_fog covers a visible enemy move that the map already resolved from source to destination. Skipping only the source lets the later try_track_army pass reprocess the destination delta as if the same army moved again into adjacent fog, creating a duplicate tracker.
                        skip.add(dest)
                    else:
                        logbook.info(f'ARMY {str(armyAtSrc)} AT SOURCE OF PLAYER {player.index} MOVE {str(src)}->{str(dest)} DID NOT MATCH THE PLAYER THE MAP DETECTED AS MOVER, SCRAPPING ARMY...')
                        self.scrap_army(armyAtSrc, scrapEntangled=False)

        with self.perf_timer.begin_move_event('ArmyTracker emergence pathing'):
            self.unaccounted_tile_diffs: typing.Dict[Tile, int] = {}
            for tile, diffTuple in self.map.army_emergences.items():
                emergedAmount, emergingPlayer = diffTuple
                if emergingPlayer == -1:
                    continue

                self.should_recalc_fog_land_by_player[emergingPlayer] = True

                self.unaccounted_tile_diffs[tile] = emergedAmount
                # self.unaccounted_tile_diffs[tile] = emergedAmount
                # map has already dealt with ALL possible perfect-information moves.

                isMoveIntoFog = (
                    (
                        False
                        # (tile.delta.oldOwner == tile.player and tile.player != self.map.player_index)
                        or 0 - Tile.get_move_half_amount(tile.delta.oldArmy) == emergedAmount
                        or 0 - tile.delta.oldArmy + 1 == emergedAmount
                    )
                    and emergedAmount < 0  # must be negative emergence to be a move into fog
                )

                try:
                    existingArmy = self.armies[tile]
                except KeyError:
                    existingArmy = None

                if isMoveIntoFog:
                    if tile.delta.gainedSight and existingArmy:
                        logbook.info(
                            f'gainedSight splitting existingArmy back into fog 1 - emerged {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                        self.try_split_fogged_army_back_into_fog(existingArmy, trackingArmies)
                        skip.add(tile)
                    else:
                        logbook.info(f'IGNORING maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                    continue

                # Jump straight to fog source detection.
                if tile.delta.toTile is not None:
                    # the map does its job too well and tells us EXACTLY where the army emerged from, but armytracker wants the armies final destination and will re-do that work itself, so use the toTile.
                    # tile = tile.delta.toTile
                    if tile.delta.toTile in skip:
                        continue

                if tile.isCity and tile.discovered:
                    logbook.info(f'(TEMP NOT IG???) IGNORING maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it was a discovered city..?')
                    # continue

                if existingArmy and existingArmy.player == tile.player and existingArmy.value + 1 > tile.army:
                    logbook.info(f'TODO CHECK IF EVER CALLED splitting existingArmy back into fog 2 - emerged {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                    self.try_split_fogged_army_back_into_fog(existingArmy, trackingArmies)
                    skip.add(tile)
                    continue

                if emergedAmount < 0:
                    emergedAmount = 0 - emergedAmount

                logbook.info(f'Respecting maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} (from tile if known {repr(tile.delta.fromTile)})')
                emergedArmy = self.handle_unaccounted_delta(tile, emergingPlayer, emergedAmount)
                if emergedArmy is not None:
                    if tile.delta.toTile is not None and tile.delta.toTile.player == emergedArmy.player:
                        self.army_moved(emergedArmy, tile.delta.toTile, trackingArmies)
                        skip.add(tile.delta.toTile)
                    else:
                        trackingArmies[tile] = emergedArmy
                skip.add(tile)

        with self.perf_timer.begin_move_event('ArmyTracker lastmove loop'):
            for tile in self.map.get_all_tiles():
                if tile in skip:
                    continue
                if self.lastMove is not None and tile == self.lastMove.source:
                    continue
                if tile.delta.oldOwner == self.map.player_index:
                    # we track our own moves elsewhere
                    continue
                if tile.delta.toTile is None:
                    continue
                if tile.isUndiscoveredObstacle or tile.isMountain:
                    msg = f'are we really sure {str(tile)} moved to {str(tile.delta.toTile)}'
                    if BYPASS_TIMEOUTS_FOR_DEBUGGING:
                        raise AssertionError(msg)
                    else:
                        logbook.error(msg)
                        continue
                if tile.delta.toTile.isMountain:
                    msg = f'are we really sure {str(tile.delta.toTile)} was moved to from {str(tile)}'
                    if BYPASS_TIMEOUTS_FOR_DEBUGGING:
                        raise AssertionError(msg)
                    else:
                        logbook.error(msg)
                        continue

                # if armyDetectedAsMove is not None:
                armyDetectedAsMove = self.get_or_create_army_at(tile)
                logbook.info(f'Map detected army move, honoring that: {str(tile)}->{str(tile.delta.toTile)}')
                self.army_moved(armyDetectedAsMove, tile.delta.toTile, trackingArmies)
                if tile.delta.toTile.isUndiscoveredObstacle:
                    # if map detected a move into an obstacle, then
                    toTile = self.map.tiles_by_index[tile.delta.toTile.tile_index]
                    toTile.isCity = True
                    toTile.player = armyDetectedAsMove.player
                    toTile.army = armyDetectedAsMove.value
                    logbook.warning(f'CONVERTING {str(tile.delta.toTile)} UNDISCOVERED MOUNTAIN TO CITY DUE TO MAP SAYING DEFINITELY TILE MOVED THERE. {str(tile)}->{str(tile.delta.toTile)}')
                armyDetectedAsMove.update()
                if not tile.delta.toTile.visible:
                    # map knows what it is doing, force tile army update.
                    armyDetectedAsMove.value = tile.delta.toTile.army - 1

        with self.perf_timer.begin_move_event('ArmyTracker try_track_army loop'):
            for army in sorted(self.armies.values(), key=lambda a: self.map.get_distance_between(self.general, a.tile)):
                # any of our armies CANT have moved (other than the one handled explicitly above), ignore them, let other armies collide with / capture them.
                if army.player == self.map.player_index:
                    if army.last_moved_turn < self.map.turn - 1 and army.tile.army < self.track_threshold:
                        self.scrap_army(army, scrapEntangled=False)
                    else:
                        army.update()
                    continue

                self.try_track_army(army, skip, trackingArmies)

        with self.perf_timer.begin_move_event('ArmyTracker scrap unmoved'):
            self.scrap_unmoved_low_armies()

        for armyDetectedAsMove in trackingArmies.values():
            self.armies[armyDetectedAsMove.tile] = armyDetectedAsMove

        with self.perf_timer.begin_move_event('ArmyTracker clean up armies'):
            self.clean_up_armies()

    def find_visible_source(self, tile: Tile):
        if tile.delta.armyDelta == 0:
            return None

        for adjacent in tile.movable:
            isMatch = False
            unexplainedAdjDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
            if tile.delta.armyDelta + unexplainedAdjDelta == 0:
                isMatch = True

            if isMatch:
                logbook.info(
                    f"  Find visible source  {str(tile)} ({tile.delta.armyDelta}) <- {adjacent.toString()} ({unexplainedAdjDelta}) ? {isMatch}")
                return adjacent

        # try more lenient
        for adjacent in tile.movable:
            isMatch = False
            unexplainedAdjDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
            if 2 >= tile.delta.armyDelta + unexplainedAdjDelta >= -2:
                isMatch = True

            logbook.info(
                f"  Find visible source  {str(tile)} ({tile.delta.armyDelta}) <- {adjacent.toString()} ({unexplainedAdjDelta}) ? {isMatch}")
            if isMatch:
                return adjacent

        return None

    def army_moved(
            self,
            army: Army,
            toTile: Tile,
            trackingArmies: typing.Dict[Tile, Army],
            dontUpdateOldFogArmyTile=False,
            allowVisiblePlayerMismatch=False,
    ):
        """

        @param army:
        @param toTile:
        @param trackingArmies:
        @param dontUpdateOldFogArmyTile: If True, will not update the old fogged army tile to be 1
        @return:
        """
        oldTile = army.tile
        if self.log_debug:
            logbook.info(
                f'ARMY_MOVED_START turn={self.map.turn} army={army} oldTile={oldTile} toTile={toTile} '
                f'oldTileArmy={oldTile.army} toTileArmy={toTile.army} oldTileVisible={oldTile.visible} toTileVisible={toTile.visible} '
                f'dontUpdateOldFogArmyTile={dontUpdateOldFogArmyTile} armyValue={army.value} armyPlayer={army.player} '
                f'toTilePlayer={toTile.player} oldDelta={oldTile.delta.armyDelta} toDelta={toTile.delta.armyDelta}')
        existingArmy = self.armies.pop(army.tile, None)
        if army.visible and toTile.was_visible_last_turn(): # or visible?
            if army.player in self.player_moves_this_turn:
                logbook.error(f'Yo, we think player {army.player} moved twice this turn...? {str(army)} -> {str(toTile)}')

            self.player_moves_this_turn.add(army.player)

        try:
            existingTracking = trackingArmies[toTile]
        except KeyError:
            existingTracking = None

        if (
            existingTracking is None
            or existingTracking.value < army.value
            or existingTracking.player != toTile.player
        ):
            trackingArmies[toTile] = army

        try:
            potentialMergeOrKilled = self.armies[toTile]
        except KeyError:
            potentialMergeOrKilled = None
        if self.log_debug:
            logbook.info(
                f'ARMY_MOVED_COLLISION_CHECK turn={self.map.turn} army={army} toTile={toTile} '
                f'existingArmyFromOldTile={existingArmy} potentialMergeOrKilled={potentialMergeOrKilled} '
                f'existingTracking={existingTracking}')
        if potentialMergeOrKilled is not None:
            if potentialMergeOrKilled.player == army.player:
                self.merge_armies(army, potentialMergeOrKilled, toTile, trackingArmies)
            elif toTile.visible and toTile.army <= 1 and toTile.delta.armyDelta < 0:
                possibleMovedTarget = None
                candidateMovedTargets = []
                for adjacent in toTile.movable:
                    if adjacent.isMountain or adjacent.player != army.player or not adjacent.visible:
                        continue
                    candidateMovedTargets.append(adjacent)
                    if possibleMovedTarget is not None:
                        possibleMovedTarget = None
                        break
                    possibleMovedTarget = adjacent
                logbook.info(
                    f"  Priority-loss chase candidates for {potentialMergeOrKilled} from {toTile}: "
                    f"{[adjacent.toString() for adjacent in candidateMovedTargets]}")
                if possibleMovedTarget is None and len(candidateMovedTargets) > 0:
                    targetGeneral = self.map.generals[potentialMergeOrKilled.player]
                    if targetGeneral is not None:
                        bestDist = None
                        for adjacent in candidateMovedTargets:
                            dist = abs(adjacent.x - targetGeneral.x) + abs(adjacent.y - targetGeneral.y)
                            if bestDist is None or dist < bestDist:
                                bestDist = dist
                                possibleMovedTarget = adjacent
                            elif dist == bestDist:
                                possibleMovedTarget = None
                if possibleMovedTarget is not None:
                    logbook.info(f"  Army {potentialMergeOrKilled} was chased off priority-lost tile {toTile} to {possibleMovedTarget}")
                    self.army_moved(potentialMergeOrKilled, possibleMovedTarget, trackingArmies, allowVisiblePlayerMismatch=True)
                elif toTile.delta.toTile is None:
                    self.collide_armies(army, potentialMergeOrKilled, toTile, trackingArmies)
            elif toTile.delta.toTile is None:
                self.collide_armies(army, potentialMergeOrKilled, toTile, trackingArmies)

        army.update_tile(toTile)

        if army.value < -1 or (army.player != army.tile.player and army.tile.visible and not allowVisiblePlayerMismatch):
            logbook.info(f"    Army {str(army)} scrapped for being negative or run into larger tile")
            self.scrap_army(army, scrapEntangled=False)
        if army.tile.visible and len(army.entangledArmies) > 0:
            self.resolve_entangled_armies(army)

        if not oldTile.visible and not dontUpdateOldFogArmyTile:
            oldTile.army = 1
            oldTile.player = army.player
            if self.map.is_army_bonus_turn:
                oldTile.army += 1
            if oldTile.isCity or oldTile.isGeneral and self.map.is_city_bonus_turn:
                oldTile.army += 1

        # if not toTile.visible:
        #     toTile.player = army.player

        if army.scrapped:
            army.expectedPaths = []
        else:
            # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_collide_entangled_and_de_entangle_multiple_armies_correctly depends on a visible moved army being present in self.armies before later same-turn fog emergence resolution. Otherwise an entangled sibling can be moved onto the same visible tile without colliding with the already-emerged army.
            self.armies[toTile] = army
            # Ok then we need to recalculate the expected path.
            # TODO detect if enemy army is likely trying to defend
            if self.log_debug:
                logbook.info(
                    f'EXPECTED_PATH_DEBUG_CALL context=army_moved turn={self.map.turn} army={army} '
                    f'tile={army.tile} oldTile={oldTile} toTile={toTile} value={army.value} tileArmy={army.tile.army} '
                    f'visible={army.tile.visible} discovered={army.tile.discovered}')
            army.expectedPaths = ArmyTracker.get_army_expected_path(self.map, army, self.general, self.player_targets, log_debug=self.log_debug)
            # logbook.info(f'set army {str(army)} expected paths to {str(army.expectedPaths)}')

        if army.last_seen_turn > self.map.turn - 6:
            army.last_moved_turn = self.map.turn - 1
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_TRACE_SET_LAST_MOVED turn={self.map.turn} context=army_moved army={army} '
                    f'tile={army.tile} lastSeen={army.last_seen_turn} newLastMoved={army.last_moved_turn} '
                    f'expectedPaths={[str(path) for path in army.expectedPaths]}')

        for listener in self.notify_army_moved:
            listener(army)
        if self.log_debug:
            logbook.info(
                f'ARMY_MOVED_COMPLETE turn={self.map.turn} army={army} oldTile={oldTile} toTile={toTile} '
                f'oldTileArmyAfter={oldTile.army} toTileArmyAfter={toTile.army} valueAfter={army.value} '
                f'scrapped={army.scrapped} expectedPaths={[str(path) for path in army.expectedPaths]}')

    def scrap_army(self, army: Army, scrapEntangled: bool = False):
        if self.log_debug:
            logbook.info(
                f'ARMY_SCRAP turn={self.map.turn} army={army} scrapEntangled={scrapEntangled} '
                f'tile={army.tile} tileArmy={army.tile.army} value={army.value} '
                f'entangledValue={army.entangledValue} entangled={[str(entangled) for entangled in army.entangledArmies]}')
        self.restore_fog_tile_reverts(army)
        army.scrapped = True
        if scrapEntangled:
            for entangledArmy in army.entangledArmies:
                self.restore_fog_tile_reverts(entangledArmy)
                entangledArmy.scrapped = True
            self.resolve_entangled_armies(army)
        else:
            for entangledArmy in army.entangledArmies:
                try:
                    entangledArmy.entangledArmies.remove(army)
                except:
                    pass

    def restore_fog_tile_reverts(self, army: Army):
        for revert in army.fogTileReverts.values():
            logbook.info(
                f'FOG_TILE_REVERT_APPLY turn={self.map.turn} army={army} tile={revert.tile} '
                f'currentArmy={revert.tile.army} currentPlayer={revert.tile.player} currentTempFog={revert.tile.isTempFogPrediction} '
                f'revertArmy={revert.army} revertPlayer={revert.player} revertTempFog={revert.isTempFogPrediction}')
            # NEVER modify visible tile army values
            if not revert.tile.visible:
                revert.tile.army = revert.army
                revert.tile.player = revert.player
                revert.tile.isTempFogPrediction = revert.isTempFogPrediction
        army.fogTileReverts = {}

    def resolve_entangled_armies(self, army):
        if len(army.entangledArmies) > 0:
            logbook.info(f"{str(army)} resolving {len(army.entangledArmies)} entangled armies")
            resolvedByTile: typing.Set[Tile] = set()
            for entangledArmy in army.entangledArmies:
                logbook.info(f"    {entangledArmy.toString()} entangled, entangledValue {entangledArmy.entangledValue}")
                if entangledArmy.tile in self.armies and self.armies[entangledArmy.tile] == entangledArmy:
                    del self.armies[entangledArmy.tile]
                entangledArmy.scrapped = True
                if entangledArmy.entangledValue is None:
                    entangledArmy.entangledArmies = []
                    continue
                if entangledArmy.tile in resolvedByTile:
                    entangledArmy.entangledArmies = []
                    continue
                resolvedByTile.add(entangledArmy.tile)
                # NEVER modify visible tile army values
                if not entangledArmy.tile.visible and entangledArmy.tile.army > 0:
                    newArmy = max(entangledArmy.tile.army - entangledArmy.entangledValue, 1)
                    logbook.info(
                        f"    updating entangled army tile {entangledArmy.toString()} from army {entangledArmy.tile.army} to {newArmy}")
                    entangledArmy.tile.army = newArmy
                    if not entangledArmy.tile.discovered and entangledArmy.tile.player >= 0:
                        self.reset_temp_tile_marked(entangledArmy.tile)
                    # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_collide_entangled_and_de_entangle_multiple_armies_correctly covers an entangled army emerging while a smaller real residual remains in fog. Resolving the entanglement must leave a distinct tracker for that residual instead of only reducing the fog tile number and losing the army.
                    if newArmy > 1:
                        residualArmy = Army(entangledArmy.tile)
                        residualArmy.value = newArmy - 1
                        residualArmy.last_seen_turn = entangledArmy.last_seen_turn
                        residualArmy.last_moved_turn = self.map.turn - 1
                        if self.log_debug:
                            logbook.info(
                                f'FOG_PATH_TRACE_SET_LAST_MOVED turn={self.map.turn} context=residual_entangled '
                                f'army={residualArmy} tile={residualArmy.tile} value={residualArmy.value} '
                                f'lastSeen={residualArmy.last_seen_turn} newLastMoved={residualArmy.last_moved_turn}')
                        if self.log_debug:
                            logbook.info(
                                f'EXPECTED_PATH_DEBUG_CALL context=residual_entangled turn={self.map.turn} army={residualArmy} '
                                f'tile={residualArmy.tile} value={residualArmy.value} tileArmy={residualArmy.tile.army} '
                                f'visible={residualArmy.tile.visible} discovered={residualArmy.tile.discovered}')
                        residualArmy.expectedPaths = ArmyTracker.get_army_expected_path(self.map, residualArmy, self.general, self.player_targets, log_debug=self.log_debug)
                        self.armies[entangledArmy.tile] = residualArmy

                entangledArmy.entangledArmies = []
            army.entangledArmies = []

    def army_could_capture(self, army, fogTargetTile):
        if army.player != fogTargetTile.player:
            return army.value > fogTargetTile.army
        return True

    def move_army_into_fog(self, army: Army, fogTargetTile: Tile):
        self.armies.pop(army.tile, None)

        # if fogTargetTile in self.armies:
        #     army.scrapped = True
        #     return
        try:
            existingTargetFoggedArmy = self.armies[fogTargetTile]
        except KeyError:
            existingTargetFoggedArmy = None
        if existingTargetFoggedArmy is not None:
            if army in existingTargetFoggedArmy.entangledArmies:
                army.scrapped = True
                return

        movingPlayer = self.map.players[army.player]

        if not fogTargetTile.visible:
            army.record_fog_tile_revert(fogTargetTile)
            if self.map.is_player_on_team_with(fogTargetTile.player, army.player):
                fogTargetTile.army += army.value
                if not fogTargetTile.isGeneral:
                    oldPlayer = self.map.players[fogTargetTile.player]
                    if fogTargetTile in oldPlayer.tiles:
                        oldPlayer.tiles.remove(fogTargetTile)
                    if not fogTargetTile.discovered and fogTargetTile.player != army.player:
                        fogTargetTile.isTempFogPrediction = True
                    fogTargetTile.player = army.player
                    movingPlayer.tiles.append(fogTargetTile)
            else:
                fogTargetTile.army -= army.value
                if fogTargetTile.army < 0:
                    fogTargetTile.army = 0 - fogTargetTile.army
                    oldPlayer = self.map.players[fogTargetTile.player]
                    if fogTargetTile in oldPlayer.tiles:
                        oldPlayer.tiles.remove(fogTargetTile)
                    movingPlayer.tiles.append(fogTargetTile)
                    # if not fogTargetTile.discovered and len(army.entangledArmies) == 0:
                    fogTargetTile.player = army.player
        logbook.info(f"      fogTargetTile {fogTargetTile.toString()} updated army to {fogTargetTile.army}")
        # breaks stuff real bad. Don't really want to do this anyway.
        # Rather track the army through fog with no consideration of owning the tiles it crosses
        # fogTargetTile.player = army.player
        army.update_tile(fogTargetTile)
        army.value = fogTargetTile.army - 1
        self.armies[fogTargetTile] = army
        for listener in self.notify_army_moved:
            listener(army)

    def get_nearby_armies(self, army, armyMap=None):
        if armyMap is None:
            armyMap = self.armies
        # super fastMode depth 2 bfs effectively
        nearbyArmies = []
        for tile in army.tile.movable:
            if tile in armyMap:
                nearbyArmies.append(armyMap[tile])
            for nextTile in tile.movable:
                if nextTile != army.tile and nextTile in armyMap:
                    nearbyArmies.append(armyMap[nextTile])
        for nearbyArmy in nearbyArmies:
            logbook.info(f"Army {str(army)} had nearbyArmy {str(nearbyArmy)}")
        return nearbyArmies

    def find_new_armies(self):
        logbook.info("Finding new armies:")
        playerLargest = [None for x in range(len(self.map.players))]

        if self.map.is_army_bonus_turn:
            self.update_track_threshold()

        # don't do largest tile for now?
        # for tile in self.map.pathableTiles:
        #    if tile.player != -1 and (playerLargest[tile.player] == None or tile.army > playerLargest[tile.player].army):
        #        playerLargest[tile.player] = tile
        for player in self.map.players:
            for tile in player.tiles:
                if tile in self.fog_back_push_touched_tiles_this_turn and tile not in self.armies:
                    continue

                if tile not in self.armies and not tile.visible and (tile.isCity or tile.isGeneral):
                    continue

                notOurMove = (self.lastMove is None or (tile != self.lastMove.source and tile != self.lastMove.dest))

                tileNewlyMovedByEnemy = (
                    tile not in self.armies
                    and not tile.delta.gainedSight
                    and tile.player != self.map.player_index
                    and abs(tile.delta.armyDelta) > 2
                    and tile.army > 2
                    and notOurMove
                )

                isTileValidForArmy = (
                    playerLargest[tile.player] == tile
                    or tile.army > self.track_threshold
                    or tileNewlyMovedByEnemy
                )

                if isTileValidForArmy:
                    try:
                        tileArmy = self.armies[tile]
                    except KeyError:
                        tileArmy = None

                    if tileArmy is None or tileArmy.scrapped:
                        logbook.info(
                            f"{str(tile)} Discovered as Army! (tile.army {tile.army}, tile.delta {tile.delta.armyDelta}) - no fog emergence")

                        army = self.get_or_create_army_at(tile, skip_expected_path=not tile.visible and tile.isCity or tile.isGeneral)
                        if not army.visible:
                            army.value = army.tile.army - 1
                        else:
                            army.last_seen_turn = self.map.turn

                # if tile WAS bordered by fog find the closest fog army and remove it (not tile.visible or tile.delta.gainedSight)

    def new_army_emerged(self, emergedTile: Tile, armyEmergenceValue: float, emergingPlayer: int = -1, distance: int | None = None):
        """
        when an army can't be resolved to coming from the fog from a known source, this method gets called to track its emergence location.
        @param emergedTile:
        @param armyEmergenceValue:
        @return:
        """

        if emergedTile.player == self.map.player_index or emergedTile.player in self.map.teammates:
            return

        if emergingPlayer == -1:
            emergingPlayer = emergedTile.player
            if emergingPlayer == -1:
                raise AssertionError('neutral army emergence...?')

        self.unrecaptured_emergence_events[emergingPlayer].add(emergedTile)

        # largest = [0]
        # largestTile = [None]

        if not self.has_perfect_information_of_player_cities_and_general(emergingPlayer):
            if distance is None:
                distance = max(10, self.min_spawn_distance) + 1
                if self.map.turn < 300:
                    distance = max(distance, int(self.map.turn / 4))
                else:
                    distance = 75

            armyEmergenceValue = 2 + (armyEmergenceValue ** 0.75)

            if armyEmergenceValue > 10:
                armyEmergenceValue = 10

            armyEmergenceScaledToTurns = 5 * armyEmergenceValue / (5 + self.map.turn // 25)

            logbook.info(f"running new_army_emerged for tile {str(emergedTile)} with emValueScaled {armyEmergenceScaledToTurns:.2f}, distance {distance}")

            # bannedTiles, connectedTiles, pathToUnelim = self.get_fog_connected_based_on_emergences(emergingPlayer, predictedGeneralLocation=None, additionalRequiredTiles=[emergedTile])

            distancePlateau = max(1, min(distance - 1, 5))

            def foreachFunc(tile, dist):
                if not tile.discovered:
                    distCapped = max(distancePlateau, dist)
                    emergeValue = distancePlateau * armyEmergenceScaledToTurns // distCapped
                    # if self.valid_general_positions_by_player[emergingPlayer][tile]:
                    # TODO this is doing the weird +1 emergence every turn thing
                    self.emergenceLocationMap[emergedTile.player][tile] += max(1, emergeValue)
                    # if largest[0] < self.emergenceLocationMap[emergedTile.player][tile]]:
                    #     largestTile[0] = tile
                    #     largest[0] = self.emergenceLocationMap[emergedTile.player][tile]]
                visibleOrDiscNeut = (tile.was_visible_last_turn() or (tile.discoveredAsNeutral and self.map.turn <= 100))
                return (tile.isObstacle or visibleOrDiscNeut) and tile != emergedTile

            breadth_first_foreach_dist(self.map, [emergedTile], distance, foreachFunc, bypassDefaultSkip=True)

            if len(self.uneliminated_emergence_events[emergedTile.player]) < 8:
                logbook.info(f'new_army_emerged calling limit_gen_position_from_emergence because less than 8 so far')
                self.limit_gen_position_from_emergence(self.map.players[emergedTile.player], emergedTile, emergenceAmount=armyEmergenceValue)

        for handler in self.notify_unresolved_army_emerged:
            handler(emergedTile)

    def tile_discovered_neutral(self, neutralTile: Tile):
        logbook.info(f"running tile_discovered_neutral for tile {neutralTile.toString()}")

        # then reset bad predictions that went into the fog from this tile
        self.drop_incorrect_player_fog_around(neutralTile, neutralTile.delta.oldOwner)

    def is_friendly_team(self, p1: int, p2: int) -> bool:
        if p1 == p2:
            return True
        if p1 < 0 or p2 < 0:
            return False
        if self.map.teams is not None and self.map.teams[p1] == self.map.teams[p2]:
            return True
        return False

    def is_enemy_team(self, p1: int, p2: int) -> bool:
        if p1 == p2:
            return False
        if p1 < 0 or p2 < 0:
            return False
        if self.map.teams is not None and self.map.teams[p1] != self.map.teams[p2]:
            return True
        return False

    def notify_seen_player_tile(self, tile: Tile):
        self._flipped_tiles.add(tile)

    def notify_concrete_emergence(self, maxDist: int, emergingTile: Tile, confidentFromGeneral: bool):
        player = emergingTile.player
        self.unrecaptured_emergence_events[player].add(emergingTile)
        self._limit_general_position_to_within_tile_and_distance(player, emergingTile, maxDist, alsoIncreaseEmergence=False, skipIfLongerThanExisting=True, overrideCityPerfectInfo=confidentFromGeneral)
        if confidentFromGeneral:
            for tile in self.map.get_all_tiles():
                self.emergenceLocationMap[player][tile] /= 5.0

        incTiles = []

        def foreachFunc(curTile: Tile, dist: int):
            if dist == 0:
                return
            incTiles.append((curTile, dist))

            return curTile.visible and curTile != emergingTile

        breadth_first_foreach_dist(self.map, [emergingTile], maxDepth=maxDist, foreachFunc=foreachFunc)

        if len(incTiles) == 0:
            incAmount = 20
        else:
            incAmount = 500 / len(incTiles)

        for incTile, dist in incTiles:
            self.emergenceLocationMap[player][incTile] += incAmount

    def find_fog_source(self, armyPlayer: int, tile: Tile, delta: int | None = None, depthLimit: int | None = None) -> Path | None:
        """
        Looks for a fog source to this tile that produces the provided (positive) delta, or if none provided, the
        (positive) delta from the tile this turn.
        @param tile:
        @param delta:
        @return:
        """
        if delta is None:
            delta = abs(tile.delta.armyDelta)

        armyPlayerObj = self.map.players[armyPlayer]
        standingArmy = armyPlayerObj.standingArmy

        if depthLimit is None:
            depthLimit = self.min_spawn_distance

            if self.map.turn > 75:
                depthLimit += 15

        missingCities = max(0, armyPlayerObj.cityCount - 1 - len(where(armyPlayerObj.cities, lambda c: c.discovered)))

        allowVisionlessObstaclesAndCities = False
        candidates = where(tile.movable,
                     lambda adj: not adj.isNotPathable and adj.was_not_visible_last_turn())

        wasDiscoveredEnemyTile = tile.delta.oldOwner == -1 and tile.delta.gainedSight

        prioritizeCityWallSource = self.detect_army_likely_breached_wall(armyPlayer, tile, delta)

        emergenceMap = self.emergenceLocationMap[armyPlayer]
        tilesEverOwned = self.tiles_ever_owned_by_player[armyPlayer]
        validGenPositions = self.valid_general_positions_by_player[armyPlayer]

        if (
            len(candidates) == 0
            or missingCities > 0  # TODO questionable
        ):
            if missingCities > 0:
                logbook.info(f"        For new army at tile {str(tile)}, checking for undiscovered city emergence")
                allowVisionlessObstaclesAndCities = True
            else:
                logbook.info(f"        For new army at tile {str(tile)} there were no adjacent fogBois and no missing cities, give up...?")
                return None

        def valFunc(
                thisTile: Tile,
                prioObject
        ):
            (distWeighted, dist, negArmy, turnsNegative, citiesConverted, negBonusScore, consecUndisc, meetsCriteria) = prioObject
            if dist == 0:
                return None

            if citiesConverted > missingCities:
                return None

            if not meetsCriteria:
                return None

            val = 0
            if negArmy > 3 * dist + 3:
                val = -10000 - negArmy * 10
            elif negArmy > 0:
                val = -5000 - negArmy * 10
            # elif negArmy > 10:
            #     val = -10000 - negArmy
            else:
                val = negArmy * 10

            if self.is_friendly_team(thisTile.player, armyPlayer) and thisTile.army > 8:
                negMhArmy = negArmy + thisTile.army // 2
                if negMhArmy > 3 * dist + 3:
                    moveHalfVal = -10000 - negMhArmy * 10
                elif negMhArmy > 0:
                    moveHalfVal = -5000 - negMhArmy * 10
                else:
                    moveHalfVal = negMhArmy * 10
                if moveHalfVal > val:
                    logbook.info(
                        f"using moveHalfVal {moveHalfVal:.1f} over val {val:.1f} for tile {str(thisTile)} turn {self.map.turn}")
                    val = moveHalfVal
            elif not thisTile.discovered:
                undiscValOffset = 3 - 3 / max(1.0, self.emergenceLocationMap[armyPlayer][thisTile])
                logbook.debug(f'new val @ {str(thisTile)} val {val:.3f}, negArmy {negArmy}, undiscValOffset {undiscValOffset:.3f}, negBonusScore {negBonusScore}')
                val += undiscValOffset

            # closest path value to the actual army value. Fake tuple for logging.
            # 2*abs for making it 3x improvement on the way to the right path, and 1x unemprovement for larger armies than the found tile
            # negative weighting on dist to try to optimize for shorter paths instead of exact
            bonus = max(0, 0 - negBonusScore)
            bonusPts = bonus ** 0.25 - 1
            combined = val - citiesConverted * 10 - dist + bonusPts
            logbook.debug(f'       val {combined:.2f} @ {str(thisTile)} val {val:.3f}, negBonusScore {negBonusScore}, bonusPts {bonusPts:.3f}, negArmy {negArmy}, dist {dist}')
            return combined, 0 - citiesConverted

        # if (0-negArmy) - dist*2 < tile.army:
        #    return (0-negArmy)
        # return -1

        def prioFunc(
                nextTile: Tile,
                prioObject
        ):
            (distWeighted, dist, negArmy, turnsNeg, citiesConverted, negBonusScore, consecutiveUndiscovered, meetsCriteria) = prioObject
            try:
                theArmy = self.armies[nextTile]
            except KeyError:
                theArmy = None
            if theArmy is not None:
                consecutiveUndiscovered = 0
                if self.is_friendly_team(theArmy.player, armyPlayer):
                    negArmy -= theArmy.value
                else:
                    negArmy += theArmy.value
            elif nextTile.isUndiscoveredObstacle or (not nextTile.visible and nextTile.isCostlyNeutralCity):
                citiesConverted += 1
                if citiesConverted > missingCities:
                    return None

                undiscVal = self.emergenceLocationMap[armyPlayer][nextTile]

                if nextTile.discovered:
                    negBonusScore -= 5

                if prioritizeCityWallSource:
                    if nextTile.isUndiscoveredObstacle:
                        negBonusScore -= undiscVal
                        negBonusScore += self.map.get_distance_between(self.general, nextTile) * 5
                        for t in nextTile.movable:
                            if not self.map.is_tile_on_team_with(t, armyPlayer) and t.visible and not t.isObstacle:
                                negBonusScore += 1
                    else:
                        negBonusScore -= undiscVal
                    dist += 1  # try to deprioritize these with high distance...?
                else:
                    if nextTile.isUndiscoveredObstacle:
                        negBonusScore += 150 / (undiscVal + 1)
                    else:
                        negBonusScore += 150 / (undiscVal + 1)

                    dist += 5  # try to deprioritize these with high distance...?

                consecutiveUndiscovered += 1
            else:
                if not nextTile.discovered:
                    consecutiveUndiscovered += 1
                    undiscVal = emergenceMap[nextTile]
                    negBonusScore -= undiscVal
                    # if nextTile.player == -1:
                    #     if undiscVal > 0:
                    #         emergenceLocalityBonusArmy = max(1, round(undiscVal ** 0.25 - 1))
                    #         negArmy -= emergenceLocalityBonusArmy
                else:
                    consecutiveUndiscovered = 0
                if self.is_friendly_team(nextTile.player, armyPlayer):
                    negArmy -= nextTile.army - 1
                elif nextTile.discovered:
                    negArmy += nextTile.army + 1

            if not meetsCriteria and not nextTile.was_visible_last_turn():
                meetsCriteria = nextTile in tilesEverOwned or nextTile in validGenPositions or theArmy is not None

            if negArmy <= 0:
                turnsNeg += 1
            dist += 1
            return dist * citiesConverted, dist, negArmy, turnsNeg, citiesConverted, negBonusScore, consecutiveUndiscovered, meetsCriteria

        def fogSkipFunc(
                nextTile: Tile,
                prioObject
        ):
            if prioObject is None:
                return True

            (distWeighted, dist, negArmy, turnsNegative, citiesConverted, negBonusScore, consecutiveUndiscovered, meetsCriteria) = prioObject
            if citiesConverted > missingCities:
                return True

            if nextTile.isGeneral and not nextTile.player == armyPlayer:
                return True

            # logbook.info("nextTile {}: negArmy {}".format(nextTile.toString(), negArmy))
            return (
                    False
                    or (nextTile.visible and not nextTile.delta.gainedSight and not (wasDiscoveredEnemyTile and self.is_friendly_team(nextTile.player, tile.player)))
                    or turnsNegative > 7
                    or consecutiveUndiscovered > 20
                    or dist > 30
            )

        inputTiles = {}
        logbook.info(f"Looking for fog army path of value {delta} to tile {str(tile)}, prioritizeCityWallSource {prioritizeCityWallSource}")
        # we want the path to get army up to 0, so start it at the negative delta (positive)
        inputTiles[tile] = ((0, 0, delta, 0, 0, 0, 0, False), 0)

        fogSourcePath = breadth_first_dynamic_max(
            self.map,
            inputTiles,
            valFunc,
            maxTurns=depthLimit,
            maxDepth=depthLimit,
            maxTime=1.0,
            noNeutralCities=not allowVisionlessObstaclesAndCities,
            noNeutralUndiscoveredObstacles=not allowVisionlessObstaclesAndCities,
            priorityFunc=prioFunc,
            skipFunc=fogSkipFunc,
            searchingPlayer=armyPlayer,
            logResultValues=True,
            noLog=False)
        if fogSourcePath is not None:
            logbook.info(
                f"        For new army at tile {str(tile)} we found fog source path???? {str(fogSourcePath)}")
        else:
            logbook.info(f"        NO fog source path for new army at {str(tile)} depth {depthLimit} for delta {delta}")
        return fogSourcePath

    def find_next_fog_city_candidate_near_tile(
            self,
            cityPlayer: int,
            tile: Tile,
            cutoffDist: int = 12,
            distanceWeightReduction: int = 3,
            wallBreakWeight: float = 2.0,
            emergenceWeight: float = 1.0,
            doNotConvert: bool = False,
            forceConnected: bool = False
    ) -> Tile | None:
        """
        Looks for a fog city candidate nearby a given tile, and convert it to player owned if so.

        @param cityPlayer:
        @param tile:
        @param cutoffDist:
        @param distanceWeightReduction: the larger this number, the less distance will scale the result (and the more emergenceVal / wall_break_val will scale it).
        @param wallBreakWeight: the larger this number, the more wallbreak value will matter.
        @param doNotConvert: if True, this method will not convert the city to player owned for you.
        @return:
        """

        armyPlayerObj = self.map.players[cityPlayer]
        missingCities = armyPlayerObj.cityCount - 1 - len(armyPlayerObj.cities)
        if missingCities <= 0:
            return

        gen = self.map.players[self.map.player_index].general
        genSpan = self.map.get_distance_between(gen, tile)
        genMapRaw = self._boardAnalysis.intergeneral_analysis.aMap.raw

        alliedPlayers = self.map.get_teammates(cityPlayer)

        def valFunc(
                thisTile: Tile,
                prioObject
        ):
            dist, _, validLocation = prioObject
            if not validLocation:
                return None

            if forceConnected:
                anyConn = False
                for t in thisTile.movable:
                    if t.player in alliedPlayers:
                        anyConn = True
                    break
                if not anyConn:
                    return None

            if thisTile.visible or thisTile == tile or dist == 0:
                return None

            isPotentialFogCity = thisTile.isCity and thisTile.isNeutral
            isPotentialFogCity = isPotentialFogCity or thisTile.isUndiscoveredObstacle
            if not isPotentialFogCity:
                return None

            wallBreakBonus = self._boardAnalysis.enemy_wall_breach_scores.raw[thisTile.tile_index]
            if not wallBreakBonus or wallBreakBonus < 3:
                wallBreakBonus = 0
            else:
                wallBreakBonus = wallBreakBonus * wallBreakWeight

            emergenceVal = (1 + self.emergenceLocationMap[cityPlayer].raw[thisTile.tile_index] * emergenceWeight + wallBreakBonus) / (dist + distanceWeightReduction)
            val = emergenceVal
            return val, True  # has to be tuple or logging blows up i guess

        def prioFunc(
                nextTile: Tile,
                prioObject
        ):
            (dist, _, validLocation) = prioObject

            dist += 1
            if nextTile.isUndiscoveredObstacle:
                # try to path around obstacles over going through them..? Takes 2 extra moves to
                # go around an obstacle to the other side so at minimum make it cost that
                # much extra so going around is otherwise equal to through
                dist += 2
                for t in nextTile.movable:
                    if t.isObstacle:
                        continue

                    if genMapRaw[nextTile.tile_index] + 4 < genMapRaw[t.tile_index] < 150:
                        dist -= 2

            if not validLocation:
                dist += 0.5

            if dist > 1:
                validLocation = True

            return dist, 0, validLocation

        def fogSkipFunc(
                nextTile: Tile,
                prioObject
        ):
            if prioObject is None:
                return True

            (dist, _, validLocation) = prioObject

            # logbook.info("nextTile {}: negArmy {}".format(nextTile.toString(), negArmy))
            return (
                    (nextTile.visible and not nextTile.delta.gainedSight)
                    or dist > cutoffDist
            )

        inputTiles = {}
        # we want the path to get army up to 0, so start it at the negative delta (positive)
        inputTiles[tile] = ((0, 0, True), 0)
        for player in self.map.players:
            for city in player.cities:
                if city.discovered:
                    continue
                inputTiles[city] = ((-2, 0, False), 0)

        fogSourcePath = breadth_first_dynamic_max(
            self.map,
            inputTiles,
            valFunc,
            maxTime=100000.0,
            noNeutralCities=False,
            noNeutralUndiscoveredObstacles=False,
            priorityFunc=prioFunc,
            skipFunc=fogSkipFunc,
            searchingPlayer=cityPlayer,
            logResultValues=True,
            noLog=True)
        if fogSourcePath is not None:
            newFogCity = fogSourcePath.tail.tile
            if not doNotConvert:
                self.convert_fog_city_to_player_owned(newFogCity, cityPlayer)
            logbook.info(
                f"        Found new fog city!???? {str(newFogCity)}")
            return newFogCity

        else:
            logbook.info(f"        NO alternate fog city found for {str(tile)} depth ")

        return None

    def remove_nearest_fog_city(self, cityPlayerIndex: int, tile: Tile, distanceIfNotExcessCities: int):
        """
        Looks for a fog city near this tile and remove it if found.
        If the player has too many cities on the map vs their actual city count, removes with unlimited distance.

        @param cityPlayerIndex:
        @param tile:
        @param distanceIfNotExcessCities: The cutoff removal distance to use if the map doesn't have too many player cities on it already.

        @return:
        """

        cityPlayer = self.map.players[cityPlayerIndex]
        extraCities = len(cityPlayer.cities) + 1 - cityPlayer.cityCount

        logbook.info(f'Looking for fog city near {str(tile)} for player {cityPlayerIndex} with extraCities {extraCities} from discovered city.')

        skipTiles = set()
        for t in self.map.get_all_tiles():
            if t.discoveredAsNeutral and t.delta.discovered:
                skipTiles.add(t)

        badCityPath = SearchUtils.breadth_first_find_queue(
            self.map,
            [tile],
            # t in self.fog_cities_by_player[cityPlayerIndex]
            goalFunc=lambda t, army, dist: t.isCity and not t.discovered and t.player == cityPlayerIndex,
            maxDepth=200,
            skipTiles=skipTiles,
            bypassDefaultSkipLogic=True,
            noLog=True)

        if badCityPath is not None:
            badCity = badCityPath.tail.tile
            logbook.info(f'Found removable fog city {str(badCity)} via path {str(badCityPath)}')
            if extraCities > 0 or badCityPath.length <= distanceIfNotExcessCities:
                logbook.info(f'  Fog city {str(badCity)} removed.')
                self.reset_temp_tile_marked(badCity)
                extraCities -= 1
            else:
                logbook.info(f'  Fog city {str(badCity)} NOT REMOVED due to not meeting length / excess city requirements.')
        else:
            logbook.info(f'  No fog city path found to remove.')

    def resolve_fog_emergence(
            self,
            player: int,
            sourceFogArmyPath: Path,
            fogTile: Tile,
    ) -> Army | None:
        existingArmy = None
        armiesFromFog = []
        existingArmy = self.armies.pop(fogTile, None)
        if existingArmy is not None and existingArmy.player == player:
            armiesFromFog.append(existingArmy)

        node = sourceFogArmyPath.start.next
        while node is not None:
            logbook.info(f"resolve_fog_emergence tile {str(node.tile)}")
            fogArmy = self.armies.pop(node.tile, None)
            if fogArmy is not None and self.is_friendly_team(fogArmy.player, player):
                logbook.info(f"  ^ was army {str(node.tile)}")
                armiesFromFog.append(fogArmy)
            if not node.tile.visible:
                if not node.tile.discovered and node.tile.player != player:
                    node.tile.isTempFogPrediction = True
                    self.map.players[player].tiles.append(node.tile)
                # if node.tile.army > 0:
                node.tile.army = 1
                node.tile.player = player
                if self.map.is_army_bonus_turn:
                    node.tile.army += 1
                if self.map.is_city_bonus_turn and (node.tile.isCity or node.tile.isGeneral):
                    node.tile.army += 1
            node = node.next

        maxArmy = None
        candidateArmies = SearchUtils.where(armiesFromFog, lambda army: army.entangledValue is not None)
        if len(candidateArmies) == 0:
            candidateArmies = armiesFromFog
        for army in candidateArmies:
            if maxArmy is None or maxArmy.value < army.value:
                maxArmy = army

        if maxArmy is not None:
            # update path on army
            node = sourceFogArmyPath.get_reversed().start
            while node is not None and node.tile != maxArmy.tile:
                node = node.next

            if node is not None:
                node = node.next
                while node is not None:
                    maxArmy.update_tile(node.tile)
                    node = node.next

            # scrap other armies from the fog
            for army in armiesFromFog:
                if army != maxArmy:
                    logbook.info(f"  ^ scrapping {str(army)} as it was not largest on emergence path")
                    self.scrap_army(army, scrapEntangled=True)

            self.resolve_entangled_armies(maxArmy)
            logbook.info(f'set fog source for {str(fogTile)} to {str(maxArmy)}')
            if maxArmy.scrapped:
                # sometimes we can inadvertently scrap this army during this process, but this is the one we definitely want to keep.
                maxArmy.scrapped = False
            maxArmy.update_tile(fogTile)
            maxArmy.update()
            maxArmy.last_moved_turn = self.map.turn - 1
            # maxArmy.player = fogTile.player
            # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_duplicate_army_out_of_fog covers the case where resolve_fog_emergence returns an army but it's not added to self.armies[fogTile]. This causes find_new_armies to create a duplicate army. Uncommenting this line fixes the duplication.
            self.armies[fogTile] = maxArmy
            maxArmy.path = sourceFogArmyPath
            maxArmy.expectedPaths = []
        else:
            # then this is a brand new army because no armies were on the fogPath, but we set the source path to 1's still
            maxArmy = Army(fogTile)
            # armies told to load from fog ignore the tiles army. In this case, we want to explicitly respect it.
            if not fogTile.visible:
                maxArmy.value = fogTile.army - 1
            else:
                maxArmy.last_seen_turn = self.map.turn

            # self.armies[fogTile] = maxArmy
            maxArmy.path = sourceFogArmyPath

        return maxArmy

    def merge_armies(self, largerArmy: Army, smallerArmy: Army, finalTile: Tile, armyDict: typing.Dict[Tile, Army] | None = None):
        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(f'FOG DEBUG: Merging armies - larger: {str(largerArmy)} (value {largerArmy.value}), smaller: {str(smallerArmy)} (value {smallerArmy.value}) at {finalTile}')
        if self.log_debug:
            logbook.info(
                f'ARMY_MERGE_START turn={self.map.turn} larger={largerArmy} smaller={smallerArmy} finalTile={finalTile} '
                f'largerValue={largerArmy.value} smallerValue={smallerArmy.value} finalTileArmyBefore={finalTile.army} '
                f'largerEntangledValue={largerArmy.entangledValue} smallerEntangledValue={smallerArmy.entangledValue} '
                f'largerEntangled={[str(entangled) for entangled in largerArmy.entangledArmies]} '
                f'smallerEntangled={[str(entangled) for entangled in smallerArmy.entangledArmies]}')
        self.armies.pop(largerArmy.tile, None)
        self.armies.pop(smallerArmy.tile, None)
        largerArmy.absorb_fog_tile_reverts(smallerArmy)
        smallerArmy.fogTileReverts = {}
        largerArmy.entangledArmies.extend(smallerArmy.entangledArmies)
        self.scrap_army(smallerArmy, scrapEntangled=False)
        for entangled in smallerArmy.entangledArmies:
            entangled.entangledArmies.append(largerArmy)
        if largerArmy.entangledValue is None:
            largerArmy.entangledValue = largerArmy.value
        if smallerArmy.entangledValue is None:
            smallerArmy.entangledValue = smallerArmy.value
        largerArmy.entangledValue += smallerArmy.entangledValue

        if largerArmy.tile != finalTile:
            largerArmy.update_tile(finalTile)

        if armyDict is None:
            armyDict = self.armies

        armyDict[finalTile] = largerArmy
        largerArmy.update()
        if self.log_debug:
            logbook.info(
                f'ARMY_MERGE_COMPLETE turn={self.map.turn} army={largerArmy} finalTile={finalTile} '
                f'valueAfter={largerArmy.value} entangledValueAfter={largerArmy.entangledValue} '
                f'finalTileArmyAfter={finalTile.army} entangled={[str(entangled) for entangled in largerArmy.entangledArmies]}')
        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(f'FOG DEBUG: Merge completed - final army: {str(largerArmy)} with value {largerArmy.value} at {finalTile}')

    def collide_armies(self, movingArmy: Army, targetArmy: Army, finalTile: Tile, armyDict: typing.Dict[Tile, Army] | None = None):
        if self.log_debug:
            logbook.info(
                f'ARMY_COLLIDE_START turn={self.map.turn} moving={movingArmy} target={targetArmy} finalTile={finalTile} '
                f'movingValue={movingArmy.value} targetValue={targetArmy.value} finalTileArmyBefore={finalTile.army} '
                f'movingPlayer={movingArmy.player} targetPlayer={targetArmy.player} finalTilePlayer={finalTile.player}')
        self.armies.pop(movingArmy.tile, None)
        self.armies.pop(targetArmy.tile, None)
        movingArmy.absorb_fog_tile_reverts(targetArmy)
        targetArmy.fogTileReverts = {}

        if not self.map.is_player_on_team_with(movingArmy.player, targetArmy.player):
            # determine expected army value
            if (targetArmy.value < movingArmy.value and not finalTile.visible) or (finalTile.player == movingArmy.player and finalTile.visible):
                targetArmy.value = 0
                self.scrap_army(targetArmy, scrapEntangled=True)
            else:
                targetArmy.value -= movingArmy.tile.delta.armyDelta
        elif finalTile.isGeneral and finalTile.player != movingArmy.player:
            self.scrap_army(movingArmy, scrapEntangled=True)
        else:
            self.scrap_army(targetArmy, scrapEntangled=True)

        if movingArmy.tile != finalTile:
            movingArmy.update_tile(finalTile)

        if armyDict is None:
            armyDict = self.armies

        armyDict[finalTile] = movingArmy
        movingArmy.update()
        if self.log_debug:
            logbook.info(
                f'ARMY_COLLIDE_COMPLETE turn={self.map.turn} moving={movingArmy} target={targetArmy} finalTile={finalTile} '
                f'movingValueAfter={movingArmy.value} targetValueAfter={targetArmy.value} finalTileArmyAfter={finalTile.army} '
                f'movingScrapped={movingArmy.scrapped} targetScrapped={targetArmy.scrapped}')

    def has_perfect_information_of_player_cities_and_general(self, player: int):
        mapPlayer = self.map.players[player]
        if mapPlayer.general is not None and mapPlayer.general.isGeneral and self.has_perfect_information_of_player_cities(player):
            # then we have perfect information about the player, no point in tracking emergence values
            return True

        return False

    def try_track_own_move(self, army: Army, skip: typing.Set[Tile], trackingArmies: typing.Dict[Tile, Army]):
        if self.map.last_player_index_submitted_move is not None:
            # then map determined it did something and wasn't dropped. Execute it.
            src, dest, move_half = self.map.last_player_index_submitted_move
            if src.visible:
                logbook.info(f'executing OUR move {str(self.map.last_player_index_submitted_move)}')

                self.army_moved(army, dest, trackingArmies)

    def try_track_army(
            self,
            army: Army,
            skip: typing.Set[Tile],
            trackingArmies: typing.Dict[Tile, Army]
    ):
        armyTile = army.tile
        if army.scrapped:
            self.armies.pop(armyTile, None)
            return

        if army.tile in skip:
            logbook.info(f"Army {str(army)} was in skip set. Skipping")
            return
        # army may have been removed (due to entangled resolution)
        if armyTile not in self.armies:
            logbook.info(f"Skipped armyTile {armyTile.toString()} because no longer in self.armies?")
            return
        # army = self.armies[armyTile]
        if army.tile != armyTile:
            raise Exception(
                f"bitch, army key {armyTile.toString()} didn't match army tile {str(army)}")

        # if army.tile.was_visible_last_turn() and army.tile.delta.unexplainedDelta == 0:
        #

        armyRealTileDelta = 0 - army.tile.delta.armyDelta
        # armyUnexplainedDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
        # if army.tile.visible and self.unaccounted_tile_diffs
        if armyRealTileDelta == 0 and army.tile.visible and not army.tile.delta.gainedSight:
            logbook.info(f'army didnt move...? {str(army)}')
            army.update()
            return

        # if armyRealTileDelta == 0 and armyTile.visible:
        #     # Army didn't move...?
        #     continue
        logbook.info(
            f"{str(army)} army.value {army.value} actual delta {army.tile.delta.armyDelta}, armyRealTileDelta {armyRealTileDelta}")
        foundLocation = False
        # if army.tile.delta.armyDelta == expectedDelta:
        #    # army did not move and we attacked it?

        if army.visible and army.player == army.tile.player and army.value < army.tile.army - 1:
            self.handle_gathered_to_army(army, skip, trackingArmies)
            return

        lostVision = (army.visible and not army.tile.visible)
        # lostVision breaking stuff?
        # army values are 1 less than the actual tile value, so +1
        if (
                1 == 1
                # and not lostVision
                and army.visible
                and army.tile.visible
                and army.tile.delta.armyDelta == 0
                and army.tile.player == army.player
        ):
            # army hasn't moved
            army.update()
            if not army.scrapped and not army.visible:
                army.value = army.tile.army - 1
            self.check_for_should_scrap_unmoved_army(army)
            return

        # army probably moved. Check adjacents for the army
        for adjacent in army.tile.movable:
            if adjacent.isMountain:
                continue

            foundLocation = self.test_army_adjacent_move(army, adjacent, skip, trackingArmies)

            if foundLocation:
                break

        if not foundLocation:
            if not army.visible and not army.tile.visible:
                # let the fog mover handle it
                return
            # now try fog movements?
            fogBois = []
            fogCount = 0
            for adjacent in army.tile.movable:
                if adjacent.isMountain or adjacent.isNotPathable:
                    continue

                # fogged armies cant move to other fogged tiles when army is uncovered unless that player already owns the other fogged tile
                legalFogMove = (army.visible or adjacent.player == army.player)
                if not adjacent.was_visible_last_turn() and self.army_could_capture(army, adjacent) and legalFogMove:
                    # if (closestFog == None or self.distMap[adjacent.x][adjacent.y] < self.distMap[closestFog.x][closestFog.y]):
                    #    closestFog = adjacent
                    expected = army.value
                    expectCaptured = False
                    if self.map.is_player_on_team_with(adjacent.delta.oldOwner, army.player):
                        expected += adjacent.delta.oldArmy
                        expectCaptured = True
                    else:
                        expected -= adjacent.delta.oldArmy
                        if expected < 0:
                            expectCaptured = True

                    if adjacent.visible and ((not expected * 0.7 < adjacent.army < expected * 1.3) or (expectCaptured and adjacent.player != army.player)):
                        continue

                    fogBois.append(adjacent)
                    fogCount += 1

                expectedAdjDelta = 0
                adjDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
                # expectedAdjDelta = 0
                logbook.info(
                    f"  adjacent delta raw {adjacent.delta.armyDelta} expectedAdjDelta {expectedAdjDelta}")
                logbook.info(
                    f"  armyDeltas: army {str(army)} {armyRealTileDelta} - adj {adjacent.toString()} {adjDelta} expAdj {expectedAdjDelta}")
                # expectedDelta is fine because if we took the expected tile we would get the same delta as army remaining on army tile.
                if ((armyRealTileDelta > 0 or
                     (not army.tile.visible and
                      adjacent.visible and
                      adjacent.delta.armyDelta != expectedAdjDelta)) and
                        adjDelta - armyRealTileDelta == army.tile.delta.expectedDelta):
                    foundLocation = True
                    logbook.info(
                        f"    Army (Based on expected delta?) probably moved from {str(army)} to {adjacent.toString()}")
                    self.unaccounted_tile_diffs.pop(army.tile, None)
                    self.army_moved(army, adjacent, trackingArmies)
                    break

            if not foundLocation and len(fogBois) > 0 and army.player != self.map.player_index and (
                    army.tile.was_visible_last_turn()):  # prevent entangling and moving fogged cities and stuff that we stopped incrementing
                fogArmies = []
                if len(fogBois) == 1:
                    fogTarget = fogBois[0]
                    # if fogTarget.visible and not fogTarget.army > 5:
                    #     self.scrap_army(army)
                    #     return
                    foundLocation = True
                    logbook.info(f"    WHOO! Army {str(army)} moved into fog at {fogBois[0].toString()}!?")
                    self.move_army_into_fog(army, fogTarget)
                    if fogCount == 1:
                        logbook.info("closestFog and fogCount was 1, converting fogTile to be owned by player")
                        fogTarget.player = army.player
                    self.unaccounted_tile_diffs.pop(army.tile, None)
                    self.army_moved(army, fogTarget, trackingArmies, dontUpdateOldFogArmyTile=True)

                else:
                    # validFogDests = []
                    # for fogBoi in fogBois:
                    #
                    foundLocation = True
                    logbook.info(f"    Army {str(army)} IS BEING ENTANGLED! WHOO! EXCITING!")
                    entangledArmies = army.get_split_for_fog(fogBois)
                    for i, fogBoi in enumerate(fogBois):
                        logbook.info(
                            f"    Army {str(army)} entangled moved to {str(fogBoi)}")
                        self.move_army_into_fog(entangledArmies[i], fogBoi)
                        self.unaccounted_tile_diffs.pop(entangledArmies[i].tile, None)
                        self.army_moved(entangledArmies[i], fogBoi, trackingArmies, dontUpdateOldFogArmyTile=True)
                return

            if army.player != army.tile.player and army.tile.was_visible_last_turn():
                logbook.info(f"  Army {str(army)} got eated? Scrapped for not being the right player anymore")
                self.scrap_army(army, scrapEntangled=True)

        army.update()

    def get_or_create_army_at(
            self,
            tile: Tile,
            skip_expected_path: bool = False
    ) -> Army:
        try:
            army = self.armies[tile]
        except KeyError:
            army = None
        if army is not None:
            return army

        logbook.info(f'creating new army at {str(tile)} in get_or_create.')
        army = Army(tile)
        army.last_moved_turn = 0
        if army.tile.delta.fromTile is not None or army.tile.delta.unexplainedDelta != 0:
            army.last_moved_turn = self.map.turn - 1
        if not tile.visible:
            army.last_moved_turn = self.map.turn - 2  # this should only really happen on incrementing fog cities or on initial unit test map load
            army.value = tile.army - 1
        else:
            army.last_seen_turn = self.map.turn

        if not skip_expected_path:
            if self.log_debug:
                nearbyTrackedArmies = []
                for trackedArmy in self.armies.values():
                    nearbyTrackedArmies.append(
                        f'{trackedArmy}:tile={trackedArmy.tile}:value={trackedArmy.value}:tileArmy={trackedArmy.tile.army}:scrapped={trackedArmy.scrapped}')
                logbook.info(
                    f'EXPECTED_PATH_DEBUG_CALL context=get_or_create turn={self.map.turn} army={army} '
                    f'tile={army.tile} value={army.value} tileArmy={army.tile.army} visible={army.tile.visible} '
                    f'discovered={army.tile.discovered} skip_expected_path={skip_expected_path} '
                    f'nearbyTrackedArmies={" | ".join(nearbyTrackedArmies)}')
            army.expectedPaths = ArmyTracker.get_army_expected_path(self.map, army, self.general, self.player_targets, log_debug=self.log_debug)
            logbook.info(f'set army {str(army)} expected path to {str(army.expectedPaths)}')

        self.armies[tile] = army
        if self.log_debug:
            logbook.info(
                f'ARMY_CREATE turn={self.map.turn} army={army} tile={tile} visible={tile.visible} discovered={tile.discovered} '
                f'player={tile.player} tileArmy={tile.army} delta={tile.delta.armyDelta} unexplainedDelta={tile.delta.unexplainedDelta} '
                f'fromTile={tile.delta.fromTile} toTile={tile.delta.toTile} skip_expected_path={skip_expected_path} '
                f'expectedPaths={[str(path) for path in army.expectedPaths]}')

        return army

    def handle_gathered_to_army(self, army: Army, skip: typing.Set[Tile], trackingArmies: typing.Dict[Tile, Army]):
        logbook.info(
            f"Army {str(army)} tile was just gathered to (or city increment or whatever), nbd, update it.")
        unaccountedForDelta = abs(army.tile.delta.armyDelta)
        source = self.find_visible_source(army.tile)
        if source is None:
            logbook.info(
                f"Army {str(army)} must have been gathered to from under the fog, searching:")
            self.handle_unaccounted_delta(army.tile, army.player, unaccountedForDelta)
        else:
            if source in self.armies:
                sourceArmy = self.armies[source]
                larger = sourceArmy
                smaller = army
                if sourceArmy.value < army.value:
                    larger = army
                    smaller = sourceArmy
                logbook.info(
                    f"Army {str(army)} was gathered to visibly from source ARMY {sourceArmy.toString()} and will be merged as {larger.toString()}")
                skip.add(larger.tile)
                skip.add(smaller.tile)
                self.merge_armies(larger, smaller, army.tile)
                return
            else:
                logbook.info(f"Army {str(army)} was gathered to visibly from source tile {source.toString()}")
                trackingArmies[army.tile] = army
        army.update()

    def test_army_adjacent_move(
            self,
            army: Army,
            adjacent: Tile,
            skip: typing.Set[Tile],
            trackingArmies: typing.Dict[Tile, Army]
    ) -> bool:
        unexplainedSourceDelta = self.unaccounted_tile_diffs.get(army.tile, army.tile.delta.armyDelta)
        armyRealTileDelta = 0 - unexplainedSourceDelta
        unexplainedAdjDelta = self.unaccounted_tile_diffs.get(adjacent, 0)
        positiveUnexplainedAdjDelta = 0 - unexplainedAdjDelta
        adjacentIncludesArmy = SearchUtils.any_where(army.entangledArmies, lambda a: a.tile == adjacent)
        if adjacentIncludesArmy:
            logbook.info(f"    Army skipping {str(army)} -> {adjacent} because there was already an entangled army at this tile.")
            return False

        if adjacent.delta.gainedSight and adjacent.army < positiveUnexplainedAdjDelta // 2:
            logbook.info(f"    Army skipping {str(army)} -> {adjacent} because gained sight and doesn't have much army.")
            return False

        # only works when the source army is still visible
        if armyRealTileDelta > 0 and abs(unexplainedAdjDelta) - abs(armyRealTileDelta) == 0:
            logbook.info(
                f"    Army probably moved from {str(army)} to {adjacent.toString()} based on unexplainedAdjDelta {unexplainedAdjDelta} vs armyRealTileDelta {armyRealTileDelta}")
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True
        elif not army.tile.visible and positiveUnexplainedAdjDelta > 1:
            if positiveUnexplainedAdjDelta * 1.1 - army.value > 0 and army.value > positiveUnexplainedAdjDelta // 2 - 1:
                logbook.info(
                    f"    Army probably moved from {str(army)} to {adjacent.toString()} based on unexplainedAdjDelta {unexplainedAdjDelta} vs armyRealTileDelta {armyRealTileDelta}")
                self.unaccounted_tile_diffs[army.tile] = unexplainedSourceDelta - unexplainedAdjDelta
                self.unaccounted_tile_diffs.pop(adjacent, None)
                self.army_moved(army, adjacent, trackingArmies)
                return True
        elif adjacent.delta.gainedSight and armyRealTileDelta > 0 and positiveUnexplainedAdjDelta * 0.9 < armyRealTileDelta < positiveUnexplainedAdjDelta * 1.25:
            logbook.info(
                f"    Army (WishyWashyFog) probably moved from {str(army)} to {adjacent.toString()}")
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True
        elif positiveUnexplainedAdjDelta != 0 and abs(positiveUnexplainedAdjDelta) - army.value == 0:
            # handle fog moves?
            logbook.info(
                f"    Army (SOURCE FOGGED?) probably moved from {str(army)} to {adjacent.toString()}. adj (dest) visible? {adjacent.visible}")
            oldTile = army.tile
            if oldTile.army > army.value - positiveUnexplainedAdjDelta and not oldTile.visible:
                newArmy = adjacent.army
                logbook.info(
                    f"Updating tile {oldTile.toString()} army from {oldTile.army} to {newArmy}")
                # NEVER modify visible tile army values
                if not oldTile.visible:
                    oldTile.army = army.value - positiveUnexplainedAdjDelta + 1

            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True

        return False

    def use_fog_source_path_and_increase_emergence(
            self,
            armyTile: Tile,
            sourceFogArmyPath: Path,
            delta: int,
            emergingPlayer: int = -1,
            depthLimit: int | None = None,
    ) -> bool:
        """
        Verifies whether a fog source path was good or not and returns True if good, False otherwise.
        Handles notifying army emergence for poor army resolution paths.

        @param armyTile:
        @param sourceFogArmyPath:
        @param delta: the (positive) tile delta to be matching against for the fog path.
        @return:
        """
        player = sourceFogArmyPath.start.tile.player
        if player == -1:
            try:
                a = self.armies[sourceFogArmyPath.start.tile]
            except KeyError:
                a = None
            if a is not None:
                player = a.player

        convertedCity = False
        dist = 0
        for tile in sourceFogArmyPath.tileList:
            isVisionLessNeutCity = tile.isCity and tile.isNeutral and not tile.visible
            if tile.isUndiscoveredObstacle or isVisionLessNeutCity:
                self.convert_fog_city_to_player_owned(tile, player)
                convertedCity = True

            if convertedCity:
                increase = 1 + sourceFogArmyPath.length - dist
                self.emergenceLocationMap[player][tile] += increase

            dist += 1

        fogPath = sourceFogArmyPath.get_reversed()
        emergenceValueCovered = sourceFogArmyPath.value - armyTile.army
        self.fogPaths.append(fogPath)
        minRatio = 0.85
        leeway = min(4, self.map.turn // 50) + 1

        isGoodResolution = emergenceValueCovered + leeway > delta * minRatio  # +3 offsets incorrect fog guess tiles moved over by the army at lower emergence values
        logbook.info(
            f"emergenceValueCovered ({emergenceValueCovered} + leeway {leeway}) > delta {delta} * {minRatio} ({armyTile.army * minRatio:.1f}) : {isGoodResolution}")
        if not isGoodResolution:
            armyEmergenceValue = max(4.0, delta - emergenceValueCovered)
            logbook.info(
                f"  WAS POOR RESOLUTION! Adding emergence for player {armyTile.player} armyTile {armyTile.toString()} value {armyEmergenceValue}")
            self.new_army_emerged(armyTile, armyEmergenceValue, emergingPlayer=emergingPlayer, distance=depthLimit)
        else:
            # Make the emerged tile path be permanent...?
            for t in fogPath.tileList:
                if t.isTempFogPrediction:
                    t.isTempFogPrediction = False

        return isGoodResolution

    def check_for_should_scrap_unmoved_army(self, army: Army):
        thresh = self.track_threshold - 1
        if self.map.get_distance_between(self.general, army.tile) < 5:
            thresh = 4
        if self.map.get_distance_between(self.general, army.tile) < 2:
            thresh = 2

        if (
                (army.tile.visible and army.value < thresh)
                or (not army.tile.visible and army.value < thresh)
        ):
            logbook.info(f"  Army {str(army)} Stopped moving. Scrapped for being low value")
            self.scrap_army(army, scrapEntangled=False)

    def scrap_unmoved_low_armies(self):
        for army in list(self.armies.values()):
            if army.last_moved_turn < self.map.turn - 1:
                self.check_for_should_scrap_unmoved_army(army)

    @classmethod
    def get_army_expected_path(
            cls,
            map: MapBase,
            army: Army,
            general: Tile,
            playerTargets: typing.List[Tile],
            negativeTiles: typing.Set[Tile] | None = None,
            log_debug: bool = False
    ) -> typing.List[Path]:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the tiles,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """
        if isinstance(army, Tile):
            raise AssertionError('Dont call this with tiles instead of army')

        if log_debug:
            logbook.info(
                f'EXPECTED_PATH_DEBUG_ENTRY turn={map.turn} army={army} tile={army.tile} '
                f'value={army.value} tileArmy={army.tile.army} player={army.player} '
                f'visible={army.tile.visible} discovered={army.tile.discovered} '
                f'negativeCount={0 if negativeTiles is None else len(negativeTiles)} '
                f'targets={[str(target) for target in playerTargets]}')

        if map.is_tile_friendly(army.tile):
            # Why would we be using this for friendly armies...?
            if log_debug:
                logbook.info(f'EXPECTED_PATH_DEBUG_RETURN_FRIENDLY turn={map.turn} army={army} tile={army.tile}')
            return []

        if army.value <= 0:
            if army.tile.army > 1:
                army.value = army.tile.army - 1
            else:
                if log_debug:
                    logbook.info(
                        f'EXPECTED_PATH_DEBUG_RETURN_NO_ARMY turn={map.turn} army={army} tile={army.tile} '
                        f'value={army.value} tileArmy={army.tile.army}')
                return []

        remainingCycleTurns = 50 - map.turn % 50

        if negativeTiles is None:
            negativeTiles = set()

        def log_expected_path_source(source: str, path: Path | None):
            if not log_debug:
                return
            visibleTiles = []
            if path is not None:
                for pathTile in path.tileList:
                    if pathTile.visible:
                        visibleTiles.append(str(pathTile))
            logbook.info(
                f'EXPECTED_PATH_DEBUG_SOURCE turn={map.turn} source={source} army={army} '
                f'path={path} visibleTiles={visibleTiles}')

        pathA = ArmyTracker.get_army_expected_path_non_flank(map, army, general, playerTargets, negativeTiles=negativeTiles)
        log_expected_path_source('non_flank_a', pathA)
        if log_debug:
            logbook.info(f'EXPECTED_PATH_DEBUG_NON_FLANK_RESULT turn={map.turn} army={army} path={pathA}')
        if pathA and pathA.length > 0:
            negativeTiles.update(pathA.tileList)
            if log_debug:
                logbook.info(
                    f'EXPECTED_PATH_DEBUG_NEGATIVE_AFTER_NON_FLANK turn={map.turn} army={army} '
                    f'negativeTiles={[str(tile) for tile in negativeTiles]}')
        pathB = ArmyTracker.get_army_expected_path_flank(map, army, general, negativeTiles=negativeTiles, log_debug=log_debug)
        log_expected_path_source('flank_b', pathB)
        if log_debug:
            logbook.info(f'EXPECTED_PATH_DEBUG_FLANK_RESULT turn={map.turn} army={army} path={pathB}')

        matrices = []

        paths = []
        if pathA is not None and pathA.length > 0:
            paths.append(pathA)
            matrices.append(map.distance_mapper.get_tile_dist_matrix(pathA.tail.tile))
        if pathB is not None and pathB.length > 0 and not SearchUtils.any_where(paths, lambda p: p.tail.tile == pathB.tail.tile):
            paths.append(pathB)
            if pathB.length > 2:
                pathC = ArmyTracker.get_army_expected_path_flank(map, army, general, skipTiles=pathB.tileList[3:], negativeTiles=negativeTiles, log_debug=log_debug)
                log_expected_path_source('flank_c', pathC)
                if log_debug:
                    logbook.info(f'EXPECTED_PATH_DEBUG_FLANK_C_RESULT turn={map.turn} army={army} path={pathC}')
                if pathC is not None and pathC.length > 0 and pathC.tail.tile != pathB.tail.tile:
                    paths.append(pathC)
                    matrices.append(map.distance_mapper.get_tile_dist_matrix(pathC.tail.tile))
            matrices.append(map.distance_mapper.get_tile_dist_matrix(pathB.tail.tile))

        if len(matrices) == 0:
            matrices.append(map.distance_mapper.get_tile_dist_matrix(general))
        summed = MapMatrix.get_summed(matrices)
        # summed.negate()
        pathD = ArmyTracker.get_expected_enemy_expansion_path(map, army.tile, general, negativeTiles=set(itertools.chain.from_iterable(p.tileList for p in paths)), maxTurns=max(15, remainingCycleTurns), prioMatrix=summed)
        log_expected_path_source('expansion_d', pathD)
        if log_debug:
            logbook.info(f'EXPECTED_PATH_DEBUG_EXPANSION_D_RESULT turn={map.turn} army={army} path={pathD}')
        if pathD is not None and pathD.length > 0:
            paths.append(pathD)
            # MapMatrix.subtract_from_matrix(summed, map.distance_mapper.get_tile_dist_matrix(pathD.tail.tile))
            MapMatrix.add_to_matrix(summed, map.distance_mapper.get_tile_dist_matrix(pathD.tail.tile))
            pathE = ArmyTracker.get_expected_enemy_expansion_path(map, army.tile, general, negativeTiles=set(itertools.chain.from_iterable(p.tileList for p in paths)), maxTurns=max(15, remainingCycleTurns), prioMatrix=summed)
            log_expected_path_source('expansion_e', pathE)
            if log_debug:
                logbook.info(f'EXPECTED_PATH_DEBUG_EXPANSION_E_RESULT turn={map.turn} army={army} path={pathE}')
            if pathE is not None and pathE.length > 0:
                paths.append(pathE)

        if len(paths) > 1:
            secondTile = paths[0].tileList[1]
            noAltExits = True
            for otherPath in paths[1:]:
                if otherPath.tileList[1] != secondTile:
                    noAltExits = False
                    break
            if noAltExits:
                skips = {secondTile}

                pathF = ArmyTracker.get_expected_enemy_expansion_path(map, army.tile, general, negativeTiles=set(itertools.chain.from_iterable(p.tileList for p in paths)), prioMatrix=summed, maxTurns=remainingCycleTurns, skipTiles=skips)
                log_expected_path_source('expansion_f', pathF)
                if log_debug:
                    logbook.info(f'EXPECTED_PATH_DEBUG_EXPANSION_F_RESULT turn={map.turn} army={army} path={pathF}')
                if pathF is not None and pathF.length > 0:
                    paths.append(pathF)
        if log_debug:
            logbook.info(
                f'EXPECTED_PATH_DEBUG_RETURN turn={map.turn} army={army} '
                f'paths={[str(path) for path in paths]}')
        for path in paths:
            logbook.info(f"Army {army} NEW expected path: {path}")
        return paths

    @classmethod
    def get_army_expected_path_non_flank(
            cls,
            map: MapBase,
            army: Army,
            general: Tile,
            player_targets: typing.List[Tile],
            negativeTiles: typing.Set[Tile] | None = None
    ) -> Path | None:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the tiles,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """

        if army.value <= 0:
            return None

        if army.tile.isCity and len(army.expectedPaths) == 0 and army.tile.lastMovedTurn < map.turn - 2:
            return None

        if army.player == map.player_index or army.player in map.teammates:
            return None

        armyDistFromGen = map.get_distance_between(general, army.tile)

        skip = set()
        skipCutoff = 3 * army.value // 4

        for player in map.players:
            if not map.is_player_on_team_with(player.index, map.player_index):
                continue

            for tile in player.tiles:
                if tile.army > skipCutoff and not tile.isCity and not tile.isGeneral and map.is_tile_visible_to(tile, army.player):
                    skip.add(tile)

        def goalFunc(tile: Tile, armyAmt: int, dist: int) -> bool:
            # don't pick cities over general as tiles when they're basically the same distance from gen, pick gen if its within 2 tiles of other tiles.
            if dist + 2 < armyDistFromGen and tile in player_targets:
                return True
            if tile == map.generals[map.player_index]:
                return True
            return False

        if len(army.entangledArmies) > 0:
            for entangled in army.entangledArmies:
                skip.add(entangled.tile)
                for entangledPath in entangled.expectedPaths:
                    skip.update(entangledPath.tileList)

        logbook.info(f'Looking for army {str(army)}s expected non-flank movement path:')
        path = SearchUtils.breadth_first_find_queue(
            map,
            [army.tile],
            # goalFunc=lambda tile, armyAmt, dist: armyAmt + tile.army > 0 and tile in player_targets,  # + tile.army so that we find paths that reach tiles regardless of killing them.
            goalFunc=goalFunc,
            prioFunc=lambda t: (not t.visible, t.player == army.player, t.army if t.player == army.player else 0 - t.army),
            skipTiles=skip,
            maxTime=1.0,
            maxDepth=23,
            noNeutralCities=army.tile.army < 150,
            searchingPlayer=army.player,
            negativeTiles=negativeTiles,
            noLog=True)

        if path is None:
            return None
            # path = SearchUtils.breadth_first_find_queue(
            #     map,
            #     [army.tile],
            #     # goalFunc=lambda tile, armyAmt, dist: armyAmt + tile.army > 0 and tile in player_targets,  # + tile.army so that we find paths that reach tiles regardless of killing them.
            #     goalFunc=goalFunc,
            #     prioFunc=lambda t: (not t.visible, t.player == army.player, t.army if t.player == army.player else 0 - t.army),
            #     skipTiles=skip,
            #     maxTime=0.1,
            #     maxDepth=23,
            #     noNeutralCities=army.tile.army < 150,
            #     searchingPlayer=army.player,
            #     noLog=True)

        return path.get_positive_subsegment(forPlayer=army.player, teams=MapBase.get_teams_array(map), negativeTiles=negativeTiles)

    @classmethod
    def get_army_expected_path_flank(
            cls,
            map: MapBase,
            army: Army,
            general: Tile,
            skipTiles: typing.List[Tile] | None = None,
            negativeTiles: typing.Set[Tile] | None = None,
            log_debug: bool = False
    ) -> Path | None:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the tiles,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """

        if army.value <= 0:
            return None

        if army.tile.isCity and len(army.expectedPaths) == 0 and army.tile.lastMovedTurn < map.turn - 2:
            return None

        if army.player == map.player_index or army.player in map.teammates:
            return None

        debugFlankPathing = log_debug
        if debugFlankPathing:
            logbook.info(
                f'FLANK_PATH_DEBUG_START turn={map.turn} army={army} tile={army.tile} '
                f'value={army.value} tileArmy={army.tile.army} player={army.player} '
                f'visible={army.tile.visible} discovered={army.tile.discovered} '
                f'negativeCount={0 if negativeTiles is None else len(negativeTiles)} '
                f'skipTilesCount={0 if skipTiles is None else len(skipTiles)}')

        def valueFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile.visible:
                if debugFlankPathing:
                    logbook.info(
                        f'FLANK_PATH_DEBUG_VALUE_REJECT_VISIBLE turn={map.turn} '
                        f'tile={tile} prioVals={prioVals}')
                return None

            value = 0 - map.get_distance_between(general, tile), 0
            if debugFlankPathing:
                logbook.info(
                    f'FLANK_PATH_DEBUG_VALUE_ACCEPT turn={map.turn} tile={tile} '
                    f'generalDist={map.get_distance_between(general, tile)} value={value} prioVals={prioVals}')
            return value

        def prioFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile.visible:
                if debugFlankPathing:
                    logbook.info(
                        f'FLANK_PATH_DEBUG_PRIO_REJECT_VISIBLE turn={map.turn} '
                        f'tile={tile} prioVals={prioVals}')
                return None

            priority = map.get_distance_between(general, tile), 0
            if debugFlankPathing:
                logbook.info(
                    f'FLANK_PATH_DEBUG_PRIO_ACCEPT turn={map.turn} tile={tile} '
                    f'priority={priority} prioVals={prioVals}')
            return priority

        skip = MapMatrixSet(map)

        visibleSkipCount = 0
        for tile in map.get_all_tiles():
            if tile.visible:
                skip.add(tile)
                visibleSkipCount += 1

        if skipTiles is not None:
            skip.update(skipTiles)
        if debugFlankPathing:
            candidateTiles = []
            for tile in map.get_all_tiles():
                candidateTiles.append(
                    f'{tile}:vis{tile.visible}:disc{tile.discovered}:p{tile.player}:a{tile.army}:skip{tile in skip}')
            logbook.info(
                f'FLANK_PATH_DEBUG_SKIP_SUMMARY turn={map.turn} visibleSkipCount={visibleSkipCount} '
                f'totalSkipCount={sum(1 for skipped in skip.raw if skipped)} candidates={" | ".join(candidateTiles)}')

        if len(army.entangledArmies) > 0:
            for entangled in army.entangledArmies:
                skip.add(entangled.tile)
                for entangledPath in entangled.expectedPaths:
                    skip.update(entangledPath.tileList)

        startTiles = {army.tile: ((0, 0), 0)}

        logbook.info(f'Looking for army {str(army)}s expected flank path:')
        path = SearchUtils.breadth_first_dynamic_max(
            map,
            startTiles,
            # goalFunc=lambda tile, armyAmt, dist: armyAmt + tile.army > 0 and tile in player_targets,  # + tile.army so that we find paths that reach tiles regardless of killing them.
            valueFunc=valueFunc,
            priorityFunc=prioFunc,
            skipTiles=skip,
            maxTime=1.0,
            maxDepth=30,
            noNeutralCities=army.tile.army < 150,
            searchingPlayer=army.player,
            noLog=True)

        if path is None:
            if debugFlankPathing:
                logbook.info(f'FLANK_PATH_DEBUG_RAW_RESULT_NONE turn={map.turn} army={army}')
            return None

        if debugFlankPathing:
            logbook.info(f'FLANK_PATH_DEBUG_RAW_RESULT turn={map.turn} path={path}')

        positivePath = path.get_positive_subsegment(forPlayer=army.player, teams=MapBase.get_teams_array(map), negativeTiles=negativeTiles)
        if debugFlankPathing:
            logbook.info(f'FLANK_PATH_DEBUG_POSITIVE_RESULT turn={map.turn} path={positivePath}')
        return positivePath

    def convert_fog_city_to_player_owned(self, tile: Tile, player: int, isTempFogPrediction: bool = True):
        if player == -1:
            raise AssertionError(f'lol player -1 in convert_fog_city_to_player_owned for tile {str(tile)}')
        wasUndisc = not tile.discovered
        tile.update(self.map, player, army=1, isCity=True, isGeneral=False)
        tile.update(self.map, TILE_OBSTACLE, army=0, isCity=False, isGeneral=False)
        tile.delta = TileDelta()
        if wasUndisc:
            tile.discovered = False
            tile.discoveredAsNeutral = False
            tile.isTempFogPrediction = isTempFogPrediction

        self.map.players[player].cities.append(tile)
        self.map.update_reachable()

    def handle_unaccounted_delta(self, tile: Tile, player: int, unaccountedForDelta: int) -> Army | None:
        """
        Sources a (positive) delta army amount from fog and announces army emergence if not well-resolved.
        Returns an army the army resolved to be, if one is found.
        DOES NOT create an army if a source fog army is not found.
        """

        # # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog covers a small visible +1 enemy tile delta adjacent to fog armies that were just pushed back into fog. Do not resolve that low-value visible tile growth through fog source pathing, or it creates a phantom tracked army at the visible tile.
        # if (tile.delta.discovered or tile.visible) and not tile.army > self.track_threshold and not unaccountedForDelta > self.track_threshold and len(self.map.players[player].tiles) > 4:
        #     return None

        depthLimit = self.get_emergence_max_depth_to_general_or_none(player, tile, unaccountedForDelta, useOpponentKnownFogTileArmy=False)
        generalDepthLimit = self.get_emergence_max_depth_to_general_or_none(player, tile, unaccountedForDelta)

        if tile not in self.skip_emergence_tile_pathings:
            sourceFogArmyPath = self.find_fog_source(player, tile, unaccountedForDelta, depthLimit=depthLimit)
            if sourceFogArmyPath is not None:
                limitFromTile = tile
                if tile.delta.toTile is not None and tile.delta.toTile.visible and not tile.visible:
                    limitFromTile = tile.delta.toTile
                self.unaccounted_tile_diffs.pop(tile, 0)
                # we can only depth-limit when we found SOME fog army path...
                # idk why this was originally filtering with toTile is None? But was failing test_should_know_the_general_is_literally_right_there__wtf
                if generalDepthLimit is not None and generalDepthLimit < 60 and (limitFromTile.delta.toTile is None or limitFromTile.delta.toTile.visible):
                    maxDistToGen = generalDepthLimit
                    logbook.info(f'WHOO LIMITING GENERAL BY {generalDepthLimit} from {limitFromTile} (tile was {tile}) BASED ON SHEER STANDING ARMY EMERGENCE')

                    self._limit_general_position_to_within_tile_and_distance(player, limitFromTile, maxDistToGen, alsoIncreaseEmergence=True, skipIfLongerThanExisting=True, emergenceAmount=unaccountedForDelta)

                if sourceFogArmyPath.start.tile.player != player:
                    if sourceFogArmyPath.start.tile.isGeneral:
                        raise Exception(f'WTF trying to path from a different general...? {sourceFogArmyPath}')
                    sourceFogArmyPath.start.tile.player = player

                wasGoodPath = self.use_fog_source_path_and_increase_emergence(tile, sourceFogArmyPath, unaccountedForDelta, depthLimit=depthLimit)
                if wasGoodPath:
                    self.pathed_fog_emergence_tiles.add(tile)

                return self.resolve_fog_emergence(player, sourceFogArmyPath, tile)

        if self.opponent_tracker is not None and unaccountedForDelta > self.track_threshold:
            self.opponent_tracker.notify_unresolved_emerged_army(tile, player, unaccountedForDelta)

        return None

    def get_emergence_max_depth_to_general_or_none(self, player: int, tile: Tile, unaccountedForDelta: int = -1, useOpponentKnownFogTileArmy: bool = True):
        # TODO if we take into account the worst case amount of army they guaranteed have left on their tiles from OpponentTracker
        #  eg in test test_because_of_opponent_tracker_registering_max_possible_emergence_pulling_ALL_army_off_of_general_should_limit_gen_spawn we limit to dist 10
        #  but really we know they have at minimum 2x 2s left in that test so we could actually limit to 6 since 2 army can't be on the general from that knowledge.
        if unaccountedForDelta == -1:
            unaccountedForDelta = abs(tile.delta.armyDelta)
        armyPlayerObj = self.map.players[player]
        depthLimit = None
        armyInFog = armyPlayerObj.standingArmy - armyPlayerObj.visibleStandingArmy
        if useOpponentKnownFogTileArmy:
            ogArmyInFog = armyInFog
            armyInFog = max(0, min(armyInFog, armyInFog - self._get_known_non_general_fog_tile_extra_army(player, assumeUnderestimation=True)))
            logbook.info(f'general limiter adjusted from armyInFog {ogArmyInFog} to {armyInFog} base don _get_known_non_general_fog_tile_extra_army')
        if unaccountedForDelta > 2 * armyInFog - 4:
            depthLimit = self._calculate_maximum_general_distance_for_raw_fog_standing_army(armyPlayerObj, armyInFog)

        return depthLimit

    def _get_known_non_general_fog_tile_extra_army(self, player: int, assumeUnderestimation: bool = False) -> int:
        if self.opponent_tracker is None:
            return 0

        fogTileCountDict = self.opponent_tracker.get_player_fog_tile_count_dict(player)
        extraArmy = 0
        maxTileSize = 0
        for tileArmy, tileCount in fogTileCountDict.items():
            if tileArmy <= 1:
                continue
            extraArmy += (tileArmy - 1) * tileCount
            maxTileSize = max(tileArmy, maxTileSize)

        offset = 0
        # assume we overestimate their gather efficiency by a few tiles.
        #  We need to do this because if we thought they had no leftover 2's on a previous round, and they actually were inefficient and DID leave some leftover 2's,
        #  then we assume their gather moves this round could only gather 2s when they could gather a few 3's, making us off by a few.
        #  This offset is just a shot in the dark but hopefully it is pretty accurate.
        if assumeUnderestimation:
            offset = maxTileSize + 1
        return extraArmy - offset

    def add_need_to_track_city(self, city: Tile):
        logbook.info(f'armytracker tracking updated city for next scan: {str(city)}')
        self.updated_city_tiles.add(city)

    def rescan_city_information(self):
        for city in self.updated_city_tiles:
            self.check_need_to_shift_fog_city(city)

            self.check_if_this_city_was_actual_fog_city_location(city)

        for player in self.map.players:
            for city in player.cities:
                if not city.discovered:
                    self.check_need_to_shift_fog_city(city)

        self.updated_city_tiles = set()

    def check_need_to_shift_fog_city(self, city: Tile) -> Tile | None:
        if not city.discovered:
            noFriendlies = True
            for t in city.movableNoObstacles:
                if self.map.is_tile_on_team_with(t, city.player):
                    noFriendlies = False
                    break

            if noFriendlies:
                newCity = self._find_replacement_fog_city_internal(city, forceConnected=True)
                return newCity

        if city.delta.oldOwner == city.player:
            return None
        if city.delta.oldOwner == -1:
            return None
        if city.was_visible_last_turn():
            return None

        if len(self.map.players[city.delta.oldOwner].cities) >= self.map.players[city.delta.oldOwner].cityCount + 1:
            logbook.info(f'Not shifting player {city.delta.oldOwner} city {str(city)} because already enough cities on the board.')
            return None

        newCity = self._find_replacement_fog_city_internal(city, forceConnected=True)

        return newCity

    def _find_replacement_fog_city_internal(self, city: Tile, forceConnected: bool):
        prevArmy = city.delta.oldArmy

        cityOwner = city.delta.oldOwner
        if not city.visible:
            cityOwner = city.player

        cityPlayer = self.map.players[cityOwner]

        logbook.info(f"_find_replacement_fog_city_internal FINDING NEXT FOG CITY FOR PLAYER {cityOwner} for not-fog-city tile {str(city)}")
        newCity = self.find_next_fog_city_candidate_near_tile(cityOwner, city, forceConnected=forceConnected)
        if not city.discovered:
            self.map.reset_wrong_undiscovered_fog_guess(city)
        if not city.isCity or cityOwner != city.player:
            cityPlayer.cities = [c for c in cityPlayer.cities if c != city]

        if newCity:
            newCity.army = prevArmy
            newCity.isTempFogPrediction = True

        return newCity

    def check_if_this_city_was_actual_fog_city_location(self, city: Tile):
        if not city.visible:
            return None
        if not city.isCity and not city.isGeneral:
            return None
        if city.isNeutral:
            return None
        if city.delta.oldOwner == city.player:
            return None

        # we just detected that player has this city.
        self.remove_nearest_fog_city(city.player, tile=city, distanceIfNotExcessCities=10)

    def detect_army_likely_breached_wall(self, armyPlayer: int, tile: Tile, delta: int | None = None) -> bool:
        """
        Returns true if an army emerging on tile likely breached a wall to get there.

        @param armyPlayer:
        @param tile:
        @param delta:
        @return:
        """

        emgMap = self.emergenceLocationMap[armyPlayer]

        def reasonablePathDetector(sourceTile: Tile, armyAmt: int, dist: int) -> bool:
            if sourceTile.isObstacle:
                return False
            if emgMap.raw[sourceTile.tile_index] <= 0:
                return False
            if sourceTile.visible:
                return False
            if sourceTile == tile:
                return False

            return True

        reasonablePath = SearchUtils.breadth_first_find_queue(self.map, [tile], reasonablePathDetector, noNeutralCities=True, maxDepth=6, noLog=True)
        if reasonablePath is not None:
            logbook.info(f'army {str(tile)} by p{armyPlayer} found a reasonable path, so non-wall-breach. Path {str(reasonablePath)}.')
            return False

        logbook.info(f'army {str(tile)} by p{armyPlayer} likely breached wall as no reasonable path was found.')

        return True

    def verify_player_tile_and_army_counts_valid(self):
        """
        Makes sure we dont have too many fog tiles or too much fog army for what is visible and known on the player map.

        @return:
        """

        logbook.info(f'PLAYER FOG TILE RE-EVALUATION')
        for player in self.map.players:
            actualTileCount = player.tileCount

            mapTileCount = len(player.tiles)

            visibleMapTileCount = 0

            for tile in player.tiles:
                if tile.visible:
                    visibleMapTileCount += 1

            emgMap = self.emergenceLocationMap[player.index]

            if actualTileCount < mapTileCount:
                logbook.info(f'reducing player {player.index} over-tiles')
                realDists = SearchUtils.build_distance_map_matrix(self.map, list(self.tiles_ever_owned_by_player[player.index]))

                # strip extra tiles
                tilesAsEncountered = SearchUtils.HeapQueue()
                for tile in player.tiles:
                    if not tile.discovered:
                        dist = realDists[tile]
                        emergenceBonus = max(0.0, emgMap.raw[tile.tile_index])
                        tilesAsEncountered.put((emergenceBonus / (dist + 1) - 3 * dist + tile.army, tile))

                while mapTileCount > actualTileCount and tilesAsEncountered.queue:
                    toRemove: Tile
                    score, toRemove = tilesAsEncountered.get()
                    if not toRemove.isCity and not toRemove.isGeneral:
                        logbook.info(f'dropped player {player.index} over-tile tile {str(toRemove)}')
                        self.reset_temp_tile_marked(toRemove, noLog=True)
                        mapTileCount -= 1
                        try:
                            army = self.armies[toRemove]
                        except KeyError:
                            army = None
                        if army:
                            self.scrap_army(army, scrapEntangled=False)

                player.tiles = [t for t in self.map.get_all_tiles() if t.player == player.index]

            actualScore = player.score
            mapScore = 0
            visibleMapScore = 0
            entangledTracker = set()
            for tile in player.tiles:
                if tile.visible:
                    visibleMapScore += tile.army

                try:
                    army = self.armies[tile]
                except KeyError:
                    army = None
                if army is not None and len(army.entangledArmies) > 0:
                    if army.name in entangledTracker:
                        continue
                    entangledTracker.add(army.name)
                mapScore += tile.army

            if actualScore < mapScore:
                logbook.info(f'reducing player {player.index} over-score, actual {actualScore} vs map {mapScore}')
                # strip extra tiles
                tilesAsEncountered = HeapQueue()
                for tile in player.tiles:
                    genCityDePriority = 0

                    if tile.isGeneral or tile.isCity:
                        genCityDePriority = 50

                    if tile in self.armies:
                        genCityDePriority += 10

                    try:
                        tileArmy = self.armies[tile]
                    except KeyError:
                        tileArmy = None
                    if not tile.visible and (tileArmy is None or len(tileArmy.entangledArmies) == 0):
                        dist = self.map.get_distance_between(self.general, tile)
                        emergenceBonus = max(0.0, self.emergenceLocationMap[player.index][tile])
                        tilesAsEncountered.put((emergenceBonus - tile.lastSeen + genCityDePriority - dist / 10, tile))

                while mapScore > actualScore and tilesAsEncountered.queue:
                    toReduce: Tile
                    score, toReduce = tilesAsEncountered.get()
                    reduceTo = 1
                    if self.map.turn % 50 < 15:
                        reduceTo = 2

                    reduceBy = toReduce.army - reduceTo
                    if mapScore - reduceBy < actualScore:
                        reduceBy = mapScore - actualScore

                    logbook.info(f'reducing player {player.index} over-score tile {str(toReduce)} by {reduceBy}')

                    toReduce.army = toReduce.army - reduceBy
                    mapScore -= reduceBy
                    self.decremented_fog_tiles_this_turn.add(toReduce)
                    try:
                        army = self.armies[toReduce]
                    except KeyError:
                        army = None
                    if army:
                        army.value = toReduce.army - 1
                        if army.value <= 0:
                            self.scrap_army(army, scrapEntangled=False)

    def get_tile_emergence_for_player(self, tile: Tile, player: int) -> float:
        if player == -1:
            return 0

        return self.emergenceLocationMap[player][tile]

    def drop_incorrect_player_fog_around(self, neutralTile: Tile, forPlayer: int):
        """
        Does NOT remove tiles from players tile lists

        @param neutralTile:
        @param forPlayer:
        @return:
        """
        logbook.info(f'drop_incorrect_player_fog_around for player {forPlayer} wrong tile {str(neutralTile)}')
        q = deque()

        # TODO this might be droppable to 2 now that I fixed the ever_owned_by_player update order..
        playerTileAdvantageDepth = 3

        isDroppingChainedBadFog = forPlayer != -1
        if isDroppingChainedBadFog:
            allFogTilesNearby = self.tiles_ever_owned_by_player[forPlayer].copy()

            def foreachFunc(t: Tile):
                allFogTilesNearby.add(t)
                return t.visible and t not in self.tiles_ever_owned_by_player[forPlayer]

            SearchUtils.breadth_first_foreach(self.map, list(self.tiles_ever_owned_by_player[forPlayer]), playerTileAdvantageDepth, foreachFunc=foreachFunc, noLog=True)
            for tile in allFogTilesNearby:
                q.append((forPlayer, tile))
        else:
            for p, tileSet in enumerate(self.tiles_ever_owned_by_player):
                allFogTilesNearby = tileSet.copy()

                def foreachFunc(t: Tile):
                    allFogTilesNearby.add(t)
                    return t.visible and t not in tileSet

                SearchUtils.breadth_first_foreach(self.map, list(tileSet), playerTileAdvantageDepth, foreachFunc=foreachFunc, noLog=True)
                for tile in allFogTilesNearby:
                    q.append((p, tile))

        forPlayerRequiredConnected = self.player_connected_tiles[forPlayer]

        q.append((-1, neutralTile))

        visited = set()
        while q:
            curPlayer: int
            curTile: Tile
            curPlayer, curTile = q.popleft()

            if curTile in visited:
                continue

            if curTile.discoveredAsNeutral and not curTile.delta.gainedSight and not curPlayer == -1:
                continue

            visited.add(curTile)

            if not curTile.discovered or curTile.isTempFogPrediction:
                if isDroppingChainedBadFog:
                    if curPlayer == -1 and curTile.player == forPlayer and curTile not in forPlayerRequiredConnected:
                        self.should_recalc_fog_land_by_player[curTile.player] = True
                        self.reset_temp_tile_marked(curTile)
                    if curPlayer == -1:
                        self.emergenceLocationMap[forPlayer][curTile] = 0
                else:
                    if curTile.player != -1 and curPlayer != curTile.player and curTile not in forPlayerRequiredConnected and curTile.player != -1:
                        self.should_recalc_fog_land_by_player[curTile.player] = True
                        self.reset_temp_tile_marked(curTile)

            if curTile.visible and curTile.discoveredAsNeutral and not curTile.delta.gainedSight and curTile != neutralTile:
                if isDroppingChainedBadFog:
                    if curTile not in self.tiles_ever_owned_by_player[forPlayer] and curTile.player != forPlayer:
                        continue
                # elif curPlayer != -1 and curTile not in self.tiles_ever_owned_by_player[curPlayer] and curTile.player != curPlayer:
                #     continue

            if not curTile.isUndiscoveredObstacle:
                for tile in curTile.movable:
                    # if tile not in visited:
                    q.append((curPlayer, tile))

    def _pre_army_track_handle_flipped_tiles(self):
        """To be called every time a tile is flipped from one owner to another owner by the map updates themselves."""

        for tile in self._flipped_tiles:
            if tile.player != -1:  #  and (tile.delta.oldOwner == -1 or not self.map.players[tile.delta.oldOwner].dead)  # not sure why this logic was here...?
                self.tiles_ever_owned_by_player[tile.player].add(tile)

        self._handle_flipped_discovered_as_neutrals()

        if self.map.has_misty_veil and self.map.has_watchtower:
            for oldOwner, tile in self._flipped_by_army_tracker_this_turn:
                if self.map.is_tile_friendly(tile):
                    for mv in tile.movable:
                        if not mv.visible:
                            for playerMat in self.valid_general_positions_by_player:
                                playerMat.raw[mv.tile_index] = False

    def _post_army_track_handle_flipped_tiles(self):
        """To be called every time a tile is flipped from one owner to another owner by the map updates themselves."""

        reTilePlayers = set()
        for oldOwner, tile in self._flipped_by_army_tracker_this_turn:

            if oldOwner >= 0:
                reTilePlayers.add(oldOwner)
                if not self.map.is_player_on_team_with(oldOwner, tile.player):
                    self.unrecaptured_emergence_events[oldOwner].discard(tile)
            if tile.player >= 0:
                reTilePlayers.add(tile.player)

        if len(reTilePlayers) > 0:
            with self.perf_timer.begin_move_event(f're-tiling players {reTilePlayers}'):
                for playerIndex in reTilePlayers:
                    player = self.map.players[playerIndex]
                    player.tiles = []
                for tile in self.map.reachable_tiles:
                    if tile.player == -1 or tile.player not in reTilePlayers:
                        continue

                    player = self.map.players[tile.player]
                    player.tiles.append(tile)

        recheckPlayers = set()
        reFogLandPlayers = set()

        for tile in self._flipped_tiles:
            if tile.player != tile.delta.oldOwner and tile.delta.gainedSight:
                if tile.player != -1:
                    self.players_with_incorrect_tile_predictions.add(tile.player)
                if tile.delta.oldOwner != -1:
                    self.players_with_incorrect_tile_predictions.add(tile.delta.oldOwner)
            if tile.delta.discovered and tile.player != -1:
                recheckPlayers.add(tile.player)
                for adj in tile.movable:
                    if adj.player >= 0 and not self.map.is_tile_friendly(adj):
                        reFogLandPlayers.add(adj.player)
                if not self.map.is_tile_friendly(tile) and SearchUtils.any_where(tile.movable, lambda t: not t.visible):
                    self.discovered_enemy_land_connector_tiles[tile.player].add(tile)
                    reFogLandPlayers.add(tile.player)

                for player in self.map.players:
                    # if not self.valid_general_positions_by_player[player.index]
                    emergence = self.emergenceLocationMap[player.index].raw[tile.tile_index]
                    for movable in tile.movable:
                        if movable.discovered:
                            continue
                        movableEmergence = self.emergenceLocationMap[player.index].raw[movable.tile_index]
                        if emergence > movableEmergence:
                            self.emergenceLocationMap[player.index].raw[movable.tile_index] = movableEmergence + emergence // 2

            elif tile.player >= 0 and SearchUtils.any_where(tile.movable, lambda t: not t.discovered):
                reFogLandPlayers.add(tile.player)

            if self.map.is_tile_friendly(tile):
                continue

            if tile.delta.discovered:
                for player in self.map.players:
                    self.valid_general_positions_by_player[player.index].raw[tile.tile_index] = False

                if tile.isGeneral or (tile.isCity and tile.delta.discoveredExGeneralCity):
                    generalPositionPlayer = tile.player
                    if not tile.isGeneral:
                        generalPositionPlayer = -1

                    for player in self.map.players:
                        if player.dead:
                            continue
                        if self.map.is_player_on_team_with(player.index, generalPositionPlayer):
                            if generalPositionPlayer != player.index and self.map.is_2v2:
                                def limitSpawnAroundAllyGen(t: Tile, dist: int) -> bool:
                                    if t.isObstacle or t.isCity:
                                        return True
                                    if dist > MAX_ALLY_SPAWN_DISTANCE or dist < MIN_ALLY_SPAWN_DISTANCE:
                                        self.valid_general_positions_by_player[player.index].discard(t)
                                    return False
                                # TODO stop bypassing default skip once server patch goes live with 2v2 ally distance limit check!
                                logbook.info(f'Limiting limitSpawnAroundAllyGen OUTSIDE dist {MAX_ALLY_SPAWN_DISTANCE} from {tile}')
                                SearchUtils.breadth_first_foreach_dist(self.map, [tile], 1000, foreachFunc=limitSpawnAroundAllyGen, bypassDefaultSkip=True)
                            continue

                        def limitSpawnAroundOtherGen(t: Tile):
                            self.valid_general_positions_by_player[player.index].discard(t)

                        logbook.info(f'Limiting limitSpawnAroundOtherGen at dist {self.min_spawn_distance} from {tile}')
                        SearchUtils.breadth_first_foreach(self.map, [tile], self.min_spawn_distance, foreachFunc=limitSpawnAroundOtherGen, bypassDefaultSkip=True)

                    if generalPositionPlayer != -1:
                        for t in self.map.get_all_tiles():
                            self.valid_general_positions_by_player[generalPositionPlayer].raw[t.tile_index] = False
                        self.valid_general_positions_by_player[generalPositionPlayer].raw[tile.tile_index] = True

        mustReLimit = False
        for tile in self._flipped_tiles:
            if tile.player == -1 and tile.delta.discovered:
                mustReLimit = True
                break

        # TODO why do we do this before we add new limitations below...?
        if mustReLimit:
            self.re_limit_gen_locations()

        for tile in self._flipped_tiles:
            for p in self.map.players:
                if p.general is not None:
                    continue
                if not tile.isGeneral or tile.player != p.index:
                    self.valid_general_positions_by_player[p.index].discard(tile)

            if self.map.is_tile_friendly(tile):
                continue

            if tile.player == -1:
                continue

            if tile.delta.gainedSight and tile.delta.oldOwner == tile.player:
                # We just walked up and now see this tile; the enemy already held it before.
                # This is NOT a fog-emergence event and tells us nothing new about their general location.
                if SearchUtils.any_where(tile.movable, lambda t: not t.visible):
                    self.discovered_enemy_land_connector_tiles[tile.player].add(tile)
                    reFogLandPlayers.add(tile.player)
                continue

            skip = False
            for mv in tile.movable:
                # if (mv.player == tile.player or mv.delta.oldOwner == tile.player) and not mv.delta.gainedSight and mv.discovered: # todo removed gainedsight?
                if (mv.player == tile.player or mv.delta.oldOwner == tile.player) and not mv.delta.gainedSight and mv.discovered:
                    skip = True

            if skip:
                continue

            if tile in self.pathed_fog_emergence_tiles:
                # then we knew about this army, skip it.
                continue

            p = self.map.players[tile.player]

            if (p.tileCount > 75 or p.cityCount > 1) and not self.map.is_custom_map:
                # self.re_limit_gen_locations()
                continue

            logbook.info(f'_flipped_tiles running limit_gen_position_from_emergence p{p}, tile {tile}')
            self.limit_gen_position_from_emergence(p, tile)

        for player in reFogLandPlayers:
            p = self.map.players[player]
            if p.tileCount < 25:
                with self.perf_timer.begin_move_event('extended tile dist limit by tile count'):
                    totalTiles = p.tileCount
                    limitDist = totalTiles
                    # tiles = list([t for t in p.tiles if t.visible])
                    for t in self.tiles_ever_owned_by_player[p.index]:
                        if t.player != p.index:
                            totalTiles += 1
                            limitDist += 1
                            # tiles.append(t)
                        if t.visible:
                            limitDist -= 1

                    visibleElims = [t for t in self.tiles_ever_owned_by_player[p.index] if t.visible]
                    self._limit_general_position_to_within_tiles_and_distance(p.index, visibleElims, limitDist, alsoIncreaseEmergence=False)

        for player in recheckPlayers:
            self._check_over_elimination(player)

    def limit_gen_position_from_emergence(self, p: Player, tile: Tile, emergenceAmount: int = -1):
        # ok then this tile is a candidate for limiting distance from general...?
        pLaunchTiming = self.player_launch_timings[tile.player]

        maxDist = self.map.turn - pLaunchTiming
        maxDist = min(maxDist, p.tileCount - 1)
        # if not tile.delta.gainedSight:
        #     maxDist = min(maxDist, p.tileCount)
        if self.map.turn <= 100 and (pLaunchTiming > 17 or (pLaunchTiming > 13 and self.map.turn < pLaunchTiming * 3)):
            # then, unless they did some real dumb stuff, they can't be further than than their launch timing dist, either
            # THIS produces bad behavior
            cycle1Trail1DistLimitAkaStartArmy = pLaunchTiming // 2  # no +1 because we're including the general as 0. So really a general launching with 9 army can only reach 8 tiles away from the general.
            trail1EndTurn = pLaunchTiming + cycle1Trail1DistLimitAkaStartArmy - 1

            if self.map.turn > trail1EndTurn + 1:
                expectedSecondLaunchArmy = (pLaunchTiming + cycle1Trail1DistLimitAkaStartArmy) // 2 + 1 - cycle1Trail1DistLimitAkaStartArmy
                tilesCapturedInAddlLaunches = p.tileCount - cycle1Trail1DistLimitAkaStartArmy
                turnToRetraverseAndGetFurther = trail1EndTurn + cycle1Trail1DistLimitAkaStartArmy

                if tilesCapturedInAddlLaunches < expectedSecondLaunchArmy:
                    # then we're still in second launch.

                    # TODO if we recorded which turns they captured tiles on, we could subtract from this distance the count of tiles captured during second launch but BEFORE we reached cycle1Trail1DistLimitAkaStartArmy*2 turns from launch
                    if self.map.turn >= turnToRetraverseAndGetFurther:
                        maxExtraDist = self.map.turn - turnToRetraverseAndGetFurther + 1
                        maxExtraDist = min(maxExtraDist, tilesCapturedInAddlLaunches)
                        if maxDist > cycle1Trail1DistLimitAkaStartArmy + maxExtraDist:
                            maxDist = cycle1Trail1DistLimitAkaStartArmy + maxExtraDist
                            logbook.info(f'self.map.turn >= turnToRetraverseAndGetFurther {turnToRetraverseAndGetFurther}, maxDist = min(maxDist {maxDist}, cycle1Trail1DistLimitAkaStartArmy + maxExtraDist {cycle1Trail1DistLimitAkaStartArmy + maxExtraDist} ')
                            # then they cant be further away than their initial trail was as they could have retraversed.
                    elif trail1EndTurn < 44:
                        # then this is their second trail, but they don't have time to get further than original launch dist so, we can still limit by that..
                        if maxDist > cycle1Trail1DistLimitAkaStartArmy:
                            logbook.info(f'Preferring cycle1Trail1DistLimitAkaStartArmy {cycle1Trail1DistLimitAkaStartArmy} over existing maxDist {maxDist} because turn < 44')
                            maxDist = cycle1Trail1DistLimitAkaStartArmy
                    else:
                        logbook.info(f'because of weird nonstandard launch, they may be full retraversing, so FORCING distance to their tilecount {p.tileCount}')
                        maxDist = p.tileCount
                else:
                    if self.map.turn <= 50:
                        # otherwise, they've been capturing tiles, meaning we can limit by the max of either original launch limit or their max second launch limit
                        if maxDist > max(tilesCapturedInAddlLaunches, cycle1Trail1DistLimitAkaStartArmy):
                            logbook.info(f'because turn <= 50 and late launch, we can limit by the max of tilesCapturedInAddlLaunches {tilesCapturedInAddlLaunches} and cycle1Trail1DistLimitAkaStartArmy {cycle1Trail1DistLimitAkaStartArmy}, down from {maxDist}')
                            maxDist = max(tilesCapturedInAddlLaunches, cycle1Trail1DistLimitAkaStartArmy)
                    else:
                        # otherwise, they've had plenty of time
                        if maxDist > tilesCapturedInAddlLaunches + cycle1Trail1DistLimitAkaStartArmy:
                            logbook.info(f'we can limit by the max of tilesCapturedInAddlLaunches {tilesCapturedInAddlLaunches} + cycle1Trail1DistLimitAkaStartArmy {cycle1Trail1DistLimitAkaStartArmy}, down from {maxDist}')
                            maxDist = tilesCapturedInAddlLaunches + cycle1Trail1DistLimitAkaStartArmy

                # can never limit shorter than the original furthest tiles in case we just found that instead of a subsequent trail.
                if maxDist < cycle1Trail1DistLimitAkaStartArmy:
                    logbook.info(f'increasing max to cycle1Trail1DistLimitAkaStartArmy {cycle1Trail1DistLimitAkaStartArmy} up from {maxDist} because can never limit shorter than the original furthest tiles in case we just found that instead of a subsequent trail.')
                    maxDist = cycle1Trail1DistLimitAkaStartArmy
            else:
                if maxDist > cycle1Trail1DistLimitAkaStartArmy:
                    logbook.info(
                        f'havent had time for additional launches so limiting by to cycle1Trail1DistLimitAkaStartArmy {cycle1Trail1DistLimitAkaStartArmy} down from {maxDist}')
                    maxDist = cycle1Trail1DistLimitAkaStartArmy

        # only run the 'distance' emerger if the tile clearly was them moving (and not an old trail).
        if (tile.army > 2 and self.map.turn < 100) or (tile.army > 1 and self.map.turn < 50) or tile.was_visible_last_turn():
            limitByRawStandingArmy = self.get_emergence_max_depth_to_general_or_none(p.index, tile, emergenceAmount)
            if limitByRawStandingArmy is not None and maxDist > limitByRawStandingArmy:
                logbook.info(f'WHOO LIMITING PLAYER {p.index} GENERAL BY {limitByRawStandingArmy} BASED ON SHEER STANDING ARMY EMERGENCE AT {tile}')
                # this function doesn't expect you to include the emerging tile, where our calculation above does.
                maxDist = limitByRawStandingArmy

        increaseEmergence = self.map.turn < 51 or maxDist < 15
        if len(self.uneliminated_emergence_events[p.index]) == 0 or (len(self.uneliminated_emergence_events[p.index]) == 1 and self.uneliminated_emergence_events[p.index].get(tile, 0) > maxDist):
            # logbook.info(f'throwing out p{p.index} emergences for the very first emergence, as we want to use the dist limiter exclusively for first contact.')
            # self._reset_player_emergences(p.index)
            # tile.delta.unexplainedDelta = 0
            self.skip_emergence_tile_pathings.add(tile)
            if tile.delta.fromTile is not None:
                self.skip_emergence_tile_pathings.add(tile.delta.fromTile)

            increaseEmergence = True

        logbook.info(f'running a gen position limiter for p{p.index} from {str(tile)} distance {maxDist}, incEmergence={increaseEmergence}')
        self._limit_general_position_to_within_tile_and_distance(p.index, tile, maxDist, alsoIncreaseEmergence=increaseEmergence, skipIfLongerThanExisting=True, emergenceAmount=emergenceAmount)

    def re_limit_gen_locations(self):
        for p, playerElims in enumerate(self.uneliminated_emergence_events):
            self.re_limit_player_gen_locations(p, playerElims)

    def re_limit_player_gen_locations(self, player: int, playerElimEvents: typing.Dict[Tile, int]):
        for prevElimTile, prevElimDist in playerElimEvents.items():
            cityPerfectInfo = prevElimTile in self.uneliminated_emergence_event_city_perfect_info[player]
            logbook.info(f'RE-eliminating p{player} t{prevElimTile} d{prevElimDist}, perfectCity{cityPerfectInfo}')
            self._limit_general_position_to_within_tile_and_distance(player, prevElimTile, prevElimDist, alsoIncreaseEmergence=False, overrideCityPerfectInfo=cityPerfectInfo, bypass2v2Partner=True)  # alsoIncreaseEmergence=self.map.turn < 56)

    def _handle_flipped_discovered_as_neutrals(self):
        with self.perf_timer.begin_move_event('handling discovered-as-neutral'):
            alreadyRan = set()

            for tile in self._flipped_tiles:
                # this doesn't seem right...? Why is this here...?
                if tile.delta.lostSight:
                    for adj in tile.adjacents:
                        if adj.delta.lostSight and tile.player != -1:
                            self.tiles_ever_owned_by_player[tile.player].add(adj)

            for tile in self._flipped_tiles:
                if tile.player == -1 and not tile.isMountain and not tile.isCity and tile.delta.discovered and tile not in alreadyRan:
                    alreadyRan.add(tile)
                    self.tile_discovered_neutral(tile)

            for tile in self._flipped_tiles:
                for adj in tile.adjacents:
                    if adj.player == -1 and not adj.isMountain and not adj.isCity and adj.delta.discovered and adj not in alreadyRan:
                        alreadyRan.add(adj)
                        self.tile_discovered_neutral(adj)

            if len(alreadyRan) > 0:
                with self.perf_timer.begin_move_event(f'gen re-limit for {len(alreadyRan)} alreadyRan'):
                    self.re_limit_gen_locations()

    def _limit_general_position_to_within_tile_and_distance(
            self,
            player: int,
            tile: Tile,
            maxDist: int,
            alsoIncreaseEmergence: bool = True,
            skipIfLongerThanExisting: bool = False,
            overrideCityPerfectInfo: bool | None = None,
            emergenceAmount: int = -1,
            bypass2v2Partner: bool = False):

        if not bypass2v2Partner and self.map.is_2v2:
            teammates = self.map.get_teammates_no_self(player)
            for teammate in teammates:
                if not self.map.players[teammate].dead:
                    allyMaxDist = maxDist + MAX_ALLY_SPAWN_DISTANCE
                    logbook.info(f'ALSO limiting ally {teammate} to distance {allyMaxDist} from {tile}')
                    self._limit_general_position_to_within_tile_and_distance(
                        teammate,
                        tile,
                        allyMaxDist,
                        alsoIncreaseEmergence,
                        skipIfLongerThanExisting,
                        overrideCityPerfectInfo,
                        emergenceAmount,
                        bypass2v2Partner=True,
                    )

        playerUnelim = self.uneliminated_emergence_events[player]
        existingLimit = playerUnelim.get(tile, None)

        if existingLimit is not None and existingLimit <= maxDist:
            if skipIfLongerThanExisting:
                logbook.info(f'bypassing {str(tile)} @ dist {maxDist} because it is longer or equal to existing limit for that tile at dist {existingLimit}')
                return

        if emergenceAmount == -1 and len(playerUnelim) == 0:
            emergenceAmount = max(20, 5000 / self.map.turn)
            # emergenceAmount = max(20, self.map.turn / 2)

        elims = self._limit_general_position_to_within_tiles_and_distance(player, [tile], maxDist, alsoIncreaseEmergence, overrideCityPerfectInfo=overrideCityPerfectInfo, emergenceAmount=emergenceAmount)
        shouldSave = elims > 0 or len(playerUnelim) < 3

        if shouldSave and (existingLimit is None or existingLimit > maxDist):
            logbook.info(f'including new elim p{player} {str(tile)} at dist {maxDist} which eliminated {elims}')
            playerUnelim[tile] = maxDist
            cityPerfectInfo = overrideCityPerfectInfo
            if cityPerfectInfo is None:
                cityPerfectInfo = self.has_perfect_information_of_player_cities(player)
            if cityPerfectInfo:
                self.uneliminated_emergence_event_city_perfect_info[player].add(tile)
            else:
                self.uneliminated_emergence_event_city_perfect_info[player].discard(tile)

        if elims > 0:
            self._check_over_elimination(player)

    def _limit_general_position_to_within_tiles_and_distance(self, player: int, tiles: typing.List[Tile], maxDist: int, alsoIncreaseEmergence: bool = True, overrideCityPerfectInfo: bool | None = None, emergenceAmount: int = -1, dontCountSwamps: bool = True) -> int:
        validSet = set()

        # ONLY USE FOR EMERGENCE
        launchDist = self.player_launch_timings[player] // 2 + 1
        launchDist = max(9, launchDist)
        emFactor = 50
        divOffset = 1

        if self.map.turn > 50:
            emFactor = 50
            divOffset = 3

        if emergenceAmount != -1 and self.map.turn > 50:
            emFactor = emergenceAmount * 3

        hasPerfectInfoOfPlayerCities = overrideCityPerfectInfo
        if hasPerfectInfoOfPlayerCities is None:
            hasPerfectInfoOfPlayerCities = self.has_perfect_information_of_player_cities(player)

        validPositions = self.valid_general_positions_by_player[player]
        emgMap = self.emergenceLocationMap[player]
        everOwned = self.tiles_ever_owned_by_player[player]

        if alsoIncreaseEmergence:
            def limiter(t: Tile, dist: int) -> bool:
                if validPositions.raw[t.tile_index]:
                    validSet.add(t.tile_index)
                    launchDistDiff = abs(launchDist - dist)
                    launchDistFactor = (divOffset + launchDistDiff)
                    launchEmergence = emFactor // launchDistFactor
                    emgMap.raw[t.tile_index] += launchEmergence
                if t.discoveredAsNeutral and t not in everOwned:  # and (t.visible or self.map.turn < 50)   # should be solved without the visible check by adding the lost-sight-ever-owned-by-player hack to allow pathing through the fog now.
                    return True
                if (t.isCostlyNeutralCity and (t.visible or hasPerfectInfoOfPlayerCities)) or t.isMountain or (t.isUndiscoveredObstacle and hasPerfectInfoOfPlayerCities) or t.isGeneral:
                    return True
                return False

        else:
            def limiter(t: Tile, dist: int) -> bool:
                if validPositions.raw[t.tile_index]:
                    validSet.add(t.tile_index)
                if t.discoveredAsNeutral and t not in everOwned:  # and (t.visible or self.map.turn < 50)   # should be solved without the visible check by adding the lost-sight-ever-owned-by-player hack to allow pathing through the fog now.
                    return True
                if (t.isCostlyNeutralCity and (t.visible or hasPerfectInfoOfPlayerCities)) or t.isMountain or (t.isUndiscoveredObstacle and hasPerfectInfoOfPlayerCities) or t.isGeneral:
                    return True
                return False

        starting = set()
        for tile in tiles:
            for movable in tile.movable:
                if movable.isObstacle:
                    continue
                starting.add(movable)

        if dontCountSwamps:
            SearchUtils.breadth_first_foreach_dist_fast_free_swamp_no_default_skip(
                self.map,
                [t for t in starting],
                maxDist - 1,
                limiter)
        else:
            SearchUtils.breadth_first_foreach_dist_fast_no_default_skip(
                self.map,
                [t for t in starting],
                maxDist - 1,
                limiter)

        if len(validSet) == 0:
            if BYPASS_TIMEOUTS_FOR_DEBUGGING:
                raise AssertionError('we produced an invalid general position restriction with 0 valid tiles.')
            else:
                logbook.error('we produced an invalid general position restriction with 0 valid tiles.')
                self._check_over_elimination(player)
                return 0

        elims = 0
        for t in self.map.tiles_by_index:
            if t.tile_index not in validSet and validPositions.raw[t.tile_index]:
                # logbook.info(f'elimin')
                elims += 1
                validPositions.raw[t.tile_index] = False
                if elims < 5:
                    logbook.info(f'elim {elims} was {str(t)} (will stop logging at 5)')

        return elims

    def _initialize_viable_general_positions(self):
        ourGens = [self.map.generals[self.map.player_index]]
        self.seen_player_lookup[self.map.player_index] = True
        for teammate in self.map.teammates:
            if self.map.generals[teammate] is not None:
                ourGens.append(self.map.generals[teammate])
            self.seen_player_lookup[teammate] = True

        for p in self.map.players:
            mm = self.valid_general_positions_by_player[p.index]

            if p.general is not None:
                mm.add(p.general)
                continue

            validTiles = self.map.valid_spawns
            if validTiles is None:
                validTiles = self.map.get_all_tiles()

            for tile in validTiles:
                if tile.isObstacle or tile.isCity:
                    continue

                if tile.visible:
                    continue

                if tile.discovered:
                    continue

                if tile.isSwamp:
                    continue

                if tile.isDesert:
                    continue

                mm.raw[tile.tile_index] = True

        for p, general in enumerate(self.map.generals):
            if general is None:
                continue

            distances = self.map.distance_mapper.get_tile_dist_matrix(general)

            for player in self.map.players:
                mm = self.valid_general_positions_by_player[player.index]
                if self.map.is_player_on_team_with(general.player, player.index):
                    mm.discard(general)
                    continue

                for tile in self.map.get_all_tiles():
                    dist = self.map.manhattan_dist(tile, general)

                    if dist < self.min_spawn_distance:  # spawns are manhattan distance
                        mm.discard(tile)
                        continue

                    if distances[tile] == 1000 and not self.map.is_custom_map:
                        mm.discard(tile)

    def find_territory_bisection_paths(self, targetPlayer: int) -> typing.Tuple[MapMatrixInterface[bool], MapMatrixInterface[int], typing.List[Path]]:
        bisectPaths = []

        bisectCandidates = MapMatrix(self.map, False)
        bisectDistances = MapMatrix(self.map, 100)

        # bfs from all known enemy tiles

        everPlayerTiles = self.tiles_ever_owned_by_player[targetPlayer]
        playerValid = self.valid_general_positions_by_player[targetPlayer]

        enemyBisectableStart = list(everPlayerTiles)

        def foreachFunc(t: Tile, d: int) -> bool:
            bisectDistances[t] = d

            if d > 3 and not t.discovered and playerValid[t]:
                bisectCandidates[t] = True

            if t.discoveredAsNeutral:
                return True  # dont bother routing through invisible stuff that can't be part of an original general constriction
            if t.visible and not t in everPlayerTiles:
                return True  # don't bother routing through visible stuff that was never theirs
            return False

        SearchUtils.breadth_first_foreach_dist(self.map, enemyBisectableStart, 150, foreachFunc)

        startTiles = {}
        for tile in self.map.players[self.map.player_index].tiles:
            startTiles[tile] = ((0, 100, 0, 0, None), 0)

        def valFunc(curTile, curPrio):
            (
                dist,
                negBisectDistAvg,
                negBisectDistSum,
                negBisects,
                fromTile
            ) = curPrio

            if dist == 0:
                return None

            return negBisects

        def prioFunc(nextTile, lastPrio):
            (
                dist,
                negBisectDistAvg,
                negBisectDistSum,
                negBisects,
                fromTile
            ) = lastPrio

            dist += 1
            if bisectCandidates[nextTile]:
                negBisectDistSum -= bisectDistances[nextTile]
                negBisects -= 1
                negBisectDistAvg = negBisectDistSum / dist

            return dist, negBisectDistAvg, negBisectDistSum, negBisects, nextTile

        def skipFuncDynamic(tile: Tile, prioObj):
            (
                dist,
                negBisectDistAvg,
                negBisectDistSum,
                negBisects,
                fromTile
            ) = prioObj
            if dist > 2 and tile.visible and not self.map.is_player_on_team_with(tile.player, targetPlayer):
                return True

            if not tile.discovered and not bisectCandidates[tile]:
                return True

            # if fromTile is not None:
            #     movingAwayFromUs = self.map.get_distance_between(self.general, tile) > self.map.get_distance_between(self.general, fromTile)
            #     movingAwayOrParallelToEn = self.map.get_distance_between(self.general, tile) > self.map.get_distance_between(self.general, fromTile)

        results = SearchUtils.breadth_first_dynamic_max_per_tile_global_visited(self.map, startTiles, valueFunc=valFunc, priorityFunc=prioFunc, skipFunc=skipFuncDynamic)

        logbook.info(f'BISECTOR FOUND {len(results)} BISECT PATHS...?')

        bestCandidates = HeapQueue()

        for startTile, resultPath in results.items():
            distance = resultPath.length
            bisectDistSum = 0
            bisects = 0
            for tile in resultPath.tileList:
                if bisectCandidates[tile]:
                    bisectDistSum += bisectDistances[tile]
                    bisects += 1

            logbook.info(f'bisect candidate bisects{bisects}, bisectDistSum{bisectDistSum}, {str(resultPath)}')

            if bisects == 0:
                continue

            bisectDistAvg = bisectDistSum / bisects

            bestCandidates.put((bisectDistAvg, resultPath))

        bannedTiles = set()
        while bestCandidates.queue:
            (avg, path) = bestCandidates.get()

            skip = False
            for tile in path.tileList:
                if tile in bannedTiles:
                    skip = True
                    break

            if skip:
                continue

            for tile in path.tileList:
                bannedTiles.add(tile)

            logbook.info(f'bisect included bisectAvg{avg}, {str(path)}')

            bisectPaths.append(path)

        return bisectCandidates, bisectDistances, bisectPaths

    def has_perfect_information_of_player_cities(self, player: int, overrideCities: int | None = None) -> bool:
        mapPlayer = self.map.players[player]
        realCities = where(mapPlayer.cities, lambda c: c.discovered)
        cityCount = overrideCities
        if cityCount is None:
            cityCount = mapPlayer.cityCount

        return len(realCities) >= cityCount - 1

    def try_split_fogged_army_back_into_fog(self, army: Army, trackingArmies: typing.Dict[Tile, Army]):
        potential = []
        for adj in army.tile.movable:
            if not adj.visible and not adj.isMountain and not adj.isUndiscoveredObstacle:
                potential.append(adj)

        self.armies.pop(army.tile, None)
        trackingArmies.pop(army.tile, None)

        if len(potential) > 1:
            logbook.info(f"    Army {str(army)} IS BEING ENTANGLED BACK INTO THE FOG (last seen {army.last_seen_turn})")
            entangledArmies = army.get_split_for_fog(potential)
            for i, fogBoi in enumerate(potential):
                logbook.info(
                    f"    Army {str(army)} entangled moved to {str(fogBoi)}")
                self._push_fogged_army_guess_back_to_fog_tile(entangledArmies[i], fogBoi, trackingArmies)

        elif len(potential) == 1:
            self._push_fogged_army_guess_back_to_fog_tile(army, potential[0], trackingArmies)

    def _push_fogged_army_guess_back_to_fog_tile(self, army: Army, fogTargetTile: Tile, trackingArmies: typing.Dict[Tile, Army]):
        self.fog_back_push_touched_tiles_this_turn.add(fogTargetTile)

        existingArmy = self.armies.get(fogTargetTile, None)
        if self.log_debug:
            logbook.info(
                f'FOG_BACK_PUSH_ATTEMPT turn={self.map.turn} moving={army} from={army.tile} target={fogTargetTile} '
                f'movingValue={army.value} movingEntangledValue={army.entangledValue} targetArmy={fogTargetTile.army} '
                f'targetPlayer={fogTargetTile.player} existing={existingArmy} '
                f'existingValue={existingArmy.value if existingArmy is not None else None} '
                f'existingEntangledValue={existingArmy.entangledValue if existingArmy is not None else None} '
                f'existingInMovingEntangled={existingArmy in army.entangledArmies if existingArmy is not None else None} '
                f'movingInExistingEntangled={army in existingArmy.entangledArmies if existingArmy is not None else None}')
        if existingArmy is not None:
            if existingArmy == army:
                existingArmy = None
            elif existingArmy in army.entangledArmies or army in existingArmy.entangledArmies:
                logbook.info(f"    Fog back-push discarded {str(army)} instead of moving into entangled army {str(existingArmy)}")
                existingArmy.last_moved_turn = self.map.turn - 1
                existingArmy.value = existingArmy.tile.army - 1
                if self.log_debug:
                    logbook.info(
                        f'FOG_PATH_TRACE_SET_LAST_MOVED turn={self.map.turn} context=fog_back_push_keep_existing '
                        f'army={existingArmy} tile={existingArmy.tile} value={existingArmy.value} '
                        f'newLastMoved={existingArmy.last_moved_turn} discardedArmy={army}')
                if self.log_debug:
                    logbook.info(
                        f'FOG_BACK_PUSH_ENTANGLED_COLLISION turn={self.map.turn} discarded={army} kept={existingArmy} '
                        f'keptTileArmy={existingArmy.tile.army} keptValueAfter={existingArmy.value} '
                        f'keptLastMoved={existingArmy.last_moved_turn}')
                self.scrap_army(army, scrapEntangled=False)
                return
            else:
                logbook.info(f"    Fog back-push discarded {str(army)} instead of merging into existing army {str(existingArmy)}")
                if self.log_debug:
                    logbook.info(
                        f'FOG_BACK_PUSH_EXISTING_COLLISION turn={self.map.turn} discarded={army} existing={existingArmy} '
                        f'existingTileArmy={existingArmy.tile.army} existingValue={existingArmy.value}')
                self.scrap_army(army, scrapEntangled=False)
                return

        oldTile = army.tile
        self.armies.pop(oldTile, None)
        trackingArmies.pop(oldTile, None)
        self.unaccounted_tile_diffs.pop(oldTile, None)
        self.unaccounted_tile_diffs.pop(fogTargetTile, None)

        if oldTile.visible:
            army.record_fog_tile_revert(oldTile)
            # NEVER modify visible tile army values
            # oldTile.army = max(1, oldTile.army)

        army.record_fog_tile_revert(fogTargetTile)
        if fogTargetTile.player != army.player and not fogTargetTile.discovered:
            fogTargetTile.isTempFogPrediction = True
        if fogTargetTile.player != army.player and not fogTargetTile.isGeneral:
            oldPlayer = self.map.players[fogTargetTile.player]
            if fogTargetTile in oldPlayer.tiles:
                oldPlayer.tiles.remove(fogTargetTile)
            if fogTargetTile not in self.map.players[army.player].tiles:
                self.map.players[army.player].tiles.append(fogTargetTile)
            fogTargetTile.player = army.player

        fogTargetTile.army = max(1, army.value + 1)
        army.update_tile(fogTargetTile)
        army.value = fogTargetTile.army - 1
        army.last_moved_turn = self.map.turn - 1
        if self.log_debug:
            logbook.info(
                f'FOG_PATH_TRACE_SET_LAST_MOVED turn={self.map.turn} context=fog_back_push_move '
                f'army={army} tile={army.tile} value={army.value} newLastMoved={army.last_moved_turn}')
        trackingArmies[fogTargetTile] = army
        self.armies[fogTargetTile] = army
        if self.log_debug:
            logbook.info(
                f'FOG_BACK_PUSH_MOVED turn={self.map.turn} army={army} oldTile={oldTile} target={fogTargetTile} '
                f'oldTileArmyAfter={oldTile.army} targetArmyAfter={fogTargetTile.army} valueAfter={army.value} '
                f'lastMoved={army.last_moved_turn}')
        for listener in self.notify_army_moved:
            listener(army)

    def update_track_threshold(self):
        tilesRankedByArmy = list(sorted(where(self.map.pathable_tiles, filter_func=lambda t: t.player != -1), key=lambda t: t.army))
        percentile = 96
        percentileIndex = percentile * len(tilesRankedByArmy) // 100
        tileAtPercentile = tilesRankedByArmy[percentileIndex]
        if tileAtPercentile.army - 1 > self.track_threshold:
            newTrackThreshold = tileAtPercentile.army - 1
            logbook.info(f'RAISING TRACK THRESHOLD FROM {self.track_threshold} TO {newTrackThreshold}')
            self.track_threshold = newTrackThreshold

    def _move_fogged_army_along_path(self, army: Army, path: Path | None, armyAlreadyPopped: bool = False):
        if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(f'FOG DEBUG: _move_fogged_army_along_path called for army {str(army)} path {str(path)}')

        isCompletePath = (
            path is None
            or path.start is None
            or path.start.next is None
            or path.start.next.tile is None
        )

        if isCompletePath:
            try:
                army.expectedPaths.remove(path)
            except:
                pass

        if isCompletePath or path.start.next.tile.visible:
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_STOP turn={self.map.turn} army={army} isCompletePath={isCompletePath} '
                    f'nextVisible={False if isCompletePath else path.start.next.tile.visible} '
                    f'tile={army.tile} tileArmyBefore={army.tile.army} valueBefore={army.value}')
            army.value = army.tile.army - 1
            if self.log_debug:
                logbook.info(f'FOG_PATH_STOP_VALUE_UPDATE turn={self.map.turn} army={army} valueAfter={army.value}')
            # Tests/test_ArmyTracker.py::ArmyTrackerTests::test_should_not_shuffle__lose__or_duplicate_fog_armies_when_pushing_them_back_into_the_fog covers an entangled fog army that collides with a sibling and then stops on a visible path, leaving its old tile with army=1. That stopped zero-value tracker is not a real army and must not remain tracked.
            if army.value <= 0:
                self.scrap_army(army, scrapEntangled=False)

            return

        nextTile = path.start.next.tile
        if self.log_debug:
            logbook.info(
                f'FOG_PATH_MOVE_ATTEMPT turn={self.map.turn} army={army} from={army.tile} to={nextTile} '
                f'value={army.value} entangledValue={army.entangledValue} oldTileArmy={army.tile.army} '
                f'nextTileArmy={nextTile.army} nextTilePlayer={nextTile.player} path={path}')
        if not nextTile.visible:
            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Moving army {str(army)} from {army.tile} to fog tile {nextTile}')
                logbook.info(f'FOG DEBUG: Before move - army.value={army.value}, army.tile.army={army.tile.army}, nextTile.army={nextTile.army}, nextTile.player={nextTile.player}')

            # CRITICAL FIX: Prevent army from moving into its own tile, which causes duplication
            if nextTile == army.tile:
                if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                    logbook.info(f'FOG DEBUG: Army {str(army)} trying to move into its own tile {nextTile}, SKIPPING to prevent duplication')
                return

            try:
                existingArmy = self.armies[nextTile]
            except KeyError:
                existingArmy = None
            if existingArmy is not None and existingArmy == army:
                existingArmy = None

            if existingArmy is not None and DebugHelper.IS_DEBUGGING:
                logbook.info(f'FOG DEBUG: Found existing army at destination: {str(existingArmy)}')
            # if existingArmy is not None and army in existingArmy.entangledArmies:
            #     logbook.info(
            #         f"Refusing to move army {str(army)} into entangled brother {str(existingArmy)}")
            #     # do nothing
            #     return

            if not armyAlreadyPopped:
                self.armies.pop(army.tile, None)

            logbook.info(
                f"Moving fogged army {str(army)} along expected path {str(path)}")

            oldTile = army.tile
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_OLD_TILE_CLEAR turn={self.map.turn} army={army} oldTile={oldTile} '
                    f'oldTileArmyBefore={oldTile.army} cityBonus={self.map.is_city_bonus_turn} armyBonus={self.map.is_army_bonus_turn}')
            army.record_fog_tile_revert(oldTile)
            army.record_fog_tile_revert(nextTile)
            # NEVER modify visible tile army values
            if not oldTile.visible:
                oldTile.army = 1
                if self.map.is_city_bonus_turn and oldTile.isCity or oldTile.isGeneral:
                    oldTile.army += 1
                if self.map.is_army_bonus_turn:
                    oldTile.army += 1
            if self.log_debug:
                logbook.info(f'FOG_PATH_OLD_TILE_CLEARED turn={self.map.turn} army={army} oldTile={oldTile} oldTileArmyAfter={oldTile.army}')

            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Updated old tile {oldTile} army to {oldTile.army}')

            if existingArmy is not None:
                if existingArmy in army.entangledArmies:
                    logbook.info(f'entangled army collided with itself, scrapping the collision-mover {str(army)} in favor of {str(existingArmy)}')
                    existingArmy.last_moved_turn = self.map.turn - 1
                    existingArmy.value = existingArmy.tile.army - 1
                    if self.log_debug:
                        logbook.info(
                            f'FOG_PATH_TRACE_SET_LAST_MOVED turn={self.map.turn} context=fog_path_keep_existing '
                            f'army={existingArmy} tile={existingArmy.tile} value={existingArmy.value} '
                            f'newLastMoved={existingArmy.last_moved_turn} discardedArmy={army}')
                    if self.log_debug:
                        logbook.info(
                            f'FOG_PATH_ENTANGLED_COLLISION turn={self.map.turn} discarded={army} kept={existingArmy} '
                            f'keptTileArmy={existingArmy.tile.army} keptValueAfter={existingArmy.value} '
                            f'keptLastMoved={existingArmy.last_moved_turn}')
                    self.scrap_army(army, scrapEntangled=False)
                    if self.log_debug:
                        logbook.info(
                            f'FOG_PATH_ENTANGLED_COLLISION_AFTER_SCRAP turn={self.map.turn} discarded={army} '
                            f'discardedScrapped={army.scrapped} discardedTile={army.tile} discardedValue={army.value} '
                            f'kept={existingArmy} keptTile={existingArmy.tile} keptValue={existingArmy.value}')
                    return

            # if not oldTile.discovered:
            #     oldTile.player = -1
            #     oldTile.army = 0
            # NEVER modify visible tile army values
            if not nextTile.visible:
                if nextTile.player == army.player:
                    if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                        logbook.info(f'FOG DEBUG: nextTile {nextTile} belongs to same player, adding {army.value} to existing {nextTile.army}')
                    if self.log_debug:
                        logbook.info(
                            f'FOG_PATH_SAME_PLAYER_ADD turn={self.map.turn} army={army} nextTile={nextTile} '
                            f'nextTileArmyBefore={nextTile.army} addingValue={army.value} existingArmy={existingArmy}')
                    nextTile.army = nextTile.army + army.value
                else:
                    if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                        logbook.info(f'FOG DEBUG: nextTile {nextTile} belongs to enemy {nextTile.player}, subtracting {army.value} from existing {nextTile.army}')
                    if self.log_debug:
                        logbook.info(
                            f'FOG_PATH_DIFFERENT_PLAYER_SUB turn={self.map.turn} army={army} nextTile={nextTile} '
                            f'nextTileArmyBefore={nextTile.army} subtractingValue={army.value} nextTilePlayerBefore={nextTile.player}')
                    if nextTile.player != army.player and not nextTile.discovered:
                        nextTile.isTempFogPrediction = True
                    nextTile.army = nextTile.army - army.value
                if nextTile.army < 0:
                    nextTile.army = 0 - nextTile.army
                if not nextTile.isGeneral:
                    nextTile.player = army.player

            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Updated next tile {nextTile} army to {nextTile.army}, player to {nextTile.player}')

            if existingArmy is not None:
                if existingArmy.player == army.player:
                    if existingArmy.value > army.value:
                        self.merge_armies(existingArmy, army, nextTile)
                    else:
                        self.merge_armies(army, existingArmy, nextTile)
                    return

            army.update_tile(nextTile)
            army.value = nextTile.army - 1
            if self.log_debug:
                logbook.info(
                    f'FOG_PATH_MOVE_COMPLETE turn={self.map.turn} army={army} oldTile={oldTile} nextTile={nextTile} '
                    f'oldTileArmyAfter={oldTile.army} nextTileArmyAfter={nextTile.army} valueAfter={army.value}')
            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Final army update - army {str(army)} now at {army.tile} with value {army.value}')
            self.armies[nextTile] = army
            path.remove_start()
            if self.log_debug and DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
                logbook.info(f'FOG DEBUG: Completed fog army movement for {str(army)}')
            return

    def try_find_army_sink(
            self,
            player: int,
            annihilatedFogArmy: int,
            tookNeutCity: bool
    ):
        """
        Tries to find a fog army sink for fog annihilation, and optionally converts it into a neutral city if the player just took one.

        @param player:
        @param annihilatedFogArmy:
        @param tookNeutCity:

        @return:
        """

        possibleArmies = []
        for army in self.armies.values():
            if army.player != player:
                continue
            if army.visible:
                continue

            possibleArmies.append(army)

        possibleArmies = list(sorted(possibleArmies, key=lambda a: abs(annihilatedFogArmy - a.value - 1) + self.map.get_distance_between(self.general, a.tile)))

        # likelyArmy = None

        for (fromRange, toRange) in [
            (0, 5),
            (5, 9),
            (9, 15),
        ]:
            for army in possibleArmies:
                seenAgo = self.map.turn - army.last_seen_turn
                if seenAgo >= toRange:
                    continue
                if seenAgo < fromRange:
                    continue
                if tookNeutCity:
                    cutoff = min(14, 1 + seenAgo)
                    logbook.info(f"try_find_army_sink FINDING NEXT FOG CITY FOR PLAYER {player} for not-fog-city tile {str(army.tile)} (dist {cutoff})")
                    potentialCity = self.find_next_fog_city_candidate_near_tile(player, army.tile, cutoffDist=cutoff)
                    if potentialCity is not None:
                        self.convert_fog_city_to_player_owned(potentialCity, player)
                        split = army.get_split_for_fog([army.tile, potentialCity])
                        ogArmySplit = split[0]
                        # likelyArmy = ogArmySplit
                        self.armies[army.tile] = ogArmySplit
                        army = split[1]
                        # army.tile.army = army.value + 1
                        army.path = Path()
                        army.update_tile(potentialCity)
                        potentialCity.army = max(1, army.value - annihilatedFogArmy)
                        army.value = max(0, army.value - annihilatedFogArmy)
                        army.tile.army = army.value + 1
                        for entangled in army.entangledArmies:
                            entangled.value = max(0, entangled.value - annihilatedFogArmy)
                            entangled.tile.army = entangled.value + 1
                        if self.log_debug:
                            logbook.info(
                                f'EXPECTED_PATH_DEBUG_CALL context=army_sink turn={self.map.turn} army={army} '
                                f'tile={army.tile} value={army.value} tileArmy={army.tile.army} '
                                f'visible={army.tile.visible} discovered={army.tile.discovered}')
                        army.expectedPaths = ArmyTracker.get_army_expected_path(self.map, army, self.general, self.player_targets, log_debug=self.log_debug)
                        self.armies[army.tile] = army
                        army.last_moved_turn = self.map.turn

                        return True

                    logbook.info(f"try_find_army_sink did not find fog city for {str(army.tile)}, reducing army by {annihilatedFogArmy} anyway.")
                    self._reduce_army_sink_for_fog_annihilation(army, annihilatedFogArmy)
                    return True

                else:
                    # likelyArmy = army
                    self._reduce_army_sink_for_fog_annihilation(army, annihilatedFogArmy)
                    return True

        return False

    def _reduce_army_sink_for_fog_annihilation(
            self,
            army: Army,
            annihilatedFogArmy: int
    ):
        army.value -= annihilatedFogArmy
        if army.value < 0:
            army.value = 0
        army.tile.army = army.value + 1
        for entangled in army.entangledArmies:
            entangled.value = max(0, entangled.value - annihilatedFogArmy)
            entangled.tile.army = entangled.value + 1

    def _inc_slash_dec_fog_prediction_to_get_player_tile_count_right(
            self,
            playerIndex: int,
            playerExpectedFogTileCounts: typing.Dict[int, int],
            predictedGeneralLocation: Tile | None
    ):
        player = self.map.players[playerIndex]
        tileDiff = player.tileCount - len(player.tiles)

        # we should already have moved any fogged armies adjacent to neutrals for capture, I think? So if this is positive, we can't use fog armies for that...?
        if tileDiff > 0:
            with self.perf_timer.begin_move_event(f'ArmyTracker ++{tileDiff} fog land {playerIndex}'):
                playerExpectedFogTileCounts = playerExpectedFogTileCounts.copy()
                for tile in player.tiles:
                    if tile.visible:
                        continue
                    curCount = playerExpectedFogTileCounts.get(tile.army, None)
                    if curCount is None:
                        continue
                    if curCount > 1:
                        playerExpectedFogTileCounts[tile.army] = curCount - 1
                    else:
                        del playerExpectedFogTileCounts[tile.army]

                connectedTiles = set(t for t in player.tiles)
                setTilesToConvert = set()
                tempPredictions = self._fill_land_from_connected_tiles_for_player(
                    playerIndex,
                    set(),
                    connectedDark=set(t for t in connectedTiles if not t.visible),
                    connectedTiles=connectedTiles,
                    numStartTilesToFill=0,
                    numTilesToFillIn=tileDiff,
                    ourGen=self.general,
                    pathToPotentialEnGeneral=None,
                    playerExpectedFogTileCounts=playerExpectedFogTileCounts,
                    outputTilesToBeConverted=setTilesToConvert)
                self.map.players[player.index].tiles.extend(tempPredictions)

        elif tileDiff < 0:
            with self.perf_timer.begin_move_event(f'ArmyTracker -{tileDiff} fog land {playerIndex}'):
                # playerExpectedFogTileCounts = playerExpectedFogTileCounts.copy()
                # for tile in player.tiles:
                #     if tile.visible:
                #         continue
                #     curCount = playerExpectedFogTileCounts.get(tile.army, None)
                #     if curCount is None:
                #         continue
                #     if curCount > 1:
                #         playerExpectedFogTileCounts[tile.army] = curCount - 1
                #     else:
                #         del playerExpectedFogTileCounts[tile.army]

                removable = HeapQueue()
                for tile in player.tiles:
                    if tile.isTempFogPrediction:
                        removable.put((0 - self.map.distance_mapper.get_distance_between(self.general, tile), tile))

                while tileDiff < 0 and removable.queue:
                    (negDist, tile) = removable.get()
                    self.reset_temp_tile_marked(tile)
                    tileDiff += 1

                    self.map.players[player.index].tiles.remove(tile)

    def _build_fog_prediction_internal(
            self,
            player: int,
            playerExpectedFogTileCounts: typing.Dict[int, int],
            predictedGeneralLocation: Tile | None
    ):
        playerObj = self.map.players[player]
        if playerObj.dead:
            return

        ourGen = self.map.generals[self.map.player_index]
        bannedTiles, connectedTiles, coreConnected, pathToUnelim = self.get_fog_connected_based_on_emergences(player, predictedGeneralLocation)
        self.connectedByPlayer[player] = connectedTiles
        self.coreConnectedByPlayer[player] = coreConnected
        if len(coreConnected) == 0 and predictedGeneralLocation is not None:
            coreConnected.add(predictedGeneralLocation)
            connectedTiles.add(predictedGeneralLocation)

        keep = []
        for tile in playerObj.tiles:
            if tile.isTempFogPrediction and not tile.discovered and tile not in self.armies and not tile.isGeneral and not tile.isCity:
                self.map.reset_wrong_undiscovered_fog_guess(tile)
            else:
                keep.append(tile)
                if not tile.visible:
                    amt = playerExpectedFogTileCounts.get(tile.army, 0)
                    if amt > 0:
                        # reduce the expected fog counts by any tiles that we're keeping.
                        playerExpectedFogTileCounts[tile.army] = amt - 1

        self.map.players[player].tiles = keep

        tilesToConvertToTempPlayer = set()

        numTilesToFillIn = self.map.players[player].tileCount - len(self.map.players[player].tiles)

        connectedDark = [t for t in connectedTiles if not t.visible or SearchUtils.any_where(t.movable, lambda m: not m.visible)]

        numStartTilesToFill = min(numTilesToFillIn, 24) - len(connectedDark)

        with self.perf_timer.begin_move_event(f'ArmyTracker fill land p{player}'):
            tempPredictions = self._fill_land_from_connected_tiles_for_player(player, bannedTiles, connectedDark, connectedTiles, numStartTilesToFill, numTilesToFillIn, ourGen, pathToUnelim, playerExpectedFogTileCounts, tilesToConvertToTempPlayer)

        self.map.players[player].tiles.extend(tempPredictions)

    def get_fog_connected_based_on_emergences(
            self,
            player: int,
            predictedGeneralLocation,
            additionalRequiredTiles: typing.Iterable[Tile] | None = None
    ) -> typing.Tuple[MapMatrixSet, TileSet, TileSet, Path | None]:
        """
        Returns bannedTiles, connectedSet, coreConnectedSet, pathToClosestUneliminatedGenPosition
        @param player:
        @param predictedGeneralLocation:
        @param additionalRequiredTiles:
        @return:
        """
        tilesEverOwned = self.tiles_ever_owned_by_player[player]
        uneliminated = self.uneliminated_emergence_events[player]
        unrecapturedEmergenceEvents: typing.Set[Tile] = self.unrecaptured_emergence_events[player]
        validGenSpots = self.valid_general_positions_by_player[player]
        teamStats = self.map.get_team_stats(player)
        perfectInfo = teamStats.cityCount == len(teamStats.teamPlayers)
        bannedTiles = MapMatrixSet(self.map)
        for tile in self.map.get_all_tiles():
            if (tile.discoveredAsNeutral or tile.visible) and tile not in uneliminated and tile not in unrecapturedEmergenceEvents and tile not in tilesEverOwned:
                bannedTiles.add(tile)
                # logbook.info(f'BANNING {tile} because if (tile.discoveredAsNeutral {tile.discoveredAsNeutral} or tile.visible {tile.visible}) and tile not in uneliminated {tile not in uneliminated} and tile not in unrecapturedEmergenceEvents {tile not in unrecapturedEmergenceEvents} and tile not in tilesEverOwned {tile not in tilesEverOwned}')
            elif tile.isObstacle and perfectInfo:
                bannedTiles.add(tile)
                # logbook.info(f'BANNING {tile} because obstacle and perfectInfo')

        requiredTiles = []
        requiredIncluded = set()
        for tile in uneliminated.keys():
            # if not SearchUtils.any_where(tile.movable, lambda t: not t.visible):
            #     continue
            if tile not in requiredIncluded:
                requiredIncluded.add(tile)
                requiredTiles.append(tile)

        for tile in unrecapturedEmergenceEvents:
            if tile not in requiredIncluded:
                requiredIncluded.add(tile)
                requiredTiles.append(tile)

        if additionalRequiredTiles is not None:
            for t in additionalRequiredTiles:
                if t not in requiredIncluded:
                    requiredIncluded.add(t)
                    requiredTiles.append(t)
        # I think this is messing stuff up
        if len(requiredIncluded) == 0:
            for tile in tilesEverOwned:
                if tile.isNotPathable:
                    continue
                if not SearchUtils.any_where(tile.movable, lambda t: not t.visible):
                    continue
                requiredIncluded.add(tile)
                requiredTiles.append(tile)

        # # find the closest un-eliminated valid general location:
        # pathToUnelim = SearchUtils.breadth_first_find_queue(self.map, requiredTiles, lambda t, _1, _2: validGenSpots[t], noNeutralCities=True)
        # if pathToUnelim is not None and pathToUnelim.tail.tile not in requiredIncluded:
        #     requiredIncluded.add(pathToUnelim.tail.tile)
        #     requiredTiles.append(pathToUnelim.tail.tile)
        # if len(requiredTiles) == 0:
        #     logbook.warning(f'ArmyTracker found no tiles to build fog land from for player {player}')
        #     return
        with self.perf_timer.begin_move_event(f'Fog land build get_spanning_tree_set_from_tile_lists p{player} (num required {len(requiredTiles)})'):
            connectedSet, missingRequired = MapSpanningUtils.get_spanning_tree_set_from_tile_lists(self.map, requiredTiles, bannedTiles)
            # connectedTiles = [t for t in connectedSet]
            self.unconnectable_tiles[player] = missingRequired
            coreConnected = MapSpanningUtils.trim_spanning_tree_ends_as_new_set(toTrim=connectedSet, trimDepth=5, minRemainingCount=int(0.49 + len(connectedSet) / 3))
        # with self.perf_timer.begin_move_event(f'ArmyTracker build_network_x_steiner_tree p{player} (num banned {len(bannedTileList)}, required {len(requiredTiles)})'):
        #     connectedTiles = GatherSteiner.build_network_x_steiner_tree(self.map, requiredTiles, bannedTiles=bannedTiles)
        self.player_connected_tiles[player] = connectedSet
        # TODO this was just bad, why did I add it?
        # if self.map.players[player].cityCount == 1:
        #     with self.perf_timer.begin_move_event(f'Fog land build add_emergence_around_minimum_connected_tree p{player}'):
        #         self.add_emergence_around_minimum_connected_tree(connectedTiles, requiredTiles, player)
        with self.perf_timer.begin_move_event(f'Fog land build connecting to valid gen spawn p{player}'):
            pathToUnelim: Path | None = None
            if predictedGeneralLocation is not None:
                if predictedGeneralLocation not in connectedSet:
                    pathToUnelim = SearchUtils.breadth_first_find_queue(
                        self.map,
                        [predictedGeneralLocation],
                        lambda t, _1, _2: t in connectedSet,
                        noNeutralCities=True,
                        skipTiles=bannedTiles,
                        noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2

                # find the closest un-eliminated valid general location:
                if pathToUnelim is None:
                    pathToUnelim = SearchUtils.breadth_first_find_queue(
                        self.map,
                        [t for t in validGenSpots],
                        lambda t, _1, _2: t in connectedSet,
                        noNeutralCities=True,
                        skipTiles=bannedTiles,
                        noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2

            if pathToUnelim is not None:
                pathToUnelim = pathToUnelim.get_reversed()
                for tile in pathToUnelim.tileList:
                    if tile not in connectedSet:
                        connectedSet.add(tile)
                # TODO stop logging bannedTiles super expensive
                logbook.info(f'found pathToUnelim {pathToUnelim}, resulting in {len(connectedSet)} connectedSet tiles') #and bannedTiles ({bannedTiles})')
            else:
                logbook.warning(f'no pathToUnelim to p{player} spawn found!?')

        self._connect_discovered_enemy_land_connector_tiles(player, connectedSet, bannedTiles)
        coreConnected = MapSpanningUtils.trim_spanning_tree_ends_as_new_set(toTrim=connectedSet, trimDepth=5, minRemainingCount=int(0.49 + len(connectedSet) / 3))

        return bannedTiles, connectedSet, coreConnected, pathToUnelim

    def _connect_discovered_enemy_land_connector_tiles(
            self,
            player: int,
            connectedSet: typing.Set[Tile],
            bannedTiles: TileSet
    ):
        for tile in list(self.discovered_enemy_land_connector_tiles[player]):
            if tile.player != player or not SearchUtils.any_where(tile.movable, lambda t: not t.visible):
                self.discovered_enemy_land_connector_tiles[player].discard(tile)
                continue
            if tile in connectedSet or len(connectedSet) == 0:
                continue

            pathToConnectedLand = SearchUtils.breadth_first_find_queue(
                self.map,
                [tile],
                lambda t, _1, _2: t in connectedSet,
                noNeutralCities=True,
                skipTiles=bannedTiles,
                noLog=True)
            if pathToConnectedLand is None:
                continue

            for pathTile in pathToConnectedLand.tileList:
                if pathTile not in connectedSet:
                    connectedSet.add(pathTile)

    def _fill_land_from_connected_tiles_for_player(
            self,
            player: int,
            bannedTiles,
            connectedDark,
            connectedTiles,
            numStartTilesToFill,
            numTilesToFillIn,
            ourGen,
            pathToPotentialEnGeneral,
            playerExpectedFogTileCounts,
            outputTilesToBeConverted
    ) -> typing.List[Tile]:
        """
        Returns temp prediction tiles

        @param bannedTiles:
        @param connectedDark: ConnectedTiles that are not visible or have a not visible movable, and are part of the required connection plan (?)
        @param connectedTiles: The spanning tree built from connection points (emergences and discoveries).
        @param numStartTilesToFill: Num tiles near enemy general (pathToUnelim tail) to fill in specifically, since the tiles shouldn't actually be evenly distributed near our land
        @param numTilesToFillIn: Num tiles to fill in in total
        @param ourGen:
        @param pathToPotentialEnGeneral:
        @param playerExpectedFogTileCounts: The expected number of tiles of each tile value the opponent should have in the fog, per the opponentTracker fog tracker.
        @param outputTilesToBeConverted:
        @return:
        """
        secondIterConnected = connectedTiles.copy()
        if pathToPotentialEnGeneral is not None:
            secondIterConnected.update(pathToPotentialEnGeneral.tileList)
        if pathToPotentialEnGeneral is not None:
            # this ban makes it so we don't try to double-fill the connectedDark tiles. These can be pathed through but wont be converted.
            nearGenBan = bannedTiles.copy()
            for t in connectedDark:
                nearGenBan.add(t)

            approxEnGen = pathToPotentialEnGeneral.tail.tile

            numMissingCities = self.get_team_missing_city_count_by_player(player)
            # < 30 because if they have basically ALL the cities then we'll just flood-fill their cities with the land-filler, instead..
            while 0 < numMissingCities < 20:
                cutoffDist = max(1, min(10, numStartTilesToFill - len(outputTilesToBeConverted) - numMissingCities))
                logbook.info(f"_fill_land_from_connected_tiles_for_player FINDING NEXT FOG CITY FOR PLAYER {player} for not-fog-city tile {str(approxEnGen)} (dist {cutoffDist}, missing remaining {numMissingCities})")
                potCity = self.find_next_fog_city_candidate_near_tile(player, approxEnGen, cutoffDist=cutoffDist, distanceWeightReduction=5, wallBreakWeight=4, emergenceWeight=1.0)
                if potCity is None:
                    break
                numMissingCities -= 1
                outputTilesToBeConverted.add(potCity)
                logbook.info(f'setting fog city {potCity} to be player owned in _fill_land_from_connected_tiles_for_player. Connecting it.')
                self.determine_tiles_to_fill_in(outputTilesToBeConverted, nearGenBan, outputTilesToBeConverted, numStartTilesToFill + 1)  # +1 because the final tile is already part of our connected set

            # here we make sure our connected tiles also connect to the enemy general
            nearGenBan.discard(pathToPotentialEnGeneral.tail.tile)
            self.determine_tiles_to_fill_in([approxEnGen], nearGenBan, outputTilesToBeConverted, numStartTilesToFill + 1)  # +1 because the final tile is already part of our connected set
            # we want to start our second whole expansiony thingy from these new tiles, too, because probably they've expanded backwards some.
            secondIterConnected = list(itertools.chain.from_iterable([connectedTiles, outputTilesToBeConverted]))

        self.determine_tiles_to_fill_in(secondIterConnected, bannedTiles, outputTilesToBeConverted, numTilesToFillIn)
        currentTileAmount = SearchUtils.Counter(1)
        if len(playerExpectedFogTileCounts) > 0:
            currentTileAmount.value = max(playerExpectedFogTileCounts.keys())
        if len(playerExpectedFogTileCounts) == 0:
            playerExpectedFogTileCounts[1] = 1
        tileAmountLeft = SearchUtils.Counter(playerExpectedFogTileCounts[currentTileAmount.value])
        tempPredictions = []
        overwriteArmyThresh = self.track_threshold // 2 + 1

        updateReachable = [False]

        def foreachConverterFunc(tile: Tile, dist: int):
            if tile.visible:
                return

            if tile.army > overwriteArmyThresh:
                return

            if tile.isGeneral or tile.isCostlyNeutralCity:
                return

            if tile not in outputTilesToBeConverted:
                return tile.isObstacle

            tile.isTempFogPrediction = True
            tempPredictions.append(tile)
            tile.army = currentTileAmount.value
            tileAmountLeft.value -= 1
            while tileAmountLeft.value <= 0 and currentTileAmount.value > 1:
                currentTileAmount.value -= 1
                tileAmountLeft.value = playerExpectedFogTileCounts.get(currentTileAmount.value, 0)

            tile.player = player
            if tile.isUndiscoveredObstacle or (tile.isCity and tile.player == -1):
                logbook.info(f'UPDATING REACHABLE BECAUSE OF {tile} IN _fill_land_from_connected_tiles_for_player')
                self.convert_fog_city_to_player_owned(tile, player)
                updateReachable[0] = True

        # aInFinal = self.map.GetTile(8, 12) in tempPredictions
        # bInFinal = self.map.GetTile(8, 11) in tempPredictions
        # aInToConvert = self.map.GetTile(8, 12) in tilesToConvertToTempPlayer
        # bInToConvert = self.map.GetTile(8, 11) in tilesToConvertToTempPlayer
        #
        # aInPath = self.map.GetTile(8, 12) in pathToUnelim.tileSet
        # bInPath = self.map.GetTile(8, 11) in pathToUnelim.tileSet
        #
        # aInConnectedDark = self.map.GetTile(8, 12) in connectedDark
        # bInConnectedDark = self.map.GetTile(8, 11) in connectedDark
        SearchUtils.breadth_first_foreach_dist_fast_incl_neut_cities(self.map, self.map.players[self.map.player_index].tiles, maxDepth=250, foreachFunc=foreachConverterFunc)
        if updateReachable[0]:
            self.map.update_reachable()

        return tempPredictions

    def get_team_missing_city_count_by_player(self, player: int) -> int:
        """
        Gets the number of cities the players TEAM has that we have never had vision of yet (so basically the number of undiscovered obstacles that are cities).
        Excludes fog-guess cities.

        @param player:
        @return:
        """
        unkCount = 0
        for pIdx in self.map.get_teammates(player):
            p = self.map.players[pIdx]
            if p.dead:
                continue
            # general doesn't count
            unkCount += p.cityCount - 1 - len(p.cities)

        return max(0, unkCount)

    def determine_tiles_to_fill_in(
            self,
            connectedDark: typing.Iterable[Tile],
            bannedTiles: typing.Set[Tile],
            tilesToConvertToAddTo: typing.Set[Tile],
            numTilesToFillIn: int,
            # tilesToPathButNotInclude: typing.Set[Tile]
    ):
        beforeCount = len(tilesToConvertToAddTo)
        connectedDarkList = list(connectedDark)
        preseededConnectedDark = 0
        skips = set(bannedTiles)
        skips.difference_update(connectedDarkList)
        for tile in connectedDarkList:
            if not tile.discovered and tile.player == -1:
                tilesToConvertToAddTo.add(tile)
                preseededConnectedDark += 1

        numFillTilesNeeded = numTilesToFillIn
        bannedCount = sum(1 for _ in bannedTiles)
        logbook.info(
            f'FOG_DETERMINE_START turn={self.map.turn} connectedDark={len(connectedDarkList)} banned={bannedCount} '
            f'before={beforeCount} preseeded={preseededConnectedDark} afterPreseed={len(tilesToConvertToAddTo)} '
            f'numFillTilesNeeded={numFillTilesNeeded}')
        deferredVisionEdgeTileSet: typing.Set[Tile] = set()
        deferVisionBaseline: typing.Set[Tile] = set()

        def deferForeach(t: Tile):
            if not t.visible and t in skips:
                return True
            if t.player != -1 and t.visible and (not t.discoveredAsNeutral or self.map.team_ids_by_player_index[t.player] != self.map.friendly_team):
                return True
            deferVisionBaseline.add(t)
            return False

        SearchUtils.breadth_first_foreach_fast_no_neut_cities(self.map, self.map.players[self.map.player_index].tiles, 5, deferForeach)

        def is_vision_edge_tile(tile: Tile) -> bool:
            return tile in deferVisionBaseline

        def add_deferred_vision_edge_tiles_if_needed():
            for deferredTile in deferredVisionEdgeTileSet:
                if len(tilesToConvertToAddTo) >= numFillTilesNeeded:
                    return
                tilesToConvertToAddTo.add(deferredTile)

        def findFunc(tile: Tile, army: float, dist: int) -> bool:
            if len(tilesToConvertToAddTo) >= numFillTilesNeeded:
                return True

            if tile.player == -1 and tile not in tilesToConvertToAddTo and not tile.isSwamp:
                if is_vision_edge_tile(tile):
                    if tile not in deferredVisionEdgeTileSet and tile not in connectedDark:
                        deferredVisionEdgeTileSet.add(tile)
                    return False
                tilesToConvertToAddTo.add(tile)

            return False

        # TODO add breadth_first_foreach_terminating and use that instead so we dont waste time building unused paths in exchange for not fully looping
        fakePath = SearchUtils.breadth_first_find_queue(self.map, connectedDarkList, findFunc, skipTiles=skips, noNeutralCities=True, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        add_deferred_vision_edge_tiles_if_needed()
        if fakePath is None:
            if len(tilesToConvertToAddTo) < numFillTilesNeeded:
                logbook.error(f'unable to fill the requested {numFillTilesNeeded} numTilesToFillIn {numTilesToFillIn} tiles from {connectedDarkList}, (skips {skips}) allowing neutral cities...?')
                fakePath = SearchUtils.breadth_first_find_queue(self.map, connectedDarkList, findFunc, skipTiles=skips, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
                add_deferred_vision_edge_tiles_if_needed()
            if fakePath is None and len(tilesToConvertToAddTo) < numFillTilesNeeded:
                # then we couldn't fully build the set?
                conDark = set(connectedDarkList)
                logbook.error(f'unable to fully build {numFillTilesNeeded} numFillTilesNeeded, {numTilesToFillIn} numTilesToFillIn the set of tiles...? '
                              f'\r\n{len(tilesToConvertToAddTo)} tilesToConvertToAddTo ({tilesToConvertToAddTo})'
                              f'\r\n{len(conDark)} connectedDark ({conDark})')
        logbook.info(
            f'FOG_DETERMINE_END turn={self.map.turn} before={beforeCount} after={len(tilesToConvertToAddTo)} '
            f'added={len(tilesToConvertToAddTo) - beforeCount} deferred={len(deferredVisionEdgeTileSet)} '
            f'fakePathLen={None if fakePath is None else fakePath.length}')

    def _check_over_elimination(self, player: int):
        if player == -1:
            return
        if self.map.players[player].dead:
            return

        validGenPos = self.valid_general_positions_by_player[player]
        numValid = 0
        lastValid = None
        genPos = self.map.pathable_tiles
        if self.map.valid_spawns:
            genPos = self.map.valid_spawns

        for tile in genPos:
            if tile.player >= 0 and tile.discovered and not tile.isGeneral:
                validGenPos.raw[tile.tile_index] = False
                continue
            if validGenPos.raw[tile.tile_index]:
                numValid += 1
                lastValid = tile

        mustResetAndIncrease = False
        if numValid == 0:
            mustResetAndIncrease = True
            logbook.error(f'having to reset general valid positions for p{player} due to over elimination')

        if numValid == 1:
            if lastValid.visible or lastValid.discovered:
                if not lastValid.isGeneral:
                    logbook.error(f'For player {player} we only have one valid tile left, {lastValid}, however we have already discovered that tile. Refusing to set gen position...')
                    mustResetAndIncrease = True
            else:
                logbook.info(f'SETTING THE ONLY VALID REMAINING TILE TO BE GENERAL {lastValid} for player p{player}')
                if not lastValid.isGeneral:
                    # UnitTests/test_ArmyInterceptionUnit.ArmyInterceptionUnitTests.test_should_correctly_value_intercept_from_general - combat tile 5,15 owned by p0 being set as general for p1
                    if lastValid.player != -1 and lastValid.player != player:
                        logbook.error(f'For player {player} we only have one valid tile left, {lastValid}, however it is owned by player {lastValid.player}. Refusing to set gen position...')
                        mustResetAndIncrease = True
                    else:
                        lastValid.isGeneral = True
                        lastValid.player = player
                        self.map.generals[player] = lastValid
                        self.map.players[player].general = lastValid
                elif lastValid.player != player:
                    logbook.error(f'For player {player} we only have one valid tile left, {lastValid}, however we think thats a different general...')
                    mustResetAndIncrease = True

        if mustResetAndIncrease:
            validTiles = self.map.pathable_tiles
            if self.map.valid_spawns:
                validTiles = self.map.valid_spawns
            for tile in validTiles:
                if not tile.discovered and not tile.isCity and not tile.visible and not tile.isGeneral and tile.player in (-1, player):
                    validGenPos.raw[tile.tile_index] = True
            playerEvents = self.uneliminated_emergence_events[player]
            for tile, distance in list(playerEvents.items()):
                playerEvents[tile] = distance + 2
            # self.re_limit_player_gen_locations(player, playerEvents)

    @classmethod
    def get_expected_enemy_expansion_path(
            cls,
            map: MapBase,
            enTile: Tile,
            general: Tile,
            negativeTiles: typing.Container[Tile] | None = None,
            maxTurns: int = 45,
            prioMatrix: MapMatrix | None = None,
            skipTiles: typing.Container[Tile] | None = None,
            noLog: bool = True,
    ) -> Path | None:
        if prioMatrix is None:
            prioMatrix = map.distance_mapper.get_tile_dist_matrix(general)

        def valueFunc(curTile, prioObj):
            dist, negCaps, negArmy, negPrioDist = prioObj
            if negArmy > 0:
                return None
            if dist == 0:
                return None

            # prefer one or two negative tiles if they get us to larger patches of capturable material (finds longer more realistic paths)
            weightedDist = dist + 2
            # weightedDist = dist
            distDiff = maxTurns - dist
            # if distDiff < 4 and negArmy < -10:  # and negPrioDist > -6
            if distDiff < 4 or negArmy > -10:  # and negPrioDist > -6
                weightedDist = dist

            val = (0 - negCaps / weightedDist, 0-negPrioDist, dist)
            # logbook.info(f'val {str(curTile)}: {str(val)}')
            return val

        def prioFunc(nextTile, prioObj):
            dist, negCaps, negArmy, negPrioDist = prioObj
            if negArmy > 0:
                return None

            prioDist = prioMatrix.raw[nextTile.tile_index]
            # if prioDist is None:
            #     return None

            if map.is_tile_on_team_with(nextTile, enTile.player):
                negArmy -= nextTile.army
            else:
                negArmy += nextTile.army
                if negativeTiles is None or nextTile not in negativeTiles:
                    if map.is_tile_on_team_with(nextTile, general.player):
                        negCaps -= 2.05
                    else:
                        negCaps -= 0.7

            negCaps -= 0.03 * prioDist - 0.10
            # negCaps -= 0.00001 * dist

            negArmy += 1

            return dist+1, negCaps, negArmy, 0-prioDist

        initDist = prioMatrix.raw[enTile.tile_index]
        path = SearchUtils.breadth_first_dynamic_max(
            map,
            {enTile: ((0, 0, 0 - enTile.army + 1, 0-initDist), 0)},
            maxDepth=maxTurns,
            valueFunc=valueFunc,
            priorityFunc=prioFunc,
            searchingPlayer=enTile.player,
            noNeutralCities=True,
            skipTiles=skipTiles,
            noLog=noLog,
        )

        return path

    def add_emergence_around_minimum_connected_tree(self, connectedTiles: typing.List[Tile], requiredTiles: typing.List[Tile], player: int):
        enPlayer = self.map.players[player]
        emergeMap = self.emergenceLocationMap[player]
        validMap = self.valid_general_positions_by_player[player]

        basis = enPlayer.tileCount - len(connectedTiles)
        factor = 1.0
        if len(requiredTiles) == 2:
            distBetween = len(connectedTiles)
            if distBetween > enPlayer.tileCount // 2:
                # then probably this is two forks and we div the dist by 2 ish
                logbook.info(f'Due to high dist between two emergence points, using high factor.')
                basis = basis // 2
                factor = 30.0
            elif distBetween > enPlayer.tileCount // 4:
                # then probably this is two forks and we div the dist by 2 ish
                logbook.info(f'Due to high dist between two emergence points, using high factor.')
                basis = 2 * basis / 3
                factor = 10.0
        elif basis > 15:
            basis = int(math.sqrt(basis) + 1)
        depth = basis

        def foreachFunc(tile: Tile):
            if validMap[tile]:
                emergeMap[tile] += factor

        SearchUtils.breadth_first_foreach(self.map, connectedTiles, depth, foreachFunc, noLog=True)

    def get_prediction_value_x_y(self, player: int, x: int, y: int) -> float:
        """
        Return the emergence value for the tile at x,y for player player

        @param player:
        @param x:
        @param y:
        @return:
        """

        return self.emergenceLocationMap[player].raw[self.map.GetTile(x, y).tile_index]

    def get_prediction_value(self, player: int, tile: Tile) -> float:
        """
        Return the emergence value for the tile for player player

        @param player:
        @param tile
        @return:
        """

        return self.emergenceLocationMap[player].raw[tile.tile_index]

    def _reset_player_emergences(self, player: int):
        self.emergenceLocationMap[player] = MapMatrix(self.map, 0.0)

    def reset_temp_tile_marked(self, curTile: Tile, noLog: bool = False):
        if not noLog:
            logbook.info(f'resetting wrong undisc fog guess {str(curTile)}')

        if curTile.player >= 0 and curTile.isCity and curTile in self.map.players[curTile.player].cities:
            self.map.players[curTile.player].cities.remove(curTile)

        self._flipped_by_army_tracker_this_turn.append((curTile.player, curTile))
        if curTile.player >= 0:
            self.dropped_fog_tiles_this_turn.add(curTile)

        self.map.reset_wrong_undiscovered_fog_guess(curTile)

    def get_unique_armies_by_player(self, player: int) -> typing.List[Army]:
        armiesIncl = set()
        armies = []
        for army in self.armies.values():
            if army.player != player:
                continue
            if army.name not in armiesIncl:
                armiesIncl.add(army.name)
                armies.append(army)

        return armies

    def _calculate_maximum_general_distance_for_raw_fog_standing_army(self, player: Player, armyInFog: int) -> int:
        cityCount = player.cityCount
        if cityCount < 0:
            cityCount = 0
        # walk backward through turn order till we go negative
        maxDist = 0
        armyLeft = armyInFog  # - (player.cityCount - 1) // 2  # for each 2 cities (after general), they must leave behind a 2 instead of a 1, so
        turn = self.map.turn
        while True:
            if armyLeft < 0:
                break
            if turn & 1 == 0:
                armyLeft -= cityCount

            if turn % 50 == 0:
                armyLeft -= player.tileCount - SearchUtils.count(player.tiles, lambda t: t.visible)

            turn -= 1
            maxDist += 1

        return maxDist

    def has_player_seen(self, player: int, tile: Tile):
        # TODO when building ever_owned with an updated tile, just also update a new ever_seen. Also convert both to mapmatrix probably..?
        everOwned = self.tiles_ever_owned_by_player[player]
        for v in tile.visibleTo:
            if v in everOwned:
                return True

        return False

