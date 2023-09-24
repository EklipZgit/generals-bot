import logging
import random
import time
import traceback
import typing
import unittest

import BotHost
import EarlyExpandUtils
import GatherUtils
import SearchUtils
from ArmyEngine import ArmySimResult
from ArmyTracker import Army
from DataModels import Move
from Path import Path
from Sim.GameSimulator import GameSimulator, GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from ViewInfo import ViewInfo, PathColorer
from Viewer.ViewerProcessHost import ViewerHost
from base.client.map import MapBase, Tile, Score, Player, TILE_FOG, TILE_OBSTACLE
from bot_ek0x45 import EklipZBot


class TestBase(unittest.TestCase):
    GLOBAL_BYPASS_REAL_TIME_TEST = False
    """Change to True to have NO TEST bring up a viewer at all"""

    # __test__ = False
    def __init__(self, methodName: str = ...):
        super().__init__(methodName)
        self._initialized: bool = False

    def begin_capturing_logging(self, logLevel: int = logging.INFO):
        # without force=True, the first time a logging.log* is called earlier in the code, the config gets set to
        # default: WARN and basicConfig after that point has no effect without force=True
        logging.basicConfig(format='%(message)s', level=logLevel, force=True)

    def stop_capturing_logging(self):
        logging.basicConfig(format='%(message)s', level=logging.FATAL, force=True)

    def _initialize(self):
        if not self._initialized:
            self._initialized = True
            # self._set_up_log_stream()
            self.disable_search_time_limits_and_enable_debug_asserts()

    def load_turn_1_map_and_general(self, mapFileName: str) -> typing.Tuple[MapBase, Tile]:
        turn = 1
        board = TextMapLoader.load_map_from_file(f"{mapFileName}")

        map = self.get_test_map(board, turn=turn)
        general = next(t for t in map.pathableTiles if t.isGeneral)
        general.army = 1
        map.player_index = general.player
        map.generals[general.player] = general

        return map, general

    def load_map_and_general_from_string(self, rawMapDataString: str, turn: int, player_index: int = -1) -> typing.Tuple[MapBase, Tile]:
        board = TextMapLoader.load_map_from_string(rawMapDataString)
        data = TextMapLoader.load_data_from_string(rawMapDataString)

        map = self.get_test_map(board, turn=turn)
        TextMapLoader.load_map_data_into_map(map, data)
        general = next(t for t in map.pathableTiles if t.isGeneral and (t.player == player_index or player_index == -1))
        map.player_index = general.player
        map.generals[general.player] = general

        return map, general

    def load_map_and_general(self, mapFilePath: str, turn: int, player_index: int = -1) -> typing.Tuple[MapBase, Tile]:
        try:
            if player_index == -1:
                gameData = TextMapLoader.load_data_from_file(mapFilePath)
                if 'bot_player_index' in gameData:
                    player_index = int(gameData['bot_player_index'])
            rawMapStr = TextMapLoader.get_map_raw_string_from_file(mapFilePath)
            return self.load_map_and_general_from_string(rawMapStr, turn, player_index)
        except:
            logging.info(f'failed to load file {mapFilePath}')
            raise

    def load_map_and_generals(
            self,
            mapFilePath: str,
            turn: int,
            player_index: int = -1,
            fill_out_tiles: bool = False,
            respect_player_vision: bool = False
    ) -> typing.Tuple[MapBase, Tile, Tile]:
        rawData = TextMapLoader.get_map_raw_string_from_file(mapFilePath)
        return self.load_map_and_generals_from_string(rawData, turn, player_index, fill_out_tiles, respect_player_vision)

    def load_map_and_generals_from_string(
            self,
            rawMapStr: str,
            turn: int,
            player_index: int = -1,
            fill_out_tiles=False,
            respect_player_vision: bool = False
    ) -> typing.Tuple[MapBase, Tile, Tile]:
        gameData = TextMapLoader.load_data_from_string(rawMapStr)
        if player_index == -1 and 'bot_player_index' in gameData:
            player_index = int(gameData['bot_player_index'])

        map, general = self.load_map_and_general_from_string(rawMapStr, turn, player_index)

        botTargetPlayer = None
        if 'bot_target_player' in gameData:
            botTargetPlayer = int(gameData['bot_target_player'])

        enemyGen: Tile = None
        if botTargetPlayer is not None and map.generals[botTargetPlayer] is not None:
            enemyGen = map.generals[botTargetPlayer]
        elif 'targetPlayerExpectedGeneralLocation' in gameData:
            x, y = gameData['targetPlayerExpectedGeneralLocation'].split(',')
            enemyGen = map.GetTile(int(x), int(y))
            if not enemyGen.isGeneral:
                enemyGen.isGeneral = True
                enemyGen.player = botTargetPlayer
                if enemyGen.army == 0:
                    enemyGen.army = 10
            map.generals[enemyGen.player] = enemyGen
            map.players[enemyGen.player].general = enemyGen
        elif any(filter(lambda gen: gen is not None and gen != general, map.generals)):
            enemyGen = next(filter(lambda gen: gen is not None and gen != general, map.generals))
            map.generals[enemyGen.player] = enemyGen
            map.players[enemyGen.player].general = enemyGen
        else:
            raise AssertionError("Unable to produce an enemy general from given map data file...")

        for i, player in enumerate(map.players):
            if i != general.player and i != enemyGen.player:
                chars = TextMapLoader.get_player_char_index_map()
                enemyChar, _ = chars[i]
                # player.dead = True

                if f'{enemyChar}Score' in gameData:
                    player.score = int(gameData[f'{enemyChar}Score'])
                if f'{enemyChar}Tiles' in gameData:
                    player.tileCount = int(gameData[f'{enemyChar}Tiles'])
                if f'{enemyChar}CityCount' in gameData:
                    player.cityCount = int(gameData[f'{enemyChar}CityCount'])
                if f'{enemyChar}Stars' in gameData:
                    player.stars = float(gameData[f'{enemyChar}Stars'])
                if f'{enemyChar}KnowsKingLocation' in gameData:
                    player.knowsKingLocation = gameData[f'{enemyChar}KnowsKingLocation'].lower() == 'true'
                if f'{enemyChar}Dead' in gameData:
                    player.dead = gameData[f'{enemyChar}Dead'].lower() == 'true'
                if f'{enemyChar}LeftGame' in gameData:
                    player.leftGame = gameData[f'{enemyChar}LeftGame'].lower() == 'true'
                if f'{enemyChar}LeftGameTurn' in gameData:
                    player.leftGameTurn = int(gameData[f'{enemyChar}LeftGameTurn'])
                if f'{enemyChar}AggressionFactor' in gameData:
                    player.aggression_factor = int(gameData[f'{enemyChar}AggressionFactor'])

        if fill_out_tiles:
            chars = TextMapLoader.get_player_char_index_map()
            enemyChar, _ = chars[enemyGen.player]

            enemyScore = None
            enemyTiles = None
            enemyCities = 1

            if f'{enemyChar}Score' in gameData:
                enemyScore = int(gameData[f'{enemyChar}Score'])
            if f'{enemyChar}Tiles' in gameData:
                enemyTiles = int(gameData[f'{enemyChar}Tiles'])
            if f'{enemyChar}CityCount' in gameData:
                enemyCities = int(gameData[f'{enemyChar}CityCount'])

            playerChar, _ = chars[general.player]
            playerScore = None
            playerTiles = None
            if f'{playerChar}Score' in gameData:
                playerScore = int(gameData[f'{playerChar}Score'])
            if f'{playerChar}Tiles' in gameData:
                playerTiles = int(gameData[f'{playerChar}Tiles'])

            self.ensure_player_tiles_and_scores(map, general, playerTiles, playerScore, enemyGen, enemyTiles, enemyScore, enemyCities, respect_player_vision)

        for player in map.players:
            player.score = 0
            player.tileCount = 0
            player.cityCount = 0
            player.cities = []
            player.tiles = []
            player.general = []
        for tile in map.get_all_tiles():
            tile.lastSeen = 0
            if tile.player >= 0:
                tilePlayer = map.players[tile.player]
                tilePlayer.score += tile.army
                tilePlayer.tileCount += 1
                if tile.isGeneral:
                    tilePlayer.cityCount += 1
                    tilePlayer.general = tile
                if tile.isCity:
                    tilePlayer.cityCount += 1
                    tilePlayer.cities.append(tile)
                tilePlayer.tiles.append(tile)

        return map, general, enemyGen

    def get_test_map(self, tiles: typing.List[typing.List[Tile]], turn: int = 1, player_index: int = 0, dont_set_seen_visible_discovered: bool = False, num_players: int = -1) -> MapBase:
        self._initialize()
        figureOutPlayerCount = num_players == -1
        num_players = max(num_players, 2)
        for row in tiles:
            for tile in row:
                if not dont_set_seen_visible_discovered:
                    tile.lastSeen = turn
                    tile.visible = True
                    tile.discovered = True
                if figureOutPlayerCount:
                    num_players = max(num_players, tile.player + 1)

        fakeScores = [Score(n, 100, 100, False) for n in range(0, num_players)]

        usernames = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

        map = MapBase(player_index=player_index, teams=None, user_names=usernames[0:num_players], turn=turn, map_grid_y_x=tiles, replay_url='42069')
        map.update_scores(fakeScores)
        map.update_turn(turn)
        map.update()
        return map

    def get_empty_weight_map(self, map: MapBase, empty_value = 0):
        return [[empty_value for y in map.grid] for x in map.grid[0]]

    def get_from_general_weight_map(self, map: MapBase, general: Tile, negate: bool = False):
        distMap = SearchUtils.build_distance_map_incl_mountains(map, [general])
        if negate:
            for x in range(len(distMap)):
                for y in range(len(distMap[0])):
                    distMap[x][y] = 0 - distMap[x][y]
        return distMap

    def get_opposite_general_distance_map(self, map: MapBase, general: Tile, negate: bool = False):
        furthestTile = self.get_furthest_tile_from_general(map, general)

        furthestMap = SearchUtils.build_distance_map_incl_mountains(map, [furthestTile])
        if negate:
            for x in range(len(furthestMap)):
                for y in range(len(furthestMap[0])):
                    furthestMap[x][y] = 0 - furthestMap[x][y]

        return furthestMap

    def get_test_army_tiles(self, map: MapBase, general: Tile, enemyGen: Tile) -> typing.Tuple[Army, Army]:
        enemyArmy = None
        generalArmy = None
        for tile in map.get_all_tiles():
            if tile.player == enemyGen.player and (enemyArmy is None or enemyArmy.army < tile.army):
                enemyArmy = tile
            elif tile.player == general.player and (generalArmy is None or generalArmy.army < tile.army):
                generalArmy = tile

        # # now include generals
        # for tile in map.get_all_tiles():
        #     if enemyArmy is None and tile.player == enemyGen.player and tile.army > 3:
        #         enemyArmy = tile
        #     elif generalArmy is None and tile.player == general.player and tile.army > 3:
        #         generalArmy = tile

        if enemyArmy is None:
            raise AssertionError("Couldn't find an enemy tile with army > 3")
        if generalArmy is None:
            raise AssertionError("Couldn't find a friendly tile with army > 3")

        return Army(generalArmy), Army(enemyArmy)

    def render_paths(self, map: MapBase, paths: typing.List[Path | None], infoStr: str):
        viewInfo = self.get_view_info(map)

        r = 255
        g = 0
        b = 0
        encounteredFirst = False
        for path in paths:
            if path is not None:
                encounteredFirst = True
                viewInfo.paths.appendleft(
                    PathColorer(path, r, g, b, alpha=150, alphaDecreaseRate=5, alphaMinimum=10))
            elif encounteredFirst:
                b += 50
            else:
                continue
            r -= 40
            g += 40
            g = min(255, g)
            r = max(0, r)
            b = min(255, b)

        self.render_view_info(map, viewInfo, infoStr)

    def render_moves(self, map: MapBase, infoStr: str, moves1: typing.List[Move | None], moves2: typing.List[Move | None] = None, addlViewInfoLogLines: typing.List[str] | None = None):
        viewInfo = self.get_view_info(map)
        verifiedColors = False
        for move in moves1:
            if move is not None:
                if move.source.player == 1:
                    temp = moves1
                    moves1 = moves2
                    moves2 = temp
                verifiedColors = True
                break
        if not verifiedColors:
            for move in moves2:
                if move is not None:
                    if move.source.player == 0:
                        temp = moves1
                        moves1 = moves2
                        moves2 = temp
                    break

        r = 255
        g = 0
        b = 0
        encounteredFirst = False
        for move in moves1:
            if move is not None:
                encounteredFirst = True
                path = Path()
                path.add_next(move.source)
                path.add_next(move.dest, move.move_half)
                viewInfo.paths.appendleft(
                    PathColorer(path, r, g, b, alpha=150, alphaDecreaseRate=5, alphaMinimum=10))
            elif encounteredFirst:
                b += 40
            else:
                continue
            r -= 20
            g += 20
            g = min(255, g)
            r = max(0, r)
            b = min(255, b)

        r = 0
        g = 0
        b = 255
        if moves2 is not None:
            for move in moves2:
                if move is not None:
                    encounteredFirst = True
                    path = Path()
                    path.add_next(move.source)
                    path.add_next(move.dest, move.move_half)
                    viewInfo.paths.appendleft(
                        PathColorer(path, r, g, b, alpha=150, alphaDecreaseRate=5, alphaMinimum=10))
                elif encounteredFirst:
                    r += 40
                else:
                    continue
                b -= 20
                g += 20
                g = min(255, g)
                b = max(0, b)
                r = min(255, r)

        if addlViewInfoLogLines is not None:
            for line in addlViewInfoLogLines:
                viewInfo.addAdditionalInfoLine(line)

        self.render_view_info(map, viewInfo, infoStr)

    def render_sim_analysis(self, map: MapBase, simResult: ArmySimResult):
        aMoves = [aMove for aMove, bMove in simResult.expected_best_moves]
        bMoves = [bMove for aMove, bMove in simResult.expected_best_moves]

        addlLines = [l.strip() for l in simResult.best_result_state.get_moves_string().split('\n')]
        self.render_moves(map, str(simResult), aMoves, bMoves, addlLines)

    def disable_search_time_limits_and_enable_debug_asserts(self):
        SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = True
        EarlyExpandUtils.DEBUG_ASSERTS = True
        GatherUtils.USE_DEBUG_ASSERTS = True
        BotHost.FORCE_NO_VIEWER = False

    def enable_search_time_limits_and_disable_debug_asserts(self):
        SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = False
        EarlyExpandUtils.DEBUG_ASSERTS = False
        GatherUtils.USE_DEBUG_ASSERTS = False
        BotHost.FORCE_NO_VIEWER = False

    def reset_map_to_just_generals(self, map: MapBase, turn: int = 16):
        """
        Resets a map to a specific turn, leaving only generals around at whatever army they'd have at that point.
        Resets all cities to 45 army.

        @param map:
        @param turn:
        @return:
        """
        map.turn = turn
        for tile in map.get_all_tiles():
            if tile.isMountain:
                tile.tile = TILE_OBSTACLE

            if tile.isCity and tile.isNeutral:
                tile.player = -1
                tile.tile = TILE_OBSTACLE
                continue

            if tile.isCity:
                tile.army = 45
                tile.player = -1
                tile.tile = TILE_OBSTACLE
                continue

            if tile.isGeneral:
                tile.army = turn // 2 + 1
                tile.tile = tile.player
                map.generals[tile.player] = tile
            else:
                tile.army = 0
                tile.player = -1
                tile.tile = TILE_FOG

        map.update()

    def get_furthest_tile_from_general(self, map: MapBase, general: Tile) -> Tile:
        distMap = SearchUtils.build_distance_map(map, [general])
        maxDist = 0
        furthestTile: Tile = None
        for tile in map.pathableTiles:
            tileDist = distMap[tile.x][tile.y]
            if tileDist > maxDist:
                maxDist = tileDist
                furthestTile = tile
        return furthestTile

    def reset_map_with_enemy_general_discovered_and_gen_as_p0(self, map: MapBase, general: Tile) -> Tile:
        """
        Resets the map and returns the enemy general location (if one existed) or creates one at a far spawn from current general.
        Always makes player general become player 0, and enemy general become player 1

        @param map:
        @param general:
        @return:
        """
        self.reset_map_to_just_generals(map, turn=1)

        enemyGen: Tile = None
        if map.generals[0] is None or map.generals[1] is None:
            enemyGen = self.generate_enemy_general_opposite_general(map, general)
        else:
            enemyGen = next(filter(lambda g: g is not None and g != general, map.generals))

        enemyGen.army = general.army

        general.player = 0
        enemyGen.player = 1

        map.generals = [general, enemyGen]
        map.usernames = ['a', 'b']
        map.player_index = 0

        map.players = [Player(i) for i in range(2)]
        map.scores = [Score(player.index, total=0, tiles=1, dead=False) for player in map.players]

        map.update()

        return enemyGen


    def generate_opposite_general_and_give_tiles(self, map: MapBase, general: Tile, tileAmount: int = 50, armyOnTiles: int = 1):
        """
        always makes player general become player 0, and enemy general become player 1
        @param map:
        @param general:
        @param tileAmount:
        @param armyOnTiles:
        @return:
        """
        enemyGeneral = self.reset_map_with_enemy_general_discovered_and_gen_as_p0(map, general)

        targetScore = tileAmount * armyOnTiles + general.army

        self.ensure_player_tiles_and_scores(
            map,
            general,
            tileAmount,
            targetScore,
            enemyGeneral,
            tileAmount,
            targetScore)

        return enemyGeneral

    def get_view_info(self, map: MapBase) -> ViewInfo:
        viewInfo = ViewInfo(1, map.cols, map.rows)
        viewInfo.playerTargetScores = [0 for p in map.players]
        return viewInfo

    def render_view_info(self, map: MapBase, viewInfo: ViewInfo, infoString: str | None = None):
        titleString = infoString
        if titleString is None:
            titleString = self._testMethodName
        viewer = ViewerHost(titleString, cell_width=None, cell_height=None, alignTop=False, alignLeft=False, noLog=True)
        viewer.noLog = True
        if infoString is not None:
            viewInfo.infoText = infoString
        viewer.start()
        viewer.send_update_to_viewer(viewInfo, map, isComplete=False)

        while not viewer.check_viewer_closed():
            viewer.send_update_to_viewer(viewInfo, map, isComplete=False)
            time.sleep(0.1)

    def assertNoRepetition(
            self,
            simHost: GameSimulatorHost,
            minForRepetition=1,
            msg="Expected no move repetition.",
            repetitionPlayer: int | None = None):
        moved: typing.List[typing.Dict[Tile, int]] = [{} for player in simHost.bot_hosts]

        for histEntry in simHost.sim.moves_history:
            for i, move in enumerate(histEntry):
                if move is None:
                    continue
                if move.source not in moved[i]:
                    moved[i][move.source] = 0

                moved[i][move.source] = moved[i][move.source] + 1

        failures = []
        for player in range(len(simHost.bot_hosts)):
            if repetitionPlayer is not None and player != repetitionPlayer:
                continue

            playerMoves = moved[player]
            for tile, repetitions in sorted(playerMoves.items(), key=lambda kvp: kvp[1], reverse=True):
                if repetitions > minForRepetition:
                    failures.append(f'player {player} had {repetitions} repetitions of {str(tile)}.')

        if len(failures) > 0:
            self.fail(msg + '\r\n' + '\r\n'.join(failures))

    def assertPlayerTileCount(self, simHost: GameSimulatorHost, player: int, tileCount: int):
        simPlayer = simHost.sim.players[player]
        self.assertEqual(tileCount, simPlayer.map.players[player].tileCount)

    def assertPlayerTileVisibleAndCorrect(self, x: int, y: int, sim: GameSimulator, player_index: int):
        playerTile = self.get_player_tile(x, y, sim, player_index)
        mapTile = sim.sim_map.GetTile(x, y)
        self.assertTrue(playerTile.visible, f'tile {x},{y} should have been visible for p{player_index}')
        self.assertTrue(playerTile.discovered, f'tile {x},{y} should have been discovered for p{player_index}')
        self.assertEqual(mapTile.tile, playerTile.tile, f'tile {x},{y} tile mismatched despite perfect vision for p{player_index}')
        self.assertPlayerTileCorrect(x, y, sim, player_index)

    def assertPlayerTileCorrect(self, x: int, y: int, sim: GameSimulator, player_index: int):
        """
        Just asserts that the player has (or has predicted) correct data about the tile, whether visible to the player or not.
        Useful for testing the fog-of-war board state predictions and enemy fog emergence stuff works well, etc.
        @param x:
        @param y:
        @param sim:
        @param player_index:
        @return:
        """
        playerTile = self.get_player_tile(x, y, sim, player_index)
        mapTile = sim.sim_map.GetTile(x, y)
        # Can't assert 'tile' value itself, as the player map may refuse to update the map tile or have fog where sim map has empty, etc.
        #  Often these can and should diverge between player map and sim map with perfect information.
        # self.assertEqual(mapTile.tile, playerTile.tile, f'tile {x},{y} should have been discovered for p{player_index}')
        self.assertEqual(mapTile.army, playerTile.army, f'tile {x},{y} army mismatched for p{player_index}')
        self.assertEqual(mapTile.player, playerTile.player, f'tile {x},{y} player mismatched for p{player_index}')
        self.assertEqual(mapTile.isCity, playerTile.isCity, f'tile {x},{y} isCity mismatched for p{player_index}')
        self.assertEqual(mapTile.isMountain, playerTile.isMountain, f'tile {x},{y} isMountain mismatched for p{player_index}')
        self.assertEqual(mapTile.isGeneral, playerTile.isGeneral, f'tile {x},{y} isGeneral mismatched for p{player_index}')

    def assertPlayerTileNotVisible(self, x: int, y: int, sim: GameSimulator, player_index: int) -> Tile:
        playerTile = self.get_player_tile(x, y, sim, player_index)
        self.assertFalse(playerTile.visible)
        return playerTile

    def assertPlayerTileLostVision(self, x: int, y: int, sim: GameSimulator, player_index: int):
        playerTile = self.assertPlayerTileNotVisible(x, y, sim, player_index)
        self.assertTrue(playerTile.discovered, f'tile {x},{y} should have been discovered for p{player_index}')
        mapTile = sim.sim_map.GetTile(x, y)
        # player map should still understand the real owner
        self.assertEqual(mapTile.player, playerTile.player, f'tile {x},{y} player mismatched for p{player_index}')
        self.assertEqual(mapTile.army, playerTile.army, f'tile {x},{y} army mismatched for p{player_index}')
        self.assertEqual(sim.turn - 1, playerTile.lastSeen, f'tile {x},{y} lastSeen wasnt last turn for p{player_index}')
        return playerTile

    def assertGatheredNear(
            self,
            simHost: GameSimulatorHost,
            player: int,
            x: int,
            y: int,
            radius: int,
            requiredAvgTileValue: float = 2
    ):
        sumArmy = SearchUtils.Counter(0)
        countTiles = SearchUtils.Counter(0)
        map = simHost.sim.players[player].map
        sourceTile = map.GetTile(x, y)

        def countFunc(tile: Tile):
            if tile.player == player:
                sumArmy.add(tile.army)
                countTiles.add(1)
        SearchUtils.breadth_first_foreach(map, [sourceTile], radius, countFunc)

        armyPerTile = sumArmy.value / countTiles.value
        if armyPerTile > requiredAvgTileValue:
            self.fail(f'dist {radius} from {str(sourceTile)} had avg {armyPerTile:.1f} army per tile which exceeded {requiredAvgTileValue}. Had {sumArmy.value} army on {countTiles.value} tiles.')

    def assertCleanedUpTilesNear(
            self,
            simHost: GameSimulatorHost,
            player: int,
            x: int,
            y: int,
            radius: int,
            capturedWithinLastTurns: int = 15,
            requireCountCapturedInWindow: int = 10):
        countCaptured = SearchUtils.Counter(0)
        map = simHost.sim.sim_map
        sourceTile = map.GetTile(x, y)

        def countFunc(tile: Tile):
            if tile.player == player and tile.turn_captured > map.turn - capturedWithinLastTurns:
                countCaptured.add(1)
        SearchUtils.breadth_first_foreach(map, [sourceTile], radius, countFunc)

        if countCaptured.value < requireCountCapturedInWindow:
            self.fail(f'dist {radius} from {str(sourceTile)} only had {countCaptured.value} captured tiles, required {requireCountCapturedInWindow}.')

    def get_player_tile(self, x: int, y: int, sim: GameSimulator, player_index: int) -> Tile:
        player = sim.players[player_index]
        tile = player.map.GetTile(x, y)
        return tile

    def get_player_largest_tile(self, sim: GameSimulator, player_index: int) -> Tile:
        largest = None
        for tile in sim.sim_map.get_all_tiles():
            if tile.player == player_index and (largest is None or largest.army < tile.army):
                largest = tile
        return largest

    def render_sim_map_from_all_perspectives(self, sim):
        simMapViewInfo = ViewInfo(3, sim.sim_map.cols, sim.sim_map.rows)
        self.render_view_info(sim.sim_map, simMapViewInfo, 'Sim Map Raw')
        for player in sim.players:
            playerViewInfo = ViewInfo(3, player.map.cols, player.map.rows)
            self.render_view_info(player.map, playerViewInfo, f'p{player.index} view')

    def ensure_player_tiles_and_scores(
            self,
            map: MapBase,
            general: Tile,
            generalTileCount: int,
            generalTargetScore: int | None = None,
            enemyGeneral: Tile = None,
            enemyGeneralTileCount: int = None,
            enemyGeneralTargetScore: int = None,
            enemyCityCount: int = 1,
            respectPlayerVision: bool = False,
    ):
        """
        Leave enemy params empty to match the general values evenly (and create an enemy general opposite general)
        -1 means leave the map alone, keep whatever tiles and army amounts are already on the map
        """

        bannedEnemyTiles: typing.Set[Tile] = set()
        if respectPlayerVision:
            for tile in map.get_all_tiles():
                if tile.player == general.player:
                    for adj in tile.adjacents:
                        if adj.isObstacle:
                            continue
                        if adj.player == -1:
                            bannedEnemyTiles.add(adj)

        if enemyGeneral is None:
            enemyGeneral = map.generals[(general.player + 1) % 2]
        if enemyGeneral is None:
            enemyGeneral = self.generate_enemy_general_opposite_general(map, general)

        if enemyGeneralTargetScore is None:
            enemyGeneralTargetScore = generalTargetScore

        if enemyGeneralTileCount is None:
            enemyGeneralTileCount = generalTileCount

        enemyMap = self.get_from_general_weight_map(map, enemyGeneral)
        countTilesEnemy = SearchUtils.Counter(SearchUtils.count(map.pathableTiles, lambda tile: tile.player == enemyGeneral.player))
        countScoreEnemy = SearchUtils.Counter(enemyGeneral.army)
        countCitiesEnemy = SearchUtils.Counter(SearchUtils.count(map.pathableTiles, lambda tile: tile.player == enemyGeneral.player and (tile.isGeneral or tile.isCity)))

        newTiles = set()

        genDistMap = self.get_from_general_weight_map(map, general)
        countTilesGeneral = SearchUtils.Counter(
            SearchUtils.count(map.pathableTiles, lambda tile: tile.player == general.player))
        countScoreGeneral = SearchUtils.Counter(general.army)

        if enemyGeneralTileCount == -1:
            enemyGeneralTileCount = countTilesEnemy.value
        if enemyGeneralTargetScore == -1:
            enemyGeneralTargetScore = map.players[enemyGeneral.player].score

        if generalTileCount == -1:
            generalTileCount = countTilesGeneral.value
        if generalTargetScore == -1:
            generalTargetScore = map.players[general.player].score

        def generateTilesFunc(tile: Tile, dist: int):
            if tile == general or tile == enemyGeneral:
                return

            tileToGen = genDistMap[tile.x][tile.y]
            tileToOp = enemyMap[tile.x][tile.y]

            if tile.isObstacle and tile not in bannedEnemyTiles:
                countPlayerAdj = SearchUtils.count(tile.adjacents, lambda t: t.player == general.player)
                if countPlayerAdj == 0 and countCitiesEnemy.value < enemyCityCount and tileToOp < tileToGen:
                    tile.player = enemyGeneral.player
                    tile.army = 1
                    tile.isCity = True
                    tile.isMountain = False
                    tile.tile = enemyGeneral.player
                    countTilesEnemy.add(1)
                    countCitiesEnemy.add(1)
                    newTiles.add(tile)
                return

            if tile.isNeutral and not tile.isCity:
                if tileToGen < tileToOp:
                    if countTilesGeneral.value < generalTileCount:
                        tile.player = general.player
                        tile.army = 1
                        countTilesGeneral.add(1)
                        newTiles.add(tile)
                else:
                    if countTilesEnemy.value < enemyGeneralTileCount and tile not in bannedEnemyTiles:
                        tile.player = enemyGeneral.player
                        tile.army = 1
                        countTilesEnemy.add(1)
                        newTiles.add(tile)
            if tile.player == general.player:
                countScoreGeneral.add(tile.army)
            if tile.player == enemyGeneral.player:
                countScoreEnemy.add(tile.army)

        SearchUtils.breadth_first_foreach_dist(map, [general, enemyGeneral], 100, generateTilesFunc,
                                               skipFunc=lambda tile: tile.isObstacle, bypassDefaultSkip=True)

        if enemyGeneralTargetScore is not None and countScoreEnemy.value > enemyGeneralTargetScore:
            countScoreEnemy.value = countScoreEnemy.value - enemyGeneral.army + 1
            enemyGeneral.army = 1

        if enemyGeneralTargetScore is not None and countScoreEnemy.value > enemyGeneralTargetScore:
            raise AssertionError(f"countScoreEnemy.value {countScoreEnemy.value} > enemyGeneralTargetScore {enemyGeneralTargetScore}. Have to implement reducing the army on non-visible tiles from the snapshot here")

        iter = 0
        while enemyGeneralTargetScore is not None and countScoreEnemy.value < enemyGeneralTargetScore and iter < 100:
            for tile in newTiles:
                if tile.player == enemyGeneral.player and countScoreEnemy.value < enemyGeneralTargetScore:
                    countScoreEnemy.add(1)
                    tile.army += 1
            iter += 1

        while generalTargetScore is not None and countScoreGeneral.value < generalTargetScore:
            for tile in map.get_all_tiles():
                if tile.player == general.player and countScoreGeneral.value < generalTargetScore:
                    countScoreGeneral.add(1)
                    tile.army += 1

        scores: typing.List[None | Score] = [None for _ in map.players]
        scores[general.player] = Score(general.player, countScoreGeneral.value, countTilesGeneral.value, dead=False)
        scores[enemyGeneral.player] = Score(enemyGeneral.player, countScoreEnemy.value, countTilesEnemy.value, dead=False)

        map.update()
        map.clear_deltas_and_score_history()

    def generate_enemy_general_opposite_general(self, map: MapBase, general: Tile) -> Tile:
        map.generals[general.player] = general
        furthestTile = self.get_furthest_tile_from_general(map, general)
        furthestTile.player = (general.player + 1) % 2
        furthestTile.isGeneral = True
        map.generals[furthestTile.player] = furthestTile
        enemyGen = furthestTile
        return enemyGen

    def a_b_test(
            self,
            numRuns: int,
            configureA: typing.Callable[[EklipZBot], None],
            configureB: typing.Callable[[EklipZBot], None] | None = None,
            debugMode: bool = False,
            mapFile: str | typing.List[str] | None = None,
            debugModeTurnTime: float = 0.1,
            debugModeRenderAllPlayers: bool = False,
            noCities: bool | None = None
    ):
        """
        run numRuns games on a map flipping general spawns each time, and asserts that A beat B most of the time.
        Always outputs the final results at the end.
        Takes a config function for A and optional config function for B.
        If debugMode = True will attach a viewer to A.

        @param numRuns:
        @param configureA:
        @param configureB:
        @param debugMode:
        @param mapFile: If none, will cycle fairly between a set of symmetric maps.
        @param noCities: If True, all cities will be converted to mountains. By default it will be 50-50 whether the map has cities or not.
        @return:
        """
        mapFiles = [
            'SymmetricTestMaps/even_playground_map_small__left_right.txtmap',
            'SymmetricTestMaps/even_playground_map_small__top_left_bot_right.txtmap',
            'SymmetricTestMaps/even_playground_map_small__top_right_bot_left.txtmap',
        ]
        if isinstance(mapFile, str):
            mapFiles = [mapFile]
        elif isinstance(mapFile, list):
            mapFiles = mapFile

        curMapFile = mapFiles[0]

        minGameDurationToCount = 125

        aWins = 0
        bWins = 0
        for i in range(numRuns):
            a = i % 2
            b = (a + 1) % 2

            banCitiesThisIter = noCities

            # randomize maps every time we do a mirrored set of matches
            if a == 0:
                curMapFile = random.choice(mapFiles)
                if banCitiesThisIter is None:
                    banCitiesThisIter = random.choice([True, False])

            try:
                lastWinTurns = 0
                winner = -1
                while lastWinTurns < minGameDurationToCount:
                    self.stop_capturing_logging()
                    map, general, enemyGen = self.load_map_and_generals(curMapFile, 1, fill_out_tiles=False)
                    map.usernames[a] = 'a'
                    map.usernames[b] = 'b'
                    self.reset_map_to_just_generals(map)

                    if banCitiesThisIter:
                        for tile in map.get_all_tiles():
                            if tile.isCity:
                                map.convert_tile_to_mountain(tile)

                    self.enable_search_time_limits_and_disable_debug_asserts()

                    playerToRender = a
                    if debugMode and debugModeRenderAllPlayers:
                        playerToRender = -2
                    simHost = GameSimulatorHost(map, player_with_viewer=playerToRender)
                    aBot = simHost.get_bot(a)
                    bBot = simHost.get_bot(b)

                    configureA(aBot)
                    if configureB is not None:
                        configureB(bBot)

                    winner = simHost.run_sim(run_real_time=debugMode, turn_time=debugModeTurnTime)
                    lastWinTurns = simHost.sim.turn
                    if lastWinTurns < minGameDurationToCount:
                        self.begin_capturing_logging()
                        logging.info(f'replaying short game turns {simHost.sim.turn} (won by {"a" if winner == a else "b"}={winner})')
                        self.stop_capturing_logging()

                if a == winner:
                    aWins += 1
                elif b == winner:
                    bWins += 1
                else:
                    raise AssertionError(f"wtf, winner was {str(winner)}")
                self.begin_capturing_logging()
                logging.info(f'aWins: {aWins}, bWins: {bWins} (games {aWins + bWins})')
                self.stop_capturing_logging()
            except:
                self.begin_capturing_logging()
                logging.info(f'error: {traceback.format_exc()}')
                self.stop_capturing_logging()
                pass

        aIndicator = 'A--'
        if aWins > bWins:
            aIndicator = 'A++'

        self.begin_capturing_logging()
        msg = f'{aIndicator} | A won {aWins} times, B won {bWins} times out of {numRuns} games ({numRuns - aWins - bWins} errors?)'
        logging.info(msg)

        self.assertGreater(aWins, bWins, msg)
