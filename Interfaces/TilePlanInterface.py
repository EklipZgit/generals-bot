import typing

from DataModels import Move
from base.client.map import Tile


class TilePlanInterface(object):
    length: int

    value: float

    tileSet: typing.Set[Tile]

    requiredDelay: int

    def get_first_move(self) -> Move:
        raise NotImplementedError()

    def pop_first_move(self) -> Move:
        """Should update the length, value, and tileset."""
        raise NotImplementedError()