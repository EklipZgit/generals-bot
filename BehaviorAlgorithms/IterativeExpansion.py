from __future__ import annotations

import heapq
import itertools
import random
import time
import typing
from collections import deque
from enum import Enum

from BehaviorAlgorithms.Flow.FlowGraphModels import FlowGraphMethod, IslandFlowNode, IslandFlowEdge, IslandMaxFlowGraph, FlowExpansionPlanOption
from BehaviorAlgorithms.Flow.NxFlowGraphData import NxFlowGraphData

import logbook
import networkx as nx

import DebugHelper
import Gather
import SearchUtils
from Gather import GatherDebug, GatherCapturePlan
from MapMatrix import MapMatrix
from Path import Path
from Algorithms import TileIslandBuilder, TileIsland
from BoardAnalyzer import BoardAnalyzer
from Models import Move
from Interfaces import MapMatrixInterface, TileSet
from PerformanceTimer import PerformanceTimer
from ViewInfo import ViewInfo, TargetStyle, PathColorer
from base import Colors
from base.client.map import MapBase, Tile
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.PyMaxFlowIteratorHelpers import compute_island_max_flow_with_pymaxflow

ITERATIVE_EXPANSION_EN_CAP_VAL = 2.2


def _deep_copy_flow_nodes(rootNodes: typing.Iterable[IslandFlowNode], cloneScopeLookup: typing.Dict[int, IslandFlowNode]) -> typing.Iterable[IslandFlowNode]:
    """
    returns an iterable on deep copies of the original root nodes (in their original order). Reuses nodes from, and backfills, the cloneScopeLookup node table.

    Infinite loops if there are cycles.
    """
    q: typing.List[typing.Tuple[IslandFlowNode | None, int, IslandFlowNode]] = []
    """fromCloneNode, toOriginalNode"""
    for r in rootNodes:
        q.append((None, 0, r))

    while q:
        sourceClone, flowAmt, destOriginal = q.pop()
        destId = destOriginal.island.unique_id
        destClone = cloneScopeLookup.get(destId, None)
        if destClone is None:
            destClone = IslandFlowNode(destOriginal.island, destOriginal.desired_army)
            cloneScopeLookup[destId] = destClone

        if sourceClone is not None:
            sourceClone.set_flow_to(destClone, flowAmt)

        for destEdge in destOriginal.flow_to:
            q.append((destClone, destEdge.edge_army, destEdge.target_flow_node))

    nodeIterable = (cloneScopeLookup[r.island.unique_id] for r in rootNodes)
    return nodeIterable


def _deep_copy_flow_node(rootNode: IslandFlowNode, cloneScopeLookup: typing.Dict[int, IslandFlowNode]) -> IslandFlowNode:
    """
    Infinite loops if there are cycles. Reuses nodes from, and backfills, the cloneScopeLookup node table.
    """
    q: typing.List[typing.Tuple[IslandFlowNode | None, int, IslandFlowNode]] = []
    """fromCloneNode, toOriginalNode"""

    q.append((None, 0, rootNode))

    while q:
        sourceClone, flowAmt, destOriginal = q.pop()
        destId = destOriginal.island.unique_id
        destClone = cloneScopeLookup.get(destId, None)
        if destClone is None:
            destClone = IslandFlowNode(destOriginal.island, destOriginal.desired_army)
            cloneScopeLookup[destId] = destClone

        if sourceClone is not None:
            sourceClone.set_flow_to(destClone, flowAmt)

        for destEdge in destOriginal.flow_to:
            q.append((destClone, destEdge.edge_army, destEdge.target_flow_node))

    return cloneScopeLookup[rootNode.island.unique_id]


class FlowExpansionPlanOptionCollection(object):
    def __init__(self):
        self.flow_plans: typing.List[FlowExpansionPlanOption] = []
        self.best_plans_by_tile: MapMatrixInterface[FlowExpansionPlanOption] = None
        self.superset_flow_plans: typing.List[FlowExpansionPlanOption] = []


class FlowGraphDebugStats(object):
    def __init__(self, redArmy: int = 0, blueArmy: int = 0, enemyGeneralBalance: int = 0):
        self.red_army_total: int = redArmy
        self.blue_army_total: int = blueArmy
        self.enemy_general_balance: int = enemyGeneralBalance

    def summary_line(self, label: str = '') -> str:
        mode = 'backpressure' if self.enemy_general_balance < 0 else 'sink'
        return f'{label}: redArmy={self.red_army_total}, blueArmy={self.blue_army_total}, enGen{mode}={self.enemy_general_balance}'


class ArmyFlowExpanderLastRun(object):
    def __init__(self):
        self.flow_stats_no_neut: FlowGraphDebugStats = FlowGraphDebugStats()
        self.flow_stats_inc_neut: FlowGraphDebugStats = FlowGraphDebugStats()


class ArmyFlowExpander(object):
    def __init__(self, map: MapBase, perfTimer: PerformanceTimer | None = None):
        self.map: MapBase = map
        self.perf_timer: PerformanceTimer = perfTimer
        if self.perf_timer is None:
            self.perf_timer = PerformanceTimer()
            self.perf_timer.begin_move(map.turn)
        self.team: int = map.team_ids_by_player_index[map.player_index]
        self.friendlyGeneral: Tile = map.generals[map.player_index]
        self.target_team: int = -1
        self.enemyGeneral: Tile | None = None
        self.island_builder: TileIslandBuilder = None
        self.dists_to_target_large_island: MapMatrixInterface[int] = None

        self.method: FlowGraphMethod = FlowGraphMethod.MinCostFlow

        self.flow_graph: IslandMaxFlowGraph | None = None
        self.last_run: ArmyFlowExpanderLastRun = ArmyFlowExpanderLastRun()
        self._networkx_flow_direction_finder: NetworkXFlowDirectionFinder | None = None

        self.debug_render_capture_count_threshold: int = 10000
        """If there are more captures in any given plan option than this, then the option will be rendered inline as generated in a new debug viewer window."""

        self.log_debug: bool = DebugHelper.is_debug_or_unit_test_mode()
        self.use_debug_asserts: bool = True

        # TODO determine if this should always be true when using use_min_cost_flow_edges_only=True  Turning this on produces worse plans with max flow
        self.use_all_pairs_visited: bool = True
        """If True, a global visited set will be used to avoid finding overlapping gathers from multiple contact points. If false (much slower) we will build a visited set per border with enemy land."""
        #
        # self.include_neutral_flow: bool = True
        # """Whether or not to allow flowing into neutral tiles. Make sure to set this before calling any methods on the class, as cached graph data will have already used or not used it once cached."""

        self.use_min_cost_flow_edges_only: bool = True
        """If true, use the min-cost-max-flow flownodes to route army. Otherwise, brute force / AStar."""

        self.use_backpressure_from_enemy_general: bool = True
        """If True, lets the enemy general push back."""

        # self.block_cross_gather_from_enemy_borders: bool = False
        # """If true, tries to prevent criss-cross gathers that pull other border tiles to attack another border."""

        self._dynamic_heuristic_ratio: float = 1.0
        """As we get low on time this will be altered to find longer, less precise plans faster."""
        self._dynamic_heuristic_falsehood_ratio: float = 0.0
        """As we get low on time, this will be increased from zero to begin an inconsistent heuristic that prefers gathering larger amounts of army per turn, but stops guaranteeing (nearly) optimal results."""

    def get_expansion_options(
            self,
            islands: TileIslandBuilder,
            asPlayer: int,
            targetPlayer: int,
            turns: int,
            boardAnalysis: BoardAnalyzer,
            territoryMap: MapMatrixInterface[int],
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
            cutoffTime: float | None = None
    ) -> FlowExpansionPlanOptionCollection:
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
        # startTiles: typing.Dict[Tile, typing.Tuple[FlowExpansionVal, int]] = {}
        # friendlyPlayers = self.map.get_teammates(asPlayer)
        # targetPlayers = self.map.get_teammates(targetPlayer)

        # blah = self.find_flow_plans_nx_maxflow(islands, ourIslands, targetIslands, asPlayer, turns, negativeTiles=negativeTiles)

        # self.flow_graph = self.build_max_flow_min_cost_flow_nodes(
        #     islands,
        #     ourIslands,
        #     targetIslands,
        #     searchingPlayer,
        #     turns,
        #     blockGatherFromEnemyBorders,
        #     negativeTiles
        # )

        plans = self.find_flow_plans(islands, boardAnalysis, asPlayer, targetPlayer, turns, negativeTiles=negativeTiles, cutoffTime=cutoffTime)

        start = time.perf_counter()

        finalPlans = self.filter_plans_by_common_supersets_and_sort(plans)
        logbook.info(f'finished pruning flow plans in {time.perf_counter() - start:.5f} additional seconds')
        return finalPlans

    def filter_plans_by_common_supersets_and_sort(self, plans: typing.List[FlowExpansionPlanOption]) -> FlowExpansionPlanOptionCollection:
        # this forces us to not eliminate longer larger gathers with tiny little leaf-move style captures.
        # Prio first by longer lengths, then by whether they had any captures, and THEN by econ value.
        start = time.perf_counter()
        plans.sort(key=lambda p: (p.length > 8, len(p.approximate_capture_tiles) > 2, p.econValue / p.length), reverse=True)

        finalPlans = []

        # unvisited = {t for t in self.map.pathableTiles}
        plansVisited: MapMatrixInterface[PlanDupeChecker] = MapMatrix(self.map, None)
        bestPlanByTile: MapMatrixInterface[FlowExpansionPlanOption] = MapMatrix(self.map, None)

        planSets = []

        for plan in plans:
            planSet = None
            illegalPlan = False
            for tile in plan.tileSet:
                existing = plansVisited.raw[tile.tile_index]
                if existing is not None:
                    if planSet is not None and planSet != existing:
                        illegalPlan = True
                        if self.log_debug:
                            logbook.info(f'bypassed {plan.shortInfo()} due to crossover on {tile} with {existing} (and {planSet})')
                        break
                    planSet = existing

            if illegalPlan:
                continue

            newTiles = plan.tileSet
            if planSet is None:
                if self.log_debug:
                    logbook.info(f'BRAND NEW SETS {plan.shortInfo()}')
                planSet = PlanDupeChecker()
                planSets.append(planSet)
            else:
                diff = plan.tileSet.symmetric_difference(planSet.set)
                if len(diff) == 0:
                    if self.log_debug:
                        logbook.info(f'bypassed same but lower vt {plan.shortInfo()} due to exact tile match in {planSet}')
                    continue

                if diff.issubset(plan.tileSet):
                    newTiles = diff
                    if self.log_debug:
                        logbook.info(f'INCLUSION SUPERSET UPDATES FROM {planSet} to {plan.shortInfo()}')
                else:
                    newTiles = diff.intersection(plan.tileSet)
                    if self.log_debug:
                        logbook.info(f'INCLUSION SINGLE OVERLAP SETS {plan.shortInfo()} FOR JUST {[t for t in newTiles]}')

            planSet.plans.append(plan)
            planSet.set.update(newTiles)
            for tile in newTiles:
                plansVisited.raw[tile.tile_index] = planSet
                bestPlanByTile.raw[tile.tile_index] = plan

            if illegalPlan:
                continue

            if self.log_debug:
                logbook.info(f'INCLUDING {plan.shortInfo()}')
            finalPlans.append(plan)

        finalPlans = sorted(finalPlans, key=lambda p: (p.econValue / p.length, p.length), reverse=True)

        superSetPlans = []
        planContainer = FlowExpansionPlanOptionCollection()
        planContainer.flow_plans = finalPlans
        for planSet in planSets:
            planSet.plans.sort(key=lambda p: (p.length, p.econValue), reverse=True)

            unIncluded = planSet.set.copy()
            for flowPlan in planSet.plans:
                includeSuper = False
                for tile in flowPlan.tileSet:
                    if tile in unIncluded:
                        unIncluded.discard(tile)
                        includeSuper = True

                if includeSuper:
                    superSetPlans.append(flowPlan)
            #
            # exist = plansVisited.raw[tile.tile_index]
            # if exist is not None:
            #     # ignore warning, we're intentionally changing the type of the contents in the matrix
            #     plansVisited.raw[tile.tile_index] = exist.plan

        logbook.info(f'filter_plans_by_common_supersets_and_sort sorted and supersetted in {time.perf_counter() - start:.5f}s')

        planContainer.best_plans_by_tile = bestPlanByTile
        planContainer.superset_flow_plans = superSetPlans

        return planContainer

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
        self.ensure_flow_graph_exists(islands)
        flowGraph = self._build_max_flow_min_cost_flow_nodes(
            islands,
            ourIslands,
            targetIslands,
            searchingPlayer,
            turns,
            # blockGatherFromEnemyBorders=
            includeNeutralDemand=True,
            negativeTiles=negativeTiles,
            method=FlowGraphMethod.MinCostFlow
        )

        return []

    def _get_networkx_flow_direction_finder(self) -> NetworkXFlowDirectionFinder:
        if self._networkx_flow_direction_finder is None:
            self._networkx_flow_direction_finder = NetworkXFlowDirectionFinder(
                self.map,
                self.island_builder.intergeneral_analysis,
                self.friendlyGeneral,
                self.use_backpressure_from_enemy_general,
                self.perf_timer,
                self.log_debug,
                self.live_render_invalid_flow_config,
            )
        self._networkx_flow_direction_finder.configure(self.team, self.target_team, self.enemyGeneral)
        return self._networkx_flow_direction_finder

    def _get_island_max_flow_dict(
            self,
            islands: TileIslandBuilder,
            graphData: NxFlowGraphData,
            method: FlowGraphMethod = FlowGraphMethod.NetworkSimplex,
            render_on_exception: bool = True
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        """Returns the flow dict produced from the input graph data"""
        return self._get_networkx_flow_direction_finder().get_island_max_flow_dict(islands, graphData, method, render_on_exception)

    def _build_max_flow_min_cost_flow_nodes(
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
    ) -> IslandMaxFlowGraph:
        """Returns the list of root IslandFlowNodes that have nothing that flows in to them. The entire graph can be traversed from the root nodes (from possibly multiple directions)."""
        return self._get_networkx_flow_direction_finder().build_max_flow_min_cost_flow_nodes(
            islands,
            ourIslands,
            targetIslands,
            searchingPlayer,
            turns,
            blockGatherFromEnemyBorders,
            negativeTiles,
            includeNeutralDemand,
            method
        )

    def get_flow_nodes_from_lookups(
            self,
            ourIslands: list[TileIsland],
            targetGeneralIsland: TileIsland,
            targetIslands: list[TileIsland],
            withNeutFlowDict: dict[int, dict[int, int]],
            graphLookup: dict[int, IslandFlowNode],
            nxGraphData: NxFlowGraphData,
    ) -> tuple[list[IslandFlowEdge], list[IslandFlowNode], list[IslandFlowNode]]:
        """
        Converts nx flow graph data into flow edges and flow nodes.

        :param ourIslands:
        :param targetGeneralIsland:
        :param targetIslands:
        :param withNeutFlowDict:
        :param graphLookup:
        :param nxGraphData:
        :return: backfillNeutEdges, enemyBackfillFlowNodes, finalRootFlowNodes
        """
        return self._get_networkx_flow_direction_finder().get_flow_nodes_from_lookups(
            ourIslands,
            targetGeneralIsland,
            targetIslands,
            withNeutFlowDict,
            graphLookup,
            nxGraphData,
        )

    def find_flow_plans(
            self,
            islands: TileIslandBuilder,
            boardAnalysis: BoardAnalyzer,
            searchingPlayer: int,
            targetPlayer: int,
            turns: int,
            negativeTiles: TileSet | None = None,
            cutoffTime: float | None = None
    ) -> typing.List[FlowExpansionPlanOption]:
        """
        Build a plan of which islands should flow into which other islands.
        This is basically a bi-directional search from all borders between islands, and currently brute forces all possible combinations.

        @param islands:
        @param boardAnalysis:
        @param searchingPlayer:
        @param targetPlayer:
        @param turns:
        @param negativeTiles:
        @param cutoffTime: time.perf_counter() time to stop at.
        @return:
        """

        start = time.perf_counter()

        opts: typing.Dict[typing.Tuple[TileIsland, TileIsland], typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]]] = {}
        """"""

        self._seeded_pairs: typing.Dict[int, typing.Set[int]] = {}  # targetIsland.unique_id -> set of seeded friendlyIsland.unique_ids

        self.team = myTeam = self.map.team_ids_by_player_index[searchingPlayer]
        self.target_team = targetTeam = self.map.team_ids_by_player_index[targetPlayer]
        self.island_builder = islands
        self.dists_to_target_large_island = islands.large_tile_island_distances_by_team_id[targetTeam]
        if self.dists_to_target_large_island is None:
            self.dists_to_target_large_island = boardAnalysis.intergeneral_analysis.bMap

        ourIslands = islands.tile_islands_by_player[searchingPlayer]
        targetIslands = islands.tile_islands_by_team_id[targetTeam]

        if self.use_min_cost_flow_edges_only:
            # method = FlowGraphMethod.CapacityScaling  # 67ms on test_should_recognize_gather_into_top_path_is_best (with single-tile islands on borders)
            # method = FlowGraphMethod.MinCostFlow    # 6.5ms on test_should_recognize_gather_into_top_path_is_best (with single-tile islands on borders)
            # method = FlowGraphMethod.NetworkSimplex    # 9ms on test_should_recognize_gather_into_top_path_is_best (with single-tile islands on borders)
            # method = FlowGraphMethod.MinCostFlow
            method = self.method
            # method = FlowGraphMethod.PyMaxflowWithNodeSplitting


            # Build the flow graph data - needed by both NetworkX and PyMaxflow
            # PyMaxflow converts from NetworkX graph format internally
            with self.perf_timer.begin_move_event('ensure_flow_graph_exists'):
                self.ensure_flow_graph_exists(islands)

            with self.perf_timer.begin_move_event('_build_max_flow_min_cost_flow_nodes'):
                self.flow_graph = self._build_max_flow_min_cost_flow_nodes(
                    islands,
                    ourIslands,
                    targetIslands,
                    searchingPlayer,
                    turns,
                    # blockGatherFromEnemyBorders=
                    includeNeutralDemand=True,
                    negativeTiles=negativeTiles,
                    method=method
                )
                self._capture_last_run_flow_stats()

        turnsUsed: int

        targetCalculatedNode: IslandFlowNode
        friendlyUncalculatedNone: IslandFlowNode
        targetCalculated: TileIsland
        friendlyUncalculated: TileIsland
        turnsLeft: int
        numTilesLeftToCapFromTarget: int
        uncappedTargetIslandArmy: int
        frLeftoverArmy: int
        friendlyTileLeftoverIdx: int
        targetTiles: typing.Deque[int]
        """Uncaptured target tiles"""
        econValue: float
        visited: typing.Set[TileIsland]
        """This is NOT global, but per-border-island-pair"""
        nextTargets: typing.Dict[TileIsland, IslandFlowNode]
        nextFriendlies: typing.Dict[TileIsland, IslandFlowNode | None]
        rootNodes: typing.Dict[int, IslandFlowNode]
        pairOptions: typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]]
        """for each starting border pair, a new dict of distance -> (flowGraph, econValue, turnsUsed, armyRemainingTotal, incompleteTargetIsland or none, incompleteFriendlyIsland or none, unusedIncompleteSourceArmy, friendlyGatheredSum)"""

        maxTeam = max(self.map.team_ids_by_player_index)
        capValueByTeam = [1.0 for t in range(maxTeam + 2)]
        capValueByTeam[myTeam] = 0.0
        # TODO intentional decision for now to value flow expansion en caps lower than other expansion-fed algos do, to prioritize their more concrete results over these wishywashy results.
        capValueByTeam[targetTeam] = ITERATIVE_EXPANSION_EN_CAP_VAL

        friendlyBorderingEnemy = None
        # if self.block_cross_gather_from_enemy_borders:
        #     friendlyBorderingEnemy = {i for i in itertools.chain.from_iterable(t.border_islands for t in targetIslands if t.tile_count_all_adjacent_friendly > 8) if i.team == myTeam}
        # else:
        #     friendlyBorderingEnemy = set()

        with self.perf_timer.begin_move_event('main flow node aStar in find_flow_plans'):
            q: SearchUtils.HeapQueueMax[typing.Tuple[
                float,
                int,
                int,
                int,
                int,
                typing.Deque[int],
                float,
                int,
                int,
                int,
                IslandFlowNode,
                IslandFlowNode,
                typing.Set[TileIsland],
                typing.Dict[TileIsland, IslandFlowNode],
                typing.Dict[TileIsland, IslandFlowNode],
                typing.Dict[int, IslandFlowNode],
                typing.Dict[int, typing.Tuple[typing.Dict[int, IslandFlowNode], float, int, int, TileIsland | None, TileIsland | None, int | None, int]],
            ]] = SearchUtils.HeapQueueMax()

            queueIterCount = 0
            tileIterCount = 0
            dumpIterCount = 0
            tieBreaker = 0

            globalVisited = set()

            for targetIsland in islands.all_tile_islands:
                if targetIsland.team == myTeam:
                    continue
                for adjacentFriendlyIsland in targetIsland.border_islands:
                    if adjacentFriendlyIsland.team != myTeam:
                        continue

                    if not self._is_flow_allowed(adjacentFriendlyIsland, targetIsland, armyAmount=0):
                        continue

                    tgCapValue = capValueByTeam[targetIsland.team]
                    tieBreaker += 1
                    pairOptions = {}
                    opts[(targetIsland, adjacentFriendlyIsland)] = pairOptions
                    seededFriendlies = self._seeded_pairs.get(targetIsland.unique_id)
                    if seededFriendlies is None:
                        seededFriendlies = set()
                        self._seeded_pairs[targetIsland.unique_id] = seededFriendlies
                    seededFriendlies.add(adjacentFriendlyIsland.unique_id)

                    sourceNode = IslandFlowNode(adjacentFriendlyIsland, desiredArmy=0 - adjacentFriendlyIsland.sum_army + adjacentFriendlyIsland.tile_count)
                    destNode = IslandFlowNode(targetIsland, desiredArmy=targetIsland.sum_army + targetIsland.tile_count)
                    if self.log_debug:
                        logbook.info(f'ADDING EDGE (start) FROM {sourceNode} TO {destNode}')
                    sourceNode.set_flow_to(destNode, 0)
                    if not self.use_all_pairs_visited:
                        visited = set()
                    else:
                        visited = globalVisited
                    # visited.add(targetIsland)
                    # visited.add(adjacentFriendlyIsland)
                    frLeftoverIdx = sourceNode.island.tile_count - 1
                    tgTiles = deque(t.army for t in targetIsland.tiles_by_army)

                    nextTargs = {}
                    nextFriendlies = {}

                    for altNext in adjacentFriendlyIsland.border_islands:
                        if altNext == targetIsland:
                            continue
                        # if altNext.team != myTeam and altNext not in nextTargs:
                        #     nextTargs[altNext] = sourceNode
                        if altNext.team == myTeam and altNext not in nextFriendlies:
                            # if altNext not in friendlyBorderingEnemy:
                            nextFriendlies[altNext] = sourceNode

                    for altNext in targetIsland.border_islands:
                        if altNext == adjacentFriendlyIsland:
                            continue
                        # if altNext.team != myTeam and altNext not in nextTargs:
                        #     nextTargs[altNext] = destNode
                        # if altNext.team == myTeam and altNext not in nextFriendlies:
                        #     # if altNext not in friendlyBorderingEnemy:
                        #     nextFriendlies[altNext] = destNode

                        # allow 'targeting' our own tiles, as we may need to pass through them on the way to capture lots of enemy tiles.
                        if altNext not in nextTargs and altNext not in nextFriendlies:
                            nextTargs[altNext] = destNode

                    self.enqueue(
                        q,
                        self._get_a_star_priority_val(tgCapValue, 0.0, 0, 0, frLeftoverIdx, adjacentFriendlyIsland, targetIsland, searchTurns=turns, tgTiles=tgTiles),
                        0,
                        turns + 1,  # turns + 1 (and turns left -1) because the very first tile doesn't count as a move, as only the dest counts.
                        targetIsland.sum_army + targetIsland.tile_count,
                        tieBreaker,
                        tgTiles,
                        0.0,
                        0,
                        0,  # frTileLeftoverArmy,
                        frLeftoverIdx,  # friendlyTileLeftoverIdx,
                        destNode,
                        sourceNode,
                        visited,
                        nextTargs,  # nextTargets
                        nextFriendlies,  # nextFriendlies
                        {sourceNode.island.unique_id: sourceNode},  # rootNodes
                        pairOptions
                    )

            start = time.perf_counter()
            if cutoffTime is None:
                cutoffTime = start + 300.0

            fullTime = cutoffTime - start
            stage1Time = fullTime / 6
            stage2Time = 2 * fullTime / 6
            stage3Time = 3 * fullTime / 6
            stage4Time = 4 * fullTime / 6

            self._dynamic_heuristic_ratio = 1.0
            self._dynamic_heuristic_falsehood_ratio = 0.0
            stage1Ratio = 1.1
            stage2Ratio = 1.3
            stage3Ratio = 1.5
            stage4Ratio = 2.0
            logbook.info(f'beginning flow expand heuristic loop for {fullTime:.5f}s')

            while q:
                (
                    negVt,
                    turnsUsed,
                    turnsLeft,
                    uncappedTargetIslandArmy,
                    randomTieBreak,
                    targetTiles,
                    econValue,
                    gathSum,
                    frLeftoverArmy,
                    friendlyTileLeftoverIdx,
                    targetCalculatedNode,
                    friendlyUncalculatedNode,
                    visited,
                    nextTargets,
                    nextFriendlies,
                    rootNodes,
                    pairOptions
                ) = q.get()

                # TODO this should not be necessary...
                if turnsLeft <= 0:
                    continue

                targetTiles = targetTiles.copy()
                # TODO THESE ARE FOR DEBUGGING PURPOSES TO ENSURE NO REFERENCE CROSS SECTION AND TO WHITTLE DOWN WHICH VARIABLE IS THE PROBLEM:
                # tempLookup = {}
                # rootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), tempLookup)}
                # targetCalculatedNode = _deep_copy_flow_node(targetCalculatedNode, tempLookup)
                # friendlyUncalculatedNode = _deep_copy_flow_node(friendlyUncalculatedNode, tempLookup)
                # nextFriendlies = {island: _deep_copy_flow_node(n, tempLookup) for island, n in nextFriendlies.items()}
                # nextTargets = {island: _deep_copy_flow_node(n, tempLookup) for island, n in nextTargets.items()}
                # END TODO

                # visited = visited.copy()

                targetCalculated = targetCalculatedNode.island
                friendlyUncalculated = friendlyUncalculatedNode.island
                if self.log_debug:
                    logbook.info(
                        f'\r\n  popped {friendlyUncalculated} -...-> {targetCalculated}'
                        f'\r\n        negVt: {negVt}'
                        f'\r\n        rootNodes: {" | ".join(str(n.island.shortIdent()) for n in rootNodes.values())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_children(rootNodes.values()))}'
                        f'\r\n        nextFriendlies {" | ".join(str(n.shortIdent()) for n in nextFriendlies.keys())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(nextFriendlies.values()))}'
                        f'\r\n        nextTargets {" | ".join(str(n.shortIdent()) for n in nextTargets.keys())}  <-  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(nextTargets.values()))}'
                        f'\r\n        turnsUsed: {turnsUsed}, turnsLeft: {turnsLeft}'
                        f'\r\n        uncappedTargetIslandArmy: {uncappedTargetIslandArmy}, targetTiles: {repr(targetTiles)}'
                        f'\r\n        econValue: {econValue:.3f}, gathSum: {gathSum}'
                        f'\r\n        frLeftoverArmy: {frLeftoverArmy}, friendlyTileLeftoverIdx: {friendlyTileLeftoverIdx}'
                        f'\r\n        visited: {({t.shortIdent() for t in visited})}'
                    )
                queueIterCount += 1
                if queueIterCount & 31 == 0:
                    used = time.perf_counter() - start
                    if used > fullTime:
                        logbook.info(f'flow expand terminating early due to used {used:.5f}s vs fullTime {fullTime:.5f}')
                        break
                    if self._dynamic_heuristic_ratio < stage4Ratio and used > stage4Time:
                        logbook.info(f'flow expand swapping heur ratio to {stage4Ratio} because used {used:.5f}s vs stage4Time {stage4Time:.5f}')
                        self._dynamic_heuristic_ratio = stage4Ratio
                        self._dynamic_heuristic_falsehood_ratio = self._dynamic_heuristic_ratio - 1.0
                    elif self._dynamic_heuristic_ratio < stage3Ratio and used > stage3Time:
                        logbook.info(f'flow expand swapping heur ratio to {stage3Ratio} because used {used:.5f}s vs stage3Time {stage3Time:.5f}')
                        self._dynamic_heuristic_ratio = stage3Ratio
                        self._dynamic_heuristic_falsehood_ratio = self._dynamic_heuristic_ratio - 1.0
                    elif self._dynamic_heuristic_ratio < stage2Ratio and used > stage2Time:
                        logbook.info(f'flow expand swapping heur ratio to {stage2Ratio} because used {used:.5f}s vs stage2Time {stage2Time:.5f}')
                        self._dynamic_heuristic_ratio = stage2Ratio
                        self._dynamic_heuristic_falsehood_ratio = self._dynamic_heuristic_ratio - 1.0
                    elif self._dynamic_heuristic_ratio < stage1Ratio and used > stage1Time:
                        logbook.info(f'flow expand swapping heur ratio to {stage1Ratio} because used {used:.5f}s vs stage1Time {stage1Time:.5f}')
                        self._dynamic_heuristic_ratio = stage1Ratio
                        self._dynamic_heuristic_falsehood_ratio = self._dynamic_heuristic_ratio - 1.0

                # we re-visit the same friendly node if we were unable to use all of its army on the last target cycle.
                # if friendlyUncalculated in visited and friendlyUncalculated.:
                #     logbook.info(f'DOUBLE VISITING {friendlyUncalculated} ???')
                # continue

                # TODO orig
                if not self.log_debug:
                    visited.add(friendlyUncalculated)
                    visited.add(targetCalculated)
                else:
                    if friendlyUncalculated not in visited:
                        logbook.info(f'    visiting friendlyUncalculated {friendlyUncalculated}')
                        visited.add(friendlyUncalculated)
                    if targetCalculated not in visited:
                        logbook.info(f'    visiting targetCalculated {targetCalculated}')
                        visited.add(targetCalculated)

                # if friendlyTileLeftoverIdx < 0:
                #     # TODO this shouldn't be necessary if my code is correct
                #     if self.log_debug:
                #         logbook.info(f'    Resetting friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} frLeftoverArmy {frLeftoverArmy}')
                #     friendlyTileLeftoverIdx = friendlyUncalculated.tile_count - 1
                #     frLeftoverArmy = friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1
                #     if self.log_debug:
                #         logbook.info(f'    --Reset to friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} frLeftoverArmy {frLeftoverArmy}')

                # TODO remove the turnsLeft > 1, this shouldn't be necessary, something is doing a final increment after running out of moves and then letting us re-enter this loop.
                if self.use_debug_asserts:
                    self.assertEverythingSafe(
                        turns,
                        negVt,
                        turnsUsed,
                        turnsLeft,
                        uncappedTargetIslandArmy,
                        randomTieBreak,
                        targetTiles,
                        econValue,
                        gathSum,
                        frLeftoverArmy,
                        friendlyTileLeftoverIdx,
                        targetCalculatedNode,
                        friendlyUncalculatedNode,
                        visited,
                        nextTargets,
                        nextFriendlies,
                        rootNodes,
                        pairOptions
                    )
                # logbook.info(f'Processing {targetCalculated.name} <- {friendlyUncalculated.name}')

                nextGathedSum = gathSum
                capValue = capValueByTeam[targetCalculated.team]

                # # have to leave 1's behind when leaving our own land
                # friendlyCappingArmy = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count
                # necessaryToFullyCap = uncappedTargetIslandArmy
                # # have to leave 1's behind when capping enemy land, too
                # armyLeftIfFullyCapping = friendlyCappingArmy - necessaryToFullyCap
                # turnsLeftIfFullyCapping = turnsLeft - numTilesLeftToCapFromTarget - friendlyUncalculated.tile_count
                # canFullyCap = turnsLeftIfFullyCapping >= 0 and armyLeftIfFullyCapping >= 0
                #
                # canFullyCap = False
                # validOpt = True
                # # TODO turn short circuit back on? Probably no because then we can't do the partial captures...?
                # if False and canFullyCap:
                #     # then we can actually dump all in and shortcut the more expensive logic
                #     turnsLeft = turnsLeftIfFullyCapping
                #     uncappedTargetIslandArmy = 0 - armyLeftIfFullyCapping
                #     econValue += numTilesLeftToCapFromTarget * capValue
                #     nextGathedSum += friendlyCappingArmy
                #     numTilesLeftToCapFromTarget = 0
                #
                #     turnsUsed = turns - turnsLeft
                #     existingBestTuple = pairOptions.get(turnsUsed, None)
                #
                #     if validOpt and (existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed):
                #         # turnsUsed == 13 and ArmyFlowExpander.is_any_tile_in_flow(rootNodes, [self.map.GetTile(14, 1), self.map.GetTile(13, 0)])
                #         pairOptions[turnsUsed] = (
                #             rootNodes,
                #             econValue,
                #             turnsUsed,
                #             0 - uncappedTargetIslandArmy,
                #             None,  # TODO this may be an incomplete capture... right...?
                #             None,
                #             None,
                #             nextGathedSum
                #         )
                # else:
                if True:
                    # then we can't dump it all in, have to do iterative check.

                    (
                        uncappedTargetIslandArmy,
                        dumpIterCount,
                        econValue,
                        frLeftoverArmy,
                        friendlyTileLeftoverIdx,
                        remainingFrIslandArmy,
                        nextGathedSum,
                        tileIterCount,
                        turnsLeft
                    ) = self._execute_island_tile_gather_capture_loop_and_record_options(
                        uncappedTargetIslandArmy,
                        capValue,
                        dumpIterCount,
                        econValue,
                        frLeftoverArmy,
                        friendlyTileLeftoverIdx,
                        friendlyUncalculated,
                        nextGathedSum,
                        pairOptions,
                        rootNodes,
                        targetCalculated,
                        targetTiles,
                        tileIterCount,
                        turns,
                        turnsLeft,
                        # remainingIslandArmy: int | None = None
                    )

                    if self.use_debug_asserts and remainingFrIslandArmy != 0 and targetCalculated.team != self.team:
                        if uncappedTargetIslandArmy != 0 and uncappedTargetIslandArmy <= remainingFrIslandArmy and friendlyTileLeftoverIdx >= 0:
                            raise Exception(
                                f'Expected uncappedTargetIslandArmy {uncappedTargetIslandArmy} to be >= remainingFrIslandArmy {remainingFrIslandArmy}, turnsLeft {turnsLeft} (fr leftover {frLeftoverArmy}, index {friendlyTileLeftoverIdx}, targetTiles {targetTiles}) to always have been reduced to 0 unless there are no target tiles left')

                    # Necessary because when we terminate the loop early above due to running out of TARGET tiles, we need to keep track of the remaining army we have to gather for the second loop below.
                    # TODO ACTUALLY THIS IS COVERED BY frLeftoverArmy NOW, NO...?
                    # uncappedTargetIslandArmy -= remainingFrIslandArmy

                if turnsLeft == 0:
                    continue

                if not targetTiles:
                    # we need to include new targets, then.
                    dumpIterCount, tieBreaker, tileIterCount = self._queue_next_targets_and_next_friendlies(
                        uncappedTargetIslandArmy,
                        capValueByTeam,
                        dumpIterCount,
                        econValue,
                        frLeftoverArmy,
                        friendlyBorderingEnemy,
                        friendlyTileLeftoverIdx,
                        friendlyUncalculated,
                        myTeam,
                        nextFriendlies,
                        nextGathedSum,
                        nextTargets,
                        pairOptions,
                        q,
                        rootNodes,
                        targetTeam,
                        tieBreaker,
                        tileIterCount,
                        targetTiles,
                        turns,
                        turnsLeft,
                        visited)
                else:
                    tieBreaker = self._queue_next_friendlies_only(
                        uncappedTargetIslandArmy,
                        capValue,
                        econValue,
                        frLeftoverArmy,
                        friendlyUncalculated,
                        myTeam,
                        nextFriendlies,
                        nextGathedSum,
                        nextTargets,
                        pairOptions,
                        q,
                        rootNodes,
                        targetCalculatedNode,
                        targetTiles,
                        tieBreaker,
                        turns,
                        turnsLeft,
                        visited)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion iteration complete in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')
        start = time.perf_counter()

        output = []
        for (targetIsland, source), planOptionsByTurns in opts.items():
            for turns, (rootNodes, econValue, otherTurns, armyRemainingInIncompleteSource, incompleteTargetIsland, incompleteSourceIsland, unusedSourceArmy, gathedArmySum) in planOptionsByTurns.items():
                if otherTurns != turns:
                    raise Exception(f'Shouldnt happen, turn mismatch {turns} vs {otherTurns}')

                # if armyRemaining < 0:
                #     # then this is a partial capture option, we already pruned out the other moves in theory, and it is already worst-case moves assuming our largest tiles are furthest and their largest tiles are in front
                #     armyRemaining = 0

                plan = self._build_flow_expansion_option(
                    islands,
                    targetIsland,
                    source,
                    rootNodes,
                    econValue,
                    armyRemainingInIncompleteSource,
                    turns,
                    targetIslands,
                    ourIslands,
                    incompleteTargetIsland,
                    incompleteSourceIsland,
                    unusedSourceArmy,
                    gathedArmySum)
                plan.gathered_army = gathedArmySum

                if plan.length == 0:
                    msg = f'plan had length 0 for {turns} - econValue: {econValue:.2f} | armyRemainingInIncompleteSource: {armyRemainingInIncompleteSource} | unusedSourceArmy: {unusedSourceArmy} | gathedArmySum: {gathedArmySum} | rootNodes: {rootNodes} | incompleteTargetIsland: {incompleteTargetIsland} | incompleteSourceIsland: {incompleteSourceIsland}'
                    logbook.info(msg)
                    if GatherDebug.USE_DEBUG_ASSERTS:
                        raise Exception(msg)
                    continue

                if plan.get_first_move() is None:
                    msg = f'plan wasnt able to produce a first move for {turns} - econValue: {econValue:.2f} | armyRemainingInIncompleteSource: {armyRemainingInIncompleteSource} | unusedSourceArmy: {unusedSourceArmy} | gathedArmySum: {gathedArmySum} | rootNodes: {rootNodes} | incompleteTargetIsland: {incompleteTargetIsland} | incompleteSourceIsland: {incompleteSourceIsland}'
                    logbook.info(msg)
                    if GatherDebug.USE_DEBUG_ASSERTS:
                        raise Exception(msg)
                    continue

                output.append(plan)

        dur = time.perf_counter() - start
        logbook.info(f'Flow expansion plan build in {dur:.5f}s, core iter {queueIterCount}, dump iter {dumpIterCount}, tile iter {tileIterCount}')

        return output

    def _execute_island_tile_gather_capture_loop_and_record_options(
            self,
            uncappedTargetIslandArmy,
            capValue,
            dumpIterCount,
            econValue,
            frLeftoverArmy,
            friendlyTileLeftoverIdx,
            friendlyUncalculated,
            nextGathedSum,
            pairOptions,
            rootNodes,
            targetCalculated,
            targetTiles,
            tileIterCount,
            turns,
            turnsLeft,
            # remainingIslandArmy: int | None = None
    ):
        # brokeOnTurns = False
        # if remainingIslandArmy is None:
        remainingFrIslandArmy = self.get_friendly_island_army_left(friendlyUncalculated, frLeftoverArmy, friendlyTileLeftoverIdx)

        # remainingFrIslandArmy = self.get_friendly_island_army_left(friendlyUncalculated, 0, friendlyTileLeftoverIdx)
        # trueArmyToDump = remainingFrIslandArmy + frLeftoverArmy
        # armyToDump = friendlyUncalculated.sum_army - friendlyUncalculated.tile_count  # We need to leave 1 army behind per tile.
        # # ############## we start at 1, because pulling the first tile doesn't count as a move (the tile we move to counts as the move, whether thats to enemy or to another friendly gather tile)
        # friendlyIdx = 1
        # frTileArmy = friendlyUncalculated.tiles_by_army[0].army
        # friendlyIdx = 0
        while (friendlyTileLeftoverIdx >= 0 or frLeftoverArmy > 0) and targetTiles and turnsLeft > 0:
            tgTileArmyToCap = targetTiles.popleft() + 1
            # if validOpt:
            dumpIterCount += 1

            # pull as many fr tiles as necessary to cap the en tile
            # while frTileArmy < tgTileArmyToCap and turnsLeft > 1 and friendlyIdx < len(friendlyUncalculated.tiles_by_army):
            # turns left > 1 because there is no point to gather one more tile if we dont have a turn left to capture another tile with that army.
            while frLeftoverArmy <= tgTileArmyToCap and turnsLeft > 0 and friendlyTileLeftoverIdx >= 0:
                frTileArmy = friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army - 1  # -1, we have to leave 1 army behind.
                nextGathedSum += frTileArmy
                frLeftoverArmy += frTileArmy
                turnsLeft -= 1
                friendlyTileLeftoverIdx -= 1
                tileIterCount += 1

            if turnsLeft <= 0:
                # we already put all the data for all valid options in the pairOptions, so we can just break here and not worry about anything else if there is nothing else to add to the queue.
                # brokeOnTurns = True
                break

            if friendlyTileLeftoverIdx >= 0:
                pass

            if frLeftoverArmy < tgTileArmyToCap:
                # then we didn't complete the capture
                # validOpt = False
                targetTiles.appendleft(tgTileArmyToCap - frLeftoverArmy - 1)  # -1 offsets the +1 we added earlier for the capture itself
                # turnsLeft += 1  # don't count this turn, we're going to gather more and then re-do this move
                uncappedTargetIslandArmy -= frLeftoverArmy
                remainingFrIslandArmy -= frLeftoverArmy
                # we dont use this after breaking
                # armyToDump = 0
                if self.log_debug:
                    logbook.info(
                        f'    broke early on standard army usage {frLeftoverArmy} < {tgTileArmyToCap} at friendlyTileLeftoverIdx {friendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[friendlyTileLeftoverIdx].army}) w/ turnsLeft {turnsLeft} and targetTiles {targetTiles}')
                frLeftoverArmy = 0
                break

            # cap the en tile
            econValue += capValue
            uncappedTargetIslandArmy -= tgTileArmyToCap
            remainingFrIslandArmy -= tgTileArmyToCap
            frLeftoverArmy -= tgTileArmyToCap
            turnsLeft -= 1
            turnsUsed = turns - turnsLeft
            existingBestTuple = pairOptions.get(turnsUsed, None)

            if tgTileArmyToCap > 0 and (existingBestTuple is None or existingBestTuple[1] / existingBestTuple[2] < econValue / turnsUsed and econValue > 0.0):
                # turnsUsed == 13 and ArmyFlowExpander.is_any_tile_in_flow(rootNodes.values(), [self.map.GetTile(14, 1), self.map.GetTile(13, 0)])
                pairOptions[turnsUsed] = (
                    rootNodes,
                    econValue,
                    turnsUsed,
                    remainingFrIslandArmy,
                    targetCalculated if targetTiles else None,
                    friendlyUncalculated if friendlyTileLeftoverIdx >= 0 else None,
                    remainingFrIslandArmy if friendlyTileLeftoverIdx >= 0 else None,
                    nextGathedSum,
                )

        if uncappedTargetIslandArmy < 0:
            # add the negative of the uncapped target army to our frLeftoverArmy, then set uncapped target to zero.
            frLeftoverArmy -= uncappedTargetIslandArmy
            uncappedTargetIslandArmy = 0
        elif frLeftoverArmy < 0:
            uncappedTargetIslandArmy -= frLeftoverArmy

        return uncappedTargetIslandArmy, dumpIterCount, econValue, frLeftoverArmy, friendlyTileLeftoverIdx, remainingFrIslandArmy, nextGathedSum, tileIterCount, turnsLeft

    def _queue_next_targets_and_next_friendlies(
            self,
            uncappedTargetIslandArmy,
            capValueByTeam,
            dumpIterCount,
            econValue,
            frLeftoverArmy,
            friendlyBorderingEnemy,
            friendlyTileLeftoverIdx,
            friendlyUncalculated,
            myTeam,
            nextFriendlies,
            nextGathedSum,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            tileIterCount,
            tilesToCap,
            turns,
            turnsLeft,
            visited
    ):
        for (nextTargetIsland, nextTargetFromNode) in nextTargets.items():
            if nextTargetIsland in visited:
                if self.log_debug:
                    logbook.info(f'skipped targ {nextTargetIsland} from {nextTargetFromNode}')
                continue

            capValue = capValueByTeam[nextTargetIsland.team]

            # capture as much of the new target as we can
            newEconValue = econValue
            newUncappedTargetIslandArmy = uncappedTargetIslandArmy
            if nextTargetIsland.team == self.team:
                newTargetTiles = deque(-t.army for t in nextTargetIsland.tiles_by_army)
                newUncappedTargetIslandArmy += nextTargetIsland.tile_count - nextTargetIsland.sum_army
            else:
                newTargetTiles = deque(t.army for t in nextTargetIsland.tiles_by_army)
                newUncappedTargetIslandArmy += nextTargetIsland.sum_army + nextTargetIsland.tile_count
            newTurnsLeft = turnsLeft
            # add
            newFriendlyTileLeftoverIdx = friendlyTileLeftoverIdx
            newFrLeftoverArmy = frLeftoverArmy

            # proves only these 3 value variables are being modified (of value variables)
            dumpIterCount, tieBreaker, tileIterCount = self._calculate_next_target_and_queue_next_friendlies(
                capValue,
                dumpIterCount,
                friendlyBorderingEnemy,
                friendlyUncalculated,
                myTeam,
                newUncappedTargetIslandArmy,
                newEconValue,
                newFrLeftoverArmy,
                newFriendlyTileLeftoverIdx,
                newTargetTiles,
                newTurnsLeft,
                nextFriendlies,
                nextGathedSum,
                nextTargetFromNode,
                nextTargetIsland,
                nextTargets,
                pairOptions,
                q,
                rootNodes,
                targetTeam,
                tieBreaker,
                tileIterCount,
                turns,
                visited)

        return dumpIterCount, tieBreaker, tileIterCount

    def _calculate_next_target_and_queue_next_friendlies(
            self,
            capValue,
            dumpIterCount,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextGathedSum,
            nextTargetFromNode,
            nextTargetIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            tileIterCount,
            turns,
            visited
    ):
        # dumpIterCount, newUncappedTargetIslandArmy, newEconValue, newTurnsLeft, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, tileIterCount = self._calculate_next_target_values(
        #     capValue,
        #     dumpIterCount,
        #     friendlyUncalculated,
        #     newUncappedTargetIslandArmy,
        #     newEconValue,
        #     newFrLeftoverArmy,
        #     newFriendlyTileLeftoverIdx,
        #     newTargetTiles,
        #     newTurnsLeft,
        #     nextGathedSum,
        #     nextTargetIsland,
        #     pairOptions,
        #     rootNodes,
        #     tileIterCount,
        #     turns)
        newTurnsUsed = turns - newTurnsLeft

        # stillUnusedExistingFriendlyArmy = newFriendlyTileLeftoverIdx >= 0 or (newFrLeftoverArmy > 1 and len(newTargetTiles) == 0)
        # if stillUnusedExistingFriendlyArmy:
        tieBreaker = self._queue_current_friendlies_from_next_target_values(
            capValue,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextGathedSum,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            nextTargetFromNode,
            nextTargetIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            newTurnsUsed,
            visited)

        # else:
        #     for (nextFriendlyUncalculated, nextFriendlyFromNode) in nextFriendlies.items():
        #         if nextFriendlyUncalculated in visited:
        #             if self.log_debug:
        #                 logbook.info(f'skipped src  {nextFriendlyUncalculated} from {nextFriendlyFromNode}')
        #             continue
        #
        #         # TODO check if would orphan gatherable islands in the middle of 1s? Actually, we keep having the option to pull orphans in, so really we should value the plan by the amount of orphaned stuff, not the search through the plan.
        #
        #         tieBreaker = self._queue_next_friendlies_from_next_target_values(
        #             capValue,
        #             friendlyBorderingEnemy,
        #             friendlyUncalculated,
        #             myTeam,
        #             newUncappedTargetIslandArmy,
        #             newEconValue,
        #             newTargetTiles,
        #             newTurnsLeft,
        #             nextFriendlies,
        #             nextFriendlyFromNode,
        #             nextFriendlyUncalculated,
        #             nextGathedSum,
        #             newFrLeftoverArmy,
        #             nextTargetFromNode,
        #             nextTargetIsland,
        #             nextTargets,
        #             pairOptions,
        #             q,
        #             rootNodes,
        #             targetTeam,
        #             tieBreaker,
        #             newTurnsUsed,
        #             visited)

        return dumpIterCount, tieBreaker, tileIterCount

    def _queue_next_friendlies_from_next_target_values(
            self,
            capValue,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextFriendlyFromNode,
            nextFriendlyUncalculated,
            nextGathedSum,
            newFrLeftoverArmy,
            nextTargetFromNode,
            nextTargetIsland: TileIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            newTurnsUsed,
            visited
    ):
        if self.log_debug:
            logbook.info(f'tg {nextTargetIsland}, newTurnsUsed {newTurnsUsed} newTurnsLeft {newTurnsLeft}, fr {nextFriendlyUncalculated}')

        lookup = {}

        newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}

        copyTargetFromNode = lookup[nextTargetFromNode.island.unique_id]
        nextTargetCalculatedNode = IslandFlowNode(nextTargetIsland, nextTargetIsland.sum_army + nextTargetIsland.tile_count)

        if self.use_debug_asserts and copyTargetFromNode.island not in nextTargetCalculatedNode.island.border_islands:
            # TODO remove once algo reliable
            raise Exception(f'Tried to add illegal edge from {copyTargetFromNode} TO {nextTargetCalculatedNode}')
        if self.log_debug:
            logbook.info(f'    adding target (friendly) edge from {copyTargetFromNode.island.unique_id} TO {nextTargetCalculatedNode.island.unique_id}')
        copyTargetFromNode.set_flow_to(nextTargetCalculatedNode, 0)

        # TODO remove try catches
        try:
            copyFriendlyFromNode = lookup[nextFriendlyFromNode.island.unique_id]
        except:
            logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
            raise
        newRootNodes.pop(copyFriendlyFromNode.island.unique_id, None)
        nextFriendlyUncalculatedNode = IslandFlowNode(nextFriendlyUncalculated, 0 - nextFriendlyUncalculated.sum_army + nextFriendlyUncalculated.tile_count)
        if self.use_debug_asserts and nextFriendlyUncalculatedNode.island not in copyFriendlyFromNode.island.border_islands:
            # TODO remove once algo reliable
            raise Exception(f'Tried to add illegal edge from {nextFriendlyUncalculatedNode} TO {copyFriendlyFromNode}')
        if self.log_debug:
            logbook.info(f'    adding friendly (target) edge from {nextFriendlyUncalculatedNode.island.unique_id} TO {copyFriendlyFromNode.island.unique_id}')

        nextFriendlyUncalculatedNode.set_flow_to(copyFriendlyFromNode, 0)
        # if copyFriendlyFromNode.island.team == self.team:
        newRootNodes[nextFriendlyUncalculated.unique_id] = nextFriendlyUncalculatedNode
        newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}
        del newNextFriendlies[nextFriendlyUncalculated]

        # this lets us visit in arbitrary orders (ew)
        newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}
        del newNextTargets[nextTargetIsland]

        self._try_include_nexts_by_flow(
            myTeam,
            nextFriendlyUncalculated.border_islands,
            newNextFriendlies,
            newNextTargets,
            newFrLeftoverArmy,
            nextFriendlyUncalculated,
            nextFriendlyUncalculatedNode,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy)

        self._try_queue_next_capture(
            myTeam,
            nextTargetIsland.border_islands,
            newNextFriendlies,
            newNextTargets,
            newFrLeftoverArmy,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            newRootNodes,
            friendlyBorderingEnemy)

        tieBreaker += 1
        nextFrTileIdx = nextFriendlyUncalculated.tile_count - 1

        self.enqueue(
            q,
            self._get_a_star_priority_val(capValue, newEconValue, newTurnsUsed, newFrLeftoverArmy, nextFrTileIdx, nextFriendlyUncalculated, nextTargetCalculatedNode.island, searchTurns=newTurnsUsed + newTurnsLeft, tgTiles=newTargetTiles),
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            newFrLeftoverArmy,
            nextFrTileIdx,
            nextTargetCalculatedNode,
            nextFriendlyUncalculatedNode,
            visited,
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        )
        return tieBreaker

    def enqueue(
            self,
            q,
            prioVal,
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            newFrLeftoverArmy,
            nextFrTileIdx,
            nextTargetCalculatedNode: IslandFlowNode,
            nextFriendlyUncalculatedNode: IslandFlowNode,
            visited,
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions):

        if self.log_debug:
            logbook.info(
                f'\r\n      enqueueing {nextFriendlyUncalculatedNode.island} -...-> {nextTargetCalculatedNode.island}'
                f'\r\n            negVt: {prioVal}'
                f'\r\n            rootNodes: {" | ".join(str(n.island.shortIdent()) for n in newRootNodes.values())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_children(newRootNodes.values()))}'
                f'\r\n            nextFriendlies {" | ".join(str(n.shortIdent()) for n in newNextFriendlies.keys())}  ->  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(newNextFriendlies.values()))}'
                f'\r\n            nextTargets {" | ".join(str(n.shortIdent()) for n in newNextTargets.keys())}  <-  {" | ".join(str(n.island.shortIdent()) for n in ArmyFlowExpander.iterate_flow_nodes(newNextTargets.values()))}'
                f'\r\n            turnsUsed: {newTurnsUsed}, turnsLeft: {newTurnsLeft}'
                f'\r\n            uncappedTargetIslandArmy: {newUncappedTargetIslandArmy}, targetTiles: {repr(newTargetTiles)}'
                f'\r\n            econValue: {newEconValue:.3f}, gathSum: {nextGathedSum}'
                f'\r\n            frLeftoverArmy: {newFrLeftoverArmy}, friendlyTileLeftoverIdx: {nextFrTileIdx}'
                f'\r\n            visited: {({t.shortIdent() for t in visited})}'
            )
        q.put((
            prioVal,
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            newFrLeftoverArmy,
            nextFrTileIdx,
            nextTargetCalculatedNode,
            nextFriendlyUncalculatedNode,
            visited,
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        ))

    def _try_include_nexts_by_flow(
            self,
            myTeam,
            borderIslands,
            newNextFriendlies,
            newNextTargets,
            nextFrLeftoverArmy,
            nextFriendlyUncalculated,
            nextFriendlyUncalculatedNode,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            friendlyBorderingEnemy=None,
    ):
        for adj in borderIslands:
            if adj.team == myTeam:
                if adj in visited or adj in newNextFriendlies:
                    continue
                # TODO need to allow gathering through neutral land
                if not self._is_flow_allowed(adj, nextFriendlyUncalculated, armyAmount=nextGathedSum, isSubsequentFriendly=True, friendlyBorderingEnemy=friendlyBorderingEnemy):
                    continue
                newNextFriendlies[adj] = nextFriendlyUncalculatedNode
            else:
                # A gather arm feeds army INTO the main stream and cannot simultaneously
                # attack its own enemy neighbors — those would be an independent stream.
                pass

    def _try_queue_next_capture(
            self,
            myTeam,
            borderIslands,
            newNextFriendlies,
            newNextTargets,
            nextFrLeftoverArmy,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            rootNodes: typing.Dict[int, IslandFlowNode] | None = None,
            friendlyBorderingEnemy=None,
    ):
        for adj in borderIslands:
            if adj.team == myTeam:
                if adj in visited or adj in newNextFriendlies or adj in newNextTargets:
                    continue
                # TODO need to allow gathering through neutral land
                eitherAllowed = self._is_flow_allowed(nextTargetIsland, adj, armyAmount=nextGathedSum, isSubsequentFriendly=True, friendlyBorderingEnemy=friendlyBorderingEnemy) or self._is_flow_allowed(adj, nextTargetIsland, armyAmount=nextGathedSum, isSubsequentFriendly=True, friendlyBorderingEnemy=friendlyBorderingEnemy)
                if not eitherAllowed:
                    continue
                newNextTargets[adj] = nextTargetCalculatedNode
            else:
                if adj in visited or not self._is_flow_allowed(fromIsland=nextTargetIsland, toIsland=adj, armyAmount=nextFrLeftoverArmy, isSubsequentTarget=True):
                    continue
                # Skip enemy/neutral targets that border a friendly island NOT in the current flow.
                # Those targets already have their own seeded (target, friendly) pair and belong
                # to an independent stream. Only skip if rootNodes is known.
                if rootNodes is not None:
                    seededFriendlies = self._seeded_pairs.get(adj.unique_id)
                    if seededFriendlies and not seededFriendlies.issubset(rootNodes):
                        continue
                newNextTargets[adj] = nextTargetCalculatedNode

    def _queue_current_friendlies_from_next_target_values(
            self,
            capValue,
            friendlyBorderingEnemy,
            friendlyUncalculated,
            myTeam,
            newUncappedTargetIslandArmy,
            newEconValue,
            newTargetTiles,
            newTurnsLeft,
            nextFriendlies,
            nextGathedSum,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            nextTargetFromNode,
            nextTargetIsland,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetTeam,
            tieBreaker,
            newTurnsUsed,
            visited
    ):
        if self.log_debug:
            logbook.info(f'tg {nextTargetIsland}, newTurnsUsed {newTurnsUsed} newTurnsLeft {newTurnsLeft}, EXIST fr {friendlyUncalculated} (newFriendlyTileLeftoverIdx {newFriendlyTileLeftoverIdx})')

        lookup = {}

        newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}

        copyTargetFromNode = lookup[nextTargetFromNode.island.unique_id]
        nextTargetCalculatedNode = IslandFlowNode(nextTargetIsland, nextTargetIsland.sum_army + nextTargetIsland.tile_count)

        if copyTargetFromNode.island not in nextTargetCalculatedNode.island.border_islands:
            # TODO remove once algo reliable
            raise Exception(f'Tried to add illegal edge from {copyTargetFromNode} TO {nextTargetCalculatedNode}')
        if self.log_debug:
            logbook.info(f'    adding target (solo) edge from {copyTargetFromNode.island.unique_id} TO {nextTargetCalculatedNode.island.unique_id}')

        copyTargetFromNode.set_flow_to(nextTargetCalculatedNode, 0)
        try:
            copyFriendlyFromNode = lookup[friendlyUncalculated.unique_id]
        except:
            logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
            raise

        newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}

        # this lets us visit in arbitrary orders (ew)
        newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}
        del newNextTargets[nextTargetIsland]

        self._try_queue_next_capture(
            myTeam,
            nextTargetIsland.border_islands,
            newNextFriendlies,
            newNextTargets,
            newFrLeftoverArmy,
            nextGathedSum,
            nextTargetCalculatedNode,
            nextTargetIsland,
            visited,
            newRootNodes,
            friendlyBorderingEnemy)

        tieBreaker += 1

        self.enqueue(
            q,
            self._get_a_star_priority_val(capValue, newEconValue, newTurnsUsed, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, friendlyUncalculated, nextTargetIsland, searchTurns=newTurnsUsed + newTurnsLeft, tgTiles=newTargetTiles),
            newTurnsUsed,
            newTurnsLeft,
            newUncappedTargetIslandArmy,
            tieBreaker,
            newTargetTiles,
            newEconValue,
            nextGathedSum,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            nextTargetCalculatedNode,
            copyFriendlyFromNode,
            # visited.copy(),
            visited,  # note we are not cloning visited, so this isn't full TSP
            newNextTargets,
            newNextFriendlies,
            newRootNodes,
            pairOptions
        )
        return tieBreaker

    def _calculate_next_target_values(
            self,
            capValue,
            dumpIterCount,
            friendlyUncalculated,
            newUncappedTargetIslandArmy,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            newTargetTiles,
            newTurnsLeft,
            nextGathedSum,
            nextTargetIsland,
            pairOptions,
            rootNodes,
            tileIterCount,
            turns):
        if self.log_debug:
            logbook.info(
                f'\r\n  beginning next target {nextTargetIsland} with newUncappedTargetIslandArmy {newUncappedTargetIslandArmy} and newTargetTiles {newTargetTiles}: \r\n    newFrLeftoverArmy {newFrLeftoverArmy} with newFriendlyTileLeftoverIdx {newFriendlyTileLeftoverIdx} ({friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx].army}) \r\n    w/ starting newTurnsLeft {newTurnsLeft}')

        (
            newUncappedTargetIslandArmy,
            dumpIterCount,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            remainingFrIslandArmy,
            nextGathedSum,
            tileIterCount,
            newTurnsLeft
        ) = self._execute_island_tile_gather_capture_loop_and_record_options(
            newUncappedTargetIslandArmy,
            capValue,
            dumpIterCount,
            newEconValue,
            newFrLeftoverArmy,
            newFriendlyTileLeftoverIdx,
            friendlyUncalculated,
            nextGathedSum,
            pairOptions,
            rootNodes,
            nextTargetIsland,
            newTargetTiles,
            tileIterCount,
            turns,
            newTurnsLeft)
        return dumpIterCount, newUncappedTargetIslandArmy, newEconValue, newTurnsLeft, newFrLeftoverArmy, newFriendlyTileLeftoverIdx, tileIterCount

    def _queue_next_friendlies_only(
            self,
            armyToCap,
            capValue,
            econValue,
            frLeftoverArmy,
            friendlyUncalculated,
            myTeam,
            nextFriendlies,
            nextGathedSum,
            nextTargets,
            pairOptions,
            q,
            rootNodes,
            targetCalculatedNode,
            targetTiles,
            tieBreaker,
            turns,
            turnsLeft,
            visited
    ):
        turnsUsed = turns - turnsLeft
        for (nextFriendlyUncalculated, nextFriendlyFromNode) in nextFriendlies.items():
            if nextFriendlyUncalculated in visited:
                # logbook.info(f'skipped src  {newFriendlyUncalculated.name} from {friendlyUncalculated.name}')
                continue

            lookup = {}

            newRootNodes = {n.island.unique_id: n for n in _deep_copy_flow_nodes(rootNodes.values(), lookup)}

            copyTargetCalculatedNode = lookup[targetCalculatedNode.island.unique_id]

            newRootNodes.pop(nextFriendlyFromNode.island.unique_id, None)
            try:
                copyFriendlyFromNode = lookup[nextFriendlyFromNode.island.unique_id]
            except:
                logbook.info(' | '.join(str(n.island.unique_id) for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())))
                raise

            nextFriendlyUncalculatedNode = IslandFlowNode(nextFriendlyUncalculated, 0 - nextFriendlyUncalculated.sum_army + nextFriendlyUncalculated.tile_count)
            if self.use_debug_asserts and nextFriendlyUncalculatedNode.island not in copyFriendlyFromNode.island.border_islands:
                # TODO remove once algo reliable
                raise Exception(f'Tried to add illegal edge from {nextFriendlyUncalculatedNode} TO {copyFriendlyFromNode}')

            if self.log_debug:
                logbook.info(f'    adding friendly edge from {nextFriendlyUncalculatedNode.island.unique_id} TO {copyFriendlyFromNode.island.unique_id}')
            nextFriendlyUncalculatedNode.set_flow_to(copyFriendlyFromNode, 0)
            # if copyFriendlyFromNode.island.team == self.team:
            newRootNodes[nextFriendlyUncalculated.unique_id] = nextFriendlyUncalculatedNode

            newNextFriendlies = {island: _deep_copy_flow_node(n, lookup) for island, n in nextFriendlies.items()}
            del newNextFriendlies[nextFriendlyUncalculated]
            newNextTargets = {island: _deep_copy_flow_node(n, lookup) for island, n in nextTargets.items()}

            self._try_include_nexts_by_flow(
                myTeam,
                nextFriendlyUncalculated.border_islands,
                newNextFriendlies,
                newNextTargets,
                frLeftoverArmy,
                nextFriendlyUncalculated,
                nextFriendlyUncalculatedNode,
                nextGathedSum,
                copyTargetCalculatedNode,
                targetCalculatedNode.island,
                visited,
                friendlyBorderingEnemy=None)  # TODO

            tieBreaker += 1
            frTileIdx = nextFriendlyUncalculated.tile_count - 1

            self.enqueue(
                q,
                self._get_a_star_priority_val(capValue, econValue, turnsUsed, frLeftoverArmy, frTileIdx, nextFriendlyUncalculated, targetCalculatedNode.island, searchTurns=turnsUsed + turnsLeft, tgTiles=targetTiles),
                turnsUsed,
                turnsLeft,
                armyToCap,
                tieBreaker,
                targetTiles.copy(),
                econValue,
                nextGathedSum,
                frLeftoverArmy,
                frTileIdx,
                copyTargetCalculatedNode,
                nextFriendlyUncalculatedNode,
                # visited.copy(),
                visited,  # note we are not cloning visited, so this isn't full TSP
                newNextTargets,
                newNextFriendlies,
                newRootNodes,
                pairOptions
            )
        return tieBreaker

    def _build_flow_expansion_option(
            self,
            islandBuilder: TileIslandBuilder,
            target: TileIsland,
            source: TileIsland,
            sourceNodes: typing.Dict[int, IslandFlowNode],
            econValue: float,
            armyRemainingInIncompleteSource: int,
            turns,
            targetIslands: typing.List[TileIsland],
            ourIslands: typing.List[TileIsland],
            incompleteTarget: TileIsland | None,
            incompleteSource: TileIsland | None,
            unusedSourceArmy: int | None,
            gathedArmySum: int,
            negativeTiles: TileSet | None = None,
            useTrueValueGathered: bool = True,
    ) -> FlowExpansionPlanOption:
        if self.log_debug:
            logbook.info(f'building plan for {source.name}->{target.name} (econ {econValue:.2f} turns {turns} armyRemainingInIncompleteSource {armyRemainingInIncompleteSource})')

        # TODO we want to keep our moves as wide across any borders as possible, if we combine everything into one big tile then we have the potential to waste moves.
        # need to build our initial lines outwards from the border as straight as possible, then combine as needed as captures fail.
        # fromMatrix: MapMatrixInterface[Tile] = MapMatrix(self.map)
        # fromArmy: MapMatrixInterface[int] = MapMatrix(self.map)

        # border = set(itertools.chain.from_iterable(t.movable for t in target.tile_set if t in source.tile_set))
        capping = set()
        gathing = set()
        team = self.team

        curArmy: int
        curIdk: int
        curNode: IslandFlowNode
        fromNode: IslandFlowNode | None

        incompleteSourceNode: IslandFlowNode | None = None
        incompleteTargetNode: IslandFlowNode | None = None
        incompleteTargetFrom: typing.Dict[int, IslandFlowNode] = {}
        allBorderTiles = set()

        # TODO this can be completely redone much more efficient by using the raw queue loop below to build the gather / capture plan itself instead of using it for tile lists and then building a whole addl tree.

        rebuiltGathedSum = unusedSourceArmy
        rebuiltCumulativeSum = unusedSourceArmy
        if rebuiltGathedSum is None:
            rebuiltGathedSum = 0
            rebuiltCumulativeSum = 0
        rebuiltCumulativeTurns = -1
        lookup = {}
        q: typing.List[typing.Tuple[int, int, IslandFlowNode, IslandFlowNode | None]] = [(0, 0, n, None) for n in sourceNodes.values()]
        while q:
            curArmy, curIdk, curNode, fromNode = q.pop()
            # TODO not sure why the below would be needed instead of the hardcoded source/target. Revert if necessary...?
            # if fromNode is not None and fromNode.island == source and curNode.island == target:
            if fromNode is not None and fromNode.island.team == team and curNode.island.team != team:
                # borderTiles = islandBuilder.get_inner_border_tiles(fromNode.island, curNode.island)
                borderTiles = islandBuilder.get_inner_border_tiles(curNode.island, fromNode.island)
                allBorderTiles.update(borderTiles)

            lookup[curNode.island.unique_id] = curNode
            if curNode.island == incompleteTarget:
                incompleteTargetNode = curNode
                if fromNode:
                    incompleteTargetFrom[fromNode.island.unique_id] = fromNode
            elif curNode.island == incompleteSource:
                incompleteSourceNode = curNode
                gathed = curNode.island.sum_army - curNode.island.tile_count - unusedSourceArmy
                curArmy += gathed
                rebuiltGathedSum += gathed
                rebuiltCumulativeSum += gathed
            else:
                rebuiltCumulativeTurns += curNode.island.tile_count
                if curNode.island.team == team:
                    gathing.update(curNode.island.tile_set)
                    gathed = curNode.island.sum_army - curNode.island.tile_count
                    curArmy += gathed
                    rebuiltGathedSum += gathed
                    rebuiltCumulativeSum += gathed
                else:
                    capping.update(curNode.island.tile_set)
                    gathed = curNode.island.sum_army + curNode.island.tile_count
                    curArmy -= gathed
                    # rebuiltGathedSum -= gathed
                    rebuiltCumulativeSum -= gathed

            for edge in curNode.flow_to:
                # right now can only flow to one,
                # TODO must figure out how to split in future when can target multiple....
                edge.edge_army = curArmy
                q.append((curArmy, curIdk, edge.target_flow_node, curNode))

        if incompleteSourceNode:
            tiles = self._find_island_consumed_tiles_from_borders(islandBuilder, incompleteSourceNode, gathing, capping, unusedSourceArmy, incompleteSourceNode.flow_to, negativeTiles)
            if GatherDebug.USE_DEBUG_ASSERTS and (capping or gathing):
                anyConnected = False
                for t in tiles:
                    for mv in t.movableNoObstacles:
                        if mv in capping or mv in gathing:
                            anyConnected = True
                            break
                    if anyConnected:
                        break
                if not anyConnected:
                    msg = (f'_find_island_consumed_tiles_from_borders did not produce connected tiles for '
                           f'\r\n  incompleteSourceNode {incompleteSourceNode} w/ tiles {incompleteSourceNode.island.tile_set}... '
                           f'\r\n  incompleteSourceNode.flow_to {incompleteSourceNode.flow_to}... '
                           f'\r\n  tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(tiles)])}'
                           f'\r\n  gathing {" | ".join([f"{t.x},{t.y}" for t in sorted(gathing)])}'
                           f'\r\n  capping {" | ".join([f"{t.x},{t.y}" for t in sorted(capping)])}')
                    self.live_render_capture_stuff(
                        islandBuilder,
                        capping=capping,
                        gathing=gathing,
                        incompleteSource=incompleteSource,
                        incompleteTarget=incompleteTarget,
                        incompleteSourceNode=incompleteSourceNode,
                        incompleteTargetNode=incompleteTargetNode,
                        sourceUnused=unusedSourceArmy,
                        plan=None,
                        extraInfo=msg)
                    raise Exception(msg)
            gathing.update(tiles)
            rebuiltCumulativeTurns += len(tiles)
            # gathed = incompleteSourceNode.island.sum_army - incompleteSourceNode.island.tile_count
            # rebuiltGathedSum += gathed

        if incompleteTargetNode:
            # No +1: the algo counts 1 turn per tile; the MST gives the root tile for free
            # (plan.length = N-1 for N tiles), so the plan will be turns-1 long — which is
            # exactly what the VT cutoff denominator (econValue/(turns-1)) expects.
            # Adding +1 caused one extra tile to be selected beyond what the algo had army for.
            # Cap at tile_count-1: incompleteTarget is set only when the algo stopped before
            # exhausting the island, so at most tile_count-1 tiles were actually captured.
            incompleteUsedTurns = min(turns - len(gathing) - len(capping), incompleteTargetNode.island.tile_count - 1)
            if incompleteUsedTurns > 0:
                tiles = self._find_island_consumed_tiles_from_borders_by_count(islandBuilder, incompleteTargetNode, gathing, capping, incompleteUsedTurns, incompleteTargetFrom, negativeTiles)
                if GatherDebug.USE_DEBUG_ASSERTS:
                    anyConnected = False
                    for t in tiles:
                        for mv in t.movableNoObstacles:
                            if mv in capping or mv in gathing:
                                anyConnected = True
                                break
                        if anyConnected:
                            break
                    if not anyConnected:
                        msg = (f'_find_island_consumed_tiles_from_borders_by_count did not produce connected tiles for '
                               f'\r\n  incompleteTargetNode {incompleteTargetNode} w/ tiles {incompleteTargetNode.island.tile_set}... '
                               f'\r\n  incompleteTargetFrom {incompleteTargetFrom}... '
                               f'\r\n  tiles {" | ".join([f"{t.x},{t.y}" for t in sorted(tiles)])}'
                               f'\r\n  gathing {" | ".join([f"{t.x},{t.y}" for t in sorted(gathing)])}'
                               f'\r\n  capping {" | ".join([f"{t.x},{t.y}" for t in sorted(capping)])}')
                        self.live_render_capture_stuff(
                            islandBuilder,
                            capping=capping,
                            gathing=gathing,
                            incompleteSource=incompleteSource,
                            incompleteTarget=incompleteTarget,
                            incompleteSourceNode=incompleteSourceNode,
                            incompleteTargetNode=incompleteTargetNode,
                            sourceUnused=unusedSourceArmy,
                            plan=None,
                            extraInfo=msg)
                        raise Exception(msg)
                capping.update(tiles)
                rebuiltCumulativeTurns += len(tiles)
                for t in tiles:
                    rebuiltCumulativeSum -= t.army - 1

        if self.log_debug:
            logbook.info(
                f'pre-GCP {source.name}->{target.name} {econValue:.2f}v/{turns}t'
                f' | gathing=[{" ".join(f"{t.x},{t.y}" for t in sorted(gathing))}]'
                f' | capping=[{" ".join(f"{t.x},{t.y}" for t in sorted(capping))}]'
            )
        plan = Gather.convert_contiguous_capture_tiles_to_gather_capture_plan(
            self.map,
            rootTiles=allBorderTiles,
            tiles=gathing,
            negativeTiles=negativeTiles,
            searchingPlayer=self.friendlyGeneral.player,
            priorityMatrix=None,
            useTrueValueGathered=useTrueValueGathered,
            captures=capping,
        )

        # ok now we need to figure out how to route the captures...
        # self.flow_graph

        # for toIsland, fromIsland in flowGraph.items():
        #     if toIsland == incompleteTarget:
        #         pass
        #     else:
        #         if toIsland.team == team:
        #             gathing.update(toIsland.tile_set)
        #         else:
        #             capping.update(toIsland.tile_set)
        #
        #     if fromIsland == incompleteSource:
        #         pass
        #     else:
        #         if fromIsland.team == team:
        #             gathing.update(fromIsland.tile_set)
        #         else:
        #             capping.update(fromIsland.tile_set)

        if len(capping) > self.debug_render_capture_count_threshold:
            self.live_render_capture_stuff(islandBuilder, capping, gathing, incompleteSource, incompleteTarget, incompleteSourceNode, incompleteTargetNode, unusedSourceArmy)

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

        # plan = FlowExpansionPlanOption(
        #     moves,
        #     econValue,
        #     turns,  # TODO should be finalTurns once implemented
        #     captures,
        #     armyRemaining
        # )

        if self.log_debug or self.use_debug_asserts:
            planVt = plan.econValue / plan.length
            expectedVt = econValue / turns
            cutoffVt = econValue / max(1, turns - 1)
            violatesVtCutoff = planVt > cutoffVt * 1.10001
            msg = ''
            if self.log_debug or violatesVtCutoff:
                msg = (f'\r\n(expected {expectedVt:.3f} ({econValue:.2f}v/{turns}t) - built gcap plan {plan}'
                    f'\r\n   FOR algo output econValue {econValue:.2f}, turns {turns}, incompleteTarget {incompleteTarget}, incompleteSource {incompleteSource}, unusedSourceArmy {unusedSourceArmy}, gathedArmySum {gathedArmySum}, armyRemainingInIncompleteSource {armyRemainingInIncompleteSource}'
                    f'\r\n   FOR raw rebuiltCumulativeTurns {rebuiltCumulativeTurns} (vs {plan.length}), rebuiltGathedSum {rebuiltGathedSum}, rebuiltCumulativeSum {rebuiltCumulativeSum} (vs plan.gathered_army {plan.gathered_army})')
                if violatesVtCutoff:
                    msg = '\r\nVIOLATION OF VT:' + msg
                logbook.info(msg)
            if violatesVtCutoff and self.use_debug_asserts:
                anyInvalid = [n for n in plan.root_nodes if n.value < 0]
                if len(anyInvalid) > 0:
                    err = (f'Something went wrong. {expectedVt:.3f} ({econValue:.2f}v/{turns}t). The GCP is overvalued {planVt:.3f} ({plan.econValue:2f}v/{plan.length}t)'
                           f'\r\n{msg}')
                    addlColorings = [
                        (TargetStyle.GRAY, 16, 'rootTiles', allBorderTiles),
                    ]
                    if negativeTiles:
                        addlColorings.append((TargetStyle.YELLOW, 14, 'negativeTiles', negativeTiles))
                    self.live_render_capture_stuff(
                        islandBuilder,
                        capping=plan.approximate_capture_tiles,
                        gathing=plan.tileSet.difference(plan.approximate_capture_tiles),
                        incompleteSource=incompleteSource,
                        incompleteTarget=incompleteTarget,
                        incompleteSourceNode=incompleteSourceNode,
                        incompleteTargetNode=incompleteTargetNode,
                        sourceUnused=unusedSourceArmy,
                        plan=plan,
                        extraInfo=err,
                        addlTileColorings=addlColorings,
                    )
                    raise Exception(err)

        return plan

    def live_render_capture_stuff(
            self,
            islandBuilder: TileIslandBuilder,
            capping: TileSet,
            gathing: TileSet,
            incompleteSource: TileIsland | None,
            incompleteTarget: TileIsland | None,
            incompleteSourceNode: IslandFlowNode | None,
            incompleteTargetNode: IslandFlowNode | None,
            sourceUnused: int | None = None,
            extraInfo: str | None = None,
            plan: FlowExpansionPlanOption | None = None,
            addlTileColorings: typing.List[typing.Tuple[TargetStyle, int, str, typing.Iterable[Tile]]] | None = None,
    ):
        from Viewer import ViewerProcessHost
        debugViewInfo = ViewerProcessHost.get_renderable_view_info(self.map)
        inf = 'capping {len(capping)}, gathing {len(gathing)}'
        if extraInfo:
            inf = extraInfo
            debugViewInfo.add_info_multiline(inf)

        for tile in capping:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.RED)
        for tile in gathing:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.GREEN)
        debugViewInfo.add_info_line_no_log('GREEN = gathing')
        debugViewInfo.add_info_line_no_log('RED = capping')
        if incompleteTarget:
            debugViewInfo.add_info_line(f'ORANGE = incompleteTarget tileset: {incompleteTarget}')
            if len(incompleteTargetNode.flow_to) > 0:
                debugViewInfo.add_info_line(f'      to {" | ".join([str(t) for t in incompleteTargetNode.flow_to])}')
            for tile in incompleteTarget.tile_set:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.ORANGE, radiusReduction=16)
        if incompleteSource:
            debugViewInfo.add_info_line(f'BLUE = incompleteSource tileset: {incompleteSource} ({sourceUnused} unused)')
            if len(incompleteSourceNode.flow_to) > 0:
                debugViewInfo.add_info_line(f'      to {" | ".join([str(t) for t in incompleteSourceNode.flow_to])}')
            for tile in incompleteSource.tile_set:
                debugViewInfo.add_targeted_tile(tile, TargetStyle.BLUE, radiusReduction=14)

        first = set()
        dupes = set()

        for opt in optsSorted:
            for tile in opt.tiles:
                if tile in first:
                    dupes.add(tile)
                else:
                    first.add(tile)

        for tile in dupes:
            debugViewInfo.add_targeted_tile(tile, TargetStyle.GRAY, radiusReduction=-1)
        if dupes:
            debugViewInfo.add_info_line('GRAY = DUPLICATE FLOW OPTION TILES:')
            debugViewInfo.add_info_line('|'.join(f'{t.x},{t.y}' for t in dupes))

        if addlTileColorings:
            for targetStyleColor, radiusReduction, name, tileSet in addlTileColorings:
                debugViewInfo.add_info_line_no_log(f'{targetStyleColor} = {name}')
                for tile in tileSet:
                    debugViewInfo.add_targeted_tile(tile, targetStyleColor, radiusReduction=radiusReduction)

        if plan:
            move_list = plan.get_move_list()
            logbook.info(f'  Plan has {len(move_list)} moves, {len(plan.root_nodes)} root nodes')
            if len(move_list) == 0 and len(plan.root_nodes) > 0:
                logbook.info(f'  Root nodes: {[str(n) for n in plan.root_nodes]}')
            debugViewInfo.add_info_line(self.last_run.flow_stats_inc_neut.summary_line('YES neut'))
            debugViewInfo.add_info_line(self.last_run.flow_stats_no_neut.summary_line('NO neut'))
            if self.enemyGeneral is not None:
                ArmyFlowExpander.add_flow_expansion_option_to_view_info(
                    self.map,
                    plan,
                    plan.player,
                    tgPlayer=self.enemyGeneral.player,
                    viewInfo=debugViewInfo,
                    dontAddSourceTargetCircles=True
                )

        islandBuilder.add_tile_islands_to_view_info(debugViewInfo, printIslandInfoLines=True, renderIslandNames=True)
        ViewerProcessHost.render_view_info_debug(inf, inf if extraInfo is None else None, self.map, debugViewInfo)

    def live_render_invalid_flow_config(
            self,
            islandBuilder: TileIslandBuilder,
            nxGraph: nx.DiGraph,
            extraInfo: str | None = None,
    ):
        from Viewer import ViewerProcessHost
        debugViewInfo = ViewerProcessHost.get_renderable_view_info(self.map)
        inf = 'invalid flow config'
        if extraInfo:
            inf = extraInfo
            debugViewInfo.add_info_line(inf)

        ArmyFlowExpander.add_nx_flow_precursor_graph_to_view_info(nxGraph, islandBuilder, debugViewInfo)
        islandBuilder.add_tile_islands_to_view_info(debugViewInfo, printIslandInfoLines=False, renderIslandNames=True)

        ViewerProcessHost.render_view_info_debug(inf, inf, self.map, debugViewInfo)

    @staticmethod
    def add_flow_expansion_option_to_view_info(
            map: MapBase,
            bestOpt: FlowExpansionPlanOption,
            sourcePlayer: int,
            tgPlayer: int,
            viewInfo: ViewInfo,
            dontAddSourceTargetCircles: bool = False):
        tgTeam = map.team_ids_by_player_index[tgPlayer]
        sourceTeam = map.team_ids_by_player_index[sourcePlayer]

        i = 0
        for move in bestOpt.get_move_list():
            path = Path.from_move(move)
            viewInfo.color_path(PathColorer(
                path,
                min(255, 100 + 10 * i), max(0, 200 - 10 * i), 100,
                255,
                0, 0
            ))
            i += 1

        if not dontAddSourceTargetCircles:
            for tile in bestOpt.tileSet:
                ts = TargetStyle.YELLOW
                if map.is_tile_on_team(tile, tgTeam):
                    ts = TargetStyle.RED
                elif map.is_tile_on_team(tile, sourceTeam):
                    ts = TargetStyle.GREEN

                viewInfo.add_targeted_tile(tile, ts, radiusReduction=10)

    @staticmethod
    def add_flow_graph_to_view_info(
            flowGraph: IslandMaxFlowGraph,
            viewInfo: ViewInfo,
            noNeut: bool = True,
            withNeut: bool = True,
            showBackfillNeut: bool = False,
            lastRun: ArmyFlowExpanderLastRun | None = None,
            noLog: bool = False):
        # things drawn last win
        if withNeut:
            viewInfo.add_info_line_opt_log(f'PURPLE/BLUE = YES neutral max flows', noLog=noLog)
            if lastRun is not None:
                viewInfo.add_info_line_opt_log(lastRun.flow_stats_inc_neut.summary_line('YES neut'), noLog=noLog)
            else:
                viewInfo.add_info_line_opt_log(ArmyFlowExpander._get_flow_graph_summary_line(flowGraph.root_flow_nodes_inc_neut, flowGraph.enemy_backfill_nodes_inc_neut, flowGraph.flow_node_lookup_by_island_inc_neut, 'YES neut'), noLog=noLog)
            # Need to draw the blue last since it will be covered by the gray if drawn earlier.
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.enemy_backfill_nodes_inc_neut, Colors.LIGHT_BLUE)

        if noNeut:
            viewInfo.add_info_line_opt_log(f'BLACK/PINK = NO neutral max flows', noLog=noLog)
            if lastRun is not None:
                viewInfo.add_info_line_opt_log(lastRun.flow_stats_no_neut.summary_line('NO neut'), noLog=noLog)
            else:
                viewInfo.add_info_line_opt_log(ArmyFlowExpander._get_flow_graph_summary_line(flowGraph.root_flow_nodes_no_neut, flowGraph.enemy_backfill_nodes_no_neut, flowGraph.flow_node_lookup_by_island_no_neut, 'NO neut'), noLog=noLog)
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.enemy_backfill_nodes_no_neut, Colors.WHITE_PURPLE)
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.root_flow_nodes_no_neut, Colors.BLACK)

        if withNeut:
            ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.root_flow_nodes_inc_neut, Colors.DARK_PURPLE)
            # if showBackfillNeut:
            #     ArmyFlowExpander._include_flow_with_colors(viewInfo, flowGraph.enemy_backfill_neut_dump_edges, Colors.DARK_PURPLE)

    def _capture_last_run_flow_stats(self):
        self.last_run = ArmyFlowExpanderLastRun()
        finder = self._get_networkx_flow_direction_finder()

        if finder.graph_data_no_neut is not None:
            nx_no = finder.graph_data_no_neut
            bal = nx_no.friendly_army_supply - nx_no.enemy_army_demand
            self.last_run.flow_stats_no_neut = FlowGraphDebugStats(
                nx_no.friendly_army_supply,
                nx_no.enemy_army_demand,
                bal
            )

        if finder.graph_data is not None:
            nx_inc = finder.graph_data
            bal = nx_inc.friendly_army_supply - nx_inc.enemy_army_demand
            self.last_run.flow_stats_inc_neut = FlowGraphDebugStats(
                nx_inc.friendly_army_supply,
                nx_inc.enemy_army_demand,
                bal
            )

        no_neut_stats = self.last_run.flow_stats_no_neut
        inc_neut_stats = self.last_run.flow_stats_inc_neut
        logbook.info(inc_neut_stats.summary_line('YES neut'))
        logbook.info(no_neut_stats.summary_line('NO neut'))

    @staticmethod
    def _get_flow_graph_summary_line(
            root_nodes: typing.List[IslandFlowNode],
            enemy_backfill_nodes: typing.List[IslandFlowNode],
            flow_node_lookup: typing.Dict[int, IslandFlowNode],
            label: str,
    ) -> str:
        red_total = sum(node.island.sum_army for node in root_nodes)
        blue_total = sum(node.island.sum_army for node in enemy_backfill_nodes)

        enemy_general_node = None
        for flow_node in flow_node_lookup.values():
            if any(tile.isGeneral for tile in flow_node.island.tile_set):
                enemy_general_node = flow_node
                break

        enemy_general_flow = 0
        enemy_general_mode = 'backpressure'
        if enemy_general_node is not None:
            enemy_general_flow = enemy_general_node.army_flow_received
            if enemy_general_flow > 0:
                enemy_general_mode = 'sink'

        return f'{label}: redArmy={red_total}, blueArmy={blue_total}, enGen{enemy_general_mode}={enemy_general_flow}'

    @staticmethod
    def _include_flow_with_colors(viewInfo, sources, sourceColor):
        q: typing.Deque[IslandFlowNode] = deque()
        visited = set()
        for flowSource in sources:
            q.append(flowSource)
        while q:
            flowNode: IslandFlowNode = q.popleft()
            if flowNode.island.unique_id in visited:
                continue
            visited.add(flowNode.island.unique_id)

            allSourceX = [t.x for t in flowNode.island.tile_set]
            allSourceY = [t.y for t in flowNode.island.tile_set]
            sourceX = sum(allSourceX) / len(allSourceX)
            sourceY = sum(allSourceY) / len(allSourceY)

            for destinationEdge in flowNode.flow_to:
                allDestX = [t.x for t in destinationEdge.target_flow_node.island.tile_set]
                allDestY = [t.y for t in destinationEdge.target_flow_node.island.tile_set]
                destX = sum(allDestX) / len(allDestX)
                destY = sum(allDestY) / len(allDestY)

                viewInfo.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{destinationEdge.edge_army}', color=sourceColor)
                q.append(destinationEdge.target_flow_node)

    @staticmethod
    def add_nx_flow_precursor_graph_to_view_info(digraph: nx.DiGraph, islandBuilder: TileIslandBuilder, viewInfo: ViewInfo):
        for flowSource in digraph.edges(data=True):
            fromId, toId, dataBag = flowSource
            if fromId < 0:
                fromId = -fromId
            if toId < 0:
                toId = -toId
            if toId == fromId:
                continue

            weight = dataBag['weight']
            capacity = dataBag['capacity']

            if fromId in islandBuilder.tile_islands_by_unique_id:
                fromIsland = islandBuilder.tile_islands_by_unique_id[fromId]

                allSourceX = [t.x for t in fromIsland.tile_set]
                allSourceY = [t.y for t in fromIsland.tile_set]
                sourceX = sum(allSourceX) / len(allSourceX)
                sourceY = sum(allSourceY) / len(allSourceY)
            else:
                sourceX = viewInfo.map.cols + 1
                sourceY = viewInfo.map.rows + 1

            if toId in islandBuilder.tile_islands_by_unique_id:
                toIsland = islandBuilder.tile_islands_by_unique_id[toId]
                allDestX = [t.x for t in toIsland.tile_set]
                allDestY = [t.y for t in toIsland.tile_set]
                destX = sum(allDestX) / len(allDestX)
                destY = sum(allDestY) / len(allDestY)
            else:
                destX = viewInfo.map.cols + 2
                destY = viewInfo.map.rows + 2

            viewInfo.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{weight}, {capacity}', color=Colors.BLACK)

    def ensure_flow_graph_exists(self, islands: TileIslandBuilder):
        finder = self._get_networkx_flow_direction_finder()
        finder.ensure_flow_graph_exists(islands)
        self.enemyGeneral = finder.enemy_general

    def _build_island_flow_precursor_nx_data(self, islands: TileIslandBuilder, useNeutralFlow: bool) -> NxFlowGraphData:
        finder = self._get_networkx_flow_direction_finder()
        graphData = finder._build_island_flow_precursor_nx_data(islands, useNeutralFlow)
        self.enemyGeneral = finder.enemy_general
        return graphData

    def _determine_initial_demands_and_split_input_output_nodes(self, graph, islands, ourSet, targetSet, includeNeutralFlow: bool):
        return self._get_networkx_flow_direction_finder()._determine_initial_demands_and_split_input_output_nodes(graph, islands, ourSet, targetSet, includeNeutralFlow)

    def _find_island_consumed_tiles_from_borders(
            self,
            islandBuilder: TileIslandBuilder,
            incompleteSource: IslandFlowNode,
            gathing: typing.Set[Tile],
            capping: typing.Set[Tile],
            unusedSourceArmy: int,
            flowTo: typing.List[IslandFlowEdge],
            negativeTiles: TileSet | None = None
    ) -> typing.Set[Tile]:
        q: typing.List[typing.Tuple[int, Tile]] = []

        incIsland = incompleteSource.island
        borders = set()

        useCappingGathing = len(gathing) > 0 or len(capping) > 0
        if useCappingGathing:
            # for destEdge in flowTo:
            for incompleteTile in incIsland.tile_set:
                for t in incompleteTile.movableNoObstacles:
                    if t in capping or t in gathing:
                        borders.add(incompleteTile)
                        # dont need to keep checking this incompleteTile, try the next one
                        break

                # for t in borderLookup[destEdge.target_flow_node.island.unique_id]:
                #     if t in capping or t in gathing:
                #         borders.add(t)

        if not borders:
            borderLookup = islandBuilder.get_island_border_tile_lookup(incIsland)
            for destEdge in flowTo:
                try:
                    borders.update(borderLookup[destEdge.target_flow_node.island.unique_id])
                except:
                    logbook.error(f'failed to find border from {incompleteSource.island} to {destEdge.target_flow_node.island}')
                    raise

        toUse = incIsland.sum_army - unusedSourceArmy - incIsland.tile_count

        for tile in borders:
            heapq.heappush(q, (1 - tile.army, tile))

        used = set()
        # overFillOpts = set()
        while q:
            negArmy, tile = heapq.heappop(q)
            if tile in used:
                continue

            toUse = toUse + negArmy
            used.add(tile)
            if toUse <= 0:
                break

            # nextToUse = toUse + negArmy
            # if nextToUse < 0:
            #     overFillOpts.add(tile)
            #     continue
            #
            # used.add(tile)
            # toUse = nextToUse
            # if toUse == 0:
            #     break

            for mv in tile.movable:
                if mv in incIsland.tile_set:
                    heapq.heappush(q, (1 - mv.army, mv))

        if toUse < 0:
            logbook.warning(
                f'toUse was {toUse}, expected 0. (used {used}). We will have extra army in the flow that isnt going to be known about by the algo. unusedSourceArmy was {unusedSourceArmy}, island tile army was {[t.army for t in incompleteSource.island.tiles_by_army]}')
        if toUse > 0:
            logbook.warning(f'toUse was {toUse}, expected 0. (used {used}). THIS IS INVALID. unusedSourceArmy was {unusedSourceArmy}, island tile army was {[t.army for t in incompleteSource.island.tiles_by_army]}')

        return used

    def _find_island_consumed_tiles_from_borders_by_count(
            self,
            islandBuilder: TileIslandBuilder,
            incompleteDest: IslandFlowNode,
            gathing: typing.Set[Tile],
            capping: typing.Set[Tile],
            countToInclude: int,
            comeFrom: typing.Dict[int, IslandFlowNode],
            negativeTiles: TileSet | None = None
    ) -> typing.Set[Tile]:
        q: typing.List[typing.Tuple[int, Tile]] = []
        if countToInclude <= 0:
            return set()

        incIsland = incompleteDest.island
        borders = set()

        useCappingGathing = len(gathing) > 0 or len(capping) > 0
        if useCappingGathing:
            # for borderNode in comeFrom.values():
            #     for t in borderLookup[borderNode.island.unique_id]:
            #         if t in capping or t in gathing:
            #             borders.add(t)
            for incompleteTile in incIsland.tile_set:
                for t in incompleteTile.movableNoObstacles:
                    if t in capping or t in gathing:
                        borders.add(incompleteTile)
                        # dont need to keep checking this incompleteTile, try the next one
                        break

        if not borders:
            borderLookup = islandBuilder.get_island_border_tile_lookup(incIsland)
            for borderNode in comeFrom.values():
                borders.update(borderLookup[borderNode.island.unique_id])

        for tile in borders:
            heapq.heappush(q, (1 - tile.army, tile))

        used = set()
        while q:
            negArmy, tile = heapq.heappop(q)
            if tile in used:
                continue
            used.add(tile)
            if len(used) >= countToInclude:
                break

            for mv in tile.movable:
                if mv in incIsland.tile_set:
                    heapq.heappush(q, (1 - mv.army, mv))

        return used

    @staticmethod
    def iterate_flow_nodes(rootNodes: typing.Iterable[IslandFlowNode]) -> typing.Generator[IslandFlowNode, None, None]:
        q = deque()

        n: IslandFlowNode
        initVisited = set()
        for n in rootNodes:
            if n in initVisited:
                continue
            q.append(n)
            initVisited.add(n)

        visited = set()

        while q:
            n = q.popleft()
            alreadyVis = n.island.unique_id in visited
            if alreadyVis:
                continue

            visited.add(n.island.unique_id)
            yield n

            for edge in n.flow_to:
                q.append(edge.target_flow_node)

        # TODO second test, remove EVERYTHING below this line later
        initVisited = set()
        iter = 0
        for n in rootNodes:
            if n in initVisited:
                continue
            q.append(n)
            initVisited.add(n)

        vis2 = set()
        while q:
            iter += 1
            n = q.popleft()
            vis2.add(n.island.unique_id)

            for edge in n.flow_to:
                q.append(edge.target_flow_node)
            if iter > 600:
                raise Exception(f'infinite looped. Nodes in loop: {" | ".join(str(n) for n in q)}')

        if len(vis2) != len(visited):
            raise Exception(
                f'flow nodes were corrupted, there were paths to different copies of the same node in them, with different flow_to contents, resulting in {len(vis2)} visited without visited set, and {len(visited)} with visited set.')

    @staticmethod
    def iterate_flow_children(rootNodes: typing.Iterable[IslandFlowNode]) -> typing.Generator[IslandFlowNode, None, None]:
        q = deque()

        n: IslandFlowNode
        initVisited = set()
        for n in rootNodes:
            if n in initVisited:
                continue
            for edge in n.flow_to:
                q.append(edge.target_flow_node)
            initVisited.add(n)

        visited = set()

        while q:
            n = q.popleft()
            alreadyVis = n.island.unique_id in visited
            if alreadyVis:
                continue

            visited.add(n.island.unique_id)
            yield n

            for edge in n.flow_to:
                q.append(edge.target_flow_node)

        # TODO second test, remove EVERYTHING below this line later
        iter = 0
        initVisited = set()
        for n in rootNodes:
            if n in initVisited:
                continue
            for edge in n.flow_to:
                q.append(edge.target_flow_node)
            initVisited.add(n)

        vis2 = set()
        while q:
            iter += 1
            n = q.popleft()
            vis2.add(n.island.unique_id)

            for edge in n.flow_to:
                q.append(edge.target_flow_node)

            if iter > 600:
                raise Exception(f'infinite looped. Nodes in loop: {" | ".join(str(n) for n in q)}')

        if len(vis2) != len(visited):
            raise Exception(
                f'flow nodes were corrupted, there were paths to different copies of the same node in them, with different flow_to contents, resulting in {len(vis2)} visited without visited set, and {len(visited)} with visited set.')

    def assertEverythingSafe(
            self,
            fullSearchTurns,
            negVt,
            turnsUsed,
            turnsLeft,
            armyToCap,
            randomTieBreak,
            targetTiles: typing.Deque[int],
            econValue,
            gathSum,
            # TODO
            frLeftoverArmy,
            friendlyTileLeftoverIdx,
            targetCalculatedNode,
            friendlyUncalculatedNode,
            visited: typing.Set[TileIsland],
            nextTargets,
            nextFriendlies,
            rootNodes,
            pairOptions,
    ):
        if turnsUsed <= 0:
            return
        mismatches = []
        safetyChecker = {}
        minTurnsUsed = -1  # first move doesn't cost anything
        maxTurnsUsed = -1
        expectedTurnsUsed = -1
        nodes = [n for n in ArmyFlowExpander.iterate_flow_nodes(rootNodes.values())]
        if len(nodes) == 0:
            self.live_render_capture_stuff(
                self.island_builder,
                capping=itertools.chain.from_iterable([i.tile_set for i in visited]),
                gathing=friendlyUncalculatedNode.island.tile_set,
                incompleteSource=friendlyUncalculatedNode.island,
                incompleteTarget=targetCalculatedNode.island,
                incompleteSourceNode=friendlyUncalculatedNode,
                incompleteTargetNode=targetCalculatedNode,
                sourceUnused=gathSum,
                plan=None,
                extraInfo=(f"turnsUsed {turnsUsed}, turnsLeft {turnsLeft}, econValue {econValue:.2f},"
                    f"\r\n  gathSum {gathSum}, frLeftoverArmy {frLeftoverArmy}, armyToCap {armyToCap},"
                    f"\r\n  negVt {negVt},  randomTieBreak {randomTieBreak}"))
            raise Exception('no nodes in flow')
        for n in nodes:
            existing = safetyChecker.get(n.island.unique_id, None)
            if existing is not None:
                if existing != n:
                    mismatches.append(f'Corrupted root nodes; {n}  !=  {existing}')
                logbook.info(f'double visiting {existing}')
                # we flow to this node twice...? means we make two moves into it, at minimum.
                minTurnsUsed += 1
                maxTurnsUsed += 1
            else:
                safetyChecker[n.island.unique_id] = n
                if n.island.unique_id == targetCalculatedNode.island.unique_id:
                    minTurnsUsed += n.island.tile_count - len(targetTiles)
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count - len(targetTiles)
                elif n.island.unique_id == friendlyUncalculatedNode.island.unique_id:
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count - friendlyTileLeftoverIdx - 1
                    continue
                else:
                    minTurnsUsed += n.island.tile_count
                    maxTurnsUsed += n.island.tile_count
                    expectedTurnsUsed += n.island.tile_count

        if turnsUsed < minTurnsUsed:
            mismatches.append(f'rootNodes min traversed tilecount summed to {minTurnsUsed} but turnsUsed was {turnsUsed}')
        if turnsUsed > maxTurnsUsed:
            mismatches.append(f'rootNodes max traversed tilecount summed to {maxTurnsUsed} but turnsUsed was {turnsUsed}')
        if turnsUsed != expectedTurnsUsed:
            mismatches.append(f'rootNodes expected turnsUsed summed to {expectedTurnsUsed} but turnsUsed was {turnsUsed}')

        maxTurnsLeft = fullSearchTurns - minTurnsUsed
        minTurnsLeft = fullSearchTurns - maxTurnsUsed
        if turnsLeft < minTurnsLeft:
            mismatches.append(f'rootNodes min traversed turnsLeft (fullSearch - maxTurnsUsed) to {minTurnsLeft} but turnsLeft was {turnsLeft}')
        if turnsLeft > maxTurnsLeft:
            mismatches.append(f'rootNodes max traversed turnsLeft (fullSearch - minTurnsUsed) to {maxTurnsLeft} but turnsLeft was {turnsLeft}')
        #
        # # if len(safetyChecker) != len(visited):
        # #     mismatches.append(f'visited {len(visited)}  != len(safetyChecker) {len(safetyChecker)}')
        # #     for i, islandFlowNode in safetyChecker.items():
        # #         if islandFlowNode.island not in visited:
        # #             mismatches.append(f'  rootNodes visited {islandFlowNode} but it was not in visited.')
        # #
        # #     for island in visited:
        # #         match = safetyChecker.get(island.unique_id, None)
        # #         if match is None:
        # #             mismatches.append(f'  visited contained {island} but it was not in rootNodes.')
        #
        for n in ArmyFlowExpander.iterate_flow_nodes(nextTargets.values()):
            existing = safetyChecker.get(n.island.unique_id, None)
            if existing is not None:
                if existing != n:
                    mismatches.append(f'Corrupted nextTarget nodes; {n}  !=  {existing}')
            else:
                safetyChecker[n.island.unique_id] = n

        for n in ArmyFlowExpander.iterate_flow_nodes(nextFriendlies.values()):
            existing = safetyChecker.get(n.island.unique_id, None)
            if existing is not None:
                if existing != n:
                    mismatches.append(f'Corrupted nextFriendlies nodes; {n}  !=  {existing}')
            else:
                safetyChecker[n.island.unique_id] = n

        existing = safetyChecker.get(targetCalculatedNode.island.unique_id, None)
        if existing is not None:
            if existing != targetCalculatedNode:
                mismatches.append(f'Corrupted targetCalculatedNode node; {targetCalculatedNode}  !=  {existing}')
        else:
            safetyChecker[targetCalculatedNode.island.unique_id] = targetCalculatedNode

        existing = safetyChecker.get(friendlyUncalculatedNode.island.unique_id, None)
        # if existing is not None:
        if existing != friendlyUncalculatedNode:
            mismatches.append(f'Corrupted friendlyUncalculatedNode node; {friendlyUncalculatedNode} != {existing}')
        else:
            safetyChecker[friendlyUncalculatedNode.island.unique_id] = friendlyUncalculatedNode

        if mismatches:
            mismatch_lines = "\r\n    ".join(mismatches)
            self.live_render_capture_stuff(
                self.island_builder,
                capping=set(itertools.chain.from_iterable([i.tile_set for i in visited])),
                gathing=friendlyUncalculatedNode.island.tile_set,
                incompleteSource=friendlyUncalculatedNode.island,
                incompleteTarget=targetCalculatedNode.island,
                incompleteSourceNode=friendlyUncalculatedNode,
                incompleteTargetNode=targetCalculatedNode,
                sourceUnused=gathSum,
                plan=None,
                extraInfo=(f"turnsUsed {turnsUsed}, turnsLeft {turnsLeft}, econValue {econValue:.2f},"
                    f"\r\n  gathSum {gathSum}, frLeftoverArmy {frLeftoverArmy}, armyToCap {armyToCap},"
                    f"\r\n  negVt {negVt},  randomTieBreak {randomTieBreak},"
                    f"\r\n    {mismatch_lines}"))
            msg = "Search is corrupted;\r\n" + "\r\n".join(mismatches)
            logbook.error(msg)
            raise Exception(msg)

    def _get_a_star_priority_val_true(
            self,
            capValue: float,
            econValueSoFar: float,
            newTurnsUsed: int,
            newFrLeftoverArmy: int,
            newFriendlyTileLeftoverIdx: int,
            friendlyUncalculated: TileIsland,
            targetIsland: TileIsland,
            searchTurns: int,
            tgTiles: typing.Deque[int]
    ) -> float:
        """
        Must always OVERESTIMATE the potential reward if we want to properly A*.
        Reward should always be based on a full searchTurns length plan potential.

        @param capValue:
        @param econValueSoFar:
        @param newTurnsUsed:
        @param newFrLeftoverArmy:
        @param newFriendlyTileLeftoverIdx:
        @param friendlyUncalculated:
        @param searchTurns:
        @param tgTiles:
        @return:
        """
        # TODO we can look at the current tile islands adjacent friendly total and deduce whether we must waste at least one extra move bridging a gap to reach our full max value econ vt...?
        # TODO look at army avail to gather vs army avail to capture vs tiles avail to capture to estimate how move-effective the next gather would be...?
        frIslandArmyLeft = self.get_friendly_island_army_left(friendlyUncalculated, newFrLeftoverArmy, newFriendlyTileLeftoverIdx)

        maxCaps = (frIslandArmyLeft - 1) // 2

        turnsAtOptimalCaps = searchTurns - newTurnsUsed - newFriendlyTileLeftoverIdx
        # if targetIsland.tile_count_all_adjacent_friendly < turnsAtOptimalCaps:
        #     turnsAtOptimalCaps -= 3

        maxAddlEcon = 0.0
        if targetIsland.team == -1:
            turnsAtOptimalCaps -= len(tgTiles)
            # assume that we finish out this island and then go back to capturing enemy tiles for the rest of the time
            maxAddlEcon += capValue * len(tgTiles)
            # penalize our number of captures based on wasting 1 army per captured tile? This seems questionable.
            maxCaps -= len(tgTiles) // 2

        if maxCaps < turnsAtOptimalCaps:
            # we must spend at LEAST one more turn gathering.
            # TODO this is probably where we can break A* and approximate how many turns we probably have to gather to keep capping, maybe? Or maybe this doesn't matter if using global visited set.
            turnsAtOptimalCaps -= 1
            # turnsAtOptimalCaps -= 1 + 2 * (self._dynamic_heuristic_ratio - 1.0)

        maxAddlEcon += turnsAtOptimalCaps * 2

        # by multiplying the base econ as we search for longer, we reward paths that are already longer.
        rewardMetric = (econValueSoFar * self._dynamic_heuristic_ratio) + maxAddlEcon
        # rewardMetric = econValueSoFar + maxAddlEcon * self._dynamic_heuristic_ratio

        # the logic in the other spot
        # maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)
        # maxPossibleNewEconPerTurn = (newEconValue + maxCaps * capValue) / (newTurnsUsed + maxCaps + newFriendlyTileLeftoverIdx)

        return rewardMetric

    def _get_a_star_priority_val(
            self,
            capValue: float,
            econValueSoFar: float,
            newTurnsUsed: int,
            newFrLeftoverArmy: int,
            newFriendlyTileLeftoverIdx: int,
            friendlyUncalculated: TileIsland,
            targetIsland: TileIsland,
            searchTurns: int,
            tgTiles: typing.Deque[int]
    ) -> float:
        """
        Must always OVERESTIMATE the potential reward if we want to properly A*.
        Reward should always be based on a full searchTurns length plan potential.

        @param capValue:
        @param econValueSoFar:
        @param newTurnsUsed:
        @param newFrLeftoverArmy:
        @param newFriendlyTileLeftoverIdx:
        @param friendlyUncalculated:
        @param searchTurns:
        @param tgTiles:
        @return:
        """
        # TODO we can look at the current tile islands adjacent friendly total and deduce whether we must waste at least one extra move bridging a gap to reach our full max value econ vt...?
        # TODO look at army avail to gather vs army avail to capture vs tiles avail to capture to estimate how move-effective the next gather would be...?
        frIslandArmyLeft = self.get_friendly_island_army_left(friendlyUncalculated, newFrLeftoverArmy, newFriendlyTileLeftoverIdx)

        maxCaps = (frIslandArmyLeft - 1) // 2

        turnsAtOptimalCaps = searchTurns - newTurnsUsed - newFriendlyTileLeftoverIdx - 1
        # if targetIsland.tile_count_all_adjacent_friendly < turnsAtOptimalCaps:
        #     turnsAtOptimalCaps -= 3

        if turnsAtOptimalCaps > targetIsland.tile_count:
            distToLargeIsland = self.dists_to_target_large_island.raw[next(iter(targetIsland.tile_set)).tile_index]
            if distToLargeIsland > 2:
                if targetIsland.team == self.team:
                    turnsAtOptimalCaps -= distToLargeIsland - 1
                elif targetIsland.team != self.target_team:
                    turnsAtOptimalCaps -= distToLargeIsland // 2 - 1

        maxAddlEcon = 0.0
        if targetIsland.team == -1:
            turnsAtOptimalCaps -= len(tgTiles)
            # assume that we finish out this island and then go back to capturing enemy tiles for the rest of the time
            maxAddlEcon += capValue * len(tgTiles)
            # penalize our number of captures based on wasting 1 army per captured tile? This seems questionable.
            maxCaps -= len(tgTiles) // 2
        elif targetIsland.team == self.team:
            turnsAtOptimalCaps -= len(tgTiles)
            # tgTiles are negative values when they are friendly team.
            frIslandArmyLeft -= sum(tgTiles) + len(tgTiles)

        if maxCaps < turnsAtOptimalCaps:
            # we must spend at LEAST one more turn gathering.
            # TODO this is probably where we can break A* and approximate how many turns we probably have to gather to keep capping, maybe? Or maybe this doesn't matter if using global visited set.
            turnsAtOptimalCaps -= 1
            # turnsAtOptimalCaps -= 1 + 2 * (self._dynamic_heuristic_ratio - 1.0)
        #
        # if maxCaps > 0 and self._dynamic_heuristic_falsehood_ratio != 0.0:
        #     maxAddlEcon += maxCaps * self._dynamic_heuristic_falsehood_ratio

        maxAddlEcon += turnsAtOptimalCaps * 2

        # by multiplying the base econ as we search for longer, we reward paths that are already longer.
        rewardMetric = (econValueSoFar * self._dynamic_heuristic_ratio) + maxAddlEcon
        # rewardMetric = econValueSoFar + maxAddlEcon * self._dynamic_heuristic_ratio

        # the logic in the other spot
        # maxPossibleNewEconPerTurn = (econValue + maxPossibleAddlCaps * capValue) / (turnsUsed + maxPossibleAddlCaps + nextFriendlyUncalculated.tile_count)
        # maxPossibleNewEconPerTurn = (newEconValue + maxCaps * capValue) / (newTurnsUsed + maxCaps + newFriendlyTileLeftoverIdx)

        return rewardMetric

    def get_friendly_island_army_left(self, friendlyUncalculated, newFrLeftoverArmy, newFriendlyTileLeftoverIdx):
        frIslandArmyLeft: int = newFrLeftoverArmy
        # TODO can get rid of this iteration by just also maintaining a 'friendlyIslandArmyUsed' that we can subtract from its total army to avoid these extra sums
        if newFriendlyTileLeftoverIdx * 2 >= friendlyUncalculated.tile_count:
            frIslandArmyLeft += friendlyUncalculated.sum_army - sum(t.army for t in friendlyUncalculated.tiles_by_army[newFriendlyTileLeftoverIdx + 1:])
        else:
            frIslandArmyLeft += sum(t.army for t in friendlyUncalculated.tiles_by_army[0:newFriendlyTileLeftoverIdx + 1])
        if newFriendlyTileLeftoverIdx >= 0:
            frIslandArmyLeft -= newFriendlyTileLeftoverIdx + 1
        return frIslandArmyLeft

    def _is_flow_allowed(
            self,
            fromIsland: TileIsland,
            toIsland: TileIsland,
            armyAmount: int,
            isSubsequentTarget: bool = False,
            isSubsequentFriendly: bool = False,
            friendlyBorderingEnemy: typing.Set[TileIsland] | None = None
    ) -> bool:
        if not self.use_min_cost_flow_edges_only:
            if isSubsequentTarget:
                # TODO note this restricts us to only sink one-island-deep into FFA enemy territory who is not target player
                #  (since we allow them as destinations above but will only branch into neutral or target from there).
                if fromIsland.team != self.target_team and fromIsland.team != -1 and toIsland.team != self.target_team:
                    return False
            if isSubsequentFriendly:
                if fromIsland.team != self.team:  # or (friendlyBorderingEnemy and fromIsland in friendlyBorderingEnemy)
                    return False
            return True

        #
        # # TODO remove these later
        # if isSubsequentTarget:
        #     # TODO note this restricts us to only sink one-island-deep into FFA enemy territory who is not target player
        #     #  (since we allow them as destinations above but will only branch into neutral or target from there).
        #     if fromIsland.team != self.target_team and fromIsland.team != -1 and fromIsland.team != self.team and toIsland.team != self.target_team:
        #         return False

        # if isSubsequentFriendly:
        #     if fromIsland.team != self.team:  # or (friendlyBorderingEnemy and fromIsland in friendlyBorderingEnemy)
        #         return False

        allow = False
        if fromIsland.unique_id not in self.flow_graph.flow_node_lookup_by_island_no_neut:
            return False
        if toIsland.unique_id not in self.flow_graph.flow_node_lookup_by_island_no_neut:
            return False
        fromNoNeut = self.flow_graph.flow_node_lookup_by_island_no_neut[fromIsland.unique_id]
        toNoNeut = self.flow_graph.flow_node_lookup_by_island_no_neut[toIsland.unique_id]
        for dest in fromNoNeut.flow_to:
            if toNoNeut == dest.target_flow_node:
                return True
                allow = True
                break

        fromWithNeut = self.flow_graph.flow_node_lookup_by_island_inc_neut[fromIsland.unique_id]
        toWithNeut = self.flow_graph.flow_node_lookup_by_island_inc_neut[toIsland.unique_id]
        for dest in fromWithNeut.flow_to:
            if toWithNeut == dest.target_flow_node:
                return True
                allow = True
                break

        return allow
        # fromWithNeut = self.flow_graph.flow_node_lookup_by_island_inc_neut[fromIsland.unique_id]
        #
        # if fromNoNeut.



class PlanDupeChecker(object):
    def __init__(self):
        self.plans: typing.List[FlowExpansionPlanOption] = []
        self.set: typing.Set[Tile] = set()

    def __str__(self) -> str:
        return ' | '.join(p.shortInfo() for p in self.plans)

    def __repr__(self) -> str:
        return str(self)