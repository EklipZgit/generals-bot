import argparse
import logging
import time
import typing

from PerformanceTimer import PerformanceTimer
from base import bot_base
from base.client.map import MapBase, Tile
from base.viewer import GeneralsViewer
from bot_ek0x45 import EklipZBot

FORCE_NO_VIEWER = False
FORCE_PRIVATE = False


class BotHostBase(object):
    def __init__(self, name: str, placeMoveFunc: typing.Callable[[Tile, Tile, bool], bool],  gameType: str, noUi: bool = True, alignBottom: bool = False, alignRight: bool = False):
        self._name = name
        self._game_type = gameType

        self.place_move_func: typing.Callable[[Tile, Tile, bool], bool] = placeMoveFunc

        self.eklipz_bot = EklipZBot(threadCount=42069)
        self.has_viewer: bool = not FORCE_NO_VIEWER and not noUi

        self.align_bottom: bool = alignBottom
        self.align_right: bool = alignRight

        self._viewer: GeneralsViewer = None

    # Consumes thread
    def run_viewer_loop(self):
        # Consumes thread
        self._viewer.run_main_viewer_loop(not self.align_bottom, not self.align_right)

    def make_move(self, currentMap: MapBase):
        # todo most of this logic / timing / whatever should move into EklipZbot...
        timer: PerformanceTimer = self.eklipz_bot.perf_timer
        timer.record_update(currentMap.turn)

        if self.eklipz_bot._map is None:
            self.eklipz_bot._map = currentMap

        startTime = time.perf_counter()
        with timer.begin_move(currentMap.turn) as moveTimer:
            move = self.eklipz_bot.find_move()
            duration = time.perf_counter() - startTime
            self.eklipz_bot.viewInfo.lastMoveDuration = duration
            if move is not None:
                if move.source.army == 1 or move.source.army == 0 or move.source.player != self.eklipz_bot.general.player:
                    logging.info(f"!!!!!!!!! {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} was a bad move from enemy / 1 tile!!!! This turn will do nothing :(")
                else:
                    with moveTimer.begin_event(f'Sending move {str(move)} to server'):
                        if not self.place_move_func(move.source, move.dest, move.move_half):
                            logging.info(
                                "!!!!!!!!! {},{} -> {},{} was an illegal move!!!! This turn will do nothing :(".format(
                                    move.source.x, move.source.y,
                                    move.dest.x, move.dest.y))

            if self.has_viewer:
                self._viewer.updateGrid(currentMap)

        return

    def initialize_viewer(self):
        window_title = "%s (%s)" % (self._name, self._game_type)
        self._viewer = GeneralsViewer(window_title)
        self._viewer.ekBot = self.eklipz_bot

    def notify_game_over(self):
        self.eklipz_bot._map.complete = True
        if self.has_viewer:
            self._viewer.kill()


class BotHost(BotHostBase):
    def __init__(
            self,
            name: str,
            gameType: str,
            roomId: typing.Union[None, str],
            isPublic: bool,
            noUi: bool,
            alignBottom: bool,
            alignRight: bool
    ):
        super().__init__(name, self.place_move, gameType, noUi, alignBottom, alignRight)

        if FORCE_PRIVATE and self._game_type != 'private':
            raise AssertionError('Bot forced private only for the moment')

        # also creates the viewer, for now. Need to move that out to view sim games
        self.bot_client = bot_base.GeneralsBot(
            self.make_move,
            name=self._name,
            gameType=self._game_type,
            privateRoomID=roomId,
            public_server=isPublic)

        self.eklipz_bot.clear_moves_func = self.bot_client.send_clear_moves

    # returns whether the placed move was valid
    def place_move(self, source: Tile, dest: Tile, move_half=False) -> bool:
        if source.army == 1 or source.army == 0:
            logging.info(
                "BOT PLACED BAD MOVE! {},{} to {},{}. Will send anyway, i guess.".format(source.x, source.y, dest.x,
                                                                                         dest.y))
        else:
            logging.info("Placing move: {},{} to {},{}".format(source.x, source.y, dest.x, dest.y))
        return self.bot_client.place_move(source, dest, move_half=move_half)

    # consumes main thread until game complete
    def run(self):
        addlThreads = []
        viewerUpdateCallback = None

        # Start Game Viewer
        if self.has_viewer:
            self.initialize_viewer()
            addlThreads.append(self.run_viewer_loop)
            viewerUpdateCallback = self._viewer.updateGrid

        self.bot_client.run(addlThreads, viewerUpdateCallback)


if __name__ == '__main__':
    # raise AssertionError("stop")
    parser = argparse.ArgumentParser()
    parser.add_argument('-name', metavar='str', type=str, default='42069',
                        help='Name of Bot')
    parser.add_argument('-g', '--gameType', metavar='str', type=str,
                        choices=["private", "custom", "1v1", "ffa", "team"],
                        default="ffa", help='Game Type: private, custom, 1v1, ffa, or team')
    # parser.add_argument('--roomID', metavar='str', type=str, default="EklipZ_ai", help='Private Room ID (optional)')
    parser.add_argument('--roomID', metavar='str', type=str, help='Private Room ID (optional)')
    parser.add_argument('--right', action='store_true')
    parser.add_argument('--bottom', action='store_true')
    parser.add_argument('--no-ui', action='store_true', help="Hide UI (no game viewer)")
    parser.add_argument('--public', action='store_true', help="Run on public (not bot) server")
    args = vars(parser.parse_args())

    name: str = args['name']
    gameType: str = args['gameType']
    roomId = args['roomID']
    isPublic: bool = args['public']
    noUi = args['no_ui']
    alignBottom: bool = args['bottom']
    alignRight: bool = args['right']

    host = BotHost(name, gameType, roomId, isPublic, noUi, alignBottom, alignRight)
    host.run()
