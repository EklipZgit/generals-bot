import heapq
import typing

from Algorithms import MapSpanningUtils
from Interfaces import TileSet, MapMatrixInterface
from base.client.map import MapBase
from base.client.tile import Tile


def kruskals_gather(map: MapBase, targetTurns: int, rootTiles: typing.List[Tile], tilesToIncludeIfPossible: typing.Iterable[Tile], negativeTiles: TileSet, gatherRewardMatrix: MapMatrixInterface[float] | None = None):
   connectedTiles, missing = MapSpanningUtils.get_spanning_tree_from_tile_lists(map, rootTiles, negativeTiles)

   q = []
   for tile in map.reachable_tiles:
       down = map.GetTile(tile.x, tile.y + 1)
       right = map.GetTile(tile.x + 1, tile.y)

       if down in map.reachable_tiles:
          heapq.heappush()