'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

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
        self.map = map
        self.fastestVisionThreat: typing.Union[None, ThreatObj] = None
        self.fastestThreat: typing.Union[None, ThreatObj] = None
        self.highestThreat: typing.Union[None, ThreatObj] = None
        self.playerTiles = None

        self.anyThreat = False

        self.ignoreThreats = False

        self.largeVisibleEnemyTiles: typing.List[Tile] = []

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
                    "not searching general vision due to tile {},{} of player {}".format(tile.x, tile.y, tile.player))
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
                    logging.info("dest BFS found VISION against our general:\n{}".format(path.toString()))
                    curThreat = path
        threatObj = None
        if curThreat is not None:
            army = curThreat.start.tile
            if curThreat.start.tile in armies:
                army = armies[army]
            analysis = ArmyAnalyzer(self.map, general, army)
            threatObj = ThreatObj(curThreat.length - 1, curThreat.value, curThreat, ThreatType.Vision, None, analysis)
        logging.info("VISION threat analyzer took {:.3f}".format(time.time() - startTime))
        return threatObj

    def getFastestThreat(self, general: Tile, depth: int, armies: typing.Dict[Tile, Army]):
        startTime = time.time()
        logging.info("------  fastest threat analyzer: depth {}".format(depth))
        curThreat = None
        saveTile = None
        # searchArmyAmount = -0.5  # commented during off by one defense issues and replaced with 0?
        # 0 has been leaving off-by-ones, trying -1.5 to see how that affects it
        searchArmyAmount = 0.5
        for player in self.map.players:
            if (not player.dead
                    and player.index != general.player
                    and player.index not in self.map.teammates
                    and len(self.playerTiles[player.index]) > 0
                    and self.map.players[player.index].tileCount > 10):
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
                    noLog=False)
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
                        logging.info("saveTile blocks path to our king: {},{}".format(saveTile.x, saveTile.y))
                    logging.info("dest BFS found KILL against our general:\n{}".format(path.toString()))
                    curThreat = path
                    # path.calculate_value(forPlayer=player.index)
        for armyTile in armies.keys():
            army = armies[armyTile]
            # if this is an army in the fog that isn't on a tile owned by that player, lets see if we need to path it.
            if not armyTile.visible and armyTile.player != army.player and army.player != general.player:
            # if army.player != general.player:
                startTiles = {}
                startTiles[armyTile] = ((0, 0, 0, 0 - army.value - 1, armyTile.x, armyTile.y, 0.5), 0)
                goalFunc = lambda tile, prio: tile == general
                path = breadth_first_dynamic(self.map, startTiles, goalFunc, 0.2, depth, noNeutralCities=True,
                                             searchingPlayer=army.player)
                if path is not None:
                    logging.info("Army thingy found a path! Army {}, path {}".format(army.toString(), path.toString()))
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
        logging.info("fastest threat analyzer took {:.3f}".format(time.time() - startTime))
        return threatObj

    def getHighestThreat(self, general: Tile, depth: int, armies: typing.Dict[Tile, Army]):
        return self.fastestThreat

    def scan(self, general: Tile):
        self.largeVisibleEnemyTiles = []
        self.playerTiles = [[] for player in self.map.players]
        for x in range(self.map.cols):
            for y in range(self.map.rows):
                tile = self.map.grid[y][x]
                if tile.player != -1:
                    self.playerTiles[tile.player].append(tile)
                    if (tile.player not in self.map.teammates and tile.player != general.player and tile.army > max(2,
                                                                                                                    general.army // 4) and tile.visible and not tile.isGeneral):
                        self.largeVisibleEnemyTiles.append(tile)
