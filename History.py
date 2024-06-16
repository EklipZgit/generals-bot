"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logbook
import typing
from copy import deepcopy
import time
import json
from pprint import pprint,pformat

from Models import Move


class History(object):
    def    __init__(self):
        self.contested_cities = {}
        self.aggressive_enemy_moves = []
        self.player_captures = []
        self.attempted_threat_kills = set()
        self.move_history: typing.Dict[int, typing.List[Move]] = {}
        self.droppedHistory = {}

    def add_city_contestation(self, city, turn, player, army):
        if city not in self.contested_cities:
            contestedObject = ContestedCityInfo(city, 0)
            self.contested_cities[city] = contestedObject
        contestedObject = self.contested_cities[city]
        contestedObject.add_contested(turn, player, army)

    def captured_player(self, turn, capturedPlayer, capturingPlayer):
        self.player_captures.append(PlayerCapture(turn, capturedPlayer, capturingPlayer))

class ContestedCityInfo(object):
    def __init__(self, city, contestationCount = 0):
        self.contestationCount = contestationCount
        self.tile = city
        self.city = city
        self.contestedTurns = []

    def add_contested(self, turn, player, army):
        self.contestedTurns.append(ContestInstance(self.city, turn, player, army))

        
class ContestInstance(object):
    def    __init__(self, tile, turn, player, army):
        self.tile = tile
        self.turn = turn
        self.player = player
        self.army = army


class PlayerCapture(object):
    def    __init__(self, turn, capturedPlayer, capturingPlayer):
        self.capturedPlayer = capturedPlayer
        self.capturingPlayer = capturingPlayer
        self.turn = turn