import time
import typing

import logbook

import DebugHelper
import KnapsackUtils
import SearchUtils
from . import recalculate_tree_values, prune_mst_to_turns_with_values, GatherDebug
from Interfaces import MapMatrixInterface
from Models import GatherTreeNode
from Path import Path
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile


def _knapsack_max_gather_iteration(
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


def _get_sub_knapsack_max_gather(
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

    # NOT causing the duplicates issue
    if len(startTilesDict) < remainingTurns // 10:
        return _get_single_line_iterative_starter_max(
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
        maxDepth=10000,
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

    gatheredArmy, maxPaths = _knapsack_max_gather_iteration(remainingTurns, valuePerTurnPathPerTilePerDistance, logList=logEntries if shouldLog else None)

    return int(round(gatheredArmy)), maxPaths


def _get_single_line_iterative_starter_max(
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
        maxDepth=10000000,
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
    else:
        logEntries.append(f'Initial vt path {valuePerTurnPath}')

    if GatherDebug.USE_DEBUG_ASSERTS:
        vis = set()
        for t in valuePerTurnPath.tileList:
            if t in vis:
                raise Exception(f'{t} was in path twice! Path {valuePerTurnPath}')
            vis.add(t)

    return valuePerTurnPath.value, [valuePerTurnPath]


def _build_tree_node_lookup(
        newPaths: typing.List[Path],
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]],
        searchingPlayer: int,
        teams: typing.List[int],
        # skipTiles: typing.Set[Tile],
        shouldLog: bool = False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
) -> typing.Dict[Tile, GatherTreeNode]:
    gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {}
    return _extend_tree_node_lookup(
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


def _extend_tree_node_lookup(
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

    if GatherDebug.USE_DEBUG_ASSERTS:
        for p in newPaths:
            vis = set()
            for t in p.tileList:
                if t in vis:
                    raise Exception(f'{t} was in path twice! Path {p}')
                vis.add(t)

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
                logbook.info('\r\n' + '\r\n'.join(logEntries))
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
                logbook.info('\r\n' + '\r\n'.join(logEntries))
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
            if GatherDebug.USE_DEBUG_ASSERTS:
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
                if GatherDebug.USE_DEBUG_ASSERTS:
                    logbook.info('\r\n' + '\r\n'.join(logEntries))
                    raise AssertionError(errMsg)

                curGatherTreeNode.toTile = None
                break

            if iter > 600 and nextGatherTreeNode is not None:
                logbook.info('\r\n' + '\r\n'.join(logEntries))
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
                    logbook.info('\r\n' + '\r\n'.join(logEntries))
                    raise AssertionError(msg)
                else:
                    logbook.error(msg)
                break
            curGatherTreeNode = nextGatherTreeNode

    return gatherTreeNodeLookup


def _build_next_level_start_dict_max(
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


def _add_tree_nodes_to_start_tiles_dict_recurse_max(
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
        added += _add_tree_nodes_to_start_tiles_dict_recurse_max(node, startTilesDict, searchingPlayer, remainingTurns, baseCaseFunc, dist=dist + 1)
    #
    # if startTilesEntry is not None:
    #     (prioObj, oldDist) = startTilesEntry
    #     logbook.info(f'shifting {str(rootNode.tile)} from {oldDist} to {oldDist + added}')
    #     startTilesDict[rootNode.tile] = (prioObj, oldDist + added)

    return added


def _knapsack_max_gather_recurse(
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
        newGatheredArmy, newPaths = _get_sub_knapsack_max_gather(
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
        logbook.info('\r\n' + '\r\n'.join(logEntries))

        if GatherDebug.USE_DEBUG_ASSERTS:
            for p in newPaths:
                vis = set()
                for t in p.tileList:
                    if t in vis:
                        raise Exception(f'{t} was in path twice! Path {p}')
                    vis.add(t)

        turnsUsed = 0
        for path in newPaths:
            turnsUsed += path.length
        calculatedLeftOverTurns = remainingTurns - turnsUsed
        expectedLeftOverTurns = remainingTurns - turnsToTry
        newStartTilesDict = startTilesDict

        # loop because we may not find a full plan due to cramped conditions etc in a single iteration
        while calculatedLeftOverTurns < remainingTurns:
            #  + GOTO ITERATE T = T - T//3
            turnsLeft, newStartTilesDict = _build_next_level_start_dict_max(
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
            childGatheredArmy, newChildPaths = _knapsack_max_gather_recurse(
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


# TODO make two versions of this, one that respects defensive depth stuff (and actually calculates move order safety to avoid impossible defense gathers that dont violate depth but would need to make 2 depth 2 moves or whatever)
#  and one that doesnt even give a shit about the gather nodes until after the gather is complete maybe? Though that version could respect capture roots.
def _knapsack_max_gather_iterative_prune(
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
        perIterationFunc: typing.Callable[[typing.Dict[Tile, typing.Tuple[typing.Any, int]]], None] | None = None,
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
        shouldLog: bool = False,
        fastMode: bool = False,
        slowMode: bool = False
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
    @param fastMode: run much faster, but less accurate version of the algo.
    @param slowMode: run much slower, but in theory more accurate version of the algo?

    @return: (valGathered, rootNodes)
    """
    origStartTilesDict = startTilesDict.copy()

    rootNodes: typing.List[GatherTreeNode] = []

    maxPerIteration = max(min(4, fullTurns // 2), 1 * fullTurns // 4)
    if fastMode:
        maxPerIteration = max(min(7, 3 * fullTurns // 4), 1 * fullTurns // 2)
    # if slowMode:
    #     maxPerIteration = 2

    teams = MapBase.get_teams_array(map)

    standardMode = not fastMode and not slowMode

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

    try:
        while lastPrunedTo < fullTurns:
            itr.add(1)
            turnsToGather = fullTurns - turnsSoFar
            logEntries.append(f'Sub Knap (iter {itr.value} {1000.0 * (time.perf_counter() - startTime):.1f}ms in) turns {turnsToGather} sub_knapsack, fullTurns {fullTurns}, turnsSoFar {turnsSoFar}')
            if shouldLog:
                logEntries.append(f'start tiles: {str(newStartTilesDict)}')

            if perIterationFunc is not None:
                perIterationFunc(newStartTilesDict)

            newGatheredArmy, newPaths = _get_sub_knapsack_max_gather(
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

            _extend_tree_node_lookup(
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
                    _add_tree_nodes_to_start_tiles_dict_recurse_max(
                        rootNode,
                        newStartTilesDict,
                        searchingPlayer,
                        calculatedLeftOverTurns,
                        baseCaseFunc,
                        dist=distance
                    )

            rootNodes = [g for g in (gatherTreeNodeLookup.get(tile, None) for tile in origStartTilesDict) if g is not None]

            if GatherDebug.USE_DEBUG_ASSERTS:
                # rootNodes = [gatherTreeNodeLookup[tile] for tile in origStartTilesDict]
                logEntries.append('doing recalc after adding to start dict')

                recalcTotalTurns, recalcTotalValue = recalculate_tree_values(
                    logEntries,
                    rootNodes,
                    negativeTiles,
                    searchingPlayer,
                    teams,
                    onlyCalculateFriendlyArmy=not useTrueValueGathered,
                    priorityMatrix=priorityMatrix,
                    viewInfo=viewInfo,
                    shouldAssert=True)

                if prevBest < recalcTotalValue:
                    logEntries.append(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} > {prevBest}!')
                elif prevBest > 0 and prevBest > recalcTotalValue:
                    logbook.info('\r\n' + '\r\n'.join(logEntries))
                    raise AssertionError(f'gather iteration {itr.value} for turns {turnsToGather} value {recalcTotalValue} WORSE than prev {prevBest}? This should be impossible.')
                # if recalcTotalValue != newGatheredArmy + valueSoFar:
                #     if not SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
                #         raise AssertionError(f'recalculated gather value {recalcTotalValue} didnt match algo output gather value {newGatheredArmy}')
                if recalcTotalTurns != turnsUsedByNewPaths + turnsSoFar:
                    msg = f'recalc gather turns {recalcTotalTurns} didnt match algo turns turnsUsedByNewPaths {turnsUsedByNewPaths} + turnsSoFar {turnsSoFar}'
                    if GatherDebug.USE_DEBUG_ASSERTS:
                        # TODO figure this shit the fuck out, what the fuck
                        logbook.info('\r\n' + '\r\n'.join(logEntries))
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

            # if we're at the end of the gather, gather 1 level at a time for the last phase to make sure we dont miss any optimal branches.

            if itr.value > 1 and maxPerIteration > 1:
                if fastMode:
                    # maxPerIteration = min(3 * maxPerIteration // 4, nextTurnsLeft // 2 + 1)
                    maxPerIteration = 3 * maxPerIteration // 4 + 1
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
            totalTurns, totalValue, rootNodes = prune_mst_to_turns_with_values(
                rootNodes,
                turns=pruneToTurns,
                searchingPlayer=searchingPlayer,
                viewInfo=viewInfo,
                noLog=not shouldLog and not GatherDebug.USE_DEBUG_ASSERTS,  # and not DebugHelper.IS_DEBUGGING
                gatherTreeNodeLookupToPrune=gatherTreeNodeLookup,
                allowNegative=includeGatherTreeNodesThatGatherNegative,
                tileDictToPrune=newStartTilesDict,
                logEntries=logEntries,
                overpruneCutoff=overpruneCutoff,
                # this was for adjusting the prune depth backwards, or something...?
                # parentPruneFunc=lambda t, prunedNode: _start_tiles_prune_helper(startTilesDict, t, prunedNode)
            )
            logEntries.append(
                f'pruned {ogTotalValue:.2f}v @ {ogTotalTurns}t to {totalValue:.2f}v @ {totalTurns}t (goal was {pruneToTurns}t, overpruneCut {overpruneCutoff}t, maxPerIteration {maxPerIteration}, allowNegative={includeGatherTreeNodesThatGatherNegative})')

            if GatherDebug.USE_DEBUG_ASSERTS:
                recalcTotalTurns, recalcTotalValue = recalculate_tree_values(
                    logEntries,
                    rootNodes,
                    negativeTiles,
                    searchingPlayer,
                    teams,
                    onlyCalculateFriendlyArmy=not useTrueValueGathered,
                    priorityMatrix=priorityMatrix,
                    viewInfo=viewInfo,
                    shouldAssert=GatherDebug.USE_DEBUG_ASSERTS
                )

                if recalcTotalTurns != totalTurns:
                    logbook.info('\r\n' + '\r\n'.join(logEntries))
                    raise AssertionError(f'Pruned turns {totalTurns} didnt match recalculated, {recalcTotalTurns}')
                if round(recalcTotalValue, 6) != round(totalValue, 6):
                    logbook.info('\r\n' + '\r\n'.join(logEntries))
                    raise AssertionError(f'Pruned value {round(totalValue, 6)} didnt match recalculated, {round(recalcTotalValue, 6)}')

                if totalTurns > pruneToTurns and includeGatherTreeNodesThatGatherNegative:
                    logbook.info('\r\n' + '\r\n'.join(logEntries))
                    raise AssertionError(f'Pruned turns {totalTurns} was more than the amount requested, {pruneToTurns}')

            # Not necessary because of the prune override func...
            # invalidTurnDiff = bestNonInvalid - pruneToTurns
            # prunedTurnDiff = abs(pruneToTurns - totalTurns)
            # if totalTurns < pruneToTurns:
            #     if abs(invalidTurnDiff) < prunedTurnDiff:
            #         logEntries.append(f'  Due to pruneToTurns {pruneToTurns} resulting in {totalTurns} while the best non-invalid prune was {bestNonInvalid}, (invalidTurnDiff: {invalidTurnDiff}, prunedTurnDiff: {prunedTurnDiff}) increasing pruneToTurns to {bestNonInvalid}...')
            #         pruneToTurns = bestNonInvalid
            #     elif invalidTurnDiff > 0 and bestNonInvalid < fullTurns:
            #         newPruneTo = (pruneToTurns + bestNonInvalid) // 2
            #         logEntries.append(f'   --pruneToTurns {pruneToTurns} resulting in {totalTurns} while the best non-invalid prune was {bestNonInvalid}, (invalidTurnDiff: {invalidTurnDiff}, prunedTurnDiff: {prunedTurnDiff}) increasing pruneToTurns to {newPruneTo}...')
            #         pruneToTurns = newPruneTo
            # else:
            #     logEntries.append(f'   ++pruneToTurns {pruneToTurns} resulting in {totalTurns} while the best non-invalid prune was {bestNonInvalid}, (invalidTurnDiff: {invalidTurnDiff}, prunedTurnDiff: {prunedTurnDiff}) increasing pruneToTurns to {bestNonInvalid}...')

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
        if GatherDebug.USE_DEBUG_ASSERTS:
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


def knapsack_max_gather(
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
    totalValue, usedTurns, rootNodes = knapsack_max_gather_with_values(
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


def knapsack_max_gather_with_values(
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
        perIterationFunc: typing.Callable[[typing.Dict[Tile, typing.Tuple[typing.Any, int]]], None] | None = None,
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
        fastMode: bool = False,
        slowMode: bool = False,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
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
    @return: (valueGathered, rootNodes)
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

        def default_value_func_max_gathered_per_turn(
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
            # this breaks if not max val when the 'find big first boi' comes out
            if realDist > 0:
                # val = value / realDist
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

        valueFunc = default_value_func_max_gathered_per_turn

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

        def default_priority_func(nextTile, currentPriorityObject):
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
            if priorityMatrix is not None:
                negGatheredSum -= priorityMatrix.raw[nextTile.tile_index]

            if priorityTiles and nextTile in priorityTiles:
                numPrioTiles += 1
            realDist += 1
            prioVal = -100000
            if realDist > 0:
                prioVal = 10000 + negGatheredSum / realDist + 0.05 * (realDist * realDist)

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
        totalValue, rootNodes = _knapsack_max_gather_iterative_prune(
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
            perIterationFunc=perIterationFunc,
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
            fastMode=fastMode,
            slowMode=slowMode,
        )
    else:
        gatheredValue, maxPaths = _knapsack_max_gather_recurse(
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

        gatherTreeNodeLookup = _build_tree_node_lookup(
            maxPaths,
            startTilesDict,
            searchingPlayer,
            teams,
            # skipTiles
            shouldLog=shouldLog,
            priorityMatrix=priorityMatrix,
        )

        rootNodes: typing.List[GatherTreeNode] = list(SearchUtils.where(gatherTreeNodeLookup.values(), lambda treeNode: treeNode.toTile is None))

        totalTurns, totalValue = recalculate_tree_values(
            [],
            rootNodes,
            negativeTilesOrig,
            searchingPlayer=searchingPlayer,
            teams=teams,
            onlyCalculateFriendlyArmy=not useTrueValueGathered,
            viewInfo=viewInfo,
            shouldAssert=GatherDebug.USE_DEBUG_ASSERTS,
            priorityMatrix=priorityMatrix)

    totalTurns = 0
    for g in rootNodes:
        totalTurns += g.gatherTurns

    logbook.info(
        f"Concluded knapsack_levels_backpack_gather with {itr.value} iterations. Gather turns {totalTurns}, value {totalValue}. Duration: {time.perf_counter() - startTime:.4f}")
    return totalValue, totalTurns, rootNodes
