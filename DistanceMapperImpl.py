import logbook

import SearchUtils
from MapMatrix import MapMatrix
from base.client.map import DistanceMapper, MapBase, Tile


class DistanceMapperImpl(DistanceMapper):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self._dists: MapMatrix[MapMatrix[int] | None] = MapMatrix(map, None)  # SearchUtils.dumbassDistMatrix(map)

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int | None:
        tileDists = self._dists[tileA]
        if tileDists is None:
            tileDists = self._get_tile_dist_matrix_internal(tileA)

        dist = tileDists[tileB]
        if dist > 999:
            if tileB in self.map.reachableTiles and tileA in self.map.reachableTiles:
                logbook.warn(f'tileA {str(tileA)} and tileB {str(tileB)} both in reachable, but had bad distance. Force recalculating all distances...')
                self.recalculate()
                return self.get_distance_between(tileA, tileB)
            return None
        else:
            return dist

    def get_tile_dist_matrix(self, tile: Tile) -> MapMatrix[int]:
        tileDists = self._dists[tile]
        if tileDists is None:
            tileDists = self._get_tile_dist_matrix_internal(tile)

        return tileDists

    def _get_tile_dist_matrix_internal(self, tile: Tile) -> MapMatrix[int]:
        tileDists = self.build_distance_map_matrix_fast(tile)
        self._dists[tile] = tileDists
        return tileDists

    def build_distance_map_matrix_fast(self, startTile: Tile) -> MapMatrix[int]:
        distanceMap = MapMatrix(self.map, 1000)

        def bfs_dist_mapper(tile, dist):
            distanceMap[tile] = dist

        SearchUtils.breadth_first_foreach_dist(
            self.map,
            [startTile],
            1000,
            bfs_dist_mapper,
            skipTiles=None,
            skipFunc=lambda tile: tile.isObstacle and tile != startTile,
            bypassDefaultSkip=True,
            noLog=True)
        return distanceMap

    def recalculate(self):
        logbook.info(f'RESETTING CACHED DISTANCE MAPS IN DistanceMapperImpl')
        for tile in self.map.get_all_tiles():
            self._dists[tile] = None
