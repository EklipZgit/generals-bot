import SearchUtils
from MapMatrix import MapMatrix
from base.client.map import DistanceMapper, MapBase, Tile


class DistanceMapperImpl(DistanceMapper):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.dists: MapMatrix[MapMatrix[int] | None] = MapMatrix(map, None)  # SearchUtils.dumbassDistMatrix(map)

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int | None:
        tileDists = self.dists[tileA]
        if tileDists is None:
            tileDists = self._get_tile_dist_matrix_internal(tileA)

        dist = tileDists[tileB]
        if dist > 999:
            return None
        else:
            return dist

    def get_tile_dist_matrix(self, tile: Tile) -> MapMatrix[int]:
        tileDists = self.dists[tile]
        if tileDists is None:
            tileDists = self._get_tile_dist_matrix_internal(tile)

        return tileDists

    def _get_tile_dist_matrix_internal(self, tile: Tile) -> MapMatrix[int]:
        tileDists = SearchUtils.build_distance_map_matrix(self.map, [tile])
        self.dists[tile] = tileDists
        return tileDists

    def recalculate(self):
        for tile in self.map.get_all_tiles():
            self.dists[tile] = None
