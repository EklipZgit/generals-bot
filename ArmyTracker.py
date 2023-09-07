'''
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
'''

import SearchUtils
from SearchUtils import *
from Path import Path
from base.client.map import Tile, TILE_FOG


class Army(object):
    start = 'A'
    end = 'Z'
    curLetter = start

    def get_letter(self):
        ch = Army.curLetter
        if (ord(ch) + 1 > ord(Army.end)):
            Army.curLetter = Army.start
        else:
            Army.curLetter = chr(ord(ch) + 1)
        return ch

    def __init__(self, tile: Tile):
        self.tile: Tile = tile
        self.path: Path = Path()
        self.player: int = tile.player
        self.visible: bool = tile.visible
        self.value: int = 0
        """Always the value of the tile, minus one. For some reason."""
        self.update_tile(tile)
        self.expectedPath: Path | None = None
        self.entangledArmies: typing.List[Army] = []
        self.name = self.get_letter()
        self.entangledValue = None
        self.scrapped = False
        self.last_moved_turn: int = 0

    def update_tile(self, tile):
        self.path.add_next(tile)
        self.tile = tile
        self.update()

    def update(self):
        if self.tile.visible:
            self.value = self.tile.army - 1
        self.visible = self.tile.visible

    def get_split_for_fog(self, fogTiles):
        split = []
        for tile in fogTiles:
            splitArmy = self.clone()
            splitArmy.entangledValue = self.value
            split.append(splitArmy)
        # entangle the armies
        for splitBoi in split:
            splitBoi.entangledArmies = list(where(split, lambda army: army != splitBoi))
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
        if self.expectedPath is not None:
            newDude.expectedPath = self.expectedPath.clone()
        newDude.entangledArmies = list(self.entangledArmies)
        newDude.name = self.name
        newDude.scrapped = self.scrapped
        return newDude

    def toString(self):
        return f"[{self.name} {self.tile.toString()} p{self.player} v{self.value}]"

    def __str__(self):
        return self.toString()

    def __repr__(self):
        return self.toString()


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

        self.lastMove: Move | None = None
        self.track_threshold = 10
        """Minimum tile value required to track an 'army' for performance reasons."""

        self.fogPaths = []
        self.emergenceLocationMap: typing.List[typing.List[typing.List[int]]] = [
            [[0 for x in range(self.map.rows)] for y in range(self.map.cols)] for z in range(len(self.map.players))]

        self.player_targets: typing.List[Tile] = []
        """The list of tiles we expect an enemy player might be trying to attack."""

        self.notify_unresolved_army_emerged: typing.List[typing.Callable[[Tile], None]] = []
        self.notify_army_moved: typing.List[typing.Callable[[Tile], None]] = []

        self.player_aggression_ratings = [PlayerAggressionTracker(z) for z in range(len(self.map.players))]
        self.lastTurn = -1

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

        advancedTurn = False
        if turn > self.lastTurn:
            advancedTurn = True
            if self.lastTurn == -1:
                self.lastTurn = turn
                self.find_new_armies()
                return

            self.lastTurn = turn
            self.player_moves_this_turn: typing.Set[int] = set()
        else:
            logging.info(f'army tracker scan ran twice this turn {turn}...? Bailing?')
            return

        self.player_targets = self.map.players[self.map.player_index].cities.copy()
        self.player_targets.append(self.map.generals[self.map.player_index])

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

    def move_fogged_army_paths(self):
        for army in list(self.armies.values()):
            if army.tile.visible:
                continue

            if (army.expectedPath is None
                    or army.expectedPath.start is None
                    or army.expectedPath.start.next is None
                    or army.expectedPath.start.next.tile is None
            ):
                continue

            if army.player in self.player_moves_this_turn:
                continue

            nextTile = army.expectedPath.start.next.tile
            if not nextTile.visible:
                logging.info(
                    f"Moving fogged army {army.toString()} along expected path {army.expectedPath.toString()}")
                del self.armies[army.tile]

                existingArmy = self.armies.get(nextTile, None)

                oldTile = army.tile
                oldTile.army = 1
                if self.map.is_city_bonus_turn and oldTile.isCity or oldTile.isGeneral:
                    oldTile.army += 1
                if self.map.is_army_bonus_turn:
                    oldTile.army += 1
                if nextTile.player == army.player:
                    nextTile.army = nextTile.army + army.value
                else:
                    nextTile.army = nextTile.army - army.value
                    if nextTile.army < 0:
                        nextTile.army = 0 - nextTile.army

                if existingArmy is not None:
                    if existingArmy in army.entangledArmies:
                        logging.info(f'entangled army collided with itself, scrapping the collision-mover {str(army)} in favor of {str(existingArmy)}')
                        self.scrap_army(existingArmy)
                        continue
                    elif existingArmy.player == army.player:
                        if existingArmy.value > army.value:
                            self.merge_armies(existingArmy, army, nextTile)
                        else:
                            self.merge_armies(army, existingArmy, nextTile)
                        continue

                army.update_tile(nextTile)
                army.value = nextTile.army - 1
                self.armies[nextTile] = army
                army.expectedPath.made_move()

    def clean_up_armies(self):
        for army in list(self.armies.values()):
            if army.scrapped:
                logging.info(f"Army {army.toString()} was scrapped last turn, deleting.")
                if army.tile in self.armies and self.armies[army.tile] == army:
                    del self.armies[army.tile]
                continue
            elif army.player == self.map.player_index and not army.tile.visible:
                logging.info(f"Army {army.toString()} was ours but under fog now, so was destroyed. Scrapping.")
                self.scrap_army(army)
            elif army.tile.visible and len(army.entangledArmies) > 0 and army.tile.player == army.player:
                if army.tile.army * 1.2 > army.value > (army.tile.army - 1) * 0.8:
                    # we're within range of expected army value, resolve entanglement :D
                    logging.info(f"Army {army.toString()} was entangled and rediscovered :D disentangling other armies")
                    self.resolve_entangled_armies(army)
                else:
                    logging.info(
                        f"Army {army.toString()} was entangled at this tile, but army value doesn't match expected?\n  - NOT army.tile.army * 1.2 ({army.tile.army * 1.2}) > army.value ({army.value}) > (army.tile.army - 1) * 0.8 ({(army.tile.army - 1) * 0.8})")
                    for entangled in army.entangledArmies:
                        logging.info(f"    removing {army.toString()} from entangled {entangled.toString()}")
                        entangled.entangledArmies.remove(army)
                    if army.tile in self.armies and self.armies[army.tile] == army:
                        del self.armies[army.tile]
                continue
            elif army.tile.delta.gainedSight and (
                    army.tile.player == -1 or (army.tile.player != army.player and len(army.entangledArmies) > 0)):
                logging.info(
                    f"Army {army.toString()} just uncovered was an incorrect army prediction. Disentangle and remove from other entangley bois")
                for entangled in army.entangledArmies:
                    logging.info(f"    removing {army.toString()} from entangled {entangled.toString()}")
                    entangled.entangledArmies.remove(army)

                if army.tile in self.armies and self.armies[army.tile] == army:
                    del self.armies[army.tile]

    def track_army_movement(self):
        # for army in list(self.armies.values()):
        #    self.determine_army_movement(army, adjArmies)
        trackingArmies = {}
        skip = set()

        self.unaccounted_tile_diffs: typing.Dict[Tile, int] = {}
        for tile in self.map.get_all_tiles():
            if tile.delta.armyDelta != 0 and not tile.delta.gainedSight and not tile.delta.lostSight:
                self.unaccounted_tile_diffs[tile] = tile.delta.armyDelta

        if self.lastMove is not None:
            playerMoveArmy = self.get_or_create_army_at(self.lastMove.source)
            playerMoveArmy.player = self.map.player_index
            playerMoveArmy.value = self.lastMove.source.delta.oldArmy - 1
            self.try_track_own_move(playerMoveArmy, skip, trackingArmies)

        for tile in self.map.get_all_tiles():
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

            army = self.get_or_create_army_at(tile)

            logging.info(f'Map detected army move, honoring that: {str(tile)}->{str(tile.delta.toTile)}')
            self.army_moved(army, tile.delta.toTile, trackingArmies)
            if tile.delta.toTile.isUndiscoveredObstacle:
                tile.delta.toTile.isCity = True
                tile.delta.toTile.player = army.player
                tile.delta.toTile.army = army.value
                logging.warning(f'CONVERTING {str(tile.delta.toTile)} UNDISCOVERED MOUNTAIN TO CITY DUE TO MAP SAYING DEFINITELY TILE MOVED THERE. {str(tile)}->{str(tile.delta.toTile)}')
            army.update()
            if not tile.delta.toTile.visible:
                # map knows what it is doing, force tile army update.
                army.value = tile.delta.toTile.army - 1

        for army in list(self.armies.values()):
            # any of our armies CANT have moved (other than the one handled explicitly above), ignore them, let other armies collide with / capture them.
            if army.player == self.map.player_index:
                if army.last_moved_turn < self.map.turn - 1 and army.tile.army < self.track_threshold:
                    self.scrap_army(army)
                else:
                    army.update()
                continue

            self.try_track_army(army, skip, trackingArmies)

        self.scrap_unmoved_low_armies()

        for army in trackingArmies.values():
            self.armies[army.tile] = army

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
                    f"  Find visible source  {tile.toString()} ({tile.delta.armyDelta}) <- {adjacent.toString()} ({unexplainedAdjDelta}) ? {isMatch}")
                return adjacent

        # try more lenient
        for adjacent in tile.movable:
            isMatch = False
            unexplainedAdjDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
            if 2 >= tile.delta.armyDelta + unexplainedAdjDelta >= -2:
                isMatch = True

            logging.info(
                f"  Find visible source  {tile.toString()} ({tile.delta.armyDelta}) <- {adjacent.toString()} ({unexplainedAdjDelta}) ? {isMatch}")
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
        if army.visible and toTile.visible or toTile.delta.lostSight:
            if army.player in self.player_moves_this_turn:
                logging.error(f'Yo, we think a player moved twice this turn...?')

            self.player_moves_this_turn.add(army.player)

        army.update_tile(toTile)
        existingTracking = trackingArmies.get(toTile, None)
        h = ""
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

        if army.value < -1 or (army.player != army.tile.player and army.tile.visible):
            logging.info(f"    Army {army.toString()} scrapped for being negative or run into larger tile")
            self.scrap_army(army)
        if army.tile.visible and len(army.entangledArmies) > 0:
            self.resolve_entangled_armies(army)

        if not oldTile.visible and not dontUpdateOldFogArmyTile:
            oldTile.army = 1
            oldTile.player = army.player
            if self.map.is_army_bonus_turn:
                oldTile.army += 1
            if oldTile.isCity or oldTile.isGeneral and self.map.is_city_bonus_turn:
                oldTile.army += 1

        if army.player != self.map.player_index:
            if army.scrapped:
                army.expectedPath = None
            else:
                # TODO detect if enemy army is likely trying to defend
                army.expectedPath = self.get_army_expected_path(army)

        army.last_moved_turn = self.map.turn - 1

        for listener in self.notify_army_moved:
            listener(army.tile)

    def scrap_army(self, army):
        army.scrapped = True
        for entangledArmy in army.entangledArmies:
            entangledArmy.scrapped = True
        self.resolve_entangled_armies(army)

    def resolve_entangled_armies(self, army):
        if len(army.entangledArmies) > 0:
            logging.info(f"{army.toString()} resolving {len(army.entangledArmies)} entangled armies")
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
                        entangledArmy.tile.army = 0
                        entangledArmy.tile.player = -1
                        entangledArmy.tile.tile = TILE_FOG

                entangledArmy.entangledArmies = []
            army.entangledArmies = []

    def army_could_capture(self, army, fogTargetTile):
        if army.player != fogTargetTile.player:
            return army.value > fogTargetTile.army
        return True

    def move_fogged_army(self, army: Army, fogTargetTile: Tile):
        if army.tile in self.armies:
            del self.armies[army.tile]
        # if fogTargetTile in self.armies:
        #     army.scrapped = True
        #     return
        existingTargetFoggedArmy = self.armies.get(fogTargetTile, None)
        if existingTargetFoggedArmy is not None:
            if army in existingTargetFoggedArmy.entangledArmies:
                army.scrapped = True
                return

        if fogTargetTile.player == army.player:
            fogTargetTile.army += army.value
        else:
            fogTargetTile.army -= army.value
            if fogTargetTile.army < 0:
                fogTargetTile.army = 0 - fogTargetTile.army
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
            listener(army.tile)

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
            logging.info(f"Army {army.toString()} had nearbyArmy {nearbyArmy.toString()}")
        return nearbyArmies

    def find_new_armies(self):
        logging.info("Finding new armies:")
        playerLargest = [None for x in range(len(self.map.players))]
        # don't do largest tile for now?
        # for tile in self.map.pathableTiles:
        #    if tile.player != -1 and (playerLargest[tile.player] == None or tile.army > playerLargest[tile.player].army):
        #        playerLargest[tile.player] = tile
        for tile in self.map.pathableTiles:
            notOurMove = (self.lastMove is None or (tile != self.lastMove.source and tile != self.lastMove.dest))
            tileNewlyMovedByEnemy = (tile not in self.armies
                                     and not tile.delta.gainedSight
                                     and tile.player != self.map.player_index
                                     and abs(tile.delta.armyDelta) > 2
                                     and tile.army > 2
                                     and notOurMove)

            # if we moved our army into a spot last turn that a new enemy army appeared this turn
            tileArmy = self.armies.get(tile, None)

            if (
                    (tileArmy is None or tileArmy.scrapped)
                    and tile.player != -1
                    and (playerLargest[tile.player] == tile
                         or tile.army >= self.track_threshold
                         or tileNewlyMovedByEnemy)
            ):
                logging.info(
                    f"{tile.toString()} Discovered as Army! (tile.army {tile.army}, tile.delta {tile.delta.armyDelta}) Determining if came from fog")
                resolvedFogSourceArmy = False
                resolvedReasonableFogValuePath = False
                delta = abs(tile.delta.armyDelta)
                if delta > tile.army / 2:
                    # maybe this came out of the fog?
                    sourceFogArmyPath = self.find_fog_source(tile, delta)
                    if sourceFogArmyPath is not None:
                        self.use_fog_source_path(tile, sourceFogArmyPath, delta)

                        self.resolve_fog_emergence(sourceFogArmyPath, tile)
                if not resolvedFogSourceArmy:
                    # then tile is a new army.
                    army = self.get_or_create_army_at(tile)
                    if not army.visible:
                        army.value = army.tile.army - 1
                    self.new_army_emerged(tile, delta)
            # if tile WAS bordered by fog find the closest fog army and remove it (not tile.visible or tile.delta.gainedSight)

    def new_army_emerged(self, emergedTile: Tile, armyEmergenceValue: int):
        """
        when an army can't be resolved to coming from the fog from a known source, this method gets called to track its emergence location.
        @param emergedTile:
        @param armyEmergenceValue:
        @return:
        """

        if not self.has_perfect_information_of_player_cities_and_general(emergedTile.player):
            logging.info(f"running new_army_emerged for tile {emergedTile.toString()}")
            distance = 11
            # armyEmergenceValue =
            armyEmergenceValue = 2 + (armyEmergenceValue ** 0.8)
            if armyEmergenceValue > 50:
                armyEmergenceValue = 50

            def foreachFunc(tile, dist):
                self.emergenceLocationMap[emergedTile.player][tile.x][tile.y] += 3 * armyEmergenceValue // max(7, (
                        dist + 1))

            negativeLambda = lambda tile: tile.discovered
            skipFunc = lambda tile: (tile.visible or tile.discoveredAsNeutral) and tile != emergedTile
            breadth_first_foreach_dist(self.map, [emergedTile], distance, foreachFunc, negativeLambda, skipFunc)

        for handler in self.notify_unresolved_army_emerged:
            handler(emergedTile)

    def tile_discovered_neutral(self, neutralTile):
        logging.info(f"running tile_discovered_neutral for tile {neutralTile.toString()}")
        distance = 6
        armyEmergenceValue = 40

        def foreachFunc(tile, dist):
            self.emergenceLocationMap[neutralTile.player][tile.x][tile.y] -= 1 * armyEmergenceValue // (dist + 5)
            if self.emergenceLocationMap[neutralTile.player][tile.x][tile.y] < 0:
                self.emergenceLocationMap[neutralTile.player][tile.x][tile.y] = 0

        negativeLambda = lambda tile: tile.discovered or tile.player >= 0
        skipFunc = lambda tile: tile.visible and tile != neutralTile
        breadth_first_foreach_dist(self.map, [neutralTile], distance, foreachFunc, negativeLambda, skipFunc)

    def find_fog_source(self, tile: Tile, delta: int | None = None):
        """
        Looks for a fog source to this tile that produces the provided (positive) delta, or if none provided, the
        (positive) delta from the tile this turn.
        @param tile:
        @param delta:
        @return:
        """
        if delta is None:
            delta = abs(tile.delta.armyDelta)
        if len(where(tile.movable,
                     lambda adj: not adj.isNotPathable and (adj.delta.gainedSight or not adj.visible))) == 0:
            logging.info(f"        For new army at tile {tile.toString()} there were no adjacent fogBois, no search")
            return None

        def valFunc(thisTile: Tile, prioObject):
            (dist, negArmy, turnsNegative, consecUndisc) = prioObject
            if dist == 0:
                return None

            val = 0
            if negArmy > 0:
                val = -2000 - negArmy
            else:
                val = negArmy

            if thisTile.player == tile.player and thisTile.army > 8:
                negArmy += thisTile.army // 2

                if negArmy > 0:
                    moveHalfVal = -2000 - negArmy
                else:
                    moveHalfVal = negArmy
                if moveHalfVal > val:
                    logging.info(
                        f"using moveHalfVal {moveHalfVal:.1f} over val {val:.1f} for tile {thisTile.toString()} turn {self.map.turn}")
                    val = moveHalfVal
            # closest path value to the actual army value. Fake tuple for logging.
            # 2*abs for making it 3x improvement on the way to the right path, and 1x unemprovement for larger armies than the found tile
            # negative weighting on dist to try to optimize for shorter paths instead of exact
            return val, 0

        # if (0-negArmy) - dist*2 < tile.army:
        #    return (0-negArmy)
        # return -1

        def pathSortFunc(nextTile, prioObject):
            (dist, negArmy, turnsNeg, consecutiveUndiscovered) = prioObject
            theArmy = self.armies.get(nextTile, None)
            if theArmy is not None:
                consecutiveUndiscovered = 0
                if theArmy.player == tile.player:
                    negArmy -= theArmy.value
                else:
                    negArmy += theArmy.value
            else:
                if not nextTile.discovered:
                    consecutiveUndiscovered += 1
                else:
                    consecutiveUndiscovered = 0
                if nextTile.player == tile.player:
                    negArmy -= nextTile.army - 1
                else:
                    negArmy += nextTile.army + 1

            if negArmy <= 0:
                turnsNeg += 1
            dist += 1
            return dist, negArmy, turnsNeg, consecutiveUndiscovered

        def fogSkipFunc(nextTile, prioObject):
            (dist, negArmy, turnsNegative, consecutiveUndiscovered) = prioObject
            # logging.info("nextTile {}: negArmy {}".format(nextTile.toString(), negArmy))
            return (
                    (nextTile.visible and not nextTile.delta.gainedSight)
                    or turnsNegative > 6
                    or consecutiveUndiscovered > 15
                    or dist > 20
            )

        inputTiles = {}
        logging.info(f"Looking for fog army path of value {delta} to tile {tile.toString()}")
        # we want the path to get army up to 0, so start it at the negative delta (positive)
        inputTiles[tile] = ((0, delta, 0, 0), 0)

        fogSourcePath = breadth_first_dynamic_max(
            self.map,
            inputTiles,
            valFunc,
            maxTime=100000.0,
            noNeutralCities=True,
            priorityFunc=pathSortFunc,
            skipFunc=fogSkipFunc,
            searchingPlayer=tile.player,
            logResultValues=True,
            noLog=False)
        if fogSourcePath is not None:
            logging.info(
                f"        For new army at tile {tile.toString()} we found fog source path???? {fogSourcePath.toString()}")
        else:
            logging.info(f"        NO fog source path for new army at {tile.toString()}")
        return fogSourcePath

    def resolve_fog_emergence(self, sourceFogArmyPath, fogTile):
        existingArmy = None
        armiesFromFog = []
        existingArmy = self.armies.pop(fogTile, None)
        if existingArmy is not None and existingArmy.player == fogTile.player:
            armiesFromFog.append(existingArmy)

        node = sourceFogArmyPath.start.next
        while node is not None:
            logging.info(f"resolve_fog_emergence tile {node.tile.toString()}")
            fogArmy = self.armies.pop(node.tile, None)
            if fogArmy is not None and fogArmy.player == fogTile.player:
                logging.info(f"  was army {node.tile.toString()}")
                armiesFromFog.append(fogArmy)
            # if node.tile.army > 0:
            node.tile.army = 1
            node.tile.player = fogTile.player
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
            while node.tile != maxArmy.tile:
                node = node.next
            node = node.next
            while node is not None:
                maxArmy.update_tile(node.tile)
                node = node.next

            # scrap other armies from the fog
            for army in armiesFromFog:
                if army != maxArmy:
                    logging.info(f"  scrapping {army.toString()}")
                    self.scrap_army(army)
            self.resolve_entangled_armies(maxArmy)
            logging.info(f'set fog source for {str(fogTile)} to {str(maxArmy)}')
            maxArmy.update_tile(fogTile)
            maxArmy.update()
            self.armies[fogTile] = maxArmy
            maxArmy.path = sourceFogArmyPath
            maxArmy.expectedPath = None
        else:
            # then this is a brand new army because no armies were on the fogPath, but we set the source path to 1's still
            army = Army(fogTile)
            if not fogTile.visible:
                army.value = fogTile.army - 1
            self.armies[fogTile] = army
            army.path = sourceFogArmyPath

    def merge_armies(self, largerArmy, smallerArmy, finalTile, armyDict: typing.Dict[Tile, Army] | None = None):
        self.armies.pop(largerArmy.tile, None)
        self.armies.pop(smallerArmy.tile, None)
        self.scrap_army(smallerArmy)

        if largerArmy.tile != finalTile:
            largerArmy.update_tile(finalTile)

        if armyDict is None:
            armyDict = self.armies

        armyDict[finalTile] = largerArmy
        largerArmy.update()

    def has_perfect_information_of_player_cities_and_general(self, player: int):
        mapPlayer = self.map.players[player]
        if mapPlayer.general is not None and len(mapPlayer.cities) == mapPlayer.cityCount - 1:
            # then we have perfect information about the player, no point in tracking emergence values
            return True

        return False

    def try_track_own_move(self, army: Army, skip: typing.Set[Tile], trackingArmies: typing.Dict[Tile, Army]):
        playerMoveDest = self.lastMove.dest
        playerMoveSrc = self.lastMove.source
        logging.info(
            f"    Army (lastMove) probably moved from {army.toString()} to {playerMoveDest.toString()}")
        expectedDestDelta = army.value
        if self.lastMove.move_half:
            expectedDestDelta = (army.value + 1) // 2
        expectedSourceDelta = 0 - expectedDestDelta  # these should always match if no other army interferes.
        if playerMoveDest.delta.oldOwner != self.map.player_index:
            expectedDestDelta = 0 - expectedDestDelta

        likelyDroppedMove = False
        if playerMoveSrc.delta.armyDelta == 0:
            likelyDroppedMove = True
            if playerMoveDest.delta.armyDelta == 0:
                logging.error(
                    f'Army tracker determined player DEFINITELY dropped move {str(self.lastMove)}. Setting last move to none...')
                self.lastMove = None
                return
            else:
                logging.error(
                    f'Army tracker determined player PROBABLY dropped move {str(self.lastMove)}, but the dest DID have an army delta, double check on this... Continuing in case this is 2v2 BS or something.')

        # ok, then probably we didn't drop a move.

        actualSrcDelta = playerMoveSrc.delta.armyDelta
        actualDestDelta = playerMoveDest.delta.armyDelta

        sourceDeltaMismatch = expectedSourceDelta != actualSrcDelta
        destDeltaMismatch = expectedDestDelta != actualDestDelta

        sourceWasAttackedWithPriority = False
        sourceWasCaptured = False
        if sourceDeltaMismatch or self.lastMove.source.player != self.map.player_index:
            amountAttacked = actualSrcDelta - expectedSourceDelta
            if self.lastMove.source.player != self.map.player_index:
                sourceWasCaptured = True
                if MapBase.player_had_priority(self.lastMove.source.player, self.map.turn):
                    sourceWasAttackedWithPriority = True
                    logging.info(
                        f'MOVE {str(self.lastMove)} seems to have been captured with priority. Nuking our army and having no unexplained diffs (to let the main army tracker just calculate this capture).')
                    if destDeltaMismatch:
                        logging.error(
                            f'  ^ {str(self.lastMove)} IS QUESTIONABLE THOUGH BECAUSE DEST DID HAVE AN UNEXPLAINED DIFF. NUKING ANYWAY.')
                    self.scrap_army(army)
                    self.lastMove = None
                    return
                else:
                    logging.info(
                        f'MOVE {str(self.lastMove)} was capped WITHOUT priority..? Adding unexplained diff {amountAttacked} based on actualSrcDelta {actualSrcDelta} - expectedSourceDelta {expectedSourceDelta}. Continuing with dest diff calc')
                    self.unaccounted_tile_diffs[self.lastMove.source] = amountAttacked  # negative number
            else:
                # we can get here if the source tile was attacked with priority but not for full damage, OR if it was attacked without priority for non full damage...
                destArmyInterferedToo = False
                if not destDeltaMismatch:
                    # then we almost certainly didn't have source attacked with priority.
                    logging.warning(
                        f'MOVE {str(self.lastMove)} ? src attacked for amountAttacked {amountAttacked} WITHOUT priority based on actualSrcDelta {actualSrcDelta} vs expectedSourceDelta {expectedSourceDelta}')
                elif not MapBase.player_had_priority(self.map.player_index, self.map.turn):
                    # if we DIDNT have priority (this is hit or miss in FFA, tho).
                    armyMadeItToDest = playerMoveDest.delta.armyDelta
                    amountAttacked = expectedDestDelta - armyMadeItToDest
                    if playerMoveSrc.army == 0:
                        amountAttacked -= 1  # enemy can attack us down to 0 without flipping the tile, special case this

                    logging.warning(
                        f'MOVE {str(self.lastMove)} ? src attacked for amountAttacked {amountAttacked} based on destDelta {playerMoveDest.delta.armyDelta} vs expectedDestDelta {expectedDestDelta}')
                else:
                    destArmyInterferedToo = True
                    # TODO what to do here?
                    logging.warning(
                        f'???MOVE {str(self.lastMove)} ? player had priority but we still had a dest delta as well as source delta...?')

                self.unaccounted_tile_diffs[self.lastMove.source] = amountAttacked  # negative number
                if not destArmyInterferedToo:
                    # intentionally do nothing about the dest tile diff if we found a source tile diff, as it is really unlikely that both source and dest get interfered with on same turn.
                    self.army_moved(army, playerMoveDest, trackingArmies)
                    return
        else:
            # nothing happened, we moved the expected army off of source. Not unexplained.
            self.unaccounted_tile_diffs.pop(playerMoveSrc, 0)

        if destDeltaMismatch:
            unexplainedDelta = expectedDestDelta - actualDestDelta
            if playerMoveDest.delta.oldOwner == playerMoveDest.delta.newOwner:
                unexplainedDelta = 0 - unexplainedDelta

            self.unaccounted_tile_diffs[self.lastMove.dest] = unexplainedDelta
            logging.info(
                f'MOVE {str(self.lastMove)} with expectedDestDelta {expectedDestDelta} likely collided with unexplainedDelta {unexplainedDelta} at dest based on actualDestDelta {actualDestDelta}.')
        else:
            logging.info(
                f'!MOVE {str(self.lastMove)} made it to dest with no issues, moving army.\r\n    expectedDestDelta {expectedDestDelta}, expectedSourceDelta {expectedSourceDelta}, actualSrcDelta {actualSrcDelta}, actualDestDelta {actualDestDelta}, sourceWasAttackedWithPriority {sourceWasAttackedWithPriority}, sourceWasCaptured {sourceWasCaptured}')
            self.unaccounted_tile_diffs.pop(playerMoveDest, 0)
        self.army_moved(army, playerMoveDest, trackingArmies)

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
            logging.info(f"Army {army.toString()} was in skip set. Skipping")
            return
        # army may have been removed (due to entangled resolution)
        if armyTile not in self.armies:
            logging.info(f"Skipped armyTile {armyTile.toString()} because no longer in self.armies?")
            return
        # army = self.armies[armyTile]
        if army.tile != armyTile:
            raise Exception(
                f"bitch, army key {armyTile.toString()} didn't match army tile {army.toString()}")

        armyRealTileDelta = 0 - army.tile.delta.armyDelta
        if armyRealTileDelta == 0 and army.tile.visible:
            logging.info(f'army didnt move...? {str(army)}')
            army.update()
            return

        # if armyRealTileDelta == 0 and armyTile.visible:
        #     # Army didn't move...?
        #     continue
        logging.info(
            f"{army.toString()} army.value {army.value} actual delta {army.tile.delta.armyDelta}, armyRealTileDelta {armyRealTileDelta}")
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

        # elif self.isArmyBonus and armyRealTileDelta > 0 and abs(adjDelta - armyRealTileDelta) == 2:
        #     # handle bonus turn capture moves?
        #     foundLocation = True
        #     logging.info("    Army (BONUS CAPTURE?) probably moved from {} to {}".format(army.toString(), adjacent.toString()))
        #     self.army_moved(army, adjacent, trackingArmies)
        #     break

        # if not foundLocation:
        #     # first check if the map decided where it went
        #     if army.tile.delta.toTile is not None:
        #         foundLocation = True
        #         logging.info(
        #             f"  army.tile.delta.toTile != None, using {army.tile.delta.toTile.toString()}")
        #         self.army_moved(army, army.tile.delta.toTile, trackingArmies)

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
                if not adjacent.visible and self.army_could_capture(army, adjacent) and legalFogMove:
                    # if (closestFog == None or self.distMap[adjacent.x][adjacent.y] < self.distMap[closestFog.x][closestFog.y]):
                    #    closestFog = adjacent
                    fogBois.append(adjacent)
                    fogCount += 1

                expectedAdjDelta = 0
                adjDelta = self.unaccounted_tile_diffs.get(adjacent, adjacent.delta.armyDelta)
                # expectedAdjDelta = 0
                logging.info(
                    f"  adjacent delta raw {adjacent.delta.armyDelta} expectedAdjDelta {expectedAdjDelta}")
                logging.info(
                    f"  armyDeltas: army {army.toString()} {armyRealTileDelta} - adj {adjacent.toString()} {adjDelta} expAdj {expectedAdjDelta}")
                # expectedDelta is fine because if we took the expected tile we would get the same delta as army remaining on army tile.
                if ((armyRealTileDelta > 0 or
                     (not army.tile.visible and
                      adjacent.visible and
                      adjacent.delta.armyDelta != expectedAdjDelta)) and
                        adjDelta - armyRealTileDelta == army.tile.delta.expectedDelta):
                    foundLocation = True
                    logging.info(
                        f"    Army (Based on expected delta?) probably moved from {army.toString()} to {adjacent.toString()}")
                    self.unaccounted_tile_diffs.pop(army.tile, None)
                    self.army_moved(army, adjacent, trackingArmies)

                if foundLocation:
                    break

            if not foundLocation and len(fogBois) > 0 and army.player != self.map.player_index and (
                    army.tile.visible or army.tile.delta.lostSight):  # prevent entangling and moving fogged cities and stuff that we stopped incrementing
                fogArmies = []
                if len(fogBois) == 1:
                    foundLocation = True
                    logging.info(f"    WHOO! Army {army.toString()} moved into fog at {fogBois[0].toString()}!?")
                    self.move_fogged_army(army, fogBois[0])
                    if fogCount == 1:
                        logging.info("closestFog and fogCount was 1, converting fogTile to be owned by player")
                        fogBois[0].player = army.player
                    self.unaccounted_tile_diffs.pop(army.tile, None)
                    self.army_moved(army, fogBois[0], trackingArmies, dontUpdateOldFogArmyTile=True)

                else:
                    foundLocation = True
                    logging.info(f"    Army {army.toString()} IS BEING ENTANGLED! WHOO! EXCITING!")
                    entangledArmies = army.get_split_for_fog(fogBois)
                    for i, fogBoi in enumerate(fogBois):
                        logging.info(
                            f"    Army {army.toString()} entangled moved to {fogBoi.toString()}")
                        self.move_fogged_army(entangledArmies[i], fogBoi)
                        self.unaccounted_tile_diffs.pop(entangledArmies[i].tile, None)
                        self.army_moved(entangledArmies[i], fogBoi, trackingArmies, dontUpdateOldFogArmyTile=True)
                return

            if army.player != army.tile.player and army.tile.visible:
                logging.info(f"  Army {army.toString()} got eated? Scrapped for not being the right player anymore")
                self.scrap_army(army)

        army.update()

    def get_or_create_army_at(self, tile: Tile) -> Army:
        army = self.armies.get(tile, None)
        if army is None:
            army = Army(tile)
            army.last_moved_turn = self.map.turn
            if not tile.visible:
                army.value = tile.army - 1

            army.expectedPath = self.get_army_expected_path(army)

            self.armies[tile] = army

        return army

    def handle_gathered_to_army(self, army: Army, skip: typing.Set[Tile], trackingArmies: typing.Dict[Tile, Army]):
        logging.info(
            f"Army {army.toString()} tile was just gathered to (or city increment or whatever), nbd, update it.")
        unaccountedForDelta = abs(army.tile.delta.armyDelta)
        source = self.find_visible_source(army.tile)
        if source is None:
            logging.info(
                f"Army {army.toString()} must have been gathered to from under the fog, searching:")
            sourceFogArmyPath = self.find_fog_source(army.tile, unaccountedForDelta)
            if sourceFogArmyPath is not None:
                armyTile = army.tile
                self.use_fog_source_path(armyTile, sourceFogArmyPath, unaccountedForDelta)

                self.resolve_fog_emergence(sourceFogArmyPath, army.tile)
        else:
            if source in self.armies:
                sourceArmy = self.armies[source]
                larger = sourceArmy
                smaller = army
                if sourceArmy.value < army.value:
                    larger = army
                    smaller = sourceArmy
                logging.info(
                    f"Army {army.toString()} was gathered to visibly from source ARMY {sourceArmy.toString()} and will be merged as {larger.toString()}")
                skip.add(larger.tile)
                skip.add(smaller.tile)
                self.merge_armies(larger, smaller, army.tile)
                return
            else:
                logging.info(f"Army {army.toString()} was gathered to visibly from source tile {source.toString()}")
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
                f"    Army probably moved from {army.toString()} to {adjacent.toString()} based on unexplainedAdjDelta {unexplainedAdjDelta} vs armyRealTileDelta {armyRealTileDelta}")
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True
        elif not army.tile.visible and positiveUnexplainedAdjDelta > 1:
            if positiveUnexplainedAdjDelta * 1.1 - army.value > 0 and army.value > positiveUnexplainedAdjDelta // 2 - 1:
                logging.info(
                    f"    Army probably moved from {army.toString()} to {adjacent.toString()} based on unexplainedAdjDelta {unexplainedAdjDelta} vs armyRealTileDelta {armyRealTileDelta}")
                self.unaccounted_tile_diffs[army.tile] = unexplainedSourceDelta - unexplainedAdjDelta
                self.unaccounted_tile_diffs.pop(adjacent, None)
                self.army_moved(army, adjacent, trackingArmies)
                return True
        elif adjacent.delta.gainedSight and armyRealTileDelta > 0 and positiveUnexplainedAdjDelta * 0.9 < armyRealTileDelta < positiveUnexplainedAdjDelta * 1.25:
            logging.info(
                f"    Army (WishyWashyFog) probably moved from {army.toString()} to {adjacent.toString()}")
            self.unaccounted_tile_diffs.pop(army.tile, None)
            self.unaccounted_tile_diffs.pop(adjacent, None)
            self.army_moved(army, adjacent, trackingArmies)
            return True
        elif positiveUnexplainedAdjDelta != 0 and abs(positiveUnexplainedAdjDelta) - army.value == 0:
            # handle fog moves?
            logging.info(
                f"    Army (SOURCE FOGGED?) probably moved from {army.toString()} to {adjacent.toString()}. adj (dest) visible? {adjacent.visible}")
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
            logging.info(f"  Army {army.toString()} Stopped moving. Scrapped for being low value")
            self.scrap_army(army)

    def scrap_unmoved_low_armies(self):
        for army in list(self.armies.values()):
            if army.last_moved_turn < self.map.turn - 1:
                self.check_for_should_scrap_unmoved_army(army)

    def get_army_expected_path(self, army: Army) -> Path | None:
        """
        Returns none if asked to predict a friendly army path.

        Returns the path to the nearest player target out of the targets,
         WHETHER OR NOT the army can actually reach that target or capture it successfully.

        @param army:
        @return:
        """
        if army.player == self.map.player_index:
            return None

        return SearchUtils.breadth_first_find_queue(
            self.map,
            [army.tile],
            goalFunc=lambda tile, army, dist: army > 0 and tile in self.player_targets,
            maxTime=0.1,
            maxDepth=10,
            noNeutralCities=army.tile.army < 150,
            searchingPlayer=army.player)
