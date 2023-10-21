import typing

from base.client.map import MapBase, Tile


class TileCompressor(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map

    def compress_tile(self, tile: Tile) -> str:
        return str(tile)

    def compress_tile_list(self, tiles: typing.List[Tile], charsLeft: int) -> str:
        compressed = []
        for tile in tiles:
            if charsLeft < 5:
                break

            charsLeft -= 1  # separator
            c = self.compress_tile(tile)
            compressed.append(c)
            charsLeft -= len(c)

        return '|'.join(compressed)

    def decompress_tile(self, tileStr: str) -> Tile | None:
        try:
            xStr, yStr = tileStr.split(',')
            return self.map.GetTile(int(xStr), int(yStr))
        except:
            return None

    def decompress_tile_list(self, tiles_str) -> typing.List[Tile]:
        individual = tiles_str.split('|')
        return [self.decompress_tile(s) for s in individual if self.decompress_tile(s) is not None]


class ServerTileCompressor(TileCompressor):
    def __init__(self, map: MapBase):
        super().__init__(map)

    def compress_tile(self, tile: Tile) -> str:
        return str(self.map.get_tile_index(tile))

    def decompress_tile(self, tileStr: str) -> Tile | None:
        try:
            return self.map.get_tile_by_tile_index(int(tileStr))
        except:
            return None

