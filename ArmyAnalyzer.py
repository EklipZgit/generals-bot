"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    July 2019
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import  annotations

import itertools
import time
import typing

import logbook
from numba.cpython.cmathimpl import INF

from collections import deque

import SearchUtils
from ArmyTracker import Army
from Path import Path
from base.client.map import Tile, MapBase, TILE_OBSTACLE
from MapMatrix import MapMatrix, MapMatrixSet


class PathWay:
    def __init__(self, distance):
        self.distance: int = distance
        self.tiles: typing.Set[Tile] = set()
        self.seed_tile: Tile = None

    def add_tile(self, tile):
        self.tiles.add(tile)


SENTINAL = "~"

INF_PATH_WAY = PathWay(distance=1000)


class ArmyAnalyzer:
    TimeSpentBuildingPathwaysChokeWidthsAndMinPath: float = 0.0
    TimeSpentBuildingInterceptChokes: float = 0.0
    TimeSpentInInit: float = 0.0
    NumAnalysisBuilt: int = 0

    def __init__(self, map: MapBase, armyA: Tile | Army, armyB: Tile | Army):
        startTime = time.perf_counter()
        self.map: MapBase = map
        if type(armyA) is Army:
            self.tileA: Tile = armyA.tile
        else:
            self.tileA: Tile = armyA

        if type(armyB) is Army:
            self.tileB: Tile = armyB.tile
        else:
            self.tileB: Tile = armyB

        # path chokes are relative to the paths between A and B
        self.pathWayLookupMatrix: MapMatrix[PathWay | None] = MapMatrix(map, initVal=None)
        self.pathWays: typing.List[PathWay] = []
        self.shortestPathWay: PathWay = INF_PATH_WAY
        self.chokeWidths: MapMatrix[int] = MapMatrix(map)
        """
        If the army were to path through this tile, this is the number of alternate nearby tiles the army could also be at. So if the army has to make an extra wide path to get here, wasting moves, this will be chokeWidth1 even if the actual choke is 2 wide.
        """
        self.interceptChokes: MapMatrix[int] = MapMatrix(map)
        """The value in here for a tile represents the number of additional moves necessary for worst case intercept, for an army that reaches this tile on the earliest turn the bTile army could reach this. It is effectively the difference between the best case and worst case intercept turns for an intercept reaching this tile."""

        self.interceptTurns: MapMatrix[int] = MapMatrix(map)
        """This represents the raw turns into the intercept of an army that another army army must reach this tile to successfully achieve an intercept, ASSUMING the enemy army goes this way."""

        self.interceptDistances: MapMatrix[int] = MapMatrix(map)
        """The number of moves you will waste to achieve the intercept, worst case, regardless of which way the enemy army goes."""

        self.tileDistancesLookup: typing.Dict[int, typing.List[Tile]] = {}
        """A lookup from the number of turns into the intercept, to which tiles the enemy army could have reached by that point (shorted path only)."""

        logbook.info(f"ArmyAnalyzer analyzing {self.tileA} and {self.tileB}")

        self.aMap: MapMatrix[int] = map.distance_mapper.get_tile_dist_matrix(self.tileA)
        self.bMap: MapMatrix[int] = map.distance_mapper.get_tile_dist_matrix(self.tileB)
        ArmyAnalyzer.TimeSpentInInit += time.perf_counter() - startTime

        self.scan()

        ArmyAnalyzer.NumAnalysisBuilt += 1

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    @classmethod
    def dump_times(cls):
        logbook.info(f'OVERALL TIME SPENT IN ARMY ANALYZER:\r\n'
                     f'         TimeSpentBuildingPathwaysChokeWidthsAndMinPath: {cls.TimeSpentBuildingPathwaysChokeWidthsAndMinPath:.5f}s\r\n'
                     f'         TimeSpentBuildingInterceptChokes: {cls.TimeSpentBuildingInterceptChokes:.5f}s\r\n'
                     f'         TimeSpentInInit: {cls.TimeSpentInInit:.5f}s\r\n'
                     f'         NumAnalysisBuilt: {cls.NumAnalysisBuilt}\r\n')

    @classmethod
    def reset_times(cls):
        cls.TimeSpentBuildingPathwaysChokeWidthsAndMinPath = 0.0
        cls.TimeSpentBuildingInterceptChokes = 0.0
        cls.TimeSpentInInit = 0.0
        cls.NumAnalysisBuilt = 0

    def scan(self):
        start = time.perf_counter()
        self.build_chokes_and_pathways()
        ArmyAnalyzer.TimeSpentBuildingPathwaysChokeWidthsAndMinPath += time.perf_counter() - start

        start = time.perf_counter()
        self.build_intercept_chokes()
        ArmyAnalyzer.TimeSpentBuildingInterceptChokes += time.perf_counter() - start

    # This is heavily optimized at this point.
    def build_chokes_and_pathways(self):
        minPath = INF_PATH_WAY
        for tile in self.map.pathableTiles:
            # build the pathway
            path = self.pathWayLookupMatrix._grid[tile.x][tile.y]
            if path:
                continue

            path = self.build_pathway(tile)
            self.pathWays.append(path)
            if path.distance < minPath.distance:
                minPath = path

            chokeCounterMap = {}
            for pathTile in path.tiles:
                if pathTile.isMountain or (pathTile.tile == TILE_OBSTACLE and not pathTile.discovered and not pathTile.isCity) or (pathTile.isCity and pathTile.player == -1):
                    continue

                chokeKey = self._get_choke_key(pathTile)
                chokeCounterMap[chokeKey] = chokeCounterMap.get(chokeKey, 0) + 1

            for pathTile in path.tiles:
                if pathTile.isMountain or (pathTile.tile == TILE_OBSTACLE and not pathTile.discovered and not pathTile.isCity) or (pathTile.isCity and pathTile.player == -1):
                    continue
                cw = chokeCounterMap[self._get_choke_key(pathTile)]
                self.chokeWidths._grid[pathTile.x][pathTile.y] = cw

        self.shortestPathWay = minPath
    # # stack
    # def build_pathway(self, tile) -> PathWay:
    #     aMap = self.aMap
    #     bMap = self.bMap
    #     lookupMatrix = self.pathWayLookupMatrix
    #
    #     distance = aMap[tile] + bMap[tile]
    #     # logbook.info("  building pathway from tile {} distance {}".format(tile.toString(), distance))
    #     path = PathWay(distance=distance)
    #     pathTiles = path.tiles
    #     path.seed_tile = tile
    #
    #     queue = deque()
    #     queue.appendleft(tile)
    #     while queue:
    #         currentTile = queue.pop()
    #         if lookupMatrix._grid[currentTile.x][currentTile.y]:
    #             continue
    #         currentTileDistance = aMap[currentTile] + bMap[currentTile]
    #         if currentTileDistance != distance:
    #             continue
    #
    #         # logbook.info("    adding tile {}".format(currentTile.toString()))
    #         pathTiles.add(currentTile)
    #         lookupMatrix[currentTile] = path
    #
    #         for adjacentTile in currentTile.movable:
    #             queue.append(adjacentTile)
    #     return path

    # def build_pathway(self, tile) -> PathWay:
    #     aMap = self.aMap
    #     bMap = self.bMap
    #     lookupMatrix = self.pathWayLookupMatrix
    #
    #     distance = aMap[tile] + bMap[tile]
    #     # logbook.info("  building pathway from tile {} distance {}".format(tile.toString(), distance))
    #     path = PathWay(distance=distance)
    #     pathTiles = path.tiles
    #     path.seed_tile = tile
    #
    #     queue = deque()
    #     queue.appendleft(tile)
    #     while queue:
    #         currentTile = queue.pop()
    #         currentTileDistance = aMap[currentTile] + bMap[currentTile]
    #         if currentTileDistance != distance:
    #             continue
    #         if currentTile in lookupMatrix:
    #             continue
    #
    #         # logbook.info("    adding tile {}".format(currentTile.toString()))
    #         pathTiles.add(currentTile)
    #         lookupMatrix[currentTile] = path
    #
    #         for adjacentTile in currentTile.movable:
    #             queue.appendleft(adjacentTile)
    #     return path


    # recurse
    def build_pathway(self, tile) -> PathWay:
        distance = self.aMap._grid[tile.x][tile.y] + self.bMap._grid[tile.x][tile.y]
        #logbook.info("  building pathway from tile {} distance {}".format(tile.toString(), distance))
        path = PathWay(distance=distance)
        path.seed_tile = tile

        self._build_pathway_recurse(path, tile)

        return path

    # I hate all of these .grid hacks, but they are like 30% faster sadly..
    def _build_pathway_recurse(self, path: PathWay, currentTile: Tile):
        if self.pathWayLookupMatrix._grid[currentTile.x][currentTile.y]:
            return
        if self.aMap._grid[currentTile.x][currentTile.y] + self.bMap._grid[currentTile.x][currentTile.y] != path.distance:
            return

        #logbook.info("    adding tile {}".format(currentTile.toString()))
        path.tiles.add(currentTile)
        self.pathWayLookupMatrix._grid[currentTile.x][currentTile.y] = path

        for adjacentTile in currentTile.movable:
            if self.pathWayLookupMatrix._grid[adjacentTile.x][adjacentTile.y]:
                continue

            if adjacentTile.isMountain or (adjacentTile.tile == TILE_OBSTACLE and not adjacentTile.discovered and not adjacentTile.isCity) or (adjacentTile.isCity and adjacentTile.player == -1):
                continue

            self._build_pathway_recurse(path, adjacentTile)

    def _get_choke_key(self, tile: Tile) -> typing.Tuple:
        # including path in the key forces the 'chokes' to be part of the same pathway.
        return self.aMap._grid[tile.x][tile.y], self.bMap._grid[tile.x][tile.y]

        # return self.aMap[tile], self.bMap[tile]
        # return path.distance, self.aMap[tile], self.bMap[tile]

    def _get_tile_middle_width(self, tile: Tile, path: PathWay, width: int) -> int:
        # if width == 1:
        #     return 0

        return width // 2

    def build_intercept_points(self):
        q = deque()
        # TODO this can just be array of arrays, just need to know min and max values...?
        distancesLookup = {}
        closedBy = {}
        visitedByLookup = {}

        q.append((self.tileB, set()))

        visited = MapMatrixSet(self.map)
        pw = self.pathWayLookupMatrix._grid[self.tileA.x][self.tileA.y]
        if pw is None:
            return

        shortestDist = pw.distance

        while q:
            nextTile, fromClosed = q.popleft()
            if nextTile not in self.shortestPathWay.tiles:
                continue
            if nextTile in visited:
                continue

            visited.add(nextTile)
            nextBDist = self.bMap[nextTile]

            pw = self.pathWayLookupMatrix[nextTile]

            offsetDist = nextBDist + pw.distance - shortestDist

            curSet = distancesLookup.get(offsetDist, None)
            if not curSet:
                curSet = []
                distancesLookup[offsetDist] = curSet

            curSet.append(nextTile)

            for t in nextTile.movable:
                if t.isObstacle:
                    continue  # TODO ??
                if t not in visited:  # and t in self.shortestPathWay.tiles
                    nPw = self.pathWayLookupMatrix[t]
                    if nPw is None:
                        continue
                    if nPw.distance >= pw.distance:
                        q.append(t)

    def build_intercept_chokes(self):
        q = deque()
        # TODO this can just be array of arrays, just need to know min and max values...?
        distancesLookup = {}
        closedBy = {}
        visitedByLookup = {}

        q.append(self.tileB)

        visited = MapMatrixSet(self.map)
        pw = self.pathWayLookupMatrix._grid[self.tileA.x][self.tileA.y]
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
            nextBDist = self.bMap[nextTile]

            pw = self.pathWayLookupMatrix[nextTile]

            offsetDist = nextBDist + pw.distance - shortestDist

            curSet = distancesLookup.get(offsetDist, None)
            if not curSet:
                curSet = []
                distancesLookup[offsetDist] = curSet

            curSet.append(nextTile)

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

        zeroChokes = []
        oneChokes = set()

        for r in range(self.shortestPathWay.distance + 1):
            curSet = distancesLookup.get(r, None)
            if not curSet:
                continue
            if len(curSet) == 1:
                # then this is a primary choke
                zeroChokes.append(curSet[0])
                # for t in curSet[0].movable:
                #     if not t.isObstacle:
                #         oneChokes.add(t)
                continue
            if len(curSet) == 2:
                first = curSet[0]
                firstDist = self.bMap[first]
                # then this is likely a 1-away choke, verify and find common one-choke tiles
                anyOne = False
                for t in curSet[0].movable:
                    # this forces us to be directional with the save, you can only claim this chase-intercept when arriving from the front, not the back, of a choke.
                    # TODO this breaks test_should_see_split_path_blocker_as_mid_choke, we need to intercept with a one-tile from behind, there.
                    # if self.bMap[t] < firstDist:
                    #     continue
                    if t.isObstacle:
                        continue
                    if t in curSet[1].movable:
                        oneChokes.add(t)
                        anyOne = True
                if anyOne:
                    continue

            # TODO there is a split if we cannot build a chain of adjacents..?

            # logbook.info(f'at dist {r}, found {len(curSet)} tiles')
            #
            # for tile in curSet:
            #     maxDist = 0
            #     for altTile in curSet:
            #         if tile == altTile:
            #             continue
            #
            #         dist = self.map.distance_mapper.get_distance_between_or_none(tile, altTile)
            #         if dist is None:
            #             continue
            #         if dist > maxDist:
            #             maxDist = dist
            #     # logbook.info(f'ic {str(tile)} = {maxDist}')
            #     self.interceptChokes[tile] = maxDist

        self.tileDistancesLookup = distancesLookup

        shortestSet = self.shortestPathWay.tiles

        def foreachFunc(tile: Tile, stateObj: typing.Tuple[int, int, Tile | None]) -> typing.Tuple[int, int, Tile | None]:
            dist, interceptMoves, fromTile = stateObj
            self.interceptChokes[tile] = dist
            self.interceptDistances[tile] = interceptMoves
            # This is what lets us include the tiles 1 away from shortest path, which is good for finding common one-tile-away shared split intercept points
            if tile not in shortestSet:
                return None
            return dist + 1, interceptMoves + 1, tile

        startTiles: typing.Dict[Tile, typing.Tuple[int, typing.Tuple[int, int, Tile | None]]] = {}
        """Tile -> (startDist, (prioStartDist, interceptMoves, fromTile))"""

        # oneChokes come first because we must overwrite them with zeroChokes, if the zeroChoke is also a oneChoke
        for oneChoke in oneChokes:
            # oneChoke can guaranteed intercept
            startTiles[oneChoke] = 1, (1, 0, None)

        # for zeroChoke in zeroChokes:
        #     #... this does nothing except lie about the intercept moves
        #     for tile in zeroChoke.movable:
        #         if tile.isObstacle:
        #             continue
        #         startTiles[tile] = 0, (0, 0, None)

        furthestZeroChoke = 0
        for zeroChoke in zeroChokes:
            if zeroChoke != self.tileA:
                dist = self.bMap[zeroChoke]
                if dist > furthestZeroChoke:
                    furthestZeroChoke = dist
            # normally we can reach a zero choke one turn behind our opponent and be safe.
            turn = -1
            # if zeroChoke.isGeneral:
            #     # must get to general 1 ahead of opp to be safe, however the search out from this choke needs to pretend it is a normal zero choke(?)
            #     turn = 0
            # elif SearchUtils.any_where(zeroChoke.movable, lambda t: t.isGeneral):
            #     # we must get to a tile next to our general at the same time as opp, no chasing, or we lose on priority. TODO take into account priority?
            #     turn = 0

            startTiles[zeroChoke] = turn, (turn, 0, None)
        SearchUtils.breadth_first_foreach_with_state_and_start_dist(self.map, startTiles, maxDepth=20, foreachFunc=foreachFunc, noLog=True)
        for zeroChoke in zeroChokes:
            if zeroChoke.isGeneral:
                # must get to general 1 ahead of opp to be safe
                self.interceptChokes[zeroChoke] = 1
                # we must get to a tile next to our general at the same time as opp, no chasing, or we lose on priority. TODO take into account priority?
                for tile in zeroChoke.movable:
                    existingVal = self.interceptChokes[tile]
                    if existingVal is not None:
                        self.interceptChokes[tile] = existingVal + 1

        for icTile in self.map.pathableTiles:
            chokeDist = self.interceptChokes[icTile]
            if chokeDist is not None:
                aDist = self.aMap[icTile]
                # anything above our closest choke, we can move in by 1
                # if bDist < furthestZeroChoke:
                #     bDist += 1
                interceptWorstCaseDist = self.interceptDistances[icTile]
                interceptTurns = self.shortestPathWay.distance - aDist + 1  # - chokeDist - interceptWorstCaseDist
                self.interceptTurns[icTile] = interceptTurns

        self.fix_choke_widths(self.shortestPathWay.tiles)

    def fix_choke_widths(self, shortestTiles: typing.Set[Tile]):
        # TODO this isn't right either
        def foreachFunc(tile: Tile, stateObj: typing.Tuple[int, int]) -> typing.Tuple[int, int] | None:
            if tile in shortestTiles:
                return None
            prevCw, _ = stateObj
            newCw = prevCw + 1
            self.chokeWidths[tile] = newCw
            # This is what lets us include the tiles 1 away from shortest path, which is good for finding common one-tile-away shared split intercept points
            return newCw, 0

        startTiles: typing.Dict[Tile, typing.Tuple[int, typing.Tuple[int, int]]] = {}
        for tile in shortestTiles:
            ourDist = self.chokeWidths[tile]
            for adj in tile.movable:
                existing = startTiles.get(adj, None)
                if not existing or existing[0] > ourDist:
                    startTiles[adj] = (ourDist, (ourDist, 0))

        SearchUtils.breadth_first_foreach_with_state_and_start_dist(self.map, startTiles, maxDepth=20, foreachFunc=foreachFunc, noLog=True)

    def is_choke(self, tile: Tile) -> bool:
        # chokeVal = self.interceptChokes[tile]
        # return chokeVal is not None and chokeVal <= 0 and self.interceptDistances[tile] == 0
        chokeMoves = self.interceptDistances[tile]
        return chokeMoves is not None and chokeMoves == 0

    def is_one_behind_safe_choke(self, tile: Tile) -> bool:
        chokeVal = self.interceptChokes[tile]
        return chokeVal == -1  # TODO should this be only -1? not sure what its used for.

    def is_two_move_capture_choke(self, tile: Tile) -> bool:
        chokeMoves = self.interceptDistances[tile]
        return chokeMoves is not None and chokeMoves <= 2

    @classmethod
    def build_from_path(cls, map: MapBase, path: Path) -> ArmyAnalyzer:

        tileA = path.tail.tile
        tileB = path.start.tile
        if path.length != map.distance_mapper.get_distance_between(tileB, tileA):
            # then we have a mid-point non-shortest-path scenario
            i = 0
            node = path.start
            prev = None
            while node is not None and map.distance_mapper.get_distance_between(tileB, node.tile) == i:
                i += 1
                prev = node
                node = node.next

            logbook.info(f'ArmyAnalyzer.build_from_path was non-shortest, shortest segment ending at {prev.tile} for path {tileB}-->{tileA}  ({path})')
            tileA = prev.tile

        # # old furthest point logic, picked the furthest FRIENDLY tile in the path
        # dists = map.distance_mapper.get_tile_dist_matrix(path.start.tile)
        # furthestPoint = max(path.tileList, key=lambda t: dists[t] if map.is_tile_friendly(t) else 0)
        # logbook.info(f'backfilling threat army analysis from {str(path.start.tile)}->{str(furthestPoint)}')
        # if furthestPoint != tileA:
        #     raise AssertionError(f'old logic picked {furthestPoint}, new logic picked {tileA}')

        analyzer = ArmyAnalyzer(map, tileA, tileB)

        return analyzer
