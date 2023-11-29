"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logging
import typing
from collections import deque
from enum import Enum

from ArmyTracker import Army, ArmyTracker
from BoardAnalyzer import BoardAnalyzer
from DangerAnalyzer import DangerAnalyzer
from DataModels import GatherTreeNode
from Directives import Timings
from Path import Path
from StrategyModels import CycleStatsData
from Territory import TerritoryClassifier
from base.client.map import Tile
from MapMatrix import MapMatrix


class TargetStyle(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3
    GOLD = 4
    PURPLE = 5
    TEAL = 6
    ORANGE = 7
    WHITE = 8
    YELLOW = 9


class PathColorer(object):
    def __init__(self, path, r, g, b, alpha = 255, alphaDecreaseRate = 10, alphaMinimum = 100):
        self.path = path
        self.color = (r, g, b)
        self.alpha = alpha
        self.alphaDecreaseRate = alphaDecreaseRate
        self.alphaMinimum = alphaMinimum


class ViewInfo(object):
    def __init__(self, countHist, cols, rows):
        # list of true/false matrixes and the color to color the border
        self._divisions: typing.List[typing.Tuple[MapMatrix[bool], typing.Tuple[int, int, int], int]] = []
        self._zones: typing.List[typing.Tuple[MapMatrix[bool], typing.Tuple[int, int, int], int]] = []
        # Draws the red target circles

        # self.ekBot.dump_turn_data_to_string()
        self.board_analysis: BoardAnalyzer | None = None
        self.targetingArmy: Army | None = None
        self.armyTracker: ArmyTracker | None = None
        self.dangerAnalyzer: DangerAnalyzer | None = None
        self.currentPath: Path | None = None
        self.gatherNodes: typing.List[GatherTreeNode] | None = None
        self.redGatherNodes: typing.List[GatherTreeNode] | None = None
        self.territories: TerritoryClassifier | None = None
        self.perfEvents: typing.List[str] = []
        self.allIn: bool = False
        self.timings: Timings | None = None
        self.allInCounter: int = 0
        self.targetPlayer: int = -1
        self.team_cycle_stats: typing.Dict[int, CycleStatsData] = {}
        self.team_last_cycle_stats: typing.Dict[int, CycleStatsData] = {}
        self.player_fog_tile_counts: typing.Dict[int, typing.Dict[int, int]] = {}
        self.generalApproximations: typing.List[typing.Tuple[float, float, int, Tile | None]] = []
        """
        List of general location approximation data as averaged by enemy tiles bordering undiscovered and euclid averaged.
        Tuple is (xAvg, yAvg, countUsed, generalTileIfKnown)
        Used for player targeting (we do the expensive approximation only for the target player?)
        This is aids.
        """
        self.playerTargetScores: typing.List[int] = []

        self.targetedTiles: typing.List[typing.Tuple[Tile, TargetStyle, int]] = []
        # self.redTargetedTileHistory: typing.List[typing.List[typing.Tuple[Tile, TargetStyle]]] = []
        # for i in range(countHist):
        #     self.redTargetedTileHistory.append([])

        # per-tile int that darkens the red 'evaluated' X drawn on evaluated tiles.
        self.evaluatedGrid: typing.List[typing.List[int]] = []
        self.infoText = "(replace with whatever text here)"
        self.cols = cols
        self.rows = rows
        self.paths: typing.Deque[PathColorer] = deque()
        self.topRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.midRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomMidRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomLeftGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomMidLeftGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.midLeftGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.lastMoveDuration = 0.0
        self.addlTimingsLineText: str = ""
        self.addlInfoLines: typing.List[str] = []
        self.statsLines: typing.List[str] = []

    def turnInc(self):
        self.addlTimingsLineText = ""
        self.addlInfoLines = []
        self.statsLines = []
        self._divisions = []
        self._zones = []
        self.board_analysis: BoardAnalyzer | None = None
        self.targetingArmy: Army | None = None
        self.armyTracker: ArmyTracker | None = None
        self.dangerAnalyzer: DangerAnalyzer | None = None
        self.currentPath: Path | None = None
        self.gatherNodes: typing.List[GatherTreeNode] | None = None
        self.perfEvents = []
        self.paths = deque()
        self.redGatherNodes: typing.List[GatherTreeNode] | None = None
        self.territories: TerritoryClassifier | None = None
        self.allIn: bool = False
        self.timings: Timings | None = None
        self.allInCounter: int = 0
        self.targetPlayer: int = -1
        self.topRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.midRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomMidRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomRightGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomLeftGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.bottomMidLeftGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        self.midLeftGridText = [[None for y in range(self.rows)] for x in range(self.cols)]
        # countHist = len(self.redTargetedTileHistory)
        # for i in range(countHist):
        #     if (i == countHist - 2):
        #         break
        #     self.redTargetedTileHistory[countHist - i - 1] = self.redTargetedTileHistory[countHist - i - 2]
        # self.redTargetedTileHistory[0] = self.targetedTiles
        self.targetedTiles = []

        self.evaluatedGrid = [[0 for y in range(self.rows)] for x in range(self.cols)]

    def add_targeted_tile(self, tile: Tile, targetStyle: TargetStyle = TargetStyle.RED, radiusReduction: int = 6):
        self.targetedTiles.append((tile, targetStyle, radiusReduction))

    def add_info_line(self, additionalInfo: str):
        logging.info(additionalInfo)
        self.addlInfoLines.append(additionalInfo)

    def add_stats_line(self, statsLine: str):
        logging.info(statsLine)
        self.statsLines.append(statsLine)

    def add_map_division(self, divisionMatrix: MapMatrix[bool], color: typing.Tuple[int, int, int], alpha: int = 128):
        self._divisions.append((divisionMatrix, color, alpha))

    def add_map_zone(self, zoneMatrix: MapMatrix[bool], color: typing.Tuple[int, int, int], alpha: int = 15):
        """Note this doesn't do pure alpha...?"""
        self._zones.append((zoneMatrix, color, alpha))

    def color_path(self, pathColorer: PathColorer, start: bool = False):
        if not start:
            self.paths.append(pathColorer)
        else:
            self.paths.insert(0, pathColorer)
