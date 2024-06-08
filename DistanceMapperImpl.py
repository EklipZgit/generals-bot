import typing
from collections import deque

import logbook

import SearchUtils
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix
from base.client.map import DistanceMapper, MapBase, Tile


UNREACHABLE = 1000
"""The placeholder distance value for unreachable land"""


class DistanceMapperImpl(DistanceMapper):
    # THIS IS NOT THREAD SAFE
    # THIS IS NOT THREAD SAFE
    # THIS IS NOT THREAD SAFE
    # THIS IS NOT THREAD SAFE

    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self._dists: MapMatrixInterface[MapMatrixInterface[int] | None] = MapMatrix(map)

    def get_distance_between_or_none(self, tileA: Tile, tileB: Tile) -> int | None:
        dist = self.get_distance_between(tileA, tileB)

        if dist > 999:
            # TODO this is a debug assert setup...
            if tileB in self.map.reachable_tiles and tileA in self.map.reachable_tiles:
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
            if tileB in self.map.reachable_tiles and tileA in self.map.reachable_tiles:
                logbook.warn(f'tileA {str(tileA)} and tileB {str(tileB)} both in reachable, but had bad distance. Force recalculating all distances...')
                self.recalculate()
                return self.get_distance_between(tileA, tileB)
            return None
        else:
            return dist

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int:
        tileDists = self._dists.raw[tileA.tile_index]
        if tileDists is None:
            tileDists = self._build_distance_map_matrix_fast(tileA)
            self._dists.raw[tileA.tile_index] = tileDists

        return tileDists.raw[tileB.tile_index]

    def get_distance_between_dual_cache(self, tileA: Tile, tileB: Tile) -> int:
        tileDists = self._dists.raw[tileA.tile_index]
        if tileDists is None:
            bDists = self._dists.raw[tileB.tile_index]
            if bDists is None:
                tileDists = self._build_distance_map_matrix_fast(tileA)
                self._dists.raw[tileA.tile_index] = tileDists
            else:
                return bDists.raw[tileA.tile_index]

        return tileDists.raw[tileB.tile_index]

    def get_tile_dist_matrix(self, tile: Tile) -> MapMatrixInterface[int]:
        tileDists = self._dists.raw[tile.tile_index]
        if tileDists is None:
            tileDists = self._build_distance_map_matrix_fast(tile)
            self._dists.raw[tile.tile_index] = tileDists

        return tileDists

    def _build_distance_map_matrix_fast(self, startTile: Tile) -> MapMatrixInterface[int]:
        distanceMap = MapMatrix(self.map, UNREACHABLE)

        frontier = deque()

        distanceMap.raw[startTile.tile_index] = 0
        for mov in startTile.movable:
            frontier.append((mov, 1))

        dist: int
        current: Tile
        while frontier:
            (current, dist) = frontier.popleft()
            if distanceMap.raw[current.tile_index] != UNREACHABLE:
                continue

            distanceMap.raw[current.tile_index] = dist

            if current.isObstacle:
                continue

            newDist = dist + 1
            for n in current.movable:  # new spots to try
                if distanceMap.raw[n.tile_index] != UNREACHABLE:
                    continue

                frontier.append((n, newDist))

        return distanceMap

    def recalculate(self):
        logbook.info(f'RESETTING CACHED DISTANCE MAPS IN DistanceMapperImpl')
        # for tile in self.map.get_all_tiles():
        #     self._dists.raw[tile.tile_index] = None
        self._dists = MapMatrix(self.map, None)
