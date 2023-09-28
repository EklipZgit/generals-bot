"""
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
"""

import logging
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

    def convert_to_dist_dict(self, offset: int = -1) -> typing.Dict[Tile, int]:
        dict = self.path.get_reversed().convert_to_dist_dict(offset=-1)
        for tile in self.path.tileSet:
            if tile.isGeneral:
                # need to gather to general 1 turn earlier than otherwise necessary
                dict[tile] = dict[tile] + 1

        return dict


class DangerAnalyzer(object):
    def __init__(self, map):
        self.map: MapBase = map
        self.fastestVisionThreat: typing.Union[None, ThreatObj] = None
        self.fastestThreat: typing.Union[None, ThreatObj] = None
        self.highestThreat: typing.Union[None, ThreatObj] = None
        self.playerTiles = None

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

    def analyze(self, general: Tile, depth: int, armies: typing.Dict[Tile, Army]):
        self.scan(general)

        self.fastestThreat = self.getFastestThreat(general, depth, armies)
        self.highestThreat = self.getHighestThreat(general, depth, armies)
        self.fastestVisionThreat = self.getVisionThreat(general, 9, armies)

        self.anyThreat = self.fastestThreat is not None or self.fastestVisionThreat is not None or self.highestThreat is not None

    def getVisionThreat(self, general: Tile, depth: int, armies: typing.Dict[Tile, Army]):
        startTime = time.time()
        logging.info("------  VISION threat analyzer: depth {}".format(depth))
        curThreat = None
        for tile in general.adjacents:
            if tile.player != -1 and tile.player != general.player:
                logging.info(
                    f"not searching general vision due to tile {tile.x},{tile.y} of player {tile.player}")
                # there is already general vision.
                return None
        for player in self.map.players:
            if not player.dead and (player.index != general.player) and len(self.playerTiles[player.index]) > 0 and \
                    self.map.players[player.index].tileCount > 10:
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
                    logging.info(f"dest BFS found VISION against our general:\n{str(path)}")
                    curThreat = path
        threatObj = None
        if curThreat is not None:
            army = curThreat.start.tile
            if curThreat.start.tile in armies:
                army = armies[army]
            analysis = ArmyAnalyzer(self.map, general, army)
            threatObj = ThreatObj(curThreat.length - 1, curThreat.value, curThreat, ThreatType.Vision, None, analysis)
        logging.info(f"VISION threat analyzer took {time.time() - startTime:.3f}")
        return threatObj

    def getFastestThreat(self, general: Tile, depth: int, armies: typing.Dict[Tile, Army]):
        startTime = time.time()
        logging.info(f"------  fastest threat analyzer: depth {depth}")
        curThreat = None
        saveTile = None
        # searchArmyAmount = -0.5  # commented during off by one defense issues and replaced with 0?
        # 0 has been leaving off-by-ones, trying -1.5 to see how that affects it

        genPlayer = self.map.players[general.player]

        isFfaMode = self.map.remainingPlayers > 2

        searchArmyAmount = 0.5
        defendableFromPlayers = set()
        for player in self.map.players:
            if player.dead:
                continue
            if player.index == general.player or player.index in self.map.teammates:
                continue
            if len(self.playerTiles[player.index]) == 0 or player.tileCount <= 2:
                continue
            if player.score > genPlayer.score * 1.5 and isFfaMode:
                continue

            defendableFromPlayers.add(player.index)

            path = dest_breadth_first_target(
                map=self.map,
                goalList=[general],
                targetArmy=searchArmyAmount,
                maxTime=0.05,
                maxDepth=depth,
                negativeTiles=None,
                searchingPlayer=player.index,
                dontEvacCities=False,
                dupeThreshold=3,
                noLog=True)
            if (path is not None
                    and (curThreat is None
                         or path.length < curThreat.length
                         or (path.length == curThreat.length and path.value > curThreat.value))):
                # If there is NOT another path to our general that doesn't hit the same tile next to our general,
                # then we can use one extra turn on defense gathering to that 'saveTile'.
                lastTile = path.tail.prev.tile
                altPath = dest_breadth_first_target(
                    map=self.map,
                    goalList=[general],
                    targetArmy=searchArmyAmount,
                    maxTime=0.05,
                    maxDepth=path.length + 5,
                    negativeTiles=None,
                    searchingPlayer=player.index,
                    dontEvacCities=False,
                    dupeThreshold=5,
                    skipTiles=[lastTile])
                if altPath is None or altPath.length > path.length:
                    saveTile = lastTile
                    logging.info(f"saveTile blocks path to our king: {saveTile.x},{saveTile.y}")
                logging.info(f"dest BFS found KILL against our general:\n{str(path)}")
                curThreat = path
                # path.calculate_value(forPlayer=player.index)

        for armyTile, army in armies.items():
            # if this is an army in the fog that isn't on a tile owned by that player, lets see if we need to path it.
            # if army.player != general.player:
            if armyTile.visible:
                continue

            if army.player not in defendableFromPlayers:
                continue

            if armyTile.player == army.player:
                continue  # covered under normal search above

            if army.last_moved_turn < self.map.turn - 4:
                continue  # dont defend against invisible predicted threats that probably arent real

            startTiles = {}
            startTiles[armyTile] = ((0, 0, 0, 0 - army.value - 1, armyTile.x, armyTile.y, 0.5), 0)
            goalFunc = lambda tile, prio: tile == general
            path = breadth_first_dynamic(
                self.map,
                startTiles,
                goalFunc,
                0.2,
                depth,
                noNeutralCities=army.value < 150,
                searchingPlayer=army.player)
            if path is not None:
                logging.info(
                    f"Army tile mismatch threat searcher found a path! Army {str(army)}, path {str(path)}")
                if path.value > 0 and (
                        curThreat is None or path.length < curThreat.length or path.value > curThreat.value):
                    curThreat = path
                army.expectedPath = path
        threatObj = None
        if curThreat is not None:
            army = curThreat.start.tile
            if curThreat.start.tile in armies:
                army = armies[army]
            analysis = ArmyAnalyzer(self.map, general, army)
            threatObj = ThreatObj(curThreat.length - 1, curThreat.value, curThreat, ThreatType.Kill, saveTile, analysis)
        else:
            logging.info("no fastest threat found")
        logging.info(f"fastest threat analyzer took {time.time() - startTime:.3f}")
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
