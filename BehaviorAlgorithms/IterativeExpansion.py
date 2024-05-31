from __future__ import annotations

import itertools
import random
import time
import typing
from collections import deque
from enum import Enum

import logbook
import networkx as nx

import GatherUtils
import KnapsackUtils
import SearchUtils
from SearchUtils import HeapQueue
from Algorithms import TileIslandBuilder, TileIsland, MapSpanningUtils
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Interfaces import TilePlanInterface, MapMatrixInterface, TileSet
from PerformanceTimer import PerformanceTimer
from ViewInfo import ViewInfo, TargetStyle
from base.client.map import MapBase, Tile


class IslandCompletionInfo(object):
    def __init__(self, island: TileIsland):
        self.tiles_left: int = island.tile_count
        self.army_left: int = island.sum_army


class FlowExpansionPlanOption(TilePlanInterface):
    def __init__(self, moveList: typing.List[Move] | None, econValue: float, turns: int, captures: int, armyRemaining: int):
        self.moves: typing.List[Move] = moveList
        self._tileSet: typing.Set[Tile] | None = None
        self._tileList: typing.List[Tile] | None = None
        self._econ_value: float = econValue
        self._turns: int = turns
        self.captures: int = captures
        """The number of tiles this plan captures."""
        self.armyRemaining: int = armyRemaining

    @property
    def length(self) -> int:
        return self._turns

    @property
    def econValue(self) -> float:
        return self._econ_value

    @econValue.setter
    def econValue(self, value: float):
        self._econ_value = value

    @property
    def tileSet(self) -> typing.Set[Tile]:
        if self._tileSet is None:
            self._tileSet = set()
            for move in self.moves:
                self._tileSet.add(move.source)
                self._tileSet.add(move.dest)
        return self._tileSet

    @property
    def tileList(self) -> typing.List[Tile]:
        if self._tileList is None:
            self._tileList = []
            for move in self.moves:
                self._tileList.append(move.source)
                self._tileList.append(move.dest)
        return self._tileList

    @property
    def requiredDelay(self) -> int:
        return 0

    def get_move_list(self) -> typing.List[Move]:
        return self.moves

    def get_first_move(self) -> Move:
        return self.moves[0]

    def pop_first_move(self) -> Move:
        move = self.moves[0]
        self.moves.remove(move)
        return move

    def __str__(self):
        return f'flow {self.econValue:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt) cap {self.captures}, rA {self.armyRemaining}: {self.moves}'

    def __repr__(self):
        return str(self)

    def clone(self) -> FlowExpansionPlanOption:
        clone = FlowExpansionPlanOption(
            self.moves.copy(),
            self.econValue,
            self._turns,
            self.captures,
            self.armyRemaining)
        return clone


class FlowGraphMethod(Enum):
    NetworkSimplex = 1,
    CapacityScaling = 2,


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


class IslandFlowNode(object):
    def __init__(self, island: TileIsland, desiredArmy: int):
        self.island: TileIsland = island
        self.desired_army: int = desiredArmy
        self.flow_to: typing.List[IslandFlowEdge] = []

    def __str__(self) -> str:
        targets = [f'({n.edge_army}) t{n.target_flow_node.island.team}:{n.target_flow_node.island.unique_id}/{n.target_flow_node.island.name}' for n in self.flow_to]
        flowStr = ''
        if targets:
            flowStr = f' -> {" | ".join(targets)}'
        return f't{self.island.team}:{self.island.unique_id}/{self.island.name}{flowStr}'

    def __repr__(self) -> str:
        return str(self)


class IslandFlowEdge(object):
    def __init__(self, targetIslandFlowNode: IslandFlowNode, edgeArmy: int):
        self.target_flow_node: IslandFlowNode = targetIslandFlowNode
        self.edge_army: int = edgeArmy

    def __str__(self) -> str:
        return f'({self.edge_army}) {self.target_flow_node}'

    def __repr__(self) -> str:
        return str(self)


class IslandFlowGraph(object):
    def __init__(self, ourRootFlowNodes: typing.List[IslandFlowNode], enemyBackfillFlowNodes: typing.List[IslandFlowNode], enemyBackfillNeutEdges: typing.List[IslandFlowEdge]):
        self.root_flow_nodes: typing.List[IslandFlowNode] = ourRootFlowNodes
        self.enemy_backfill_nodes: typing.List[IslandFlowNode] = enemyBackfillFlowNodes
        self.enemy_neut_dump_edges: typing.List[IslandFlowEdge] = enemyBackfillNeutEdges


class ArmyFlowExpander(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.team: int = map._teams[map.player_index]
        self.target_team: int = -1
        self.friendlyGeneral: Tile = map.generals[map.player_index]
        self.enemyGeneral: Tile | None = None

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
            bonusCapturePointMatrix: MapMatrixInterface[float] | None = None,
            # colors: typing.Tuple[int, int, int] = (235, 240, 50),
            # additionalOptionValues: typing.List[typing.Tuple[float, int, Path]] | None = None,
            perfTimer: PerformanceTimer | None = None,
    ) -> typing.List[FlowExpansionPlanOption]:
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
        ourIslands = islands.tile_islands_by_player[asPlayer]
        # friendlyPlayers = self.map.get_teammates(asPlayer)
        # targetPlayers = self.map.get_teammates(targetPlayer)

        blah = self.find_flow_plans_nx_maxflow(islands, ourIslands, targetIslands, asPlayer, turns, negativeTiles=negativeTiles)
        flowPlan = self.find_flow_plans(ourIslands, targetIslands, asPlayer, turns, negativeTiles=negativeTiles)
        return sorted(flowPlan, key=lambda p: (p.econValue / p.length, p.length), reverse=True)
        # output = []
        # for (target, source), planOptionsByTurns in flowPlan.items():
        #     for turns, bestPlan in planOptionsByTurns.items():
        #         output.append(bestPlan)
        #
        # return output

    def find_flow_plans_nx_maxflow(
            self,
            islands: TileIslandBuilder,
            ourIslands: typing.List[TileIsland],
            targetIslands: typing.List[TileIsland],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: TileSet | None = None
    ) -> typing.List[FlowExpansionPlanOption]:
        flowGraph = self.build_flow_graph(
            islands,
            ourIslands,
            targetIslands,
            searchingPlayer,
            turns,
            blockGatherFromEnemyBorders,
            negativeTiles
        )

        return []

    def build_flow_graph(
            self,
            islands: TileIslandBuilder,
            ourIslands: typing.List[TileIsland],
            targetIslands: typing.List[TileIsland],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: TileSet | None = None,
            includeNeutralDemand: bool = False,
            method: FlowGraphMethod = FlowGraphMethod.NetworkSimplex
    ) -> IslandFlowGraph:
        """Returns the list of root IslandFlowNodes that have nothing that flows in to them. The entire graph can be traversed from the root nodes (from possibly multiple directions)."""
        start = time.perf_counter()
        # has to be digraph because of input/output node pairs?
        graph: nx.Graph = nx.DiGraph()
        # graph: nx.Graph = nx.Graph()

        # positive island ids = 'in' nodes, negative island ids = corresponding 'out' node.

        ourSet = {i.unique_id for i in ourIslands}
        targetSet = {i.unique_id for i in targetIslands}
        myTeam = ourIslands[0].team

        generalIsland: TileIsland = islands.tile_island_lookup.raw[self.friendlyGeneral.tile_index]
        if self.enemyGeneral is None or self.enemyGeneral.player == -1 or self.map.is_player_on_team(self.enemyGeneral.player, myTeam):
            raise AssertionError(f'Cannot call find_flow_plans_nx_maxflow without setting enemyGeneral to some (enemy) tile.')

        # TODO use capacity to avoid chokepoints and such and route around enemy focal points

        targetGeneralIsland: TileIsland = islands.tile_island_lookup.raw[self.enemyGeneral.tile_index]

        flowGraphLookup: typing.Dict[int, IslandFlowNode] = {}

        neutSinks = set()

        cumulativeDemand = 0
        idx = 0
        # build input output connectivity edges
        for island in islands.all_tile_islands:
            # TODO this - 1 assumes no retraverses / pocket tiles with only one adjacency
            cost = island.tile_count - 1
            inAttrs = {}
            demand = island.tile_count - island.sum_army
            if island.unique_id in ourSet:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
            elif island.unique_id in targetSet:
                demand = island.sum_army + island.tile_count
                inAttrs['demand'] = demand
                cumulativeDemand += demand
            elif includeNeutralDemand and island.team == -1:
                inAttrs['demand'] = demand
                cumulativeDemand += demand
                cost *= 2

            flowNode = IslandFlowNode(island, demand)
            flowGraphLookup[island.unique_id] = flowNode

            graph.add_node(island.unique_id, **inAttrs)

            # edge from in_island to out_island with the node crossing cost
            graph.add_edge(island.unique_id, -island.unique_id, weight=cost, capacity=100000)

        for island in islands.all_tile_islands:
            isIslandNeut = island.team == -1
            areAllBordersNeut = True
            for movableIsland in island.bordered:
                # edge from out_island to in_movableIsland
                graph.add_edge(-island.unique_id, movableIsland.unique_id, weight=1, capacity=100000)
                if movableIsland.team != -1:
                    areAllBordersNeut = False

            if isIslandNeut and areAllBordersNeut:
                neutSinks.add(island.unique_id)

        enGenNode = graph.nodes.get(targetGeneralIsland.unique_id)
        demand = enGenNode['demand'] - cumulativeDemand
        graph.add_node(targetGeneralIsland.unique_id, demand=demand)

        for neutSinkId in neutSinks:
            graph.add_edge(-targetGeneralIsland.unique_id, neutSinkId, weight=0, capacity=100000)

        # if cumulativeDemand < 0:
        #     # then we have more army to dump than the enemy will accept. Add (subtract the negative) to the enemies general demand.
        #     enGenNode = graph.nodes.get(targetGeneralIsland.unique_id)
        #     demand = enGenNode['demand'] - cumulativeDemand
        #     graph.add_node(targetGeneralIsland.unique_id, demand=demand)
        # else:
        #     # then the enemy has more land than we have army. Add more outbound army to our general
        #     ourGenNode = graph.nodes.get(generalIsland.unique_id)
        #     demand = ourGenNode['demand'] - cumulativeDemand
        #     graph.add_node(generalIsland.unique_id, demand=demand)

        flowCost: int
        """The cost of the whole flow network that is output. Pretty useless to us."""
        flowDict: typing.Dict[int, typing.Dict[int, int]]
        """The lookup from a given node to a dictionary of target nodes (and the army to send across to those nodes)."""

        if method == FlowGraphMethod.NetworkSimplex:
            flowCost, flowDict = nx.flow.network_simplex(graph)
        elif method == FlowGraphMethod.CapacityScaling:
            flowCost, flowDict = nx.flow.capacity_scaling(graph)
        else:
            raise NotImplemented(str(method))

        logbook.info(f'{method} complete in {time.perf_counter() - start:.5f}s')

        start = time.perf_counter()

        backfillNeutEdges = []

        for nodeId, targets in flowDict.items():
            if nodeId > 0:
                # we don't care about the movement of army through a node so skip the input -> output entries
                continue

            nodeId = -nodeId
            sourceNode = flowGraphLookup[nodeId]

            # if len(targets) == 0:
            #     continue
            for targetNodeId, targetFlowAmount in targets.items():
                if targetFlowAmount == 0:
                    continue
                ourSet.discard(targetNodeId)
                targetSet.discard(targetNodeId)
                targetNode = flowGraphLookup[targetNodeId]
                edge = IslandFlowEdge(targetNode, targetFlowAmount)
                if targetNodeId in neutSinks and sourceNode.island is targetGeneralIsland:
                    backfillNeutEdges.append(edge)
                    continue

                sourceNode.flow_to.append(edge)

        finalRootFlowNodes = [flowGraphLookup[id] for id in ourSet]
        enemyBackfillFlowNodes = [flowGraphLookup[id] for id in targetSet]

        flowGraph = IslandFlowGraph(finalRootFlowNodes, enemyBackfillFlowNodes, backfillNeutEdges)

        logbook.info(f'{method} FlowNodes complete in {time.perf_counter() - start:.5f}s')
        return flowGraph

    def find_flow_plans(
            self,
            ourIslands: typing.List[TileIsland],
            targetIslands: typing.List[TileIsland],
            searchingPlayer: int,
            turns: int,
            blockGatherFromEnemyBorders: bool = True,
            negativeTiles: TileSet | None = None,
    ) -> typing.List[FlowExpansionPlanOption]:
        """
        Build a plan of which islands should flow into which other islands.
        This is basically a bi-directional search from all borders between islands, and currently brute forces all possible combinations.

        @param ourIslands:
        @param targetIslands:
        @param searchingPlayer:
        @param turns:
        @param blockGatherFromEnemyBorders:
        @param negativeTiles:
        @return:
        """

        start = time.perf_counter()

        opts: typing.Dict[typing.Tuple[TileIsland, TileIsland], typing.Dict[int, typing.Tuple[typing.Dict[TileIsland, TileIsland], float, int, int, TileIsland | None, TileIsland | None, int]]] = {}
        """
        Inner tuple is """

        self.team = myTeam = self.map._teams[searchingPlayer]
        self.target_team = targetTeam = targetIslands[0].team

        turnsUsed: int

        targetCalculated: TileIsland
        friendlyUncalculated: TileIsland
        turnsLeft: int
        tilesToCap: int
        armyToCap: int
        targetTiles: typing.Deque[int]
        econValue: float
        visited: typing.Set[TileIsland]
        nextTargets: typing.Set[TileIsland]
        nextFriendlies: typing.Set[TileIsland]
        fromDict: typing.Dict[TileIsland, TileIsland]
        pairOptions: typing.Dict[int, typing.Tuple[typing.Dict[TileIsland, TileIsland], float, int, int, TileIsland | None, TileIsland | None, int]]
        """distance -> (fromDict, econValue, turnsUsed, armyRemaining, incompleteTargetIsland or none, incompleteFriendlyIsland or none, friendlyGatheredSum)"""

        capValue = 2
        if targetIslands[0].team == -1:
            capValue = 1
        if blockGatherFromEnemyBorders:
            friendlyBorderingEnemy = {i for i in itertools.chain.from_iterable(t.bordered for t in targetIslands if t.tile_count_all_adjacent_friendly > 8) if i.team == myTeam}
        else:
            friendlyBorderingEnemy = set()

        q: HeapQueue[typing.Tuple[
            float,
            int,
            int,
            int,
            int,
            int,
            typing.Deque[int],
            float,
            int,
            TileIsland,
            TileIsland,
            typing.Set[TileIsland],
            typing.Set[TileIsland],
            typing.Set[TileIsland],
            typing.Dict[TileIsland, TileIsland],
            typing.Dict[int, typing.Tuple[typing.Dict[TileIsland, TileIsland], float, int, int, TileIsland | None, TileIsland | None, int]],
        ]] = HeapQueue()

        queueIterCount = 0
        tileIterCount = 0
        dumpIterCount = 0
        tieBreaker = 0
        for target in targetIslands:
            for adjacent in target.bordered:
                if adjacent.team != myTeam:
                    continue
                tieBreaker += 1
                pairOptions = {}
                opts[(target, adjacent)] = pairOptions
                # turns+1 because pulling the first tile doesn't count as a move (the tile we move to counts as the move, whether thats to enemy or to another friendly gather tile), however this algo doesn't know whether it is first move or not, so we just start the whole cycle with one extra 'turn' so we can pull that initial tile for free.
                maxPossibleAddlCaps = (adjacent.sum_army - adjacent.tile_count) // 2
                maxPossibleNewEconPerTurn = (maxPossibleAddlCaps * capValue) / (maxPossibleAddlCaps + adjacent.tile_count)
                q.put((
                    maxPossibleNewEconPerTurn,
                    -1,
                    turns + 1,
                    target.tile_count,
                    target.sum_army + target.tile_count,
                    tieBreaker,
                    deque(t.army for t in target.tiles_by_army),
                    0.0,
                    0,
                    target,
                    adjacent,
                    {target},
                    {t for t in target.bordered if t.team == targetTeam},  # nextTargets
                    {t for t in adjacent.bordered if t.team == myTeam and t not in friendlyBorderingEnemy},  # nextFriendlies
                    {target: adjacent},  # fromdict
                    pairOptions
                ))

                logbook.info(f'------------------\r\n---------------\r\nBEGINNING {target.name}<->{adjacent.name}')
                while q:
                    (
                        negVt,
                        turnsUsed,
                        turnsLeft,
                        tilesToCap,
                        armyToCap,
                        randomTieBreak,
                        targetTiles,
                        econValue,
                        gathSum,
                        targetCalculated,
                        friendlyUncalculated,
                        visited,
                        nextTargets,
                        nextFriendlies,
                        fromDict,
                        pairOptions
                    ) = q.get()
                    queueIterCount += 1
                    # if friendlyUncalculated in visited:
                    #     continue
                    visited.add(friendlyUncalculated)
                    visited.add(targetCalculated)
                    # logbook.info(f'Processing {targetCalculated.name} <- {friendlyUncalculated.name}')

                    nextGathedSum = gathSum

                    # have to leave 1's behind when leaving our own land
                    friendlyCappingArmy = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count
                    necessaryToFullyCap = armyToCap
                    # have to leave 1's behind when capping enemy land, too
                    armyLeftIfFullyCapping = friendlyCappingArmy - necessaryToFullyCap
                    turnsLeftIfFullyCapping = turnsLeft - tilesToCap - friendlyUncalculated.tile_count
                    validOpt = True
                    friendlyTileLeftoverIdx = 0
                    frTileLeftoverArmy = 0
                    # TODO turn short circuit back on?
                    if False and turnsLeftIfFullyCapping >= 0 and armyLeftIfFullyCapping >= 0:
                        # then we can actually dump all in and shortcut the more expensive logic
                        turnsLeft = turnsLeftIfFullyCapping
                        armyToCap = 0 - armyLeftIfFullyCapping
                        econValue += tilesToCap * capValue
                        nextGathedSum += friendlyCappingArmy
                        tilesToCap = 0

                        turnsUsed = turns - turnsLeft
                        existingBestTuple = pairOptions.get(turnsUsed, None)

                        if validOpt and (existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed):
                            pairOptions[turnsUsed] = (
                                fromDict,
                                econValue,
                                turnsUsed,
                                0 - armyToCap,
                                None,
                                None,
                                nextGathedSum
                            )
                    else:
                        # then we can't dump it all in, have to do iterative check.

                        armyToDump = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count  # We need to leave 1 army behind per tile.
                        # # ############## we start at 1, because pulling the first tile doesn't count as a move (the tile we move to counts as the move, whether thats to enemy or to another friendly gather tile)
                        # friendlyIdx = 1
                        # frTileArmy = friendlyUncalculated.tiles_by_army[0].army
                        # friendlyIdx = 0
                        friendlyTileLeftoverIdx = len(friendlyUncalculated.tiles_by_army) - 1
                        while armyToDump > 0 and targetTiles and turnsLeft > 0:
                            tgTileArmyToCap = targetTiles.popleft() + 1
                            # if validOpt:
                            dumpIterCount += 1

                            # pull as many fr tiles as necessary to cap the en tile
                            # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
                            while frTileLeftoverArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyTileLeftoverIdx >= 0:
                                frTileArmy = friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
                                nextGathedSum += frTileArmy
                                frTileLeftoverArmy += frTileArmy
                                turnsLeft -= 1
                                friendlyTileLeftoverIdx -= 1
                                # friendlyIdx += 1
                                tileIterCount += 1

                            if frTileLeftoverArmy < tgTileArmyToCap:
                                # validOpt = False
                                targetTiles.appendleft(tgTileArmyToCap - frTileLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
                                # turnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
                                armyToCap -= frTileLeftoverArmy
                                armyToDump = 0
                                break

                            # cap the en tile
                            tilesToCap -= 1
                            econValue += capValue
                            armyToCap -= tgTileArmyToCap
                            armyToDump -= tgTileArmyToCap
                            frTileLeftoverArmy -= tgTileArmyToCap
                            turnsLeft -= 1
                            turnsUsed = turns - turnsLeft
                            existingBestTuple = pairOptions.get(turnsUsed, None)

                            if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed:
                                pairOptions[turnsUsed] = (
                                    fromDict,
                                    econValue,
                                    turnsUsed,
                                    armyToDump,
                                    targetCalculated,
                                    friendlyUncalculated,
                                    nextGathedSum,
                                )
                            if tilesToCap < 0:
                                raise AssertionError('todo remove later, this should never be possible or we would have hit the other case above.')

                        # Necessary because when we terminate the loop early above due to running out of TARGET tiles, we need to keep track of the remaining army we have to gather for the second loop below.
                        armyToCap -= armyToDump

                    if tilesToCap == 0:
                        # we need to include new targets, then.
                        for nextTarget in nextTargets:
                            if nextTarget in visited:
                                # logbook.info(f'skipped targ {nextTarget.name} from {targetCalculated.name}')
                                continue

                            newNextTargets = nextTargets.copy()
                            newNextTargets.discard(nextTarget)
                            for adj in nextTarget.bordered:
                                if adj.team != targetTeam or adj in visited:
                                    continue
                                newNextTargets.add(adj)
                            # newVisiteds = visited.copy()
                            newTilesToCap = tilesToCap + nextTarget.tile_count
                            newEconValue = econValue
                            armyOffset = 0
                            newTargetTiles = deque(t.army for t in nextTarget.tiles_by_army)
                            newTurnsLeft = turnsLeft
                            armyToDump = 0 - armyToCap
                            newArmyToCap = armyToCap
                            newArmyToCap += nextTarget.sum_army + nextTarget.tile_count

                            newFrTileLeftoverArmy = frTileLeftoverArmy
                            while armyToDump > 0 and newTargetTiles and newTurnsLeft > 0:
                                tgTileArmyToCap = newTargetTiles.popleft() + 1
                                # if validOpt:
                                dumpIterCount += 1

                                # pull as many fr tiles as necessary to cap the en tile
                                # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
                                while newFrTileLeftoverArmy < tgTileArmyToCap and newTurnsLeft > 1 and friendlyTileLeftoverIdx >= 0:
                                    newFrTileLeftoverArmy += friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
                                    newTurnsLeft -= 1
                                    friendlyTileLeftoverIdx -= 1
                                    # friendlyIdx += 1
                                    tileIterCount += 1

                                if newFrTileLeftoverArmy < tgTileArmyToCap:
                                    # validOpt = False
                                    newTargetTiles.appendleft(tgTileArmyToCap - newFrTileLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
                                    # turnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
                                    newArmyToCap -= newFrTileLeftoverArmy
                                    # armyToDump = 0
                                    break

                                # cap the en tile
                                newTilesToCap -= 1
                                newEconValue += capValue
                                newArmyToCap -= tgTileArmyToCap
                                armyToDump -= tgTileArmyToCap
                                newFrTileLeftoverArmy -= tgTileArmyToCap
                                newTurnsLeft -= 1

                                turnsUsed = turns - newTurnsLeft
                                existingBestTuple = pairOptions.get(turnsUsed, None)

                                if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < newEconValue / turnsUsed:
                                    pairOptions[turnsUsed] = (
                                        fromDict,
                                        newEconValue,
                                        turnsUsed,
                                        armyToDump,
                                        nextTarget,
                                        friendlyUncalculated,
                                        nextGathedSum
                                    )
                            # armyLeftOver = 0 - armyToCap
                            # while armyLeftOver > 0 and newTargetTiles:
                            #     tileArmyToCap = newTargetTiles.popleft() + 1
                            #
                            #     if tileArmyToCap > armyLeftOver:
                            #         newTargetTiles.appendleft(tileArmyToCap - 1)
                            #         break
                            #
                            #     # then we technically actually pre-capture some of the tiles to capture here
                            #     #  ought to increment newTilesCapped and decrement newTilesToCap based on the tile values in the island...?
                            #     newTilesToCap -= 1
                            #     newEconValue += capValue
                            #     newArmyToCap -= tileArmyToCap
                            #     armyLeftOver -= tileArmyToCap
                            #     newTurnsLeft -= 1
                            #
                            #     if newArmyToCap <= 0:
                            #         turnsUsed = turns - newTurnsLeft
                            #         existingBestTuple = pairOptions.get(turnsUsed, None)
                            #
                            #         if existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed:
                            #             pairOptions[turnsUsed] = (
                            #                 fromDict,
                            #                 newEconValue,
                            #                 turnsUsed,
                            #                 0 - newArmyToCap
                            #             )
                            #

                            turnsUsed = turns - turnsLeft
                            for newFriendlyUncalculated in nextFriendlies:
                                newFromDict = fromDict.copy()
                                if newFriendlyUncalculated in visited:
                                    # logbook.info(f'skipped src  {newFriendlyUncalculated.name} from {friendlyUncalculated.name}')
                                    continue

                                newNextFriendlies = nextFriendlies.copy()
                                newNextFriendlies.discard(newFriendlyUncalculated)
                                for adj in newFriendlyUncalculated.bordered:
                                    if adj.team != myTeam or adj in visited or adj in friendlyBorderingEnemy:
                                        continue
                                    newNextFriendlies.add(adj)

                                maxPossibleAddlCaps = (newFriendlyUncalculated.sum_army - newFriendlyUncalculated.tile_count) // 2
                                maxPossibleNewEconPerTurn = (newEconValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + newFriendlyUncalculated.tile_count)

                                newFromDict[newFriendlyUncalculated] = friendlyUncalculated
                                newFromDict[nextTarget] = targetCalculated
                                tieBreaker += 1
                                q.put((0 - maxPossibleNewEconPerTurn, turnsUsed, newTurnsLeft, newTilesToCap, newArmyToCap, tieBreaker, newTargetTiles, newEconValue, nextGathedSum, nextTarget, newFriendlyUncalculated, visited,
                                       newNextTargets, newNextFriendlies, newFromDict, pairOptions))
                    else:
                        turnsUsed = turns - turnsLeft
                        for newFriendlyUncalculated in nextFriendlies:
                            if newFriendlyUncalculated in visited:
                                # logbook.info(f'skipped src  {newFriendlyUncalculated.name} from {friendlyUncalculated.name}')
                                continue

                            newNextFriendlies = nextFriendlies.copy()
                            newNextFriendlies.discard(newFriendlyUncalculated)
                            for adj in newFriendlyUncalculated.bordered:
                                if adj.team != myTeam or adj in visited:
                                    continue
                                newNextFriendlies.add(adj)

                            newFromDict = fromDict.copy()
                            newFromDict[newFriendlyUncalculated] = friendlyUncalculated
                            maxPossibleAddlCaps = (newFriendlyUncalculated.sum_army - newFriendlyUncalculated.tile_count) // 2
                            maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + newFriendlyUncalculated.tile_count)
                            tieBreaker += 1
                            q.put((0 - maxPossibleNewEconPerTurn, turnsUsed, turnsLeft, tilesToCap, armyToCap, tieBreaker, targetTiles.copy(), econValue, nextGathedSum, targetCalculated, newFriendlyUncalculated, visited, nextTargets,
                                   newNextFriendlies, newFromDict, pairOptions))

        output = []
        for (target, source), planOptionsByTurns in opts.items():
            for turns, (fromDict, econValue, otherTurns, armyRemaining, incompleteTarget, incompleteSource, gathedArmySum) in planOptionsByTurns.items():
                if otherTurns != turns:
                    raise AssertionError(f'Shouldnt happen, turn mismatch {turns} vs {otherTurns}')

                if armyRemaining < 0:
                    # then this is a partial capture option, we already pruned out the other moves in theory, and it is already worst-case moves assuming our largest tiles are furthest and their largest tiles are in front
                    armyRemaining = 0

                plan = self.build_flow_expansion_option(target, source, fromDict, econValue, armyRemaining, turns, targetIslands, ourIslands, incompleteTarget, incompleteSource)

                output.append(plan)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion complete in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')

        return output


    def build_flow_expansion_option(
            self,
            target: TileIsland,
            source: TileIsland,
            fromDict: typing.Dict[TileIsland, TileIsland],
            econValue: float,
            armyRemaining: int,
            turns,
            targetIslands: typing.List[TileIsland],
            ourIslands: typing.List[TileIsland],
            incompleteTarget: TileIsland | None,
            incompleteSource: TileIsland | None
    ) -> FlowExpansionPlanOption:
        logbook.info(f'building plan for {source.name}->{target.name} (econ {econValue:.2f} turns {turns} army rem {armyRemaining})')
        moves, captures, finalTurns = self._calculate_moves_and_captures(target, source, fromDict, targetIslands, ourIslands, incompleteTarget, incompleteSource)
        plan = FlowExpansionPlanOption(
            moves,
            econValue,
            turns,  # TODO should be finalTurns once implemented
            captures,
            armyRemaining
        )

        return plan


    def _calculate_moves_and_captures(
            self,
            target: TileIsland,
            source: TileIsland,
            fromDict: typing.Dict[TileIsland, TileIsland],
            targetIslands: typing.List[TileIsland],
            ourIslands: typing.List[TileIsland],
            incompleteTarget: TileIsland | None,
            incompleteSource: TileIsland | None,
            negativeTiles: TileSet | None = None,
    ) -> typing.Tuple[typing.List[Move], int, int]:
        """
        return  moves, captures, finalTurns
        @param target:
        @param source:
        @param fromDict:
        @return:  moves, captures, finalTurns
        """
        # TODO we want to keep our moves as wide across any borders as possible, if we combine everything into one big tile then we have the potential to waste moves.
        # need to build our initial lines outwards from the border as straight as possible, then combine as needed as captures fail.
        # fromMatrix: MapMatrixInterface[Tile] = MapMatrix(self.map)
        # fromArmy: MapMatrixInterface[int] = MapMatrix(self.map)

        # border = set(itertools.chain.from_iterable(t.movable for t in target.tile_set if t in source.tile_set))
        capping = set()
        gathing = set()
        targetTeam = self.target_team
        team = self.team

        for toIsland, fromIsland in fromDict.items():
            if toIsland == incompleteTarget:
                pass
            else:
                if toIsland.team == team:
                    gathing.update(toIsland.tile_set)
                else:
                    capping.update(toIsland.tile_set)

            if fromIsland == incompleteSource:
                pass
            else:
                if fromIsland.team == team:
                    gathing.update(fromIsland.tile_set)
                else:
                    capping.update(fromIsland.tile_set)

        if len(capping) > 1000:
            from Viewer import ViewerProcessHost

            inf = f'capping {len(capping)}, gathing {len(gathing)}'
            debugViewInfo = ViewerProcessHost.get_renderable_view_info(self.map)
            for tile in capping:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.RED)
            for tile in gathing:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.GREEN)
            if incompleteTarget:
                for tile in incompleteTarget.tile_set:
                    debugViewInfo.add_targeted_tile(tile, TargetStyle.ORANGE)
            if incompleteSource:
                for tile in incompleteSource.tile_set:
                    debugViewInfo.add_targeted_tile(tile, TargetStyle.BLUE)

            for island in sorted(itertools.chain.from_iterable([targetIslands, ourIslands]), key=lambda i: (i.team, str(i.name))):
                color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

                debugViewInfo.add_map_zone(island.tile_set, color, alpha=80)
                debugViewInfo.add_map_division(island.tile_set, color, alpha=200)
                if island.name:
                    for tile in island.tile_set:
                        if debugViewInfo.bottomRightGridText[tile]:
                            debugViewInfo.midRightGridText[tile] = island.name
                        else:
                            debugViewInfo.bottomRightGridText[tile] = island.name

                debugViewInfo.add_info_line_no_log(f'{island.team}: island {island.name} - {island.sum_army}a/{island.tile_count}t ({island.sum_army_all_adjacent_friendly}a/{island.tile_count_all_adjacent_friendly}t) {str(island.tile_set)}')

            ViewerProcessHost.render_view_info_debug(inf, inf, self.map, debugViewInfo)

        # q = deque()
        # # border = set()
        # for tile in gathing:
        #     for adj in tile.movable:
        #         if adj not in capping:
        #             continue
        #         border.add((tile, adj))

        # visited = set()
        # while q

        # tilesToKill =
        #
        # q = deque()
        # for t in border:
        moves = []
        captures = 0
        finalTurns = 0
        return moves, captures, finalTurns
