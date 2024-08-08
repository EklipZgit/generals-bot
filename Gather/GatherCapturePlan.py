from __future__ import  annotations

import typing
from collections import deque

import logbook

from Models import GatherTreeNode, Move
from Gather import GatherDebug, GatherPrune
from Interfaces import TilePlanInterface, MapMatrixInterface
from base.client.map import MapBase
from base.client.tile import Tile


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
        self.has_more_moves: bool = len(rootNodes) > 0
        self.approximate_capture_tiles: typing.Set[Tile] = set()
        self._move_list: typing.List[Move] | None = None

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

            GatherTreeNode.foreach_tree_node(self.root_nodes, incrementer)

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
                self._tileSet = self.approximate_capture_tiles.copy()
                GatherTreeNode.foreach_tree_node(self.root_nodes, lambda n: self._tileSet.add(n.tile))

        return self._tileSet

    @tileSet.setter
    def tileSet(self, value):
        raise AssertionError("NO SETTING!")

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = []
            self._tileSet = set()
            for n in GatherTreeNode.iterate_tree_nodes(self.root_nodes):
                self._tileList.append(n.tile)
                self._tileSet.add(n.tile)
            for t in self.approximate_capture_tiles:
                if t not in self._tileSet:
                    self.tileList.append(t)
                    self.tileSet.add(t)
        return self._tileList

    @property
    def requiredDelay(self) -> int:
        return self._requiredDelay

    def get_first_move(self) -> Move | None:
        if self.value_func:
            return GatherPrune.get_tree_move(self.root_nodes, self.value_func)
        else:
            raise AssertionError(f'cannot call get_first_move when value_func is None (after pickling)')
            # i = 0
            # while i < len(self.tileList):
            #     if self.tileList[i]
            # return Move(self.tileList[0], self.tileList[1])

    def pop_first_move(self) -> Move | None:
        if self.value_func:
            move = GatherPrune.get_tree_move(self.root_nodes, self.value_func, pop=True)
            self._move_list = None
            return move
        else:
            raise AssertionError(f'cannot call pop move when value_func is None (after pickling)')

    def get_move_list(self) -> typing.List[Move]:
        if self._move_list is not None:
            return self._move_list
        if self.value_func:
            self._move_list = GatherPrune.get_tree_moves(self.root_nodes, self.value_func)
            return self._move_list
        else:
            raise AssertionError(f'cannot call get_move_list when value_func is null (after pickling)')

    def __getstate__(self):
        # important because otherwise these are not generated and set.
        tileList = self.tileList
        tileSet = self.tileSet
        state = self.__dict__.copy()

        # if 'notify_unresolved_army_emerged' in state:
        #     del state['notify_unresolved_army_emerged']

        if 'value_func' in state:
            if self._move_list is None:
                self._move_list = GatherPrune.get_tree_moves(self.root_nodes, self.value_func)
            del state['value_func']
            state['_move_list'] = self._move_list

        if '_abc_impl' in state:
            del state['_abc_impl']

        if '_map' in state:
            del state['_map']

        if 'start' in state:
            raise Exception('wtf why')
            del state['start']

        if 'tail' in state:
            raise Exception('wtf why')
            del state['tail']
        #
        # if 'perf_timer' in state:
        #     del state['perf_timer']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.notify_unresolved_army_emerged = []
        self.notify_army_moved = []

    def __str__(self) -> str:
        return f'{self._econ_value:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt), armyGath {self.gathered_army}, del {self.requiredDelay}'

    def __repr__(self) -> str:
        return f'{self._econ_value:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt), armyGath {self.gathered_army}, del {self.requiredDelay}, tiles {self.tileList}'

    def include_additional_fog_gather(self, fogTurns: int, fogGatherValue: int):
        self._turns += fogTurns
        self.gather_turns += fogTurns
        self.gathered_army += fogGatherValue
        self.gather_capture_points += fogGatherValue
        self.fog_gather_turns += fogTurns
        self.fog_gather_army += fogGatherValue

    def include_approximate_capture_tiles(self, captures: typing.Iterable[Tile]):
        preCount = len(self.approximate_capture_tiles)
        self.approximate_capture_tiles.update(captures)
        if len(self.approximate_capture_tiles) != preCount:
            self._tileSet = None
            self._tileList = None

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
            captures: typing.Set[Tile] | None = None,
            viewInfo=None,
            cloneNodes: bool = False
    ) -> GatherCapturePlan:
        """
        Returns the plan. The root nodes must be connected to all their children, but do not need the correct army / econ values (will be recalculated).

        @param map:
        @param rootNodes:
        @param negativeTiles:
        @param searchingPlayer:
        @param onlyCalculateFriendlyArmy: If True, captured tiles will NOT be included in the gatherValue and gatherPoints calculations (but will still be included in econValue calculations).
        @param priorityMatrix: The priority matrix for both gathered and captured nodes. Always added to the 'gatherPoints' sum. Optionally also included in the econ value calculation.
        @param includeGatherPriorityAsEconValues: if True, the priority matrix values of gathered nodes will be included in the econValue of the plan for gatherNodes.
        @param includeCapturePriorityAsEconValues: if True, the priority matrix values of CAPTURED nodes will be included in the econValue of the plan for enemy tiles in the plan.
        @param captures: a set of tiles to include as approximate captures in this gather capture plan
        @param viewInfo:
        @param cloneNodes: if True, the original root nodes will not be modified and will be cloned instead. Default is false.
        @return:
        """
        if cloneNodes:
            rootNodes = GatherTreeNode.clone_nodes(rootNodes)
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

        #prunes invalid gather nodes.
        rootNodes = GatherPrune.prune_mst_to_army(rootNodes, 1000000000, searchingPlayer, map.team_ids_by_player_index, map.turn, viewInfo)
        plan.root_nodes = rootNodes

        # plan.gathered_army += currentNode.value
        for currentNode in rootNodes:
            plan._turns += currentNode.gatherTurns

        if captures:
            GatherCapturePlan._include_capture_estimation_in_calculation(
                plan,
                captures,
                searchingPlayer,
                frPlayers,
                negativeTiles,
                onlyCalculateFriendlyArmy,
                priorityMatrix,
                includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
            )

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
            for currentNode in GatherTreeNode.iterate_tree_nodes(rootNodes):
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
        if GatherDebug.USE_DEBUG_LOGGING:
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
            if GatherDebug.USE_DEBUG_LOGGING:
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
                if isTileFriendly:
                    if includeGatherPriorityAsEconValues:
                        econValue += prioVal
                elif includeCapturePriorityAsEconValues:
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

    @staticmethod
    def _include_capture_estimation_in_calculation(
            plan: GatherCapturePlan,
            captures: typing.Set[Tile],
            searchingPlayer: int,
            frPlayers: typing.List[int],
            negativeTiles: typing.Set[Tile] | None = None,
            onlyCalculateFriendlyArmy=False,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            includeCapturePriorityAsEconValues: bool = True
    ):
        """
        Adds captures to the value of the plan.

        @param plan:
        @param negativeTiles:
        @param searchingPlayer:
        @param frPlayers:
        @param onlyCalculateFriendlyArmy:
        @param priorityMatrix:
        @param includeCapturePriorityAsEconValues:
        @return:
        """
        captures = captures.difference(plan.tileSet)
        plan.include_approximate_capture_tiles(captures)
        lookup = {n.tile: n for n in GatherTreeNode.iterate_tree_nodes(plan.root_nodes)}

        q = deque()
        # for rn in plan.root_nodes:
        #     for mv in rn.tile.movable:
        #         if mv in captures:
        #             q.append((mv, rn, rn.value + rn.tile.army - 1))
        for cap in captures:
            for mv in cap.movable:
                node = lookup.get(mv, None)
                if node:
                    q.append((cap, node, node.value + node.tile.army - 1))

        fromRoot: GatherTreeNode
        toCap: Tile

        vis = set()
        while q:
            (toCap, fromRoot, armyAmt) = q.popleft()

            if toCap.tile_index in vis or toCap not in captures:
                continue

            vis.add(toCap.tile_index)

            # we leave one node behind at each tile, except the root tile.
            sumArmy = -1
            sumPoints = -1
            econValue = 0.0
            armyAmt -= 1
            currentTile = toCap
            isTileFriendly = currentTile.player in frPlayers

            # elif priorityMatrix:
            #     sum += priorityMatrix[currentTile]

            if not negativeTiles or currentTile not in negativeTiles:
                if isTileFriendly:
                    sumArmy += currentTile.army
                    armyAmt += currentTile.army
                    # sumPoints += currentTile.army
                    if currentTile.isCity:
                        plan.friendly_city_count += 1
                else:
                    armyAmt -= currentTile.army
                    if not onlyCalculateFriendlyArmy:
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
                sumPoints += prioVal
                if includeCapturePriorityAsEconValues:
                    econValue += prioVal
                # if USE_DEBUG_ASSERTS:
                #     logbook.info(f'appending {currentTile}  {currentTile.army}a  matrix {priorityMatrix[currentTile]:.3f} -> {sumArmy:.3f}')

            # we do econValue BEFORE the children because the children will sum their own econ value
            sumPoints += sumArmy
            plan.gathered_army += sumArmy
            # plan.econValue += econValue
            plan.gather_capture_points += sumPoints
            plan._turns += 1
            if isTileFriendly:
                plan.gather_turns += 1
            #
            # for child in currentNode.children:
            #     GatherCapturePlan._recalculate_gather_plan_values(
            #         plan,
            #         child,
            #         negativeTiles,
            #         searchingPlayer,
            #         frPlayers,
            #         onlyCalculateFriendlyArmy,
            #         priorityMatrix,
            #         includeGatherPriorityAsEconValues,
            #         includeCapturePriorityAsEconValues)
            #     sumArmy += child.value
            #     sumPoints += child.points
            #     turns += child.gatherTurns

            fromRoot.value += sumArmy
            # old behavior was tile 'values' were points, not army. Safe to not preserve that...?
            fromRoot.points += sumPoints
            fromRoot.gatherTurns += 1
            if armyAmt < 0:
                # then we must waste at least one turn shuffling army around, borrowing gathered army from a different root node inlet
                plan.gather_turns += 1
            # plan.gather_capture_points += sumPoints
            # plan.econValue +=

            for mv in toCap.movable:
                q.append((mv, fromRoot, armyAmt))

        # for root in plan.root_nodes:

    def shortInfo(self) -> str:
        return f'{self._econ_value:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt), armyGath {self.gathered_army} {self.root_nodes[0].tile}'

