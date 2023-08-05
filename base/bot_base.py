'''
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Generals Bot: Base Bot Class
'''

import sys
import traceback
import logging
import os
import threading
import time

from .client import generals
from .client.map import MapBase


class GeneralsBot(object):
    def __init__(self, updateMethod, name="PurdueBot", gameType="private", privateRoomID="PurdueBot", public_server=False):
        # Save Config
        self._updateMethod = updateMethod
        self._name = name
        self._gameType = gameType
        self._privateRoomID = privateRoomID
        self._public_server = public_server
        self._map_update_callback = None

        # ----- Start Game -----
        
        self._running = True
        self._move_event = threading.Event()

    def run(self, additional_thread_methods: list, map_update_callback = None):
        self._map_update_callback = map_update_callback
        # Start Game Thread
        _create_thread(self._start_game_thread)
        time.sleep(0.2)
        # Start Chat Message Thead
        _create_thread(self._start_chat_thread)
        #time.sleep(0.2)
        # Start Game Move Thread
        _create_thread(self._start_moves_thread)
        time.sleep(0.2)

        for method in additional_thread_methods:
            _create_thread(method)
            time.sleep(0.2)

        while self._running:
            time.sleep(1.0)

        time.sleep(1.0)
        os._exit(0) # End Program

    ######################### Handle Updates From Server #########################
    
    def getLastCommand(self):
        return self._game.lastChatCommand

    def _start_game_thread(self):
        # Create Game
        if self._gameType in ['1v1', 'ffa', 'private']:
            self._game = generals.Generals("efg" + self._name, self._name, self._gameType, gameid=self._privateRoomID, public_server=self._public_server)
        elif self._gameType == "team": # team
            self._game = generals.Generals("efg" + self._name, self._name, 'team')

        logging.info("game start...?")

        # Start Receiving Updates
        try:
            for update in self._game.get_updates():
                self._set_update(update)

                # Perform Make Move
                #self._make_move()
                self._move_event.set()

                # Update GeneralsViewer Grid
                selfDir = dir(self)

                if self._map_update_callback is not None:
                    logging.info("map update callback...?")
                    self._map_update_callback(update)
        except ValueError: # Already in match, restart    
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
            
            logging.info("Exit: Already in queue in _start_update_loop")
            time.sleep(3)
            os._exit(0) # End Program
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            #logging.info("inf")  # Log it or whatever here
            #logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
            #logging.info("warn")  # Log it or whatever here
            #logging.warning(''.join('!! ' + line for line in lines))  # Log it or whatever here
            logging.info("err")  # Log it or whatever here
            logging.error(''.join('!! ' + line for line in lines))  # Log it or whatever here

        logging.info("crashed out of update loop, quitting")
        time.sleep(3)
        os._exit(0) # End Program

    def _set_update(self, update):
        if update.complete:
            logging.info("!!!! Game Complete. Result = " + str(update.result) + " !!!!")
            if '_moves_realized' in dir(self):
                logging.info("Moves: %d, Realized: %d" % (self._update.turn, self._moves_realized))
            self._running = False
            time.sleep(2.0)
            logging.info("terminating")
            self._game._terminate()
            time.sleep(1.0)
            os._exit(0) # End Program
            return

        self._update = update

    ######################### Move Generation #########################

    def _start_moves_thread(self):
        self._moves_realized = 0
        while self._running:
            try:
                self._move_event.wait()
                self._move_event.clear()
                self._make_move()
                self._moves_realized+=1
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                #logging.info("inf")  # Log it or whatever here
                #logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
                #logging.info("warn")  # Log it or whatever here
                #logging.warning(''.join('!! ' + line for line in lines))  # Log it or whatever here
                logging.info("err")  # Log it or whatever here
                logging.error(''.join('!! ' + line for line in lines))  # Log it or whatever here

    def _make_move(self):
        self._updateMethod(self, self._update)


    ######################### Chat Messages #########################

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

    ######################### Tile Finding #########################

    def place_move(self, source, dest, move_half=False) -> bool:
        if self.validPosition(dest.x, dest.y):
            self._game.move(source.y, source.x, dest.y, dest.x, move_half)
            return True
        return False

    def validPosition(self, x, y):
        return 0 <= y < self._update.rows and 0 <= x < self._update.cols and self._update._tile_grid[y][x] != generals.map.TILE_MOUNTAIN



######################### Global Helpers #########################

def _create_thread(f):
    t = threading.Thread(target=f)
    t.daemon = True
    t.start()
