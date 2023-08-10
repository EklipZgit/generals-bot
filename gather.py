'''
@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
April 2017
Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
EklipZ bot - Tries to play generals lol
'''

import logging
import random
from copy import deepcopy
import time
import json
from collections import deque 
from queue import PriorityQueue
from pprint import pprint,pformat
from SearchUtils import a_star_kill, dest_breadth_first_target
from DataModels import stringPath, PathFromPathNode, get_tile_list_from_path, get_tile_list_from_path_tuple
from enum import Enum


#def breadth_first_gather(searchingPlayer, startTiles, maxTime = 0.1, maxDepth = 30, negativeTiles = None, avoidTiles = None, leafValueGrid = None, map = None):
#	origStartTiles = startTiles
#	startTiles = set(startTiles)
#	frontier = PriorityQueue()
#	visitedBack = [[None for x in range(map.rows)] for y in range(map.cols)]
#	visitedFwd = [[None for x in range(map.rows)] for y in range(map.cols)]
#	visitedSet = set()
#	# visitedSet.add((goal.x, goal.y))
#	# visited[goal.x][goal.y][0] = (startArmy, None)

#	# sort on distance, then army, then x and y (to stop the paths from shuffling randomly and looking annoying)
#	start = time.time()
#	for tile in startTiles:
#		startArmy = tile.army
#		if (tile.player != searchingPlayer):
#			startArmy = 0 - tile.army
#		frontier.put((0, 0 - startArmy, tile.x, tile.y, tile, None, 0))
#	iter = 0
#	depthEvaluated = 0
#	while not frontier.empty():
#		iter += 1
#		if (iter % 100 == 0 and time.time() - start > maxTime):
#			break
			
#		(dist, popArmy, x, y, current, cameFrom, neutCount) = frontier.get()
#		army = 0 - popArmy
			
			
#		if (current in visitedSet):
#			continue
#		if (current.isMountain or not current.discovered and current.isNotPathable):
#			continue
#		if (current.isCity and current.player != searchingPlayer and not current in startTiles):
#			continue
#		visitedSet.add(current)
#		visitedBack[current.x][current.y] = cameFrom
#		if cameFrom != None:
#			visitedFwd[cameFrom.x][cameFrom.y] = current
#		x = current.x
#		y = current.y
#		# if (current.isGeneral and current.player == searchingPlayer and not self.general_move_safe(visited[current.x][current.y][dist - 1][1])):
#		# if (current.isGeneral and current.player == searchingPlayer):
#		# 	continue

#		if dist > depthEvaluated:
#			depthEvaluated = dist
#		if (dist <= maxDepth):
#			for next in current.movable: #new spots to try
#				if avoidTiles != None and next in avoidTiles:
#					continue
#				# self.viewInfo.evaluatedGrid[next.x][next.y] += 1
#				# inc = 0 if not (next.isCity or next.isGeneral) else dist / 2
#				#new_cost = cost_so_far[current] + graph.cost(current, next)
#				nextArmy = army - 1
#				if (negativeTiles == None or next not in negativeTiles):
#					if (searchingPlayer == next.player):
#						nextArmy += next.army
#					else:
#						nextArmy -= next.army
#				newNeutCount = neutCount
#				if (next.player == -1):
#					newNeutCount += 1
#				newDist = dist + 1
#				# if newDist not in visited[next.x][next.y] or visited[next.x][next.y][newDist][0] < nextArmy:
#				# 	visited[next.x][next.y][newDist] = (nextArmy, current)
#				frontier.put((newDist, 0 - nextArmy, next.x, next.y, next, current, newNeutCount))

#	logging.info("BFS GATHER ITERATIONS {}, DURATION: {}, DEPTH: {}".format(iter, time.time() - start, depthEvaluated))

#	result = self.breadth_first_gather_rebuild(startTiles, visitedBack, map.player_index)
		
#	return result

#def breadth_first_gather_rebuild(self, startTiles, fromMap, searchingPlayer):
#	results = []
#	for tile in startTiles:
#		gather = self.get_gather(tile, None, fromMap, 0, searchingPlayer)
#		if (gather.tile.player == searchingPlayer):
#			gather.value -= gather.tile.army
#		else:
#			gather.value += gather.tile.army
				
#		results.append(gather)
#	return results

#def get_gather(self, tile, fromTile, fromMap, turn, searchingPlayer):
#	gatherTotal = tile.army
#	turnTotal = 1
#	if (tile.player != searchingPlayer):
#		gatherTotal = 0 - tile.army
#	gatherTotal -= 1
#	thisNode = GatherNode(tile, fromTile, turn)
#	if (tile.player == -1):
#		thisNode.neutrals = 1
#	for move in tile.movable:
#		# logging.info("evaluating {},{}".format(move.x, move.y))
#		if (move == fromTile):
#			# logging.info("move == fromTile  |  {},{}".format(move.x, move.y))
#			continue
#		if (fromMap[move.x][move.y] != tile):
#			# logging.info("fromMap[move.x][move.y] != tile  |  {},{}".format(move.x, move.y))
#			continue
#		gather = self.get_gather(move, tile, fromMap, turn + 1, searchingPlayer)
#		if (gather.value > 0):
#			gatherTotal += gather.value
#			turnTotal += gather.gatherTurns
#			thisNode.children.append(gather)
#			thisNode.neutrals += gather.neutrals
				
#	thisNode.value = gatherTotal
#	thisNode.gatherTurns = turnTotal
#	if thisNode.tile.isCity:
#		thisNode.value -= 10
#	if (thisNode.value > 0):
#		self.leafValueGrid[thisNode.tile.x][thisNode.tile.y] = thisNode.value
#	# logging.info("{},{} ({}  {})".format(thisNode.tile.x, thisNode.tile.y, thisNode.value, thisNode.gatherTurns))
#	return thisNode

#def get_gather_move(searchingPlayer, gathers, parent, minGatherAmount = 0, pruneThreshold = None, preferNeutral = True, allowNonKill = False, map = None):
#	if pruneThreshold == None:
#		player = searchingPlayer
#		pruneThreshPercent = 45
#		pruneThreshold = self.get_median_tile_value(pruneThreshPercent) - 1
#		logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(20, self.get_median_tile_value(20)))
#		logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(35, self.get_median_tile_value(35)))
#		logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(50, self.get_median_tile_value(50)))
#		logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(65, self.get_median_tile_value(65)))
#		logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(75, self.get_median_tile_value(75)))
#		logging.info("~!~!~!~!~!~!~ pruneThreshold {}: {}".format(pruneThreshPercent, pruneThreshold))

#		pruneThreshold = (player.standingArmy - self.general.army) / player.tileCount
#		logging.info("~!~!~!~!~!~!~ pruneThreshold via average {}%: {}".format(pruneThreshPercent, pruneThreshold))
#	start = time.time()
#	logging.info("Gathering :)")
#	move = self._get_gather_move_int(gathers, parent, minGatherAmount, pruneThreshold, preferNeutral, allowNonKill = allowNonKill)
#	if move == None and pruneThreshold > 0:
#		newThreshold = max(0, self.get_median_tile_value(25) - 2)
#		logging.info("\nEEEEEEEEEEEEEEEEEEEEEEEE\nEEEEEEEEE\nEE\nNo move found for pruneThreshold {}, retrying with {}".format(pruneThreshold, newThreshold))
#		move = self._get_gather_move_int(gathers, parent, minGatherAmount, newThreshold, preferNeutral, allowNonKill = allowNonKill)
#	if move == None:
#		logging.info("\nNo move found......... :(")
#		newThreshold = 0
#		logging.info("\nEEEEEEEEEEEEEEEEEEEEEEEE\nEEEEEEEEE\nEE\nNo move found for pruneThreshold {}, retrying with {}".format(pruneThreshold, newThreshold))
#		move = self._get_gather_move_int(gathers, parent, minGatherAmount, newThreshold, preferNeutral, allowNonKill = allowNonKill)
#	if move == None:
#		logging.info("\nNo move found......... :(")
#	logging.info("GATHER MOVE DURATION: {}".format(time.time() - start))
#	return move

#def _get_gather_move_int(self, gathers, parent, minGatherAmount = 0, pruneThreshold = 0, preferNeutral = False, allowNonKill = False):
#	move = None
#	maxGather = None
#	for gather in gathers:
#		#if maxGather == None or (gather.value - gather.tile.army) / gather.gatherTurns > (maxGather.value - maxGather.tile.army) / maxGather.gatherTurns:
#		if (gather.value / gather.gatherTurns > pruneThreshold and gather.value >= minGatherAmount 
#				and compare_gathers(maxGather, gather, preferNeutral)):
#			maxGather = gather
#	# if maxGather != None and (parent == None or maxGather.value / maxGather.gatherTurns > parent.value / parent.gatherTurns):
#	if maxGather != None:
#		gatherWorthwhile = is_gather_worthwhile(maxGather, parent)
#		if parent == None or gatherWorthwhile:
#			move = self._get_gather_move_int(maxGather.children, maxGather, minGatherAmount, pruneThreshold, preferNeutral, allowNonKill)
#		if self.is_move_safe_valid(move, allowNonKill = allowNonKill):
#			logging.info("Returning child move {},{} -> {},{}".format(move.source.x, move.source.y, move.dest.x, move.dest.y))
#			return move
#		if parent != None:
#			if maxGather.tile.army <= 1 or maxGather.tile.player != self._map.player_index:
#				logging.info("WTF tried to move {},{} with 1 or less army :v".format(maxGather.tile.x, maxGather.tile.y))
#			elif maxGather.value > 0:
#				logging.info("Returning {},{} -> {},{}".format(maxGather.tile.x, maxGather.tile.y, parent.tile.x, parent.tile.y))
#				parent.children.remove(maxGather)
#				return Move(maxGather.tile, parent.tile)
#	logging.info("FUCK! NO POSITIVE GATHER MOVE FOUND")
#	return None