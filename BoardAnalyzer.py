"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    July 2019
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logging
import time
import json
from ArmyAnalyzer import *
from SearchUtils import *
from collections import deque
from queue import PriorityQueue
from Path import Path


class BoardAnalyzer:
    def __init__(self, map: MapBase, general: Tile, teammateGeneral: Tile | None = None):
        startTime = time.time()
        self.map: MapBase = map
        self.general: Tile = general
        self.teammate_general: Tile | None = teammateGeneral
        self.should_rescan = True

        # TODO probably calc these chokes for the enemy, too?
        self.innerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
        """Tiles that only have one outward path away from our general."""

        self.outerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
        """Tiles that only have a single inward path towards our general."""

        self.intergeneral_analysis: ArmyAnalyzer = None

        self.core_play_area_matrix: MapMatrix[bool] = None

        self.extended_play_area_matrix: MapMatrix[bool] = None

        self.flank_danger_play_area_matrix: MapMatrix[bool] = None

        self.general_distances: typing.List[typing.List[int]] = []
        self.friendly_distances: typing.List[typing.List[int]] = []
        self.teammate_distances: typing.List[typing.List[int]] = []

        self.inter_general_distance: int = 0
        """The (possibly estimated) distance between our gen and target player gen."""

        self.within_core_play_area_threshold: int = 1
        """The cutoff point where we draw pink borders as the 'core' play area between generals."""

        self.within_extended_play_area_threshold: int = 2
        """The cutoff point where we draw yellow borders as the 'extended' play area between generals."""

        self.within_flank_danger_play_area_threshold: int = 4
        """The cutoff point where we draw red borders as the flank danger surface area."""

        self.rescan_chokes()

        logging.info("BoardAnalyzer completed in {:.3f}".format(time.time() - startTime))

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def rescan_chokes(self):
        self.should_rescan = False
        oldInner = self.innerChokes
        oldOuter = self.outerChokes
        self.innerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]

        self.outerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]

        self.general_distances = build_distance_map(self.map, [self.general])
        if self.teammate_general is not None and self.teammate_general.player in self.map.teammates:
            self.teammate_distances = build_distance_map(self.map, [self.teammate_general])
            self.friendly_distances = build_distance_map(self.map, [self.teammate_general, self.general])
        else:
            self.friendly_distances = self.general_distances

        for tile in self.map.pathableTiles:
            # logging.info("Rescanning chokes for {}".format(tile.toString()))
            tileDist = self.friendly_distances[tile.x][tile.y]
            movableInnerCount = count(tile.movable, lambda adj: tileDist == self.friendly_distances[adj.x][adj.y] - 1)
            movableOuterCount = count(tile.movable, lambda adj: tileDist == self.friendly_distances[adj.x][adj.y] + 1)
            if movableInnerCount == 1:
                self.outerChokes[tile.x][tile.y] = True
            # checking movableInner to avoid considering dead ends 'chokes'
            if (movableOuterCount == 1
                    # and movableInnerCount >= 1
            ):
                self.innerChokes[tile.x][tile.y] = True
            if self.map.turn > 4:
                if oldInner[tile.x][tile.y] != self.innerChokes[tile.x][tile.y]:
                    logging.info(
                        f"  inner choke change: tile {tile.toString()}, old {oldInner[tile.x][tile.y]}, new {self.innerChokes[tile.x][tile.y]}")
                if oldOuter[tile.x][tile.y] != self.outerChokes[tile.x][tile.y]:
                    logging.info(
                        f"  outer choke change: tile {tile.toString()}, old {oldOuter[tile.x][tile.y]}, new {self.outerChokes[tile.x][tile.y]}")

    def rebuild_intergeneral_analysis(self, opponentGeneral):
        self.intergeneral_analysis = ArmyAnalyzer(self.map, self.general, opponentGeneral)

        enemyDistMap = self.intergeneral_analysis.bMap
        generalDistMap = self.intergeneral_analysis.aMap
        general = self.general

        self.inter_general_distance = enemyDistMap[general.x][general.y]
        self.within_core_play_area_threshold = int((self.inter_general_distance + 1) * 1.1)
        self.within_extended_play_area_threshold = int((self.inter_general_distance + 2) * 1.2)
        self.within_flank_danger_play_area_threshold = int((self.inter_general_distance + 2) * 1.3)
        logging.info(f'BOARD ANALYSIS THRESHOLDS:\r\n'
                     f'     board shortest dist: {self.inter_general_distance}\r\n'
                     f'     core area dist: {self.within_core_play_area_threshold}\r\n'
                     f'     extended area dist: {self.within_extended_play_area_threshold}\r\n'
                     f'     flank danger dist: {self.within_flank_danger_play_area_threshold}')

        self.core_play_area_matrix: MapMatrix[bool] = MapMatrix(self.map, initVal=False)
        self.extended_play_area_matrix: MapMatrix[bool] = MapMatrix(self.map, initVal=False)
        self.flank_danger_play_area_matrix: MapMatrix[bool] = MapMatrix(self.map, initVal=False)

        for tile in self.map.pathableTiles:
            enDist = enemyDistMap[tile.x][tile.y]
            frDist = generalDistMap[tile.x][tile.y]
            tileDistSum = enDist + frDist
            if tileDistSum < self.within_extended_play_area_threshold:
                self.extended_play_area_matrix[tile] = True

            if tileDistSum < self.within_core_play_area_threshold:
                self.core_play_area_matrix[tile] = True

            if (
                    tileDistSum < self.within_flank_danger_play_area_threshold
                    # and tileDistSum > self.within_core_play_area_threshold
                    and frDist / (enDist + 1) < 0.7  # prevent us from considering tiles more than 2/3rds into enemy territory as flank danger
            ):
                self.flank_danger_play_area_matrix[tile] = True

    def get_flank_pathways(
            self,
            filter_out_players: typing.List[int] | None = None,
    ) -> typing.Set[Tile]:
        flankDistToCheck = int(self.intergeneral_analysis.shortestPathWay.distance * 1.5)
        flankPathTiles = set()
        for pathway in self.intergeneral_analysis.pathWays:
            if pathway.distance < flankDistToCheck and len(pathway.tiles) >= self.intergeneral_analysis.shortestPathWay.distance:
                for tile in pathway.tiles:
                    if filter_out_players is None or tile.player not in filter_out_players:
                        flankPathTiles.add(tile)

        return flankPathTiles

    # minAltPathCount will force that many paths to be included even if they are greater than maxAltLength
    def find_flank_leaves(
            self,
            leafMoves,
            minAltPathCount,
            maxAltLength
    ) -> typing.List[Move]:
        goodLeaves: typing.List[Move] = []

        # order by: totalDistance, then pick tile by closestToOpponent
        cutoffDist = self.intergeneral_analysis.shortestPathWay.distance // 4
        includedPathways = set()
        for move in leafMoves:
            # sometimes these might be cut off by only being routed through the general
            neutralCity = (move.dest.isCity and move.dest.player == -1)
            if not neutralCity and move.dest in self.intergeneral_analysis.pathWayLookupMatrix and move.source in self.intergeneral_analysis.pathWayLookupMatrix:
                pathwaySource = self.intergeneral_analysis.pathWayLookupMatrix[move.source]
                pathwayDest = self.intergeneral_analysis.pathWayLookupMatrix[move.dest]
                if pathwaySource.distance <= maxAltLength:
                    #if pathwaySource not in includedPathways:
                    if pathwaySource.distance > pathwayDest.distance or pathwaySource.distance == pathwayDest.distance:
                        # moving to a shorter path or moving along same distance path
                        # If getting further from our general (and by extension closer to opp since distance is equal)
                        gettingFurtherFromOurGen = self.intergeneral_analysis.aMap[move.source.x][move.source.y] < self.intergeneral_analysis.aMap[move.dest.x][move.dest.y]
                        # not more than cutoffDist tiles behind our general, effectively

                        reasonablyCloseToTheirGeneral = self.intergeneral_analysis.bMap[move.dest.x][move.dest.y] < cutoffDist + self.intergeneral_analysis.aMap[self.intergeneral_analysis.tileB.x][self.intergeneral_analysis.tileB.y]

                        if gettingFurtherFromOurGen and reasonablyCloseToTheirGeneral:
                            includedPathways.add(pathwaySource)
                            goodLeaves.append(move)
                    else:
                        logging.info("Pathway for tile {} was already included, skipping".format(move.source.toString()))

        return goodLeaves
