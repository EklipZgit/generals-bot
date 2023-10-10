import argparse
import logging
import queue
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
        placeMoveFunc: typing.Callable[[Tile, Tile, bool], None],
        gameType: str,
        noUi: bool = True,
        alignBottom: bool = False,
        alignRight: bool = False,
        throw: bool = False,
        noLog: bool = False
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

        self.place_move_func: typing.Callable[[Tile, Tile, bool], None] = placeMoveFunc

        self.eklipz_bot = EklipZBot(threadCount=42069)
        self.has_viewer: bool = not FORCE_NO_VIEWER and not noUi

        self.align_bottom: bool = alignBottom
        self.align_right: bool = alignRight

        self._viewer: ViewerHost | None = None
        self.rethrow: bool = throw
        self.noLog: bool = noLog

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
                        self.place_move_func(move.source, move.dest, move.move_half)

            if not self.eklipz_bot.no_file_logging:
                with moveTimer.begin_event(f'Dump {currentMap.turn}.txtmap to disk'):
                    self.save_txtmap(currentMap)

            if self.has_viewer and self._viewer is not None:
                with moveTimer.begin_event(f'Sending turn {currentMap.turn} update to Viewer'):
                    self.eklipz_bot.viewInfo.perfEvents.extend(moveTimer.get_events_organized_longest_to_shortest(limit=15, indentSize=2))
                    self._viewer.send_update_to_viewer(self.eklipz_bot.viewInfo, currentMap, currentMap.complete)

            with moveTimer.begin_event(f'Main thread check for pygame exit'):
                if self.is_viewer_closed_by_user():
                    currentMap.complete = True
                    currentMap.result = False
                    self.notify_game_over()

        return

    def receive_update_no_move(self, currentMap: MapBase):
        timer: PerformanceTimer = self.eklipz_bot.perf_timer
        timer.record_update(currentMap.turn)

        if not self.eklipz_bot.isInitialized:
            self.eklipz_bot.initialize_map_for_first_time(currentMap)
        self.eklipz_bot._map = currentMap

        startTime = time.perf_counter()
        with timer.begin_move(currentMap.turn) as moveTimer:
            try:
                with moveTimer.begin_event(f'Init turn - no move'):
                    self.eklipz_bot.init_turn()
            except:
                errMsg = traceback.format_exc()
                self.eklipz_bot.viewInfo.addAdditionalInfoLine(f'ERROR: {errMsg}')
                logging.error('ERROR: IN EKBOT.init_turn():')
                logging.error(errMsg)
                if self.rethrow:
                    raise

            duration = time.perf_counter() - startTime
            self.eklipz_bot.viewInfo.lastMoveDuration = duration
            self.eklipz_bot.viewInfo.addAdditionalInfoLine(f'Missed move chance turn {currentMap.turn}')

            if not self.eklipz_bot.no_file_logging:
                with moveTimer.begin_event(f'Dump {currentMap.turn}.txtmap to disk'):
                    self.save_txtmap(currentMap)

            if self.has_viewer and self._viewer is not None:
                with moveTimer.begin_event(f'Sending turn {currentMap.turn} update to Viewer'):
                    self.eklipz_bot.viewInfo.perfEvents.extend(moveTimer.get_events_organized_longest_to_shortest(limit=15, indentSize=2))
                    self._viewer.send_update_to_viewer(self.eklipz_bot.viewInfo, currentMap, currentMap.complete)

            with moveTimer.begin_event(f'Main thread check for pygame exit'):
                if self.is_viewer_closed_by_user():
                    currentMap.complete = True
                    currentMap.result = False
                    self.notify_game_over()


    def save_txtmap(self, map: MapBase):
        if self.noLog:
            return
        try:
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
        except:
            logging.error(traceback.format_exc())

    def initialize_viewer(self, skip_file_logging: bool = False):
        window_title = "%s (%s)" % (self._name.split('_')[-1], self._game_type)
        self._viewer = ViewerHost(window_title, alignTop=not self.align_bottom, alignLeft=not self.align_right, noLog=skip_file_logging)

    def is_viewer_closed_by_user(self) -> bool:
        if self.has_viewer and self._viewer is not None and self._viewer.check_viewer_closed():
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
            alignRight: bool,
            noLog: bool,
    ):
        super().__init__(name, self.place_move, gameType, noUi, alignBottom, alignRight, noLog=noLog)

        if FORCE_PRIVATE and self._game_type != 'private':
            raise AssertionError('Bot forced private only for the moment')

        # also creates the viewer, for now. Need to move that out to view sim games
        self.bot_client = bot_base.GeneralsClientHost(
            self.make_move,
            self.receive_update_no_move,
            name=self._name,
            userId=userId,
            gameType=self._game_type,
            privateRoomID=roomId,
            public_server=isPublic)

        self.eklipz_bot.clear_moves_func = self.bot_client.send_clear_moves

    # returns whether the placed move was valid
    def place_move(self, source: Tile, dest: Tile, move_half=False):
        if source.army == 1 or source.army == 0:
            logging.info(
                f"BOT PLACED BAD MOVE! {source.x},{source.y} to {dest.x},{dest.y}. Will send anyway, i guess.")
        else:
            logging.info(f"Placing move: {source.x},{source.y} to {dest.x},{dest.y}")
        self.bot_client.place_move(source, dest, move_half=move_half)

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
    parser.add_argument('--no-log', action='store_true', help="Skip all logging")
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
    noLog = args['no_log']
    alignBottom: bool = args['bottom']
    alignRight: bool = args['right']

    if not noLog:
        BotLogging.set_up_logger(logging.INFO)

    logging.info("newing up bot host")
    host = BotHostLiveServer(name, gameType, roomId, userId, isPublic, noUi, alignBottom, alignRight, noLog=noLog)

    logging.info("running bot host")
    host.run()
