'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

import logging
import time
import json

import SearchUtils
from SearchUtils import *
from collections import deque 
from queue import PriorityQueue 
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
		self.entangledArmies = []
		self.name = self.get_letter()
		self.entangledValue = None
		self.scrapped = False

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
		if self.expectedPath is not None:
			newDude.expectedPath = self.expectedPath.clone()
		newDude.entangledArmies = list(self.entangledArmies)
		newDude.name = self.name
		newDude.scrapped = self.scrapped
		return newDude

	def toString(self):
		return f"({self.name}) {self.tile.toString()}"

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
		"""??? how is this different from tracking armies...?"""
		self.trackingArmies: typing.Dict[Tile, Army] = {}
		"""used to keep track of armies while attempting to resolve where they went"""
		self.distMap = None
		self.lastMove: Move | None = None
		self.track_threshold = 10
		self.fogPaths = []
		self.emergenceLocationMap: typing.List[typing.List[typing.List[int]]] = [[[0 for x in range(self.map.rows)] for y in range(self.map.cols)] for z in range(len(self.map.players))]
		self.notify_unresolved_army_emerged: typing.List[typing.Callable[[Tile], None]] = []
		self.notify_army_moved: typing.List[typing.Callable[[Tile], None]] = []
		self.player_aggression_ratings = [PlayerAggressionTracker(z) for z in range(len(self.map.players))]
		self.lastTurn = 0

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
	def scan(self, distMap, lastMove, turn):
		self.lastMove = lastMove
		advancedTurn = False
		if turn > self.lastTurn:
			advancedTurn = True
			self.lastTurn = turn
			self.player_moves_this_turn: typing.Set[int] = set()
		else:
			logging.info(f'army tracker scan ran twice this turn {turn}...? Bailing?')
			return

		# if we have perfect info about a players general / cities, we don't need to track emergence, clear the emergence map
		for player in self.map.players:
			if self.has_perfect_information_of_player_cities_and_general(player.index):
				self.emergenceLocationMap[player.index] = [[0 for x in range(self.map.rows)] for y in range(self.map.cols)]

		self.fogPaths = []
		self.distMap = distMap
		self.track_army_movement()
		self.clean_up_armies()
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
				oldTile = army.tile
				oldTile.army = 1
				nextTile.army = nextTile.army + army.value
				army.update_tile(nextTile)
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
			elif army.tile.delta.gainedSight and (army.tile.player == -1 or (army.tile.player != army.player and len(army.entangledArmies) > 0)):
				logging.info(
					f"Army {army.toString()} just uncovered was an incorrect army prediction. Disentangle and remove from other entangley bois")
				for entangled in army.entangledArmies:
					logging.info(f"    removing {army.toString()} from entangled {entangled.toString()}")
					entangled.entangledArmies.remove(army)
					
				if army.tile in self.armies and self.armies[army.tile] == army:
					del self.armies[army.tile]


	def track_army_movement(self):
		#for army in list(self.armies.values()):
		#	self.determine_army_movement(army, adjArmies)
		self.trackingArmies = {}
		skip = set()

		tempTileShouldBe3 = self.map.GetTile(11, 13)
		tempTileTg = self.map.GetTile(10, 14)

		unaccountedDiffs: typing.Dict[Tile, int] = {}
		"""Negative number means enemy moved here"""

		# deal with our armies first so we can build up unaccounted for diffs in advance of looking at what other players MIGHT have done
		for army in filter(lambda a: a.player == self.map.player_index, list(self.armies.values())):
			self.try_track_army(army, skip, unaccountedDiffs)

		for army in filter(lambda a: a.player != self.map.player_index, list(self.armies.values())):
			self.try_track_army(army, skip, unaccountedDiffs)

		for army in self.trackingArmies.values():
			self.armies[army.tile] = army
	
	def find_visible_source(self, tile):
		if tile.delta.armyDelta == 0:
			return None
		# todo check for 0 sums first before 2 >= x >= -2
		for adjacent in tile.movable:
			isMatch = False
			if 2 >= tile.delta.armyDelta + adjacent.delta.armyDelta >= -2:
				isMatch = True
			
			logging.info(
				f"  Find visible source  {tile.toString()} ({tile.delta.armyDelta}) <- {adjacent.toString()} ({adjacent.delta.armyDelta}) ? {isMatch}")
			if isMatch:
				return adjacent

		return None

	def army_moved(self, army, tile, dontUpdateArmy=False):
		oldTile = army.tile
		if army.tile in self.armies:
			del self.armies[army.tile]
		if army.visible and tile.visible or tile.delta.lostSight:
			if army.player in self.player_moves_this_turn:
				logging.error(f'Yo, we think a player moved twice this turn...?')

			self.player_moves_this_turn.add(army.player)

		army.update_tile(tile)
		self.trackingArmies[tile] = army
		if army.value < 0 or (army.player != army.tile.player and army.tile.visible):
			logging.info(f"    Army {army.toString()} scrapped for being low value or run into larger tile")
			self.scrap_army(army)
		if army.tile.visible and len(army.entangledArmies) > 0:
			self.resolve_entangled_armies(army)

		if not oldTile.visible and not dontUpdateArmy:
			oldTile.army = 1
			oldTile.player = army.player
			if self.map.is_army_bonus_turn:
				oldTile.army += 1
			if oldTile.isCity or oldTile.isGeneral and self.map.is_city_bonus_turn:
				oldTile.army += 1

		if army.player != self.map.player_index:
			targets = self.map.players[self.map.player_index].cities.copy()
			targets.append(self.map.generals[self.map.player_index])
			army.expectedPath = SearchUtils.breadth_first_find_queue(
				self.map,
				[army.tile],
				goalFunc=lambda tile, army, dist: army > 0 and tile in targets,
				maxTime=0.1,
				maxDepth=10,
				noNeutralCities=tile.army < 150,
				searchingPlayer=army.player)

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
		#fogTargetTile.player = army.player
		army.update_tile(fogTargetTile)
		self.armies[fogTargetTile] = army
		for listener in self.notify_army_moved:
			listener(army.tile)

	# returns an array due to the possibility of winning or losing the move-first coinflip, 
	# and need to account for both when the inspected tile is the source tile of our last army move
	def get_expected_dest_delta(self, tile):
		baseExpected = 0
		# if tile.delta.oldOwner != tile.delta.newOwner:
		# 	baseExpected = tile.delta.expectedDelta
		# else:
		# 	baseExpected = 0 - tile.delta.expectedDelta

		expected = [baseExpected]
		if self.lastMove is not None and tile == self.lastMove.dest:
			wonFight = self.lastMove.dest.player == self.map.player_index
			logging.info(
				f"    {self.lastMove.dest.toString()} dest_delta lastMove.dest: delta {self.lastMove.dest.delta.armyDelta} armyMoved {self.lastMove.army_moved} nonFriendly {self.lastMove.non_friendly} wonFight {wonFight}")
			# 4 cases. 
			# we won a fight on dest, and dest started as opps (non_friendly == True)
			# we lost a fight on dest, dest started as opps (non_friendly == True)
			# we won a fight on dest, and dest started as ours (non_friendly == False)
			# we lost a fight on dest, dest started as ours (non_friendly == False)
			if self.lastMove.non_friendly:
				expected[0] = self.lastMove.army_moved
			else:
				expected[0] = 0 - self.lastMove.army_moved
			expected[0] += baseExpected
			logging.info(f"      expected delta to {expected[0]} (baseExpected {baseExpected})")
		
		if self.lastMove is not None and tile == self.lastMove.source:
			expected = [0, baseExpected]
			wonFight = self.lastMove.source.player == self.map.player_index
			logging.info(
				f"    {self.lastMove.source.toString()} dest_delta  lastMove.source: delta {self.lastMove.source.delta.armyDelta} armyMoved {self.lastMove.army_moved} wonFight {wonFight}")
			# inverted because we were moving away from
			if not wonFight:
				expected[0] = self.lastMove.army_moved
			else:
				expected[0] = 0 - self.lastMove.army_moved
			
			expected[0] += baseExpected
			logging.info(f"      expected delta to 0 or {expected[1]} (baseExpected {baseExpected})")

		return expected


	def get_nearby_armies(self, army, armyMap = None):
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
		#for tile in self.map.pathableTiles:
		#	if tile.player != -1 and (playerLargest[tile.player] == None or tile.army > playerLargest[tile.player].army):
		#		playerLargest[tile.player] = tile
		for tile in self.map.pathableTiles:			
			notOurMove = (self.lastMove is None or (tile != self.lastMove.source and tile != self.lastMove.dest))
			tileNewlyMovedByEnemy = (tile not in self.armies 
									and not tile.delta.gainedSight 
									and tile.player != self.map.player_index 
									and abs(tile.delta.armyDelta) > 2 
									and tile.army > 2
									and notOurMove)

			# if we moved our army into a spot last turn that a new enemy army appeared this turn
			tileArmy = None
			if tile in self.armies:
				tileArmy = self.armies[tile]

			if (tileArmy is None or tileArmy.scrapped) and tile.player != -1 and (playerLargest[tile.player] == tile or tile.army >= self.track_threshold or tileNewlyMovedByEnemy):
				logging.info(
					f"{tile.toString()} Discovered as Army! (tile.army {tile.army}, tile.delta {tile.delta.armyDelta}) Determining if came from fog")
				resolvedFogSourceArmy = False
				resolvedReasonableFogValuePath = False
				if abs(tile.delta.armyDelta) > tile.army / 2:
					# maybe this came out of the fog?
					sourceFogArmyPath = self.find_fog_source(tile)
					if sourceFogArmyPath is not None:
						self.fogPaths.append(sourceFogArmyPath.get_reversed())
						resolvedFogSourceArmy = True
						minRatio = 1.8
						isGoodResolution = sourceFogArmyPath.value > tile.army * minRatio
						logging.info(
							f"sourceFogArmyPath.value ({sourceFogArmyPath.value}) > tile.army * {minRatio} ({tile.army * minRatio:.1f}) : {isGoodResolution}")
						if not isGoodResolution:
							armyEmergenceValue = abs(tile.delta.armyDelta)
							logging.info(
								f"  WAS POOR RESOLUTION! Adding emergence for player {tile.player} tile {tile.toString()} value {armyEmergenceValue}")
							self.new_army_emerged(tile, armyEmergenceValue)
						self.resolve_fog_emergence(sourceFogArmyPath, tile)
				if not resolvedFogSourceArmy:
					# then tile is a new army.
					army = Army(tile)
					self.armies[tile] = army
					self.new_army_emerged(tile, tile.army - 1)
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
			#armyEmergenceValue =
			armyEmergenceValue = 2 + (armyEmergenceValue ** 0.8)
			if armyEmergenceValue > 50:
				armyEmergenceValue = 50


			def foreachFunc(tile, dist):
				self.emergenceLocationMap[emergedTile.player][tile.x][tile.y] += 3 * armyEmergenceValue // max(7, (dist + 1))

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
		if delta is None:
			delta = abs(tile.delta.armyDelta)
		if len(where(tile.movable, lambda adj: not adj.isNotPathable and (adj.delta.gainedSight or not adj.visible))) == 0:
			logging.info(f"        For new army at tile {tile.toString()} there were no adjacent fogBois, no search")
			return None
		distPowFactor = 0.3
		distOffset = 4
		#best = -2000
		#bestArmy = 0
		#bestDist = 0
		#for negArmy in range(-50, 50, 5):
		#	for dist in range(0,10, 2):
		#		val = 1000 - (2*abs(negArmy) - negArmy) * ((distOffset+dist)**distPowFactor)
		#		if dist == 0:
		#			val = -2000
		#		if val > best:
		#			best = val
		#			bestArmy = negArmy
		#			bestDist = dist
		#		logging.info("trackerValFunc negArmy {} dist {} = {:.1f}".format(negArmy, dist, val))
		#logging.info("Best was negArmy {} dist {} val {:.1f}".format(bestArmy, bestDist, best))

		def valFunc(thisTile, prioObject):
			(dist, negArmy, turnsNegative, consecUndisc) = prioObject
			val = 0
			if dist == 0:
				val = -2000
			else:
				val = 1000 - (2*abs(negArmy) - negArmy) * ((distOffset+dist)**distPowFactor)
				if thisTile.player == tile.player and thisTile.army > 8:
					negArmy += thisTile.army // 2
					moveHalfVal = 1000 - (2*abs(negArmy) - negArmy) * ((distOffset+dist)**distPowFactor)
					if moveHalfVal > val:
						logging.info(
							f"using moveHalfVal {moveHalfVal:.1f} over val {val:.1f} for tile {thisTile.toString()} turn {self.map.turn}")
						val = moveHalfVal
			# closest path value to the actual army value. Fake tuple for logging.
			# 2*abs for making it 3x improvement on the way to the right path, and 1x unemprovement for larger armies than the found tile
			# negative weighting on dist to try to optimize for shorter paths instead of exact 
			return (val, 0)
			#if (0-negArmy) - dist*2 < tile.army:
			#	return (0-negArmy)
			#return -1

		def pathSortFunc(nextTile, prioObject):
			(dist, negArmy, turnsNeg, consecutiveUndiscovered) = prioObject
			if nextTile in self.armies:
				consecutiveUndiscovered = 0
				theArmy = self.armies[nextTile]
				if theArmy.player == tile.player:
					negArmy -= nextTile.army - 1
				else:
					negArmy += nextTile.army + 1
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
			return (dist, negArmy, turnsNeg, consecutiveUndiscovered)

		def fogSkipFunc(nextTile, prioObject): 
			(dist, negArmy, turnsNegative, consecutiveUndiscovered) = prioObject
			#logging.info("nextTile {}: negArmy {}".format(nextTile.toString(), negArmy))
			return (nextTile.visible and not nextTile.delta.gainedSight) or turnsNegative > 1 or consecutiveUndiscovered > 8 or dist > 17

		inputTiles = {}
		logging.info(f"Looking for fog army path of value {delta} to tile {tile.toString()}")
		# we want the path to get army up to 0, so start it at the negative delta (positive)
		inputTiles[tile] = ((0, delta, 0, 0), 0)

		fogSourcePath = breadth_first_dynamic_max(self.map,
											inputTiles,
											valFunc,
											noNeutralCities=True,
											priorityFunc=pathSortFunc,
											skipFunc=fogSkipFunc,
											searchingPlayer = tile.player, logResultValues = True)
		if (fogSourcePath is not None):
			logging.info(
				f"        For new army at tile {tile.toString()} we found fog source path???? {fogSourcePath.toString()}")
		else:
			logging.info(f"        NO fog source path for new army at {tile.toString()}")
		return fogSourcePath

	def resolve_fog_emergence(self, sourceFogArmyPath, fogTile):
		existingArmy = None
		armiesFromFog = []
		if fogTile in self.armies:
			existingArmy = self.armies[fogTile]
			if existingArmy.player == fogTile.player:
				armiesFromFog.append(existingArmy)

		node = sourceFogArmyPath.start.next
		while node is not None:
			logging.info(f"resolve_fog_emergence tile {node.tile.toString()}")
			if node.tile in self.armies:
				logging.info(f"  was army {node.tile.toString()}")
				armiesFromFog.append(self.armies[node.tile])
			if node.tile.army > 0:
				node.tile.army = 1
			node = node.next

		maxArmy = None
		for army in armiesFromFog:
			if maxArmy is None or maxArmy.value < army.value:
				maxArmy = army

		if maxArmy is not None:
			if maxArmy.tile in self.armies:
				del self.armies[maxArmy.tile]

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
			self.armies[fogTile] = maxArmy
			maxArmy.expectedPath = None
		else:
			# then this is a brand new army because no armies were on the fogPath, but we set the source path to 1's still
			army = Army(fogTile)
			self.armies[fogTile] = army
			army.path = sourceFogArmyPath

	def merge_armies(self, largerArmy, smallerArmy, finalTile):
		del self.armies[largerArmy.tile]
		del self.armies[smallerArmy.tile]
		self.scrap_army(smallerArmy)
		
		if largerArmy.tile != finalTile:
			largerArmy.update_tile(finalTile)
		self.armies[finalTile] = largerArmy
		largerArmy.update()

	def has_perfect_information_of_player_cities_and_general(self, player: int):
		mapPlayer = self.map.players[player]
		if mapPlayer.general is not None and len(mapPlayer.cities) == mapPlayer.cityCount - 1:
			# then we have perfect information about the player, no point in tracking emergence values
			return True

		return False

	def try_track_army(self, army: Army, skip: typing.Set[Tile], unaccountedForDiffs: typing.Dict[Tile, int]):
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
		# if armyRealTileDelta == 0 and armyTile.visible:
		# 	# Army didn't move...?
		# 	continue
		logging.info(
			f"{army.toString()} army.value {army.value} actual delta {army.tile.delta.armyDelta}, armyRealTileDelta {armyRealTileDelta}")
		foundLocation = False
		# if army.tile.delta.armyDelta == expectedDelta:
		#	# army did not move and we attacked it?

		if army.visible and army.player == army.tile.player and army.value < army.tile.army - 1:
			logging.info(
				f"Army {army.toString()} tile was just gathered to (or city increment or whatever), nbd, update it.")
			unaccountedForDelta = army.tile.army - army.value - 1
			source = self.find_visible_source(army.tile)
			if source is None:
				logging.info(
					f"Army {army.toString()} must have been gathered to from under the fog, searching:")
				sourceFogArmyPath = self.find_fog_source(army.tile, unaccountedForDelta)
				if sourceFogArmyPath is not None:
					self.fogPaths.append(sourceFogArmyPath.get_reversed())
					minRatio = 1.8
					isGoodResolution = sourceFogArmyPath.value > army.tile.army * minRatio
					logging.info(
						f"sourceFogArmyPath.value ({sourceFogArmyPath.value}) > army.tile.army * {minRatio} ({army.tile.army * minRatio:.1f}) : {isGoodResolution}")
					if not isGoodResolution:
						armyEmergenceValue = max(4, abs(army.tile.delta.armyDelta) - sourceFogArmyPath.value)
						logging.info(
							f"  WAS POOR RESOLUTION! Adding emergence for player {army.tile.player} army.tile {army.tile.toString()} value {armyEmergenceValue}")
						self.new_army_emerged(army.tile, armyEmergenceValue)

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
			self.trackingArmies[army.tile] = army
			army.update()
			return

		lostVision = (army.visible and not army.tile.visible)
		# lostVision breaking stuff?
		lostVision = False
		# army values are 1 less than the actual tile value, so +1
		if lostVision or (
				army.value + 1 + army.tile.delta.expectedDelta != army.tile.army or army.tile.player != army.player):
			# army probably moved. Check adjacents for the army

			for adjacent in army.tile.movable:
				if adjacent.isMountain:
					continue
				expectedAdjDeltaArr = self.get_expected_dest_delta(adjacent)
				adjDelta = abs(adjacent.delta.armyDelta)
				unexplainedDelta = adjacent.delta.armyDelta - expectedAdjDeltaArr[0]
				for expectedAdjDelta in expectedAdjDeltaArr:
					logging.info(
						f"  adjacent {adjacent.toString()} delta raw {adjacent.delta.armyDelta} expectedAdjDelta {expectedAdjDelta}")
					logging.info(
						f"  armyDeltas: army {army.toString()} {armyRealTileDelta} - adj {adjacent.toString()} {adjDelta}  -  lostVision {lostVision}")
					# if this was our move
					if (self.lastMove is not None
							and self.lastMove.source == army.tile
							and self.lastMove.dest == adjacent):
						foundLocation = True
						logging.info(
							f"    Army (lastMove) probably moved from {army.toString()} to {adjacent.toString()}")
						expectedDelta = 0 - army.value
						if self.lastMove.move_half:
							expectedDelta = 0 - (army.value + 1) // 2
						actualDelta = adjacent.delta.armyDelta
						self.army_moved(army, adjacent)
						unaccountedForDiffs[self.lastMove.dest] = expectedDelta - actualDelta
						break

				if foundLocation:
					break

				if armyRealTileDelta > 0 and adjDelta - armyRealTileDelta == 0:  # < 0...?
					foundLocation = True
					logging.info(
						f"    Army probably moved from {army.toString()} to {adjacent.toString()}")
					self.army_moved(army, adjacent)
					break
				elif armyRealTileDelta > 0 and unexplainedDelta - armyRealTileDelta == 0:  # < 0...?
					foundLocation = True
					logging.info(
						f"    Army probably moved from {army.toString()} to {adjacent.toString()} based on unexplainedDelta {unexplainedDelta} vs armyRealTileDelta {armyRealTileDelta}")
					self.army_moved(army, adjacent)
					break

				elif not army.tile.visible and unexplainedDelta > 1:  # < 0...?
					if unexplainedDelta * 1.1 - army.tile.army > 0:
						foundLocation = True
						logging.info(
							f"    Army probably moved from {army.toString()} to {adjacent.toString()} based on unexplainedDelta {unexplainedDelta} vs armyRealTileDelta {armyRealTileDelta}")
						self.army_moved(army, adjacent)
						break

				elif adjacent.delta.gainedSight and armyRealTileDelta > 0 and adjDelta * 0.9 < armyRealTileDelta < adjDelta * 1.25:
					foundLocation = True
					logging.info(
						f"    Army (WishyWashyFog) probably moved from {army.toString()} to {adjacent.toString()}")
					self.army_moved(army, adjacent)
					break
				elif adjDelta != 0 and adjDelta - army.value == 0:
					# handle fog moves?
					foundLocation = True
					logging.info(
						f"    Army (SOURCE FOGGED?) probably moved from {army.toString()} to {adjacent.toString()}. adj (dest) visible? {adjacent.visible}")
					oldTile = army.tile
					if oldTile.army > army.value - adjDelta and not oldTile.visible:
						newArmy = adjacent.army
						logging.info(
							f"Updating tile {oldTile.toString()} army from {oldTile.army} to {newArmy}")
						oldTile.army = army.value - adjDelta + 1

					self.army_moved(army, adjacent)
					break
			# elif self.isArmyBonus and armyRealTileDelta > 0 and abs(adjDelta - armyRealTileDelta) == 2:
			# 	# handle bonus turn capture moves?
			# 	foundLocation = True
			# 	logging.info("    Army (BONUS CAPTURE?) probably moved from {} to {}".format(army.toString(), adjacent.toString()))
			# 	self.army_moved(army, adjacent)
			# 	break

			if not foundLocation:
				# first check if the map decided where it went
				if army.tile.delta.toTile is not None:
					foundLocation = True
					logging.info(
						f"  army.tile.delta.toTile != None, using {army.tile.delta.toTile.toString()}")
					self.army_moved(army, army.tile.delta.toTile)

			if not foundLocation:
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
						#	closestFog = adjacent
						fogBois.append(adjacent)
						fogCount += 1

					expectedAdjDeltaArr = self.get_expected_dest_delta(adjacent)
					for expectedAdjDelta in expectedAdjDeltaArr:
						logging.info(
							f"  adjacent delta raw {adjacent.delta.armyDelta} expectedAdjDelta {expectedAdjDelta}")
						adjDelta = abs(adjacent.delta.armyDelta + expectedAdjDelta)
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
							self.army_moved(army, adjacent)
							break

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
						self.army_moved(army, fogBois[0], dontUpdateArmy=True)

					else:
						foundLocation = True
						logging.info(f"    Army {army.toString()} IS BEING ENTANGLED! WHOO! EXCITING!")
						entangledArmies = army.get_split_for_fog(fogBois)
						for i, fogBoi in enumerate(fogBois):
							logging.info(
								f"    Army {army.toString()} entangled moved to {fogBoi.toString()}")
							self.move_fogged_army(entangledArmies[i], fogBoi)
							self.army_moved(entangledArmies[i], fogBoi, dontUpdateArmy=True)
					return

				if army.player != army.tile.player and army.tile.visible:
					logging.info(f"  Army {army.toString()} got eated? Scrapped for not being the right player anymore")
					self.scrap_army(army)

			army.update()
		else:
			army.update()
			# army hasn't moved
			if (army.tile.visible and army.value < self.track_threshold - 1) or (
					not army.tile.visible and army.value < 3):
				logging.info(f"  Army {army.toString()} Stopped moving. Scrapped for being low value")
				self.scrap_army(army)