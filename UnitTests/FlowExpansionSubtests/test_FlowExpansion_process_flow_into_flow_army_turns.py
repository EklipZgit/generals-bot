import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import (
    ArmyFlowExpanderV2,
    FlowArmyTurnsLookupTable,
    FlowBorderPairKey,
    FlowStreamIslandContribution,
    FlowTurnsEntry,
    ITERATIVE_EXPANSION_EN_CAP_VAL,
)
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from ViewInfo import TargetStyle
from base import Colors
from base.client.map import MapBase
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot


class FlowExpansionProcessFlowIntoFlowArmyTurnsTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)
        return bot

    # ------------------------------------------------------------------
    # Debug rendering helpers
    # ------------------------------------------------------------------

    def render_lookup_table_debug(
        self,
        map: MapBase,
        expander: ArmyFlowExpanderV2,
        lookup_table: FlowArmyTurnsLookupTable,
        title: str = 'process_flow_into_flow_army_turns debug',
    ):
        """
        Visualizes a FlowArmyTurnsLookupTable:
        - Draws flow graph arrows in the background
        - Labels each tile by island membership
        - Lists all non-None capture and gather entries in info lines
        - Highlights border pair crossing with an orange arrow
        - Shows metadata values
        """
        view_info = self.get_renderable_view_info(map)

        from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
        if expander.flow_graph is not None:
            ArmyFlowExpander.add_flow_graph_to_view_info(expander.flow_graph, view_info, lastRun=None)

        bp = lookup_table.border_pair
        view_info.add_info_line(f'=== {title} ===')
        view_info.add_info_line(f'Border pair: friendly={bp.friendly_island_id} -> target={bp.target_island_id}')

        # Draw the border-pair crossing arrow
        if expander.flow_graph is not None:
            flow_lookup = expander.flow_graph.flow_node_lookup_by_island_inc_neut
            fn = flow_lookup.get(bp.friendly_island_id)
            tn = flow_lookup.get(bp.target_island_id)
            if fn and tn:
                fx = sum(t.x for t in fn.island.tile_set) / len(fn.island.tile_set)
                fy = sum(t.y for t in fn.island.tile_set) / len(fn.island.tile_set)
                tx = sum(t.x for t in tn.island.tile_set) / len(tn.island.tile_set)
                ty = sum(t.y for t in tn.island.tile_set) / len(tn.island.tile_set)
                view_info.draw_diagonal_arrow_between_xy(fx, fy, tx, ty, label='BP', color=Colors.ORANGE)

        # Metadata
        meta = lookup_table.metadata
        view_info.add_info_line(f'Metadata: max_flow={meta.get("max_flow_across_border", "?")} '
                                f'friendly_tiles={meta.get("friendly_stream_tile_count", "?")} '
                                f'target_tiles={meta.get("target_stream_tile_count", "?")}')

        # Capture entries
        cap_entries = [e for e in lookup_table.capture_entries_by_turn if e is not None]
        view_info.add_info_line(f'Capture entries ({len(cap_entries)}):')
        for e in cap_entries:
            n_target = len(e.included_target_flow_nodes)
            view_info.add_info_line(
                f'  t={e.turns} req_army={e.required_army} econ={e.econ_value:.2f} '
                f'target_nodes={n_target} incomplete_tgt={e.incomplete_target_island_id}'
            )
            for node in e.included_target_flow_nodes:
                for tile in node.island.tile_set:
                    view_info.topRightGridText[tile] = f'C{e.turns}'
                    view_info.add_targeted_tile(tile, TargetStyle.RED, radiusReduction=6)

        # Gather entries
        gath_entries = [e for e in lookup_table.gather_entries_by_turn if e is not None]
        view_info.add_info_line(f'Gather entries ({len(gath_entries)}):')
        for e in gath_entries:
            n_friendly = len(e.included_friendly_flow_nodes)
            view_info.add_info_line(
                f'  t={e.turns} gathered={e.gathered_army} '
                f'friendly_nodes={n_friendly} incomplete_fr={e.incomplete_friendly_island_id}'
            )
            for node in e.included_friendly_flow_nodes:
                for tile in node.island.tile_set:
                    view_info.topRightGridText[tile] = f'G{e.turns}'
                    view_info.add_targeted_tile(tile, TargetStyle.GREEN, radiusReduction=6)

        # Prefix tables
        best_cap = [e for e in lookup_table.best_capture_entries_prefix if e is not None]
        best_gath = [e for e in lookup_table.best_gather_entries_prefix if e is not None]
        view_info.add_info_line(f'Prefix: best_capture={len(best_cap)} non-None, best_gather={len(best_gath)} non-None')

        self.render_view_info(map, view_info, title)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _build_expander_with_flow_graph(
        self,
        map: MapBase,
        general: Tile,
        enemyGeneral: Tile,
    ) -> tuple[ArmyFlowExpanderV2, TileIslandBuilder]:
        """Build the flow expander and flow graph for a given map/generals."""

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.enemy_general = enemyGeneral
        expander._ensure_flow_graph_exists(builder)
        return expander, builder

    def _run_process_flow(
        self,
        expander: ArmyFlowExpanderV2,
        builder: TileIslandBuilder,
    ) -> list[FlowArmyTurnsLookupTable]:
        """Run the full Phase 2 pipeline and return the lookup tables."""
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )
        return expander._process_flow_into_flow_army_turns(
            border_pairs, expander.flow_graph, target_crossable
        )

    # ------------------------------------------------------------------
    # Tests: return structure
    # ------------------------------------------------------------------

    def test_process_flow__single_border_pair__returns_one_lookup_table(self):
        """
        Simplest possible map: one friendly island, one enemy island.
        _process_flow_into_flow_army_turns must return exactly one FlowArmyTurnsLookupTable.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'single border pair returns one lookup table')

        self.assertGreaterEqual(len(lookup_tables), 1, 'Expected at least one lookup table for the single border pair')
        for lt in lookup_tables:
            self.assertIsInstance(lt, FlowArmyTurnsLookupTable)

    def test_process_flow__lookup_table_has_all_required_fields(self):
        """
        The returned FlowArmyTurnsLookupTable must have all required fields populated:
        border_pair, capture_entries_by_turn, gather_entries_by_turn,
        best_capture_entries_prefix, best_gather_entries_prefix, metadata.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'lookup table has all required fields')

        self.assertIsNotNone(lt.border_pair, 'border_pair must be set')
        self.assertIsInstance(lt.border_pair, FlowBorderPairKey)
        self.assertIsNotNone(lt.capture_entries_by_turn, 'capture_entries_by_turn must be set')
        self.assertIsInstance(lt.capture_entries_by_turn, list)
        self.assertIsNotNone(lt.gather_entries_by_turn, 'gather_entries_by_turn must be set')
        self.assertIsInstance(lt.gather_entries_by_turn, list)
        self.assertIsNotNone(lt.best_capture_entries_prefix, 'best_capture_entries_prefix must be set')
        self.assertIsInstance(lt.best_capture_entries_prefix, list)
        self.assertIsNotNone(lt.best_gather_entries_prefix, 'best_gather_entries_prefix must be set')
        self.assertIsInstance(lt.best_gather_entries_prefix, list)
        self.assertIsNotNone(lt.metadata, 'metadata must be set')
        self.assertIsInstance(lt.metadata, dict)

    def test_process_flow__metadata_contains_required_keys(self):
        """
        metadata dict must contain: max_flow_across_border, friendly_stream_tile_count,
        target_stream_tile_count, border_pair.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        meta = lookup_tables[0].metadata

        if debugMode:
            self.render_lookup_table_debug(map, expander, lookup_tables[0], 'metadata keys present')

        self.assertIn('max_flow_across_border', meta, 'metadata must contain max_flow_across_border')
        self.assertIn('friendly_stream_tile_count', meta, 'metadata must contain friendly_stream_tile_count')
        self.assertIn('target_stream_tile_count', meta, 'metadata must contain target_stream_tile_count')
        self.assertIn('border_pair', meta, 'metadata must contain border_pair')

    def test_process_flow__metadata_tile_counts_are_positive(self):
        """
        friendly_stream_tile_count and target_stream_tile_count must both be >= 1
        when the map has at least one friendly island and one target island.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        meta = lookup_tables[0].metadata

        if debugMode:
            self.render_lookup_table_debug(map, expander, lookup_tables[0], 'metadata tile counts positive')

        self.assertGreaterEqual(meta['friendly_stream_tile_count'], 1,
                                'friendly_stream_tile_count must be >= 1')
        self.assertGreaterEqual(meta['target_stream_tile_count'], 1,
                                'target_stream_tile_count must be >= 1')

    # ------------------------------------------------------------------
    # Tests: capture lookup entries
    # ------------------------------------------------------------------

    def test_process_flow__capture_lookup_turn0_is_empty_border_state(self):
        """
        Per the MD spec, captureLookup[0] represents the zero-cost border starting state
        with no islands captured yet.
        required_army=0, econ_value=0.0, included_target_flow_nodes=().

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'capture t=0 is empty border state')

        entry0 = lt.capture_entries_by_turn[0]
        self.assertIsNotNone(entry0, 'capture_entries_by_turn[0] must not be None (border state)')
        self.assertEqual(0, entry0.turns, 'turns at index 0 must be 0')
        self.assertEqual(0, entry0.required_army, 'border state must require 0 army')
        self.assertAlmostEqual(0.0, entry0.econ_value, places=5, msg='border state must have 0.0 econ_value')
        self.assertEqual(0, len(entry0.included_target_flow_nodes),
                         'border state must have no included target flow nodes')

    def test_process_flow__single_enemy_island_generates_capture_entry(self):
        """
        After adding one enemy island (b1 at turn 1), capture_entries_by_turn must have a
        non-None entry at the appropriate turn index with:
        - required_army >= 1 (at least the b1 army)
        - econ_value >= ITERATIVE_EXPANSION_EN_CAP_VAL (one enemy tile)
        - exactly one included target flow node

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'single enemy island capture entry')

        # Find any non-None capture entry beyond turn 0
        non_zero_entries = [e for e in lt.capture_entries_by_turn if e is not None and e.turns > 0]
        self.assertGreater(len(non_zero_entries), 0,
                           'Must have at least one capture entry beyond turn 0')

        first_cap = min(non_zero_entries, key=lambda e: e.turns)
        self.assertGreaterEqual(first_cap.required_army, 1,
                                'First capture entry must require at least 1 army')
        self.assertGreaterEqual(first_cap.econ_value, ITERATIVE_EXPANSION_EN_CAP_VAL,
                                'First enemy capture entry econ_value must be >= ITERATIVE_EXPANSION_EN_CAP_VAL')
        self.assertEqual(1, len(first_cap.included_target_flow_nodes),
                         'First capture entry should include exactly one enemy island')

    def test_process_flow__enemy_capture_econ_value_is_en_cap_val_per_tile(self):
        """
        An enemy island with tile_count=1 must produce econ_value == ITERATIVE_EXPANSION_EN_CAP_VAL.
        An enemy island with tile_count=2 must produce econ_value == 2 * ITERATIVE_EXPANSION_EN_CAP_VAL.

        Layout (1 row, 2 enemy tiles then general):
          aG1  a5   b2   bG1
        The b2 island has 1 tile (value=1, army=2), so first capture entry should have econ=EN_CAP_VAL.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b2   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'enemy econ value per tile')

        non_zero = [e for e in lt.capture_entries_by_turn if e is not None and e.turns > 0]
        self.assertGreater(len(non_zero), 0)

        first_cap = min(non_zero, key=lambda e: e.turns)
        # Each enemy tile captured = ITERATIVE_EXPANSION_EN_CAP_VAL
        n_tiles_captured = sum(n.island.tile_count for n in first_cap.included_target_flow_nodes)
        expected_econ = ITERATIVE_EXPANSION_EN_CAP_VAL * n_tiles_captured
        self.assertAlmostEqual(
            expected_econ, first_cap.econ_value, places=4,
            msg=f'econ_value must be EN_CAP_VAL * {n_tiles_captured} tiles'
        )

    def test_process_flow__neutral_capture_econ_value_is_one_per_tile(self):
        """
        A neutral island (team=-1) captured in the target stream must contribute
        econ_value == 1.0 per tile (not ITERATIVE_EXPANSION_EN_CAP_VAL).

        Layout:
          aG1  a5   (neut)   b1   bG1
        The neutral tile between friendly and enemy should appear in the capture stream.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a5        b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'neutral capture econ = 1.0/tile')

        # Find any capture entry that includes a neutral island
        all_entries = [e for lt in lookup_tables for e in lt.capture_entries_by_turn if e is not None and e.turns > 0]
        neutral_entries = [
            e for e in all_entries
            if any(n.island.team == -1 for n in e.included_target_flow_nodes)
        ]
        self.assertGreater(len(neutral_entries), 0,
                           'Expected at least one capture entry that includes a neutral island')

        for e in neutral_entries:
            neut_tiles = sum(n.island.tile_count for n in e.included_target_flow_nodes if n.island.team == -1)
            enemy_tiles = sum(n.island.tile_count for n in e.included_target_flow_nodes if n.island.team != -1 and n.island.team == expander.target_team)
            expected_econ = neut_tiles * 1.0 + enemy_tiles * ITERATIVE_EXPANSION_EN_CAP_VAL
            self.assertAlmostEqual(
                expected_econ, e.econ_value, places=4,
                msg='Neutral tiles must count as 1.0 econ, enemy tiles as EN_CAP_VAL'
            )

    def test_process_flow__crossing_island_adds_no_econ_value(self):
        """
        A target-crossable friendly island included in the capture stream must contribute
        zero econ_value and zero required_army (only turn cost).

        Uses the encircled outpost layout from test_FlowExpansion_TargetCrossable.

        Layout (5 rows, 6 cols):
          b1   b1   b1   b1   b1   b1
          aG1  a1   a1   a1   b1   b1
          a1   a1   a1   b1   a1   bG1   <- outpost at (4,2)
          a1   a1   a1   a1   b1   b1
          b1   b1   b1   b1   b1   b1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
b1   b1   b1   b1   b1   b1
aG1  a1   a1   a1   b1   b1
a1   a1   a1   b1   a1   bG1
a1   a1   a1   a1   b1   b1
b1   b1   b1   b1   b1   b1
|    |    |    |    |    |
        """
        MapBase.DO_NOT_RANDOMIZE = True

        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        self.begin_capturing_logging()
        expander.log_debug = True
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        if len(target_crossable) == 0:
            self.fail('No target-crossable islands detected; outpost may not qualify in this flow graph configuration')

        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )
        lookup_tables = expander._process_flow_into_flow_army_turns(
            border_pairs, expander.flow_graph, target_crossable
        )

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'crossing island no econ value')

        # Find capture entries containing a crossing (friendly) node
        all_cap_entries = [
            e for lt in lookup_tables
            for e in lt.capture_entries_by_turn
            if e is not None and e.turns > 0
        ]
        crossing_entries = []
        for e in all_cap_entries:
            for node in e.included_target_flow_nodes:
                if node.island.team == expander.team and node.island.unique_id in target_crossable:
                    crossing_entries.append(e)
                    break

        if crossing_entries:
            # When a crossing entry exists, the econ_value should only reflect
            # enemy/neutral tiles captured, NOT the crossing friendly tile
            for e in crossing_entries:
                non_crossing_tiles = sum(
                    n.island.tile_count for n in e.included_target_flow_nodes
                    if not (n.island.team == expander.team and n.island.unique_id in target_crossable)
                )
                max_expected_econ = non_crossing_tiles * ITERATIVE_EXPANSION_EN_CAP_VAL
                self.assertLessEqual(
                    e.econ_value, max_expected_econ + 1e-6,
                    'Crossing friendly island must not contribute econ_value to capture entry'
                )

    # ------------------------------------------------------------------
    # Tests: gather lookup entries
    # ------------------------------------------------------------------

    def test_process_flow__gather_lookup_turn0_is_empty_border_state(self):
        """
        gatherLookup[0] represents the zero-cost border starting state (per MD spec).
        gathered_army=0, included_friendly_flow_nodes=().

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'gather t=0 is empty border state')

        entry0 = lt.gather_entries_by_turn[0]
        self.assertIsNotNone(entry0, 'gather_entries_by_turn[0] must not be None (border state)')
        self.assertEqual(0, entry0.turns, 'turns at index 0 must be 0, since the move is consumed on the capture side of the border pair')
        self.assertEqual(2, entry0.gathered_army, 'border state must have gathered_army={whatever first tile in the friendly border island is}')
        self.assertEqual(1, len(entry0.included_friendly_flow_nodes),
                         'border state must have no included friendly flow nodes')

    def test_process_flow__gather_entry_accumulated_army_matches_islands(self):
        """
        After including a friendly island with army=3 (a3), the first non-zero gather entry
        must have gathered_army == 3 (or >= 3 if the general tile is also included first).

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG3  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'gather army matches islands')

        non_zero_gath = [e for e in lt.gather_entries_by_turn if e is not None and e.turns > 0]
        self.assertGreater(len(non_zero_gath), 0,
                           'Must have at least one gather entry beyond turn 0')

        # The cumulative gathered_army at each entry must equal the sum of sum_army
        # for all included_friendly_flow_nodes
        for e in non_zero_gath:
            expected_army = sum(n.island.sum_army - n.island.tile_count for n in e.included_friendly_flow_nodes)
            self.assertEqual(expected_army, e.gathered_army,
                             f'gathered_army={e.gathered_army} must equal sum of included island armies={expected_army} at t={e.turns}')

    def test_process_flow__gather_entry_turns_matches_tile_count(self):
        """
        The turns index for each gather entry must equal the cumulative tile count of all
        included friendly islands.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'gather turns matches tile count')

        non_zero_gath = [e for e in lt.gather_entries_by_turn if e is not None and e.turns > 0]
        for e in non_zero_gath:
            expected_turns = sum(n.island.tile_count for n in e.included_friendly_flow_nodes)
            self.assertEqual(expected_turns, e.turns,
                             f'turns={e.turns} must match cumulative tile count={expected_turns}')

    def test_process_flow__multi_island_gather_entries_are_cumulative(self):
        """
        When multiple friendly islands exist, each successive gather entry must include
        all previously-included islands plus the new one.

        Layout (two distinct friendly non-gen islands):
          aG1  a3   a5   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a3   a5   b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'multi-island gather cumulative')

        non_zero_gath = [
            e for lt in lookup_tables
            for e in lt.gather_entries_by_turn
            if e is not None and e.turns > 0
        ]
        # Sort by turns ascending; each entry should have >= islands than the previous
        non_zero_gath.sort(key=lambda e: e.turns)
        for i in range(len(non_zero_gath) - 1):
            a = non_zero_gath[i]
            b = non_zero_gath[i + 1]
            if b.turns > a.turns:
                self.assertGreaterEqual(
                    len(b.included_friendly_flow_nodes),
                    len(a.included_friendly_flow_nodes),
                    f'Gather entry at t={b.turns} must include >= islands vs t={a.turns}'
                )

    # ------------------------------------------------------------------
    # Tests: prefix tables
    # ------------------------------------------------------------------

    def test_process_flow__prefix_capture_nondecreasing_econ_value(self):
        """
        best_capture_entries_prefix[i] must have econ_value >= best_capture_entries_prefix[i-1]
        for all i (or both None).

        Layout:
          aG1  a5   b1   b3   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a5   b1   b3   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'prefix capture nondecreasing econ')

        for lt in lookup_tables:
            prefix = lt.best_capture_entries_prefix
            prev = None
            for entry in prefix:
                if entry is not None and prev is not None:
                    self.assertGreaterEqual(
                        entry.econ_value, prev.econ_value,
                        f'best_capture_entries_prefix econ_value must be nondecreasing: '
                        f'{entry.econ_value:.2f} < {prev.econ_value:.2f}'
                    )
                if entry is not None:
                    prev = entry

    def test_process_flow__prefix_gather_nondecreasing_gathered_army(self):
        """
        best_gather_entries_prefix[i] must have gathered_army >= best_gather_entries_prefix[i-1]
        (when both non-None). Ensures the prefix table is monotone.

        Layout:
          aG1  a3   a5   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a3   a5   b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'prefix gather nondecreasing army')

        for lt in lookup_tables:
            prefix = lt.best_gather_entries_prefix
            prev = None
            for entry in prefix:
                if entry is not None and prev is not None:
                    self.assertGreaterEqual(
                        entry.gathered_army, prev.gathered_army,
                        f'best_gather_entries_prefix gathered_army must be nondecreasing: '
                        f'{entry.gathered_army} < {prev.gathered_army}'
                    )
                if entry is not None:
                    prev = entry

    def test_process_flow__prefix_length_matches_lookup_length(self):
        """
        best_capture_entries_prefix and best_gather_entries_prefix must have the same
        length as capture_entries_by_turn and gather_entries_by_turn respectively.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)
        lt = lookup_tables[0]

        if debugMode:
            self.render_lookup_table_debug(map, expander, lt, 'prefix length matches lookup length')

        self.assertEqual(len(lt.capture_entries_by_turn), len(lt.best_capture_entries_prefix),
                         'best_capture_entries_prefix length must match capture_entries_by_turn length')
        self.assertEqual(len(lt.gather_entries_by_turn), len(lt.best_gather_entries_prefix),
                         'best_gather_entries_prefix length must match gather_entries_by_turn length')

    # ------------------------------------------------------------------
    # Tests: multi border pairs
    # ------------------------------------------------------------------

    def test_process_flow__multiple_border_pairs_produce_independent_tables(self):
        """
        When the map has two independent friendly-to-enemy borders, the method must
        produce a separate FlowArmyTurnsLookupTable for each border pair.
        Each table's border_pair must be distinct.

        Layout (two rows):
          aG1  b1  bG1
          a5   b1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  b1   bG1
a5   b1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'multiple border pairs independent tables')

        # All returned border_pair keys must be unique
        pair_keys = [lt.border_pair for lt in lookup_tables]
        unique_keys = set((p.friendly_island_id, p.target_island_id) for p in pair_keys)
        self.assertEqual(len(pair_keys), len(unique_keys),
                         'Each FlowArmyTurnsLookupTable must have a unique border_pair key')

    def test_process_flow__no_border_pairs_returns_empty_list(self):
        """
        If there are no border pairs (impossible in practice but we can test with an
        empty border_pairs list passed directly), the method must return an empty list.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )

        result = expander._process_flow_into_flow_army_turns([], expander.flow_graph, target_crossable)

        self.assertEqual([], result, 'Empty border_pairs list must produce empty result')

    # ------------------------------------------------------------------
    # Tests: metadata / max flow
    # ------------------------------------------------------------------

    def test_process_flow__metadata_max_flow_nonnegative(self):
        """
        max_flow_across_border in metadata must always be >= 0.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            self.render_lookup_table_debug(map, expander, lookup_tables[0], 'max_flow nonnegative')

        for lt in lookup_tables:
            self.assertGreaterEqual(lt.metadata['max_flow_across_border'], 0,
                                    'max_flow_across_border must be >= 0')

    def test_process_flow__metadata_border_pair_matches_table_border_pair(self):
        """
        metadata['border_pair'] must be the same object (or equal) to lt.border_pair.

        Layout:
          aG1  a3   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            self.render_lookup_table_debug(map, expander, lookup_tables[0], 'metadata border_pair matches')

        for lt in lookup_tables:
            self.assertEqual(lt.border_pair, lt.metadata['border_pair'],
                             'metadata["border_pair"] must equal lt.border_pair')

    # ------------------------------------------------------------------
    # Tests: FlowTurnsEntry fields
    # ------------------------------------------------------------------

    def test_process_flow__entry_turns_field_matches_index(self):
        """
        For every non-None entry in capture_entries_by_turn and gather_entries_by_turn,
        entry.turns must equal its index in the list.

        Layout:
          aG1  a5   b1   b3   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a5   b1   b3   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'entry.turns matches index')

        for lt in lookup_tables:
            for idx, entry in enumerate(lt.capture_entries_by_turn):
                if entry is not None:
                    self.assertEqual(idx, entry.turns,
                                     f'capture entry.turns={entry.turns} must equal index={idx}')
            for idx, entry in enumerate(lt.gather_entries_by_turn):
                if entry is not None:
                    self.assertEqual(idx, entry.turns,
                                     f'gather entry.turns={entry.turns} must equal index={idx}')

    def test_process_flow__capture_entries_required_army_nonnegative(self):
        """
        All capture entries must have required_army >= 0.

        Layout:
          aG1  a5   b1   b3   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a5   b1   b3   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'required_army nonnegative')

        for lt in lookup_tables:
            for entry in lt.capture_entries_by_turn:
                if entry is not None:
                    self.assertGreaterEqual(entry.required_army, 0,
                                            f'required_army must be >= 0 at t={entry.turns}')

    def test_process_flow__capture_entries_econ_value_nonnegative(self):
        """
        All capture entries must have econ_value >= 0.0.

        Layout:
          aG1  a5   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'econ_value nonnegative')

        for lt in lookup_tables:
            for entry in lt.capture_entries_by_turn:
                if entry is not None:
                    self.assertGreaterEqual(entry.econ_value, 0.0,
                                            f'econ_value must be >= 0.0 at t={entry.turns}')

    def test_process_flow__gather_entries_gathered_army_nonnegative(self):
        """
        All gather entries must have gathered_army >= 0.

        Layout:
          aG1  a5   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'gathered_army nonnegative')

        for lt in lookup_tables:
            for entry in lt.gather_entries_by_turn:
                if entry is not None:
                    self.assertGreaterEqual(entry.gathered_army, 0,
                                            f'gathered_army must be >= 0 at t={entry.turns}')

    # ------------------------------------------------------------------
    # Tests: combined army/econ values match expected from map data
    # ------------------------------------------------------------------

    def test_process_flow__two_enemy_islands_capture_econ_cumulative(self):
        """
        Map with two enemy islands (b1 and b3 in separate cells) should produce
        capture entries where:
        - First entry covers the closer/lower-army island
        - Second entry covers both islands with strictly greater econ_value than the first
        - Each individual entry's econ_value equals EN_CAP_VAL * total_enemy_tiles_in_that_entry

        Layout (all single-tile islands):
          aG1  a8   b1   b3   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a8   b1   b3   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'two enemy islands cumulative econ')

        non_zero_cap = [
            e for lt in lookup_tables
            for e in lt.capture_entries_by_turn
            if e is not None and e.turns > 0
        ]
        self.assertGreater(len(non_zero_cap), 0, 'Expected at least one non-zero capture entry')

        # For each capture entry, econ_value must exactly equal the per-island sum
        for e in non_zero_cap:
            expected_econ = sum(
                ITERATIVE_EXPANSION_EN_CAP_VAL * n.island.tile_count
                if n.island.team == expander.target_team
                else 1.0 * n.island.tile_count
                for n in e.included_target_flow_nodes
                if not (n.island.team == expander.team)  # skip crossing nodes
            )
            self.assertAlmostEqual(
                expected_econ, e.econ_value, places=4,
                msg=f'econ_value={e.econ_value:.4f} at t={e.turns} must equal computed econ={expected_econ:.4f}'
            )

        # The entry with max econ_value should include more target nodes than the minimum entry
        if len(non_zero_cap) >= 2:
            min_econ_entry = min(non_zero_cap, key=lambda e: e.econ_value)
            max_econ_entry = max(non_zero_cap, key=lambda e: e.econ_value)
            self.assertGreater(max_econ_entry.econ_value, min_econ_entry.econ_value,
                               'Entry with more islands captured should have higher econ_value')

    def test_process_flow__capture_required_army_monotone_nondecreasing(self):
        """
        As we capture more islands, required_army must be monotone nondecreasing across
        non-None capture entries (each additional island can only add army cost, not reduce it).

        Layout:
          aG1  a8   b1   b3   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a8   b1   b3   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        self.assertGreaterEqual(len(lookup_tables), 1)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'required_army monotone nondecreasing')

        for lt in lookup_tables:
            non_zero_cap = [e for e in lt.capture_entries_by_turn if e is not None and e.turns > 0]
            non_zero_cap.sort(key=lambda e: e.turns)
            for i in range(len(non_zero_cap) - 1):
                self.assertGreaterEqual(
                    non_zero_cap[i + 1].required_army,
                    non_zero_cap[i].required_army,
                    f'required_army must be nondecreasing: t={non_zero_cap[i].turns} -> t={non_zero_cap[i+1].turns}'
                )

    def test_process_flow__neutral_gap_still_produces_lookup_table(self):
        """
        When a neutral island sits between friendly and enemy, _process_flow_into_flow_army_turns
        must still produce at least one lookup table with non-None capture entries
        (the neutral island is part of the capture stream).

        Layout:
          aG1  a5   (neut)   b1   bG1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a5        b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._build_expander_with_flow_graph(map, general, enemyGeneral)
        lookup_tables = self._run_process_flow(expander, builder)

        if debugMode:
            for lt in lookup_tables:
                self.render_lookup_table_debug(map, expander, lt, 'neutral gap produces lookup table')

        self.assertGreater(len(lookup_tables), 0,
                           'Must produce at least one lookup table even with neutral gap')

        all_cap = [e for lt in lookup_tables for e in lt.capture_entries_by_turn if e is not None and e.turns > 0]
        self.assertGreater(len(all_cap), 0,
                           'Must have at least one non-zero capture entry even through neutral gap')
