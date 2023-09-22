import logging
import time
import traceback
import typing

from BotHost import BotHostBase
from DataModels import Move
from Path import Path
from SearchUtils import count, where
from base.bot_base import create_thread
from base.client.map import MapBase, Tile, TILE_EMPTY, TILE_OBSTACLE, Score, TILE_FOG, TILE_MOUNTAIN, TileDelta
from bot_ek0x45 import EklipZBot


def generate_player_map(player_index: int, map_raw: MapBase) -> MapBase:
    playerMap = [[Tile(x, y, tile=TILE_FOG, army=0, player=-1) for x in range(map_raw.cols)] for y in
                 range(map_raw.rows)]

    scores = [Score(n, map_raw.players[n].score, map_raw.players[n].tileCount, map_raw.players[n].dead) for n in
              range(0, len(map_raw.players))]

    map = MapBase(player_index=player_index, teams=None, user_names=map_raw.usernames, turn=map_raw.turn,
                  map_grid_y_x=playerMap, replay_url='42069')
    map.update_scores(scores)
    map.update_turn(map_raw.turn)
    for x in range(map_raw.cols):
        for y in range(map_raw.rows):
            realTile = map_raw.grid[y][x]

            hasVision = realTile.player == player_index or any(
                filter(lambda tile: tile.player == player_index, realTile.adjacents))

            if hasVision:
                map.update_visible_tile(realTile.x, realTile.y, realTile.tile, realTile.army, realTile.isCity, realTile.isGeneral)
                if realTile.isMountain:
                    map.grid[realTile.y][realTile.x].tile = TILE_MOUNTAIN
                    map.grid[realTile.y][realTile.x].isMountain = True
            else:
                if realTile.isCity or realTile.isMountain:
                    map.update_visible_tile(realTile.x, realTile.y, TILE_OBSTACLE, tile_army=0, is_city=False, is_general=False)
                else:
                    map.update_visible_tile(realTile.x, realTile.y, TILE_FOG, tile_army=0, is_city=False, is_general=False)

    map.update()

    return map

def generate_player_map_with_pre_existing_vision(player_index: int, map_raw: MapBase) -> MapBase:
    playerMap = [[Tile(x, y, tile=TILE_FOG, army=0, player=-1) for x in range(map_raw.cols)] for y in range(map_raw.rows)]

    scores = [Score(n, map_raw.players[n].score, map_raw.players[n].tileCount, map_raw.players[n].dead) for n in range(0, len(map_raw.players))]

    map = MapBase(player_index=player_index, teams=None, user_names=map_raw.usernames, turn=map_raw.turn, map_grid_y_x=playerMap, replay_url='42069')
    map.update_scores(scores)
    map.update_turn(map_raw.turn)
    for x in range(map_raw.cols):
        for y in range(map_raw.rows):
            playerTile = playerMap[y][x]
            realTile = map_raw.grid[y][x]

            hasVision = realTile.player == player_index or any(filter(lambda tile: tile.player == player_index, realTile.adjacents))
            playerTile.visible = hasVision
            playerTile.discovered = hasVision

            if hasVision:
                playerTile.isCity = realTile.isCity
                playerTile.isMountain = realTile.isMountain
                playerTile.player = realTile.player
                playerTile.tile = realTile.tile
                playerTile.army = realTile.army
                playerTile.isGeneral = realTile.isGeneral
                if playerTile.isGeneral:
                    map.generals[playerTile.player] = playerTile
            else:
                if realTile.isCity or realTile.isMountain:
                    playerTile.tile = TILE_OBSTACLE

    map.update()

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
            if tile.army != 0 and not playerTile.visible:
                playerTile.army = tile.army
                playerTile.player = tile.player
                playerTile.discovered = True
                playerTile.visible = False
                playerTile.isCity = tile.isCity
                playerTile.isMountain = tile.isMountain
                playerTile.isGeneral = tile.isGeneral
                # playerTile.tile = tile.tile
            if playerTile.isGeneral:
                self.map.players[playerTile.player].general = playerTile
                self.map.generals[playerTile.player] = playerTile


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

        self.players: typing.List[GamePlayer] = [GamePlayer(map_raw, i) for i in range(len(map_raw.players))]
        self.turn: int = map_raw.turn
        self.sim_map: MapBase = map_raw
        self.moves: typing.List[typing.Union[None, Move]] = [None for i in range(len(map_raw.players))]
        self.moves_history: typing.List[typing.List[typing.Union[None, Move]]] = []
        self.tiles_updated_this_cycle: typing.Set[Tile] = set()
        self.ignore_illegal_moves = ignore_illegal_moves

    def make_move(self, player_index: int, move: Move, force: bool = False) -> bool:
        if self.moves[player_index] is not None:
            if not force:
                raise AssertionError(f'player {player_index} already has a move queued this turn, {str(self.moves[player_index])}')
        self.moves[player_index] = move
        return True

    def execute_turn(self, dont_require_all_players_to_move=False):
        moveOrder = [pair for pair in enumerate(self.moves)]
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
        self._update_map_values()
        self.send_update_to_player_maps()
        self.tiles_updated_this_cycle = set()

    def is_game_over(self) -> bool:
        for player in self.players:
            if player.map.complete:
                player.dead = True

        if count(self.players, lambda player: not player.dead) > 1:
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
        if destTile.player == player_index:
            destTile.army += armyBeingMoved
        else:
            destPlayer = None
            if destTile.player >= 0:
                destPlayer = self.players[destTile.player]
            destTile.army -= armyBeingMoved

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
                    mapTile.army = mapTile.army // 2
                    self.tiles_updated_this_cycle.add(mapTile)
                    self._stage_tile_captured_events(mapTile, capturer, captured)

        captured.set_captured(capturer.index)

    def _update_map_values(self):
        self.sim_map.turn += 1
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
            player.map.update_turn(self.turn)

            playerScoreClone = [Score(score.player, score.total, score.tiles, score.dead) for score in self.sim_map.scores]
            player.map.update_scores(playerScoreClone)
            # give all players in the game perfect information about each others cities like they would have in a normal game by that turn
            for i, otherPlayer in enumerate(self.players):
                player.map.players[i].cityCount = otherPlayer.map.players[otherPlayer.map.player_index].cityCount

        # send updates for tiles they lost vision of
        # send updates for tiles they can see
        for tile in self.sim_map.get_all_tiles():
            # the way the game client works, it always 'updates' every tile on the players map even if it didn't get a server update, that's why the deltas were ghosting in the sim
            # if tile in self.tiles_updated_this_cycle:
            for player in self.players:
                playerHasVision = tile.player == player.index or any(filter(lambda adj: adj.player == player.index, tile.adjacents))
                if playerHasVision:
                    player.map.update_visible_tile(tile.x, tile.y, tile.tile, tile.army, tile.isCity, tile.isGeneral)
                else:
                    self._send_player_lost_vision_of_tile(player, tile)

        for player in self.players:
            if noDeltas:
                player.map.clear_deltas_and_score_history()
            player.map.update()
            player.tiles_lost_this_turn = set()
            player.tiles_gained_this_turn = set()

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
        self._update_scores()
        self._send_updates_to_player_maps(noDeltas)

    def reset_player_map_deltas(self):
        for player in self.players:
            player.map.clear_deltas_and_score_history()


class GameSimulatorHost(object):
    def __init__(self, map: MapBase, player_with_viewer: int = -1, playerMapVision: MapBase | None = None, afkPlayers: None | typing.List[int] = None, allAfkExceptMapPlayer: bool =False):
        self.move_queue: typing.List[typing.List[Move | None]] = [[] for player in map.players]
        self.sim = GameSimulator(map, ignore_illegal_moves=False)

        self.bot_hosts: typing.List[BotHostBase | None] = [None for player in self.sim.players]

        self._between_turns_funcs: typing.List[typing.Callable] = []

        self.forced_afk_players: typing.List[int] = []
        if afkPlayers is not None:
            self.forced_afk_players = afkPlayers

        if allAfkExceptMapPlayer:
            self.forced_afk_players = [i for i in where(range(len(map.players)), lambda p: p != map.player_index)]

        charMap = {
            0: 'a',
            1: 'b',
            2: 'c',
            3: 'd',
            4: 'e',
            5: 'f',
            6: 'g',
            7: 'h'
        }

        for i in range(len(self.bot_hosts)):
            char = charMap[i]
            if i in self.forced_afk_players:
                # just leave the botHost as None for the afk player
                continue
            hasUi = i == player_with_viewer or player_with_viewer == -2
            # i=i captures the current value of i in the lambda, otherwise all players lambdas would send the last players player index...
            botMover = lambda source, dest, moveHalf, i=i: self.sim.make_move(player_index=i, move=Move(source, dest, moveHalf))
            botHost = BotHostBase(char, botMover, 'test', noUi=not hasUi, alignBottom=True, throw=True)
            if hasUi:
                botHost.initialize_viewer()

            self.bot_hosts[i] = botHost

        if playerMapVision is not None:
            self.apply_map_vision(playerMapVision.player_index, rawMap=playerMapVision)

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
            botHost.eklipz_bot.targetPlayer = (botHost.eklipz_bot.general.player + 1) % 2
            botHost.eklipz_bot.targetPlayerObj = botHost.eklipz_bot._map.players[botHost.eklipz_bot.targetPlayer]
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
        for playerIndex, botHost in enumerate(self.bot_hosts):
            if botHost is None:
                continue
            if botHost.has_viewer and run_real_time:
                botHost.run_viewer_loop()

        if run_real_time:
            # time to look at the first move
            time.sleep(2)

        winner = None
        try:
            turnsRun = 0
            while turnsRun < turns:
                winner = self.execute_turn(run_real_time=run_real_time, turn_time=turn_time)
                if winner is not None:
                    break
                turnsRun += 1
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
            raise

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

    def reveal_player_general(self, playerToReveal, playerToRevealTo, hidden=False):
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
        playerObj = self.sim.players[player]
        paths = moves_str.split('  ')
        for path_str in paths:
            if path_str.strip().lower() == 'none':
                self.move_queue[player].append(None)
                continue

            moves = path_str.split('->')
            prevTile: Tile | None = None
            for move_str in moves:
                xStr, yStr = move_str.strip().split(',')
                moveHalf=False
                if yStr.endswith('z'):
                    moveHalf = True
                    yStr.strip('z')

                currentTile = playerObj.map.GetTile(int(xStr), int(yStr))
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
                botHost.make_move(player.map)

            # if we have a move queued explicitly, overwrite their move with the test-forced move.
            if len(self.move_queue[playerIndex]) > 0:
                move = self.move_queue[playerIndex].pop(0)
                if self.sim.sim_map.GetTile(move.source.x, move.source.y).player == playerIndex:
                    self.sim.make_move(playerIndex, move, force=True)
                if self.bot_hosts[playerIndex] is not None:
                    fullArmy = self.sim.sim_map.GetTile(move.source.x, move.source.y).army
                    move.army_moved = fullArmy - 1
                    if move.move_half:
                        move.army_moved = fullArmy // 2

                    self.bot_hosts[playerIndex].eklipz_bot.armyTracker.lastMove = move
                    self.bot_hosts[playerIndex].eklipz_bot.history.move_history[self.sim.turn] = [move]

        for func in self._between_turns_funcs:
            try:
                func()
            except:
                if run_real_time:
                    logging.error(f'assertion failure while running live, turn {self.sim.turn}')
                    logging.error(traceback.format_exc())
                    time.sleep(20)
                raise

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
                try:
                    func()
                except:
                    if run_real_time:
                        logging.error(f'assertion failure while running live, turn {self.sim.turn}')
                        logging.error(traceback.format_exc())
                        time.sleep(20)
                    raise
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
