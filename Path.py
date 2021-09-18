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
import math
from DataModels import TreeNode
from collections import deque 
from queue import PriorityQueue
from pprint import pprint,pformat



class PathMove(object):
	def __init__(self, tile, next = None, prev = None, move_half = False):
		self.tile = tile
		self.next = next
		self.prev = prev
		self.move_half = move_half

	def clone(self):
		return PathMove(self.tile, self.next, self.prev)

	def __str__(self):
		return self.toString()

	def toString(self):
		prevVal = "[]"
		if self.prev is not None:
			prevVal = "[{},{}]".format(self.prev.tile.x, self.prev.tile.y)
		nextVal = "[]"
		if self.next is not None:
			nextVal = "[{},{}]".format(self.next.tile.x, self.next.tile.y)
		myVal = "[{},{}]".format(self.tile.x, self.tile.y)

		val = "(prev:{} me:{} next:{})".format(prevVal, myVal, nextVal)
		return val
	#def __gt__(self, other):
	#	if (other == None):
	#		return True
	#	return self.turn > other.turn
	#def __lt__(self, other):
	#	if (other == None):
	#		return True
	#	return self.turn < other.turn
	def __str__(self):
		return self.toString()


class Path(object):
	def __init__(self, value = 0):
		self.start = None
		self._pathQueue = deque()
		self.tail = None
		self._tileList = None
		self.value = value
	def __gt__(self, other):
		if (other == None):
			return True
		return self.length > other.length
	def __lt__(self, other):
		if (other == None):
			return True
		return self.length < other.length

	@property
	def length(self):
		return len(self._pathQueue) - 1

	@property
	def tileSet(self):
		return set(self.tileList)
	@tileSet.setter
	def tileSet(self, value):
		raise AssertionError("NO SETTING!")

	@property
	def tileList(self):
		if self._tileList == None:
			self._tileList = list()
			node = self.start
			while node is not None:
				self._tileList.append(node.tile)
				node = node.next
		return list(self._tileList)

	def add_next(self, nextTile):
		move = PathMove(nextTile)
		move.prev = self.tail
		if self.start == None:
			self.start = move
		if self.tail is not None:
			self.tail.next = move
		if self._tileList is not None:
			self._tileList.append(nextTile)
		self.tail = move
		self._pathQueue.append(move)

	def add_start(self, startTile):
		move = PathMove(startTile)
		if self.start is not None:
			move.next = self.start
			self.start.prev = move
		self.start = move
		if self._tileList is not None:
			self._tileList.insert(0, startTile)
		self._pathQueue.appendleft(move)

	def made_move(self):
		if len(self._pathQueue) == 0:
			logging.info(", bitch? Why you tryin to made_move when there aint no moves to made?")
			return
		if self._tileList is not None:
			self._tileList.remove(self.start.tile)
		self.start = self.start.next
		return self._pathQueue.popleft()

	def remove_end(self):
		if len(self._pathQueue) == 0:
			logging.info(", bitch? Removing nothing??")
			return
		if self._tileList is not None:
			self._tileList.remove(self.tail.tile)
		move = self._pathQueue.pop()
		self.tail = self.tail.prev
		if self.tail is not None:
			self.tail.next = None
		return move	
	
	def convert_to_dist_dict(self):
		dist = 0
		dict = {}
		node = self.start
		while node is not None:
			dict[node.tile] = dist
			node = node.next
			dist += 1
		return dict

	def calculate_value(self, forPlayer):
		val = 0
		node = self.start
		i = 0
		while (node is not None):
			tile = node.tile
			if tile.player == forPlayer:
				val += tile.army - 1
				if tile.isCity or tile.isGeneral:
					val += math.floor(i * 0.5)
			else:
				val -= tile.army + 1
				if tile.isCity or tile.isGeneral and tile.player != -1:
					val -= math.floor(i * 0.5)
			node = node.next
			i += 1
		self.value = val
		return val

	def clone(self):
		newPath = Path()
		node = self.start
		while node is not None:
			newPath.add_next(node.tile)
			node = node.next
		return newPath

	def get_reversed(self):
		if (self.start == None or self.start.next == None):
			return self.clone()

		newPath = Path()
		temp = self.tail
		while temp is not None:
			newPath.add_next(temp.tile)
			temp = temp.prev
		newPath.value = self.value
		return newPath
	
	# 10 things, want 3 end
	def get_subsegment(self, count, end=False):
		newPath = self.clone()
		length = len(self._pathQueue)
		i = 0
		while i < length - count:
			i += 1
			if end:
				newPath.made_move()
			else:
				newPath.remove_end()
		return newPath

	def __str__(self):
		return self.toString()

	def toString(self):
		val = "[{} len {}] ".format(self.value, self.length)
		node = self.start
		while node is not None:
			val = val + str(node.tile.x) + "," + str(node.tile.y) + " "
			node = node.next
		return val

	def convert_to_tree_nodes(self):
		curTreeNode = None
		curPathNode = self.start
		prevPathTile = None
		turn = 0
		while curPathNode is not None:
			prevTreeNode = curTreeNode
			curTreeNode = TreeNode(curPathNode.tile, prevPathTile, turn)
			curTreeNode.children.append(prevTreeNode)
			turn += 1
			prevPathTile = curPathNode.tile
			curPathNode = curPathNode.next
		return curTreeNode

	
		
	

def PathFromPathNode(pathEnd, path):
	if pathEnd == None or path == None:
		return None
	pathLength = pathEnd.turn
	value = pathEnd.value
	cityCount = path.cityCount
	pathDict = pathEnd.pathDict

	node = path
	turn = 0
	
	curVal = node.tile.army
	head = PathMove(Move(node.tile, node.parent.tile), None, node.parent.value, turn)
	
	prev = head
	node = node.parent
	while (node.parent is not None):
		turn += 1
		prev.next = PathMove(Move(node.tile, node.parent.tile), None, node.parent.value, turn)
		prev = prev.next
		node = node.parent
	
	return Path(head, pathLength, value, cityCount, pathDict)
