import logging
import time
import traceback
import typing

import DebugHelper
from BotHost import BotHostBase
from DataModels import Move
from Path import Path
from SearchUtils import count, where
from Sim.TextMapLoader import TextMapLoader
from base.bot_base import create_thread
from base.client.generals import ChatUpdate
from base.client.map import MapBase, Tile, TILE_EMPTY, TILE_OBSTACLE, Score, TILE_FOG, TILE_MOUNTAIN, TileDelta
from bot_ek0x45 import EklipZBot


def generate_player_map(player_index: int, map_raw: MapBase) -> MapBase:
    playerMap = [[Tile(x, y, tile=TILE_FOG, army=0, player=-1) for x in range(map_raw.cols)] for y in
                 range(map_raw.rows)]

    scores = [Score(n, map_raw.players[n].score, map_raw.players[n].tileCount, map_raw.players[n].dead) for n in
              range(0, len(map_raw.players))]

    friendlyPlayers = [player_index]

    teams = None
    if map_raw.teams is not None:
        teams = [i for i in map_raw.teams]
        for p, t in enumerate(teams):
            if p != player_index and teams[player_index] == t:
                friendlyPlayers.append(p)

    map = MapBase(
        player_index=player_index,
        teams=teams,
        user_names=map_raw.usernames,
        turn=map_raw.turn,
        map_grid_y_x=playerMap,
        replay_url='42069')

    # map.USE_OLD_MOVEMENT_DETECTION = False
    map.update_scores(scores)
    map.update_turn(map_raw.turn)
    for x in range(map_raw.cols):
        for y in range(map_raw.rows):
            realTile = map_raw.grid[y][x]

            hasVision = realTile.player in friendlyPlayers or any(
                filter(lambda tile: tile.player in friendlyPlayers, realTile.adjacents))

            if hasVision:
                map.update_visible_tile(realTile.x, realTile.y, realTile.tile, realTile.army, realTile.isCity, realTile.isGeneral)
                if realTile.isMountain:
                    map.grid[realTile.y][realTile.x].tile = TILE_MOUNTAIN
                    map.grid[realTile.y][realTile.x].isMountain = True
            else:
                if realTile.isCity or realTile.isMountain:
                    tile = map.GetTile(realTile.x, realTile.y)
                    tile.isMountain = False
                    tile.tile = TILE_OBSTACLE
                    tile.army = 0
                    tile.isCity = False
                    # tile.discovered = realTile.discovered
                    map.update_visible_tile(realTile.x, realTile.y, TILE_OBSTACLE, tile_army=0, is_city=False, is_general=False)
                else:
                    map.update_visible_tile(realTile.x, realTile.y, TILE_FOG, tile_army=0, is_city=False, is_general=False)

    map.update(bypassDeltas=True)

    return map


class GamePlayer(object):
    def __init__(self, map_raw: MapBase, player_index: int):
        self.index = player_index
        self.map = generate_player_map(player_index, map_raw)
        self.move_history: typing.List[typing.Union[None, Move]] = []
        self.tiles_gained_this_turn: typing.Set[Tile] = set()
        self.tiles_lost_this_turn: typing.Set[Tile] = set()
        self.dead: bool = map_raw.players[player_index].dead
        self.captured_by: int = -1

    def set_captured(self, captured_by_player: int):
        self.dead = True
        self.captured_by = captured_by_player

    def __str__(self):
        return f'{self.index} {"alive" if not self.dead else "dead"}'

    def __repr__(self):
        return str(self)

    def set_map_vision(self, rawMap: MapBase):
        for tile in rawMap.get_all_tiles():
            playerTile = self.map.GetTile(tile.x, tile.y)
            playerTile.discovered = playerTile.visible
            if not playerTile.visible:
                playerTile.army = tile.army
                playerTile.visible = False
                playerTile.isCity = tile.isCity
                playerTile.isMountain = tile.discovered and tile.isMountain
                playerTile.player = tile.player
                playerTile.discovered = tile.discovered
                playerTile.isGeneral = tile.isGeneral
                # playerTile.tile = tile.tile
            if playerTile.isGeneral:
                self.map.players[playerTile.player].general = playerTile
                self.map.generals[playerTile.player] = playerTile

        for rawPlayer in rawMap.players:
            player = self.map.players[rawPlayer.index]

            if rawPlayer.aggression_factor > 0:
                player.aggression_factor = rawPlayer.aggression_factor

            if rawPlayer.delta25score > 0:
                player.delta25score = rawPlayer.delta25score

            if rawPlayer.delta25tiles > 0:
                player.delta25tiles = rawPlayer.delta25tiles

            if rawPlayer.knowsKingLocation > 0:
                player.knowsKingLocation = rawPlayer.knowsKingLocation

            if rawPlayer.last_seen_move_turn > 0:
                player.last_seen_move_turn = rawPlayer.last_seen_move_turn

            if rawPlayer.cityGainedTurn > 0:
                player.cityGainedTurn = rawPlayer.cityGainedTurn

            if rawPlayer.cityLostTurn > 0:
                player.cityLostTurn = rawPlayer.cityLostTurn

            player.leftGame = rawPlayer.leftGame
            if rawPlayer.leftGameTurn > 0:
                player.leftGameTurn = rawPlayer.leftGameTurn

            player.dead = rawPlayer.dead


class GameSimulator(object):
    def __init__(self, map_raw: MapBase, ignore_illegal_moves: bool = False):
        """

        @param map_raw: Should be the full map
        """
        for tile in map_raw.get_all_tiles():
            if tile.tile == TILE_FOG:
                tile.tile = TILE_EMPTY
            if tile.isCity:
                tile.tile = tile.player
            if tile.tile == TILE_OBSTACLE or tile.isMountain:
                tile.tile = TILE_MOUNTAIN

        # force the map to internalize the above changes
        map_raw.init_grid_movable()
        map_raw.update()

        self.teams: typing.List[int] = map_raw.teams
        if self.teams is None:
            self.teams = [i for i in range(len(map_raw.players))]

        self.players: typing.List[GamePlayer] = [GamePlayer(map_raw, i) for i in range(len(map_raw.players))]
        self.turn: int = map_raw.turn
        self.sim_map: MapBase = map_raw
        self.moves: typing.List[typing.Union[None, Move]] = [None for i in range(len(map_raw.players))]
        self.moves_history: typing.List[typing.List[typing.Union[None, Move]]] = []
        """moves_history[-1] is the most recent set of moves, and moves_history[-1][0] would be player 0's selected move."""
        self.tiles_updated_this_cycle: typing.Set[Tile] = set()
        self.ignore_illegal_moves = ignore_illegal_moves

    def make_move(self, player_index: int, move: Move | None, force: bool = False) -> bool:
        if self.moves[player_index] is not None:
            if not force:
                raise AssertionError(f'player {player_index} already has a move queued this turn, {str(self.moves[player_index])}')
        self.moves[player_index] = move
        return True

    def execute_turn(self, dont_require_all_players_to_move=False):
        moveOrder = [pair for pair in enumerate(self.moves)]

        logging.info(f'SIM MAP TURN {self.turn + 1}')
        self.sim_map.update_turn(self.turn + 1)
        for tile in self.sim_map.get_all_tiles():
            tile.delta.oldArmy = tile.army
            tile.delta.oldOwner = tile.player
            tile.delta.newOwner = tile.player

        if self.turn & 1 == 1:
            moveOrder = reversed(moveOrder)

        for player, move in moveOrder:
            if move is None:
                if not dont_require_all_players_to_move:
                    raise AssertionError(f'player {player} does not have a move queued yet for turn {self.turn}')
                continue

            self._execute_move(player, move)

        self.turn = self.turn + 1
        self.moves_history.append(self.moves)
        self.moves = [None for _ in self.moves]
        # intentionally do this before increments so we dont need to deal with expected deltas
        self._update_tile_deltas()
        self._update_map_values_for_any_increments()
        self._update_scores()
        logging.info(f'END SIM MAP TURN {self.turn}, UPDATING PLAYER MAPS')

        self.send_update_to_player_maps()
        self.tiles_updated_this_cycle = set()

    def is_game_over(self) -> bool:
        livingTeams = set()
        for player in self.players:
            if player.map.complete:
                player.dead = True
            if not player.dead:
                livingTeams.add(self.teams[player.index])
                logging.info(f'player {player.index} still alive')

        if len(livingTeams) > 1:
            logging.info(f'living teams {livingTeams}')
            return False

        logging.info(f'Detected game win')

        for player in self.players:
            if not player.dead:
                player.map.complete = True
                player.map.result = True

        return True

    def _execute_move(self, player_index: int, move: Move):
        player = self.players[player_index]
        player.move_history.append(move)
        sourceTile = self.sim_map.GetTile(move.source.x, move.source.y)
        destTile = self.sim_map.GetTile(move.dest.x, move.dest.y)
        if sourceTile.player != player_index:
            if not self.ignore_illegal_moves and sourceTile not in self.tiles_updated_this_cycle:
                raise AssertionError(f'player {player_index} made a move from a tile they dont own. {str(move)}')
            return

        if sourceTile.army <= 1:
            # this happens when the tile they are moving gets attacked and is not necessarily a problem
            if not self.ignore_illegal_moves and sourceTile not in self.tiles_updated_this_cycle:
                raise AssertionError(f'player {player_index} made a move from a {sourceTile.army} army tile. {str(move)}')
            return

        if destTile.isMountain:
            if not self.ignore_illegal_moves:
                raise AssertionError(f'player {player_index} made a move into a mountain. {str(move)}')
            return

        armyBeingMoved = sourceTile.army - 1
        if move.move_half:
            armyBeingMoved = sourceTile.army // 2

        sourceTile.army = sourceTile.army - armyBeingMoved

        isAlliedGeneralDest = (destTile.isGeneral and self.teams[destTile.player] == self.teams[player_index])

        if not destTile.isNeutral and self.teams[destTile.player] == self.teams[player_index]:
            destTile.army += armyBeingMoved
            # destTile.delta.armyDelta += armyBeingMoved
            if not destTile.isGeneral and destTile.player != player_index:
                # captured teammates tile
                destPlayer = self.players[destTile.player]
                destTile.player = player_index
                self._stage_tile_captured_events(destTile, player, destPlayer)

        else:
            destTile.army -= armyBeingMoved

            destPlayer = None
            if destTile.player >= 0:
                destPlayer = self.players[destTile.player]
            # destTile.delta.armyDelta -= armyBeingMoved

            if destTile.army < 0:
                destTile.army = 0 - destTile.army
                self._stage_tile_captured_events(destTile, player, destPlayer)
                if destTile.isGeneral:
                    genArmy = destTile.army
                    # player killed
                    self._execute_player_capture(player, destPlayer)
                    # we just incorrectly halved this, set it back to what it should be
                    destTile.army = genArmy
                    destTile.isCity = True
                    destTile.isGeneral = False

                destTile.player = player_index
                # destTile.delta.newOwner = player_index

        sourceTile.delta.toTile = destTile
        destTile.delta.fromTile = sourceTile

        self.tiles_updated_this_cycle.add(sourceTile)
        self.tiles_updated_this_cycle.add(destTile)

    def _stage_tile_captured_events(self, captured_tile: Tile, capturing_player: GamePlayer, captured_player: GamePlayer | None):
        if captured_player is not None:
            captured_player.tiles_lost_this_turn.add(captured_tile)
            if captured_tile in captured_player.tiles_gained_this_turn:
                captured_player.tiles_gained_this_turn.remove(captured_tile)
        captured_tile.turn_captured = self.turn
        capturing_player.tiles_gained_this_turn.add(captured_tile)

    def _execute_player_capture(self, capturer: GamePlayer, captured: GamePlayer):
        for row in self.sim_map.grid:
            for mapTile in row:
                if mapTile.player == captured.index:
                    mapTile.player = capturer.index
                    mapTile.army -= mapTile.army // 2
                    self.tiles_updated_this_cycle.add(mapTile)
                    self._stage_tile_captured_events(mapTile, capturer, captured)

        captured.set_captured(capturer.index)
        for player in self.players:
            player.map.handle_player_capture(capturer.index, captured.index)

    def _update_map_values_for_any_increments(self):
        if self.sim_map.turn != self.turn:
            raise AssertionError(f'Something desynced, sim_map.turn + 1 was {self.sim_map.turn} while sim turn was {self.turn}')

        for row in self.sim_map.grid:
            for mapTile in row:
                updated = False
                if self.turn % 2 == 0 and (mapTile.isGeneral or (mapTile.isCity and not mapTile.isNeutral)):
                    mapTile.army += 1
                    updated = True

                if self.turn % 50 == 0 and mapTile.player >= 0:
                    mapTile.army += 1
                    updated = True

                if updated:
                    self.tiles_updated_this_cycle.add(mapTile)

    def _update_scores(self):
        scores = [Score(player.index, 0, 0, player.dead) for player in self.players]

        for row in self.sim_map.grid:
            for mapTile in row:
                if mapTile.isNeutral or mapTile.isMountain:
                    continue

                tilePlayerScore = scores[mapTile.player]

                tilePlayerScore.tiles += 1
                tilePlayerScore.total += mapTile.army

        self.sim_map.update_scores(scores)

    def _send_updates_to_player_maps(self, noDeltas=False):
        # actual server client map executes in this order:
        # turn
        # scores
        # tile data
        # call update

        for player in self.players:
            logging.info(f'----')
            logging.info(f'----')
            logging.info(f'SIM SENDING TURN {self.turn} MAP UPDATES TO PLAYER {player.index}')
            player.map.update_turn(self.turn)

            playerScoreClone = [Score(score.player, score.total, score.tiles, score.dead) for score in self.sim_map.scores]
            player.map.update_scores(playerScoreClone)

            # send updates for tiles they lost vision of
            # send updates for tiles they can see
            for tile in self.sim_map.get_all_tiles():
                # the way the game client works, it always 'updates' every tile on the players map even if it didn't get a server update, that's why the deltas were ghosting in the sim
                # if tile in self.tiles_updated_this_cycle:
                playerHasVision = (not tile.isNeutral and self.teams[tile.player] == self.teams[player.index]) or any(filter(lambda adj: not adj.isNeutral and self.teams[adj.player] == self.teams[player.index], tile.adjacents))
                if playerHasVision:
                    player.map.update_visible_tile(tile.x, tile.y, tile.tile, tile.army, tile.isCity, tile.isGeneral)
                else:
                    self._send_player_lost_vision_of_tile(player, tile)

            player.map.update(bypassDeltas=noDeltas)
            player.tiles_lost_this_turn = set()
            player.tiles_gained_this_turn = set()
        logging.info(f'END SIM PLAYER MAP UPDATES FOR TURN {self.turn}')

    def _send_player_lost_vision_of_tile(self, player: GamePlayer, tile: Tile):
        tileVal = TILE_FOG
        if (tile.isMountain or tile.isCity) and not tile.isGeneral:
            tileVal = TILE_OBSTACLE
        # pretend we're the game server
        player.map.update_visible_tile(tile.x, tile.y, tileVal, tile_army=0, is_city=False, is_general=False)

    def end_game(self):
        for player in self.players:
            player.map.result = False
            player.map.complete = True

    def set_general_vision(self, playerToReveal, playerToRevealTo, hidden=False):
        revealGeneral = self.sim_map.generals[playerToReveal]

        player = self.players[playerToRevealTo]
        if not hidden:
            player.map.update_visible_tile(revealGeneral.x, revealGeneral.y, revealGeneral.player, revealGeneral.army, is_city=False, is_general=True)
            player.map.update_visible_tile(revealGeneral.x, revealGeneral.y, TILE_FOG, 0, is_city=False, is_general=False)
        else:
            # we're hiding the general
            self.set_tile_vision(playerToRevealTo, revealGeneral.x, revealGeneral.y, undiscovered=True, hidden=True)
            player.map.generals[playerToReveal] = None

    def set_tile_vision(self, playerToRevealTo, x, y, hidden=False, undiscovered=False):
        player = self.players[playerToRevealTo]
        tile = self.sim_map.GetTile(x, y)
        if not undiscovered:
            player.map.update_visible_tile(tile.x, tile.y, tile.player, tile.army, is_city=tile.isCity, is_general=tile.isGeneral)
            if hidden:
                player.map.update_visible_tile(tile.x, tile.y, TILE_OBSTACLE if tile.isCity or tile.isMountain else TILE_FOG, 0, is_city=False, is_general=False)
        else:
            # we're hiding the general
            playerTile = player.map.GetTile(tile.x, tile.y)
            playerTile.visible = False
            playerTile.discovered = False
            playerTile.tile = TILE_OBSTACLE if tile.isCity or tile.isMountain else TILE_FOG
            playerTile.isCity = False
            playerTile.isGeneral = False
            playerTile.army = 0
            playerTile.player = -1

    def send_update_to_player_maps(self, noDeltas=False):
        self._send_updates_to_player_maps(noDeltas)

    def reset_player_map_deltas(self):
        for player in self.players:
            player.map.clear_deltas_and_score_history()

    def _update_tile_deltas(self):
        for tile in self.tiles_updated_this_cycle:
            if tile.player != tile.delta.oldOwner:
                tile.delta.armyDelta = 0 - tile.army - tile.delta.oldArmy
                tile.delta.newOwner = tile.player

            elif tile.army != tile.delta.oldArmy:
                tile.delta.armyDelta = tile.army - tile.delta.oldArmy


class GameSimulatorHost(object):
    def __init__(
            self,
            map: MapBase,
            player_with_viewer: int = -1,
            playerMapVision: MapBase | None = None,
            afkPlayers: None | typing.List[int] = None,
            allAfkExceptMapPlayer: bool = False,
            teammateNotAfk: bool = False,
            respectTurnTimeLimitToDropMoves: bool = False):
        """

        @param map:
        @param player_with_viewer:
        @param playerMapVision:
        @param afkPlayers:
        @param allAfkExceptMapPlayer:
        @param respectTurnTimeLimitToDropMoves: Note that if capturing logging in pycharm unit tests, the logging makes the program REALLY slow so moves will drop like flies...
        """
        self.move_queue: typing.List[typing.List[Move | None]] = [[] for player in map.players]
        self.sim = GameSimulator(map, ignore_illegal_moves=False)

        self.bot_hosts: typing.List[BotHostBase | None] = [None for player in self.sim.players]
        self.dropped_move_counts_by_player: typing.List[int] = [0 for player in self.sim.players]

        self.player_move_cutoff_time: float = 0.475
        """If a player takes longer to move than this, and a debugger is not attached, then the players move will be discarded and an error logged. Does not include the first 12 turns."""

        self._between_turns_funcs: typing.List[typing.Callable] = []

        self.forced_afk_players: typing.List[int] = []
        if afkPlayers is not None:
            self.forced_afk_players = afkPlayers

        if allAfkExceptMapPlayer:
            self.forced_afk_players = [i for i in where(range(len(map.players)), lambda p: p != map.player_index)]

        if teammateNotAfk:
            for teammate in map.teammates:
                self.forced_afk_players.remove(teammate)

        self.player_with_viewer: int = player_with_viewer

        self.respect_turn_time_limit: bool = respectTurnTimeLimitToDropMoves

        charMap = [c for c, idx in TextMapLoader.get_player_char_index_map()]

        for i in range(len(self.bot_hosts)):
            char = charMap[i]
            if i in self.forced_afk_players:
                # just leave the botHost as None for the afk player
                continue
            if self.sim.sim_map.players[i].dead:
                continue
            # i=i captures the current value of i in the lambda, otherwise all players lambdas would send the last players player index...
            hasUi = i == player_with_viewer or player_with_viewer == -2
            botMover = lambda source, dest, moveHalf, i=i: self.sim.make_move(player_index=i, move=Move(source, dest, moveHalf))
            botPinger = lambda tile, i=i: self.notify_teammates_tile_ping(player=i, tile=tile)
            botChatter = lambda message, teamChat, i=i: self.notify_chat_message(player=i, message=message, teamChat=teamChat)
            botHost = BotHostBase(char, botMover, botPinger, botChatter, 'test', noUi=not hasUi, alignBottom=True, throw=True)

            self.bot_hosts[i] = botHost

        if playerMapVision is not None:
            self.apply_map_vision(playerMapVision.player_index, rawMap=playerMapVision)
        self.sim._update_scores()
        self.sim.send_update_to_player_maps(noDeltas=True)
        # # clear all the tile deltas and stuff.
        # for player in self.sim.players:
        #     player.map.update_turn(self.sim.sim_map.turn)
        #
        #     player.map.update()

        for playerIndex, botHost in enumerate(self.bot_hosts):
            if botHost is None:
                continue
            player = self.sim.players[playerIndex]
            # this actually just initializes the bots viewers and stuff, we throw this first move away
            botHost.eklipz_bot.initialize_map_for_first_time(player.map)
            # botHost.eklipz_bot.targetPlayer = (botHost.eklipz_bot.general.player + 1) % 2
            # botHost.eklipz_bot.targetPlayerObj = botHost.eklipz_bot._map.players[botHost.eklipz_bot.targetPlayer]
            # botHost.eklipz_bot.init_turn()
            botHost.make_move(player.map)

        # throw the initialized moves away
        self.sim.moves = [None for move in self.sim.moves]
        self.sim.reset_player_map_deltas()

    def run_sim(self, run_real_time: bool = True, turn_time: float = 0.5, turns: int = 10000) -> int | None:
        """
        Runs a sim for some number of turns and returns the player who won in that time (or None if no winner).

        @param run_real_time:
        @param turn_time:
        @param turns:
        @return:
        """
        self.give_players_perfect_initial_city_information()
        self.dropped_move_counts_by_player = [0 for player in self.sim.players]

        for playerIndex, botHost in enumerate(self.bot_hosts):
            if botHost is None:
                continue

            botHost.eklipz_bot.expand_plan = None
            botHost.eklipz_bot.timings = None
            botHost.eklipz_bot.curPath = None

            if botHost.has_viewer and run_real_time:
                botHost.initialize_viewer(botHost.eklipz_bot.no_file_logging)
                botHost._viewer.send_update_to_viewer(botHost.eklipz_bot.viewInfo, botHost.eklipz_bot._map)
                botHost.run_viewer_loop()

        if run_real_time:
            # time to look at the first move, pygame doesn't start up that quickly
            time.sleep(2)

        winner = None
        try:
            turnsRun = 0
            while turnsRun < turns:
                winner = self.execute_turn(run_real_time=run_real_time, turn_time=turn_time)
                if winner is not None:
                    break
                turnsRun += 1
            if not self.sim.is_game_over():
                for idx, botHost in enumerate(self.bot_hosts):
                    if botHost is not None and not self.sim.players[idx].dead:
                        # perform the final 'bot' turn without actual executing the move or getting the next
                        # server update. Allows things like the army tracker etc and the map viewer to update with the
                        # bots final calculated map state and everything.
                        botHost.make_move(self.sim.players[idx].map)
        except:
            try:
                self.sim.end_game()
                for botHost in self.bot_hosts:
                    if botHost is None:
                        continue
                    botHost.notify_game_over()
            except:
                logging.error(f"(error v notifying bots of game over turn {self.sim.turn})")
                logging.error(traceback.format_exc())
                logging.error("(error ^ notifying bots of game over above, less important than real error logged below)")

            logging.error(f"(error v running bot sim turn {self.sim.turn})")
            logging.error(traceback.format_exc())
            logging.fatal(f'IMPORT TEST FILES FOR TURN {self.sim.turn} FROM @ {repr([b.eklipz_bot.logDirectory for b in self.bot_hosts if b is not None])}')
            raise

        if run_real_time:
            self.wait_until_viewer_closed_or_time_elapses(max(3.0, turn_time * 4))

        self.sim.end_game()
        for botHost in self.bot_hosts:
            if botHost is None:
                continue
            botHost.notify_game_over()

        if winner == -1:
            winner = None
        return winner

    def make_player_afk(self, player: int):
        self.forced_afk_players.append(player)

    def reveal_player_general(self, playerToReveal: int, playerToRevealTo: int, hidden=False):
        self.sim.set_general_vision(playerToReveal, playerToRevealTo, hidden=hidden)
        revealPlayer = self.sim.players[playerToRevealTo]
        revealGeneral = self.sim.sim_map.generals[playerToReveal]

        revealPlayer.map.players[playerToRevealTo].knowsKingLocation = True

        if hidden:
            botHost = self.bot_hosts[playerToRevealTo]
            playerTile = revealPlayer.map.GetTile(revealGeneral.x, revealGeneral.y)
            if botHost is not None and playerTile in botHost.eklipz_bot.armyTracker.armies:
                del botHost.eklipz_bot.armyTracker.armies[playerTile]

                revealPlayer.map.players[playerToRevealTo].knowsKingLocation = False

    # def reveal_player_tile(self, playerToTileTo, x, y):
    #     self.sim.set_general_vision(playerToReveal, playerToRevealTo, hidden=hidden)
    #     revealPlayer = self.sim.players[playerToRevealTo]
    #     revealGeneral = self.sim.sim_map.generals[playerToReveal]
    #
    #     if hidden:
    #         botHost = self.bot_hosts[playerToRevealTo]
    #         playerTile = revealPlayer.map.GetTile(revealGeneral.x, revealGeneral.y)
    #         if botHost is not None and playerTile in botHost.eklipz_bot.armyTracker.armies:
    #             del botHost.eklipz_bot.armyTracker.armies[playerTile]

    def apply_map_vision(self, player: int, rawMap: MapBase):
        playerToGiveVision = self.sim.players[player]
        playerToGiveVision.set_map_vision(rawMap)

    def queue_player_moves_str(self, player: int, moves_str: str):
        """
        x,y->x',y'->... to represent paths.
        double space to separate individual paths.
        double space 'none' double space to represent no-op moves.
        
        @param player:
        @param moves_str:
        @return:
        """
        paths = moves_str.split('  ')
        for path_str in paths:
            if path_str.strip().lower() == 'none':
                self.move_queue[player].append(None)
                continue

            moves = path_str.split('->')
            prevTile: Tile | None = None
            for move_str in moves:
                (currentTile, moveHalf) = self.get_player_tile_from_move_str(player, move_str)
                if prevTile is not None:
                    self.move_queue[player].append(Move(prevTile, currentTile, moveHalf))
                prevTile = currentTile

    def queue_player_move(self, player: int, move: Move | None):
        playerObj = self.sim.players[player]
        if move is None:
            self.move_queue[player].append(move)
            return

        self.move_queue[player].append(Move(playerObj.map.GetTile(move.source.x, move.source.y), playerObj.map.GetTile(move.dest.x, move.dest.y), move.move_half))

    def execute_turn(self, run_real_time: bool = False, turn_time: float = 0.5) -> int | None:
        """
        Runs a turn of the sim, and returns None or the player ID of the winner, if the game ended this turn.
        @param run_real_time:
        @param turn_time:
        @return:
        """
        logging.info(f'sim starting turn {self.sim.turn}')
        start = time.perf_counter()
        winner = None
        for playerIndex, botHost in enumerate(self.bot_hosts):
            player = self.sim.players[playerIndex]

            if not player.dead and not player.index in self.forced_afk_players:
                moveStart = time.perf_counter()
                try:
                    botHost.make_move(player.map)
                except:
                    raise AssertionError(f'{traceback.format_exc()}\r\n\r\nIMPORT TEST FILES FOR TURN {self.sim.turn} FROM @ {botHost.eklipz_bot.logDirectory}')

                moveTime = time.perf_counter() - moveStart
                if self.respect_turn_time_limit and self.sim.sim_map.turn > 20 and moveTime > self.player_move_cutoff_time and not DebugHelper.IS_DEBUGGING:
                    logging.error(f'turn {self.sim.sim_map.turn}: player {playerIndex} {self.sim.sim_map.usernames[playerIndex]} took {moveTime:.3f} to move, dropping its move!')
                    self.sim.make_move(playerIndex, None, force=True)
                    self.dropped_move_counts_by_player[playerIndex] += 1

            # if we have a move queued explicitly, overwrite their move with the test-forced move.
            if len(self.move_queue[playerIndex]) > 0:
                move = self.move_queue[playerIndex].pop(0)
                if move is not None and self.sim.sim_map.GetTile(move.source.x, move.source.y).player != playerIndex:
                    move = None
                self.sim.make_move(playerIndex, move, force=True)
                if self.bot_hosts[playerIndex] is not None:
                    if move is not None:
                        fullArmy = self.sim.sim_map.GetTile(move.source.x, move.source.y).army
                        # the army on these tiles has changed since the Move object was created, fix the army amount.
                        move.army_moved = fullArmy - 1
                        if move.move_half:
                            move.army_moved = fullArmy // 2

                    self.bot_hosts[playerIndex].eklipz_bot.armyTracker.last_player_index_submitted_move = move
                    self.bot_hosts[playerIndex].eklipz_bot.history.move_history[self.sim.turn] = [move]

                player = self.sim.players[playerIndex]
                player.map.last_player_index_submitted_move = None
                if move is not None:
                    player.map.last_player_index_submitted_move = (move.source, move.dest, move.move_half)

        for func in self._between_turns_funcs:
            self._run_between_turns_func(run_real_time, func)

        if run_real_time:
            elapsed = time.perf_counter() - start
            if elapsed < turn_time:
                time.sleep(turn_time - elapsed)

        self.sim.execute_turn(dont_require_all_players_to_move=True)

        gameEndedByUser = False
        for botHost in self.bot_hosts:
            if botHost is None:
                continue
            if botHost.has_viewer and botHost.is_viewer_closed_by_user():
                gameEndedByUser = True

        if self.sim.is_game_over() or gameEndedByUser:
            # run these one last time
            for func in self._between_turns_funcs:
                self._run_between_turns_func(run_real_time, func)
            self.sim.end_game()
            for player in self.sim.players:
                if not player.dead:
                    if winner is None:
                        winner = player.index
                    else:
                        winner = -1
            for botHost in self.bot_hosts:
                if botHost is None:
                    continue
                botHost.notify_game_over()

        if winner == -1:
            winner = None
        return winner

    def get_player_map(self, player: int = -1) -> MapBase:
        if player == -1:
            player = self.sim.sim_map.player_index

        return self.sim.players[player].map

    def get_bot(self, player: int = -1) -> EklipZBot:
        if player == -1:
            player = self.sim.sim_map.player_index

        return self.bot_hosts[player].eklipz_bot

    def run_between_turns(self, func: typing.Callable):
        self._between_turns_funcs.append(func)

    def assert_last_move(self, player: int, move: str | None):
        pObj = self.sim.players[player]
        actualMove = pObj.move_history[-1]
        if move is None:
            assert actualMove is None
        else:
            srcStr, destStr = move.split('->')
            srcTile, moveHalf = self.get_player_tile_from_move_str(player, srcStr)
            destTile, _ = self.get_player_tile_from_move_str(player, destStr)
            assert srcTile.x == actualMove.source.x
            assert srcTile.y == actualMove.source.y
            assert destTile.x == actualMove.dest.x
            assert destTile.y == actualMove.dest.y

    def get_player_tile_from_move_str(self, player: int, move_str: str) -> typing.Tuple[Tile, bool]:
        """
        returns the move tile, and whether it ended with 'z' indicating move-half.

        @param move_str:
        @return:
        """
        xStr, yStr = move_str.strip().split(',')
        moveHalf = False
        if yStr.strip().endswith('z'):
            moveHalf = True
            yStr = yStr.strip('z ')

        currentTile = self.sim.players[player].map.GetTile(int(xStr), int(yStr))
        return currentTile, moveHalf

    def give_players_perfect_initial_city_information(self):
        # give all players in the game perfect information about each others cities like they would have in a normal game by that turn
        for player in self.sim.players:
            for i, otherPlayer in enumerate(self.sim.players):
                player.map.players[i].cityCount = otherPlayer.map.players[otherPlayer.map.player_index].cityCount

    def _run_between_turns_func(self, run_real_time: bool, func):
        try:
            func()
        except:
            logging.error(f'assertion failure while running live, turn {self.sim.turn}')
            logging.error(traceback.format_exc())
            if run_real_time:
                self.wait_until_viewer_closed_or_time_elapses(600)
            raise

    def notify_teammates_tile_ping(self, player: int, tile: Tile):
        bot: BotHostBase
        for p, bot in enumerate(self.bot_hosts):
            if p == player or bot is None or bot.eklipz_bot is None:
                continue
            if self.sim.sim_map.teams[player] == self.sim.sim_map.teams[p]:
                logging.info(f'SIM NOTIFYING TILE PING {str(tile)} FROM p{player} TO p{p}')
                bot.eklipz_bot.notify_tile_ping(tile)

    def notify_chat_message(self, player: int, message: str, teamChat: bool):
        bot: BotHostBase
        for p, bot in enumerate(self.bot_hosts):
            if p == player or bot is None or bot.eklipz_bot is None:
                continue
            if not teamChat or self.sim.sim_map.teams[player] == self.sim.sim_map.teams[p]:
                chatUpdate = ChatUpdate(self.sim.sim_map.usernames[player], teamChat, message)
                logging.info(f'SIM NOTIFYING CHAT {str(chatUpdate)} FROM p{player} TO p{p}')
                bot.eklipz_bot.notify_chat_message(chatUpdate)

    def any_bot_has_viewer_running(self) -> bool:
        for bot in self.bot_hosts:
            if bot is not None and bot.has_viewer and not bot.is_viewer_closed():
                return True

        return False

    def wait_until_viewer_closed_or_time_elapses(self, max_seconds_to_wait: float):
        if not self.any_bot_has_viewer_running():
            return

        start = time.perf_counter()
        logging.info(f'(WAITING UNTIL YOU CLOSE THE VIEWER OR {max_seconds_to_wait} SECONDS ELAPSES....)')
        while self.any_bot_has_viewer_running() and time.perf_counter() - start < max_seconds_to_wait:
            time.sleep(1)
