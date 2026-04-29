from __future__ import annotations

import typing

import logbook

from BehaviorAlgorithms.Flow.FlowDirectionFinderABC import FlowDirectionFinderABC
from BehaviorAlgorithms.Flow.FlowGraphModels import IslandFlowNode, IslandMaxFlowGraph
from BehaviorAlgorithms.Flow.NetworkXFlowDirectionFinder import NetworkXFlowDirectionFinder
from BehaviorAlgorithms.Flow.NxFlowGraphData import NxFlowGraphData
from BehaviorAlgorithms.PyMaxFlowIteratorHelpers import PyMaxFlowGraphData, PyMaxFlowComputer, NxToPyMaxflowConverter
from MapMatrix import MapMatrix
from PerformanceTimer import PerformanceTimer

if typing.TYPE_CHECKING:
    from Algorithms import TileIslandBuilder, TileIsland
    from ArmyAnalyzer import ArmyAnalyzer
    from base.client.map import MapBase, Tile
    from Interfaces import TileSet
    from BehaviorAlgorithms.Flow.FlowGraphModels import FlowGraphMethod


class PyMaxFlowDirectionFinder(FlowDirectionFinderABC):
    """
    FlowDirectionFinderABC implementation that uses PyMaxflow (Boykov-Kolmogorov) for
    flow computation.  Graph construction is delegated to a NetworkXFlowDirectionFinder
    (which already knows how to turn island data into an NxFlowGraphData); the resulting
    NxFlowGraphData is then converted to PyMaxFlowGraphData and solved with PyMaxFlowComputer.

    Both ArmyFlowExpanderV2 and ArmyFlowExpander supply intergeneral_analysis at construction
    time (obtained from island_builder.intergeneral_analysis before calling this).
    """

    def __init__(
        self,
        map: 'MapBase',
        intergeneral_analysis: 'ArmyAnalyzer',
        perf_timer: PerformanceTimer,
        log_debug: bool,
        use_backpressure: bool,
        friendly_general: 'Tile',
        invalid_flow_renderer,
    ):
        self.map: 'MapBase' = map
        self.perf_timer: PerformanceTimer = perf_timer
        self.log_debug: bool = log_debug
        self.use_backpressure_from_enemy_general: bool = use_backpressure
        self.friendly_general: 'Tile' = friendly_general
        self.invalid_flow_renderer = invalid_flow_renderer

        self._intergeneral_analysis: 'ArmyAnalyzer' = intergeneral_analysis
        self._nx_finder: NetworkXFlowDirectionFinder | None = None

        self.team: int = map.friendly_team
        self.target_team: int = [t for t in map.get_teams_array(map) if t != self.team][0]
        self._enemy_general: 'Tile | None' = None

        self.pymax_graph_data: PyMaxFlowGraphData | None = None
        self.pymax_graph_data_no_neut: PyMaxFlowGraphData | None = None
        self._last_built_graphs_turn: int = -1

    def _get_nx_finder(self) -> NetworkXFlowDirectionFinder:
        """Return (and lazily construct) the inner NX finder."""
        if self._nx_finder is None:
            self._nx_finder = NetworkXFlowDirectionFinder(
                self.map,
                self._intergeneral_analysis,
                self.friendly_general,
                self.use_backpressure_from_enemy_general,
                self.perf_timer,
                self.log_debug,
                self.invalid_flow_renderer,
            )
        self._nx_finder.configure(self.team, self.target_team, self._enemy_general)
        return self._nx_finder

    # ------------------------------------------------------------------
    # FlowDirectionFinderABC interface
    # ------------------------------------------------------------------

    def configure(self, team: int, target_team: int, enemy_general: 'Tile | None'):
        self.team = team
        self.target_team = target_team
        self.enemy_general = enemy_general

    def invalidate_cache(self):
        self.pymax_graph_data = None
        self.pymax_graph_data_no_neut = None
        if self._nx_finder is not None:
            self._nx_finder.invalidate_cache()

    @property
    def graph_data(self) -> PyMaxFlowGraphData | None:
        return self.pymax_graph_data

    @property
    def graph_data_no_neut(self) -> PyMaxFlowGraphData | None:
        return self.pymax_graph_data_no_neut

    @property
    def enemy_general(self) -> 'Tile | None':
        return self._enemy_general

    @enemy_general.setter
    def enemy_general(self, value: 'Tile | None'):
        self._enemy_general = value

    def ensure_graph_data_available(self, islands: 'TileIslandBuilder'):
        # if self.pymax_graph_data is not None and self._last_built_graphs_turn >= self.map.turn:
        #     return

        # TODO directly build pymaxflow input graph instead of converting nx lol

        nx_finder = self._get_nx_finder()
        nx_finder.ensure_graph_data_available(islands)
        self._enemy_general = nx_finder.enemy_general

        converter = NxToPyMaxflowConverter()
        converter.log_debug = self.log_debug
        self.pymax_graph_data = converter.convert_nx_flow_graph_data(nx_finder.nx_graph_data)
        self.pymax_graph_data_no_neut = converter.convert_nx_flow_graph_data(nx_finder.nx_graph_data_no_neut)
        self._last_built_graphs_turn = self.map.turn

    def build_graph_data(self, islands: 'TileIslandBuilder', use_neutral_flow: bool) -> PyMaxFlowGraphData:
        nx_finder = self._get_nx_finder()
        nx_data: NxFlowGraphData = nx_finder.build_graph_data(islands, use_neutral_flow)
        self._enemy_general = nx_finder.enemy_general
        converter = NxToPyMaxflowConverter()
        converter.log_debug = self.log_debug
        return converter.convert_nx_flow_graph_data(nx_data)

    def compute_flow_dict(
        self,
        islands: 'TileIslandBuilder',
        graph_data: PyMaxFlowGraphData,
        method,
        render_on_exception: bool = True
    ) -> typing.Dict[int, typing.Dict[int, int]]:
        computer = PyMaxFlowComputer(self.perf_timer, self.log_debug)
        _flow_value, flow_dict = computer.compute_flow(graph_data, method)
        return flow_dict

    def build_flow_graph(
        self,
        islands: 'TileIslandBuilder',
        our_islands: typing.List['TileIsland'],
        target_islands: typing.List['TileIsland'],
        searching_player: int,
        turns: int,
        blockGatherFromEnemyBorders: bool = True,
        negativeTiles: 'TileSet | None' = None,
        includeNeutralDemand: bool = False,
        method=None,
    ) -> 'IslandMaxFlowGraph':
        self.ensure_graph_data_available(islands)

        graph_data_with_neut: PyMaxFlowGraphData = self.pymax_graph_data
        graph_data_no_neut: PyMaxFlowGraphData = self.pymax_graph_data_no_neut

        with_neut_flow_dict = self.compute_flow_dict(islands, graph_data_with_neut, method)
        no_neut_flow_dict = self.compute_flow_dict(islands, graph_data_no_neut, method)

        target_general_island = islands.tile_island_lookup.raw[self._enemy_general.tile_index]

        with_neut_graph_lookup: typing.Dict[int, IslandFlowNode] = {}
        no_neut_graph_lookup: typing.Dict[int, IslandFlowNode] = {}

        for island in islands.all_tile_islands:
            demand_no_neut = graph_data_no_neut.demand_lookup.get(island.unique_id, 0)
            no_neut_graph_lookup[island.unique_id] = IslandFlowNode(island, demand_no_neut)

            demand_with_neut = graph_data_with_neut.demand_lookup.get(island.unique_id, 0)
            with_neut_graph_lookup[island.unique_id] = IslandFlowNode(island, demand_with_neut)

        backfill_neut_edges, enemy_backfill_flow_nodes, final_root_flow_nodes = self.build_flow_nodes_from_lookups(
            our_islands, target_general_island, target_islands, with_neut_flow_dict, with_neut_graph_lookup, graph_data_with_neut, self.log_debug
        )
        backfill_neut_no_neut_edges, enemy_backfill_no_neut_flow_nodes, final_root_no_neut_flow_nodes = self.build_flow_nodes_from_lookups(
            our_islands, target_general_island, target_islands, no_neut_flow_dict, no_neut_graph_lookup, graph_data_no_neut, self.log_debug
        )

        no_neut_flow_node_lookup = MapMatrix(self.map, None)
        inc_neut_flow_node_lookup = MapMatrix(self.map, None)
        for flow_node in no_neut_graph_lookup.values():
            for t in flow_node.island.tile_set:
                no_neut_flow_node_lookup.raw[t.tile_index] = flow_node
        for flow_node in with_neut_graph_lookup.values():
            for t in flow_node.island.tile_set:
                inc_neut_flow_node_lookup.raw[t.tile_index] = flow_node

        return IslandMaxFlowGraph(
            final_root_no_neut_flow_nodes,
            final_root_flow_nodes,
            enemy_backfill_no_neut_flow_nodes,
            enemy_backfill_flow_nodes,
            backfill_neut_no_neut_edges,
            backfill_neut_edges,
            no_neut_flow_node_lookup,
            inc_neut_flow_node_lookup,
            no_neut_graph_lookup,
            with_neut_graph_lookup,
        )
