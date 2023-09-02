import logging
import time
import typing
from collections import deque
from queue import PriorityQueue

import KnapsackUtils
import SearchUtils
from DataModels import Move, TreeNode
from Path import Path
from SearchUtils import where
from ViewInfo import ViewInfo
from base.client.map import Tile, MapBase

USE_DEBUG_ASSERTS = False


def knapsack_gather_iteration(
        turns: int,
        valuePerTurnPathPerTile: typing.Dict[Tile, typing.List[Path]],
        shouldLog: bool = False
) -> typing.Tuple[int, typing.List[Path]]:
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
                values.append(path.value)
                weights.append(path.length)
            groupIdx += 1
    if len(paths) == 0:
        return 0, []

    # if shouldLog:
    logging.info(f"Feeding solve_multiple_choice_knapsack {len(paths)} paths turns {turns}:")
    if shouldLog:
        for i, path in enumerate(paths):
            logging.info(
                f"{i}:  group[{str(path.start.tile)}] value {path.value} length {path.length} path {path.toString()}")

    totalValue, maxKnapsackedPaths = KnapsackUtils.solve_multiple_choice_knapsack(paths, turns, weights, values, groups)
    logging.info(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")
    return totalValue, maxKnapsackedPaths


def get_sub_knapsack_gather(
        map,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        valueFunc,
        baseCaseFunc,
        maxTime: float,
        remainingTurns: int,
        fullTurns: int,
        # treeNodeLookup: typing.Dict[Tile, TreeNode],
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
        shouldLog: bool = False
) -> typing.Tuple[int, typing.List[Path]]:
    logging.info(f"Sub-knap looking for the next path with remainingTurns {remainingTurns} (fullTurns {fullTurns})")

    if len(startTilesDict) < remainingTurns // 5:
        logging.info(f"DUE TO SMALL SEARCH START TILE COUNT {len(startTilesDict)}, FALLING BACK TO FINDING AN INITIAL MAX-VALUE-PER-TURN PATH FOR {remainingTurns} (fullTurns {fullTurns})")
        valuePerTurnPath = SearchUtils.breadth_first_dynamic_max(
            map,
            startTilesDict,
            valueFunc,
            0.1,
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
            logResultValues=shouldLog,
            ignoreNonPlayerArmy=not useTrueValueGathered)
        if valuePerTurnPath is None:
            logging.info(f'didnt find a max path searching to startTiles {"  ".join([str(tile) for tile in startTilesDict])}?')
            return 0, []
        return valuePerTurnPath.value, [valuePerTurnPath]

    valuePerTurnPathPerTilePerDistance = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
        map,
        startTilesDict,
        valueFunc,
        0.1,
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
        logResultValues=shouldLog,
        ignoreNonPlayerArmy=not useTrueValueGathered
        )

    gatheredArmy, maxPaths = knapsack_gather_iteration(remainingTurns, valuePerTurnPathPerTilePerDistance, shouldLog=shouldLog)
    return gatheredArmy, maxPaths


def build_tree_node_lookup(
        newPaths: typing.List[Path],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        # negativeTiles: typing.Set[Tile],
        shouldLog: bool = False
) -> typing.Dict[Tile, TreeNode]:
    treeNodeLookup: typing.Dict[Tile, TreeNode] = {}
    return extend_tree_node_lookup(
        newPaths,
        treeNodeLookup,
        startTilesDict,
        searchingPlayer,
        shouldLog,
        force=True
    )

def extend_tree_node_lookup(
        newPaths: typing.List[Path],
        treeNodeLookup: typing.Dict[Tile, TreeNode],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        useTrueValueGathered: bool = False,
        # negativeTiles: typing.Set[Tile],
        shouldLog: bool = False,
        force: bool = False
) -> typing.Dict[Tile, TreeNode]:
    """
    Returns the remaining turns after adding the paths, and the new tree nodes list, and the new startingTileDict.
    If a path in the list does not produce any army, returns None for remaining turns.

    @param newPaths:
    # @param treeNodeLookup:
    @param searchingPlayer:
    # @param negativeTiles:
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

        if pathNode.tile in treeNodeLookup:
            currentTreeNode = treeNodeLookup[pathNode.tile]
        else:
            if not force:
                raise AssertionError('Should never get here with no root tree pathNode.')
            currentTreeNode = TreeNode(pathNode.tile, None, distance)
            # currentTreeNode.gatherTurns = 1
            treeNodeLookup[pathNode.tile] = currentTreeNode
        treeNodePathAddingOnTo = currentTreeNode
        # runningValue = valuePerTurnPath.value - pathNode.tile.army
        runningValue = valuePerTurnPath.value
        runningTrunkDist = treeNodePathAddingOnTo.trunkDistance
        runningTrunkValue = treeNodePathAddingOnTo.trunkValue
        # if pathNode.tile.player == searchingPlayer:
        #     runningValue -= pathNode.tile.army
        # elif useTrueValueGathered:
        #     runningValue += pathNode.tile.army
        # negativeTiles.add(pathNode.tile)
        # skipping because first tile is actually already on the path
        pathNode = pathNode.next
        # add the new path to startTiles and then search a new path
        while pathNode is not None:
            runningTrunkDist += 1
            newDist = distance + addlDist
            distanceLookup[pathNode.tile] = newDist
            # negativeTiles.add(pathNode.tile)
            # if viewInfo:
            #	viewInfo.bottomRightGridText[pathNode.tile.x][pathNode.tile.y] = newDist
            nextTreeNode = TreeNode(pathNode.tile, currentTreeNode.tile, newDist)

            tileEffect = 1
            if pathNode.tile.player == searchingPlayer:
                tileEffect -= pathNode.tile.army
            elif useTrueValueGathered:
                tileEffect += pathNode.tile.army
            runningTrunkValue -= tileEffect
            nextTreeNode.value = runningValue
            nextTreeNode.trunkValue = runningTrunkValue
            nextTreeNode.trunkDistance = runningTrunkDist
            nextTreeNode.gatherTurns = valuePerTurnPath.length - addlDist + 1
            runningValue += tileEffect
            if nextTreeNode not in currentTreeNode.children:
                currentTreeNode.children.append(nextTreeNode)
                prunedToRemove = None
                for p in currentTreeNode.pruned:
                    if p.tile == nextTreeNode.tile:
                        prunedToRemove = p
                if prunedToRemove is not None:
                    currentTreeNode.pruned.remove(prunedToRemove)
            currentTreeNode = nextTreeNode
            treeNodeLookup[pathNode.tile] = currentTreeNode
            addlDist += 1
            pathNode = pathNode.next

        # now bubble the value of the path and turns up the tree
        curTreeNode = treeNodePathAddingOnTo
        while True:
            curTreeNode.value += valuePerTurnPath.value
            curTreeNode.gatherTurns += valuePerTurnPath.length
            if curTreeNode.fromTile is None:
                break
            curTreeNode = treeNodeLookup[curTreeNode.fromTile]

    return treeNodeLookup


def build_next_level_start_dict(
        newPaths: typing.List[Path],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        remainingTurns: int,
        # negativeTiles: typing.Set[Tile],
        baseCaseFunc,
) -> typing.Tuple[int | None, typing.Dict[Tile, typing.Tuple[typing.Any, int]]]:
    """
    Returns the remaining turns after adding the paths, and the new startingTileDict.
    If a path in the list produces a path that accomplishes nothing, returns None for remaining turns indicating that this search branch has exhausted useful paths.

    @param newPaths:
    @param searchingPlayer:
    # @param negativeTiles:
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

        # negativeTiles.add(node.tile)
        # skipping because first tile is actually already on the path
        node = node.next
        # add the new path to startTiles and then search a new path
        while node is not None:
            newDist = distance + addlDist
            nextPrioObj = baseCaseFunc(node.tile, newDist)
            startTilesDict[node.tile] = (nextPrioObj, newDist)
            # negativeTiles.add(node.tile)
            logging.info(
                f"Including tile {node.tile.x},{node.tile.y} in startTilesDict at newDist {newDist}  (distance {distance} addlDist {addlDist})")
            # if viewInfo:

            addlDist += 1
            node = node.next

    if hadInvalidPath:
        remainingTurns = None

    return remainingTurns, startTilesDict


def add_tree_nodes_to_start_tiles_dict_recurse(
        rootNode: TreeNode,
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        remainingTurns: int,
        # negativeTiles: typing.Set[Tile],
        baseCaseFunc,
        dist: int = 0
):
    """
    Adds nodes recursively to the start tiles dict.
    DOES NOT make a copy of the start tiles dict.

    @param rootNode:
    @param searchingPlayer:
    # @param negativeTiles:
    @return:
    """

    if rootNode.tile not in startTilesDict:
        nextPrioObj = baseCaseFunc(rootNode.tile, dist)
        startTilesDict[rootNode.tile] = (nextPrioObj, dist)
    for node in rootNode.children:
        add_tree_nodes_to_start_tiles_dict_recurse(node, startTilesDict, searchingPlayer, remainingTurns, baseCaseFunc, dist=dist + 1)


def _knapsack_levels_gather_recurse(
        itr: SearchUtils.Counter,
        map: MapBase,
        startTilesDict,
        # treeNodeLookup: typing.Dict[Tile, TreeNode],
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
        includeTreeNodesThatGatherNegative=False,
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
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @return:
    """
    maxIterationGatheredArmy: int = -1
    maxIterationPaths: typing.List[Path] = []

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
                # negativeTiles,
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
                # treeNodeLookup=treeNodeLookup.copy(),
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
                includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
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
        # treeNodeLookup: typing.Dict[Tile, TreeNode],
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
        includeTreeNodesThatGatherNegative=False,
        shouldLog=False
) -> typing.Tuple[int, typing.List[TreeNode]]:
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
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @param shouldLog:
    @return:
    """
    origStartTilesDict = startTilesDict.copy()

    rootNodes: typing.List[TreeNode] = []

    maxPerIteration = max(4, fullTurns // 3 - 1)

    turnsSoFar = 0
    totalValue = 0
    newStartTilesDict = startTilesDict.copy()
    treeNodeLookup: typing.Dict[Tile, TreeNode] = {}
    for tile, data in startTilesDict.items():
        (_, dist) = data
        treeNodeLookup[tile] = TreeNode(tile, fromTile=None, turn=dist)

    prevBest = 0

    lastPrunedTo = 0

    while lastPrunedTo <= fullTurns:
        itr.add(1)
        turnsToGather = fullTurns - turnsSoFar
        logging.info(f'Beginning {turnsToGather} sub_knapsack, fullTurns {fullTurns}, turnsSoFar {turnsSoFar}')
        newGatheredArmy, newPaths = get_sub_knapsack_gather(
            map,
            newStartTilesDict,
            valueFunc,
            baseCaseFunc,
            0.1,
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
            shouldLog=shouldLog,
            useTrueValueGathered=useTrueValueGathered
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
            treeNodeLookup,
            newStartTilesDict,
            searchingPlayer,
            useTrueValueGathered=useTrueValueGathered,
            # negativeTiles
            shouldLog=shouldLog
        )

        rootNodes = [treeNodeLookup[tile] for tile in origStartTilesDict]

        if USE_DEBUG_ASSERTS:
            recalcTotalValue, recalcTotalTurns = recalculate_tree_values(
                rootNodes,
                negativeTiles,
                origStartTilesDict,
                searchingPlayer,
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
        maxPerIteration = max(maxPerIteration // 2, 1)
        # maxPerIteration = maxPerIteration // 2 + 1

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
            treeNodeLookupToPrune=treeNodeLookup,
            tileDictToPrune=newStartTilesDict)

        if USE_DEBUG_ASSERTS:
            recalcTotalValue, recalcTotalTurns = recalculate_tree_values(
                rootNodes,
                negativeTiles,
                newStartTilesDict,
                searchingPlayer,
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
            rootNode = treeNodeLookup.get(path.start.tile, None)
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

        # _debug_print_diff_between_start_dict_and_treenodes(treeNodeLookup, newStartTilesDict)

        lastPrunedTo = pruneToTurns
        turnsSoFar = totalTurns

    return totalValue, rootNodes

def _debug_print_diff_between_start_dict_and_treenodes(
        treeNodes: typing.Dict[Tile, TreeNode],
        startDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]]
):
    if len(treeNodes) != len(startDict):
        logging.info(f'~~startDict: {len(startDict)}, vs treeNodes {len(treeNodes)}')
    else:
        logging.info(f'startDict: {len(startDict)}, vs treeNodes {len(treeNodes)}')

    for tile, node in sorted(treeNodes.items()):
        if tile not in startDict:
            path = Path()
            curNode = node
            while curNode is not None:
                path.add_next(curNode.tile)
                curNode = treeNodes.get(curNode.fromTile, None)
            logging.info(f'  missing from startDict: {str(tile)}  ({str(node)}), path {str(path)}')

    for tile, val in sorted(startDict.items()):
        (prioThing, dist) = val
        if tile not in treeNodes:
            logging.info(f'  missing from treeNodes: {str(tile)}  (dist {dist}, [{str(prioThing)}])')


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
        includeTreeNodesThatGatherNegative=False,
        shouldLog=False
) -> typing.List[TreeNode]:
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
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
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
        includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
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
        viewInfo=None,
        distPriorityMap=None,
        useTrueValueGathered=False,
        includeTreeNodesThatGatherNegative=False,
        shouldLog=False,
        useRecurse=False
) -> typing.Tuple[int, typing.List[TreeNode]]:
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
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @return:
    """
    startTime = time.time()
    negativeTilesOrig = negativeTiles
    if negativeTiles is not None:
        negativeTiles = negativeTiles.copy()
    else:
        negativeTiles = set()
    # q = PriorityQueue()

    # if isinstance(startTiles, dict):
    #	for tile in startTiles.keys():
    #		(startPriorityObject, distance) = startTiles[tile]

    #		startVal = startPriorityObject

    #		allowedDepth = turns - distance
    #		startTiles = {}
    #		startTiles[tile] = (startPriorityObject,

    # TODO break ties by maximum distance from threat (ideally, gathers from behind our gen are better
    #           than gathering stuff that may open up a better attack path in front of our gen)

    # TODO factor in cities, right now they're not even incrementing. need to factor them into the timing and calculate when they'll be moved.
    if searchingPlayer == -2:
        if isinstance(startTiles, dict):
            searchingPlayer = [t for t in startTiles.keys()][0].player
        else:
            searchingPlayer = startTiles[0].player

    logging.info(f"Trying knapsack-bfs-gather. Turns {turns}. Searching player {searchingPlayer}")
    if valueFunc is None:
        logging.info("Using default valueFunc")

        def default_value_func_max_gathered_per_turn(
                currentTile,
                priorityObject
        ):
            (
                depthDist,
                dist,
                realDist,
                negPrioTilesPerTurn,
                negGatheredSum,
                negArmySum,
                # xSum,
                # ySum,
                numPrioTiles
            ) = priorityObject

            if negArmySum >= 0 and not includeTreeNodesThatGatherNegative:
                return None
            if currentTile.army < 2 or currentTile.player != searchingPlayer:
                return None

            value = 0 - negGatheredSum
            prioObj = (value,  # most army per turn
                       depthDist,
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
        logging.info("Using default priorityFunc")

        def default_priority_func(nextTile, currentPriorityObject):
            (
                depthDist,
                dist,
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
                if searchingPlayer == nextTile.player:
                    negArmySum -= nextTile.army
                    negGatheredSum -= nextTile.army
                # # this broke gather approximation, couldn't predict actual gather values based on this
                # if nextTile.isCity:
                #	negArmySum -= turns // 3
                else:
                    negArmySum += nextTile.army
                    if useTrueValueGathered:
                        negGatheredSum += nextTile.army
            # if nextTile.player != searchingPlayer and not (nextTile.player == -1 and nextTile.isCity):
            #	negDistanceSum -= 1
            # hacks us prioritizing further away tiles
            # if distPriorityMap is not None:
            #     negDistanceSum -= distPriorityMap[nextTile.x][nextTile.y]
            if priorityTiles is not None and nextTile in priorityTiles:
                numPrioTiles += 1
            realDist += 1
            depthDist += 1
            prioObj = (
                depthDist,
                dist + 1,
                realDist,
                numPrioTiles / depthDist,
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
                startingDist,
                0 - initialDistance,
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
            # treeNodeLookup=treeNodeLookup,
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
            includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
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
            includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
            shouldLog=shouldLog,
        )

        treeNodeLookup = build_tree_node_lookup(
            maxPaths,
            startTilesDict,
            searchingPlayer,
            # negativeTiles
            shouldLog=shouldLog
        )

        rootNodes: typing.List[TreeNode] = list(where(treeNodeLookup.values(), lambda treeNode: treeNode.fromTile is None))

        totalValue, totalTurns = recalculate_tree_values(
            rootNodes,
            negativeTilesOrig,
            origStartTilesDict,
            searchingPlayer=searchingPlayer,
            onlyCalculateFriendlyArmy=not useTrueValueGathered,
            viewInfo=viewInfo,
            shouldAssert=True)

    logging.info(
        f"Concluded knapsack_levels_backpack_gather with {itr.value} path segments, value {totalValue}. Duration: {time.time() - startTime:.3f}")
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
        includeTreeNodesThatGatherNegative: bool = False,
        shouldLog: bool = True
) -> typing.List[TreeNode]:
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
        includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
        shouldLog=shouldLog,
    )

    return nodes

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
        includeTreeNodesThatGatherNegative: bool = False,
        shouldLog: bool = True
) -> typing.Tuple[int, int, typing.List[TreeNode]]:
    """
    Legacy iterative BFS greedy backpack gather, where every iteration it adds the max army-per-turn path that it finds on to the existing gather plan.
    SHOULD be replaced by variations of the multiple-choice-knapsack gathers that pull lots of paths in a single BFS and knapsack them.

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
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
    @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
     to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
     Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
     Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
    @return:
    """
    startTime = time.time()
    negativeTilesOrig = negativeTiles
    if negativeTiles is not None:
        negativeTiles = negativeTiles.copy()
    else:
        negativeTiles = set()

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

            if negArmySum >= 0:
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
                #	negArmySum -= turns // 3
                else:
                    negArmySum += nextTile.army
                    if useTrueValueGathered:
                        negGatheredSum += nextTile.army
            # if nextTile.player != searchingPlayer and not (nextTile.player == -1 and nextTile.isCity):
            #	negDistanceSum -= 1
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

    treeNodeLookup = {}
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
            currentTreeNode = None

            if node.tile in treeNodeLookup:
                currentTreeNode = treeNodeLookup[node.tile]
            else:
                currentTreeNode = TreeNode(node.tile, None, distance)
                currentTreeNode.gatherTurns = 1
            runningValue = valuePerTurnPath.value - node.tile.army
            currentTreeNode.value += runningValue
            runningValue -= node.tile.army
            treeNodeLookup[node.tile] = currentTreeNode
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
                #	viewInfo.bottomRightGridText[node.tile.x][node.tile.y] = newDist
                nextTreeNode = TreeNode(node.tile, currentTreeNode.tile, newDist)
                nextTreeNode.value = runningValue
                nextTreeNode.gatherTurns = 1
                runningValue -= node.tile.army
                currentTreeNode.children.append(nextTreeNode)
                currentTreeNode = nextTreeNode
                treeNodeLookup[node.tile] = currentTreeNode
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

    rootNodes = list(where(treeNodeLookup.values(), lambda treeNode: treeNode.fromTile is None))

    totalValue, turnsUsed = recalculate_tree_values(
        rootNodes,
        negativeTilesOrig,
        origStartTiles,
        searchingPlayer=searchingPlayer,
        onlyCalculateFriendlyArmy=not useTrueValueGathered,
        viewInfo=viewInfo)

    logging.info(
        f"Concluded greedy-bfs-gather with {itr} path segments, value {totalValue}. Duration: {time.time() - startTime:.3f}")
    return totalValue, turnsUsed, rootNodes


def recalculate_tree_values(
        rootNodes: typing.List[TreeNode],
        negativeTiles: typing.Set[Tile] | None,
        startTilesDict: typing.Dict[Tile, object],
        searchingPlayer: int,
        onlyCalculateFriendlyArmy=False,
        viewInfo=None,
        shouldAssert=False
) -> typing.Tuple[int, int]:
    totalValue = 0
    totalTurns = 0
    for currentNode in rootNodes:
        _recalculate_tree_values_recurse(
            currentNode,
            negativeTiles,
            startTilesDict,
            searchingPlayer,
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
            if child.tile.player == searchingPlayer:
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
        currentNode: TreeNode,
        negativeTiles: typing.Set[Tile] | None,
        startTilesDict: typing.Dict[Tile, object],
        searchingPlayer: int,
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
        if currentNode.tile.player == searchingPlayer:
            sum += currentNode.tile.army
        elif not onlyCalculateFriendlyArmy:
            sum -= currentNode.tile.army
    for child in currentNode.children:
        _recalculate_tree_values_recurse(
            child,
            negativeTiles,
            startTilesDict,
            searchingPlayer,
            onlyCalculateFriendlyArmy,
            viewInfo,
            shouldAssert=shouldAssert)
        sum += child.value
        turns += child.gatherTurns

    # if viewInfo:
    #     viewInfo.bottomRightGridText[currentNode.tile.x][currentNode.tile.y] = sum

    if shouldAssert:
        if currentNode.value != sum:
            raise AssertionError(f'currentNode val {currentNode.value} != recalculated sum {sum}')
        if currentNode.gatherTurns != turns:
            raise AssertionError(f'currentNode turns {currentNode.gatherTurns} != recalculated turns {turns}')

    currentNode.value = sum
    currentNode.gatherTurns = turns


def get_tree_move(
        gathers: typing.List[TreeNode],
        priorityFunc: typing.Callable[[Tile, typing.Tuple | None], typing.Tuple],
        valueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None]
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

    highestValue = None
    highestValueMove = None
    while q.qsize() > 0:
        (curPrio, curGather) = q.get()
        if len(curGather.children) == 0:
            # WE FOUND OUR FIRST MOVE!
            thisValue = valueFunc(curGather.tile, curPrio)
            if (thisValue is not None
                    and curGather.fromTile is not None
                    and (highestValue is None or thisValue > highestValue)
            ):
                highestValue = thisValue
                highestValueMove = Move(curGather.tile, curGather.fromTile)
                logging.info(f"new highestValueMove {highestValueMove.toString()}!")
        for gather in curGather.children:
            nextPrio = priorityFunc(gather.tile, curPrio)
            q.put((nextPrio, gather))

    if highestValueMove is None:
        return None

    logging.info(f"highestValueMove in get_tree_move was {highestValueMove.toString()}!")
    return highestValueMove


def calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(
        treeNodes: typing.List[TreeNode],
        searchingPlayer: int,
        invalidMoveFunc: typing.Callable[[TreeNode], bool],
        viewInfo: ViewInfo | None = None,
        noLog: bool = True
) -> typing.Tuple[int, typing.Dict[Tile, TreeNode]]:
    """
    Returns (numNodesInTree, priorityQueue of leaves, lowest value first, lookup from Tile to TreeNode).
    Does not queue root nodes (nodes where fromTile is None) into the leaf queue.
    @param treeNodes:
    @param searchingPlayer:
    @param invalidMoveFunc: Should return True for invalid moves that should ALWAYS be pruned as leaves. (Generally moves that would try to move negative army, or whatever).
    @param viewInfo:
    @param noLog:
    @return:
    """

    nodeMap = {}

    count = 0
    # find the leaves
    queue = deque()
    for treeNode in treeNodes:
        treeNode.trunkValue = 0
        queue.appendleft(treeNode)

    while not len(queue) == 0:
        current = queue.pop()
        nodeMap[current.tile] = current
        if current.fromTile is not None:
            count += 1
        if not noLog:
            logging.info(" current {}, count {}".format(current.tile.toString(), count))
        for child in current.children:
            child.trunkValue = current.trunkValue
            child.trunkDistance = current.trunkDistance + 1
            if child.tile.player == searchingPlayer:
                child.trunkValue += child.tile.army
            #else:
            #    child.trunkValue -= child.tile.army
            child.trunkValue -= 1
            # if viewInfo is not None:
            #     viewInfo.bottomLeftGridText[child.tile.x][child.tile.y] = child.trunkValue
            queue.appendleft(child)

    return count, nodeMap


def prune_mst_to_turns(
        rootNodes: typing.List[TreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        treeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[TreeNode], bool] | None = None,
) -> typing.List[TreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param turns: The number of turns to prune the MST down to.
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param treeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(TreeNode) -> bool, return true if you want a leaf TreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.

    @return: The list same list of rootnodes passed in, modified.
    """
    count, totalValue, rootNodes = prune_mst_to_turns_with_values(
        rootNodes=rootNodes,
        turns=turns,
        searchingPlayer=searchingPlayer,
        viewInfo=viewInfo,
        noLog=noLog,
        treeNodeLookupToPrune=treeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        invalidMoveFunc=invalidMoveFunc,
    )

    return rootNodes


def prune_mst_to_turns_with_values(
        rootNodes: typing.List[TreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        treeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[TreeNode], bool] | None = None,
) -> typing.Tuple[int, int, typing.List[TreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing treenode lookup map instead of rebuilding...?
     MAKE A GATHER CLASS THAT STORES THE ROOT NODES, THE NODE LOOKUP, THE VALUE, THE TURNS

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param turns: The number of turns to prune the MST down to.
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param treeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(TreeNode) -> bool, return true if you want a leaf TreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if invalidMoveFunc is None:
        def invalid_move_func(node: TreeNode):
            if node.value <= 0:
                return True
            if node.tile.player != searchingPlayer:
                return True
        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: TreeNode, curPrioObj: typing.Tuple | None):
        try:
            rawValPerTurn = node.value / node.trunkDistance
            trunkValPerTurn = node.trunkValue / node.trunkDistance
        except:
            rawValPerTurn = -100
            trunkValPerTurn = -100
        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile.x][node.tile.y] = f'v{node.value}'
            viewInfo.bottomMidRightGridText[node.tile.x][node.tile.y] = f'tv{node.trunkValue}'
            viewInfo.bottomRightGridText[node.tile.x][node.tile.y] = f'td{node.trunkDistance}'

            viewInfo.bottomMidLeftGridText[node.tile.x][node.tile.y] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile.x][node.tile.y] = f'vt{rawValPerTurn:.1f}'

        return rawValPerTurn, node.value, 0 - node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=lambda node, _, turnsLeft, curValue: turnsLeft <= turns,
        pruneValueFunc=pruneFunc,
        invalidMoveFunc=invalidMoveFunc,
        viewInfo=viewInfo,
        noLog=noLog,
        treeNodeLookupToPrune=treeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
    )


def prune_mst_to_army(
        rootNodes: typing.List[TreeNode],
        army: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        treeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[TreeNode], bool] | None = None
) -> typing.List[TreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing treenode lookup map instead of rebuilding...?
    TODO make sure no recalculate tree nodes is necessary.

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param army: The army amount to prune the MST down to
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param treeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(TreeNode) -> bool, return true if you want a leaf TreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.

    @return: The list same list of rootnodes passed in, modified.
    """
    start = time.perf_counter()

    cityCounter = SearchUtils.Counter(0)

    def cityCounterFunc(node: TreeNode):
        if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node not in rootNodes:
            if node.tile.player == searchingPlayer:
                cityCounter.add(1)
            else:
                cityCounter.add(-1)
    iterate_tree_nodes(rootNodes, cityCounterFunc)

    if invalidMoveFunc is None:
        def invalid_move_func(node: TreeNode):
            if node.value <= 0:
                return True
            if node.tile.player != searchingPlayer:
                return True
        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def untilFunc(node: TreeNode, _, turnsLeft: int, curValue: int):
        cityIncrementAmount = cityCounter.value * (turnsLeft - 1) // 2
        armyLeftIfPruned = curValue - node.value + cityIncrementAmount
        # armyLeftIfPruned = curValue + cityIncrementAmount
        if armyLeftIfPruned < army:
            return True
        return False

    count, totalValue, rootNodes = prune_mst_until(
        rootNodes,
        untilFunc=untilFunc,
        pruneValueFunc=lambda node, curObj: (node.value, node.trunkDistance),
        invalidMoveFunc=invalidMoveFunc,
        viewInfo=viewInfo,
        noLog=noLog,

        treeNodeLookupToPrune=treeNodeLookupToPrune
    )

    return rootNodes


# TODO can implement prune as multiple choice knapsack, optimizing lowest weight combinations of tree prunes instead of highest weight, maybe?
def prune_mst_until(
        rootNodes: typing.List[TreeNode],
        untilFunc: typing.Callable[[TreeNode, typing.Tuple, int, int], bool],
        pruneValueFunc: typing.Callable[[TreeNode, typing.Tuple | None], typing.Tuple],
        invalidMoveFunc: typing.Callable[[TreeNode], bool],
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        treeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
) -> typing.Tuple[int, int, typing.List[TreeNode]]:
    """
    Prunes excess / bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing treenode lookup map instead of rebuilding...?
    TODO make sure no recalculate tree nodes is necessary.

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param untilFunc: Func[curNode, curPriorityObject, treeNodeCountRemaining, curValue] -> bool (should return False to continue pruning, True to return the tree).
    @param pruneValueFunc: Func[curNode, curPriorityObject] - min are pruned first
    @param viewInfo:
    @param noLog:
    @param treeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(TreeNode) -> bool, return true if you want a leaf TreeNode to always be prune. For example, pruning gather nodes that begin at an enemy tile or that are 1's.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified).
    """
    start = time.perf_counter()

    nodeMap: typing.Dict[Tile, TreeNode] = {}
    leaves = PriorityQueue()


    def leafAdder(current: TreeNode):
        nodeMap[current.tile] = current
        if current.fromTile is not None and len(current.children) == 0:
            # then we're a leaf. Add to heap
            # value = current.trunkValue / max(1, current.trunkDistance)
            value = current.value
            validMove = 1
            if invalidMoveFunc(current):
                if not noLog:
                    logging.info("tile {} will be eliminated due to invalid move, army {}".format(current.tile.toString(), current.tile.army))
                validMove = 0
            if not noLog:
                logging.info("  tile {} had value {:.1f}, trunkDistance {}".format(current.tile.toString(), value, current.trunkDistance))
            leaves.put((validMove, pruneValueFunc(current, None), current))

    iterate_tree_nodes(rootNodes, leafAdder)

    curValue = 0
    for node in rootNodes:
        curValue += node.value

    count = len(nodeMap) - len(rootNodes)
    if not noLog:
        logging.info(f'MST prune beginning with {count} nodes ({len(leaves.queue)} leaves)')

    if not noLog:
        logging.info("DEQUEUEING")

    # now we have all the leaves, smallest value first
    while not leaves.empty():
        validMove, prioObj, current = leaves.get()
        if current.fromTile is None:
            continue
        if validMove > 0:
            if untilFunc(current, prioObj, count, curValue):
                # Then this was a valid move, and we've pruned enough leaves out.
                # Thus we should break. Otherwise if validMove == 0, we want to keep popping invalid moves off until they're valid again.
                break
        else:
            logging.info(f'pruning extra invalid tree node despite untilFunc == True: {str(current)}')

        if not noLog:
            logging.info(f'pruning tree node {str(current)}')

        # now remove this leaf from its parent and bubble the value change all the way up
        parent = None
        count -= 1
        curValue -= current.value
        parent = nodeMap[current.fromTile]
        realParent = parent
        if parent is not None:
            parent.children.remove(current)
            parent.pruned.append(current)

        while True:
            parent.value -= current.value
            parent.gatherTurns -= 1
            if parent.fromTile is None:
                break
            parent = nodeMap[parent.fromTile]

        if treeNodeLookupToPrune is not None:
            treeNodeLookupToPrune.pop(current.tile, None)
        if tileDictToPrune is not None:
            tileDictToPrune.pop(current.tile, None)

        if not noLog:
            logging.info("    popped/pruned {} value {:.1f} count {}".format(current.tile.toString(), current.value, count))

        if realParent is not None and len(realParent.children) == 0 and realParent.fromTile is not None:
            #(value, length) = self.get_prune_point(nodeMap, realParent)
            # value = realParent.trunkValue / max(1, realParent.trunkDistance)
            value = realParent.value
            parentValidMove = 1
            if invalidMoveFunc(realParent):
                logging.info("parent {} will be eliminated due to invalid move, army {}".format(realParent.tile.toString(), realParent.tile.army))
                parentValidMove = 0

            if not noLog:
                logging.info("  Appending parent {} (valid {}) had value {:.1f}, trunkDistance {}".format(realParent.tile.toString(), parentValidMove, value, realParent.trunkDistance))

            nextPrioObj = pruneValueFunc(realParent, prioObj)
            leaves.put((parentValidMove, nextPrioObj, realParent))

    #while not leaves.empty():
    totalValue = 0
    for node in rootNodes:
        # the root tree nodes need + 1 to their value
        # node.value += 1
        totalValue += node.value
    if not noLog:
        logging.info("  Pruned MST to turns {} with value {} in duration {:.3f}".format(count, totalValue, time.perf_counter() - start))
    return count, totalValue, rootNodes

def iterate_tree_nodes(
        treeNodes: typing.List[TreeNode],
        forEachFunc: typing.Callable[[TreeNode], None]
):
    q: typing.Deque[TreeNode] = deque()
    for n in treeNodes:
        q.append(n)
    while len(q) > 0:
        cur = q.popleft()
        forEachFunc(cur)
        for c in cur.children:
            q.append(c)