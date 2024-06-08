"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    July 2019
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import annotations

import itertools
import time
import typing

import logbook

from collections import deque

import SearchUtils
from Army import Army
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

    def __init__(self, map: MapBase, armyA: Tile | Army, armyB: Tile | Army, bypassRetraverseThreshold: int = -1, bypassRetraverseThresholdPathTiles: typing.Iterable[Tile] | None = None):
        """

        @param map:
        @param armyA:
        @param armyB:
        @param bypassRetraverseThreshold: if set to a positive integer, will bypass including tiles where army at tile B would retraverse this many of its own friendly tiles with no adjacent A team tiles.
        @param bypassRetraverseThresholdPathTiles: if included, these tiles will be excluded from the retraverse limitation
        """
        startTime = time.perf_counter()
        self.map: MapBase = map
        if isinstance(armyA, Army):
            self.tileA: Tile = armyA.tile
        else:
            self.tileA: Tile = armyA

        if isinstance(armyB, Army):
            self.tileB: Tile = armyB.tile
        else:
            self.tileB: Tile = armyB

        # path chokes are relative to the paths between A and B
        self.pathWayLookupMatrix: MapMatrixInterface[PathWay | None] = MapMatrix(map, initVal=None)
        self.pathWays: typing.List[PathWay] = []
        self.shortestPathWay: PathWay = INF_PATH_WAY
        self.chokeWidths: MapMatrixInterface[int] = MapMatrix(map)
        """
        If the army were to path through this tile, this is the number of alternate nearby tiles the army could also be at. So if the army has to make an extra wide path to get here, wasting moves, this will be chokeWidth1 even if the actual choke is 2 wide.
        """

        self.interceptChokes: MapMatrixInterface[int] = MapMatrix(map)
        """The value in here for a tile represents the number of additional moves necessary for worst case intercept, for an army that reaches this tile on the earliest turn the bTile army could reach this. It is effectively the difference between the best case and worst case intercept turns for an intercept reaching this tile."""

        self.interceptTurns: MapMatrixInterface[int] = MapMatrix(map)
        """This represents the raw turns into the intercept of an army that another army army must reach this tile to successfully achieve an intercept, ASSUMING the enemy army goes this way."""

        self.interceptDistances: MapMatrixInterface[int] = MapMatrix(map)
        """The number of moves you will waste to achieve the intercept, worst case, regardless of which way the enemy army goes."""

        self.tileDistancesLookup: typing.Dict[int, typing.List[Tile]] = {}
        """A lookup from the number of turns into the intercept, to which tiles the enemy army could have reached by that point (shorted path only)."""

        logbook.info(f"ArmyAnalyzer analyzing {self.tileA} and {self.tileB}")

        self.aMap: MapMatrixInterface[int]
        self.bMap: MapMatrixInterface[int]

        if bypassRetraverseThreshold <= 0:
            self.aMap = map.distance_mapper.get_tile_dist_matrix(self.tileA)
            self.bMap = map.distance_mapper.get_tile_dist_matrix(self.tileB)
        else:
            skip = {t for t in itertools.chain.from_iterable(map.players[p].tiles for p in map.get_teammates(self.tileB.player))}

            if bypassRetraverseThresholdPathTiles:
                skip.difference_update(bypassRetraverseThresholdPathTiles)

            def foreachFunc(tile: Tile):
                skip.discard(tile)

            SearchUtils.breadth_first_foreach_fast_no_neut_cities(map, [t for t in map.pathable_tiles if map.is_tile_on_team_with(t, self.tileA.player) or t == self.tileB], maxDepth=bypassRetraverseThreshold, foreachFunc=foreachFunc)
            logbook.info(f'building distance maps except skipping {len(skip)} tiles: {" | ".join([str(t) for t in skip])}')

            self.aMap = SearchUtils.build_distance_map_matrix(map, [self.tileA], skip)
            self.bMap = SearchUtils.build_distance_map_matrix(map, [self.tileB], skip)

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
        for tile in self.map.pathable_tiles:
            # build the pathway
            path = self.pathWayLookupMatrix.raw[tile.tile_index]
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
                self.chokeWidths.raw[pathTile.tile_index] = cw

        self.shortestPathWay = minPath

    # recurse
    def build_pathway(self, tile) -> PathWay:
        distance = self.aMap.raw[tile.tile_index] + self.bMap.raw[tile.tile_index]
        #logbook.info("  building pathway from tile {} distance {}".format(tile.toString(), distance))
        path = PathWay(distance=distance)
        path.seed_tile = tile

        self._build_pathway_recurse(path, tile)

        return path

    # I hate all of these .grid hacks, but they are like 30% faster sadly..
    def _build_pathway_recurse(self, path: PathWay, currentTile: Tile):
        if self.pathWayLookupMatrix.raw[currentTile.tile_index]:
            return
        if self.aMap.raw[currentTile.tile_index] + self.bMap.raw[currentTile.tile_index] != path.distance:
            return

        #logbook.info("    adding tile {}".format(currentTile.toString()))
        path.tiles.add(currentTile)
        self.pathWayLookupMatrix.raw[currentTile.tile_index] = path

        for adjacentTile in currentTile.movable:
            if self.pathWayLookupMatrix.raw[adjacentTile.tile_index]:
                continue

            if adjacentTile.isMountain or (adjacentTile.tile == TILE_OBSTACLE and not adjacentTile.discovered and not adjacentTile.isCity) or (adjacentTile.isCity and adjacentTile.player == -1):
                continue

            self._build_pathway_recurse(path, adjacentTile)

    def _get_choke_key(self, tile: Tile) -> typing.Tuple:
        # including path in the key forces the 'chokes' to be part of the same pathway.
        return self.aMap.raw[tile.tile_index], self.bMap.raw[tile.tile_index]

        # return self.aMap[tile], self.bMap[tile]
        # return path.distance, self.aMap[tile], self.bMap[tile]

    def build_intercept_chokes(self):
        q = deque()
        # TODO this can just be array of arrays, just need to know min and max values...?
        distancesLookup = {}

        q.append(self.tileB)

        visited = MapMatrixSet(self.map)
        pw = self.pathWayLookupMatrix.raw[self.tileA.tile_index]
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

        for icTile in self.map.pathable_tiles:
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
            if ourDist is None:
                continue
            for adj in tile.movable:
                existing = startTiles.get(adj, None)
                if not existing or existing[0] > ourDist:
                    startTiles[adj] = (ourDist, (ourDist, 0))

        SearchUtils.breadth_first_foreach_with_state_and_start_dist(self.map, startTiles, maxDepth=20, foreachFunc=foreachFunc, noLog=True)

    def is_choke(self, tile: Tile) -> bool:
        chokeMoves = self.interceptDistances[tile]
        return chokeMoves is not None and chokeMoves == 0

    def is_one_behind_safe_choke(self, tile: Tile) -> bool:
        chokeVal = self.interceptChokes[tile]
        return chokeVal == -1  # TODO should this be only -1? not sure what its used for.

    def is_two_move_capture_choke(self, tile: Tile) -> bool:
        chokeMoves = self.interceptDistances[tile]
        return chokeMoves is not None and chokeMoves <= 2

    @classmethod
    def build_from_path(cls, map: MapBase, path: Path, bypassRetraverse: bool = False) -> ArmyAnalyzer:
        """

        @param map:
        @param path:
        @param bypassRetraverse: if True, will make sure that the average captures of the path are matched by the army analysis board; tiles will be cut if it involves backtracking over friendly territory instead of capturing tiles. DO NOT use for kill threats.
        @return:
        """

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

        bypassRetraverseThreshold = -1
        bypassRetraversePath = None
        if bypassRetraverse:
            bypassRetraverseThreshold = 2
            bypassRetraversePath = path.tileList

        analyzer = ArmyAnalyzer(map, tileA, tileB, bypassRetraverseThreshold=bypassRetraverseThreshold, bypassRetraverseThresholdPathTiles=bypassRetraversePath)

        return analyzer
