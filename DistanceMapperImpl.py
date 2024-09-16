import time
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
        self.time_total: float = 0.0
        self.time_building_distmaps: float = 0.0
        self.resets_total: int = 0

    def get_distance_between_or_none(self, tileA: Tile, tileB: Tile) -> int | None:
        """Performs worse than the dual cache version."""
        dist = self.get_distance_between(tileA, tileB)
        # above is already timed
        start = time.perf_counter()

        if dist > 999:
            # TODO this is a debug assert setup...
            if tileB in self.map.reachable_tiles and tileA in self.map.reachable_tiles:
                logbook.error(f'tileA {str(tileA)} and tileB {str(tileB)} both in reachable, but had bad distance. Force recalculating all distances...')
                self.recalculate()
                self.time_total += time.perf_counter() - start
                return self.get_distance_between(tileA, tileB)
            self.time_total += time.perf_counter() - start
            return None
        else:
            self.time_total += time.perf_counter() - start
            return dist

    def get_distance_between_or_none_dual_cache(self, tileA: Tile, tileB: Tile) -> int | None:
        dist = self.get_distance_between_dual_cache(tileA, tileB)
        # above is already timed
        start = time.perf_counter()

        if dist > 999:
            # TODO this is a debug assert setup...
            if tileB in self.map.reachable_tiles and tileA in self.map.reachable_tiles:
                logbook.error(f'tileA {str(tileA)} and tileB {str(tileB)} both in reachable, but had bad distance. Force recalculating all distances...')
                self.recalculate()
                self.time_total += time.perf_counter() - start
                return self.get_distance_between(tileA, tileB)
            self.time_total += time.perf_counter() - start
            return None
        else:
            self.time_total += time.perf_counter() - start
            return dist

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int:
        start = time.perf_counter()
        """Performs worse than the dual cache version."""
        tileDists = self._dists.raw[tileA.tile_index]
        if tileDists is None:
            tileDists = self._build_distance_map_matrix_fast(tileA)
            self._dists.raw[tileA.tile_index] = tileDists

        self.time_total += time.perf_counter() - start
        return tileDists.raw[tileB.tile_index]

    def get_distance_between_dual_cache(self, tileA: Tile, tileB: Tile) -> int:
        start = time.perf_counter()
        tileDists = self._dists.raw[tileA.tile_index]
        if tileDists is None:
            bDists = self._dists.raw[tileB.tile_index]
            if bDists is None:
                tileDists = self._build_distance_map_matrix_fast(tileA)
                self._dists.raw[tileA.tile_index] = tileDists
            else:
                return bDists.raw[tileA.tile_index]

        self.time_total += time.perf_counter() - start
        return tileDists.raw[tileB.tile_index]

    def get_tile_dist_matrix(self, tile: Tile) -> MapMatrixInterface[int]:
        start = time.perf_counter()
        tileDists = self._dists.raw[tile.tile_index]
        if tileDists is None:
            tileDists = self._build_distance_map_matrix_fast(tile)
            self._dists.raw[tile.tile_index] = tileDists

        self.time_total += time.perf_counter() - start
        return tileDists

    def _build_distance_map_matrix_fast(self, startTile: Tile) -> MapMatrixInterface[int]:
        start = time.perf_counter()
        distanceMap = MapMatrix(self.map, UNREACHABLE)

        frontier = deque()
        raw = distanceMap.raw
        raw[startTile.tile_index] = 0
        frontier.append((startTile, 0))

        dist: int
        current: Tile
        while frontier:
            (current, dist) = frontier.popleft()
            newDist = dist + 1
            for n in current.movable:  # new spots to try
                if raw[n.tile_index] != UNREACHABLE:
                    continue

                raw[n.tile_index] = newDist

                if n.isObstacle:
                    continue

                frontier.append((n, newDist))

        self.time_building_distmaps += time.perf_counter() - start
        return distanceMap

    def recalculate(self):
        logbook.info(f'RESETTING CACHED DISTANCE MAPS IN DistanceMapperImpl')
        self.resets_total += 1
        # for tile in self.map.get_all_tiles():
        #     self._dists.raw[tile.tile_index] = None
        self._dists = MapMatrix(self.map, None)

    def dump_times(self):
        logbook.info(f'OVERALL TIME SPENT IN DISTANCE MAPPER:\r\n'
                     f'         Distmaps: {self.time_building_distmaps:.5f}s\r\n'
                     f'         Time total: {self.time_total:.5f}s\r\n'
                     f'         Num resets: {self.resets_total}\r\n')

    def reset_times(self):
        self.time_total = 0.0
        self.time_building_distmaps = 0.0
        self.resets_total = 0
