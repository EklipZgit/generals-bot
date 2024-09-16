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
..#D = a tile that isn't visible, but has been discovered. Note that undiscovered inferred tiles are recorded as being a player, out of vision, with no D.

Bot state data is below the second |  |  |  |  |  | and is ignored when loading MAPs but not when loading BOTs.
"""
import pathlib
import typing

from Army import Army
from Path import Path
from SearchUtils import count
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase, PLAYER_CHAR_INDEX_PAIRS
from base.client.tile import TILE_OBSERVATORY, TILE_LOOKOUT


class TextMapLoader(object):
    @staticmethod
    def load_map_from_file(file_path_from_tests_folder: str) -> typing.List[typing.List[Tile]]:
        data = TextMapLoader.get_map_raw_string_from_file(file_path_from_tests_folder)
        return TextMapLoader.load_map_from_string(data)

    @staticmethod
    def load_map_from_string(data: str) -> typing.List[typing.List[Tile]]:
        mapRows = []
        data = data.strip('\r\n')
        rows = data.splitlines()
        widthRow = rows[0]
        width = count(widthRow, lambda c: c == '|')
        split_every = len(widthRow.split('|')[1]) + 1
        indent = len(widthRow) - len(widthRow.lstrip())
        y = 0
        numRows = 0
        for row in rows[1:]:
            if row.startswith('|'):
                # stuff after this point is ekBot data etc
                break
            numRows += 1
        for row in rows[1:]:
            if indent > 0:
                row = row[indent:]
            if row.startswith('|'):
                # stuff after this point is ekBot data etc
                break
            row = row.rstrip()

            cols = [Tile(x, y, tileIndex=y * width + x) for x in range(width)]
            textTiles = [row[i:i+split_every] for i in range(0, len(row), split_every)]
            x = 0
            for textTile in textTiles:
                curTile = cols[x]
                TextMapLoader.__apply_text_tile_to_tile(curTile, textTile)
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
            kvpStr = rows[i].strip()
            if not kvpStr:
                continue
            key, value = kvpStr.split('=')
            if key in mapData:
                raise AssertionError(f'key {key} in file twice')
            mapData[key] = value

        return mapData

    @staticmethod
    def dump_map_to_string(map: MapBase) -> str:
        maxWidth = 0
        vals = []
        for row in map.grid:
            rowVals = []
            for tile in row:
                valRep = tile.get_value_representation()
                maxWidth = max(len(valRep), maxWidth)
                rowVals.append(valRep)

            vals.append(rowVals)

        split_every = maxWidth

        outputToJoin = []
        for i in range(map.cols):
            outputToJoin.append('|')
            for j in range(split_every - 1):
                outputToJoin.append(' ')

        outputToJoin.append('\n')

        for row in vals:
            for valRep in row:
                outputToJoin.append(valRep)
                charsLeft = split_every - len(valRep)

                for i in range(charsLeft):
                    outputToJoin.append(' ')

            outputToJoin.append('\n')

        for i in range(len(map.grid[0])):
            outputToJoin.append('|')
            for j in range(split_every - 1):
                outputToJoin.append(' ')

        raw = ''.join(outputToJoin)
        lines = raw.splitlines()

        lines.append(f'turn={map.turn}')
        lines.append(f'player_index={map.player_index}')
        if map.is_custom_map:
            lines.append('is_custom_map=True')
        if map.walled_city_base_value is not None:
            lines.append(f'walled_city_base_value={map.walled_city_base_value}')

        lines.append(f'PATHABLE_CITY_THRESHOLD={Tile.PATHABLE_CITY_THRESHOLD}')

        gameType = '1v1'
        if len(map.players) > 2:
            if map.is_2v2:
                gameType = 'team'
            elif map.teams is not None and len(map.teams) > 0:
                gameType = 'custom_team'
            else:
                gameType = 'ffa'

        if map.teams is not None:
            teams = ','.join([str(t) for t in map.teams])
            lines.append(f'teams={teams}')

        lines.append(f'mode={gameType}')
        mods = []
        for i in range(len(map.modifiers_by_id)):
            if map.modifiers_by_id[i]:
                mods.append(str(i))
        if len(mods) > 0:
            lines.append(f'modifiers={",".join(mods)}')

        return '\n'.join([line.rstrip() for line in lines])

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
                if 'D' in text_tile:
                    tile.discovered = True
                return
            case 'O':
                tile.army = 0
                tile.tile = TILE_OBSERVATORY
                tile.player = -1
                tile.isMountain = True
                tile.isObservatory = True
                if 'D' in text_tile:
                    tile.discovered = True
                return
            case 'L':
                tile.army = 0
                tile.tile = TILE_LOOKOUT
                tile.player = -1
                tile.isMountain = True
                tile.isLookout = True
                if 'D' in text_tile:
                    tile.discovered = True
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
            case 'i':
                player = 8
            case 'j':
                player = 9
            case 'k':
                player = 10
            case 'l':
                player = 11
            case 'm':
                player = 12
            case 'n':
                player = 13
            case 'o':
                player = 14
            case 'p':
                player = 15
            case 'C':
                tile.tile = -1
            case 'N':
                tile.tile = -1
            case 'D':
                tile.tile = -1
            case 'S':
                tile.tile = -1
            case 'E':
                tile.tile = -1
            case _:
                raise AssertionError(f'text_tile [{text_tile}] did not match a known pattern.')

        if 'C' in text_tile:
            tile.isCity = True

        if 'G' in text_tile:
            tile.isGeneral = True

        if 'E' in text_tile:
            tile.isDesert = True

        if 'S' in text_tile:
            tile.isSwamp = True

        if 'D' in text_tile:
            tile.discovered = True

        tile.player = player
        if player >= 0:
            tile.tile = player

        armyStr = text_tile.lstrip(' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ').rstrip('D ')
        if len(armyStr) > 0:
            army = int(armyStr)
            tile.army = army

        tile.turn_captured = 0

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
        return PLAYER_CHAR_INDEX_PAIRS

    @staticmethod
    def dump_armies(map: MapBase, armies: typing.Dict[Tile, Army]) -> str:
        """
        @param map:
        @param armies:
        @return:
        """

        armyStrs = []
        for army in armies.values():
            entangled = [army.tile]
            entangled.extend(a.tile for a in army.entangledArmies)
            tileStr = "|".join([f'{t.x},{t.y}' for t in entangled])

            pathsStr = "|".join([str(p) for p in army.expectedPaths])

            armyStr = f'{army.name}+{army.value}!{army.entangledValue}^{army.last_seen_turn}*{army.last_moved_turn}&{pathsStr}%{tileStr}'

            armyStrs.append(armyStr)

        return ':'.join(armyStrs)

    @staticmethod
    def parse_path(map: MapBase, pathStr: str) -> Path | None:
        if pathStr == "None":
            return None
        # [28 len 3] 7,18 -> 6,18 -> 6,17 -> 5,17

        try:
            _, path = pathStr.split('] ')

            resultPath = Path()
            for tileStr in path.split('->'):
                xStr, yStr = tileStr.split(',')
                yStr = yStr.lower().strip()

                moveHalf = False
                if yStr.endswith('z'):
                    moveHalf = True
                    yStr = yStr.strip('z')

                tile = map.GetTile(int(xStr), int(yStr))
                resultPath.add_next(tile, moveHalf)

            return resultPath
        except:
            # TODO handle other gather capture plan types?

            return None

    @staticmethod
    def load_armies(map: MapBase, data: typing.Dict[str, str]) -> typing.Dict[Tile, Army]:
        """
        @param map:
        @param data:
        @return:
        """

        armies = {}

        if 'Armies' not in data:
            return armies

        raw = data['Armies']

        armiesRaw = raw.split(':')

        for armyRaw in armiesRaw:
            if len(armyRaw) == 0:
                continue
            name, everythingElse = armyRaw.split('+')
            value, everythingElse = everythingElse.split('!')
            entangledValue, everythingElse = everythingElse.split('^')
            lastSeenTurn, everythingElse = everythingElse.split('*')
            lastMovedTurn, everythingElse = everythingElse.split('&')
            expectedPathsCombined, everythingElse = everythingElse.split('%')
            expectedPaths = [TextMapLoader.parse_path(map, pStr) for pStr in expectedPathsCombined.split('|')]
            tilesRaw = everythingElse.split('|')

            xRaw, yRaw = tilesRaw[0].split(',')

            curTile = map.GetTile(int(xRaw), int(yRaw))
            army = armies.get(curTile, None)
            if not army:
                army = Army(curTile, name)
                armies[curTile] = army
            army.name = name
            army.value = int(value)
            if entangledValue != "None" and entangledValue:
                army.entangledValue = int(entangledValue)

            army.expectedPaths = expectedPaths
            army.last_seen_turn = int(lastSeenTurn)
            army.last_moved_turn = int(lastMovedTurn)
            if len(tilesRaw) > 1:
                for tileRaw in tilesRaw[1:]:
                    xRaw, yRaw = tileRaw.split(',')
                    entangledTile = map.GetTile(int(xRaw), int(yRaw))
                    entangled = armies.get(entangledTile, None)
                    if not entangled:
                        entangled = Army(entangledTile)
                        armies[entangledTile] = entangled
                    army.entangledArmies.append(entangled)

        return armies

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

        if f'player_index' in data:
            map.player_index = int(data['player_index'])
        if f'player_index' in data:
            map.player_index = int(data['player_index'])

        if f'teams' in data:
            teams = data['teams'].split(',')
            map.set_teams([int(s) for s in teams])
        else:
            map.friendly_team = MapBase.get_teams_array(map)[map.player_index]

        if 'mode' in data:
            map.is_2v2 = data['mode'] == 'team'
        if 'turn' in data:
            map.turn = int(data['turn'])
        if 'modifiers' in data and len(data['modifiers']) > 0:
            mods = data['modifiers'].split(',')
            for mod in mods:
                map.modifiers_by_id[int(mod)] = True

        if 'is_custom_map' in data:
            map.is_custom_map = bool(data['is_custom_map'])
        # if 'valid_spawns' in data:
        #     map.valid_spawns = bool(data['is_custom_map'])
        if 'walled_city_base_value' in data:
            map.walled_city_base_value = int(data['walled_city_base_value'])
            map.is_walled_city_game = True
        if 'PATHABLE_CITY_THRESHOLD' in data:
            Tile.PATHABLE_CITY_THRESHOLD = int(data['PATHABLE_CITY_THRESHOLD'])
        else:
            Tile.PATHABLE_CITY_THRESHOLD = 5   # old replays, no cities were ever pathable. However setting negative makes all neutrals unpathable.

        for player in map.players:
            char, index = playerCharMap[player.index]

            if f'{char}Username' in data:
                map.usernames[index] = data[f'{char}Username']
            if f'{char}Score' in data:
                player.score = int(data[f'{char}Score'])
            if f'{char}Tiles' in data:
                player.tileCount = int(data[f'{char}Tiles'])
            if f'{char}CityCount' in data:
                player.cityCount = int(data[f'{char}CityCount'])
            if f'{char}Stars' in data:
                player.stars = float(data[f'{char}Stars'])
            if f'{char}KnowsKingLocation' in data:
                player.knowsKingLocation = data[f'{char}KnowsKingLocation'].lower() == 'true'
            if f'{char}KnowsAllyKingLocation' in data:
                player.knowsAllyKingLocation = data[f'{char}KnowsAllyKingLocation'].lower() == 'true'
            if f'{char}Dead' in data:
                player.dead = data[f'{char}Dead'].lower() == 'true'
            if f'{char}LeftGame' in data:
                player.leftGame = data[f'{char}LeftGame'].lower() == 'true'
            if f'{char}LeftGameTurn' in data:
                player.leftGameTurn = int(data[f'{char}LeftGameTurn'])
            if f'{char}AggressionFactor' in data:
                player.aggression_factor = int(data[f'{char}AggressionFactor'])
            if f'{char}Delta25Tiles' in data:
                player.delta25tiles = int(data[f'{char}Delta25Tiles'])
            if f'{char}Delta25Score' in data:
                player.delta25score = int(data[f'{char}Delta25Score'])
            if f'{char}CityGainedTurn' in data:
                player.cityGainedTurn = int(data[f'{char}CityGainedTurn'])
            if f'{char}CityLostTurn' in data:
                player.cityLostTurn = int(data[f'{char}CityLostTurn'])
            if f'{char}LastSeenMoveTurn' in data:
                player.last_seen_move_turn = int(data[f'{char}LastSeenMoveTurn'])
            player.team = map.team_ids_by_player_index[player.index]

        for tile in map.get_all_tiles():
            tile.turn_captured = 0