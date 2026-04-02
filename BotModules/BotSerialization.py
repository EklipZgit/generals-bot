import typing

from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet
from base.client.map import Tile, new_value_grid

class BotSerialization:
    @staticmethod
    def convert_int_tile_2d_array_to_string(bot, rows: typing.List[typing.List[int]]) -> str:
        return ','.join([str(rows[tile.x][tile.y]) for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_float_tile_2d_array_to_string(bot, rows: typing.List[typing.List[float]]) -> str:
        return ','.join([f'{rows[tile.x][tile.y]:.2f}' for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_int_map_matrix_to_string(bot, mapMatrix: MapMatrixInterface[int]) -> str:
        return ','.join([str(mapMatrix[tile]) for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_float_map_matrix_to_string(bot, mapMatrix: MapMatrixInterface[float]) -> str:
        return ','.join([f'{mapMatrix[tile]:.2f}' for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_bool_map_matrix_to_string(bot, mapMatrix: MapMatrixInterface[bool] | MapMatrixSet) -> str:
        return ''.join(["1" if mapMatrix[tile] else "0" for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_tile_set_to_string(bot, tiles: typing.Set[Tile]) -> str:
        return ''.join(["1" if tile in tiles else "0" for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_tile_int_dict_to_string(bot, tiles: typing.Dict[Tile, int]) -> str:
        return ','.join([str(tiles.get(tile, '')) for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_string_to_int_tile_2d_array(bot, data: str) -> typing.List[typing.List[int]]:
        arr = new_value_grid(bot._map, -1)

        values = data.split(',')
        i = 0
        prev = None
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            arr[tile.x][tile.y] = int(v)

            prev = tile
            i += 1

        return arr

    @staticmethod
    def convert_string_to_float_tile_2d_array(bot, data: str) -> typing.List[typing.List[float]]:
        arr = new_value_grid(bot._map, 0.0)

        values = data.split(',')
        i = 0
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            if v != '':
                arr[tile.x][tile.y] = float(v)
            i += 1

        return arr

    @staticmethod
    def convert_string_to_bool_map_matrix(bot, data: str) -> MapMatrixInterface[bool]:
        matrix = MapMatrix(bot._map, False)
        i = 0
        for v in data:
            if v == "1":
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                matrix[tile] = True
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_bool_map_matrix_set(bot, data: str) -> MapMatrixSet:
        matrix = MapMatrixSet(bot._map)
        i = 0
        for v in data:
            if v == "1":
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                matrix.add(tile)
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_int_map_matrix(bot, data: str) -> MapMatrixInterface[int]:
        matrix = MapMatrix(bot._map, -1)
        values = data.split(',')
        i = 0
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            matrix[tile] = int(v)
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_float_map_matrix(bot, data: str) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, -1.0)
        values = data.split(',')
        i = 0
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            matrix[tile] = float(v)
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_tile_set(bot, data: str) -> typing.Set[Tile]:
        outputSet = set()
        i = 0
        for v in data:
            if v == "1":
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                outputSet.add(tile)
            i += 1

        return outputSet

    @staticmethod
    def convert_string_to_tile_int_dict(bot, data: str) -> typing.Dict[Tile, int]:
        outputSet = {}
        i = 0
        for v in data.split(','):
            if v != "N" and v != '':
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                outputSet[tile] = int(v)
            i += 1

        return outputSet

    @staticmethod
    def get_tile_by_tile_index(bot, tileIndex: int) -> Tile:
        x, y = BotSerialization.convert_tile_server_index_to_friendly_x_y(bot, tileIndex)
        return bot._map.GetTile(x, y)

    @staticmethod
    def convert_tile_server_index_to_friendly_x_y(bot, tileIndex: int) -> typing.Tuple[int, int]:
        y = tileIndex // bot._map.cols
        x = tileIndex % bot._map.cols
        return x, y
