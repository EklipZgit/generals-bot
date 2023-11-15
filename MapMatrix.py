import typing
from typing import TypeVar, Generic

from base.client.map import Tile, MapBase, new_value_grid

T = TypeVar('T')


class MapMatrix(Generic[T]):
    def __init__(self, map: MapBase, initVal: T = None):
        self.init_val: T = initVal
        self.grid: typing.List[typing.List[T]] = new_value_grid(map, initVal)
        self.map: MapBase = map

    def add(self, item: Tile, value: T):
        self.grid[item.x][item.y] = value

    def __setitem__(self, key: Tile, item: T):
        self.grid[key.x][key.y] = item

    def __getitem__(self, key: Tile) -> T:
        val = self.grid[key.x][key.y]
        return val

    def values(self) -> typing.List[T]:
        allValues: typing.List[T] = []
        for row in self.grid:
            for item in row:
                if item != self.init_val:
                    allValues.append(item)
        return allValues

    def keys(self) -> typing.List[Tile]:
        allKeys: typing.List[Tile] = []
        for y, row in enumerate(self.grid):
            for x, item in enumerate(row):
                if item != self.init_val:
                    allKeys.append(self.map.GetTile(x, y))
        return allKeys

    def __delitem__(self, key: Tile):
        self.grid[key.x][key.y] = self.init_val

    def __contains__(self, tile: Tile):
        return self.grid[tile.x][tile.y] != self.init_val

    def __str__(self):
        return repr(self.grid)

    def __repr__(self):
        return str(self)

