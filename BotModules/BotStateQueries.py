from __future__ import annotations

import typing

import BotModules as BM
import logbook
import SearchUtils
from base.client.map import Tile
import typing


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot

class BotStateQueries:
    @staticmethod
    def is_all_in(bot: EklipZBot):
        return bot.is_all_in_losing or bot.is_all_in_army_advantage or bot.all_in_city_behind

    @staticmethod
    def is_tile_enemy(bot: EklipZBot, tile: Tile) -> bool:
        """Check if a tile belongs to an enemy player."""
        return tile is not None and tile.player != -1 and tile.player != bot.general.player and bot._map.is_tile_enemy(tile)

    @staticmethod
    def is_ffa_exclusive_targeting_active(bot: EklipZBot) -> bool:
        """
        Tests/test_FFA.py::test_should_not_attack_unprovoked_enemies_in_early_ffa
        Tests/test_FFA.py::test_should_exclusively_attack_player_that_attacks_us_in_early_ffa
        In a non-dominant FFA where multiple distinct enemy players have revealed territory, the bot
        must refuse to opportunistically attack: only players actively attacking us
        (is_player_aggressive / aggression_factor > 120), players who left the game, or a single
        enemy we can clearly kill (which becomes the exclusive locked target) may be attacked.
        Tiles of unattackable players may still be CROSSED only as part of a path to attack the
        locked target; expansion/gather/leaf/city-kill moves may never capture them.
        @param bot:
        @return:
        """
        if not BotStateQueries.is_still_ffa_and_non_dominant(bot):
            return False

        revealedCount = 0
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates:
                continue
            if len(player.tiles) > 0:
                revealedCount += 1

        return revealedCount >= 2

    @staticmethod
    def get_ffa_clear_kill_enemy_player(bot: EklipZBot) -> int:
        """
        Returns the one enemy player we can clearly kill right now while exclusive targeting is
        active: their general location is known, we have a decisive standing-army advantage over
        them, and their general is reachable within ~12 turns. -1 if nobody qualifies.
        @param bot:
        @return:
        """
        bestPlayer = -1
        bestArmyRatio = 1.3
        ourStats = bot._map.get_team_stats(bot._map.player_index)
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            enGen = bot._map.generals[player.index]
            if enGen is None or not enGen.isGeneral:
                continue
            enStats = bot._map.get_team_stats(player.index)
            if enStats.standingArmy <= 0:
                continue
            armyRatio = ourStats.standingArmy / enStats.standingArmy
            genDist = bot._map.get_distance_between(bot.general, enGen)
            if genDist > 12:
                continue
            if armyRatio >= bestArmyRatio:
                bestArmyRatio = armyRatio
                bestPlayer = player.index
        return bestPlayer

    @staticmethod
    def update_ffa_exclusive_target_lock(bot: EklipZBot) -> None:
        """
        Maintains bot.ffa_exclusive_target_lock: the enemy player we are committed to attacking
        exclusively while is_ffa_exclusive_targeting_active holds. Sticky per
        Tests/test_FFA.py::test_should_exclusively_attack_player_that_attacks_us_in_early_ffa:
        once locked we stay on that player until they die or the FFA-pacifist gate ends, so
        aggression_factor decay mid-war cannot release the lock. The strongest current aggressor
        is preferred; otherwise a clear-kill candidate is locked so we target that player only.
        @param bot:
        @return:
        """
        if not BotStateQueries.is_ffa_exclusive_targeting_active(bot):
            if bot.ffa_exclusive_target_lock != -1:
                logbook.info(f'FFA_EXCL unlock p{bot.ffa_exclusive_target_lock} ({bot._map.usernames[bot.ffa_exclusive_target_lock]}): pacifist gate ended')
                bot.ffa_exclusive_target_lock = -1
            return

        if bot.ffa_exclusive_target_lock != -1:
            if bot._map.players[bot.ffa_exclusive_target_lock].dead:
                logbook.info(f'FFA_EXCL unlock p{bot.ffa_exclusive_target_lock} ({bot._map.usernames[bot.ffa_exclusive_target_lock]}): locked player died')
                bot.ffa_exclusive_target_lock = -1
            else:
                return

        bestAggro = -1
        bestAggroFactor = 120
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            if BM.BotTimings.BotTimings.is_player_aggressive(bot, player.index) and player.aggression_factor > bestAggroFactor:
                bestAggroFactor = player.aggression_factor
                bestAggro = player.index
        if bestAggro != -1:
            bot.ffa_exclusive_target_lock = bestAggro
            logbook.info(f'FFA_EXCL locked p{bestAggro} ({bot._map.usernames[bestAggro]}): attacking us, aggro {bestAggroFactor}')
            return

        clearKill = BotStateQueries.get_ffa_clear_kill_enemy_player(bot)
        if clearKill != -1:
            bot.ffa_exclusive_target_lock = clearKill
            logbook.info(f'FFA_EXCL locked p{clearKill} ({bot._map.usernames[clearKill]}): clear kill candidate')

    @staticmethod
    def get_ffa_unattackable_players(bot: EklipZBot) -> typing.Set[int] | None:
        """
        Returns the set of revealed enemy player indexes whose tiles may NOT be attacked while
        is_ffa_exclusive_targeting_active holds, or None when the restriction does not apply.
        Attackable: the exclusive locked target, players actively attacking us, and players that
        left the game (free kills per Tests/test_FFA.py FFA pacifism tests).
        @param bot:
        @return:
        """
        if not BotStateQueries.is_ffa_exclusive_targeting_active(bot):
            return None

        attackable = set()
        if bot.ffa_exclusive_target_lock != -1:
            attackable.add(bot.ffa_exclusive_target_lock)
        afkPlayers = BM.BotTargeting.BotTargeting.get_afk_players(bot)
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            if player.leftGame or player in afkPlayers or BM.BotTimings.BotTimings.is_player_aggressive(bot, player.index):
                attackable.add(player.index)

        unattackable = set()
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            if player.index not in attackable:
                unattackable.add(player.index)
        return unattackable

    @staticmethod
    def get_ffa_unattackable_tiles(bot: EklipZBot) -> typing.Set[Tile]:
        """
        All tiles currently owned by get_ffa_unattackable_players. For negativeTiles/skipTiles
        inputs of non-attack searches (expansion plans, econ gathers, leaf captures) so they can
        neither capture nor path through unattackable enemy land. Empty set when inactive.
        @param bot:
        @return:
        """
        unattackable = BotStateQueries.get_ffa_unattackable_players(bot)
        if not unattackable:
            return set()
        return set(t for t in bot._map.pathable_tiles if t.player in unattackable)

    @staticmethod
    def is_tile_ffa_unattackable(bot: EklipZBot, tile: Tile) -> bool:
        """
        @param bot:
        @param tile:
        @return: True when tile belongs to a revealed enemy we may not attack under FFA exclusive targeting.
        """
        if tile is None or tile.player < 0:
            return False
        unattackable = BotStateQueries.get_ffa_unattackable_players(bot)
        return unattackable is not None and tile.player in unattackable

    @staticmethod
    def is_still_ffa_and_non_dominant(bot: EklipZBot) -> bool:
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
    def get_intergeneral_analysis(bot: EklipZBot):
        return bot.board_analysis.intergeneral_analysis

    @staticmethod
    def get_player_army_amount_on_path(bot: EklipZBot, path, player: int, startIdx=0, endIdx=1000):
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
    def get_player_army_amount_on_tiles(bot: EklipZBot, tiles: typing.Iterable[Tile], player: int):
        value = 0
        for tile in tiles:
            if bot._map.is_player_on_team_with(tile.player, player):
                value += (tile.army - 1)
        return value

    @staticmethod
    def get_target_army_inc_adjacent_enemy(bot: EklipZBot, tile) -> int:
        sumAdj = 0
        for adj in tile.adjacents:
            if BotStateQueries.is_tile_enemy(bot, adj):
                sumAdj += adj.army - 1
        armyToSearch = sumAdj
        return armyToSearch

    @staticmethod
    def get_target_army_inc_adjacent_enemy_and_tiles(bot: EklipZBot, tile) -> typing.Tuple[int, typing.Set[Tile]]:
        sumAdj = 0
        adjTiles = set()
        for adj in tile.adjacents:
            if BotStateQueries.is_tile_enemy(bot, adj):
                if adj.army > 1:
                    sumAdj += adj.army - 1
                    adjTiles.add(adj)
        armyToSearch = sumAdj
        return armyToSearch, adjTiles

    @staticmethod
    def parse_tile_str(bot: EklipZBot, tileStr: str):
        xStr, yStr = tileStr.split(',')
        return bot._map.GetTile(int(xStr), int(yStr))

    @staticmethod
    def parse_bool(bot: EklipZBot, boolStr: str) -> bool:
        return boolStr.lower().strip() == "true"

    @staticmethod
    def str_tiles(bot: EklipZBot, tiles) -> str:
        return '|'.join([str(t) for t in tiles])

    @staticmethod
    def get_army_at(bot: EklipZBot, tile: Tile, no_expected_path: bool = False):
        return bot.armyTracker.get_or_create_army_at(tile, skip_expected_path=no_expected_path)

    @staticmethod
    def get_army_at_x_y(bot: EklipZBot, x: int, y: int):
        tile = bot._map.GetTile(x, y)
        return BotStateQueries.get_army_at(bot, tile)

    @staticmethod
    def get_n_closest_team_tiles_near(bot: EklipZBot, nearTiles: typing.List[Tile], player: int, distance: int, limit: int, includeNeutral: bool = False) -> typing.List[Tile]:
        tiles = set(nearTiles)

        def nearbyTileAdder(tile: Tile) -> bool:
            if len(tiles) > limit:
                return True

            if bot._map.is_tile_on_team_with(tile, player) or (includeNeutral and tile.isNeutral and tile.army == 0 and not tile.isObstacle):
                tiles.add(tile)

            return False

        SearchUtils.breadth_first_foreach(bot._map, nearTiles, distance, foreachFunc=nearbyTileAdder)

        return [t for t in tiles]


BM.BotStateQueries = BotStateQueries
