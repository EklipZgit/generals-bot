import typing

import SearchUtils
from base.client.map import Tile


class BotStateQueries:
    @staticmethod
    def is_all_in(bot):
        return bot.is_all_in_losing or bot.is_all_in_army_advantage or bot.all_in_city_behind

    @staticmethod
    def is_still_ffa_and_non_dominant(bot) -> bool:
        isFfa = False
        if bot._map.remainingPlayers > 2 and not bot._map.is_2v2:
            isFfa = True

        if not isFfa:
            return False

        dominating = 0
        nearEven = bot._map.remainingPlayers - 1
        dominatedBy = 0
        for player in bot._map.players:
            if player == bot.general.player:
                continue

            if bot.opponent_tracker.winning_on_army(byRatio=1.2, againstPlayer=player.index, offset=-10, useFullArmy=True):
                dominating += 1
                nearEven -= 1
            elif not bot.opponent_tracker.winning_on_army(byRatio=0.9, againstPlayer=player.index, useFullArmy=True):
                dominatedBy += 1
                nearEven -= 1

        if dominating > dominatedBy:
            return False

        return True

    @staticmethod
    def get_intergeneral_analysis(bot):
        return bot.board_analysis.intergeneral_analysis

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
            if BotStateQueries.is_tile_enemy(bot, adj):
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
