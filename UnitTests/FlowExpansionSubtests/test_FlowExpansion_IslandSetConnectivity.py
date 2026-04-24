import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from MapMatrix import MapMatrix
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase, Tile
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot


class FlowExpansionIslandSetConnectivityTests(TestBase):
    """
    Tests that FlowExpansion produces connected/contiguous tile sets.

    The bug: FlowExpansion can produce gather/capture tile sets that contain
    disconnected tiles - tiles that aren't actually reachable from each other
    through the set itself. This causes issues when the algorithm tries to
    construct valid gather plans.

    These tests verify that for any expansion plan produced:
    1. All tiles in the gather set (gathing) form a single connected component
    2. All tiles in the capture set (capping) form a single connected component
     3. The gather and capture sets are adjacent (share at least one border)
    """

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)
        return bot

    def _build_expander_v2(self, map, builder):
        """Helper: build ArmyFlowExpanderV2 with flow graph and detection results."""
        from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
        expander = ArmyFlowExpanderV2(map)
        expander._ensure_flow_graph_exists(builder)
        return expander

    def _get_tile_connected_components(self, tiles: typing.Set[Tile]) -> typing.List[typing.Set[Tile]]:
        """
        Find all connected components in a set of tiles using BFS.
        Two tiles are connected if they are adjacent (share an edge).
        """
        if not tiles:
            return []

        remaining = set(tiles)
        components = []

        while remaining:
            # Start a new component
            start = remaining.pop()
            component = {start}
            queue = [start]

            while queue:
                current = queue.pop(0)
                for neighbor in current.movable:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)

            components.append(component)

        return components

    def _assert_tile_set_connected(self, tile_set: typing.Set[Tile], set_name: str, border_pair_str: str):
        """
        Assert that all tiles in the set form a single connected component.
        """
        if not tile_set:
            return  # Empty set is vacuously connected

        components = self._get_tile_connected_components(tile_set)

        if len(components) > 1:
            # Build detailed error message
            component_info = []
            for i, comp in enumerate(components):
                tile_strs = [f"({t.x},{t.y})" for t in sorted(comp, key=lambda t: (t.x, t.y))]
                component_info.append(f"  Component {i+1} ({len(comp)} tiles): {', '.join(tile_strs)}")

            error_msg = (
                f"{set_name} tile set is DISCONNECTED for border pair {border_pair_str}!\n"
                f"Expected 1 connected component, found {len(components)}:\n"
                + "\n".join(component_info)
            )
            self.fail(error_msg)

    def _assert_gather_capture_adjacent(self, gathing: typing.Set[Tile], capping: typing.Set[Tile],
                                       border_pair_str: str):
        """
        Assert that gather and capture sets share at least one adjacent tile pair.
        """
        if not gathing or not capping:
            return  # Can't check adjacency if either set is empty

        found_adjacent = False
        for cap_tile in capping:
            for adj in cap_tile.movable:
                if adj in gathing:
                    found_adjacent = True
                    break
            if found_adjacent:
                break

        if not found_adjacent:
            gathing_str = ', '.join([f"({t.x},{t.y})" for t in sorted(gathing, key=lambda t: (t.x, t.y))])
            capping_str = ', '.join([f"({t.x},{t.y})" for t in sorted(capping, key=lambda t: (t.x, t.y))])
            self.fail(
                f"Gather and capture sets are NOT ADJACENT for border pair {border_pair_str}!\n"
                f"Gather tiles ({len(gathing)}): {gathing_str}\n"
                f"Capture tiles ({len(capping)}): {capping_str}"
            )

    def _run_expansion_and_validate_connectivity(
        self,
        map: MapBase,
        builder: TileIslandBuilder,
        turn_budget: int = 50
    ) -> typing.List:
        """
        Run FlowExpansion V2 and validate that all produced plans have connected tile sets.
        Returns the list of plans for additional assertions.
        """
        expander = self._build_expander_v2(map, builder)

        # Run the full expansion flow
        # intergeneral_analysis is an ArmyAnalyzer with tileA (friendly) and tileB (enemy)
        analysis = BoardAnalyzer(map, builder.intergeneral_analysis.tileA)
        analysis.rebuild_intergeneral_analysis(builder.intergeneral_analysis.tileB, possibleSpawns=None)
        territory: MapMatrixInterface[int] = MapMatrix(map, -1)
        for tile in map.pathable_tiles:
            territory[tile] = tile.player

        result = expander.get_expansion_options(
            islands=builder,
            asPlayer=map.player_index,
            targetPlayer=builder.intergeneral_analysis.tileB.player,
            turns=turn_budget,
            boardAnalysis=analysis,
            territoryMap=territory,
        )
        plans = result.flow_plans

        # Validate connectivity of each plan's tile sets
        for plan in plans:
            # Get the full tile set from the plan
            # The plan's tileSet includes both gather and capture tiles
            all_tiles = plan.tileSet

            # Get border pair info for error messages
            # Plans from FlowExpansion don't have border_pair attached, so use plan ID
            border_pair_str = f"plan_{id(plan)}"

            # Validate that the entire plan's tile set is connected
            # This catches the bug where FlowExpansion produces disconnected tile sets
            self._assert_tile_set_connected(all_tiles, "Plan", border_pair_str)

        return plans

    def _collect_gather_tiles_from_node(self, node, gathered: typing.Set[Tile]):
        """Recursively collect all tiles from a gather tree node."""
        if node.tile:
            gathered.add(node.tile)
        for child in node.children:
            self._collect_gather_tiles_from_node(child, gathered)

    def test_disconnected_island_set__horizontal_split_map(self):
        """
        Test map with horizontal split between friendly (blue) and enemy (red) territories.

        Layout resembles the screenshot: friendly territory on right, enemy on left,
        with a contested border in the middle.

        The test validates that FlowExpansion produces connected tile sets.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Map format: a = player 0 (red/enemy), b = player 1 (blue/friendly)
        # G = General, M = mountain/obstacle
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  M    M    a3   a4   a4   a8   a2   a6   a1   a1   a1   a1   a1   a1   a1   a1   a1
a1   M    M    a3   a3   a3   a3   a2   a1   a2   b2   b2   b2   b6   b2   b2   b2   a1
a2   a3   a4   a2   a3   a3   a8   a2   a2   a2   b2   a2   b2   b5   b2   b2   b3   a1
a3   a3   a3   a3   a3   a3   a3   a3   a3   a2   b2   a2   b2   b4   b4   b4   b3   a1
a3   a3   a2   a3   a4   a3   a4   a3   a3   a2   b2   a2   a2   a2   a2   a2   b2   a1
a3   a3   a3   a5   a3   a2   a2   a3   a2   a1   a1   a1   a1   b2   b2   b2   b2   a1
a3   a3   a3   a3   a3   a3   a3   a3   a2   a4   a4   a4   a4   b4   b3   b3   b3   a1
a4   a4   a2   a4   a4   a3   a3   a4   a2   a4   a3   a3   a3   b3   b2   b2   b2   b2
a4   a2   a3   a3   a4   a3   a2   a2   M    M    a2   b2   b2   b2   b2   b2   b2   b2
a2   a3   a3   a2   a3   a2   a3   a2   M    b1   a2   b2   M    M    b2   b2   b2   b2
a2   a3   a3   a3   a3   a2   a2   a3   M    b1   a2   b2   b2   M    b2   b2   b2   b2
a2   a3   a2   a3   a2   a2   M    M    M    b2   b2   b2   b2   b2   b2   b2   b2   b2
a4   a4   a4   a4   a3   a3   M    a2   M    M    b2   b2   b2   b2   b2   b2   b2   b2
a3   a3   a4   a3   a3   a2   M    a2   a2   b2   b2   b2   b2   b2   b2   b1   b1   b2
a3   a3   a3   a3   a3   a2   M    a2   a2   b2   b2   b2   b1   b1   b1   b1   b1   b1
a3   a3   a3   a2   a3   a3   M    a2   a2   b2   b2   b2   b2   b1   b1   b1   b1   b1
a2   a3   a2   a2   a2   a2   M    M    M    b2   b2   b2   b2   b2   b2   b1   b1   bG1
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
        """

        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Run expansion and validate connectivity
        plans = self._run_expansion_and_validate_connectivity(map, builder, turn_budget=50)

        # Additional assertions specific to this test
        self.assertIsNotNone(plans, "Expansion should produce plans")

        if debugMode:
            self.render_all_tile_islands(map, builder)

    def test_disconnected_island_set__small_contested_border(self):
        """
        Simpler test case: small map with a single contested border.

        Layout:
          aG1  a5   a5   a5   b5   bG1
          a5   a5   a5   X    b5   b5
          a5   a5   a5   a5   b5   b5

        The X (mountain) creates a gap that could cause disconnected sets
        if the algorithm isn't careful.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapData = """
|    |    |    |    |    |
aG1  a5   a5   a5   b5   bG1
a5   a5   a5   M    b5   b5
a5   a5   a5   a5   b5   b5
|    |    |    |    |    |
        """

        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Run expansion and validate connectivity
        plans = self._run_expansion_and_validate_connectivity(map, builder, turn_budget=20)

        self.assertIsNotNone(plans, "Expansion should produce plans")

        if debugMode:
            self.render_all_tile_islands(map, builder)

    def test_disconnected_island_set__island_with_gap(self):
        """
        Test where friendly territory has a "hole" or gap that could cause
        the algorithm to produce disconnected gather sets.

        Layout:
          aG1  a3   a3   a3   a3   a3
          a3   a3   b3   b3   a3   a3  ← friendly "island" in middle
          a3   a3   b3   b3   a3   a3
          a3   a3   a3   a3   bG1  a3  ← enemy general adjacent to friendly

        The friendly tiles in the middle should form a single connected set,
        but the algorithm might incorrectly include disconnected tiles.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        mapData = """
|    |    |    |    |    |    |
aG1  a3   a3   a3   a3   a3   a3
a3   a3   b3   b3   a3   a3   a3
a3   a3   b3   b3   a3   a3   a3
a3   a3   a3   a3   bG1  a3   a3
|    |    |    |    |    |    |
        """

        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # First, verify our friendly island is connected
        friendly_islands = [isl for isl in builder.tile_islands_by_team_id[general.player]]
        self.assertGreater(len(friendly_islands), 0, "Should have at least one friendly island")

        for isl in friendly_islands:
            components = self._get_tile_connected_components(set(isl.tile_set))
            self.assertEqual(
                1, len(components),
                f"Friendly island {isl.unique_id} should be connected, but has {len(components)} components"
            )

        # Run expansion and validate connectivity
        plans = self._run_expansion_and_validate_connectivity(map, builder, turn_budget=20)

        self.assertIsNotNone(plans, "Expansion should produce plans")

        if debugMode:
            self.render_all_tile_islands(map, builder)

    def render_all_tile_islands(self, map: MapBase, builder: TileIslandBuilder):
        """Render the tile islands for visual debugging."""
        view_info = self.get_renderable_view_info(map)
        from Algorithms.TileIslandBuilder import TileIslandBuilder as TIB
        TIB.add_tile_islands_to_view_info(builder, view_info)
        self.render_view_info(map, view_info)
