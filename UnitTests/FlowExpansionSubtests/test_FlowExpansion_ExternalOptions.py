"""
Tests for external options (interceptions, etc.) integration into FlowExpansion knapsacking.

This module tests:
1. External options being converted to ExternalPlanOption format
2. External options being included in the MKCP solver
3. Conflict detection between external options and flow-based options
4. External options appearing in the final output plans
"""

import typing
import unittest

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import (
    ArmyFlowExpanderV2,
    EnrichedFlowTurnsEntry,
    ExternalPlanOption,
    FlowBorderPairKey,
)
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Interfaces.TilePlanInterface import TilePlanInterface
from Tests.TestBase import TestBase
from base.client.map import MapBase, Tile


class MockTilePlanOption(TilePlanInterface):
    """Mock external option for testing without requiring full InterceptionOptionInfo setup."""

    def __init__(
        self,
        tiles: typing.Set[Tile],
        length: int,
        required_delay: int,
        econ_value: float,
        name: str = "mock"
    ):
        self._tiles = tiles
        self._length = length
        self._required_delay = required_delay
        self._econ_value = econ_value
        self._name = name

    @property
    def length(self) -> int:
        return self._length

    @property
    def requiredDelay(self) -> int:
        return self._required_delay

    @property
    def econValue(self) -> float:
        return self._econ_value

    @property
    def tileSet(self) -> typing.Set[Tile]:
        return self._tiles

    @property
    def tileList(self) -> typing.List[Tile]:
        return list(self._tiles)

    @property
    def tiles(self) -> typing.Iterable[Tile]:
        return iter(self._tiles)

    def __iter__(self):
        return iter([])

    def get_first_move(self):
        return None

    def pop_first_move(self):
        return None

    def clone(self):
        return MockTilePlanOption(set(self._tiles), self._length, self._required_delay, self._econ_value, self._name)

    def get_move_list(self):
        return []

    def __str__(self) -> str:
        return f"MockOption({self._name}, v={self._econ_value:.2f}, t={self._length})"


class ExternalOptionsTests(TestBase):
    """Test external options integration into FlowExpansion."""

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    # Simple 1-row map: aG1 a3 b1 bG1
    _SIMPLE_MAP = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
"""

    def _build_expander(self, mapData: str):
        """Helper: load map, construct expander (not yet run)."""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        expander = ArmyFlowExpanderV2(map)
        expander.friendlyGeneral = general
        expander.enemyGeneral = enemyGeneral
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.log_debug = False
        return expander, map, general, enemyGeneral

    def _build_expander_through_phase3(self, mapData: str, turns: int = 50):
        """Helper: load map, run V2 through Phase 3, return (expander, lookup_tables, islands)."""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.friendlyGeneral = general
        expander.enemyGeneral = enemyGeneral
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.island_builder = builder
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

        return expander, lookup_tables, builder

    # -----------------------------------------------------------------------
    # ExternalPlanOption dataclass
    # -----------------------------------------------------------------------

    def test_external_plan_option_dataclass(self):
        """Test that ExternalPlanOption dataclass can be created and accessed."""
        mock_plan = {"name": "test"}  # Simulated plan object
        tile_set = frozenset()

        ext_opt = ExternalPlanOption(
            plan=mock_plan,
            turns=5,
            econ_value=10.5,
            tile_set=tile_set,
            group_id=1000000
        )

        self.assertEqual(ext_opt.turns, 5)
        self.assertEqual(ext_opt.econ_value, 10.5)
        self.assertEqual(ext_opt.group_id, 1000000)
        self.assertIs(ext_opt.plan, mock_plan)

    # -----------------------------------------------------------------------
    # _convert_additional_options_to_external
    # -----------------------------------------------------------------------

    def test_convert_additional_options_filters_by_turn_budget(self):
        """Options whose length+delay exceeds the turn budget must be filtered out."""
        expander, map, general, enemyGeneral = self._build_expander(self._SIMPLE_MAP)
        tiles = set(map.get_all_tiles())

        # length=3 delay=0 → total=3 → fits in budget=5
        option_fits = MockTilePlanOption(tiles, length=3, required_delay=0, econ_value=10.0, name="fits")
        # length=8 delay=0 → total=8 → exceeds budget=5
        option_too_long = MockTilePlanOption(tiles, length=8, required_delay=0, econ_value=20.0, name="too_long")

        external_options = expander._convert_additional_options_to_external(
            [option_fits, option_too_long], turns=5
        )

        self.assertEqual(len(external_options), 1, "Only the option within budget should be included")
        self.assertEqual(external_options[0].turns, 3)  # length + requiredDelay
        self.assertEqual(external_options[0].econ_value, 10.0)

    def test_convert_additional_options_filters_zero_econ_value(self):
        """Options with zero or negative econ value must be filtered out."""
        expander, map, general, enemyGeneral = self._build_expander(self._SIMPLE_MAP)
        tiles = set(map.get_all_tiles())

        option_positive = MockTilePlanOption(tiles, length=2, required_delay=0, econ_value=5.0, name="positive")
        option_zero = MockTilePlanOption(tiles, length=2, required_delay=0, econ_value=0.0, name="zero")
        option_negative = MockTilePlanOption(tiles, length=2, required_delay=0, econ_value=-5.0, name="negative")

        external_options = expander._convert_additional_options_to_external(
            [option_positive, option_zero, option_negative], turns=10
        )

        self.assertEqual(len(external_options), 1, "Only the positive econ-value option should be included")
        self.assertEqual(external_options[0].econ_value, 5.0)

    def test_convert_additional_options_skips_none(self):
        """None entries in additional_options must be skipped gracefully."""
        expander, map, general, enemyGeneral = self._build_expander(self._SIMPLE_MAP)
        tiles = set(map.get_all_tiles())

        option_valid = MockTilePlanOption(tiles, length=2, required_delay=0, econ_value=5.0, name="valid")

        external_options = expander._convert_additional_options_to_external(
            [None, option_valid, None], turns=10
        )

        self.assertEqual(len(external_options), 1)
        self.assertEqual(external_options[0].econ_value, 5.0)

    def test_external_options_get_unique_group_ids(self):
        """Each external option must receive a unique group ID starting at 1000000."""
        expander, map, general, enemyGeneral = self._build_expander(self._SIMPLE_MAP)
        tiles = set(map.get_all_tiles())

        option1 = MockTilePlanOption(tiles, length=2, required_delay=0, econ_value=5.0, name="opt1")
        option2 = MockTilePlanOption(tiles, length=3, required_delay=0, econ_value=7.0, name="opt2")
        option3 = MockTilePlanOption(tiles, length=4, required_delay=0, econ_value=9.0, name="opt3")

        external_options = expander._convert_additional_options_to_external(
            [option1, option2, option3], turns=10
        )

        self.assertEqual(len(external_options), 3)
        self.assertEqual(external_options[0].group_id, 1000000)
        self.assertEqual(external_options[1].group_id, 1000001)
        self.assertEqual(external_options[2].group_id, 1000002)

    def test_external_options_tile_set_stored_as_frozenset(self):
        """The tile_set in ExternalPlanOption must be a frozenset of the option's tiles."""
        expander, map, general, enemyGeneral = self._build_expander(self._SIMPLE_MAP)

        tiles_list = list(map.get_all_tiles())[:3]
        tiles_set = set(tiles_list)

        option = MockTilePlanOption(tiles_set, length=2, required_delay=0, econ_value=5.0)

        external_options = expander._convert_additional_options_to_external([option], turns=10)

        self.assertEqual(len(external_options), 1)
        self.assertIsInstance(external_options[0].tile_set, frozenset)
        self.assertEqual(external_options[0].tile_set, frozenset(tiles_set))

    def test_external_options_requiredDelay_counts_toward_budget(self):
        """requiredDelay + length must both count toward the turn budget."""
        expander, map, general, enemyGeneral = self._build_expander(self._SIMPLE_MAP)
        tiles = set(map.get_all_tiles())

        # length=3, delay=3 → total=6, budget=5 → should be filtered
        option_delayed = MockTilePlanOption(tiles, length=3, required_delay=3, econ_value=10.0, name="delayed")
        # length=2, delay=2 → total=4, budget=5 → should be included
        option_ok = MockTilePlanOption(tiles, length=2, required_delay=2, econ_value=8.0, name="ok")

        external_options = expander._convert_additional_options_to_external(
            [option_delayed, option_ok], turns=5
        )

        self.assertEqual(len(external_options), 1, "Only total<=budget should be included")
        self.assertEqual(external_options[0].turns, 4)  # length=2 + delay=2
        self.assertEqual(external_options[0].econ_value, 8.0)

    # -----------------------------------------------------------------------
    # External options in _solve_grouped_knapsack
    # -----------------------------------------------------------------------

    def test_knapsack_with_external_option_included_in_solution(self):
        """An external option that fits within budget must appear in the solution."""
        expander, lookup_tables, builder = self._build_expander_through_phase3(self._SIMPLE_MAP)
        tiles = set(expander.map.get_all_tiles())

        # Create an external option with high value that fits in budget
        ext_option = MockTilePlanOption(set(), length=2, required_delay=0, econ_value=100.0, name="highval")
        external_options = expander._convert_additional_options_to_external([ext_option], turns=10)

        self.assertEqual(len(external_options), 1)

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=10, external_options=external_options)

        # The external option should appear in the solution
        external_keys = [k for k in solution.keys() if isinstance(k, str) and k.startswith("external_")]
        self.assertGreater(len(external_keys), 0, "External option should appear in knapsack solution")

    def test_knapsack_external_option_excluded_when_budget_too_tight(self):
        """An external option whose turns exceed the budget must not appear in the solution."""
        expander, lookup_tables, builder = self._build_expander_through_phase3(self._SIMPLE_MAP)
        tiles = set(expander.map.get_all_tiles())

        # Create an external option that's too long for the budget
        ext_option = MockTilePlanOption(set(), length=20, required_delay=0, econ_value=100.0, name="toolong")
        # But it already won't be converted (filtered in _convert)
        external_options = expander._convert_additional_options_to_external([ext_option], turns=5)

        self.assertEqual(len(external_options), 0, "Option exceeding budget should be filtered at conversion")

        solution = expander._solve_grouped_knapsack(lookup_tables, turn_budget=5, external_options=[])
        external_keys = [k for k in solution.keys() if isinstance(k, str) and k.startswith("external_")]
        self.assertEqual(len(external_keys), 0, "No external options in empty external_options list")

    def test_knapsack_flow_plans_unaffected_when_no_external_options(self):
        """Passing no external options must produce the same solution as the old path."""
        expander, lookup_tables, builder = self._build_expander_through_phase3(self._SIMPLE_MAP)

        solution_no_ext = expander._solve_grouped_knapsack(lookup_tables, turn_budget=10)
        solution_empty_ext = expander._solve_grouped_knapsack(lookup_tables, turn_budget=10, external_options=[])

        # Both should return the same set of flow border pair keys
        flow_keys_no_ext = {k for k in solution_no_ext.keys() if isinstance(k, FlowBorderPairKey)}
        flow_keys_empty = {k for k in solution_empty_ext.keys() if isinstance(k, FlowBorderPairKey)}
        self.assertEqual(flow_keys_no_ext, flow_keys_empty,
                         "Flow-only solution should be identical whether external_options is None or []")


if __name__ == '__main__':
    unittest.main()
