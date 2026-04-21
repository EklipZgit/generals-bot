import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2, FlowBorderPairKey, FlowArmyTurnsLookupTable, EnrichedFlowTurnsEntry, FlowTurnsEntry
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot


class FlowExpansionLookupPostProcessingTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)
        return bot

    def _setup_expander_with_lookup_tables(
        self,
        map: MapBase,
        general,
        enemyGeneral,
    ) -> tuple[ArmyFlowExpanderV2, TileIslandBuilder, list[FlowArmyTurnsLookupTable]]:
        """Build the flow expander, flow graph, and lookup tables for a given map/generals."""
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.enemy_general = enemyGeneral
        expander._ensure_flow_graph_exists(builder)

        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )

        lookup_tables = expander._process_flow_into_flow_army_turns(
            border_pairs, expander.flow_graph, target_crossable
        )

        return expander, builder, lookup_tables

    # ------------------------------------------------------------------
    # Basic gather-capture pairing tests
    # ------------------------------------------------------------------

    def test_postprocess__simple_linear_map__basic_pairing(self):
        """
        Simplest case: single friendly island with army, single enemy island.
        Verify that capture entries are paired with gather entries correctly.

        Layout:
          aG1  a5   b1   bG1

        Expected:
        - Gather turn 1: gathered_army=5 (from a5)
        - Capture turn 1: required_army=1 (to capture b1)
        - Pairing: capture turn 1 should pair with gather turn 1
        - Combined turn cost: 1 + 1 = 2
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)

        self.assertGreater(len(lookup_tables), 0, 'Should have at least one lookup table')

        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries
            self.assertGreater(len(enriched_entries), 0, 'Should have at least one enriched capture entry')

            for enriched in enriched_entries:
                self.assertIsNotNone(enriched.capture_entry, 'Capture entry should not be None')
                self.assertIsNotNone(enriched.gather_entry, 'Gather entry should not be None')
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'Gather entry must provide sufficient army: '
                    f'gathered={enriched.gather_entry.gathered_army} vs required={enriched.capture_entry.required_army}'
                )
                self.assertEqual(
                    enriched.combined_turn_cost,
                    enriched.capture_entry.turns + enriched.gather_entry.turns,
                    'Combined turn cost should equal sum of capture and gather turns'
                )
                if enriched.combined_turn_cost > 0:
                    expected_density = enriched.capture_entry.econ_value / enriched.combined_turn_cost
                    self.assertAlmostEqual(
                        enriched.combined_value_density,
                        expected_density,
                        places=5,
                        msg='Combined value density should equal econ_value / combined_turn_cost'
                    )

    def test_postprocess__zero_army_required__pairs_with_turn_zero_gather(self):
        """
        When a capture entry requires zero army (e.g., turn 0 initial state),
        it should pair with the turn 0 gather entry.

        Layout:
          aG1  a5   b1   bG1

        Expected:
        - Turn 0 capture entry (no capture yet) requires 0 army
        - Should pair with turn 0 gather entry (no gather yet)
        - Combined turn cost: 0 + 0 = 0
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            turn_zero_capture = lookup_table.capture_entries_by_turn[0]
            self.assertIsNotNone(turn_zero_capture, 'Turn 0 capture entry should exist')
            self.assertEqual(0, turn_zero_capture.required_army, 'Turn 0 capture should require 0 army')

            enriched_with_zero = [e for e in lookup_table.enriched_capture_entries
                                 if e.capture_entry.turns == 0]
            if enriched_with_zero:
                enriched = enriched_with_zero[0]
                self.assertEqual(0, enriched.gather_entry.turns, 'Turn 0 capture should pair with turn 0 gather')
                self.assertEqual(0, enriched.combined_turn_cost, 'Combined turn cost should be 0')

    def test_postprocess__multiple_captures__each_paired_with_minimum_gather(self):
        """
        Multiple capture entries should each be paired with the minimum-turn gather
        entry that provides sufficient army.

        Layout:
          aG1  a3   a5   b1   b3   bG1

        Expected:
        - Capture turn 1 (b1, army=1) pairs with gather turn 1 (a3, army=3)
        - Capture turn 2 (b1+b3, army=4) pairs with gather turn 2 (a3+a5, army=8)
        - Each capture uses the minimum gather that satisfies its army requirement
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a3   a5   b1   b3   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            for enriched in enriched_entries:
                required_army = enriched.capture_entry.required_army
                gathered_army = enriched.gather_entry.gathered_army

                self.assertGreaterEqual(
                    gathered_army, required_army,
                    f'Gather must provide sufficient army: gathered={gathered_army} vs required={required_army}'
                )

                gather_turn = enriched.gather_entry.turns
                for earlier_turn in range(gather_turn):
                    earlier_gather = lookup_table.gather_entries_by_turn[earlier_turn]
                    if earlier_gather is not None:
                        self.assertLess(
                            earlier_gather.gathered_army, required_army,
                            f'Earlier gather turn {earlier_turn} (army={earlier_gather.gathered_army}) '
                            f'should not satisfy required_army={required_army}, '
                            f'otherwise it should have been chosen instead of turn {gather_turn}'
                        )

    # ------------------------------------------------------------------
    # Partial capture and partial gather scenarios
    # ------------------------------------------------------------------

    def test_postprocess__partial_capture__pairs_correctly(self):
        """
        Test partial capture scenarios where we capture only part of an island.
        Currently, the implementation creates entries only at island boundaries,
        so this test verifies that behavior.

        Layout:
          aG1  a10  b1   b5   bG1

        Expected:
        - Capture turn 1: b1 (army=1)
        - Capture turn 2: b1+b5 (army=6)
        - Each should pair with appropriate gather entry
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a10  b1   b5   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            for enriched in enriched_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    'Gather must always provide sufficient army for partial captures'
                )

    def test_postprocess__partial_gather__pairs_correctly(self):
        """
        Test partial gather scenarios where we gather from multiple islands.

        Layout:
          aG1  a2   a3   a5   b1   bG1

        Expected:
        - Gather turn 1: a2 (army=2)
        - Gather turn 2: a2+a3 (army=5)
        - Gather turn 3: a2+a3+a5 (army=10)
        - Capture entries should pair with the minimum gather that satisfies them
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a2   a3   a5   b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            gather_entries = lookup_table.gather_entries_by_turn

            cumulative_army = 0
            for turn, gather_entry in enumerate(gather_entries):
                if gather_entry is not None:
                    self.assertGreaterEqual(
                        gather_entry.gathered_army, cumulative_army,
                        f'Gather army should be monotonically increasing: '
                        f'turn {turn} has {gather_entry.gathered_army}, expected >= {cumulative_army}'
                    )
                    cumulative_army = gather_entry.gathered_army

    def test_postprocess__partial_capture_plus_partial_gather__comprehensive(self):
        """
        Comprehensive test with both partial captures and partial gathers.

        Layout:
          aG1  a2   a4   a6   b1   b2   b3   bG1

        Expected:
        - Multiple gather entries: turn 1 (a2), turn 2 (a2+a4), turn 3 (a2+a4+a6)
        - Multiple capture entries: turn 1 (b1), turn 2 (b1+b2), turn 3 (b1+b2+b3)
        - Each capture should pair with minimum sufficient gather
        - All pairings should maintain army >= required_army invariant
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |
aG1  a2   a4   a6   b1   b2   b3   bG1
|    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            self.assertGreater(len(enriched_entries), 0, 'Should have enriched capture entries')

            for enriched in enriched_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'Partial gather+capture: gathered={enriched.gather_entry.gathered_army} '
                    f'must be >= required={enriched.capture_entry.required_army}'
                )

                self.assertEqual(
                    enriched.gather_index,
                    enriched.gather_entry.turns,
                    'Gather index should match gather entry turns'
                )

    # ------------------------------------------------------------------
    # Edge cases and boundary conditions
    # ------------------------------------------------------------------

    def test_postprocess__no_sufficient_gather__capture_not_enriched(self):
        """
        When a capture entry requires more army than any gather entry can provide,
        it should not appear in the enriched_capture_entries list.

        Layout:
          aG1  a2   b10  bG1

        Expected:
        - Capture turn 1 (b10) requires army=10
        - Gather turn 1 (a2) provides army=2
        - Capture should NOT be enriched (no sufficient gather support)
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a2   b10  bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            capture_entries = lookup_table.capture_entries_by_turn
            gather_entries = lookup_table.gather_entries_by_turn
            enriched_entries = lookup_table.enriched_capture_entries

            max_gather_army = max((g.gathered_army for g in gather_entries if g is not None), default=0)

            for enriched in enriched_entries:
                self.assertLessEqual(
                    enriched.capture_entry.required_army, max_gather_army,
                    'Enriched captures should only include those with sufficient gather support'
                )

            unsupported_captures = [
                c for c in capture_entries
                if c is not None and c.required_army > max_gather_army
            ]
            for unsupported in unsupported_captures:
                self.assertNotIn(
                    unsupported,
                    [e.capture_entry for e in enriched_entries],
                    f'Capture requiring {unsupported.required_army} army should not be enriched '
                    f'when max gather is only {max_gather_army}'
                )

    def test_postprocess__exact_army_match__pairs_correctly(self):
        """
        When gather army exactly matches required army, pairing should work correctly.

        Layout:
          aG1  a5   b5   bG1

        Expected:
        - Capture turn 1 (b5) requires army=5
        - Gather turn 1 (a5) provides army=5
        - Should pair successfully with exact match
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b5   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            exact_matches = [
                e for e in enriched_entries
                if e.gather_entry.gathered_army == e.capture_entry.required_army
            ]

            for enriched in exact_matches:
                self.assertEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    'Exact match pairing should work correctly'
                )

    def test_postprocess__multiple_border_pairs__independent_enrichment(self):
        """
        When there are multiple border pairs, each should have independent
        enriched capture entries.

        Layout:
          aG1  a5   b1   bG1
          a3   b2
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a5   b1   bG1
a3   b2
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'Each border pair should maintain gather >= required invariant independently'
                )

    # ------------------------------------------------------------------
    # EnrichedFlowTurnsEntry data structure tests
    # ------------------------------------------------------------------

    def test_enriched_entry__all_fields_populated_correctly(self):
        """
        Verify that all fields in EnrichedFlowTurnsEntry are populated correctly.

        Layout:
          aG1  a10  b3   bG1

        Expected:
        - capture_entry: FlowTurnsEntry for capturing b3
        - gather_entry: FlowTurnsEntry for gathering a10
        - gather_index: turn index of gather entry
        - combined_turn_cost: capture.turns + gather.turns
        - combined_value_density: capture.econ_value / combined_turn_cost
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a10  b3   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            for enriched in enriched_entries:
                self.assertIsNotNone(enriched.capture_entry, 'capture_entry should be populated')
                self.assertIsNotNone(enriched.gather_entry, 'gather_entry should be populated')
                self.assertIsInstance(enriched.gather_index, int, 'gather_index should be an integer')
                self.assertIsInstance(enriched.combined_turn_cost, int, 'combined_turn_cost should be an integer')
                self.assertIsInstance(enriched.combined_value_density, float, 'combined_value_density should be a float')

                self.assertEqual(
                    enriched.gather_index,
                    enriched.gather_entry.turns,
                    'gather_index should match gather_entry.turns'
                )

                self.assertEqual(
                    enriched.combined_turn_cost,
                    enriched.capture_entry.turns + enriched.gather_entry.turns,
                    'combined_turn_cost should be sum of capture and gather turns'
                )

                if enriched.combined_turn_cost > 0:
                    expected_density = enriched.capture_entry.econ_value / enriched.combined_turn_cost
                    self.assertAlmostEqual(
                        enriched.combined_value_density,
                        expected_density,
                        places=5,
                        msg='combined_value_density should be econ_value / combined_turn_cost'
                    )

    def test_enriched_entry__combined_value_density__monotonic_preference(self):
        """
        Verify that combined_value_density correctly reflects the value-per-turn metric.
        Higher density should indicate better efficiency.

        Layout:
          aG1  a2   a8   b1   b5   bG1

        Expected:
        - Different capture/gather combinations should produce different densities
        - Density should reflect econ_value / combined_turn_cost
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a2   a8   b1   b5   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            for enriched in enriched_entries:
                if enriched.combined_turn_cost > 0:
                    manual_density = enriched.capture_entry.econ_value / enriched.combined_turn_cost
                    self.assertAlmostEqual(
                        enriched.combined_value_density,
                        manual_density,
                        places=5,
                        msg='Density calculation should be consistent'
                    )

    # ------------------------------------------------------------------
    # _find_minimum_gather_support tests
    # ------------------------------------------------------------------

    def test_find_minimum_gather__returns_earliest_sufficient_gather(self):
        """
        _find_minimum_gather_support should return the earliest (minimum-turn) gather
        entry that provides sufficient army.

        Layout:
          aG1  a3   a5   a10  b8   bG1

        Expected:
        - For capture requiring 8 army, should return gather with a3+a5 (turn 2, army=8)
        - Should NOT return a3+a5+a10 (turn 3, army=18) even though it's sufficient
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a3   a5   a10  b8   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)

        for lookup_table in lookup_tables:
            gather_entries = lookup_table.gather_entries_by_turn

            for capture_entry in lookup_table.capture_entries_by_turn:
                if capture_entry is None or capture_entry.required_army == 0:
                    continue

                min_gather = expander._find_minimum_gather_support(capture_entry, gather_entries)

                if min_gather is not None:
                    self.assertGreaterEqual(
                        min_gather.gathered_army,
                        capture_entry.required_army,
                        'Minimum gather must provide sufficient army'
                    )

                    for earlier_turn in range(min_gather.turns):
                        earlier_gather = gather_entries[earlier_turn]
                        if earlier_gather is not None:
                            self.assertLess(
                                earlier_gather.gathered_army,
                                capture_entry.required_army,
                                f'No earlier gather should be sufficient if turn {min_gather.turns} is minimum'
                            )

    def test_find_minimum_gather__no_sufficient_gather__returns_none(self):
        """
        When no gather entry provides sufficient army, _find_minimum_gather_support
        should return None.

        Layout:
          aG1  a2   b20  bG1

        Expected:
        - Capture requiring 20 army
        - Gather providing only 2 army
        - Should return None
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a2   b20  bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)

        for lookup_table in lookup_tables:
            gather_entries = lookup_table.gather_entries_by_turn

            high_army_captures = [
                c for c in lookup_table.capture_entries_by_turn
                if c is not None and c.required_army > 10
            ]

            for capture_entry in high_army_captures:
                min_gather = expander._find_minimum_gather_support(capture_entry, gather_entries)

                max_gather_army = max((g.gathered_army for g in gather_entries if g is not None), default=0)

                if capture_entry.required_army > max_gather_army:
                    self.assertIsNone(
                        min_gather,
                        f'Should return None when no gather provides sufficient army: '
                        f'required={capture_entry.required_army}, max_gather={max_gather_army}'
                    )

    # ------------------------------------------------------------------
    # Neutral island scenarios
    # ------------------------------------------------------------------

    def test_postprocess__neutral_in_capture_path__pairs_correctly(self):
        """
        When neutral islands are in the capture path, they should be included
        in the capture entries and paired with appropriate gather entries.

        Layout:
          aG1  a10       b1   bG1

        Expected:
        - Capture turn 1: neutral (army=0)
        - Capture turn 2: neutral + b1 (army=1)
        - Should pair with gather entries correctly
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a10       b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries

            for enriched in enriched_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    'Neutral captures should still maintain gather >= required invariant'
                )

    # ------------------------------------------------------------------
    # Complex multi-island scenarios
    # ------------------------------------------------------------------

    def test_postprocess__complex_multi_island__all_pairings_valid(self):
        """
        Complex scenario with multiple friendly and enemy islands.
        Verify all enriched entries maintain the gather >= required invariant.

        Layout:
          aG1  a2   a3   a5   b1   b2   b4   bG1

        Expected:
        - Multiple gather options: a2, a2+a3, a2+a3+a5
        - Multiple capture options: b1, b1+b2, b1+b2+b4
        - All pairings should be valid
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |
aG1  a2   a3   a5   b1   b2   b4   bG1
|    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        total_enriched = 0
        for lookup_table in lookup_tables:
            enriched_entries = lookup_table.enriched_capture_entries
            total_enriched += len(enriched_entries)

            for enriched in enriched_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    'Complex scenario: all pairings must maintain gather >= required'
                )

                if enriched.capture_entry.turns > 0:
                    self.assertGreater(
                        enriched.combined_turn_cost, 0,
                        'Combined turn cost should be positive for non-trivial captures'
                    )

                if enriched.capture_entry.econ_value > 0:
                    self.assertGreater(
                        enriched.combined_value_density, 0,
                        'Value density should be positive when econ_value > 0'
                    )

        self.assertGreater(total_enriched, 0, 'Should have at least some enriched entries in complex scenario')

    def test_postprocess__vertical_map__multiple_paths(self):
        """
        Vertical map layout with multiple potential paths.

        Layout:
          aG1  b1  bG1
          a5   b2
          a3   b1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG1  b1   bG1
a5   b2
a3   b1
|    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    'Vertical map: gather >= required must hold'
                )

    # ------------------------------------------------------------------
    # Metadata and debug logging tests
    # ------------------------------------------------------------------

    def test_postprocess__enriched_list_stored_in_lookup_table(self):
        """
        Verify that enriched_capture_entries are properly stored in the lookup table.

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

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)

        for lookup_table in lookup_tables:
            self.assertEqual(
                0, len(lookup_table.enriched_capture_entries),
                'Before post-processing, enriched_capture_entries should be empty'
            )

        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            self.assertIsInstance(
                lookup_table.enriched_capture_entries, list,
                'enriched_capture_entries should be a list'
            )

            for enriched in lookup_table.enriched_capture_entries:
                self.assertIsInstance(
                    enriched, EnrichedFlowTurnsEntry,
                    'Each enriched entry should be an EnrichedFlowTurnsEntry instance'
                )

    # ------------------------------------------------------------------
    # 2x2 corner scenario — army validity and MKCP overlap guard
    # ------------------------------------------------------------------

    def test_postprocess__2x2_corner__army3__no_direct_single_tile_capture(self):
        """
        2x2 corner: blue (0,1) has army=3, blue (0,0) has army=2.
        From (0,1): leaves 2 behind, arrives at (1,1) with 2. (1,1) has army=2 → net=0, INVALID.
        The capture of a 2-army tile requires the mover to arrive with >2, i.e. gather >= 3.

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a3   (1,1)=b2

        Expected (Bug #2 guard):
        - No enriched entry may pair a required_army=2 capture with a gather_army < 3.
        - The army invariant (gather >= required) must hold for every enriched entry.
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

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'2x2 army=3: gather >= required must hold '
                    f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                )
                # Specifically: a 2-army tile capture needs arrive-army >2, i.e. gather >= 3
                if enriched.capture_entry.required_army == 2:
                    self.assertGreaterEqual(
                        enriched.gather_entry.gathered_army, 3,
                        'Capturing a 2-army tile from army=3 source is invalid (arrives with 2 vs 2)'
                    )

    def test_postprocess__2x2_corner__army4__single_tile_capture_enriched(self):
        """
        2x2 corner: blue (0,1) has army=4, blue (0,0) has army=2.
        From (0,1): leaves 3 behind, arrives at (1,1) with 3. (1,1) has army=2 → net=1 ✓ VALID.
        A single-tile capture is achievable and must appear in enriched entries.
        Capturing both tiles requires arriving at (1,0) with >2 after the (1,1) capture:
        4 total - 1 left behind - 2 captured = 1 remaining → cannot capture (1,0)=2. NOT valid.

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a4   (1,1)=b2

        Bug #1 guard: (1,1) and (1,0) must NOT both appear as independent top-level plan
        outputs for the same knapsack budget — they belong to the same capture path.
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

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        # Army invariant
        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'2x2 army=4: gather >= required '
                    f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                )

        # Single-tile capture must be achievable (army=4 > required=2)
        all_enriched = [e for lt in lookup_tables for e in lt.enriched_capture_entries]
        self.assertGreater(len(all_enriched), 0,
                           'army=4 is sufficient to capture a 2-army tile: enriched entries must exist')

        # Bug #1 guard: the two red tiles must not both appear as independent single-tile captures
        # from separate border pairs simultaneously (they share the same capture stream path).
        # Across ALL lookup tables, there must not be two DIFFERENT 1-tile capture entries
        # whose included_target_flow_nodes are disjoint (each capturing just one of the two tiles).
        one_tile_captures = [
            e for e in all_enriched
            if e.capture_entry.turns == 1 and len(e.capture_entry.included_target_flow_nodes) == 1
        ]
        if len(one_tile_captures) >= 2:
            # If two 1-tile captures exist, they must belong to the SAME border pair
            # (same lookup table), not to different border pairs capturing disjoint tiles.
            border_pair_ids = {
                (lt.border_pair.friendly_island_id, lt.border_pair.target_island_id)
                for lt in lookup_tables
                for e in lt.enriched_capture_entries
                if e in one_tile_captures
            }
            # Two separate border pairs both producing a single-tile capture is the MKCP overlap bug
            self.assertLessEqual(
                len(border_pair_ids), 1,
                f'Bug #1: two independent 1-tile capture border pairs found — these should be one group: {border_pair_ids}'
            )

    def test_postprocess__2x2_corner__army7__two_tile_capture_enriched(self):
        """
        2x2 corner: blue (0,1) has army=7.
        Full two-tile capture:
          (0,1)->7, leaves 6, captures (1,1) army=2 → 4 left. Leaves 3, arrives (1,0) with 3, 3>2 ✓.

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a7   (1,1)=b2

        Expected:
        - Two-tile capture (turns=2) must appear in enriched entries.
        - Its required_army must be paired with a gather providing >= 4 army.
        - Army invariant holds for all entries.
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

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        # Army invariant
        for lookup_table in lookup_tables:
            for enriched in lookup_table.enriched_capture_entries:
                self.assertGreaterEqual(
                    enriched.gather_entry.gathered_army,
                    enriched.capture_entry.required_army,
                    f'2x2 army=7: gather >= required '
                    f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                )

        all_enriched = [e for lt in lookup_tables for e in lt.enriched_capture_entries]
        two_tile_captures = [e for e in all_enriched if e.capture_entry.turns == 2]
        self.assertGreater(len(two_tile_captures), 0,
                           'army=7 must produce a valid two-tile capture enriched entry (turns=2)')
        for enriched in two_tile_captures:
            self.assertGreaterEqual(
                enriched.gather_entry.gathered_army, 4,
                'Two-tile capture of two 2-army tiles requires gathered_army >= 4'
            )

    def test_postprocess__upstream_gather_distance_must_be_accounted__not_overcapture(self):
        """
        Regression: the postprocessor must not pair a capture entry with a gather entry
        whose gather_turns is less than the number of islands being gathered.

        With desired_tile_island_size=1 every island is exactly 1 tile.  Each island in
        the upstream gather stream is 1 move-turn further from the border than the previous
        one.  Therefore gather_entry.turns must be >= len(included_friendly_flow_nodes).

        In the failing case the upstream stream contained a16 (col 5, 1 tile away from
        border) and a12 (col 0, 6 tiles away from border), yet gath_turns=2 was reported
        because _generate_gather_lookup_table only sums island.tile_count not path distance.
        This let the knapsack pick a plan that claimed to capture 8 enemy tiles (armyGath=-9
        in the render) using army that physically cannot arrive at the border in that time.

        Layout (1 row, 14 cols) with desired_tile_island_size=1:
          a12  a4  a2  a3  aG2  a16  b2  b2  b2  b2  b3  b3  b3  bG1
           0    1   2   3   4    5    6   7   8   9  10  11  12   13

        Key invariant (necessary condition for feasibility):
          gather_entry.turns >= len(gather_entry.included_friendly_flow_nodes)

        Because each of those islands is at least 1 move away from the next, the minimum
        walk time to consolidate N islands at the border is N turns.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |
a12  a4   a2   a3   aG2  a16  b2   b2   b2   b2   b3   b3   b3   bG1
|    |    |    |    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.enemyGeneral = enemyGeneral
        expander._ensure_flow_graph_exists(builder)

        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )
        lookup_tables = expander._process_flow_into_flow_army_turns(
            border_pairs, expander.flow_graph, target_crossable
        )
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        self.assertGreater(len(lookup_tables), 0, 'Should have at least one lookup table')

        # The border tile (a16 at col 5) is the friendly island directly adjacent to the enemy.
        # All gathered army must physically walk to this tile before it can be used.
        border_tile = map.GetTile(5, 0)

        all_enriched = [e for lt in lookup_tables for e in lt.enriched_capture_entries]
        self.assertGreater(len(all_enriched), 0, 'Should have at least one enriched entry')

        for enriched in all_enriched:
            if enriched.capture_entry.turns == 0:
                continue  # Turn-0 seed; skip

            # Find the maximum tile distance from the border across all gathered islands.
            # gather_entry.turns must be >= this distance: you cannot deliver army from a
            # tile that is D tiles away in fewer than D move-turns.
            max_dist = 0
            for flow_node in enriched.gather_entry.included_friendly_flow_nodes:
                for tile in flow_node.island.tile_set:
                    dist = abs(tile.x - border_tile.x) + abs(tile.y - border_tile.y)
                    if dist > max_dist:
                        max_dist = dist

            self.assertGreaterEqual(
                enriched.gather_entry.turns,
                max_dist,
                f'gather_turns={enriched.gather_entry.turns} < max_dist_to_border={max_dist}: '
                f'army from a tile {max_dist} steps away cannot arrive at the border in fewer turns. '
                f'cap_turns={enriched.capture_entry.turns}, '
                f'req={enriched.capture_entry.required_army}, '
                f'gathered={enriched.gather_entry.gathered_army}'
            )

    def test_postprocess__neutral_gap_between_friendly_and_enemy__traversal_cost_reflected_in_required_army(self):
        """
        Regression: two neutral tiles (army=0) sit between the friendly border island
        (a2@col4) and the first enemy tile (b2@col7).  The postprocessor must NOT produce
        an enriched capture entry for b2 with cap_turns < 3, because physically reaching
        b2 requires walking through col5 and col6 first.

        Layout (1 row, 11 cols) with desired_tile_island_size=1, fill_out_tiles=False:
          a3   aG4  a2   a2   a2   __   __   b2   N40  __   bG1
           0    1    2    3    4    5    6    7    8    9    10

        From the observed bug (before fix):
          - The capture stream sorted b2 before the neutrals (higher type_bonus),
            producing a spurious enriched entry with cap_t=1 req=4 gath=2 surplus=-2...
            wait, actually surplus=+2 — armyGath=2-4 < 0 so it wasn't valid?  No: the
            observed log showed "Capture turn 1 (army=2) paired with gather turn 1 (army=2)"
            with density=0.500, and the knapsack selected cap_t=3 req=6 gath=6 (surplus=0)
            as the best plan.  The materialize step then computes armyGath=1 (net true-value)
            rather than the correct -1, because only 3 a2 tiles are included — without aG4.

        Expected correct postprocessing output for the border pair (a2@col4 -> b2@col7):
          cap_t=1  req=2   (neut@5 only)        paired with gath_t=1  gath=2  (a2@col4)
          cap_t=2  req=3   (neut@5 + neut@6)    paired with gath_t=3  gath=6
          cap_t=3  req=6   (neut@5+6 + b2@7)    paired with gath_t=3  gath=6  surplus=0

        Key assertions:
        1. No enriched entry includes b2 with cap_turns < 3.
        2. The enriched entry for b2 (cap_turns=3) must have required_army=6.
        3. gathered_army for that entry must equal 6 (3 a2 tiles, no surplus).
        4. No enriched entry for b2 may have gathered_army > required_army
           (positive surplus would mean the neutral traversal was undercounted, since
           the 3 a2 tiles give exactly the needed army with zero spare).
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |
a3   aG4  a2   a2   a2             b2   N40       bG1
|    |    |    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)

        self.begin_capturing_logging()
        builder = TileIslandBuilder(map)
        builder.desired_tile_island_size = 1
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.log_debug = False
        expander.get_expansion_options(
            builder, general.player, enemyGeneral.player, turns=50,
            boardAnalysis=None, territoryMap=None, negativeTiles=None,
        )
        lookup_tables = expander.last_lookup_tables

        self.assertIsNotNone(lookup_tables)
        self.assertEqual(len(lookup_tables), 1, 'Expected exactly one lookup table for this single-border-pair map')

        lt = lookup_tables[0]

        # The border pair's friendly side must be a2@col4 (the rightmost friendly tile)
        self.assertEqual(lt.border_pair.friendly_island_id, builder.tile_island_lookup.raw[map.GetTile(4, 0).tile_index].unique_id,
                         'friendly_island_id must be a2@col4')
        # The border pair's target side must be the neutral at col5 — the island directly adjacent to the friendly border.
        self.assertEqual(lt.border_pair.target_island_id, builder.tile_island_lookup.raw[map.GetTile(5, 0).tile_index].unique_id,
                         'target_island_id must be the neutral at col5 — the island directly adjacent to the friendly border')

        """
        |    |    |    |    |    |    |    |    |    |    |
        a3   aG4  a2   a2   a2             b2   N40       bG1
        |    |    |    |    |    |    |    |    |    |    |
                """
        # --- Exact enriched pairings (this is a PostProcessing test — assert on enriched output) ---
        #
        # The postprocessor must pair each capture entry with the minimum-turn gather that
        # provides gathered_army >= required_army.
        #
        # Gather stream (from the flow graph, upstream from a2@col4):
        #   gath_t=0: seed, gathered=0
        #   gath_t=1: [a2@col4],          gathered=2
        #   gath_t=3: [a2@col4, a2+a2@col2-3],  gathered=6
        #   gath_t=4: [col4, col2-3, aG4@col1], gathered=10
        #
        # Capture stream (downstream from neut@col5 outward):
        #   cap_t=0: seed, req=0
        #   cap_t=1: [neut@col5],              req=0+1+1=2,  econ=1.0
        #   cap_t=2: [neut@col5, neut@col6],   req=0+2+1=3,  econ=2.0
        #   cap_t=3: [neut@5, neut@6, b2@7],   req=2+3+1=6,  econ=4.2
        #
        # Gather stream army-at-border after deducting within-gather traversal cost:
        #   gath_t=0: seed,                          gathered=0
        #   gath_t=1: [col4],                        gathered=2  (depth=1, cost=0,  2-0=2)
        #   gath_t=3: [col4, col2-col3(2-tile)],     gathered=5  (col2-3: depth=3, cost=1, 4-1=3; 2+3=5)
        #   gath_t=4: [col4, col2-col3, aG4@col1],   gathered=6  (aG4: depth=4, cost=3, 4-3=1; 5+1=6)
        #
        # Expected pairings:
        #   e0: cap_t=0 req=0  -> gath_t=0 gath=0
        #   e1: cap_t=1 req=2  -> gath_t=1 gath=2   (col4 alone covers it)
        #   e2: cap_t=2 req=3  -> gath_t=3 gath=5   (gath_t=1=2 insufficient; t=3 gives 5>=3)
        #   e3: cap_t=3 req=6  -> gath_t=4 gath=6   (gath_t=3=5 insufficient; t=4 adds aG4 -> 6>=6)
        enriched = lt.enriched_capture_entries
        self.assertEqual(len(enriched), 4, f'Expected exactly 4 enriched entries (t=0,1,2,3), got {len(enriched)}')
        e0, e1, e2, e3 = enriched
        """
        |    |    |    |    |    |    |    |    |    |    |
        a3   aG4  a2   a2   a2             b2   N40       bG1
        |    |    |    |    |    |    |    |    |    |    |
                """

        self.assertEqual(e0.capture_entry.turns, 0)
        self.assertEqual(e0.gather_entry.turns, 0)

        self.assertEqual(e1.capture_entry.turns, 1)
        self.assertEqual(e1.capture_entry.required_army, 2)
        self.assertEqual(e1.gather_entry.turns, 1)
        self.assertEqual(e1.gather_entry.gathered_army, 2)

        self.assertEqual(e2.capture_entry.turns, 2)
        self.assertEqual(e2.capture_entry.required_army, 3)
        self.assertEqual(e2.gather_entry.turns, 3,
                         'cap_t=2 req=3: gath_t=1 gives 2 (insufficient); gath_t=3 gives 5')
        self.assertEqual(e2.gather_entry.gathered_army, 5,
                         'gath_t=3: col4(2) + col2-col3(4-1traversal=3) = 5 army at border')

        """
        |    |    |    |    |    |    |    |    |    |    |
        a3   aG4  a2   a2   a2             b2   N40       bG1
        |    |    |    |    |    |    |    |    |    |    |
                """
        self.assertEqual(e3.capture_entry.turns, 3)
        self.assertEqual(e3.capture_entry.required_army, 6)
        # gath_t=3 only delivers 5 army at the border (insufficient for req=6).
        # gath_t=4 adds aG4@col1 (army=4, depth=4, traversal_cost=3 -> 1 net) -> 5+1=6.
        self.assertEqual(e3.gather_entry.turns, 4,
                         'cap_t=3 req=6: gath_t=3 delivers only 5; must use gath_t=4 (adds aG4)')
        self.assertEqual(e3.gather_entry.gathered_army, 6,
                         'gath_t=4: col4(2) + col2-3(3) + aG4(4-3=1) = 6 army at border')
        aG4_tile = map.GetTile(1, 0)
        e3_gather_tiles = {tl for n in e3.gather_entry.included_friendly_flow_nodes for tl in n.island.tile_set}
        self.assertIn(aG4_tile, e3_gather_tiles,
                      f'gath_t=4 must include aG4@col1, got {sorted((t.x,t.y) for t in e3_gather_tiles)}')

    def test_postprocess__empty_lookup_tables__no_crash(self):
        """
        Verify that post-processing handles empty lookup tables gracefully.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |
aG1  bG1
|    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder, lookup_tables = self._setup_expander_with_lookup_tables(map, general, enemyGeneral)

        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        for lookup_table in lookup_tables:
            self.assertIsInstance(lookup_table.enriched_capture_entries, list)
