import argparse
import logging
import os
import time

from base import bot_base
from base.bot_base import _create_thread
from base.viewer import GeneralsViewer
from bot_ek0x45 import EklipZBot

FORCE_NO_VIEWER = False

class BotHost(object):
    def __init__(self):
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

        self.eklipz_bot = EklipZBot(threadCount=42069)
        self._name = args['name']
        self._game_type = args['gameType']

        # also creates the viewer, for now. Need to move that out to view sim games
        self.bot_client = bot_base.GeneralsBot(self.make_move,
                                               name=self._name,
                                               gameType=self._game_type,
                                               privateRoomID=args['roomID'],
                                               public_server=args['public'])

        self.has_viewer: bool = not FORCE_NO_VIEWER and not args['no_ui']
        logging.info(f'has_viewer: {self.has_viewer}')
        self.align_bottom: bool = args['bottom']
        self.align_right: bool = args['right']

        self._viewer: GeneralsViewer = None

    # consumes main thread until game complete
    def run(self):
        addlThreads = []
        viewerUpdateCallback = None

        # Start Game Viewer
        if self.has_viewer:
            window_title = "%s (%s)" % (self._name, self._game_type)
            self._viewer = GeneralsViewer(window_title)
            self._viewer.ekBot = self.eklipz_bot
            addlThreads.append(self.run_viewer_loop)
            viewerUpdateCallback = self._viewer.updateGrid

        self.bot_client.run(addlThreads, viewerUpdateCallback)

    # Consumes thread
    def run_viewer_loop(self):
        # Consumes thread
        self._viewer.main_viewer_loop(not self.align_bottom, not self.align_right)

    def make_move(self, currentBot, currentMap):
        self.eklipz_bot._bot = currentBot
        self.eklipz_bot._map = currentMap

        command = currentBot.getLastCommand()
        # if (command == "-s"):
        #    return
        startTime = time.perf_counter()
        move = self.eklipz_bot.find_move()
        duration = time.perf_counter() - startTime
        self.eklipz_bot.viewInfo.lastMoveDuration = duration
        if move is not None:
            if not self.place_move(move.source, move.dest, currentBot, move.move_half):
                logging.info(
                    "!!!!!!!!! {},{} -> {},{} was an illegal / bad move!!!! This turn will do nothing :(".format(
                        move.source.x, move.source.y,
                        move.dest.x, move.dest.y))
        return

    # returns whether the placed move was valid
    def place_move(self, source, dest, bot_client, move_half=False) -> bool:
        if source.army == 1 or source.army == 0:
            logging.info(
                "BOT PLACED BAD MOVE! {},{} to {},{}. Will send anyway, i guess.".format(source.x, source.y, dest.x,
                                                                                         dest.y))
        else:
            logging.info("Placing move: {},{} to {},{}".format(source.x, source.y, dest.x, dest.y))
        return bot_client.place_move(source, dest, move_half=move_half)

if __name__ == '__main__':
    host = BotHost()
    host.run()