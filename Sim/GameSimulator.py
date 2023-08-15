import logging
import time
import traceback
import typing

from BotHost import BotHostBase
from DataModels import Move
from SearchUtils import count
from base.bot_base import create_thread
from base.client.map import MapBase, Tile, TILE_EMPTY, TILE_OBSTACLE, Score, TILE_FOG, TILE_MOUNTAIN


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
        self.dead: bool = False
        self.captured_by: int = -1

    def set_captured(self, captured_by_player: int):
        self.dead = True
        self.captured_by = captured_by_player


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
        self.tiles_updated_this_cycle: typing.Set[Tile] = set()
        self.ignore_illegal_moves = ignore_illegal_moves

    def make_move(self, player_index: int, move: Move) -> bool:
        if self.moves[player_index] is not None:
            raise AssertionError(f'player {player_index} already has a move queued this turn, {str(self.moves[player_index])}')
        self.moves[player_index] = move
        return True

    def execute_turn(self, dont_require_all_players_to_move=False):
        moveOrder = [pair for pair in enumerate(self.moves)]
        if self.turn % 2 == 0:
            moveOrder = reversed(moveOrder)

        for player, move in moveOrder:
            if move is None:
                if not dont_require_all_players_to_move:
                    raise AssertionError(f'player {player} does not have a move queued yet for turn {self.turn}')
                continue

            self._execute_move(player, move)

        self.turn = self.turn + 1
        self.moves = [None for _ in self.moves]
        self._update_map_values()
        self._update_scores()
        self._send_updates_to_player_maps()
        self.tiles_updated_this_cycle = set()

    def is_game_over(self) -> bool:
        for player in self.players:
            if player.map.complete:
                player.dead = True

        if count(self.players, lambda player: not player.dead) > 1:
            return False

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

    def _send_updates_to_player_maps(self):
        # actual server client map executes in this order:
        # turn
        # scores
        # tile data
        # call update

        for player in self.players:
            player.map.update_turn(self.turn)

            playerScoreClone = [Score(score.player, score.total, score.tiles, score.dead) for score in self.sim_map.scores]
            player.map.update_scores(playerScoreClone)

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

    def reveal_player_general(self, playerToReveal, playerToRevealTo):
        revealGeneral = self.sim_map.generals[playerToReveal]

        player = self.players[playerToRevealTo]

        player.map.update_visible_tile(revealGeneral.x, revealGeneral.y, revealGeneral.player, revealGeneral.army, is_city=False, is_general=True)
        player.map.update_visible_tile(revealGeneral.x, revealGeneral.y, TILE_FOG, 0, is_city=False, is_general=False)


class GameSimulatorHost(object):
    def __init__(self, map: MapBase, player_with_viewer: int = -1):
        self.sim = GameSimulator(map, ignore_illegal_moves=False)

        self.bot_hosts: typing.List[BotHostBase | None] = [None for player in self.sim.players]

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
            hasUi = i == player_with_viewer or player_with_viewer == -2
            # i=i captures the current value of i in the lambda, otherwise all players lambdas would send the last players player index...
            botMover = lambda source, dest, moveHalf, i=i: self.sim.make_move(player_index=i, move=Move(source, dest, moveHalf))
            botHost = BotHostBase(char, botMover, 'test', noUi=not hasUi, alignBottom=True)
            if hasUi:
                botHost.initialize_viewer()

            self.bot_hosts[i] = botHost

    def run_sim(self, run_real_time: bool = True, turn_time: float = 0.5):
        try:
            for botHost in self.bot_hosts:
                if botHost.has_viewer:
                    botHost.run_viewer_loop()
            while self.sim.turn < 2500:
                logging.info(f'sim starting turn {self.sim.turn}')
                start = time.perf_counter()
                for playerIndex, botHost in enumerate(self.bot_hosts):
                    player = self.sim.players[playerIndex]
                    if not player.dead:
                        botHost.make_move(player.map)
                if run_real_time:
                    elapsed = time.perf_counter() - start
                    if elapsed < turn_time:
                        time.sleep(turn_time - elapsed)

                self.sim.execute_turn(dont_require_all_players_to_move=True)

                gameEndedByUser = False
                for botHost in self.bot_hosts:
                    if botHost.has_viewer and botHost.is_viewer_closed_by_user():
                        gameEndedByUser = True

                if self.sim.is_game_over() or gameEndedByUser:
                    self.sim.end_game()
                    for botHost in self.bot_hosts:
                        botHost.notify_game_over()
                    break
        except:
            self.sim.end_game()
            try:
                for botHost in self.bot_hosts:
                    botHost.notify_game_over()
            except:
                logging.info("(error v notifying bots of game over, less important than real error below)")
                logging.info(traceback.format_exc())
                logging.info("(error ^ notifying bots of game over, less important than real error below)")

            logging.info("(error v running bot sim)")
            logging.info(traceback.format_exc())
            raise

        self.sim.end_game()
        for botHost in self.bot_hosts:
            botHost.notify_game_over()

        logging.info('game over!')
