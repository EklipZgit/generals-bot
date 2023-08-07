'''
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
'''

from __future__ import annotations
import logging
import typing
from copy import deepcopy
import time
import json
import math
from DataModels import TreeNode, Move
from collections import deque
from queue import PriorityQueue
from pprint import pprint,pformat

from base.client.map import Tile


class PathMove(object):
    def __init__(self, tile: Tile, next: typing.Union[None, PathMove] = None, prev: typing.Union[None, PathMove] = None, move_half: bool = False):
        self.tile: Tile = tile
        self.next: typing.Union[None, PathMove] = next
        self.prev: typing.Union[None, PathMove] = prev
        self.move_half: bool = move_half

    def clone(self) -> PathMove:
        return PathMove(self.tile, self.next, self.prev)

    def toString(self) -> str:
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

    def __str__(self) -> str:
        return self.toString()

    def __repr__(self) -> str:
        return str(self)


class Path(object):
    def __init__(self, value: int = 0):
        self.start: typing.Union[None, PathMove] = None
        self._pathQueue = deque()
        self.tail: typing.Union[None, PathMove] = None
        self._tileList: typing.List[Tile] = None
        # The exact army tile number that will exist on the final tile at the end of the path run.
        # So for a path that exactly kills a tile with minimum kill army, this should be 1.
        self.value: int = value

    def __gt__(self, other) -> bool:
        if other is None:
            return True
        return self.length > other.length

    def __lt__(self, other) -> bool:
        if other is None:
            return True
        return self.length < other.length

    @property
    def length(self) -> int:
        return len(self._pathQueue) - 1

    @property
    def tileSet(self) -> typing.Set[Tile]:
        return set(self.tileList)

    @tileSet.setter
    def tileSet(self, value):
        raise AssertionError("NO SETTING!")

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = list()
            node = self.start
            while node is not None:
                self._tileList.append(node.tile)
                node = node.next
        return list(self._tileList)

    def add_next(self, nextTile):
        move = PathMove(nextTile)
        move.prev = self.tail
        if self.start is None:
            self.start = move
        if self.tail is not None:
            self.tail.next = move
        if self._tileList is not None:
            self._tileList.append(nextTile)
        self.tail = move
        self._pathQueue.append(move)

    def add_start(self, startTile: Tile):
        move = PathMove(startTile)
        if self.start is not None:
            move.next = self.start
            self.start.prev = move
        self.start = move
        if self._tileList is not None:
            self._tileList.insert(0, startTile)
        self._pathQueue.appendleft(move)

    def made_move(self) -> PathMove:
        if len(self._pathQueue) == 0:
            raise ", bitch? Why you tryin to made_move when there aint no moves to made?"

        if self._tileList is not None:
            self._tileList.remove(self.start.tile)
        self.start = self.start.next
        return self._pathQueue.popleft()

    def remove_end(self) -> PathMove:
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

    def convert_to_dist_dict(self) -> typing.Dict[Tile, int]:
        dist = 0
        dict = {}
        node = self.start
        while node is not None:
            dict[node.tile] = dist
            node = node.next
            dist += 1
        return dict

    def calculate_value(self, forPlayer: int) -> int:
        # offset the first val = val - 1
        val = 1
        node = self.start
        i = 0
        while node is not None:
            val = val - 1
            tile = node.tile
            if tile.player == forPlayer:
                val += tile.army
                if tile.isCity or tile.isGeneral:
                    val += math.floor(max(0, i - 1) * 0.5)
            else:
                val -= tile.army
                if tile.isCity or tile.isGeneral and tile.player != -1:
                    val -= math.floor(max(0, i - 1) * 0.5)
            node = node.next
            i += 1
        self.value = val
        return val

    def clone(self) -> Path:
        newPath = Path(self.value)
        node = self.start
        while node is not None:
            newPath.add_next(node.tile)
            node = node.next
        return newPath

    def get_reversed(self) -> Path:
        if self.start is None or self.start.next is None:
            return self.clone()

        newPath = Path()
        temp = self.tail
        while temp is not None:
            newPath.add_next(temp.tile)
            temp = temp.prev
        newPath.value = self.value
        return newPath

    # 10 things, want 3 end
    def get_subsegment(self, count, end=False) -> Path:
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

    def __str__(self) -> str:
        return self.toString()

    def toString(self) -> str:
        val = "[{} len {}] ".format(self.value, self.length)
        node = self.start
        while node is not None:
            val = val + str(node.tile.x) + "," + str(node.tile.y) + " "
            node = node.next
        return val

    def __repr__(self) -> str:
        return str(self)

    def convert_to_tree_nodes(self) -> TreeNode:
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
