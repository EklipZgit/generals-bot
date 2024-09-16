from __future__ import annotations
import typing

from abc import ABC, abstractmethod
from Models import Move
from base.client.tile import Tile


T = typing.TypeVar('T', bound='Parent')  # use string


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
            prevVal = f"[{self.prev.tile.x},{self.prev.tile.y}]"
        nextVal = "[]"
        if self.next is not None:
            nextVal = f"[{self.next.tile.x},{self.next.tile.y}]"
        myVal = f"[{self.tile.x},{self.tile.y}]"

        val = f"(prev:{prevVal} me:{myVal} next:{nextVal})"
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


class TilePlanInterface(ABC):
    @property
    @abstractmethod
    def length(self) -> int:
        raise NotImplementedError()

    @property
    @abstractmethod
    def econValue(self) -> float:
        raise NotImplementedError()

    @property
    @abstractmethod
    def tileSet(self) -> typing.Set[Tile]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def tileList(self) -> typing.List[Tile]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def requiredDelay(self) -> int:
        raise NotImplementedError()

    @abstractmethod
    def get_first_move(self) -> Move:
        raise NotImplementedError()

    @abstractmethod
    def pop_first_move(self) -> Move:
        """Should update the length, value, and tileset."""
        raise NotImplementedError()

    @abstractmethod
    def clone(self: typing.Self) -> typing.Self:
        """should be a deep clone of the original"""
        raise NotImplementedError()

    @property
    def tail(self) -> PathMove | None:
        moves = self.get_move_list()
        if not moves:
            return None
        lastMove = moves[-1]
        return PathMove(lastMove.source, PathMove(lastMove.dest, None), move_half=lastMove.move_half)

    @property
    def start(self) -> PathMove | None:
        firstMove = self.get_first_move()
        if firstMove is None:
            return None
        return PathMove(firstMove.source, PathMove(firstMove.dest, None), move_half=firstMove.move_half)

    @abstractmethod
    def get_move_list(self) -> typing.List[Move | None]:
        """
        Should NOT be cached, SHOULD be generated on the fly (or if cached, return a copy of the list that can be safely modified).
        Must have at least 1 move in it.
        Does NOT need to have as many moves in it as there is length (the length may imply inferred other moves that are not yet calculated).
        Can return 'none' move waiting moves, in which case we need a mechanism to intersperse other move opts in the middle sometimes?
        """
        raise NotImplementedError()

    def __gt__(self, other) -> bool:
        if other is None:
            return True
        if self.econValue == other.econValue:
            return self.length > other.length
        return self.econValue > other.econValue

    def __lt__(self, other) -> bool:
        if other is None:
            return False
        if self.econValue == other.econValue:
            return self.length < other.length
        return self.econValue < other.econValue
