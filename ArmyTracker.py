"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import annotations

import SearchUtils
from DataModels import Move
from SearchUtils import *
from Path import Path
from base.client.map import Tile, TILE_OBSTACLE, TileDelta


class Army(object):
    start = 'A'
    end = 'z'
    curLetter = start

    def get_letter(self):
        ch = Army.curLetter
        if (ord(ch) + 1 > ord(Army.end)):
            Army.curLetter = Army.start
        else:
            Army.curLetter = chr(ord(ch) + 1)
            while Army.curLetter in ['[', '\\', ']', '^', '_', '`']:
                Army.curLetter = chr(ord(Army.curLetter) + 1)
        return ch

    def __init__(self, tile: Tile):
        self.tile: Tile = tile
        self.path: Path = Path()
        self.player: int = tile.player
        self.visible: bool = tile.visible
        self.value: int = 0
        """Always the value of the tile, minus one. For some reason."""
        self.update_tile(tile)
        self.expectedPaths: typing.List[Path] = []
        self.entangledArmies: typing.List[Army] = []
        self.name = self.get_letter()
        self.entangledValue = None
        self.scrapped = False
        self.last_moved_turn: int = 0
        self.last_seen_turn: int = 0

    def update_tile(self, tile):
        if self.path.tail is None or self.path.tail.tile != tile:
            self.path.add_next(tile)

        if self.tile != tile:
            self.tile = tile

        self.update()

    def update(self):
        if self.tile.visible:
            self.value = self.tile.army - 1
        self.visible = self.tile.visible

    def get_split_for_fog(self, fogTiles: typing.List[Tile]) -> typing.List[Army]:
        split = []
        for tile in fogTiles:
            splitArmy = self.clone()
            splitArmy.entangledValue = self.value
            if self.entangledValue is not None:
                splitArmy.entangledValue = self.entangledValue
            split.append(splitArmy)
        # entangle the armies
        for existingEntangled in self.entangledArmies:
            existingEntangled.entangledArmies.extend(split)
        for splitBoi in split:
            splitBoi.entangledArmies.extend(where(split, lambda army: army != splitBoi))
        logging.info(f"for army {self.toString()} set self as scrapped because splitting for fog")
        self.scrapped = True
        return split

    def clone(self):
        newDude = Army(self.tile)
        if self.path is not None:
            newDude.path = self.path.clone()
        newDude.player = self.player
        newDude.visible = self.visible
        newDude.value = self.value
        newDude.last_moved_turn = self.last_moved_turn
        for path in self.expectedPaths:
            newDude.expectedPaths.append(path.clone())
        newDude.entangledArmies = list(self.entangledArmies)
        newDude.name = self.name
        newDude.scrapped = self.scrapped
        return newDude

    def toString(self):
        return f"[{self.name} {self.tile} p{self.player} v{self.value}{' scr' if self.scrapped else ''}]"

    def __str__(self):
        return self.toString()

    def __repr__(self):
        return self.toString()

    def include_path(self, path: Path):
        if path is None:
            return

        foundMatch = False
        for existingPath in self.expectedPaths:
            pathNode = path.start
            existingPathNode = existingPath.start

            isPathMatch = True
            while pathNode is not None and existingPathNode is not None:
                if pathNode.tile != existingPathNode.tile:
                    isPathMatch = False
                    break

                pathNode = pathNode.next
                existingPathNode = existingPathNode.next

            if pathNode is not None or existingPathNode is not None:
                # then one was longer than the other, also false
                isPathMatch = False

            if isPathMatch:
                foundMatch = True
                break

        if not foundMatch:
            self.expectedPaths.append(path)


class PlayerAggressionTracker(object):
    def __init__(self, index):
        self.player = index


class ArmyTracker(object):
    def __init__(self, map: MapBase):
        self.player_moves_this_turn: typing.Set[int] = set()
        self.map: MapBase = map
        self.armies: typing.Dict[Tile, Army] = {}
        self.genDistances: typing.List[typing.List[int]] = []
        """Actual armies. During a scan, this stores the armies that haven't been dealt with since last turn, still."""

        self.unaccounted_tile_diffs: typing.Dict[Tile, int] = {}
        """
        Used to keep track of messy army interaction diffs discovered when determining an army didn't 
        do exactly what was expected to use to infer what armies on adjacent tiles did.
        Negative numbers mean attacked by opp, (or opp tile attacked by friendly army).
        Positive would mean ally merged with our army (or enemy ally merged with enemy army...?)
        """

        self.valid_general_positions_by_player: typing.List[MapMatrix[bool]] = [MapMatrix(map, False) for _ in self.map.players]
        """The true/false matrix of valid general positions by player"""

        self.tiles_ever_owned_by_player: typing.List[typing.Set[Tile]] = [set([t for t in player.tiles if t.visible or t.discovered]) for player in self.map.players]
        """The set of tiles that we've ever seen owned by a player. TODO exclude tiles from player captures...?"""

        self.uneliminated_emergence_events: typing.List[typing.Dict[Tile, int]] = [{} for player in self.map.players]
        """The set of emergence events that have resulted in general location restrictions in the past and have not been dropped in favor of more restrictive restrictions."""

        self.seen_player_lookup: typing.List[bool] = [False for player in self.map.players]
        """Whether a player has been seen."""

        self.is_long_spawns: bool = len(self.map.players) == 2

        self.min_spawn_distance: int = 9
        if self.is_long_spawns:
            self.min_spawn_distance = 15

        self._initialize_viable_general_positions()

        self.player_launch_timings = [0 for _ in self.map.players]

        self.updated_city_tiles: typing.Set[Tile] = set()
        """Cities that were revealed or changed players or mountains that were fog-guess-cities will get stuck here during map updates."""

        self.lastMove: Move | None = None
        self.track_threshold: int = 10
        """Minimum tile value required to track an 'army' for performance reasons."""
        self.update_track_threshold()

        self._flipped_tiles: typing.Set[Tile] = set()

        self.fogPaths = []
        self.emergenceLocationMap: typing.List[typing.List[typing.List[int]]] = [
            [[0 for x in range(self.map.rows)] for y in range(self.map.cols)] for z in range(len(self.map.players))]
        """List by player of emergence values."""

        self.player_targets: typing.List[Tile] = []
        """The list of tiles we expect an enemy player might be trying to attack."""

        self.notify_unresolved_army_emerged: typing.List[typing.Callable[[Tile], None]] = []
        self.notify_army_moved: typing.List[typing.Callable[[Army], None]] = []

        self.player_aggression_ratings = [PlayerAggressionTracker(z) for z in range(len(self.map.players))]
        self.lastTurn = -1
        self.decremented_fog_tiles_this_turn: typing.Set[Tile] = set()
        self.dropped_fog_tiles_this_turn: typing.Set[Tile] = set()

    def __getstate__(self):
        state = self.__dict__.copy()

        if 'notify_unresolved_army_emerged' in state:
            del state['notify_unresolved_army_emerged']

        if 'notify_army_moved' in state:
            del state['notify_army_moved']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.notify_unresolved_army_emerged = []
        self.notify_army_moved = []

    # distMap used to determine how to move armies under fog
    def scan(self, lastMove: Move | None, turn: int, genDistances: typing.List[typing.List[int]]):
        self.lastMove = lastMove
        self.genDistances = genDistances
        self.decremented_fog_tiles_this_turn = set()
        self.dropped_fog_tiles_this_turn = set()
        if self.map.turn < 50:
            for player in self.map.players:
                if self.player_launch_timings[player.index] == 0 and player.tileCount > 1:
                    if player.tileCount > 2:
                        self.player_launch_timings[player.index] = 18
                    else:
                        self.player_launch_timings[player.index] = self.map.turn - 1

        self._handle_flipped_tiles()

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
                logging.info('armyTracker last turn wasnt set, exclusively scanning for new armies to avoid pushing fog tiles around on the turn the map was loaded up')
                self.lastTurn = turn
                self.find_new_armies()
                return

            self.lastTurn = turn
            self.player_moves_this_turn: typing.Set[int] = set()
        else:
            logging.info(f'army tracker scan ran twice this turn {turn}...? Bailing?')
            return

        # if we have perfect info about a players general / cities, we don't need to track emergence, clear the emergence map
        for player in self.map.players:
            if self.has_perfect_information_of_player_cities_and_general(player.index):
                self.emergenceLocationMap[player.index] = [
                    [0 for x in range(self.map.rows)] for y in range(self.map.cols)
                ]

        self.fogPaths = []

        self.track_army_movement()
        self.find_new_armies()

        if advancedTurn:
            self.move_fogged_army_paths()

        self.verify_player_tile_and_army_counts_valid()

        for army in self.armies.values():
            if army.tile.visible:
                army.last_seen_turn = self.map.turn

        for player in self.map.players:
            if len(player.tiles) > 0:
                self.seen_player_lookup[player.index] = True

    def move_fogged_army_paths(self):
        for army in list(self.armies.values()):
            if army.tile.visible:
                continue
            if army.player == self.map.player_index or army.player in self.map.teammates:
                self.scrap_army(army, scrapEntangled=False)
                continue
            if army.last_moved_turn == self.map.turn - 1:
                army.value = army.tile.army - 1
                continue

            if army.player in self.player_moves_this_turn:
                continue
            #
            # if army.scrapped:
            #     continue

            logging.info(f'moving fogged army paths for {str(army)}')

            fogPathNexts = {}
            for path in army.expectedPaths:
                if (path is None
                        or path.start is None
                        or path.start.next is None
                        or path.start.next.tile is None
                ):
                    continue

                nextPaths = fogPathNexts.get(path.start.next.tile, [])
                nextPaths.append(path)
                fogPathNexts[path.start.next.tile] = nextPaths

            if len(fogPathNexts) > 1:
                nextArmies = army.get_split_for_fog(list(fogPathNexts.keys()))

                for nextTile, paths in fogPathNexts.items():
                    nextArmy = nextArmies.pop()
                    # nextArmy.expectedPaths = where(nextArmy.expectedPaths, lambda p: p.start.next.tile == nextTile)
                    nextArmy.expectedPaths = []

                    first = True
                    for path in paths:
                        nextArmy.expectedPaths.append(path)
                        if path.start.next.tile.visible:
                            logging.info(f'for army {str(nextArmy)} ignoring SPLIT fog path move into visible: {str(path)}')
                            continue

                        logging.info(f'respecting army {str(nextArmy)} SPLIT fog path: {str(path)}')

                        self._move_fogged_army_along_path(nextArmy, path)

                        logging.info(f'AFTER: army {str(nextArmy)}: {str(nextArmy.expectedPaths)}')
                        # if first:
                        # else:
                        #     path.made_move()
                        first = False
                    if not nextArmy.scrapped:
                        self.armies[nextArmy.tile] = nextArmy

            elif len(fogPathNexts) == 1:
                first = True
                for path in army.expectedPaths:
                    if path is not None and path.start.next is not None and path.start.next.tile.visible:
                        logging.info(f'for army {str(army)} ignoring fog path move into visible: {str(path)}')
                        continue

                    logging.info(f'respecting army {str(army)} fog path: {str(path)}')

                    self._move_fogged_army_along_path(army, path)

                    logging.info(f'AFTER: army {str(army)}: {str(army.expectedPaths)}')
                    # if first:
                    # elif path.length > 0:
                    #     path.made_move()
                    first = False

    def clean_up_armies(self):
        for army in list(self.armies.values()):
            if army.scrapped:
                logging.info(f"Army {str(army)} was scrapped last turn, deleting.")
                if army.tile in self.armies and self.armies[army.tile] == army:
                    del self.armies[army.tile]
                continue
            elif (army.player == self.map.player_index or army.player in self.map.teammates) and not army.tile.visible:
                logging.info(f"Army {str(army)} was ours but under fog now, so was destroyed. Scrapping.")
                self.scrap_army(army, scrapEntangled=True)
            elif army.tile.visible and len(army.entangledArmies) > 0 and army.tile.player == army.player:
                if army.tile.army * 1.2 > army.value > (army.tile.army - 1) * 0.8:
                    # we're within range of expected army value, resolve entanglement :D
                    logging.info(f"Army {str(army)} was entangled and rediscovered :D disentangling other armies")
                    self.resolve_entangled_armies(army)
                else:
                    logging.info(
                        f"Army {str(army)} was entangled at this tile, but army value doesn't match expected?\n  - NOT army.tile.army * 1.2 ({army.tile.army * 1.2}) > army.value ({army.value}) > (army.tile.army - 1) * 0.8 ({(army.tile.army - 1) * 0.8})")
                    for entangled in army.entangledArmies:
                        logging.info(f"    removing {str(army)} from entangled {str(entangled)}")
                        try:
                            entangled.entangledArmies.remove(army)
                        except:
                            pass
                    if army.tile in self.armies and self.armies[army.tile] == army:
                        del self.armies[army.tile]
                continue
            elif army.tile.delta.gainedSight and (
                    army.tile.player == -1 or (army.tile.player != army.player and len(army.entangledArmies) > 0)):
                logging.info(
                    f"Army {str(army)} just uncovered was an incorrect army prediction. Disentangle and remove from other entangley bois")
                for entangled in army.entangledArmies:
                    logging.info(f"    removing {str(army)} from entangled {str(entangled)}")
                    entangled.entangledArmies.remove(army)

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
                        logging.info(f'RESPECTING MAP DETERMINED PLAYER MOVE {str(src)}->{str(dest)} BY p{player.index} FOR ARMY {str(armyAtSrc)}')
                        self.army_moved(armyAtSrc, dest, trackingArmies, dontUpdateOldFogArmyTile=True)  # map already took care of this for us
                        skip.add(src)
                    else:
                        logging.info(f'ARMY {str(armyAtSrc)} AT SOURCE OF PLAYER {player.index} MOVE {str(src)}->{str(dest)} DID NOT MATCH THE PLAYER THE MAP DETECTED AS MOVER, SCRAPPING ARMY...')
                        self.scrap_army(armyAtSrc, scrapEntangled=False)

        self.unaccounted_tile_diffs: typing.Dict[Tile, int] = {}
        for tile, diffTuple in self.map.army_emergences.items():
            emergedAmount, emergingPlayer = diffTuple
            if emergingPlayer == -1:
                continue

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
                    logging.info(
                        f'gainedSight splitting existingArmy back into fog 1 - emerged {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                    self.try_split_fogged_army_back_into_fog(existingArmy, trackingArmies)
                    skip.add(tile)
                else:
                    logging.info(f'IGNORING maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                continue

            # Jump straight to fog source detection.
            if tile.delta.toTile is not None:
                # the map does its job too well and tells us EXACTLY where the army emerged from, but armytracker wants the armies final destination and will re-do that work itself, so use the toTile.
                # tile = tile.delta.toTile
                if tile.delta.toTile in skip:
                    continue

            if tile.isCity and tile.discovered:
                logging.info(f'IGNORING maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it was a discovered city..?')
                continue

            if existingArmy and existingArmy.player == tile.player and existingArmy.value + 1 > tile.army:
                logging.info(f'TODO CHECK IF EVER CALLED splitting existingArmy back into fog 2 - emerged {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} because it appears to have been a move INTO fog. Will be tracked via emergence.')
                self.try_split_fogged_army_back_into_fog(existingArmy, trackingArmies)
                skip.add(tile)
                continue

            if emergedAmount < 0:
                emergedAmount = 0 - emergedAmount

            if len(self.map.players[emergingPlayer].tiles) < 4:
                emergedAmount += 7

            logging.info(f'Respecting maps determined unexplained emergence of {emergedAmount} by player {emergingPlayer} on tile {repr(tile)} (from tile if known {repr(tile.delta.fromTile)})')
            emergedArmy = self.handle_unaccounted_delta(tile, emergingPlayer, emergedAmount)
            if emergedArmy is not None:
                if tile.delta.toTile is not None and tile.delta.toTile.player == emergedArmy.player:
                    self.army_moved(emergedArmy, tile.delta.toTile, trackingArmies)
                    skip.add(tile.delta.toTile)
                else:
                    trackingArmies[tile] = emergedArmy
            skip.add(tile)

        for tile in self.map.get_all_tiles():
            if tile in skip:
                continue
            if self.lastMove is not None and tile == self.lastMove.source:
                continue
            if tile.delta.toTile is None:
                continue
            if tile.isUndiscoveredObstacle or tile.isMountain:
                msg = f'are we really sure {str(tile)} moved to {str(tile.delta.toTile)}'
                if BYPASS_TIMEOUTS_FOR_DEBUGGING:
                    raise AssertionError(msg)
                else:
                    logging.error(msg)
                    continue
            if tile.delta.toTile.isMountain:
                msg = f'are we really sure {str(tile.delta.toTile)} was moved to from {str(tile)}'
                if BYPASS_TIMEOUTS_FOR_DEBUGGING:
                    raise AssertionError(msg)
                else:
                    logging.error(msg)
                    continue

            # armyDetectedAsMove = self.armies.get(tile, None)
            # if armyDetectedAsMove is not None:
            armyDetectedAsMove = self.get_or_create_army_at(tile)
            logging.info(f'Map detected army move, honoring that: {str(tile)}->{str(tile.delta.toTile)}')
            self.army_moved(armyDetectedAsMove, tile.delta.toTile, trackingArmies)
            if tile.delta.toTile.isUndiscoveredObstacle:
                tile.delta.toTile.isCity = True
                tile.delta.toTile.player = armyDetectedAsMove.player
                tile.delta.toTile.army = armyDetectedAsMove.value
                logging.warning(f'CONVERTING {str(tile.delta.toTile)} UNDISCOVERED MOUNTAIN TO CITY DUE TO MAP SAYING DEFINITELY TILE MOVED THERE. {str(tile)}->{str(tile.delta.toTile)}')
            armyDetectedAsMove.update()
            if not tile.delta.toTile.visible:
                # map knows what it is doing, force tile army update.
                armyDetectedAsMove.value = tile.delta.toTile.army - 1

        for army in sorted(self.armies.values(), key=lambda a: self.genDistances[a.tile.x][a.tile.y]):
            # any of our armies CANT have moved (other than the one handled explicitly above), ignore them, let other armies collide with / capture them.
            if army.player == self.map.player_index:
                if army.last_moved_turn < self.map.turn - 1 and army.tile.army < self.track_threshold:
                    self.scrap_army(army, scrapEntangled=False)
                else:
                    army.update()
                continue

            self.try_track_army(army, skip, trackingArmies)

        self.scrap_unmoved_low_armies()

        for armyDetectedAsMove in trackingArmies.values():
            self.armies[armyDetectedAsMove.tile] = armyDetectedAsMove

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
                logging.info(
                    f"  Find visible source  {str(tile)} ({tile.delta.armyDelta}) <- {adjacent.toString()} ({unexplainedAdjDelta}) ? {isMatch}")
                return adjacent

        # try more lenient
        for adjacent in tile.movable:
            isMatch = False
            unexplainedAdjDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
            if 2 >= tile.delta.armyDelta + unexplainedAdjDelta >= -2:
                isMatch = True

            logging.info(
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
                logging.error(f'Yo, we think player {army.player} moved twice this turn...? {str(army)} -> {str(toTile)}')

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
            logging.info(f"    Army {str(army)} scrapped for being negative or run into larger tile")
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
            army.expectedPaths = self.get_army_expected_path(army)
            logging.info(f'set army {str(army)} expected paths to {str(army.expectedPaths)}')

        army.last_moved_turn = self.map.turn - 1

        for listener in self.notify_army_moved:
            listener(army)

    def scrap_army(self, army: Army, scrapEntangled: bool):
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
            logging.info(f"{str(army)} resolving {len(army.entangledArmies)} entangled armies")
            for entangledArmy in army.entangledArmies:
                logging.info(f"    {entangledArmy.toString()} entangled")
                if entangledArmy.tile in self.armies:
                    del self.armies[entangledArmy.tile]
                entangledArmy.scrapped = True
                if not entangledArmy.tile.visible and entangledArmy.tile.army > 0:
                    # remove the army value from the tile?
                    newArmy = max(entangledArmy.tile.army - entangledArmy.entangledValue, 1)
                    logging.info(
                        f"    updating entangled army tile {entangledArmy.toString()} from army {entangledArmy.tile.army} to {newArmy}")
                    entangledArmy.tile.army = newArmy
                    if not entangledArmy.tile.discovered and entangledArmy.tile.player >= 0:
                        entangledArmy.tile.reset_wrong_undiscovered_fog_guess()

                entangledArmy.entangledArmies = []
            army.entangledArmies = []

    def army_could_capture(self, army, fogTargetTile):
        if army.player != fogTargetTile.player:
            return army.value > fogTargetTile.army
        return True

    def move_fogged_army(self, army: Army, fogTargetTile: Tile):
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
        logging.info(f"      fogTargetTile {fogTargetTile.toString()} updated army to {fogTargetTile.army}")
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
        # super fast depth 2 bfs effectively
        nearbyArmies = []
        for tile in army.tile.movable:
            if tile in armyMap:
                nearbyArmies.append(armyMap[tile])
            for nextTile in tile.movable:
                if nextTile != army.tile and nextTile in armyMap:
                    nearbyArmies.append(armyMap[nextTile])
        for nearbyArmy in nearbyArmies:
            logging.info(f"Army {str(army)} had nearbyArmy {str(nearbyArmy)}")
        return nearbyArmies

    def find_new_armies(self):
        logging.info("Finding new armies:")
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
        for tile in self.map.pathableTiles:
            notOurMove = (self.lastMove is None or (tile != self.lastMove.source and tile != self.lastMove.dest))

            movingPlayer = tile.player
            anyPlayersMoves = playerMoves.get(tile, None)

            if anyPlayersMoves is not None:
                movingPlayer = [p for p in anyPlayersMoves][0]

            # if tile.delta.oldOwner != self.map.player_index and (tile.delta.oldOwner != tile.delta.newOwner or tile.delta.unexplainedDelta > 0):
            #     self.handle_unaccounted_delta(tile, movingPlayer, unaccountedForDelta=abs(tile.delta.unexplainedDelta))

            tileNewlyMovedByEnemy = (
                tile not in self.armies
                and not tile.delta.gainedSight
                and tile.player != self.map.player_index
                and abs(tile.delta.armyDelta) > 2
                and tile.army > 2
                and notOurMove
            )

            # if we moved our army into a spot last turn that a new enemy army appeared this turn
            tileArmy = self.armies.get(tile, None)

            if (
                (tileArmy is None or tileArmy.scrapped)
                and tile.player != -1
                and (
                    playerLargest[tile.player] == tile
                    or tile.army > self.track_threshold
                    or tileNewlyMovedByEnemy
                )
            ):
                logging.info(
                    f"{str(tile)} Discovered as Army! (tile.army {tile.army}, tile.delta {tile.delta.armyDelta}) - no fog emergence")

                army = self.get_or_create_army_at(tile)
                if not army.visible:
                    army.value = army.tile.army - 1
            # if tile WAS bordered by fog find the closest fog army and remove it (not tile.visible or tile.delta.gainedSight)

    def new_army_emerged(self, emergedTile: Tile, armyEmergenceValue: int):
        """
        when an army can't be resolved to coming from the fog from a known source, this method gets called to track its emergence location.
        @param emergedTile:
        @param armyEmergenceValue:
        @return:
        """

        if emergedTile.player == self.map.player_index or emergedTile.player in self.map.teammates:
            return

        emergingPlayer = emergedTile.player

        # largest = [0]
        # largestTile = [None]

        if not self.has_perfect_information_of_player_cities_and_general(emergingPlayer):
            distance = self.min_spawn_distance + 1

            armyEmergenceValue = 2 + (armyEmergenceValue ** 0.75)

            if armyEmergenceValue > 10:
                armyEmergenceValue = 10

            # # armyEmergenceValue =
            # if self.map.turn <= 30:
            #     armyEmergenceValue += 5
            # elif self.map.turn <= 50:
            #     armyEmergenceValue += 3
            # elif self.map.turn <= 60:
            #     armyEmergenceValue += 2
            # elif self.map.turn <= 100:
            #     armyEmergenceValue += 1

            armyEmergenceScaledToTurns = 5 * armyEmergenceValue / (5 + self.map.turn // 25)

            logging.info(f"running new_army_emerged for tile {str(emergedTile)} with emValueScaled {armyEmergenceScaledToTurns:.2f}, distance {distance}")

            def foreachFunc(tile, dist):
                distCapped = max(4, dist)
                emergeValue = 4 * armyEmergenceScaledToTurns // distCapped
                # if self.valid_general_positions_by_player[emergingPlayer][tile]:
                self.emergenceLocationMap[emergedTile.player][tile.x][tile.y] += max(1, emergeValue)
                    # if largest[0] < self.emergenceLocationMap[emergedTile.player][tile.x][tile.y]:
                    #     largestTile[0] = tile
                    #     largest[0] = self.emergenceLocationMap[emergedTile.player][tile.x][tile.y]

            def negative_func(tile: Tile):
                return tile.discovered

            def skip_func(tile: Tile):
                visibleOrDiscNeut = (tile.was_visible_last_turn() or (tile.discoveredAsNeutral and self.map.turn <= 100))
                return (tile.isObstacle or visibleOrDiscNeut) and tile != emergedTile

            breadth_first_foreach_dist(self.map, [emergedTile], distance, foreachFunc, negative_func, skip_func, bypassDefaultSkip=True)

        for handler in self.notify_unresolved_army_emerged:
            handler(emergedTile)

    def tile_discovered_neutral(self, neutralTile: Tile):
        logging.info(f"running tile_discovered_neutral for tile {neutralTile.toString()}")

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

    def find_fog_source(self, armyPlayer: int, tile: Tile, delta: int | None = None) -> Path | None:
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
        missingCities = max(0, armyPlayerObj.cityCount - 1 - len(where(armyPlayerObj.cities, lambda c: c.discovered)))

        allowVisionlessObstaclesAndCities = False
        candidates = where(tile.movable,
                     lambda adj: not adj.isNotPathable and adj.was_not_visible_last_turn())

        wasDiscoveredEnemyTile = tile.delta.oldOwner == -1 and tile.delta.gainedSight

        prioritizeCityWallSource = self.detect_army_likely_breached_wall(armyPlayer, tile, delta)

        if (
            len(candidates) == 0
            or missingCities > 0  # TODO questionable
        ):
            if missingCities > 0:
                logging.info(f"        For new army at tile {str(tile)}, checking for undiscovered city emergence")
                allowVisionlessObstaclesAndCities = True
            else:
                logging.info(f"        For new army at tile {str(tile)} there were no adjacent fogBois and no missing cities, give up...?")
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
                    logging.info(
                        f"using moveHalfVal {moveHalfVal:.1f} over val {val:.1f} for tile {str(thisTile)} turn {self.map.turn}")
                    val = moveHalfVal
            elif not thisTile.discovered:
                negArmy -= max(1, int(self.emergenceLocationMap[armyPlayer][thisTile.x][thisTile.y] ** 0.25) - 1)
                val += 3 - 3 / max(1, self.emergenceLocationMap[armyPlayer][thisTile.x][thisTile.y])

            # closest path value to the actual army value. Fake tuple for logging.
            # 2*abs for making it 3x improvement on the way to the right path, and 1x unemprovement for larger armies than the found tile
            # negative weighting on dist to try to optimize for shorter paths instead of exact
            return val - citiesConverted * 10 - dist - negBonusScore, 0 - citiesConverted

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

                undiscVal = self.emergenceLocationMap[armyPlayer][nextTile.x][nextTile.y]

                if nextTile.discovered:
                    negBonusScore -= 5

                if prioritizeCityWallSource:
                    if nextTile.isUndiscoveredObstacle:
                        negBonusScore -= undiscVal
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
                    undiscVal = self.emergenceLocationMap[armyPlayer][nextTile.x][nextTile.y]
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
                meetsCriteria = nextTile in self.tiles_ever_owned_by_player[armyPlayer] or self.valid_general_positions_by_player[armyPlayer][nextTile] or theArmy is not None

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

            # logging.info("nextTile {}: negArmy {}".format(nextTile.toString(), negArmy))
            return (
                    False
                    or (nextTile.visible and not nextTile.delta.gainedSight and not (wasDiscoveredEnemyTile and self.is_friendly_team(nextTile.player, tile.player)))
                    or turnsNegative > 6
                    or consecutiveUndiscovered > 20
                    or dist > 30
            )

        inputTiles = {}
        logging.info(f"Looking for fog army path of value {delta} to tile {str(tile)}, prioritizeCityWallSource {prioritizeCityWallSource}")
        # we want the path to get army up to 0, so start it at the negative delta (positive)
        inputTiles[tile] = ((0, 0, delta, 0, 0, 0, 0, False), 0)

        depthLimit = self.min_spawn_distance

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
            logging.info(
                f"        For new army at tile {str(tile)} we found fog source path???? {str(fogSourcePath)}")
        else:
            logging.info(f"        NO fog source path for new army at {str(tile)}")
        return fogSourcePath

    def find_next_fog_city_candidate_near_tile(self, cityPlayer: int, tile: Tile, cutoffDist: int = 10) -> Tile | None:
        """
        Looks for a fog city candidate nearby a given tile
        @param cityPlayer:
        @param tile:
        @return:
        """

        armyPlayerObj = self.map.players[cityPlayer]
        missingCities = armyPlayerObj.cityCount - 1 - len(armyPlayerObj.cities)
        if missingCities == 0:
            return

        def valFunc(
                thisTile: Tile,
                prioObject
        ):
            dist, _ = prioObject
            if thisTile.visible:
                return None

            isPotentialFogCity = thisTile.isCity and thisTile.isNeutral
            isPotentialFogCity = isPotentialFogCity or thisTile.isUndiscoveredObstacle
            if not isPotentialFogCity:
                return None

            return self.emergenceLocationMap[cityPlayer][thisTile.x][thisTile.y] / dist, True  # has to be tuple or logging blows up i guess

        def pathSortFunc(
                nextTile: Tile,
                prioObject
        ):
            (dist, _) = prioObject

            dist += 1
            if nextTile.isUndiscoveredObstacle:
                # try to path around obstacles over going through them..? Takes 2 extra moves to 
                # go around an obstacle to the other side so at minimum make it cost that 
                # much extra so going around is otherwise equal to through
                dist += 2

            return dist, 0

        def fogSkipFunc(
                nextTile: Tile,
                prioObject
        ):
            if prioObject is None:
                return True

            (dist, _) = prioObject

            # logging.info("nextTile {}: negArmy {}".format(nextTile.toString(), negArmy))
            return (
                    (nextTile.visible and not nextTile.delta.gainedSight)
                    or (nextTile.discoveredAsNeutral and self.map.turn < 400)
                    or dist > cutoffDist
            )

        inputTiles = {}
        logging.info(f"FINDING NEXT FOG CITY FOR PLAYER {cityPlayer} for not-fog-city tile {str(tile)}")
        # we want the path to get army up to 0, so start it at the negative delta (positive)
        inputTiles[tile] = ((0, 0), 0)

        fogSourcePath = breadth_first_dynamic_max(
            self.map,
            inputTiles,
            valFunc,
            maxTime=100000.0,
            noNeutralCities=False,
            noNeutralUndiscoveredObstacles=False,
            priorityFunc=pathSortFunc,
            skipFunc=fogSkipFunc,
            searchingPlayer=cityPlayer,
            logResultValues=True,
            noLog=False)
        if fogSourcePath is not None:
            newFogCity = fogSourcePath.tail.tile
            self.convert_fog_city_to_player_owned(newFogCity, cityPlayer)
            logging.info(
                f"        Found new fog city!???? {str(newFogCity)}")
            return newFogCity

        else:
            logging.info(f"        NO alternate fog city found for {str(tile)}")

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

        logging.info(f'Looking for fog city near {str(tile)} for player {cityPlayerIndex} with extraCities {extraCities} from discovered city.')

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
            logging.info(f'Found removable fog city {str(badCity)} via path {str(badCityPath)}')
            if extraCities > 0 or badCityPath.length <= distanceIfNotExcessCities:
                logging.info(f'  Fog city {str(badCity)} removed.')
                badCity.reset_wrong_undiscovered_fog_guess()
                self.map.players[cityPlayerIndex].cities.remove(badCity)
                extraCities -= 1
            else:
                logging.info(f'  Fog city {str(badCity)} NOT REMOVED due to not meeting length / excess city requirements.')
        else:
            logging.info(f'  No fog city path found to remove.')

    def resolve_fog_emergence(
            self,
            player: int,
            sourceFogArmyPath: Path,
            fogTile: Tile
    ) -> Army | None:
        existingArmy = None
        armiesFromFog = []
        existingArmy = self.armies.pop(fogTile, None)
        if existingArmy is not None and existingArmy.player == player:
            armiesFromFog.append(existingArmy)

        node = sourceFogArmyPath.start.next
        while node is not None:
            logging.info(f"resolve_fog_emergence tile {str(node.tile)}")
            fogArmy = self.armies.pop(node.tile, None)
            if fogArmy is not None and self.is_friendly_team(fogArmy.player, player):
                logging.info(f"  ^ was army {str(node.tile)}")
                armiesFromFog.append(fogArmy)
            if not node.tile.visible:
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
                    logging.info(f"  ^ scrapping {str(army)} as it was not largest on emergence path")
                    self.scrap_army(army, scrapEntangled=True)

            self.resolve_entangled_armies(maxArmy)
            logging.info(f'set fog source for {str(fogTile)} to {str(maxArmy)}')
            maxArmy.update_tile(fogTile)
            maxArmy.update()
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
            logging.info(f'executing OUR move {str(self.map.last_player_index_submitted_move)}')

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
            logging.info(f"Army {str(army)} was in skip set. Skipping")
            return
        # army may have been removed (due to entangled resolution)
        if armyTile not in self.armies:
            logging.info(f"Skipped armyTile {armyTile.toString()} because no longer in self.armies?")
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
            logging.info(f'army didnt move...? {str(army)}')
            army.update()
            return

        # if armyRealTileDelta == 0 and armyTile.visible:
        #     # Army didn't move...?
        #     continue
        logging.info(
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
                logging.info(
                    f"  adjacent delta raw {adjacent.delta.armyDelta} expectedAdjDelta {expectedAdjDelta}")
                logging.info(
                    f"  armyDeltas: army {str(army)} {armyRealTileDelta} - adj {adjacent.toString()} {adjDelta} expAdj {expectedAdjDelta}")
                # expectedDelta is fine because if we took the expected tile we would get the same delta as army remaining on army tile.
                if ((armyRealTileDelta > 0 or
                     (not army.tile.visible and
                      adjacent.visible and
                      adjacent.delta.armyDelta != expectedAdjDelta)) and
                        adjDelta - armyRealTileDelta == army.tile.delta.expectedDelta):
                    foundLocation = True
                    logging.info(
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
                    logging.info(f"    WHOO! Army {str(army)} moved into fog at {fogBois[0].toString()}!?")
                    self.move_fogged_army(army, fogTarget)
                    if fogCount == 1:
                        logging.info("closestFog and fogCount was 1, converting fogTile to be owned by player")
                        fogTarget.player = army.player
                    self.unaccounted_tile_diffs.pop(army.tile, None)
                    self.army_moved(army, fogTarget, trackingArmies, dontUpdateOldFogArmyTile=True)

                else:
                    # validFogDests = []
                    # for fogBoi in fogBois:
                    #
                    foundLocation = True
                    logging.info(f"    Army {str(army)} IS BEING ENTANGLED! WHOO! EXCITING!")
                    entangledArmies = army.get_split_for_fog(fogBois)
                    for i, fogBoi in enumerate(fogBois):
                        logging.info(
                            f"    Army {str(army)} entangled moved to {str(fogBoi)}")
                        self.move_fogged_army(entangledArmies[i], fogBoi)
                        self.unaccounted_tile_diffs.pop(entangledArmies[i].tile, None)
                        self.army_moved(entangledArmies[i], fogBoi, trackingArmies, dontUpdateOldFogArmyTile=True)
                return

            if army.player != army.tile.player and army.tile.was_visible_last_turn():
                logging.info(f"  Army {str(army)} got eated? Scrapped for not being the right player anymore")
                self.scrap_army(army, scrapEntangled=True)

        army.update()

    def get_or_create_army_at(
            self,
            tile: Tile,
            skip_expected_path: bool = False
    ) -> Army:
        army = self.armies.get(tile, None)
        if army is None:
            logging.info(f'creating new army at {str(tile)} in get_or_create.')
            army = Army(tile)
            army.last_moved_turn = self.map.turn
            if not tile.visible:
                army.last_moved_turn = self.map.turn - 2  # this should only really happen on incrementing fog cities or on initial unit test map load
                army.value = tile.army - 1

            if not skip_expected_path:
                army.expectedPaths = self.get_army_expected_path(army)
                logging.info(f'set army {str(army)} expected path to {str(army.expectedPaths)}')

            self.armies[tile] = army

        return army

    def handle_gathered_to_army(self, army: Army, skip: typing.Set[Tile], trackingArmies: typing.Dict[Tile, Army]):
        logging.info(
            f"Army {str(army)} tile was just gathered to (or city increment or whatever), nbd, update it.")
        unaccountedForDelta = abs(army.tile.delta.armyDelta)
        source = self.find_visible_source(army.tile)
        if source is None:
            logging.info(
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
                logging.info(
                    f"Army {str(army)} was gathered to visibly from source ARMY {sourceArmy.toString()} and will be merged as {larger.toString()}")
                skip.add(larger.tile)
                skip.add(smaller.tile)
                self.merge_armies(larger, smaller, army.tile)
                return
            else:
                logging.info(f"Army {str(army)} was gathered to visibly from source tile {source.toString()}")
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

        # only works when the source army is still visible
        if armyRealTileDelta > 0 and abs(unexplainedAdjDelta) - abs(armyRealTileDelta) == 0:
            logging.info(
                f"    Army probably moved from {str(army)} to {adjacent.toString()} based on unexplainedAdjDelta {unexplainedAdjDelta} vs armyRealTileDelta {armyRealTileDelta}")
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True
        elif not army.tile.visible and positiveUnexplainedAdjDelta > 1:
            if positiveUnexplainedAdjDelta * 1.1 - army.value > 0 and army.value > positiveUnexplainedAdjDelta // 2 - 1:
                logging.info(
                    f"    Army probably moved from {str(army)} to {adjacent.toString()} based on unexplainedAdjDelta {unexplainedAdjDelta} vs armyRealTileDelta {armyRealTileDelta}")
                self.unaccounted_tile_diffs[army.tile] = unexplainedSourceDelta - unexplainedAdjDelta
                self.unaccounted_tile_diffs.pop(adjacent, None)
                self.army_moved(army, adjacent, trackingArmies)
                return True
        elif adjacent.delta.gainedSight and armyRealTileDelta > 0 and positiveUnexplainedAdjDelta * 0.9 < armyRealTileDelta < positiveUnexplainedAdjDelta * 1.25:
            logging.info(
                f"    Army (WishyWashyFog) probably moved from {str(army)} to {adjacent.toString()}")
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True
        elif positiveUnexplainedAdjDelta != 0 and abs(positiveUnexplainedAdjDelta) - army.value == 0:
            # handle fog moves?
            logging.info(
                f"    Army (SOURCE FOGGED?) probably moved from {str(army)} to {adjacent.toString()}. adj (dest) visible? {adjacent.visible}")
            oldTile = army.tile
            if oldTile.army > army.value - positiveUnexplainedAdjDelta and not oldTile.visible:
                newArmy = adjacent.army
                logging.info(
                    f"Updating tile {oldTile.toString()} army from {oldTile.army} to {newArmy}")
                oldTile.army = army.value - positiveUnexplainedAdjDelta + 1

            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True

        return False

    def use_fog_source_path(
            self,
            armyTile: Tile,
            sourceFogArmyPath: Path,
            delta: int
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
                self.emergenceLocationMap[player][tile.x][tile.y] += increase

            dist += 1

        fogPath = sourceFogArmyPath.get_reversed()
        emergenceValueCovered = sourceFogArmyPath.value - armyTile.army
        self.fogPaths.append(fogPath)
        minRatio = 0.9

        isGoodResolution = emergenceValueCovered > delta * minRatio
        logging.info(
            f"emergenceValueCovered ({emergenceValueCovered}) > armyTile.army * {minRatio} ({armyTile.army * minRatio:.1f}) : {isGoodResolution}")
        if not isGoodResolution:
            armyEmergenceValue = max(4, delta - emergenceValueCovered)
            logging.info(
                f"  WAS POOR RESOLUTION! Adding emergence for player {armyTile.player} armyTile {armyTile.toString()} value {armyEmergenceValue}")
            self.new_army_emerged(armyTile, armyEmergenceValue)

        return isGoodResolution

    def check_for_should_scrap_unmoved_army(self, army: Army):
        thresh = self.track_threshold - 1
        if self.genDistances[army.tile.x][army.tile.y] < 5:
            thresh = 4
        if self.genDistances[army.tile.x][army.tile.y] < 2:
            thresh = 2

        if (
                (army.tile.visible and army.value < thresh)
                or (not army.tile.visible and army.value < thresh)
        ):
            logging.info(f"  Army {str(army)} Stopped moving. Scrapped for being low value")
            self.scrap_army(army, scrapEntangled=False)

    def scrap_unmoved_low_armies(self):
        for army in list(self.armies.values()):
            if army.last_moved_turn < self.map.turn - 1:
                self.check_for_should_scrap_unmoved_army(army)

    def get_army_expected_path(self, army: Army) -> typing.List[Path]:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the tiles,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """
        pathA = self.get_army_expected_path_non_flank(army)
        pathB = self.get_army_expected_path_flank(army)

        paths = []

        if pathB is not None and (pathA is None or pathB.length >= pathA.length // 2):
            paths.append(pathB)
            if pathA is not None:
                paths.append(pathA)
        elif pathA is not None:
            paths.append(pathA)
            if pathB is not None and pathB.length != pathA.length:
                paths.append(pathB)
        elif pathB is not None:
            paths.append(pathB)

        return paths

    def get_army_expected_path_non_flank(self, army: Army) -> Path | None:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the tiles,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """

        if army.tile.isCity and len(army.expectedPaths) == 0 and army.tile.lastMovedTurn < self.map.turn - 2:
            return None

        if army.player == self.map.player_index or army.player in self.map.teammates:
            return None

        armyDistFromGen = self.genDistances[army.tile.x][army.tile.y]

        def goalFunc(tile: Tile, armyAmt: int, dist: int) -> bool:
            # don't pick cities over general as tiles when they're basically the same distance from gen, pick gen if its within 2 tiles of other tiles.
            if dist + 2 < armyDistFromGen and tile in self.player_targets:
                return True
            if tile == self.map.generals[self.map.player_index]:
                return True
            return False

        skip = None
        if len(army.entangledArmies) > 0:
            skip = set()
            for entangled in army.entangledArmies:
                skip.add(entangled.tile)
                for entangledPath in entangled.expectedPaths:
                    skip.update(entangledPath.tileList)

        logging.info(f'Looking for army {str(army)}s expected movement path:')
        path = SearchUtils.breadth_first_find_queue(
            self.map,
            [army.tile],
            # goalFunc=lambda tile, armyAmt, dist: armyAmt + tile.army > 0 and tile in self.player_targets,  # + tile.army so that we find paths that reach tiles regardless of killing them.
            goalFunc=goalFunc,
            prioFunc=lambda t: (not t.visible, t.player == army.player, t.army if t.player == army.player else 0 - t.army),
            skipTiles=skip,
            maxTime=0.1,
            maxDepth=23,
            noNeutralCities=army.tile.army < 150,
            searchingPlayer=army.player,
            noLog=True)

        return path

    def get_army_expected_path_flank(self, army: Army) -> Path | None:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the tiles,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """

        if army.tile.isCity and len(army.expectedPaths) == 0 and army.tile.lastMovedTurn < self.map.turn - 2:
            return None

        if army.player == self.map.player_index or army.player in self.map.teammates:
            return None

        def valueFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile.visible:
                return None

            return 0 - self.genDistances[tile.x][tile.y], 0

        def prioFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile.visible:
                return None

            return self.genDistances[tile.x][tile.y], 0

        skip = set()

        for tile in self.map.get_all_tiles():
            if tile.visible:
                skip.add(tile)

        if len(army.entangledArmies) > 0:
            for entangled in army.entangledArmies:
                skip.add(entangled.tile)
                for entangledPath in entangled.expectedPaths:
                    skip.update(entangledPath.tileList)

        startTiles = {army.tile: ((0, 0), 0)}

        logging.info(f'Looking for army {str(army)}s expected movement path:')
        path = SearchUtils.breadth_first_dynamic_max(
            self.map,
            startTiles,
            # goalFunc=lambda tile, armyAmt, dist: armyAmt + tile.army > 0 and tile in self.player_targets,  # + tile.army so that we find paths that reach tiles regardless of killing them.
            valueFunc=valueFunc,
            priorityFunc=prioFunc,
            skipTiles=skip,
            maxTime=0.1,
            maxDepth=30,
            noNeutralCities=army.tile.army < 150,
            searchingPlayer=army.player,
            noLog=True)

        return path

    def convert_fog_city_to_player_owned(self, tile: Tile, player: int):
        if player == -1:
            raise AssertionError(f'lol player -1 in convert_fog_city_to_player_owned for tile {str(tile)}')
        wasUndiscObst = tile.isUndiscoveredObstacle
        tile.update(self.map, player, army=1, isCity=True, isGeneral=False)
        tile.update(self.map, TILE_OBSTACLE, army=0, isCity=False, isGeneral=False)
        tile.delta = TileDelta()
        if wasUndiscObst:
            tile.discovered = False
            tile.discoveredAsNeutral = False

        self.map.players[player].cities.append(tile)
        self.map.update_reachable()

    def handle_unaccounted_delta(self, tile: Tile, player: int, unaccountedForDelta: int) -> Army | None:
        """
        Sources a delta army amount from fog and announces army emergence if not well-resolved.
        Returns an army the army resolved to be, if one is found.
        DOES NOT create an army if a source fog army is not found.
        """

        if tile.delta.discovered and not tile.army > self.track_threshold and not unaccountedForDelta > self.track_threshold and len(self.map.players[player].tiles) > 4:
            return None

        sourceFogArmyPath = self.find_fog_source(player, tile, unaccountedForDelta)
        if sourceFogArmyPath is not None:
            self.use_fog_source_path(tile, sourceFogArmyPath, unaccountedForDelta)

            self.unaccounted_tile_diffs.pop(tile, 0)

            return self.resolve_fog_emergence(player, sourceFogArmyPath, tile)

        return None

    def add_need_to_track_city(self, city: Tile):
        logging.info(f'armytracker tracking updated city for next scan: {str(city)}')
        self.updated_city_tiles.add(city)

    def rescan_city_information(self):
        for city in self.updated_city_tiles:
            self.check_need_to_shift_fog_city(city)

            self.check_if_this_city_was_actual_fog_city_location(city)

        self.updated_city_tiles = set()

    def check_need_to_shift_fog_city(self, city: Tile) -> Tile | None:
        if city.delta.oldOwner == city.player:
            return None
        if city.delta.oldOwner == -1:
            return None
        if city.was_visible_last_turn():
            return None

        if len(self.map.players[city.delta.oldOwner].cities) >= self.map.players[city.delta.oldOwner].cityCount + 1:
            logging.info(f'Not shifting player {city.delta.oldOwner} city {str(city)} because already enough cities on the board.')
            return None

        return self.find_next_fog_city_candidate_near_tile(city.delta.oldOwner, city)

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
            if self.emergenceLocationMap[armyPlayer][sourceTile.x][sourceTile.y] <= 0:
                return False
            return True

        reasonablePath = SearchUtils.breadth_first_find_queue(self.map, [tile], reasonablePathDetector, noNeutralCities=True, maxDepth=8, noLog=True)
        if reasonablePath is not None:
            return False
        return True

    def verify_player_tile_and_army_counts_valid(self):
        """
        Makes sure we dont have too many fog tiles or too much fog army for what is visible and known on the player map.

        @return:
        """

        logging.info(f'PLAYER FOG TILE RE-EVALUATION')
        for player in self.map.players:
            actualTileCount = player.tileCount

            mapTileCount = len(player.tiles)

            visibleMapTileCount = 0

            for tile in player.tiles:
                if tile.visible:
                    visibleMapTileCount += 1

            if actualTileCount < mapTileCount:
                logging.info(f'reducing player {player.index} over-tiles')
                realDists = SearchUtils.build_distance_map(self.map, list(self.tiles_ever_owned_by_player[player.index]))

                # strip extra tiles
                tilesAsEncountered = PriorityQueue()
                for tile in player.tiles:
                    if not tile.discovered:
                        dist = realDists[tile.x][tile.y]
                        emergenceBonus = max(0, self.emergenceLocationMap[player.index][tile.x][tile.y])
                        tilesAsEncountered.put((emergenceBonus / (dist + 1) - 3 * dist + tile.army, tile))

                while mapTileCount > actualTileCount and not tilesAsEncountered.empty():
                    toRemove: Tile
                    score, toRemove = tilesAsEncountered.get()
                    if not toRemove.isCity:
                        logging.info(f'dropped player {player.index} over-tile tile {str(toRemove)}')
                        toRemove.reset_wrong_undiscovered_fog_guess()
                        mapTileCount -= 1
                        self.dropped_fog_tiles_this_turn.add(toRemove)
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
                logging.info(f'reducing player {player.index} over-score, actual {actualScore} vs map {mapScore}')
                # strip extra tiles
                tilesAsEncountered = PriorityQueue()
                for tile in player.tiles:
                    genCityDePriority = 0

                    if tile.isGeneral or tile.isCity:
                        genCityDePriority = 50

                    if tile in self.armies:
                        genCityDePriority += 10

                    tileArmy = self.armies.get(tile, None)
                    if not tile.visible and (tileArmy is None or len(tileArmy.entangledArmies) == 0):
                        dist = self.genDistances[tile.x][tile.y]
                        emergenceBonus = max(0, self.emergenceLocationMap[player.index][tile.x][tile.y])
                        tilesAsEncountered.put((emergenceBonus - tile.lastSeen + genCityDePriority - dist / 10, tile))

                while mapScore > actualScore and not tilesAsEncountered.empty():
                    toReduce: Tile
                    score, toReduce = tilesAsEncountered.get()
                    reduceTo = 1
                    if self.map.turn % 50 < 15:
                        reduceTo = 2

                    reduceBy = toReduce.army - reduceTo
                    if mapScore - reduceBy < actualScore:
                        reduceBy = mapScore - actualScore

                    logging.info(f'reducing player {player.index} over-score tile {str(toReduce)} by {reduceBy}')

                    toReduce.army = toReduce.army - reduceBy
                    mapScore -= reduceBy
                    self.decremented_fog_tiles_this_turn.add(toReduce)
                    army = self.armies.get(toReduce, None)
                    if army:
                        army.value = toReduce.army - 1
                        if army.value <= 0:
                            self.scrap_army(army, scrapEntangled=False)

    def get_tile_emergence_for_player(self, tile: Tile, player: int) -> int:
        if player == -1:
            return 0

        return self.emergenceLocationMap[player][tile.x][tile.y]

    def drop_incorrect_player_fog_around(self, neutralTile: Tile, forPlayer: int):
        logging.info(f'drop_incorrect_player_fog_around for player {forPlayer} wrong tile {str(neutralTile)}')
        q = deque()

        playerTileAdvantageDepth = 3

        isDroppingChainedBadFog = forPlayer != -1
        if isDroppingChainedBadFog:
            allFogTilesNearby = self.tiles_ever_owned_by_player[forPlayer].copy()
            SearchUtils.breadth_first_foreach(self.map, list(self.tiles_ever_owned_by_player[forPlayer]), playerTileAdvantageDepth, foreachFunc=lambda t: allFogTilesNearby.add(t), skipFunc=lambda t: t.visible and t not in self.tiles_ever_owned_by_player[forPlayer])
            for tile in allFogTilesNearby:
                q.append((forPlayer, tile))
        else:
            for p, tileSet in enumerate(self.tiles_ever_owned_by_player):
                allFogTilesNearby = tileSet.copy()
                SearchUtils.breadth_first_foreach(self.map, list(tileSet), playerTileAdvantageDepth, foreachFunc=lambda t: allFogTilesNearby.add(t), skipFunc=lambda t: t.visible and t not in tileSet)
                for tile in allFogTilesNearby:
                    q.append((p, tile))

        q.append((-1, neutralTile))

        visited = set()
        while len(q) > 0:
            curPlayer: int
            curTile: Tile
            curPlayer, curTile = q.popleft()

            if curTile in visited:
                continue

            visited.add(curTile)

            if curTile.discoveredAsNeutral and not curTile.delta.gainedSight:
                continue

            if not curTile.discovered:
                if isDroppingChainedBadFog:
                    if curPlayer == -1 and curTile.player == forPlayer:
                        logging.info(f'resetting wrong undisc fog guess {str(curTile)}')
                        if curTile.isCity and curTile in self.map.players[curTile.player].cities:
                            self.map.players[curTile.player].cities.remove(curTile)
                        curTile.reset_wrong_undiscovered_fog_guess()
                    if curPlayer == -1:
                        self.emergenceLocationMap[forPlayer][curTile.x][curTile.y] = 0
                else:
                    if curTile.player != -1 and curPlayer != curTile.player:
                        logging.info(f'resetting wrong undisc fog guess {str(curTile)}')
                        curTile.reset_wrong_undiscovered_fog_guess()
                        if curTile.isCity and curTile in self.map.players[curTile.player].cities:
                            self.map.players[curTile.player].cities.remove(curTile)

                    # for p, playerEmergences in enumerate(self.emergenceLocationMap):
                    #     if p == curPlayer:
                    #         continue
                    #     playerEmergences[curTile.x][curTile.y] = max(0, playerEmergences[curTile.x][curTile.y] - 2)

            if curTile.visible and curTile.discoveredAsNeutral and not curTile.delta.gainedSight and curTile != neutralTile:
                if isDroppingChainedBadFog:
                    if curTile not in self.tiles_ever_owned_by_player[forPlayer] and curTile.player != forPlayer:
                        continue
                # elif curPlayer != -1 and curTile not in self.tiles_ever_owned_by_player[curPlayer] and curTile.player != curPlayer:
                #     continue

            for tile in curTile.movable:
                if tile not in visited:
                    q.append((curPlayer, tile))

    def _handle_flipped_tiles(self):
        """To be called every time a tile is flipped from one owner to another owner."""

        def limitSpawnAroundOtherGen(t: Tile):
            self.valid_general_positions_by_player[player.index][t] = False

        for tile in self._flipped_tiles:
            if tile.player == -1 and not tile.isMountain and not tile.isCity and tile.delta.discovered:
                self.tile_discovered_neutral(tile)

            if tile.delta.lostSight:
                for adj in tile.adjacents:
                    if adj.delta.lostSight:
                        self.tiles_ever_owned_by_player[tile.player].add(adj)

        for tile in self._flipped_tiles:
            logging.info(f"AT Handling flipped {repr(tile)}")
            if tile.player != -1 and (tile.delta.oldOwner == -1 or not self.map.players[tile.delta.oldOwner].dead):
                self.tiles_ever_owned_by_player[tile.player].add(tile)

            if self.map.is_tile_friendly(tile):
                continue

            if tile.delta.discovered:
                for player in self.map.players:
                    self.valid_general_positions_by_player[player.index][tile] = False

                if tile.isGeneral:
                    for player in self.map.players:
                        if self.map.is_player_on_team_with(player.index, tile.player):
                            if tile.player != player.index and self.map.is_2v2:
                                def limitSpawnAroundAllyGen(t: Tile):
                                    if abs(t.x - tile.x) + abs(t.y - tile.y) > 11:
                                        self.valid_general_positions_by_player[player.index][t] = False

                                SearchUtils.breadth_first_foreach(self.map, [tile], 100, foreachFunc=limitSpawnAroundAllyGen)
                            continue

                        SearchUtils.breadth_first_foreach(self.map, [tile], self.min_spawn_distance, foreachFunc=limitSpawnAroundOtherGen)

                    for t in self.map.get_all_tiles():
                        if t != tile:
                            self.valid_general_positions_by_player[tile.player][t] = False
                        else:
                            self.valid_general_positions_by_player[tile.player][t] = True

        mustReLimit = False
        for tile in self._flipped_tiles:
            if tile.player == -1 and tile.delta.discovered:
                mustReLimit = True
                break

        if mustReLimit:
            for p, playerElims in enumerate(self.uneliminated_emergence_events):
                for prevElimTile, prevElimDist in playerElims.items():
                    logging.info(f'RE-eliminating p{p} t{prevElimTile} d{prevElimDist}')
                    self._limit_general_position_to_within_tile_and_distance(p, prevElimTile, prevElimDist, alsoIncreaseEmergence=False)  # alsoIncreaseEmergence=self.map.turn < 56)

        for tile in self._flipped_tiles:
            for p in self.map.players:
                if p.general is not None:
                    continue
                if not tile.isGeneral or tile.player != p.index:
                    self.valid_general_positions_by_player[p.index][tile] = False

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

            if p.tileCount > 75:
                continue

            # ok then this tile is a candidate for limiting distance from general...?
            maxDist = self.map.turn - self.player_launch_timings[tile.player]
            playerVisibleTiles = [t for t in p.tiles if t.visible and not t.delta.gainedSight]
            maxDist = min(maxDist, p.tileCount - 1)
            # if not tile.delta.gainedSight:
            #     maxDist = min(maxDist, p.tileCount)

            if self.map.turn <= 100 and self.player_launch_timings[tile.player] > 17:
                # then, unless they did some real dumb stuff, they can't be further than than their launch timing dist, either
                cycle1DistLimit = self.player_launch_timings[tile.player] // 2 + 1
                if self.map.turn <= 50:
                    maxDist = min(maxDist, cycle1DistLimit)
                else:
                    cycle2DistLimit = p.tileCount - 23 + cycle1DistLimit
                    maxDist = min(maxDist, cycle2DistLimit)

            logging.info(f'running a gen position limiter for p{p.index} from {str(tile)} distance {maxDist}')
            self._limit_general_position_to_within_tile_and_distance(tile.player, tile, maxDist, alsoIncreaseEmergence=self.map.turn < 56)

        self._flipped_tiles.clear()

    def _limit_general_position_to_within_tile_and_distance(self, player: int, tile: Tile, maxDist: int, alsoIncreaseEmergence: bool = True):
        validSet = set()

        launchDist = self.player_launch_timings[player] // 2 + 1
        launchDist = max(9, launchDist)

        hasPerfectInfoOfPlayerCities = self.has_perfect_information_of_player_cities(player)

        def limiter(t: Tile, dist: int):
            if not self.valid_general_positions_by_player[player][t]:
                return

            validSet.add(t)
            if alsoIncreaseEmergence:
                launchDistDiff = abs(launchDist - dist)
                launchDistFactor = (1 + launchDistDiff)
                launchEmergence = 50 // launchDistFactor
                self.emergenceLocationMap[player][t.x][t.y] += launchEmergence

        def skipper(t: Tile) -> bool:
            if t.discoveredAsNeutral and t not in self.tiles_ever_owned_by_player[player]:  # and (t.visible or self.map.turn < 50)   # should be solved without the visible check by adding the lost-sight-ever-owned-by-player hack to allow pathing through the fog now.
                return True
            if (t.isCity and t.player == -1 and (t.visible or hasPerfectInfoOfPlayerCities)) or t.isMountain or (t.isUndiscoveredObstacle and hasPerfectInfoOfPlayerCities) or t.isGeneral:
                return True
            return False

        SearchUtils.breadth_first_foreach_dist(
            self.map,
            [mv for mv in tile.movable if not mv.isObstacle],
            maxDist - 1,
            limiter,
            skipFunc=skipper)

        if len(validSet) == 0:
            if BYPASS_TIMEOUTS_FOR_DEBUGGING:
                raise AssertionError('we produced an invalid general position restriction with 0 valid tiles.')
            else:
                logging.error('we produced an invalid general position restriction with 0 valid tiles.')
                return

        elims = 0
        for t in self.map.get_all_tiles():
            if t not in validSet and self.valid_general_positions_by_player[player][t]:
                # logging.info(f'elimin')
                elims += 1
                self.valid_general_positions_by_player[player][t] = False
                if elims < 5:
                    logging.info(f'elim {elims} was {str(t)} (will stop logging at 5)')

        existingLimit = self.uneliminated_emergence_events[player].get(tile, None)

        if elims > 0 and (existingLimit is None or existingLimit > maxDist):
            logging.info(f'including new elim p{player} {str(tile)} at dist {maxDist} which eliminated {elims}')
            self.uneliminated_emergence_events[player][tile] = maxDist

    def _initialize_viable_general_positions(self):
        ourGens = [self.map.generals[self.map.player_index]]
        self.seen_player_lookup[self.map.player_index] = True
        for teammate in self.map.teammates:
            if self.map.generals[teammate] is not None:
                ourGens.append(self.map.generals[teammate])
            self.seen_player_lookup[teammate] = True

        for p in self.map.players:
            if p.general is not None:
                self.valid_general_positions_by_player[p.index][p.general] = True
                continue

            for tile in self.map.get_all_tiles():
                if tile.isObstacle:
                    continue

                if tile.visible:
                    continue

                if tile.discovered:
                    continue

                self.valid_general_positions_by_player[p.index][tile] = True

        for p, general in enumerate(self.map.generals):
            if general is None:
                continue

            distances = SearchUtils.build_distance_map_matrix(self.map, [general])

            for player in self.map.players:
                if self.map.is_player_on_team_with(general.player, player.index):
                    self.valid_general_positions_by_player[player.index][general] = False
                    continue

                for tile in self.map.get_all_tiles():
                    if distances[tile] < self.min_spawn_distance:
                        self.valid_general_positions_by_player[player.index][tile] = False
                        continue

                    if distances[tile] == 1000:
                        self.valid_general_positions_by_player[player.index][tile] = False

    def find_territory_bisection_paths(self, targetPlayer: int) -> typing.Tuple[MapMatrix[bool], MapMatrix[int], typing.List[Path]]:
        bisectPaths = []

        bisectCandidates = MapMatrix(self.map, False)
        bisectDistances = MapMatrix(self.map, 100)

        # bfs from all known enemy tiles

        everPlayerTiles = self.tiles_ever_owned_by_player[targetPlayer]
        playerValid = self.valid_general_positions_by_player[targetPlayer]

        enemyBisectableStart = list(everPlayerTiles)

        def foreachFunc(t: Tile, d: int):
            bisectDistances[t] = d

            if d > 3 and not t.discovered and playerValid[t]:
                bisectCandidates[t] = True

        def skipFunc(t: Tile) -> bool:
            if t.discoveredAsNeutral:
                return True  # dont bother routing through invisible stuff that can't be part of an original general constriction
            if t.visible and not t in everPlayerTiles:
                return True  # don't bother routing through visible stuff that was never theirs
            return False

        SearchUtils.breadth_first_foreach_dist(self.map, enemyBisectableStart, 150, foreachFunc, skipFunc=skipFunc)

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
            #     movingAwayFromUs = self.genDistances[tile.x][tile.y] > self.genDistances[fromTile.x][fromTile.y]
            #     movingAwayOrParallelToEn = self.genDistances[tile.x][tile.y] > self.genDistances[fromTile.x][fromTile.y]

        results = SearchUtils.breadth_first_dynamic_max_per_tile(self.map, startTiles, valueFunc=valFunc, priorityFunc=prioFunc, skipFunc=skipFuncDynamic, useGlobalVisitedSet=True)

        logging.info(f'BISECTOR FOUND {len(results)} BISECT PATHS...?')

        bestCandidates = PriorityQueue()

        for startTile, resultPath in results.items():
            distance = resultPath.length
            bisectDistSum = 0
            bisects = 0
            for tile in resultPath.tileList:
                if bisectCandidates[tile]:
                    bisectDistSum += bisectDistances[tile]
                    bisects += 1

            logging.info(f'bisect candidate bisects{bisects}, bisectDistSum{bisectDistSum}, {str(resultPath)}')

            if bisects == 0:
                continue

            bisectDistAvg = bisectDistSum / bisects

            bestCandidates.put((bisectDistAvg, resultPath))

        bannedTiles = set()
        while not bestCandidates.empty():
            (avg, path) = bestCandidates.get(block=False)

            skip = False
            for tile in path.tileList:
                if tile in bannedTiles:
                    skip = True
                    break

            if skip:
                continue

            for tile in path.tileList:
                bannedTiles.add(tile)

            logging.info(f'bisect included bisectAvg{avg}, {str(path)}')

            bisectPaths.append(path)

        return bisectCandidates, bisectDistances, bisectPaths

    def has_perfect_information_of_player_cities(self, player: int) -> bool:
        mapPlayer = self.map.players[player]
        realCities = where(mapPlayer.cities, lambda c: c.discovered)
        return len(realCities) >= mapPlayer.cityCount - 1

    def try_split_fogged_army_back_into_fog(self, army: Army, trackingArmies: typing.Dict[Tile, Army]):
        potential = []
        for adj in army.tile.movable:
            if not adj.visible and not adj.isMountain and not adj.isUndiscoveredObstacle:
                potential.append(adj)

        if len(potential) > 1:
            logging.info(f"    Army {str(army)} IS BEING ENTANGLED BACK INTO THE FOG")
            entangledArmies = army.get_split_for_fog(potential)
            for i, fogBoi in enumerate(potential):
                logging.info(
                    f"    Army {str(army)} entangled moved to {str(fogBoi)}")
                self.move_fogged_army(entangledArmies[i], fogBoi)
                self.unaccounted_tile_diffs.pop(entangledArmies[i].tile, None)
                self.army_moved(entangledArmies[i], fogBoi, trackingArmies, dontUpdateOldFogArmyTile=True)

        elif len(potential) == 1:
            self.move_fogged_army(army, potential[0])
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.army_moved(army, potential[0], trackingArmies, dontUpdateOldFogArmyTile=True)

    def update_track_threshold(self):
        tilesRankedByArmy = list(sorted(where(self.map.pathableTiles, filter_func=lambda t: t.player != -1), key=lambda t: t.army))
        percentile = 96
        percentileIndex = percentile * len(tilesRankedByArmy) // 100
        tileAtPercentile = tilesRankedByArmy[percentileIndex]
        if tileAtPercentile.army - 1 > self.track_threshold:
            newTrackThreshold = tileAtPercentile.army - 1
            logging.info(f'RAISING TRACK THRESHOLD FROM {self.track_threshold} TO {newTrackThreshold}')
            self.track_threshold = newTrackThreshold

    def _move_fogged_army_along_path(self, army: Army, path: Path):

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
            #     logging.info(
            #         f"Refusing to move army {str(army)} into entangled brother {str(existingArmy)}")
            #     # do nothing
            #     return

            self.armies.pop(army.tile, None)

            logging.info(
                f"Moving fogged army {str(army)} along expected path {str(path)}")

            oldTile = army.tile
            oldTile.army = 1
            if self.map.is_city_bonus_turn and oldTile.isCity or oldTile.isGeneral:
                oldTile.army += 1
            if self.map.is_army_bonus_turn:
                oldTile.army += 1

            if existingArmy is not None:
                if existingArmy in army.entangledArmies:
                    logging.info(f'entangled army collided with itself, scrapping the collision-mover {str(army)} in favor of {str(existingArmy)}')
                    self.scrap_army(army, scrapEntangled=False)
                    return

            # if not oldTile.discovered:
            #     oldTile.player = -1
            #     oldTile.army = 0
            if nextTile.player == army.player:
                nextTile.army = nextTile.army + army.value
            else:
                nextTile.army = nextTile.army - army.value
                if nextTile.army < 0:
                    nextTile.army = 0 - nextTile.army
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
            path.made_move()

    def try_find_army_sink(
            self,
            player: int,
            annihilatedFogArmy: int,
            tookNeutCity: bool
    ) -> bool:
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

        possibleArmies = list(sorted(possibleArmies, key=lambda a: abs(annihilatedFogArmy - a.value)))

        for army in possibleArmies:
            army.value -= annihilatedFogArmy
            if army.value < 0:
                army.value = 0
            army.tile.army = army.value + 1

            if tookNeutCity:
                potentialCity = self.find_next_fog_city_candidate_near_tile(player, army.tile)
                if potentialCity is not None:
                    self.convert_fog_city_to_player_owned(potentialCity, player)
                    army.tile.army = 1
                    army.update_tile(potentialCity)
                    potentialCity.army = army.value + 1

                    break

            else:
                break

