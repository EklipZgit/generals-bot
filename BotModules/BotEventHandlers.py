from __future__ import annotations

import logbook

import SearchUtils
from Army import Army
from base.client.map import Tile, GeneralTrade
import typing


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot

class BotEventHandlers:
    @staticmethod
    def handle_general_trade(bot: EklipZBot) -> None:
        """
        Rebinds all bot state that depends on our general's identity/location
        after a mutual general capture (general trade) was detected in
        MapBase.update. Called at the start of init_turn, BEFORE any
        general-dependent calculations, so every analyzer sees the NEW
        general this turn. Never re-runs initialize_from_map_for_first_time
        (that would duplicate callbacks/rebuild everything) and never touches
        unrelated third players.
        Tests: Tests/test_GeneralTrade.py test_sim__general_trade__bot_fog_state.
        """
        trade = bot._map.general_trade
        newGen = bot._map.generals[bot._map.player_index]
        logbook.info(f'EH: General trade handler! Old gen {str(trade.old_general)} <-> new gen {str(newGen)} vs p{trade.opponent}')

        bot.general = newGen
        bot.player = bot._map.players[bot._map.player_index]
        bot.armyTracker.general = newGen
        if bot.cityAnalyzer is not None:
            bot.cityAnalyzer.general = newGen
            bot.cityAnalyzer.reset_reachability()
        if bot.board_analysis is not None:
            bot.board_analysis.general = newGen
            bot.board_analysis.general_distances = bot._map.distance_mapper.get_tile_dist_matrix(newGen)
            # the defense anchor must point at a live general, not dangle None
            # through consumers before a rescan re-establishes it
            bot.board_analysis.central_defense_point = newGen
            bot.board_analysis.should_rescan = True
        bot._gen_distances = bot._map.distance_mapper.get_tile_dist_matrix(newGen)
        bot._ally_distances = None

        # the traded enemy's general location is now KNOWN (our old general
        # tile); re-point the expected-location field immediately so nothing
        # targets our own new gen tile instead this turn
        if bot.targetPlayer == trade.opponent:
            enemyGen = bot._map.generals[trade.opponent]
            if enemyGen is not None and enemyGen.isGeneral:
                bot.targetPlayerExpectedGeneralLocation = enemyGen
        # stale alternative-gen-position distance caches carry the OLD
        # locations for the traded pair; clear them so they rebuild
        for tradedIdx in (trade.player, trade.opponent):
            if bot._alt_en_gen_position_distances[tradedIdx] is not None:
                bot._alt_en_gen_position_distances[tradedIdx] = None

        # invalidate general-dependent cached paths/plans that pointed at the
        # old general's location
        bot.curPath = None
        bot.curPathPrio = -1
        bot.shortest_path_to_target_player = None
        bot.target_player_gather_path = None
        bot.target_player_gather_targets = set()
        bot.general_safe_func_set = {}
        bot.threat_kill_path = None
        bot.launchPoints = [newGen]
        return None

    @staticmethod
    def handle_observer_general_trade(bot: EklipZBot, trade: GeneralTrade) -> None:
        """
        Reconciles bot-level spatial caches for a general trade between two
        OTHER players: territory labels/distances exchange between the pair,
        alternate enemy-general position guesses swap, the target's expected
        general location re-points to the swapped known general (or the other
        side's stored candidate), and general-dependent path caches reset.
        The real player identities, targetPlayer index, aggression and all
        behavioral stats stay untouched; our own general is never rebound.
        Tests: Tests/test_FfaGeneralTrade.py
        """
        pA, pB = trade.player, trade.opponent
        logbook.info(f'EH: Observed general trade handler p{pA} <-> p{pB}')

        # territory ownership labels exchange on every tile they claim
        territoryMap = bot.territories.territoryMap
        for idx in range(len(territoryMap.raw)):
            if territoryMap.raw[idx] == pA:
                territoryMap.raw[idx] = pB
            elif territoryMap.raw[idx] == pB:
                territoryMap.raw[idx] = pA
        bot.territories.territoryDistances[pA], bot.territories.territoryDistances[pB] = (
            bot.territories.territoryDistances[pB], bot.territories.territoryDistances[pA])
        # singleton teams: the team distance matrix is per-team but only
        # meaningful for the swapped players - exchange the entries
        teamA = bot._map.team_ids_by_player_index[pA] if pA < len(bot._map.team_ids_by_player_index) else -1
        teamB = bot._map.team_ids_by_player_index[pB] if pB < len(bot._map.team_ids_by_player_index) else -1
        if (teamA >= 0 and teamB >= 0 and teamA < len(bot.territories.territoryTeamDistances)
                and teamB < len(bot.territories.territoryTeamDistances)):
            bot.territories.territoryTeamDistances[teamA], bot.territories.territoryTeamDistances[teamB] = (
                bot.territories.territoryTeamDistances[teamB], bot.territories.territoryTeamDistances[teamA])

        # alternate enemy-general candidate lists swap between the pair
        if pA < len(bot.alt_en_gen_positions) and pB < len(bot.alt_en_gen_positions):
            bot.alt_en_gen_positions[pA], bot.alt_en_gen_positions[pB] = (
                bot.alt_en_gen_positions[pB], bot.alt_en_gen_positions[pA])
        for tradedIdx in (pA, pB):
            if tradedIdx < len(bot._alt_en_gen_position_distances) and bot._alt_en_gen_position_distances[tradedIdx] is not None:
                bot._alt_en_gen_position_distances[tradedIdx] = None

        # generalApproximations entries embed the player index - remap pairs
        for i, entry in enumerate(bot.generalApproximations):
            dist, weight, entryPlayer, entryTile = entry
            if entryPlayer == pA:
                bot.generalApproximations[i] = (dist, weight, pB, entryTile)
            elif entryPlayer == pB:
                bot.generalApproximations[i] = (dist, weight, pA, entryTile)

        # target expected general location: if the target is one of the
        # traded pair, point at the swapped KNOWN general ref, else the other
        # side's stored candidate; never rebind our own general
        if bot.targetPlayer in (pA, pB):
            knownGen = bot._map.generals[bot.targetPlayer]
            if knownGen is not None and knownGen.isGeneral:
                bot.targetPlayerExpectedGeneralLocation = knownGen
            elif bot.alt_en_gen_positions[bot.targetPlayer]:
                bot.targetPlayerExpectedGeneralLocation = bot.alt_en_gen_positions[bot.targetPlayer][0]

        # invalidate general-dependent cached paths/plans for the traded pair
        bot.curPath = None
        bot.curPathPrio = -1
        bot.shortest_path_to_target_player = None
        bot.target_player_gather_path = None
        bot.target_player_gather_targets = set()
        bot.threat_kill_path = None
        if bot.board_analysis is not None:
            bot.board_analysis.should_rescan = True
        return None

    @staticmethod
    def handle_city_found(bot: EklipZBot, tile):
        logbook.info(f"EH: City found handler! City {str(tile)}")
        bot.armyTracker.add_need_to_track_city(tile)
        bot.territories.needToUpdateAroundTiles.add(tile)
        if tile.player != -1:
            bot.board_analysis.should_rescan = True
        return None

    @staticmethod
    def handle_tile_captures(bot: EklipZBot, tile: Tile):
        logbook.info(
            f"EH: Tile captured! Tile {repr(tile)}, oldOwner {tile.delta.oldOwner} newOwner {tile.delta.newOwner}")
        bot.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity:
            bot.win_condition_analyzer.record_city_capture(tile, tile.player, army=tile.army)
            bot.armyTracker.add_need_to_track_city(tile)

            if tile.delta.oldOwner == -1 or tile.delta.newOwner == -1:
                bot.board_analysis.should_rescan = True
                bot._map.distance_mapper.recalculate()
                bot.cityAnalyzer.reset_reachability()
                if tile.delta.newOwner == -1:
                    return

        if not tile.delta.gainedSight:
            bot.armyTracker.notify_seen_player_tile(tile)

        # Tests: Tests/test_GeneralTrade.py - during a general trade bot.general
        # is mid-rebind (the cached general already flipped to the enemy), so
        # self identity must come from the map's fixed player_index, not the
        # possibly-stale bot.general.player.
        if tile.delta.oldOwner == bot._map.player_index or tile.delta.oldOwner in bot._map.teammates:
            if not bot._map.is_tile_friendly(tile):
                murderer = bot._map.players[tile.player]

                tileScore = 10
                if bot.territories.territoryMap[tile] == tile.delta.newOwner:
                    tileScore = 5
                elif bot._map.is_player_on_team_with(bot.territories.territoryMap[tile], bot._map.player_index):
                    tileScore = 30

                if tile.isCity:
                    tileScore += 5
                    tileScore = tileScore * 10

                murderer.aggression_factor += tileScore

        return None

    @staticmethod
    def handle_player_captures(bot: EklipZBot, capturee: int, capturer: int):
        logbook.info(
            f"EH: Player captured! capturee {bot._map.usernames[capturee]} ({capturee}) capturer {bot._map.usernames[capturer]} ({capturer})")
        for army in list(bot.armyTracker.armies.values()):
            if army.player == capturee:
                logbook.info(f"EH:   scrapping dead players army {str(army)}")
                bot.armyTracker.scrap_army(army, scrapEntangled=True)

        bot.history.captured_player(bot._map.turn, capturee, capturer)

        # Tests/test_OpponentTracker.py::OpponentTrackerTests.test_should_transfer_gather_queue_and_fog_pools_on_enemy_capture
        # enemy-vs-enemy kills transfer the victim's OpponentTracker gather
        # queue + fog pools to the killer halved (skipped internally when the
        # capturer is us).
        bot.opponent_tracker.notify_player_capture(capturee, capturer)

        if capturer == bot._map.player_index:
            logbook.info(f"setting lastPlayerKilled to {capturee}")
            bot.lastPlayerKilled = capturee
            playerGen = bot._map.players[capturee].general
            bot.launchPoints.append(playerGen)

        bot.trigger_player_capture_re_eval = True

        return None

    @staticmethod
    def reevaluate_after_player_capture(bot: EklipZBot):
        if bot._map.remainingPlayers <= 3:
            if not bot.opponent_tracker.winning_on_economy(byRatio=0.8):
                bot.viewInfo.add_info_line("not even on economy, going all in effective immediately")
                bot.is_all_in_losing = True
                bot.all_in_losing_counter = 300

    @staticmethod
    def handle_tile_deltas(bot: EklipZBot, tile):
        logbook.info(f"EH: Tile delta handler! Tile {repr(tile)} delta {tile.delta.armyDelta}")
        return None

    @staticmethod
    def handle_tile_discovered(bot: EklipZBot, tile):
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
    def handle_tile_vision_change(bot: EklipZBot, tile: Tile):
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
    def handle_army_moved(bot: EklipZBot, army: Army):
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
    def clear_fog_armies_around(bot: EklipZBot, enemyGeneral: Tile):

        def fog_army_clear_func(tile: Tile):
            if not tile.visible and tile in bot.armyTracker.armies:
                army = bot.armyTracker.armies[tile]
                if army.player == enemyGeneral.player:
                    bot.armyTracker.scrap_army(army, scrapEntangled=False)

        SearchUtils.breadth_first_foreach(bot._map, [enemyGeneral], maxDepth=7, foreachFunc=fog_army_clear_func)

    @staticmethod
    def _fmt_gen_diag_tile(t: Tile | None) -> str:
        if t is None:
            return 'None'
        return (f'{t.x},{t.y}(own={t.player},G={int(t.isGeneral)},v={int(t.visible)},'
                f'd={int(t.discovered)},a={t.army},i={t.tile_index})')

    @staticmethod
    def log_general_state_debug(bot: EklipZBot) -> None:
        """
        TEMPORARY DIAGNOSTIC (general-coloring investigation): per-turn dump of
        every general-reference path that could paint our general as another
        player's - map.generals[] slot vs tile.player, players[].general refs,
        dead/capturedBy, trade state, whether our general tile sits in another
        player's predicted valid_general_positions (the spawn overlay paints
        those in that player's color), and all live isGeneral tiles with their
        owner deltas. Remove once the miscoloring source is identified.
        """
        mapObj = bot._map
        us = mapObj.player_index
        fmt = BotEventHandlers._fmt_gen_diag_tile

        logbook.info(
            f'GENDIAG t{mapObj.turn} pi={us} botGen={fmt(bot.general)} '
            f'target={bot.targetPlayer} tPEL={fmt(bot.targetPlayerExpectedGeneralLocation)}')

        genTilesByIndex: typing.Dict[int, typing.Set[int]] = {}
        ourGen = bot.general if bot.general is not None else mapObj.generals[us]
        for p in mapObj.players:
            gen = mapObj.generals[p.index]
            pgen = p.general
            if gen is not None:
                genTilesByIndex.setdefault(gen.tile_index, set()).add(p.index)
            if pgen is not None:
                genTilesByIndex.setdefault(pgen.tile_index, set()).add(p.index)
            seen = bot.armyTracker.seen_player_lookup[p.index] if bot.armyTracker is not None else False
            if bot.armyTracker is not None:
                validPos = bot.armyTracker.valid_general_positions_by_player[p.index]
                validCount = sum(validPos.raw)
                ourGenInValid = ourGen is not None and validPos[ourGen]
            else:
                validCount = -1
                ourGenInValid = False
            logbook.info(
                f'GENDIAG p{p.index}: gen={fmt(gen)} pgen={fmt(pgen)} dead={p.dead} capBy={p.capturedBy} '
                f'tiles={len(p.tiles)} seen={seen} validGen={validCount} ourGenInValid={ourGenInValid}')

        # TEMPORARY DIAGNOSTIC: if our general tile lands in any per-player set
        # that drives an overlay tinted in that player's color
        # (player_connected_tiles zone, unconnectable/alt-gen targeted tiles,
        # ffa placement seeds, or the evidence sets that unban it from the
        # connected-tile spanning tree), that is the miscoloring source.
        if ourGen is not None and bot.armyTracker is not None:
            for p in mapObj.players:
                if mapObj.is_player_on_team_with(us, p.index):
                    continue
                inEverOwned = ourGen in bot.armyTracker.tiles_ever_owned_by_player[p.index]
                inUneliminated = ourGen in bot.armyTracker.uneliminated_emergence_events[p.index]
                inUnrecaptured = ourGen in bot.armyTracker.unrecaptured_emergence_events[p.index]
                inConnected = ourGen in bot.armyTracker.player_connected_tiles[p.index]
                inUnconnectable = ourGen in bot.armyTracker.unconnectable_tiles[p.index]
                inAltGen = ourGen in bot.alt_en_gen_positions[p.index]
                inFfaSeed = (
                    p.index < len(bot.armyTracker.ffa_general_placement.positions)
                    and bot.armyTracker.ffa_general_placement.positions[p.index] is ourGen)
                emergenceVal = bot.armyTracker.emergenceLocationMap[p.index].raw[ourGen.tile_index]
                if (inEverOwned or inUneliminated or inUnrecaptured or inConnected
                        or inUnconnectable or inAltGen or inFfaSeed or emergenceVal > 0):
                    logbook.warning(
                        f'GENDIAG OGEN-IN p{p.index}: everOwned={inEverOwned} '
                        f'unelim={inUneliminated} unrecap={inUnrecaptured} '
                        f'connected={inConnected} unconnectable={inUnconnectable} '
                        f'altGen={inAltGen} ffaSeed={inFfaSeed} emergeVal={emergenceVal}')

        for p in mapObj.players:
            gen = mapObj.generals[p.index]
            pgen = p.general
            onTeam = mapObj.is_player_on_team_with(us, p.index)
            if gen is not None and gen.player != p.index:
                logbook.error(f'GENDIAG VIOLATION generals[{p.index}] {fmt(gen)} tile owned by p{gen.player}')
            if pgen is not None and pgen.player != p.index:
                logbook.error(f'GENDIAG VIOLATION players[{p.index}].general {fmt(pgen)} tile owned by p{pgen.player}')
            if gen is not None and not gen.isGeneral:
                logbook.error(f'GENDIAG VIOLATION generals[{p.index}] {fmt(gen)} isGeneral=False')
            if pgen is not None and not pgen.isGeneral:
                logbook.error(f'GENDIAG VIOLATION players[{p.index}].general {fmt(pgen)} isGeneral=False')
            if not onTeam:
                if gen is not None and gen.player == us:
                    logbook.error(f'GENDIAG VIOLATION generals[{p.index}] {fmt(gen)} IS OUR TILE')
                if pgen is not None and pgen.player == us:
                    logbook.error(f'GENDIAG VIOLATION players[{p.index}].general {fmt(pgen)} IS OUR TILE')
                if ourGen is not None and bot.armyTracker is not None and \
                        bot.armyTracker.valid_general_positions_by_player[p.index][ourGen]:
                    logbook.error(f'GENDIAG VIOLATION our general {fmt(ourGen)} in valid_general_positions p{p.index}')

        for tileIndex, playerSet in genTilesByIndex.items():
            if len(playerSet) > 1:
                tile = mapObj.get_tile_by_tile_index(tileIndex)
                logbook.error(f'GENDIAG VIOLATION same general tile {fmt(tile)} claimed as general by players {sorted(playerSet)}')

        for tile in mapObj.get_all_tiles():
            if tile.isGeneral:
                d = tile.delta
                logbook.info(
                    f'GENDIAG isGenTile {fmt(tile)} own {d.oldOwner}->{d.newOwner} '
                    f'gainS={d.gainedSight} lostS={d.lostSight} disc={d.discovered}')

        pendingStr = str([(n.server_turn, n.player_a, n.player_b) for n in mapObj._pending_trade_notifications])
        appliedStr = str(sorted(mapObj._applied_trade_keys)) if mapObj._applied_trade_keys else '[]'
        logbook.info(
            f'GENDIAG trades: general_trade={mapObj.general_trade} trades={mapObj.general_trades} '
            f'pending={pendingStr} applied={appliedStr} '
            f'preTrade={[fmt(t) for t in mapObj._pre_trade_generals]}')
