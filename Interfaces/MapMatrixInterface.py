from __future__ import annotations

import typing

from base.client.tile import Tile

T = typing.TypeVar('T')


class MapMatrixInterface(typing.Generic[T]):
    raw: typing.List[T]

    def add(self, item: Tile, value: T = True):
        pass

    def add_if_not_in(self, key: Tile, value: T = True) -> bool:
        pass

    def __setitem__(self, key: Tile, item: T):
        pass

    def __getitem__(self, key: Tile) -> T:
        pass

    def get(self, key: Tile, defaultVal: T | None = None) -> T | None:
        pass

    def values(self) -> typing.List[T]:
        pass

    def keys(self) -> typing.List[Tile]:
        pass

    def copy(self) -> MapMatrixInterface[T]:
        pass

    def negate(self):
        pass

    def __delitem__(self, key: Tile):
        pass

    def __contains__(self, tile: Tile) -> bool:
        pass

    def discard(self, key: Tile):
        pass


class MetaTileSet(typing.Protocol):

    def add(self, item: Tile):
        pass

    def __getitem__(self, key: Tile) -> bool:
        pass

    def __iter__(self) -> typing.Iterable[Tile]:
        pass

    def update(self, tiles: typing.Iterable[Tile]):
        pass

    def copy(self) -> MetaTileSet:
        pass

    def __delitem__(self, key: Tile):
        pass

    def discard(self, key: Tile):
        pass

    def __contains__(self, tile: Tile) -> bool:
        pass

    def __str__(self) -> str:
        pass

    def __repr__(self) -> str:
        pass


TileSet = typing.Union[MetaTileSet | typing.Set[Tile]]