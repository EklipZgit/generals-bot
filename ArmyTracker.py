'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

import logging
import time
import json
from SearchUtils import *
from collections import deque 
from queue import PriorityQueue 
from Path import Path
from base.client.map import Tile


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
		logging.info("for army {} set self as scrapped because splitting for fog".format(self.toString()))
		self.scrapped = True
		return split


	def clone(self):
		newDude = Army(self.tile)
		if self.path != None:
			newDude.path = self.path.clone()
		newDude.player = self.player
		newDude.visible = self.visible
		newDude.value = self.value
		if self.expectedPath != None:
			newDude.expectedPath = self.expectedPath.clone()
		newDude.entangledArmies = list(self.entangledArmies)
		newDude.name = self.name
		newDude.scrapped = self.scrapped
		return newDude

	def toString(self):
		return "({}) {}".format(self.name, self.tile.toString())

	def __str__(self):
		return self.toString()

	def __repr__(self):
		return self.toString()


class PlayerAggressionTracker(object):
	def __init__(self, index):
		self.player = index


class ArmyTracker(object):
	def __init__(self, map):
		self.map = map
		self.armies: typing.Dict[Tile, Army] = {}
		# used to keep track of armies while attempting to resolve where they went
		self.trackingArmies: typing.Dict[Tile, Army] = {}
		self.isArmyBonus = map.turn % 50 == 0
		self.isCityBonus = map.turn % 2 == 0
		self.distMap = None
		self.lastMove = None
		self.track_threshold = 10
		self.fogPaths = []
		self.emergenceLocationMap = [[[0 for x in range(self.map.rows)] for y in range(self.map.cols)] for z in range(len(self.map.players))]
		self.notify_unresolved_army_emerged = []
		self.player_aggression_ratings = [PlayerAggressionTracker(z) for z in range(len(self.map.players))]
		self.lastTurn = 0

	def __getstate__(self):
		state = self.__dict__.copy()

		if 'notify_unresolved_army_emerged' in state:
			del state['notify_unresolved_army_emerged']

		return state

	def __setstate__(self, state):
		self.__dict__.update(state)
		self.notify_unresolved_army_emerged = []

	# distMap used to determine how to move armies under fog
	def scan(self, distMap, lastMove, turn):
		self.lastMove = lastMove
		logging.info("ARMY TRACKER SCANNING BEEEEEEEEEEEEEEEEEEEEEEEEEEP BOOOOOOOOOOOOP")
		if turn > self.lastTurn:
			self.lastTurn = turn
			self.move_fogged_army_paths()
		self.fogPaths = []
		self.clean_up_armies()
		self.distMap = distMap
		self.isArmyBonus = self.map.turn % 50 == 0
		self.isCityBonus = self.map.turn % 2 == 0
		start = time.time()
		self.track_army_movement()
		self.find_new_armies()
		logging.info("ARMY TRACKER TOOK {:.3f}\n".format(time.time() - start))

	def move_fogged_army_paths(self):
		for army in list(self.armies.values()):
			if not army.tile.visible and army.expectedPath != None:
				nextTile = army.expectedPath.start.next.tile
				if not nextTile.visible:
					logging.info("Moving fogged army {} along expected path {}".format(army.toString(), army.expectedPath.toString()))
					del self.armies[army.tile]
					army.update_tile(nextTile)
					self.armies[nextTile] = army
					army.expectedPath.made_move()

	def clean_up_armies(self):
		for army in list(self.armies.values()):
			if army.scrapped:
				logging.info("Army {} was scrapped last turn, deleting.".format(army.toString()))
				if army.tile in self.armies and self.armies[army.tile] == army:
					del self.armies[army.tile]
				continue
			elif army.player == self.map.player_index and not army.tile.visible:
				logging.info("Army {} was ours but under fog now, so was destroyed. Scrapping.".format(army.toString()))
				self.scrap_army(army)
			elif army.tile.visible and len(army.entangledArmies) > 0 and army.tile.player == army.player:
				if army.tile.army * 1.2 > army.value > (army.tile.army - 1) * 0.8:
					# we're within range of expected army value, resolve entanglement :D
					logging.info("Army {} was entangled and rediscovered :D disentangling other armies".format(army.toString()))
					self.resolve_entangled_armies(army)
				else:
					logging.info("Army {} was entangled at this tile, but army value doesn't match expected?\n  - NOT army.tile.army * 1.2 ({}) > army.value ({}) > (army.tile.army - 1) * 0.8 ({})".format(army.toString(), army.tile.army * 1.2, army.value, (army.tile.army - 1) * 0.8))
					for entangled in army.entangledArmies:
						logging.info("    removing {} from entangled {}".format(army.toString(), entangled.toString()))
						entangled.entangledArmies.remove(army)
					if army.tile in self.armies and self.armies[army.tile] == army:
						del self.armies[army.tile]
				continue
			elif army.tile.delta.gainedSight and (army.tile.player == -1 or (army.tile.player != army.player and len(army.entangledArmies) > 0)):
				logging.info("Army {} just uncovered was an incorrect army prediction. Disentangle and remove from other entangley bois".format(army.toString()))
				for entangled in army.entangledArmies:
					logging.info("    removing {} from entangled {}".format(army.toString(), entangled.toString()))
					entangled.entangledArmies.remove(army)
					
				if army.tile in self.armies and self.armies[army.tile] == army:
					del self.armies[army.tile]


	def track_army_movement(self):
		#for army in list(self.armies.values()):
		#	self.determine_army_movement(army, adjArmies)
		self.trackingArmies = {}
		skip = set()

		for army in list(self.armies.values()):
			armyTile = army.tile
			if army.scrapped:
				continue
			if army.tile in skip:
				logging.info("Army {} was in skip set. Skipping".format(army.toString()))
				continue
			# army may have been removed (due to entangled resolution)
			if armyTile not in self.armies:
				logging.info("Skipped armyTile {} because no longer in self.armies?".format(armyTile.toString()))
				continue
			# army = self.armies[armyTile]
			if army.tile != armyTile:
				raise Exception("bitch, army key {} didn't match army tile {}".format(armyTile.toString(), army.toString()))
			armyRealTileDelta = 0 - army.tile.delta.armyDelta
			logging.info("{} army.value {} actual delta {}, armyRealTileDelta {}".format(army.toString(), army.value, army.tile.delta.armyDelta, armyRealTileDelta))
			foundLocation = False
			#if army.tile.delta.armyDelta == expectedDelta:
			#	# army did not move and we attacked it?

	
			if army.player == army.tile.player and army.value < army.tile.army - 1 and army.tile.visible:
				logging.info("Army {} tile was just gathered to, nbd, update it.".format(army.toString()))
				source = self.find_visible_source(army.tile)
				if source == None:
					logging.info("Army {} must have been gathered to from under the fog, searching:".format(army.toString()))
					sourceFogArmyPath = self.find_fog_source(army.tile)
					if sourceFogArmyPath != None:
						self.fogPaths.append(sourceFogArmyPath.get_reversed())	
						minRatio = 1.8
						isGoodResolution = sourceFogArmyPath.value > army.tile.army * minRatio
						logging.info("sourceFogArmyPath.value ({}) > army.tile.army * {} ({:.1f}) : {}".format(sourceFogArmyPath.value, minRatio, army.tile.army * minRatio, isGoodResolution))
						if not isGoodResolution:
							armyEmergenceValue = abs(army.tile.delta.armyDelta)
							logging.info("  WAS POOR RESOLUTION! Adding emergence for player {} army.tile {} value {}".format(army.tile.player, army.tile.toString(), armyEmergenceValue))
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
						logging.info("Army {} was gathered to visibly from source ARMY {} and will be merged as {}".format(army.toString(), sourceArmy.toString(), larger.toString()))
						skip.add(larger.tile)
						skip.add(smaller.tile)
						self.merge_armies(larger, smaller, army.tile)
						continue
					else:
						logging.info("Army {} was gathered to visibly from source tile {}".format(army.toString(), source.toString()))
				self.trackingArmies[army.tile] = army
				army.update()
				continue

			lostVision = (army.visible and not army.tile.visible)
			# lostVision breaking stuff?
			lostVision = False
			# wheres this fucking + 1 come from...?
			if lostVision or (army.value + 1 + army.tile.delta.expectedDelta != army.tile.army or army.tile.player != army.player):
				# army probably moved. Check adjacents for the army

				for adjacent in army.tile.movable:
					if adjacent.isMountain:
						continue
					expectedAdjDeltaArr = self.get_expected_dest_delta(adjacent)
					for expectedAdjDelta in expectedAdjDeltaArr:
						logging.info("  adjacent {} delta raw {} expectedAdjDelta {}".format(adjacent.toString(), adjacent.delta.armyDelta, expectedAdjDelta))
						adjDelta = abs(adjacent.delta.armyDelta + expectedAdjDelta)
						logging.info("  armyDeltas: army {} {} - adj {} {}  -  lostVision {}".format(army.toString(), armyRealTileDelta, adjacent.toString(), adjDelta, lostVision))
						# if this was our move
						if (self.lastMove != None and self.lastMove.source == army.tile and self.lastMove.dest == adjacent):
							foundLocation = True
							logging.info("    Army (lastMove) probably moved from {} to {}".format(army.toString(), adjacent.toString()))
							self.army_moved(army, adjacent)
							break
						## if this tile was taken by army player and army tile delta was negative
						#if 

					if foundLocation: break

					if armyRealTileDelta > 0 and adjDelta - armyRealTileDelta == 0:
						foundLocation = True
						logging.info("    Army probably moved from {} to {}".format(army.toString(), adjacent.toString()))
						self.army_moved(army, adjacent)
						break
					elif adjacent.delta.gainedSight and armyRealTileDelta > 0 and adjDelta * 0.9 < armyRealTileDelta < adjDelta * 1.25:
						foundLocation = True
						logging.info("    Army (WishyWashyFog) probably moved from {} to {}".format(army.toString(), adjacent.toString()))
						self.army_moved(army, adjacent)
						break
					elif adjDelta != 0 and adjDelta - (army.value) == 0:
						# handle fog moves?
						foundLocation = True
						logging.info("    Army (SOURCE FOGGED?) probably moved from {} to {}. adj (dest) visible? {}".format(army.toString(), adjacent.toString(), adjacent.visible))
						oldTile = army.tile
						if oldTile.army > army.value - adjDelta and not oldTile.visible:
							newArmy = 1 + army.value - adjDelta
							logging.info("Updating tile {} army from {} to {}".format(oldTile.toString(), oldTile.army, newArmy))
							oldTile.army = army.value - adjDelta
						self.army_moved(army, adjacent)
						break
					elif self.isArmyBonus and armyRealTileDelta > 0 and abs(adjDelta - armyRealTileDelta) == 2:
						# handle bonus turn capture moves?
						foundLocation = True
						logging.info("    Army (BONUS CAPTURE?) probably moved from {} to {}".format(army.toString(), adjacent.toString()))
						self.army_moved(army, adjacent)
						break
				if not foundLocation:
					# first check if the map decided where it went
					if army.tile.delta.toTile != None:
						foundLocation = True
						logging.info("  army.tile.delta.toTile != None, using {}".format(army.tile.delta.toTile.toString()))
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
							#if (closestFog == None or self.distMap[adjacent.x][adjacent.y] < self.distMap[closestFog.x][closestFog.y]):
							#	closestFog = adjacent
							fogBois.append(adjacent)
							fogCount += 1
						expectedAdjDeltaArr = self.get_expected_dest_delta(adjacent)
						for expectedAdjDelta in expectedAdjDeltaArr:
							logging.info("  adjacent delta raw {} expectedAdjDelta {}".format(adjacent.delta.armyDelta, expectedAdjDelta))
							adjDelta = abs(adjacent.delta.armyDelta + expectedAdjDelta)
							logging.info("  armyDeltas: army {} {} - adj {} {} expAdj {}".format(army.toString(), armyRealTileDelta, adjacent.toString(), adjDelta, expectedAdjDelta))
							# expectedDelta is fine because if we took the expected tile we would get the same delta as army remaining on army tile.
							if ((armyRealTileDelta > 0 or 
									(not army.tile.visible and 
												adjacent.visible and 
												adjacent.delta.armyDelta != expectedAdjDelta)) and
									adjDelta - armyRealTileDelta == army.tile.delta.expectedDelta):
								foundLocation = True
								logging.info("    Army (Based on expected delta?) probably moved from {} to {}".format(army.toString(), adjacent.toString()))
								self.army_moved(army, adjacent)
								break
						if foundLocation: break
					if not foundLocation and len(fogBois) > 0 and army.player != self.map.player_index and (army.tile.visible or army.tile.delta.lostSight): # prevent entangling and moving fogged cities and stuff that we stopped incrementing
						fogArmies = []
						if len(fogBois) == 1:
							foundLocation = True
							logging.info("    WHOO! Army {} moved into fog at {}!?".format(army.toString(), fogBois[0].toString()))
							self.move_fogged_army(army, fogBois[0])
							if fogCount == 1:
								logging.info("closestFog and fogCount was 1, converting fogTile to be owned by player")
								fogBois[0].player = army.player
							self.army_moved(army, fogBois[0])
						
						else:
							foundLocation = True
							logging.info("    Army {} IS BEING ENTANGLED! WHOO! EXCITING!".format(army.toString()))
							entangledArmies = army.get_split_for_fog(fogBois)
							for i, fogBoi in enumerate(fogBois):
								logging.info("    Army {} entangled moved to {}".format(army.toString(), fogBoi.toString()))
								self.move_fogged_army(entangledArmies[i], fogBoi)
								self.army_moved(entangledArmies[i], fogBoi)
						continue
					if army.player != army.tile.player and army.tile.visible:
						logging.info("  Army {} got eated? Scrapped for not being the right player anymore".format(army.toString()))
						self.scrap_army(army)
				army.update()
			else:
				army.update()
				# army hasn't moved
				if (army.tile.visible and army.value < self.track_threshold - 1) or (not army.tile.visible and army.value < 3):
					logging.info("  Army {} Stopped moving. Scrapped for being low value".format(army.toString()))
					self.scrap_army(army)
				#else:
				#	if army.tile in self.trackingArmies:
				#		# don't continue to track on this army because it didn't move and wont be valuable for evaluating tiles that aren't basic tracking
				#		del self.trackingArmies[army.tile]
				#	else: 
				#		logging.info("    WTF? Army {} no longer in self.trackingArmies, can't remove it?".format(army.toString()))
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
			
			logging.info("  Find visible source  {} ({}) <- {} ({}) ? {}".format(tile.toString(), tile.delta.armyDelta, adjacent.toString(), adjacent.delta.armyDelta, isMatch))
			if isMatch:
				return adjacent

		return None



	def army_moved(self, army, tile):
		if army.tile in self.armies:
			del self.armies[army.tile]
		army.update_tile(tile)
		self.trackingArmies[tile] = army
		if army.value < 0 or (army.player != army.tile.player and army.tile.visible):
			logging.info("    Army {} scrapped for being low value or run into larger tile".format(army.toString()))
			self.scrap_army(army)

	def scrap_army(self, army):
		army.scrapped = True
		for entangledArmy in army.entangledArmies:
			entangledArmy.scrapped = True
		self.resolve_entangled_armies(army)

	def resolve_entangled_armies(self, army):
		if len(army.entangledArmies) > 0:
			logging.info("{} resolving {} entangled armies".format(army.toString(), len(army.entangledArmies)))
			for entangledArmy in army.entangledArmies:
				logging.info("    {} entangled".format(entangledArmy.toString()))
				if entangledArmy.tile in self.armies:
					del self.armies[entangledArmy.tile]
				entangledArmy.scrapped = True
				if not entangledArmy.tile.visible and entangledArmy.tile.army > 0:
					# remove the army value from the tile?
					newArmy = max(entangledArmy.tile.army - entangledArmy.entangledValue - 1, 0)
					logging.info("    updating entangled army tile {} from army {} to {}".format(entangledArmy.toString(), entangledArmy.tile.army, newArmy))
					entangledArmy.tile.army = newArmy
				entangledArmy.entangledArmies = []
			army.entangledArmies = []

	def army_could_capture(self, army, fogTargetTile):
		if army.player != fogTargetTile.player:
			return army.value > fogTargetTile.army
		return True

	def move_fogged_army(self, army, fogTargetTile):
		if army.tile in self.armies:
			del self.armies[army.tile]
		if fogTargetTile.player == army.player:
			fogTargetTile.army += army.value
		else:
			fogTargetTile.army = army.value - fogTargetTile.army
		logging.info("      fogTargetTile {} updated army to {}".format(fogTargetTile.toString(), fogTargetTile.army))
		# breaks stuff real bad. Don't really want to do this anyway. 
		# Rather track the army through fog with no consideration of owning the tiles it crosses
		#fogTargetTile.player = army.player
		army.update_tile(fogTargetTile)
		self.armies[fogTargetTile] = army
		
	def get_expected_delta(self, tile):
		if self.map.players[tile.player].dead:
			return 0
		expected = 0
		if (tile.isCity or tile.isGeneral) and self.isCityBonus:
			expected += 1
		if self.lastMove != None and tile == self.lastMove.dest:
			if self.lastMove.non_friendly and self.lastMove.dest.delta.oldOwner != self.lastMove.dest.delta.newOwner:
				expected -= self.lastMove.army_moved
			else:
				expected += self.lastMove.army_moved
			logging.info("    {} delta lastMove.dest: non_friendly {} army_moved {} to change expected delta to {}".format(self.lastMove.dest.toString(), self.lastMove.non_friendly, self.lastMove.army_moved, expected))

		return expected

	# returns an array due to the possibility of winning or losing the move-first coinflip, 
	# and need to account for both when the inspected tile is the source tile of our last army move
	def get_expected_dest_delta(self, tile):
		baseExpected = 0
		if tile.delta.oldOwner != tile.delta.newOwner:
			baseExpected = tile.delta.expectedDelta
		else:
			baseExpected = 0 - tile.delta.expectedDelta

		expected = [baseExpected]
		if self.lastMove != None and tile == self.lastMove.dest:
			wonFight = self.lastMove.dest.player == self.map.player_index
			logging.info("    {} dest_delta lastMove.dest: delta {} armyMoved {} nonFriendly {} wonFight {}".format(self.lastMove.dest.toString(), self.lastMove.dest.delta.armyDelta, self.lastMove.army_moved, self.lastMove.non_friendly, wonFight))
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
			logging.info("      expected delta to {} (baseExpected {})".format(expected[0], baseExpected))
		
		if self.lastMove != None and tile == self.lastMove.source:
			expected = [baseExpected,0]
			wonFight = self.lastMove.source.player == self.map.player_index
			logging.info("    {} dest_delta  lastMove.source: delta {} armyMoved {} wonFight {}".format(self.lastMove.source.toString(), self.lastMove.source.delta.armyDelta, self.lastMove.army_moved, wonFight))
			# inverted because we were moving away from
			if not wonFight:
				expected[1] = self.lastMove.army_moved
			else:
				expected[1] = 0 - self.lastMove.army_moved
			
			expected[1] += baseExpected
			logging.info("      expected delta to 0 or {} (baseExpected {})".format(expected[1], baseExpected))

		return expected


	def get_nearby_armies(self, army, armyMap = None):
		if armyMap == None:
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
			logging.info("Army {} had nearbyArmy {}".format(army.toString(), nearbyArmy.toString()))
		return nearbyArmies

	def find_new_armies(self):
		logging.info("Finding new armies:")
		playerLargest = [None for x in range(len(self.map.players))]
		# don't do largest tile for now?
		#for tile in self.map.pathableTiles:
		#	if tile.player != -1 and (playerLargest[tile.player] == None or tile.army > playerLargest[tile.player].army):
		#		playerLargest[tile.player] = tile
		for tile in self.map.pathableTiles:			
			notOurMove = (self.lastMove == None or (tile != self.lastMove.source and tile != self.lastMove.dest))
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

			if (tileArmy == None or tileArmy.scrapped) and tile.player != -1 and (playerLargest[tile.player] == tile or tile.army >= self.track_threshold or tileNewlyMovedByEnemy):
				logging.info("{} Discovered as Army! (tile.army {}, tile.delta {}) Determining if came from fog".format(tile.toString(), tile.army, tile.delta.armyDelta))
				resolvedFogSourceArmy = False
				resolvedReasonableFogValuePath = False
				if abs(tile.delta.armyDelta) > tile.army / 2:
					# maybe this came out of the fog?
					sourceFogArmyPath = self.find_fog_source(tile)
					if sourceFogArmyPath != None:
						self.fogPaths.append(sourceFogArmyPath.get_reversed())
						resolvedFogSourceArmy = True
						minRatio = 1.8
						isGoodResolution = sourceFogArmyPath.value > tile.army * minRatio
						logging.info("sourceFogArmyPath.value ({}) > tile.army * {} ({:.1f}) : {}".format(sourceFogArmyPath.value, minRatio, tile.army * minRatio, isGoodResolution))
						if not isGoodResolution:
							armyEmergenceValue = abs(tile.delta.armyDelta)
							logging.info("  WAS POOR RESOLUTION! Adding emergence for player {} tile {} value {}".format(tile.player, tile.toString(), armyEmergenceValue))
							self.new_army_emerged(tile, armyEmergenceValue)
						self.resolve_fog_emergence(sourceFogArmyPath, tile)
				if not resolvedFogSourceArmy:
					# then tile is a new army.
					army = Army(tile)
					self.armies[tile] = army
					self.new_army_emerged(tile, tile.army - 1)
				# if tile WAS bordered by fog find the closest fog army and remove it (not tile.visible or tile.delta.gainedSight)


	def new_army_emerged(self, emergedTile, armyEmergenceValue):
		logging.info("running new_army_emerged for tile {}".format(emergedTile.toString()))
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
		logging.info("running tile_discovered_neutral for tile {}".format(neutralTile.toString()))
		distance = 6
		armyEmergenceValue = 40
		def foreachFunc(tile, dist):
			self.emergenceLocationMap[neutralTile.player][tile.x][tile.y] -= 1 * armyEmergenceValue // (dist + 5)
			if self.emergenceLocationMap[neutralTile.player][tile.x][tile.y] < 0:
				self.emergenceLocationMap[neutralTile.player][tile.x][tile.y] = 0

		negativeLambda = lambda tile: tile.discovered or tile.player >= 0
		skipFunc = lambda tile: tile.visible and tile != neutralTile
		breadth_first_foreach_dist(self.map, [neutralTile], distance, foreachFunc, negativeLambda, skipFunc)



	def find_fog_source(self, tile):
		if len(where(tile.movable, lambda adj: not adj.isNotPathable and (adj.delta.gainedSight or not adj.visible))) == 0:
			logging.info("        For new army at tile {} there were no adjacent fogBois, no search".format(tile.toString()))
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
						logging.info("using moveHalfVal {:.1f} over val {:.1f} for tile {} turn {}".format(moveHalfVal, val, thisTile.toString(), self.map.turn))
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
			return (nextTile.visible and not nextTile.delta.gainedSight) or turnsNegative > 1 or consecutiveUndiscovered > 7 or dist > 15
		inputTiles = {}
		delta = abs(tile.delta.armyDelta)
		logging.info("Looking for fog army path of value {} to tile {}".format(delta, tile.toString()))
		# we want the path to get army up to 0, so start it at the negative delta (positive)
		inputTiles[tile] = ((0, delta, 0, 0), 0)

		fogSourcePath = breadth_first_dynamic_max(self.map,
											inputTiles,
											valFunc,
											noNeutralCities=True,
											priorityFunc=pathSortFunc,
											skipFunc=fogSkipFunc,
											searchingPlayer = tile.player, logResultValues = True)
		if (fogSourcePath != None):
			logging.info("        For new army at tile {} we found fog source path???? {}".format(tile.toString(), fogSourcePath.toString()))
		else:
			logging.info("        NO fog source path for new army at {}".format(tile.toString()))
		return fogSourcePath

	def resolve_fog_emergence(self, sourceFogArmyPath, fogTile):
		existingArmy = None
		armiesFromFog = []
		if fogTile in self.armies:
			existingArmy = self.armies[fogTile]
			if existingArmy.player == fogTile.player:
				armiesFromFog.append(existingArmy)

		node = sourceFogArmyPath.start.next
		while node != None:
			logging.info("resolve_fog_emergence tile {}".format(node.tile.toString()))
			if node.tile in self.armies:
				logging.info("  was army {}".format(node.tile.toString()))
				armiesFromFog.append(self.armies[node.tile])
			if node.tile.army > 0:
				node.tile.army = 1
			node = node.next

		maxArmy = None
		for army in armiesFromFog:
			if maxArmy == None or maxArmy.value < army.value:
				maxArmy = army

		if maxArmy != None:
			if maxArmy.tile in self.armies:
				del self.armies[maxArmy.tile]

			# update path on army
			node = sourceFogArmyPath.get_reversed().start
			while node.tile != maxArmy.tile:
				node = node.next
			node = node.next
			while node != None:
				maxArmy.update_tile(node.tile)
				node = node.next

			# scrap other armies from the fog
			for army in armiesFromFog:
				if army != maxArmy:
					logging.info("  scrapping {}".format(army.toString()))
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