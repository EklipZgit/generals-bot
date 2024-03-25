from __future__ import annotations

import typing
from typing import TypeVar, Generic

from base.client.map import Tile, MapBase, new_value_grid

T = TypeVar('T')


class MapMatrix(Generic[T]):
    """
    About 2.5x faster access than dict, trading for slightly slower initial allocation.
    MapMatrix is faster than Dict[Tile, X] down to about 15-20 assignments + accesses.
    Down to 150 assignments + accesses, this is faster than MapMatrixFlat.
    Then from 150 assignments/accesses down to 4 assignments/accesses, MapMatrixFlat is faster than Dict[Tile, X].
    So, use this for high access stuff so long as you're not making lots of copies.
    If doing lots of .copy()s, dict is about 20x faster at very small counts, and about 2x faster on normal 1v1 sized maps, and 1.5x faster at very large (800+, large FFA map sized) counts.
    """
    def __init__(self, map: MapBase, initVal: T = None, emptyVal: T | None | str = 'PLACEHOLDER'):
        self.init_val: T = initVal
        if emptyVal != 'PLACEHOLDER':
            self.init_val = emptyVal

        self._grid: typing.List[typing.List[T]] = [[initVal] * map.rows for _ in range(map.cols)] if map is not None else None
        self.map: MapBase = map

    def add(self, item: Tile, value: T = True):
        self._grid[item.x][item.y] = value

    def __setitem__(self, key: Tile, item: T):
        self._grid[key.x][key.y] = item

    def __getitem__(self, key: Tile) -> T:
        return self._grid[key.x][key.y]

    def get(self, key: Tile, defaultVal: T | None):
        val = self._grid[key.x][key.y]
        return defaultVal if val == self.init_val else val

    def values(self) -> typing.List[T]:
        allValues: typing.List[T] = []
        for row in self._grid:
            for item in row:
                if item != self.init_val:
                    allValues.append(item)
        return allValues

    def keys(self) -> typing.List[Tile]:
        allKeys: typing.List[Tile] = []
        for x, row in enumerate(self._grid):
            for y, item in enumerate(row):
                if item != self.init_val:
                    allKeys.append(self.map.GetTile(x, y))
        return allKeys

    def copy(self) -> MapMatrix[T]:
        """
        cost on 1v1 size map is about 0.00222ms
        @return:
        """
        myClone = MapMatrix(None)
        myClone.init_val = self.init_val
        myClone.map = self.map
        myClone._grid = [yList.copy() for yList in self._grid]

        return myClone

    def __delitem__(self, key: Tile):
        self._grid[key.x][key.y] = self.init_val

    def __contains__(self, tile: Tile) -> bool:
        return self._grid[tile.x][tile.y] != self.init_val

    def __str__(self) -> str:
        return repr(self._grid)

    def __repr__(self) -> str:
        return str(self)


class MapMatrixFlat(Generic[T]):
    """
    Only faster than the 2d mapmatrix for VERY SMALL numbers of read/writes (less than 150 reads + writes). Any more accesses than that and the 2d matrix (where multiplication is not required to determine index) is 22% better (or, mapmatrixflat is 30% worse) as we approach infinite accesses.
    Note, using this is pretty much always faster than using dictionary. Dictionary wins at 4 sets + 4 gets, and is already slower by 7 sets 7 gets.
    So choose between MapMatrixFlat and MapMatrix depending on how sparse you expect assignments/accesses to be.
    Note that initializing a Flat mapmatrix is between 1/2 and 1/3 as expensive as initializing a 2d mapmatrix (surprisingly, not better than that).
     And the cost is about 0.0022ms (mapmatrix) vs 0.00088ms (mapmatrixflat) per initialization on a medium sized map. Both scale linearly with map size.
    If doing lots of .copy()s, dict is about 10x faster at very small counts, and about equivalent at normal 1v1 sized map tile count (so if the dict would be completely full), and this is 50% faster at high (800+) counts like FFA maps.
    """
    def __init__(self, map: MapBase, initVal: T = None, emptyVal: T | None | str = 'PLACEHOLDER'):
        self.init_val: T = initVal
        if emptyVal != 'PLACEHOLDER':
            self.init_val = emptyVal

        self._grid: typing.List[T] = [initVal] * (map.cols * map.rows) if map is not None else None
        self._rows = map.rows if map is not None else -1
        self.map: MapBase = map

    def add(self, item: Tile, value: T = True):
        self._grid[item.x * self._rows + item.y] = value

    def __setitem__(self, key: Tile, item: T):
        self._grid[key.x * self._rows + key.y] = item

    def __getitem__(self, key: Tile) -> T:
        return self._grid[key.x * self._rows + key.y]

    def get(self, key: Tile, defaultVal: T | None):
        val = self._grid[key.x * self._rows + key.y]
        return defaultVal if val == self.init_val else val

    def values(self) -> typing.List[T]:
        allValues: typing.List[T] = []
        for row in self._grid:
            for item in row:
                if item != self.init_val:
                    allValues.append(item)
        return allValues

    def keys(self) -> typing.List[Tile]:
        allKeys: typing.List[Tile] = []
        for x, row in enumerate(self._grid):
            for y, item in enumerate(row):
                if item != self.init_val:
                    allKeys.append(self.map.GetTile(x, y))
        return allKeys

    def copy(self) -> MapMatrixFlat[T]:
        """
        copy cost on 1v1 sized map is about 0.0012ms. So you can copy about 1000 times in 1ms.
        @return:
        """
        myClone = MapMatrixFlat(None)
        myClone.init_val = self.init_val
        myClone.map = self.map
        myClone._grid = self._grid.copy()
        myClone._rows = self._rows

        return myClone

    def __delitem__(self, key: Tile):
        self._grid[key.x * self._rows + key.y] = self.init_val

    def __contains__(self, tile: Tile) -> bool:
        return self._grid[tile.x * self._rows + tile.y] != self.init_val

    def __str__(self) -> str:
        return repr(self._grid)

    def __repr__(self) -> str:
        return str(self)


class MapMatrixSet(typing.Protocol):
    """
    if > 50 accesses to the set, or if more than 1/16th of the map will added to the set, then this is faster than normal Set() object.
    Also if you're midway on either, like 100 accesses with 50 tiles in the set, this is faster.
    Only about 20% faster though or so, so not really worth a large investment.
    """
    def __init__(self, map: MapBase, fromIterable: typing.Iterable[Tile] | None = None):
        # if fromIterable is None or len(fromIterable) < 100:
        self._grid: typing.List[typing.List[bool]] = [[False] * map.rows for _ in range(map.cols)] if map is not None else None
        self.map: MapBase = map
        if fromIterable is not None:
            for t in fromIterable:
                self._grid[t.x][t.y] = True

    def add(self, item: Tile):
        self._grid[item.x][item.y] = True

    def __getitem__(self, key: Tile) -> bool:
        return self._grid[key.x][key.y]

    def __iter__(self) -> typing.Iterable[Tile]:
        for x, row in enumerate(self._grid):
            for y, item in enumerate(row):
                if item:
                    yield self.map.GetTile(x, y)

    def update(self, tiles: typing.Iterable[Tile]):
        for t in tiles:
            self._grid[t.x][t.y] = True

    def copy(self) -> MapMatrixSet:
        """
        cost on 1v1 size map is about 0.00222ms
        @return:
        """
        myClone = MapMatrixSet(None)
        myClone.map = self.map
        myClone._grid = [yList.copy() for yList in self._grid]

        return myClone

    def __delitem__(self, key: Tile):
        self._grid[key.x][key.y] = False

    def discard(self, key: Tile):
        self._grid[key.x][key.y] = False

    def __contains__(self, tile: Tile) -> bool:
        return self._grid[tile.x][tile.y]

    def __str__(self) -> str:
        return repr(self._grid)

    def __repr__(self) -> str:
        return str(self)


class MapMatrixSetWithLength(object):
    """
    if > 300 accesses to the set, then this is faster than normal Set() object.
    """
    def __init__(self, map: MapBase):
        self._grid: typing.List[typing.List[bool]] = [[False] * map.rows for _ in range(map.cols)] if map is not None else None
        self.map: MapBase = map
        self._length: int = 0

    def add(self, item: Tile):
        if not self._grid[item.x][item.y]:
            self._length += 1
            self._grid[item.x][item.y] = True

    def __len__(self):
        return self._length

    def __setitem__(self, key: Tile, val: bool):
        if val:
            self.add(key)
        else:
            self.discard(key)

    def __getitem__(self, key: Tile) -> bool:
        return self._grid[key.x][key.y]

    def __iter__(self) -> typing.Iterable[Tile]:
        for x, row in enumerate(self._grid):
            for y, item in enumerate(row):
                if item:
                    yield self.map.GetTile(x, y)

    def update(self, tiles: typing.Iterable[Tile]):
        for t in tiles:
            self._grid[t.x][t.y] = True

    def copy(self) -> MapMatrixSetWithLength:
        """
        cost on 1v1 size map is about 0.00222ms
        @return:
        """
        myClone = MapMatrixSetWithLength(None)
        myClone.map = self.map
        myClone._grid = [yList.copy() for yList in self._grid]

        return myClone

    def __delitem__(self, key: Tile):
        if self._grid[key.x][key.y]:
            self._length -= 1
            self._grid[key.x][key.y] = False

    def discard(self, key: Tile):
        if self._grid[key.x][key.y]:
            self._length -= 1
            self._grid[key.x][key.y] = False

    def __contains__(self, tile: Tile) -> bool:
        return self._grid[tile.x][tile.y]

    def __str__(self) -> str:
        return repr(self._grid)

    def __repr__(self) -> str:
        return str(self)


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
