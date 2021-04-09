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
	def __init__(self, map, general):
		startTime = time.time()
		self.map = map
		self.general = general
		self.should_rescan = False

		self.innerChokes = None
		self.outerChokes = None

		self.intergeneral_analysis = None

		self.rescan_chokes()

		logging.info("BoardAnalyzer completed in {:.3f}".format(time.time() - startTime))

	def rescan_chokes(self):
		self.should_rescan = False
		oldInner = self.innerChokes
		oldOuter = self.outerChokes
		self.innerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
		self.outerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
		self.genDistMap = build_distance_map(self.map, [self.general])
		for tile in self.map.reachableTiles:
			logging.info("Rescanning chokes for {}".format(tile.toString()))
			tileDist = self.genDistMap[tile.x][tile.y]
			moveableInnerCount = count(tile.moveable, lambda adj: tileDist == self.genDistMap[adj.x][adj.y] - 1)
			if moveableInnerCount == 1:
				self.outerChokes[tile.x][tile.y] = True
			moveableOuterCount = count(tile.moveable, lambda adj: tileDist == self.genDistMap[adj.x][adj.y] + 1)
			# checking moveableInner to avoid considering dead ends 'chokes'
			if moveableOuterCount == 1 and moveableInnerCount >= 1:
				self.innerChokes[tile.x][tile.y] = True
			if self.map.turn > 4:
				if oldInner != None and oldInner[tile.x][tile.y] != self.innerChokes[tile.x][tile.y]:
					logging.info("  inner choke change: tile {}, old {}, new {}".format(tile.toString(), oldInner[tile.x][tile.y], self.innerChokes[tile.x][tile.y]))
				if oldOuter != None and oldOuter[tile.x][tile.y] != self.outerChokes[tile.x][tile.y]:
					logging.info("  outer choke change: tile {}, old {}, new {}".format(tile.toString(), oldOuter[tile.x][tile.y], self.outerChokes[tile.x][tile.y]))

	def rebuild_intergeneral_analysis(self, opponentGeneral):
		self.intergeneral_analysis = ArmyAnalyzer(self.map, self.general, opponentGeneral)

	# minAltPathCount will force that many paths to be included even if they are greater than maxAltLength
	def find_flank_leaves(self, leafMoves, minAltPathCount, maxAltLength):
		goodLeaves = []

		# order by: totalDistance, then pick tile by closestToOpponent

		includedPathways = set()
		for move in leafMoves:
			# sometimes these might be cut off by only being routed through the general
			neutralCity = (move.dest.isCity and move.dest.player == -1)
			if not neutralCity and move.dest in self.intergeneral_analysis.pathways and move.source in self.intergeneral_analysis.pathways:
				pathwaySource = self.intergeneral_analysis.pathways[move.source]
				pathwayDest = self.intergeneral_analysis.pathways[move.dest]
				if pathwaySource.distance <= maxAltLength:
					#if pathwaySource not in includedPathways:
					if pathwaySource.distance > pathwayDest.distance or pathwaySource.distance == pathwayDest.distance:
						# moving to a shorter path or moving along same distance path
						# If getting further from our general (and by extension closer to opp since distance is equal)
						gettingFurtherFromOurGen = self.intergeneral_analysis.aMap[move.source.x][move.source.y] < self.intergeneral_analysis.aMap[move.dest.x][move.dest.y]
						# not more than cutoffDist tiles behind our general, effectively
						cutoffDist = 5
						reasonablyCloseToTheirGeneral = self.intergeneral_analysis.bMap[move.dest.x][move.dest.y] < cutoffDist + self.intergeneral_analysis.aMap[self.intergeneral_analysis.tileB.x][self.intergeneral_analysis.tileB.y]
					
						if (gettingFurtherFromOurGen and reasonablyCloseToTheirGeneral):
							includedPathways.add(pathwaySource)
							goodLeaves.append(move)
					else:
						logging.info("Pathway for tile {} was already included, skipping".format(move.source.toString()))

		return goodLeaves
