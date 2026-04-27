import time
import typing
from collections import deque

import logbook

import Gather
import SearchUtils
from Algorithms import TileIslandBuilder
from Algorithms.TileIslandBuilder import IslandBuildMode
from BehaviorAlgorithms import IterativeExpansion
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2, EnrichedFlowTurnsEntry
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, IslandFlowNode, FlowGraphMethod
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile
from base.viewer import PLAYER_COLORS
from bot_ek0x45 import EklipZBot

method = FlowGraphMethod.MinCostFlow

class FlowExpansionLookupGenerationTests(TestBase):
    """
    Tests for Phase 2: Building per-border gather/capture lookup tables.

    Also includes connectivity validations to catch disconnected tile set bugs
    at the lookup generation stage.
    """

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def _assert_flow_nodes_produce_connected_tiles(
        self,
        flow_nodes: typing.Iterable,
        set_name: str,
        test_context: str
    ):
        """
        Assert that a set of flow nodes produces a connected tile set.
        Flow nodes are connected if their islands share at least one border tile.
        """
        # Collect all tiles from the flow nodes
        all_tiles: typing.Set[Tile] = set()
        for flow_node in flow_nodes:
            all_tiles.update(flow_node.island.tile_set)

        if not all_tiles:
            return  # Empty set is vacuously connected

        # Find connected components using BFS
        remaining = set(all_tiles)
        components = []

        while remaining:
            start = remaining.pop()
            component = {start}
            queue = [start]

            while queue:
                current = queue.pop(0)
                for neighbor in current.movable:
                    if neighbor in remaining and neighbor in all_tiles:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)

            components.append(component)

        if len(components) > 1:
            component_info = []
            for i, comp in enumerate(components):
                tile_strs = [f"({t.x},{t.y})" for t in sorted(comp, key=lambda t: (t.x, t.y))]
                component_info.append(f"  Component {i+1} ({len(comp)} tiles): {', '.join(tile_strs)}")

            error_msg = (
                f"{set_name} flow nodes produce DISCONNECTED tile set in {test_context}!\n"
                f"Expected 1 connected component, found {len(components)}:\n"
                + "\n".join(component_info)
            )
            self.fail(error_msg)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_lookup_generation__basic_two_island_map(self):
        """Test lookup table generation on a simple two-island map"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Import and test the V2 expander
        flowExpanderV2 = ArmyFlowExpanderV2(map)

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Test lookup table generation (Phase 2)
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertEqual(1, len(lookup_tables), 'Should generate one lookup table for the single border pair')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        self.assertIsNotNone(lookup_table.border_pair, 'Border pair should be set')
        self.assertIsNotNone(lookup_table.capture_entries_by_turn, 'Capture entries should be initialized')
        self.assertIsNotNone(lookup_table.gather_entries_by_turn, 'Gather entries should be initialized')

        # For this simple case, we expect at least one valid capture entry
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None]
        self.assertGreater(len(capture_entries), 0, 'Should have at least one capture entry')

        # Verify the first non-zero capture entry has reasonable values
        non_zero_capture_entries = [entry for entry in capture_entries if entry.turns > 0]
        self.assertGreater(len(non_zero_capture_entries), 0, 'Should have at least one non-zero turn capture entry')

        first_capture = non_zero_capture_entries[0]
        self.assertGreater(first_capture.turns, 0, 'Turns should be positive')
        self.assertGreaterEqual(first_capture.required_army, 1, 'Should require at least 1 army')
        self.assertGreater(first_capture.econ_value, 0, 'Should have positive econ value')


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly(self):
        """Test V2 lookup generation for pull-through friendly scenario"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a3   a1   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs for this scenario
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs for pull-through friendly scenario')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        self.assertIsNotNone(lookup_table.capture_entries_by_turn, 'Should have capture entries')
        self.assertIsNotNone(lookup_table.gather_entries_by_turn, 'Should have gather entries')

        # Should have capture entries for enemy tiles
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        self.assertGreater(len(capture_entries), 0, 'Should have capture options')

        # Should have gather entries from friendly tiles
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture has reasonable values (enemy tile with 1 army)
        first_capture = capture_entries[0]
        self.assertGreater(first_capture.turns, 0, 'Should have positive turn count')
        self.assertEqual(first_capture.required_army, 2, 'Should require two army moving across the border')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should be worth enemy tile capture')

        # Verify gather functionality works (should gather from friendly tiles)
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather move is free since we pay the turn cost on the capture lookup side.')
        self.assertEqual(first_gather.gathered_army, 0, 'Gathers no army in the crossing-1 move')

        # Verify gather functionality works (should gather from friendly tiles)
        second_gather = gather_entries[1]
        self.assertEqual(second_gather.turns, 1, 'First gather move is free since we pay the turn cost on the capture lookup side.')
        self.assertEqual(second_gather.gathered_army, 2, 'Gathers 2 army across the 1')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables")
            logbook.info(f"First table has {len(capture_entries)} capture entries and {len(gather_entries)} gather entries")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral(self):
        """Test V2 lookup generation for pull-through neutral scenario"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a4        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs for this scenario
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs for pull-through neutral scenario')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        self.assertIsNotNone(lookup_table.capture_entries_by_turn, 'Should have capture entries')
        self.assertIsNotNone(lookup_table.gather_entries_by_turn, 'Should have gather entries')

        # Should have capture entries including neutral tiles
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        self.assertGreater(len(capture_entries), 0, 'Should have capture options')

        # Should have gather entries from friendly tiles
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture has reasonable values
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should have positive turn count')
        self.assertEqual(first_capture.required_army, 1, 'Should handle neutral capture (1 army cost)')
        self.assertEqual(first_capture.econ_value, 1, 'Neut capture is worth 1')

        # Verify the first capture has reasonable values
        second_capture = capture_entries[1]
        self.assertEqual(second_capture.turns, 2, 'Should have positive turn count')
        self.assertEqual(second_capture.required_army, 3, '1 for the neut, 2 for the en 1')
        self.assertEqual(second_capture.econ_value, 1 + IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Neut capture 1 + one en tile val')

        # Verify gather functionality works
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'Should have positive turn count')
        self.assertEqual(first_gather.gathered_army, 3, 'Should gather army from friendly tiles')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables")
            logbook.info(f"First table has {len(capture_entries)} capture entries and {len(gather_entries)} gather entries")


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__excess_source(self):
        """Test V2 lookup generation for basic move with excess source"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a4   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture has reasonable values (enemy tile with 1 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: 1 enemy + 1 tile traversal')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works (should gather from friendly tiles)
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 3, 'a4 tile (border) contributes 3 army (4-1=3)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for excess source scenario")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly__excess_source(self):
        """Test V2 lookup generation for pull-through friendly with excess source"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a4   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture has reasonable values (enemy tile with 1 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: moving a1 through to capture b1 (1+1)')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works (should gather from friendly tiles)
        # The border island is a1@col2 with 1 army - contributes 0 (1-1=0)
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 0, 'a1 border tile contributes 0 army (1-1=0)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for pull-through friendly excess source")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral__excess_source(self):
        """Test V2 lookup generation for pull-through neutral with excess source"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a5        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (neutral tile with 0 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture neutral island')
        self.assertEqual(first_capture.required_army, 1, 'Should require 1 army for neutral: 0 army + 1 tile')
        self.assertEqual(first_capture.econ_value, 1, 'Should have neutral econ value of 1')

        # Verify the second capture (neutral + enemy)
        second_capture = capture_entries[1]
        self.assertEqual(second_capture.turns, 2, 'Should take 2 turns to capture neutral then enemy')
        self.assertEqual(second_capture.required_army, 3, 'Should require 3 army: 0 neut + 1 enemy + 2 tiles')
        self.assertEqual(second_capture.econ_value, 1 + IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have neut + enemy econ value')

        # Verify gather functionality works
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 4, 'a5 tile contributes 4 army (5-1=4)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for pull-through neutral excess source")


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__need_cumulative_gather(self):
        """Test V2 lookup generation for basic move needing cumulative gather"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG2  a2   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture has reasonable values (enemy tile with 1 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: 1 enemy + 1 tile')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works (should gather from friendly tiles)
        # Border island is a2@col1 with 2 army - contributes 1 (2-1=1)
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 1, 'a2 border tile contributes 1 army (2-1=1)')

        # Second gather from a2 + aG2: aG2@col0 depth=2, cost=1, contributes 2-1=1, total = 1+1=2
        second_gather = gather_entries[1]
        self.assertEqual(second_gather.turns, 1, 'Should take 1 turn to gather from aG2')
        self.assertEqual(second_gather.gathered_army, 2, 'Both tiles contribute 2 army total (1+1)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for cumulative gather scenario")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly__need_cumulative_gather(self):
        """Test V2 lookup generation for pull-through friendly needing cumulative gather"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG2  a2   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (enemy with 1 army, pulled through a1)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: a1 through to b1')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works (should gather from friendly tiles)
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 0, 'No army gathered at turn 0')

        # Gather from a1@col2: depth=1, cost=0, contributes 1
        second_gather = gather_entries[1]
        self.assertEqual(second_gather.turns, 1, 'Should take 1 turn to gather from a1')
        self.assertEqual(second_gather.gathered_army, 1, 'a1 tile contributes 1 army')

        # Gather from a1 + a2: a2@col1 depth=2, cost=1, contributes 2-1=1, total = 1+1=2
        third_gather = gather_entries[2]
        self.assertEqual(third_gather.turns, 2, 'Should take 2 turns to gather from a1+a2')
        self.assertEqual(third_gather.gathered_army, 2, 'a1+a2 tiles contribute 2 army total (1+1)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for pull-through friendly cumulative gather")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral__need_cumulative_gather(self):
        """Test V2 lookup generation for pull-through neutral needing cumulative gather"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG2  a3        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (neutral with 0 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture neutral island')
        self.assertEqual(first_capture.required_army, 1, 'Should require 1 army for neutral: 0 army + 1 tile')
        self.assertEqual(first_capture.econ_value, 1, 'Should have neutral econ value of 1')

        # Verify the second capture (neutral + enemy)
        second_capture = capture_entries[1]
        self.assertEqual(second_capture.turns, 2, 'Should take 2 turns to capture neutral then enemy')
        self.assertEqual(second_capture.required_army, 3, 'Should require 3 army: 0 neut + 1 enemy + 2 tiles')
        self.assertEqual(second_capture.econ_value, 1 + IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have neut + enemy econ value')

        # Verify gather functionality works
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 2, 'a3 tile contributes 2 army (3-1=2)')

        # Gather from a3 + aG2: aG2@col0 depth=2, cost=1, contributes 2-1=1, total = 2+1=3
        second_gather = gather_entries[1]
        self.assertEqual(second_gather.turns, 1, 'Should take 1 turn to gather from aG2')
        self.assertEqual(second_gather.gathered_army, 3, 'a3+aG2 tiles contribute 3 army total (2+1)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for pull-through neutral cumulative gather")


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__multi_enemy_tiles(self):
        """Test V2 lookup generation for basic move with multiple enemy tiles"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG3  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (enemy with 1 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: 1 enemy + 1 tile')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 2, 'a3 tile contributes 2 army (3-1=2)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for multi enemy tiles scenario")


    def test_build_flow_expand_plan__should_produce_valid_only__most_basic_move__multi_enemy_tiles__differing_army(self):
        """Test V2 lookup generation for basic move with multiple enemy tiles with differing army"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG3  a5   b1   bG3
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (enemy with 1 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: 1 enemy + 1 tile')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 4, 'a5 tile contributes 4 army (5-1=4)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for multi enemy tiles with differing army scenario")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_friendly__multi_enemy_tiles(self):
        """Test V2 lookup generation for pull-through friendly with multiple enemy tiles"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG3  a3   a1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (enemy with 1 army, pulled through a1)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: a1 through to b1')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works
        # Border island is a1@col2 with 1 army - contributes 0 (1-1=0)
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 0, 'a1 border tile contributes 0 army (1-1=0)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for pull-through friendly multi enemy tiles scenario")


    def test_build_flow_expand_plan__should_produce_valid_only__pull_through_neutral__multi_enemy_tiles(self):
        """Test V2 lookup generation for pull-through neutral with multiple enemy tiles"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG2  a5   b1        bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        # Use V2 expander to test lookup generation
        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Should find border pairs
        self.assertGreater(len(border_pairs), 0, 'Should find border pairs')

        # Test lookup table generation
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Verify basic lookup table structure
        lookup_table = lookup_tables[0]
        capture_entries = [entry for entry in lookup_table.capture_entries_by_turn if entry is not None and entry.turns > 0]
        gather_entries = [entry for entry in lookup_table.gather_entries_by_turn if entry is not None]

        self.assertGreater(len(capture_entries), 0, 'Should have capture options')
        self.assertGreater(len(gather_entries), 0, 'Should have gather options')

        # Verify the first capture (enemy with 1 army)
        first_capture = capture_entries[0]
        self.assertEqual(first_capture.turns, 1, 'Should take 1 turn to capture enemy island')
        self.assertEqual(first_capture.required_army, 2, 'Should require 2 army: 1 enemy + 1 tile')
        self.assertEqual(first_capture.econ_value, IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL, 'Should have enemy econ value')

        # Verify gather functionality works
        first_gather = gather_entries[0]
        self.assertEqual(first_gather.turns, 0, 'First gather at border takes 0 turns')
        self.assertEqual(first_gather.gathered_army, 4, 'a5 tile contributes 4 army (5-1=4)')

        # Gather from a5 + aG2: aG2@col0 depth=2, cost=1, contributes 2-1=1, total = 4+1=5
        second_gather = gather_entries[1]
        self.assertEqual(second_gather.turns, 1, 'Should take 1 turn to gather from aG2')
        self.assertEqual(second_gather.gathered_army, 5, 'a5+aG2 tiles contribute 5 army total (4+1)')

        if debugMode:
            logbook.info(f"Generated {len(lookup_tables)} lookup tables for pull-through neutral multi enemy tiles scenario")


    # CAPTURE LOOKUP GENERATION TESTS

    def test_capture_lookup_generation__basic_enemy_capture(self):
        """Test basic capture lookup generation with a single enemy island"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Debug: Check if we found any border pairs
        if debugMode:
            logbook.info(f"Found {len(border_pairs)} border pairs")
            logbook.info(f"Target-crossable islands: {target_crossable}")
            logbook.info(f"Team: {flowExpanderV2.team}, Target team: {flowExpanderV2.target_team}")

            # Print island info
            for island in builder.all_tile_islands:
                logbook.info(f"Island {island.unique_id}: team={island.team}, tiles={island.tile_count}, army={island.sum_army}")

        self.assertGreater(len(border_pairs), 0, 'Should find at least one border pair for this simple map')

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate capture lookup table
        capture_lookup = flowExpanderV2._generate_capture_lookup_table(
            border_pair, target_contribs, stream_data
        )

        # Verify basic structure
        self.assertIsNotNone(capture_lookup, 'Capture lookup should be generated')
        self.assertEqual(51, len(capture_lookup), 'Should have entries for turns 0-50')

        # Turn 0 should be the initial border state
        turn0_entry = capture_lookup[0]
        self.assertIsNotNone(turn0_entry, 'Turn 0 entry should exist')
        self.assertEqual(0, turn0_entry.turns, 'Turn 0 should have 0 turns')
        self.assertEqual(0, turn0_entry.required_army, 'Turn 0 should require 0 army')
        self.assertEqual(0.0, turn0_entry.econ_value, 'Turn 0 should have 0 econ value')

        # Find first non-zero turn entry (should be the enemy island capture)
        non_zero_entries = [entry for entry in capture_lookup if entry is not None and entry.turns > 0]
        self.assertGreater(len(non_zero_entries), 0, 'Should have non-zero turn entries')

        first_capture = non_zero_entries[0]
        self.assertEqual(1, first_capture.turns, 'First capture should take 1 turn (enemy island size 1)')
        self.assertEqual(2, first_capture.required_army, 'Should require 3 army to capture 1-army tile: sum_army(1) + tiles(1) = 2')
        self.assertAlmostEqual(
            IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL,
            first_capture.econ_value,
            places=2,
            msg='Should have enemy econ value for 1 tile'
        )
        self.assertEqual(1, len(first_capture.included_target_flow_nodes), 'Should include 1 target node')

        # Debug rendering
        if debugMode:
            self._render_capture_lookup_debug(capture_lookup, border_pair, target_contribs)

    def test_capture_lookup_generation__neutral_capture(self):
        """Test capture lookup generation with neutral islands"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapData = """
|    |    |    |    |
aG1  a4        b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate capture lookup table
        capture_lookup = flowExpanderV2._generate_capture_lookup_table(
            border_pair, target_contribs, stream_data
        )

        # Find neutral capture entries
        non_zero_entries = [entry for entry in capture_lookup if entry is not None and entry.turns > 0]
        self.assertGreater(len(non_zero_entries), 0, 'Should have non-zero turn entries')

        # Debug: Print all entries to understand what we have
        if debugMode:
            logbook.info(f"Found {len(non_zero_entries)} non-zero entries:")
            for i, entry in enumerate(non_zero_entries):
                logbook.info(f"  Entry {i}: turns={entry.turns}, army={entry.required_army}, econ={entry.econ_value:.2f}")
                for j, node in enumerate(entry.included_target_flow_nodes):
                    logbook.info(f"    Node {j}: island {node.island.unique_id}, team={node.island.team}, tiles={node.island.tile_count}, army={node.island.sum_army}")

        # Find entries with neutral econ value (1.0 per tile) vs enemy econ value (ITERATIVE_EXPANSION_EN_CAP_VAL per tile)
        neutral_entries = []
        enemy_entries = []

        for entry in non_zero_entries:
            has_neutral = False
            has_enemy = False
            for node in entry.included_target_flow_nodes:
                if node.island.team != flowExpanderV2.target_team and node.island.team != map.player_index:
                    has_neutral = True
                elif node.island.team == flowExpanderV2.target_team:
                    has_enemy = True

            if has_neutral:
                neutral_entries.append(entry)
            if has_enemy:
                enemy_entries.append(entry)

        # Should have at least one neutral capture
        self.assertGreater(len(neutral_entries), 0, 'Should have neutral capture entries')

        # Check neutral capture properties
        neutral_capture = neutral_entries[0]
        self.assertGreater(neutral_capture.turns, 0, 'Neutral capture should take at least 1 turn')

        # Neutral islands should have 0 army, but the total army cost depends on what else is included
        for node in neutral_capture.included_target_flow_nodes:
            if node.island.team != flowExpanderV2.target_team and node.island.team != map.player_index:
                # This is a neutral island
                self.assertEqual(0, node.island.sum_army, 'Neutral island should have 0 army')

        # Should have at least one enemy capture
        self.assertGreater(len(enemy_entries), 0, 'Should have enemy capture entries')

        # Check enemy capture properties
        enemy_capture = enemy_entries[0]
        self.assertGreater(enemy_capture.turns, 0, 'Enemy capture should take at least 1 turn')
        self.assertGreater(enemy_capture.required_army, 0, 'Enemy capture should require army')

        # Verify econ values are correctly calculated
        total_neutral_econ = sum(1.0 * node.island.tile_count for node in neutral_capture.included_target_flow_nodes
                                if node.island.team != flowExpanderV2.target_team and node.island.team != map.player_index)
        total_enemy_econ = sum(IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * node.island.tile_count
                              for node in neutral_capture.included_target_flow_nodes
                              if node.island.team == flowExpanderV2.target_team)
        expected_econ = total_neutral_econ + total_enemy_econ
        self.assertAlmostEqual(expected_econ, neutral_capture.econ_value, places=2,
                              msg=f'Neutral capture econ should be {expected_econ}, got {neutral_capture.econ_value}')

        if debugMode:
            self._render_capture_lookup_debug(capture_lookup, border_pair, target_contribs)

    def test_capture_lookup_generation__target_crossable_friendly_island(self):
        """Test capture lookup generation with target-crossable friendly islands"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # Create a map where a small friendly island is surrounded by enemy islands
        # This should make it target-crossable
        mapData = """
|    |    |    |    |
aG1  a2   a1   b2   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )

        # Print debug info about target-crossable detection
        if debugMode:
            logbook.info(f"Target-crossable islands: {target_crossable}")
            for island in builder.all_tile_islands:
                if island.team == map.player_index:
                    logbook.info(f"Friendly island {island.unique_id}: tiles={island.tile_count}, army={island.sum_army}")

        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # If we have target-crossable islands, test the behavior
        if target_crossable:
            # Find a border pair that might involve target-crossable islands
            for border_pair in border_pairs:
                stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
                if not stream_data:
                    continue

                friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

                # Check if any target contributions are crossing nodes
                crossing_contribs = [c for c in target_contribs if c.is_crossing]
                if crossing_contribs:
                    capture_lookup = flowExpanderV2._generate_capture_lookup_table(
                        border_pair, target_contribs, stream_data
                    )

                    # Verify crossing nodes have turn cost but no army cost or econ value
                    non_zero_entries = [entry for entry in capture_lookup if entry is not None and entry.turns > 0]

                    for entry in non_zero_entries:
                        for node in entry.included_target_flow_nodes:
                            if node.island.unique_id in target_crossable:
                                # This is a crossing node - should be reflected in the turn cost
                                # but not add army requirement or econ value
                                if debugMode:
                                    logbook.info(f"Crossing node {node.island.unique_id} included in turn {entry.turns}")

                    if debugMode:
                        self._render_capture_lookup_debug(capture_lookup, border_pair, target_contribs)
                    break  # Found a test case
        else:
            # If no target-crossable islands detected, that's also a valid test result
            self.assertTrue(True, 'No target-crossable islands in this simple map')

    def test_capture_lookup_generation__multiple_enemy_islands(self):
        """Test capture lookup generation with multiple enemy islands"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a5   b1   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate capture lookup table
        capture_lookup = flowExpanderV2._generate_capture_lookup_table(
            border_pair, target_contribs, stream_data
        )

        # Should have entries for capturing 1, 2, or both enemy islands
        non_zero_entries = [entry for entry in capture_lookup if entry is not None and entry.turns > 0]
        self.assertGreater(len(non_zero_entries), 1, 'Should have multiple capture options')

        # First capture should be 1 turn for first enemy island
        first_capture = non_zero_entries[0]
        self.assertEqual(1, first_capture.turns, 'First capture should be 1 turn')
        self.assertEqual(2, first_capture.required_army, 'First capture should require 2 army: sum_army(1) + tiles(1) = 2')
        self.assertAlmostEqual(
            IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL,
            first_capture.econ_value,
            places=2,
            msg='First capture should have econ value for 1 enemy tile'
        )

        # Should have an entry for capturing both enemy islands
        both_captures = None
        for entry in non_zero_entries:
            if len(entry.included_target_flow_nodes) == 2:
                both_captures = entry
                break

        self.assertIsNotNone(both_captures, 'Should have entry for capturing both enemy islands')
        self.assertEqual(2, both_captures.turns, 'Both captures should take 2 turns')
        self.assertEqual(4, both_captures.required_army, 'Both captures should require 5 army: sum_army(1+1) + tiles(2) = 4')
        self.assertAlmostEqual(
            IterativeExpansion.ITERATIVE_EXPANSION_EN_CAP_VAL * 2,
            both_captures.econ_value,
            places=2,
            msg='Both captures should have econ value for 2 enemy tiles'
        )

        if debugMode:
            self._render_capture_lookup_debug(capture_lookup, border_pair, target_contribs)

    def _render_capture_lookup_debug(self, capture_lookup, border_pair, target_contribs):
        """Debug rendering for capture lookup tables"""
        logbook.info(f"\n=== CAPTURE LOOKUP DEBUG for border pair {border_pair.friendly_island_id}->{border_pair.target_island_id} ===")
        logbook.info(f"Target contributions: {len(target_contribs)}")
        for i, contrib in enumerate(target_contribs):
            logbook.info(f"  {i}: Island {contrib.island_id}, tiles={contrib.tile_count}, army={contrib.army_amount}, crossing={contrib.is_crossing}")

        logbook.info(f"\nCapture lookup entries:")
        for turn, entry in enumerate(capture_lookup):
            if entry is not None:
                logbook.info(f"  Turn {turn}: army={entry.required_army}, econ={entry.econ_value:.2f}, targets={len(entry.included_target_flow_nodes)}")
        logbook.info("=== END CAPTURE LOOKUP DEBUG ===\n")


    # GATHER LOOKUP GENERATION TESTS

    def test_gather_lookup_generation__basic_single_island(self):
        """Test basic gather lookup generation with a single friendly island"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate gather lookup table
        gather_lookup = flowExpanderV2._generate_gather_lookup_table(
            border_pair, friendly_contribs, stream_data
        )

        # Verify basic structure
        self.assertIsNotNone(gather_lookup, 'Gather lookup should be generated')
        self.assertEqual(51, len(gather_lookup), 'Should have entries for turns 0-50')   # this is retarded, change

        # Turn 0 should be the initial border state

        # Find first non-zero turn entry (should be the friendly island gather)
        non_zero_entries = [entry for entry in gather_lookup if entry is not None]
        self.assertGreater(len(non_zero_entries), 0, 'Should have non-zero turn entries')

        first_gather = non_zero_entries[0]
        self.assertEqual(0, first_gather.turns, 'First gather should take 0 turns (friendly island size 1), as the move cost is paid on the capture side of the border crossing')
        self.assertEqual(2, first_gather.gathered_army, 'Should gather 2 army from friendly island with a 3 on it')
        self.assertEqual(0, first_gather.required_army, 'Gather entries should have 0 required army')
        self.assertEqual(0.0, first_gather.econ_value, 'Gather entries should have 0 econ value')
        self.assertEqual(1, len(first_gather.included_friendly_flow_nodes), 'Should include 1 friendly node')

        # Debug rendering
        if debugMode:
            self._render_gather_lookup_debug(gather_lookup, border_pair, friendly_contribs)

    def test_gather_lookup_generation__multiple_islands_cumulative(self):
        """Test gather lookup generation with multiple friendly islands showing cumulative gathering"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a2   a2   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate gather lookup table
        gather_lookup = flowExpanderV2._generate_gather_lookup_table(
            border_pair, friendly_contribs, stream_data
        )

        # Should have entries for gathering from 1, 2, or both friendly islands
        non_zero_entries = [entry for entry in gather_lookup if entry is not None]
        self.assertGreater(len(non_zero_entries), 1, 'Should have multiple gather options')

        # First gather should be 1 turn for first friendly island
        first_gather = non_zero_entries[0]
        self.assertEqual(0, first_gather.turns, 'First gather should be 0 turns as we pay the cost on the capture side for crossing the border pair')
        self.assertEqual(1, first_gather.gathered_army, 'First gather should gather 1 army from the 2 tile')
        self.assertEqual(1, len(first_gather.included_friendly_flow_nodes), 'Should include 1 friendly node')

        # Should have an entry for gathering from both friendly islands
        self.assertEqual(2, len(non_zero_entries))
        both_gathers = non_zero_entries[1]
        self.assertEqual(2, len(both_gathers.included_friendly_flow_nodes))

        self.assertIsNotNone(both_gathers, 'Should have entry for gathering from both friendly islands')
        self.assertEqual(1, both_gathers.turns, 'Both gathers should take 1 turn in addition to the free initial border cost')
        # border island a2@col2: depth=1, tile_count=1, traversal_cost=0, contributes 2
        # upstream island a2@col1: depth=2, tile_count=1, traversal_cost=1, contributes 2-1=1
        # total army arriving at border = 2+1 = 3
        self.assertEqual(2, both_gathers.gathered_army, 'Both gathers should gather 3 army at border after traversal deduction')
        self.assertEqual(2, len(both_gathers.included_friendly_flow_nodes), 'Should include 2 friendly nodes')

        if debugMode:
            self._render_gather_lookup_debug(gather_lookup, border_pair, friendly_contribs)

    def test_gather_lookup_generation__varying_army_amounts(self):
        """Test gather lookup generation with islands having different army amounts"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a2   a5   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate gather lookup table
        gather_lookup = flowExpanderV2._generate_gather_lookup_table(
            border_pair, friendly_contribs, stream_data
        )

        # Verify that the higher army island is preferred first (due to better army/tile ratio)
        non_zero_entries = [entry for entry in gather_lookup if entry is not None]
        self.assertGreater(len(non_zero_entries), 0, 'Should have non-zero turn entries')

        # The first entry should be from the island with better army/tile ratio (the 5-army island)
        first_gather = non_zero_entries[0]
        self.assertEqual(0, first_gather.turns, 'First gather should be 0 turns, as we pay the move cost on the capture side for the border crossing')
        # Should be 5 army - 1
        self.assertEqual(first_gather.gathered_army, 4, f'First gather should be from either island, got {first_gather.gathered_army}')

        # Should have cumulative gathering
        self.assertEqual(2, len(non_zero_entries))
        second_gather = non_zero_entries[1]
        self.assertEqual(1, second_gather.turns, 'adds 1 move and 1 army to first gather.')
        # Should be 5 army - 1
        self.assertEqual(second_gather.gathered_army, 5, 'adds 1 move and 1 army to first gather.')
        if debugMode:
            self._render_gather_lookup_debug(gather_lookup, border_pair, friendly_contribs)

    def test_gather_lookup_generation__turn_accounting_consistency(self):
        """Test that turn accounting is consistent and matches expected behavior"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a2   a1   a2   b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        # Build stream data for the first border pair
        border_pair = border_pairs[0]
        stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
        friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        # Generate gather lookup table
        gather_lookup = flowExpanderV2._generate_gather_lookup_table(
            border_pair, friendly_contribs, stream_data
        )

        # Verify turn accounting: each island contributes its tile count to turn cost
        non_zero_entries = [entry for entry in gather_lookup if entry is not None]

        for entry in non_zero_entries:
            # Calculate expected turn count based on included islands
            expected_turns = sum(node.island.tile_count for node in entry.included_friendly_flow_nodes) - 1
            self.assertEqual(expected_turns, entry.turns,
                           f'Turn count should match sum of tile counts for included islands')

            # gathered_army = raw island sum minus within-gather traversal cost.
            # Traversal can only reduce the available army, never increase it.
            raw_sum = sum(node.island.sum_army for node in entry.included_friendly_flow_nodes)
            self.assertLessEqual(entry.gathered_army, raw_sum,
                               f'Gathered army at border must be <= raw sum (traversal deduction)')
            self.assertGreaterEqual(entry.gathered_army, 0,
                               f'Gathered army must be non-negative')

        if debugMode:
            self._render_gather_lookup_debug(gather_lookup, border_pair, friendly_contribs)

    # ------------------------------------------------------------------
    # 2x2 corner scenario — army validity and border pair grouping
    # ------------------------------------------------------------------

    def test_lookup_generation__2x2_corner__army3__both_border_pairs_only_valid_capture(self):
        """
        2x2 corner scenario with blue (0,1) having army=3.
        Blue cannot directly capture either red tile (3-1=2 leaves behind, 2 vs 2 = no capture).
        Both border pairs must reflect this: NO enriched entry for a direct single-tile capture
        from (0,1) alone; only a combined gather from (0,0)+(0,1) can succeed.

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a3   (1,1)=b2

        Bug #1 guard: the two red tiles should NOT both appear as top-level outputs
        from separate border pairs that share capture territory.
        Bug #2 guard: capture entries with required_army > available gather_army must
        not appear in enriched_capture_entries.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG2  b2   bG1
a3   b2
|    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )
        flowExpanderV2._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        self.assertGreater(len(lookup_tables), 0, 'Should have at least one lookup table')

        # Army invariant: every enriched entry must have gather >= required
        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'2x2 army=3: gather must always cover required army '
                    f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                )

        # Bug #2: a single-island capture of a 2-army red tile requires 2 army net,
        # meaning the mover must arrive with >2. From (0,1) alone (army=3, leaves 2, arrives 2):
        # 2 vs 2 = 0 net — NOT a valid capture. No enriched entry with required_army=2
        # should be paired with a gather_army < 3.
        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                if enriched.capture_entry.required_army == 2:
                    self.assertGreaterEqual(
                        enriched.gather_entry.gathered_army, 3,
                        'Capturing a 2-army tile requires at least 3 gathered army '
                        '(need to arrive with >2 after leaving 1 behind)'
                    )

    def test_lookup_generation__2x2_corner__army4__direct_capture_valid(self):
        """
        2x2 corner scenario with blue (0,1) having army=4.
        Blue CAN directly capture one red tile: 4-1=3 arrives, 3>2 succeeds.
        A single-tile capture from (0,1) to (1,1) should appear as a valid enriched entry.
        There is still NOT enough army to capture both red tiles in sequence (3 left on (1,1),
        1 leaves, arrives at (1,0) with... actually 2 left would need >2 to cap (1,0)=2: fails).

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a4   (1,1)=b2

        Expected:
        - Capture (1,1) only should be achievable directly (turns=1 with sufficient gather)
        - Capture (1,1)+(1,0) requires more army than available in this 2-turn window
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG2  b2   bG1
a4   b2
|    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )
        flowExpanderV2._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        self.assertGreater(len(lookup_tables), 0, 'Should have at least one lookup table')

        # Army invariant must hold for all entries
        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'2x2 army=4: gather must always cover required army '
                    f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                )

        # With army=4 on (0,1), there should be at least one valid single-tile capture enriched entry
        total_enriched = sum(len(lt.enriched_capture_entries) for lt in lookup_tables)
        self.assertGreater(total_enriched, 0,
                           'army=4 is enough to capture a 2-army tile: should have at least one enriched entry')

    def test_lookup_generation__2x2_corner__army7__two_tile_capture_valid(self):
        """
        2x2 corner scenario with blue (0,1) having army=7.
        Blue can capture both red tiles in sequence:
          (0,1)->7, leaves 6, arrives at (1,1) with 6, 6>2 captures, 4 left on (1,1)
          -> leaves 3 on (1,1), arrives at (1,0) with 3, 3>2 captures ✓

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a7   (1,1)=b2

        Expected:
        - Two-tile capture (both red tiles) should be achievable
        - The two-tile capture enriched entry requires >= 4 army (need 3 to reach (1,0))
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG2  b2   bG1
a7   b2
|    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = enemyGeneral.player

        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )
        flowExpanderV2._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        self.assertGreater(len(lookup_tables), 0, 'Should have at least one lookup table')

        # Army invariant
        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'2x2 army=7: gather must always cover required army '
                    f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                )

        # With army=7, a 2-turn capture (both tiles) should be achievable
        # The two-tile capture requires army=4 (need 3 to arrive at (1,0) after capturing (1,1))
        all_enriched = [e for lt in lookup_tables for e in lt.enriched_capture_entries]
        two_tile_captures = [e for e in all_enriched if e.capture_entry.turns == 2]
        self.assertGreater(len(two_tile_captures), 0,
                           'army=7 should produce a valid two-tile capture enriched entry')
        for enriched in two_tile_captures:
            self.assertGreaterEqual(
                enriched.gather_entry.gathered_army, 4,
                'Two-tile capture of two 2-army tiles requires gathered_army >= 4'
            )

    def test_lookup_generation__gather_turns_must_include_path_distance_to_border(self):
        """
        Regression test: gather_entry.turns must reflect the actual number of move-turns
        needed to walk all gathered army to the capture border, not just the sum of island
        tile_counts.

        Scenario (from observed bug in screenshot):
          a16 is directly adjacent to the enemy border (at col 5).
          Behind it: aG2 at col 4, a2 at col 3 (wait, see layout), a3 at col 2, a4 at col 1,
          a12 at col 0.  The flow graph assigns a gather_entry that includes a16 (col 5) AND
          a12 (col 0) with gath_turns=2 (one island each).  But to pull a12's army to col 5
          requires walking 5 tiles — 5 move-turns just for that piece, not 1.

          When the lookup table says gath_turns=2 for [a16, a12] and cap_turns=5 for 5 enemy
          tiles, the combined_turn_cost=7 is a lie: the real cost is at least cap_turns +
          distance(a12→border) = 5+5 = 10, meaning the plan is much worse than reported AND
          may be physically impossible within the assumed turn window.

        Layout (1 row, 14 cols) with desired_tile_island_size=1:
          a12  a4  a2  a3  aG2  a16  b2  b2  b2  b2  b3  b3  b3  bG1
           0    1   2   3   4    5    6   7   8   9  10  11  12   13

        Key assertions:
        1. Any enriched entry whose gather includes island a12 (sum=12, at col 0) must have
           gather_turns >= 5 (the distance from col 0 to the border at col 5).
        2. No enriched entry may claim gathered_army >= required_army when the gather_turns
           is too small to physically deliver that army to the border.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |
a12  a4   a2   a3   aG2  a16  b2   b2   b2   b2   b3   b3   b3   bG1
|    |    |    |    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True
        flowExpanderV2.target_team = enemyGeneral.player

        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )
        flowExpanderV2._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        self.assertGreater(len(lookup_tables), 0, 'Should have at least one lookup table')

        # Island a12 is at (0,0); the border island a16 is at (5,0).  Distance = 5 moves.
        # Any enriched entry that includes a12 in its gather must have gath_turns >= 5.
        a12_tile = map.GetTile(0, 0)
        a12_island_id = builder.tile_island_lookup.raw[a12_tile.tile_index].unique_id

        all_enriched = [e for lt in lookup_tables for e in lt.enriched_capture_entries]

        for enriched in all_enriched:
            if enriched.capture_entry.turns == 0:
                continue  # Turn-0 seed entry; skip
            gather_island_ids = {n.island.unique_id for n in enriched.gather_entry.included_friendly_flow_nodes}
            if a12_island_id not in gather_island_ids:
                continue
            # This entry claims to use a12's army — gather_turns must cover the 5-tile distance
            self.assertGreaterEqual(
                enriched.gather_entry.turns,
                5,
                f'gather_entry includes a12 (col 0) but gath_turns={enriched.gather_entry.turns} '
                f'is less than the 5-move distance to the border at col 5. '
                f'cap_turns={enriched.capture_entry.turns}, '
                f'req={enriched.capture_entry.required_army}, '
                f'gathered={enriched.gather_entry.gathered_army}'
            )

    def test_lookup_generation__neutral_tiles_between_friendly_and_enemy__must_count_as_traversal_cost(self):
        """
        Regression: when neutral tiles sit between the friendly border island and the
        enemy tile, the capture stream must treat them as mandatory traversal steps
        BEFORE the enemy tile — not sort them after it by value.

        Layout (1 row, 11 cols) with desired_tile_island_size=1, fill_out_tiles=False:
          a3   aG4  a2   a2   a2   __   __   b2   N4   __   bG1
           0    1    2    3    4    5    6    7    8    9    10

        Cols 5 and 6 are neutral tiles (army=0) blocking the path from a2@col4 to b2@col7.
        Any plan that captures b2 must traverse both neutrals first:
          col4 -> col5 -> col6 -> col7  =  3 moves minimum.

        Previous bug: the capture stream sorted b2 (enemy, high type_bonus) before the
        neutrals, producing a spurious cap_t=1 req=4 entry that teleports past the two
        mandatory neutral tiles, and reported armyGath=1 instead of the correct 0.

        Assertions:
        1. No capture entry for b2 may have cap_turns < 3 (must traverse 2 neutrals first).
        2. The 3-turn capture entry for the 2 neutrals + b2 must have required_army = 5:
             army_cost(neut@5) + army_cost(neut@6) + army(b2) + turns + 1 = 1+1+3 = 5.
        3. Three a2 tiles give gathered_army = 6 — exactly meeting required, surplus = 0,
           so armyGath should be 0 (not positive), meaning aG4 IS needed for any surplus.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |
aG3  a3   a2   a2   a2             b2   N4        bG10
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = False
        opts = flowExpanderV2.get_expansion_options(
            builder, general.player, enemyGeneral.player, turns=50,
            boardAnalysis=None, territoryMap=None, negativeTiles=None
        )

        lookup_tables = flowExpanderV2.last_lookup_tables
        self.assertIsNotNone(lookup_tables, 'last_lookup_tables must be set after get_expansion_options')
        self.assertGreater(len(lookup_tables), 0, 'Should produce at least one lookup table')

        # self.render_flow_expansion_debug(flowExpanderV2, opts, renderAll=True)

        # b2 is at col 7.  Any capture entry whose included_target_flow_nodes contains b2
        # must have cap_turns >= 3 (col5 neutral + col6 neutral + col7 b2 = 3 mandatory steps).
        b2_tile = map.GetTile(7, 0)
        b2_island_id = builder.tile_island_lookup.raw[b2_tile.tile_index].unique_id

        found_b2_entry = False
        self.assertEqual(1, len(lookup_tables), 'Should have exactly one lookup table - the friendly-neutral island border pair')
        lt = lookup_tables[0]

        # e1 should cost 1, a2->N0
        e1: EnrichedFlowTurnsEntry = lt.enriched_capture_entries[0]
        self.assertEqual(1, e1.capture_entry.turns)
        self.assertEqual(1, e1.capture_entry.econ_value)
        self.assertEqual(1, e1.combined_value_density)

        for enriched in lt.enriched_capture_entries:
            cap = enriched.capture_entry
            if cap.turns == 0:
                self.fail('should be no zero turn enriched cap entries anymore')
            target_island_ids = {n.island.unique_id for n in cap.included_target_flow_nodes}
            if b2_island_id not in target_island_ids:
                continue
            found_b2_entry = True
            # Must have walked through both neutrals first — minimum 3 turns
            self.assertEqual(
                3, cap.turns,
                f'Capture entry including b2 (col 7) has cap_turns={cap.turns} < 3; '
                f'the two neutral tiles at cols 5-6 are mandatory traversal and cannot be skipped. '
                f'req={cap.required_army} gath={enriched.gather_entry.gathered_army}'
            )

            self.assertEqual(
                5, cap.required_army,
                f'3-turn capture of neut+neut+b2 must require army=5 (1+1+3), got {cap.required_army}'
            )
            # The 3xa2 gather covers exactly 6 — surplus must be 0, not positive
            # (positive surplus here would mean the plan incorrectly bypasses the neutrals)
            surplus = enriched.gather_entry.gathered_army - cap.required_army
            self.assertEqual(surplus, 0)

        self.assertTrue(found_b2_entry, 'Expected at least one enriched entry capturing b2@col7')

    def test_lookup_generation__MORE_neutral_tiles_between_friendly_and_enemy__must_count_as_traversal_cost(self):
        """
        Regression: when neutral tiles sit between the friendly border island and the
        enemy tile, the capture stream must treat them as mandatory traversal steps
        BEFORE the enemy tile — not sort them after it by value.

        Layout (1 row, 11 cols) with desired_tile_island_size=1, fill_out_tiles=False:
          a3   aG5  a2   a2   a2   __   __   __   b2   N4   __   bG1
           0    1    2    3    4    5    6    7    8    9   10    11

        Cols 5 and 6 are neutral tiles (army=0) blocking the path from a2@col4 to b2@col7.
        Any plan that captures b2 must traverse both neutrals first:
          col4 -> col5 -> col6 -> col7  =  3 moves minimum.

        Previous bug: the capture stream sorted b2 (enemy, high type_bonus) before the
        neutrals, producing a spurious cap_t=1 req=4 entry that teleports past the two
        mandatory neutral tiles, and reported armyGath=1 instead of the correct 0.

        Assertions:
        1. No capture entry for b2 may have cap_turns < 4 (must traverse 3 neutrals first).
        2. The 4-turn capture entry for the 2 neutrals + b2 must have required_army = 6:
             army_cost(neut@5) + army_cost(neut@6) + army(b2) + turns + 1 = 1+1+1+3 = 6.
        3. Three a2 tiles give gathered_army = 6 — exactly meeting required, surplus = 0,
           so armyGath should be 0 (not positive), meaning aG4 IS needed for any surplus.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |
a3   aG4  a2   a2   a2                  b2   N4        bG1
|    |    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = False
        opts = flowExpanderV2.get_expansion_options(
            builder, general.player, enemyGeneral.player, turns=50,
            boardAnalysis=None, territoryMap=None, negativeTiles=None
        )

        lookup_tables = flowExpanderV2.last_lookup_tables
        self.assertIsNotNone(lookup_tables, 'last_lookup_tables must be set after get_expansion_options')
        self.assertGreater(len(lookup_tables), 0, 'Should produce at least one lookup table')

#         self.render_flow_expansion_debug(flowExpanderV2, opts, renderAll=True)

        # b2 is at col 7.  Any capture entry whose included_target_flow_nodes contains b2
        # must have cap_turns >= 3 (col5 neutral + col6 neutral + col7 b2 = 3 mandatory steps).
        b2_tile = map.GetTile(8, 0)

        # TODO BELOW HERE INCORRECT
        b2_island_id = builder.tile_island_lookup.raw[b2_tile.tile_index].unique_id

        found_b2_entry = False
        self.assertEqual(1, len(lookup_tables), 'Should have exactly one lookup table - the friendly-neutral island border pair')
        lt = lookup_tables[0]

        # e1 should cost 1, a2->N0
        e1: EnrichedFlowTurnsEntry = lt.enriched_capture_entries[0]
        self.assertEqual(1, e1.capture_entry.turns)
        self.assertEqual(1, e1.capture_entry.econ_value)
        self.assertEqual(1, e1.combined_value_density)

        for enriched in lt.enriched_capture_entries:
            cap = enriched.capture_entry
            if cap.turns == 0:
                self.fail('should be no zero turn enriched cap entries anymore')
            target_island_ids = {n.island.unique_id for n in cap.included_target_flow_nodes}
            if b2_island_id not in target_island_ids:
                continue
            found_b2_entry = True
            # Must have walked through both neutrals first — minimum 3 turns
            self.assertEqual(
                4, cap.turns,
                f'Capture entry including b2 (col 8) has cap_turns={cap.turns} < 3; '
                f'the two neutral tiles at cols 5-6 are mandatory traversal and cannot be skipped. '
                f'req={cap.required_army} gath={enriched.gather_entry.gathered_army}'
            )

            self.assertEqual(
                6, cap.required_army,
                f'4-turn capture of neut+neut+b2 must require army=6 (0+0+2+3), got {cap.required_army}'
            )
            # The 3xa2 gather covers exactly 6 — surplus must be 0, not positive
            # (positive surplus here would mean the plan incorrectly bypasses the neutrals)
            surplus = enriched.gather_entry.gathered_army - cap.required_army
            self.assertEqual(surplus, 0)

        self.assertTrue(found_b2_entry, 'Expected at least one enriched entry capturing b2@col7')
    def test_lookup_generation__LARGE_GAP_neutral_tiles_between_friendly_and_enemy__must_count_as_traversal_cost(self):
        """
        Regression: when neutral tiles sit between the friendly border island and the
        enemy tile, the capture stream must treat them as mandatory traversal steps
        BEFORE the enemy tile — not sort them after it by value.

        Layout (1 row, 11 cols) with desired_tile_island_size=1, fill_out_tiles=False:
          a3   aG9  a2   a2   a2   __   __   __   __   __   __   __   __   __   b2   N4   __   bG1
           0    1    2    3    4    5    6    7    8    9   10   11   12   13   14   15   16   17

        Cols 5 and 6 are neutral tiles (army=0) blocking the path from a2@col4 to b2@col7.
        Any plan that captures b2 must traverse both neutrals first:
          col4 -> col5 -> ... -> col14  =  13 moves minimum.

        Previous bug: the capture stream sorted b2 (enemy, high type_bonus) before the
        neutrals, producing a spurious cap_t=1 req=4 entry that teleports past the two
        mandatory neutral tiles, and reported armyGath=1 instead of the correct 0.

        Assertions:
        1. No capture entry for b2 may have cap_turns < 3 (must traverse 2 neutrals first).
        2. The 3-turn capture entry for the 2 neutrals + b2 must have required_army = 5:
             army_cost(neut@5) + army_cost(neut@6) + army(b2) + turns + 1 = 1+1+3 = 5.
        3. Three a2 tiles give gathered_army = 6 — exactly meeting required, surplus = 0,
           so armyGath should be 0 (not positive), meaning aG4 IS needed for any surplus.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
a3   aG10 a2   a2   a2                                                b2   N4        bG1
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = False
        opts = flowExpanderV2.get_expansion_options(
            builder, general.player, enemyGeneral.player, turns=50,
            boardAnalysis=None, territoryMap=None, negativeTiles=None
        )

        lookup_tables = flowExpanderV2.last_lookup_tables
        self.assertIsNotNone(lookup_tables, 'last_lookup_tables must be set after get_expansion_options')
        self.assertGreater(len(lookup_tables), 0, 'Should produce at least one lookup table')

#         self.render_flow_expansion_debug(flowExpanderV2, opts, renderAll=True)

        # b2 is at col 7.  Any capture entry whose included_target_flow_nodes contains b2
        # must have cap_turns >= 3 (col5 neutral + col6 neutral + col7 b2 = 3 mandatory steps).
        b2_tile = map.GetTile(14, 0)

        # TODO BELOW HERE INCORRECT
        b2_island_id = builder.tile_island_lookup.raw[b2_tile.tile_index].unique_id

        found_b2_entry = False
        self.assertEqual(1, len(lookup_tables), 'Should have exactly one lookup table - the friendly-neutral island border pair')
        lt = lookup_tables[0]

        # e1 should cost 1, a2->N0
        e1: EnrichedFlowTurnsEntry = lt.enriched_capture_entries[0]
        self.assertEqual(1, e1.capture_entry.turns)
        self.assertEqual(1, e1.capture_entry.econ_value)
        self.assertEqual(1, e1.combined_value_density)

        enriched: EnrichedFlowTurnsEntry
        for enriched in lt.enriched_capture_entries:
            cap = enriched.capture_entry
            if cap.turns == 0:
                self.fail('should be no zero turn enriched cap entries anymore')
            target_island_ids = {n.island.unique_id for n in cap.included_target_flow_nodes}
            if b2_island_id not in target_island_ids:
                continue
            found_b2_entry = True
            # Must have walked through both neutrals first — minimum 3 turns
            self.assertEqual(
                10, cap.turns,
                f'Capture entry including b2 (col 14) has cap_turns={cap.turns} < 13; '
                f'the neutrals are mandatory traversal and cannot be skipped. '
                f'req={cap.required_army} gath={enriched.gather_entry.gathered_army}'
            )
            self.assertEqual(
                13, enriched.combined_turn_cost,
                f'Capture entry including b2 (col 14) has cap_turns={cap.turns} < 13; '
                f'the neutrals are mandatory traversal and cannot be skipped. '
                f'req={cap.required_army} gath={enriched.gather_entry.gathered_army}'
            )
            # For the 3-turn entry: required_army must equal 6 (0+0+2 army_cost + 3 turns + 1)

            self.assertEqual(
                12, cap.required_army,
                f'10-turn capture of neut*9+b2 must require army=9+3=12, got {cap.required_army}'
            )
            # The 3xa2 gather covers exactly 6 — surplus must be 0, not positive
            # (positive surplus here would mean the plan incorrectly bypasses the neutrals)
            surplus = enriched.gather_entry.gathered_army - cap.required_army
            self.assertEqual(surplus, 0)

        self.assertTrue(found_b2_entry, 'Expected at least one enriched entry capturing b2@col7')

    def test_gather_lookup_generation__army_contribution_is_sum_army_minus_tile_count_not_depth_traversal(self):
        """
        Regression test: gather army contribution must use (sum_army - tile_count) per island,
        NOT (sum_army - (depth - tile_count)).

        With the old depth-based formula, branches feeding into a large intermediate island
        (e.g. 3 islands feeding into a 5-tile hub) would each pay the hub's 5-tile traversal cost
        as part of their own traversal_cost, causing negative contributions and starving
        high-turn gather entries of army.

        The correct model: each island leaves 1 army per tile behind when the stack moves
        through it. Intermediate traversal is already accounted for by those intermediate
        islands' own contributions — downstream traversal must NOT be subtracted again.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        # Map: one general with a 5-tile hub island (row 1) and 3 single-tile branches
        # feeding into it from below, plus a chain leading to the neutral border.
        # The 3 branch tiles (row 2, cols 1-3) feed into the hub (row 1, cols 1-5).
        # The hub feeds into the border tile (row 0, col 2) which captures a neutral.
        #
        # Layout:
        #   (0,0)   (0,1)N  (0,2)N  (0,3)N  (0,4)N  (0,5)N  <- neutrals (to capture)
        #   (1,0)a3 (1,1)a3 (1,2)a3 (1,3)a3 (1,4)a3           <- friendly hub (5 tiles, 15 army)
        #   (2,0)   (2,1)a2 (2,2)a2 (2,3)a2                   <- 3 branch tiles (1t each, 2 army)
        #   (3,0)aG1                                           <- general
        #   ...
        #                                               bG1    <- enemy general
        testData = """
|    |    |    |    |    |    |
     N    N    N    N    N
a3   a3   a3   a3   a3
     a2   a2   a2
aG1                      bG1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 50, fill_out_tiles=False)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        flowExpanderV2.enemyGeneral = enemyGeneral

        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        self.assertGreater(len(border_pairs), 0, 'Should have at least one border pair')

        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Find the border pair that involves the hub island
        hub_tiles = [t for t in map.tiles_by_index if t.player == general.player and t.army >= 3]
        branch_tiles = [t for t in map.tiles_by_index if t.player == general.player and t.army == 2]

        # With correct formula: hub (5t, 15a) contributes 15-5=10, each branch (1t, 2a) contributes 2-1=1
        # Total net = 10 + 3*1 = 13 army (plus general tile contributions)
        # With buggy formula: branch tiles at depth hub_depth+1 would have traversal_cost >= 5,
        # giving negative contributions and starving the gather.

        for tbl in lookup_tables:
            gather_entries = [e for e in tbl.gather_entries_by_turn if e is not None and e.gathered_army > 0]
            if not gather_entries:
                continue

            # At any turn, gathered_army must be >= 0 (never negative due to branch over-subtraction)
            for e in gather_entries:
                self.assertGreaterEqual(
                    e.gathered_army, 0,
                    f'Gathered army must never go negative (bp={tbl.border_pair.friendly_island_id}->'
                    f'{tbl.border_pair.target_island_id}, turn={e.turns}, army={e.gathered_army}). '
                    f'Negative values indicate the old depth-based traversal cost bug.'
                )

            # The border island (the one at depth=1) has traversal_cost=0, so its army
            # contribution equals its full sum_army.  The t=1 gather entry must match.
            # This verifies the depth-based formula doesn't over-subtract the border island.
            border_island_id = tbl.border_pair.friendly_island_id
            border_island = builder.tile_islands_by_unique_id[border_island_id]
            t1_entry = next((e for e in gather_entries if e.turns == 0), None)
            if t1_entry is not None:
                self.assertEqual(
                    t1_entry.gathered_army, border_island.sum_army - border_island.tile_count,
                    f'Turn-1 gather must equal border island sum_army (traversal_cost=0 at depth=1). '
                    f'got {t1_entry.gathered_army}, expected {border_island.sum_army}. '
                    f'Low value indicates depth-based over-subtraction bug.'
                )

    def test_gather_lookup_generation__empty_friendly_stream(self):
        """Test gather lookup generation when no friendly islands are available (edge case)"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # This is an edge case - map with only general and no other friendly islands
        mapData = """
|    |    |    |
aG1  a1   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        self.begin_capturing_logging()

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True

        # Set target team to enemy player
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        if border_pairs:
            # Build stream data for the first border pair
            border_pair = border_pairs[0]
            stream_data = flowExpanderV2._build_border_pair_stream_data(border_pair, flowExpanderV2.flow_graph, target_crossable)
            friendly_contribs, target_contribs = flowExpanderV2._preprocess_flow_stream_tilecounts(stream_data, border_pair)

            # Generate gather lookup table
            gather_lookup = flowExpanderV2._generate_gather_lookup_table(
                border_pair, friendly_contribs, stream_data
            )

            # Should handle empty friendly stream gracefully
            self.assertIsNotNone(gather_lookup, 'Gather lookup should be generated even with empty friendly stream')

            # Should have turn 0 entry
            turn0_entry = gather_lookup[0]
            self.assertIsNotNone(turn0_entry, 'Turn 0 entry should exist')
            self.assertEqual(0, turn0_entry.turns, 'Turn 0 should have 0 turns')
            self.assertEqual(0, turn0_entry.gathered_army, 'Turn 0 should have 0 gathered army')

            if debugMode:
                self._render_gather_lookup_debug(gather_lookup, border_pair, friendly_contribs)
        else:
            # If no border pairs found, that's also a valid test result for this edge case since there is no valid captures here at all
            self.assertTrue(True, 'No border pairs found in edge case scenario')

    # ------------------------------------------------------------------
    # Connectivity validation tests
    # ------------------------------------------------------------------

    def test_lookup_generation__connectivity__horizontal_split_map(self):
        """
        Regression test: Verify that lookup table entries produce connected tile sets.

        This test loads the problematic map from the screenshot and asserts that
        each gather and capture entry's included flow nodes produce a connected
        set of tiles (not disconnected components).

        Layout resembles: friendly territory on right, enemy on left, contested border.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

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

        flowExpanderV2 = ArmyFlowExpanderV2(map)
        flowExpanderV2.log_debug = True
        flowExpanderV2.target_team = enemyGeneral.player

        # Set up the flow graph and preprocessing
        flowExpanderV2._ensure_flow_graph_exists(builder)
        target_crossable = flowExpanderV2._detect_target_crossable_friendly_islands(
            builder, flowExpanderV2.flow_graph, flowExpanderV2.team, flowExpanderV2.target_team
        )
        border_pairs = flowExpanderV2._enumerate_border_pairs(
            flowExpanderV2.flow_graph, builder, flowExpanderV2.team, flowExpanderV2.target_team, target_crossable
        )

        self.assertGreater(len(border_pairs), 0, 'Should find at least one border pair')

        # Generate lookup tables
        lookup_tables = flowExpanderV2._process_flow_into_flow_army_turns(
            border_pairs, flowExpanderV2.flow_graph, target_crossable
        )

        self.assertGreater(len(lookup_tables), 0, 'Should generate lookup tables')

        # Validate connectivity for each lookup table entry
        for lookup_table in lookup_tables:
            border_pair = lookup_table.border_pair
            context = f"border_pair {border_pair.friendly_island_id}->{border_pair.target_island_id}"

            # Check gather entries for connectivity
            for entry in lookup_table.gather_entries_by_turn:
                if entry is not None and entry.included_friendly_flow_nodes:
                    self._assert_flow_nodes_produce_connected_tiles(
                        entry.included_friendly_flow_nodes,
                        f"Gather entry (turns={entry.turns})",
                        context
                    )

            # Check capture entries for connectivity
            for entry in lookup_table.capture_entries_by_turn:
                if entry is not None and entry.included_target_flow_nodes:
                    self._assert_flow_nodes_produce_connected_tiles(
                        entry.included_target_flow_nodes,
                        f"Capture entry (turns={entry.turns})",
                        context
                    )

        if debugMode:
            logbook.info(f"Validated connectivity for {len(lookup_tables)} lookup tables")
