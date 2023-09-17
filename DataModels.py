"""
	@ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
	April 2017
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	EklipZ bot - Tries to play generals lol
"""

import typing

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
        if other is None:
            return True
        return self.turn > other.turn

    def __lt__(self, other):
        if other is None:
            return True
        return self.turn < other.turn

    def __str__(self):
        return f'{str(self.parent) if self.parent is not None else ""} -> {str(self.tile)}'

    def __repr__(self):
        return str(self)


def get_tile_list_from_path(pathObject):
    path = pathObject.start
    if path is None:
        return None
    pathList = []
    while path is not None:
        pathList.append(path.tile)
        path = path.next
    return pathList


def get_tile_set_from_path(pathObject):
    return pathObject.tileSet


def reverse_path(path):
    newPath = path.get_reversed()
    return newPath


def get_player_army_amount_on_path(path, player, startIdx=0, endIdx=1000):
    value = 0
    idx = 0
    pathNode = path.start
    while pathNode is not None:
        if pathNode.tile.player == player and idx >= startIdx and idx <= endIdx:
            value += (pathNode.tile.army - 1)
        pathNode = pathNode.next
        idx += 1
    return value


class TreeNode(object):
    def __init__(self, tile: Tile, fromTile: Tile | None, turn: int):
        self.tile: Tile = tile
        self.fromTile: Tile | None = fromTile
        self.value: int = 0
        self.trunkValue: int = 0
        """
        trunkValue is the value of the branch up to and including this node, 
        so it starts at 0 at the gather targets and goes up as you move out along the tree.
        """

        self.trunkDistance: int = 0
        """
        How far from a root this is. Does not take into account the starting distance that 
        the actual tree search was weighted with.
        """

        self.turn: int = turn
        self.gatherTurns: int = 0
        self.neutrals: int = 0
        self.children: typing.List[TreeNode] = []
        """Child gather tree nodes"""
        self.pruned: typing.List[TreeNode] = []
        """Children that have been pruned from the actual gather"""

    def __gt__(self, other):
        if other is None:
            return True
        return self.value > other.value

    def __lt__(self, other):
        if other is None:
            return False
        return self.value < other.value

    def __eq__(self, other):
        if None == other:
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

    def strip_all_prunes(self):
        for c in self.children:
            c.strip_all_prunes()
        self.pruned = []

    def __str__(self):
        return f'[{str(self.tile)}<-{str(self.fromTile)} t{str(self.gatherTurns)} v{self.value} tv{self.trunkValue}, ch{len(self.children)}]'

    def __repr__(self):
        return str(self)


class Move(object):
    def __init__(self, source: Tile, dest: Tile, move_half=False):
        self.source: Tile = source
        self.dest: Tile = dest
        self.move_half = move_half
        self.army_moved: int = source.army - 1
        if self.move_half:
            self.army_moved = (source.army - 1) // 2
        self.non_friendly = self.source.player != self.dest.player

    def __gt__(self, other):
        if other is None:
            return True
        return self.source.army - self.dest.army > other.source.army - other.dest.army

    def __lt__(self, other):
        if other is None:
            return False
        return self.source.army - self.dest.army < other.source.army - other.dest.army

    def __str__(self):
        return self.toString()

    def __repr__(self):
        return self.toString()

    def __hash__(self):
        return hash((self.source.x, self.source.y, self.dest.x, self.dest.y, self.move_half))

    def __eq__(self, other):
        if isinstance(other, Move):
            return self.source.x == other.source.x and self.source.y == other.source.y and self.dest.x == other.dest.x and self.dest.y and self.move_half == other.move_half

        return False

    def toString(self):
        moveHalfString = ""
        if self.move_half:
            moveHalfString = 'z'
        return "{},{} -{}> {},{}".format(self.source.x, self.source.y, moveHalfString, self.dest.x, self.dest.y)
