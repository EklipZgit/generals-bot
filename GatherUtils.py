from __future__ import annotations

import logbook
import time
import typing
from collections import deque

import DebugHelper
import GatherSteiner
import KnapsackUtils
import SearchUtils
from DataModels import Move, GatherTreeNode
from Interfaces import TilePlanInterface
from MapMatrix import MapMatrixInterface, MapMatrixSet, TileSet, MapMatrix
from Path import Path
from SearchUtils import where
from ViewInfo import ViewInfo
from base.client.map import Tile, MapBase

USE_DEBUG_ASSERTS = False


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


class GatherCapturePlan(TilePlanInterface):
    def __init__(
            self,
            rootNodes: typing.List[GatherTreeNode],
            map: MapBase,
            econValue: float,
            turnsTotalInclCap: int,
            gatherValue: int,
            gatherCapturePoints: float,
            gatherTurns: int,
            requiredDelay: int,
            minValueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None] | None = None,
            friendlyCityCount: int | None = None,
            enemyCityCount: int | None = None,
            asPlayer: int = -1
    ):
        """

        @param rootNodes:
        @param map:
        @param econValue:
        @param turnsTotalInclCap:
        @param gatherValue: The actual amount of army gathered. If this was with UseTrueValueGathered, should be the actual amount of army that WILL end up on the destination tile (excluding negative tiles).
        @param gatherCapturePoints: The weighted-by-gather/capture-matrices value of the gather. Different from econValue, which is the expected econ payoff of using this gather/capture plan.
        @param gatherTurns: The total number of turns this gather plan spends GATHERING (not capturing). DONT just set this to the same thing as turnsTotalInclCap.
        @param requiredDelay: You'd usually not delay a gather unless it involved multiple cities capturing something.
        @param minValueFunc: The move selection function for prioritizing leaf move order. Default is simply delaying cities as first priority and second priority the furthest tiles from our general.
        @param friendlyCityCount: leave None to auto-calculate.
        @param enemyCityCount: leave None to auto-calculate.
        @param asPlayer: defaults to the map.player_index player if not provided.
        """
        if asPlayer == -1:
            asPlayer = map.player_index
        self.player: int = asPlayer
        self.root_nodes: typing.List[GatherTreeNode] = rootNodes
        self.gathered_army: int = gatherValue
        """The actual amount of army gathered. If this was with UseTrueValueGathered=True or OnlyConsiderFriendlyArmy=False, should be the actual amount of army that WILL end up on the destination tile (excluding negative tiles). Otherwise should be the sum of friendly army gathered."""
        self.gather_capture_points: float = gatherCapturePoints
        """The actual amount of capture points gathered. Mimicks the same logic as gathered_army, but includes the priorityMatrix values (including negative tiles)."""
        self._econ_value: float = econValue
        """The expected economic payoff from performing this gather/capture plan. May or may not include priorityMatrix weight for gathered / captured tiles."""
        self._turns: int = turnsTotalInclCap
        self.gather_turns: int = gatherTurns
        """The total number of turns spent GATHERING (not capturing). Use length for the total plan length instead."""
        self.friendly_city_count: int = friendlyCityCount
        self.enemy_city_count: int = enemyCityCount
        self.fog_gather_turns: int = 0
        """The number of turns this gather includes from unknown (not included in tileset/tilelist) fog tiles."""
        self.fog_gather_army: int = 0
        """The amount of army this gather includes from unknown (not included in tileset/tilelist) fog tiles."""
        self._requiredDelay: int = requiredDelay
        self._tileList: typing.List[Tile] | None = None
        self._tileSet: typing.Set[Tile] | None = None
        self._map: MapBase = map
        self.value_func: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None] = minValueFunc

        if not self.value_func:  # emptyVal value func, gathers based on cityCount then distance from general
            frPlayers = map.get_teammates(asPlayer)

            def default_value_func(currentTile, currentPriorityObject):
                negCityCount = army = unfriendlyTileCount = 0
                # i don't think this does anything...?
                curIsOurCity = True
                if currentPriorityObject is not None:
                    (nextIsOurCity, negCityCount, unfriendlyTileCount, army, curIsOurCity) = currentPriorityObject
                    army -= 1
                nextIsOurCity = curIsOurCity
                curIsOurCity = True
                if currentTile.player in frPlayers:
                    if currentTile.isGeneral or currentTile.isCity:
                        negCityCount -= 1
                    army += currentTile.army
                else:
                    if currentTile.isGeneral or currentTile.isCity and army + 2 <= currentTile.army:
                        curIsOurCity = False
                        # cityCount += 1
                    unfriendlyTileCount += 1
                    army -= currentTile.army

                # heuristicVal = negArmy / distFromPlayArea
                return nextIsOurCity, negCityCount, unfriendlyTileCount, army, curIsOurCity

            self.value_func = default_value_func

        if self.friendly_city_count is None or self.enemy_city_count is None:
            self.friendly_city_count = 0
            self.enemy_city_count = 0
            frPlayers = map.get_teammates(asPlayer)

            def incrementer(node: GatherTreeNode):
                if node.tile.isCity:
                    if node.tile.player in frPlayers:
                        self.friendly_city_count += 1
                    elif node.tile.player >= 0:
                        self.enemy_city_count += 1

            foreach_tree_node(self.root_nodes, incrementer)

    def clone(self) -> GatherCapturePlan:
        clone = GatherCapturePlan(
            rootNodes=[n.deep_clone() for n in self.root_nodes],
            map=self._map,
            econValue=self._econ_value,
            turnsTotalInclCap=self._turns,
            gatherValue=self.gathered_army,
            gatherCapturePoints=self.gather_capture_points,
            gatherTurns=self.gather_turns,
            friendlyCityCount=self.friendly_city_count,
            requiredDelay=self._requiredDelay,
            minValueFunc=self.value_func,
            asPlayer=self.player,
        )

        if self._tileList is not None:
            clone._tileList = self._tileList.copy()
        if self._tileSet is not None:
            clone._tileSet = self._tileSet.copy()

        return clone

    @property
    def length(self) -> int:
        return self._turns

    @property
    def econValue(self) -> float:
        return self._econ_value

    @econValue.setter
    def econValue(self, econValue: float):
        self._econ_value = econValue

    @property
    def tileSet(self) -> typing.Set[Tile]:
        if self._tileSet is None:
            if self._tileList is not None:
                self._tileSet = set(self._tileList)
            else:
                self._tileSet = set()
                foreach_tree_node(self.root_nodes, lambda n: self._tileSet.add(n.tile))

        return self._tileSet

    @tileSet.setter
    def tileSet(self, value):
        raise AssertionError("NO SETTING!")

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = []
            foreach_tree_node(self.root_nodes, lambda n: self._tileList.append(n.tile))
        return self._tileList

    @property
    def requiredDelay(self) -> int:
        return self._requiredDelay

    def get_first_move(self) -> Move:
        if self.value_func:
            return get_tree_move(self.root_nodes, self.value_func)
        else:
            return Move(self.tileList[0], self.tileList[1])

    def pop_first_move(self) -> Move:
        if self.value_func:
            return get_tree_move(self.root_nodes, self.value_func, pop=True)
        else:
            raise AssertionError(f'cannot call pop move when value_func is null (after pickling)')

    def get_move_list(self) -> typing.List[Move]:
        if self.value_func:
            return get_tree_moves(self.root_nodes, self.value_func)
        else:
            raise AssertionError(f'cannot call get_move_list when value_func is null (after pickling)')

    def __getstate__(self):
        tileList = self.tileList
        tileSet = self.tileSet
        state = self.__dict__.copy()

        # if 'notify_unresolved_army_emerged' in state:
        #     del state['notify_unresolved_army_emerged']

        if 'value_func' in state:
            del state['value_func']
        #
        # if 'perf_timer' in state:
        #     del state['perf_timer']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.notify_unresolved_army_emerged = []
        self.notify_army_moved = []

    def __str__(self):
        return f'{self._econ_value:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt), armyGath {self.gathered_army}, del {self.requiredDelay}, tiles {self.tileList}'

    def __repr__(self):
        return str(self)

    def include_additional_fog_gather(self, fogTurns: int, fogGatherValue: int):
        self._turns += fogTurns
        self.gather_turns += fogTurns
        self.gathered_army += fogGatherValue
        self.gather_capture_points += fogGatherValue
        self.fog_gather_turns += fogTurns
        self.fog_gather_army += fogGatherValue

    @staticmethod
    def build_from_root_nodes(
            map: MapBase,
            # logEntries: typing.List[str],
            rootNodes: typing.List[GatherTreeNode],
            negativeTiles: typing.Set[Tile] | None,
            searchingPlayer: int,
            onlyCalculateFriendlyArmy=False,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            includeGatherPriorityAsEconValues: bool = False,
            includeCapturePriorityAsEconValues: bool = True,
            viewInfo=None,
            cloneNodes: bool = False
    ) -> GatherCapturePlan:
        """
        Returns the plan

        @param map:
        @param rootNodes:
        @param negativeTiles:
        @param searchingPlayer:
        @param onlyCalculateFriendlyArmy: If True, captured tiles will NOT be included in the gatherValue and gatherPoints calculations (but will still be included in econValue calculations).
        @param priorityMatrix: The priority matrix for both gathered and captured nodes. Always added to the 'gatherPoints' sum. Optionally also included in the econ value calculation.
        @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
        @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
        @param viewInfo:
        @param cloneNodes: if True, the original root nodes will not be modified and will be cloned instead. Default is false.
        @return:
        """
        if cloneNodes:
            rootNodes = clone_nodes(rootNodes)
        plan = GatherCapturePlan(
            [],  # we dont pass the root nodes in because we're going to hand-calculate all the values and dont want it doing weird stuff.
            map,
            econValue=0.0,
            turnsTotalInclCap=0,
            gatherValue=0,
            gatherCapturePoints=0.0,
            gatherTurns=0,
            requiredDelay=0,
            friendlyCityCount=0,
        )
        plan._turns = 0
        frPlayers = map.get_teammates(searchingPlayer)

        for currentNode in rootNodes:
            GatherCapturePlan._recalculate_gather_plan_values(
                plan,
                # logEntries,
                currentNode,
                negativeTiles,
                searchingPlayer,
                frPlayers,
                onlyCalculateFriendlyArmy,
                priorityMatrix,
                includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
                includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
            )
            plan.root_nodes.append(currentNode)
            # plan.gathered_army += currentNode.value
            plan._turns += currentNode.gatherTurns

        # find the leaves and build the trunk values.
        leaves = []
        queue = deque()
        for treeNode in rootNodes:
            treeNode.trunkValue = 0
            treeNode.trunkDistance = 0
            queue.appendleft(treeNode)

        while queue:
            current = queue.pop()
            if not current.children:
                leaves.append(current)
            for child in current.children:
                trunkValue = current.trunkValue
                trunkDistance = current.trunkDistance + 1
                if not negativeTiles or child.tile not in negativeTiles:
                    if child.tile.player in frPlayers:
                        trunkValue += child.tile.army
                    elif not onlyCalculateFriendlyArmy:
                        trunkValue -= child.tile.army
                # always leave 1 army behind.
                trunkValue -= 1
                child.trunkValue = trunkValue
                child.trunkDistance = trunkDistance

                queue.appendleft(child)

        if viewInfo:
            for currentNode in iterate_tree_nodes(rootNodes):
                currentTile = currentNode.tile
                viewInfo.midRightGridText.raw[currentTile.tile_index] = f'v{currentNode.value:.1f}'
                viewInfo.bottomMidRightGridText.raw[currentTile.tile_index] = f'tv{currentNode.trunkValue:.1f}'
                viewInfo.bottomRightGridText.raw[currentTile.tile_index] = f'td{currentNode.trunkDistance}'

                if currentNode.trunkDistance > 0:
                    rawValPerTurn = currentNode.value / currentNode.trunkDistance
                    trunkValPerTurn = currentNode.trunkValue / currentNode.trunkDistance
                    viewInfo.bottomMidLeftGridText.raw[currentTile.tile_index] = f'tt{trunkValPerTurn:.1f}'
                    viewInfo.bottomLeftGridText.raw[currentTile.tile_index] = f'vt{rawValPerTurn:.1f}'

        plan.leaves = leaves

        return plan

    @staticmethod
    def _recalculate_gather_plan_values(
            plan: GatherCapturePlan,
            # logEntries: typing.List[str],
            currentNode: GatherTreeNode,
            negativeTiles: typing.Set[Tile] | None,
            searchingPlayer: int,
            frPlayers: typing.List[int],
            onlyCalculateFriendlyArmy=False,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            includeGatherPriorityAsEconValues: bool = False,
            includeCapturePriorityAsEconValues: bool = True,
    ):
        if USE_DEBUG_ASSERTS:
            logbook.info(f'RECALCING currentNode {currentNode}')

        isStartNode = False

        # we leave one node behind at each tile, except the root tile.
        turns = 1
        sumArmy = -1
        sumPoints = -1
        econValue = 0.0
        currentTile = currentNode.tile
        isTileFriendly = currentTile.player in frPlayers

        if currentNode.toTile is None:
            if USE_DEBUG_ASSERTS:
                logbook.info(f'{currentTile} is first tile, starting at 0')
            isStartNode = True
            turns = 0
            sumArmy = 0
            sumPoints = 0
        # elif priorityMatrix:
        #     sum += priorityMatrix[currentTile]

        if not negativeTiles or currentTile not in negativeTiles:
            if isTileFriendly:
                if not isStartNode:
                    sumArmy += currentTile.army
                    # sumPoints += currentTile.army
                    if currentTile.isCity:
                        plan.friendly_city_count += 1
            else:
                if not onlyCalculateFriendlyArmy and not isStartNode:
                    sumArmy -= currentTile.army
                    # sumPoints -= currentTile.army
                if currentTile.player >= 0:
                    econValue += 2.2
                    if currentTile.isCity:
                        plan.enemy_city_count += 1
                else:
                    econValue += 1.0

        if priorityMatrix:
            prioVal = priorityMatrix.raw[currentTile.tile_index]
            if not isStartNode:
                sumPoints += prioVal
                if isTileFriendly and includeGatherPriorityAsEconValues:
                    econValue += prioVal
            elif not isTileFriendly and includeCapturePriorityAsEconValues:
                econValue += prioVal
            # if USE_DEBUG_ASSERTS:
            #     logbook.info(f'appending {currentTile}  {currentTile.army}a  matrix {priorityMatrix[currentTile]:.3f} -> {sumArmy:.3f}')

        # we do econValue BEFORE the children because the children will sum their own econ value
        sumPoints += sumArmy
        plan.gathered_army += sumArmy
        plan.econValue += econValue
        plan.gather_capture_points += sumPoints
        if isTileFriendly:
            plan.gather_turns += turns

        for child in currentNode.children:
            GatherCapturePlan._recalculate_gather_plan_values(
                plan,
                child,
                negativeTiles,
                searchingPlayer,
                frPlayers,
                onlyCalculateFriendlyArmy,
                priorityMatrix,
                includeGatherPriorityAsEconValues,
                includeCapturePriorityAsEconValues)
            sumArmy += child.value
            sumPoints += child.points
            turns += child.gatherTurns

        currentNode.value = sumArmy
        # old behavior was tile 'values' were points, not army. Safe to not preserve that...?
        currentNode.points = sumPoints
        currentNode.gatherTurns = turns
        # friendly_city_count  # covered above
        # enemy_city_count  # covered above
        # gathered_army  # covered above
        # gather_capture_points  # covered above
        # _econ_value  # covered above.
        # _turns  # covered by the outer rootnodes loop
        # gather_turns   # covered in if above


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


def _dump_log_entries(logEntries: typing.List[str]):
    logbook.info('\r\n' + '\r\n'.join(logEntries))


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

            rootNodes = [gatherTreeNodeLookup[tile] for tile in origStartTilesDict]

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
                # parentPruneFunc=lambda t, prunedNode: _start_tiles_prune_helper(startTilesDict, t, prunedNode)
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
        viewInfo: ViewInfo | None =None,
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
                #xSum,
                #ySum,
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

            if priorityMatrix is not None:
                negGatheredSum -= priorityMatrix.raw[nextTile.tile_index]

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
                #xSum + nextTile.x,
                #ySum + nextTile.y,
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
            if distPriorityMap is not None:
                initialDistance = distPriorityMap.raw[tile.tile_index]
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
            priorityMatrix=priorityMatrix,
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
    valuePerTurnPath: Path | None = None
    origStartTiles = startTilesDict.copy()
    while remainingTurns > 0:
        if valuePerTurnPath is not None:
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
        f"Concluded greedy-bfs-gather with {itr} path segments, value {totalValue}. Duration: {time.perf_counter() - startTime:.4f}")
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


def get_tree_move(
        gathers: typing.List[GatherTreeNode],
        valueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None],
        pop: bool = False
) -> typing.Union[None, Move]:
    moves = get_tree_moves(gathers, valueFunc, pop=pop, limit=1)
    if moves:
        return moves[0]
    return None
    # if len(gathers) == 0:
    #     logbook.info("get_tree_move... len(gathers) == 0?")
    #     return None
    #
    # # TODO this is just an iterate-all-leaves-and-keep-max function, why the hell are we using a priority queue?
    # #  we don't call this often so who cares I guess, but wtf copy paste, normal queue would do fine.
    # q = SearchUtils.HeapQueue()
    #
    # for gather in gathers:
    #     basePrio = priorityFunc(gather.tile, None)
    #     q.put((basePrio, gather))
    #
    # lookup = {}
    #
    # highestValue = None
    # highestValueNode = None
    # while q.queue:
    #     (curPrio, curGather) = q.get()
    #     lookup[curGather.tile] = curGather
    #     if len(curGather.children) == 0:
    #         # WE FOUND OUR FIRST MOVE!
    #         thisValue = valueFunc(curGather.tile, curPrio)
    #         if (thisValue is not None
    #                 and curGather.fromTile is not None
    #                 and (highestValue is None or thisValue > highestValue)
    #         ):
    #             highestValue = thisValue
    #             highestValueNode = curGather
    #             logbook.info(f"new highestValueNode {str(highestValueNode)}!")
    #     for gather in curGather.children:
    #         nextPrio = priorityFunc(gather.tile, curPrio)
    #         q.put((nextPrio, gather))
    #
    # if highestValueNode is None:
    #     return None
    #
    # if pop:
    #     if highestValueNode.fromTile is not None:
    #         parent = lookup[highestValueNode.fromTile]
    #         parent.children.remove(highestValueNode)
    #
    # highestValueMove = Move(highestValueNode.tile, highestValueNode.fromTile)
    # logbook.info(f"highestValueMove in get_tree_move was {highestValueMove.toString()}!")
    # return highestValueMove


def get_tree_moves(
        gathers: typing.List[GatherTreeNode],
        valueFunc: typing.Callable[[Tile, typing.Tuple | None], typing.Tuple | None],
        limit: int = 10000,
        pop: bool = False
) -> typing.List[Move]:
    if len(gathers) == 0:
        logbook.info("get_tree_moves... len(gathers) == 0?")
        return []

    q = deque()

    if not pop:
        gathers = [g.deep_clone() for g in gathers]

    for gather in gathers:
        basePrio = valueFunc(gather.tile, None)
        q.append((basePrio, gather))

    moveQ = SearchUtils.HeapQueueMax()

    fromPrioLookup = {}

    while q:
        (curPrio, curGather) = q.popleft()
        if not curGather.children:
            moveQ.put((curPrio, curGather))
        else:
            fromPrioLookup[curGather.tile] = curPrio
            for gather in curGather.children:
                nextPrio = valueFunc(gather.tile, curPrio)
                q.append((nextPrio, gather))

    moves = []
    iter = 0
    while moveQ.queue:
        (curPrio, curGather) = moveQ.get()
        fromGather = curGather.fromGather
        if fromGather is not None:
            moves.append(Move(curGather.tile, curGather.toTile))
            fromGather.children.remove(curGather)
            iter += 1
            if iter >= limit:
                break

            if not fromGather.children:
                fromPrio = fromPrioLookup.get(fromGather.toTile, None)
                curPrio = valueFunc(fromGather.tile, fromPrio)
                moveQ.put((curPrio, fromGather))

    return moves


def prune_mst_to_turns(
        rootNodes: typing.List[GatherTreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.

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
        preferPrune=preferPrune,
        allowNegative=allowNegative,
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
        preferPrune: typing.Set[Tile] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
        allowNegative: bool = True,
        logEntries: typing.List[str] | None = None,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if logEntries is None:
        logEntries = []

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer and len(node.children) == 0:
                return True
        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: GatherTreeNode, curPrioObj: typing.Tuple | None):
        rawValPerTurn = -100
        # trunkValPerTurn = -100
        # trunkBehindNodeValuePerTurn = -100
        if node.gatherTurns > 0:
            rawValPerTurn = node.value / node.gatherTurns
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkBehindNodeValuePerTurn = trunkValPerTurn
            # trunkBehindNodeValue = node.trunkValue - node.value
            # trunkBehindNodeValuePerTurn = trunkBehindNodeValue / node.trunkDistance
        elif node.value > 0:
            if USE_DEBUG_ASSERTS:
                raise AssertionError(f'divide by zero exception for {str(node)} with value {round(node.value, 6)} turns {node.gatherTurns}')
        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile] = f'v{node.value:.0f}'
            viewInfo.bottomMidRightGridText[node.tile] = f'tv{node.trunkValue:.0f}'
            viewInfo.bottomRightGridText[node.tile] = f'td{node.trunkDistance}'

            # viewInfo.bottomMidLeftGridText[node.tile] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile] = f'vt{rawValPerTurn:.1f}'

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
        preferPrune=preferPrune,
        logEntries=logEntries,
        allowNegative=allowNegative,
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
        preferPrune: typing.Set[Tile] | None = None,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.

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
        preferPrune=preferPrune,
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
        preferPrune: typing.Set[Tile] | None = None,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer and len(node.children) == 0:
                return True
        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: GatherTreeNode, curPrioObj: typing.Tuple | None):
        rawValPerTurn = -100
        # trunkValPerTurn = -100
        # trunkBehindNodeValuePerTurn = -100
        if node.gatherTurns > 0:
            rawValPerTurn = node.value / node.gatherTurns
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkBehindNodeValuePerTurn = trunkValPerTurn
            # trunkBehindNodeValue = node.trunkValue - node.value
            # trunkBehindNodeValuePerTurn = trunkBehindNodeValue / node.trunkDistance
        elif node.value > 0:
            if USE_DEBUG_ASSERTS:
                raise AssertionError(f'divide by zero exception for {str(node)} with value {round(node.value, 6)} turns {node.gatherTurns}')

        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile] = f'v{node.value:.1f}'
            viewInfo.bottomMidRightGridText[node.tile] = f'tv{node.trunkValue:.1f}'
            viewInfo.bottomRightGridText[node.tile] = f'td{node.trunkDistance}'

            # viewInfo.bottomMidLeftGridText[node.tile] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile] = f'vt{rawValPerTurn:.1f}'

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
        preferPrune=preferPrune,
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
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param pruneLargeTilesFirst: if True (emptyVal), then largest tiles will be pruned first allowing this prune to be used to maximize leaving tiles for offense if possible.

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
            if node.tile.army <= 1:
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
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        pruneBranches=False  # if you turn this to true, test_should_not_miscount_gather_prune_at_neut_city will fail. Need to fix how mid-branch city prunes function apparently.
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
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
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
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        pruneLargeTilesFirst=pruneLargeTilesFirst,
    )

    return rootNodes


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
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
        allowBranchPrune: bool = True,
        minTurns: int = 0,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param minArmy: The minimum army amount to prune the MST down to.
    @param searchingPlayer:
    @param teams: the teams array to use when calculating whether a gathered tile adds or subtracts army.
    @param additionalIncrement: if need to gather extra army due to incrementing, include the POSITIVE enemy city increment or NEGATIVE allied increment value here.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param allowBranchPrune: Optionally, pass false to disable pruning whole branches. Allowing branch prunes produces lower value per turn trees but also smaller trees.
    @param minTurns: The minimum number of turns that can be pruned to.

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

    if totalValue < minArmy:
        return totalTurns, totalValue, rootNodes

    def cityCounterFunc(node: GatherTreeNode):
        if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node.tile not in citySkipTiles:
            if teams[node.tile.player] == teams[searchingPlayer]:
                cityCounter.add(1)
                # each time we add one of these we must gather all the other cities in the tree first too so we lose that many increment turns + that
                cityGatherDepthCounter.add(node.trunkDistance)
            else:
                cityCounter.add(-1)

    foreach_tree_node(rootNodes, cityCounterFunc)

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer:
                return True
        invalidMoveFunc = invalid_move_func

    curValuePerTurn = SearchUtils.Counter(totalValue / totalTurns)

    def untilFunc(node: GatherTreeNode, _, turnsLeft: int, curValue: int):
        turnsLeftIfPruned = turnsLeft - node.gatherTurns
        if turnsLeftIfPruned <= minTurns:
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
            if node.toTile is not None:
                msg = f'ERRPRUNE {repr(node)} td {node.trunkDistance} or gathTurns {node.gatherTurns}'
                logbook.info(msg)
                if viewInfo:
                    viewInfo.add_info_line(msg)
                if USE_DEBUG_ASSERTS:
                    raise AssertionError(msg)
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
        preferPrune=preferPrune,
        allowNegative=allowNegative,
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
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
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
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        allowBranchPrune=allowBranchPrune
    )

    return rootNodes


def _would_prune_cause_negative_root(current: GatherTreeNode, nodeMap: typing.Dict[Tile, GatherTreeNode], logEntries: typing.List[str]):
    parent: GatherTreeNode | None = nodeMap.get(current.toTile, None)
    nextParent = parent

    while nextParent is not None:
        parent = nextParent
        nextParent = nodeMap.get(nextParent.toTile, None)

    if logEntries:
        logEntries.append(f'neg root? parent {parent.tile} <- current {current.tile} | parent.value {parent.value:.2f} - current.value {current.value:.2f} = {parent.value - current.value:.2f}')
    if parent.value - current.value < 0:
        return True

    return False


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
        preferPrune: typing.Set[Tile] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
        allowNegative: bool = True,
        logEntries: typing.List[str] | None = None,
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
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified).
    """
    start = time.perf_counter()

    nodeMap: typing.Dict[Tile, GatherTreeNode] = {}
    pruneHeap = SearchUtils.HeapQueue()

    logEnd = False
    if logEntries is None:
        logEntries = []
        logEnd = True

    iter = 0

    def nodeInitializer(current: GatherTreeNode):
        nodeMap[current.tile] = current
        if current.toTile is not None and (len(current.children) == 0 or pruneBranches):
            # then we're a leaf. Add to heap
            # value = current.trunkValue / max(1, current.trunkDistance)
            value = current.value
            validMove = True
            if invalidMoveFunc(current) and len(current.children) == 0:
                if not noLog:
                    logEntries.append(
                        f"tile {current.tile.toString()} will be eliminated due to invalid move, army {current.tile.army}")
                validMove = False
            if not noLog:
                logEntries.append(
                    f"  tile {current.tile.toString()} had value {value:.1f}, trunkDistance {current.trunkDistance}")
            pruneHeap.put((validMove, preferPrune is None or current.tile not in preferPrune, pruneOrderFunc(current, None), current))

    foreach_tree_node(rootNodes, nodeInitializer)

    curValue = 0
    for node in rootNodes:
        curValue += node.value

    count = len(nodeMap) - len(rootNodes)
    if not noLog:
        logEntries.append(f'MST prune beginning with {count} nodes ({len(pruneHeap.queue)} nodes)')

    childRecurseQueue: typing.Deque[GatherTreeNode] = deque()

    initialCount = len(nodeMap)

    current: GatherTreeNode
    try:
        # now we have all the leaves, smallest value first
        while pruneHeap.queue:
            validMove, isPreferPrune, prioObj, current = pruneHeap.get()
            iter += 1
            if iter > initialCount * 3:
                logEntries.append("PRUNE WENT INFINITE, BREAKING")
                if viewInfo is not None:
                    viewInfo.add_info_line('ERR PRUNE WENT INFINITE!!!!!!!!!')
                    viewInfo.add_info_line('ERR PRUNE WENT INFINITE!!!!!!!!!')
                    viewInfo.add_info_line('ERR PRUNE WENT INFINITE!!!!!!!!!')
                break

            if current.toTile is None:
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
            elif not noLog:
                logEntries.append(f'Intending to prune extra invalid tree node regardless of untilFunc: {str(current)}')

            if pruneOverrideFunc is not None and pruneOverrideFunc(current, prioObj, count, curValue):
                if not noLog:
                    logEntries.append(f'SKIPPING pruning tree node {str(current)} due to pruneOverrideFunc')
                continue

            if not allowNegative and _would_prune_cause_negative_root(current, nodeMap, logEntries if not noLog else None):
                if not noLog:
                    logEntries.append(f'SKIPPING pruning tree node {str(current)} because would cause negative node')
                continue

            # make sure the value of this prune didn't go down, if it did, shuffle it back into the heap with new priority.
            if validMove:
                doubleCheckPrioObj = pruneOrderFunc(current, prioObj)
                if doubleCheckPrioObj > prioObj:
                    pruneHeap.put((validMove, preferPrune is None or current.tile not in preferPrune, doubleCheckPrioObj, current))
                    if not noLog:
                        logEntries.append(
                            f'requeued {str(current)} (prio went from {str(prioObj)} to {str(doubleCheckPrioObj)})')
                    continue

            if not noLog:
                logEntries.append(f'pruning tree node {str(current)}')

            # now remove this leaf from its parent and bubble the value change all the way up
            curValue -= current.value
            parent: GatherTreeNode | None = nodeMap.get(current.toTile, None)
            realParent: GatherTreeNode | None = parent

            if parent is not None:
                try:
                    parent.children.remove(current)
                except ValueError:
                    logEntries.append(f'child {str(current)} already not present on {str(parent)}')
                    if USE_DEBUG_ASSERTS:
                        raise AssertionError(f'child {str(current)} already not present on {str(parent)}')
                parent.pruned.append(current)

            while parent is not None:
                parent.value -= current.value
                parent.gatherTurns -= current.gatherTurns
                if parentPruneFunc is not None:
                    parentPruneFunc(parent.tile, current)
                if parent.toTile is None:
                    break
                parent = nodeMap.get(parent.toTile, None)

            childRecurseQueue.append(current)
            childIter = 0
            while childRecurseQueue:
                toDropFromLookup = childRecurseQueue.popleft()
                childIter += 1
                if childIter > initialCount * 3:
                    logEntries.append("PRUNE CHILD WENT INFINITE, BREAKING")
                    if viewInfo is not None:
                        viewInfo.add_info_line('ERR PRUNE CHILD WENT INFINITE!!!!!!!!!')
                    if USE_DEBUG_ASSERTS:
                        queueStr = '\r\n'.join([str(i) for i in childRecurseQueue])
                        raise AssertionError(f"PRUNE CHILD WENT INFINITE, BREAKING, {str(toDropFromLookup)}. QUEUE:\r\n{queueStr}")
                    break

                if gatherTreeNodeLookupToPrune is not None:
                    gatherTreeNodeLookupToPrune.pop(toDropFromLookup.tile, None)
                if tileDictToPrune is not None:
                    tileDictToPrune.pop(toDropFromLookup.tile, None)
                nodeMap.pop(toDropFromLookup.tile, None)
                count -= 1
                if not noLog:
                    logEntries.append(
                        f"    popped/pruned BRANCH CHILD {toDropFromLookup.tile.toString()} value {toDropFromLookup.value:.1f} count {count}")
                for child in toDropFromLookup.children:
                    childRecurseQueue.append(child)

            if not noLog:
                logEntries.append(f"    popped/pruned {current.tile.toString()} value {current.value:.1f} count {count}")

            if realParent is not None and len(realParent.children) == 0 and realParent.toTile is not None:
                # (value, length) = self.get_prune_point(nodeMap, realParent)
                # value = realParent.trunkValue / max(1, realParent.trunkDistance)
                value = realParent.value
                parentValidMove = True
                if invalidMoveFunc(realParent):
                    if not noLog:
                        logEntries.append(
                            f"parent {str(realParent.tile)} will be eliminated due to invalid move, army {realParent.tile.army}")
                    parentValidMove = False

                if not noLog:
                    logEntries.append(
                        f"  Appending parent {str(realParent.tile)} (valid {parentValidMove}) had value {value:.1f}, trunkDistance {realParent.trunkDistance}")

                nextPrioObj = pruneOrderFunc(realParent, prioObj)
                pruneHeap.put((parentValidMove, preferPrune is None or realParent.tile not in preferPrune, nextPrioObj, realParent))

    except Exception as ex:
        logEntries.append('prune got an error, dumping state:')

        logEntries.append(f'rootNodes: {repr(rootNodes)}')
        # logEntries.append(f'untilFunc: {repr(untilFunc)}')
        # logEntries.append(f'pruneOrderFunc: {repr(pruneOrderFunc)}')
        # logEntries.append(f'invalidMoveFunc: {repr(invalidMoveFunc)}')
        logEntries.append(f'pruneBranches: {repr(pruneBranches)}')
        # logEntries.append(f'pruneOverrideFunc: {repr(pruneOverrideFunc)}')
        # logEntries.append(f'viewInfo: {repr(viewInfo)}')
        # logEntries.append(f'noLog: {repr(noLog)}')
        logEntries.append(f'gatherTreeNodeLookupToPrune: {repr(gatherTreeNodeLookupToPrune)}')
        logEntries.append(f'tileDictToPrune: {repr(tileDictToPrune)}')
        if logEnd:
            _dump_log_entries(logEntries)
        raise

    #while not leaves.empty():
    totalValue = 0
    for node in rootNodes:
        # the root tree nodes need + 1 to their value
        # node.value += 1
        totalValue += node.value
    if not noLog:
        logEntries.append(
            f"  Pruned MST to turns {count} with value {totalValue} in duration {time.perf_counter() - start:.4f}")

        if logEnd:
            _dump_log_entries(logEntries)

    return count, totalValue, rootNodes


def foreach_tree_node(
        gatherTreeNodes: typing.List[GatherTreeNode],
        forEachFunc: typing.Callable[[GatherTreeNode], None]
):
    i = 0
    q: typing.Deque[GatherTreeNode] = deque()
    for n in gatherTreeNodes:
        q.append(n)
    while q:
        i += 1
        cur = q.popleft()
        forEachFunc(cur)
        for c in cur.children:
            q.append(c)
        if i > 500:
            raise AssertionError(f'iterate_tree_nodes infinite looped. Nodes in the cycle: {str([str(n) for n in q])}')


def iterate_tree_nodes(
    rootNodes: typing.List[GatherTreeNode],
) -> typing.Generator[GatherTreeNode, None, None]:
    i = 0
    q: typing.Deque[GatherTreeNode] = deque()
    for n in rootNodes:
        q.append(n)
    while q:
        i += 1
        cur = q.popleft()
        yield cur
        for c in cur.children:
            q.append(c)
        if i > 500:
            raise AssertionError(f'iterate_tree_nodes infinite looped. Nodes in the cycle: {str([str(n) for n in q])}')


def iterate_tree_node(
    rootNode: GatherTreeNode,
) -> typing.Generator[GatherTreeNode, None, None]:
    i = 0
    q: typing.Deque[GatherTreeNode] = deque()
    q.append(rootNode)
    while q:
        i += 1
        cur = q.popleft()
        yield cur
        for c in cur.children:
            q.append(c)
        if i > 500:
            raise AssertionError(f'iterate_tree_nodes infinite looped. Nodes in the cycle: {str([str(n) for n in q])}')


def get_tree_leaves(gathers: typing.List[GatherTreeNode]) -> typing.List[GatherTreeNode]:
    # fuck it, do it recursively i'm too tired for this
    combined = []
    for gather in gathers:
        if len(gather.children) == 0:
            if gather.toTile is not None:
                combined.append(gather)
        else:
            combined.extend(get_tree_leaves(gather.children))

    return combined


def get_tree_leaves_further_than_distance(
        gatherNodes: typing.List[GatherTreeNode],
        distMap: MapMatrixInterface[int],
        dist: int,
        minArmy: int = 1,
        curArmy: int = 0
) -> typing.List[GatherTreeNode]:
    includeAll = False
    if minArmy > curArmy:
        includeAll = True

    leavesToInclude = []
    for n in gatherNodes:
        leaves = get_tree_leaves([n])
        distOffs = 0
        if n.tile.isGeneral:
            distOffs = 1
        leavesGreaterThanDistance = []
        for g in leaves:
            if distMap[g.tile] >= dist - distOffs or (g.toTile and distMap[g.toTile] >= dist - distOffs):
                leavesGreaterThanDistance.append(g)
        if includeAll:
            leavesToInclude.extend(leavesGreaterThanDistance)
            continue

        for leaf in leavesGreaterThanDistance:
            leafContribution = (leaf.tile.army - 1)
            if curArmy - leafContribution <= minArmy:
                leavesToInclude.append(leaf)
            else:
                curArmy -= leafContribution

    return leavesToInclude


def convert_contiguous_tiles_to_gather_tree_nodes_with_values(
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
    rootNodes = build_mst_from_root_and_contiguous_tiles(map, rootTiles, tiles)

    return GatherCapturePlan.build_from_root_nodes(
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


def build_mst_from_root_and_contiguous_tiles(map: MapBase, rootTiles: typing.Iterable[Tile], tiles: TileSet, maxDepth: int = 1000) -> typing.List[GatherTreeNode]:
    """Does NOT calculate values"""
    visited = MapMatrixSet(map)

    q = deque()
    for tile in rootTiles:
        q.appendleft((tile, None, None, 0))

    rootNodes = []
    tile: Tile
    fromTile: Tile | None
    fromNode: GatherTreeNode | None
    while True:
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
                q.appendleft((t, tile, newNode, fromDepth + 1))

    return rootNodes


def build_mst_to_root_from_path_and_contiguous_tiles(map: MapBase, rootPath: Path, tiles: TileSet, maxDepth: int, reversePath: bool = False) -> GatherTreeNode:
    """Does NOT calculate values"""
    inputList = rootPath.tileList

    rootTiles = build_mst_from_root_and_contiguous_tiles(map, rootTiles=inputList, tiles=tiles, maxDepth=maxDepth)

    if reversePath:
        rootTiles = list(reversed(rootTiles))

    prev = None
    # if not reversePath:
    for node in rootTiles:
        if prev:
            prev.fromGather = node
            # logbook.info(f'setting {node.tile} fromGather to {prev.tile}')
            # logbook.info(f'appending {node.tile} to {prev.tile}s children')
            logbook.info(f'setting {prev.tile} fromGather to {node.tile}')
            logbook.info(f'appending {prev.tile} to {node.tile}s children')
            node.children.append(prev)
            prev.toTile = node.tile
        prev = node

    return rootTiles[-1]


def clone_nodes(gatherNodes: typing.List[GatherTreeNode]) -> typing.List[GatherTreeNode]:
    return [n.deep_clone() for n in gatherNodes]


def build_max_value_gather_tree_linking_specific_nodes(
    map: MapBase,
    rootTiles: typing.Iterable[Tile],
    tiles: typing.Iterable[Tile],
    asPlayer: int = -1,
    gatherMatrix: MapMatrixInterface[float | None] = None,
    captureMatrix: MapMatrixInterface[float | None] = None,
    negativeTiles: TileSet | None = None,
    prioritizeCaptureHighArmyTiles: bool = False,
    useTrueValueGathered: bool = True,
    includeGatherPriorityAsEconValues: bool = False,
    includeCapturePriorityAsEconValues: bool = True,
    logDebug: bool = False,
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
    @param gatherMatrix: Priority values for gathered tiles. Only applies to friendly tiles.
    @param captureMatrix: Priority values for captured tiles. Only applies to non-friendly tiles.
    @param prioritizeCaptureHighArmyTiles: If true, we'll value pathing through large army enemy territory over pathing through small army enemy territory.
    @param negativeTiles: The negative tile set, as with any other gather. Does not bypass the capture/gather priority matrix values.
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

    # baseCostOffset = map.largest_army_tile.army + 5
    baseCostOffset = 0

    weightMatrix = MapMatrix(map, 0-baseCostOffset)

    for t in map.get_all_tiles():
        # positive weights are not allowed...? Need to find the max and offset, presumably?
        if map.is_tile_on_team_with(t, asPlayer):
            weightMatrix.raw[t.tile_index] += t.army
            if gatherMatrix:
                weightMatrix.raw[t.tile_index] += gatherMatrix.raw[t.tile_index]
        else:
            if prioritizeCaptureHighArmyTiles:
                weightMatrix.raw[t.tile_index] += t.army
            else:
                weightMatrix.raw[t.tile_index] -= t.army

            if captureMatrix:
                weightMatrix.raw[t.tile_index] += captureMatrix.raw[t.tile_index]
        if logDebug:
            logbook.info(f'tile {t} weight: {weightMatrix.raw[t.tile_index]:.3f}')

    steinerNodes = GatherSteiner.build_network_x_steiner_tree(map, tiles, asPlayer, weightMod=weightMatrix, baseWeight=1000)
    # steinerMatrix = MapMatrixSet(map, steinerNodes)

    plan = convert_contiguous_tiles_to_gather_tree_nodes_with_values(
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

    usedTime = time.perf_counter()-startTime
    logbook.info(f'build_max_value_gather_tree_linking_specific_nodes complete in {usedTime:.4f}s with {plan}')

    return plan


def gather_approximate_turns_to_tile(
    map: MapBase,
    rootTile: Tile,
    approximateTargetTurns: int,
    asPlayer: int = -1,
    gatherMatrix: MapMatrixInterface[float | None] = None,
    captureMatrix: MapMatrixInterface[float | None] = None,
    negativeTiles: TileSet | None = None,
    prioritizeCaptureHighArmyTiles: bool = False,
    useTrueValueGathered: bool = True,
    includeGatherPriorityAsEconValues: bool = False,
    includeCapturePriorityAsEconValues: bool = True,
    logDebug: bool = False,
    viewInfo=None,
) -> GatherCapturePlan:
    """
    When you want to gather a max amount to some specific tile in some rough number of turns.

    @param map:
    @param rootTile: The tile that will be the destination of the gather.
    @param asPlayer:
    @param gatherMatrix: Priority values for gathered tiles. Only applies to friendly tiles.
    @param captureMatrix: Priority values for captured tiles. Only applies to non-friendly tiles.
    @param prioritizeCaptureHighArmyTiles: If true, we'll value pathing through large army enemy territory over pathing through small army enemy territory.
    @param negativeTiles: The negative tile set, as with any other gather. Does not bypass the capture/gather priority matrix values.
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

    steinerNodes = GatherSteiner.get_prize_collecting_gather_mapmatrix(map, asPlayer, rootTile, approximateTargetTurns, gatherMatrix, captureMatrix)

    plan = convert_contiguous_tiles_to_gather_tree_nodes_with_values(
        map,
        rootTiles=[rootTile],
        tiles=steinerNodes,
        negativeTiles=negativeTiles,
        searchingPlayer=asPlayer,
        priorityMatrix=weightMatrix,
        useTrueValueGathered=useTrueValueGathered,
        includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        viewInfo=viewInfo,
    )

    usedTime = time.perf_counter()-startTime
    logbook.info(f'gather_approximate_turns_to_tile complete in {usedTime:.4f}s with {plan}')

    return plan
