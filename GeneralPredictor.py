"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logging
import math
import random
import typing
from copy import deepcopy
import time
import json
from ArmyAnalyzer import *
from collections import deque
from queue import PriorityQueue
from pprint import pprint, pformat
from SearchUtils import *
from DataModels import *
from enum import Enum


class ThreatType(Enum):
    Kill = 1
    Vision = 2


class GeneralPredictor(object):
    def __init__(self, map: MapBase):
        self.is_2v2 = map.is_2v2
        self.map: MapBase = map
        self.eliminated_by_player: typing.List[MapMatrix[bool]] = [MapMatrix(map, False) for player in map.players]
        self.teams: typing.List[int] = MapBase.get_teams_array(map)

