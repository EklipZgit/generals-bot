'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	July 2019
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

import logging
import time
import json
from ArmyAnalyzer import *
from SearchUtils import *
from collections import deque 
from queue import PriorityQueue 
from Path import Path


class BoardAnalyzer:
	def __init__(self, map: MapBase, general: Tile):
		startTime = time.time()
		self.map: MapBase = map
		self.general: Tile = general
		self.should_rescan = False

		self.innerChokes: typing.List[typing.List[bool]] = None
		self.outerChokes: typing.List[typing.List[bool]] = None

		self.intergeneral_analysis: ArmyAnalyzer = None

		self.rescan_chokes()

		logging.info("BoardAnalyzer completed in {:.3f}".format(time.time() - startTime))

	def __getstate__(self):
		state = self.__dict__.copy()
		if "map" in state:
			del state["map"]
		return state

	def __setstate__(self, state):
		self.__dict__.update(state)
		self.map = None

	def rescan_chokes(self):
		self.should_rescan = False
		oldInner = self.innerChokes
		oldOuter = self.outerChokes
		self.innerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
		"""What are these???"""

		self.outerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
		"""What are these???"""

		self.genDistMap = build_distance_map(self.map, [self.general])
		for tile in self.map.pathableTiles:
			logging.info("Rescanning chokes for {}".format(tile.toString()))
			tileDist = self.genDistMap[tile.x][tile.y]
			movableInnerCount = count(tile.movable, lambda adj: tileDist == self.genDistMap[adj.x][adj.y] - 1)
			if movableInnerCount == 1:
				self.outerChokes[tile.x][tile.y] = True
			movableOuterCount = count(tile.movable, lambda adj: tileDist == self.genDistMap[adj.x][adj.y] + 1)
			# checking movableInner to avoid considering dead ends 'chokes'
			if movableOuterCount == 1 and movableInnerCount >= 1:
				self.innerChokes[tile.x][tile.y] = True
			if self.map.turn > 4:
				if oldInner != None and oldInner[tile.x][tile.y] != self.innerChokes[tile.x][tile.y]:
					logging.info("  inner choke change: tile {}, old {}, new {}".format(tile.toString(), oldInner[tile.x][tile.y], self.innerChokes[tile.x][tile.y]))
				if oldOuter != None and oldOuter[tile.x][tile.y] != self.outerChokes[tile.x][tile.y]:
					logging.info("  outer choke change: tile {}, old {}, new {}".format(tile.toString(), oldOuter[tile.x][tile.y], self.outerChokes[tile.x][tile.y]))

	def rebuild_intergeneral_analysis(self, opponentGeneral):
		self.intergeneral_analysis = ArmyAnalyzer(self.map, self.general, opponentGeneral)

	def get_tile_usefulness_score(self, x: int, y: int):
		# score a tile based on how far out of the play area it is and whether it is on a good flank path
		return 100

	def get_flank_pathways(
			self,
			filter_out_players: typing.List[int] | None = None,
	) -> typing.Set[Tile]:
		flankDistToCheck = int(self.intergeneral_analysis.shortestPathWay.distance * 1.5)
		flankPathTiles = set()
		for pathway in self.intergeneral_analysis.pathWays:
			if pathway.distance < flankDistToCheck and len(pathway.tiles) >= self.intergeneral_analysis.shortestPathWay.distance:
				for tile in pathway.tiles:
					if filter_out_players is None or tile.player not in filter_out_players:
						flankPathTiles.add(tile)

		return flankPathTiles

	# minAltPathCount will force that many paths to be included even if they are greater than maxAltLength
	def find_flank_leaves(
			self,
			leafMoves,
			minAltPathCount,
			maxAltLength
	) -> typing.List[Move]:
		goodLeaves: typing.List[Move] = []

		# order by: totalDistance, then pick tile by closestToOpponent
		cutoffDist = self.intergeneral_analysis.shortestPathWay.distance // 4
		includedPathways = set()
		for move in leafMoves:
			# sometimes these might be cut off by only being routed through the general
			neutralCity = (move.dest.isCity and move.dest.player == -1)
			if not neutralCity and move.dest in self.intergeneral_analysis.pathWayLookupMatrix and move.source in self.intergeneral_analysis.pathWayLookupMatrix:
				pathwaySource = self.intergeneral_analysis.pathWayLookupMatrix[move.source]
				pathwayDest = self.intergeneral_analysis.pathWayLookupMatrix[move.dest]
				if pathwaySource.distance <= maxAltLength:
					#if pathwaySource not in includedPathways:
					if pathwaySource.distance > pathwayDest.distance or pathwaySource.distance == pathwayDest.distance:
						# moving to a shorter path or moving along same distance path
						# If getting further from our general (and by extension closer to opp since distance is equal)
						gettingFurtherFromOurGen = self.intergeneral_analysis.aMap[move.source.x][move.source.y] < self.intergeneral_analysis.aMap[move.dest.x][move.dest.y]
						# not more than cutoffDist tiles behind our general, effectively

						reasonablyCloseToTheirGeneral = self.intergeneral_analysis.bMap[move.dest.x][move.dest.y] < cutoffDist + self.intergeneral_analysis.aMap[self.intergeneral_analysis.tileB.x][self.intergeneral_analysis.tileB.y]
					
						if (gettingFurtherFromOurGen and reasonablyCloseToTheirGeneral):
							includedPathways.add(pathwaySource)
							goodLeaves.append(move)
					else:
						logging.info("Pathway for tile {} was already included, skipping".format(move.source.toString()))

		return goodLeaves
