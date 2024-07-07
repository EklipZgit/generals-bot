import heapq
import random
import time
import typing

import logbook
import networkx as nx
import numpy as np

import DebugHelper
import Gather
import KnapsackUtils
import SearchUtils
from Algorithms.FastDisjointSet import FastDisjointTileSetMultiSum
from MapMatrix import MapMatrix
from Viewer import ViewerProcessHost
from Viewer.ViewerProcessHost import DebugLiveViewerHost
from base import Colors
from . import recalculate_tree_values, prune_mst_to_turns_with_values, GatherDebug, GatherCapturePlan, NetworkXHelpers, GatherSteiner
from Interfaces import MapMatrixInterface, TileSet
from Models import GatherTreeNode
from Path import Path
from ViewInfo import ViewInfo, TargetStyle, PathColorer
from base.client.map import MapBase
from base.client.tile import Tile


def _knapsack_max_set_gather_iteration(
        turns: int,
        valuePerTurnPathPerTile: typing.Dict[Tile, typing.List[Path]],
        logList: typing.List[str] | None = None,
        valueFunc: typing.Callable[[Path], int] | None = None,
) -> typing.Tuple[int, typing.List[Path]]:
    factor = 1
    if valueFunc is None:
        factor = 1000

        def value_func(path: Path) -> int:
            return int(path.value * 1000)

        valueFunc = value_func

    # build knapsack weights and values
    groupedPaths = [group for group in valuePerTurnPathPerTile.values()]
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
                values.append(valueFunc(path))
                weights.append(path.length)
            groupIdx += 1
    if len(paths) == 0:
        return 0, []

    if logList is not None:
        logList.append(f"Feeding solve_multiple_choice_knapsack {len(paths)} paths turns {turns}:")
        for i, path in enumerate(paths):
            logList.append(
                f"{i}:  group[{str(path.start.tile)}] value {path.value} length {path.length} path {path.toString()}")

    totalValue, maxKnapsackedPaths = KnapsackUtils.solve_multiple_choice_knapsack(paths, turns, weights, values, groups, noLog=logList is None)
    if logList:
        logList.append(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")

    return totalValue // factor, maxKnapsackedPaths


def _get_sub_knapsack_max_set_gather(
        map,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        valueFunc,
        pathValueFunc,
        remainingTurns: int,
        fullTurns: int,
        # noNeutralCities,
        # negativeTiles,
        skipTiles,
        searchingPlayer,
        priorityFunc,
        skipFunc: typing.Callable[[Tile, typing.Any], bool] | None,
        ignoreStartTile,
        incrementBackward,
        preferNeutral,
        logEntries: typing.List[str],
        useTrueValueGathered: bool = False,
        shouldLog: bool = False,
) -> typing.Tuple[int, typing.List[Path]]:
    subSkip = skipFunc

    # this dies outright in defensive scenarios. Need to either parameterize it or accomplish this some other way.
    # if remainingTurns / fullTurns < 0.6:
    #     if skipFunc is not None:
    #         def initSkip(tile: Tile, prioObj: typing.Any) -> bool:
    #             if map.is_tile_friendly(tile) and tile.army <= 1:
    #                 return True

    #             return skipFunc(tile, prioObj)

    #         subSkip = initSkip
    #     else:
    #         def initSkip(tile: Tile, prioObj: typing.Any) -> bool:
    #             if map.is_tile_friendly(tile) and tile.army <= 1 and tile not in startTilesDict:
    #                 return True

    #             return False

    #         subSkip = initSkip

    # NOT causing the duplicates issue
    if len(startTilesDict) < remainingTurns // 10:
        return _get_single_line_iterative_starter_max_set(
            fullTurns,
            ignoreStartTile,
            incrementBackward,
            logEntries,
            map,
            # negativeTiles,
            preferNeutral,
            priorityFunc,
            remainingTurns,
            searchingPlayer,
            shouldLog,
            subSkip,
            skipTiles,
            startTilesDict,
            useTrueValueGathered,
            valueFunc,
            pathValueFunc=pathValueFunc)

    valuePerTurnPathPerTilePerDistance = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance_global_visited(
        map,
        startTilesDict,
        valueFunc,
        10000000,
        remainingTurns,
        maxDepth=10000,
        noNeutralCities=True,
        # negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=subSkip,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        # priorityMatrix=priorityMatrix,
        logResultValues=shouldLog,
        ignoreNonPlayerArmy=not useTrueValueGathered,
        ignoreIncrement=True,
        priorityMatrixSkipStart=True,
        pathValueFunc=pathValueFunc,
        noLog=not shouldLog  # note, these log entries end up AFTER all the real logs...
    )

    gatheredArmy, maxPaths = _knapsack_max_set_gather_iteration(remainingTurns, valuePerTurnPathPerTilePerDistance, logList=logEntries if shouldLog else None)

    return int(round(gatheredArmy)), maxPaths


def _get_single_line_iterative_starter_max_set(
        fullTurns,
        ignoreStartTile,
        incrementBackward,
        logEntries,
        map,
        # negativeTiles,
        preferNeutral,
        priorityFunc,
        remainingTurns,
        searchingPlayer,
        shouldLog,
        skipFunc,
        skipTiles,
        startTilesDict,
        useTrueValueGathered,
        valueFunc,
        pathValueFunc):
    logEntries.append(f"DUE TO SMALL SEARCH START TILE COUNT {len(startTilesDict)}, FALLING BACK TO FINDING AN INITIAL MAX-VALUE-PER-TURN PATH FOR {remainingTurns} (fullTurns {fullTurns})")
    #
    # validTupleIndexes = []
    #
    # def vTValueFunc(tile, prioObj):
    #     valPrio = valueFunc(tile, prioObj)
    #     if valPrio is None:
    #         return None
    #     if prioObj is None:
    #         return None
    #     dist = prioObj[0]
    #     if dist == 0:
    #         return None
    #
    #     if len(validTupleIndexes) == 0:
    #         for i in range(len(valPrio)):
    #             tupleItem = valPrio[i]
    #             try:
    #                 val = tupleItem / dist
    #                 validTupleIndexes.append(i)
    #             except:
    #                 pass
    #
    #         if len(validTupleIndexes) == 0:
    #             raise AssertionError(f'couldnt find any valid tuple indexes in valPrio that could be divided by dist. valPrio: {valPrio}')
    #
    #     outTuple = []
    #     for tupleIdx in validTupleIndexes:
    #         outTuple.append(valPrio[tupleIdx] / dist)
    #     return outTuple

    valuePerTurnPath = SearchUtils.breadth_first_dynamic_max_global_visited(
        map,
        startTilesDict,
        valueFunc,
        # vTValueFunc,
        1000000,
        # max(min(remainingTurns, 3), min(15, 2 * remainingTurns // 3)),
        remainingTurns,
        maxDepth=10000000,
        noNeutralCities=True,
        # negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=skipFunc,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        logResultValues=shouldLog,
        noLog=not shouldLog,
        ignoreIncrement=True,
        pathValueFunc=pathValueFunc,
        priorityMatrixSkipStart=True)
    if valuePerTurnPath is None:
        logEntries.append(f'didnt find a max path searching to startTiles {"  ".join([str(tile) for tile in startTilesDict])}?')
        return 0, []
    else:
        logEntries.append(f'Initial vt path {valuePerTurnPath}')

    if GatherDebug.USE_DEBUG_ASSERTS:
        vis = set()
        for t in valuePerTurnPath.tileList:
            if t in vis:
                raise Exception(f'{t} was in path twice! Path {valuePerTurnPath}')
            vis.add(t)

    return valuePerTurnPath.value, [valuePerTurnPath]

#
# def _build_tree_node_lookup(
#         newPaths: typing.List[Path],
#         startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
#         searchingPlayer: int,
#         teams: typing.List[int],
#         # skipTiles: typing.Set[Tile],
#         shouldLog: bool = False,
#         priorityMatrix: MapMatrixInterface[float] | None = None,
# ) -> typing.Dict[Tile, GatherTreeNode]:
#     gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {}
#     return _extend_tree_node_lookup(
#         newPaths,
#         gatherTreeNodeLookup,
#         startTilesDict,
#         searchingPlayer,
#         teams,
#         set(),
#         [],
#         shouldLog=shouldLog,
#         force=True,
#         priorityMatrix=priorityMatrix,
#     )

#
# def _extend_tree_node_lookup(
#         newPaths: typing.List[Path],
#         gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
#         startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
#         searchingPlayer: int,
#         teams: typing.List[int],
#         negativeTiles: typing.Set[Tile],
#         logEntries: typing.List[str],
#         useTrueValueGathered: bool = False,
#         shouldLog: bool = False,
#         force: bool = False,
#         priorityMatrix: MapMatrixInterface[float] | None = None,
# ) -> typing.Dict[Tile, GatherTreeNode]:
#     """
#     Returns the remaining turns after adding the paths, and the new tree nodes list, and the new startingTileDict.
#     If a path in the list does not produce any army, returns None for remaining turns.
#     Sets trunkdistance.
#
#     @param force:
#     @param shouldLog:
#     @param startTilesDict:
#     @param newPaths:
#     @param negativeTiles:
#     @param gatherTreeNodeLookup:
#     @param searchingPlayer:
#     @param useTrueValueGathered:
#     @return:
#     """
#     distanceLookup: typing.Dict[Tile, int] = {}
#     for tile, (_, distance) in startTilesDict.items():
#         distanceLookup[tile] = distance
#
#     if GatherDebug.USE_DEBUG_ASSERTS:
#         for p in newPaths:
#             vis = set()
#             for t in p.tileList:
#                 if t in vis:
#                     raise Exception(f'{t} was in path twice! Path {p}')
#                 vis.add(t)
#
#     for valuePerTurnPath in newPaths:
#         if valuePerTurnPath.tail.tile.army <= 1 or valuePerTurnPath.tail.tile.player != searchingPlayer:
#             # THIS should never happen since we are supposed to nuke these already in the startTilesDict builder
#             logbook.error(
#                 f"TERMINATING extend_tree_node_lookup PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
#             continue
#
#         if shouldLog:
#             logbook.info(
#                 f"Adding valuePerTurnPath (v/t {(valuePerTurnPath.value - valuePerTurnPath.start.tile.army + 1) / valuePerTurnPath.length:.3f}): {valuePerTurnPath.toString()}")
#
#         # itr += 1
#         # add the new path to startTiles, rinse, and repeat
#         pathNode = valuePerTurnPath.start
#         # we need to factor in the distance that the last path was already at (say we're gathering to a threat,
#         # you can't keep adding gathers to the threat halfway point once you're gathering for as many turns as half the threat length
#         distance = distanceLookup[pathNode.tile]
#         # TODO? May need to not continue with the previous paths priorityObjects and instead start fresh, as this may unfairly weight branches
#         #       towards the initial max path, instead of the highest actual additional value
#         addlDist = 1
#
#         currentGatherTreeNode = gatherTreeNodeLookup.get(pathNode.tile, None)
#         if currentGatherTreeNode is None:
#             startTilesDictStringed = "\r\n      ".join([repr(t) for t in startTilesDict.items()])
#             gatherTreeNodeLookupStringed = "\r\n      ".join([repr(t) for t in gatherTreeNodeLookup.items()])
#             newPathsStringed = "\r\n      ".join([repr(t) for t in newPaths])
#             msg = (f'Should never get here with no root tree pathNode. pathNode.tile {str(pathNode.tile)} dist {distance} in path {str(valuePerTurnPath)}.\r\n'
#                    f'  Path was {repr(valuePerTurnPath)}\r\n'
#                    f'  startTiles was\r\n      {startTilesDictStringed}\r\n'
#                    f'  gatherTreeNodeLookup was\r\n      {gatherTreeNodeLookupStringed}\r\n'
#                    f'  newPaths was\r\n      {newPathsStringed}')
#
#             if not force:
#                 logbook.info('\r\n' + '\r\n'.join(logEntries))
#                 raise AssertionError(msg)
#
#             logbook.error(msg)
#
#             currentGatherTreeNode = GatherTreeNode(pathNode.tile, None, distance)
#             # currentGatherTreeNode.gatherTurns = 1
#             gatherTreeNodeLookup[pathNode.tile] = currentGatherTreeNode
#
#         gatherTreeNodePathAddingOnTo = currentGatherTreeNode
#         # runningValue = valuePerTurnPath.value - pathNode.tile.army
#         runningValue = valuePerTurnPath.value
#         runningTrunkDist = gatherTreeNodePathAddingOnTo.trunkDistance
#         runningTrunkValue = gatherTreeNodePathAddingOnTo.trunkValue
#         # if pathNode.tile.player == searchingPlayer:
#         #     runningValue -= pathNode.tile.army
#         # elif useTrueValueGathered:
#         #     runningValue += pathNode.tile.army
#         # skipTiles.add(pathNode.tile)
#         # skipping because first tile is actually already on the path
#         pathNode = pathNode.next
#         # add the new path to startTiles and then search a new path
#         iter = 0
#         while pathNode is not None:
#             # if DebugHelper.IS_DEBUGGING and pathNode.tile.x == 17 and pathNode.tile.y > 1 and pathNode.tile.y < 5:
#             #     pass
#             iter += 1
#             if iter > 600:
#                 logbook.info('\r\n' + '\r\n'.join(logEntries))
#                 raise AssertionError(f'Infinite looped in extend_tree_node_lookup, {str(pathNode)}')
#             runningTrunkDist += 1
#             newDist = distance + addlDist
#             distanceLookup[pathNode.tile] = newDist
#             # skipTiles.add(pathNode.tile)
#             # if viewInfo:
#             #    viewInfo.bottomRightGridText[pathNode.tile] = newDist
#             nextGatherTreeNode = GatherTreeNode(pathNode.tile, currentGatherTreeNode.tile, newDist)
#
#             tileEffect = 1
#
#             if negativeTiles is None or pathNode.tile not in negativeTiles:
#                 if teams[pathNode.tile.player] == teams[searchingPlayer]:
#                     tileEffect -= pathNode.tile.army
#                 elif useTrueValueGathered:
#                     tileEffect += pathNode.tile.army
#             # if priorityMatrix and pathNode.next is not None:
#             #     runningValue -= priorityMatrix[pathNode.tile]
#
#             runningTrunkValue -= tileEffect
#             if GatherDebug.USE_DEBUG_ASSERTS:
#                 logEntries.append(f'ETNL: setting {nextGatherTreeNode} value to {runningValue}')
#             nextGatherTreeNode.value = runningValue
#             nextGatherTreeNode.trunkValue = runningTrunkValue
#             nextGatherTreeNode.trunkDistance = runningTrunkDist
#             nextGatherTreeNode.gatherTurns = valuePerTurnPath.length - addlDist + 1
#             runningValue += tileEffect
#             if priorityMatrix:
#                 runningValue -= priorityMatrix[pathNode.tile]
#
#             if nextGatherTreeNode not in currentGatherTreeNode.children:
#                 currentGatherTreeNode.children.append(nextGatherTreeNode)
#                 prunedToRemove = None
#                 for p in currentGatherTreeNode.pruned:
#                     if p.tile == nextGatherTreeNode.tile:
#                         prunedToRemove = p
#                 if prunedToRemove is not None:
#                     currentGatherTreeNode.pruned.remove(prunedToRemove)
#             currentGatherTreeNode = nextGatherTreeNode
#             gatherTreeNodeLookup[pathNode.tile] = currentGatherTreeNode
#             addlDist += 1
#             pathNode = pathNode.next
#
#         # now bubble the value of the path and turns up the tree
#         curGatherTreeNode = gatherTreeNodePathAddingOnTo
#         iter = 0
#         while True:
#             iter += 1
#
#             curGatherTreeNode.value += valuePerTurnPath.value
#             curGatherTreeNode.gatherTurns += valuePerTurnPath.length
#             if curGatherTreeNode.toTile is None:
#                 break
#
#             nextGatherTreeNode = gatherTreeNodeLookup.get(curGatherTreeNode.toTile, None)
#             if nextGatherTreeNode is not None and nextGatherTreeNode.toTile == curGatherTreeNode.tile:
#                 errMsg = f'found graph cycle in extend_tree_node_lookup, {str(curGatherTreeNode)}<-{str(curGatherTreeNode.toTile)}  ({str(nextGatherTreeNode)}<-{str(nextGatherTreeNode.toTile)}) setting curGatherTreeNode fromTile to None to break the cycle.'
#                 logbook.error(errMsg)
#                 if GatherDebug.USE_DEBUG_ASSERTS:
#                     logbook.info('\r\n' + '\r\n'.join(logEntries))
#                     raise AssertionError(errMsg)
#
#                 curGatherTreeNode.toTile = None
#                 break
#
#             if iter > 600 and nextGatherTreeNode is not None:
#                 logbook.info('\r\n' + '\r\n'.join(logEntries))
#                 raise AssertionError(f'Infinite looped in extend_tree_node_lookup, {str(curGatherTreeNode)}<-{str(curGatherTreeNode.toTile)}  ({str(nextGatherTreeNode)}<-{str(nextGatherTreeNode.toTile)})')
#
#             if nextGatherTreeNode is None:
#                 startTilesDictStringed = "\r\n      ".join([repr(t) for t in startTilesDict.items()])
#                 gatherTreeNodeLookupStringed = "\r\n      ".join([repr(t) for t in gatherTreeNodeLookup.items()])
#                 newPathsStringed = "\r\n      ".join([repr(t) for t in newPaths])
#                 fromDist = distanceLookup.get(curGatherTreeNode.toTile, None)
#                 curDist = distanceLookup.get(curGatherTreeNode.tile, None)
#                 msg = (f'curGatherTreeNode {repr(curGatherTreeNode)} HAD A FROM TILE {repr(curGatherTreeNode.toTile)} fromDist [{fromDist}] curDist [{curDist}] THAT WAS NOT IN THE gatherTreeNodeLookup...?\r\n'
#                        f'  Path was {repr(valuePerTurnPath)}\r\n'
#                        f'  startTiles was\r\n      {startTilesDictStringed}\r\n'
#                        f'  gatherTreeNodeLookup was\r\n      {gatherTreeNodeLookupStringed}\r\n'
#                        f'  newPaths was\r\n      {newPathsStringed}')
#                 if not force:
#                     logbook.info('\r\n' + '\r\n'.join(logEntries))
#                     raise AssertionError(msg)
#                 else:
#                     logbook.error(msg)
#                 break
#             curGatherTreeNode = nextGatherTreeNode
#
#     return gatherTreeNodeLookup


def _build_next_level_start_dict_max_set(
        newPaths: typing.List[Path],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        remainingTurns: int,
        # skipTiles: typing.Set[Tile],
        baseCaseFunc,
) -> typing.Tuple[int | None, typing.Dict[Tile, typing.Tuple[typing.Any, int]]]:
    """
    Returns the remaining turns after adding the paths, and the new startingTileDict.
    If a path in the list produces a path that accomplishes nothing, returns None for remaining turns indicating that this search branch has exhausted useful paths.

    @param newPaths:
    @param searchingPlayer:
    # @param skipTiles:
    @return:
    """

    startTilesDict = startTilesDict.copy()
    hadInvalidPath = False

    for valuePerTurnPath in newPaths:
        if valuePerTurnPath.tail.tile.army <= 1 or valuePerTurnPath.tail.tile.player != searchingPlayer:
            logbook.info(
                f"TERMINATING build_next_level_start_dict PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
            # in theory this means you fucked up your value function; your value function should return none when the path under evaluation isn't even worth considering
            hadInvalidPath = True
            continue
        logbook.info(
            f"Adding valuePerTurnPath (v/t {(valuePerTurnPath.value - valuePerTurnPath.start.tile.army + 1) / valuePerTurnPath.length:.3f}): {valuePerTurnPath.toString()}")

        remainingTurns = remainingTurns - valuePerTurnPath.length
        # itr += 1
        # add the new path to startTiles, rinse, and repeat
        node = valuePerTurnPath.start
        # we need to factor in the distance that the last path was already at (say we're gathering to a threat,
        # you can't keep adding gathers to the threat halfway point once you're gathering for as many turns as half the threat length
        (startPriorityObject, distance) = startTilesDict[node.tile]
        # TODO? May need to not continue with the previous paths priorityObjects and instead start fresh, as this may unfairly weight branches
        #       towards the initial max path, instead of the highest actual additional value
        addlDist = 1

        # skipTiles.add(node.tile)
        # skipping because first tile is actually already on the path
        node = node.next
        # add the new path to startTiles and then search a new path
        while node is not None:
            newDist = distance + addlDist
            nextPrioObj = baseCaseFunc(node.tile, newDist)
            startTilesDict[node.tile] = (nextPrioObj, newDist)
            # skipTiles.add(node.tile)
            # logbook.info(
            #     f"Including tile {node.tile.x},{node.tile.y} in startTilesDict at newDist {newDist}  (distance {distance} addlDist {addlDist})")
            # if viewInfo:

            addlDist += 1
            node = node.next

    if hadInvalidPath:
        remainingTurns = None

    return remainingTurns, startTilesDict


def _knapsack_max_set_gather_iterative_prune(
        itr: SearchUtils.Counter,
        map: MapBase,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        cutoffTime: float,
        rewardMatrix: MapMatrixInterface[float],
        armyCostMatrix: MapMatrixInterface[float],
        # gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        remainingTurns: int,
        fullTurns: int,
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        pathValueFunc=None,
        # negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        perIterationFunc: typing.Callable[[typing.Dict[Tile, typing.Tuple[typing.Any, int]]], None] | None = None,
        incrementBackward=True,
        preferNeutral=False,
        viewInfo=None,
        logEntries: typing.List[str] | None = None,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog: bool = False,
        fastMode: bool = False,
        slowMode: bool = False,
        renderLive: bool = True,
) -> typing.Tuple[int, typing.Set[Tile]]:
    """

    @param itr:
    @param map:
    @param startTilesDict:
    @param remainingTurns:
    @param fullTurns:
    @param targetArmy:
    @param valueFunc:
    @param baseCaseFunc:
    # @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc:
    @param skipFunc:
    @param incrementBackward:
    @param preferNeutral:
    @param viewInfo:
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @param fastMode: run much faster, but less accurate version of the algo.
    @param slowMode: run much slower, but in theory more accurate version of the algo?

    @return: (valGathered, rootNodes)
    """
    origStartTilesDict = startTilesDict.copy()
    rootTiles = {t for t in startTilesDict.keys()}

    pruneReconnectCountMatrix = MapMatrix(map, 0)

    liveRenderer = None
    if renderLive:
        liveRenderer = ViewerProcessHost.start_debug_live_renderer(map, startPaused=True)

    maxPerIteration = max(min(4, fullTurns // 2), 1 * fullTurns // 2 - 1)
    if fastMode:
        maxPerIteration = max(min(7, 3 * fullTurns // 5 - 1), 1 * fullTurns // 2)
    # if slowMode:
    #     maxPerIteration = 2

    teams = MapBase.get_teams_array(map)

    standardMode = not fastMode and not slowMode

    turnsSoFar = 0
    totalValue = 0
    newStartTilesDict = startTilesDict.copy()

    prevBest = 0

    lastPrunedTo = 0

    if logEntries is None:
        logEntries = []

    startTime = time.perf_counter()

    prunedSet: typing.Set[Tile] = set()

    bestSet = None
    bestVal = -10000
    bestStart = newStartTilesDict
    bestTurns = 1

    try:
        while lastPrunedTo < fullTurns:
            itr.add(1)
            turnsToGather = fullTurns - turnsSoFar
            logEntries.append(f'Sub Knap (iter {itr.value} {1000.0 * (time.perf_counter() - startTime):.1f}ms in) turns {turnsToGather} sub_knapsack, fullTurns {fullTurns}, turnsSoFar {turnsSoFar}')
            if shouldLog:
                logEntries.append(f'start tiles: {str(newStartTilesDict)}')

            if perIterationFunc is not None:
                perIterationFunc(newStartTilesDict)

            forest = FastDisjointTileSetMultiSum([rewardMatrix, armyCostMatrix])
            for tile, data in newStartTilesDict.items():
                for mv in tile.movable:
                    if mv in newStartTilesDict:
                        forest.merge(tile, mv)

            if liveRenderer:
                liveRenderer.view_info.add_stats_line(f'LIGHT BLUE = {len(newStartTilesDict)} iter start tiles')
                liveRenderer.view_info.add_map_zone(newStartTilesDict.copy(), Colors.LIGHT_BLUE, alpha=150)

            newGatheredArmy, newPaths = _get_sub_knapsack_max_set_gather(
                map,
                newStartTilesDict,
                valueFunc,
                pathValueFunc,
                remainingTurns=turnsToGather,
                fullTurns=fullTurns,
                # negativeTiles=negativeTiles,
                skipTiles=skipTiles,
                searchingPlayer=searchingPlayer,
                priorityFunc=priorityFunc,
                skipFunc=skipFunc,
                ignoreStartTile=True,
                incrementBackward=incrementBackward,
                preferNeutral=preferNeutral,
                # priorityMatrix=priorityMatrix,
                shouldLog=shouldLog,
                # useTrueValueGathered=useTrueValueGathered,
                logEntries=logEntries
            )

            if len(newPaths) == 0:
                logEntries.append('no new paths found, breaking knapsack stuff')
                break  # gatherTreeNodeLookup[map.GetTile(15,9)].children[0] == gatherTreeNodeLookup[map.GetTile(16,9)]
            # elif DebugHelper.IS_DEBUGGING:
            #     logEntries.append(f'  returned:')
            #     logEntries.extend([f'\r\n    {p}' for p in newPaths])

            turnsUsedByNewPaths = 0
            for path in newPaths:
                turnsUsedByNewPaths += path.length

            calculatedLeftOverTurns = remainingTurns - turnsUsedByNewPaths

            for path in newPaths:
                last = path.tileList[0]
                for tile in path.tileList[1:]:
                    forest.merge(tile, last)
                    newStartTilesDict[tile] = (baseCaseFunc(tile, 0), 0)

            if liveRenderer:
                for path in newPaths:
                    liveRenderer.view_info.color_path(
                        PathColorer(
                            path,
                            100, 255, 100,
                            alpha=200,
                        ),
                    )
                    liveRenderer.view_info.add_info_line(f' path {path}')

            # if calculatedLeftOverTurns < remainingTurns - 1:
            #     continue

            # if GatherDebug.USE_DEBUG_ASSERTS:
            #     # rootNodes = [gatherTreeNodeLookup[tile] for tile in origStartTilesDict]
            #     logEntries.append('doing recalc after adding to start dict')
            #
            #     recalcTotalTurns, recalcTotalValue = recalculate_tree_values(
            #         logEntries,
            #         rootNodes,
            #         negativeTiles,
            #         origStartTilesDict,
            #         searchingPlayer,
            #         teams,
            #         onlyCalculateFriendlyArmy=not useTrueValueGathered,
            #         priorityMatrix=priorityMatrix,
            #         viewInfo=viewInfo,
            #         shouldAssert=True)
            #
            #     if prevBest < recalcTotalValue:
            #         logEntries.append(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} > {prevBest}!')
            #     elif prevBest > 0 and prevBest > recalcTotalValue:
            #         logbook.info('\r\n' + '\r\n'.join(logEntries))
            #         raise AssertionError(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} WORSE than prev {prevBest}? This should be impossible.')
            #     # if recalcTotalValue != newGatheredArmy + valueSoFar:
            #     #     if not SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
            #     #         raise AssertionError(f'recalculated gather value {recalcTotalValue} didnt match algo output gather value {newGatheredArmy}')
            #     if recalcTotalTurns != turnsUsedByNewPaths + turnsSoFar:
            #         msg = f'recalc gather turns {recalcTotalTurns} didnt match algo turns turnsUsedByNewPaths {turnsUsedByNewPaths} + turnsSoFar {turnsSoFar}'
            #         if GatherDebug.USE_DEBUG_ASSERTS:
            #             # TODO figure this shit the fuck out, what the fuck
            #             logbook.info('\r\n' + '\r\n'.join(logEntries))
            #             raise AssertionError(msg)
            #         elif viewInfo:
            #             viewInfo.add_info_line(msg)

            totalTurns = turnsUsedByNewPaths + turnsSoFar

            if not liveRenderer:
                now = time.perf_counter()
                if now > cutoffTime:
                    if totalTurns == fullTurns or itr.value > 4:
                        logEntries.append(f'BREAKING GATHER ITER {itr.value} EARLY AFTER {now - startTime:.4f} WITH TURNS USED {totalTurns} (latest new paths added {turnsUsedByNewPaths})')
                        break
                    newMaxPer = maxPerIteration + 1
                    logEntries.append(f'LONG RUNNING GATHER ITER {itr.value} {now - startTime:.4f} SHIFTING maxPerIteration from {maxPerIteration} to {newMaxPer}')
                    maxPerIteration = newMaxPer
                    if totalTurns == fullTurns and itr.value > 2:
                        logEntries.append(f'BREAKING GATHER ITER {itr.value} EARLY AFTER {now - startTime:.4f} WITH TURNS USED {totalTurns} (latest new paths added {turnsUsedByNewPaths})')
                        break

            # keep only the maxPerIteration best from each gather level

            # if we're at the end of the gather, gather 1 level at a time for the last phase to make sure we dont miss any optimal branches.

            if itr.value > 1 and maxPerIteration > 1:
                if fastMode:
                    # maxPerIteration = min(3 * maxPerIteration // 4, nextTurnsLeft // 2 + 1)
                    maxPerIteration = 5 * maxPerIteration // 7 + 1
                elif not slowMode:
                    maxPerIteration = 3 * maxPerIteration // 5 + 1
                else:
                    maxPerIteration = 1

            wouldBeNextTurnsLeft = fullTurns - (lastPrunedTo + maxPerIteration)

            if maxPerIteration > 1:
                if standardMode:
                    maxItCutoff = maxPerIteration
                    if wouldBeNextTurnsLeft < maxItCutoff and standardMode:
                        newIter = max(1, maxPerIteration // 2)
                        logEntries.append(f'cutting back maxPerIteration from what it would be, {maxPerIteration}, to {newIter}, due to wouldBeNextTurnsLeft {wouldBeNextTurnsLeft} <= maxPerIteration {maxPerIteration}')
                        maxPerIteration = newIter
                        # pruneToTurns = lastPrunedTo + maxPerIteration
                else:
                    maxItCutoff = maxPerIteration // 2
                    if wouldBeNextTurnsLeft <= maxItCutoff:
                        newIter = maxPerIteration // 2 + 1
                        logEntries.append(f'FAST cutting back maxPerIteration from what it would be, {maxPerIteration}, to {newIter}, due to wouldBeNextTurnsLeft {wouldBeNextTurnsLeft} <= maxItCutoff {maxItCutoff}')
                        # maxPerIteration = max(1, maxPerIteration // 2)
                        maxPerIteration = newIter
                        # pruneToTurns = lastPrunedTo + maxPerIteration

            if maxPerIteration < 1:
                maxPerIteration = 1

            pruneToTurns = lastPrunedTo + maxPerIteration

            # if len(newPaths) > 1:
            # TODO try pruning to max VT here instead of constant turns...?
            ogTotalValue = totalValue + newGatheredArmy
            ogTotalTurns = totalTurns
            overpruneCutoff = max(pruneToTurns // 2, lastPrunedTo - maxPerIteration)
            # overpruneCutoff = pruneToTurns
            rootForestSubset, (gatherVal, armySum) = forest.subset_with_values(next(iter(rootTiles)))

            curTurns = len(rootForestSubset) - len(rootTiles)
            if totalTurns > 0:
                if bestVal < gatherVal:
                    bestVal = gatherVal
                    bestSet = rootForestSubset.copy()
                    bestStart = newStartTilesDict.copy()
                    bestTurns = curTurns

                if bestVal / bestTurns > gatherVal * 1.04 / curTurns:
                    msg = f'  -- overriding poor re-plan {gatherVal:.1f}/{len(rootForestSubset)} back to bestVal {bestVal:.1f}/{len(bestSet)}'
                    logEntries.append(msg)
                    if liveRenderer:
                        liveRenderer.view_info.add_info_line(msg)
                    newStartTilesDict = bestStart.copy()
                    rootForestSubset = bestSet.copy()

            if pruneToTurns == fullTurns:
                break

            totalTurns, totalValue, prunedSet = prune_set_to_turns_and_reconnect_with_values(
                map,
                rootTiles,
                rootForestSubset,
                turns=pruneToTurns,
                finalTargetTurns=fullTurns,
                searchingPlayer=searchingPlayer,
                valueMatrix=rewardMatrix,
                armyCostMatrix=armyCostMatrix,
                iteration=itr.value,
                viewInfo=viewInfo,
                noLog=not shouldLog and not GatherDebug.USE_DEBUG_ASSERTS,  # and not DebugHelper.IS_DEBUGGING
                # gatherTreeNodeLookupToPrune=gatherTreeNodeLookup,
                allowNegative=includeGatherTreeNodesThatGatherNegative,
                tileDictToPrune=newStartTilesDict,
                logEntries=logEntries,
                baseCaseFunc=baseCaseFunc,
                overpruneCutoff=overpruneCutoff,
                liveRenderer=liveRenderer,
                pruneReconnectCountMatrix=pruneReconnectCountMatrix,
                # This WAS here to update the start dist
                # parentPruneFunc=lambda t, prunedNode: _start_tiles_prune_helper(startTilesDict, t, prunedNode)
            )
            logEntries.append(
                f' pruned {ogTotalValue:.2f}v @ {ogTotalTurns}t to {totalValue:.2f}v @ {totalTurns}t (goal was {pruneToTurns}t, overpruneCut {overpruneCutoff}t, maxPerIteration {maxPerIteration}, allowNegative={includeGatherTreeNodesThatGatherNegative})')

            if liveRenderer:
                liveRenderer.view_info.add_stats_line(f'PURPLE = {len(prunedSet)} iteration final tiles')
                liveRenderer.view_info.add_map_zone(prunedSet.copy(), Colors.PURPLE, alpha=150)
                liveRenderer.view_info.add_map_zone(prunedSet.difference(newStartTilesDict.keys()), Colors.P_TEAL, alpha=200)
                liveRenderer.view_info.add_info_line(
                    f'i {itr.value} pruned {ogTotalValue:.2f}v @ {ogTotalTurns}t to {totalValue:.2f}v @ {totalTurns}t (goal was {pruneToTurns}t, overpruneCut {overpruneCutoff}t, maxPerIteration {maxPerIteration}, allowNegative={includeGatherTreeNodesThatGatherNegative})')
                # liveRenderer.view_info.bottomLeftGridText = liveValRenderMatrix.copy()
                # liveRenderer.view_info.topRightGridText = disconnectCounts.copy()
                liveRenderer.trigger_update(clearViewInfoAfter=True)
                # for t in map.get_all_tiles():
                #     existing = liveValRenderMatrix.raw[t.tile_index]
                #     if existing:
                #         existing = existing.lstrip('I')
                #         liveValRenderMatrix.raw[t.tile_index] = existing

            lastPrunedTo = pruneToTurns
            turnsSoFar = totalTurns

    finally:
        logbook.info('\n'.join(logEntries))

    return bestVal, bestSet


def prune_set_naive(
        rootTiles: typing.Set[Tile],
        toPrune: typing.Set[Tile],
        pruneTo: int,
        valueMatrix: MapMatrixInterface[float],
        pruneReconnectCountMatrix: MapMatrixInterface[int],
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        logEntries: typing.List[str] | None = None,
) -> typing.List[Tile]:
    start = time.perf_counter()
    pruned = []
    dcQueue = []
    #
    # mean = 0.0
    # stdDev = 0.2
    # randShuffles = np.random.normal(mean, stdDev, len(toPrune)).tolist()

    for i, tile in enumerate(toPrune):
        if tile in rootTiles:
            continue

        reconnectWeight = max(0.0, pruneReconnectCountMatrix.raw[tile.tile_index] - 1.5)
        # reconnectWeight *= reconnectWeight
        heapq.heappush(dcQueue, (valueMatrix.raw[tile.tile_index] + reconnectWeight, tile))
        # heapq.heappush(dcQueue, (valueMatrix.raw[tile.tile_index] + reconnectWeight + randShuffles[i], tile))

        # heapq.heappush(dcQueue, (valueMatrix.raw[tile.tile_index] + randShuffles[i], tile))
        # heapq.heappush(dcQueue, (valueMatrix.raw[tile.tile_index], tile))

    while len(toPrune) - len(rootTiles) > pruneTo and dcQueue:
        _, t = heapq.heappop(dcQueue)

        newPruned = _prune_connected_by_value(t, toPrune, valueMatrix, rootTiles, tileDictToPrune, dropSimilarOffset=0.1, logEntries=logEntries)
        for t in newPruned:
            # already done by the _prune_connected_by_value func..
            # toPrune.discard(t)
            # if tileDictToPrune:
            #     tileDictToPrune.pop(t, None)
            pruned.append(t)

    # if logEntries:
    #     logEntries.append(f'  naive pruned {len(pruned)} to {len(toPrune)} in {(time.perf_counter() - start) * 1000.0:.2f}ms')

    return pruned


def _heur_quick_prune_connected_set(toPrune: typing.Set[Tile], pruneTo: int, valueMatrix: MapMatrixInterface[float], rootTiles: typing.Set[Tile]) -> typing.List[Tile]:
    """
    Prunes a connected set by the worst obviously pruneable tiles down to some amount.

    @param toPrune:
    @param pruneTo:
    @param valueMatrix:
    @param rootTiles:
    @return:
    """

    def heur_prunable(tile: Tile) -> bool:
        mvInSet = [mv for mv in tile.movable if mv in toPrune]
        if len(mvInSet) == 1:
            return True
        if len(mvInSet) > 2:
            return False
        if len(mvInSet) == 2:
            for alt in mvInSet[0].movable:
                for mv in alt.movable:
                    if mv == tile:
                        continue
                    if mv in mvInSet[1].movable:
                        # they are part of a cube and this is a cube corner
                        return True
        return False

    pruned = []
    unprunable = set()
    q = []
    for t in toPrune:
        if t in rootTiles:
            continue
        heapq.heappush(q, (valueMatrix.raw[t.tile_index], t))

    while q and len(toPrune) > pruneTo:
        _, t = heapq.heappop(q)

        if heur_prunable(t):
            pruned.append(t)
            toPrune.discard(t)
            for mv in t.movable:
                if mv in unprunable:
                    unprunable.discard(mv)
                    heapq.heappush(q, (valueMatrix.raw[mv.tile_index], mv))
        else:
            unprunable.add(t)

    return pruned


def prune_set_by_articulation_points(
        map: MapBase,
        rootTiles: typing.Set[Tile],
        toPrune: typing.Set[Tile],
        pruneTo: int,
        valueMatrix: MapMatrixInterface[float],
        armyCostMatrix: MapMatrixInterface[float],
        pruneReconnectCountMatrix: MapMatrixInterface[int],  # Do not need, because this one is intelligent...?
        currentGathVal: float,
        currentArmySum: float,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None,
        logEntries: typing.List[str] | None = None
) -> typing.Tuple[float, float, typing.List[Tile]]:
    """
    Prunes based on the worst tile that isn't an articulation point.
    Returns (prunedGathVal, prunedArmySum, prunedNodes)

    @param rootTiles:
    @param toPrune:
    @param pruneTo:
    @param valueMatrix:
    @param armyCostMatrix:
    @param currentGathVal:
    @param currentArmySum:
    @return:
    """
    if pruneTo <= 0:
        pruned = [t for t in toPrune]
        toPrune.clear()
        return 0.0, 0.0, pruned

    ogLen = len(toPrune)

    pruned = []

    if ogLen <= pruneTo:
        return currentGathVal, currentArmySum, pruned

    start = time.perf_counter()
    dcQueue = []
    for tile in toPrune:
        if tile in rootTiles:
            continue

        heapq.heappush(dcQueue, (valueMatrix.raw[tile.tile_index], tile))

    unableToPrune = set()

    nxForBcc = Gather.build_networkX_graph_no_obstacles_no_weights(
        map,
        # skipTiles,
        validTiles=toPrune,
    )

    # pruned = []
    unsafeToCut = set()
    mustReEvaluateUnsafe = True
    articExecutions = 0

    while len(toPrune) > pruneTo and dcQueue:
        if mustReEvaluateUnsafe:
            unsafeToCut = {t for t in nx.algorithms.articulation_points(nxForBcc)}
            mustReEvaluateUnsafe = False
            articExecutions += 1

        _, t = heapq.heappop(dcQueue)

        if t.tile_index in unsafeToCut:
            unableToPrune.add(t)
            continue

        mustReEvaluateUnsafe = sum(1 for mv in t.movable if mv in toPrune) != 1
        # mustReEvaluateUnsafe = True

        # pruned = _prune_connected_by_value(t, toPrune, valueMatrix, rootTiles)
        toPrune.discard(t)
        nxForBcc.remove_node(t.tile_index)
        currentGathVal -= valueMatrix.raw[t.tile_index]
        currentArmySum -= armyCostMatrix.raw[t.tile_index]
        if tileDictToPrune:
            tileDictToPrune.pop(t, None)
        pruned.append(t)

        if len(dcQueue) < 2 or (mustReEvaluateUnsafe and len(toPrune) + 5 > pruneTo):
            # don't retry these until we're near the end at least, so we dont turn this into n^2 worst case
            for mightPruneNow in unableToPrune:
                heapq.heappush(dcQueue, (valueMatrix.raw[mightPruneNow.tile_index], mightPruneNow))
            unableToPrune.clear()
        elif not mustReEvaluateUnsafe:
            for mv in t.movable:
                if mv in unableToPrune:
                    unableToPrune.discard(mv)
                    heapq.heappush(dcQueue, (valueMatrix.raw[mv.tile_index], mv))

    if logEntries:
        dur = time.perf_counter() - start
        durPerPrune = dur / (ogLen - len(toPrune))
        logEntries.append(f'  articulation point prune pruned {ogLen - len(toPrune)}tiles/{articExecutions}execs ({ogLen} down to {len(toPrune)}) in {1000.0 * dur:.2f}ms, {1000.0 * durPerPrune:.2f}ms each - gathVal {currentGathVal:.2f}, armySum {currentArmySum:.2f}')

    return currentGathVal, currentArmySum, pruned


def prune_set_by_heuristic_articulation_points(
        map: MapBase,
        rootTiles: typing.Set[Tile],
        toPrune: typing.Set[Tile],
        pruneTo: int,
        valueMatrix: MapMatrixInterface[float],
        armyCostMatrix: MapMatrixInterface[float],
        pruneReconnectCountMatrix: MapMatrixInterface[int],  # Do not need, because this one is intelligent...?
        currentGathVal: float,
        currentArmySum: float,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None,
        logEntries: typing.List[str] | None = None
) -> typing.Tuple[float, float, typing.List[Tile]]:
    """
    Prunes based on a very basic method of finding a set of tiles that are probably articulation points and pruning them.
    (but does not find ALL articulation points; so may prune better tiles while worst articulation point tiles exist still,
    so dont use this all the way).
    Prunes based on the worst tile that is obviously not an articulation points.

    Returns (prunedGathVal, prunedArmySum, prunedNodes)

    @param rootTiles:
    @param toPrune:
    @param pruneTo:
    @param valueMatrix:
    @param armyCostMatrix:
    @param currentGathVal:
    @param currentArmySum:
    @return:
    """

    if pruneTo <= 0:
        pruned = [t for t in toPrune]
        toPrune.clear()
        return 0.0, 0.0, pruned

    ogLen = len(toPrune)

    pruned = []

    if ogLen <= pruneTo:
        return currentGathVal, currentArmySum, pruned

    quickPruneTo = pruneTo
    start = time.perf_counter()
    startGath = currentGathVal
    startArmy = currentArmySum
    pruned = _heur_quick_prune_connected_set(toPrune, quickPruneTo, valueMatrix, rootTiles)
    for t in pruned:
        currentGathVal -= valueMatrix.raw[t.tile_index]
        currentArmySum -= armyCostMatrix.raw[t.tile_index]
        if tileDictToPrune:
            tileDictToPrune.pop(t, None)
        toPrune.discard(t)

    quickPruneCount = len(pruned)
    if logEntries:
        dur = time.perf_counter() - start
        if len(pruned) == 0:
            durPerPrune = float('inf')
        else:
            durPerPrune = dur / (ogLen - len(toPrune))
        logEntries.append(f'  artic heur QUICK pruned {quickPruneCount} ({ogLen} down to {len(toPrune)}) in {1000.0 * dur:.2f}ms, {1000.0 * durPerPrune:.2f}ms each - gathVal {startGath:.2f}->{currentGathVal:.2f}, armySum {startArmy:.2f}->{currentArmySum:.2f}')

    return currentGathVal, currentArmySum, pruned


def _prune_connected_by_value(
        node: Tile,
        setToPrune: typing.Set[Tile],
        valueMatrix: MapMatrixInterface[float],
        # disconnectCounts: MapMatrixInterface[int],
        rootTiles: typing.Set[Tile],
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None,
        dropSimilarOffset: float = 0.0,
        logEntries: typing.List[str] | None = None,
) -> typing.List[Tile]:
    """
    prunes connected with value equal to or lower than

    @param node:
    @param setToPrune:
    @param valueMatrix:
    @return:
    """
    cutoff = valueMatrix.raw[node.tile_index] + dropSimilarOffset
    q = [(node, cutoff)]

    pruned = []

    while q:
        tile, fromVal = q.pop()

        curVal = valueMatrix.raw[tile.tile_index]
        if tile not in setToPrune or curVal > cutoff or curVal > fromVal + dropSimilarOffset:
            continue

        # if logEntries:
        #     logEntries.append(f'  addl prune {tile}, (curVal {curVal:.1f} vs cutoff {cutoff:.1f} vs fromVal {fromVal:.1f}) {len(pruned)} pruned so far')

        pruned.append(tile)
        setToPrune.discard(tile)
        if tileDictToPrune:
            tileDictToPrune.pop(tile, None)
        # disconnectCounts.raw[tile.tile_index] += 1

        for movable in tile.movable:
            if movable not in setToPrune or movable in rootTiles:
                continue

            q.append((movable, curVal))

    return pruned


def prune_set_to_turns_and_reconnect_with_values(
        map: MapBase,
        rootTiles: typing.Set[Tile],
        toPrune: typing.Set[Tile],
        turns: int,
        finalTargetTurns: int,
        searchingPlayer: int,
        valueMatrix: MapMatrixInterface[float],
        armyCostMatrix: MapMatrixInterface[float],
        pruneReconnectCountMatrix: MapMatrixInterface[int],
        iteration: int,
        skipTiles: TileSet | None = None,
        baseCaseFunc: typing.Callable[[Tile, int], typing.Tuple] | None = None,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
        allowNegative: bool = True,
        overpruneCutoff: int | None = None,
        logEntries: typing.List[str] | None = None,
        liveRenderer: DebugLiveViewerHost | None = None,
) -> typing.Tuple[int, float, typing.Set[Tile]]:  # FastDisjointTileSetMultiSum
    """
    Prunes bad nodes from a set, and then rejoins them.

    @param rootTiles: the set of tiles that cannot be pruned.
    @param toPrune: The set to prune, and then reconnect (?)
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """

    desiredTotalNodes = turns + len(rootTiles)

    # pruneDiff = len(toPrune) - len(rootTiles) - turns
    # numToPruneNaive = int(pruneDiff * 1.5)
    # prune_set_naive(rootTiles, toPrune, numToPruneNaive, valueMatrix)

    # rawArmy = 0
    # gathVal = 0
    # for t in toPrune:
    #     rawArmy += armyCostMatrix.raw[t.tile_index]
    #     gathVal += valueMatrix.raw[t.tile_index]
    someRoot = next(iter(rootTiles))

    # over prune the set naively, before we reconnect it. TODO adjust the overprune amount...?
    # naiveTargetTurns = overpruneCutoff - random.randint(-2, 5)
    naiveTargetTurns = overpruneCutoff - 5
    prunedTiles = prune_set_naive(rootTiles, toPrune, naiveTargetTurns, valueMatrix, pruneReconnectCountMatrix, tileDictToPrune, logEntries)
    if liveRenderer:
        liveRenderer.view_info.add_stats_line(f'O - ORANGE = {len(prunedTiles)} naive pruned ({len(toPrune)} remaining, tg {naiveTargetTurns})')
        for t in prunedTiles:
            liveRenderer.view_info.add_targeted_tile(t, TargetStyle.ORANGE, radiusReduction=12)

    reconnectTargetTurns = desiredTotalNodes
    if desiredTotalNodes / finalTargetTurns > 0.92 and iteration & 1 == 0:  #
        # very good outputs, poor runtime
        gathVal, rawArmy, reconnectedSubset = _reconnect_steiner_subprune(
            map,
            someRoot,
            rootTiles,
            toPrune,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            skipTiles,
            reconnectTargetTurns,
            overpruneCutoff,
            baseCaseFunc,
            tileDictToPrune,
            liveRenderer)
        logEntries.append(f'   steiner {len(reconnectedSubset)}')
    elif desiredTotalNodes / finalTargetTurns > 0.85 and iteration & 2 != 0:  #  and iteration & 2 != 0
        gathVal, rawArmy, reconnectedSubset = _reconnect_dynamic_find_forest(
            map,
            someRoot,
            rootTiles,
            toPrune,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            skipTiles,
            finalTargetTurns,  # reconnectTargetTurns,
            overpruneCutoff,
            baseCaseFunc,
            tileDictToPrune,
            liveRenderer)
        logEntries.append(f'   dynamic forest {len(reconnectedSubset)}')

    else:
        # poor outputs, ish?
        gathVal, rawArmy, reconnectedSubset = _reconnect_fast_pcst(
            map,
            someRoot,
            rootTiles,
            toPrune,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            skipTiles,
            reconnectTargetTurns,
            overpruneCutoff,
            baseCaseFunc,
            tileDictToPrune,
            liveRenderer)
        logEntries.append(f'   pcst {len(reconnectedSubset)}')

    qpTurns = desiredTotalNodes + 6
    gathVal, rawArmy, qpArticTiles = prune_set_by_heuristic_articulation_points(
        map,
        rootTiles,
        reconnectedSubset,
        qpTurns,
        valueMatrix,
        armyCostMatrix,
        pruneReconnectCountMatrix,
        gathVal,
        rawArmy,
        tileDictToPrune,
        logEntries)

    if liveRenderer:
        liveRenderer.view_info.add_stats_line(f'O - TEAL = {len(qpArticTiles)} HEUR artic pruned ({len(reconnectedSubset)} returned, tg {qpTurns})')
        for t in qpArticTiles:
            liveRenderer.view_info.add_targeted_tile(t, TargetStyle.TEAL, radiusReduction=14)

    articPruneTargetTurns = desiredTotalNodes
    finalGathVal, finalRawArmy, prunedArticTiles = prune_set_by_articulation_points(
        map,
        rootTiles,
        reconnectedSubset,
        articPruneTargetTurns,
        valueMatrix,
        armyCostMatrix,
        pruneReconnectCountMatrix,
        gathVal,
        rawArmy,
        tileDictToPrune,
        logEntries)
    # for t in prunedArticTiles:
    #     forest.unsafe_delete

    if liveRenderer:
        liveRenderer.view_info.add_stats_line(f'O - RED = {len(prunedArticTiles)} artic pruned ({len(reconnectedSubset)} returned, tg {articPruneTargetTurns})')
        for t in prunedArticTiles:
            liveRenderer.view_info.add_targeted_tile(t, TargetStyle.RED, radiusReduction=10)

    return len(reconnectedSubset) - len(rootTiles), finalGathVal, reconnectedSubset


def _reconnect_steiner_subprune(
        map,
        someRoot,
        rootTiles,
        toReconnect,
        valueMatrix,
        armyCostMatrix,
        pruneReconnectCountMatrix,
        skipTiles,
        reconnectTargetTurns,
        overpruneCutoff,
        baseCaseFunc,
        tileDictToPrune,
        liveRenderer
) -> typing.Tuple[float, float, typing.Set[Tile]]:
    """
    Reconnects a partially disconnected set and returns the valueSum / armySum of the reconnected set.

    @param map:
    @param someRoot:
    @param rootTiles:
    @param toReconnect:
    @param valueMatrix:
    @param armyCostMatrix:
    @param pruneReconnectCountMatrix:
    @param skipTiles:
    @param reconnectTargetTurns:
    @param overpruneCutoff:
    @param baseCaseFunc:
    @param tileDictToPrune:
    @param liveRenderer:
    @return:
    """
    # steinerGraph = NetworkXHelpers.build_networkX_graph_flat_weight_mod_subtract(
    #     map, valueMatrix, baseWeight=1000, bannedTiles=skipTiles
    # )
    steinerGraph = NetworkXHelpers.build_networkX_graph_flat_weight_mod_scale(
        map, valueMatrix, bannedTiles=skipTiles
    )
    reconnectedSubset = GatherSteiner.build_network_x_steiner_tree_from_arbitrary_nx_graph(map, steinerGraph, requiredTiles=toReconnect)
    reconnectionTiles = []
    gathVal = 0
    rawArmy = 0
    tileDictToPrune.clear()
    for t in reconnectedSubset:
        if t not in toReconnect:
            reconnectionTiles.append(t)
        gathVal += valueMatrix.raw[t.tile_index]
        rawArmy += armyCostMatrix.raw[t.tile_index]
        tileDictToPrune[t] = (baseCaseFunc(t, 0), 0)

    #
    # reconnectionTiles, forest = _reconnect_iterative_heuristic(
    #     map,
    #     reconnectTargetTurns,
    #     partiallyDisconnectedSetToModify=toReconnect,
    #     rootTiles=rootTiles,
    #     valueMatrix=valueMatrix,
    #     armyCostMatrix=armyCostMatrix,
    #     skipTiles=skipTiles,
    #     bareMinTurns=overpruneCutoff,  # TODO
    #     doNotAllowExtraTurns=False,
    #     liveRenderer=liveRenderer,
    # )
    # reconnectedSubset, (gathVal, rawArmy) = forest.subset_with_values(next(iter(rootTiles)))

    if liveRenderer:
        liveRenderer.view_info.add_stats_line(f'O - PURPLE = {len(reconnectionTiles)} +stein rec ({len(reconnectedSubset)} total, min {overpruneCutoff}, tg {reconnectTargetTurns})')
        for t in reconnectionTiles:
            liveRenderer.view_info.add_targeted_tile(t, TargetStyle.PURPLE, radiusReduction=6)

    for tile in reconnectionTiles:
        pruneReconnectCountMatrix.raw[tile.tile_index] += 1

    return gathVal, rawArmy, reconnectedSubset


def _reconnect_fast_pcst(
        map,
        someRoot,
        rootTiles,
        toReconnect,
        valueMatrix,
        armyCostMatrix,
        pruneReconnectCountMatrix,
        skipTiles,
        reconnectTargetTurns,
        overpruneCutoff,
        baseCaseFunc,
        tileDictToPrune,
        liveRenderer
) -> typing.Tuple[float, float, typing.Set[Tile]]:
    """
    Reconnects a partially disconnected set and returns the valueSum / armySum of the reconnected set.

    @param map:
    @param someRoot:
    @param rootTiles:
    @param toReconnect:
    @param valueMatrix:
    @param armyCostMatrix:
    @param pruneReconnectCountMatrix:
    @param skipTiles:
    @param reconnectTargetTurns:
    @param overpruneCutoff:
    @param baseCaseFunc:
    @param tileDictToPrune:
    @param liveRenderer:
    @return:
    """
    reconnectedSubset = GatherSteiner.get_prize_collecting_gather_mapmatrix_single_iteration(
        map,
        valueMatrix,
        map.player_index,
        rootTiles=rootTiles,
        mustInclude=toReconnect,
        negativeTiles=None,
        skipTiles=skipTiles,
    )

    reconnectionTiles = []

    gathVal = 0
    rawArmy = 0
    tileDictToPrune.clear()
    for t in reconnectedSubset:
        if t not in toReconnect:
            reconnectionTiles.append(t)
        gathVal += valueMatrix.raw[t.tile_index]
        rawArmy += armyCostMatrix.raw[t.tile_index]
        tileDictToPrune[t] = (baseCaseFunc(t, 0), 0)

    #
    # reconnectionTiles, forest = _reconnect_iterative_heuristic(
    #     map,
    #     reconnectTargetTurns,
    #     partiallyDisconnectedSetToModify=toReconnect,
    #     rootTiles=rootTiles,
    #     valueMatrix=valueMatrix,
    #     armyCostMatrix=armyCostMatrix,
    #     skipTiles=skipTiles,
    #     bareMinTurns=overpruneCutoff,  # TODO
    #     doNotAllowExtraTurns=False,
    #     liveRenderer=liveRenderer,
    # )
    # reconnectedSubset, (gathVal, rawArmy) = forest.subset_with_values(next(iter(rootTiles)))

    if liveRenderer:
        liveRenderer.view_info.add_stats_line(f'O - PURPLE = {len(reconnectionTiles)} +stein rec ({len(reconnectedSubset)} total, min {overpruneCutoff}, tg {reconnectTargetTurns})')
        for t in reconnectionTiles:
            liveRenderer.view_info.add_targeted_tile(t, TargetStyle.PURPLE, radiusReduction=6)

    for tile in reconnectionTiles:
        pruneReconnectCountMatrix.raw[tile.tile_index] += 1

    return gathVal, rawArmy, reconnectedSubset


def _reconnect_dynamic_find_forest(
        map,
        someRoot,
        rootTiles,
        toReconnect,
        valueMatrix,
        armyCostMatrix,
        pruneReconnectCountMatrix,
        skipTiles,
        reconnectTargetTurns,
        overpruneCutoff,
        baseCaseFunc,
        tileDictToPrune,
        liveRenderer
) -> typing.Tuple[float, float, typing.Set[Tile]]:
    """
    Reconnects a partially disconnected set and returns the valueSum / armySum of the reconnected set.

    @param map:
    @param someRoot:
    @param rootTiles:
    @param toReconnect:
    @param valueMatrix:
    @param armyCostMatrix:
    @param pruneReconnectCountMatrix:
    @param skipTiles:
    @param reconnectTargetTurns:
    @param overpruneCutoff:
    @param baseCaseFunc:
    @param tileDictToPrune:
    @param liveRenderer:
    @return:
    """
    reconnectionTiles, forest = _reconnect_iterative_heuristic(
        map,
        reconnectTargetTurns,
        partiallyDisconnectedSetToModify=toReconnect,
        rootTiles=rootTiles,
        valueMatrix=valueMatrix,
        armyCostMatrix=armyCostMatrix,
        skipTiles=skipTiles,
        bareMinTurns=overpruneCutoff,  # TODO
        doNotAllowExtraTurns=False,
        liveRenderer=liveRenderer,
    )
    reconnectedSubset, (gathVal, rawArmy) = forest.subset_with_values(next(iter(rootTiles)))
    if liveRenderer:
        liveRenderer.view_info.add_stats_line(f'O - PURPLE = {len(reconnectionTiles)} +reconn ({len(reconnectedSubset)} total, min {overpruneCutoff}, tg {reconnectTargetTurns})')
        for t in reconnectionTiles:
            liveRenderer.view_info.add_targeted_tile(t, TargetStyle.PURPLE, radiusReduction=6)
    if baseCaseFunc and tileDictToPrune:
        for tile in list(tileDictToPrune.keys()):
            if not forest.connected(tile, someRoot):
                tileDictToPrune.pop(tile, None)

        for tile in reconnectionTiles:
            if forest.connected(someRoot, tile):
                tileDictToPrune[tile] = (baseCaseFunc(tile, 0), 0)
    for tile in reconnectionTiles:
        pruneReconnectCountMatrix.raw[tile.tile_index] += 1
    return gathVal, rawArmy, reconnectedSubset


# def _start_tiles_prune_helper(
#         startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
#         parentTile: Tile,
#         gatherNodeBeingPruned: GatherTreeNode
# ):
#     prioDistTuple = startTilesDict.get(parentTile, None)
#
#     if prioDistTuple is not None:
#         prios, oldDist = prioDistTuple
#         if GatherDebug.USE_DEBUG_LOGGING:
#             logbook.info(f'pruning {str(parentTile)} from {oldDist} to {oldDist - gatherNodeBeingPruned.gatherTurns} (pruned {str(gatherNodeBeingPruned.tile)} gatherTurns {gatherNodeBeingPruned.gatherTurns})')
#         startTilesDict[parentTile] = (prios, oldDist - gatherNodeBeingPruned.gatherTurns)

def _reconnect_iterative_heuristic(
        map: MapBase,
        pruneTo: int,
        partiallyDisconnectedSetToModify: typing.Set[Tile],
        rootTiles: typing.Set[Tile],
        # disconnectedCounts: MapMatrixInterface[int],
        skipTiles: TileSet | None,
        valueMatrix: MapMatrixInterface[float],
        armyCostMatrix: MapMatrixInterface[float],
        bareMinTurns: int,
        doNotAllowExtraTurns: bool = False,
        liveRenderer: DebugLiveViewerHost | None = None,
        # costPer: typing.Dict[Tile, int]
        logEntries: typing.List[str] | None = None,
) -> typing.Tuple[typing.Set[Tile], FastDisjointTileSetMultiSum]:
    """
    Returns the set of newly added tiles used to reconnect, and a forest with values (sumValueMatrix, sumArmyCost) that has been partially reconnected.

    @param map:
    @param pruneTo: limit the number of turns we can potentially use. This isn't guaranteed and may cause the gather to not connect all nodes or something?
    @param partiallyDisconnectedSetToModify: the (possibly disconnected) tiles currently have in the set, to begin reconnection from.
    @param skipTiles:
    @param rootTiles:
    @param valueMatrix: gather prio values.
    @return:
    """

    excessTurns = pruneTo - bareMinTurns

    start = time.perf_counter()
    if GatherDebug.USE_DEBUG_LOGGING and logEntries:
        logEntries.append('starting _reconnect')
    # includedSet = set()

    forest = FastDisjointTileSetMultiSum([valueMatrix, armyCostMatrix])

    # missingIncluded = curSet.copy()
    newTiles: typing.Set[Tile] = set()

    negativeTiles = None

    # if justDisconnectedTiles is None:
    #     justDisconnectedTiles = missingIncluded
    # else:
    #     # missingIncluded tiles shouldn't have a 'gather value', treat them as negative. Our goal is finding the best tiles in between all the included, not the highest value included connection point
    #     justDisconnectedTiles = justDisconnectedTiles.copy()
    #     justDisconnectedTiles.update(missingIncluded)

    # expectedMinRemaining = 0
    # for tile in missingIncluded:
    #     expectedMinRemaining += costPer.get(tile, 0)

    # logbook.info(f'bareMinTurns {bareMinTurns}, excessTurns {excessTurns}, expectedMinRemaining {expectedMinRemaining}')
    if logEntries:
        logEntries.append(f'bareMinTurns {bareMinTurns}, excessTurns {excessTurns}')

    # # skipTiles.difference_update(requiredTiles)
    # for req in requiredTiles:
    #     skipTiles.discard(req)

    # if len(requiredTiles) == 0:
    #     return includedSet, missingIncluded

    # usefulStartSet = {t: baseTuple for t in includedSet}
    usefulStartSet = dict()

    if GatherDebug.USE_DEBUG_LOGGING:
        logEntries.append('Completed sets setup')

    someRoot = None
    for root in rootTiles:
        someRoot = root

    for t in partiallyDisconnectedSetToModify:
        for adj in t.movable:
            if adj in partiallyDisconnectedSetToModify:
                if forest.merge(t, adj):
                    # these werent already connected
                    pass
    #
    # for t in rootTiles:
    #     val = forest.subset_value(t)
    #     usefulStartSet[t] = ((-1000000, 0, 0), 0)

    # def findFunc(t: Tile, prio: typing.Tuple) -> bool:
    #     (
    #         prio,
    #         dist,
    #         negGatherPoints,
    #         fromTile,
    #         originTile,
    #     ) = prio
    #     if t not in forest:
    #         return False
    #
    #     if forest.connected(t, originTile):
    #         return False
    #
    #     return True

    def findFunc(t: Tile, prio: typing.Tuple) -> bool:
        return t in forest and not forest.connected(t, someRoot)

    # def valueFunc(t: Tile, prio: typing.Tuple) -> typing.Tuple | None:
    #     if t not in forest:
    #         return None
    #
    #     (
    #         prio,
    #         dist,
    #         negGatherPoints,
    #         fromTile,
    #         originTile,
    #     ) = prio
    #
    #     if forest.connected(t, originTile):
    #         return None
    #
    #     missingVal = forest.subset_values(t)
    #     missingSize = forest.subset_size(t)
    #
    #     # negGatherPoints -= missingVal
    #     # if forest.connected(someRoot, t):
    #     #     negGatherPoints -= 2.0
    #     #     if negGatherPoints < 0:
    #     #         negGatherPoints *= 1.15
    #     #     else:
    #     #         negGatherPoints -= 1.0
    #
    #     return 0 - negGatherPoints, 0 - dist - missingSize

    iteration = 0
    # while len(missingIncluded) > 0:
    while forest.subset_size(someRoot) < pruneTo:
        # iter += 1
        if GatherDebug.USE_DEBUG_LOGGING and logEntries:
            logEntries.append(f'missingIncluded iter {iteration}')

        # expectedMinRemaining = 0
        # closestDist = pruneTo
        # closest = None
        # for tile in missingIncluded:
        #     # TODO
        #     # cost = costPer.get(tile, 0)
        #     cost = 1
        #     expectedMinRemaining += cost
        #     if 1 < cost < closestDist:
        #         closestDist = cost
        #         closest = tile
        #
        # costSoFar = len(includedSet)
        # excessTurnsLeft = pruneTo - (costSoFar + expectedMinRemaining)
        #
        # logbook.info(f'  costSoFar {costSoFar}, expectedMinRemaining {expectedMinRemaining} (out of max {pruneTo}, min {bareMinTurns}), closestDist {closestDist}, excessTurnsLeft {excessTurnsLeft}')

        excessTurnsLeft = pruneTo - forest.subset_size(someRoot)
        if GatherDebug.USE_DEBUG_LOGGING and logEntries:
            logEntries.append(f'  included so far {forest.subset_size(someRoot)} (missing {forest.n_subsets - 1} subsets), (out of max {pruneTo}, min {bareMinTurns}), excessTurnsLeft {excessTurnsLeft}')

        def prioFunc(tile: Tile, prioObj: typing.Tuple):
            (
                prio,
                dist,
                negGatherPoints,
                fromTile,
                originTile,
            ) = prioObj
            # only necessary when doing max instead of greedy find first
            # if fromTile in forest and fromTile != originTile:
            #     # not allowed to path through other parts of the forest, valfunc should just connect the forest...
            #     return None

            # if tile not in justDisconnectedTiles:
            negGatherPoints -= valueMatrix.raw[tile.tile_index]

            # TODO ASTARIFY THIS?
            # newCost = dist + 1
            # costWeight = excessTurnsLeft - (dist + 1)
            # # tile.coords in [(8, 6)]
            # if costWeight > 0 and negGatherPoints < 0:
            #     excessCostRat = costWeight / excessTurnsLeft
            #     """Ratio of excess turns left over"""
            #     costDivisor = (0 - negGatherPoints) * excessCostRat
            #     newCost -= costWeight * excessCostRat  #- 1/costDivisor
            #     # newCost -= excessTurnsLeft * (1 / excessCostRat)

            # newDist = dist + 10 / (10 + disconnectedCounts.raw[tile.tile_index])
            newDist = dist + 1

            # dfs heur
            newPrio = negGatherPoints / newDist if negGatherPoints < 0 else negGatherPoints * newDist

            #bfs
            newPrio = newDist + negGatherPoints / newDist

            if tile in forest:
                newPrio -= 100

            return (
                newPrio,
                newDist,
                negGatherPoints,
                tile,
                originTile,
            )

        # # naive start
        usefulStartSet = dict()
        for t in partiallyDisconnectedSetToModify:
            if forest.connected(t, someRoot):
                usefulStartSet[t] = ((-10000, 0, 0, None, t), 0)

        # usefulStartSet = dict()
        # for t in partiallyDisconnectedSetToModify:
        #     if not forest.connected(t, someRoot):
        #         gathVal, armyVal = forest.subset_values(t)
        #         size = forest.subset_size(t)
        #         # usefulStartSet[t] = ((-10000, 0, 0, None, t), 0)
        #         usefulStartSet[t] = ((-gathVal / size, size - 1, -gathVal, None, t), 0)

        # # new tiles are always connected to root. saves us from having to modify the og set
        # for t in newTiles:
        #     usefulStartSet[t] = ((-10000, 0, 0, None, t), 0)

        path = SearchUtils.breadth_first_dynamic(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noLog=not GatherDebug.USE_DEBUG_LOGGING, noVal=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        # path = SearchUtils.breadth_first_dynamic_max(map, usefulStartSet, valueFunc, maxTurns=excessTurnsLeft, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noLog=not GatherDebug.USE_DEBUG_LOGGING)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
        if path is None:
            if GatherDebug.USE_DEBUG_LOGGING and logEntries:
                logEntries.append(f'  Path NONE! Performing altBanned set')
            # altBanned = skipTiles.copy()
            # altBanned.update([t for t in map.reachableTiles if t.isMountain])
            path = SearchUtils.breadth_first_dynamic(map, usefulStartSet, findFunc, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noNeutralCities=False, noLog=not GatherDebug.USE_DEBUG_LOGGING, noVal=True)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            # path = SearchUtils.breadth_first_dynamic_max(map, usefulStartSet, valueFunc, maxTurns=excessTurnsLeft, negativeTiles=negativeTiles, skipTiles=skipTiles, priorityFunc=prioFunc, noNeutralCities=False, noLog=not GatherDebug.USE_DEBUG_LOGGING)  # , prioFunc=lambda t: (ourGen.x - t.x)**2 + (ourGen.y - t.y)**2
            if path is None:
                if GatherDebug.USE_DEBUG_LOGGING and logEntries:
                    logEntries.append(f'  No AltPath, breaking early with {len(partiallyDisconnectedSetToModify) - forest.subset_size(someRoot)} left missing')
                break
                # raise AssertionError(f'No MST building path found...? \r\nFrom {includedSet} \r\nto {missingIncluded}')
            # else:
            #     if GatherDebug.USE_DEBUG_LOGGING and logEntries:
            #         logEntries.append(f'  AltPath len {path.length}')
        # else:
        #     if GatherDebug.USE_DEBUG_LOGGING and logEntries:
        #         logEntries.appendinfo(f'  Path len {path.length}')

        # logEntries.append(f'    found {path.start.tile}->{path.tail.tile} len {path.length} (closest {closest} len {closestDist}) {path}')
        if GatherDebug.USE_DEBUG_LOGGING and logEntries:
            logEntries.append(f'    found {path.start.tile}->{path.tail.tile} len {path.length}')

        # lastTile: Tile = someRoot

        if liveRenderer:
            liveRenderer.view_info.color_path(
                PathColorer(
                    path,
                    255, 255, 0,
                    alpha=180,
                    alphaDecreaseRate=0,
                    alphaMinimum=100,
                )
            )

        # first = path.tileList[0]
        last = path.tileList[-1]
        newTiles.update(path.tileList[1:-1])
        for tile in path.tileList:
            forest.merge(tile, last)

            # _include_all_adj_required_set_forest(tile, forest, newTiles, usefulStartSet, valueMatrix, last) # , lastTile
            # _include_all_adj_required_set_gather(tile, includedSet, newTiles, usefulStartSet, missingIncluded, valueMatrix) # , lastTile
            # lastTile = tile

        # for tile in path.tileList:
        #     usefulStartSet

    if GatherDebug.USE_DEBUG_LOGGING and logEntries:
        logEntries.append(f'_reconnect completed in {time.perf_counter() - start:.5f}s with {len(partiallyDisconnectedSetToModify) - forest.subset_size(someRoot)} missing after {iteration} path iterations')

    return newTiles, forest


def _debug_print_diff_between_start_dict_and_tree_nodes(
        gatherTreeNodes: typing.Dict[Tile, GatherTreeNode],
        startDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]]
):
    if len(gatherTreeNodes) != len(startDict):
        logbook.info(f'~~startDict: {len(startDict)}, vs GatherTreeNodes {len(gatherTreeNodes)}')
    else:
        logbook.info(f'startDict: {len(startDict)}, vs GatherTreeNodes {len(gatherTreeNodes)}')

    for tile, node in sorted(gatherTreeNodes.items()):
        if tile not in startDict:
            path = Path()
            curNode = node
            while curNode is not None:
                path.add_next(curNode.tile)
                curNode = gatherTreeNodes.get(curNode.toTile, None)
            logbook.info(f'  missing from startDict: {str(tile)}  ({str(node)}), path {str(path)}')

    for tile, val in sorted(startDict.items()):
        (prioThing, dist) = val
        if tile not in gatherTreeNodes:
            logbook.info(f'  missing from GatherTreeNodes: {str(tile)}  (dist {dist}, [{str(prioThing)}])')


def gather_max_set_iterative(
        map: MapBase,
        startTiles,
        turns: int,
        armyCostMatrix: MapMatrixInterface[int],
        valueMatrix: MapMatrixInterface[int],
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        priorityTiles=None,
        ignoreStartTile=True,
        incrementBackward=True,
        preferNeutral=False,
        viewInfo=None,
        distPriorityMap=None,
        includeGatherTreeNodesThatGatherNegative=False,
        cutoffTime: float | None = None,
        shouldLog=False,
        fastMode: bool = False
) -> typing.List[GatherTreeNode]:
    """
    Does black magic and shits out a spiderweb with numbers in it, sometimes the numbers are even right

    @param map:
    @param startTiles:
    startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile]
    @param turns:
    @param targetArmy:
    @param valueFunc:
    valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object
    @param baseCaseFunc:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc:
    priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted
    @param skipFunc:
    @param priorityTiles:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param viewInfo:
    @param distPriorityMap:
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @param fastMode: whether to use the fastMode (less optimal results but much quicker) iterative params.
    @return:
    """
    totalValue, usedTurns, rootNodes = gather_max_set_iterative_plan(
        map=map,
        startTiles=startTiles,
        armyCostMatrix=armyCostMatrix,
        valueMatrix=valueMatrix,
        turns=turns,
        targetArmy=targetArmy,
        valueFunc=valueFunc,
        baseCaseFunc=baseCaseFunc,
        # negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=skipFunc,
        priorityTiles=priorityTiles,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        viewInfo=viewInfo,
        distPriorityMap=distPriorityMap,
        # useTrueValueGathered=useTrueValueGathered,
        includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
        # priorityMatrix=priorityMatrix,
        cutoffTime=cutoffTime,
        shouldLog=shouldLog,
        fastMode=fastMode
    )

    return rootNodes


def gather_max_set_iterative_plan(
        map: MapBase,
        startTiles,
        turns: int,
        valueMatrix: MapMatrixInterface[float],
        armyCostMatrix: MapMatrixInterface[float],
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        pathValueFunc=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc: typing.Callable[[Tile, typing.Any], bool] | None = None,
        perIterationFunc: typing.Callable[[typing.Dict[Tile, typing.Tuple[typing.Any, int]]], None] | None = None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=True,
        preferNeutral=False,
        viewInfo: ViewInfo | None = None,
        distPriorityMap=None,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog=False,  # DebugHelper.IS_DEBUGGING
        cutoffTime: float | None = None,
        fastMode: bool = False,
        slowMode: bool = False,
        renderLive: bool = False,
) -> GatherCapturePlan:
    """
    Does black magic and shits out a spiderweb with numbers in it, sometimes the numbers are even right.
    The UseTrueValueGathered equivalent is simply the armyCostMatrix also passed in for the valueMatrix.
    valueMatrix is used to prioritize what to grab.
    armyCostMatrix is used to make sure the gather isn't invalid.

    @param map:
    @param startTiles:
    startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile], OR dict distance = startTiles[tile] (which will be converted to (startPriorityObject, distance) by baseCaseFunc)
    @param turns:
    @param targetArmy:
    @param valueFunc:
    valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object
    @param baseCaseFunc:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc:
    priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted
    @param skipFunc:
    @param priorityTiles:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param viewInfo:
    @param distPriorityMap:
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @return: (valueGathered, rootNodes)
    """
    startTime = time.perf_counter()

    if cutoffTime is None:
        cutoffTime = time.perf_counter() + 500

    # negativeTilesOrig = set()
    # q = HeapQueue()

    # if isinstance(startTiles, dict):
    #    for tile in startTiles.keys():
    #        (startPriorityObject, distance) = startTiles[tile]

    #        startVal = startPriorityObject

    #        allowedDepth = turns - distance
    #        startTiles = {}
    #        startTiles[tile] = (startPriorityObject,

    # TODO break ties by maximum distance from threat (ideally, gathers from behind our gen are better
    #           than gathering stuff that may open up a better attack path in front of our gen)

    # TODO factor in cities, right now they're not even incrementing. need to factor them into the timing and calculate when they'll be moved.
    if searchingPlayer == -2:
        if isinstance(startTiles, dict):
            searchingPlayer = next(iter(startTiles.keys())).player
        else:
            searchingPlayer = next(iter(startTiles)).player

    logEntries = []

    friendlyPlayers = map.get_teammates(searchingPlayer)

    if shouldLog:
        logbook.info(f"Trying knapsack-max-iter-gather. Turns {turns}. Searching player {searchingPlayer}")
    if valueFunc is None:

        if shouldLog:
            logbook.info("Using emptyVal valueFunc")

        def default_value_func_max_set_gathered_per_turn(
                currentTile,
                priorityObject
        ):
            (
                prioVal,
                negPrioTilesPerTurn,
                realDist,  # realDist is
                negGatheredSum,
                negArmySum,
                # xSum,
                # ySum,
                numPrioTiles
            ) = priorityObject
            # existingPrio = priosByTile.get(key, None)
            # if existingPrio is None or existingPrio > priorityObject:
            #     priosByTile[key] = prioObj

            if negArmySum >= 0 and not includeGatherTreeNodesThatGatherNegative:
                return None
            if negGatheredSum >= 0:
                return None
            if currentTile.army < 2 or currentTile.player != searchingPlayer:
                return None

            val = -1000
            # this breaks if not max vt when the 'find big first boi' comes out
            if realDist > 0:
                # vt = value / realDist
                val = 0 - negGatheredSum

            valueObj = (val,  # most army
                        # then by the furthest 'distance' (which when gathering to a path, weights short paths to the top of the path higher which is important)
                        0 - negGatheredSum,  # then by maximum amount gathered...?
                        0 - negArmySum,
                        realDist,  # then by the real distance
                        # 0 - xSum,
                        # 0 - ySum
                        )
            if shouldLog:
                logEntries.append(f'VALUE {str(currentTile)} : {str(valueObj)}')
            return valueObj

        valueFunc = default_value_func_max_set_gathered_per_turn

    if pathValueFunc is None:
        if shouldLog:
            logbook.info("Using emptyVal pathValueFunc")

        def default_path_value_func(path, valueObj) -> float:
            (
                value,  # most army
                gatheredSum,  # then by maximum amount gathered...?
                armySum,
                realDist,  # then by the real distance
            ) = valueObj

            if shouldLog:
                logEntries.append(f"PATH VALUE {path}: {gatheredSum:.2f}")
            return gatheredSum

        pathValueFunc = default_path_value_func

    if priorityFunc is None:
        if shouldLog:
            logbook.info("Using emptyVal priorityFunc")

        def default_priority_func(nextTile: Tile, currentPriorityObject):
            (
                prioVal,
                negPrioTilesPerTurn,
                realDist,  # realDist is
                negGatheredSum,
                negArmySum,
                # xSum,
                # ySum,
                numPrioTiles
            ) = currentPriorityObject
            # if nextTile.x == 6 and nextTile.y == 2 and map.turn == 224:
            #     pass

            negArmySum -= armyCostMatrix.raw[nextTile.tile_index]
            negGatheredSum -= valueMatrix.raw[nextTile.tile_index]

            if priorityTiles and nextTile in priorityTiles:
                numPrioTiles += 1

            realDist += 1
            prioVal = -100000

            # max iterative dfs
            # if realDist > 0:
            #     prioVal = 10000 + negGatheredSum / realDist + 0.01 * (realDist * realDist)

            # bfs
            if realDist > 0:
                # prioVal = 10000 + negGatheredSum / realDist + 0.01 * (realDist * realDist)
                prioVal = realDist + negGatheredSum / realDist

            prioObj = (
                prioVal,
                numPrioTiles / max(1, realDist),
                realDist,
                negGatheredSum,
                negArmySum,
                # xSum + nextTile.x,
                # ySum + nextTile.y,
                numPrioTiles
            )
            if shouldLog or GatherDebug.USE_DEBUG_ASSERTS:
                logEntries.append(f'PRIO {str(nextTile)} : {str(prioObj)}')
            # logbook.info("prio: nextTile {} got realDist {}, negNextArmy {}, negDistanceSum {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
            return prioObj

        priorityFunc = default_priority_func

    if baseCaseFunc is None:
        if shouldLog:
            logbook.info("Using emptyVal baseCaseFunc")

        def default_base_case_func(tile, startingDist):
            # we would like to not gather to an enemy tile without killing it, so must factor it into the path. army value is negative for priority, so use positive for enemy army.
            # if useTrueValueGathered and tile.player != searchingPlayer:
            #     if shouldLog:
            #         logbook.info(
            #             f"tile {tile.toString()} was not owned by searchingPlayer {searchingPlayer}, adding its army {tile.army}")
            #     startArmy = tile.army

            armyNegSum = 0
            gathNegSum = 0

            # if useTrueValueGathered and tile.player not in friendlyPlayers:
            #     # TODO this seems wrong
            #     gathNegSum += tile.army
            #     armyNegSum += tile.army

            prioObj = (
                # starttiles always have max priority, must hever be revisited (or else we can pop paths that would pass through the start tiles again which screws everything.......?)
                -100000000000.0,
                0,  # prioTilesPerTurn
                0,  # realDist
                gathNegSum,  # gath neg
                armyNegSum,  # army neg
                0
            )
            if shouldLog or GatherDebug.USE_DEBUG_ASSERTS:
                logEntries.append(f"BASE CASE: {str(tile)} -> {str(prioObj)}")
            return prioObj

        baseCaseFunc = default_base_case_func

        # def default_per_iteration_func(preIterStartDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]]):
        #     priosByTile.clear()

        # perIterationFunc = default_per_iteration_func

    # TODO get rid of this somehow? it is used to prevent start tiles from counting towards shit?
    negativeTiles = set()

    startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]] = {}
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            if isinstance(startTiles[tile], int) or isinstance(startTiles[tile], float):
                distance = startTiles[tile]
                startTilesDict[tile] = (baseCaseFunc(tile, distance), distance)
            else:
                startTilesDict = startTiles

            negativeTiles.add(tile)
    else:
        for tile in startTiles:
            # then use baseCaseFunc to initialize their priorities, and set initial distance to 0
            startTilesDict[tile] = (baseCaseFunc(tile, 0), 0)
            negativeTiles.add(tile)

    if shouldLog:
        for tile, (startPriorityObject, distance) in startTilesDict.items():
            logEntries.append(f"Including tile {tile.x},{tile.y} in startTiles at distance {distance}")

    itr = SearchUtils.Counter(0)

    totalValue, gathSet = _knapsack_max_set_gather_iterative_prune(
        itr=itr,
        map=map,
        startTilesDict=startTilesDict,
        rewardMatrix=valueMatrix,
        armyCostMatrix=armyCostMatrix,
        cutoffTime=cutoffTime,
        # gatherTreeNodeLookup=gatherTreeNodeLookup,
        remainingTurns=turns,
        fullTurns=turns,
        targetArmy=targetArmy,
        valueFunc=valueFunc,
        baseCaseFunc=baseCaseFunc,
        pathValueFunc=pathValueFunc,
        # negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=skipFunc,
        perIterationFunc=perIterationFunc,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        viewInfo=viewInfo,
        # priorityMatrix=priorityMatrix,
        # useTrueValueGathered=useTrueValueGathered,
        includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
        logEntries=logEntries,
        shouldLog=shouldLog,
        fastMode=fastMode,
        slowMode=slowMode,
        renderLive=renderLive,
    )

    gcp: GatherCapturePlan | None = None

    if gathSet:
        rootTiles = {t for t in startTilesDict.keys()}

        gcp = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
            map,
            rootTiles,
            gathSet,
            searchingPlayer=searchingPlayer,
            priorityMatrix=valueMatrix,
            useTrueValueGathered=True,
            # valueMatrix=valueMatrix,  # TODO do econ value from value matrix, maybe? or something?
        )

        logbook.info(
            f"Concluded gather_max_set_iterative_with_values with {itr.value} iterations. Gather turns {gcp.length}, value {totalValue}. Duration: {time.perf_counter() - startTime:.4f}")
    else:
        logbook.info(
            f"Concluded gather_max_set_iterative_with_values with {itr.value} iterations. NO GCP FOUND! Duration: {time.perf_counter() - startTime:.4f}")
    return gcp
