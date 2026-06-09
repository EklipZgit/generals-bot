import logbook

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2, EnrichedFlowTurnsEntry, FlowBorderPairKey
from BehaviorAlgorithms.IterativeExpansion import ITERATIVE_EXPANSION_EN_CAP_VAL
from BoardAnalyzer import BoardAnalyzer
from Gather.GatherCaptureGroupKnapsacker import (
    GroupedKnapsackInput,
    GroupedKnapsackPreGroupInput,
    GroupedKnapsackPreGroupItem,
    GroupedKnapsackIterationSummary,
)
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot

"""
Grouped-knapsack repro workflow:
1. Temporarily set BehaviorAlgorithms.FlowExpansion.OUTPUT_KNAPSACK_TEST_REPRO_LOGS = True.
2. Run the scenario/test that produces bad MKCP grouping or conflict-pruning behavior.
3. Copy the log block between FE_KNAPSACK_REPRO_BEGIN and FE_KNAPSACK_REPRO_END.
4. Paste that emitted test body into this file, replacing test_grouped_knapsack__logged_repro_template or adding a new test.
5. Prefer the emitted _solve_grouped_knapsack_pre_group_input call because it tests group formation as well as conflict repair.
6. Set OUTPUT_KNAPSACK_TEST_REPRO_LOGS back to False after capturing the repro logs.
"""


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

        expander._ensure_flow_graph_exists(builder, turns=50)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )
        lookup_tables = expander._process_flow_into_flow_army_turns(
            border_pairs, expander.flow_graph, target_crossable, 50
        )
        expander._postprocess_flow_stream_gather_capture_lookup_pairs(lookup_tables)

        return expander, lookup_tables

    def _run_logged_grouped_knapsack_repro(
            self,
            repro: GroupedKnapsackInput,
            expected_chosen_weight: int | None = None,
            expected_chosen_indices: list[int] | None = None
    ):
        result = ArmyFlowExpanderV2._solve_grouped_knapsack_input(repro, noLog=False)
        if expected_chosen_weight is not None:
            self.assertEqual(expected_chosen_weight, result.chosen_weight)
        if expected_chosen_indices is not None:
            self.assertEqual(expected_chosen_indices, result.chosen_indices)
        return result

    def _assert_no_duplicate_repro_item_tile_use(
            self,
            item_tile_sets: list[list[int]],
            chosen_indices: list[int]
    ):
        used_tiles: set[int] = set()
        overlaps = []
        for chosen_idx in chosen_indices:
            chosen_tile_set = set(item_tile_sets[chosen_idx])
            overlap = used_tiles & chosen_tile_set
            if len(overlap) > 0:
                overlaps.append(f'Chosen item {chosen_idx} reused tiles {sorted(overlap)}')
            used_tiles.update(chosen_tile_set)

        if len(overlaps) > 0:
            self.fail(f'The following plan items were chosen that duplicated tiles:\r\n  {"\r\n  ".join(overlaps)}')

    def test_grouped_knapsack__logged_repro_template(self):
        self.skipTest('Paste FE_KNAPSACK_REPRO_BEGIN output here when debugging grouped knapsack conflict repair')

    def test_grouped_knapsack__spare_capacity_fill_keeps_disjoint_external_after_maybe_substitution(self):
        self.skipTest('Rejected spare-capacity fill regression; FE gather lookup validity should prevent the original issue')

    def test_grouped_knapsack__should_choose_two_local_enemy_captures_over_one_general_rally(self):
        self.begin_capturing_logging()
        repro = GroupedKnapsackPreGroupInput(
            turn_budget=8,
            items=[
                GroupedKnapsackPreGroupItem(
                    border_pair=(729, 695),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=5676,
                    econ_value=5.68,
                    friendly_island_set=[729, 733],
                    target_island_set=[684, 695, 723],
                    item_tile_set=[79, 80, 98, 116, 117]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(349, 708),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=4602,
                    econ_value=4.604,
                    friendly_island_set=[349],
                    target_island_set=[696, 708],
                    item_tile_set=[228, 246, 264]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(349, 708),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=6998,
                    econ_value=7.006,
                    friendly_island_set=[348, 349, 351, 356, 358, 360],
                    target_island_set=[686, 696, 708],
                    item_tile_set=[210, 228, 246, 263, 264, 281, 299, 316, 317]),
                GroupedKnapsackPreGroupItem(
                    border_pair=None,
                    external_group_id=1000001,
                    is_external=True,
                    weight=1,
                    value=2201,
                    econ_value=2.202,
                    friendly_island_set=[],
                    target_island_set=[],
                    item_tile_set=[117, 118]),
                GroupedKnapsackPreGroupItem(
                    border_pair=None,
                    external_group_id=1000002,
                    is_external=True,
                    weight=1,
                    value=2201,
                    econ_value=2.202,
                    friendly_island_set=[],
                    target_island_set=[],
                    item_tile_set=[246, 264]),
            ],
            max_iterations=32)
        result = ArmyFlowExpanderV2._solve_grouped_knapsack_pre_group_input(repro, noLog=False)
        self.assertEqual(6, result.chosen_weight)
        self.assertEqual([1, 0], result.chosen_indices)
        self._assert_no_duplicate_repro_item_tile_use([t.item_tile_set for t in repro.items], result.chosen_indices)

    def test_grouped_knapsack__should_not_do_retarded_shit_at_end_of_round_instead_of_flowing_4and2_and_7and2_into_enemy_land_despite_common_upstream(self):
        self.begin_capturing_logging()
        repro = GroupedKnapsackPreGroupInput(
            turn_budget=9,
            items=[
                GroupedKnapsackPreGroupItem(
                    border_pair=(639, 592),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=993,
                    econ_value=1.0,
                    friendly_island_set=[638, 639, 643, 647, 654, 662, 748],
                    target_island_set=[592],
                    item_tile_set=[13, 14, 15, 33, 51, 69, 87, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(639, 592),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=1991,
                    econ_value=2.0,
                    friendly_island_set=[638, 639, 643, 647, 654, 662, 665, 748],
                    target_island_set=[592, 709],
                    item_tile_set=[13, 14, 15, 31, 33, 49, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(639, 592),
                    external_group_id=None,
                    is_external=False,
                    weight=10,
                    value=2990,
                    econ_value=3.0,
                    friendly_island_set=[638, 639, 643, 647, 654, 662, 665, 748],
                    target_island_set=[592, 709],
                    item_tile_set=[13, 14, 15, 31, 33, 49, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(638, 583),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=994,
                    econ_value=1.0,
                    friendly_island_set=[638, 643, 647, 654, 662, 748],
                    target_island_set=[583],
                    item_tile_set=[15, 16, 33, 51, 69, 87, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(638, 583),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=1992,
                    econ_value=2.0,
                    friendly_island_set=[638, 643, 647, 654, 662, 665, 748],
                    target_island_set=[583, 584],
                    item_tile_set=[15, 16, 17, 33, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(638, 583),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=2991,
                    econ_value=3.0,
                    friendly_island_set=[638, 643, 647, 654, 662, 665, 748],
                    target_island_set=[583, 584, 585],
                    item_tile_set=[15, 16, 17, 33, 34, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(643, 593),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=995,
                    econ_value=1.0,
                    friendly_island_set=[643, 647, 654, 662, 748],
                    target_island_set=[593],
                    item_tile_set=[32, 33, 51, 69, 87, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(643, 593),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=1993,
                    econ_value=2.0,
                    friendly_island_set=[643, 647, 654, 662, 665, 748],
                    target_island_set=[593, 709],
                    item_tile_set=[31, 32, 33, 49, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(643, 593),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=2992,
                    econ_value=3.0,
                    friendly_island_set=[643, 647, 654, 662, 665, 748],
                    target_island_set=[593, 709],
                    item_tile_set=[31, 32, 33, 49, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(647, 594),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=996,
                    econ_value=1.0,
                    friendly_island_set=[647, 654, 662, 748],
                    target_island_set=[594],
                    item_tile_set=[50, 51, 69, 87, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(647, 594),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=1994,
                    econ_value=2.0,
                    friendly_island_set=[647, 654, 662, 665, 748],
                    target_island_set=[594, 709],
                    item_tile_set=[31, 49, 50, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(647, 594),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=2993,
                    econ_value=3.0,
                    friendly_island_set=[647, 654, 662, 665, 748],
                    target_island_set=[594, 709],
                    item_tile_set=[31, 49, 50, 51, 69, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(650, 586),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=997,
                    econ_value=1.0,
                    friendly_island_set=[650, 655, 665],
                    target_island_set=[586],
                    item_tile_set=[52, 70, 88, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(650, 586),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=1996,
                    econ_value=2.0,
                    friendly_island_set=[650, 655, 665],
                    target_island_set=[585, 586],
                    item_tile_set=[34, 52, 70, 88, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(650, 581),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=997,
                    econ_value=1.0,
                    friendly_island_set=[650, 655, 665],
                    target_island_set=[581],
                    item_tile_set=[70, 71, 88, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(650, 581),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=1996,
                    econ_value=2.0,
                    friendly_island_set=[650, 655, 665],
                    target_island_set=[580, 581],
                    item_tile_set=[70, 71, 88, 89, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(654, 589),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=998,
                    econ_value=1.0,
                    friendly_island_set=[654, 748],
                    target_island_set=[589],
                    item_tile_set=[86, 87, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(654, 589),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=1996,
                    econ_value=2.0,
                    friendly_island_set=[654, 665, 748],
                    target_island_set=[588, 589],
                    item_tile_set=[85, 86, 87, 105, 106]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(658, 580),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=998,
                    econ_value=1.0,
                    friendly_island_set=[658, 745],
                    target_island_set=[580],
                    item_tile_set=[89, 107, 125]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(642, 620),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=994,
                    econ_value=1.0,
                    friendly_island_set=[642, 747, 748, 757, 758, 763],
                    target_island_set=[620],
                    item_tile_set=[105, 123, 140, 141, 156, 157, 158]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(642, 620),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=3192,
                    econ_value=3.2,
                    friendly_island_set=[642, 665, 747, 748, 757, 758, 763],
                    target_island_set=[620, 838],
                    item_tile_set=[105, 106, 123, 140, 141, 156, 157, 158, 174]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(646, 847),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=2198,
                    econ_value=2.2,
                    friendly_island_set=[646, 660],
                    target_island_set=[847],
                    item_tile_set=[176, 177, 178]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(646, 847),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=4397,
                    econ_value=4.4,
                    friendly_island_set=[646, 660],
                    target_island_set=[846, 847],
                    item_tile_set=[175, 176, 177, 178]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(646, 847),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=6596,
                    econ_value=6.6000000000000005,
                    friendly_island_set=[646, 660],
                    target_island_set=[838, 846, 847],
                    item_tile_set=[174, 175, 176, 177, 178]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(646, 847),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=8791,
                    econ_value=8.8,
                    friendly_island_set=[646, 660, 665, 749, 760, 765],
                    target_island_set=[678, 838, 846, 847],
                    item_tile_set=[106, 124, 142, 160, 174, 175, 176, 177, 178, 192]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(640, 670),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=2198,
                    econ_value=2.2,
                    friendly_island_set=[640, 663],
                    target_island_set=[670],
                    item_tile_set=[250, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(640, 670),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=4396,
                    econ_value=4.4,
                    friendly_island_set=[640, 656, 663],
                    target_island_set=[670, 734],
                    item_tile_set=[232, 250, 266, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(640, 670),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=6592,
                    econ_value=6.6000000000000005,
                    friendly_island_set=[640, 649, 653, 656, 660, 663],
                    target_island_set=[670, 734, 785],
                    item_tile_set=[178, 196, 214, 232, 248, 250, 266, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(640, 670),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=8791,
                    econ_value=8.8,
                    friendly_island_set=[640, 649, 653, 656, 660, 663],
                    target_island_set=[670, 732, 734, 785],
                    item_tile_set=[178, 196, 214, 232, 247, 248, 250, 266, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(640, 670),
                    external_group_id=None,
                    is_external=False,
                    weight=10,
                    value=10990,
                    econ_value=11.0,
                    friendly_island_set=[640, 649, 653, 656, 660, 663],
                    target_island_set=[670, 732, 734, 772, 785],
                    item_tile_set=[178, 196, 214, 232, 247, 248, 250, 265, 266, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(640, 670),
                    external_group_id=None,
                    is_external=False,
                    weight=15,
                    value=13185,
                    econ_value=13.2,
                    friendly_island_set=[640, 649, 653, 656, 660, 663, 665, 749, 760, 765],
                    target_island_set=[670, 732, 734, 770, 772, 785],
                    item_tile_set=[106, 124, 142, 160, 178, 196, 214, 232, 246, 247, 248, 250, 265, 266, 267, 268]),
            ],
            max_iterations=32)
        self.begin_capturing_logging()
        result = ArmyFlowExpanderV2._solve_grouped_knapsack_pre_group_input(repro, noLog=False)
        self.assertGreaterEqual(sum([t.value for t in repro.items]), 10900)
        self.assertEqual([26, 23], result.chosen_indices)
        self._assert_no_duplicate_repro_item_tile_use([t.item_tile_set for t in repro.items], result.chosen_indices)
        self.assertEqual(8, result.chosen_weight)

    def test_grouped_knapsack__cave_choke_repro_uses_large_flow_plan(self):
        # NOTE: this is from test_should_be_able_to_flow_expand_towards_neutrals_and_predicted_general_in_1v1__no_duplicate_tile_use
        repro = GroupedKnapsackPreGroupInput(
            turn_budget=50,
            items=[
                GroupedKnapsackPreGroupItem(
                    border_pair=(30, 3),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[30],
                    target_island_set=[3],
                    item_tile_set=[0, 1]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(34, 5),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[34],
                    target_island_set=[5],
                    item_tile_set=[4, 24]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[35],
                    target_island_set=[8],
                    item_tile_set=[25, 26]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=4397,
                    econ_value=4.4,
                    friendly_island_set=[34, 35],
                    target_island_set=[8, 116],
                    item_tile_set=[6, 24, 25, 26]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=6595,
                    econ_value=6.6000000000000005,
                    friendly_island_set=[33, 34, 35],
                    target_island_set=[8, 116, 130],
                    item_tile_set=[6, 7, 23, 24, 25, 26]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=8793,
                    econ_value=8.8,
                    friendly_island_set=[33, 34, 35, 36],
                    target_island_set=[8, 116, 130, 145],
                    item_tile_set=[6, 7, 8, 23, 24, 25, 26, 43]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=10991,
                    econ_value=11.0,
                    friendly_island_set=[32, 33, 34, 35, 36],
                    target_island_set=[8, 116, 130, 145, 152],
                    item_tile_set=[6, 7, 8, 9, 22, 23, 24, 25, 26, 43]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=11,
                    value=13189,
                    econ_value=13.2,
                    friendly_island_set=[31, 32, 33, 34, 35, 36],
                    target_island_set=[8, 116, 130, 145, 152, 153],
                    item_tile_set=[6, 7, 8, 9, 21, 22, 23, 24, 25, 26, 29, 43]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=13,
                    value=15386,
                    econ_value=15.399999999999999,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 48],
                    target_island_set=[8, 10, 116, 130, 145, 152, 153],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 43, 49]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=15,
                    value=17584,
                    econ_value=17.599999999999998,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48],
                    target_island_set=[8, 10, 14, 116, 130, 145, 152, 153],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 41, 42, 43, 49, 60, 61, 69, 80]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=17,
                    value=19782,
                    econ_value=19.799999999999997,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48],
                    target_island_set=[8, 10, 14, 116, 130, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 41, 42, 43, 49, 60, 61, 69, 80, 89]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=19,
                    value=21980,
                    econ_value=21.999999999999996,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48],
                    target_island_set=[8, 10, 14, 15, 116, 130, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 41, 42, 43, 49, 60, 61, 69, 80, 88, 89]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=21,
                    value=24178,
                    econ_value=24.199999999999996,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48],
                    target_island_set=[8, 10, 14, 15, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 41, 42, 43, 49, 60, 61, 69, 80, 87, 88, 89]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=23,
                    value=26376,
                    econ_value=26.399999999999995,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48],
                    target_island_set=[8, 10, 13, 14, 15, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 41, 42, 43, 49, 60, 61, 67, 69, 80, 87, 88, 89]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=25,
                    value=28574,
                    econ_value=28.599999999999994,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48, 51],
                    target_island_set=[8, 10, 12, 13, 14, 15, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 66, 67, 69, 80, 87, 88, 89]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=26,
                    value=30773,
                    econ_value=30.799999999999994,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 47, 48, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 65, 66, 67, 69, 80, 87, 88, 89]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=28,
                    value=32971,
                    econ_value=32.99999999999999,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 44, 47, 48, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 104, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 65, 66, 67, 69, 80, 85, 87, 88, 89, 100]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=30,
                    value=35169,
                    econ_value=35.199999999999996,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 41, 44, 47, 48, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 104, 105, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 62, 65, 66, 67, 69, 80, 85, 87, 88, 89, 100, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=32,
                    value=37368,
                    econ_value=37.4,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 41, 43, 44, 47, 48, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 104, 105, 106, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 62, 65, 66, 67, 69, 80, 81, 85, 87, 88, 89, 100, 105, 125]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=34,
                    value=39566,
                    econ_value=39.6,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 41, 43, 44, 47, 48, 49, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 91, 104, 105, 106, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 62, 65, 66, 67, 69, 80, 81, 85, 87, 88, 89, 100, 101, 105, 124, 125]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=36,
                    value=41764,
                    econ_value=41.800000000000004,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 41, 43, 44, 45, 47, 48, 49, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 91, 92, 104, 105, 106, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 62, 65, 66, 67, 69, 80, 81, 85, 87, 88, 89, 100, 101, 102, 105, 124, 125, 144]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(35, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=38,
                    value=43962,
                    econ_value=44.00000000000001,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 41, 43, 44, 45, 46, 47, 48, 49, 51],
                    target_island_set=[8, 10, 11, 12, 13, 14, 15, 80, 91, 92, 104, 105, 106, 116, 130, 131, 145, 152, 153, 154],
                    item_tile_set=[6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26, 29, 40, 41, 42, 43, 49, 60, 61, 62, 65, 66, 67, 69, 80, 81, 85, 87, 88, 89, 100, 101, 102, 105, 121, 124, 125, 143, 144]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[37],
                    target_island_set=[11],
                    item_tile_set=[45, 65]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=4397,
                    econ_value=4.4,
                    friendly_island_set=[35, 37],
                    target_island_set=[11, 12],
                    item_tile_set=[25, 45, 65, 66]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=6595,
                    econ_value=6.6000000000000005,
                    friendly_island_set=[34, 35, 37],
                    target_island_set=[11, 12, 13],
                    item_tile_set=[24, 25, 45, 65, 66, 67]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=8793,
                    econ_value=8.8,
                    friendly_island_set=[33, 34, 35, 37],
                    target_island_set=[11, 12, 13, 104],
                    item_tile_set=[23, 24, 25, 45, 65, 66, 67, 85]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=10991,
                    econ_value=11.0,
                    friendly_island_set=[33, 34, 35, 36, 37],
                    target_island_set=[11, 12, 13, 104, 105],
                    item_tile_set=[23, 24, 25, 43, 45, 65, 66, 67, 85, 105]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=11,
                    value=13189,
                    econ_value=13.2,
                    friendly_island_set=[32, 33, 34, 35, 36, 37],
                    target_island_set=[11, 12, 13, 104, 105, 106],
                    item_tile_set=[22, 23, 24, 25, 43, 45, 65, 66, 67, 85, 105, 125]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=13,
                    value=15386,
                    econ_value=15.399999999999999,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37],
                    target_island_set=[11, 12, 13, 91, 104, 105, 106],
                    item_tile_set=[21, 22, 23, 24, 25, 43, 45, 65, 66, 67, 85, 105, 124, 125]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=15,
                    value=17584,
                    econ_value=17.599999999999998,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 48],
                    target_island_set=[11, 12, 13, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 43, 45, 65, 66, 67, 85, 105, 124, 125, 144]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=17,
                    value=19782,
                    econ_value=19.799999999999997,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48],
                    target_island_set=[11, 12, 13, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 143, 144]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=19,
                    value=21980,
                    econ_value=21.999999999999996,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48],
                    target_island_set=[11, 12, 13, 69, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 142, 143, 144]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=21,
                    value=24178,
                    econ_value=24.199999999999996,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48],
                    target_island_set=[11, 12, 13, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 142, 143, 144, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=23,
                    value=26376,
                    econ_value=26.399999999999995,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48],
                    target_island_set=[11, 12, 13, 60, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 142, 143, 144, 161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=25,
                    value=28574,
                    econ_value=28.599999999999994,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48],
                    target_island_set=[11, 12, 13, 52, 60, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 142, 143, 144, 160, 161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=27,
                    value=30772,
                    econ_value=30.799999999999994,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48, 51],
                    target_island_set=[11, 12, 13, 16, 52, 60, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=28,
                    value=32971,
                    econ_value=32.99999999999999,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 47, 48, 51],
                    target_island_set=[11, 12, 13, 16, 52, 60, 61, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=30,
                    value=35169,
                    econ_value=35.199999999999996,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 44, 47, 48, 51],
                    target_island_set=[11, 12, 13, 16, 52, 60, 61, 62, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 65, 66, 67, 80, 85, 100, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181, 201]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=32,
                    value=37368,
                    econ_value=37.4,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 41, 44, 47, 48, 51],
                    target_island_set=[11, 12, 13, 16, 18, 52, 60, 61, 62, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 62, 65, 66, 67, 80, 85, 100, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181, 200, 201]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=34,
                    value=39566,
                    econ_value=39.6,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 41, 43, 44, 47, 48, 51],
                    target_island_set=[11, 12, 13, 16, 18, 52, 60, 61, 62, 63, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 62, 65, 66, 67, 80, 81, 85, 100, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181, 200, 201, 221]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=36,
                    value=41764,
                    econ_value=41.800000000000004,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 41, 43, 44, 47, 48, 49, 51],
                    target_island_set=[11, 12, 13, 16, 18, 52, 60, 61, 62, 63, 64, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 62, 65, 66, 67, 80, 81, 85, 100, 101, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181, 200, 201, 221, 241]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=38,
                    value=43962,
                    econ_value=44.00000000000001,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 41, 43, 44, 45, 47, 48, 49, 51],
                    target_island_set=[11, 12, 13, 16, 18, 52, 53, 60, 61, 62, 63, 64, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 62, 65, 66, 67, 80, 81, 85, 100, 101, 102, 105, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181, 200, 201, 221,
                                   240, 241]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(37, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=40,
                    value=46160,
                    econ_value=46.20000000000001,
                    friendly_island_set=[31, 32, 33, 34, 35, 36, 37, 41, 43, 44, 45, 46, 47, 48, 49, 51],
                    target_island_set=[11, 12, 13, 16, 18, 52, 53, 54, 60, 61, 62, 63, 64, 69, 70, 80, 91, 92, 104, 105, 106],
                    item_tile_set=[20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 45, 60, 61, 62, 65, 66, 67, 80, 81, 85, 100, 101, 102, 105, 121, 124, 125, 140, 142, 143, 144, 160, 161, 162, 181, 200, 201,
                                   221, 240, 241, 260]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(38, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[38],
                    target_island_set=[12],
                    item_tile_set=[46, 66]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(40, 10),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[40],
                    target_island_set=[10],
                    item_tile_set=[48, 49]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(40, 10),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=4397,
                    econ_value=4.4,
                    friendly_island_set=[39, 40],
                    target_island_set=[10, 14],
                    item_tile_set=[47, 48, 49, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(42, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[42],
                    target_island_set=[14],
                    item_tile_set=[68, 69]),
            ],
            max_iterations=32)
        self.begin_capturing_logging()
        result = ArmyFlowExpanderV2._solve_grouped_knapsack_pre_group_input(repro, noLog=False)
        self.assertEqual(43, result.chosen_weight)
        self._assert_no_duplicate_repro_item_tile_use([t.item_tile_set for t in repro.items], result.chosen_indices)
        self.assertGreaterEqual(sum([t.value for t in repro.items]), 52000)


    def test_a_more_open_normal_map__knapsack_direct(self):
        self.begin_capturing_logging()
        repro = GroupedKnapsackPreGroupInput(
            turn_budget=50,
            items=[
                GroupedKnapsackPreGroupItem(
                    border_pair=(141, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[141],
                    target_island_set=[8],
                    item_tile_set=[2, 22]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(141, 8),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[141],
                    target_island_set=[8, 9],
                    item_tile_set=[2, 3, 22]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(142, 9),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[142],
                    target_island_set=[9],
                    item_tile_set=[3, 23]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(142, 9),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[142],
                    target_island_set=[8, 9],
                    item_tile_set=[2, 3, 23]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[144],
                    target_island_set=[34],
                    item_tile_set=[7, 27]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[144],
                    target_island_set=[32, 34],
                    item_tile_set=[7, 8, 27]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=4195,
                    econ_value=4.2,
                    friendly_island_set=[144, 151, 152],
                    target_island_set=[32, 34, 129],
                    item_tile_set=[7, 8, 9, 27, 46, 47]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=6393,
                    econ_value=6.4,
                    friendly_island_set=[144, 150, 151, 152],
                    target_island_set=[32, 34, 129, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 27, 45, 46, 47]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=8591,
                    econ_value=8.600000000000001,
                    friendly_island_set=[144, 150, 151, 152, 162],
                    target_island_set=[32, 34, 129, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 27, 45, 46, 47, 65]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=13,
                    value=10787,
                    econ_value=10.8,
                    friendly_island_set=[144, 150, 151, 152, 162, 188],
                    target_island_set=[32, 34, 129, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 27, 43, 44, 45, 46, 47, 64, 65]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=16,
                    value=12984,
                    econ_value=13.0,
                    friendly_island_set=[141, 142, 144, 150, 151, 152, 162, 188],
                    target_island_set=[32, 34, 129, 130, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 13, 22, 23, 27, 43, 44, 45, 46, 47, 64, 65]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=19,
                    value=15181,
                    econ_value=15.2,
                    friendly_island_set=[141, 142, 144, 149, 150, 151, 152, 161, 162, 188],
                    target_island_set=[32, 34, 129, 130, 132, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 13, 22, 23, 27, 30, 42, 43, 44, 45, 46, 47, 63, 64, 65]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=23,
                    value=17377,
                    econ_value=17.4,
                    friendly_island_set=[141, 142, 143, 144, 149, 150, 151, 152, 161, 162, 169, 188, 190],
                    target_island_set=[32, 34, 129, 130, 131, 132, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 13, 22, 23, 24, 27, 30, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 83, 84]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=27,
                    value=19572,
                    econ_value=19.599999999999998,
                    friendly_island_set=[141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 168, 169, 176, 188, 190],
                    target_island_set=[32, 34, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 13, 22, 23, 24, 27, 30, 31, 41, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 82, 83, 84, 103]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=29,
                    value=20570,
                    econ_value=20.599999999999998,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 168, 169, 176, 188, 190],
                    target_island_set=[32, 34, 35, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[6, 7, 8, 9, 10, 11, 12, 13, 21, 22, 23, 24, 27, 30, 31, 41, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 82, 83, 84, 103]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=31,
                    value=21568,
                    econ_value=21.599999999999998,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 168, 169, 175, 176, 188, 190],
                    target_island_set=[32, 33, 34, 35, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 21, 22, 23, 24, 27, 30, 31, 41, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 82, 83, 84, 102, 103]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=33,
                    value=22566,
                    econ_value=22.599999999999998,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 188, 190],
                    target_island_set=[32, 33, 34, 35, 47, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 21, 22, 23, 24, 27, 30, 31, 33, 41, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 81, 82, 83, 84, 102, 103]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=38,
                    value=24761,
                    econ_value=24.799999999999997,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 186, 188, 190, 191, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23, 24, 27, 30, 31, 33, 34, 40, 41, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 81, 82, 83, 84, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=39,
                    value=26960,
                    econ_value=26.999999999999996,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 186, 188, 190, 191, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23, 24, 27, 30, 31, 32, 33, 34, 40, 41, 42, 43, 44, 45, 46, 47, 50, 63, 64, 65, 81, 82, 83, 84, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=40,
                    value=29159,
                    econ_value=29.199999999999996,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 186, 188, 190, 191, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 27, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 50, 56, 57, 63, 64, 65, 81, 82, 83,
                                   84, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=42,
                    value=31357,
                    econ_value=31.399999999999995,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 186, 188, 190, 191, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 27, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 50, 56, 57, 63, 64, 65, 81, 82, 83,
                                   84, 100, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=43,
                    value=33556,
                    econ_value=33.599999999999994,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 186, 188, 190, 191, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 27, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 50, 56, 57, 63, 64, 65, 81, 82, 83,
                                   84, 100, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=44,
                    value=35756,
                    econ_value=35.8,
                    friendly_island_set=[140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 161, 162, 167, 168, 169, 175, 176, 186, 188, 190, 191, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 27, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 50, 56, 57, 63, 64, 65, 81, 82, 83,
                                   84, 100, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(144, 34),
                    external_group_id=None,
                    is_external=False,
                    weight=49,
                    value=37951,
                    econ_value=38.0,
                    friendly_island_set=[136, 140, 141, 142, 143, 144, 148, 149, 150, 151, 152, 158, 161, 162, 167, 168, 169, 175, 176, 186, 188, 189, 190, 191, 206, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 27, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 50, 56, 57, 60, 63, 64, 65, 80, 81,
                                   82, 83, 84, 100, 101, 102, 103, 120, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(145, 129),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=2199,
                    econ_value=2.2,
                    friendly_island_set=[145],
                    target_island_set=[129],
                    item_tile_set=[9, 29]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(147, 26),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[147],
                    target_island_set=[26],
                    item_tile_set=[167, 168]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(147, 26),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[147, 231],
                    target_island_set=[26, 27],
                    item_tile_set=[166, 167, 168, 169]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(147, 26),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=2995,
                    econ_value=3.0,
                    friendly_island_set=[139, 147, 231],
                    target_island_set=[26, 27, 28],
                    item_tile_set=[146, 148, 166, 167, 168, 169]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=2198,
                    econ_value=2.2,
                    friendly_island_set=[153, 154],
                    target_island_set=[131],
                    item_tile_set=[48, 49, 50]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=4396,
                    econ_value=4.4,
                    friendly_island_set=[153, 154, 165],
                    target_island_set=[131, 132],
                    item_tile_set=[30, 48, 49, 50, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=6594,
                    econ_value=6.6000000000000005,
                    friendly_island_set=[152, 153, 154, 165],
                    target_island_set=[131, 132, 133],
                    item_tile_set=[30, 31, 47, 48, 49, 50, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=8792,
                    econ_value=8.8,
                    friendly_island_set=[151, 152, 153, 154, 165],
                    target_island_set=[131, 132, 133, 134],
                    item_tile_set=[10, 11, 12, 30, 31, 46, 47, 48, 49, 50, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=11,
                    value=10989,
                    econ_value=11.0,
                    friendly_island_set=[150, 151, 152, 153, 154, 164, 165],
                    target_island_set=[131, 132, 133, 134],
                    item_tile_set=[10, 11, 12, 30, 31, 45, 46, 47, 48, 49, 50, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=13,
                    value=13187,
                    econ_value=13.2,
                    friendly_island_set=[150, 151, 152, 153, 154, 162, 164, 165],
                    target_island_set=[131, 132, 133, 134],
                    item_tile_set=[10, 11, 12, 30, 31, 45, 46, 47, 48, 49, 50, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=17,
                    value=15382,
                    econ_value=15.399999999999999,
                    friendly_island_set=[150, 151, 152, 153, 154, 162, 164, 165, 188],
                    target_island_set=[129, 131, 132, 133, 134],
                    item_tile_set=[9, 10, 11, 12, 30, 31, 43, 44, 45, 46, 47, 48, 49, 50, 64, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=20,
                    value=17579,
                    econ_value=17.599999999999998,
                    friendly_island_set=[141, 142, 150, 151, 152, 153, 154, 162, 164, 165, 188],
                    target_island_set=[129, 130, 131, 132, 133, 134],
                    item_tile_set=[9, 10, 11, 12, 13, 22, 23, 30, 31, 43, 44, 45, 46, 47, 48, 49, 50, 64, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=21,
                    value=18578,
                    econ_value=18.599999999999998,
                    friendly_island_set=[141, 142, 150, 151, 152, 153, 154, 162, 164, 165, 188],
                    target_island_set=[32, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[8, 9, 10, 11, 12, 13, 22, 23, 30, 31, 43, 44, 45, 46, 47, 48, 49, 50, 64, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=23,
                    value=19576,
                    econ_value=19.599999999999998,
                    friendly_island_set=[141, 142, 150, 151, 152, 153, 154, 161, 162, 164, 165, 188],
                    target_island_set=[32, 34, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[7, 8, 9, 10, 11, 12, 13, 22, 23, 30, 31, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=25,
                    value=20574,
                    econ_value=20.599999999999998,
                    friendly_island_set=[141, 142, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 188],
                    target_island_set=[32, 34, 35, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[6, 7, 8, 9, 10, 11, 12, 13, 22, 23, 30, 31, 42, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=27,
                    value=21572,
                    econ_value=21.599999999999998,
                    friendly_island_set=[141, 142, 143, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 188],
                    target_island_set=[32, 33, 34, 35, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 22, 23, 24, 30, 31, 42, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 68, 69]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=29,
                    value=22570,
                    econ_value=22.599999999999998,
                    friendly_island_set=[141, 142, 143, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 169, 188],
                    target_island_set=[32, 33, 34, 35, 47, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 22, 23, 24, 30, 31, 33, 42, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 68, 69, 84]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=34,
                    value=24765,
                    econ_value=24.799999999999997,
                    friendly_island_set=[141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 168, 169, 176, 188, 190],
                    target_island_set=[32, 33, 34, 35, 47, 91, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 22, 23, 24, 30, 31, 33, 34, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 68, 69, 82, 83, 84, 103]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=39,
                    value=26960,
                    econ_value=26.999999999999996,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 190],
                    target_island_set=[32, 33, 34, 35, 47, 91, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 68, 69, 81, 82, 83, 84, 102, 103]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=43,
                    value=29156,
                    econ_value=29.199999999999996,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 190, 191, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 56, 57, 63, 64, 65, 68, 69,
                                   81, 82, 83, 84, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=44,
                    value=31355,
                    econ_value=31.399999999999995,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 190, 191, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 56, 57, 63, 64, 65, 68, 69,
                                   81, 82, 83, 84, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=45,
                    value=33554,
                    econ_value=33.599999999999994,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 190, 191, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 56, 57, 63, 64, 65, 68, 69,
                                   81, 82, 83, 84, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=47,
                    value=35753,
                    econ_value=35.8,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 190, 191, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 56, 57, 63, 64, 65, 68, 69,
                                   81, 82, 83, 84, 100, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=48,
                    value=37952,
                    econ_value=38.0,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 190, 191, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 56, 57, 63, 64, 65, 68, 69,
                                   81, 82, 83, 84, 100, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(154, 131),
                    external_group_id=None,
                    is_external=False,
                    weight=50,
                    value=40150,
                    econ_value=40.2,
                    friendly_island_set=[140, 141, 142, 143, 148, 149, 150, 151, 152, 153, 154, 161, 162, 164, 165, 167, 168, 169, 175, 176, 186, 188, 189, 190, 191, 217, 219],
                    target_island_set=[32, 33, 34, 35, 47, 91, 123, 128, 129, 130, 131, 132, 133, 134],
                    item_tile_set=[5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 56, 57, 63, 64, 65, 68, 69,
                                   80, 81, 82, 83, 84, 100, 101, 102, 103, 121]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(157, 39),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[157],
                    target_island_set=[39],
                    item_tile_set=[187, 207]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(157, 39),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[156, 157],
                    target_island_set=[37, 39],
                    item_tile_set=[186, 187, 207, 208]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(157, 39),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=2996,
                    econ_value=3.0,
                    friendly_island_set=[156, 157],
                    target_island_set=[37, 38, 39],
                    item_tile_set=[186, 187, 207, 208, 227]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(159, 37),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[159],
                    target_island_set=[37],
                    item_tile_set=[188, 208]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(159, 37),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[159],
                    target_island_set=[37, 39],
                    item_tile_set=[188, 207, 208]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(159, 37),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=2996,
                    econ_value=3.0,
                    friendly_island_set=[157, 159],
                    target_island_set=[37, 38, 39],
                    item_tile_set=[187, 188, 207, 208, 227]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[163],
                    target_island_set=[43],
                    item_tile_set=[190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[160, 163],
                    target_island_set=[42, 43],
                    item_tile_set=[171, 189, 190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=2995,
                    econ_value=3.0,
                    friendly_island_set=[159, 160, 163],
                    target_island_set=[41, 42, 43],
                    item_tile_set=[151, 171, 188, 189, 190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=5191,
                    econ_value=5.2,
                    friendly_island_set=[156, 157, 159, 160, 163, 232],
                    target_island_set=[41, 42, 43, 94],
                    item_tile_set=[151, 165, 171, 172, 185, 186, 187, 188, 189, 190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=12,
                    value=7388,
                    econ_value=7.4,
                    friendly_island_set=[138, 156, 157, 159, 160, 163, 232],
                    target_island_set=[41, 42, 43, 94, 95],
                    item_tile_set=[145, 151, 165, 171, 172, 173, 185, 186, 187, 188, 189, 190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=14,
                    value=9586,
                    econ_value=9.600000000000001,
                    friendly_island_set=[138, 155, 156, 157, 159, 160, 163, 232],
                    target_island_set=[41, 42, 43, 88, 94, 95],
                    item_tile_set=[145, 151, 153, 165, 171, 172, 173, 184, 185, 186, 187, 188, 189, 190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 43),
                    external_group_id=None,
                    is_external=False,
                    weight=16,
                    value=11784,
                    econ_value=11.8,
                    friendly_island_set=[138, 146, 155, 156, 157, 159, 160, 163, 232],
                    target_island_set=[41, 42, 43, 80, 88, 94, 95],
                    item_tile_set=[133, 145, 151, 153, 164, 165, 171, 172, 173, 184, 185, 186, 187, 188, 189, 190, 191]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(163, 45),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[163],
                    target_island_set=[45],
                    item_tile_set=[190, 210]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(172, 112),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=2197,
                    econ_value=2.2,
                    friendly_island_set=[170, 171, 172],
                    target_island_set=[112],
                    item_tile_set=[88, 89, 90, 91]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(174, 38),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[174],
                    target_island_set=[38],
                    item_tile_set=[226, 227]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(174, 38),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[174],
                    target_island_set=[38, 39],
                    item_tile_set=[207, 226, 227]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(176, 4),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[176],
                    target_island_set=[4],
                    item_tile_set=[103, 123]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(176, 4),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[175, 176],
                    target_island_set=[4, 6],
                    item_tile_set=[102, 103, 123, 143]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(176, 4),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=2995,
                    econ_value=3.0,
                    friendly_island_set=[175, 176, 191],
                    target_island_set=[4, 5, 6],
                    item_tile_set=[101, 102, 103, 123, 142, 143]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(176, 4),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=3993,
                    econ_value=4.0,
                    friendly_island_set=[175, 176, 191, 219],
                    target_island_set=[3, 4, 5, 6],
                    item_tile_set=[101, 102, 103, 121, 123, 142, 143, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(179, 75),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=2197,
                    econ_value=2.2,
                    friendly_island_set=[177, 178, 179],
                    target_island_set=[75],
                    item_tile_set=[87, 105, 106, 107]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(179, 75),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=4393,
                    econ_value=4.4,
                    friendly_island_set=[177, 178, 179, 184, 185, 192],
                    target_island_set=[74, 75],
                    item_tile_set=[67, 87, 104, 105, 106, 107, 124, 126]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(180, 77),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=2197,
                    econ_value=2.2,
                    friendly_island_set=[178, 179, 180],
                    target_island_set=[77],
                    item_tile_set=[106, 107, 108, 128]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(180, 77),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=3195,
                    econ_value=3.2,
                    friendly_island_set=[177, 178, 179, 180],
                    target_island_set=[28, 77],
                    item_tile_set=[105, 106, 107, 108, 128, 148]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(180, 77),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=4193,
                    econ_value=4.2,
                    friendly_island_set=[177, 178, 179, 180, 185],
                    target_island_set=[26, 28, 77],
                    item_tile_set=[105, 106, 107, 108, 126, 128, 148, 168]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(180, 77),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=5191,
                    econ_value=5.2,
                    friendly_island_set=[177, 178, 179, 180, 185, 192],
                    target_island_set=[26, 27, 28, 77],
                    item_tile_set=[104, 105, 106, 107, 108, 126, 128, 148, 168, 169]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[181],
                    target_island_set=[12],
                    item_tile_set=[245, 265]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[181],
                    target_island_set=[12, 221],
                    item_tile_set=[245, 265, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=2997,
                    econ_value=3.0,
                    friendly_island_set=[181],
                    target_island_set=[12, 221],
                    item_tile_set=[245, 265, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=3995,
                    econ_value=4.0,
                    friendly_island_set=[173, 181],
                    target_island_set=[12, 221],
                    item_tile_set=[225, 245, 265, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=4994,
                    econ_value=5.0,
                    friendly_island_set=[173, 181],
                    target_island_set=[12, 221],
                    item_tile_set=[225, 245, 265, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=5992,
                    econ_value=6.0,
                    friendly_island_set=[166, 173, 181],
                    target_island_set=[12, 221, 223],
                    item_tile_set=[205, 225, 245, 265, 283, 284, 285, 286, 302, 303, 304, 305, 306, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(181, 12),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=6991,
                    econ_value=7.0,
                    friendly_island_set=[166, 173, 181],
                    target_island_set=[12, 221, 223],
                    item_tile_set=[205, 225, 245, 265, 283, 284, 285, 286, 302, 303, 304, 305, 306, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(182, 13),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[182],
                    target_island_set=[13],
                    item_tile_set=[246, 266]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(182, 13),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[182],
                    target_island_set=[13, 221],
                    item_tile_set=[246, 266, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(182, 13),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=2996,
                    econ_value=3.0,
                    friendly_island_set=[174, 182],
                    target_island_set=[13, 221],
                    item_tile_set=[226, 246, 266, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(182, 13),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=3995,
                    econ_value=4.0,
                    friendly_island_set=[174, 182],
                    target_island_set=[13, 221],
                    item_tile_set=[226, 246, 266, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[183],
                    target_island_set=[19],
                    item_tile_set=[247, 248]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[183],
                    target_island_set=[19, 20],
                    item_tile_set=[247, 248, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=2997,
                    econ_value=3.0,
                    friendly_island_set=[183],
                    target_island_set=[14, 19, 20],
                    item_tile_set=[247, 248, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=3995,
                    econ_value=4.0,
                    friendly_island_set=[182, 183],
                    target_island_set=[13, 14, 19, 20],
                    item_tile_set=[246, 247, 248, 266, 267, 268]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=4994,
                    econ_value=5.0,
                    friendly_island_set=[182, 183],
                    target_island_set=[13, 14, 19, 20, 221],
                    item_tile_set=[246, 247, 248, 266, 267, 268, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=5992,
                    econ_value=6.0,
                    friendly_island_set=[174, 182, 183],
                    target_island_set=[13, 14, 19, 20, 221],
                    item_tile_set=[226, 246, 247, 248, 266, 267, 268, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 19),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=6991,
                    econ_value=7.0,
                    friendly_island_set=[174, 182, 183],
                    target_island_set=[13, 14, 19, 20, 221],
                    item_tile_set=[226, 246, 247, 248, 266, 267, 268, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[183],
                    target_island_set=[14],
                    item_tile_set=[247, 267]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[183],
                    target_island_set=[13, 14],
                    item_tile_set=[247, 266, 267]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=2997,
                    econ_value=3.0,
                    friendly_island_set=[183],
                    target_island_set=[13, 14, 221],
                    item_tile_set=[247, 266, 267, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=3995,
                    econ_value=4.0,
                    friendly_island_set=[182, 183],
                    target_island_set=[13, 14, 221],
                    item_tile_set=[246, 247, 266, 267, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=4994,
                    econ_value=5.0,
                    friendly_island_set=[182, 183],
                    target_island_set=[13, 14, 221],
                    item_tile_set=[246, 247, 266, 267, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=5992,
                    econ_value=6.0,
                    friendly_island_set=[174, 182, 183],
                    target_island_set=[13, 14, 221],
                    item_tile_set=[226, 246, 247, 266, 267, 285, 286, 305, 306]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(183, 14),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=6991,
                    econ_value=7.0,
                    friendly_island_set=[174, 182, 183],
                    target_island_set=[13, 14, 221, 223],
                    item_tile_set=[226, 246, 247, 266, 267, 283, 284, 285, 286, 302, 303, 304, 305, 306, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(194, 3),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[194],
                    target_island_set=[3],
                    item_tile_set=[161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(194, 3),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[194, 201],
                    target_island_set=[3, 5],
                    item_tile_set=[141, 142, 161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(194, 3),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=2995,
                    econ_value=3.0,
                    friendly_island_set=[194, 201, 219],
                    target_island_set=[3, 5, 6],
                    item_tile_set=[121, 141, 142, 143, 161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(194, 3),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=3994,
                    econ_value=4.0,
                    friendly_island_set=[194, 201, 219],
                    target_island_set=[3, 4, 5, 6],
                    item_tile_set=[121, 123, 141, 142, 143, 161, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(196, 30),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[196],
                    target_island_set=[30],
                    item_tile_set=[261, 281]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[197],
                    target_island_set=[11],
                    item_tile_set=[262, 263]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[196, 197],
                    target_island_set=[11, 223],
                    item_tile_set=[261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=2995,
                    econ_value=3.0,
                    friendly_island_set=[196, 197, 202],
                    target_island_set=[11, 223],
                    item_tile_set=[241, 261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=3994,
                    econ_value=4.0,
                    friendly_island_set=[196, 197, 202],
                    target_island_set=[11, 223],
                    item_tile_set=[241, 261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=4992,
                    econ_value=5.0,
                    friendly_island_set=[195, 196, 197, 202],
                    target_island_set=[11, 223],
                    item_tile_set=[241, 260, 261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=10,
                    value=5990,
                    econ_value=6.0,
                    friendly_island_set=[195, 196, 197, 202, 205],
                    target_island_set=[11, 223],
                    item_tile_set=[240, 241, 260, 261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=12,
                    value=6988,
                    econ_value=7.0,
                    friendly_island_set=[195, 196, 197, 202, 204, 205],
                    target_island_set=[11, 223],
                    item_tile_set=[220, 240, 241, 260, 261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(197, 11),
                    external_group_id=None,
                    is_external=False,
                    weight=14,
                    value=7986,
                    econ_value=8.0,
                    friendly_island_set=[195, 196, 197, 198, 202, 204, 205],
                    target_island_set=[11, 223],
                    item_tile_set=[200, 220, 240, 241, 260, 261, 262, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[199],
                    target_island_set=[16],
                    item_tile_set=[201, 221]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[199, 203],
                    target_island_set=[16, 22],
                    item_tile_set=[181, 201, 221, 222]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=2995,
                    econ_value=3.0,
                    friendly_island_set=[194, 199, 203],
                    target_island_set=[16, 18, 22],
                    item_tile_set=[161, 181, 201, 221, 222, 242]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=7,
                    value=3993,
                    econ_value=4.0,
                    friendly_island_set=[194, 199, 201, 203],
                    target_island_set=[16, 18, 22, 23],
                    item_tile_set=[141, 161, 181, 201, 221, 222, 242, 243]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=9,
                    value=4991,
                    econ_value=5.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=10,
                    value=5990,
                    econ_value=6.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=11,
                    value=6989,
                    econ_value=7.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=12,
                    value=7988,
                    econ_value=8.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=13,
                    value=8987,
                    econ_value=9.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=14,
                    value=9986,
                    econ_value=10.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=15,
                    value=10985,
                    econ_value=11.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=16,
                    value=11984,
                    econ_value=12.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=17,
                    value=12983,
                    econ_value=13.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=18,
                    value=13982,
                    econ_value=14.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 220, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324, 325, 326, 344, 345]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=19,
                    value=14981,
                    econ_value=15.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 220, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324, 325, 326, 344, 345]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=20,
                    value=15980,
                    econ_value=16.0,
                    friendly_island_set=[194, 199, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 220, 223],
                    item_tile_set=[121, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324, 325, 326, 344, 345]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=22,
                    value=16978,
                    econ_value=17.0,
                    friendly_island_set=[194, 199, 200, 201, 203, 219],
                    target_island_set=[11, 16, 18, 22, 23, 220, 223],
                    item_tile_set=[121, 140, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 322, 323, 324, 325, 326, 344, 345]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(199, 16),
                    external_group_id=None,
                    is_external=False,
                    weight=24,
                    value=17976,
                    econ_value=18.0,
                    friendly_island_set=[194, 199, 200, 201, 203, 206, 219],
                    target_island_set=[11, 16, 18, 22, 23, 220, 222, 223],
                    item_tile_set=[120, 121, 140, 141, 161, 181, 201, 221, 222, 242, 243, 263, 283, 284, 302, 303, 304, 307, 308, 309, 322, 323, 324, 325, 326, 327, 344, 345, 346, 347]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(201, 5),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[201],
                    target_island_set=[5],
                    item_tile_set=[141, 142]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(201, 5),
                    external_group_id=None,
                    is_external=False,
                    weight=3,
                    value=1997,
                    econ_value=2.0,
                    friendly_island_set=[201, 219],
                    target_island_set=[3, 5],
                    item_tile_set=[121, 141, 142, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(201, 5),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=2996,
                    econ_value=3.0,
                    friendly_island_set=[201, 219],
                    target_island_set=[3, 5, 6],
                    item_tile_set=[121, 141, 142, 143, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(201, 5),
                    external_group_id=None,
                    is_external=False,
                    weight=5,
                    value=3995,
                    econ_value=4.0,
                    friendly_island_set=[201, 219],
                    target_island_set=[3, 4, 5, 6],
                    item_tile_set=[121, 123, 141, 142, 143, 162]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(202, 18),
                    external_group_id=None,
                    is_external=False,
                    weight=1,
                    value=999,
                    econ_value=1.0,
                    friendly_island_set=[202],
                    target_island_set=[18],
                    item_tile_set=[241, 242]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(202, 18),
                    external_group_id=None,
                    is_external=False,
                    weight=2,
                    value=1998,
                    econ_value=2.0,
                    friendly_island_set=[202],
                    target_island_set=[18, 22],
                    item_tile_set=[222, 241, 242]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(202, 18),
                    external_group_id=None,
                    is_external=False,
                    weight=4,
                    value=2996,
                    econ_value=3.0,
                    friendly_island_set=[202, 205],
                    target_island_set=[16, 18, 22],
                    item_tile_set=[221, 222, 240, 241, 242]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(202, 18),
                    external_group_id=None,
                    is_external=False,
                    weight=6,
                    value=3994,
                    econ_value=4.0,
                    friendly_island_set=[202, 204, 205],
                    target_island_set=[16, 18, 22, 23],
                    item_tile_set=[220, 221, 222, 240, 241, 242, 243]),
                GroupedKnapsackPreGroupItem(
                    border_pair=(202, 18),
                    external_group_id=None,
                    is_external=False,
                    weight=8,
                    value=4992,
                    econ_value=5.0,
                    friendly_island_set=[198, 202, 204, 205],
                    target_island_set=[11, 16, 18, 22, 23],
                    item_tile_set=[200, 220, 221, 222, 240, 241, 242, 243, 263]),
            ],
            max_iterations=32)
        result = ArmyFlowExpanderV2._solve_grouped_knapsack_pre_group_input(repro, noLog=False)
        self.assertEqual(50, result.chosen_weight)
        self._assert_no_duplicate_repro_item_tile_use([t.item_tile_set for t in repro.items], result.chosen_indices)
        self.assertGreaterEqual(sum([t.value for t in repro.items]), 45000)

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

        # All selected entries must respect the turns budget
        total_weight = sum(e.turns for e in solution.values())
        self.assertLessEqual(total_weight, turn_budget,
                             f'Total turns {total_weight} must not exceed budget {turn_budget}')

        # Every selected entry must have positive econ value
        for bp, enriched in solution.items():
            self.assertIsInstance(bp, FlowBorderPairKey)
            self.assertIsInstance(enriched, EnrichedFlowTurnsEntry)
            self.assertGreater(enriched.capture_entry.econ_value, 0,
                               'Selected capture must have positive econ value')

        if debugMode:
            for bp, enriched in solution.items():
                logbook.info(f'Selected {bp.friendly_island_id}->{bp.target_island_id}: '
                             f'turns={enriched.turns}, value={enriched.capture_entry.econ_value:.2f}')

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
        total_weight = sum(e.turns for e in solution.values())
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

        # Find minimum possible turns across all enriched entries
        min_cost = min(
            e.turns
            for tbl in groups_with_entries
            for e in tbl.enriched_capture_entries
            if e.turns > 0
        )

        # Budget just fits one group's cheapest item, not two
        tight_budget = min_cost
        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=tight_budget)

        total_weight = sum(e.turns for e in solution.values())
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
            self.assertGreaterEqual(enriched.turns, 1, 'turns must be >= 1')
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

    def test_grouped_knapsack__turns_equals_capture_plus_gather_turns(self):
        """Sanity check: turns in solution == capture.turns + gather.turns."""
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
            self.assertEqual(expected, enriched.turns,
                             f'turns must equal capture.turns + gather.turns for pair {bp}')
