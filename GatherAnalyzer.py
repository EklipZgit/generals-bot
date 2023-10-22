import SearchUtils
from base.client.map import MapBase, Tile
from MapMatrix import MapMatrix


class GatherAnalyzer(object):
    def __init__(self, map: MapBase):
        self.gather_locality_map: MapMatrix[int] = MapMatrix(map, 0)
        self.map = map

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def scan(self):
        """
        Look for pockets of far away army and put weights on them

        @return:
        """

        self.gather_locality_map: MapMatrix[int] = MapMatrix(self.map, 0)
        for tile in self.map.pathableTiles:
            if tile.player != self.map.player_index:
                continue

            def counter(nearbyTile: Tile):
                if nearbyTile.isCity or nearbyTile.isGeneral:
                    # Skip cities because we want to gather TILES not CITIES :|
                    return
                if nearbyTile.player == self.map.player_index:
                    self.gather_locality_map[tile] += nearbyTile.army - 1

            SearchUtils.breadth_first_foreach(self.map, [tile], maxDepth=4, foreachFunc=counter, skipFunc=lambda curTile: curTile.isNeutral and curTile.isCity, noLog=True)


