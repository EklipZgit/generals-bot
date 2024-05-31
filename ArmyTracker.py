"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import annotations

import itertools

import SearchUtils
from Algorithms import MapSpanningUtils
from Army import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from MapMatrix import MapMatrixSet, TileSet
from PerformanceTimer import PerformanceTimer
from SearchUtils import *
from Path import Path
from base.client.map import Tile, TILE_OBSTACLE, TileDelta, Player


class PlayerAggressionTracker(object):
    def __init__(self, index):
        self.player = index


class ArmyTracker(object):
    def __init__(self, map: MapBase, perfTimer: PerformanceTimer | None = None):
        self.perf_timer: PerformanceTimer = perfTimer
        if self.perf_timer is None:
            self.perf_timer = PerformanceTimer()
        self.player_moves_this_turn: typing.Set[int] = set()
        self.map: MapBase = map
        self.general: Tile = map.generals[map.player_index]

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

        self.uneliminated_emergence_event_city_perfect_info: typing.List[typing.Set[Tile]] = [set() for player in self.map.players]
        """Whether a given emergence event had perfect city info or not."""

        self.seen_player_lookup: typing.List[bool] = [False for player in self.map.players]
        """Whether a player has been seen."""

        self.is_long_spawns: bool = len(self.map.players) == 2

        self.min_spawn_distance: int = 9
        if self.is_long_spawns:
            self.min_spawn_distance = 15

        self._initialize_viable_general_positions()

        self.player_launch_timings = [0 for _ in self.map.players]
        self.skip_emergence_tile_pathings = set()

        self.updated_city_tiles: typing.Set[Tile] = set()
        self.unconnectable_tiles: typing.List[typing.Set[Tile]] = [set() for p in self.map.players]
        self.player_connected_tiles: typing.List[typing.Set[Tile]] = [set() for p in self.map.players]
        self.players_with_incorrect_tile_predictions: typing.Set[int] = set()
        """Cities that were revealed or changed players or mountains that were fog-guess-cities will get stuck here during map updates."""

        self.lastMove: Move | None = None
        self.track_threshold: int = 10
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
        self._boardAnalysis: BoardAnalyzer | None = None

    def __getstate__(self):
        state = self.__dict__.copy()

        if 'notify_unresolved_army_emerged' in state:
            del state['notify_unresolved_army_emerged']

        if 'notify_army_moved' in state:
            del state['notify_army_moved']

        if 'perf_timer' in state:
            del state['perf_timer']

        # if '_boardAnalysis' in state:
        #     del state['_boardAnalysis']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.notify_unresolved_army_emerged = []
        self.notify_army_moved = []

    # distMap used to determine how to move armies under fog
    def scan_movement_and_emergences(
            self,
            lastMove: Move | None,
            turn: int,
            boardAnalysis: BoardAnalyzer
    ):
        self._flipped_by_army_tracker_this_turn = []
        self._boardAnalysis = boardAnalysis
        self.skip_emergence_tile_pathings = set()
        self.lastMove = lastMove
        self.decremented_fog_tiles_this_turn = set()
        self.dropped_fog_tiles_this_turn = set()
        self.players_with_incorrect_tile_predictions = set()
        for player in self.map.players:
            if self.player_launch_timings[player.index] == 0 and player.tileCount > 1:
                if player.tileCount == 2:
                    self.player_launch_timings[player.index] = self.map.turn - 1
                else:
                    # then this is a unit test or custom map with starting tiles
                    self.player_launch_timings[player.index] = 24

        with self.perf_timer.begin_move_event('ArmyTracker flipped tiles / neutral discovery'):
            self._handle_flipped_tiles()

        with self.perf_timer.begin_move_event('ArmyTracker city rescan'):
            self.rescan_city_information()

        self.player_targets = self.map.players[self.map.player_index].cities.copy()
        self.player_targets.append(self.map.generals[self.map.player_index])
        for teammate in self.map.teammates:
            teamPlayer = self.map.players[teammate]
            self.player_targets.extend(teamPlayer.cities)
            self.player_targets.append(teamPlayer.general)

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
            logbook.info(f'army tracker scan ran twice this turn {turn}...? Bailing?')
            return

        # if we have perfect info about a players general / cities, we don't need to track emergence, clear the emergence map
        for player in self.map.players:
            if self.has_perfect_information_of_player_cities_and_general(player.index):
                self.emergenceLocationMap[player.index] = MapMatrix(self.map, 0.0)

        self.fogPaths = []

        with self.perf_timer.begin_move_event('ArmyTracker army movement'):
            self.track_army_movement()
        with self.perf_timer.begin_move_event('ArmyTracker find new armies'):
            self.find_new_armies()

        with self.perf_timer.begin_move_event('ArmyTracker fog movement / increment'):
            if advancedTurn:
                self.move_fogged_army_paths()
                self.increment_fogged_armies()

        for army in self.armies.values():
            if army.tile.visible:
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
        if self.map.is_player_on_team_with(self.map.player_index, player.index) or len(player.tiles) == 0 or (player.tileDelta == 0 and player.index not in self.players_with_incorrect_tile_predictions and not force):
            return

        if self.should_recalc_fog_land_by_player[player.index]:
            self._build_fog_prediction_internal(player.index, playersExpectedFogTileCounts, predictedGeneralLocation)
            self.should_recalc_fog_land_by_player[player.index] = False
        else:
            self._inc_slash_dec_fog_prediction_to_get_player_tile_count_right(player.index, playersExpectedFogTileCounts, predictedGeneralLocation)

    def increment_fogged_armies(self):
        if not self.map.is_army_bonus_turn:
            return

        for army in list(self.armies.values()):
            if army.tile.visible:
                continue

            if army.tile.army > army.value + 1 > army.tile.army - 2:
                army.value += 1

    def move_fogged_army_paths(self):
        armyVals = list(a for a in self.armies.values() if not a.tile.visible)
        for army in armyVals:
            if army.player == self.map.player_index or army.player in self.map.teammates:
                self.scrap_army(army, scrapEntangled=False)
                continue
            if army.last_moved_turn == self.map.turn - 1:
                army.value = army.tile.army - 1
                continue

            if army.player in self.player_moves_this_turn:
                continue

            if not army.visible and army.last_seen_turn < self.map.turn - 10 and (army.tile.isCity or army.tile.isGeneral):
                logbook.info(f'skipping army {army} as it hasnt moved and is on a city/gen')
                continue

            logbook.info(f'moving fogged army paths for {str(army)}')

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

                nextPaths = fogPathNexts.get(nextTile, [])
                nextPaths.append(path)
                if len(nextPaths) == 1:
                    fogPathNexts[nextTile] = nextPaths

            if len(fogPathNexts) > 1:
                self.armies.pop(army.tile, None)

                nextArmies = army.get_split_for_fog(list(fogPathNexts.keys()))

                for nextTile, paths in fogPathNexts.items():
                    nextArmy = nextArmies.pop()
                    nextArmy.expectedPaths = []

                    if nextTile == origTile:
                        for path in paths:
                            logbook.info(f'for army {str(nextArmy)} ignoring SPLIT fog path move into visible: {str(path)}')
                            nextArmy.expectedPaths.append(path)

                        if not nextArmy.scrapped:
                            self.armies[nextArmy.tile] = nextArmy

                        continue
                    for path in paths:
                        nextArmy.expectedPaths.append(path)

                        logbook.info(f'respecting army {str(nextArmy)} SPLIT fog path: {str(path)}')

                        self._move_fogged_army_along_path(nextArmy, path, armyAlreadyPopped=True)

                        logbook.info(f'AFTER: army {str(nextArmy)}: {str(nextArmy.expectedPaths)}')
                    if not nextArmy.scrapped:
                        self.armies[nextArmy.tile] = nextArmy

            elif len(fogPathNexts) == 1:
                for path in army.expectedPaths:
                    if path is not None and path.start.next is not None and path.start.next.tile.visible:
                        logbook.info(f'for army {str(army)} ignoring fog path move into visible: {str(path)}')
                        continue

                    logbook.info(f'respecting army {str(army)} fog path: {str(path)}')

                    self._move_fogged_army_along_path(army, path)

                    logbook.info(f'AFTER: army {str(army)}: {str(army.expectedPaths)}')

            if anyNextVisible:
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

            playerMoves: typing.Dict[Tile, typing.Set[int]] = {}
            for player in self.map.players:
                if player.index == self.map.player_index:
                    continue
                if player.last_move is not None:
                    src: Tile
                    dest: Tile
                    src, dest, movedHalf = player.last_move
                    if src is not None:
                        l = playerMoves.get(src, set())
                        l.add(player.index)
                        if len(l) == 1:
                            playerMoves[src] = l
                    if dest is not None:
                        l = playerMoves.get(dest, set())
                        l.add(player.index)
                        if len(l) == 1:
                            playerMoves[dest] = l

                    armyAtSrc = self.armies.get(src, None)
                    if armyAtSrc is not None:
                        if armyAtSrc.player == player.index:
                            logbook.info(f'RESPECTING MAP DETERMINED PLAYER MOVE {str(src)}->{str(dest)} BY p{player.index} FOR ARMY {str(armyAtSrc)}')
                            self.army_moved(armyAtSrc, dest, trackingArmies, dontUpdateOldFogArmyTile=True)  # map already took care of this for us
                            skip.add(src)
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

                existingArmy = self.armies.get(tile, None)

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
                    logbook.info(f'IGNORING maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it was a discovered city..?')
                    continue

                if existingArmy and existingArmy.player == tile.player and existingArmy.value + 1 > tile.army:
                    logbook.info(f'TODO CHECK IF EVER CALLED splitting existingArmy back into fog 2 - emerged {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                    self.try_split_fogged_army_back_into_fog(existingArmy, trackingArmies)
                    skip.add(tile)
                    continue

                if emergedAmount < 0:
                    emergedAmount = 0 - emergedAmount

                if len(self.map.players[emergingPlayer].tiles) < 4:
                    emergedAmount += 7

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

                # armyDetectedAsMove = self.armies.get(tile, None)
                # if armyDetectedAsMove is not None:
                armyDetectedAsMove = self.get_or_create_army_at(tile)
                logbook.info(f'Map detected army move, honoring that: {str(tile)}->{str(tile.delta.toTile)}')
                self.army_moved(armyDetectedAsMove, tile.delta.toTile, trackingArmies)
                if tile.delta.toTile.isUndiscoveredObstacle:
                    tile.delta.toTile.isCity = True
                    tile.delta.toTile.player = armyDetectedAsMove.player
                    tile.delta.toTile.army = armyDetectedAsMove.value
                    logbook.warn(f'CONVERTING {str(tile.delta.toTile)} UNDISCOVERED MOUNTAIN TO CITY DUE TO MAP SAYING DEFINITELY TILE MOVED THERE. {str(tile)}->{str(tile.delta.toTile)}')
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
            dontUpdateOldFogArmyTile=False
    ):
        """

        @param army:
        @param toTile:
        @param trackingArmies:
        @param dontUpdateOldFogArmyTile: If True, will not update the old fogged army tile to be 1
        @return:
        """
        oldTile = army.tile
        existingArmy = self.armies.pop(army.tile, None)
        if army.visible and toTile.was_visible_last_turn(): # or visible?
            if army.player in self.player_moves_this_turn:
                logbook.error(f'Yo, we think player {army.player} moved twice this turn...? {str(army)} -> {str(toTile)}')

            self.player_moves_this_turn.add(army.player)

        existingTracking = trackingArmies.get(toTile, None)
        if (
            existingTracking is None
            or existingTracking.value < army.value
            or existingTracking.player != toTile.player
        ):
            trackingArmies[toTile] = army

        potentialMergeOrKilled = self.armies.get(toTile, None)
        if potentialMergeOrKilled is not None:
            if potentialMergeOrKilled.player == army.player:
                self.merge_armies(army, potentialMergeOrKilled, toTile, trackingArmies)
            elif toTile.delta.toTile is None:
                self.collide_armies(army, potentialMergeOrKilled, toTile, trackingArmies)

        army.update_tile(toTile)

        if army.value < -1 or (army.player != army.tile.player and army.tile.visible):
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
            # Ok then we need to recalculate the expected path.
            # TODO detect if enemy army is likely trying to defend
            army.expectedPaths = ArmyTracker.get_army_expected_path(self.map, army, self.general, self.player_targets)
            logbook.info(f'set army {str(army)} expected paths to {str(army.expectedPaths)}')

        army.last_moved_turn = self.map.turn - 1

        for listener in self.notify_army_moved:
            listener(army)

    def scrap_army(self, army: Army, scrapEntangled: bool = False):
        army.scrapped = True
        if scrapEntangled:
            for entangledArmy in army.entangledArmies:
                entangledArmy.scrapped = True
            self.resolve_entangled_armies(army)
        else:
            for entangledArmy in army.entangledArmies:
                try:
                    entangledArmy.entangledArmies.remove(army)
                except:
                    pass

    def resolve_entangled_armies(self, army):
        if len(army.entangledArmies) > 0:
            logbook.info(f"{str(army)} resolving {len(army.entangledArmies)} entangled armies")
            for entangledArmy in army.entangledArmies:
                logbook.info(f"    {entangledArmy.toString()} entangled")
                if entangledArmy.tile in self.armies:
                    del self.armies[entangledArmy.tile]
                entangledArmy.scrapped = True
                if not entangledArmy.tile.visible and entangledArmy.tile.army > 0:
                    # remove the army value from the tile?
                    newArmy = max(entangledArmy.tile.army - entangledArmy.entangledValue, 1)
                    logbook.info(
                        f"    updating entangled army tile {entangledArmy.toString()} from army {entangledArmy.tile.army} to {newArmy}")
                    entangledArmy.tile.army = newArmy
                    if not entangledArmy.tile.discovered and entangledArmy.tile.player >= 0:
                        self.reset_temp_tile_marked(entangledArmy.tile)

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
        existingTargetFoggedArmy = self.armies.get(fogTargetTile, None)
        if existingTargetFoggedArmy is not None:
            if army in existingTargetFoggedArmy.entangledArmies:
                army.scrapped = True
                return

        movingPlayer = self.map.players[army.player]

        if not fogTargetTile.visible:
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

        if self.map.turn % 50 == 0:
            self.update_track_threshold()

        playerMoves: typing.Dict[Tile, typing.Set[int]] = {}
        for player in self.map.players:
            if player == self.map.player_index:
                continue
            if player.last_move is not None:
                src: Tile
                dest: Tile
                src, dest, movedHalf = player.last_move
                if src is not None:
                    l = playerMoves.get(src, set())
                    l.add(player.index)
                    if len(l) == 1:
                        playerMoves[src] = l
                if dest is not None:
                    l = playerMoves.get(dest, set())
                    l.add(player.index)
                    if len(l) == 1:
                        playerMoves[dest] = l

        # don't do largest tile for now?
        # for tile in self.map.pathableTiles:
        #    if tile.player != -1 and (playerLargest[tile.player] == None or tile.army > playerLargest[tile.player].army):
        #        playerLargest[tile.player] = tile
        for player in self.map.players:
            for tile in player.tiles:
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
                    tileArmy = self.armies.get(tile, None)

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
                distance = self.min_spawn_distance + 1

            armyEmergenceValue = 2 + (armyEmergenceValue ** 0.75)

            if armyEmergenceValue > 10:
                armyEmergenceValue = 10

            armyEmergenceScaledToTurns = 5 * armyEmergenceValue / (5 + self.map.turn // 25)

            logbook.info(f"running new_army_emerged for tile {str(emergedTile)} with emValueScaled {armyEmergenceScaledToTurns:.2f}, distance {distance}")

            # bannedTiles, connectedTiles, pathToUnelim = self.get_fog_connected_based_on_emergences(emergingPlayer, predictedGeneralLocation=None, additionalRequiredTiles=[emergedTile])

            def foreachFunc(tile, dist):
                if not tile.discovered:
                    distCapped = max(4, dist)
                    emergeValue = 4 * armyEmergenceScaledToTurns // distCapped
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

        def pathSortFunc(
                nextTile: Tile,
                prioObject
        ):
            (distWeighted, dist, negArmy, turnsNeg, citiesConverted, negBonusScore, consecutiveUndiscovered, meetsCriteria) = prioObject
            theArmy = self.armies.get(nextTile, None)
            if theArmy is not None:
                consecutiveUndiscovered = 0
                if self.is_friendly_team(theArmy.player, armyPlayer):
                    negArmy -= theArmy.value
                else:
                    negArmy += theArmy.value
            elif nextTile.isUndiscoveredObstacle or (not nextTile.visible and nextTile.isCity and nextTile.isNeutral):
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
                    or turnsNegative > 6
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
            maxTime=100000.0,
            noNeutralCities=not allowVisionlessObstaclesAndCities,
            noNeutralUndiscoveredObstacles=not allowVisionlessObstaclesAndCities,
            priorityFunc=pathSortFunc,
            skipFunc=fogSkipFunc,
            searchingPlayer=armyPlayer,
            logResultValues=True,
            noLog=False)
        if fogSourcePath is not None:
            logbook.info(
                f"        For new army at tile {str(tile)} we found fog source path???? {str(fogSourcePath)}")
        else:
            logbook.info(f"        NO fog source path for new army at {str(tile)}")
        return fogSourcePath

    def find_next_fog_city_candidate_near_tile(
            self,
            cityPlayer: int,
            tile: Tile,
            cutoffDist: int = 10,
            distanceWeightReduction: int = 3,
            wallBreakWeight: float = 2.0,
            emergenceWeight: float = 1.0,
            doNotConvert: bool = False
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

        def valFunc(
                thisTile: Tile,
                prioObject
        ):
            dist, _, validLocation = prioObject
            if not validLocation:
                return None

            if thisTile.visible or thisTile == tile or dist == 0:
                return None

            isPotentialFogCity = thisTile.isCity and thisTile.isNeutral
            isPotentialFogCity = isPotentialFogCity or thisTile.isUndiscoveredObstacle
            if not isPotentialFogCity:
                return None

            wallBreakBonus = self._boardAnalysis.enemy_wall_breach_scores[thisTile]
            if not wallBreakBonus or wallBreakBonus < 3:
                wallBreakBonus = 0
            else:
                wallBreakBonus = wallBreakBonus * wallBreakWeight

            emergenceVal = (self.emergenceLocationMap[cityPlayer][thisTile] * emergenceWeight + wallBreakBonus) / (dist + distanceWeightReduction)
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

                    if self.map.get_distance_between(self.general, t) > self.map.get_distance_between(self.general, nextTile) + 4 and self.map.get_distance_between(self.general, t) < 150:
                        dist -= 2

            if not validLocation:
                dist += 0.5

            if dist > 3:
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
                    or (nextTile.discoveredAsNeutral and self.map.turn < 400)
                    or dist > cutoffDist
            )

        inputTiles = {}
        logbook.info(f"FINDING NEXT FOG CITY FOR PLAYER {cityPlayer} for not-fog-city tile {str(tile)}")
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
            noLog=False)
        if fogSourcePath is not None:
            newFogCity = fogSourcePath.tail.tile
            if not doNotConvert:
                self.convert_fog_city_to_player_owned(newFogCity, cityPlayer)
            logbook.info(
                f"        Found new fog city!???? {str(newFogCity)}")
            return newFogCity

        else:
            logbook.info(f"        NO alternate fog city found for {str(tile)}")

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
        for army in armiesFromFog:
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
            # self.armies[fogTile] = maxArmy
            maxArmy.path = sourceFogArmyPath
            maxArmy.expectedPaths = []
        else:
            # then this is a brand new army because no armies were on the fogPath, but we set the source path to 1's still
            maxArmy = Army(fogTile)
            # armies told to load from fog ignore the tiles army. In this case, we want to explicitly respect it.
            if not fogTile.visible:
                maxArmy.value = fogTile.army - 1
            # self.armies[fogTile] = maxArmy
            maxArmy.path = sourceFogArmyPath

        return maxArmy

    def merge_armies(self, largerArmy: Army, smallerArmy: Army, finalTile: Tile, armyDict: typing.Dict[Tile, Army] | None = None):
        self.armies.pop(largerArmy.tile, None)
        self.armies.pop(smallerArmy.tile, None)
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

    def collide_armies(self, movingArmy: Army, targetArmy: Army, finalTile: Tile, armyDict: typing.Dict[Tile, Army] | None = None):
        self.armies.pop(movingArmy.tile, None)
        self.armies.pop(targetArmy.tile, None)

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
        army = self.armies.get(tile, None)
        if army is not None:
            return army

        logbook.info(f'creating new army at {str(tile)} in get_or_create.')
        army = Army(tile)
        army.last_moved_turn = 0
        if army.tile.delta.fromTile is not None:
            army.last_moved_turn = self.map.turn - 1
        if not tile.visible:
            army.last_moved_turn = self.map.turn - 2  # this should only really happen on incrementing fog cities or on initial unit test map load
            army.value = tile.army - 1

        if not skip_expected_path:
            army.expectedPaths = ArmyTracker.get_army_expected_path(self.map, army, self.general, self.player_targets)
            logbook.info(f'set army {str(army)} expected path to {str(army.expectedPaths)}')

        self.armies[tile] = army

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

        isGoodResolution = emergenceValueCovered + 3 > delta * minRatio  # +3 offsets incorrect fog guess tiles moved over by the army at lower emergence values
        logbook.info(
            f"emergenceValueCovered ({emergenceValueCovered}) > armyTile.army * {minRatio} ({armyTile.army * minRatio:.1f}) : {isGoodResolution}")
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
            negativeTiles: typing.Set[Tile] | None = None
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

        if map.is_tile_friendly(army.tile):
            # Why would we be using this for friendly armies...?
            return []

        if army.value <= 0:
            if army.tile.army > 1:
                army.value = army.tile.army - 1
            else:
                return []

        remainingCycleTurns = 50 - map.turn % 50

        if negativeTiles is None:
            negativeTiles = set()

        pathA = ArmyTracker.get_army_expected_path_non_flank(map, army, general, playerTargets, negativeTiles=negativeTiles)
        if pathA and pathA.length > 0:
            negativeTiles.update(pathA.tileList)
        pathB = ArmyTracker.get_army_expected_path_flank(map, army, general, negativeTiles=negativeTiles)

        matrices = []

        paths = []
        if pathA is not None and pathA.length > 0:
            paths.append(pathA)
            matrices.append(map.distance_mapper.get_tile_dist_matrix(pathA.tail.tile))
        if pathB is not None and pathB.length > 0 and not SearchUtils.any_where(paths, lambda p: p.tail.tile == pathB.tail.tile):
            paths.append(pathB)
            if pathB.length > 2:
                pathC = ArmyTracker.get_army_expected_path_flank(map, army, general, skipTiles=pathB.tileList[3:], negativeTiles=negativeTiles)
                if pathC is not None and pathC.length > 0 and pathC.tail.tile != pathB.tail.tile:
                    paths.append(pathC)
                    matrices.append(map.distance_mapper.get_tile_dist_matrix(pathC.tail.tile))
            matrices.append(map.distance_mapper.get_tile_dist_matrix(pathB.tail.tile))

        if len(matrices) == 0:
            matrices.append(map.distance_mapper.get_tile_dist_matrix(general))
        summed = MapMatrix.get_summed(matrices)
        # summed.negate()
        pathD = ArmyTracker.get_expected_enemy_expansion_path(map, army.tile, general, negativeTiles=set(itertools.chain.from_iterable(p.tileList for p in paths)), maxTurns=remainingCycleTurns, prioMatrix=summed)
        if pathD is not None and pathD.length > 0:
            paths.append(pathD)
            # MapMatrix.subtract_from_matrix(summed, map.distance_mapper.get_tile_dist_matrix(pathD.tail.tile))
            MapMatrix.add_to_matrix(summed, map.distance_mapper.get_tile_dist_matrix(pathD.tail.tile))
            pathE = ArmyTracker.get_expected_enemy_expansion_path(map, army.tile, general, negativeTiles=set(itertools.chain.from_iterable(p.tileList for p in paths)), maxTurns=max(20, remainingCycleTurns), prioMatrix=summed)
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
                if pathF is not None and pathF.length > 0:
                    paths.append(pathF)

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
            maxTime=0.1,
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

        def valueFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile.visible:
                return None

            return 0 - map.get_distance_between(general, tile), 0

        def prioFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile.visible:
                return None

            return map.get_distance_between(general, tile), 0

        skip = MapMatrixSet(map)

        for tile in map.get_all_tiles():
            if tile.visible:
                skip.add(tile)

        if skipTiles is not None:
            skip.update(skipTiles)

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
            maxTime=0.1,
            maxDepth=30,
            noNeutralCities=army.tile.army < 150,
            searchingPlayer=army.player,
            noLog=True)

        if path is None:
            return None

        return path.get_positive_subsegment(forPlayer=army.player, teams=MapBase.get_teams_array(map), negativeTiles=negativeTiles)

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

        if tile.delta.discovered and not tile.army > self.track_threshold and not unaccountedForDelta > self.track_threshold and len(self.map.players[player].tiles) > 4:
            return None

        depthLimit = self.get_emergence_max_depth_to_general_or_none(player, tile, unaccountedForDelta)

        sourceFogArmyPath = self.find_fog_source(player, tile, unaccountedForDelta, depthLimit=depthLimit)
        if sourceFogArmyPath is not None:
            self.unaccounted_tile_diffs.pop(tile, 0)

            if tile not in self.skip_emergence_tile_pathings:
                if depthLimit is not None and depthLimit < 40 and tile.delta.toTile is None:
                    logbook.info(f'WHOO LIMITING GENERAL BY {depthLimit} BASED ON SHEER STANDING ARMY EMERGENCE')

                    maxDistToGen = depthLimit
                    self._limit_general_position_to_within_tile_and_distance(player, tile, maxDistToGen, alsoIncreaseEmergence=True, skipIfLongerThanExisting=True, emergenceAmount=unaccountedForDelta)

                self.use_fog_source_path_and_increase_emergence(tile, sourceFogArmyPath, unaccountedForDelta, depthLimit=depthLimit)

                return self.resolve_fog_emergence(player, sourceFogArmyPath, tile)

        return None

    def get_emergence_max_depth_to_general_or_none(self, player: int, tile: Tile, unaccountedForDelta: int = -1):
        if unaccountedForDelta == -1:
            unaccountedForDelta = abs(tile.delta.armyDelta)
        armyPlayerObj = self.map.players[player]
        depthLimit = None
        armyInFog = armyPlayerObj.standingArmy - armyPlayerObj.visibleStandingArmy
        if unaccountedForDelta > 2 * armyInFog - 4:
            depthLimit = self._calculate_maximum_general_distance_for_raw_fog_standing_army(armyPlayerObj, armyInFog)

        return depthLimit

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
                newCity = self._find_replacement_fog_city_internal(city)
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

        newCity = self._find_replacement_fog_city_internal(city)

        return newCity

    def _find_replacement_fog_city_internal(self, city: Tile):
        prevArmy = city.delta.oldArmy

        cityOwner = city.delta.oldOwner
        if not city.visible:
            cityOwner = city.player

        cityPlayer = self.map.players[cityOwner]

        newCity = self.find_next_fog_city_candidate_near_tile(cityOwner, city)
        if not city.discovered:
            city.reset_wrong_undiscovered_fog_guess()
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

        def reasonablePathDetector(sourceTile: Tile, armyAmt: int, dist: int) -> bool:
            if sourceTile.isObstacle:
                return False
            if self.emergenceLocationMap[armyPlayer][sourceTile] <= 0:
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

            if actualTileCount < mapTileCount:
                logbook.info(f'reducing player {player.index} over-tiles')
                realDists = SearchUtils.build_distance_map_matrix(self.map, list(self.tiles_ever_owned_by_player[player.index]))

                # strip extra tiles
                tilesAsEncountered = SearchUtils.HeapQueue()
                for tile in player.tiles:
                    if not tile.discovered:
                        dist = realDists[tile]
                        emergenceBonus = max(0.0, self.emergenceLocationMap[player.index][tile])
                        tilesAsEncountered.put((emergenceBonus / (dist + 1) - 3 * dist + tile.army, tile))

                while mapTileCount > actualTileCount and tilesAsEncountered.queue:
                    toRemove: Tile
                    score, toRemove = tilesAsEncountered.get()
                    if not toRemove.isCity and not toRemove.isGeneral:
                        logbook.info(f'dropped player {player.index} over-tile tile {str(toRemove)}')
                        self.reset_temp_tile_marked(toRemove, noLog=True)
                        mapTileCount -= 1
                        army = self.armies.get(toRemove, None)
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

                army = self.armies.get(tile, None)
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

                    tileArmy = self.armies.get(tile, None)
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
                    army = self.armies.get(toReduce, None)
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

    def _handle_flipped_tiles(self):
        """To be called every time a tile is flipped from one owner to another owner by the map updates themselves."""

        for tile in self._flipped_tiles:
            if tile.player != -1:  #  and (tile.delta.oldOwner == -1 or not self.map.players[tile.delta.oldOwner].dead)  # not sure why this logic was here...?
                self.tiles_ever_owned_by_player[tile.player].add(tile)

        self._handle_flipped_discovered_as_neutrals()

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
                for tile in self.map.reachableTiles:
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

                for player in self.map.players:
                    # if not self.valid_general_positions_by_player[player.index]
                    emergence = self.emergenceLocationMap[player.index][tile]
                    for movable in tile.movable:
                        movableEmergence = self.emergenceLocationMap[player.index][movable]
                        if movable.discovered:
                            continue
                        if emergence > movableEmergence:
                            self.emergenceLocationMap[player.index][movable] = movableEmergence + emergence // 2

            elif tile.player >= 0 and SearchUtils.any_where(tile.movable, lambda t: not t.discovered):
                reFogLandPlayers.add(tile.player)

            if self.map.is_tile_friendly(tile):
                continue

            if tile.delta.discovered:
                for player in self.map.players:
                    self.valid_general_positions_by_player[player.index].discard(tile)

                if tile.isGeneral:
                    for player in self.map.players:
                        if self.map.is_player_on_team_with(player.index, tile.player):
                            if tile.player != player.index and self.map.is_2v2:
                                def limitSpawnAroundAllyGen(t: Tile):
                                    if abs(t.x - tile.x) + abs(t.y - tile.y) > 11:
                                        self.valid_general_positions_by_player[player.index].discard(t)

                                SearchUtils.breadth_first_foreach(self.map, [tile], 1000, foreachFunc=limitSpawnAroundAllyGen, bypassDefaultSkip=True)
                            continue

                        def limitSpawnAroundOtherGen(t: Tile):
                            self.valid_general_positions_by_player[player.index].discard(t)

                        SearchUtils.breadth_first_foreach(self.map, [tile], self.min_spawn_distance, foreachFunc=limitSpawnAroundOtherGen, bypassDefaultSkip=True)

                    for t in self.map.get_all_tiles():
                        if t != tile:
                            self.valid_general_positions_by_player[tile.player].discard(t)
                        else:
                            self.valid_general_positions_by_player[tile.player].add(t)

        mustReLimit = False
        for tile in self._flipped_tiles:
            if tile.player == -1 and tile.delta.discovered:
                mustReLimit = True
                break

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

            skip = False
            for mv in tile.movable:
                # if (mv.player == tile.player or mv.delta.oldOwner == tile.player) and not mv.delta.gainedSight and mv.discovered: # todo removed gainedsight?
                if (mv.player == tile.player or mv.delta.oldOwner == tile.player) and not mv.delta.gainedSight and mv.discovered:
                    skip = True

            if skip:
                continue

            p = self.map.players[tile.player]

            if p.tileCount > 75 or p.cityCount > 1:
                continue

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

        self._flipped_tiles.clear()

        for player in recheckPlayers:
            self._check_over_elimination(player)

    def limit_gen_position_from_emergence(self, p: Player, tile: Tile, emergenceAmount: int = -1):
        # ok then this tile is a candidate for limiting distance from general...?
        pLaunchTiming = self.player_launch_timings[tile.player]
        maxDist = self.map.turn - pLaunchTiming
        playerPreviouslyVisibleTiles = [t for t in p.tiles if (t.visible or t.delta.lostSight) and not t.delta.gainedSight and t.delta.oldOwner == t.delta.newOwner]
        maxDist = min(maxDist, p.tileCount - 1)
        # if not tile.delta.gainedSight:
        #     maxDist = min(maxDist, p.tileCount)
        if self.map.turn <= 100 and pLaunchTiming > 17:
            # then, unless they did some real dumb stuff, they can't be further than than their launch timing dist, either
            # THIS produces bad behavior
            cycle1Trail1DistLimitAkaStartArmy = pLaunchTiming // 2 + 1
            trail1EndTurn = pLaunchTiming + cycle1Trail1DistLimitAkaStartArmy - 1

            trailOffset = 0
            if not tile.delta.gainedSight:
                trailOffset = 1

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
                        maxDist = min(maxDist, cycle1Trail1DistLimitAkaStartArmy + maxExtraDist)
                        # then they can be further away than their initial trail was as they could have retraversed.
                    elif trail1EndTurn < 44:
                        # then this is their second trail, but they don't have time to get further than original launch dist so, we can still limit by that..
                        maxDist = min(maxDist, cycle1Trail1DistLimitAkaStartArmy)
                    else:
                        logbook.info(f'because of weird nonstandard launch, they may be full retraversing, so using their tile count as limit in order to not over-limit')
                        maxDist = p.tileCount
                else:
                    # otherwise, they've been capturing tiles, meaning we can limit by the max of either original launch limit or their max second launch limit
                    maxDist = min(maxDist, tilesCapturedInAddlLaunches)

                # can never limit shorter than the original furthest tiles in case we just found that instead of a subsequent trail.
                maxDist = max(maxDist, cycle1Trail1DistLimitAkaStartArmy - trailOffset)
            else:
                maxDist = min(maxDist, cycle1Trail1DistLimitAkaStartArmy - trailOffset)

        limitByRawStandingArmy = self.get_emergence_max_depth_to_general_or_none(p.index, tile, emergenceAmount)
        if limitByRawStandingArmy is not None and maxDist > limitByRawStandingArmy:
            logbook.info(f'WHOO LIMITING PLAYER {p.index} GENERAL BY {limitByRawStandingArmy} BASED ON SHEER STANDING ARMY EMERGENCE AT {tile}')
            # this function doesn't expect you to include the emerging tile, where our calculation above does.
            maxDist = limitByRawStandingArmy

        increaseEmergence = self.map.turn < 51 or maxDist < 5
        if len(playerPreviouslyVisibleTiles) == 0:
            # throw out the army emergence deltas for the very first emergence, as we want to use the dist limiter exclusively for first contact.
            self._reset_player_emergences(p.index)
            # tile.delta.unexplainedDelta = 0
            self.skip_emergence_tile_pathings.add(tile)
            if tile.delta.fromTile is not None:
                self.skip_emergence_tile_pathings.add(tile.delta.fromTile)

            increaseEmergence = True

        logbook.info(f'running a gen position limiter for p{p.index} from {str(tile)} distance {maxDist}, incEmergence={increaseEmergence}')
        self._limit_general_position_to_within_tile_and_distance(p.index, tile, maxDist, alsoIncreaseEmergence=increaseEmergence, skipIfLongerThanExisting=True, emergenceAmount=emergenceAmount)

    def re_limit_gen_locations(self):
        for p, playerElims in enumerate(self.uneliminated_emergence_events):
            for prevElimTile, prevElimDist in playerElims.items():
                cityPerfectInfo = prevElimTile in self.uneliminated_emergence_event_city_perfect_info[p]
                logbook.info(f'RE-eliminating p{p} t{prevElimTile} d{prevElimDist}, perfectCity{cityPerfectInfo}')
                self._limit_general_position_to_within_tile_and_distance(p, prevElimTile, prevElimDist, alsoIncreaseEmergence=False, overrideCityPerfectInfo=cityPerfectInfo)  # alsoIncreaseEmergence=self.map.turn < 56)

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

            if len(alreadyRan) > 0 and self.map.turn < 150:
                with self.perf_timer.begin_move_event('gen re-limit'):
                    self.re_limit_gen_locations()

    def _limit_general_position_to_within_tile_and_distance(self, player: int, tile: Tile, maxDist: int, alsoIncreaseEmergence: bool = True, skipIfLongerThanExisting: bool = False, overrideCityPerfectInfo: bool | None = None, emergenceAmount: int = -1):
        playerUnelim = self.uneliminated_emergence_events[player]
        existingLimit = playerUnelim.get(tile, None)

        if existingLimit is not None and existingLimit <= maxDist:
            if skipIfLongerThanExisting:
                logbook.info(f'bypassing {str(tile)} @ dist {maxDist} because it is longer or equal to existing limit for that tile at dist {existingLimit}')
                return

        if emergenceAmount == -1 and len(playerUnelim) == 0:
            emergenceAmount = 20

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

    def _limit_general_position_to_within_tiles_and_distance(self, player: int, tiles: typing.List[Tile], maxDist: int, alsoIncreaseEmergence: bool = True, overrideCityPerfectInfo: bool | None = None, emergenceAmount: int = -1) -> int:
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

        def limiter(t: Tile, dist: int) -> bool:
            if self.valid_general_positions_by_player[player][t]:
                validSet.add(t)
                if alsoIncreaseEmergence:
                    launchDistDiff = abs(launchDist - dist)
                    launchDistFactor = (divOffset + launchDistDiff)
                    launchEmergence = emFactor // launchDistFactor
                    self.emergenceLocationMap[player][t] += launchEmergence
            if t.discoveredAsNeutral and t not in self.tiles_ever_owned_by_player[player]:  # and (t.visible or self.map.turn < 50)   # should be solved without the visible check by adding the lost-sight-ever-owned-by-player hack to allow pathing through the fog now.
                return True
            if (t.isCity and t.player == -1 and (t.visible or hasPerfectInfoOfPlayerCities)) or t.isMountain or (t.isUndiscoveredObstacle and hasPerfectInfoOfPlayerCities) or t.isGeneral:
                return True
            return False

        starting = set()
        for tile in tiles:
            for movable in tile.movable:
                if movable.isObstacle:
                    continue
                starting.add(movable)

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
        for t in self.map.get_all_tiles():
            if t not in validSet and t in self.valid_general_positions_by_player[player]:
                # logbook.info(f'elimin')
                elims += 1
                self.valid_general_positions_by_player[player].discard(t)
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
            if p.general is not None:
                self.valid_general_positions_by_player[p.index].add(p.general)
                continue

            for tile in self.map.get_all_tiles():
                if tile.isObstacle:
                    continue

                if tile.visible:
                    continue

                if tile.discovered:
                    continue

                self.valid_general_positions_by_player[p.index].add(tile)

        for p, general in enumerate(self.map.generals):
            if general is None:
                continue

            distances = self.map.distance_mapper.get_tile_dist_matrix(general)

            for player in self.map.players:
                if self.map.is_player_on_team_with(general.player, player.index):
                    self.valid_general_positions_by_player[player.index].discard(general)
                    continue

                for tile in self.map.get_all_tiles():
                    if abs(tile.x - general.x) + abs(tile.y - general.y) < self.min_spawn_distance:  # spawns are manhattan distance
                        self.valid_general_positions_by_player[player.index].discard(tile)
                        continue

                    if distances[tile] == 1000:
                        self.valid_general_positions_by_player[player.index].discard(tile)

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

        if len(potential) > 1:
            logbook.info(f"    Army {str(army)} IS BEING ENTANGLED BACK INTO THE FOG")
            entangledArmies = army.get_split_for_fog(potential)
            for i, fogBoi in enumerate(potential):
                logbook.info(
                    f"    Army {str(army)} entangled moved to {str(fogBoi)}")
                self.move_army_into_fog(entangledArmies[i], fogBoi)
                self.unaccounted_tile_diffs.pop(entangledArmies[i].tile, None)
                self.army_moved(entangledArmies[i], fogBoi, trackingArmies, dontUpdateOldFogArmyTile=True)

        elif len(potential) == 1:
            self.move_army_into_fog(army, potential[0])
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.army_moved(army, potential[0], trackingArmies, dontUpdateOldFogArmyTile=True)

    def update_track_threshold(self):
        tilesRankedByArmy = list(sorted(where(self.map.pathableTiles, filter_func=lambda t: t.player != -1), key=lambda t: t.army))
        percentile = 96
        percentileIndex = percentile * len(tilesRankedByArmy) // 100
        tileAtPercentile = tilesRankedByArmy[percentileIndex]
        if tileAtPercentile.army - 1 > self.track_threshold:
            newTrackThreshold = tileAtPercentile.army - 1
            logbook.info(f'RAISING TRACK THRESHOLD FROM {self.track_threshold} TO {newTrackThreshold}')
            self.track_threshold = newTrackThreshold

    def _move_fogged_army_along_path(self, army: Army, path: Path | None, armyAlreadyPopped: bool = False):

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
            army.value = army.tile.army - 1

            return

        nextTile = path.start.next.tile
        if not nextTile.visible:
            existingArmy = self.armies.get(nextTile, None)
            if existingArmy is not None and existingArmy == army:
                existingArmy = None
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
            oldTile.army = 1
            if self.map.is_city_bonus_turn and oldTile.isCity or oldTile.isGeneral:
                oldTile.army += 1
            if self.map.is_army_bonus_turn:
                oldTile.army += 1

            if existingArmy is not None:
                if existingArmy in army.entangledArmies:
                    logbook.info(f'entangled army collided with itself, scrapping the collision-mover {str(army)} in favor of {str(existingArmy)}')
                    self.scrap_army(army, scrapEntangled=False)
                    return

            # if not oldTile.discovered:
            #     oldTile.player = -1
            #     oldTile.army = 0
            if nextTile.player == army.player:
                nextTile.army = nextTile.army + army.value
            else:
                if nextTile.player != army.player and not nextTile.discovered:
                    nextTile.isTempFogPrediction = True
                nextTile.army = nextTile.army - army.value
                if nextTile.army < 0:
                    nextTile.army = 0 - nextTile.army
                if not nextTile.isGeneral:
                    nextTile.player = army.player

            if existingArmy is not None:
                if existingArmy.player == army.player:
                    if existingArmy.value > army.value:
                        self.merge_armies(existingArmy, army, nextTile)
                    else:
                        self.merge_armies(army, existingArmy, nextTile)
                    return

            army.update_tile(nextTile)
            army.value = nextTile.army - 1
            self.armies[nextTile] = army
            path.remove_start()

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

        for army in possibleArmies:
            seenAgo = self.map.turn - army.last_seen_turn
            if seenAgo > 8:
                continue
            if tookNeutCity:
                potentialCity = self.find_next_fog_city_candidate_near_tile(player, army.tile, cutoffDist=8 - seenAgo)
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
                    army.expectedPaths = ArmyTracker.get_army_expected_path(self.map, army, self.general, self.player_targets)
                    self.armies[army.tile] = army
                    army.last_moved_turn = self.map.turn

                    break

            else:
                # likelyArmy = army
                army.value -= annihilatedFogArmy
                if army.value < 0:
                    army.value = 0
                army.tile.army = army.value + 1

                break

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
        bannedTiles, connectedTiles, pathToUnelim = self.get_fog_connected_based_on_emergences(player, predictedGeneralLocation)

        keep = []
        for tile in playerObj.tiles:
            if tile.isTempFogPrediction and not tile.discovered and tile not in self.armies and not tile.isGeneral and not tile.isCity:
                tile.reset_wrong_undiscovered_fog_guess()
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
            player,
            predictedGeneralLocation,
            additionalRequiredTiles: typing.Iterable[Tile] | None = None
    ) -> typing.Tuple[MapMatrixSet, TileSet, Path | None]:
        """
        Returns bannedTiles, connectedSet, pathToClosestUneliminatedGenPosition
        @param player:
        @param predictedGeneralLocation:
        @param additionalRequiredTiles:
        @return:
        """
        tilesEverOwned = self.tiles_ever_owned_by_player[player]
        uneliminated = self.uneliminated_emergence_events[player]
        unrecapturedEmergenceEvents = self.unrecaptured_emergence_events[player]
        validGenSpots = self.valid_general_positions_by_player[player]
        teamStats = self.map.get_team_stats(player)
        perfectInfo = teamStats.cityCount == len(teamStats.teamPlayers)
        bannedTiles = MapMatrixSet(self.map)
        for tile in self.map.get_all_tiles():
            if tile not in uneliminated and tile not in unrecapturedEmergenceEvents and tile not in tilesEverOwned and (tile.discoveredAsNeutral or tile.visible):
                bannedTiles.add(tile)
            elif tile.isObstacle and perfectInfo:
                bannedTiles.add(tile)

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
        #     logbook.warn(f'ArmyTracker found no tiles to build fog land from for player {player}')
        #     return
        with self.perf_timer.begin_move_event(f'Fog land build get_spanning_tree_set_from_tile_lists p{player} (num required {len(requiredTiles)})'):
            connectedSet, missingRequired = MapSpanningUtils.get_spanning_tree_set_from_tile_lists(self.map, requiredTiles, bannedTiles)
            # connectedTiles = [t for t in connectedSet]
            self.unconnectable_tiles[player] = missingRequired
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

        return bannedTiles, connectedSet, pathToUnelim

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
        secondIterConnected = connectedTiles
        if pathToPotentialEnGeneral is not None:
            # this ban makes it so we don't try to double-fill the connectedDark tiles. These can be pathed through but wont be converted.
            nearGenBan = bannedTiles.copy()
            for t in connectedDark:
                nearGenBan.add(t)

            approxEnGen = pathToPotentialEnGeneral.tail.tile

            numMissingCities = self.get_team_missing_city_count_by_player(player)
            while numMissingCities > 0:
                potCity = self.find_next_fog_city_candidate_near_tile(player, approxEnGen, cutoffDist=10, distanceWeightReduction=5, wallBreakWeight=4, emergenceWeight=1.0)
                if potCity is None:
                    break
                numMissingCities -= 1
                outputTilesToBeConverted.add(potCity)
                logbook.info(f'setting fog city {potCity} to be player owned in _fill_land_from_connected_tiles_for_player.')

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

            if tile.isGeneral or tile.isCity:
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
            if tile.isUndiscoveredObstacle:
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
        skips = set(bannedTiles)
        skips.difference_update(connectedDark)
        for tile in connectedDark:
            if not tile.discovered and tile.player == -1:
                tilesToConvertToAddTo.add(tile)

        numFillTilesNeeded = numTilesToFillIn

        def findFunc(tile: Tile, army: float, dist: int) -> bool:
            if len(tilesToConvertToAddTo) >= numFillTilesNeeded:
                return True

            if tile.player == -1 and tile not in tilesToConvertToAddTo:
                tilesToConvertToAddTo.add(tile)

            return False

        # TODO add breadth_first_foreach_terminating and use that instead so we dont waste time building unused paths in exchange for not fully looping
        fakePath = SearchUtils.breadth_first_find_queue(self.map, connectedDark, findFunc, skipTiles=skips, noNeutralCities=True, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if fakePath is None:
            logbook.error(f'unable to fill the requested {numFillTilesNeeded} tiles from {connectedDark}, allowing neutral cities...?')
            fakePath = SearchUtils.breadth_first_find_queue(self.map, connectedDark, findFunc, skipTiles=skips, noLog=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if fakePath is None:
                # then we couldn't fully build the set?
                logbook.error(f'unable to fully build the set of tiles...?')

    def _check_over_elimination(self, player: int):
        if player == -1:
            return

        validGenPos = self.valid_general_positions_by_player[player]
        numValid = 0
        lastValid = None
        for tile in self.map.pathableTiles:
            if tile in validGenPos:
                numValid += 1
                lastValid = tile

        if numValid == 0:
            logbook.error(f'having to reset general valid positions for p{player} due to over elimination')
            for tile in self.map.pathableTiles:
                if not tile.discovered:
                    validGenPos.add(tile)

        if numValid == 1 and not lastValid.isGeneral and not self.map.players[player].dead:
            lastValid.player = player
            lastValid.isGeneral = True
            self.map.generals[player] = lastValid
            self.map.players[player].general = lastValid


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
                        negCaps -= 2.2
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

        return self.emergenceLocationMap[player][self.map.GetTile(x, y)]

    def get_prediction_value(self, player: int, tile: Tile) -> float:
        """
        Return the emergence value for the tile for player player

        @param player:
        @param tile
        @return:
        """

        return self.emergenceLocationMap[player][tile]

    def _reset_player_emergences(self, player: int):
        for t in self.map.pathableTiles:
            self.emergenceLocationMap[player] = MapMatrix(self.map, 0.0)

    def reset_temp_tile_marked(self, curTile: Tile, noLog: bool = False):
        if not noLog:
            logbook.info(f'resetting wrong undisc fog guess {str(curTile)}')

        if curTile.player >= 0 and curTile.isCity and curTile in self.map.players[curTile.player].cities:
            self.map.players[curTile.player].cities.remove(curTile)

        self._flipped_by_army_tracker_this_turn.append((curTile.player, curTile))
        if curTile.player >= 0:
            self.dropped_fog_tiles_this_turn.add(curTile)

        curTile.reset_wrong_undiscovered_fog_guess()

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
        # walk backward through turn order till we go negative
        maxDist = 0
        armyLeft = armyInFog  # - (player.cityCount - 1) // 2  # for each 2 cities (after general), they must leave behind a 2 instead of a 1, so
        turn = self.map.turn
        while True:
            if turn & 1 == 0:
                if armyLeft <= 0:
                    break
                armyLeft -= cityCount

            if turn % 50 == 0:
                armyLeft -= player.tileCount - SearchUtils.count(player.tiles, lambda t: t.visible)

            turn -= 1
            maxDist += 1

        return maxDist

