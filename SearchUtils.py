'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

import logging
import typing
from copy import deepcopy
import time
import json
from collections import deque 
from queue import PriorityQueue
from pprint import pprint,pformat
from DataModels import PathNode, TreeNode, Move
from Path import Path, PathMove
from test.test_float import INF
from ViewInfo import ViewInfo, PathColorer





class Counter(object):
	def __init__(self, value):
		self.value = value

	def add(self, value):
		self.value = self.value + value
		
def new_map_matrix(map, initialValueXYFunc):
	return [[initialValueXYFunc(x, y) for y in range(map.rows)] for x in range(map.cols)]
		
def new_tile_matrix(map, initialValueTileFunc):
	return [[initialValueTileFunc(map.grid[y][x]) for y in range(map.rows)] for x in range(map.cols)]

def new_value_matrix(map, initValue) -> typing.List[typing.List[int]]:
	return [[initValue] * map.rows for _ in range(map.cols)]

	

def where(list, filter):
	results = []
	for item in list:
		if filter(item):
			results.append(item)
	return results

def any(list, filter):
	for item in list:
		if filter(item):
			return True
	return False

def count(list, filter):
	count = 0
	for item in list:
		if filter(item):
			count += 1
	return count


def dest_breadth_first_target(map, goalList, targetArmy = 1, maxTime = 0.1, maxDepth = 20, 
							  negativeTiles = None, 
							  searchingPlayer = -2, 
							  dontEvacCities = False, 
							  dupeThreshold = 3, 
							  noNeutralCities = True, 
							  skipTiles = None, 
							  ignoreGoalArmy = False, 
							  noLog = True):
	'''
	GoalList can be a dict that maps from start tile to (startDist, goalTargetArmy)
	'''
	if (searchingPlayer == -2):
		searchingPlayer = map.player_index
	frontier = PriorityQueue()
	visited = [[None for _ in range(map.rows)] for _ in range(map.cols)]
	if isinstance(goalList, dict):
		for goal in goalList.keys():
			(startDist, goalTargetArmy, goalIncModifier) = goalList[goal]			
			if goal.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue			

			goalInc = goalIncModifier
			startArmy = goalIncModifier
			
			if searchingPlayer != goal.player:
				startArmy = 0 + goalTargetArmy
			else:
				startArmy = 0 - goalTargetArmy

			if ignoreGoalArmy:
				# then we have to inversely increment so we dont have to figure that out in the loop every time
				if searchingPlayer != goal.player:
					if (negativeTiles is None or goal not in negativeTiles):
						 startArmy -= goal.army
				else:
					if (negativeTiles is None or goal not in negativeTiles):
						 startArmy += goal.army

			startVal = (startDist, 0 - startArmy)
			frontier.put((startVal, goal, startDist, startArmy, goalInc, None))
	else:
		for goal in goalList:
			if goal.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue

			goalInc = 0
			startArmy = 0
			if ignoreGoalArmy and (negativeTiles is None or goal not in negativeTiles):
				# then we have to inversely increment so we dont have to figure that out in the loop every time
				if searchingPlayer != goal.player:
					startArmy = 0 - goal.army
				else:
					startArmy = goal.army

			startVal = (0, 0 - startArmy)
			frontier.put((startVal, goal, 0, startArmy, goalInc, None))
	start = time.time()
	iter = 0
	foundGoal = False
	foundArmy = -1
	foundDist = -1
	endNode = None
	depthEvaluated = 0
	while not frontier.empty():
		iter += 1
			
		(prioVals, current, dist, army, goalInc, fromTile) = frontier.get()
		if visited[current.x][current.y] != None:
			#if not noLog and iter < 100:
			#	logging.info("PopSkipped visited current {}, army {}, goalInc {}".format(current.toString(), army, goalInc))
			continue		
		if (skipTiles != None and current in skipTiles):
			if not noLog and iter < 100:
				logging.info("PopSkipped skipTile current {}, army {}, goalInc {}, targetArmy {}".format(current.toString(), army, goalInc, targetArmy))
			continue
		
		if (current.mountain or (current.isCity and noNeutralCities and current.player == -1 and current not in goalList) or (not current.discovered and current.isobstacle())):
			if not noLog and iter < 100:
				logging.info("PopSkipped Mountain, neutCity or Obstacle current {}".format(current.toString()))
			continue
		
		nextArmy = army - 1 - goalInc
		if (current.isCity and current.player != -1) or current.isGeneral:
			if current.player == searchingPlayer:
				goalInc -= 0.5
			else:
				goalInc += 0.5
		if (negativeTiles is None or current not in negativeTiles):
			if (searchingPlayer == current.player):
				if (current.isCity and dontEvacCities):								
					nextArmy += (current.army // 2)
				else:
					nextArmy += current.army
			else:
				nextArmy -= (current.army)
		newDist = dist + 1
		
		visited[current.x][current.y] = (nextArmy, fromTile)

		if nextArmy > targetArmy and nextArmy > 0 and nextArmy > foundArmy:
			foundGoal = True
			foundDist = newDist
			foundArmy = nextArmy
			endNode = current
			if not noLog and iter < 100:
				logging.info("GOAL popped {}, army {}, goalInc {}, targetArmy {}, processing".format(current.toString(), nextArmy, goalInc, targetArmy))
			break
		if newDist > depthEvaluated:
			depthEvaluated = newDist
			#targetArmy += goalInc
			
		if not noLog and iter < 100:
			logging.info("Popped current {}, army {}, goalInc {}, targetArmy {}, processing".format(current.toString(), nextArmy, goalInc, targetArmy))
		if (newDist <= maxDepth and not foundGoal):
			for next in current.moveable: #new spots to try
				frontier.put(((newDist, 0 - nextArmy), next, newDist, nextArmy, goalInc, current))
	if not noLog:
		logging.info("BFS DEST SEARCH ITERATIONS {}, DURATION: {:.3f}, DEPTH: {}, FOUNDDIST: {}".format(iter, time.time() - start, depthEvaluated, foundDist))
	if foundDist < 0:
		return None
		
	node = endNode
	dist = foundDist
	nodes = []
	army = foundArmy
	# logging.info(json.dumps(visited))
	# logging.info("PPRINT FULL")
	# logging.info(pformat(visited))

	while (node != None):
		# logging.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
		nodes.append((army, node))

		# logging.info(pformat(visited[node.x][node.y]))
		(army, node) = visited[node.x][node.y]
		dist -= 1
	nodes.reverse()
	

	(startArmy, startNode) = nodes[0]

	pathObject = Path(foundArmy)
	pathObject.add_next(startNode)

	pathStart = PathNode(startNode, None, foundArmy, foundDist, -1, None)
	path = pathStart
	dist = foundDist
	for i, armyNode in enumerate(nodes[1:]):
		(curArmy, curNode) = armyNode
		if (curNode != None):
			# logging.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
			path = PathNode(curNode, path, curArmy, dist, -1, None) 
			pathObject.add_start(curNode)
			dist -= 1
	while (path != None and path.tile.army <= 1):
		logging.info("IS THIS THE INC BUG? OMG I THINK I FOUND IT!!!!!! Finds path where waiting 1 move for city increment is superior, but then we skip the 'waiting' move and just move the 2 army off the city instead of 3 army?")
		path = path.parent
		pathObject.made_move()
	# while (node != None):
	# 	army, node = visited[node.x][node.y][dist]
	# 	if (node != None):
	# 		dist -= 1
	# 		path = PathNode(node, path, army, dist, -1, None) 

	logging.info("DEST BFS FOUND KILLPATH OF LENGTH {} VALUE {}\n{}".format(pathObject.length, pathObject.value, pathObject.toString()))
	return pathObject



def _shortestPathHeur(goal, cur):
	return abs(goal.x - cur.x) + abs(goal.y - cur.y)




def a_star_kill(map, startTiles, goal, maxTime = 0.1, maxDepth = 20, restrictionEvalFuncs = None, ignoreStartTile = False, requireExtraArmy = 0, negativeTiles = None):
	frontier = PriorityQueue()
	came_from = {}
	cost_so_far = {}
	if isinstance(startTiles, dict):
		for start in startTiles.keys():
			startDist = startTiles[start]			
			logging.info("a* enqueued start tile {} with extraArmy {}".format(start.toString(), requireExtraArmy))
			startArmy = start.army
			if ignoreStartTile:
				startArmy = 0
			startArmy -= requireExtraArmy
			#if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
			#	startArmy = start.army / 2
			cost_so_far[start] = (startDist, 0 - startArmy)	
			frontier.put((cost_so_far[start], start))
			came_from[start] = None
	else:
		for start in startTiles:
			logging.info("a* enqueued start tile {} with extraArmy {}".format(start.toString(), requireExtraArmy))
			startArmy = start.army
			if ignoreStartTile:
				startArmy = 0
			startArmy -= requireExtraArmy
			#if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
			#	startArmy = start.army / 2
			cost_so_far[start] = (0, 0 - startArmy)	
			frontier.put((cost_so_far[start], start))
			came_from[start] = None	
	start = time.time()
	iter = 0
	foundDist = -1
	foundArmy = -1
	foundGoal = False
	depthEvaluated = 0

	while not frontier.empty():
		iter += 1
		if (iter & 256 == 0 and time.time() - start > maxTime):
			logging.info("breaking A* early")
			break
		prio, current = frontier.get()
		x = current.x
		y = current.y				
		curCost = cost_so_far[current]
		dist = curCost[0]
		army = 0 - curCost[1]
						
		if dist > depthEvaluated:
			depthEvaluated = dist
		if current == goal:
			if army > 1 and army > foundArmy:
				foundDist = dist
				foundArmy = army
				foundGoal = True
				break
			else: # skip paths that go through target, that wouldn't make sense
				#logging.info("a* path went through target")
				continue
		if (dist < maxDepth):
			for next in current.moveable: #new spots to try
				if (next.mountain or ((not next.discovered) and next.isobstacle())):
					#logging.info("a* mountain")
					continue
				if restrictionEvalFuncs != None:
					if current in restrictionEvalFuncs:
						if not restrictionEvalFuncs[current](next):
							logging.info("dangerous, vetod: {},{}".format(current.x, current.y))
							continue
						else:
							logging.info("safe: {},{}".format(current.x, current.y))

				inc = 0 if not ((next.isCity and next.player != -1) or next.isGeneral) else (dist + 1) / 2
					
				#new_cost = cost_so_far[current] + graph.cost(current, next)
				nextArmy = army - 1
				if negativeTiles is None or next not in negativeTiles:
					if (startTiles[0].player == next.player):
						nextArmy += next.army + inc
					else:
						nextArmy -= (next.army + inc)
					if (next.isCity and next.player == -1):
						nextArmy -= next.army * 2
				if (nextArmy <= 0 and army > 0): # prune out paths that go negative after initially going positive
					#logging.info("a* next army <= 0: {}".format(nextArmy))
					continue
				new_cost = (dist + 1, (0 - nextArmy))
				if next not in cost_so_far or new_cost < cost_so_far[next]:
					cost_so_far[next] = new_cost
					priority = (dist + 1 + _shortestPathHeur(goal, next), 0 - nextArmy)
					frontier.put((priority, next))
					#logging.info("a* enqueued next")
					came_from[next] = current
	logging.info("A* KILL SEARCH ITERATIONS {}, DURATION: {:.3f}, DEPTH: {}".format(iter, time.time() - start, depthEvaluated))
	if not goal in came_from:
		return None

	pathObject = Path(foundArmy)
	pathObject.add_next(goal)
	node = goal
	dist = foundDist
	while (came_from[node] != None):
		#logging.info("Node {},{}".format(node.x, node.y))
		node = came_from[node]
		dist -= 1
		pathObject.add_start(node)
	logging.info("A* FOUND KILLPATH OF LENGTH {} VALUE {}\n{}".format(pathObject.length, pathObject.value, pathObject.toString()))
	pathObject.calculate_value(startTiles[0].player)
	if pathObject.value < requireExtraArmy:
		logging.info("A* path {} wasn't good enough, returning none".format(pathObject.toString()))
		return None
	return pathObject


	#goalInc = 0
	#if (tile.isCity or tile.isGeneral) and tile.player != -1:
	#	goalInc = -0.5
	#startArmy = tile.army - 1
	#if tile.player != searchingPlayer:
	#	startArmy = 0 - tile.army - 1
	#	goalInc *= -1
	#if incrementBackward:
	#	goalInc *= -1
	#if ignoreStartTile:
	#	startArmy = 0
def breadth_first_dynamic(map, startTiles, goalFunc, maxTime = 0.2, maxDepth = 100, 
					   noNeutralCities = False, 
					   negativeTiles = None, 
					   skipTiles = None, 
					   searchingPlayer = -2, 
					   priorityFunc = None,
					   skipFunc = None,
					   ignoreStartTile = False,
					   incrementBackward = False,
					   preferNeutral = False):
	'''
	startTiles dict is (startPriorityObject, distance) = startTiles[tile]
	goalFunc is (currentTile, priorityObject) -> True or False
	priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject

	# make sure to initialize the initial base values and account for first priorityObject being None.
	def default_priority_func(nextTile, currentPriorityObject):
		dist = -1
		negCityCount = negEnemyTileCount = negArmySum = x = y = 0
		if currentPriorityObject != None:
			(dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
		dist += 1
		if nextTile.isCity:
			negCityCount -= 1
		if nextTile.player != searchingPlayer and nextTile.player != -1:
			negEnemyTileCount -= 1
		if nextTile.player == searchingPlayer:
			negArmySum -= nextTile.army - 1
		else:
			negArmySum += nextTile.army + 1
		return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
	'''	
	# make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
	def default_priority_func(nextTile, currentPriorityObject):
		(dist, negCityCount, negEnemyTileCount, negArmySum, x, y, goalIncrement) = currentPriorityObject
		dist += 1
		if nextTile.isCity:
			negCityCount -= 1
		if nextTile.player != searchingPlayer and (nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
			negEnemyTileCount -= 1
			
		if (negativeTiles is None or next not in negativeTiles):
			if nextTile.player == searchingPlayer:
				negArmySum -= nextTile.army
			else:
				negArmySum += nextTile.army
		# always leaving 1 army behind. + because this is negative.
		negArmySum += 1
		# -= because we passed it in positive for our general and negative for enemy gen / cities
		negArmySum -= goalIncrement
		return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y, goalIncrement)

	if searchingPlayer == -2:
		searchingPlayer = map.player_index
	if (priorityFunc is None):
		priorityFunc = default_priority_func
	frontier = PriorityQueue()
	visited = [[{} for x in range(map.rows)] for y in range(map.cols)]
	globalVisitedSet = set()
	if isinstance(startTiles, dict):
		for tile in startTiles.keys():
			(startPriorityObject, distance) = startTiles[tile]

			startVal = startPriorityObject
			frontier.put((startVal, distance, tile, None))
	else:
		for tile in startTiles:
			if priorityFunc != default_priority_func:
				raise AssertionError("yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
			if tile.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue
			dist = 0
			negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0
			
			if not ignoreStartTile and tile.isCity:
				negCityCount = -1
			if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
				negEnemyTileCount = -1
			if not ignoreStartTile and tile.player == searchingPlayer:
				negArmySum = 1 - tile.army
			else:
				negArmySum = tile.army + 1
			if not ignoreStartTile:
				if tile.player != -1 and tile.isCity or tile.isGeneral:
					goalIncrement = 0.5
					if tile.player != searchingPlayer:
						goalIncrement *= -1			

			startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
			frontier.put((startVal, dist, tile, None))
	start = time.time()
	iter = 0
	foundGoal = False
	foundDist = 1000
	endNode = None
	depthEvaluated = 0
	foundVal = None
	while not frontier.empty():
		iter += 1
		if (iter % 1000 == 0 and time.time() - start > maxTime):
			logging.info("BFS-DYNAMIC BREAKING")
			break
			
		(prioVals, dist, current, parent) = frontier.get()
		if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
			visited[current.x][current.y][dist] = (prioVals, parent)
		#TODO no globalVisitedSet
		if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
			continue
		globalVisitedSet.add(current)
		if goalFunc(current, prioVals):
			foundGoal = True
			foundDist = dist
			foundVal = prioVals
			endNode = current
		if dist > depthEvaluated:
			depthEvaluated = dist
			if foundGoal:
				break
		if (dist <= maxDepth and not foundGoal):
			for next in current.moveable: #new spots to try
				if (next.mountain 
						or (noNeutralCities and next.player == -1 and next.isCity) 
						or (not next.discovered and next.isobstacle())):
					continue
				newDist = dist + 1
				nextVal = priorityFunc(next, prioVals)
				if (skipFunc != None and skipFunc(next, nextVal)):
					continue
				frontier.put((nextVal, newDist, next, current))

	logging.info("BFS-DYNAMIC ITERATIONS {}, DURATION: {:.3f}, DEPTH: {}".format(iter, time.time() - start, depthEvaluated))
	if foundDist >= 1000:
		return None
		
	tile = endNode
	dist = foundDist
	tileList = []
	# logging.info(json.dumps(visited))
	# logging.info("PPRINT FULL")
	# logging.info(pformat(visited))

	while (tile != None):
		# logging.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
		tileList.append(tile)

		# logging.info(pformat(visited[node.x][node.y]))
		(prioVal, tile) = visited[tile.x][tile.y][dist]
		dist -= 1
	pathObject = Path()
	for tile in reversed(tileList):
		if tile != None:
			# logging.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
			pathObject.add_next(tile)

	# while (node != None):
	# 	army, node = visited[node.x][node.y][dist]
	# 	if (node != None):
	# 		dist -= 1
	# 		path = PathNode(node, path, army, dist, -1, None)
	pathObject.calculate_value(searchingPlayer)
	logging.info("DYNAMIC BFS FOUND PATH LENGTH {} VALUE {}\n   {}".format(pathObject.length, pathObject.value, pathObject.toString()))
	return pathObject





def greedy_backpack_gather(map, startTiles, turns, targetArmy = None, valueFunc = None, baseCaseFunc = None,
					   negativeTiles = None,
					   skipTiles = None,
					   searchingPlayer = -2,
					   priorityFunc = None,
					   skipFunc = None,
					   priorityTiles = None,
					   ignoreStartTile = False,
					   incrementBackward = False,
					   preferNeutral = False,
					   viewInfo = None,
					   distPriorityMap = None,
					   useTrueValueGathered = False):
	'''
	startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile]
	valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object
	priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted
	'''
	startTime = time.time()
	negativeTilesOrig = negativeTiles
	if negativeTiles != None:
		negativeTiles = negativeTiles.copy()
	else:
		negativeTiles = set()
	#q = PriorityQueue()

	#if isinstance(startTiles, dict):
	#	for tile in startTiles.keys():
	#		(startPriorityObject, distance) = startTiles[tile]

	#		startVal = startPriorityObject

	#		allowedDepth = turns - distance
	#		startTiles = {}
	#		startTiles[tile] = (startPriorityObject, 
				
	# TODO break ties by maximum distance from threat (ideally, gathers from behind our gen are better 
	#           than gathering stuff that may open up a better attack path in front of our gen)

	# TODO factor in cities, right now they're not even incrementing. need to factor them into the timing and calculate when they'll be moved.
	if searchingPlayer == -2:		
		if isinstance(startTiles, dict):
			searchingPlayer = startTiles.keys()[0].player
		else:
			searchingPlayer = startTiles[0].player
	


	logging.info("Trying greedy-bfs-gather. Turns {}. Searching player {}".format(turns, searchingPlayer))
	if valueFunc is None:
		logging.info("Using default valueFunc")
		def default_value_func_max_gathered_per_turn(currentTile, priorityObject):
			(realDist, negPrioTilesPerTurn, negGatheredSum, negArmySum, negDistanceSum, dist, xSum, ySum, numPrioTiles) = priorityObject
			value = -1000
			if negArmySum < 0:
				value = 0 - (negGatheredSum / (max(1, realDist)))
			return (value, 0-negDistanceSum, 0-negGatheredSum, realDist, 0-xSum, 0-ySum)
		valueFunc = default_value_func_max_gathered_per_turn

		
	if priorityFunc is None:
		logging.info("Using default priorityFunc")
		def default_priority_func(nextTile, currentPriorityObject):
			(realDist, negPrioTilesPerTurn, negGatheredSum, negArmySum, negDistanceSum, dist, xSum, ySum, numPrioTiles) = currentPriorityObject
			negArmySum += 1
			negGatheredSum += 1
			if (nextTile not in negativeTiles):
				if (searchingPlayer == nextTile.player):
					negArmySum -= nextTile.army
					negGatheredSum -= nextTile.army
					# # this broke gather approximation, couldn't predict actual gather values based on this
					#if nextTile.isCity:
					#	negArmySum -= turns // 3
				else:
					negArmySum += nextTile.army
					if useTrueValueGathered:
						negGatheredSum += nextTile.army
			#if nextTile.player != searchingPlayer and not (nextTile.player == -1 and nextTile.isCity):
			#	negDistanceSum -= 1
			# hacks us prioritizing further away tiles
			if distPriorityMap != None:
				negDistanceSum -= distPriorityMap[nextTile.x][nextTile.y]
			if priorityTiles != None and nextTile in priorityTiles:
				numPrioTiles += 1
			realDist += 1
			#logging.info("prio: nextTile {} got realDist {}, negNextArmy {}, negDistanceSum {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
			return (realDist, numPrioTiles/realDist, negGatheredSum, negArmySum, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y, numPrioTiles)
		priorityFunc = default_priority_func
		

	if baseCaseFunc is None:
		logging.info("Using default baseCaseFunc")
		def default_base_case_func(tile, startingDist):
			startArmy = 0
			# we would like to not gather to an enemy tile without killing it, so must factor it into the path. army value is negative for priority, so use positive for enemy army.
			if tile.player != searchingPlayer:
				logging.info("tile {} was not owned by searchingPlayer {}, adding its army {}".format(tile.toString(), searchingPlayer, tile.army))
				startArmy = tile.army
			
			logging.info("tile {} got base case startArmy {}, startingDist {}".format(tile.toString(), startArmy, startingDist))
			return (0, 0, 0, startArmy, 0, startingDist, tile.x, tile.y, 0)
		baseCaseFunc = default_base_case_func
		

	startTilesDict = {}
	if isinstance(startTiles, dict):
		startTilesDict = startTiles
		for tile in startTiles.keys():
			negativeTiles.add(tile)
	else:
		for tile in startTiles:
			# then use baseCaseFunc to initialize their priorities, and set initial distance to 0
			startTilesDict[tile] = (baseCaseFunc(tile, 0), 0)
			negativeTiles.add(tile)
	
	for tile in startTilesDict.keys():
		(startPriorityObject, distance) = startTilesDict[tile]
		logging.info("Including tile {},{} in startTiles at distance {}".format(tile.x, tile.y, distance))
		#if viewInfo:
		#	viewInfo.bottomRightGridText[tile.x][tile.y] = distance

	startR = 100
	startG = 150
	startB = 200
	valuePerTurnPath = breadth_first_dynamic_max(map, startTilesDict, valueFunc, 0.1, turns, noNeutralCities=True,
						negativeTiles = negativeTiles, 
						skipTiles = skipTiles, 
						searchingPlayer = searchingPlayer, 
						priorityFunc = priorityFunc,
						skipFunc = skipFunc,
						ignoreStartTile = ignoreStartTile,
						incrementBackward = incrementBackward,
						preferNeutral = preferNeutral, logResultValues = True)
	
	if valuePerTurnPath is None:
		logging.info("Yo, no initial valuePerTurnPath??????? :(")
		return []
	treeNodeLookup = {}
	treeNodes = []
	itr = 0
	remainingTurns = turns
	while valuePerTurnPath != None:
		if valuePerTurnPath.tail.tile.army <= 1 or valuePerTurnPath.tail.tile.player != searchingPlayer:
			logging.info("TERMINATING greedy-bfs-gather PATH BUILDING DUE TO TAIL TILE {} THAT WAS < 1 OR NOT OWNED BY US. PATH: {}".format(valuePerTurnPath.tail.tile.toString(), valuePerTurnPath.toString()))
			break
		logging.info("Adding valuePerTurnPath (v/t {:.3f}): {}".format((valuePerTurnPath.value - valuePerTurnPath.start.tile.army + 1) / valuePerTurnPath.length, valuePerTurnPath.toString()))
		#if viewInfo:
		#	newR = (startR + 50 * itr) % 255
		#	newG = (startG - 30 * itr) % 255
		#	newB = (startB + 25 * itr) % 255
		#	viewInfo.paths.appendleft(PathColorer(valuePerTurnPath.get_reversed(), newR, newG, newB, 255, 0, 200))

		remainingTurns = remainingTurns - valuePerTurnPath.length
		itr += 1
		# add the new path to startTiles, rinse, and repeat
		node = valuePerTurnPath.start
		# we need to factor in the distance that the last path was already at (say we're gathering to a threat, 
		# you can't keep adding gathers to the threat halfway point once you're gathering for as many turns as half the threat length
		(startPriorityObject, distance) = startTilesDict[node.tile]
		# TODO? May need to not continue with the previous paths priorityObjects and instead start fresh, as this may unfairly weight branches
		#       towards the initial max path, instead of the highest actual additional value
		curPrioObj = startPriorityObject
		addlDist = 1
		currentTreeNode = None
		
		if node.tile in treeNodeLookup:
			currentTreeNode = treeNodeLookup[node.tile]
		else:
			currentTreeNode = TreeNode(node.tile, None, distance)
			currentTreeNode.gatherTurns = 1
		runningValue = valuePerTurnPath.value - node.tile.army
		currentTreeNode.value += runningValue
		runningValue -= node.tile.army
		treeNodeLookup[node.tile] = currentTreeNode
		negativeTiles.add(node.tile)
		# skipping because first tile is actually already on the path
		node = node.next
		# add the new path to startTiles and then search a new path
		while node != None:
			newDist = distance + addlDist
			nextPrioObj = baseCaseFunc(node.tile, newDist)
			startTilesDict[node.tile] = (nextPrioObj, newDist)
			negativeTiles.add(node.tile)
			logging.info("Including tile {},{} in startTilesDict at newDist {}  (distance {} addlDist {})".format(node.tile.x, node.tile.y, newDist, distance, addlDist))
			#if viewInfo:
			#	viewInfo.bottomRightGridText[node.tile.x][node.tile.y] = newDist
			nextTreeNode = TreeNode(node.tile, currentTreeNode.tile, newDist)
			nextTreeNode.value = runningValue
			nextTreeNode.gatherTurns = 1
			runningValue -= node.tile.army
			currentTreeNode.children.append(nextTreeNode)
			currentTreeNode = nextTreeNode
			treeNodeLookup[node.tile] = currentTreeNode
			addlDist += 1
			curPrioObj = nextPrioObj
			node = node.next
		
		logging.info("Searching for the next path with remainingTurns {}".format(remainingTurns))
		valuePerTurnPath = breadth_first_dynamic_max(map, startTilesDict, valueFunc, 0.1, remainingTurns, noNeutralCities=True,
							negativeTiles = negativeTiles, 
							skipTiles = skipTiles, 
							searchingPlayer = searchingPlayer, 
							priorityFunc = priorityFunc,
							skipFunc = skipFunc,
							ignoreStartTile = ignoreStartTile,
							incrementBackward = incrementBackward,
							preferNeutral = preferNeutral, logResultValues = True)
	

	logging.info("Concluded greedy-bfs-gather built from {} path segments. Duration: {:.3f}".format(itr, time.time() - startTime))
	rootNodes = list(where(treeNodeLookup.values(), lambda treeNode: treeNode.fromTile is None))
	for node in rootNodes:
		recalculate_tree_values(node, negativeTilesOrig, searchingPlayer = searchingPlayer, onlyCalculateFriendlyArmy = False, viewInfo = viewInfo)
	return rootNodes

def recalculate_tree_values(rootNode, negativeTiles, searchingPlayer, onlyCalculateFriendlyArmy = False, viewInfo = None):
	logging.info("recalculate_tree_values {}, searchingPlayer {}, onlyCalculateFriendlyArmy {}".format(rootNode.tile.toString(), searchingPlayer, onlyCalculateFriendlyArmy))
	sum = -1
	if negativeTiles is None or rootNode.tile not in negativeTiles:
		if rootNode.tile.player == searchingPlayer:
			sum += rootNode.tile.army
		elif not onlyCalculateFriendlyArmy:
			sum -= rootNode.tile.army
	for child in rootNode.children:
		recalculate_tree_values(child, negativeTiles, searchingPlayer, onlyCalculateFriendlyArmy, viewInfo)
		sum += child.value
	if viewInfo:
		viewInfo.bottomRightGridText[rootNode.tile.x][rootNode.tile.y] = sum
	rootNode.value = sum


def get_tree_move(gathers, priorityFunc, valueFunc):
	if len(gathers) == 0:
		logging.info("get_tree_move... len(gathers) == 0?")
		return None
	q = PriorityQueue()

	for gather in gathers:
		basePrio = priorityFunc(gather.tile, None)
		q.put((basePrio, gather))

	highestValue = None
	highestValueMove = None
	while q.qsize() > 0:
		(curPrio, curGather) = q.get()
		if len(curGather.children) == 0:
			# WE FOUND OUR FIRST MOVE!
			thisValue = valueFunc(curGather.tile, curPrio)
			if curGather.fromTile != None and (highestValue is None or thisValue > highestValue):
				highestValue = thisValue
				highestValueMove = Move(curGather.tile, curGather.fromTile)
				logging.info("new highestValueMove {}!".format(highestValueMove.toString()))
		for gather in curGather.children:
			nextPrio = priorityFunc(gather.tile, curPrio)
			q.put((nextPrio, gather))
	if highestValueMove is None:
		return None
	logging.info("highestValueMove in get_tree_move was {}!".format(highestValueMove.toString()))
	return highestValueMove


def breadth_first_dynamic_max(map, startTiles, valueFunc, maxTime = 0.2, maxDepth = 100, 
					   noNeutralCities = False, 
					   negativeTiles = None, 
					   skipTiles = None, 
					   searchingPlayer = -2, 
					   priorityFunc = None,
					   skipFunc = None,
					   ignoreStartTile = False,
					   incrementBackward = False,
					   preferNeutral = False,
					   useGlobalVisitedSet = True,
					   logResultValues = False,
					   noLog = False,
					   includePathValue = False,
					   fullOnly = False,
					   fullOnlyArmyDistFunc = None,
					   boundFunc = None):
	'''
	startTiles dict is (startPriorityObject, distance) = startTiles[tile]
	goalFunc is (currentTile, priorityObject) -> True or False
	priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject
	boundFunc is (currentTile, currentPiorityObject, maxPriorityObject) -> True (prune) False (continue)

	# make sure to initialize the initial base values and account for first priorityObject being None.
	def default_priority_func(nextTile, currentPriorityObject):
		dist = -1
		negCityCount = negEnemyTileCount = negArmySum = x = y = 0
		if currentPriorityObject != None:
			(dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
		dist += 1
		if nextTile.isCity:
			negCityCount -= 1
		if nextTile.player != searchingPlayer and nextTile.player != -1:
			negEnemyTileCount -= 1
		if nextTile.player == searchingPlayer:
			negArmySum -= nextTile.army - 1
		else:
			negArmySum += nextTile.army + 1
		return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
	'''	
	# make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
	def default_priority_func(nextTile, currentPriorityObject):
		(dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
		dist += 1
		if nextTile.isCity:
			negCityCount -= 1
		if nextTile.player != searchingPlayer and (nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
			negEnemyTileCount -= 1
			
		if (negativeTiles is None or next not in negativeTiles):
			if nextTile.player == searchingPlayer:
				negArmySum -= nextTile.army
			else:
				negArmySum += nextTile.army
		# always leaving 1 army behind. + because this is negative.
		negArmySum += 1
		# -= because we passed it in positive for our general and negative for enemy gen / cities
		negArmySum -= goalIncrement
		return (dist, negCityCount, negEnemyTileCount, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement)
	
	if fullOnly:
		oldValFunc = valueFunc
		def newValFunc(current, prioVals):
			army, dist, tileSet = fullOnlyArmyDistFunc(current, prioVals)

			validMoveCount = 0
			#if not noLog:
			#	logging.info("{}  EVAL".format(current.toString()))

			for adj in current.moveable:
				skipMt = adj.mountain or (adj.isCity and adj.player == -1)
				skipSearching = adj.player == searchingPlayer
				# 2 is very important unless army amounts get fixed to not include tile val
				skipArmy = army - adj.army < 2
				skipVisited = adj in tileSet or adj in negativeTiles
				skipIt = skipMt or skipSearching or skipArmy or skipVisited
				#if not noLog:
				#	logging.info("    {}   {}  mt {}, player {}, army {} ({} - {} < 1), visitedNeg {}".format(adj.toString(), skipIt, skipMt, skipSearching, skipArmy, army, adj.army, skipVisited))
				if not skipIt:
					validMoveCount += 1

			#validMoveCount = count(current.moveable, lambda adj: not  and not adj.player == searchingPlayer and (not army - adj.army < 1) and not )
			if validMoveCount > 0 and dist < maxDepth:
				#if not noLog:
				#	logging.info("{} SKIPPED VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
				return None
			#if not noLog:
			#	logging.info("{} VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
			return oldValFunc(current, prioVals)
		valueFunc = newValFunc
	
	if searchingPlayer == -2:
		searchingPlayer = map.player_index
	if (priorityFunc is None):
		priorityFunc = default_priority_func
	frontier = PriorityQueue()

	globalVisitedSet = set()
	if isinstance(startTiles, dict):
		for tile in startTiles.keys():
			(startPriorityObject, distance) = startTiles[tile]

			startVal = startPriorityObject
			startList = list()
			startList.append((tile, startVal))
			frontier.put((startVal, distance, tile, None, startList))
	else:
		for tile in startTiles:
			if priorityFunc != default_priority_func:
				raise AssertionError("yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
			if tile.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue
			dist = 0
			negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0
			
			if not ignoreStartTile and tile.isCity:
				negCityCount = -1
			if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
				negEnemyTileCount = -1
			if not ignoreStartTile and tile.player == searchingPlayer:
				negArmySum = 1 - tile.army
			else:
				negArmySum = tile.army + 1
			if not ignoreStartTile:
				if tile.player != -1 and tile.isCity or tile.isGeneral:
					goalIncrement = 0.5
					if tile.player != searchingPlayer:
						goalIncrement *= -1			

			startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
			startList = list()
			startList.append((tile, startVal))
			frontier.put((startVal, dist, tile, None, startList))

	start = time.time()
	iter = 0
	foundDist = 1000
	endNode = None
	depthEvaluated = 0
	maxValue = None
	maxPrio = None
	maxList = None
	parentString = ""
	while not frontier.empty():
		iter += 1
		if (iter & 256 == 0 and time.time() - start > maxTime):
			logging.info("BFS-DYNAMIC-MAX BREAKING EARLY")
			break

		(prioVals, dist, current, parent, nodeList) = frontier.get()
		#if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
		#TODO no globalVisitedSet
		#if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
		if useGlobalVisitedSet:
			if current in globalVisitedSet:
				continue
			globalVisitedSet.add(current)
		if skipTiles != None and current in skipTiles:
			continue

		newValue = valueFunc(current, prioVals)
		#if logResultValues:
		#	logging.info("Tile {} value?: [{}]".format(current.toString(), '], ['.join(str(x) for x in newValue)))
		#	if parent != None:
		#		parentString = parent.toString()
		#	else:
		#		parentString = "None"
		if newValue != None and (maxValue is None or newValue > maxValue):
			foundDist = dist
			if logResultValues:
				if parent != None:
					parentString = parent.toString()
				else:
					parentString = "None"
				logging.info("+Tile {} from {} is new max value: [{}]  (dist {})".format(current.toString(), parentString, '], ['.join("{:.3f}".format(x) for x in newValue), dist))
			maxValue = newValue
			maxPrio = prioVals
			endNode = current
			maxList = nodeList
		#elif logResultValues:			
		#		logging.info("   Tile {} from {} was not max value: [{}]".format(current.toString(), parentString, '], ['.join(str(x) for x in newValue)))
		if dist > depthEvaluated:
			depthEvaluated = dist
		if (dist < maxDepth):
			dist += 1
			for next in current.moveable: #new spots to try
				if (next.mountain 
						or (noNeutralCities and next.player == -1 and next.isCity) 
						or (not next.discovered and next.isobstacle())):
					continue
				nextVal = priorityFunc(next, prioVals)
				if nextVal != None:
					if boundFunc != None and boundFunc(next, nextVal, maxPrio):
						logging.info("Bounded off {}".format(next.toString()))
						continue
					if (skipFunc != None and skipFunc(next, nextVal)):
						continue
					newNodeList = list(nodeList)
					newNodeList.append((next, nextVal))
					frontier.put((nextVal, dist, next, current, newNodeList))
	if not noLog:
		logging.info("BFS-DYNAMIC-MAX ITERATIONS {}, DURATION: {:.3f}, DEPTH: {}".format(iter, time.time() - start, depthEvaluated))
	if foundDist >= 1000:
		if includePathValue:
			return None, None
		return None
		
	tile = endNode
	dist = foundDist
	pathObject = Path()
	for tileTuple in maxList:
		tile, prioVal = tileTuple
		if tile != None:
			if prioVal != None:
				logging.info("  FOUND PATH {} [{}]".format(tile.toString(), ']\n    ['.join(str(x) for x in prioVal)))
			else:
				logging.info("  FOUND PATH {} [None]".format(tile.toString()))
			# logging.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
			pathObject.add_next(tile)

	# while (node != None):
	# 	army, node = visited[node.x][node.y][dist]
	# 	if (node != None):
	# 		dist -= 1
	# 		path = PathNode(node, path, army, dist, -1, None)
	pathObject.calculate_value(searchingPlayer)
	if pathObject.length == 0:
		if not noLog:
			logging.info("BFS-DYNAMIC-MAX FOUND PATH LENGTH {} VALUE {}, returning NONE!\n   {}".format(pathObject.length, pathObject.value, pathObject.toString()))
		if includePathValue:
			return None, None
		return None
	else:		
		if not noLog:
			logging.info("BFS-DYNAMIC-MAX FOUND PATH LENGTH {} VALUE {}\n   {}".format(pathObject.length, pathObject.value, pathObject.toString()))
	if includePathValue:
		return pathObject, maxValue
	return pathObject





			#goalInc = 0
			#if (tile.isCity or tile.isGeneral) and tile.player != -1:
			#	goalInc = -0.5
			#startArmy = tile.army - 1
			#if tile.player != searchingPlayer:
			#	startArmy = 0 - tile.army - 1
			#	goalInc *= -1
			#if incrementBackward:
			#	goalInc *= -1
			#if ignoreStartTile:
			#	startArmy = 0
def bidirectional_breadth_first_dynamic(map, startTiles, goalFunc, maxTime = 0.2, maxDepth = 100, 
					   noNeutralCities = False, 
					   negativeTiles = None, 
					   skipTiles = None, 
					   searchingPlayer = -2, 
					   priorityFunc = None,
					   skipFunc = None,
					   ignoreStartTile = False,
					   incrementBackward = False,
					   preferNeutral = False):
	'''
	startTiles dict is (startPriorityObject, distance) = startTiles[tile]
	goalFunc is (currentTile, priorityObject) -> True or False
	priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject

	# make sure to initialize the initial base values and account for first priorityObject being None.
	def default_priority_func(nextTile, currentPriorityObject):
		dist = -1
		negCityCount = negEnemyTileCount = negArmySum = x = y = 0
		if currentPriorityObject != None:
			(dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
		dist += 1
		if nextTile.isCity:
			negCityCount -= 1
		if nextTile.player != searchingPlayer and nextTile.player != -1:
			negEnemyTileCount -= 1
		if nextTile.player == searchingPlayer:
			negArmySum -= nextTile.army - 1
		else:
			negArmySum += nextTile.army + 1
		return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
	'''	
	# make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
	def default_priority_func(nextTile, currentPriorityObject):
		(dist, negCityCount, negEnemyTileCount, negArmySum, x, y, goalIncrement) = currentPriorityObject
		dist += 1
		if nextTile.isCity:
			negCityCount -= 1
		if nextTile.player != searchingPlayer and (nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
			negEnemyTileCount -= 1
			
		if (negativeTiles is None or next not in negativeTiles):
			if nextTile.player == searchingPlayer:
				negArmySum -= nextTile.army
			else:
				negArmySum += nextTile.army
		# always leaving 1 army behind. + because this is negative.
		negArmySum += 1
		# -= because we passed it in positive for our general and negative for enemy gen / cities
		negArmySum -= goalIncrement
		return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y, goalIncrement)

	if searchingPlayer == -2:
		searchingPlayer = map.player_index
	if (priorityFunc is None):
		priorityFunc = default_priority_func
	frontier = PriorityQueue()
	visited = [[{} for x in range(map.rows)] for y in range(map.cols)]
	globalVisitedSet = set()
	if isinstance(startTiles, dict):
		for tile in startTiles.keys():
			(startPriorityObject, distance) = startTiles[tile]

			startVal = startPriorityObject
			frontier.put((startVal, distance, tile, None))
	else:
		for tile in startTiles:
			if priorityFunc != default_priority_func:
				raise AssertionError("yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
			if tile.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue
			dist = 0
			negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0
			
			if not ignoreStartTile and tile.isCity:
				negCityCount = -1
			if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
				negEnemyTileCount = -1
			if not ignoreStartTile and tile.player == searchingPlayer:
				negArmySum = 1 - tile.army
			else:
				negArmySum = tile.army + 1
			if not ignoreStartTile:
				if tile.player != -1 and tile.isCity or tile.isGeneral:
					goalIncrement = 0.5
					if tile.player != searchingPlayer:
						goalIncrement *= -1			

			startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
			frontier.put((startVal, dist, tile, None))
	start = time.time()
	iter = 0
	foundGoal = False
	foundDist = 1000
	endNode = None
	depthEvaluated = 0
	foundVal = None
	while not frontier.empty():
		iter += 1
		if (iter % 1000 == 0 and time.time() - start > maxTime):
			logging.info("BFS-FIND BREAKING")
			break
			
		(prioVals, dist, current, parent) = frontier.get()
		if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
			visited[current.x][current.y][dist] = (prioVals, parent)
		#TODO no globalVisitedSet
		if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
			continue
		globalVisitedSet.add(current)
		if goalFunc(current, prioVals):
			foundGoal = True
			foundDist = dist
			foundVal = prioVals
			endNode = current
		if dist > depthEvaluated:
			depthEvaluated = dist
			if foundGoal:
				break
		if (dist <= maxDepth and not foundGoal):
			for next in current.moveable: #new spots to try
				if (next.mountain 
						or (noNeutralCities and next.player == -1 and next.isCity) 
						or (not next.discovered and next.isobstacle())):
					continue
				newDist = dist + 1
				nextVal = priorityFunc(next, prioVals)
				if (skipFunc != None and skipFunc(next, nextVal)):
					continue
				frontier.put((nextVal, newDist, next, current))

	logging.info("BFS-FIND ITERATIONS {}, DURATION: {:.3f}, DEPTH: {}".format(iter, time.time() - start, depthEvaluated))
	if foundDist >= 1000:
		return None
		
	tile = endNode
	dist = foundDist
	tileList = []
	# logging.info(json.dumps(visited))
	# logging.info("PPRINT FULL")
	# logging.info(pformat(visited))

	while (tile != None):
		# logging.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
		tileList.append(tile)

		# logging.info(pformat(visited[node.x][node.y]))
		(prioVal, tile) = visited[tile.x][tile.y][dist]
		dist -= 1
	pathObject = Path()
	for tile in reversed(tileList):
		if tile != None:
			# logging.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
			pathObject.add_next(tile)

	# while (node != None):
	# 	army, node = visited[node.x][node.y][dist]
	# 	if (node != None):
	# 		dist -= 1
	# 		path = PathNode(node, path, army, dist, -1, None)
	pathObject.calculate_value(searchingPlayer)
	logging.info("DYNAMIC BFS FOUND PATH LENGTH {} VALUE {}\n   {}".format(pathObject.length, pathObject.value, pathObject.toString()))
	return pathObject



def breadth_first_find_queue(map, startTiles, goalFunc, maxTime = 0.1, maxDepth = 20, 
							 noNeutralCities = False, 
							 negativeTiles = None, 
							 skipTiles = None, 
							 searchingPlayer = -2,
							 ignoreStartTile = False):
	'''
	goalFunc is goalFunc(current, army, dist)
	'''
	if searchingPlayer == -2:
		searchingPlayer = map.player_index
	frontier = deque()
	visited = [[None for x in range(map.rows)] for y in range(map.cols)]
	if isinstance(startTiles, dict):
		for tile in startTiles.keys():
			(startDist, startArmy) = startTiles[tile]			
			if tile.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue
			tileInc = 0
			if (tile.isCity or tile.isGeneral):
				goalInc = -0.5
			startArmy = tile.army - 1
			if tile.player != searchingPlayer:
				startArmy = 0 - tile.army - 1
				goalInc = -1 * goalInc
			if ignoreStartTile:
				startArmy = 0
			visited[tile.x][tile.y] = (startArmy, None)
			frontier.appendleft((tile, startDist, startArmy, goalInc))
	else:
		for tile in startTiles:
			if tile.mountain:
				#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
				continue
			goalInc = 0
			startArmy = tile.army - 1
			if tile.player != searchingPlayer:
				startArmy = 0 - tile.army - 1
			visited[tile.x][tile.y] = (startArmy, None)
			if (tile.isCity or tile.isGeneral):
				goalInc = 0.5
			if ignoreStartTile:
				startArmy = 0
			frontier.appendleft((tile, 0, startArmy, goalInc))
	iter = 0
	start = time.time()
	foundGoal = False
	foundArmy = -100000
	foundDist = 1000
	endNode = None
	depthEvaluated = 0
	while len(frontier) > 0:
		iter += 1
		(current, dist, army, goalInc) = frontier.pop()
		if visited[current.x][current.y] != None or (skipTiles != None and current in skipTiles):
			continue
		if goalFunc(current, army, dist) and (dist < foundDist or (dist == foundDist and army > foundArmy)):
			foundGoal = True
			foundDist = dist
			foundArmy = army
			endNode = current
		if dist > depthEvaluated:
			depthEvaluated = dist
			if foundGoal:
				break
		if (dist <= maxDepth and not foundGoal):
			for next in current.moveable: #new spots to try
					
				if (next.mountain or (noNeutralCities and next.isCity and next.player == -1) or (not next.discovered and next.isobstacle())):
					continue
				inc = 0 if not ((next.isCity and next.player != -1) or next.isGeneral) else dist / 2
				#new_cost = cost_so_far[current] + graph.cost(current, next)
				nextArmy = army - 1
				if (negativeTiles is None or next not in negativeTiles):
					if (searchingPlayer == next.player):
						nextArmy += next.army + inc
					else:
						nextArmy -= (next.army + inc)
				newDist = dist + 1
				if visited[next.x][next.y] is None or visited[next.x][next.y][0] < nextArmy:
					visited[next.x][next.y] = (nextArmy, current)
				frontier.appendleft((next, newDist, nextArmy, goalInc))

	logging.info("BFS-FIND-QUEUE ITERATIONS {}, DURATION: {:.3f}, DEPTH: {}".format(iter, time.time() - start, depthEvaluated))
	if foundDist >= 1000:
		return None
		
	node = endNode
	dist = foundDist
	nodes = []
	army = foundArmy
	# logging.info(json.dumps(visited))
	# logging.info("PPRINT FULL")
	# logging.info(pformat(visited))

	while (node != None):
		# logging.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
		nodes.append((army, node))

		# logging.info(pformat(visited[node.x][node.y]))
		(army, node) = visited[node.x][node.y]
		dist -= 1
	nodes.reverse()
	(startArmy, startNode) = nodes[0]
	pathObject = Path(foundArmy)
	pathObject.add_next(startNode)
	pathStart = PathNode(startNode, None, foundArmy, foundDist, -1, None)
	path = pathStart
	dist = foundDist
	for i, armyNode in enumerate(nodes[1:]):
		(curArmy, curNode) = armyNode
		if (curNode != None):
			# logging.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
			path = PathNode(curNode, path, curArmy, dist, -1, None) 
			pathObject.add_start(curNode)
			dist -= 1

	# while (node != None):
	# 	army, node = visited[node.x][node.y]
	# 	if (node != None):
	# 		dist -= 1
	# 		path = PathNode(node, path, army, dist, -1, None) 

	logging.info("BFS-FIND-QUEUE found path OF LENGTH {} VALUE {}\n{}".format(pathObject.length, pathObject.value, pathObject.toString()))
	return pathObject






def breadth_first_foreach(map, startTiles, maxDepth, foreachFunc, negativeFunc = None, skipFunc = None, skipTiles = None, searchingPlayer = -2, noLog = False):
	'''
	skipped tiles are still foreached, they just aren't traversed
	'''
	if searchingPlayer == -2:
		searchingPlayer = map.player_index
	frontier = deque()
	globalVisited = new_value_matrix(map, False)
	if skipTiles != None:
		for tile in skipTiles:
			if not noLog:
				logging.info("    skipTiles contained {}".format(tile.toString()))
			globalVisited[tile.x][tile.y] = True

	for tile in startTiles:
		if tile.mountain:
			#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
			continue
		frontier.appendleft((tile, 0))


	if negativeFunc != None:
		oldForeachFunc = foreachFunc
		def newFunc(tile):
			if not negativeFunc(tile):
				oldForeachFunc(tile)
		foreachFunc = newFunc


	start = time.time()
	iter = 0
	depthEvaluated = 0
	dist = 0
	while len(frontier) > 0:
		iter += 1
			
		(current, dist) = frontier.pop()
		if globalVisited[current.x][current.y]:
			continue
		globalVisited[current.x][current.y] = True
		if current.mountain or (not current.discovered and current.isobstacle()):
			continue
		foreachFunc(current)
		# intentionally placed after the foreach func, skipped tiles are still foreached, they just aren't traversed
		if (skipFunc != None and skipFunc(current)):
			continue

		if (dist > maxDepth):
			break
		newDist = dist + 1
		for next in current.moveable: #new spots to try
			frontier.appendleft((next, newDist))
	if not noLog:
		logging.info("Completed breadth_first_foreach. startTiles[0] {},{}: ITERATIONS {}, DURATION {:.3f}, DEPTH {}".format(startTiles[0].x, startTiles[0].y, iter, time.time() - start, dist))





def breadth_first_foreach_dist(map, startTiles, maxDepth, foreachFunc, negativeFunc = None, skipFunc = None, skipTiles = None, searchingPlayer = -2, noLog = False):
	'''
	skipped tiles are still foreached, they just aren't traversed
	'''
	if searchingPlayer == -2:
		searchingPlayer = map.player_index
	frontier = deque()
	globalVisited = new_value_matrix(map, False)
	if skipTiles != None:
		for tile in skipTiles:
			globalVisited[tile.x][tile.y] = True

	for tile in startTiles:
		if tile.mountain:
			#logging.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
			continue
		frontier.appendleft((tile, 0))
	
	if negativeFunc != None:
		oldForeachFunc = foreachFunc
		def newFunc(tile, dist):
			if not negativeFunc(tile):
				oldForeachFunc(tile, dist)
		foreachFunc = newFunc

	start = time.time()
	iter = 0
	dist = 0
	while len(frontier) > 0:
		iter += 1
			
		(current, dist) = frontier.pop()
		if globalVisited[current.x][current.y]:
			continue
		globalVisited[current.x][current.y] = True
		if current.mountain or (not current.discovered and current.isobstacle()):
			continue
		foreachFunc(current, dist)
		# intentionally placed after the foreach func, skipped tiles are still foreached, they just aren't traversed
		if (skipFunc != None and skipFunc(current)):
			continue
		if (dist > maxDepth):
			break
		newDist = dist + 1
		for next in current.moveable: #new spots to try					
			frontier.appendleft((next, newDist))
	if not noLog:
		logging.info("Completed breadth_first_foreach_dist. startTiles[0] {},{}: ITERATIONS {}, DURATION {:.3f}, DEPTH {}".format(startTiles[0].x, startTiles[0].y, iter, time.time() - start, dist))



def build_distance_map(map, startTiles, skipTiles = None) -> typing.List[typing.List[int]]:
	distanceMap = new_value_matrix(map, INF)
	
	if skipTiles is None:
		skipTiles = None
	elif not isinstance(skipTiles, set):
		newSkipTiles = set()
		for tile in skipTiles:
			newSkipTiles.add(tile)
		skipTiles = newSkipTiles

	def bfs_dist_mapper(tile, dist):
		if dist < distanceMap[tile.x][tile.y]:
			distanceMap[tile.x][tile.y] = dist

	breadth_first_foreach_dist(map, startTiles, 1000, bfs_dist_mapper, skipTiles = skipTiles, skipFunc = lambda tile: tile.isCity and tile.player == -1)
	return distanceMap


# Stolen from https://www.geeksforgeeks.org/0-1-knapsack-problem-dp-10/
# Python3 code for Dynamic Programming 
# based solution for 0-1 Knapsack problem 

# Prints the items which are put in a  
# knapsack of capacity W 
def solve_knapsack(items, capacity, weights, values):
	timeStart = time.time()
	n = len(items)
	K = [[0 for w in range(capacity + 1)] 
			for i in range(n + 1)] 
			  
	# Build table K[][] in bottom 
	# up manner 
	for i in range(n + 1): 
		for w in range(capacity + 1): 
			if i == 0 or w == 0: 
				K[i][w] = 0
			elif weights[i - 1] <= w: 
				K[i][w] = max(values[i - 1]  
				  + K[i - 1][w - weights[i - 1]], 
							   K[i - 1][w]) 
			else: 
				K[i][w] = K[i - 1][w]
	# stores the result of Knapsack 
	res = K[n][capacity] 
	logging.info("Value Found {}".format(res))
	includedItems = []
	w = capacity 
	for i in range(n, 0, -1): 
		# lol 0.1 because float rounding error??? 
		if res <= 0: 
			break
		if i == 0:
			logging.info("i == 0 in knapsack items determiner?? res {} i {} w {}".format(res, i, w))
			break
		if w < 0:
			logging.info("w < 0 in knapsack items determiner?? res {} i {} w {}".format(res, i, w))
			break
		# either the result comes from the 
		# top (K[i-1][w]) or from (val[i-1] 
		# + K[i-1] [w-wt[i-1]]) as in Knapsack 
		# table. If it comes from the latter 
		# one/ it means the item is included. 
		# THIS IS WHY VALUE MUST BE INTS
		if res == K[i - 1][w]: 
			continue
		else: 
			# This item is included. 
			logging.info("item at index {} with value {} and weight {} was included... adding it to output. (Res {})".format(i - 1, values[i-1], weights[i-1], res))
			includedItems.append(items[i-1])
			  
			# Since this weight is included 
			# its value is deducted 
			res = res - values[i - 1] 
			w = w - weights[i - 1]
	logging.info("knapsack completed on {} items for capacity {} finding value {} in Duration {:.3f}".format(n, capacity, K[n][capacity], time.time() - timeStart))
	return (K[n][capacity], includedItems)