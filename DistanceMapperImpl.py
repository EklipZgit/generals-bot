from collections import deque

import logbook

import SearchUtils
from MapMatrix import MapMatrix
from base.client.map import DistanceMapper, MapBase, Tile


UNREACHABLE = 1000
"""The placeholder distance value for unreachable land"""


class DistanceMapperImpl(DistanceMapper):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self._dists: MapMatrix[MapMatrix[int] | None] = MapMatrix(map, None)  # SearchUtils.dumbassDistMatrix(map)

    def get_distance_between_or_none(self, tileA: Tile, tileB: Tile) -> int | None:
        dist = self.get_distance_between(tileA, tileB)

        if dist > 999:
            # TODO this is a debug assert setup...
            if tileB in self.map.reachableTiles and tileA in self.map.reachableTiles:
                logbook.warn(f'tileA {str(tileA)} and tileB {str(tileB)} both in reachable, but had bad distance. Force recalculating all distances...')
                self.recalculate()
                return self.get_distance_between(tileA, tileB)
            return None
        else:
            return dist

    def get_distance_between_or_none_dual_cache(self, tileA: Tile, tileB: Tile) -> int | None:
        dist = self.get_distance_between_dual_cache(tileA, tileB)

        if dist > 999:
            # TODO this is a debug assert setup...
            if tileB in self.map.reachableTiles and tileA in self.map.reachableTiles:
                logbook.warn(f'tileA {str(tileA)} and tileB {str(tileB)} both in reachable, but had bad distance. Force recalculating all distances...')
                self.recalculate()
                return self.get_distance_between(tileA, tileB)
            return None
        else:
            return dist

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int:
        tileDists = self._dists[tileA]
        if tileDists is None:
            tileDists = self._get_tile_dist_matrix_internal(tileA)

        return tileDists[tileB]

    def get_distance_between_dual_cache(self, tileA: Tile, tileB: Tile) -> int:
        tileDists = self._dists[tileA]
        if tileDists is None:
            bDists = self._dists[tileB]
            if bDists is None:
                tileDists = self._get_tile_dist_matrix_internal(tileA)
            else:
                return bDists[tileA]

        return tileDists[tileB]

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
        distanceMap = MapMatrix(self.map, UNREACHABLE)

        frontier = deque()

        frontier.append((startTile, 0))

        dist = 0
        while frontier:
            (current, dist) = frontier.popleft()
            if current in distanceMap:
                continue

            distanceMap[current] = dist

            if current.isObstacle and current != startTile:
                continue

            newDist = dist + 1
            for n in current.movable:  # new spots to try
                if n in distanceMap:
                    continue
                frontier.append((n, newDist))
        return distanceMap

    def recalculate(self):
        logbook.info(f'RESETTING CACHED DISTANCE MAPS IN DistanceMapperImpl')
        # for tile in self.map.get_all_tiles():
        #     self._dists[tile] = None
        self._dists = MapMatrix(self.map, None)
