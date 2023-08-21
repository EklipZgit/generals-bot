"""
Loads maps in the format that I chose to use to represent generals maps
|   |   |   | is ignored on bottom, but indicates the map width
aG# = general for player 0, # = army amount
bG# = general for player 1, # = army amount (etc out to general h)
M = mountain
C# = neutral city (army amount)
a# = tile for player 0 with # army
bC# = city for player 1 with # army
empty space = empty tile
N# = a neutral tile with army on it

Bot state data is below the second |  |  |  |  |  | and is ignored when loading MAPs but not when loading BOTs.
"""
import pathlib
import typing

from SearchUtils import count
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase




class TextMapLoader(object):
    @staticmethod
    def load_map_from_file(file_path_from_tests_folder: str, split_every: int = 5) -> typing.List[typing.List[Tile]]:
        data = TextMapLoader.get_map_raw_string_from_file(file_path_from_tests_folder)
        return TextMapLoader.load_map_from_string(data, split_every=split_every)

    @staticmethod
    def load_map_from_string(data: str, split_every: int = 5) -> typing.List[typing.List[Tile]]:
        mapRows = []
        data = data.strip('\r\n')
        rows = data.splitlines()
        widthRow = rows[0]
        width = count(widthRow, lambda c: c == '|')
        y = 0
        for row in rows[1:]:
            if row.startswith('|'):
                # stuff after this point is ekBot data etc
                break
            row = row.rstrip()

            cols = [Tile(x, y) for x in range(width)]
            textTiles = [row[i:i+split_every] for i in range(0, len(row), split_every)]
            x = 0
            for textTile in textTiles:
                TextMapLoader.__apply_text_tile_to_tile(cols[x], textTile)
                x += 1

            y += 1
            mapRows.append(cols)

        return mapRows

    @staticmethod
    def load_data_from_file(file_path_from_tests_folder: str) -> typing.Dict[str, str]:
        data = TextMapLoader.get_map_raw_string_from_file(file_path_from_tests_folder)
        return TextMapLoader.load_data_from_string(data)

    @staticmethod
    def load_data_from_string(data: str) -> typing.Dict[str, str]:
        mapData: typing.Dict[str, str] = {}
        data = data.strip('\r\n')
        rows = data.splitlines()
        lastMapRow = 0
        for i, row in enumerate(rows):
            if row.startswith('|'):
                lastMapRow = i

        for i in range(lastMapRow + 1, len(rows)):
            kvpStr = rows[i]
            key, value = kvpStr.split('=')
            if key in mapData:
                raise AssertionError(f'key {key} in file twice')
            mapData[key] = value

        return mapData

    @staticmethod
    def dump_map_to_string(map: MapBase, split_every: int = 5) -> str:
        outputToJoin = []
        for i in range(len(map.grid[0])):
            outputToJoin.append('|')
            for j in range(split_every - 1):
                outputToJoin.append(' ')

        outputToJoin.append('\n')

        for row in map.grid:
            for tile in row:
                charsLeft = split_every
                if tile.player >= 0:
                    playerChar = TextMapLoader.__convert_player_to_char(tile.player)
                    outputToJoin.append(playerChar)
                    charsLeft -= 1
                if tile.isCity:
                    outputToJoin.append('C')
                    charsLeft -= 1
                if tile.isMountain or (not tile.visible and tile.isNotPathable):
                    outputToJoin.append('M')
                    charsLeft -= 1
                if tile.isGeneral:
                    outputToJoin.append('G')
                    charsLeft -= 1
                if tile.army != 0 or tile.player >= 0:
                    if tile.player == -1 and not tile.isCity:
                        outputToJoin.append('N')
                        charsLeft -= 1
                    armyStr = str(tile.army)
                    charsLeft -= len(armyStr)
                    outputToJoin.append(armyStr)

                for i in range(charsLeft):
                    outputToJoin.append(' ')

            outputToJoin.append('\n')

        for i in range(len(map.grid[0])):
            outputToJoin.append('|')
            for j in range(split_every - 1):
                outputToJoin.append(' ')

        raw = ''.join(outputToJoin)
        lines = raw.splitlines()
        return '\n'.join([line.rstrip() for line in lines])

    @staticmethod
    def __convert_player_to_char(player: int):
        match player:
            case 0:
                return 'a'
            case 1:
                return 'b'
            case 2:
                return 'c'
            case 3:
                return 'd'
            case 4:
                return 'e'
            case 5:
                return 'f'
            case 6:
                return 'g'
            case 7:
                return 'h'

    @staticmethod
    def __apply_text_tile_to_tile(tile: Tile, text_tile: str):
        playerStr = text_tile[0]

        player = -1

        match playerStr:
            case ' ':
                if text_tile.strip() != '':
                    raise AssertionError(f'text_tile [{text_tile}] did not conform to the split_every width that was passed and is unparseable.')
                tile.army = 0
                tile.tile = TILE_EMPTY
                tile.player = -1
                return
            case 'M':
                tile.army = 0
                tile.tile = TILE_MOUNTAIN
                tile.player = -1
                tile.isMountain = True
                return
            case 'a':
                player = 0
            case 'b':
                player = 1
            case 'c':
                player = 2
            case 'd':
                player = 3
            case 'e':
                player = 4
            case 'f':
                player = 5
            case 'g':
                player = 6
            case 'h':
                player = 7
            case 'C':
                tile.tile = -1
            case 'N':
                tile.tile = -1
            case _:
                raise AssertionError(f'text_tile [{text_tile}] did not match a known pattern.')

        if 'C' in text_tile:
            tile.isCity = True

        if 'G' in text_tile:
            tile.isGeneral = True

        armyStr = text_tile.lstrip(' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
        army = int(armyStr)
        tile.player = player
        if player >= 0:
            tile.tile = player

        tile.army = army

    @staticmethod
    def get_map_raw_string_from_file(file_path_from_tests_folder):
        if not file_path_from_tests_folder.endswith('.txtmap'):
            file_path_from_tests_folder = f'{file_path_from_tests_folder}.txtmap'

        filePath = pathlib.Path(__file__).parent / f'../Tests/{file_path_from_tests_folder}'

        with open(filePath, 'r') as file:
            data = file.read()
            return data

    @staticmethod
    def get_player_char_index_map():
        return [
            ('a', 0),
            ('b', 1),
            ('c', 2),
            ('d', 3),
            ('e', 4),
            ('f', 5),
            ('g', 6),
            ('h', 7),
        ]

    @staticmethod
    def load_map_data_into_map(map: MapBase, data: typing.Dict[str, str]):
        playerCharMap = TextMapLoader.get_player_char_index_map()
        # set the base scores in case the map doesn't have the string data
        for player in map.players:
            player.score = 0
            player.tileCount = 0

        for tile in map.get_all_tiles():
            if tile.player > -1:
                map.players[tile.player].score += tile.army
                map.players[tile.player].tileCount += 1

        for player in map.players:
            char, index = playerCharMap[player.index]

            tileKey = f'{char}Tiles'
            if tileKey in data:
                player.tileCount = int(data[tileKey])

            scoreKey = f'{char}Score'
            if scoreKey in data:
                player.score = int(data[scoreKey])

            cityKey = f'{char}CityCount'
            if cityKey in data:
                player.cityCount = int(data[cityKey])

            deadKey = f'{char}Dead'
            if deadKey in data:
                player.dead = data[deadKey].lower() == 'true'