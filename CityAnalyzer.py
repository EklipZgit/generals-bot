import typing

from BoardAnalyzer import BoardAnalyzer
from base.client.map import MapBase, Tile, MapMatrix


class CityAnalyzer(object):
    def __init__(self, map: MapBase, playerGeneral: Tile):
        self.map: MapBase = map
        self.general: Tile = playerGeneral
        self.cities: typing.Set[Tile] = set()
        self.board_analysis: BoardAnalyzer = None
        # how much taking the city decreases the shortest path
        self.city_path_decrease_score: MapMatrix = MapMatrix(map, 0)
        self.city_defensability_score: MapMatrix = MapMatrix(map, 0)
        self.city_general_defense_score: MapMatrix = MapMatrix(map, 0)

    def re_scan(self, board_analysis: BoardAnalyzer):
        self.board_analysis = board_analysis
        for row in self.map.grid:
            for tile in row:
                # TODO calculate predicted enemy city locations in fog and explore mountains more in places we would WANT cities to be
                tileMightBeUndiscCity = not tile.discovered and tile.isNotPathable
                if not (tile.isCity or tileMightBeUndiscCity):
                    continue
                if tile.player == -1:
                    self.city_path_decrease_score[tile] = self._get_path_decrease_score(tile)
                    self.city_path_decrease_score = self._get_path_decrease_score(tile)

