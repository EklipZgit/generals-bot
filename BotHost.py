import argparse
import logging
import sys
import time
import traceback
import typing

from DataModels import Move
from PerformanceTimer import PerformanceTimer
from Sim.TextMapLoader import TextMapLoader
from Viewer.ViewerProcessHost import ViewerHost
from base import bot_base
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot

FORCE_NO_VIEWER = False
FORCE_PRIVATE = False


class BotHostBase(object):
    def __init__(
        self,
        name: str,
        placeMoveFunc: typing.Callable[[Tile, Tile, bool], bool],
        gameType: str,
        noUi: bool = True,
        alignBottom: bool = False,
        alignRight: bool = False,
        throw: bool = False
    ):
        """

        @param name:
        @param placeMoveFunc:
        @param gameType:
        @param noUi:
        @param alignBottom:
        @param alignRight:
        @param throw: whether to let exceptions from the bot throw, or just log them.
        (Generally throw in sim / tests, but not in game or else we dont write the bad map state etc)
        """
        self._name = name
        self._game_type = gameType

        self.place_move_func: typing.Callable[[Tile, Tile, bool], bool] = placeMoveFunc

        self.eklipz_bot = EklipZBot(threadCount=42069)
        self.has_viewer: bool = not FORCE_NO_VIEWER and not noUi

        self.align_bottom: bool = alignBottom
        self.align_right: bool = alignRight

        self._viewer: ViewerHost | None = None
        self.rethrow = throw

    def run_viewer_loop(self):
        logging.info("attempting to start viewer loop")
        self._viewer.start()

    def make_move(self, currentMap: MapBase):
        # todo most of this logic / timing / whatever should move into EklipZbot...
        timer: PerformanceTimer = self.eklipz_bot.perf_timer
        timer.record_update(currentMap.turn)

        if not self.eklipz_bot.isInitialized:
            self.eklipz_bot.initialize_map_for_first_time(currentMap)
        self.eklipz_bot._map = currentMap

        startTime = time.perf_counter()
        with timer.begin_move(currentMap.turn) as moveTimer:
            move: Move | None = None
            try:
                move = self.eklipz_bot.find_move()
            except:
                errMsg = traceback.format_exc()
                self.eklipz_bot.viewInfo.addAdditionalInfoLine(f'ERROR: {errMsg}')
                logging.error('ERROR: IN EKBOT.find_move():')
                logging.error(errMsg)
                if self.rethrow:
                    raise

            duration = time.perf_counter() - startTime
            self.eklipz_bot.viewInfo.lastMoveDuration = duration
            if move is not None:
                if move.source.army == 1 or move.source.army == 0 or move.source.player != self.eklipz_bot.general.player:
                    logging.info(
                        f"!!!!!!!!! {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} was a bad move from enemy / 1 tile!!!! This turn will do nothing :(")
                else:
                    with moveTimer.begin_event(f'Sending move {str(move)} to server'):
                        if not self.place_move_func(move.source, move.dest, move.move_half):
                            logging.info(
                                "!!!!!!!!! {},{} -> {},{} was an illegal move!!!! This turn will do nothing :(".format(
                                    move.source.x, move.source.y,
                                    move.dest.x, move.dest.y))

            if self.has_viewer:
                with moveTimer.begin_event(f'Sending turn {currentMap.turn} update to Viewer'):
                    if timer:
                        max = 15
                        cur = 0
                        for entry in sorted(timer.current_move.event_list, key=lambda e: e.get_duration(),
                                            reverse=True):
                            self.eklipz_bot.viewInfo.perfEvents.append(
                                f'{entry.get_duration():.3f} {entry.event_name}'.lstrip('0'))
                            cur += 1
                            if cur > max:
                                break
                    self._viewer.send_update_to_viewer(self.eklipz_bot.viewInfo, currentMap, currentMap.complete)

            with moveTimer.begin_event(f'Dump {currentMap.turn}.txtmap to disk'):
                self.save_txtmap(currentMap)
            with moveTimer.begin_event(f'Main thread check for pygame exit'):
                if self.is_viewer_closed_by_user():
                    currentMap.complete = True
                    currentMap.result = False
                    self.notify_game_over()

        return

    def save_txtmap(self, map: MapBase):
        try:
            mapStr = TextMapLoader.dump_map_to_string(map, split_every=5)
        except:
            try:
                mapStr = TextMapLoader.dump_map_to_string(map, split_every=6)
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)

                logging.info(f'failed to dump map, {lines}')
                mapStr = f'failed to dump map, {lines}'

        ekBotData = self.eklipz_bot.dump_turn_data_to_string()

        mapStr = f'{mapStr}\n{ekBotData}'

        mapFilePath = "{}\\{}.txtmap".format(self.eklipz_bot.logDirectory, map.turn)

        with open(mapFilePath, 'w') as mapFile:
            mapFile.write(mapStr)

    def initialize_viewer(self):
        window_title = "%s (%s)" % (self._name.split('_')[-1], self._game_type)
        self._viewer = ViewerHost(window_title, alignTop=not self.align_bottom, alignLeft=not self.align_right)

    def is_viewer_closed_by_user(self) -> bool:
        if self.has_viewer and self._viewer.check_viewer_closed():
            return True
        return False

    def notify_game_over(self):
        self.eklipz_bot._map.complete = True
        if self.has_viewer and self._viewer is not None:
            self._viewer.send_update_to_viewer(
                self.eklipz_bot.viewInfo,
                self.eklipz_bot._map,
                isComplete=True)
            self._viewer.kill()


class BotHostLiveServer(BotHostBase):
    def __init__(
            self,
            name: str,
            gameType: str,
            roomId: str | None,
            userId: str | None,
            isPublic: bool,
            noUi: bool,
            alignBottom: bool,
            alignRight: bool
    ):
        super().__init__(name, self.place_move, gameType, noUi, alignBottom, alignRight)

        if FORCE_PRIVATE and self._game_type != 'private':
            raise AssertionError('Bot forced private only for the moment')

        # also creates the viewer, for now. Need to move that out to view sim games
        self.bot_client = bot_base.GeneralsClientHost(
            self.make_move,
            name=self._name,
            userId=userId,
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

        # Start Game Viewer
        if self.has_viewer:
            logging.info("attempting to initialize viewer")
            self.initialize_viewer()
            self.run_viewer_loop()

        logging.info("attempting to run bot_client")
        try:
            self.bot_client.run(addlThreads)
        except KeyboardInterrupt:
            logging.info('keyboard interrupt received, killing viewer if any')
            self.notify_game_over()
        except:
            logging.info('unknown error occurred in bot_client.run(), notifying game over. Error was:')
            logging.info(traceback.format_exc())

            self.notify_game_over()


if __name__ == '__main__':
    import BotLogging

    BotLogging.set_up_logger(logging.INFO)

    # raise AssertionError("stop")
    parser = argparse.ArgumentParser()
    parser.add_argument('-name', metavar='str', type=str, default='helpImAlive2',
                        help='Name of Bot')
    parser.add_argument('-userID', metavar='str', type=str, default='--',
                        help='User ID to use')
    parser.add_argument('-g', '--gameType', metavar='str', type=str,
                        choices=["private", "custom", "1v1", "ffa", "team"],
                        default="private", help='Game Type: private, custom, 1v1, ffa, or team')
    parser.add_argument('--roomID', metavar='str', type=str, default="testing", help='Private Room ID (optional)')
    # parser.add_argument('--roomID', metavar='str', type=str, help='Private Room ID (optional)')
    parser.add_argument('--right', action='store_true')
    parser.add_argument('--bottom', action='store_true')
    parser.add_argument('--no-ui', action='store_true', help="Hide UI (no game viewer)")
    parser.add_argument('--public', action='store_true', help="Run on public (not bot) server")
    args = vars(parser.parse_args())

    name: str = args['name']
    userId: str | None = args['userID']
    if userId == '--':
        userId = None
    gameType: str = args['gameType']
    roomId = args['roomID']
    isPublic: bool = args['public']
    noUi = args['no_ui']
    alignBottom: bool = args['bottom']
    alignRight: bool = args['right']

    logging.info("newing up bot host")
    host = BotHostLiveServer(name, gameType, roomId, userId, isPublic, noUi, alignBottom, alignRight)

    logging.info("running bot host")
    host.run()
