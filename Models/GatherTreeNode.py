from __future__ import annotations

import typing
from collections import deque

import logbook

from Interfaces import MapMatrixInterface
from base.client.tile import Tile


T = typing.TypeVar('T')


class GatherTreeNode(typing.Generic[T]):
    def __init__(
            self,
            tile: Tile,
            toTile: Tile | None,
            stateObj: T = None
    ):
        self.tile: Tile = tile
        self.toTile: Tile | None = toTile
        """The singular tile that this gather tile will move TO in this gather."""
        self.toGather: GatherTreeNode | None = None
        """The singular gather node that this gather tile will move TO in this gather. For each child in xyzNode.children, each of the childrens .toGathers should be xyzNode."""

        self.value: int = 0
        """The army value gathered by this point in the tree."""
        self.points: float = 0.0
        self.trunkValue: int = 0
        """
        trunkValue is the value of the branch up to and including this node, 
        so it starts at 0 at the gather tiles and goes up as you move out along the tree.
        """

        self.trunkDistance: int = 0
        """
        How far from a root this is. Does not take into account the starting distance that 
        the actual tree search was weighted with.
        """

        self.stateObj: T = stateObj

        self.gatherTurns: int = 0

        self.children: typing.List[GatherTreeNode] = []
        """Child gather tree nodes"""
        self.pruned: typing.List[GatherTreeNode] = []
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
        if other is None:
            return False
        return self.tile == other.tile

    def __getstate__(self):
        state = self.__dict__.copy()

        if 'toGather' in state:
            del state['toGather']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        for child in self.children:
            child.toGather = self

    def deep_clone(self):
        newNode = GatherTreeNode(self.tile, self.toTile, self.stateObj)
        newNode.value = self.value
        newNode.trunkValue = self.trunkValue
        newNode.gatherTurns = self.gatherTurns
        newNode.trunkDistance = self.trunkDistance
        newNode.children = [node.deep_clone() for node in self.children]
        for child in newNode.children:
            child.toGather = newNode
        newNode.pruned = [node.deep_clone() for node in self.pruned]
        for child in newNode.pruned:
            child.toGather = newNode
        return newNode

    def populate_from_nodes(self):
        for child in self.children:
            child.toGather = self
            child.populate_from_nodes()
        for child in self.pruned:
            child.toGather = self
            child.populate_from_nodes()

    def strip_all_prunes(self):
        for c in self.children:
            c.strip_all_prunes()
        self.pruned = []

    def __str__(self):
        return f'[{str(self.tile)}->{str(self.toTile)} t{str(self.gatherTurns)} v{round(self.value, 6)} tv{round(self.trunkValue, 6)}, ch{len(self.children)}]'

    def __repr__(self):
        return str(self)

    @staticmethod
    def foreach_tree_node(
            gatherTreeNodes: typing.List[GatherTreeNode],
            forEachFunc: typing.Callable[[GatherTreeNode], None]
    ):
        i = 0
        q: typing.Deque[GatherTreeNode] = deque()
        for n in gatherTreeNodes:
            q.append(n)
        while q:
            i += 1
            cur = q.popleft()
            forEachFunc(cur)
            for c in cur.children:
                q.append(c)
            if i > 500:
                raise AssertionError(f'iterate_tree_nodes infinite looped. Nodes in the cycle: {str([str(n) for n in q])}')


    @staticmethod
    def iterate_tree_nodes(
            rootNodes: typing.List[GatherTreeNode],
    ) -> typing.Generator[GatherTreeNode, None, None]:
        i = 0
        q: typing.Deque[GatherTreeNode] = deque()
        for n in rootNodes:
            q.append(n)
        while q:
            i += 1
            cur = q.popleft()
            yield cur
            for c in cur.children:
                q.append(c)
            if i > 500:
                raise AssertionError(f'iterate_tree_nodes infinite looped. Nodes in the cycle: {str([str(n) for n in q])}')


    @staticmethod
    def iterate_tree_node(
            rootNode: GatherTreeNode,
    ) -> typing.Generator[GatherTreeNode, None, None]:
        i = 0
        q: typing.Deque[GatherTreeNode] = deque()
        q.append(rootNode)
        while q:
            i += 1
            cur = q.popleft()
            yield cur
            for c in cur.children:
                q.append(c)
            if i > 500:
                raise AssertionError(f'iterate_tree_nodes infinite looped. Nodes in the cycle: {str([str(n) for n in q])}')


    @staticmethod
    def get_tree_leaves(gathers: typing.List[GatherTreeNode]) -> typing.List[GatherTreeNode]:
        # fuck it, do it recursively i'm too tired for this
        combined = []
        for gather in gathers:
            if len(gather.children) == 0:
                if gather.toTile is not None:
                    combined.append(gather)
            else:
                combined.extend(GatherTreeNode.get_tree_leaves(gather.children))

        return combined


    @staticmethod
    def get_tree_leaves_further_than_distance(
            gatherNodes: typing.List[GatherTreeNode],
            distMap: MapMatrixInterface[int],
            dist: int,
            minArmy: int = 1,
            curArmy: int = 0
    ) -> typing.List[GatherTreeNode]:
        includeAll = False
        if minArmy > curArmy:
            includeAll = True

        leavesToInclude = []
        for n in gatherNodes:
            leaves = GatherTreeNode.get_tree_leaves([n])
            distOffs = 0
            if n.tile.isGeneral:
                distOffs = 1
            leavesGreaterThanDistance = []
            for g in leaves:
                if distMap[g.tile] >= dist - distOffs or (g.toTile and distMap[g.toTile] >= dist - distOffs):
                    leavesGreaterThanDistance.append(g)
            if includeAll:
                leavesToInclude.extend(leavesGreaterThanDistance)
                continue

            for leaf in leavesGreaterThanDistance:
                leafContribution = (leaf.tile.army - 1)
                if curArmy - leafContribution <= minArmy:
                    leavesToInclude.append(leaf)
                else:
                    curArmy -= leafContribution

        return leavesToInclude

    @staticmethod
    def clone_nodes(gatherNodes: typing.List[GatherTreeNode]) -> typing.List[GatherTreeNode]:
        return [n.deep_clone() for n in gatherNodes]