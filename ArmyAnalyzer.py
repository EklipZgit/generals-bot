'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	July 2019
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

import logging
import time
import json
from ArmyTracker import *
from SearchUtils import *
from collections import deque 
from queue import PriorityQueue 
from Path import Path
from base.client.map import Tile, MapMatrix


class PathWay:
	def __init__(self, distance):
		self.distance = distance
		self.tiles = set()
		self.seed_tile = None

	def add_tile(self, tile):
		self.tiles.add(tile)
		if self.seed_tile == None:
			self.seed_tile = tile
class InfPathWay:
	def __init__(self, tile):
		self.distance = INF
		self.tiles = set()
		self.tiles.add(tile)
		self.seed_tile = tile
		
SENTINAL = "~"

class ArmyAnalyzer:
	def __init__(self, map, armyA: Tile, armyB: Tile, maxDist = 1000):
		startTime = time.time()
		self.map = map
		self.tileA: Tile = armyA
		self.tileB: Tile = armyB
		# path chokes are relative to the paths between A and B
		self.pathChokes: typing.Set[Tile] = set()
		self.pathways = MapMatrix(map, initVal=None)
		self.shortestPathWay: PathWay = PathWay(distance=INF)

		if type(armyA) is Army:
			self.tileA = armyA.tile
		if type(armyB) is Army:
			self.tileB = armyB.tile
		logging.info("ArmyAnalyzer analyzing {} and {}".format(self.tileA.toString(), self.tileB.toString()))
			
		# a map of distances from point A
		self.aMap = build_distance_map(self.map, [self.tileA], [self.tileB])
		closestTile = min(self.tileB.moveable, key=lambda tile: self.aMap[tile.x][tile.y])
		self.aMap[self.tileB.x][self.tileB.y] = self.aMap[closestTile.x][closestTile.y] + 1
		logging.info("set aMap({}) to {}".format(self.tileB.toString(), self.aMap[self.tileB.x][self.tileB.y]))
		# a map of distances from point B
		self.bMap = build_distance_map(self.map, [self.tileB], [self.tileA])
		closestTile = min(self.tileA.moveable, key=lambda tile: self.bMap[tile.x][tile.y])
		self.bMap[self.tileA.x][self.tileA.y] = self.bMap[closestTile.x][closestTile.y] + 1
		logging.info("set bMap({}) to {}".format(self.tileA.toString(), self.bMap[self.tileA.x][self.tileA.y]))

		self.scan()
		logging.info("ArmyAnalyzer completed for tiles {} and {} in {:.3f}".format(self.tileA.toString(), self.tileB.toString(), time.time() - startTime))

	def scan(self):
		chokeCounterMap = {}
		minPath = PathWay(distance=INF)
		for tile in self.map.reachableTiles:
			# build the pathway
			if tile not in self.pathways:
				path = self.build_pathway(tile)
				if path.distance < minPath.distance:
					minPath = path

			# map out choke counts. TODO i don't think this pathChoke stuff works :/ make sure to visualize it well and debug.
			chokeKey = (self.aMap[tile.x][tile.y], self.bMap[tile.x][tile.y])
			if not chokeKey in chokeCounterMap:
				chokeCounterMap[chokeKey] = 1
			else:
				chokeCounterMap[chokeKey] += 1
			

		for tile in self.map.reachableTiles:
			chokeKey = (self.aMap[tile.x][tile.y], self.bMap[tile.x][tile.y])
			if tile in self.pathways:
				path = self.pathways[tile]
				if chokeCounterMap[chokeKey] == 1:
					#logging.info("  (maybe) found choke at {}? Testing for shorter pathway joins".format(tile.toString()))
					shorter = count(tile.moveable, lambda adjTile: adjTile in self.pathways and self.pathways[adjTile].distance < path.distance)
					if shorter == 0:
						#logging.info("    OK WE DID FIND A CHOKEPOINT AT {}! adding to self.pathChokes".format(tile.toString()))
						# Todo this should probably be on pathways lol
						self.pathChokes.add(tile)

		self.shortestPathWay = minPath


	def build_pathway(self, tile) -> PathWay:
		distance = self.aMap[tile.x][tile.y] + self.bMap[tile.x][tile.y]
		#logging.info("  building pathway from tile {} distance {}".format(tile.toString(), distance))
		path = PathWay(distance = distance)

		queue = deque()
		queue.appendleft(tile)
		while not len(queue) == 0:
			currentTile = queue.pop()
			if currentTile in self.pathways:
				continue
			currentTileDistance = self.aMap[currentTile.x][currentTile.y] + self.bMap[currentTile.x][currentTile.y]
			if currentTileDistance < 300:
				#so not inf
				if currentTileDistance == distance:
					#logging.info("    adding tile {}".format(currentTile.toString()))
					path.add_tile(currentTile)
					self.pathways[currentTile] = path

					for adjacentTile in currentTile.moveable:
						queue.appendleft(adjacentTile)
		return path



