from __future__ import annotations

import traceback
import typing
from collections import deque

import logbook

import KnapsackUtils
import SearchUtils
from Algorithms import TileIslandBuilder, TileIsland
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Interfaces import TilePlanInterface
from MapMatrix import MapMatrix
from Path import Path
from PerformanceTimer import PerformanceTimer
from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile


class IslandCompletionInfo(object):
    def __init__(self, island: TileIsland):
        self.tiles_left: int = island.tile_count
        self.army_left: int = island.sum_army


class FlowExpansionVal(object):
    def __init__(self, distSoFar: int, armyGathered: int, tilesLeftToCap: int, armyLeftToCap: int, islandInfo: IslandCompletionInfo):
        self.dist_so_far: int = distSoFar
        self.army_gathered: int = armyGathered
        self.tiles_left_to_cap: int = tilesLeftToCap
        self.army_left_to_cap: int = armyLeftToCap
        self.island_info: IslandCompletionInfo = islandInfo
        self.incidental_tile_capture_points: int = 0
        self.incidental_neutral_caps: int = 0
        self.incidental_enemy_caps: int = 0

    def __lt__(self, other: FlowExpansionVal | None) -> bool:
        if self.dist_so_far != other.dist_so_far:
            return self.dist_so_far < other.dist_so_far
        if self.incidental_tile_capture_points != other.incidental_tile_capture_points:
            return self.incidental_tile_capture_points < other.incidental_tile_capture_points
        if self.army_gathered != other.army_gathered:
            return self.army_gathered < other.army_gathered
        if self.tiles_left_to_cap != other.tiles_left_to_cap:
            return self.tiles_left_to_cap < other.tiles_left_to_cap
        if self.army_left_to_cap != other.army_left_to_cap:
            return self.army_left_to_cap < other.army_left_to_cap
        return False

    def __gt__(self, other: FlowExpansionVal | None) -> bool:
        return not self < other

    def __str__(self) -> str:
        return str(self.__dict__)

    # def __eq__(self, other) -> bool:
    #     if other is None:
    #         return False
    #     return self.x == other.x and self.y == other.y


class ArmyFlowExpander(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map

    def get_expansion_options(
            self,
            islands: TileIslandBuilder,
            asPlayer: int,
            targetPlayer: int,
            turns: int,
            boardAnalysis: BoardAnalyzer,
            territoryMap: typing.List[typing.List[int]],
            negativeTiles: typing.Set[Tile] = None,
            leafMoves: typing.Union[None, typing.List[Move]] = None,
            viewInfo: ViewInfo = None,
            # valueFunc=None,
            # priorityFunc=None,
            # initFunc=None,
            # skipFunc=None,
            # boundFunc=None,
            # allowLeafMoves=True,
            # useLeafMovesFirst: bool = False,
            bonusCapturePointMatrix: MapMatrix[float] | None = None,
            # colors: typing.Tuple[int, int, int] = (235, 240, 50),
            # additionalOptionValues: typing.List[typing.Tuple[float, int, Path]] | None = None,
            perfTimer: PerformanceTimer | None = None,
    ) -> typing.List[TilePlanInterface]:
        """
        The goal of this algorithm is to produce a maximal flow of army from your territory into target players friendly territories without overfilling them.
        Should produce good tile plan interface of estimated movements of army into enemy territory. Wont include all the tiles that will be captured in enemy territory since calculating that is pretty pointless.

        @param islands:
        @param asPlayer:
        @param targetPlayer:
        @param turns:
        @param boardAnalysis:
        @param territoryMap:
        @param negativeTiles:
        @param leafMoves:
        @param viewInfo:
        @param bonusCapturePointMatrix:
        @param perfTimer:
        @return:
        """
        startTiles: typing.Dict[Tile, typing.Tuple[FlowExpansionVal, int]] = {}
        targetIslands = islands.tile_islands_by_player[targetPlayer]
        ourIslands = islands.tile_islands_by_player[self.map.player_index]

        flowPlan = self.find_flow_plans(ourIslands, targetIslands)
        #
        # for targetIsland in targetIslands:
        #     islandInfo = IslandCompletionInfo(targetIsland)
        #     for tile in targetIsland.tile_set:
        #         startTiles[tile] = (FlowExpansionVal(0, 0, targetIsland.tile_count, armyLeftToCap=targetIsland.sum_army, islandInfo=islandInfo), 0)
        #
        # if negativeTiles is None:
        #     negativeTiles = set()
        #
        # friendlyPlayers = self.map.get_teammates(asPlayer)
        # targetPlayers = self.map.get_teammates(targetPlayer)
        #
        # def valFunc(curTile: Tile, prioVal: FlowExpansionVal) -> typing.Any:
        #     return prioVal
        #
        # def prioFunc(nextTile: Tile, curPrios: FlowExpansionVal) -> FlowExpansionVal | None:
        #     if curPrios.army_gathered > curPrios.army_left_to_cap + 1:
        #         return None
        #     nextPrio = FlowExpansionVal(distSoFar=curPrios.dist_so_far + 1, armyGathered=curPrios.army_gathered, tilesLeftToCap=curPrios.tiles_left_to_cap, armyLeftToCap=curPrios.army_left_to_cap, islandInfo=curPrios.island_info)
        #     nextPrio.incidental_tile_capture_points = curPrios.incidental_tile_capture_points
        #     nextPrio.incidental_enemy_caps = curPrios.incidental_enemy_caps
        #     nextPrio.incidental_neutral_caps = curPrios.incidental_neutral_caps
        #
        #     # (
        #     #     distSoFar,
        #     #     prioWeighted,
        #     #     fakeDistSoFar,
        #     #     wastedMoves,
        #     #     negTileCapturePoints,
        #     #     negArmyRemaining,
        #     #     enemyTiles,
        #     #     neutralTiles,
        #     #     pathPriority,
        #     #     tileSetSoFar,
        #     #     # adjacentSetSoFar,
        #     #     # enemyExpansionValue,
        #     #     # enemyExpansionTileSet
        #     # ) = currentPriorityObject
        #     # nextTerritory = territoryMap[nextTile]
        #
        #     nextPrio.army_gathered -= 1
        #     #
        #     # # only reward closeness to enemy up to a point then penalize it
        #     # cutoffEnemyDist = abs(enemyDistMap[nextTile.x][nextTile.y] - enemyDistPenaltyPoint)
        #     # addedPriority = 3 * (0 - cutoffEnemyDist ** 0.5 + 1)
        #     #
        #     # # reward away from our general but not THAT far away
        #     # cutoffGenDist = abs(generalDistMap[nextTile.x][nextTile.y])
        #     # addedPriority += 3 * (cutoffGenDist ** 0.5 - 1)
        #
        #     if negativeTiles is None or (nextTile not in negativeTiles):
        #         if nextTile.player in friendlyPlayers:
        #             nextPrio.army_gathered += nextTile.army
        #         else:
        #             nextPrio.army_gathered -= nextTile.army
        #
        #     usefulMove = nextTile not in negativeTiles
        #     # enemytiles or enemyterritory undiscovered tiles
        #     # isProbablyEnemyTile = (nextTile.isNeutral
        #     #                        and not nextTile.visible
        #     #                        and nextTerritory in targetPlayers)
        #     # if isProbablyEnemyTile:
        #     #     armyRemaining -= expectedUnseenEnemyTileArmy
        #
        #     if (
        #             # nextTile in tryAvoidSet
        #             nextTile in negativeTiles
        #             # or nextTile in tileSetSoFar
        #     ):
        #         # our tiles and non-target enemy tiles get negatively weighted
        #         # addedPriority -= 1
        #         # 0.7
        #         usefulMove = False
        #         # wastedMoves += 0.5
        #     elif (
        #             targetPlayer != -1
        #             and nextTile.player in targetPlayers
        #     ):
        #         nextPrio.incidental_tile_capture_points += 2
        #         # distSoFar -= 0.99
        #         # else:
        #         #     negTileCapturePoints -= 1.5
        #         nextPrio.incidental_enemy_caps += 1
        #     elif nextTile.player == -1:
        #         # if nextTile.isCity: #TODO and is reasonably placed?
        #         #    neutralTiles -= 12
        #         # we'd prefer to be killing enemy tiles, yeah?
        #         # wastedMoves += 0.2
        #         nextPrio.incidental_neutral_caps += 1
        #         nextPrio.incidental_tile_capture_points += 1
        #         # points for capping tiles in general
        #         # addedPriority += 2
        #     else:  # our tiles and non-target enemy tiles get negatively weighted
        #         # addedPriority -= 1
        #         # 0.7
        #         usefulMove = False
        #         # wastedMoves += 0.5
        #
        #     # if nextTile in tryAvoidSet:
        #     #     addedPriority -= 5
        #     #     negTileCapturePoints += 0.2
        #
        #     if bonusCapturePointMatrix:
        #         bonusPoints = bonusCapturePointMatrix[nextTile]
        #         if bonusPoints < 0.0 or usefulMove:  # for penalized tiles, always apply the penalty. For rewarded tiles, only reward when it is a move that does something.
        #             nextPrio.incidental_tile_capture_points += bonusPoints
        #         if bonusPoints < -10:
        #             return None
        #
        #
        #     # newPathPriority = pathPriority - addedPriority
        #     # prioPerTurn = (negTileCapturePoints) / (distSoFar + wastedMoves)  # - addedPriority / 4
        #
        #     # return distSoFar, prioPerTurn, fakeDistSoFar, wastedMoves, negTileCapturePoints, 0 - armyRemaining, enemyTiles, neutralTiles, newPathPriority, nextTileSet  # , nextAdjacentSet, enemyExpansionValue, nextEnemyExpansionSet
        #
        #     return nextPrio
        #
        # def skipFunc(curTile: Tile, curPrios: FlowExpansionVal) -> bool:
        #     return curPrios.tiles_left_to_cap <= 0
        #
        # prioMatrix = MapMatrix(self.map, 0, emptyVal=None)
        #
        # results = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
        #     self.map,
        #     startTiles,
        #     valueFunc=valFunc,
        #     maxTime=0.2,
        #     maxTurns=100,
        #     maxDepth=100,
        #     noNeutralCities=True,
        #     priorityFunc=prioFunc,
        #     skipFunc=skipFunc,
        #     priorityMatrix=prioMatrix,
        #     priorityMatrixSkipStart=True,
        #     priorityMatrixSkipEnd=False,
        #     logResultValues=True
        # )
        #
        # multiPathDict: typing.Dict[Tile, typing.Dict[int, typing.Tuple[int, Path]]] = {}
        #
        # # Switch this up to use more tiles at the start, just removing the first tile in each path at a time. Maybe this will let us find more 'maximal' paths?
        # def postPathEvalFunction(path, negativeTiles):
        #     value = 0
        #     last = path.start.tile
        #     # if bonusCapturePointMatrix:
        #     #     value += bonusCapturePointMatrix[path.start.tile]
        #     nextNode = path.start.next
        #     while nextNode is not None:
        #         tile = nextNode.tile
        #         # val = _get_tile_path_value(map, tile, last, negativeTiles, targetPlayers, searchingPlayer, enemyDistMap, generalDistMap, territoryMap, enemyDistPenaltyPoint, bonusCapturePointMatrix)
        #         value += val
        #
        #         last = tile
        #         nextNode = nextNode.next
        #     return value
        #
        #
        # newPaths = []
        # for tile, tilePaths in results.items():
        #     curTileDict = multiPathDict.get(tile, {})
        #     anyPathInc = False
        #     values = {}
        #     for path in tilePaths:
        #         value = postPathEvalFunction(path, negativeTiles)
        #         values[path] = value
        #         vpt = value / path.length
        #         if value >= 0.2 and vpt >= valPerTurnCutoff:
        #             anyPathInc = True
        #
        #     if anyPathInc:
        #         for path in tilePaths:
        #             visited = set()
        #             value = values[path]
        #             friendlyCityCount = 0
        #             node = path.start
        #             while node is not None:
        #                 if node.tile not in negativeTiles and node.tile not in visited:
        #                     visited.add(node.tile)
        #
        #                     if node.tile.player in friendlyPlayers and (
        #                             node.tile.isCity or node.tile.isGeneral):
        #                         friendlyCityCount += 1
        #                 node = node.next
        #             existingMax, existingPath = curTileDict.get(path.length, defaultNoPathValue)
        #             if value > existingMax:
        #                 node = path.start
        #                 while node is not None:
        #                     if (node.tile.isGeneral or node.tile.isCity) and node.tile.player == searchingPlayer:
        #                         usage = cityUsages.get(node.tile, 0)
        #                         cityUsages[node.tile] = usage + 1
        #                     node = node.next
        #                 if existingPath is not None:
        #                     logEntries.append(f'path for {str(tile)} BETTER than existing:\r\n      new {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')
        #                 curTileDict[path.length] = (value, path)
        #
        #                 # todo dont need this...?
        #                 # sortedTiles.remove(path.start.tile)
        #                 newPaths.append((value, path))
        #             else:
        #                 logEntries.append(f'path for {str(tile)} worse than existing:\r\n      bad {value} {str(path)}\r\n   exist {existingMax} {str(existingPath)}')
        #
        #     multiPathDict[tile] = curTileDict
        #
        # logEntries.append(f'iter complete @ {time.perf_counter() - startTime:.3f} iter {iter[0]} paths {len(newPaths)}')

    def find_flow_plans(self, ourIslands: typing.List[TileIsland], targetIslands: typing.List[TileIsland]) -> typing.Any:
        """
        Build a plan of which islands should flow into which other islands

        @param targetIslands:
        @return:
        """

        q = deque()
        opts = {}

        # ourFurthestIslands = self.

        for targetIsland in targetIslands:
            for ourIsland in ourIslands:


    def flow_expansion_knapsack_gather_iteration(
            self,
            turns: int,
            valuePerTurnPathPerTile: typing.Dict[typing.Any, typing.List[Path]],
            shouldLog: bool = False,
            valueFunc: typing.Callable[[Path], typing.Tuple[int, int]] | None = None,
    ) -> typing.Tuple[int, typing.List[Path]]:
        if valueFunc is None:
            def value_func(p: Path) -> typing.Tuple[int, int]:
                return p.value, p.length

            valueFunc = value_func

        totalValue = 0
        maxKnapsackedPaths = []
        pathValLookup = {}

        error = True
        attempts = 0
        while error and attempts < 4:
            attempts += 1
            try:
                # build knapsack weights and values
                groupedPaths = [valuePerTurnPathPerTile[item] for item in valuePerTurnPathPerTile]
                groups = []
                paths = []
                values = []
                weights = []
                groupIdx = 0
                for pathGroup in groupedPaths:
                    if len(pathGroup) > 0:
                        for path in pathGroup:
                            groups.append(groupIdx)
                            paths.append(path)
                            pathVal, pathDist = valueFunc(path)
                            values.append(pathVal)
                            weights.append(pathDist)
                            pathValLookup[path] = pathVal
                        groupIdx += 1
                if len(paths) == 0:
                    return 0, []

                # if shouldLog:
                logbook.info(f"Feeding solve_multiple_choice_knapsack {len(paths)} options turns {turns}:")
                if shouldLog:
                    for i, path in enumerate(paths):
                        logbook.info(
                            f"{i}:  group[{groups[i]}] value {values[i]} length {weights[i]} path {str(path)}")

                totalValue, maxKnapsackedPaths = KnapsackUtils.solve_multiple_choice_knapsack(
                    paths,
                    turns,
                    weights,
                    values,
                    groups,
                    longRuntimeThreshold=0.01)
                logbook.info(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")
                error = False
            except AssertionError as ex:
                logbook.error(f'OVER-KNAPSACKED, PRUNING ALL PATHS UNDER AVERAGE. v\r\n{str(ex)}\r\nOVER-KNAPSACKED, PRUNING ALL PATHS UNDER AVERAGE. ^ ')
                valuePerTurnPathPerTile = _prune_worst_paths_greedily(valuePerTurnPathPerTile, valueFunc)

        return totalValue, sorted(maxKnapsackedPaths, key=lambda p: pathValLookup[p] / max(1, p.length), reverse=True)


def _prune_worst_paths_greedily(
        valuePerTurnPathPerTile: typing.Dict[typing.Any, typing.List[Path]],
        valueFunc: typing.Callable[[Path], typing.Tuple[int, int]]
) -> typing.Dict[typing.Any, typing.List[Path]]:
    sum = 0
    count = 0
    for group in valuePerTurnPathPerTile.keys():
        for path in valuePerTurnPathPerTile[group]:
            value, dist = valueFunc(path)
            sum += value / dist
            count += 1
    avg = sum / count

    newDict = {}
    for group in valuePerTurnPathPerTile.keys():
        pathListByGroup = valuePerTurnPathPerTile[group]
        newListByGroup = []
        for path in pathListByGroup:
            value, dist = valueFunc(path)
            valPerTurn = value / dist
            if valPerTurn > avg:
                newListByGroup.append(path)
        if len(newListByGroup) > 0:
            newDict[group] = newListByGroup

    return newDict