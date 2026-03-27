import typing

import SearchUtils
from base.client.map import Tile


class BotStateQueries:
    @staticmethod
    def is_all_in(bot):
        return bot.is_all_in_losing or bot.is_all_in_army_advantage or bot.all_in_city_behind

    @staticmethod
    def get_player_army_amount_on_path(bot, path, player, startIdx=0, endIdx=1000):
        value = 0
        idx = 0
        pathNode = path.start
        while pathNode is not None:
            if bot._map.is_player_on_team_with(pathNode.tile.player, player) and startIdx <= idx <= endIdx:
                value += (pathNode.tile.army - 1)
            pathNode = pathNode.next
            idx += 1
        return value

    @staticmethod
    def get_target_army_inc_adjacent_enemy(bot, tile):
        sumAdj = 0
        for adj in tile.adjacents:
            if bot._map.is_tile_enemy(adj):
                sumAdj += adj.army - 1
        armyToSearch = sumAdj
        return armyToSearch

    @staticmethod
    def parse_tile_str(bot, tileStr: str):
        xStr, yStr = tileStr.split(',')
        return bot._map.GetTile(int(xStr), int(yStr))

    @staticmethod
    def parse_bool(bot, boolStr: str) -> bool:
        return boolStr.lower().strip() == "true"

    @staticmethod
    def str_tiles(bot, tiles) -> str:
        return '|'.join([str(t) for t in tiles])

    @staticmethod
    def get_army_at(bot, tile: Tile, no_expected_path: bool = False):
        return bot.armyTracker.get_or_create_army_at(tile, skip_expected_path=no_expected_path)

    @staticmethod
    def get_army_at_x_y(bot, x: int, y: int):
        tile = bot._map.GetTile(x, y)
        return BotStateQueries.get_army_at(bot, tile)

    @staticmethod
    def get_n_closest_team_tiles_near(bot, nearTiles: typing.List[Tile], player: int, distance: int, limit: int, includeNeutral: bool = False) -> typing.List[Tile]:
        tiles = set(nearTiles)

        def nearbyTileAdder(tile: Tile) -> bool:
            if len(tiles) > limit:
                return True

            if bot._map.is_tile_on_team_with(tile, player) or (includeNeutral and tile.isNeutral and tile.army == 0 and not tile.isObstacle):
                tiles.add(tile)

            return False

        SearchUtils.breadth_first_foreach(bot._map, nearTiles, distance, foreachFunc=nearbyTileAdder)

        return [t for t in tiles]
