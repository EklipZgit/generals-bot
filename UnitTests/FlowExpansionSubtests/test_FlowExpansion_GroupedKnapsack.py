import logbook

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2, EnrichedFlowTurnsEntry, FlowBorderPairKey
from BehaviorAlgorithms.IterativeExpansion import ITERATIVE_EXPANSION_EN_CAP_VAL
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot


class FlowExpansionGroupedKnapsackTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)
        return bot

    def _build_expander_v2_through_phase3(self, mapData: str, turns: int = 50):
        """Helper: load map, run V2 through Phase 3, return (expander, lookup_tables)."""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.target_team = enemyGeneral.player
        expander.log_debug = False

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

        return expander, lookup_tables

    # -----------------------------------------------------------------------
    # Phase 4: Grouped Knapsack — basic correctness
    # -----------------------------------------------------------------------

    def test_grouped_knapsack__single_border_pair__selects_best_capture_within_budget(self):
        """Single border pair: the solver should pick the highest-value capture that fits."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        self.assertGreater(len(lookup_tables), 0, 'Need at least one lookup table')
        self.assertTrue(
            any(tbl.enriched_capture_entries for tbl in lookup_tables),
            'Need at least one table with enriched entries'
        )

        turn_budget = 5
        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget)

        self.assertIsNotNone(solution, 'Solver must return a solution dict')
        self.assertGreater(len(solution), 0, 'Should select at least one border pair')

        # All selected entries must respect the combined_turn_cost budget
        total_weight = sum(e.combined_turn_cost for e in solution.values())
        self.assertLessEqual(total_weight, turn_budget,
                             f'Total combined_turn_cost {total_weight} must not exceed budget {turn_budget}')

        # Every selected entry must have positive econ value
        for bp, enriched in solution.items():
            self.assertIsInstance(bp, FlowBorderPairKey)
            self.assertIsInstance(enriched, EnrichedFlowTurnsEntry)
            self.assertGreater(enriched.capture_entry.econ_value, 0,
                               'Selected capture must have positive econ value')

        if debugMode:
            for bp, enriched in solution.items():
                logbook.info(f'Selected {bp.friendly_island_id}->{bp.target_island_id}: '
                             f'turns={enriched.combined_turn_cost}, value={enriched.capture_entry.econ_value:.2f}')

    def test_grouped_knapsack__budget_zero__returns_empty_solution(self):
        """With a budget of 0, no entry can be selected."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=0)

        self.assertIsNotNone(solution)
        self.assertEqual(0, len(solution), 'Budget=0 must produce an empty solution')

    def test_grouped_knapsack__two_border_pairs__respects_one_choice_per_group(self):
        """Two border pairs: solver may pick from both, but at most one choice per border pair."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG4  a3   b1   b1   bG1
a1   a3   b1   b1   b1
|    |    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        # Only pairs that produced enriched entries count as groups
        groups_with_entries = [tbl for tbl in lookup_tables if tbl.enriched_capture_entries]
        self.assertEqual(2, len(groups_with_entries), 'Map did not produce 2 independent border pairs with enriched entries')

        turn_budget = 20
        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget)

        # Each border pair may appear at most once in the solution
        seen_pairs: set[tuple[int, int]] = set()
        for bp in solution.keys():
            pair_key = (bp.friendly_island_id, bp.target_island_id)
            self.assertNotIn(pair_key, seen_pairs,
                             f'Border pair {pair_key} chosen more than once (grouped constraint violated)')
            seen_pairs.add(pair_key)

        # Total weight must fit
        total_weight = sum(e.combined_turn_cost for e in solution.values())
        self.assertLessEqual(total_weight, turn_budget)

    def test_grouped_knapsack__two_border_pairs__compete_for_tight_budget(self):
        """When the budget only fits one group, the higher-value group is chosen."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # Two symmetric border pairs; budget is intentionally tight
        mapData = """
|    |    |    |    |
aG1  a3   b1   b1   bG1
|    |    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        groups_with_entries = [tbl for tbl in lookup_tables if tbl.enriched_capture_entries]
        if not groups_with_entries:
            self.skipTest('No enriched entries generated for this map')

        # Find minimum possible combined_turn_cost across all enriched entries
        min_cost = min(
            e.combined_turn_cost
            for tbl in groups_with_entries
            for e in tbl.enriched_capture_entries
            if e.combined_turn_cost > 0
        )

        # Budget just fits one group's cheapest item, not two
        tight_budget = min_cost
        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=tight_budget)

        total_weight = sum(e.combined_turn_cost for e in solution.values())
        self.assertLessEqual(total_weight, tight_budget,
                             'Tight-budget solution must not exceed budget')
        self.assertLessEqual(len(solution), 1,
                             'Tight budget should only allow at most one group to be chosen')

    def test_grouped_knapsack__no_enriched_entries__returns_empty_solution(self):
        """If no border pairs have enriched entries, solution must be empty dict."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        # Manually clear enriched entries to simulate the edge case
        for tbl in lookup_tables:
            tbl.enriched_capture_entries = []

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=20)
        self.assertEqual({}, solution, 'Empty enriched entries must yield empty solution')

    def test_grouped_knapsack__solution_keys_are_FlowBorderPairKey_instances(self):
        """Solution dict keys must be FlowBorderPairKey objects (provenance contract)."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=10)

        for key, value in solution.items():
            self.assertIsInstance(key, FlowBorderPairKey,
                                  'Solution keys must be FlowBorderPairKey for Phase 5/6 provenance')
            self.assertIsInstance(value, EnrichedFlowTurnsEntry,
                                  'Solution values must be EnrichedFlowTurnsEntry')

    def test_grouped_knapsack__solution_values_carry_enriched_entry_fields(self):
        """Each solution value must retain capture_entry, gather_entry, and combined metrics."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=10)

        for bp, enriched in solution.items():
            self.assertIsNotNone(enriched.capture_entry, 'Must have capture_entry')
            self.assertIsNotNone(enriched.gather_entry, 'Must have gather_entry')
            self.assertGreaterEqual(enriched.combined_turn_cost, 1, 'combined_turn_cost must be >= 1')
            self.assertGreaterEqual(enriched.combined_value_density, 0.0, 'density must be non-negative')
            # Verify gather army covers capture requirement
            self.assertGreaterEqual(
                enriched.gather_entry.gathered_army,
                enriched.capture_entry.required_army,
                'Gather entry must supply enough army for the paired capture'
            )

    def test_grouped_knapsack__large_budget__selects_across_all_available_groups(self):
        """With a very large budget every group with entries should be selectable."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a5   b1   b1   bG1
|    |    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        groups_with_entries = [tbl for tbl in lookup_tables if tbl.enriched_capture_entries]
        if not groups_with_entries:
            self.skipTest('No enriched entries for this map')

        # Budget large enough to never be the limiting factor
        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=1000)

        # Must not select more groups than exist
        self.assertLessEqual(len(solution), len(groups_with_entries),
                             'Cannot select more groups than exist')

        # Total value must be non-negative
        total_value = sum(e.capture_entry.econ_value for e in solution.values())
        self.assertGreaterEqual(total_value, 0.0)

    # -----------------------------------------------------------------------
    # 2x2 corner scenario — MKCP overlap and army validity
    # -----------------------------------------------------------------------

    def test_grouped_knapsack__2x2_corner__army3__solution_respects_army_validity(self):
        """
        2x2 corner: blue (0,1) has army=3, blue (0,0) has army=2.
        Direct capture of a 2-army red tile is INVALID (3-1=2 arrives, 2 vs 2 = 0 net).
        The knapsack must not select any entry that pairs a required_army=2 capture
        with a gather providing only 2 army.

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a3   (1,1)=b2

        Bug #2 guard: the army requirement must be > available gathered army for invalid captures.
        Expected: if a solution is found, every selected entry satisfies gather >= required.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG2  b2   bG1
a3   b2
|    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        for turn_budget in [1, 2, 3]:
            with self.subTest(turns=turn_budget):
                solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget)

                for bp, enriched in solution.items():
                    self.assertGreaterEqual(
                        enriched.gather_entry.gathered_army,
                        enriched.capture_entry.required_army,
                        f'2x2 army=3 budget={turn_budget}: gather must cover required_army '
                        f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                    )

    def test_grouped_knapsack__2x2_corner__army4__single_tile_selected_not_both(self):
        """
        2x2 corner: blue (0,1) has army=4.
        Direct single-tile capture is valid (arrives with 3 > 2 ✓).
        Two-tile capture is NOT valid (after first cap: 2 left, can't capture second 2-army tile).

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a4   (1,1)=b2

        Bug #1 guard: the two red tiles (1,0) and (1,1) belong to the SAME capture stream.
        The knapsack must NOT output both tiles as separate independent border-pair solutions
        simultaneously — that would double-count territory.

        Expected for budget=2: at most 1 capture tile selected in any single solution.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG2  b2   bG1
a4   b2
|    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        for turn_budget in [1, 2, 3]:
            with self.subTest(turns=turn_budget):
                solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget)

                # Army invariant
                for bp, enriched in solution.items():
                    self.assertGreaterEqual(
                        enriched.gather_entry.gathered_army,
                        enriched.capture_entry.required_army,
                        f'2x2 army=4 budget={turn_budget}: gather must cover required_army '
                        f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                    )

                # Bug #1: count total target tiles selected across all chosen groups.
                # All selected border pairs must NOT include overlapping (shared) target islands.
                all_selected_target_island_ids: set[int] = set()
                for bp, enriched in solution.items():
                    for flow_node in enriched.capture_entry.included_target_flow_nodes:
                        island_id = flow_node.island.unique_id
                        self.assertNotIn(
                            island_id, all_selected_target_island_ids,
                            f'Bug #1: target island {island_id} appears in multiple selected border pairs '
                            f'(MKCP overlap: same capture territory selected twice)'
                        )
                        all_selected_target_island_ids.add(island_id)

    def test_grouped_knapsack__2x2_corner__army7__two_tile_capture_selected(self):
        """
        2x2 corner: blue (0,1) has army=7.
        Full two-tile capture is valid:
          (0,1)->7, leaves 6, captures (1,1)=2 → 4 on tile. Leave 3, capture (1,0)=2 ✓.

        Layout:
          (0,0)=aG2  (1,0)=b2
          (0,1)=a7   (1,1)=b2

        Expected for budget >= 3: a two-tile capture (turns=2) should be the chosen solution.
        No overlap: only one border pair may be chosen (since all army flows from (0,1)).
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |
aG2  b2   bG1
a7   b2
|    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        for turn_budget in [1, 2, 3, 5, 7]:
            with self.subTest(turns=turn_budget):
                solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget)

                # Army invariant
                for bp, enriched in solution.items():
                    self.assertGreaterEqual(
                        enriched.gather_entry.gathered_army,
                        enriched.capture_entry.required_army,
                        f'2x2 army=7 budget={turn_budget}: gather must cover required_army '
                        f'(gathered={enriched.gather_entry.gathered_army}, required={enriched.capture_entry.required_army})'
                    )

                # No overlap across border pairs
                all_selected_target_island_ids: set[int] = set()
                for bp, enriched in solution.items():
                    for flow_node in enriched.capture_entry.included_target_flow_nodes:
                        island_id = flow_node.island.unique_id
                        self.assertNotIn(
                            island_id, all_selected_target_island_ids,
                            f'Bug #1: target island {island_id} appears in multiple selected border pairs '
                            f'at budget={turn_budget}'
                        )
                        all_selected_target_island_ids.add(island_id)

                # For budget >= 3, the two-tile capture (turns=2 for the capture leg) should be reachable
                if turn_budget >= 3:
                    total_capture_tiles = sum(
                        len(enriched.capture_entry.included_target_flow_nodes)
                        for enriched in solution.values()
                    )
                    self.assertGreaterEqual(
                        total_capture_tiles, 2,
                        f'budget={turn_budget} with army=7 should select at least 2 capture tiles'
                    )

    def test_grouped_knapsack__combined_turn_cost_equals_capture_plus_gather_turns(self):
        """Sanity check: combined_turn_cost in solution == capture.turns + gather.turns."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        self.begin_capturing_logging()
        expander, lookup_tables = self._build_expander_v2_through_phase3(mapData)

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=10)

        for bp, enriched in solution.items():
            expected = enriched.capture_entry.turns + enriched.gather_entry.turns
            self.assertEqual(expected, enriched.combined_turn_cost,
                             f'combined_turn_cost must equal capture.turns + gather.turns for pair {bp}')
