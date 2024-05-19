from __future__ import annotations

import typing
from typing import TypeVar

from Interfaces import MapMatrixInterface, TileSet
from base.client.map import Tile, MapBase

T = TypeVar('T')

"""
Matrix perf summary:               overall     better after?    Performance diff access vs add
MapMatrix (vs dict.get(,default))  Dict()-40%  70-110 accesses  (45% access, 20% add)
MapMatrix (vs dict[])              Dict()-20%  170 accesses     (20% access, 7% add)
MapMatrix (direct vs get)          Dict()-110% 25-40 accesses   (88% access, 220% add)
MapMatrix (direct vs dict[])       Dict()-90%  40-60 accesses   (53% access, 220% add)

MapMatrixSet                       Set()~0%    70-85 adds       (-10% access, 30% add)
MapMatrixSet (direct access)       Set()-70%   30-50 accesses   (62% access, 200% add)

TLDR
now with fixed hashcode, Set() performs very well. Direct access mapmatrixset is still a good choice in high perf situations.
Dict() performs better when making lots of copies. Matrix is better than dict when using dict get()
Matrix direct access has much higher add performance than dict for lots of adds.
Matrix.get() performs poorly and should be avoided where possible unless a default is NEEDED.
If you need to iterate the tiles in smaller sets, always use Set(). 
TODO not actually benched yet. ^
"""


class MapMatrix(MapMatrixInterface[T]):
    __slots__ = ("empty_val", "raw", "map")

    def __init__(self, map: MapBase, initVal: T = None, emptyVal: T | None | str = 'PLACEHOLDER'):
        self.empty_val: T = initVal
        if emptyVal != 'PLACEHOLDER':
            self.empty_val = emptyVal

        self.raw: typing.List[T] = [initVal] * (map.cols * map.rows) if map is not None else None
        self.map: MapBase = map

    def add(self, item: Tile, value: T = True):
        self.raw[item.tile_index] = value

    def add_if_not_in(self, key: Tile, value: T = True) -> bool:
        """
        Returns true if there was not already an existing value and the value was set. Returns false if it already had a value and nothing was updated.

        @param key:
        @param value:
        @return:
        """
        if self.raw[key.tile_index] != self.empty_val:
            self.raw[key.tile_index] = value
            return True
        return False

    def __setitem__(self, key: Tile, item: T):
        self.raw[key.tile_index] = item

    def __getitem__(self, key: Tile) -> T:
        return self.raw[key.tile_index]

    def get(self, key: Tile, defaultVal: T | None = None) -> T | None:
        """Note because of the default val check, this is (substantially) slower than getitem indexing."""
        val = self.raw[key.tile_index]
        return defaultVal if val == self.empty_val else val

    def values(self) -> typing.List[T]:
        allValues: typing.List[T] = []
        for item in self.raw:
            if item != self.empty_val:
                allValues.append(item)
        return allValues

    def keys(self) -> typing.List[Tile]:
        allKeys: typing.List[Tile] = []
        for idx, item in enumerate(self.raw):
            if item != self.empty_val:
                allKeys.append(self.map.get_tile_by_tile_index(idx))
        return allKeys

    def copy(self) -> MapMatrixInterface[T]:
        """
        cost on 1v1 size map is about 0.00222ms
        @return:
        """
        myClone = MapMatrix(None)
        myClone.empty_val = self.empty_val
        myClone.map = self.map
        myClone.raw = self.raw.copy()

        return myClone

    def negate_in_place(self):
        for idx, val in enumerate(self.raw):
            self.raw[idx] = 0 - val

    def copy_negated(self) -> MapMatrix[T]:
        copy = MapMatrix(None)
        copy.raw = [0 - val for val in self.raw]
        copy.map = self.map
        copy.empty_val = self.empty_val
        return copy

    def __delitem__(self, key: Tile):
        self.raw[key.tile_index] = self.empty_val

    def __contains__(self, tile: Tile) -> bool:
        return self.raw[tile.tile_index] != self.empty_val

    def discard(self, key: Tile):
        self.raw[key.tile_index] = self.empty_val

    def __str__(self) -> str:
        return repr(self.raw)

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def get_summed(cls, matrices: typing.List[MapMatrixInterface[float]]) -> MapMatrixInterface[float]:
        if len(matrices) == 0:
            raise AssertionError('cant sum zero matrices')
        newMatrix = matrices[0].copy()
        if len(matrices) > 1:
            for matrix in matrices[1:]:
                for idx, val in enumerate(matrix.raw):
                    newMatrix.raw[idx] += val

        return newMatrix

    @classmethod
    def add_to_matrix(cls, matrixToModify: MapMatrixInterface[float], matrixToAdd: MapMatrixInterface[float]):
        for idx, val in enumerate(matrixToAdd.raw):
            matrixToModify.raw[idx] += val

    @classmethod
    def subtract_from_matrix(cls, matrixToModify: MapMatrixInterface[float], matrixToSubtract: MapMatrixInterface[float]):
        for idx, val in enumerate(matrixToSubtract.raw):
            matrixToModify.raw[idx] -= val


class MapMatrixSet(object):
    __slots__ = ("raw", "map")

    def __init__(self, map: MapBase, fromIterable: typing.Iterable[Tile] | None = None):
        # if fromIterable is None or len(fromIterable) < 100:
        self.raw: typing.List[T] = [False] * (map.cols * map.rows) if map is not None else None
        self.map: MapBase = map
        if fromIterable is not None:
            for t in fromIterable:
                self.raw[t.tile_index] = True

    def add(self, item: Tile):
        self.raw[item.tile_index] = True

    def add_check(self, item: Tile) -> bool:
        """
        Return true if the item was added, false if the item was already in the set
        @param item:
        @return:
        """
        if not self.raw[item.tile_index]:
            self.raw[item.tile_index] = True
            return True
        return False

    def __getitem__(self, key: Tile) -> bool:
        return self.raw[key.tile_index]

    def __iter__(self) -> typing.Iterable[Tile]:
        for idx, item in enumerate(self.raw):
            if item:
                yield self.map.get_tile_by_tile_index(idx)

    def update(self, tiles: typing.Iterable[Tile]):
        for t in tiles:
            self.raw[t.tile_index] = True

    def copy(self) -> MapMatrixSet:
        """
        cost on 1v1 size map is about 0.00222ms
        @return:
        """
        myClone = MapMatrixSet(None)
        myClone.map = self.map
        myClone.raw = self.raw.copy()

        return myClone

    def __delitem__(self, key: Tile):
        self.raw[key.tile_index] = False

    def discard(self, key: Tile):
        self.raw[key.tile_index] = False

    def discard_check(self, item: Tile) -> bool:
        """
        Return true if the item was removed from the set, false if the item was not in the set
        @param item:
        @return:
        """
        if self.raw[item.tile_index]:
            self.raw[item.tile_index] = False
            return True
        return False

    def __contains__(self, tile: Tile) -> bool:
        return self.raw[tile.tile_index]

    def __str__(self) -> str:
        return ' | '.join([str(t) for t in self.map.get_all_tiles() if self.raw[t.tile_index]])

    def __repr__(self) -> str:
        return str(self)
