import typing

from abc import ABC, abstractmethod
from DataModels import Move
from base.client.map import Tile


class TilePlanInterface(ABC):
    @property
    @abstractmethod
    def length(self) -> int:
        raise NotImplementedError()

    @property
    @abstractmethod
    def value(self) -> float:
        raise NotImplementedError()

    @property
    @abstractmethod
    def tileSet(self) -> typing.Set[Tile]:
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

    def __gt__(self, other) -> bool:
        if other is None:
            return True
        return self.value > other.value

    def __lt__(self, other) -> bool:
        if other is None:
            return True
        return self.value < other.value