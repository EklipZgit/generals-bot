'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

import logging
from copy import deepcopy
import time
import json
from collections import deque 
from queue import PriorityQueue
from pprint import pprint,pformat

from base.client.map import Tile


class PathNode(object):
	def __init__(self, tile, parent, value, turn, cityCount, pathDict):
		self.tile = tile
		self.parent = parent
		self.value = value
		self.turn = turn
		self.move_half = False
		self.cityCount = cityCount
		self.pathDict = pathDict

	def __gt__(self, other):
		if (other == None):
			return True
		return self.turn > other.turn

	def __lt__(self, other):
		if (other == None):
			return True
		return self.turn < other.turn

	def __str__(self):
		return f'{str(self.parent) if self.parent is not None else ""} -> {str(self.tile)}'

	def __repr__(self):
		return str(self)

def get_tile_list_from_path(pathObject):
	path = pathObject.start
	if path == None:
		return None
	pathList = []
	while path != None:
		pathList.append(path.tile)
		path = path.next
	return pathList
	

def get_tile_set_from_path(pathObject):
	return pathObject.tileSet


def reverse_path(path):
	newPath = path.get_reversed()
	return newPath


def get_player_army_amount_on_path(path, player, startIdx = 0, endIdx = 1000):
	value = 0
	idx = 0
	pathNode = path.start
	while (pathNode != None):
		if (pathNode.tile.player == player and idx >= startIdx and idx <= endIdx):
			value += (pathNode.tile.army - 1)
		pathNode = pathNode.next
		idx += 1
	return value


class TreeNode(object):
	def __init__(self, tile, fromTile, turn):
		self.tile = tile
		self.fromTile = fromTile
		self.value = 0
		self.trunkValue = 0
		self.trunkDistance = 0
		self.turn = turn
		self.gatherTurns = 0
		self.neutrals = 0
		self.children = []
		self.pruned = []

	def __gt__(self, other):
		if (other == None):
			return True
		return self.value > other.value
	def __lt__(self, other):
		if (other == None):
			return False
		return self.value < other.value
	def __eq__(self, other):
		if (None == other):
			return False
		return self.tile == other.tile

	def deep_clone(self):
		newNode = TreeNode(self.tile, self.fromTile, self.turn)
		newNode.value = self.value
		newNode.trunkValue = self.trunkValue
		newNode.gatherTurns = self.gatherTurns
		newNode.neutrals = self.neutrals
		newNode.children = [node.deep_clone() for node in self.children]
		newNode.pruned = [node.deep_clone() for node in self.pruned]
		return newNode

class Move(object):
	def __init__(self, source: Tile, dest: Tile, move_half = False):
		self.source: Tile = source
		self.dest: Tile = dest
		self.move_half = move_half
		self.army_moved: int = source.army - 1
		if self.move_half:
			self.army_moved = (source.army - 1) // 2
		self.non_friendly = self.source.player != self.dest.player

	def __gt__(self, other):
		if (other == None):
			return True
		return self.source.army - self.dest.army > other.source.army - other.dest.army
	def __lt__(self, other):
		if (other == None):
			return False
		return self.source.army - self.dest.army < other.source.army - other.dest.army
	def __eq__(self, other):
		if (None == other):
			return False
		return self.source.army - self.dest.army == other.source.army - other.dest.army
	def __str__(self):
		return self.toString()

	def toString(self):
		moveHalfString = ""
		if self.move_half:
			moveHalfString = 'z'
		return "{},{} -{}> {},{}".format(self.source.x, self.source.y, moveHalfString, self.dest.x, self.dest.y)