import unittest

from Gather.GatherCaptureGroupKnapsacker import (
    GenericTilePlanOption,
    GroupedKnapsackInput,
    PlanSolver,
    TilePlanOptionKnapsackResult,
    _solve_grouped_tile_plan_options_with_mkcp_plus_greedy_conflict_resolution,
    adapt_grouped_knapsack_input_to_tile_plan_options,
    build_tile_plan_option_conflict_constraints,
    solve_grouped_knapsack_input,
    solve_tile_plan_options,
    solve_tile_plan_options_with_cp_sat,
    solve_tile_plan_options_with_existing_knapsack_solver,
    solve_tile_plan_options_with_mp_cbc,
    solve_tile_plan_options_with_mp_scip,
)
from base.client.tile import Tile


class WrappedSourceItem(object):
    """Typed arbitrary payload used to prove GenericTilePlanOption returns source items."""

    __slots__ = ('item_id',)

    def __init__(self, item_id: str) -> None:
        self.item_id = item_id


class GatherCaptureGroupKnapsackerLinearConstraintSolverTests(unittest.TestCase):
    def _tile(self, tile_id: int) -> Tile:
        """Build a stable fake tile identity for generic solver tests."""
        return Tile(tile_id, 0, tileIndex=tile_id)

    def _build_conflicting_options(self) -> list[GenericTilePlanOption]:
        """Build a reusable conflict-case option set for exact solver parity tests."""
        tile_1 = self._tile(1)
        tile_2 = self._tile(2)
        tile_3 = self._tile(3)
        tile_4 = self._tile(4)
        return [
            GenericTilePlanOption(item='conflicting-high', length=4, tileSet={tile_1, tile_2}, econValue=13.0),
            GenericTilePlanOption(item='left', length=3, tileSet={tile_1}, econValue=6.0),
            GenericTilePlanOption(item='right', length=3, tileSet={tile_2}, econValue=6.0),
            GenericTilePlanOption(item='free', length=2, tileSet={tile_3}, econValue=5.0),
            GenericTilePlanOption(item='too-expensive-with-best-pair', length=5, tileSet={tile_4}, econValue=8.0),
        ]

    def _assert_same_tile_plan_result(
            self,
            expected: TilePlanOptionKnapsackResult,
            actual: TilePlanOptionKnapsackResult
    ) -> None:
        """Assert solver wrappers selected the same output plan."""
        self.assertEqual(expected.max_value, actual.max_value)
        self.assertEqual(expected.chosen_weight, actual.chosen_weight)
        self.assertEqual(sorted(expected.chosen_indices), sorted(actual.chosen_indices))
        self.assertEqual(sorted(expected.chosen_items), sorted(actual.chosen_items))

    def _assert_same_grouped_knapsack_result(
            self,
            expected_max_value: int,
            expected_chosen_weight: int,
            expected_chosen_indices: list[int],
            actual_max_value: int,
            actual_chosen_weight: int,
            actual_chosen_indices: list[int],
    ) -> None:
        """Assert grouped solver result fields match expected scalar values."""
        self.assertEqual(expected_max_value, actual_max_value)
        self.assertEqual(expected_chosen_weight, actual_chosen_weight)
        self.assertEqual(expected_chosen_indices, actual_chosen_indices)

    def _build_grouped_input(self) -> GroupedKnapsackInput:
        """Build a small grouped input that exercises grouping and tile overlap metadata."""
        return GroupedKnapsackInput(
            turn_budget=5,
            groups=[0, 1, 1],
            weights=[2, 3, 2],
            values=[500, 700, 650],
            econ_values=[5.0, 7.0, 6.5],
            friendly_island_sets=[[], [], []],
            target_island_sets=[[], [], []],
            item_tile_sets=[[10, 11], [20, 21], [21, 22]],
            is_external_item={},
            max_iterations=32)

    def test_build_tile_plan_option_conflict_constraints__groups_options_by_used_tile(self) -> None:
        tile_1 = self._tile(1)
        tile_2 = self._tile(2)
        tile_3 = self._tile(3)
        options = [
            GenericTilePlanOption(item='a', length=2, tileSet={tile_1, tile_2}, econValue=5.0),
            GenericTilePlanOption(item='b', length=2, tileSet={tile_2}, econValue=6.0),
            GenericTilePlanOption(item='c', length=2, tileSet={tile_3}, econValue=7.0),
            GenericTilePlanOption(item='d', length=2, tileSet={tile_1, tile_3}, econValue=8.0),
        ]

        constraints = build_tile_plan_option_conflict_constraints(options)

        self.assertEqual([0, 3], constraints.tile_to_option_indices[tile_1.tile_index])
        self.assertEqual([0, 1], constraints.tile_to_option_indices[tile_2.tile_index])
        self.assertEqual([2, 3], constraints.tile_to_option_indices[tile_3.tile_index])
        self.assertEqual(
            [[0, 1], [0, 3], [2, 3]],
            sorted(constraints.mutually_exclusive_option_indices_by_tile))

    def test_adapt_grouped_knapsack_input_to_tile_plan_options__converts_arrays_to_protocol_options(self) -> None:
        grouped_input = self._build_grouped_input()

        options = adapt_grouped_knapsack_input_to_tile_plan_options(grouped_input)

        self.assertEqual(3, len(options))
        self.assertEqual(0, options[0].item)
        self.assertEqual(2, options[0].length)
        self.assertEqual(5.0, options[0].econValue)
        self.assertEqual([10, 11], sorted(tile.tile_index for tile in options[0].tileSet))
        self.assertEqual(2, options[2].item)
        self.assertEqual([21, 22], sorted(tile.tile_index for tile in options[2].tileSet))

    def test_grouped_mkcp_internal_common_format_solver__matches_public_grouped_input_wrapper(self) -> None:
        grouped_input = self._build_grouped_input()
        options = adapt_grouped_knapsack_input_to_tile_plan_options(grouped_input)

        public_result = solve_grouped_knapsack_input(grouped_input)
        internal_result = _solve_grouped_tile_plan_options_with_mkcp_plus_greedy_conflict_resolution(
            options=options,
            turn_budget=grouped_input.turn_budget,
            groups=grouped_input.groups,
            values=grouped_input.values,
            is_external_item=grouped_input.is_external_item,
            max_iterations=grouped_input.max_iterations)

        self._assert_same_grouped_knapsack_result(
            expected_max_value=public_result.max_value,
            expected_chosen_weight=public_result.chosen_weight,
            expected_chosen_indices=public_result.chosen_indices,
            actual_max_value=internal_result.max_value,
            actual_chosen_weight=internal_result.chosen_weight,
            actual_chosen_indices=internal_result.chosen_indices)
        self.assertEqual(public_result.groups, internal_result.groups)

    def test_solve_tile_plan_options_with_cp_sat__finds_absolute_max_under_capacity_and_tile_conflicts(self) -> None:
        options = self._build_conflicting_options()

        result = solve_tile_plan_options_with_cp_sat(options, turn_budget=8, value_multiple=100)

        self.assertEqual(1800, result.max_value)
        self.assertEqual(6, result.chosen_weight)
        self.assertEqual(['conflicting-high', 'free'], sorted(result.chosen_items))
        self.assertEqual([0, 3], sorted(result.chosen_indices))

    def test_solve_tile_plan_options_with_mp_cbc__matches_cp_sat_on_tile_conflicts(self) -> None:
        options = self._build_conflicting_options()

        cp_sat_result = solve_tile_plan_options_with_cp_sat(options, turn_budget=8, value_multiple=100)
        mp_result = solve_tile_plan_options_with_mp_cbc(options, turn_budget=8, value_multiple=100)

        self._assert_same_tile_plan_result(cp_sat_result, mp_result)

    def test_solve_tile_plan_options_with_mp_scip__matches_cp_sat_on_tile_conflicts(self) -> None:
        options = self._build_conflicting_options()

        cp_sat_result = solve_tile_plan_options_with_cp_sat(options, turn_budget=8, value_multiple=100)
        mp_result = solve_tile_plan_options_with_mp_scip(options, turn_budget=8, value_multiple=100)

        self._assert_same_tile_plan_result(cp_sat_result, mp_result)

    def test_exact_solver_wrappers__all_produce_same_output_on_tile_conflicts(self) -> None:
        options = self._build_conflicting_options()

        expected = solve_tile_plan_options_with_cp_sat(options, turn_budget=8, value_multiple=100)
        direct_results = [
            solve_tile_plan_options_with_mp_cbc(options, turn_budget=8, value_multiple=100),
            solve_tile_plan_options_with_mp_scip(options, turn_budget=8, value_multiple=100),
            solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.CpSat, value_multiple=100),
            solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.MpCbc, value_multiple=100),
            solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.MpScip, value_multiple=100),
        ]

        self.assertEqual(1800, expected.max_value)
        self.assertEqual(6, expected.chosen_weight)
        self.assertEqual(['conflicting-high', 'free'], sorted(expected.chosen_items))
        self.assertEqual([0, 3], sorted(expected.chosen_indices))
        for actual in direct_results:
            self._assert_same_tile_plan_result(expected, actual)

    def test_solve_tile_plan_options__dispatches_to_selected_exact_solver(self) -> None:
        options = self._build_conflicting_options()

        cp_sat_result = solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.CpSat, value_multiple=100)
        cbc_result = solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.MpCbc, value_multiple=100)
        scip_result = solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.MpScip, value_multiple=100)

        self.assertEqual(1800, cp_sat_result.max_value)
        self._assert_same_tile_plan_result(cp_sat_result, cbc_result)
        self._assert_same_tile_plan_result(cp_sat_result, scip_result)

    def test_solve_tile_plan_options__mkcp_solver_is_stubbed_until_grouped_input_is_abstracted(self) -> None:
        options = self._build_conflicting_options()

        with self.assertRaises(NotImplementedError):
            solve_tile_plan_options(options, turn_budget=8, solver=PlanSolver.MkcpPlusGreedyConflictResolution, value_multiple=100)

    def test_solve_tile_plan_options_with_cp_sat__returns_wrapped_items(self) -> None:
        tile_1 = self._tile(1)
        tile_2 = self._tile(2)
        source_item = WrappedSourceItem('source')
        options = [
            GenericTilePlanOption(item=source_item, length=1, tileSet={tile_1}, econValue=1.0),
            GenericTilePlanOption(item='other', length=1, tileSet={tile_2}, econValue=0.5),
        ]

        result = solve_tile_plan_options_with_cp_sat(options, turn_budget=1, value_multiple=100)

        self.assertEqual([source_item], result.chosen_items)

    def test_solver_wrappers__share_same_interface_for_non_conflicting_options(self) -> None:
        tile_1 = self._tile(1)
        tile_2 = self._tile(2)
        tile_3 = self._tile(3)
        options = [
            GenericTilePlanOption(item='best', length=4, tileSet={tile_1}, econValue=10.0),
            GenericTilePlanOption(item='middle', length=3, tileSet={tile_2}, econValue=7.0),
            GenericTilePlanOption(item='small', length=2, tileSet={tile_3}, econValue=4.0),
        ]

        cp_sat_result = solve_tile_plan_options_with_cp_sat(options, turn_budget=5, value_multiple=100)
        existing_solver_result = solve_tile_plan_options_with_existing_knapsack_solver(options, turn_budget=5, value_multiple=100)

        self.assertEqual(cp_sat_result.max_value, existing_solver_result.max_value)
        self.assertEqual(sorted(cp_sat_result.chosen_items), sorted(existing_solver_result.chosen_items))
        self.assertEqual(cp_sat_result.chosen_weight, existing_solver_result.chosen_weight)


if __name__ == '__main__':
    unittest.main()
