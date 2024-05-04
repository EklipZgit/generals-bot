"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import annotations

import queue

import logbook
import typing
from DataModels import GatherTreeNode, Move
from collections import deque

from Interfaces.TilePlanInterface import TilePlanInterface
from base.client.tile import Tile
from base.client.map import MapBase


class PathMove(object):
    def __init__(self, tile: Tile, next: PathMove | None = None, prev: PathMove | None = None, move_half: bool = False):
        self.tile: Tile = tile
        self.next: PathMove | None = next
        self.prev: PathMove | None = prev
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
    #    if (other == None):
    #        return True
    #    return self.turn > other.turn
    #def __lt__(self, other):
    #    if (other == None):
    #        return True
    #    return self.turn < other.turn

    def __str__(self) -> str:
        return self.toString()

    def __repr__(self) -> str:
        return str(self)


# class PartialPathPlan(Path):


class Path(TilePlanInterface):
    __slots__ = (
        'start',
        '_pathQueue',
        'tail',
        '_tileList',
        '_tileSet',
        '_adjacentSet',
        'value',
        '_econ_value',
        '_requiredDelay',
    )

    def __init__(self, armyRemaining: float = 0):
        self.start: PathMove | None = None
        self._pathQueue: typing.Deque[PathMove] = deque()
        self.tail: PathMove | None = None
        self._tileList: typing.List[Tile] | None = None
        self._tileSet: typing.Set[Tile] | None = None
        self._adjacentSet: typing.Set[Tile] | None = None
        # The exact army tile number that will exist on the final tile at the end of the path run.
        # So for a path that exactly kills a tile with minimum kill army, this should be 1.
        self.value: float = armyRemaining
        self._econ_value: float = 0.0
        self._requiredDelay: int = 0

    # def __gt__(self, other) -> bool:
    #     if other is None:
    #         return True
    #     return self.length > other.length
    #
    # def __lt__(self, other) -> bool:
    #     if other is None:
    #         return True
    #     return self.length < other.length

    # @property
    # def value(self) -> float:
    #     return self._value
    #
    # @value.setter
    # def value(self, val: float):
    #     self._value = val

    @property
    def econValue(self) -> float:
        return self._econ_value

    @econValue.setter
    def econValue(self, val: float):
        self._econ_value = val

    @property
    def length(self) -> int:
        return max(0, len(self._pathQueue) - 1)

    @property
    def tileSet(self) -> typing.Set[Tile]:
        if self._tileSet is None:
            if self._tileList is not None:
                self._tileSet = set(self._tileList)
            else:
                self._tileSet = set()
                for t in self._pathQueue:
                    self._tileSet.add(t.tile)

        return self._tileSet

    @tileSet.setter
    def tileSet(self, value):
        raise AssertionError("NO SETTING!")

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = [t.tile for t in self._pathQueue]
        return self._tileList

    @property
    def adjacentSet(self) -> typing.Set[Tile]:
        """Includes the tileSet itself, too."""
        if self._adjacentSet is None:
            self._adjacentSet = set()
            for t in self._pathQueue:
                self._adjacentSet.update(t.tile.adjacents)

        return self._adjacentSet

    @property
    def requiredDelay(self) -> int:
        return self._requiredDelay

    @requiredDelay.setter
    def requiredDelay(self, val: int):
        self._requiredDelay = val

    def get_move_list(self) -> typing.List[Move]:
        moves = []
        node = self.start
        while node.next is not None:
            moves.append(Move(node.tile, node.next.tile, node.move_half))
            node = node.next

        return moves

    def add_next(self, nextTile, move_half=False):
        move = PathMove(nextTile)
        move.prev = self.tail
        if self.start is None:
            self.start = move
        if self.tail is not None:
            self.tail.next = move
            self.tail.move_half = move_half
        if self._tileList is not None:
            self._tileList.append(nextTile)
        if self._tileSet is not None:
            self._tileSet.add(nextTile)
        if self._adjacentSet is not None:
            self._adjacentSet.update(nextTile.adjacents)
        self.tail = move
        self._pathQueue.append(move)

    def add_start(self, startTile: Tile):
        move = PathMove(startTile)
        if self.start is not None:
            move.next = self.start
            self.start.prev = move
        else:
            self.tail = move
        self.start = move
        if self._tileList is not None:
            self._tileList.insert(0, startTile)
        if self._tileSet is not None:
            self._tileSet.add(startTile)
        if self._adjacentSet is not None:
            self._adjacentSet.update(startTile.adjacents)
        self._pathQueue.appendleft(move)

    def remove_start(self) -> PathMove:
        if len(self._pathQueue) == 0:
            raise ", bitch? Why you tryin to remove_start when there aint no moves to made?"

        self._tileSet = None
        self._tileList = None
        self._adjacentSet = None
        self.start = self.start.next
        return self._pathQueue.popleft()

    def get_first_move(self) -> Move:
        if len(self._pathQueue) <= 1:
            raise queue.Empty(f", bitch? Path length {len(self._pathQueue)}: Why you tryin to get_first_move when there aint no moves to made?")

        move = Move(self.start.tile, self.start.next.tile, self.start.move_half)
        return move

    def pop_first_move(self) -> Move:
        move = self.get_first_move()
        self._tileSet = None
        self._tileList = None
        self._adjacentSet = None
        self.start = self.start.next
        self._pathQueue.popleft()
        return move

    def remove_end(self) -> PathMove | None:
        if len(self._pathQueue) == 0:
            logbook.info(", bitch? Removing nothing??")
            return None
        self._tileSet = None
        self._tileList = None
        self._adjacentSet = None
        move = self._pathQueue.pop()
        self.tail = self.tail.prev
        if self.tail is not None:
            self.tail.next = None
        return move

    def convert_to_dist_dict(self, offset: int = 0) -> typing.Dict[Tile, int]:
        """
        returns a dict[Tile, int] starting at offset(emptyVal 0) for path.start and working up from there.
        @param offset:
        @return:
        """
        dist = offset
        dict = {}
        node = self.start
        while node is not None:
            dict[node.tile] = dist
            node = node.next
            dist += 1
        return dict

    def calculate_value(
            self,
            forPlayer: int,
            teams: typing.List[int],
            negativeTiles: None | typing.Set[Tile] | typing.Dict[Tile, typing.Any] = None,
            ignoreNonPlayerArmy: bool = False,
            ignoreIncrement: bool = False,
            incrementBackwards: bool = False,
            doNotSaveToPath: bool = False
    ) -> int:
        # have to offset the first [val - 1] I guess since the first tile didn't get moved to
        val = 1
        node = self.start
        i = 0
        while node is not None:
            tile = node.tile
            if negativeTiles is None or tile not in negativeTiles:
                if tile.player != -1 and teams[tile.player] == teams[forPlayer]:
                    val += tile.army
                    if (tile.isCity or tile.isGeneral) and not ignoreIncrement:
                        incVal = (i - 1)
                        if incrementBackwards:
                            incVal = self.length - incVal
                        val += incVal // 2
                elif not ignoreNonPlayerArmy:
                    val -= tile.army
                    if (tile.isCity or tile.isGeneral) and tile.player != -1 and not ignoreIncrement:
                        incVal = (i - 1)
                        if incrementBackwards:
                            incVal = self.length - incVal
                        val -= incVal // 2

            if not node.move_half:
                val = val - 1
            else:
                val = (val + 1) // 2

            node = node.next
            i += 1

        if not doNotSaveToPath:
            self.value = val

        return val

    def get_positive_subsegment(
            self,
            forPlayer: int,
            teams: typing.List[int],
            negativeTiles: None | typing.Set[Tile] | typing.Dict[Tile, typing.Any] = None,
            ignoreIncrement: bool = False
    ) -> Path | None:
        # have to offset the first [val - 1] I guess since the first tile didn't get moved to
        val = 1
        node = self.start
        i = 0
        while node is not None:
            tile = node.tile
            oldVal = val
            if negativeTiles is None or tile not in negativeTiles:
                if tile.player != -1 and teams[tile.player] == teams[forPlayer]:
                    val += tile.army
                    if (tile.isCity or tile.isGeneral) and not ignoreIncrement:
                        incVal = (i - 1)
                        val += incVal // 2
                else:
                    val -= tile.army
                    if (tile.isCity or tile.isGeneral) and tile.player != -1 and not ignoreIncrement:
                        incVal = (i - 1)
                        val -= incVal // 2

            if not node.move_half:
                val = val - 1
            else:
                val = (val + 1) // 2

            if val <= 0:
                val = oldVal
                break

            node = node.next
            i += 1

        sub = self.get_subsegment(i - 1)
        sub.value = val
        return sub

    def clone(self) -> Path:
        newPath = Path(self.value)
        node = self.start
        while node is not None:
            newPath.add_next(node.tile)
            node = node.next

        newPath._requiredDelay = self._requiredDelay
        newPath._econ_value = self._econ_value

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
        newPath._econ_value = self._econ_value

        return newPath

    def get_subsegment(self, count: int, end: bool = False) -> Path:
        """
        The subsegment path will be count moves long, count+1 TILES long
        @param count:
        @param end: If True, get the subsegment of the LAST {count} moves instead of FIRST {count} moves
        @return:
        """
        newPath = self.clone()
        i = 0

        if end:
            while i < self.length - count:
                i += 1
                newPath.start = newPath.start.next
                newPath._pathQueue.popleft()
        else:
            while i < self.length - count:
                i += 1
                newPath._pathQueue.pop()
                newPath.tail = newPath.tail.prev
                if newPath.tail is not None:
                    newPath.tail.next = None

        return newPath

    def __str__(self) -> str:
        node = self.start
        nodeStrs = []
        half = False
        while node is not None:
            nodeStrs.append(f'{node.tile.x},{node.tile.y}{"" if not half else "z"}')
            half = node.move_half
            node = node.next
        valStr = ''
        if self._econ_value != 0.0:
            valStr = f' {self._econ_value:.2f}v'
        return f"[{self.value}a{valStr} {self.length}t] {' -> '.join(nodeStrs)}"

    def toString(self) -> str:
        return str(self)

    def to_move_string(self):
        node = self.start
        nodeStrs = []
        half = False
        while node is not None:
            nodeStrs.append(f'{node.tile.x},{node.tile.y}{"" if not half else "z"}')
            half = node.move_half
            node = node.next
        return '->'.join(nodeStrs)

    def __repr__(self) -> str:
        return str(self)

    def convert_to_tree_nodes(self, map: MapBase, forPlayer: int) -> GatherTreeNode:
        curGatherTreeNode = None
        curPathNode = self.start
        prevPathTile = None
        turn = 0
        value = 0
        while curPathNode is not None:
            prevGatherTreeNode = curGatherTreeNode
            t = curPathNode.tile
            curGatherTreeNode = GatherTreeNode(t, prevPathTile)
            if prevGatherTreeNode is not None:
                curGatherTreeNode.children.append(prevGatherTreeNode)

            if map.is_tile_on_team_with(t, forPlayer):
                value += t.army
            else:
                value -= t.army
            value -= 1

            curGatherTreeNode.gatherTurns = turn
            curGatherTreeNode.value = value

            turn += 1
            prevPathTile = t
            curPathNode = curPathNode.next

        return curGatherTreeNode

    def break_overflow_into_one_move_path_subsegments(self, lengthToKeepInOnePath: int = 1) -> typing.List[typing.Union[Path, None]]:
        """
        Takes a path and gets a lengthToKeepInOnePath subsegment, PLUS the rest of the path as single-move subsegments. Useful when you need to interrupt a paths execution with other moves after a certain time.
        @param lengthToKeepInOnePath:
        @return:
        """
        if lengthToKeepInOnePath >= self.length:
            copy = self.clone()
            segments = [copy]
            # # can never happen in first 25 but may need to pad with Nones to keep it the original length...?
            # for _ in range(self.length, lengthToKeepInOnePath):
            #     segments.append(None)
            return segments

        # break the new path up into multiple segments, replacing the None's
        firstSegment = self.get_subsegment(lengthToKeepInOnePath)
        segments = [firstSegment]

        newCopyEnd = self.get_subsegment(self.length - lengthToKeepInOnePath, end=True)
        for i in range(newCopyEnd.length):
            segments.append(newCopyEnd.get_subsegment(1))
            newCopyEnd = newCopyEnd.get_subsegment(newCopyEnd.length - 1, end=True)

        return segments

    def convert_to_move_list(self) -> typing.List[Move]:
        moves = []
        node = self.start
        while node.next is not None:
            moves.append(Move(node.tile, node.next.tile, node.move_half))
            node = node.next

        return moves

    @classmethod
    def from_string(cls, map: MapBase, pathStr: str) -> Path:
        moves = pathStr.split('->')
        prevTile: Tile | None = None
        path = Path()
        for move_str in moves:
            xStr, yStr = move_str.strip().split(',')
            moveHalf = False
            if yStr.strip().endswith('z'):
                moveHalf = True
                yStr = yStr.strip('z ')

            nextTile = map.GetTile(int(xStr), int(yStr))

            if prevTile is None:
                path.add_next(nextTile)
                prevTile = nextTile
                continue

            if prevTile.x != nextTile.x and prevTile.y != nextTile.y:
                raise AssertionError(f'Cannot jump diagonally between {str(prevTile)} and {str(nextTile)}')

            xInc = nextTile.x - prevTile.x
            if xInc < 0:
                xInc = -1
            elif xInc > 0:
                xInc = 1

            yInc = nextTile.y - prevTile.y
            if yInc < 0:
                yInc = -1
            elif yInc > 0:
                yInc = 1

            while prevTile.x != nextTile.x or prevTile.y != nextTile.y:
                currentTile = map.GetTile(prevTile.x + xInc, prevTile.y + yInc)
                path.add_next(currentTile, moveHalf)
                prevTile = currentTile
                moveHalf = False

        path.calculate_value(forPlayer=path.start.tile.player, teams=map._teams)

        return path

    def get_subsegment_excluding_trailing_visible(self) -> Path:
        """
        Gets a subsegment of the path with visible tiles pruned from the end.
        Does NOT modify the
        @return:
        """
        path = self.clone()
        while path.tail.tile.visible and path.length > 1:
            path.remove_end()

        if path.tail.tile.visible:
            logbook.warn(f'couldn\'t successfully get_subsegment_excluding_trailing_visible because even the first move in the path was visible. Returning the length 1 subsegment: {path}')

        return path


class MoveListPath(Path):
    # noinspection PyMissingConstructor
    def __init__(self, moves: typing.List[Move | None]):
        self.start: PathMove | None = None
        self._pathQueue: typing.Deque[Move | None] = deque()

        self.tail: PathMove | None = None
        self._tileList: typing.List[Tile] | None = None
        self._tileSet: typing.Set[Tile] | None = None
        self._adjacentSet: typing.Set[Tile] | None = None
        # The exact army tile number that will exist on the final tile at the end of the path run.
        # So for a path that exactly kills a tile with minimum kill army, this should be 1.
        self.value: float = 0.0
        self._econ_value: float = 0.0
        self._requiredDelay: int = 0

        if moves:
            for move in moves:
                self.add_next_move(move)

    @property
    def econValue(self) -> float:
        return self._econ_value

    @econValue.setter
    def econValue(self, val: float):
        self._econ_value = val

    @property
    def length(self) -> int:
        return max(0, len(self._pathQueue))

    @property
    def tileSet(self) -> typing.Set[Tile]:
        if self._tileSet is None:
            if self._tileList is not None:
                self._tileSet = set(self._tileList)
            else:
                self._tileSet = set()
                for t in self._pathQueue:
                    if t:
                        self._tileSet.add(t.source)
                        self._tileSet.add(t.dest)

        return self._tileSet

    @tileSet.setter
    def tileSet(self, value):
        raise AssertionError("NO SETTING!")

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = []
            lastDest = None
            for move in self._pathQueue:
                if move:
                    if move.source != lastDest:
                        self._tileList.append(move.source)
                    self._tileList.append(move.dest)
                    lastDest = move.dest
                else:
                    lastDest = None
        return self._tileList

    @property
    def adjacentSet(self) -> typing.Set[Tile]:
        """Includes the tileSet itself, too."""
        if self._adjacentSet is None:
            self._adjacentSet = set()
            for t in self.tileList:
                self._adjacentSet.update(t.adjacents)

        return self._adjacentSet

    @property
    def requiredDelay(self) -> int:
        return self._requiredDelay

    @requiredDelay.setter
    def requiredDelay(self, val: int):
        self._requiredDelay = val

    def get_move_list(self) -> typing.List[Move]:
        return list(self._pathQueue)

    def add_next(self, nextTile, move_half=False):
        move = PathMove(nextTile)
        prev = self.tail
        move.prev = self.tail
        if self.start is None:
            self.start = move
        if self.tail is not None:
            self.tail.next = move
            self.tail.move_half = move_half
        if self._tileList is not None:
            self._tileList.append(nextTile)
        if self._tileSet is not None:
            self._tileSet.add(nextTile)
        if self._adjacentSet is not None:
            self._adjacentSet.update(nextTile.adjacents)
        self.tail = move
        if prev is not None:
            self._pathQueue.append(Move(prev.tile, nextTile, move_half))

    def add_next_move(self, move: Move | None):
        if move is None:
            self._pathQueue.append(move)
            return

        if not self.tail:
            self.add_next(move.source)

        if self.tail.tile == move.source:
            self.add_next(move.dest, move.move_half)
            return

        sourcePm = PathMove(move.source)
        sourcePm.prev = self.tail
        self.tail.next = sourcePm
        destPm = PathMove(move.dest, move_half=move.move_half)
        destPm.prev = sourcePm
        sourcePm.next = destPm

        if self._tileList is not None:
            self._tileList.append(move.source)
            self._tileList.append(move.dest)
        if self._tileSet is not None:
            self._tileSet.add(move.source)
            self._tileSet.add(move.dest)
        if self._adjacentSet is not None:
            self._adjacentSet.update(move.source.adjacents)
            self._adjacentSet.update(move.dest.adjacents)

        self.tail = destPm

        self._pathQueue.append(move)

    def add_start(self, startTile: Tile):
        move = PathMove(startTile)
        nextNode = self.start
        if self.start is not None:
            move.next = self.start
            self.start.prev = move
        else:
            self.tail = move
        self.start = move
        if self._tileList is not None:
            self._tileList.insert(0, startTile)
        if self._tileSet is not None:
            self._tileSet.add(startTile)
        if self._adjacentSet is not None:
            self._adjacentSet.update(startTile.adjacents)
        if nextNode:
            self._pathQueue.appendleft(Move(startTile, nextNode.tile))

    def remove_start(self) -> PathMove:
        pm, move = self._remove_start()
        return pm

    def _remove_start(self) -> typing.Tuple[PathMove, Move]:
        if len(self._pathQueue) == 0:
            raise ", bitch? Why you tryin to remove_start when there aint no moves to made?"

        self._tileSet = None
        self._tileList = None
        self._adjacentSet = None
        toRet = self.start
        self.start = self.start.next
        move = self._pathQueue.popleft()
        if self.start and self._pathQueue and self._pathQueue[0] and self._pathQueue[0].source != self.start.tile:
            self.start = self.start.next
        # this wasn't / isn't here in main path impl
        if self.start is not None:
            self.start.prev = None
        return toRet, move

    def get_first_move(self) -> Move:
        if len(self._pathQueue) <= 0:
            raise queue.Empty(f", bitch? Path length {len(self._pathQueue)}: Why you tryin to get_first_move when there aint no moves to made?")

        return self._pathQueue[0]

    def pop_first_move(self) -> Move:
        pm, move = self._remove_start()
        return move

    def _remove_end(self) -> typing.Tuple[PathMove | None, Move | None]:
        if len(self._pathQueue) == 0:
            logbook.info(", bitch? Removing nothing??")
            return None, None
        self._tileSet = None
        self._tileList = None
        self._adjacentSet = None
        oldTail = self.tail
        self.tail = self.tail.prev
        move = self._pathQueue.pop()
        if self.tail and self._pathQueue and self._pathQueue[-1].dest != self.tail.tile:
            self.tail = self.tail.prev
        if self.tail:
            self.tail.next = None
        return oldTail, move

    def remove_end(self) -> PathMove | None:
        pm, move = self._remove_end()
        return pm

    def remove_end_move(self) -> Move | None:
        pm, move = self._remove_end()
        return move

    def calculate_value(
            self,
            forPlayer: int,
            teams: typing.List[int],
            negativeTiles: None | typing.Set[Tile] | typing.Dict[Tile, typing.Any] = None,
            ignoreNonPlayerArmy: bool = False,
            ignoreIncrement: bool = False,
            incrementBackwards: bool = False,
            doNotSaveToPath: bool = False
    ) -> int:
        # have to offset the first [val - 1] I guess since the first tile didn't get moved to
        val = 1
        node = self.start
        i = 0
        while node is not None:
            tile = node.tile
            if negativeTiles is None or tile not in negativeTiles:
                if tile.player != -1 and teams[tile.player] == teams[forPlayer]:
                    val += tile.army
                    if (tile.isCity or tile.isGeneral) and not ignoreIncrement:
                        incVal = (i - 1)
                        if incrementBackwards:
                            incVal = self.length - incVal
                        val += incVal // 2
                elif not ignoreNonPlayerArmy:
                    val -= tile.army
                    if (tile.isCity or tile.isGeneral) and tile.player != -1 and not ignoreIncrement:
                        incVal = (i - 1)
                        if incrementBackwards:
                            incVal = self.length - incVal
                        val -= incVal // 2

            if not node.move_half:
                val = val - 1
            else:
                val = (val + 1) // 2

            node = node.next
            i += 1

        if not doNotSaveToPath:
            self.value = val

        return val

    def clone(self) -> MoveListPath:
        newPath = MoveListPath(self.get_move_list())

        newPath._requiredDelay = self._requiredDelay
        newPath._econ_value = self._econ_value
        newPath.value = self.value

        return newPath
