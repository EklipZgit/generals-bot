import logbook

import SearchUtils
from Army import Army
from base.client.map import Tile

class BotEventHandlers:
    @staticmethod
    def handle_city_found(bot, tile):
        logbook.info(f"EH: City found handler! City {str(tile)}")
        bot.armyTracker.add_need_to_track_city(tile)
        bot.territories.needToUpdateAroundTiles.add(tile)
        if tile.player != -1:
            bot.board_analysis.should_rescan = True
        return None

    @staticmethod
    def handle_tile_captures(bot, tile: Tile):
        logbook.info(
            f"EH: Tile captured! Tile {repr(tile)}, oldOwner {tile.delta.oldOwner} newOwner {tile.delta.newOwner}")
        bot.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity:
            bot.armyTracker.add_need_to_track_city(tile)

            if tile.delta.oldOwner == -1 or tile.delta.newOwner == -1:
                bot.board_analysis.should_rescan = True
                bot._map.distance_mapper.recalculate()
                bot.cityAnalyzer.reset_reachability()
                if tile.delta.newOwner == -1:
                    return

        if not tile.delta.gainedSight:
            bot.armyTracker.notify_seen_player_tile(tile)

        if tile.delta.oldOwner == bot.general.player or tile.delta.oldOwner in bot._map.teammates:
            if not bot._map.is_tile_friendly(tile):
                murderer = bot._map.players[tile.player]

                tileScore = 10
                if bot.territories.territoryMap[tile] == tile.delta.newOwner:
                    tileScore = 5
                elif bot._map.is_player_on_team_with(bot.territories.territoryMap[tile], bot.general.player):
                    tileScore = 30

                if tile.isCity:
                    tileScore += 5
                    tileScore = tileScore * 10

                murderer.aggression_factor += tileScore

        return None

    @staticmethod
    def handle_player_captures(bot, capturee: int, capturer: int):
        logbook.info(
            f"EH: Player captured! capturee {bot._map.usernames[capturee]} ({capturee}) capturer {bot._map.usernames[capturer]} ({capturer})")
        for army in list(bot.armyTracker.armies.values()):
            if army.player == capturee:
                logbook.info(f"EH:   scrapping dead players army {str(army)}")
                bot.armyTracker.scrap_army(army, scrapEntangled=True)

        bot.history.captured_player(bot._map.turn, capturee, capturer)

        if capturer == bot.general.player:
            logbook.info(f"setting lastPlayerKilled to {capturee}")
            bot.lastPlayerKilled = capturee
            playerGen = bot._map.players[capturee].general
            bot.launchPoints.append(playerGen)

        bot.trigger_player_capture_re_eval = True

        return None

    @staticmethod
    def reevaluate_after_player_capture(bot):
        if bot._map.remainingPlayers <= 3:
            if not bot.opponent_tracker.winning_on_economy(byRatio=0.8):
                bot.viewInfo.add_info_line("not even on economy, going all in effective immediately")
                bot.is_all_in_losing = True
                bot.all_in_losing_counter = 300

    @staticmethod
    def handle_tile_deltas(bot, tile):
        logbook.info(f"EH: Tile delta handler! Tile {repr(tile)} delta {tile.delta.armyDelta}")
        return None

    @staticmethod
    def handle_tile_discovered(bot, tile):
        logbook.info(f"EH: Tile discovered handler! Tile {repr(tile)}")
        bot.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity and tile.player != -1:
            bot.board_analysis.should_rescan = True
            bot._map.distance_mapper.recalculate()
        if tile.isCity and tile.player == -1 and tile.delta.oldOwner != -1:
            bot._map.distance_mapper.recalculate()

        if tile.player >= 0:
            player = bot._map.players[tile.player]
            if len(player.tiles) < 4 and tile.player == bot.targetPlayer and bot.curPath:
                bot.viewInfo.add_info_line("killing current path because JUST discovered player...")
                bot.curPath = None

        return None

    @staticmethod
    def handle_tile_vision_change(bot, tile: Tile):
        logbook.info(f"EH: Tile vision change handler! Tile {repr(tile)}")

        bot.territories.needToUpdateAroundTiles.add(tile)
        if tile.visible:
            bot.territories.revealed_tile(tile)

        if tile.delta.gainedSight:
            bot.armyTracker.notify_seen_player_tile(tile)

        if tile.isCity and tile.delta.oldOwner != tile.player and tile.delta.gainedSight:
            if bot.curPath is not None and bot.curPath.tail.tile == tile:
                bot.viewInfo.add_info_line(f'reset curPath because gained vision of a city whose player is now different.')
                bot.curPath = None

            if tile.delta.oldOwner == -1 or tile.player == -1:
                bot._map.distance_mapper.recalculate()

        if tile.delta.gainedSight and tile.player >= 0:
            bot.opponent_tracker.notify_player_tile_revealed(tile)
            if len(bot._map.players[tile.player].tiles) < 3:
                if bot._map.turn > 15:
                    allNew = True
                    for otherTile in bot._map.players[tile.player].tiles:
                        if not otherTile.delta.gainedSight:
                            allNew = False

                    for adj in tile.adjacents:
                        if adj.player in bot._map.teammates and adj.delta.armyDelta != 0:
                            allNew = False

                    if allNew:
                        bot._should_recalc_tile_islands = True
        elif tile.delta.lostSight and tile.player >= 0:
            bot.opponent_tracker.notify_player_tile_vision_lost(tile)

        if tile.isMountain:
            if bot.curPath is not None and tile in bot.curPath.tileSet:
                bot.curPath = None
            if tile.delta.oldOwner != -1:
                bot.armyTracker.add_need_to_track_city(tile)
                bot.viewInfo.add_info_line(f'FOG CITY {repr(tile)} WAS WRONG, FORCING RESCANS AND PLAYER PATH RECALCS')
                bot.target_player_gather_path = None
                bot.target_player_gather_targets = None
                bot.shortest_path_to_target_player = None
                bot.board_analysis.should_rescan = True

        if tile.visible and tile.isCity and tile.player == -1 and tile.delta.oldOwner != -1:
            if bot.curPath is not None and tile in bot.curPath.tileSet:
                bot.viewInfo.add_info_line(f'Ceasing curPath because target city was actually neutral.')
                bot.curPath = None

        if tile.isCity:
            bot.armyTracker.add_need_to_track_city(tile)

        return None

    @staticmethod
    def handle_army_moved(bot, army: Army):
        tile = army.tile
        logbook.info(f"EH: Army Moved handler! Tile {repr(tile)}")
        bot.armies_moved_this_turn.append(tile)
        player = bot._map.players[tile.player]
        player.last_seen_move_turn = bot._map.turn
        if army.path.tail.prev is not None and not army.path.tail.prev.tile.was_visible_last_turn() and army.tile.visible:
            bot.opponent_tracker.notify_emerged_army(
                army.path.tail.prev.tile,
                emergingPlayer=army.player,
                emergenceAmount=0 - army.path.tail.prev.tile.delta.armyDelta)
        bot.territories.needToUpdateAroundTiles.add(tile)
        bot.territories.revealed_tile(tile)
        return None

    @staticmethod
    def clear_fog_armies_around(bot, enemyGeneral: Tile):

        def fog_army_clear_func(tile: Tile):
            if not tile.visible and tile in bot.armyTracker.armies:
                army = bot.armyTracker.armies[tile]
                if army.player == enemyGeneral.player:
                    bot.armyTracker.scrap_army(army, scrapEntangled=False)

        SearchUtils.breadth_first_foreach(bot._map, [enemyGeneral], maxDepth=7, foreachFunc=fog_army_clear_func)
