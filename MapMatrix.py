from __future__ import annotations

import typing
from typing import TypeVar, Generic

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


class MapMatrix(Generic[T]):
    __slots__ = ("init_val", "raw", "map")  # does slots break pickle?

    def __init__(self, map: MapBase, initVal: T = None, emptyVal: T | None | str = 'PLACEHOLDER'):
        self.init_val: T = initVal
        if emptyVal != 'PLACEHOLDER':
            self.init_val = emptyVal

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
        if self.raw[key.tile_index] != self.init_val:
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
        return defaultVal if val == self.init_val else val

    def values(self) -> typing.List[T]:
        allValues: typing.List[T] = []
        for item in self.raw:
            if item != self.init_val:
                allValues.append(item)
        return allValues

    def keys(self) -> typing.List[Tile]:
        allKeys: typing.List[Tile] = []
        for idx, item in enumerate(self.raw):
            if item != self.init_val:
                allKeys.append(self.map.get_tile_by_tile_index(idx))
        return allKeys

    def copy(self) -> MapMatrix[T]:
        """
        cost on 1v1 size map is about 0.00222ms
        @return:
        """
        myClone = MapMatrix(None)
        myClone.init_val = self.init_val
        myClone.map = self.map
        myClone.raw = self.raw.copy()

        return myClone

    def negate(self):
        for idx, val in enumerate(self.raw):
            self.raw[idx] = 0 - val

    def __delitem__(self, key: Tile):
        self.raw[key.tile_index] = self.init_val

    def __contains__(self, tile: Tile) -> bool:
        return self.raw[tile.tile_index] != self.init_val

    def __str__(self) -> str:
        return repr(self.raw)

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def get_summed(cls, matrices: typing.List[MapMatrix[float]]) -> MapMatrix[float]:
        if len(matrices) == 0:
            raise AssertionError('cant sum zero matrices')
        newMatrix = matrices[0].copy()
        if len(matrices) > 1:
            for matrix in matrices[1:]:
                for idx, val in enumerate(matrix.raw):
                    newMatrix.raw[idx] += val

        return newMatrix

    @classmethod
    def add_to_matrix(cls, matrixToModify: MapMatrix[float], matrixToAdd: MapMatrix[float]):
        for idx, val in enumerate(matrixToAdd.raw):
            matrixToModify.raw[idx] += val

    @classmethod
    def subtract_from_matrix(cls, matrixToModify: MapMatrix[float], matrixToSubtract: MapMatrix[float]):
        for idx, val in enumerate(matrixToSubtract.raw):
            matrixToModify.raw[idx] -= val


class MapMatrixSet(object):
    __slots__ = ("raw", "map")  # does slots break pickle?

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

#  Never better than Set() anymore after hashcode precompute fix
# class MapMatrixSetWithLength(object):
#     """
#     Set() is 54% slower on adds, 20% faster on accesses.
#     if > 85 adds or > 150 accesses to the set, then this is faster than normal Set() object. 200/200 on large maps.
#     """
#
#     __slots__ = ("raw", "_length", "map")  # does slots break pickle?
#
#     def __init__(self, map: MapBase):
#         self.raw: typing.List[T] = [False] * (map.cols * map.rows) if map is not None else None
#         self.map: MapBase = map
#         self._length: int = 0
#
#     def add(self, item: Tile):
#         if not self.raw[item.tile_index]:
#             self._length += 1
#             self.raw[item.tile_index] = True
#
#     def add_check(self, item: Tile) -> bool:
#         """
#         Return true if the item was added, false if the item was already in the set
#         @param item:
#         @return:
#         """
#         if not self.raw[item.tile_index]:
#             self._length += 1
#             self.raw[item.tile_index] = True
#             return True
#         return False
#
#     def __len__(self):
#         return self._length
#
#     def __setitem__(self, key: Tile, val: bool):
#         """
#         Do not use, use add instead. This is slow and just here for backcompat
#         @param key:
#         @param val:
#         @return:
#         """
#         if val:
#             self.add(key)
#         else:
#             self.discard(key)
#
#     def __getitem__(self, key: Tile) -> bool:
#         return self.raw[key.tile_index]
#
#     def __iter__(self) -> typing.Iterable[Tile]:
#         for idx, val in enumerate(self.raw):
#             if val:
#                 yield self.map.get_tile_by_tile_index(idx)
#
#     def update(self, tiles: typing.Iterable[Tile]):
#         for t in tiles:
#             self.add(t)
#
#     def copy(self) -> MapMatrixSetWithLength:
#         """
#         cost on 1v1 size map is about 0.00222ms
#         @return:
#         """
#         myClone = MapMatrixSetWithLength(None)
#         myClone.map = self.map
#         myClone.raw = self.raw.copy()
#         myClone._length = self._length
#
#         return myClone
#
#     def __delitem__(self, item: Tile):
#         if self.raw[item.tile_index]:
#             self._length -= 1
#             self.raw[item.tile_index] = False
#
#     def discard(self, item: Tile):
#         if self.raw[item.tile_index]:
#             self._length -= 1
#             self.raw[item.tile_index] = False
#
#     def discard_check(self, item: Tile) -> bool:
#         """
#         Return true if the item was removed from the set, false if the item was not in the set
#         @param item:
#         @return:
#         """
#         if self.raw[item.tile_index]:
#             self.raw[item.tile_index] = False
#             self._length -= 1
#             return True
#         return False
#
#     def __contains__(self, tile: Tile) -> bool:
#         return self.raw[tile.tile_index]
#
#     def __str__(self) -> str:
#         return repr(self.raw)
#
#     def __repr__(self) -> str:
#         return str(self)

#  Never better than Set() anymore after hashcode precompute fix
# class MapMatrixSetWithLengthAndTiles(object):
#     """
#     Normal set() is about 50% slower at adds and 30% slower at accesses.
#     Becomes better than set() at around 90 accesses + adds combined on small maps. (130 on large maps)
#     Inserts are more expensive than other mapmatrixes, but still cheaper than set().
#     """
#
#     __slots__ = ("raw", "tiles", "map")  # does slots break pickle?
#
#     def __init__(self, map: MapBase, fromIterable: typing.Iterable[Tile] | None = None):
#         self.raw: typing.List[bool] = [False] * (map.cols * map.rows) if map is not None else None
#         self.map: MapBase = map
#         self.tiles: typing.List[Tile]
#         if fromIterable:
#             if isinstance(fromIterable, set):
#                 self.tiles = [t for t in fromIterable]
#                 for t in self.tiles:
#                     self.raw[t.tile_index] = True
#             else:
#                 self.tiles = []
#                 for t in fromIterable:
#                     if not self.raw[t.tile_index]:
#                         self.raw[t.tile_index] = True
#                         self.tiles.append(t)
#         else:
#             self.tiles = []
#
#         # self.tiles: typing.Deque[Tile] = deque()
#
#     def add(self, item: Tile):
#         if not self.raw[item.tile_index]:
#             self.raw[item.tile_index] = True
#             self.tiles.append(item)
#
#     def add_check(self, item: Tile) -> bool:
#         """
#         Return true if the item was added, false if the item was already in the set
#         @param item:
#         @return:
#         """
#         if not self.raw[item.tile_index]:
#             self.raw[item.tile_index] = True
#             self.tiles.append(item)
#             return True
#         return False
#
#     def __len__(self):
#         return len(self.tiles)
#
#     def __setitem__(self, key: Tile, val: bool):
#         if val:
#             self.add(key)
#         else:
#             raise AssertionError(f'Cannot set MapMatrixSetWithLengthAndTiles to false, as this would be an O(N) operation')
#             # self.discard(key)
#
#     def __getitem__(self, key: Tile) -> bool:
#         return self.raw[key.tile_index]
#
#     def __iter__(self) -> typing.Iterable[Tile]:
#         return self.tiles
#
#     def update(self, tiles: typing.Iterable[Tile]):
#         for t in tiles:
#             self.add(t)
#
#     def copy(self) -> MapMatrixSetWithLengthAndTiles:
#         """
#         cost on 1v1 size map is about 0.00222ms
#         @return:
#         """
#         myClone = MapMatrixSetWithLengthAndTiles(None)
#         myClone.map = self.map
#         myClone.raw = self.raw.copy()
#         myClone.tiles = self.tiles.copy()
#
#         return myClone
#
#     def __delitem__(self, key: Tile):
#         raise AssertionError(f'Cannot del from this as it would be an O(N) operation.')
#         # if self.raw[key.tile_index]:
#         #     self._length -= 1
#         #     self.raw[key.tile_index] = False
#
#     def discard(self, key: Tile):
#         raise AssertionError(f'Cannot discard from this as it would be an O(N) operation.')
#         # if self.raw[key.tile_index]:
#         #     self._length -= 1
#         #     self.raw[key.tile_index] = False
#
#     def __contains__(self, tile: Tile) -> bool:
#         return self.raw[tile.tile_index]
#
#     def __str__(self) -> str:
#         return repr(self.raw)
#
#     def __repr__(self) -> str:
#         return str(self)


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
