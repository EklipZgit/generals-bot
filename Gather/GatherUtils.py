from __future__ import annotations

import random

import logbook
import time
import typing
from collections import deque

import DebugHelper
import KnapsackUtils
import SearchUtils
from Models import GatherTreeNode
from . import prune_mst_to_turns_with_values, GatherSteiner
from . import GatherCapturePlan
from . import USE_DEBUG_ASSERTS
from MapMatrix import MapMatrixInterface, MapMatrixSet, TileSet, MapMatrix
from Path import Path
from SearchUtils import where
from ViewInfo import ViewInfo
from base.client.map import Tile, MapBase


T = typing.TypeVar('T')


class TreeBuilder(typing.Generic[T]):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.tree_builder_prioritizer: typing.Callable[[Tile, T], T | None] = None
        self.tree_builder_valuator: typing.Callable[[Tile, T], typing.Any | None] = None
        """The value function when finding path extensions to the spanning tree"""

        self.tree_knapsacker_valuator: typing.Callable[[Path], int] = None
        """For getting the values of tree nodes to shove in the knapsack to build the subtree iteration"""

    def build_gather_capture_tree_from_tile_sets(
            self,
            gatherTiles: MapMatrixInterface[float | None],
            captureTiles: MapMatrixInterface[float | None],
            startTiles: typing.List[Tile] | None = None
    ) -> GatherCapturePlan:
        nodeMatrix = self.build_mst_gather_from_matrices(gatherTiles, captureTiles, startTiles)

    def build_mst_gather_from_matrices(
            self,
            gatherTiles: MapMatrixInterface[float | None],
            captureTiles: MapMatrixInterface[float | None],
            startTiles: typing.List[Tile]
    ) -> MapMatrixInterface[GatherTreeNode]:
        """
        Outputs
        @param gatherTiles:
        @param captureTiles:
        @param startTiles:
        @return:
        """

        # kay need to bi-directional BFS to gather all the nodes...
        nodeMatrix: MapMatrixInterface[GatherTreeNode] = MapMatrix(self.map)

        # build dumb gather mst
        frontier: SearchUtils.HeapQueue[typing.Tuple[int, Tile, GatherTreeNode | None, int, float, int]] = SearchUtils.HeapQueue()
        for tile in startTiles:
            frontier.put((0, tile, None, 0, 0, 0))

        dist: int
        curTile: Tile
        fromNode: GatherTreeNode | None
        negArmyGathered: int
        negPrioSum: float
        negRawArmy: int
        unk: typing.Any | None
        qq = frontier.queue
        while qq:
            (dist, nextTile, fromNode, negArmyGathered, negPrioSum, negRawArmy) = frontier.get()

            curNode = nodeMatrix[nextTile]
            if curNode:
                continue

            treeNode = GatherTreeNode(nextTile, fromNode.tile)
            if fromNode:
                fromNode.children.append(treeNode)

            for movable in nextTile.movable:
                if movable in gatherTiles and movable not in nodeMatrix:
                    frontier.put((dist + 1, movable, treeNode, negArmyGathered, negPrioSum, negRawArmy))

        return nodeMatrix

def knapsack_gather_iteration(
        turns: int,
        valuePerTurnPathPerTile: typing.Dict[Tile, typing.List[Path]],
        logList: typing.List[str] | None = None,
        valueFunc: typing.Callable[[Path], int] | None = None,
) -> typing.Tuple[int, typing.List[Path]]:
    if valueFunc is None:
        def value_func(path: Path) -> int:
            return int(path.value * 1000)

        valueFunc = value_func

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

    return totalValue, maxKnapsackedPaths


def get_sub_knapsack_gather(
        map,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        valueFunc,
        baseCaseFunc,
        pathValueFunc,
        maxTime: float,
        remainingTurns: int,
        fullTurns: int,
        # gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        noNeutralCities,
        negativeTiles,
        skipTiles,
        searchingPlayer,
        priorityFunc,
        skipFunc: typing.Callable[[Tile, typing.Any], bool] | None,
        ignoreStartTile,
        incrementBackward,
        preferNeutral,
        logEntries: typing.List[str],
        useTrueValueGathered: bool = False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
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

    if len(startTilesDict) < remainingTurns // 10:
        return get_single_line_iterative_starter(
            fullTurns,
            ignoreStartTile,
            incrementBackward,
            logEntries,
            map,
            negativeTiles,
            preferNeutral,
            priorityFunc,
            priorityMatrix,
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
        maxDepth=fullTurns,
        noNeutralCities=True,
        negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=subSkip,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        priorityMatrix=priorityMatrix,
        logResultValues=shouldLog,
        ignoreNonPlayerArmy=not useTrueValueGathered,
        ignoreIncrement=True,
        priorityMatrixSkipStart=True,
        pathValueFunc=pathValueFunc,
        noLog=not shouldLog  # note, these log entries end up AFTER all the real logs...
    )

    gatheredArmy, maxPaths = knapsack_gather_iteration(remainingTurns, valuePerTurnPathPerTilePerDistance, logList=logEntries if shouldLog else None)

    return int(round(gatheredArmy)), maxPaths


def get_single_line_iterative_starter(
        fullTurns,
        ignoreStartTile,
        incrementBackward,
        logEntries,
        map,
        negativeTiles,
        preferNeutral,
        priorityFunc,
        priorityMatrix,
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
        maxDepth=fullTurns,
        noNeutralCities=True,
        negativeTiles=negativeTiles,
        skipTiles=skipTiles,
        searchingPlayer=searchingPlayer,
        priorityFunc=priorityFunc,
        skipFunc=skipFunc,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        priorityMatrix=priorityMatrix,
        logResultValues=shouldLog,
        ignoreNonPlayerArmy=not useTrueValueGathered,
        noLog=not shouldLog,
        ignoreIncrement=True,
        pathValueFunc=pathValueFunc,
        priorityMatrixSkipStart=True)
    if valuePerTurnPath is None:
        logEntries.append(f'didnt find a max path searching to startTiles {"  ".join([str(tile) for tile in startTilesDict])}?')
        return 0, []
    return valuePerTurnPath.value, [valuePerTurnPath]


def build_tree_node_lookup(
        newPaths: typing.List[Path],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        teams: typing.List[int],
        # skipTiles: typing.Set[Tile],
        shouldLog: bool = False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
) -> typing.Dict[Tile, GatherTreeNode]:
    gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {}
    return extend_tree_node_lookup(
        newPaths,
        gatherTreeNodeLookup,
        startTilesDict,
        searchingPlayer,
        teams,
        set(),
        [],
        shouldLog=shouldLog,
        force=True,
        priorityMatrix=priorityMatrix,
    )


def extend_tree_node_lookup(
        newPaths: typing.List[Path],
        gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        teams: typing.List[int],
        negativeTiles: typing.Set[Tile],
        logEntries: typing.List[str],
        useTrueValueGathered: bool = False,
        shouldLog: bool = False,
        force: bool = False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
) -> typing.Dict[Tile, GatherTreeNode]:
    """
    Returns the remaining turns after adding the paths, and the new tree nodes list, and the new startingTileDict.
    If a path in the list does not produce any army, returns None for remaining turns.
    Sets trunkdistance.

    @param force:
    @param shouldLog:
    @param startTilesDict:
    @param newPaths:
    @param negativeTiles:
    @param gatherTreeNodeLookup:
    @param searchingPlayer:
    @param useTrueValueGathered:
    @return:
    """
    distanceLookup: typing.Dict[Tile, int] = {}
    for tile, (_, distance) in startTilesDict.items():
        distanceLookup[tile] = distance

    for valuePerTurnPath in newPaths:
        if valuePerTurnPath.tail.tile.army <= 1 or valuePerTurnPath.tail.tile.player != searchingPlayer:
            # THIS should never happen since we are supposed to nuke these already in the startTilesDict builder
            logbook.error(
                f"TERMINATING extend_tree_node_lookup PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
            continue

        if shouldLog:
            logbook.info(
                f"Adding valuePerTurnPath (v/t {(valuePerTurnPath.value - valuePerTurnPath.start.tile.army + 1) / valuePerTurnPath.length:.3f}): {valuePerTurnPath.toString()}")

        # itr += 1
        # add the new path to startTiles, rinse, and repeat
        pathNode = valuePerTurnPath.start
        # we need to factor in the distance that the last path was already at (say we're gathering to a threat,
        # you can't keep adding gathers to the threat halfway point once you're gathering for as many turns as half the threat length
        distance = distanceLookup[pathNode.tile]
        # TODO? May need to not continue with the previous paths priorityObjects and instead start fresh, as this may unfairly weight branches
        #       towards the initial max path, instead of the highest actual additional value
        addlDist = 1

        currentGatherTreeNode = gatherTreeNodeLookup.get(pathNode.tile, None)
        if currentGatherTreeNode is None:
            startTilesDictStringed = "\r\n      ".join([repr(t) for t in startTilesDict.items()])
            gatherTreeNodeLookupStringed = "\r\n      ".join([repr(t) for t in gatherTreeNodeLookup.items()])
            newPathsStringed = "\r\n      ".join([repr(t) for t in newPaths])
            msg = (f'Should never get here with no root tree pathNode. pathNode.tile {str(pathNode.tile)} dist {distance} in path {str(valuePerTurnPath)}.\r\n'
                   f'  Path was {repr(valuePerTurnPath)}\r\n'
                   f'  startTiles was\r\n      {startTilesDictStringed}\r\n'
                   f'  gatherTreeNodeLookup was\r\n      {gatherTreeNodeLookupStringed}\r\n'
                   f'  newPaths was\r\n      {newPathsStringed}')

            if not force:
                _dump_log_entries(logEntries)
                raise AssertionError(msg)

            logbook.error(msg)

            currentGatherTreeNode = GatherTreeNode(pathNode.tile, None, distance)
            # currentGatherTreeNode.gatherTurns = 1
            gatherTreeNodeLookup[pathNode.tile] = currentGatherTreeNode

        gatherTreeNodePathAddingOnTo = currentGatherTreeNode
        # runningValue = valuePerTurnPath.value - pathNode.tile.army
        runningValue = valuePerTurnPath.value
        runningTrunkDist = gatherTreeNodePathAddingOnTo.trunkDistance
        runningTrunkValue = gatherTreeNodePathAddingOnTo.trunkValue
        # if pathNode.tile.player == searchingPlayer:
        #     runningValue -= pathNode.tile.army
        # elif useTrueValueGathered:
        #     runningValue += pathNode.tile.army
        # skipTiles.add(pathNode.tile)
        # skipping because first tile is actually already on the path
        pathNode = pathNode.next
        # add the new path to startTiles and then search a new path
        iter = 0
        while pathNode is not None:
            # if DebugHelper.IS_DEBUGGING and pathNode.tile.x == 17 and pathNode.tile.y > 1 and pathNode.tile.y < 5:
            #     pass
            iter += 1
            if iter > 600:
                _dump_log_entries(logEntries)
                raise AssertionError(f'Infinite looped in extend_tree_node_lookup, {str(pathNode)}')
            runningTrunkDist += 1
            newDist = distance + addlDist
            distanceLookup[pathNode.tile] = newDist
            # skipTiles.add(pathNode.tile)
            # if viewInfo:
            #    viewInfo.bottomRightGridText[pathNode.tile] = newDist
            nextGatherTreeNode = GatherTreeNode(pathNode.tile, currentGatherTreeNode.tile, newDist)

            tileEffect = 1

            if negativeTiles is None or pathNode.tile not in negativeTiles:
                if teams[pathNode.tile.player] == teams[searchingPlayer]:
                    tileEffect -= pathNode.tile.army
                elif useTrueValueGathered:
                    tileEffect += pathNode.tile.army
            # if priorityMatrix and pathNode.next is not None:
            #     runningValue -= priorityMatrix[pathNode.tile]

            runningTrunkValue -= tileEffect
            if USE_DEBUG_ASSERTS:
                logEntries.append(f'ETNL: setting {nextGatherTreeNode} value to {runningValue}')
            nextGatherTreeNode.value = runningValue
            nextGatherTreeNode.trunkValue = runningTrunkValue
            nextGatherTreeNode.trunkDistance = runningTrunkDist
            nextGatherTreeNode.gatherTurns = valuePerTurnPath.length - addlDist + 1
            runningValue += tileEffect
            if priorityMatrix:
                runningValue -= priorityMatrix[pathNode.tile]

            if nextGatherTreeNode not in currentGatherTreeNode.children:
                currentGatherTreeNode.children.append(nextGatherTreeNode)
                prunedToRemove = None
                for p in currentGatherTreeNode.pruned:
                    if p.tile == nextGatherTreeNode.tile:
                        prunedToRemove = p
                if prunedToRemove is not None:
                    currentGatherTreeNode.pruned.remove(prunedToRemove)
            currentGatherTreeNode = nextGatherTreeNode
            gatherTreeNodeLookup[pathNode.tile] = currentGatherTreeNode
            addlDist += 1
            pathNode = pathNode.next

        # now bubble the value of the path and turns up the tree
        curGatherTreeNode = gatherTreeNodePathAddingOnTo
        iter = 0
        while True:
            iter += 1

            curGatherTreeNode.value += valuePerTurnPath.value
            curGatherTreeNode.gatherTurns += valuePerTurnPath.length
            if curGatherTreeNode.toTile is None:
                break

            nextGatherTreeNode = gatherTreeNodeLookup.get(curGatherTreeNode.toTile, None)
            if nextGatherTreeNode is not None and nextGatherTreeNode.toTile == curGatherTreeNode.tile:
                errMsg = f'found graph cycle in extend_tree_node_lookup, {str(curGatherTreeNode)}<-{str(curGatherTreeNode.toTile)}  ({str(nextGatherTreeNode)}<-{str(nextGatherTreeNode.toTile)}) setting curGatherTreeNode fromTile to None to break the cycle.'
                logbook.error(errMsg)
                if USE_DEBUG_ASSERTS:
                    _dump_log_entries(logEntries)
                    raise AssertionError(errMsg)

                curGatherTreeNode.toTile = None
                break

            if iter > 600 and nextGatherTreeNode is not None:
                _dump_log_entries(logEntries)
                raise AssertionError(f'Infinite looped in extend_tree_node_lookup, {str(curGatherTreeNode)}<-{str(curGatherTreeNode.toTile)}  ({str(nextGatherTreeNode)}<-{str(nextGatherTreeNode.toTile)})')

            if nextGatherTreeNode is None:
                startTilesDictStringed = "\r\n      ".join([repr(t) for t in startTilesDict.items()])
                gatherTreeNodeLookupStringed = "\r\n      ".join([repr(t) for t in gatherTreeNodeLookup.items()])
                newPathsStringed = "\r\n      ".join([repr(t) for t in newPaths])
                fromDist = distanceLookup.get(curGatherTreeNode.toTile, None)
                curDist = distanceLookup.get(curGatherTreeNode.tile, None)
                msg = (f'curGatherTreeNode {repr(curGatherTreeNode)} HAD A FROM TILE {repr(curGatherTreeNode.toTile)} fromDist [{fromDist}] curDist [{curDist}] THAT WAS NOT IN THE gatherTreeNodeLookup...?\r\n'
                       f'  Path was {repr(valuePerTurnPath)}\r\n'
                       f'  startTiles was\r\n      {startTilesDictStringed}\r\n'
                       f'  gatherTreeNodeLookup was\r\n      {gatherTreeNodeLookupStringed}\r\n'
                       f'  newPaths was\r\n      {newPathsStringed}')
                if not force:
                    _dump_log_entries(logEntries)
                    raise AssertionError(msg)
                else:
                    logbook.error(msg)
                break
            curGatherTreeNode = nextGatherTreeNode

    return gatherTreeNodeLookup


def build_next_level_start_dict(
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


def add_tree_nodes_to_start_tiles_dict_recurse(
        rootNode: GatherTreeNode,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        remainingTurns: int,
        # skipTiles: typing.Set[Tile],
        baseCaseFunc,
        dist: int = 0
) -> int:
    """
    Adds nodes recursively to the start tiles dict.
    DOES NOT make a copy of the start tiles dict.
    Returns the number of nodes that were extended on this node.

    @param rootNode:
    @param searchingPlayer:
    # @param skipTiles:
    @return:
    """

    added = 0

    startTilesEntry = startTilesDict.get(rootNode.tile, None)
    if startTilesEntry is None:
        nextPrioObj = baseCaseFunc(rootNode.tile, dist)
        startTilesDict[rootNode.tile] = (nextPrioObj, dist)
        added += 1

    for node in rootNode.children:
        added += add_tree_nodes_to_start_tiles_dict_recurse(node, startTilesDict, searchingPlayer, remainingTurns, baseCaseFunc, dist=dist + 1)
    #
    # if startTilesEntry is not None:
    #     (prioObj, oldDist) = startTilesEntry
    #     logbook.info(f'shifting {str(rootNode.tile)} from {oldDist} to {oldDist + added}')
    #     startTilesDict[rootNode.tile] = (prioObj, oldDist + added)

    return added


def _knapsack_levels_gather_recurse(
        itr: SearchUtils.Counter,
        map: MapBase,
        startTilesDict,
        # gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        remainingTurns: int,
        fullTurns: int,
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        pathValueFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        viewInfo=None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog=False
) -> typing.Tuple[int, typing.List[Path]]:
    """

    @param itr:
    @param map:
    @param startTilesDict:
    @param remainingTurns:
    @param fullTurns:
    @param targetArmy:
    @param valueFunc:
    @param baseCaseFunc:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc:
    @param skipFunc:
    @param priorityTiles:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param viewInfo:
    @param distPriorityMap:
    @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
     capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
     so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
     gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @return:
    """
    maxIterationGatheredArmy: int = -1
    maxIterationPaths: typing.List[Path] = []

    startTime = time.perf_counter()

    turnCombos = set()
    turnCombos.add(remainingTurns)
    if remainingTurns > 3:
        # turnCombos.add(2 * remainingTurns // 3)
        # turnCombos.add(remainingTurns // 3)
        turnCombos.add(remainingTurns // 2)
        # turnCombos.add(remainingTurns // 3)

    if remainingTurns > 10:
        turnCombos.add(3 * remainingTurns // 4)
        # turnCombos.add(remainingTurns // 4)
        # turnCombos.add(remainingTurns // 2)
        # turnCombos.add(remainingTurns // 3)

    for turnsToTry in turnCombos:
        if turnsToTry <= 0:
            continue

        logbook.info(f"Sub-knap ({time.perf_counter() - startTime:.4f} into search) looking for the next path with remainingTurns {turnsToTry} (fullTurns {fullTurns})")
        logEntries = []
        newGatheredArmy, newPaths = get_sub_knapsack_gather(
            map,
            startTilesDict,
            valueFunc,
            baseCaseFunc,
            pathValueFunc,
            0.1,
            remainingTurns=turnsToTry,
            fullTurns=fullTurns,
            noNeutralCities=True,
            negativeTiles=negativeTiles,
            skipTiles=skipTiles,
            searchingPlayer=searchingPlayer,
            priorityFunc=priorityFunc,
            skipFunc=skipFunc,
            logEntries=logEntries,
            ignoreStartTile=ignoreStartTile,
            incrementBackward=incrementBackward,
            preferNeutral=preferNeutral,
            shouldLog=shouldLog,
            useTrueValueGathered=useTrueValueGathered,
        )
        _dump_log_entries(logEntries)

        turnsUsed = 0
        for path in newPaths:
            turnsUsed += path.length
        calculatedLeftOverTurns = remainingTurns - turnsUsed
        expectedLeftOverTurns = remainingTurns - turnsToTry
        newStartTilesDict = startTilesDict

        # loop because we may not find a full plan due to cramped conditions etc in a single iteration
        while calculatedLeftOverTurns < remainingTurns:
            #  + GOTO ITERATE T = T - T//3
            turnsLeft, newStartTilesDict = build_next_level_start_dict(
                newPaths,
                newStartTilesDict,
                searchingPlayer,
                calculatedLeftOverTurns,
                # skipTiles,
                baseCaseFunc
            )

            probablyBad = False
            if turnsLeft is None:
                logbook.info(
                    f'bad paths were found in the plan with {expectedLeftOverTurns} remaining turns, we should probably not continue searching')
                probablyBad = True
            elif expectedLeftOverTurns != turnsLeft:
                logbook.info(
                    f'this iteration (remainingTurns {remainingTurns} - turnsToTry {turnsToTry}) found a less than full gather plan length {remainingTurns - calculatedLeftOverTurns} (possibly because it didnt have enough tiles to gather a full plan to).')

            turnsToTry = calculatedLeftOverTurns
            childGatheredArmy, newChildPaths = _knapsack_levels_gather_recurse(
                itr=itr,
                map=map,
                startTilesDict=newStartTilesDict,
                # gatherTreeNodeLookup=gatherTreeNodeLookup.copy(),
                remainingTurns=turnsToTry,
                fullTurns=fullTurns,
                targetArmy=targetArmy,
                valueFunc=valueFunc,
                baseCaseFunc=baseCaseFunc,
                negativeTiles=negativeTiles,
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
                useTrueValueGathered=useTrueValueGathered,
                includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
                shouldLog=shouldLog,
            )

            if probablyBad and len(newChildPaths) > 0:
                logbook.error(
                    f'expected no new paths because bad path found in parent plan, but the child plan WAS able to find new paths...? This means assumptions I am making are incorrect')

            turnsUsed = 0
            for path in newChildPaths:
                turnsUsed += path.length
                newPaths.append(path)
            calculatedLeftOverTurns = calculatedLeftOverTurns - turnsUsed
            newGatheredArmy += childGatheredArmy
            expectedLeftOverTurns = remainingTurns - turnsToTry
            if turnsUsed == 0:
                break

        if newGatheredArmy > maxIterationGatheredArmy:
            maxIterationGatheredArmy = newGatheredArmy
            maxIterationPaths = newPaths

    if maxIterationGatheredArmy > 0:
        for path in maxIterationPaths:
            itr.value += 1

    if len(maxIterationPaths) == 0 or remainingTurns is None:
        # break
        return 0, maxIterationPaths

    return maxIterationGatheredArmy, maxIterationPaths


def _knapsack_levels_gather_iterative_prune(
        itr: SearchUtils.Counter,
        map: MapBase,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        cutoffTime: float,
        # gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        remainingTurns: int,
        fullTurns: int,
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        pathValueFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=True,
        preferNeutral=False,
        viewInfo=None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        logEntries: typing.List[str] | None = None,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog=False,
        fastMode=False
) -> typing.Tuple[int, typing.List[GatherTreeNode]]:
    """

    @param itr:
    @param map:
    @param startTilesDict:
    @param remainingTurns:
    @param fullTurns:
    @param targetArmy:
    @param valueFunc:
    @param baseCaseFunc:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc:
    @param skipFunc:
    @param priorityTiles:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param viewInfo:
    @param distPriorityMap:
    @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
     capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
     so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
     gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @return:
    """
    origStartTilesDict = startTilesDict.copy()

    rootNodes: typing.List[GatherTreeNode] = []

    maxPerIteration = max(4, fullTurns // 3 - 1)
    if fastMode:
        maxPerIteration = max(6, fullTurns // 2)

    teams = MapBase.get_teams_array(map)

    turnsSoFar = 0
    totalValue = 0
    newStartTilesDict = startTilesDict.copy()
    gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {}
    for tile, data in startTilesDict.items():
        (_, dist) = data
        gatherTreeNodeLookup[tile] = GatherTreeNode(tile, toTile=None, stateObj=dist)

    prevBest = 0

    lastPrunedTo = 0

    if logEntries is None:
        logEntries = []

    startTime = time.perf_counter()

    doNotBreakIncomplete = True

    try:
        while lastPrunedTo < fullTurns:
            itr.add(1)
            turnsToGather = fullTurns - turnsSoFar
            logEntries.append(f'Sub Knap (iter {itr.value} {time.perf_counter() - startTime:.4f} in) turns {turnsToGather} sub_knapsack, fullTurns {fullTurns}, turnsSoFar {turnsSoFar}')
            if shouldLog:
                logEntries.append(f'start tiles: {str(newStartTilesDict)}')
            newGatheredArmy, newPaths = get_sub_knapsack_gather(
                map,
                newStartTilesDict,
                valueFunc,
                baseCaseFunc,
                pathValueFunc,
                maxTime=1000,
                remainingTurns=turnsToGather,
                fullTurns=fullTurns,
                noNeutralCities=True,
                negativeTiles=negativeTiles,
                skipTiles=skipTiles,
                searchingPlayer=searchingPlayer,
                priorityFunc=priorityFunc,
                skipFunc=skipFunc,
                ignoreStartTile=True,
                incrementBackward=incrementBackward,
                preferNeutral=preferNeutral,
                priorityMatrix=priorityMatrix,
                shouldLog=shouldLog,
                useTrueValueGathered=useTrueValueGathered,
                logEntries=logEntries
            )

            if len(newPaths) == 0:
                logEntries.append('no new paths found, breaking knapsack stuff')
                break  # gatherTreeNodeLookup[map.GetTile(15,9)].children[0] == gatherTreeNodeLookup[map.GetTile(16,9)]
            # elif DebugHelper.IS_DEBUGGING:
            #     logEntries.append(f'  returned:')
            #     logEntries.extend([f'\r\n    {p}' for p in newPaths])

            extend_tree_node_lookup(
                newPaths,
                gatherTreeNodeLookup,
                newStartTilesDict,
                searchingPlayer,
                teams,
                logEntries=logEntries,
                negativeTiles=negativeTiles,
                useTrueValueGathered=useTrueValueGathered,
                priorityMatrix=priorityMatrix,
                shouldLog=shouldLog,
            )

            turnsUsedByNewPaths = 0
            for path in newPaths:
                turnsUsedByNewPaths += path.length
            calculatedLeftOverTurns = remainingTurns - turnsUsedByNewPaths

            for path in newPaths:
                rootNode = gatherTreeNodeLookup.get(path.start.tile, None)
                if rootNode is not None:
                    (startPriorityObject, distance) = newStartTilesDict[rootNode.tile]
                    if DebugHelper.IS_DEBUGGING:
                        logEntries.append(f'  add_tree_nodes_to_start_tiles_dict_recurse {rootNode} @ dist {distance}')
                    add_tree_nodes_to_start_tiles_dict_recurse(
                        rootNode,
                        newStartTilesDict,
                        searchingPlayer,
                        calculatedLeftOverTurns,
                        baseCaseFunc,
                        dist=distance
                    )

            rootNodes = [g for g in (gatherTreeNodeLookup.get(tile, None) for tile in origStartTilesDict) if g is not None]

            if USE_DEBUG_ASSERTS:
                # rootNodes = [gatherTreeNodeLookup[tile] for tile in origStartTilesDict]
                logEntries.append('doing recalc after adding to start dict')

                recalcTotalTurns, recalcTotalValue = recalculate_tree_values(
                    logEntries,
                    rootNodes,
                    negativeTiles,
                    origStartTilesDict,
                    searchingPlayer,
                    teams,
                    onlyCalculateFriendlyArmy=not useTrueValueGathered,
                    priorityMatrix=priorityMatrix,
                    viewInfo=viewInfo,
                    shouldAssert=True)

                if prevBest < recalcTotalValue:
                    logEntries.append(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} > {prevBest}!')
                elif prevBest > 0 and prevBest > recalcTotalValue:
                    _dump_log_entries(logEntries)
                    raise AssertionError(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} WORSE than prev {prevBest}? This should be impossible.')
                # if recalcTotalValue != newGatheredArmy + valueSoFar:
                #     if not SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
                #         raise AssertionError(f'recalculated gather value {recalcTotalValue} didnt match algo output gather value {newGatheredArmy}')
                if recalcTotalTurns != turnsUsedByNewPaths + turnsSoFar:
                    msg = f'recalc gather turns {recalcTotalTurns} didnt match algo turns turnsUsedByNewPaths {turnsUsedByNewPaths} + turnsSoFar {turnsSoFar}'
                    if USE_DEBUG_ASSERTS:
                        # TODO figure this shit the fuck out, what the fuck
                        _dump_log_entries(logEntries)
                        raise AssertionError(msg)
                    elif viewInfo:
                        viewInfo.add_info_line(msg)

            totalTurns = turnsUsedByNewPaths + turnsSoFar

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

            pruneToTurns = lastPrunedTo + maxPerIteration
            # maxPerIteration = max(maxPerIteration // 2, 1)
            maxPerIteration = maxPerIteration // 2 + 1
            if fastMode:
                maxPerIteration += 1

            # if we're at the end of the gather, gather 1 level at a time for the last phase to make sure we dont miss any optimal branches.

            # if fullTurns - pruneToTurns < max(maxPerIteration, 12):
            if fullTurns - pruneToTurns <= maxPerIteration * 2 and not fastMode:
                maxPerIteration = 1
                pruneToTurns = lastPrunedTo + maxPerIteration

            # if len(newPaths) > 1:
            # TODO try pruning to max VT here instead of constant turns...?
            logEntries.append(f'pruning current {totalValue:.2f}v @ {totalTurns}t to {pruneToTurns}t (maxPerIteration {maxPerIteration}, allowNegative={includeGatherTreeNodesThatGatherNegative})')
            totalTurns, totalValue, rootNodes = prune_mst_to_turns_with_values(
                rootNodes,
                turns=pruneToTurns,
                searchingPlayer=searchingPlayer,
                viewInfo=viewInfo,
                noLog=not shouldLog and not USE_DEBUG_ASSERTS,  # and not DebugHelper.IS_DEBUGGING
                gatherTreeNodeLookupToPrune=gatherTreeNodeLookup,
                allowNegative=includeGatherTreeNodesThatGatherNegative,
                tileDictToPrune=newStartTilesDict,
                logEntries=logEntries,
                parentPruneFunc=lambda t, prunedNode: _start_tiles_prune_helper(startTilesDict, t, prunedNode)
            )

            if USE_DEBUG_ASSERTS:
                recalcTotalTurns, recalcTotalValue = recalculate_tree_values(
                    logEntries,
                    rootNodes,
                    negativeTiles,
                    newStartTilesDict,
                    searchingPlayer,
                    teams,
                    onlyCalculateFriendlyArmy=not useTrueValueGathered,
                    priorityMatrix=priorityMatrix,
                    viewInfo=viewInfo,
                    shouldAssert=USE_DEBUG_ASSERTS
                )

                if recalcTotalTurns != totalTurns:
                    _dump_log_entries(logEntries)
                    raise AssertionError(f'Pruned turns {totalTurns} didnt match recalculated, {recalcTotalTurns}')
                if round(recalcTotalValue, 6) != round(totalValue, 6):
                    _dump_log_entries(logEntries)
                    raise AssertionError(f'Pruned value {round(totalValue, 6)} didnt match recalculated, {round(recalcTotalValue, 6)}')

                if totalTurns > pruneToTurns and includeGatherTreeNodesThatGatherNegative:
                    _dump_log_entries(logEntries)
                    raise AssertionError(f'Pruned turns {totalTurns} was more than the amount requested, {pruneToTurns}')

            # _debug_print_diff_between_start_dict_and_GatherTreeNodes(gatherTreeNodeLookup, newStartTilesDict)

            lastPrunedTo = pruneToTurns
            turnsSoFar = totalTurns

        # if DebugHelper.IS_DEBUGGING:
        #     foreach_tree_node(rootNodes, lambda n: logEntries.append(f'inc: {str(n)}'))

    finally:
        logbook.info('\n'.join(logEntries))

    return totalValue, rootNodes


def _start_tiles_prune_helper(
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        parentTile: Tile,
        gatherNodeBeingPruned: GatherTreeNode
):
    prioDistTuple = startTilesDict.get(parentTile, None)

    if prioDistTuple is not None:
        prios, oldDist = prioDistTuple
        logbook.info(f'pruning {str(parentTile)} from {oldDist} to {oldDist - gatherNodeBeingPruned.gatherTurns} (pruned {str(gatherNodeBeingPruned.tile)} gatherTurns {gatherNodeBeingPruned.gatherTurns})')
        startTilesDict[parentTile] = (prios, oldDist - gatherNodeBeingPruned.gatherTurns)


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


def knapsack_levels_backpack_gather(
        map: MapBase,
        startTiles,
        turns: int,
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
        useTrueValueGathered=False,
        includeGatherTreeNodesThatGatherNegative=False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
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
    @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
     capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
     so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
     gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @param priorityMatrix:
    @param fastMode: whether to use the fastMode (less optimal results but much quicker) iterative params.
    @return:
    """
    totalValue, rootNodes = knapsack_levels_backpack_gather_with_value(
        map=map,
        startTiles=startTiles,
        turns=turns,
        targetArmy=targetArmy,
        valueFunc=valueFunc,
        baseCaseFunc=baseCaseFunc,
        negativeTiles=negativeTiles,
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
        useTrueValueGathered=useTrueValueGathered,
        includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
        priorityMatrix=priorityMatrix,
        cutoffTime=cutoffTime,
        shouldLog=shouldLog,
        fastMode=fastMode
    )

    return rootNodes


def knapsack_levels_backpack_gather_with_value(
        map: MapBase,
        startTiles,
        turns: int,
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        pathValueFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc: typing.Callable[[Tile, typing.Any], bool] | None = None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=True,
        preferNeutral=False,
        viewInfo: ViewInfo | None = None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog=False,  # DebugHelper.IS_DEBUGGING
        useRecurse=False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        cutoffTime: float | None = None,
        fastMode: bool = False
) -> typing.Tuple[int, typing.List[GatherTreeNode]]:
    """
    Does black magic and shits out a spiderweb with numbers in it, sometimes the numbers are even right

    @param map:
    @param startTiles:
    startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile], OR dict distance = startTiles[tile] (which will be converted to (startPriorityObject, distance) by baseCaseFunc)
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
    @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
     capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
     so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
     gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @return:
    """
    startTime = time.perf_counter()
    negativeTilesOrig = negativeTiles
    if negativeTiles is not None:
        negativeTiles = negativeTiles.copy()
    else:
        negativeTiles = set()

    if cutoffTime is None:
        cutoffTime = time.perf_counter() + 500

    teams = MapBase.get_teams_array(map)
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
            searchingPlayer = [t for t in startTiles.keys()][0].player
        else:
            searchingPlayer = startTiles[0].player

    priosByTile: typing.Dict[typing.Tuple[int, int], typing.Any]

    logEntries = []

    friendlyPlayers = map.get_teammates(searchingPlayer)

    if shouldLog:
        logbook.info(f"Trying knapsack-bfs-gather. Turns {turns}. Searching player {searchingPlayer}")
    if valueFunc is None:

        if shouldLog:
            logbook.info("Using emptyVal valueFunc")

        def default_value_func_max_gathered_per_turn(
                currentTile,
                priorityObject
        ):
            (
                threatDist,
                depthDist,
                realDist,
                negPrioTilesPerTurn,
                negGatheredSum,
                negArmySum,
                # xSum,
                # ySum,
                numPrioTiles
            ) = priorityObject

            key = (currentTile.tile_index, depthDist)
            priosByTile[key] = priorityObject
            # existingPrio = priosByTile.get(key, None)
            # if existingPrio is None or existingPrio > priorityObject:
            #     priosByTile[key] = prioObj

            if negArmySum >= 0 and not includeGatherTreeNodesThatGatherNegative:
                return None
            if negGatheredSum >= 0:
                return None
            if currentTile.army < 2 or currentTile.player != searchingPlayer:
                return None

            value = 0 - negGatheredSum

            vt = 0
            if realDist > 0:
                vt = value / realDist

            prioObj = (vt,  # most army per turn
                       0 - threatDist,
                       # then by the furthest 'distance' (which when gathering to a path, weights short paths to the top of the path higher which is important)
                       0 - negGatheredSum,  # then by maximum amount gathered...?
                       0 - depthDist,  # furthest distance traveled
                       realDist,  # then by the real distance
                       # 0 - xSum,
                       # 0 - ySum
                       )
            if shouldLog:
                logEntries.append(f'VALUE {str(currentTile)} : {str(prioObj)}')
            return prioObj

        valueFunc = default_value_func_max_gathered_per_turn

    if priorityFunc is None:
        if shouldLog:
            logbook.info("Using emptyVal priorityFunc")

        priosByTile = {}

        def default_priority_func(nextTile, currentPriorityObject):
            (
                threatDist,
                depthDist,
                realDist,
                negPrioTilesPerTurn,
                negGatheredSum,
                negArmySum,
                # xSum,
                # ySum,
                numPrioTiles
            ) = currentPriorityObject
            negArmySum += 1
            negGatheredSum += 1
            # if nextTile.x == 6 and nextTile.y == 2 and map.turn == 224:
            #     pass
            if nextTile not in negativeTiles:
                if nextTile.player in friendlyPlayers:
                    negArmySum -= nextTile.army
                    negGatheredSum -= nextTile.army
                # # this broke gather approximation, couldn't predict actual gather values based on this
                # if nextTile.isCity:
                #    negArmySum -= turns // 3
                else:
                    negArmySum += nextTile.army
                    if useTrueValueGathered:
                        negGatheredSum += nextTile.army

            # TODO comment back in
            # if priorityMatrix is not None:
            #     negGatheredSum -= priorityMatrix.raw[nextTile.tile_index]

            if priorityTiles and nextTile in priorityTiles:
                numPrioTiles += 1
            realDist += 1
            depthDist += 1
            prioObj = (
                threatDist + 1,
                depthDist,
                realDist,
                numPrioTiles / max(1, depthDist),
                negGatheredSum,
                negArmySum,
                # xSum + nextTile.x,
                # ySum + nextTile.y,
                numPrioTiles
            )
            if shouldLog or USE_DEBUG_ASSERTS:
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

            initialDistance = 0
            # TODO comment back in
            # if distPriorityMap is not None:
            #     initialDistance = distPriorityMap.raw[tile.tile_index]
            armyNegSum = 0
            gathNegSum = 0

            prioObj = (
                0 - initialDistance,
                startingDist,
                0,
                0,
                gathNegSum,  # gath neg
                armyNegSum,  # army neg
                # tile.x,
                # tile.y,
                0
            )

            fromPrio = priosByTile.get((tile.tile_index, startingDist), None)

            if fromPrio is not None:
                # return fromPrio
                (
                    threatDist,
                    depthDist,
                    realDist,
                    negPrioTilesPerTurn,
                    gathNegSum,
                    armyNegSum,
                    # xSum,
                    # ySum,
                    numPrioTiles
                ) = fromPrio

                if USE_DEBUG_ASSERTS and startingDist != depthDist:
                    raise AssertionError(f'what? startingDist {startingDist} != depthDist {depthDist}')

                if shouldLog or USE_DEBUG_ASSERTS:
                    logEntries.append(f'BASE FROM: {tile} -> {str(fromPrio)}')

                prioObj = (
                    threatDist,
                    depthDist,
                    0,
                    negPrioTilesPerTurn,
                    gathNegSum,  # gath neg
                    armyNegSum,  # army neg
                    # tile.x,
                    # tile.y,
                    numPrioTiles
                )
                # return (
                #     threatDist,
                #     depthDist,
                #     realDist,
                #     negPrioTilesPerTurn,
                #     gathNegSum,
                #     armyNegSum,
                #     # xSum,
                #     # ySum,
                #     numPrioTiles
                # )

            elif useTrueValueGathered:
                if tile.player not in friendlyPlayers:
                    gathNegSum += tile.army
                    armyNegSum += tile.army

            if shouldLog or USE_DEBUG_ASSERTS:
                logEntries.append(f"BASE CASE: {str(tile)} -> {str(prioObj)}")
            return prioObj

        baseCaseFunc = default_base_case_func

    if pathValueFunc is None:
        if shouldLog:
            logbook.info("Using emptyVal pathValueFunc")

        def default_path_value_func(path, valueObj) -> float:
            (
                vt,  # most army per turn
                negThreatDist,
                gatheredSum,  # then by maximum amount gathered...?
                negDepthDist,  # furthest distance traveled
                realDist,  # then by the real distance
            ) = valueObj

            if shouldLog:
                logEntries.append(f"PATH VALUE {path}: {gatheredSum:.2f}")
            return gatheredSum

        # pathValueFunc = default_path_value_func

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

    origStartTilesDict = startTilesDict.copy()

    itr = SearchUtils.Counter(0)

    if not useRecurse:
        totalValue, rootNodes = _knapsack_levels_gather_iterative_prune(
            itr=itr,
            map=map,
            startTilesDict=startTilesDict,
            cutoffTime=cutoffTime,
            # gatherTreeNodeLookup=gatherTreeNodeLookup,
            remainingTurns=turns,
            fullTurns=turns,
            targetArmy=targetArmy,
            valueFunc=valueFunc,
            baseCaseFunc=baseCaseFunc,
            pathValueFunc=pathValueFunc,
            negativeTiles=negativeTiles,
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
            # priorityMatrix=priorityMatrix,
            useTrueValueGathered=useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            logEntries=logEntries,
            shouldLog=shouldLog,
            fastMode=fastMode
        )
    else:
        gatheredValue, maxPaths = _knapsack_levels_gather_recurse(
            itr=itr,
            map=map,
            startTilesDict=startTilesDict,
            remainingTurns=turns,
            fullTurns=turns,
            targetArmy=targetArmy,
            valueFunc=valueFunc,
            baseCaseFunc=baseCaseFunc,
            pathValueFunc=pathValueFunc,
            negativeTiles=negativeTiles,
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
            useTrueValueGathered=useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            shouldLog=shouldLog,
        )

        gatherTreeNodeLookup = build_tree_node_lookup(
            maxPaths,
            startTilesDict,
            searchingPlayer,
            teams,
            # skipTiles
            shouldLog=shouldLog,
            priorityMatrix=priorityMatrix,
        )

        rootNodes: typing.List[GatherTreeNode] = list(where(gatherTreeNodeLookup.values(), lambda treeNode: treeNode.toTile is None))

        totalTurns, totalValue = recalculate_tree_values(
            [],
            rootNodes,
            negativeTilesOrig,
            origStartTilesDict,
            searchingPlayer=searchingPlayer,
            teams=teams,
            onlyCalculateFriendlyArmy=not useTrueValueGathered,
            viewInfo=viewInfo,
            shouldAssert=True,
            priorityMatrix=priorityMatrix)

    totalTurns = 0
    for g in rootNodes:
        totalTurns += g.gatherTurns

    logbook.info(
        f"Concluded knapsack_levels_backpack_gather with {itr.value} iterations. Gather turns {totalTurns}, value {totalValue}. Duration: {time.perf_counter() - startTime:.4f}")
    return totalValue, rootNodes


def greedy_backpack_gather(
        map,
        startTiles,
        turns,
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        viewInfo=None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        includeGatherTreeNodesThatGatherNegative: bool = False,
        shouldLog: bool = True
) -> typing.List[GatherTreeNode]:
    gatheredValue, turnsUsed, nodes = greedy_backpack_gather_values(
        map=map,
        startTiles=startTiles,
        turns=turns,
        targetArmy=targetArmy,
        valueFunc=valueFunc,
        baseCaseFunc=baseCaseFunc,
        negativeTiles=negativeTiles,
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
        useTrueValueGathered=useTrueValueGathered,
        includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
        shouldLog=shouldLog,
    )

    return nodes


def is_friendly_tile(map: MapBase, tile: Tile, searchingPlayer: int) -> bool:
    if tile.player == searchingPlayer:
        return True
    if map.teams is not None and map.teams[tile.player] == map.teams[searchingPlayer]:
        return True
    return False


def greedy_backpack_gather_values(
        map,
        startTiles,
        turns,
        targetArmy=None,
        valueFunc=None,
        baseCaseFunc=None,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        priorityTiles=None,
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        viewInfo=None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        includeGatherTreeNodesThatGatherNegative: bool = False,
        shouldLog: bool = True
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Legacy iterative BFS greedy backpack gather, where every iteration it adds the max army-per-turn path that it finds on to the existing gather plan.
    SHOULD be replaced by variations of the multiple-choice-knapsack gathers that pull lots of paths in a single BFS and knapsack them.
    Returns (value, turnsUsed, gatherNodes)

    @param map:
    @param startTiles: startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile]
    @param turns:
    @param targetArmy:
    @param valueFunc: valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object (highest wins)
    @param baseCaseFunc:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc: priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted (lowest wins)
    @param skipFunc:
    @param priorityTiles:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param viewInfo:
    @param distPriorityMap:
    @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
     capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
     so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
     gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @return:
    """
    startTime = time.perf_counter()
    negativeTilesOrig = negativeTiles
    if negativeTiles is not None:
        negativeTiles = negativeTiles.copy()
    else:
        negativeTiles = set()

    teams = MapBase.get_teams_array(map)

    # TODO factor in cities, right now they're not even incrementing. need to factor them into the timing and calculate when they'll be moved.
    if searchingPlayer == -2:
        if isinstance(startTiles, dict):
            searchingPlayer = [t for t in startTiles.keys()][0].player
        else:
            searchingPlayer = startTiles[0].player

    logbook.info(f"Trying greedy-bfs-gather. Turns {turns}. Searching player {searchingPlayer}")
    if valueFunc is None:
        logbook.info("Using emptyVal valueFunc")

        def default_value_func_max_gathered_per_turn(currentTile, priorityObject):
            (realDist,
             negPrioTilesPerTurn,
             negGatheredSum,
             negArmySum,
             negDistanceSum,
             dist,
             xSum,
             ySum,
             numPrioTiles) = priorityObject

            if negArmySum >= 0 or currentTile.player != searchingPlayer:
                return None

            value = 0 - (negGatheredSum / (max(1, realDist)))

            return value, dist, 0 - negDistanceSum, 0 - negGatheredSum, realDist, 0 - xSum, 0 - ySum

        valueFunc = default_value_func_max_gathered_per_turn

    if priorityFunc is None:
        logbook.info("Using emptyVal priorityFunc")

        def default_priority_func(nextTile, currentPriorityObject):
            (realDist, negPrioTilesPerTurn, negGatheredSum, negArmySum, negDistanceSum, dist, xSum, ySum,
             numPrioTiles) = currentPriorityObject
            negArmySum += 1
            negGatheredSum += 1
            if nextTile not in negativeTiles:
                if searchingPlayer == nextTile.player:
                    negArmySum -= nextTile.army
                    negGatheredSum -= nextTile.army
                # # this broke gather approximation, couldn't predict actual gather values based on this
                # if nextTile.isCity:
                #    negArmySum -= turns // 3
                else:
                    negArmySum += nextTile.army
                    if useTrueValueGathered:
                        negGatheredSum += nextTile.army
            # if nextTile.player != searchingPlayer and not (nextTile.player == -1 and nextTile.isCity):
            #    negDistanceSum -= 1
            # hacks us prioritizing further away tiles
            if distPriorityMap is not None:
                negDistanceSum -= distPriorityMap[nextTile]
            if priorityTiles is not None and nextTile in priorityTiles:
                numPrioTiles += 1
            realDist += 1
            # logbook.info("prio: nextTile {} got realDist {}, negNextArmy {}, negDistanceSum {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
            return realDist, numPrioTiles / realDist, negGatheredSum, negArmySum, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y, numPrioTiles

        priorityFunc = default_priority_func

    if baseCaseFunc is None:
        logbook.info("Using emptyVal baseCaseFunc")

        def default_base_case_func(tile, startingDist):
            startArmy = 0
            # we would like to not gather to an enemy tile without killing it, so must factor it into the path. army value is negative for priority, so use positive for enemy army.
            if useTrueValueGathered and tile.player != searchingPlayer:
                logbook.info(
                    f"tile {tile.toString()} was not owned by searchingPlayer {searchingPlayer}, adding its army {tile.army}")
                startArmy = tile.army

            initialDistance = 0
            if distPriorityMap is not None:
                initialDistance = distPriorityMap[tile]

            logbook.info(
                f"tile {tile.toString()} got base case startArmy {startArmy}, startingDist {startingDist}")
            return 0, 0, 0, startArmy, 0 - initialDistance, startingDist, tile.x, tile.y, 0

        baseCaseFunc = default_base_case_func

    startTilesDict = {}
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            if isinstance(startTiles[tile], int):
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

    for tile in startTilesDict.keys():
        (startPriorityObject, distance) = startTilesDict[tile]
        logbook.info(f"Including tile {tile.x},{tile.y} in startTiles at distance {distance}")

    gatherTreeNodeLookup = {}
    itr = 0
    remainingTurns = turns
    valuePerTurnPath: Path
    origStartTiles = startTilesDict.copy()
    while True:
        logbook.info(f"Searching for the next path with remainingTurns {remainingTurns}")
        valuePerTurnPath = SearchUtils.breadth_first_dynamic_max_global_visited(
            map,
            startTilesDict,
            valueFunc,
            0.1,
            remainingTurns,
            maxDepth=turns,
            noNeutralCities=True,
            negativeTiles=negativeTiles,
            skipTiles=skipTiles,
            searchingPlayer=searchingPlayer,
            priorityFunc=priorityFunc,
            skipFunc=skipFunc,
            ignoreStartTile=ignoreStartTile,
            incrementBackward=incrementBackward,
            preferNeutral=preferNeutral,
            logResultValues=True,
            ignoreNonPlayerArmy=not useTrueValueGathered)

        if valuePerTurnPath is None:
            break

        if valuePerTurnPath.tail.tile.army <= 1 or valuePerTurnPath.tail.tile.player != searchingPlayer:
            logbook.info(
                f"TERMINATING greedy-bfs-gather PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
            break
        logbook.info(
            f"Adding valuePerTurnPath (v/t {(valuePerTurnPath.value - valuePerTurnPath.start.tile.army + 1) / valuePerTurnPath.length:.3f}): {valuePerTurnPath.toString()}")

        remainingTurns = remainingTurns - valuePerTurnPath.length
        itr += 1
        # add the new path to startTiles, rinse, and repeat
        node = valuePerTurnPath.start
        # we need to factor in the distance that the last path was already at (say we're gathering to a threat,
        # you can't keep adding gathers to the threat halfway point once you're gathering for as many turns as half the threat length
        (startPriorityObject, distance) = startTilesDict[node.tile]
        # TODO? May need to not continue with the previous paths priorityObjects and instead start fresh, as this may unfairly weight branches
        #       towards the initial max path, instead of the highest actual additional value
        # curPrioObj = startPriorityObject
        addlDist = 1
        # currentGatherTreeNode = None

        if node.tile in gatherTreeNodeLookup:
            currentGatherTreeNode = gatherTreeNodeLookup[node.tile]
        else:
            currentGatherTreeNode = GatherTreeNode(node.tile, None, distance)
            currentGatherTreeNode.gatherTurns = 1
        runningValue = valuePerTurnPath.value - node.tile.army
        currentGatherTreeNode.value += runningValue
        runningValue -= node.tile.army
        gatherTreeNodeLookup[node.tile] = currentGatherTreeNode
        negativeTiles.add(node.tile)
        # skipping because first tile is actually already on the path
        node = node.next
        # add the new path to startTiles and then search a new path
        while node is not None:
            newDist = distance + addlDist
            nextPrioObj = baseCaseFunc(node.tile, newDist)
            startTilesDict[node.tile] = (nextPrioObj, newDist)
            negativeTiles.add(node.tile)
            logbook.info(
                f"Including tile {node.tile.x},{node.tile.y} in startTilesDict at newDist {newDist}  (distance {distance} addlDist {addlDist})")
            # if viewInfo:
            #    viewInfo.bottomRightGridText[node.tile] = newDist
            nextGatherTreeNode = GatherTreeNode(node.tile, currentGatherTreeNode.tile, newDist)
            nextGatherTreeNode.value = runningValue
            nextGatherTreeNode.gatherTurns = 1
            runningValue -= node.tile.army
            currentGatherTreeNode.children.append(nextGatherTreeNode)
            currentGatherTreeNode = nextGatherTreeNode
            gatherTreeNodeLookup[node.tile] = currentGatherTreeNode
            addlDist += 1
            node = node.next

        if remainingTurns <= 0:
            break

    rootNodes = list(where(gatherTreeNodeLookup.values(), lambda gatherTreeNode: gatherTreeNode.toTile is None))

    turnsUsed, totalValue = recalculate_tree_values(
        [],
        rootNodes,
        negativeTilesOrig,
        origStartTiles,
        searchingPlayer=searchingPlayer,
        teams=teams,
        onlyCalculateFriendlyArmy=not useTrueValueGathered,
        viewInfo=viewInfo)

    logbook.info(
        f"Concluded greedy-bfs-gather with {itr} path segments, turns {turnsUsed}/{turns} (lenStart tiles {len(startTilesDict)}) value {totalValue}. Duration: {time.perf_counter() - startTime:.4f}")
    return totalValue, turnsUsed, rootNodes


def recalculate_tree_values(
        logEntries: typing.List[str],
        rootNodes: typing.List[GatherTreeNode],
        negativeTiles: typing.Set[Tile] | None,
        startTilesDict: typing.Dict[Tile, object],
        searchingPlayer: int,
        teams: typing.List[int],
        onlyCalculateFriendlyArmy=False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        viewInfo=None,
        shouldAssert=False
) -> typing.Tuple[int, int]:
    """
    Return totalTurns, totalValue

    @param logEntries:
    @param rootNodes:
    @param negativeTiles:
    @param startTilesDict:
    @param searchingPlayer:
    @param teams:
    @param onlyCalculateFriendlyArmy:
    @param priorityMatrix:
    @param viewInfo:
    @param shouldAssert:
    @return:
    """
    totalValue = 0
    totalTurns = 0
    # logEntries.append('recalcing treenodes....')
    for currentNode in rootNodes:
        _recalculate_tree_values_recurse(
            logEntries,
            currentNode,
            negativeTiles,
            startTilesDict,
            searchingPlayer,
            teams,
            onlyCalculateFriendlyArmy,
            priorityMatrix,
            viewInfo,
            shouldAssert)
        totalValue += currentNode.value
        totalTurns += currentNode.gatherTurns

    # find the leaves
    queue = deque()
    for treeNode in rootNodes:
        if shouldAssert and treeNode.trunkValue != 0:
            _dump_log_entries(logEntries)
            raise AssertionError(f'root node {str(treeNode)} trunk value should have been 0 but was {treeNode.trunkValue}')
        if shouldAssert and treeNode.trunkDistance != 0:
            _dump_log_entries(logEntries)
            raise AssertionError(f'root node {str(treeNode)} trunk dist should have been 0 but was {treeNode.trunkDistance}')
        treeNode.trunkValue = 0
        treeNode.trunkDistance = 0
        queue.appendleft(treeNode)

    while queue:
        current = queue.pop()
        for child in current.children:
            trunkValue = current.trunkValue
            trunkDistance = current.trunkDistance + 1
            if negativeTiles is None or child.tile not in negativeTiles:
                if teams[child.tile.player] == teams[searchingPlayer]:
                    trunkValue += child.tile.army
                elif not onlyCalculateFriendlyArmy:
                    trunkValue -= child.tile.army
            trunkValue -= 1
            if shouldAssert:
                if trunkDistance != child.trunkDistance:
                    _dump_log_entries(logEntries)
                    raise AssertionError(f'node {str(child)} trunk dist should have been {trunkDistance} but was {child.trunkDistance}')
                if trunkValue != child.trunkValue:
                    _dump_log_entries(logEntries)
                    raise AssertionError(f'node {str(child)} trunk value should have been {trunkValue} but was {child.trunkValue}')
            child.trunkValue = trunkValue
            child.trunkDistance = trunkDistance

            # if viewInfo is not None:
            #     viewInfo.bottomLeftGridText[child.tile] = child.trunkValue
            queue.appendleft(child)

    return totalTurns, totalValue


def _recalculate_tree_values_recurse(
        logEntries: typing.List[str],
        currentNode: GatherTreeNode,
        negativeTiles: typing.Set[Tile] | None,
        startTilesDict: typing.Dict[Tile, object],
        searchingPlayer: int,
        teams: typing.List[int],
        onlyCalculateFriendlyArmy=False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        viewInfo=None,
        shouldAssert=False
):
    if USE_DEBUG_ASSERTS:
        logEntries.append(f'RECALCING currentNode {currentNode}')

    isStartNode = False

    # we leave one node behind at each tile, except the root tile.
    turns = 1
    sum = -1
    currentTile = currentNode.tile
    if viewInfo:
        viewInfo.midRightGridText[currentTile] = f'v{currentNode.value:.0f}'
        viewInfo.bottomMidRightGridText[currentTile] = f'tv{currentNode.trunkValue:.0f}'
        viewInfo.bottomRightGridText[currentTile] = f'td{currentNode.trunkDistance}'

        if currentNode.trunkDistance > 0:
            rawValPerTurn = currentNode.value / currentNode.trunkDistance
            trunkValPerTurn = currentNode.trunkValue / currentNode.trunkDistance
            viewInfo.bottomMidLeftGridText[currentTile] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[currentTile] = f'vt{rawValPerTurn:.1f}'

    if currentNode.toTile is None:
        if USE_DEBUG_ASSERTS:
            logEntries.append(f'{currentTile} is first tile, starting at 0')
        isStartNode = True
        sum = 0
        turns = 0
    # elif priorityMatrix:
    #     sum += priorityMatrix[currentTile]

    if (negativeTiles is None or currentTile not in negativeTiles) and not isStartNode:
        if teams[currentTile.player] == teams[searchingPlayer]:
            sum += currentTile.army
        elif not onlyCalculateFriendlyArmy:
            sum -= currentTile.army

    if priorityMatrix and not isStartNode:
        sum += priorityMatrix[currentTile]
        if USE_DEBUG_ASSERTS:
            logEntries.append(f'appending {currentTile}  {currentTile.army}a  matrix {priorityMatrix[currentTile]:.3f} -> {sum:.3f}')

    for child in currentNode.children:
        _recalculate_tree_values_recurse(
            logEntries,
            child,
            negativeTiles,
            startTilesDict,
            searchingPlayer,
            teams,
            onlyCalculateFriendlyArmy,
            priorityMatrix,
            viewInfo,
            shouldAssert=shouldAssert)
        sum += child.value
        turns += child.gatherTurns

    # if viewInfo:
    #     viewInfo.bottomRightGridText[currentNode.tile] = sum

    if shouldAssert:
        curNodeVal = round(currentNode.value, 6)
        recalcSum = round(sum, 6)
        if curNodeVal != recalcSum:
            _dump_log_entries(logEntries)
            raise AssertionError(f'currentNode {str(currentNode)} val {curNodeVal:.6f} != recalculated sum {recalcSum:.6f}')
        if currentNode.gatherTurns != turns:
            _dump_log_entries(logEntries)
            raise AssertionError(f'currentNode {str(currentNode)} turns {currentNode.gatherTurns} != recalculated turns {turns}')

    currentNode.value = sum
    currentNode.gatherTurns = turns


def convert_contiguous_capture_tiles_to_gather_capture_plan(
        map: MapBase,
        rootTiles: typing.Iterable[Tile],
        tiles: typing.Set[Tile],
        negativeTiles: TileSet | None,
        searchingPlayer: int,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        useTrueValueGathered: bool = True,
        includeGatherPriorityAsEconValues: bool = False,
        includeCapturePriorityAsEconValues: bool = True,
        captures: typing.Set[Tile] | None = None,
        viewInfo=None,
) -> GatherCapturePlan:
    """

    @param map:
    @param rootTiles:
    @param tiles:
    @param negativeTiles:
    @param searchingPlayer:
    @param priorityMatrix:
    @param useTrueValueGathered: if True, the gathered_value will be the RAW army that ends up on the target tile(s) rather than just the sum of friendly army gathered, excluding army lost traversing enemy tiles.
    @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
    @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
    @param captures: if provided, route a TSP to try to capture these tiles as best as possible
    @param viewInfo: if included, gather values will be written the viewInfo debug output
    @return:
    """
    # ignore = None
    # if captures:
    #     ignore = captures.difference(rootTiles)

    # rootNodes = build_mst_from_root_and_contiguous_tiles(map, rootTiles, tiles, ignoreTiles=captures)

    rootNodes = build_capture_mst_from_root_and_contiguous_tiles(map, tiles.union(captures), searchingPlayer=searchingPlayer)  #, ignoreTiles=ignore

    plan = GatherCapturePlan.build_from_root_nodes(
        map,
        rootNodes,
        negativeTiles,
        searchingPlayer,
        onlyCalculateFriendlyArmy=not useTrueValueGathered,
        priorityMatrix=priorityMatrix,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        captures=captures,
        viewInfo=viewInfo,
        cloneNodes=False,
    )

    return plan

    # logs = []
    # totalTurns, totalValue = recalculate_tree_values(
    #     logs,
    #     rootNodes,
    #     negativeTiles,
    #     startTilesDict={},
    #     searchingPlayer=searchingPlayer,
    #     teams=MapBase.get_teams_array(map),
    #     priorityMatrix=priorityMatrix,
    #     shouldAssert=False,
    # )
    #
    # return GatherCapturePlan(
    #     rootNodes,
    #     map,
    #     econValue=0.0,
    #     turnsTotalInclCap=totalTurns,
    #     gatherValue=totalValue,
    #     gatherCapturePoints=totalValue,  # TODO
    #     gatherTurns=totalTurns,  # TODO
    #     requiredDelay=0,
    #     friendlyCityCount=0  # TODO
    # )


def convert_contiguous_tile_tree_to_gather_capture_plan(
        map: MapBase,
        rootTiles: typing.Iterable[Tile],
        tiles: TileSet,
        negativeTiles: TileSet | None,
        searchingPlayer: int,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        useTrueValueGathered: bool = True,
        includeGatherPriorityAsEconValues: bool = False,
        includeCapturePriorityAsEconValues: bool = True,
        viewInfo=None,
) -> GatherCapturePlan:
    """
    For use when the gather capture plan does not fork in any way. Will JUST build nodes to the root tiles.

    @param map:
    @param rootTiles:
    @param tiles:
    @param negativeTiles:
    @param searchingPlayer:
    @param priorityMatrix:
    @param useTrueValueGathered: if True, the gathered_value will be the RAW army that ends up on the target tile(s) rather than just the sum of friendly army gathered, excluding army lost traversing enemy tiles.
    @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
    @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
    @param viewInfo: if included, gather values will be written the viewInfo debug output
    @return:
    """

    rootNodes = build_mst_from_root_and_contiguous_tiles(map, rootTiles, tiles, searchingPlayer=searchingPlayer)

    plan = GatherCapturePlan.build_from_root_nodes(
        map,
        rootNodes,
        negativeTiles,
        searchingPlayer,
        onlyCalculateFriendlyArmy=not useTrueValueGathered,
        priorityMatrix=priorityMatrix,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        viewInfo=viewInfo,
        cloneNodes=False,
    )

    return plan


def build_mst_from_root_and_contiguous_tiles(map: MapBase, rootTiles: typing.Iterable[Tile], tiles: TileSet, maxDepth: int = 1000, ignoreTiles: typing.Iterable[Tile] | None = None, searchingPlayer: int = -1) -> typing.List[GatherTreeNode]:
    """Does NOT calculate values"""

    if searchingPlayer == -1:
        searchingPlayer = map.player_index

    visited = MapMatrixSet(map, ignoreTiles)

    q = deque()
    for tile in rootTiles:
        q.appendleft((tile, None, None, 0))

    if not q:
        return []

    rootNodes = []
    tile: Tile
    fromTile: Tile | None
    fromNode: GatherTreeNode | None
    while q:
        (tile, fromTile, fromNode, fromDepth) = q.pop()
        if visited.raw[tile.tile_index]:
            continue
        if fromTile:
            # break and continue in the next loop. The double loop lets us be hyper efficient here
            q.append((tile, fromTile, fromNode, fromDepth))
            break

        newNode = GatherTreeNode(tile, fromTile)
        rootNodes.append(newNode)
        visited.raw[tile.tile_index] = True

        for t in tile.movable:
            if t in tiles:
                q.appendleft((t, tile, newNode, 1))

    while q:
        (tile, fromTile, fromNode, fromDepth) = q.pop()
        if visited.raw[tile.tile_index]:
            continue
        if fromDepth > maxDepth:
            break

        newNode = GatherTreeNode(tile, fromTile)
        visited.raw[tile.tile_index] = True

        fromNode.children.append(newNode)

        for t in tile.movable:
            if t in tiles:
                if t.player == searchingPlayer:
                    q.appendleft((t, tile, newNode, fromDepth + 1))
                else:
                    q.append((t, tile, newNode, fromDepth + 1))

    return rootNodes


def build_capture_mst_from_root_and_contiguous_tiles_old(map: MapBase, tiles: TileSet, searchingPlayer: int, ignoreTiles: typing.Iterable[Tile] | None = None) -> typing.List[GatherTreeNode]:
    """Does NOT calculate values"""
    visited = MapMatrixSet(map, ignoreTiles)

    q: SearchUtils.HeapQueue[typing.Tuple[int, Tile, Tile | None, GatherTreeNode | None, int]] = SearchUtils.HeapQueue()

    teams = map.team_ids_by_player_index
    searchingTeam = teams[searchingPlayer]

    for tile in tiles:
        army = tile.army
        if teams[tile.player] != searchingTeam:
            army = 0 - tile.army
        else:
            continue
        # army -= 1
        q.put((army, tile, None, None, 0))

        # newNode = GatherTreeNode(tile, None)

    if not q:
        return []

    tile: Tile
    fromTile: Tile | None
    fromNode: GatherTreeNode | None

    nodes = []

    valLookup = {}

    while q:
        (army, tile, fromTile, fromNode, fromDepth) = q.get()
        if visited.raw[tile.tile_index]:
            continue
        # if fromDepth > maxDepth:
        #     break

        newNode = GatherTreeNode(tile, fromTile)
        nodes.append(newNode)
        visited.raw[tile.tile_index] = True

        if fromNode is not None:
            fromNode.children.append(newNode)
            newNode.toGather = fromNode

        # valLookup[newNode.tile] = army

        for t in tile.movable:
            if t in tiles:
                if teams[t.player] != searchingTeam:
                    nextArmy = army + 0 - t.army
                else:
                    nextArmy = army + t.army
                nextArmy -= 1

                q.put((nextArmy, t, tile, newNode, fromDepth + 1))

    roots = []
    # q2 = deque()
    for r in nodes:
        if r.toTile is None:
            # q2.appendleft(r)
            # rootArmy = valLookup[r.tile]
            roots.append(r)
    #
    # while q2:
    #     r = q2.pop()
    #
    #     if teams[r.tile.player] != searchingPlayer:
    #         # if r.toGather is not None:
    #         #     r.toGather.children.remove(r)
    #         #
    #         for c in r.children:
    #             q2.appendleft(c)
    #         continue
    #     elif r.toTile is None:
    #         roots.append(r)

    return roots


def build_capture_mst_from_root_and_contiguous_tiles(map: MapBase, tiles: typing.Set[Tile], searchingPlayer: int, ignoreTiles: typing.Iterable[Tile] | None = None) -> typing.List[GatherTreeNode]:
    """Does NOT calculate values"""
    dists = MapMatrix(map)
    teams = map.team_ids_by_player_index
    searchingTeam = teams[searchingPlayer]

    qq: typing.Deque[typing.Tuple[Tile, int]] = deque()

    # islands = FastDisjointSet()
    # for t in tiles:
    #     # found = dsIntForest.find(t.tile_index)
    #     for adj in t.movable:
    #         if adj.player == t.player:
    #             islands.merge(adj.tile_index, t.tile_index)
    #
    # islandIntSets: typing.List[typing.Set[int]] = islands.subsets()
    # mm = MapMatrix(map, None)
    # for islandSet in islandIntSets:
    #     for memberIdx in islandSet:
    #         mm.raw[memberIdx] = islandSet

    for tile in tiles:
        if teams[tile.player] != searchingTeam:
            continue
        # army -= 1
        qq.appendleft((tile, 0))

    if not qq:
        raise Exception(f'build_capture_mst_from_root_and_contiguous_tiles cannot be used when there are no friendly tiles to searchingPlayer {searchingPlayer} included. \r\ntiles {" | ".join([f"{t.x},{t.y}" for t in sorted(tiles)])}')
        # randTile = next(iter(tiles))
        # logbook.info(f'build_capture_mst_from_root_and_contiguous_tiles using randTile {randTile} as distance seed because no friendly tile found....?')
        # qq.appendleft((randTile, 0))

    maxDistTile = None
    maxDist = -1

    unvisited = tiles.copy()

    while qq:
        tile, dist = qq.pop()
        if dists.raw[tile.tile_index] is not None:
            continue

        unvisited.discard(tile)

        dists.raw[tile.tile_index] = dist
        if dist > maxDist:
            maxDist = dist
            maxDistTile = tile

        for movable in tile.movable:
            if movable in tiles:
                qq.appendleft((movable, dist + 1))

    if unvisited:
        logbook.warn(f'the input tiles were not fully connected to one another. disconnected tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(unvisited)])}')
        if USE_DEBUG_ASSERTS:
            raise Exception(f'the input tiles were not fully connected to one another. disconnected tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(unvisited)])}')

        frTiles = [t for t in tiles if t.player == searchingPlayer]
        addPath = SearchUtils.a_star_find(frTiles, goal=next(iter(unvisited)), noLog=True)
        if addPath is None:
            raise Exception(f'Unable to recover disconnected inputs, aStar find was unable to find a path to reconnect.')
        tiles.update(addPath.tileList)
        return build_capture_mst_from_root_and_contiguous_tiles(map, tiles, searchingPlayer, ignoreTiles)

    if USE_DEBUG_ASSERTS:
        for tile in tiles:
            dist = dists.raw[tile.tile_index]
            if dist is None:
                if USE_DEBUG_ASSERTS:
                    logbook.info(f'{tile} had dist None???? build_capture_mst_from_root_and_contiguous_tiles inputs: '
                                 f'\r\n    searchingPlayer {searchingPlayer}'
                                 f'\r\n    tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(tiles)])}')
                dists.raw[tile.tile_index] = maxDist

    q: SearchUtils.HeapQueue[typing.Tuple[float, int, Tile, Tile | None, GatherTreeNode | None, int]] = SearchUtils.HeapQueue()

    for tile in tiles:
        if teams[tile.player] == searchingTeam:
            continue

        army = 0 - tile.army
        d = dists.raw[tile.tile_index]
        if d is None:
            if USE_DEBUG_ASSERTS:
                logbook.info(f'{tile} had dist None???? build_capture_mst_from_root_and_contiguous_tiles inputs: '
                             f'\r\n    searchingPlayer {searchingPlayer}'
                             f'\r\n    tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(tiles)])}')
            d = maxDist
        q.put((-d + 0.01, army, tile, None, None, 0))

        # newNode = GatherTreeNode(tile, None)

    if not q.queue:
        return []

    tile: Tile
    fromTile: Tile | None
    fromNode: GatherTreeNode | None

    nodes = []
    visitedNodes = MapMatrix(map, None)

    # valLookup = {}

    while q.queue:
        (thing, army, tile, fromTile, fromNode, fromDepth) = q.get()
        node = visitedNodes.raw[tile.tile_index]
        if node is not None:
            continue
        # logbook.info(f'popped ({thing}) {tile} <- {fromTile}  ({army}a)')
        # if fromDepth > maxDepth:
        #     break

        if node is None:
            node = GatherTreeNode(tile, fromTile)
            node.gatherTurns = fromDepth
            visitedNodes.raw[tile.tile_index] = node
        node.data = army
        nodes.append(node)

        if fromNode is not None:
            fromNode.children.append(node)
            node.toGather = fromNode

        # valLookup[node.tile] = army

        for t in tile.movable:
            if t in tiles:
                if teams[t.player] != searchingTeam:
                    nextArmy = army + 0 - t.army
                else:
                    nextArmy = army + t.army
                nextArmy -= 1

                # TODO thing - 0.5??? This works for straight lines but wtf does it output for diverged capture paths...?
                q.put(((thing - dists.raw[t.tile_index]) / 2, nextArmy, t, tile, node, fromDepth + 1))

    roots = []
    # q2 = deque()
    for r in nodes:
        if r.toTile is None:
            # q2.appendleft(r)
            # rootArmy = valLookup[r.tile]
            roots.append(r)
    #
    # while q2:
    #     r = q2.pop()
    #
    #     if teams[r.tile.player] != searchingPlayer:
    #         # if r.toGather is not None:
    #         #     r.toGather.children.remove(r)
    #         #
    #         for c in r.children:
    #             q2.appendleft(c)
    #         continue
    #     elif r.toTile is None:
    #         roots.append(r)

    return roots


def _prune_bad(curNode: GatherTreeNode, searchingTeam: int, teams: typing.List[int], nodeLookup: typing.Dict[Tile, GatherTreeNode]):
    bestChild = None
    bestArmy = -10000
    for child in curNode.children:
        army = child.tile.army
        if teams[child.tile.player] != searchingTeam:
            army = 0 - child.tile.army
        army -= 1
        if army > bestArmy:
            bestChild = child
            bestArmy = army
            continue

    if bestChild is not None:
        curNode.children.remove(bestChild)
        curNode.toGather = bestChild
        if teams[bestChild.tile.player] != searchingTeam or bestChild.toGather is not None:
            _prune_bad(bestChild, searchingTeam, teams, nodeLookup)
        bestChild.children.append(curNode)
        bestChild.toGather = None
    else:
        raise Exception(f'uh oh, no best child for {curNode}')
    # curNode.toGather = None


# def _swap_gather_order(curNode: GatherTreeNode, searchingTeam: int, teams: typing.List[int], nodeLookup: typing.Dict[Tile, GatherTreeNode]):
#     bestChild = None
#     bestArmy = -10000
#     for child in curNode.children:
#         army = child.tile.army
#         if teams[child.tile.player] != searchingTeam:
#             army = 0 - child.tile.army
#         army -= 1
#         if army > bestArmy:
#             bestChild = child
#             bestArmy = army
#             continue
#
#     if bestChild is not None:
#         curNode.children.remove(bestChild)
#         curNode.toGather = bestChild
#         if teams[bestChild.tile.player] != searchingTeam or bestChild.toGather is not None:
#             _swap_gather_order(bestChild, searchingTeam, teams, nodeLookup)
#         bestChild.children.append(curNode)
#         bestChild.toGather = None
#     else:
#         raise Exception(f'uh oh, no best child for {curNode}')
#     # curNode.toGather = None


def build_mst_to_root_from_path_and_contiguous_tiles(map: MapBase, rootPath: Path, tiles: TileSet, maxDepth: int, reversePath: bool = False, searchingPlayer: int = -1) -> GatherTreeNode:
    """Does NOT calculate values"""
    inputList = rootPath.tileList

    rootTiles = build_mst_from_root_and_contiguous_tiles(map, rootTiles=inputList, tiles=tiles, maxDepth=maxDepth, searchingPlayer=searchingPlayer)

    if reversePath:
        rootTiles = list(reversed(rootTiles))

    prev = None
    # if not reversePath:
    for node in rootTiles:
        if prev:
            # logbook.info(f'setting {node.tile} fromGather to {prev.tile}')
            # logbook.info(f'appending {node.tile} to {prev.tile}s children')
            logbook.info(f'setting {prev.tile} fromGather to {node.tile}')
            logbook.info(f'appending {prev.tile} to {node.tile}s children')
            node.children.append(prev)
            prev.toTile = node.tile
            prev.toGather = node
        prev = node

    return rootTiles[-1]


def prune_raw_connected_nodes_to_turns__dfs(
        rootTiles: typing.Set[Tile],
        tilesBeingPruned: typing.Set[Tile],
        toTurns: int,
        asPlayer: int,
        weightMatrix: MapMatrixInterface[float],
        negativeTiles: TileSet | None = None,
        logDebug: bool = True
):
    startCount = len(tilesBeingPruned)
    start = time.perf_counter()
    while len(tilesBeingPruned) - len(rootTiles) > toTurns:
        def pruneIter() -> Tile:
            visited = set()
            # Create two stacks

            s1 = []
            # s2 = []

            # Push root to first stack
            s1.extend(rootTiles)
            prunable = []

            # Run while first stack is not empty
            while s1:
                # Pop an item from s1 and
                # append it to s2
                tile = s1.pop()

                if tile in visited:
                    # then there are two ways to get to it? Prunable...? No that would make one of the two (both?) of the sources potentially prunable.
                    continue

                # s2.append(tile)
                visited.add(tile)

                # Push left and right children of
                # removed item to s1
                anyIncl = False
                for adj in tile.movable:
                    if adj not in visited and adj in tilesBeingPruned:
                        anyIncl = True
                        s1.append(adj)

                if not anyIncl:
                    prunable.append(tile)

            # if not prunable.

            prunable.sort(key=lambda t: weightMatrix.raw[t.tile_index])

            return prunable[0]

        tileToPrune = pruneIter()
        if logDebug:
            logbook.info(f'  pruning {tileToPrune} {weightMatrix.raw[tileToPrune.tile_index]:.2f}a, left {len(tilesBeingPruned)}, leftRoot {len(rootTiles)} | len(tilesBeingPruned) - len(rootTiles) {len(tilesBeingPruned) - len(rootTiles)} > {toTurns} toTurns')
        rootTiles.discard(tileToPrune)
        tilesBeingPruned.discard(tileToPrune)

        if len(rootTiles) == 0:
            raise Exception(f'pruned root tiles to 0 tiles remaining...? len tiles {len(tilesBeingPruned)} vs startCount {startCount}...?')

    logbook.info(f'prune_raw_connected_nodes_to_turns__dfs took {time.perf_counter() - start:.5f}s to go from {startCount} to {len(tilesBeingPruned)}')



def prune_raw_connected_nodes_to_turns__bfs(
        rootTiles: typing.Set[Tile],
        tilesBeingPruned: typing.Set[Tile],
        toTurns: int,
        asPlayer: int,
        weightMatrix: MapMatrixInterface[float],
        negativeTiles: TileSet | None = None,
        logDebug: bool = True
):
    startCount = len(tilesBeingPruned)
    start = time.perf_counter()
    while len(tilesBeingPruned) - len(rootTiles) > toTurns:
        def pruneIter() -> Tile:
            visited = set()
            # Create two stacks

            s1 = deque()
            # s2 = []

            # Push root to first stack
            for t in rootTiles:
                s1.append((t, None))
            # s1.extend(rootTiles)
            prunable = set()

            # Run while first stack is not empty
            while s1:
                # Pop an item from s1 and
                # append it to s2
                tile, fromTile = s1.popleft()

                if tile in visited:
                    # then there are two ways to get to it? Prunable...? No that would make one of the two (both?) of the sources potentially prunable.
                    continue

                # s2.append(tile)
                visited.add(tile)

                # Push left and right children of
                # removed item to s1
                anyIncl = False
                movable = [t for t in tile.movable]
                # movable = tile.movable
                random.shuffle(movable)
                # for adj in tile.movable:
                for adj in movable:
                    if adj in tilesBeingPruned:
                        if adj not in visited:
                            anyIncl = True
                            s1.append((adj, tile))
                        # elif adj is not fromTile:
                        #     prunable.add(adj)

                if not anyIncl:
                    prunable.add(tile)

            # if not prunable.

            prunableL = sorted(prunable, key=lambda t: weightMatrix.raw[t.tile_index])

            return prunableL[0]

        tileToPrune = pruneIter()
        if logDebug:
            logbook.info(f'  pruning {tileToPrune} {weightMatrix.raw[tileToPrune.tile_index]:.2f}a, left {len(tilesBeingPruned)}, leftRoot {len(rootTiles)} | len(tilesBeingPruned) - len(rootTiles) {len(tilesBeingPruned) - len(rootTiles)} > {toTurns} toTurns')
        rootTiles.discard(tileToPrune)
        tilesBeingPruned.discard(tileToPrune)

        if len(rootTiles) == 0:
            raise Exception(f'pruned root tiles to 0 tiles remaining...? len tiles {len(tilesBeingPruned)} vs startCount {startCount}...?')

    logbook.info(f'prune_raw_connected_nodes_to_turns__dfs took {time.perf_counter() - start:.5f}s to go from {startCount} to {len(tilesBeingPruned)}')



# # An iterative function to do postorder
# # traversal of a given binary tree
# def postOrderIterative(root):
#     if root is None:
#         return
#
#         # Create two stacks
#     s1 = []
#     s2 = []
#
#     # Push root to first stack
#     s1.append(root)
#
#     # Run while first stack is not empty
#     while s1:
#
#         # Pop an item from s1 and
#         # append it to s2
#         node = s1.pop()
#         s2.append(node)
#
#         # Push left and right children of
#         # removed item to s1
#         if node.left:
#             s1.append(node.left)
#         if node.right:
#             s1.append(node.right)
#
#             # Print all elements of second stack
#     while s2:
#         node = s2.pop()
#         print(node.data, end=" ")

# An iterative function to do postorder
# traversal of a given binary tree
def postOrderIterative(rootTiles: typing.Iterable[Tile]) -> typing.List[Tile]:
    visited = set()
    # Create two stacks

    s1 = []
    s2 = []

    # Push root to first stack
    s1.extend(rootTiles)
    prunable = []

    # Run while first stack is not empty
    while s1:
        # Pop an item from s1 and
        # append it to s2
        tile = s1.pop()

        if tile in visited:
            continue

        s2.append(tile)
        visited.add(tile)

        # Push left and right children of
        # removed item to s1
        anyIncl = False
        for adj in tile.movable:
            if adj not in visited:
                anyIncl = True
                s1.append(adj)

        if not anyIncl:
            prunable.append(tile)



    #         # Print all elements of second stack
    # while s2:
    #     node = s2.pop()
    #     print(node.data, end=" ")

    return list(reversed(s2))


def build_max_value_gather_tree_linking_specific_nodes(
        map: MapBase,
        rootTiles: typing.Set[Tile],
        tiles: typing.Iterable[Tile],
        valueMatrix: MapMatrixInterface[float],
        asPlayer: int = -1,
        negativeTiles: TileSet | None = None,
        useTrueValueGathered: bool = True,
        includeGatherPriorityAsEconValues: bool = False,
        includeCapturePriorityAsEconValues: bool = True,
        pruneToTurns: int | None = None,
        skipTiles: TileSet | None = None,
        viewInfo=None,
) -> GatherCapturePlan:
    """
    When you want to gather some specific tiles.

    Currently just shits out a steiner tree that includes ALL the requested nodes, with no pruning, along with the optimal capture path into targets.

    Does calculate gather tree values.

    @param map:
    @param rootTiles: The tile(s) that will be the destination(s) of the gather.
    @param tiles: The tiles that must be included in the gather.
    @param asPlayer:
    @param valueMatrix: the raw value matrix used for gathering. Should include the army gathered, as well as the equivalent value of capturing enemy tiles (as compared to gathering army).
    @param negativeTiles: The negative tile set, as with any other gather. Does not bypass the capture/gather priority matrix values.
    @param useTrueValueGathered: if True, the gathered_value will be the RAW army that ends up on the target tile(s) rather than just the sum of friendly army gathered, excluding army lost traversing enemy tiles.
    @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
    @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
    @param pruneToTurns: if provided, will prune to turns (with branch pruning)
    @param skipTiles: tiles to skip
    @param viewInfo: if provided, debug output will be written to the view info tile zones.
    @return:
    """
    startTime = time.perf_counter()

    if asPlayer == -1:
        asPlayer = map.player_index

    steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, rootTiles.union(tiles), weightMod=valueMatrix, searchingPlayer=asPlayer, baseWeight=10000, bannedTiles=skipTiles)

    outputTiles = steinerNodes
    if pruneToTurns is not None:
        outputTiles = set(steinerNodes)
        prune_raw_connected_nodes_to_turns__bfs(rootTiles, outputTiles, pruneToTurns, asPlayer, valueMatrix, negativeTiles)


        # inclTiles = set(steinerNodes)
        # if viewInfo:
        #     viewInfo.add_map_zone(inclTiles, (0, 155, 255), alpha=88)
        # value, outputTiles = KruskalsSpanningGather.cutesy_chatgpt_gather(map, pruneToTurns, rootTiles, asPlayer, valueMatrix, tilesToInclude=inclTiles, viewInfo=viewInfo)
        # if viewInfo:
        #     viewInfo.add_map_zone(outputTiles, (255, 255, 0), alpha=75)

    plan = convert_contiguous_tile_tree_to_gather_capture_plan(
        map,
        rootTiles=rootTiles,
        tiles=outputTiles,
        negativeTiles=negativeTiles,
        searchingPlayer=asPlayer,
        priorityMatrix=valueMatrix,
        useTrueValueGathered=useTrueValueGathered,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        # viewInfo=viewInfo,
    )

    usedTime = time.perf_counter() - startTime
    logbook.info(f'build_max_value_gather_tree_linking_specific_nodes complete in {usedTime:.4f}s with {plan}')

    return plan


def build_gather_capture_pure_value_matrix(
        map: MapBase,
        asPlayer: int,
        negativeTiles: TileSet | None,
        gatherMatrix: MapMatrixInterface[float] | None,
        captureMatrix: MapMatrixInterface[float] | None,
        useTrueValueGathered: bool = False,
        prioritizeCaptureHighArmyTiles: bool = False,
        logDebug: bool = False
) -> MapMatrixInterface[float]:
    """

    @param map:
    @param asPlayer:
    @param negativeTiles:
    @param gatherMatrix: Priority values for gathered tiles. Only applies to friendly tiles.
    @param captureMatrix: Priority values for captured tiles. Only applies to non-friendly tiles.
    @param prioritizeCaptureHighArmyTiles: If true, we'll value pathing through large army enemy territory over pathing through small army enemy territory.
    @param useTrueValueGathered: if true, enemy tiles will 'subtract' in the output matrix. Cannot be combined with 'prioritizeCaptureHighArmyTiles'
    @param logDebug:
    @return:
    """
    # baseCostOffset = map.largest_army_tile.army + 5
    baseCostOffset = 0.0
    weightMatrix = MapMatrix(map, 0.0 - baseCostOffset)
    for t in map.get_all_tiles():
        # positive weights are not allowed...? Need to find the max and offset, presumably?
        if negativeTiles is not None and t in negativeTiles:
            weightMatrix.raw[t.tile_index] = 0.0
        elif map.is_tile_on_team_with(t, asPlayer):
            weightMatrix.raw[t.tile_index] += t.army - 1
            if gatherMatrix:
                weightMatrix.raw[t.tile_index] += gatherMatrix.raw[t.tile_index]
        else:
            if useTrueValueGathered:
                weightMatrix.raw[t.tile_index] -= t.army + 1
            elif prioritizeCaptureHighArmyTiles:
                weightMatrix.raw[t.tile_index] += t.army

            if captureMatrix:
                weightMatrix.raw[t.tile_index] += captureMatrix.raw[t.tile_index]
        if logDebug:
            logbook.info(f'tile {t} weight: {weightMatrix.raw[t.tile_index]:.3f}')

    return weightMatrix


def gather_approximate_turns_to_tiles(
        map: MapBase,
        rootTiles: typing.List[Tile],
        approximateTargetTurns: int,
        asPlayer: int = -1,
        maxTurns: int = 2000,
        minTurns: int = 2,
        gatherMatrix: MapMatrixInterface[float | None] = None,
        captureMatrix: MapMatrixInterface[float | None] = None,
        negativeTiles: TileSet | None = None,
        prioritizeCaptureHighArmyTiles: bool = False,
        skipTiles: TileSet | None = None,
        useTrueValueGathered: bool = True,
        includeGatherPriorityAsEconValues: bool = False,
        includeCapturePriorityAsEconValues: bool = True,
        logDebug: bool = False,
        viewInfo=None,
) -> GatherCapturePlan | None:
    """
    When you want to gather a max amount to some specific tile in some rough number of turns.
    PCST impl currently.

    @param map:
    @param approximateTargetTurns: The turns to get the gather to be close to.
    @param maxTurns: The max number of turns the gather can be.
    @param minTurns: The min number of turns the gather can be.
    @param rootTiles: The tile that will be the destination of the gather.
    @param asPlayer:
    @param gatherMatrix: Priority values for gathered tiles. Only applies to friendly tiles.
    @param captureMatrix: Priority values for captured tiles. Only applies to non-friendly tiles.
    @param prioritizeCaptureHighArmyTiles: If true, we'll value pathing through large army enemy territory over pathing through small army enemy territory.
    @param negativeTiles: The negative tile set, as with any other gather. Does not bypass the capture/gather priority matrix values.
    @param skipTiles: Tiles to treat as mountains
    @param useTrueValueGathered: if True, the gathered_value will be the RAW army that ends up on the target tile(s) rather than just the sum of friendly army gathered, excluding army lost traversing enemy tiles.
    @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
    @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
    @param logDebug:
    @param viewInfo: if provided, debug output will be written to the view info tile zones.
    @return:
    """
    startTime = time.perf_counter()

    if asPlayer == -1:
        asPlayer = map.player_index

    weightMatrix = MapMatrix(map, 0.0)

    for t in map.get_all_tiles():
        if map.is_tile_on_team_with(t, asPlayer):
            # weightMatrix.raw[t.tile_index] += t.army
            if gatherMatrix:
                weightMatrix.raw[t.tile_index] += gatherMatrix.raw[t.tile_index]
        else:
            # if prioritizeCaptureHighArmyTiles:
            #     weightMatrix.raw[t.tile_index] += t.army
            # else:
            #     weightMatrix.raw[t.tile_index] -= t.army

            if captureMatrix:
                weightMatrix.raw[t.tile_index] += captureMatrix.raw[t.tile_index]

        if logDebug:
            logbook.info(f'tile {t} weight: {weightMatrix.raw[t.tile_index]:.3f}')

    steinerNodes = GatherSteiner.get_prize_collecting_gather_mapmatrix(
        map,
        asPlayer,
        approximateTargetTurns,
        maxTurns,
        gatherMatrix,
        captureMatrix,
        rootTiles,
        skipTiles=skipTiles,
        negativeTiles=negativeTiles,
        prioritizeCaptureHighArmyTiles=prioritizeCaptureHighArmyTiles)

    if not steinerNodes:
        usedTime = time.perf_counter() - startTime
        logbook.info(f'gather_approximate_turns_to_tile complete in {usedTime:.4f}s with NO PLAN')
        return None

    plan = convert_contiguous_tile_tree_to_gather_capture_plan(
        map,
        rootTiles=rootTiles,
        tiles=steinerNodes,
        negativeTiles=negativeTiles,
        searchingPlayer=asPlayer,
        priorityMatrix=weightMatrix,
        useTrueValueGathered=useTrueValueGathered,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        viewInfo=viewInfo,
    )
    usedTime = time.perf_counter() - startTime
    logbook.info(f'gather_approximate_turns_to_tile complete in {usedTime:.4f}s with {plan}')

    return plan


def gath_set_quick(
        map: MapBase,
        targetTurns: int,
        rootTiles: typing.Set[Tile],
        searchingPlayer: int,
        valueMatrix: MapMatrixInterface[float],
        tilesToIncludeIfPossible: typing.Iterable[Tile] | None = None,
        negativeTiles: TileSet | None = None,
        useTrueValueGathered: bool = True,
        includeGatherPriorityAsEconValues: bool = False,
        includeCapturePriorityAsEconValues: bool = True,
        skipTiles: TileSet | None = None,
        viewInfo: ViewInfo | None = None,
) -> GatherCapturePlan:
    if tilesToIncludeIfPossible is not None:
        visited = {t.tile_index for t in tilesToIncludeIfPossible}
        toTryToInclude = [t for t in tilesToIncludeIfPossible]
    else:
        visited = set()
        toTryToInclude = []

    toSort = (t for t in map.get_all_tiles() if t.tile_index not in visited and map.is_tile_on_team_with(t, searchingPlayer))

    friendlySorted = sorted(
        toSort,
        key=lambda t: valueMatrix.raw[t.tile_index] if negativeTiles is None or t not in negativeTiles else 0.0,
        reverse=True)

    toIdx = targetTurns - len(toTryToInclude)
    for t in friendlySorted[0:toIdx]:
        visited.add(t.tile_index)
        toTryToInclude.append(t)

    # searchSet = FastDisjointSet()
    # for t in toTryToInclude:
    #     searchSet.add(t.tile_index)
    #     for mv in t.movable:
    #         if mv.tile_index in visited:
    #             searchSet.merge_fast(t.tile_index, mv.tile_index)
    #
    # sets = searchSet.subsets()
    # setsWithArmy = []
    # for gathSet in sets:
    #     armyTotal = 0
    #     for tIdx in gathSet:
    #         t = map.tiles_by_index[tIdx]
    #         armyTotal += t.army
    #     if gatherRewardMatrix:
    #         for tIdx in gathSet:
    #             armyTotal += gatherRewardMatrix.raw[tIdx]
    #
    #     setsWithArmy.append((armyTotal, gathSet))
    # setsWithArmySorted = sorted(setsWithArmy, reverse=True)

    # TODO do something, probably calculate the shortest highish value path between all sets, perhaps?
    #  Then build a minimum spanning tree joining all of the sets? Then prune that minimum spanning tree, but forceably leave root tiles and cities out of the prune, or something?
    #  Then SHIP IT

    setTiles = toTryToInclude

    gcp = build_max_value_gather_tree_linking_specific_nodes(
        map,
        rootTiles=rootTiles,
        tiles=setTiles,
        asPlayer=searchingPlayer,
        valueMatrix=valueMatrix,
        negativeTiles=negativeTiles,
        useTrueValueGathered=useTrueValueGathered,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        pruneToTurns=targetTurns,
        skipTiles=skipTiles,
        viewInfo=viewInfo
    )

    return gcp


def _dump_log_entries(logEntries: typing.List[str]):
    logbook.info('\r\n' + '\r\n'.join(logEntries))