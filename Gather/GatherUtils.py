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
from . import prune_mst_to_turns_with_values, GatherSteiner, recalculate_tree_values, cutesy_chatgpt_gather
from . import GatherCapturePlan
from . import GatherDebug
from MapMatrix import MapMatrixInterface, MapMatrixSet, TileSet, MapMatrix
from Path import Path
from SearchUtils import where
from ViewInfo import ViewInfo
from base.client.map import Tile, MapBase


T = typing.TypeVar('T')

#
# class TreeBuilder(typing.Generic[T]):
#     def __init__(self, map: MapBase):
#         self.map: MapBase = map
#         self.tree_builder_prioritizer: typing.Callable[[Tile, T], T | None] = None
#         self.tree_builder_valuator: typing.Callable[[Tile, T], typing.Any | None] = None
#         """The value function when finding path extensions to the spanning tree"""
#
#         self.tree_knapsacker_valuator: typing.Callable[[Path], int] = None
#         """For getting the values of tree nodes to shove in the knapsack to build the subtree iteration"""
#
#     def build_gather_capture_tree_from_tile_sets(
#             self,
#             gatherTiles: MapMatrixInterface[float | None],
#             captureTiles: MapMatrixInterface[float | None],
#             startTiles: typing.List[Tile] | None = None
#     ) -> GatherCapturePlan:
#         nodeMatrix = self.build_mst_gather_from_matrices(gatherTiles, captureTiles, startTiles)
#
#     def build_mst_gather_from_matrices(
#             self,
#             gatherTiles: MapMatrixInterface[float | None],
#             captureTiles: MapMatrixInterface[float | None],
#             startTiles: typing.List[Tile]
#     ) -> MapMatrixInterface[GatherTreeNode]:
#         """
#         Outputs
#         @param gatherTiles:
#         @param captureTiles:
#         @param startTiles:
#         @return:
#         """
#
#         # kay need to bi-directional BFS to gather all the nodes...
#         nodeMatrix: MapMatrixInterface[GatherTreeNode] = MapMatrix(self.map)
#
#         # build dumb gather mst
#         frontier: SearchUtils.HeapQueue[typing.Tuple[int, Tile, GatherTreeNode | None, int, float, int]] = SearchUtils.HeapQueue()
#         for tile in startTiles:
#             frontier.put((0, tile, None, 0, 0, 0))
#
#         dist: int
#         curTile: Tile
#         fromNode: GatherTreeNode | None
#         negArmyGathered: int
#         negPrioSum: float
#         negRawArmy: int
#         unk: typing.Any | None
#         qq = frontier.queue
#         while qq:
#             (dist, nextTile, fromNode, negArmyGathered, negPrioSum, negRawArmy) = frontier.get()
#
#             curNode = nodeMatrix[nextTile]
#             if curNode:
#                 continue
#
#             treeNode = GatherTreeNode(nextTile, fromNode.tile)
#             if fromNode:
#                 fromNode.children.append(treeNode)
#
#             for movable in nextTile.movable:
#                 if movable in gatherTiles and movable not in nodeMatrix:
#                     frontier.put((dist + 1, movable, treeNode, negArmyGathered, negPrioSum, negRawArmy))
#
#         return nodeMatrix

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
        if GatherDebug.USE_DEBUG_ASSERTS:
            raise Exception(f'the input tiles were not fully connected to one another. disconnected tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(unvisited)])}')

        frTiles = [t for t in tiles if t.player == searchingPlayer]
        addPath = SearchUtils.a_star_find(frTiles, goal=next(iter(unvisited)), noLog=True)
        if addPath is None:
            raise Exception(f'Unable to recover disconnected inputs, aStar find was unable to find a path to reconnect.')
        tiles.update(addPath.tileList)
        return build_capture_mst_from_root_and_contiguous_tiles(map, tiles, searchingPlayer, ignoreTiles)

    if GatherDebug.USE_DEBUG_ASSERTS:
        for tile in tiles:
            dist = dists.raw[tile.tile_index]
            if dist is None:
                if GatherDebug.USE_DEBUG_ASSERTS:
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
            if GatherDebug.USE_DEBUG_ASSERTS:
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
        prune_raw_connected_nodes_to_turns__bfs(rootTiles, outputTiles, pruneToTurns, asPlayer, valueMatrix, negativeTiles)

        # inclTiles = set(steinerNodes)
        # if viewInfo:
        #     viewInfo.add_map_zone(inclTiles, (0, 155, 255), alpha=88)
        # value, outputTiles = cutesy_chatgpt_gather(map, pruneToTurns, rootTiles, asPlayer, valueMatrix, tilesToInclude=inclTiles, viewInfo=viewInfo)
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
        gatherMatrix: MapMatrixInterface[float] | None = None,
        captureMatrix: MapMatrixInterface[float] | None = None,
        useTrueValueGathered: bool = False,
        prioritizeCaptureHighArmyTiles: bool = False,
        logDebug: bool = False
) -> MapMatrixInterface[float]:
    """

    @param map:
    @param asPlayer:
    @param negativeTiles:
    @param gatherMatrix: Priority values for gathered tiles. Only applies to friendly tiles. ADDED to the gather value of a tile.
    @param captureMatrix: Priority values for captured tiles. Only applies to non-friendly tiles. ADDED to the gather value of enemy tiles.
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

    steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, rootTiles.union(toTryToInclude), weightMod=valueMatrix, searchingPlayer=searchingPlayer, baseWeight=10000, bannedTiles=skipTiles)

    outputTiles = steinerNodes
    prune_raw_connected_nodes_to_turns__bfs(rootTiles, outputTiles, targetTurns, searchingPlayer, valueMatrix, negativeTiles)

    # plan = convert_contiguous_tile_tree_to_gather_capture_plan(
    #     map,
    #     rootTiles=rootTiles,
    #     tiles=outputTiles,
    #     negativeTiles=negativeTiles,
    #     searchingPlayer=asPlayer,
    #     priorityMatrix=valueMatrix,
    #     useTrueValueGathered=useTrueValueGathered,
    #     includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
    #     includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
    #     # viewInfo=viewInfo,
    # )



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