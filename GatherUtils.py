import logging
import time
import typing
from collections import deque
from queue import PriorityQueue

import DebugHelper
import KnapsackUtils
import SearchUtils
from DataModels import Move, GatherTreeNode
from MapMatrix import MapMatrix
from Path import Path
from SearchUtils import where
from ViewInfo import ViewInfo
from base.client.map import Tile, MapBase

USE_DEBUG_ASSERTS = False


T = typing.TypeVar('T')

class TreeBuilder(typing.Generic[T]):
    def __init__(self):
        self.tree_builder_prioritizer: typing.Callable[[Tile, T], T | None] = None
        self.tree_builder_valuator: typing.Callable[[Tile, T], typing.Any | None] = None
        """The value function when finding path extensions to the spanning tree"""

        self.tree_knapsacker_valuator: typing.Callable[[Path], int] = None
        """For getting the values of tree nodes to shove in the knapsack to build the subtree iteration"""


def knapsack_gather_iteration(
        turns: int,
        valuePerTurnPathPerTile: typing.Dict[Tile, typing.List[Path]],
        shouldLog: bool = False,
        valueFunc: typing.Callable[[Path], int] | None = None
) -> typing.Tuple[int, typing.List[Path]]:
    if valueFunc is None:
        def value_func(path: Path) -> int:
            return int(path.value * 10)
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

    toLog = []
    # if shouldLog:
    toLog.append(f"Feeding solve_multiple_choice_knapsack {len(paths)} paths turns {turns}:")
    if shouldLog:
        for i, path in enumerate(paths):
            toLog.append(
                f"{i}:  group[{str(path.start.tile)}] value {path.value} length {path.length} path {path.toString()}")

    totalValue, maxKnapsackedPaths = KnapsackUtils.solve_multiple_choice_knapsack(paths, turns, weights, values, groups)
    toLog.append(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")

    logging.info('\n'.join(toLog))
    return totalValue, maxKnapsackedPaths


def get_sub_knapsack_gather(
        map,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        valueFunc,
        baseCaseFunc,
        maxTime: float,
        remainingTurns: int,
        fullTurns: int,
        # gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        noNeutralCities,
        negativeTiles,
        skipTiles,
        searchingPlayer,
        priorityFunc,
        skipFunc,
        ignoreStartTile,
        incrementBackward,
        preferNeutral,
        useTrueValueGathered: bool = False,
        priorityMatrix: MapMatrix[float] | None = None,
        shouldLog: bool = False
) -> typing.Tuple[int, typing.List[Path]]:
    if len(startTilesDict) < remainingTurns // 10:
        logging.info(f"DUE TO SMALL SEARCH START TILE COUNT {len(startTilesDict)}, FALLING BACK TO FINDING AN INITIAL MAX-VALUE-PER-TURN PATH FOR {remainingTurns} (fullTurns {fullTurns})")
        valuePerTurnPath = SearchUtils.breadth_first_dynamic_max(
            map,
            startTilesDict,
            valueFunc,
            1000000,
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
            useGlobalVisitedSet=True,
            priorityMatrix=priorityMatrix,
            logResultValues=shouldLog,
            ignoreNonPlayerArmy=not useTrueValueGathered,
            ignoreIncrement=True)
        if valuePerTurnPath is None:
            logging.info(f'didnt find a max path searching to startTiles {"  ".join([str(tile) for tile in startTilesDict])}?')
            return 0, []
        return valuePerTurnPath.value, [valuePerTurnPath]

    valuePerTurnPathPerTilePerDistance = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
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
        skipFunc=skipFunc,
        ignoreStartTile=ignoreStartTile,
        incrementBackward=incrementBackward,
        preferNeutral=preferNeutral,
        priorityMatrix=priorityMatrix,
        logResultValues=shouldLog,
        ignoreNonPlayerArmy=not useTrueValueGathered,
        ignoreIncrement=True
        )

    gatheredArmy, maxPaths = knapsack_gather_iteration(remainingTurns, valuePerTurnPathPerTilePerDistance, shouldLog=shouldLog)
    return gatheredArmy, maxPaths


def build_tree_node_lookup(
        newPaths: typing.List[Path],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        teams: typing.List[int],
        # skipTiles: typing.Set[Tile],
        shouldLog: bool = False
) -> typing.Dict[Tile, GatherTreeNode]:
    gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {}
    return extend_tree_node_lookup(
        newPaths,
        gatherTreeNodeLookup,
        startTilesDict,
        searchingPlayer,
        teams,
        set(),
        shouldLog=shouldLog,
        force=True
    )

def extend_tree_node_lookup(
        newPaths: typing.List[Path],
        gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        teams: typing.List[int],
        negativeTiles: typing.Set[Tile],
        useTrueValueGathered: bool = False,
        shouldLog: bool = False,
        force: bool = False
) -> typing.Dict[Tile, GatherTreeNode]:
    """
    Returns the remaining turns after adding the paths, and the new tree nodes list, and the new startingTileDict.
    If a path in the list does not produce any army, returns None for remaining turns.

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
            logging.error(
                f"TERMINATING extend_tree_node_lookup PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
            continue

        if shouldLog:
            logging.info(
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

        if pathNode.tile in gatherTreeNodeLookup:
            currentGatherTreeNode = gatherTreeNodeLookup[pathNode.tile]
        else:
            startTilesDictStringed = "\r\n      ".join([repr(t) for t in startTilesDict.items()])
            gatherTreeNodeLookupStringed = "\r\n      ".join([repr(t) for t in gatherTreeNodeLookup.items()])
            newPathsStringed = "\r\n      ".join([repr(t) for t in newPaths])
            msg = (f'Should never get here with no root tree pathNode. pathNode.tile {str(pathNode.tile)} dist {distance} in path {str(valuePerTurnPath)}.\r\n'
                        f'  Path was {repr(valuePerTurnPath)}\r\n'
                        f'  startTiles was\r\n      {startTilesDictStringed}\r\n'
                        f'  gatherTreeNodeLookup was\r\n      {gatherTreeNodeLookupStringed}\r\n'
                        f'  newPaths was\r\n      {newPathsStringed}')
            logging.error(msg)

            if not force:
                raise AssertionError(msg)

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
        while pathNode is not None:
            runningTrunkDist += 1
            newDist = distance + addlDist
            distanceLookup[pathNode.tile] = newDist
            # skipTiles.add(pathNode.tile)
            # if viewInfo:
            #    viewInfo.bottomRightGridText[pathNode.tile.x][pathNode.tile.y] = newDist
            nextGatherTreeNode = GatherTreeNode(pathNode.tile, currentGatherTreeNode.tile, newDist)

            tileEffect = 1

            if negativeTiles is None or pathNode.tile not in negativeTiles:
                if teams[pathNode.tile.player] == teams[searchingPlayer]:
                    tileEffect -= pathNode.tile.army
                elif useTrueValueGathered:
                    tileEffect += pathNode.tile.army
            runningTrunkValue -= tileEffect
            nextGatherTreeNode.value = runningValue
            nextGatherTreeNode.trunkValue = runningTrunkValue
            nextGatherTreeNode.trunkDistance = runningTrunkDist
            nextGatherTreeNode.gatherTurns = valuePerTurnPath.length - addlDist + 1
            runningValue += tileEffect
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
        while True:
            curGatherTreeNode.value += valuePerTurnPath.value
            curGatherTreeNode.gatherTurns += valuePerTurnPath.length
            if curGatherTreeNode.fromTile is None:
                break
            nextGatherTreeNode = gatherTreeNodeLookup.get(curGatherTreeNode.fromTile, None)
            if nextGatherTreeNode is None:
                startTilesDictStringed = "\r\n      ".join([repr(t) for t in startTilesDict.items()])
                gatherTreeNodeLookupStringed = "\r\n      ".join([repr(t) for t in gatherTreeNodeLookup.items()])
                newPathsStringed = "\r\n      ".join([repr(t) for t in newPaths])
                fromDist = distanceLookup.get(curGatherTreeNode.fromTile, None)
                curDist = distanceLookup.get(curGatherTreeNode.tile, None)
                msg = (f'curGatherTreeNode {repr(curGatherTreeNode)} HAD A FROM TILE {repr(curGatherTreeNode.fromTile)} fromDist [{fromDist}] curDist [{curDist}] THAT WAS NOT IN THE gatherTreeNodeLookup...?\r\n'
                        f'  Path was {repr(valuePerTurnPath)}\r\n'
                        f'  startTiles was\r\n      {startTilesDictStringed}\r\n'
                        f'  gatherTreeNodeLookup was\r\n      {gatherTreeNodeLookupStringed}\r\n'
                        f'  newPaths was\r\n      {newPathsStringed}')
                if not force:
                    raise AssertionError(msg)
                else:
                    logging.error(msg)
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
            logging.info(
                f"TERMINATING build_next_level_start_dict PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
            # in theory this means you fucked up your value function; your value function should return none when the path under evaluation isn't even worth considering
            hadInvalidPath = True
            continue
        logging.info(
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
            # logging.info(
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
    #     logging.info(f'shifting {str(rootNode.tile)} from {oldDist} to {oldDist + added}')
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

        logging.info(f"Sub-knap ({time.perf_counter() - startTime:.3f} into search) looking for the next path with remainingTurns {turnsToTry} (fullTurns {fullTurns})")
        newGatheredArmy, newPaths = get_sub_knapsack_gather(
            map,
            startTilesDict,
            valueFunc,
            baseCaseFunc,
            0.1,
            remainingTurns=turnsToTry,
            fullTurns=fullTurns,
            noNeutralCities=True,
            negativeTiles=negativeTiles,
            skipTiles=skipTiles,
            searchingPlayer=searchingPlayer,
            priorityFunc=priorityFunc,
            skipFunc=skipFunc,
            ignoreStartTile=ignoreStartTile,
            incrementBackward=incrementBackward,
            preferNeutral=preferNeutral,
            shouldLog=shouldLog,
            useTrueValueGathered=useTrueValueGathered,
        )

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
                logging.info(
                    f'bad paths were found in the plan with {expectedLeftOverTurns} remaining turns, we should probably not continue searching')
                probablyBad = True
            elif expectedLeftOverTurns != turnsLeft:
                logging.info(
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
                logging.error(
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
        # gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode],
        remainingTurns: int,
        fullTurns: int,
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
        incrementBackward=True,
        preferNeutral=False,
        viewInfo=None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        priorityMatrix: MapMatrix[float] | None = None,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog=False
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

    teams = MapBase.get_teams_array(map)

    turnsSoFar = 0
    totalValue = 0
    newStartTilesDict = startTilesDict.copy()
    gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {}
    for tile, data in startTilesDict.items():
        (_, dist) = data
        gatherTreeNodeLookup[tile] = GatherTreeNode(tile, fromTile=None, stateObj=dist)

    prevBest = 0

    lastPrunedTo = 0

    startTime = time.perf_counter()

    while lastPrunedTo < fullTurns:
        itr.add(1)
        turnsToGather = fullTurns - turnsSoFar
        logging.info(f'Sub Knap (iter {itr.value} {time.perf_counter() - startTime:.3f} in) turns {turnsToGather} sub_knapsack, fullTurns {fullTurns}, turnsSoFar {turnsSoFar}')
        newGatheredArmy, newPaths = get_sub_knapsack_gather(
            map,
            newStartTilesDict,
            valueFunc,
            baseCaseFunc,
            1000,
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
        )

        if len(newPaths) == 0:
            logging.info('no new paths found, breaking knapsack stuff')
            break

        turnsUsedByNewPaths = 0
        for path in newPaths:
            turnsUsedByNewPaths += path.length
        calculatedLeftOverTurns = remainingTurns - turnsUsedByNewPaths
                
        extend_tree_node_lookup(
            newPaths,
            gatherTreeNodeLookup,
            newStartTilesDict,
            searchingPlayer,
            teams,
            useTrueValueGathered=useTrueValueGathered,
            negativeTiles=negativeTiles,
            shouldLog=shouldLog
        )

        # for path in newPaths:
        #     rootNode = gatherTreeNodeLookup.get(path.start.tile, None)
        #     if rootNode is not None:
        #         (startPriorityObject, distance) = newStartTilesDict[rootNode.tile]
        #         add_tree_nodes_to_start_tiles_dict_recurse(
        #             rootNode,
        #             newStartTilesDict,
        #             searchingPlayer,
        #             calculatedLeftOverTurns,
        #             baseCaseFunc,
        #             dist=distance
        #         )

        rootNodes = [gatherTreeNodeLookup[tile] for tile in origStartTilesDict]

        if USE_DEBUG_ASSERTS:
            recalcTotalValue, recalcTotalTurns = recalculate_tree_values(
                rootNodes,
                negativeTiles,
                origStartTilesDict,
                searchingPlayer,
                teams,
                onlyCalculateFriendlyArmy=not useTrueValueGathered,
                viewInfo=viewInfo,
                shouldAssert=True)

            if prevBest < recalcTotalValue:
                logging.info(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} > {prevBest}!')
            elif prevBest > 0 and prevBest > recalcTotalValue:
                raise AssertionError(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} WORSE than prev {prevBest}? This should be impossible.')
            # if recalcTotalValue != newGatheredArmy + valueSoFar:
            #     if not SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
            #         raise AssertionError(f'recalculated gather value {recalcTotalValue} didnt match algo output gather value {newGatheredArmy}')
            if recalcTotalTurns != turnsUsedByNewPaths + turnsSoFar:
                msg = f'recalc gather turns {recalcTotalTurns} didnt match algo turns turnsUsedByNewPaths {turnsUsedByNewPaths} + turnsSoFar {turnsSoFar}'
                if USE_DEBUG_ASSERTS:
                    # TODO figure this shit the fuck out, what the fuck
                    raise AssertionError(msg)
                elif viewInfo:
                    viewInfo.addAdditionalInfoLine(msg)

        totalTurns = turnsUsedByNewPaths + turnsSoFar

        # keep only the maxPerIteration best from each gather level

        pruneToTurns = lastPrunedTo + maxPerIteration
        # maxPerIteration = max(maxPerIteration // 2, 1)
        maxPerIteration = maxPerIteration // 2 + 1

        # if we're at the end of the gather, gather 1 level at a time for the last phase to make sure we dont miss any optimal branches.

        # if fullTurns - pruneToTurns < max(maxPerIteration, 12):
        if fullTurns - pruneToTurns <= maxPerIteration * 2:
            maxPerIteration = 1
            pruneToTurns = lastPrunedTo + maxPerIteration

        logging.info(f'pruning current {totalValue}v @ {totalTurns}t to {pruneToTurns}t')
        totalTurns, totalValue, rootNodes = prune_mst_to_turns_with_values(
            rootNodes,
            turns=pruneToTurns,
            searchingPlayer=searchingPlayer,
            viewInfo=viewInfo,
            noLog=not shouldLog,
            gatherTreeNodeLookupToPrune=gatherTreeNodeLookup,
            tileDictToPrune=newStartTilesDict,
            # parentPruneFunc=lambda t, prunedNode: _start_tiles_prune_helper(startTilesDict, t, prunedNode)
        )

        if USE_DEBUG_ASSERTS:
            recalcTotalValue, recalcTotalTurns = recalculate_tree_values(
                rootNodes,
                negativeTiles,
                newStartTilesDict,
                searchingPlayer,
                teams,
                onlyCalculateFriendlyArmy=not useTrueValueGathered,
                viewInfo=viewInfo,
                shouldAssert=USE_DEBUG_ASSERTS
            )

            if recalcTotalTurns != totalTurns:
                raise AssertionError(f'Pruned turns {totalTurns} didnt match recalculated, {recalcTotalTurns}')
            if recalcTotalValue != totalValue:
                raise AssertionError(f'Pruned value {totalValue} didnt match recalculated, {recalcTotalValue}')

            if totalTurns > pruneToTurns:
                raise AssertionError(f'Pruned turns {totalTurns} was more than the amount requested, {pruneToTurns}')

        # newStartTilesDict = origStartTilesDict.copy()
        for path in newPaths:
            rootNode = gatherTreeNodeLookup.get(path.start.tile, None)
            if rootNode is not None:
                (startPriorityObject, distance) = newStartTilesDict[rootNode.tile]
                add_tree_nodes_to_start_tiles_dict_recurse(
                    rootNode,
                    newStartTilesDict,
                    searchingPlayer,
                    calculatedLeftOverTurns,
                    baseCaseFunc,
                    dist=distance
                )

        # _debug_print_diff_between_start_dict_and_GatherTreeNodes(gatherTreeNodeLookup, newStartTilesDict)

        lastPrunedTo = pruneToTurns
        turnsSoFar = totalTurns

    return totalValue, rootNodes


def _start_tiles_prune_helper(
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        parentTile: Tile,
        gatherNodeBeingPruned: GatherTreeNode
):
    prioDistTuple = startTilesDict.get(parentTile, None)

    if prioDistTuple is not None:
        prios, oldDist = prioDistTuple
        logging.info(f'pruning {str(parentTile)} from {oldDist} to {oldDist - gatherNodeBeingPruned.gatherTurns} (pruned {str(gatherNodeBeingPruned.tile)} gatherTurns {gatherNodeBeingPruned.gatherTurns})')
        startTilesDict[parentTile] = (prios, oldDist - gatherNodeBeingPruned.gatherTurns)


def _debug_print_diff_between_start_dict_and_tree_nodes(
        gatherTreeNodes: typing.Dict[Tile, GatherTreeNode],
        startDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]]
):
    if len(gatherTreeNodes) != len(startDict):
        logging.info(f'~~startDict: {len(startDict)}, vs GatherTreeNodes {len(gatherTreeNodes)}')
    else:
        logging.info(f'startDict: {len(startDict)}, vs GatherTreeNodes {len(gatherTreeNodes)}')

    for tile, node in sorted(gatherTreeNodes.items()):
        if tile not in startDict:
            path = Path()
            curNode = node
            while curNode is not None:
                path.add_next(curNode.tile)
                curNode = gatherTreeNodes.get(curNode.fromTile, None)
            logging.info(f'  missing from startDict: {str(tile)}  ({str(node)}), path {str(path)}')

    for tile, val in sorted(startDict.items()):
        (prioThing, dist) = val
        if tile not in gatherTreeNodes:
            logging.info(f'  missing from GatherTreeNodes: {str(tile)}  (dist {dist}, [{str(prioThing)}])')


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
        priorityMatrix: MapMatrix[float] | None = None,
        shouldLog=False
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
        shouldLog=shouldLog,
    )

    return rootNodes


def knapsack_levels_backpack_gather_with_value(
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
        ignoreStartTile=False,
        incrementBackward=True,
        preferNeutral=False,
        viewInfo: ViewInfo | None =None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        includeGatherTreeNodesThatGatherNegative=False,
        shouldLog=DebugHelper.IS_DEBUGGING,
        useRecurse=False,
        priorityMatrix: MapMatrix[float] | None = None
) -> typing.Tuple[int, typing.List[GatherTreeNode]]:
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
    @return:
    """
    shouldLog = False
    startTime = time.perf_counter()
    negativeTilesOrig = negativeTiles
    if negativeTiles is not None:
        negativeTiles = negativeTiles.copy()
    else:
        negativeTiles = set()

    teams = MapBase.get_teams_array(map)
        # negativeTilesOrig = set()
    # q = PriorityQueue()

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

    if shouldLog:
        logging.info(f"Trying knapsack-bfs-gather. Turns {turns}. Searching player {searchingPlayer}")
    if valueFunc is None:

        if shouldLog:
            logging.info("Using default valueFunc")

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

            if negArmySum >= 0 and not includeGatherTreeNodesThatGatherNegative:
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
                logging.info(f'VALUE {str(currentTile)} : {str(prioObj)}')
            return prioObj

        valueFunc = default_value_func_max_gathered_per_turn

    if priorityFunc is None:
        if shouldLog:
            logging.info("Using default priorityFunc")

        def default_priority_func(nextTile, currentPriorityObject):
            (
                threatDist,
                depthDist,
                realDist,
                negPrioTilesPerTurn,
                negGatheredSum,
                negArmySum,
                #xSum,
                #ySum,
                numPrioTiles
            ) = currentPriorityObject
            negArmySum += 1
            negGatheredSum += 1
            if nextTile not in negativeTiles:
                if teams[searchingPlayer] == teams[nextTile.player]:
                    negArmySum -= nextTile.army
                    negGatheredSum -= nextTile.army
                # # this broke gather approximation, couldn't predict actual gather values based on this
                # if nextTile.isCity:
                #    negArmySum -= turns // 3
                else:
                    negArmySum += nextTile.army
                    if useTrueValueGathered:
                        negGatheredSum += nextTile.army

            if priorityMatrix is not None:
                negGatheredSum += priorityMatrix[nextTile]
                # negArmySum += priorityMatrix[nextTile]

            # if nextTile.player != searchingPlayer and not (nextTile.player == -1 and nextTile.isCity):
            #    negDistanceSum -= 1
            # hacks us prioritizing further away tiles
            # if distPriorityMap is not None:
            #     negDistanceSum -= distPriorityMap[nextTile.x][nextTile.y]
            if priorityTiles is not None and nextTile in priorityTiles:
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
                #xSum + nextTile.x,
                #ySum + nextTile.y,
                numPrioTiles
            )
            if shouldLog:
                logging.info(f'PRIO {str(nextTile)} : {str(prioObj)}')
            # logging.info("prio: nextTile {} got realDist {}, negNextArmy {}, negDistanceSum {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
            return prioObj

        priorityFunc = default_priority_func

    if baseCaseFunc is None:
        if shouldLog:
            logging.info("Using default baseCaseFunc")

        def default_base_case_func(tile, startingDist):
            startArmy = 0
            # we would like to not gather to an enemy tile without killing it, so must factor it into the path. army value is negative for priority, so use positive for enemy army.
            # if useTrueValueGathered and tile.player != searchingPlayer:
            #     if shouldLog:
            #         logging.info(
            #             f"tile {tile.toString()} was not owned by searchingPlayer {searchingPlayer}, adding its army {tile.army}")
            #     startArmy = tile.army

            initialDistance = 0
            if distPriorityMap is not None:
                initialDistance = distPriorityMap[tile.x][tile.y]
            prioObj = (
                0 - initialDistance,
                startingDist,
                0,
                0,
                0,
                startArmy,
                # tile.x,
                # tile.y,
                0
            )
            if shouldLog:
                logging.info(f"BASE CASE: {str(tile)} -> {str(prioObj)}")
            return prioObj

        baseCaseFunc = default_base_case_func

    startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]] = {}
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

        if shouldLog:
            logging.info(f"Including tile {tile.x},{tile.y} in startTiles at distance {distance}")

    origStartTilesDict = startTilesDict.copy()

    itr = SearchUtils.Counter(0)

    if not useRecurse:
        totalValue, rootNodes = _knapsack_levels_gather_iterative_prune(
            itr=itr,
            map=map,
            startTilesDict=startTilesDict,
            # gatherTreeNodeLookup=gatherTreeNodeLookup,
            remainingTurns=turns,
            fullTurns=turns,
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
            priorityMatrix=priorityMatrix,
            useTrueValueGathered=useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            shouldLog=shouldLog,
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
            shouldLog=shouldLog
        )

        rootNodes: typing.List[GatherTreeNode] = list(where(gatherTreeNodeLookup.values(), lambda treeNode: treeNode.fromTile is None))

        totalValue, totalTurns = recalculate_tree_values(
            rootNodes,
            negativeTilesOrig,
            origStartTilesDict,
            searchingPlayer=searchingPlayer,
            teams=teams,
            onlyCalculateFriendlyArmy=not useTrueValueGathered,
            viewInfo=viewInfo,
            shouldAssert=True)

    logging.info(
        f"Concluded knapsack_levels_backpack_gather with {itr.value} path segments, value {totalValue}. Duration: {time.perf_counter() - startTime:.3f}")
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

    logging.info(f"Trying greedy-bfs-gather. Turns {turns}. Searching player {searchingPlayer}")
    if valueFunc is None:
        logging.info("Using default valueFunc")

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
        logging.info("Using default priorityFunc")

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
                negDistanceSum -= distPriorityMap[nextTile.x][nextTile.y]
            if priorityTiles is not None and nextTile in priorityTiles:
                numPrioTiles += 1
            realDist += 1
            # logging.info("prio: nextTile {} got realDist {}, negNextArmy {}, negDistanceSum {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
            return realDist, numPrioTiles / realDist, negGatheredSum, negArmySum, negDistanceSum, dist + 1, xSum + nextTile.x, ySum + nextTile.y, numPrioTiles

        priorityFunc = default_priority_func

    if baseCaseFunc is None:
        logging.info("Using default baseCaseFunc")

        def default_base_case_func(tile, startingDist):
            startArmy = 0
            # we would like to not gather to an enemy tile without killing it, so must factor it into the path. army value is negative for priority, so use positive for enemy army.
            if useTrueValueGathered and tile.player != searchingPlayer:
                logging.info(
                    f"tile {tile.toString()} was not owned by searchingPlayer {searchingPlayer}, adding its army {tile.army}")
                startArmy = tile.army

            initialDistance = 0
            if distPriorityMap is not None:
                initialDistance = distPriorityMap[tile.x][tile.y]

            logging.info(
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
        logging.info(f"Including tile {tile.x},{tile.y} in startTiles at distance {distance}")

    gatherTreeNodeLookup = {}
    itr = 0
    remainingTurns = turns
    valuePerTurnPath: Path | None = None
    origStartTiles = startTilesDict.copy()
    while remainingTurns > 0:
        if valuePerTurnPath is not None:
            if valuePerTurnPath.tail.tile.army <= 1 or valuePerTurnPath.tail.tile.player != searchingPlayer:
                logging.info(
                    f"TERMINATING greedy-bfs-gather PATH BUILDING DUE TO TAIL TILE {valuePerTurnPath.tail.tile.toString()} THAT WAS < 1 OR NOT OWNED BY US. PATH: {valuePerTurnPath.toString()}")
                break
            logging.info(
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
            curPrioObj = startPriorityObject
            addlDist = 1
            currentGatherTreeNode = None

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
                logging.info(
                    f"Including tile {node.tile.x},{node.tile.y} in startTilesDict at newDist {newDist}  (distance {distance} addlDist {addlDist})")
                # if viewInfo:
                #    viewInfo.bottomRightGridText[node.tile.x][node.tile.y] = newDist
                nextGatherTreeNode = GatherTreeNode(node.tile, currentGatherTreeNode.tile, newDist)
                nextGatherTreeNode.value = runningValue
                nextGatherTreeNode.gatherTurns = 1
                runningValue -= node.tile.army
                currentGatherTreeNode.children.append(nextGatherTreeNode)
                currentGatherTreeNode = nextGatherTreeNode
                gatherTreeNodeLookup[node.tile] = currentGatherTreeNode
                addlDist += 1
                node = node.next

        logging.info(f"Searching for the next path with remainingTurns {remainingTurns}")
        valuePerTurnPath = SearchUtils.breadth_first_dynamic_max(
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

    rootNodes = list(where(gatherTreeNodeLookup.values(), lambda gatherTreeNode: gatherTreeNode.fromTile is None))

    totalValue, turnsUsed = recalculate_tree_values(
        rootNodes,
        negativeTilesOrig,
        origStartTiles,
        searchingPlayer=searchingPlayer,
        teams=teams,
        onlyCalculateFriendlyArmy=not useTrueValueGathered,
        viewInfo=viewInfo)

    logging.info(
        f"Concluded greedy-bfs-gather with {itr} path segments, value {totalValue}. Duration: {time.perf_counter() - startTime:.3f}")
    return totalValue, turnsUsed, rootNodes


def recalculate_tree_values(
        rootNodes: typing.List[GatherTreeNode],
        negativeTiles: typing.Set[Tile] | None,
        startTilesDict: typing.Dict[Tile, object],
        searchingPlayer: int,
        teams: typing.List[int],
        onlyCalculateFriendlyArmy=False,
        viewInfo=None,
        shouldAssert=False
) -> typing.Tuple[int, int]:
    totalValue = 0
    totalTurns = 0
    logging.info('recalcing treenodes....')
    for currentNode in rootNodes:
        _recalculate_tree_values_recurse(
            currentNode,
            negativeTiles,
            startTilesDict,
            searchingPlayer,
            teams,
            onlyCalculateFriendlyArmy,
            viewInfo,
            shouldAssert)
        totalValue += currentNode.value
        totalTurns += currentNode.gatherTurns

    # find the leaves
    queue = deque()
    for treeNode in rootNodes:
        if shouldAssert and treeNode.trunkValue != 0:
            raise AssertionError(f'root node {str(treeNode)} trunk value should have been 0 but was {treeNode.trunkValue}')
        if shouldAssert and treeNode.trunkDistance != 0:
            raise AssertionError(f'root node {str(treeNode)} trunk dist should have been 0 but was {treeNode.trunkDistance}')
        treeNode.trunkValue = 0
        treeNode.trunkDistance = 0
        queue.appendleft(treeNode)

    while not len(queue) == 0:
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
                if trunkValue != child.trunkValue:
                    raise AssertionError(f'node {str(child)} trunk value should have been {trunkValue} but was {child.trunkValue}')
                if trunkDistance != child.trunkDistance:
                    raise AssertionError(f'node {str(child)} trunk dist should have been {trunkDistance} but was {child.trunkDistance}')
            child.trunkValue = trunkValue
            child.trunkDistance = trunkDistance
            # if viewInfo is not None:
            #     viewInfo.bottomLeftGridText[child.tile.x][child.tile.y] = child.trunkValue
            queue.appendleft(child)

    return totalValue, totalTurns


def _recalculate_tree_values_recurse(
        currentNode: GatherTreeNode,
        negativeTiles: typing.Set[Tile] | None,
        startTilesDict: typing.Dict[Tile, object],
        searchingPlayer: int,
        teams: typing.List[int],
        onlyCalculateFriendlyArmy=False,
        viewInfo=None,
        shouldAssert=False
):
    isStartNode = False

    # we leave one node behind at each tile, except the root tile.
    turns = 1
    sum = -1
    if viewInfo:
        viewInfo.midRightGridText[currentNode.tile.x][currentNode.tile.y] = f'v{currentNode.value}'
        viewInfo.bottomMidRightGridText[currentNode.tile.x][currentNode.tile.y] = f'tv{currentNode.trunkValue}'
        viewInfo.bottomRightGridText[currentNode.tile.x][currentNode.tile.y] = f'td{currentNode.trunkDistance}'

        if currentNode.trunkDistance > 0:
            rawValPerTurn = currentNode.value / currentNode.trunkDistance
            trunkValPerTurn = currentNode.trunkValue / currentNode.trunkDistance
            viewInfo.bottomMidLeftGridText[currentNode.tile.x][currentNode.tile.y] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[currentNode.tile.x][currentNode.tile.y] = f'vt{rawValPerTurn:.1f}'

    if currentNode.fromTile is None:
        isStartNode = True
        sum = 0
        turns = 0

    if (negativeTiles is None or currentNode.tile not in negativeTiles) and not isStartNode:
        if teams[currentNode.tile.player] == teams[searchingPlayer]:
            sum += currentNode.tile.army
        elif not onlyCalculateFriendlyArmy:
            sum -= currentNode.tile.army
    for child in currentNode.children:
        _recalculate_tree_values_recurse(
            child,
            negativeTiles,
            startTilesDict,
            searchingPlayer,
            teams,
            onlyCalculateFriendlyArmy,
            viewInfo,
            shouldAssert=shouldAssert)
        sum += child.value
        turns += child.gatherTurns

    # if viewInfo:
    #     viewInfo.bottomRightGridText[currentNode.tile.x][currentNode.tile.y] = sum

    if shouldAssert:
        if currentNode.value != sum:
            raise AssertionError(f'currentNode {str(currentNode)} val {currentNode.value} != recalculated sum {sum}')
        if currentNode.gatherTurns != turns:
            raise AssertionError(f'currentNode {str(currentNode)} turns {currentNode.gatherTurns} != recalculated turns {turns}')

    currentNode.value = sum
    currentNode.gatherTurns = turns


def get_tree_move(
        gathers: typing.List[GatherTreeNode],
        priorityFunc: typing.Callable[[Tile, typing.Tuple | None], typing.Tuple],
        valueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None],
        pop: bool = False
) -> typing.Union[None, Move]:
    if len(gathers) == 0:
        logging.info("get_tree_move... len(gathers) == 0?")
        return None

    # TODO this is just an iterate-all-leaves-and-keep-max function, why the hell are we using a priority queue?
    #  we don't call this often so who cares I guess, but wtf copy paste, normal queue would do fine.
    q = PriorityQueue()

    for gather in gathers:
        basePrio = priorityFunc(gather.tile, None)
        q.put((basePrio, gather))

    lookup = {}

    highestValue = None
    highestValueNode = None
    while q.qsize() > 0:
        (curPrio, curGather) = q.get()
        lookup[curGather.tile] = curGather
        if len(curGather.children) == 0:
            # WE FOUND OUR FIRST MOVE!
            thisValue = valueFunc(curGather.tile, curPrio)
            if (thisValue is not None
                    and curGather.fromTile is not None
                    and (highestValue is None or thisValue > highestValue)
            ):
                highestValue = thisValue
                highestValueNode = curGather
                logging.info(f"new highestValueNode {str(highestValueNode)}!")
        for gather in curGather.children:
            nextPrio = priorityFunc(gather.tile, curPrio)
            q.put((nextPrio, gather))

    if highestValueNode is None:
        return None

    if pop:
        if highestValueNode.fromTile is not None:
            parent = lookup[highestValueNode.fromTile]
            parent.children.remove(highestValueNode)

    highestValueMove = Move(highestValueNode.tile, highestValueNode.fromTile)
    logging.info(f"highestValueMove in get_tree_move was {highestValueMove.toString()}!")
    return highestValueMove


def prune_mst_to_turns(
        rootNodes: typing.List[GatherTreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
) -> typing.List[GatherTreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param turns: The number of turns to prune the MST down to.
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.

    @return: The list same list of rootnodes passed in, modified.
    """
    count, totalValue, rootNodes = prune_mst_to_turns_with_values(
        rootNodes=rootNodes,
        turns=turns,
        searchingPlayer=searchingPlayer,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        invalidMoveFunc=invalidMoveFunc,
    )

    return rootNodes


def prune_mst_to_turns_with_values(
        rootNodes: typing.List[GatherTreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing GatherTreeNode lookup map instead of rebuilding...?
     MAKE A GATHER CLASS THAT STORES THE ROOT NODES, THE NODE LOOKUP, THE VALUE, THE TURNS

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param turns: The number of turns to prune the MST down to.
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.value <= 0:
                return True
            if node.tile.player != searchingPlayer and len(node.children) == 0:
                return True
        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: GatherTreeNode, curPrioObj: typing.Tuple | None):
        rawValPerTurn = -100
        # trunkValPerTurn = -100
        # trunkBehindNodeValuePerTurn = -100
        try:
            rawValPerTurn = node.value / node.gatherTurns
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkBehindNodeValuePerTurn = trunkValPerTurn
            # trunkBehindNodeValue = node.trunkValue - node.value
            # trunkBehindNodeValuePerTurn = trunkBehindNodeValue / node.trunkDistance
        except:
            pass
        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile.x][node.tile.y] = f'v{node.value}'
            viewInfo.bottomMidRightGridText[node.tile.x][node.tile.y] = f'tv{node.trunkValue}'
            viewInfo.bottomRightGridText[node.tile.x][node.tile.y] = f'td{node.trunkDistance}'

            # viewInfo.bottomMidLeftGridText[node.tile.x][node.tile.y] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile.x][node.tile.y] = f'vt{rawValPerTurn:.1f}'

        return rawValPerTurn, node.value, 0 - node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=lambda node, _, turnsLeft, curValue: turnsLeft <= turns,
        pruneOrderFunc=pruneFunc,
        invalidMoveFunc=invalidMoveFunc,
        pruneOverrideFunc=lambda node, _, turnsLeft, curValue: turnsLeft - node.gatherTurns < turns,
        viewInfo=viewInfo,
        noLog=noLog,
        pruneBranches=True,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        parentPruneFunc=parentPruneFunc,
    )


def prune_mst_to_tiles(
        rootNodes: typing.List[GatherTreeNode],
        tiles: typing.Set[Tile],
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
) -> typing.List[GatherTreeNode]:
    """
    Prunes nodes from an MST until a set of specific nodes are encountered. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param tiles: The tiles that should be force-kept within the spanning tree
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.

    @return: The list same list of rootnodes passed in, modified.
    """
    count, totalValue, rootNodes = prune_mst_to_tiles_with_values(
        rootNodes=rootNodes,
        tiles=tiles,
        searchingPlayer=searchingPlayer,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        invalidMoveFunc=invalidMoveFunc,
    )

    return rootNodes


def prune_mst_to_tiles_with_values(
        rootNodes: typing.List[GatherTreeNode],
        tiles: typing.Set[Tile],
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes nodes from an MST until a set of specific nodes are encountered. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing GatherTreeNode lookup map instead of rebuilding...?
     MAKE A GATHER CLASS THAT STORES THE ROOT NODES, THE NODE LOOKUP, THE VALUE, THE TURNS

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param tiles: The tiles that should be force-kept within the spanning tree
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.value <= 0:
                return True
            if node.tile.player != searchingPlayer and len(node.children) == 0:
                return True
        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: GatherTreeNode, curPrioObj: typing.Tuple | None):
        rawValPerTurn = -100
        # trunkValPerTurn = -100
        # trunkBehindNodeValuePerTurn = -100
        try:
            rawValPerTurn = node.value / node.gatherTurns
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkBehindNodeValuePerTurn = trunkValPerTurn
            # trunkBehindNodeValue = node.trunkValue - node.value
            # trunkBehindNodeValuePerTurn = trunkBehindNodeValue / node.trunkDistance
        except:
            pass
        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile.x][node.tile.y] = f'v{node.value}'
            viewInfo.bottomMidRightGridText[node.tile.x][node.tile.y] = f'tv{node.trunkValue}'
            viewInfo.bottomRightGridText[node.tile.x][node.tile.y] = f'td{node.trunkDistance}'

            # viewInfo.bottomMidLeftGridText[node.tile.x][node.tile.y] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile.x][node.tile.y] = f'vt{rawValPerTurn:.1f}'

        return rawValPerTurn, node.value, 0 - node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=lambda node, _, turnsLeft, curValue: node.tile in tiles,
        pruneOrderFunc=pruneFunc,
        invalidMoveFunc=invalidMoveFunc,
        pruneOverrideFunc=lambda node, _, turnsLeft, curValue: node.tile in tiles,
        viewInfo=viewInfo,
        noLog=noLog,
        pruneBranches=False,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        parentPruneFunc=parentPruneFunc,
    )


def prune_mst_to_army_with_values(
        rootNodes: typing.List[GatherTreeNode],
        army: int,
        searchingPlayer: int,
        teams: typing.List[int],
        turn: int,
        additionalIncrement: int = 0,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        pruneLargeTilesFirst: bool = False,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param army: The army amount to prune the MST down to
    @param searchingPlayer:
    @param teams: the teams array.
    @param additionalIncrement: if need to gather extra army due to incrementing, include the POSITIVE enemy city increment or NEGATIVE allied increment value here.
    @param turn: the current map turn, used to calculate city increment values.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param pruneLargeTilesFirst: if True (default), then largest tiles will be pruned first allowing this prune to be used to maximize leaving tiles for offense if possible.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    turnIncFactor = (1 + turn) & 1

    cityCounter = SearchUtils.Counter(0 - additionalIncrement)
    cityGatherDepthCounter = SearchUtils.Counter(0)
    citySkipTiles = set()
    for n in rootNodes:
        if (n.tile.isCity or n.tile.isGeneral) and not n.tile.isNeutral:
            if teams[n.tile.player] == [searchingPlayer]:
                citySkipTiles.add(n.tile)

    def cityCounterFunc(node: GatherTreeNode):
        if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node.tile not in citySkipTiles:
            if teams[node.tile.player] == teams[searchingPlayer]:
                cityCounter.add(1)
                # each time we add one of these we must gather all the other cities in the tree first too so we lose that many increment turns + that
                cityGatherDepthCounter.add(node.trunkDistance)
            else:
                cityCounter.add(-1)

        for child in node.children:
            cityCounterFunc(child)

    for n in rootNodes:
        cityCounterFunc(n)

    def setCountersToPruneCitiesRecurse(node: GatherTreeNode):
        for child in node.children:
            setCountersToPruneCitiesRecurse(child)

        if teams[node.tile.player] == teams[searchingPlayer] and (node.tile.isCity or node.tile.isGeneral):
            cityGatherDepthCounter.add(0 - node.trunkDistance)
            cityCounter.add(-1)

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.value <= 0:
                return True
            if node.tile.player != searchingPlayer:
                return True
        invalidMoveFunc = invalid_move_func

    def getCurrentCityIncAmount(gatherTurnsLeft: int) -> int:
        cityIncrementAmount = (cityCounter.value * (gatherTurnsLeft - turnIncFactor)) // 2  # +1 here definitely causes it to under-gather
        cityIncrementAmount -= cityGatherDepthCounter.value // 2
        return cityIncrementAmount

    def untilFunc(node: GatherTreeNode, _, turnsLeft: int, curValue: int):
        turnsLeftIfPruned = turnsLeft - node.gatherTurns

        # act as though we're pruning the city so we can calculate the gather value without it
        setCountersToPruneCitiesRecurse(node)

        cityIncrementAmount = getCurrentCityIncAmount(turnsLeftIfPruned)
        armyLeftIfPruned = curValue - node.value + cityIncrementAmount

        if armyLeftIfPruned < army:
            # not pruning here, put the city increments back
            cityCounterFunc(node)
            return True

        return False

    def pruneLargeTilesFirstFunc(node: GatherTreeNode, curObj) -> typing.Tuple:
        trunkValuePerTurn = node.trunkValue / node.trunkDistance if node.trunkDistance > 0 else 0
        return 0 - node.value, trunkValuePerTurn, node.trunkDistance

    def pruneWorstValuePerTurnFunc(node: GatherTreeNode, curObj) -> typing.Tuple:
        trunkValuePerTurn = node.trunkValue / node.trunkDistance if node.trunkDistance > 0 else 0
        return node.value / node.gatherTurns, trunkValuePerTurn, node.trunkDistance

    prioFunc = pruneLargeTilesFirstFunc
    if not pruneLargeTilesFirst:
        prioFunc = pruneWorstValuePerTurnFunc

    prunedTurns, noCityCalcGathValue, nodes = prune_mst_until(
        rootNodes,
        untilFunc=untilFunc,
        # if we dont include trunkVal/node.trunkDistance we end up keeping shitty branches just because they have a far, large tile on the end.
        pruneOrderFunc=prioFunc,
        # pruneOrderFunc=lambda node, curObj: (node.value, node.trunkValue / node.trunkDistance, node.trunkDistance),
        # pruneOrderFunc=lambda node, curObj: (node.value / node.gatherTurns, node.trunkValue / node.trunkDistance, node.trunkDistance),
        invalidMoveFunc=invalidMoveFunc,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        pruneBranches=True
    )

    finalIncValue = getCurrentCityIncAmount(prunedTurns)
    gathValue = noCityCalcGathValue + finalIncValue

    return prunedTurns, gathValue, nodes


def prune_mst_to_army(
        rootNodes: typing.List[GatherTreeNode],
        army: int,
        searchingPlayer: int,
        teams: typing.List[int],
        turn: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        pruneLargeTilesFirst: bool = False,
) -> typing.List[GatherTreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param army: The army amount to prune the MST down to
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param pruneLargeTilesFirst: if True, will try to prune the largest tiles out first instead of lowest value per turn.
    Useful when pruning a defense to the minimal army set needed for example while leaving large tiles available for other things.

    @return: gatherTurns, gatherValue, rootNodes
    """

    count, totalValue, rootNodes = prune_mst_to_army_with_values(
        rootNodes=rootNodes,
        army=army,
        searchingPlayer=searchingPlayer,
        teams=teams,
        turn=turn,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        invalidMoveFunc=invalidMoveFunc,
        pruneLargeTilesFirst=pruneLargeTilesFirst,
    )

    return rootNodes

#
# def prune_mst_to_max_army_per_turn_with_values(
#         rootNodes: typing.List[GatherTreeNode],
#         minArmy: int,
#         searchingPlayer: int,
#         teams: typing.List[int],
#         viewInfo: ViewInfo | None = None,
#         noLog: bool = True,
#         gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
#         invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
#         allowBranchPrune: bool = True,
# ) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
#     """
#     Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
#     O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
#
#     @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
#     @param minArmy: The minimum army amount to prune the MST down to
#     @param searchingPlayer:
#     @param viewInfo:
#     @param noLog:
#     @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
#     @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
#     @param allowBranchPrune: Optionally, pass false to disable pruning whole branches. Allowing branch prunes produces lower value per turn trees but also smaller trees.
#
#     @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified)
#     """
#     turn = 0  # TODO parameterize
#     turnIncFactor = (1 + turn) & 1
#
#     cityCounter = SearchUtils.Counter(0)
#     cityGatherDepthCounter = SearchUtils.Counter(0)
#     citySkipTiles = set()
#     totalValue = 0
#     totalTurns = 0
#     for n in rootNodes:
#         if (n.tile.isCity or n.tile.isGeneral) and not n.tile.isNeutral:
#             if teams[n.tile.player] == teams[searchingPlayer]:
#                 citySkipTiles.add(n.tile)
#
#         totalTurns += n.gatherTurns
#         totalValue += n.value
#
#     if totalTurns == 0:
#         if viewInfo:
#             viewInfo.addAdditionalInfoLine(f'zero turns gather prune, value {totalValue}')
#         return 0, 0, rootNodes
#
#
#     def cityCounterFunc(node: GatherTreeNode):
#         if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node.tile not in citySkipTiles:
#             if teams[node.tile.player] == teams[searchingPlayer]:
#                 cityCounter.add(1)
#                 # each time we add one of these we must gather all the other cities in the tree first too so we lose that many increment turns + that
#                 cityGatherDepthCounter.add(node.trunkDistance)
#             else:
#                 cityCounter.add(-1)
#
#         for child in node.children:
#             cityCounterFunc(child)
#
#     for n in rootNodes:
#         cityCounterFunc(n)
#
#     def setCountersToPruneCitiesRecurse(node: GatherTreeNode):
#         for child in node.children:
#             setCountersToPruneCitiesRecurse(child)
#
#         if teams[node.tile.player] == teams[searchingPlayer] and (node.tile.isCity or node.tile.isGeneral):
#             cityGatherDepthCounter.add(0 - node.trunkDistance)
#             cityCounter.add(-1)
#
#     if invalidMoveFunc is None:
#         def invalid_move_func(node: GatherTreeNode):
#             if node.value <= 0:
#                 return True
#             if node.tile.player != searchingPlayer:
#                 return True
#         invalidMoveFunc = invalid_move_func
#
#     def getCurrentCityIncAmount(gatherTurnsLeft: int) -> int:
#         cityIncrementAmount = (cityCounter.value * (gatherTurnsLeft - turnIncFactor)) // 2  # +1 here definitely causes it to under-gather
#         cityIncrementAmount -= cityGatherDepthCounter.value // 2
#         return cityIncrementAmount
#
#     totalValue += getCurrentCityIncAmount(totalTurns)
#     curValuePerTurn = SearchUtils.Counter(totalValue / totalTurns)
#
#     def untilFunc(node: GatherTreeNode, _, turnsLeft: int, curValue: int):
#         turnsLeftIfPruned = turnsLeft - node.gatherTurns
#
#         # act as though we're pruning the city so we can calculate the gather value without it
#         setCountersToPruneCitiesRecurse(node)
#
#         cityIncrementAmount = getCurrentCityIncAmount(turnsLeftIfPruned)
#         armyLeftIfPruned = curValue - node.value + cityIncrementAmount
#         if turnsLeftIfPruned == 0:
#             cityCounterFunc(node)
#             return True
#
#         pruneValPerTurn = armyLeftIfPruned / turnsLeftIfPruned
#
#         if pruneValPerTurn < curValuePerTurn.value or armyLeftIfPruned < minArmy:
#             # not pruning here, put the city increments back
#             cityCounterFunc(node)
#             return True
#
#         curValuePerTurn.value = pruneValPerTurn
#         return False
#
#     def pruneOrderFunc(node: GatherTreeNode, curObj):
#         if node.gatherTurns == 0 or node.trunkDistance == 0:
#             msg = f'ERR PRUNE node {repr(node)} had trunkDist {node.trunkDistance} or gatherTurns {node.gatherTurns} of 0...?'
#             # if USE_DEBUG_ASSERTS:
#             if viewInfo:
#                 viewInfo.addAdditionalInfoLine(msg)
#             return -1, -1, -1
#         return (node.value / node.gatherTurns), node.trunkValue / node.trunkDistance, node.trunkDistance
#
#     # def pruneFunc(node: GatherTreeNode, curObj) -> typing.Tuple:
#     #     trunkValuePerTurn = node.trunkValue / node.trunkDistance if node.trunkDistance > 0 else 0
#     #     return node.value / node.gatherTurns, trunkValuePerTurn, node.trunkDistance
#
#     prunedTurns, noCityCalcGathValue, nodes = prune_mst_until(
#         rootNodes,
#         untilFunc=untilFunc,
#         # if we dont include trunkVal/node.trunkDistance we end up keeping shitty branches just because they have a far, large tile on the end.
#         pruneOrderFunc=pruneOrderFunc,
#         # pruneOrderFunc=lambda node, curObj: (node.value, node.trunkValue / node.trunkDistance, node.trunkDistance),
#         # pruneOrderFunc=lambda node, curObj: (node.value / node.gatherTurns, node.trunkValue / node.trunkDistance, node.trunkDistance),
#         invalidMoveFunc=invalidMoveFunc,
#         viewInfo=viewInfo,
#         noLog=noLog,
#         gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
#         pruneBranches=False
#     )
#
#     finalIncValue = getCurrentCityIncAmount(prunedTurns)
#     gathValue = noCityCalcGathValue + finalIncValue
#
#     return prunedTurns, gathValue, nodes


def prune_mst_to_max_army_per_turn_with_values(
        rootNodes: typing.List[GatherTreeNode],
        minArmy: int,
        searchingPlayer: int,
        teams: typing.List[int],
        additionalIncrement: int = 0,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        allowBranchPrune: bool = True,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param minArmy: The minimum army amount to prune the MST down to
    @param searchingPlayer:
    @param teams: the teams array to use when calculating whether a gathered tile adds or subtracts army.
    @param additionalIncrement: if need to gather extra army due to incrementing, include the POSITIVE enemy city increment or NEGATIVE allied increment value here.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param allowBranchPrune: Optionally, pass false to disable pruning whole branches. Allowing branch prunes produces lower value per turn trees but also smaller trees.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified)
    """

    cityCounter = SearchUtils.Counter(0 - additionalIncrement)
    cityGatherDepthCounter = SearchUtils.Counter(0)
    citySkipTiles = set()
    totalValue = 0
    totalTurns = 0
    for n in rootNodes:
        if (n.tile.isCity or n.tile.isGeneral) and not n.tile.isNeutral:
            if teams[n.tile.player] == teams[searchingPlayer]:
                citySkipTiles.add(n.tile)

        totalTurns += n.gatherTurns
        totalValue += n.value

    if totalTurns == 0:
        return 0, 0, rootNodes

    def cityCounterFunc(node: GatherTreeNode):
        if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node.tile not in citySkipTiles:
            if teams[node.tile.player] == teams[searchingPlayer]:
                cityCounter.add(1)
                # each time we add one of these we must gather all the other cities in the tree first too so we lose that many increment turns + that
                cityGatherDepthCounter.add(node.trunkDistance)
            else:
                cityCounter.add(-1)
    iterate_tree_nodes(rootNodes, cityCounterFunc)

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.value <= 0:
                return True
            if node.tile.player != searchingPlayer:
                return True
        invalidMoveFunc = invalid_move_func

    curValuePerTurn = SearchUtils.Counter(totalValue / totalTurns)

    def untilFunc(node: GatherTreeNode, _, turnsLeft: int, curValue: int):
        turnsLeftIfPruned = turnsLeft - node.gatherTurns
        if turnsLeftIfPruned == 0:
            return True
        cityIncrementAmount = cityCounter.value * ((turnsLeftIfPruned - 1) // 2)
        cityIncrementAmount -= cityGatherDepthCounter.value // 2
        armyLeftIfPruned = curValue - node.value + cityIncrementAmount
        pruneValPerTurn = armyLeftIfPruned / turnsLeftIfPruned
        if pruneValPerTurn < curValuePerTurn.value or armyLeftIfPruned < minArmy:
            return True

        if teams[node.tile.player] == teams[searchingPlayer] and (node.tile.isCity or node.tile.isGeneral):
            cityGatherDepthCounter.add(0 - node.trunkDistance)
            cityCounter.add(-1)

        curValuePerTurn.value = pruneValPerTurn
        return False

    def pruneOrderFunc(node: GatherTreeNode, curObj):
        if node.gatherTurns == 0 or node.trunkDistance == 0:
            msg = f'ERR PRUNE node {repr(node)} had trunkDist {node.trunkDistance} or gatherTurns {node.gatherTurns} of 0...?'
            # if USE_DEBUG_ASSERTS:
            if viewInfo:
                viewInfo.addAdditionalInfoLine(msg)
            return -1, -1, -1
        return (node.value / node.gatherTurns), node.trunkValue / node.trunkDistance, node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=untilFunc,
        # if we dont include trunkVal/node.trunkDistance we end up keeping shitty branches just because they have a far, large tile on the end.
        pruneOrderFunc=pruneOrderFunc,
        # pruneOrderFunc=lambda node, curObj: (node.value, node.trunkValue / node.trunkDistance, node.trunkDistance),
        # pruneOrderFunc=lambda node, curObj: (node.value / node.gatherTurns, node.trunkValue / node.trunkDistance, node.trunkDistance),
        invalidMoveFunc=invalidMoveFunc,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        pruneBranches=allowBranchPrune
    )


def prune_mst_to_max_army_per_turn(
        rootNodes: typing.List[GatherTreeNode],
        minArmy: int,
        searchingPlayer: int,
        teams: typing.List[int],
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        allowBranchPrune: bool = True
) -> typing.List[GatherTreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param minArmy: The minimum army amount to prune the MST down to
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param allowBranchPrune: Optionally, pass false to disable pruning whole branches.
    Allowing branch prunes produces lower value per turn trees but also smaller trees.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified).
    """

    count, totalValue, rootNodes = prune_mst_to_max_army_per_turn_with_values(
        rootNodes=rootNodes,
        minArmy=minArmy,
        searchingPlayer=searchingPlayer,
        teams=teams,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        invalidMoveFunc=invalidMoveFunc,
        allowBranchPrune=allowBranchPrune
    )

    return rootNodes


# TODO can implement prune as multiple choice knapsack, optimizing lowest weight combinations of tree prunes instead of highest weight, maybe?
def prune_mst_until(
        rootNodes: typing.List[GatherTreeNode],
        untilFunc: typing.Callable[[GatherTreeNode, typing.Tuple, int, int], bool],
        pruneOrderFunc: typing.Callable[[GatherTreeNode, typing.Tuple | None], typing.Tuple],
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool],
        pruneBranches: bool = False,
        pruneOverrideFunc: typing.Callable[[GatherTreeNode, typing.Tuple, int, int], bool] | None = None,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes excess / bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param untilFunc: Func[curNode, curPriorityObject, GatherTreeNodeCountRemaining, curValue] -> bool (should return False to continue pruning, True to return the tree).
    @param pruneOrderFunc: Func[curNode, curPriorityObject] - min are pruned first
    @param pruneBranches: If true, runs the prune func to prioritize nodes in the middle of the tree, not just leaves.
    @param pruneOverrideFunc: Func[curNode, curPriorityObject, GatherTreeNodeCountRemaining, curValue] -> bool
    If passed, a node popped from the queue will run through this function and if the function returns true, will NOT be pruned.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified).
    """
    start = time.perf_counter()

    nodeMap: typing.Dict[Tile, GatherTreeNode] = {}
    pruneHeap = PriorityQueue()

    def nodeInitializer(current: GatherTreeNode):
        nodeMap[current.tile] = current
        if current.fromTile is not None and (len(current.children) == 0 or pruneBranches):
            # then we're a leaf. Add to heap
            # value = current.trunkValue / max(1, current.trunkDistance)
            value = current.value
            validMove = True
            if invalidMoveFunc(current) and len(current.children) == 0:
                if not noLog:
                    logging.info(
                        f"tile {current.tile.toString()} will be eliminated due to invalid move, army {current.tile.army}")
                validMove = False
            if not noLog:
                logging.info(
                    f"  tile {current.tile.toString()} had value {value:.1f}, trunkDistance {current.trunkDistance}")
            pruneHeap.put((validMove, pruneOrderFunc(current, None), current))

    iterate_tree_nodes(rootNodes, nodeInitializer)

    curValue = 0
    for node in rootNodes:
        curValue += node.value

    count = len(nodeMap) - len(rootNodes)
    if not noLog:
        logging.info(f'MST prune beginning with {count} nodes ({len(pruneHeap.queue)} nodes)')

    childRecurseQueue: typing.Deque[GatherTreeNode] = deque()

    try:
        # now we have all the leaves, smallest value first
        while not pruneHeap.empty():
            validMove, prioObj, current = pruneHeap.get()
            if current.fromTile is None:
                continue

            if current.tile not in nodeMap:
                # already pruned
                continue
            # have to recheck now that we're pruning mid branches
            validMove = not invalidMoveFunc(current)
            if validMove or len(current.children) > 0:
                if untilFunc(current, prioObj, count, curValue):
                    # Then this was a valid move, and we've pruned enough leaves out.
                    # Thus we should break. Otherwise if validMove == 0, we want to keep popping invalid moves off until they're valid again.
                    continue
            else:
                logging.info(f'pruning extra invalid tree node despite untilFunc == True: {str(current)}')

            if not noLog:
                logging.info(f'pruning tree node {str(current)}')

            if pruneOverrideFunc is not None and pruneOverrideFunc(current, prioObj, count, curValue):
                if not noLog:
                    logging.info(f'SKIPPING pruning tree node {str(current)} due to pruneOverrideFunc')
                continue

            # make sure the value of this prune didn't go down, if it did, shuffle it back into the heap with new priority.
            if validMove:
                doubleCheckPrioObj = pruneOrderFunc(current, prioObj)
                if doubleCheckPrioObj > prioObj:
                    pruneHeap.put((validMove, doubleCheckPrioObj, current))
                    if not noLog:
                        logging.info(
                            f'requeued {str(current)} (prio went from {str(prioObj)} to {str(doubleCheckPrioObj)})')
                    continue

            # now remove this leaf from its parent and bubble the value change all the way up
            parent = None
            curValue -= current.value
            parent = nodeMap[current.fromTile]
            realParent = parent

            if parent is not None:
                try:
                    parent.children.remove(current)
                except ValueError:
                    pass
                parent.pruned.append(current)

            while True:
                parent.value -= current.value
                parent.gatherTurns -= current.gatherTurns
                if parentPruneFunc is not None:
                    parentPruneFunc(parent.tile, current)
                if parent.fromTile is None:
                    break
                parent = nodeMap[parent.fromTile]

            childRecurseQueue.append(current)
            while len(childRecurseQueue) > 0:
                toDropFromLookup = childRecurseQueue.popleft()

                if gatherTreeNodeLookupToPrune is not None:
                    gatherTreeNodeLookupToPrune.pop(toDropFromLookup.tile, None)
                if tileDictToPrune is not None:
                    tileDictToPrune.pop(toDropFromLookup.tile, None)
                nodeMap.pop(toDropFromLookup.tile, None)
                count -= 1
                if not noLog:
                    logging.info(
                        f"    popped/pruned BRANCH CHILD {toDropFromLookup.tile.toString()} value {toDropFromLookup.value:.1f} count {count}")
                for child in toDropFromLookup.children:
                    childRecurseQueue.append(child)

            if not noLog:
                logging.info(f"    popped/pruned {current.tile.toString()} value {current.value:.1f} count {count}")

            if realParent is not None and len(realParent.children) == 0 and realParent.fromTile is not None:
                # (value, length) = self.get_prune_point(nodeMap, realParent)
                # value = realParent.trunkValue / max(1, realParent.trunkDistance)
                value = realParent.value
                parentValidMove = True
                if invalidMoveFunc(realParent):
                    logging.info(
                        f"parent {realParent.tile.toString()} will be eliminated due to invalid move, army {realParent.tile.army}")
                    parentValidMove = False

                if not noLog:
                    logging.info(
                        f"  Appending parent {realParent.tile.toString()} (valid {parentValidMove}) had value {value:.1f}, trunkDistance {realParent.trunkDistance}")

                nextPrioObj = pruneOrderFunc(realParent, prioObj)
                pruneHeap.put((parentValidMove, nextPrioObj, realParent))

    except Exception as ex:
        logging.error('prune got an error, dumping state:')

        logging.error(f'rootNodes: {repr(rootNodes)}')
        # logging.error(f'untilFunc: {repr(untilFunc)}')
        # logging.error(f'pruneOrderFunc: {repr(pruneOrderFunc)}')
        # logging.error(f'invalidMoveFunc: {repr(invalidMoveFunc)}')
        logging.error(f'pruneBranches: {repr(pruneBranches)}')
        # logging.error(f'pruneOverrideFunc: {repr(pruneOverrideFunc)}')
        # logging.error(f'viewInfo: {repr(viewInfo)}')
        # logging.error(f'noLog: {repr(noLog)}')
        logging.error(f'gatherTreeNodeLookupToPrune: {repr(gatherTreeNodeLookupToPrune)}')
        logging.error(f'tileDictToPrune: {repr(tileDictToPrune)}')
        raise

    #while not leaves.empty():
    totalValue = 0
    for node in rootNodes:
        # the root tree nodes need + 1 to their value
        # node.value += 1
        totalValue += node.value
    if not noLog:
        logging.info(
            f"  Pruned MST to turns {count} with value {totalValue} in duration {time.perf_counter() - start:.3f}")
    return count, totalValue, rootNodes


def iterate_tree_nodes(
        gatherTreeNodes: typing.List[GatherTreeNode],
        forEachFunc: typing.Callable[[GatherTreeNode], None]
):
    q: typing.Deque[GatherTreeNode] = deque()
    for n in gatherTreeNodes:
        q.append(n)
    while len(q) > 0:
        cur = q.popleft()
        forEachFunc(cur)
        for c in cur.children:
            q.append(c)


def get_tree_leaves(gathers: typing.List[GatherTreeNode]) -> typing.List[GatherTreeNode]:
    # fuck it, do it recursively i'm too tired for this
    combined = []
    for gather in gathers:
        if len(gather.children) == 0:
            if gather.fromTile is not None:
                combined.append(gather)
        else:
            combined.extend(get_tree_leaves(gather.children))

    return combined


def get_tree_leaves_further_than_distance(
        gatherNodes: typing.List[GatherTreeNode],
        distMap: typing.List[typing.List[int]],
        dist: int
) -> typing.List[GatherTreeNode]:
    leaves = get_tree_leaves(gatherNodes)
    leavesGreaterThanDistance = SearchUtils.where(leaves, lambda g: distMap[g.tile.x][g.tile.y] >= dist)
    return leavesGreaterThanDistance
