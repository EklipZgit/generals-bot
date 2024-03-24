"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    July 2019
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import time
import typing

import logbook
from numba.cpython.cmathimpl import INF

import DebugHelper

from collections import deque

import SearchUtils
from ArmyTracker import Army
from base.client.map import Tile
from MapMatrix import MapMatrix


class PathWay:
    def __init__(self, distance):
        self.distance = distance
        self.tiles = set()
        self.seed_tile = None

    def add_tile(self, tile):
        self.tiles.add(tile)
        if self.seed_tile == None:
            self.seed_tile = tile


class InfPathWay:
    def __init__(self, tile):
        self.distance = INF
        self.tiles = set()
        self.tiles.add(tile)
        self.seed_tile = tile


SENTINAL = "~"


class ArmyAnalyzer:
    def __init__(self, map, armyA: Tile | Army, armyB: Tile | Army, maxDist = 1000):
        startTime = time.perf_counter()
        self.map = map
        if type(armyA) is Army:
            self.tileA = armyA.tile
        else:
            self.tileA: Tile = armyA

        if type(armyB) is Army:
            self.tileB = armyB.tile
        else:
            self.tileB: Tile = armyB

        # path chokes are relative to the paths between A and B
        self.pathChokes: typing.Set[Tile] = set()
        self.pathWayLookupMatrix: MapMatrix[PathWay | None] = MapMatrix(map, initVal=None)
        self.pathWays: typing.List[PathWay] = []
        self.shortestPathWay: PathWay = PathWay(distance=INF)
        self.chokeWidths: typing.Dict[Tile, int] = {}
        self.interceptChokes: typing.Dict[Tile, int] = {}
        """The value in here for a tile represents the number of additional moves necessary for worst case intercept, for an army that reaches this tile on the earliest turn the bTile army could reach this. It is effectively the difference between the best case and worst case intercept turns for an intercept reaching this tile."""

        logbook.info(f"ArmyAnalyzer analyzing {self.tileA.toString()} and {self.tileB.toString()}")

        # self.distance: int = self.map.get_distance_between(self.tileA, self.tileB)
        self.aMap = SearchUtils.build_distance_map(self.map, [self.tileA], [])
        self.bMap = SearchUtils.build_distance_map(self.map, [self.tileB], [])

        self.scan()

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def scan(self):
        chokeCounterMap = {}
        minPath = PathWay(distance=INF)
        for tile in self.map.pathableTiles:
            # build the pathway
            path = self.pathWayLookupMatrix[tile]
            if path is None:
                path = self.build_pathway(tile)
                self.pathWays.append(path)
                if path.distance < minPath.distance:
                    minPath = path

            # map out choke counts. TODO i don't think this pathChoke stuff works :/ make sure to visualize it well and debug.
            chokeKey = self._get_choke_key(path, tile)

            if chokeKey not in chokeCounterMap:
                chokeCounterMap[chokeKey] = 1
            else:
                chokeCounterMap[chokeKey] += 1

        for tile in self.map.pathableTiles:
            path = self.pathWayLookupMatrix[tile]
            if path is not None:
                chokeKey = self._get_choke_key(path, tile)
                width = chokeCounterMap[chokeKey]
                if width == 1:
                    # if DebugHelper.IS_DEBUGGING:
                    #     logbook.info(f"  (maybe) found choke at {tile.toString()}? Testing for shorter pathway joins")
                    anyShorter = SearchUtils.any_where(tile.movable, lambda adjTile: adjTile in self.pathWayLookupMatrix and self.pathWayLookupMatrix[adjTile].distance < path.distance)
                    if anyShorter:
                        if DebugHelper.IS_DEBUGGING:
                            logbook.info(f"    OK WE DID FIND A CHOKEPOINT AT {str(tile)}! adding to self.pathChokes")
                        # Todo this should probably be on pathways lol
                        self.pathChokes.add(tile)
                self.chokeWidths[tile] = width

        self.shortestPathWay = minPath

        self.build_intercept_chokes()

    def build_pathway(self, tile) -> PathWay:
        distance = self.aMap[tile.x][tile.y] + self.bMap[tile.x][tile.y]
        #logbook.info("  building pathway from tile {} distance {}".format(tile.toString(), distance))
        path = PathWay(distance = distance)

        queue = deque()
        queue.appendleft(tile)
        while not len(queue) == 0:
            currentTile = queue.pop()
            if currentTile in self.pathWayLookupMatrix:
                continue
            currentTileDistance = self.aMap[currentTile.x][currentTile.y] + self.bMap[currentTile.x][currentTile.y]
            if currentTileDistance < 300:
                #so not inf
                if currentTileDistance == distance:
                    #logbook.info("    adding tile {}".format(currentTile.toString()))
                    path.add_tile(currentTile)
                    self.pathWayLookupMatrix[currentTile] = path

                    for adjacentTile in currentTile.movable:
                        queue.appendleft(adjacentTile)
        return path

    def _get_choke_key(self, path: PathWay, tile: Tile) -> typing.Tuple:
        # including path in the key forces the 'chokes' to be part of the same pathway.
        return path, self.aMap[tile.x][tile.y], self.bMap[tile.x][tile.y]

        # return self.aMap[tile.x][tile.y], self.bMap[tile.x][tile.y]
        # return path.distance, self.aMap[tile.x][tile.y], self.bMap[tile.x][tile.y]

    def _get_tile_middle_width(self, tile: Tile, path: PathWay, width: int) -> int:
        # if width == 1:
        #     return 0

        return width // 2

    def build_intercept_chokes(self):
        #
        # furthestOtherRefTile = None
        # furthestOtherRefDist = 0
        # for tile in self.map.pathableTiles:
        #     cumulativeDist = self.aMap[tile.x][tile.y] + self.bMap[tile.x][tile.y] + self.reference_point_map[tile]
        #     if cumulativeDist > furthestOtherRefDist:
        #         furthestOtherRefTile = tile
        #         furthestOtherRefDist = cumulativeDist
        #
        # otherRefDistMap = SearchUtils.build_distance_map_matrix(self.map, [furthestOtherRefTile])

        q = deque()
        distancesLookup = {}

        q.append(self.tileB)

        # distMinMaxTable = {}
        #
        # minX = 1000
        # maxX = -1
        # minY = 1000
        # maxY = -1

        visited = set()
        pw = self.pathWayLookupMatrix[self.tileA]
        if pw is None:
            return

        shortestDist = pw.distance

        while q:
            nextTile = q.popleft()
            if nextTile not in self.shortestPathWay.tiles:
                continue
            if nextTile in visited:
                continue

            visited.add(nextTile)
            nextBDist = self.bMap[nextTile.x][nextTile.y]
            # if nextBDist < curBDist:
            #     continue
            #
            # nextADist = self.aMap[nextTile.x][nextTile.y]
            # if nextADist > curADist:
            #     continue

            pw = self.pathWayLookupMatrix[nextTile]

            # offsetDist = nextBDist
            offsetDist = nextBDist + pw.distance - shortestDist

            curSet = distancesLookup.get(offsetDist, [])
            if len(curSet) == 0:
                distancesLookup[offsetDist] = curSet

            curSet.append(nextTile)
            #
            # if nextBDist > curBDist and not nextTile.isObstacle:
            #     # distMinMaxTable[curBDist] = (minX, minY, maxX, maxY)
            #     # distMinMaxTable[curBDist] = (minRefDist, maxRefDist)
            #     curBDist = nextBDist
            #     # if nextADist < curADist:
            #     curADist = nextADist
            #     # maxRefDist = 0
            #     # minRefDist = 10000
            #     # minX = 1000
            #     # maxX = -1
            #     # minY = 1000
            #     # maxY = -1

            # curRefDist = self.cMap[nextTile.x][nextTile.y]
            # curRefDist = abs(self.tileC.x - nextTile.x) + abs(self.tileC.y - nextTile.y)
            # maxRefDist = max(maxRefDist, curRefDist)
            # minRefDist = min(minRefDist, curRefDist)
            # minX = min(minX, nextTile.x)
            # minY = min(minY, nextTile.y)
            # maxX = max(maxX, nextTile.x)
            # maxY = max(maxY, nextTile.y)
            for t in nextTile.movable:
                if t.isObstacle:
                    continue  # TODO ??
                if t not in visited:  # and t in self.shortestPathWay.tiles
                    nPw = self.pathWayLookupMatrix[t]
                    if nPw is None:
                        continue
                    if nPw.distance >= pw.distance:
                        q.append(t)

        # distMinMaxTable[curBDist] = (minX, minY, maxX, maxY)
        # distMinMaxTable[curBDist] = (minRefDist, maxRefDist)

        for r in range(self.shortestPathWay.distance + 1):
            curSet = distancesLookup[r]

            for tile in curSet:
                maxDist = 0
                for altTile in curSet:
                    if tile == altTile:
                        continue

                    dist = self.map.get_distance_between(tile, altTile)
                    if dist is None:
                        continue
                    if dist > maxDist:
                        maxDist = dist
                # logbook.info(f'ic {str(tile)} = {maxDist}')
                self.interceptChokes[tile] = maxDist
        #
        # for tile in self.shortestPathWay.tiles:
        #     curBDist = self.bMap[tile.x][tile.y]
        #     # refDist = self.cMap[tile.x][tile.y]
        #     # refDist = abs(self.tileC.x - tile.x) + abs(self.tileC.y - tile.y)
        #     # minRefDist, maxRefDist = distMinMaxTable[curBDist]
        #     (curMinX, curMinY, curMaxX, curMaxY) = distMinMaxTable[curBDist]
        #
        #     interceptFar = curMaxX - tile.x + curMaxY - tile.y
        #     interceptClose = tile.x - curMinX + tile.y - curMinY
        #     # interceptFar = maxRefDist - refDist
        #     # interceptClose = refDist - minRefDist
        #     worstCaseInterceptTurns = max(interceptFar, interceptClose)
        #
        #     self.interceptChokes[tile] = worstCaseInterceptTurns
    #
    # def find_A_B_width_reference_point(self) -> Tile:
    #     # furthestRefTile = None
    #     # furthestRefDist = 0
    #     # for tile in self.map.pathableTiles:
    #     #     # cumulativeDist = self.aMap[tile.x][tile.y] + self.bMap[tile.x][tile.y]
    #     #     cumulativeDist = abs(self.tileA.x - tile.x) + abs(self.tileA.y - tile.y) + abs(self.tileB.x - tile.x) + abs(self.tileB.y - tile.y)
    #     #     if cumulativeDist > furthestRefDist:
    #     #         furthestRefTile = tile
    #     #         furthestRefDist = cumulativeDist
    #     xDiff = self.tileA.x - self.tileB.x
    #     yDiff = self.tileA.y - self.tileB.y
    #
    #     midX = (self.tileA.x + self.tileB.x) // 2
    #     midY = (self.tileA.y + self.tileB.y) // 2
    #
    #     midPoint = self.map.GetTile(midX, midY)
    #
    #     refTile = self.map.GetTile(midX + yDiff, midY + xDiff)
    #     if refTile is None:
    #         refTile = self.map.GetTile(midX - yDiff, midY - xDiff)
    #
    #     if refTile is None:
    #         yDiff = yDiff // 2
    #         xDiff = xDiff // 2
    #
    #         refTile = self.map.GetTile(midX + yDiff, midY + xDiff)
    #         if refTile is None:
    #             refTile = self.map.GetTile(midX - yDiff, midY - xDiff)
    #             if refTile is None:
    #                 raise AssertionError(f'neither directions midpoint ref works to retrieve a valid tile rotation.')
    #
    #     return refTile
