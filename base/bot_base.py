"""
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Generals Bot: Base Bot Class
"""
import sys
import traceback
import logging
import os
import queue
import threading
import time
import typing

from .client import generals
from .client.map import Map, Tile


class GeneralsClientHost(object):
    def __init__(
            self,
            updateMethod,
            handleMissedMoveUpdate,
            handleChatMessage,
            handleTilePing,
            name="PurdueBot",
            userId=None,
            gameType="private",
            privateRoomID: str | None = None,
            public_server=False
    ):
        # Save Config

        self._seen_update: bool = False
        self._updateMethod = updateMethod

        self._handleUpdateNoMove = handleMissedMoveUpdate

        self._handleChatMessage = handleChatMessage

        self._handleTilePing = handleTilePing

        self._map: Map | None = None

        self._server_updates_queue: "queue.Queue[typing.Tuple[str, typing.Any, float]]" = queue.Queue()
        """Used to pass server updates from the websocket thread to the bot move thread."""

        self._name = name
        if userId is None:
            userId = "efg" + self._name
        self._userId = userId
        self._gameType = gameType
        self._privateRoomID = privateRoomID
        self._public_server = public_server

        self._running = True

    def run(self, additional_thread_methods: list):
        # Start Game Thread
        create_thread(self._start_game_thread)
        time.sleep(0.1)
        # Start Chat Message Thead
        create_thread(self._start_chat_thread)
        #time.sleep(0.2)
        # Start Game Move Thread
        create_thread(self._start_moves_thread)
        time.sleep(0.1)

        for method in additional_thread_methods:
            create_thread(method)
            time.sleep(0.1)

        while self._running:
            time.sleep(1.0)

        logging.info(f'No longer self._running=True in bot_base.py, starting suicide thread')
        create_thread(self._suicide_in_4_seconds)

    def _suicide_in_4_seconds(self):
        logging.info('suicide thread started, waiting 4 seconds before killing the process')
        time.sleep(4.0)
        logging.info('ok, killing process')
        time.sleep(0.1)
        exit(0)

    def _start_game_thread(self):
        # Create Game
        self._game = generals.GeneralsClient(self._userId, self._name, self._gameType, gameid=self._privateRoomID, public_server=self._public_server)

        logging.info("game start...?")

        # Start Receiving Updates
        try:
            for update in self._game.get_updates():
                over = self._set_update(update)
                if over:
                    break

        except ValueError:  # Already in match, restart
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
            
            logging.info("Exit: Already in queue in _start_update_loop")
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            #logging.info("inf")  # Log it or whatever here
            #logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
            #logging.info("warn")  # Log it or whatever here
            #logging.warning(''.join('!! ' + line for line in lines))  # Log it or whatever here
            logging.info("err")  # Log it or whatever here
            logging.error(''.join('!! ' + line for line in lines))  # Log it or whatever here

        self._running = False
        self._game._terminate()

        logging.info("crashed out of update loop, creating suicide thread")

        create_thread(self._suicide_in_4_seconds)

    def _set_update(self, updateTuple: typing.Tuple[str, typing.Any]) -> bool:
        """Returns True if the game is over, False otherwise."""
        updateType, update = updateTuple
        timeAccurate = time.time_ns() / (10 ** 9)
        self._server_updates_queue.put((updateType, update, timeAccurate), block=True, timeout=5.0)

        over = False
        if updateType == "game_won":
            over = True
        elif updateType == "game_lost":
            over = True
        elif updateType == "game_update" and update is not None and 'turn' in update:
            if update['turn'] > 3000:
                self._game.send_surrender()

        if over:
            logging.info(f"!!!! Game Complete. Result = {updateType} !!!!")
            if '_moves_realized' in dir(self):
                logging.info(f"Moves: {self._updates_received:d}, Realized: {self._moves_realized:d}")

            # why was this sleep here?
            time.sleep(2.0)
            self._running = False
            logging.info("terminating in _set_update")
            self._game._terminate()
            time.sleep(2.0)
            logging.info("Spawning suicide thread from server-updates thread..?")
            try:
                create_thread(self._suicide_in_4_seconds)
            except:
                logging.info(traceback.format_exc())

        return over

    ######################### Move Generation #########################

    def _start_moves_thread(self):
        self._moves_realized = 0
        self._updates_received = 0
        while self._running:
            if self._map is not None and self._map.complete and self._map.remainingPlayers > 1 and not self._map.players[self._map.player_index].dead:
                # bot gave up, terminate
                self._running = False
                logging.info(f'bot gave up :(')
                break

            try:
                updateType, update, updateReceivedTime = self._server_updates_queue.get(block=True, timeout=1.0)
                gameUpdateReceived = False
                botShouldMakeMove = False
                countsForMakeMove = False
                mapUpdateTime = updateReceivedTime

                try:
                    while True:
                        countsForMakeMove = self._handle_server_update(updateType, update)
                        if countsForMakeMove:
                            botShouldMakeMove = True
                            self._updates_received += 1
                            gameUpdateReceived = True
                        updateType, update, updateReceivedTime = self._server_updates_queue.get(block=False, timeout=0.0)
                        if gameUpdateReceived and updateType == "game_update":
                            if self._map is None:
                                raise AssertionError('_map was none... but missed update?')

                            logging.info(f'UH OH, MULTIPLE SERVER UPDATES RECEIVED IN A ROW, TURN {self._map.turn} MISSED MOVE CHANCE')
                            mapUpdateTime = updateReceivedTime
                            self._notify_bot_of_missed_update(self._map, updateReceivedTime)
                except queue.Empty:
                    pass  # this is what we expect to happen 99.9% of the time unless the server is laggy or the bot takes too long making a previous move and queues up server updates...

                if botShouldMakeMove:
                    self._ask_bot_for_move(self._map, mapUpdateTime)

                    self._moves_realized += 1
            except queue.Empty:
                logging.info('no update received after 1s of waiting...?')
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                #logging.info("inf")  # Log it or whatever here
                #logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
                #logging.info("warn")  # Log it or whatever here
                #logging.warning(''.join('!! ' + line for line in lines))  # Log it or whatever here
                logging.info("err")  # Log it or whatever here
                logging.error(''.join('!! ' + line for line in lines))  # Log it or whatever here

    def _process_map_diff(self, data):
        if not self._seen_update:
            logging.info('First update...?')
            self._seen_update = True
            self._map = Map(self._game._start_data, data)

        logging.info('applying server update...?')

        self._map.apply_server_update(data)

    def _make_result(self, update, data: dict | None):
        """

        @param update:
        @param data: dict containing {'killer'=int} if we lost
        @return:
        """
        result = self._map._handle_server_game_result(update, data)

        self.result = result

    def _ask_bot_for_move(self, update, updateReceivedTime):
        self._updateMethod(update, updateReceivedTime)

    def _notify_bot_of_missed_update(self, update, updateReceivedTime: float):
        self._handleUpdateNoMove(update, updateReceivedTime)

    def place_move(self, source, dest, move_half=False):
        self._game.move(source.y, source.x, dest.y, dest.x, self._map.cols, move_half)

    def send_clear_moves(self):
        self._game.send_clear_moves()

    def _start_chat_thread(self):
        # Send Chat Messages
        try:
            while self._running:
                msg = str(input('Send Msg:'))
                self._game.send_chat(msg)
                time.sleep(0.7)
        except:
            pass

        return

    def _handle_server_update(self, updateType: str, update: typing.Any) -> bool:
        """
        Returns True if this update should trigger a bot move / board update, otherwise it gets passed as an update without triggering the missed-move logic.

        @param updateType:
        @param update:
        @return:
        """
        if updateType == "game_won":
            self._make_result(updateType, update)
        elif updateType == "game_lost":
            self._make_result(updateType, update)
        elif updateType == "player_capture":
            # NOTE player captures happen BEFORE the map update that shows you the updated tiles comes through.
            # TODO change this to PREPARE the map for a player capture, let it use the map update, and
            #  THEN perform this player captures stuff that's being triggered in here afterwards?
            self._map.handle_player_capture_text(update["text"])
            return False
        elif updateType == "chat_message":
            self._handleChatMessage(update)
            return False
        elif updateType == "ping_tile":
            x, y = self._map.convert_tile_server_index_to_x_y(update)
            self._handleTilePing(self._map.GetTile(x, y))
            return False

        if update is not None and 'map_diff' in update:
            self._process_map_diff(update)
            return True
        return False

    def send_chat(self, chatMessage: str, teamChat: bool):
        self._game.send_chat(chatMessage, teamChat)

    def ping_tile(self, pingTile: Tile):
        self._game.ping_tile(pingTile.y, pingTile.x, self._map.cols)


def create_thread(f):
    t = threading.Thread(target=f)
    t.daemon = True
    t.start()
