import argparse
import gc
import signal
import time
from multiprocessing.context import DefaultContext, DefaultContext
from multiprocessing.managers import SyncManager

import logbook
import multiprocessing
import sys
import traceback
import typing

from ArmyAnalyzer import ArmyAnalyzer
from Models import Move
from MapMatrix import MapMatrix
from PerformanceTimer import PerformanceTimer, NS_CONVERTER
from Sim.TextMapLoader import TextMapLoader
from base import bot_base
from base.client.generals import ChatUpdate
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot

from Viewer.ViewerProcessHost import ViewerHost

FORCE_NO_VIEWER = False     # if you want the bot GUI to stop distracting you from work but you dont want to stop and restart all the bot shells with noUI, flip this flag and it will force the GUI off :)
FORCE_PRIVATE = False       # if you're making changes that are gonna break the bot and want to force it to only play in private rooms temporarily but dont want to kill all the shell loops, flip this flag, and it will keep restarting and wait for the flag to be flipped back before queuing again (except private games).


class BotHostBase(object):
    def __init__(
        self,
        name: str,
        placeMoveFunc: typing.Callable[[Tile, Tile, bool], None],
        pingTileFunc: typing.Callable[[Tile], None],
        sendChatFunc: typing.Callable[[str, bool], None],
        gameType: str,
        noUi: bool = True,
        alignBottom: bool = False,
        alignRight: bool = False,
        throw: bool = False,
        noLog: bool = False,
        ctx: DefaultContext | None = None,
        mgr: SyncManager | None = None,
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

        self.ping_tile_func: typing.Callable[[Tile], None] = pingTileFunc

        self.send_chat_func: typing.Callable[[str, bool], None] = sendChatFunc

        self.eklipz_bot: EklipZBot = EklipZBot()
        self.has_viewer: bool = not FORCE_NO_VIEWER and not noUi

        self.align_bottom: bool = alignBottom
        self.align_right: bool = alignRight
        self._viewer: ViewerHost | None = None
        self.rethrow: bool = throw
        self.noLog: bool = noLog
        self.ctx: DefaultContext | None = ctx
        self.mgr: SyncManager | None = mgr

    def run_viewer_loop(self):
        logbook.info("attempting to start viewer loop")
        self._viewer.start()

    def make_move(self, currentMap: MapBase, updateReceivedTime: float):
        # todo most of this logic / timing / whatever should move into EklipZbot...
        timer: PerformanceTimer = self.eklipz_bot.perf_timer
        now = (time.time_ns() / NS_CONVERTER)
        diff = now - updateReceivedTime
        if diff > 0.3:
            logbook.info(f'MISSED MOVE receiving turn {currentMap.turn}, update diff {diff:.5f}, (now {now:.5f} - updateReceivedTime {updateReceivedTime:.5f})')
            self.receive_update_no_move(currentMap, updateReceivedTime)
            return
        else:
            logbook.info(f'receiving turn {currentMap.turn}, update diff {diff:.5f}, (now {now:.5f} - updateReceivedTime {updateReceivedTime:.5f})')

        timer.record_update(currentMap.turn, updateReceivedTime)

        if not self.eklipz_bot.isInitialized:
            self.eklipz_bot.initialize_from_map_for_first_time(currentMap)
        # self.eklipz_bot._map = currentMap

        with timer.begin_move(currentMap.turn) as moveTimer:
            gap = timer.get_elapsed_since_update(currentMap.turn)
            quickTurn = gap > 0.05
            move: Move | None = None
            if gap > 0.15:
                with moveTimer.begin_event(f'LAG GAP Init turn {currentMap.turn} - no move chance / dropped move'):
                    self.eklipz_bot.init_turn()
                    self.eklipz_bot.viewInfo.add_info_line(f'LAG GAP OF {gap:.4f}, SKIPPING MOVE :(')
                    matrix = MapMatrix(self.eklipz_bot._map, True, emptyVal=False)
                    self.eklipz_bot.viewInfo.add_map_zone(matrix, (255, 140, 0), alpha=60)
            else:
                try:
                    move = self.eklipz_bot.find_move(is_lag_move=quickTurn)
                except:
                    errMsg = traceback.format_exc()
                    self.eklipz_bot.viewInfo.add_info_line(f'ERROR: {errMsg}')
                    logbook.error('ERROR: IN EKBOT.find_move():')
                    logbook.error(errMsg)
                    if self.rethrow:
                        raise

            duration = timer.get_elapsed_since_update(currentMap.turn)
            self.eklipz_bot.viewInfo.lastMoveDuration = duration
            if move is not None:
                if move.source.army == 1 or move.source.army == 0 or move.source.player != self.eklipz_bot.general.player:
                    logbook.info(
                        f"!!!!!!!!! {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} was a bad move from enemy / 1 tile!!!! This turn will do nothing :(")
                else:
                    with moveTimer.begin_event(f'Sending move {str(move)} to server'):
                        self.place_move_func(move.source, move.dest, move.move_half)

            tilePings = self.eklipz_bot.get_queued_tile_pings()
            for tilePing in tilePings:
                self.ping_tile_func(tilePing)

            teamChatMessages = self.eklipz_bot.get_queued_teammate_messages()
            for teamChatMessage in teamChatMessages:
                self.send_chat_func(teamChatMessage, True)

            allChatMessages = self.eklipz_bot.get_queued_all_chat_messages()
            for allChatMessage in allChatMessages:
                self.send_chat_func(allChatMessage, False)

            if not self.eklipz_bot.no_file_logging:
                with moveTimer.begin_event(f'Dump {currentMap.turn}.txtmap to disk'):
                    self.save_txtmap(currentMap)

            if self.has_viewer and self._viewer is not None:
                with moveTimer.begin_event(f'Sorting perfevents for {currentMap.turn} update to Viewer'):
                    self.eklipz_bot.viewInfo.perfEvents.extend(moveTimer.get_events_organized_longest_to_shortest(limit=30, indentSize=2))
                with moveTimer.begin_event(f'Sending turn {currentMap.turn} update to Viewer'):
                    # self.eklipz_bot.viewInfo.perfEvents.extend(moveTimer.get_events_organized_longest_to_shortest(limit=40, indentSize=2))
                    self._viewer.send_update_to_viewer(self.eklipz_bot.viewInfo, currentMap, currentMap.complete)

            logbook.info(f'MOVE {currentMap.turn} TIMINGS:\r\n' + '\r\n'.join(moveTimer.get_events_organized_longest_to_shortest(limit=100, indentSize=3)))
            ArmyAnalyzer.dump_times()
            ArmyAnalyzer.reset_times()
            self.eklipz_bot._map.distance_mapper.dump_times()
            self.eklipz_bot._map.distance_mapper.reset_times()

            with moveTimer.begin_event(f'Main thread check for pygame exit'):
                if self.is_viewer_closed_by_user():
                    currentMap.complete = True
                    currentMap.result = False
                    self.notify_game_over()

        gc.collect()

    def receive_update_no_move(self, currentMap: MapBase, updateReceivedTime: float):
        timer: PerformanceTimer = self.eklipz_bot.perf_timer

        timer.record_update(currentMap.turn, updateReceivedTime)

        if not self.eklipz_bot.isInitialized:
            self.eklipz_bot.initialize_from_map_for_first_time(currentMap)
        # self.eklipz_bot._map = currentMap

        with timer.begin_move(currentMap.turn) as moveTimer:
            try:
                with moveTimer.begin_event(f'Init turn {currentMap.turn} - no move chance / dropped move'):
                    self.eklipz_bot.init_turn()
            except:
                errMsg = traceback.format_exc()
                self.eklipz_bot.viewInfo.add_info_line(f'ERROR: {errMsg}')
                logbook.error('ERROR: IN EKBOT.init_turn():')
                logbook.error(errMsg)
                if self.rethrow:
                    raise

            duration = timer.get_elapsed_since_update(currentMap.turn)
            self.eklipz_bot.viewInfo.lastMoveDuration = duration
            self.eklipz_bot.viewInfo.add_info_line(f'Missed move chance turn {currentMap.turn}')
            matrix = MapMatrix(self.eklipz_bot._map, True, emptyVal=False)
            self.eklipz_bot.viewInfo.add_map_zone(matrix, (255, 70, 0), alpha=60)

            if not self.eklipz_bot.no_file_logging:
                with moveTimer.begin_event(f'Dump {currentMap.turn}.txtmap to disk'):
                    self.save_txtmap(currentMap)

            if self.has_viewer and self._viewer is not None:
                # with moveTimer.begin_event(f'Prep vi for render {currentMap.turn}'):
                #     self.eklipz_bot.prep_view_info_for_render(None)
                with moveTimer.begin_event(f'Sending turn {currentMap.turn} update to Viewer (no move)'):
                    self.eklipz_bot.prep_view_info_for_render(None)
                    self.eklipz_bot.viewInfo.perfEvents.extend(moveTimer.get_events_organized_longest_to_shortest(limit=30, indentSize=2))
                    self._viewer.send_update_to_viewer(self.eklipz_bot.viewInfo, currentMap, currentMap.complete)

            with moveTimer.begin_event(f'Main thread check for pygame exit'):
                if self.is_viewer_closed_by_user():
                    currentMap.complete = True
                    currentMap.result = False
                    self.notify_game_over()

        gc.collect()

    def save_txtmap(self, map: MapBase):
        if self.noLog:
            return
        try:
            try:
                mapStr = TextMapLoader.dump_map_to_string(map)
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)

                logbook.info(f'failed to dump map, {lines}')
                mapStr = f'failed to dump map, {lines}'

            ekBotData = self.eklipz_bot.dump_turn_data_to_string()

            mapStr = f'{mapStr}\n{ekBotData}'

            mapFilePath = "{}//{}.txtmap".format(self.eklipz_bot.logDirectory, map.turn)

            with open(mapFilePath, 'w') as mapFile:
                mapFile.write(mapStr)
        except:
            logbook.error(traceback.format_exc())

    def initialize_viewer(self, skip_file_logging: bool = False, onClick: typing.Callable[[Tile, bool], None] | None = None):
        window_title = f'{self._game_type} {self._name.split("_")[-1]}'
        self._viewer = ViewerHost(window_title, alignTop=not self.align_bottom, alignLeft=not self.align_right, noLog=skip_file_logging, onClick=onClick, ctx=self.ctx, mgr=self.mgr)

    def is_viewer_closed_by_user(self) -> bool:
        if self.has_viewer and self._viewer is not None and self._viewer.check_viewer_closed_by_user():
            return True
        return False

    def is_viewer_closed(self) -> bool:
        if self.has_viewer and self._viewer is not None and self._viewer.check_viewer_closed():
            return True
        return False

    def check_for_viewer_events(self):
        if self.has_viewer and self._viewer is not None and self._viewer.check_viewer_closed():
            self._viewer.handle_viewer_events()

    def notify_game_over(self):
        self.eklipz_bot._map.complete = True
        if self.has_viewer and self._viewer is not None:
            self._viewer.send_update_to_viewer(
                self.eklipz_bot.viewInfo,
                self.eklipz_bot._map,
                isComplete=True)
            self._viewer.kill()

    def handle_chat_message(self, chatUpdate: ChatUpdate):
        self.eklipz_bot.notify_chat_message(chatUpdate)

    def handle_tile_ping(self, pingedTile: Tile):
        self.eklipz_bot.notify_tile_ping(pingedTile)


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
            ctx: DefaultContext,
            mgr: SyncManager
    ):
        super().__init__(name, self.place_move, self.ping_server_tile, self.send_server_chat, gameType, noUi, alignBottom, alignRight, noLog=noLog, ctx=ctx, mgr=mgr)

        if FORCE_PRIVATE and self._game_type != 'private':
            raise AssertionError('Bot forced private only for the moment')

        # also creates the viewer, for now. Need to move that out to view sim games
        self.bot_client = bot_base.GeneralsClientHost(
            self.make_move,
            self.receive_update_no_move,
            handleChatMessage=self.handle_chat_message,
            handleTilePing=self.handle_tile_ping,
            name=self._name,
            userId=userId,
            gameType=self._game_type,
            privateRoomID=roomId,
            public_server=isPublic)

        self.eklipz_bot.clear_moves_func = self.bot_client.send_clear_moves
        self.eklipz_bot.surrender_func = self.bot_client.send_surrender

    # returns whether the placed move was valid
    def place_move(self, source: Tile, dest: Tile, move_half=False):
        if source.army == 1 or source.army == 0:
            logbook.info(
                f"BOT PLACED BAD MOVE! {source.x},{source.y} to {dest.x},{dest.y}. Will send anyway, i guess.")
        else:
            logbook.info(f"Placing move: {source.x},{source.y} to {dest.x},{dest.y}")
        self.bot_client.place_move(source, dest, move_half=move_half)

    def ping_server_tile(self, pingTile: Tile):
        self.bot_client.ping_tile(pingTile)

    def send_server_chat(self, chatMessage: str, teamChat: bool):
        self.bot_client.send_chat(chatMessage, teamChat)

    # consumes main thread until game complete
    def run(self):
        addlThreads = []

        # Start Game Viewer
        if self.has_viewer:
            logbook.info("attempting to initialize viewer")
            self.initialize_viewer()
            self.run_viewer_loop()

        logbook.info("attempting to run bot_client")
        try:
            self.bot_client.run(addlThreads)
        except KeyboardInterrupt:
            logbook.info('keyboard interrupt received, killing viewer if any')
            self.notify_game_over()
        except:
            logbook.info('unknown error occurred in bot_client.run(), notifying game over. Error was:')
            logbook.info(traceback.format_exc())

            self.notify_game_over()


def run_bothost(name, gameType, roomId, userId, isPublic, noUi, alignBottom, alignRight, noLog: bool = False):
    loggingProc = None
    mgr = None
    ctx: DefaultContext = multiprocessing.get_context('spawn')
    # if not noLog:
    import BotLogging
    mgr = ctx.Manager()
    queue = mgr.Queue(-1)
    level = logbook.INFO
    if noLog:
        level = logbook.ERROR

    BotLogging.set_up_logger(level, queue=queue)

    loggingProc = ctx.Process(target=BotLogging.run_log_output_process, args=[BotLogging.LOGGING_QUEUE, level], daemon=True)

    loggingProc.start()

    def signal_handler(sig, frame):
        if loggingProc is not None:
            # loggingProc.join()
            loggingProc.kill()
        print('You pressed Ctrl+C!')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        logbook.info("newing up bot host")
        host = BotHostLiveServer(name, gameType, roomId, userId, isPublic, noUi, alignBottom, alignRight, noLog=noLog, ctx=ctx, mgr=mgr)

        logbook.info("running bot host")
        host.run()
    finally:
        print('Ended!')
        if loggingProc is not None:
            loggingProc.join(1.5)
            loggingProc.kill()
        print('logger kilt')


if __name__ == '__main__':
    # raise AssertionError("stop")
    parser = argparse.ArgumentParser()
    parser.add_argument('-name', metavar='str', type=str, default='helpImAlive2',
                        help='Name of Bot')
    parser.add_argument('-userID', metavar='str', type=str, default='--',
                        help='User ID to use')
    parser.add_argument('-g', '--gameType', metavar='str', type=str,
                        choices=["private", "custom", "1v1", "ffa", "team"],
                        default="private", help='Game Type: private, custom, 1v1, ffa, or team')
    parser.add_argument('-roomID', metavar='str', type=str, default="testing", help='Private Room ID (optional)')
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

    run_bothost(name, gameType, roomId, userId, isPublic, noUi, alignBottom, alignRight, noLog)
