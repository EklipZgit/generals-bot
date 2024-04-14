import typing

from abc import ABC, abstractmethod
from DataModels import Move
from base.client.map import Tile


T = typing.TypeVar('T', bound='Parent')  # use string


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

    @abstractmethod
    def get_move_list(self) -> typing.List[Move]:
        """Does not need to be cached, can be generated on the fly. Must have at least 1 move in it. Does NOT need to have as many moves in it as there is length (the length may imply inferred other moves that are not yet calculated)."""
        raise NotImplementedError()

    def __gt__(self, other) -> bool:
        if other is None:
            return True
        return self.econValue > other.econ_value

    def __lt__(self, other) -> bool:
        if other is None:
            return True
        return self.econValue < other.econValue