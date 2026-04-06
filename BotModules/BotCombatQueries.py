import typing

import SearchUtils
import logbook
from Army import Army
from base.client.map import Tile


class BotCombatQueries:
    @staticmethod
    def find_large_tiles_near(
            bot,
            fromTiles: typing.List[Tile],
            distance: int,
            forPlayer=-2,
            allowGeneral: bool = True,
            limit: int = 5,
            minArmy: int = 10,
            addlFilterFunc: typing.Callable[[Tile, int], bool] | None = None,
            allowTeam: bool = False
    ) -> typing.List[Tile]:
        largeTilesNearTargets = []
        if forPlayer == -2:
            forPlayer = bot.general.player

        forPlayers = [forPlayer]
        if allowTeam:
            forPlayers = bot.opponent_tracker.get_team_players_by_player(forPlayer)

        def tile_finder(tile: Tile, dist: int):
            if (
                    tile.player in forPlayers
                    and tile.army > minArmy
                    and (addlFilterFunc is None or addlFilterFunc(tile, dist))
                    and (not tile.isGeneral or allowGeneral)
            ):
                largeTilesNearTargets.append(tile)

        SearchUtils.breadth_first_foreach_dist_fast_incl_neut_cities(bot._map, fromTiles, distance, foreachFunc=tile_finder)
        largeTilesNearTargets = [t for t in sorted(largeTilesNearTargets, key=lambda t: t.army, reverse=True)]
        return largeTilesNearTargets[0:limit]

    @staticmethod
    def get_largest_tiles_as_armies(bot, player: int, limit: int) -> typing.List[Army]:
        player = bot._map.players[player]

        def sortFunc(t: Tile) -> float:
            pw = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix[t]
            dist = 100
            if pw is not None:
                dist = pw.distance
            else:
                logbook.error(f'pathway none again for {str(t)}')
            return (t.army - 1) / (dist + 5)

        tiles = sorted(player.tiles, key=sortFunc, reverse=True)
        armies = [bot.get_army_at(t, no_expected_path=True) for t in tiles[0:limit] if t.army > 1]
        return armies

    @staticmethod
    def sum_friendly_army_near_or_on_tiles(bot, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        if player is None:
            player = bot._map.player_index
        armyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile):
            if bot._map.is_tile_on_team_with(tile, player):
                armyNear.add(tile.army - 1)

        SearchUtils.breadth_first_foreach(bot._map, tiles, distance, counterFunc)
        value = armyNear.value
        return value

    @staticmethod
    def count_enemy_territory_near_tile(bot, startTile: Tile, distance: int = 2) -> int:
        enemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile) -> bool:
            tileIsNeutAndNotEnemyTerritory = tile.isNeutral and (tile.visible or bot.territories.territoryMap[tile] != bot.targetPlayer)
            if not tileIsNeutAndNotEnemyTerritory and bot._map.is_tile_enemy(tile):
                enemyNear.add(1)
            return tile.isObstacle and tile != startTile

        SearchUtils.breadth_first_foreach(bot._map, [startTile], distance, counterFunc, noLog=True, bypassDefaultSkip=True)
        value = enemyNear.value
        return value
