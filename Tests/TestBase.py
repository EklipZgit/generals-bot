import logging
import typing
import unittest

import EarlyExpandUtils
import SearchUtils
from Path import Path
from Sim.TextMapLoader import TextMapLoader
from ViewInfo import ViewInfo, PathColorer
from base.client.map import MapBase, Tile, Score, Player, TILE_FOG, TILE_OBSTACLE
from base.viewer import GeneralsViewer
from bot_ek0x45 import EklipZBot


class TestBase(unittest.TestCase):
    # __test__ = False
    def _set_up_log_stream(self):
        logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    def _initialize(self):
        self._set_up_log_stream()
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

    def load_map_and_general(self, mapFilePath: str, turn: int, player_index: int = -1) -> typing.Tuple[MapBase, Tile]:
        try:
            board = TextMapLoader.load_map_from_file(mapFilePath)
            data = TextMapLoader.load_data_from_file(mapFilePath)

            map = self.get_test_map(board, turn=turn)
            general = next(t for t in map.pathableTiles if t.isGeneral and (t.player == player_index or player_index == -1))
            map.player_index = general.player
            map.generals[general.player] = general

            self.load_map_data(map, general, data)

            return map, general
        except:
            logging.info(f'failed to load file {mapFilePath}')
            raise

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
        distMap = SearchUtils.build_distance_map(map, [general])
        if negate:
            for x in range(len(distMap)):
                for y in range(len(distMap[0])):
                    distMap[x][y] = 0 - distMap[x][y]
        return distMap

    def get_opposite_general_distance_map(self, map: MapBase, general: Tile, negate: bool = False):
        furthestTile = self.get_furthest_tile_from_general(map, general)

        furthestMap = SearchUtils.build_distance_map(map, [furthestTile])
        if negate:
            for x in range(len(furthestMap)):
                for y in range(len(furthestMap[0])):
                    furthestMap[x][y] = 0 - furthestMap[x][y]

        return furthestMap

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
                    PathColorer(path, r, g, b, alpha=10, alphaDecreaseRate=5, alphaMinimum=10))
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

    def get_player_char_index_map(self):
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

    def load_map_data(self, map: MapBase, general: Tile, data: typing.Dict[str, str]):
        playerCharMap = self.get_player_char_index_map()
        for player in map.players:
            char, index = playerCharMap[player.index]

            tileKey = f'{char}Tiles'
            if tileKey in data:
                player.tileCount = int(data[tileKey])

            scoreKey = f'{char}Score'
            if scoreKey in data:
                player.score = int(data[scoreKey])

    def disable_search_time_limits_and_enable_debug_asserts(self):
        SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = True
        EarlyExpandUtils.DEBUG_ASSERTS = True

    def enable_search_time_limits_and_disable_debug_asserts(self):
        SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = False
        EarlyExpandUtils.DEBUG_ASSERTS = False


    def reset_map(self, map: MapBase, turn: int = 16):
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

    def reset_map_with_enemy_general_discovered(self, map: MapBase, general: Tile) -> Tile:
        """
        Resets the map and returns the enemy general location (if one existed) or creates one at a far spawn from current general.
        Always makes player general become player 0, and enemy general become player 1

        @param map:
        @param general:
        @return:
        """
        self.reset_map(map, turn=1)

        enemyGen: Tile = None
        if map.generals[0] is None or map.generals[1] is None:
            map.generals[general.player] = general
            furthestTile = self.get_furthest_tile_from_general(map, general)
            furthestTile.player = (general.player + 1) % 2
            furthestTile.isGeneral = True
            map.generals[furthestTile.player] = furthestTile
            enemyGen = furthestTile
        else:
            enemyGen = next(filter(lambda g: g is not None and g != general, map.generals))

        enemyGen.army = general.army

        general.player = 0
        enemyGen.player = 1

        map.generals = [None for i in range(2)]
        map.usernames = ['a', 'b']
        map.generals[0] = general
        map.generals[1] = enemyGen
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
        enemyGeneral = self.reset_map_with_enemy_general_discovered(map, general)

        enemyMap = self.get_from_general_weight_map(map, enemyGeneral)
        genDistMap = self.get_from_general_weight_map(map, general)

        countTilesEnemy = SearchUtils.Counter(1)
        countTilesGeneral = SearchUtils.Counter(1)
        countScoreEnemy = SearchUtils.Counter(enemyGeneral.army)
        countScoreGeneral = SearchUtils.Counter(general.army)
        def generateTilesFunc(tile: Tile, dist: int):
            if tile.isObstacle:
                return
            if tile == general or tile == enemyGeneral:
                return

            tileToGen = genDistMap[tile.x][tile.y]
            tileToOp = enemyMap[tile.x][tile.y]
            if tileToGen < tileToOp:
                if countTilesGeneral.value < tileAmount:
                    tile.player = general.player
                    tile.army = armyOnTiles
                    countTilesGeneral.add(1)
                    countScoreGeneral.add(tile.army)
            else:
                if countTilesEnemy.value < tileAmount:
                    tile.player = enemyGeneral.player
                    tile.army = armyOnTiles
                    countTilesEnemy.add(1)
                    countScoreEnemy.add(tile.army)

        SearchUtils.breadth_first_foreach_dist(map, [general, enemyGeneral], 100, generateTilesFunc, skipFunc=lambda tile: tile.isCity and tile.isNeutral)

        scores = []
        scores.append(Score(general.player, countScoreGeneral.value, countTilesGeneral.value, dead=False))
        scores.append(Score(enemyGeneral.player, countScoreEnemy.value, countTilesEnemy.value, dead=False))
        scores = sorted(scores, key=lambda score: score.player)

        map.update_scores(scores)
        map.update()

        return enemyGeneral

    def get_view_info(self, map: MapBase) -> ViewInfo:
        return ViewInfo(1, map.cols, map.rows)

    def render_view_info(self, map: MapBase, viewInfo: ViewInfo, infoString: str):
        viewer = GeneralsViewer(infoString, cell_width=45, cell_height=45)
        viewer.ekBot = EklipZBot(10)
        viewer.ekBot._map = map
        viewer.noLog = True
        viewer.ekBot.viewInfo = viewInfo
        viewer.ekBot.viewInfo.readyToDraw = True
        viewer.ekBot.viewInfo.infoText = infoString
        viewer.updateGrid(map)
        viewer.run_main_viewer_loop()


