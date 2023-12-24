"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logbook
import math
import random
import typing
from copy import deepcopy
import time
import json
from ArmyAnalyzer import *
from collections import deque
from queue import PriorityQueue
from pprint import pprint, pformat
from SearchUtils import *
from DataModels import *
from enum import Enum


class ThreatType(Enum):
    Kill = 1
    Vision = 2
    Econ = 3


class ThreatObj(object):
    def __init__(self, moveCount, threatValue: float, path, type, saveTile=None, armyAnalysis=None):
        # this is the number of turns available to defend. So if the threat means 'we are dead in two turns', this will be 1
        self.turns: int = moveCount
        # the amount of army the threat currently calculates as killing the target by, so effectively the amount of
        # additional defense army that is needed to counter the threat.
        self.threatValue: int = math.ceil(threatValue)
        self.path: Path = path
        self.threatPlayer: int = path.start.tile.player
        self.threatType = type
        self.saveTile: typing.Union[None, Tile] = saveTile
        self.armyAnalysis: ArmyAnalyzer = armyAnalysis

    def convert_to_dist_dict(self, offset: int = -1, allowNonChoke: bool = False) -> typing.Dict[Tile, int]:
        # if offset == -1 and not self.path.tail.tile.isGeneral:
        #     offset = 0

        dict = self.path.get_reversed().convert_to_dist_dict(offset=offset)

        # for tile in self.armyAnalysis.shortestPathWay.tiles:
        for tile in self.path.tileList:
            dist = dict.pop(tile, None)
            # if dist is None:
            dist = self.armyAnalysis.aMap[tile.x][tile.y] + offset
            if allowNonChoke:
                dict[tile] = dist
            if tile.isGeneral:
                # need to gather to general 1 turn earlier than otherwise necessary
                dict[tile] = dist + 1
            # elif tile in self.armyAnalysis.pathChokes and not self.path.start.tile == tile:
            #     dict[tile] -= 1
            #     # pathWay = self.armyAnalysis.pathWayLookupMatrix[tile]
            #     # neighbors = where(pathWay.tiles, lambda t: t != tile and self.armyAnalysis.aMap[t.x][t.y] == self.armyAnalysis.aMap[tile.x][tile.y] and self.armyAnalysis.bMap[t.x][t.y] == self.armyAnalysis.bMap[tile.x][tile.y])
            #     # newDist = dist + 1
            #     # del dict[tile]  # necessary for 'test_should_not_make_move_away_from_threat' to pass.
            #     # logbook.info(f'Threat path tile {str(tile)} increased to dist {newDist} based on neighbors {neighbors}')
            #     pass
            # elif not allowNonChoke and tile not in self.armyAnalysis.pathChokes and not self.path.start.next.tile in tile.movable:
            else:  # and not self.path.start.next.tile in tile.movable:
                # pathWay = self.armyAnalysis.pathWayLookupMatrix[tile]
                # neighbors = where(pathWay.tiles, lambda t: t != tile and self.armyAnalysis.aMap[t.x][t.y] == self.armyAnalysis.aMap[tile.x][tile.y] and self.armyAnalysis.bMap[t.x][t.y] == self.armyAnalysis.bMap[tile.x][tile.y])
                chokeWidth = self.armyAnalysis.chokeWidths.get(tile, None)
                interceptChoke = self.armyAnalysis.interceptChokes.get(tile, None)
                if allowNonChoke or tile in self.armyAnalysis.pathChokes or (interceptChoke is not None and interceptChoke < 4):
                    if chokeWidth is not None:
                        newDist = dist + chokeWidth - 1  # this 2 is almost certainly wrong, but makes some tests pass.
                        logbook.info(f'Threat path tile {str(tile)} dist {dist} changed to {newDist} based on chokeWidth {chokeWidth} / interceptChoke {interceptChoke}')
                        dict[tile] = newDist

        return dict

    def __str__(self):
        return f'[p{self.threatPlayer} {self.threatValue} in {self.turns} @ {self.path.tail.tile}: {str(self.path)}]'


class DangerAnalyzer(object):
    def __init__(self, map):
        self.targets: typing.List[Tile] = []
        self.map: MapBase = map
        self.fastestVisionThreat: ThreatObj | None = None
        self.fastestThreat: ThreatObj | None = None
        self.fastestCityThreat: ThreatObj | None = None
        self.fastestPotentialThreat: ThreatObj | None = None
        """A threat that could reach our general if we move our army off the general."""

        self.fastestAllyThreat: ThreatObj | None = None
        self.highestThreat: ThreatObj | None = None
        self.playerTiles = None

        self.alliedGenerals: typing.List[Tile] = [self.map.generals[self.map.player_index]]
        for teammate in self.map.teammates:
            if not self.map.players[teammate].dead:
                self.alliedGenerals.append(self.map.generals[teammate])

        self.anyThreat = False

        self.ignoreThreats = False

        self.largeVisibleEnemyTiles: typing.List[Tile] = []

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def analyze(self, defenseTiles: typing.List[Tile], depth: int, armies: typing.Dict[Tile, Army]):
        general = self.map.generals[self.map.player_index]
        self.scan(general)

        self.targets = defenseTiles
        self.fastestThreat = self.getFastestThreat(depth, armies, self.map.player_index)
        self.fastestCityThreat = self.getFastestThreat(depth, armies, self.map.player_index, generalOnly=False, requireMovement=True)
        # TODO why was this here...?
        # if self.fastestCityThreat is not None and self.fastestThreat is not None:
        #     if self.fastestCityThreat.armyAnalysis.tileB == self.fastestThreat.armyAnalysis.tileB:
        #         self.fastestCityThreat = None

        negTiles = set()
        if self.fastestThreat is not None:
            negTiles.update(self.fastestThreat.path.tileSet)
        self.fastestPotentialThreat = self.getFastestThreat(depth + 2, armies, self.map.player_index, pretendTilesVacated=True, negTiles=negTiles)
        if self.map.is_2v2:
            for teammate in self.map.teammates:
                self.fastestAllyThreat = self.getFastestThreat(depth, armies, teammate)
        self.highestThreat = self.getHighestThreat(general, depth, armies)
        self.fastestVisionThreat = self.getVisionThreat(9, armies)

        self.anyThreat = self.fastestThreat is not None or self.fastestVisionThreat is not None or self.fastestAllyThreat is not None or self.highestThreat is not None

    def getVisionThreat(self, depth: int, armies: typing.Dict[Tile, Army]) -> ThreatObj | None:
        startTime = time.perf_counter()
        logbook.info("------  VISION threat analyzer: depth {}".format(depth))
        curThreat = None

        threatenedGen = None
        for player in self.map.players:
            if (
                    not player.dead
                    and (player.index != self.map.player_index)
                    and len(self.playerTiles[player.index]) > 0
                    and self.map.players[player.index].tileCount > 10
                    and player.index not in self.map.teammates
            ):
                for general in self.alliedGenerals:
                    if player.knowsKingLocation and general.player == self.map.player_index:
                        continue
                    if player.knowsAllyKingLocation and general.player in self.map.teammates:
                        continue

                    skip = False
                    for tile in general.adjacents:
                        if tile.player != -1 and tile.player != general.player:
                            logbook.info(
                                f"not searching general vision due to tile {tile.x},{tile.y} of player {tile.player}")
                            # there is already general vision.
                            skip = True
                    if skip:
                        continue

                    path = dest_breadth_first_target(
                        map=self.map,
                        goalList=general.adjacents,
                        targetArmy=0.5,
                        maxTime=0.01,
                        maxDepth=depth,
                        negativeTiles=None,
                        searchingPlayer=player.index,
                        dontEvacCities=False,
                        dupeThreshold=2)
                    if path is not None and (curThreat is None or path.length < curThreat.length or (
                            path.length == curThreat.length and path.value > curThreat.value)):
                        # self.viewInfo.addSearched(path[1].tile)
                        logbook.info(f"dest BFS found VISION against our general:\n{str(path)}")
                        curThreat = path
                        threatenedGen = general
        threatObj = None
        if curThreat is not None:
            army = curThreat.start.tile
            if curThreat.start.tile in armies:
                army = armies[army]
            analysis = ArmyAnalyzer(self.map, threatenedGen, army)
            threatObj = ThreatObj(curThreat.length - 1, curThreat.value, curThreat, ThreatType.Vision, None, analysis)
        logbook.info(f"VISION threat analyzer took {time.perf_counter() - startTime:.3f}")
        return threatObj

    def get_threats_grouped_by_tile(
            self,
            armies: typing.Dict[Tile, Army],
            includePotentialThreat: bool = True,
            includeVisionThreat: bool = True,
            alwaysIncludeArmy: Army | None = None,
            includeArmiesWithThreats: bool = False,
            alwaysIncludeRecentlyMoved: bool = False,
    ) -> typing.Dict[Tile, typing.List[ThreatObj]]:
        threatLookup = {}
        tailLookup = {}

        def addIfNotDuplicate(threat: ThreatObj):
            tailKey = threat.path.tail.tile
            threatStart = threat.path.start.tile
            l = threatLookup.get(threatStart, [])
            if len(l) == 0:
                threatLookup[threatStart] = l

            added = tailLookup.get(threatStart, set())
            if len(added) == 0:
                tailLookup[threatStart] = added

            if tailKey not in added:
                l.append(threat)
                added.add(tailKey)

        if self.fastestThreat is not None:
            addIfNotDuplicate(self.fastestThreat)
        if self.highestThreat is not None:
            addIfNotDuplicate(self.highestThreat)
        if self.fastestCityThreat is not None:
            addIfNotDuplicate(self.fastestCityThreat)
        if self.fastestAllyThreat is not None:
            addIfNotDuplicate(self.fastestAllyThreat)
        if includePotentialThreat and self.fastestPotentialThreat is not None:
            addIfNotDuplicate(self.fastestPotentialThreat)
        if includeVisionThreat and self.fastestVisionThreat is not None:
            addIfNotDuplicate(self.fastestVisionThreat)

        for threatStart, threatList in threatLookup.items():
            army = armies.get(threatStart, None)
            if army is None:
                continue

            added = tailLookup.get(threatStart)

            for path in army.expectedPaths:
                if path.start.tile == threatStart:
                    if path.tail.tile not in added:
                        added.add(path.tail.tile)
                        threat = ThreatObj(path.length - 1, path.value, path, ThreatType.Econ, None)
                        threatList.append(threat)

        if alwaysIncludeArmy or alwaysIncludeRecentlyMoved or includeArmiesWithThreats:
            for army in armies.values():
                threatStart = army.tile
                if self.map.is_player_on_team_with(army.player, self.map.player_index):
                    continue
                if army.tile in threatLookup:
                    continue  # already added

                include = False
                if alwaysIncludeArmy == army:
                    include = True
                elif alwaysIncludeRecentlyMoved and army.last_moved_turn > self.map.turn - 2:
                    for path in army.expectedPaths:
                        include = True
                elif includeArmiesWithThreats:
                    for path in army.expectedPaths:
                        if sum(map(lambda t: 1 if self.map.is_tile_friendly(t) else 0, path.tileList)) > 3:
                            include = True
                            break

                if include:
                    added = set()
                    threatList = []
                    threatLookup[threatStart] = threatList
                    for path in army.expectedPaths:
                        if path.start.tile == threatStart:
                            if path.tail.tile not in added:
                                added.add(path.tail.tile)
                                threat = ThreatObj(path.length - 1, path.value, path, ThreatType.Econ, None)
                                threatList.append(threat)

        return threatLookup

    def get_threats_by_tile(self, tile: Tile, armies: typing.Dict[Tile, Army], includePotentialThreat: bool = True, includeVisionThreat: bool = True) -> typing.List[ThreatObj]:
        threatLookup = self.get_threats_grouped_by_tile(armies, includePotentialThreat=includePotentialThreat, includeVisionThreat=includeVisionThreat)

        threatList = threatLookup.get(tile, [])
        if len(threatList) == 0:
            army = armies.get(tile, None)
            if army is not None:
                added = set()
                for path in army.expectedPaths:
                    if path.start.tile == tile:
                        if path.tail.tile not in added:
                            added.add(path.tail.tile)
                            threat = ThreatObj(path.length - 1, path.value, path, ThreatType.Kill, None)
                            threatList.append(threat)

        return threatList

    def getFastestThreat(
            self,
            depth: int,
            armies: typing.Dict[Tile, Army],
            againstPlayer: int,
            pretendTilesVacated: bool = False,
            negTiles: typing.Set[Tile] | None = None,
            generalOnly: bool = True,
            requireMovement: bool = False
    ) -> ThreatObj | None:
        """

        @param depth:
        @param armies:
        @param againstPlayer:
        @param pretendTilesVacated:
        @param negTiles:
        @param generalOnly:
        @param requireMovement: If true, will only return threats sourced from tiles that recently moved.
        @return:
        """
        startTime = time.perf_counter()
        logbook.info(f"------  fastest threat analyzer: depth {depth}")
        curThreat = None
        saveTile = None
        # searchArmyAmount = -0.5  # commented during off by one defense issues and replaced with 0?
        # 0 has been leaving off-by-ones, trying -1.5 to see how that affects it

        isFfaMode = self.map.remainingPlayers > 2 and len(self.alliedGenerals) == 1
        genPlayer = self.map.players[againstPlayer]
        if genPlayer.dead:
            return None

        general = self.map.generals[self.map.player_index]

        threatObj = None

        if negTiles is None:
            negTiles = set()

        negativeTilesToUse = negTiles.copy()

        if pretendTilesVacated:
            for tile in self.map.players[againstPlayer].tiles:
                if not tile.isGeneral and tile.army > 7:
                    negativeTilesToUse.add(tile)

        targets = self.targets
        if generalOnly:
            targets = [general]

        searchArmyAmount = 0.5
        if pretendTilesVacated:
            searchArmyAmount -= general.army - 1

        defendableFromPlayers = set()
        for player in self.map.players:
            if player.dead:
                continue
            if player.index in self.map.teammates or player.index == self.map.player_index:
                continue
            if len(self.playerTiles[player.index]) == 0 or player.tileCount <= 2:
                continue

            if self.map.is_player_on_team_with(self.map.player_index, player.index):
                continue

            if player.score > genPlayer.score * 1.5 and isFfaMode:
                continue

            defendableFromPlayers.add(player.index)

            curNegs = negativeTilesToUse.copy()
            if player.general is not None:
                curNegs.add(player.general)

            if requireMovement:
                # we only run the other large-tile scan for movement based flagging
                continue

            path = dest_breadth_first_target(
                map=self.map,
                goalList=targets,
                targetArmy=searchArmyAmount,
                maxTime=0.05,
                maxDepth=depth,
                negativeTiles=curNegs,
                searchingPlayer=player.index,
                dontEvacCities=False,
                dupeThreshold=3,
                noLog=True)

            if (path is not None
                    and (curThreat is None
                         or path.length < curThreat.length
                         or (path.length == curThreat.length and path.value > curThreat.value))):
                # If there is NOT another path to our target that doesn't hit the same tile next to our target,
                # then we can use one extra turn on defense gathering to that 'saveTile'.
                lastTile = path.tail.prev.tile
                altPath = dest_breadth_first_target(
                    map=self.map,
                    goalList=[path.tail.tile],
                    targetArmy=searchArmyAmount,
                    maxTime=0.05,
                    maxDepth=path.length + 5,
                    negativeTiles=curNegs,
                    searchingPlayer=player.index,
                    dontEvacCities=False,
                    dupeThreshold=5,
                    skipTiles=[lastTile])
                if altPath is None or altPath.length > path.length:
                    saveTile = lastTile
                    logbook.info(f"saveTile blocks path to our king: {saveTile.x},{saveTile.y}")
                logbook.info(f"dest BFS found KILL against our target:\n{str(path)}")
                curThreat = path
                depth = path.length + 1

        for armyTile, army in armies.items():
            # if this is an army in the fog that isn't on a tile owned by that player, lets see if we need to path it.
            # if army.player != target.player:
            if armyTile.visible and not requireMovement:
                continue

            if armyTile.player == army.player and not requireMovement:
                continue  # covered under normal search above

            if army.player not in defendableFromPlayers:
                continue

            if self.map.is_tile_friendly(armyTile):
                continue

            if armyTile.player in self.map.teammates:
                continue

            if not army.visible and army.last_moved_turn < self.map.turn - 4:
                continue  # dont defend against invisible predicted threats that probably arent real

            if requireMovement and army.last_moved_turn < self.map.turn - 2:
                continue

            startTiles = {}
            startTiles[armyTile] = ((0, 0, 0, 0 - army.value, armyTile.x, armyTile.y, 0.5), 0)
            goalFunc = lambda tile, prio: tile in targets
            path = breadth_first_dynamic(
                self.map,
                startTiles,
                goalFunc,
                0.2,
                depth,
                noNeutralCities=army.value < 150,
                searchingPlayer=army.player,
                incrementBackward=True)
            if path is not None:
                logbook.info(
                    f"Army tile mismatch threat searcher found a path! Army {str(army)}, path {str(path)}")
                if path.value > 0 and (
                        curThreat is None or path.length < curThreat.length or (path.value > curThreat.value and path.length == curThreat.length)):
                    curThreat = path
                army.expectedPaths.append(path)

        if curThreat is not None:
            army = curThreat.start.tile
            if curThreat.start.tile in armies:
                army = armies[army]
            analysis = ArmyAnalyzer(self.map, curThreat.tail.tile, army)
            threatObj = ThreatObj(curThreat.length - 1, curThreat.value, curThreat, ThreatType.Kill, saveTile, analysis)
            return threatObj
        else:
            logbook.info("no fastest threat found")
        return threatObj

    def getHighestThreat(self, general: Tile, depth: int, armies: typing.Dict[Tile, Army]):
        return self.fastestThreat

    def scan(self, general: Tile):
        self.largeVisibleEnemyTiles = []
        self.playerTiles = [[] for player in self.map.players]
        for tile in self.map.get_all_tiles():
            if tile.player == -1:
                continue

            self.playerTiles[tile.player].append(tile)

            if (tile.player not in self.map.teammates
                    and tile.player != general.player
                    and tile.army > max(2, general.army // 4)
                    and tile.visible
                    and not tile.isGeneral):
                self.largeVisibleEnemyTiles.append(tile)
