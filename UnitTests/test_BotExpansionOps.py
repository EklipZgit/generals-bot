import unittest
from types import SimpleNamespace
from unittest.mock import patch

import BotModules.BotExpansionOps as BotExpansionOpsModule


class _PerfEvent:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _PerfTimer:
    def begin_move_event(self, name: str):
        return _PerfEvent()


class _PlanTile:
    def __init__(
            self,
            visible: bool = True,
            player: int = 0,
            discovered: bool = True,
            isCity: bool = False,
            isGeneral: bool = False,
            army: int = 1,
            isNeutral: bool = False):
        self.visible = visible
        self.player = player
        self.discovered = discovered
        self.isCity = isCity
        self.isGeneral = isGeneral
        self.army = army
        self.isNeutral = isNeutral
        self.adjacents = []


class _PlanOption:
    def __init__(self, name: str, value: float, length: int = 1, tile_list: list | None = None):
        self.name = name
        self._econValue = value
        self._length = length
        self._tileList = tile_list if tile_list is not None else []

    @property
    def length(self) -> int:
        return self._length

    @property
    def requiredDelay(self) -> int:
        return 0

    @property
    def econValue(self) -> float:
        return self._econValue

    @property
    def tileSet(self) -> set:
        return set(self._tileList)

    @property
    def tileList(self) -> list:
        return self._tileList

    @property
    def tiles(self):
        return iter(())

    def __iter__(self):
        return iter(())

    def get_first_move(self):
        return None

    def pop_first_move(self):
        return None

    def clone(self):
        return _PlanOption(self.name, self._econValue, self._length, self._tileList)

    def get_move_list(self):
        return []

    def __str__(self) -> str:
        return self.name


class _InterceptPlan(_PlanOption):
    pass


class _FakeFlowExpander:
    instances = []

    def __init__(self, map, perf_timer):
        self.received_additional_options = None
        _FakeFlowExpander.instances.append(self)

    def get_expansion_options(self, **kwargs):
        self.received_additional_options = kwargs["additional_options"]
        return SimpleNamespace(flow_plans=[BotExpansionOpsUnitTests.flow_plan])


class BotExpansionOpsUnitTests(unittest.TestCase):
    flow_plan = _PlanOption("flow_plan", 8.8)

    def test_selector_prefers_highest_value_per_turn_over_uncertainty(self):
        uncertain_low_vt = _PlanOption(
            "uncertain_low_vt",
            1.0,
            length=1,
            tile_list=[
                _PlanTile(),
                _PlanTile(visible=False, player=-1, discovered=False, isNeutral=True)])
        higher_vt = _PlanOption(
            "higher_vt",
            3.0,
            length=2,
            tile_list=[
                _PlanTile(),
                _PlanTile()])

        selected = BotExpansionOpsModule.ExpandUtils.find_optimal_expansion_path_to_move_first(
            None,
            [uncertain_low_vt, higher_vt],
            set(),
            set(),
            lambda p, originalNegativeTiles: p.econValue,
            remainingTurns=5,
            searchingPlayer=0,
            friendlyPlayers=[0],
            territoryMap=None)

        self.assertIs(higher_vt, selected)

    def test_iterative_flow_only_passes_flow_outputs_to_expandutils_selector(self):
        _FakeFlowExpander.instances.clear()
        raw_intercept = _InterceptPlan("raw_intercept", -0.4)
        captured_additional_options = []

        def get_round_plan_with_expansion(map, **kwargs):
            captured_additional_options.extend(kwargs["additionalOptionValues"])
            return BotExpansionOpsModule.ExpandUtils.RoundPlan(
                0,
                0,
                self.flow_plan,
                [self.flow_plan],
                map.turn)

        bot = SimpleNamespace(
            territories=SimpleNamespace(territoryMap=None),
            general=SimpleNamespace(movable=[], army=1),
            _map=SimpleNamespace(turn=195, is_tile_enemy=lambda tile: False),
            timings=SimpleNamespace(cycleTurns=5, get_turn_in_cycle=lambda turn: 0),
            city_expand_plan=None,
            perf_timer=_PerfTimer(),
            teammate_general=None,
            intercept_plans={object(): SimpleNamespace(intercept_options={4: raw_intercept})},
            expansion_use_iterative_flow=True,
            expansion_use_legacy=False,
            targetPlayerExpectedGeneralLocation=None,
            expansion_allow_leaf_moves=False,
            captureLeafMoves=[],
            tileIslandBuilder=None,
            player=SimpleNamespace(index=0),
            targetPlayer=1,
            board_analysis=None,
            expansion_use_leaf_moves_first=False,
            viewInfo=SimpleNamespace(add_stats_line=lambda value: None, add_info_line=lambda value: None),
            expansion_single_iteration_time_cap=0.03,
            expansion_force_no_global_visited=True,
            expansion_force_global_visited_stage_1=False,
            expansion_allow_gather_plan_extension=False,
            expansion_always_include_non_terminating_leafmoves_in_iteration=False,
            expansion_length_weight_offset=-0.3,
            expansion_use_cutoff=True,
            blocking_tile_info=None,
            expansion_small_tile_time_ratio=1.0,
            last_flow_expander=None,
            last_flow_opt_collection=None,
            info=lambda value: None)

        with patch.object(BotExpansionOpsModule, "InterceptionOptionInfo", _InterceptPlan), \
                patch.object(BotExpansionOpsModule, "ArmyFlowExpanderV2", _FakeFlowExpander), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "get_expansion_weight_matrix", return_value=SimpleNamespace(raw=[])), \
                patch.object(BotExpansionOpsModule.BotTimings, "get_remaining_move_time", return_value=1.0), \
                patch.object(BotExpansionOpsModule.ExpandUtils, "get_round_plan_with_expansion", side_effect=get_round_plan_with_expansion), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "_should_use_iterative_negative_expand", return_value=False), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "check_launch_against_expansion_plan", side_effect=lambda bot_arg, plan, expansion_negatives: plan):
            plan = BotExpansionOpsModule.BotExpansionOps.build_expansion_plan(
                bot,
                timeLimit=0.1,
                expansionNegatives=set(),
                pathColor=(50, 30, 255))

        self.assertEqual([raw_intercept], _FakeFlowExpander.instances[0].received_additional_options)
        self.assertEqual([self.flow_plan], captured_additional_options)
        self.assertIs(self.flow_plan, plan.selected_option)


if __name__ == '__main__':
    unittest.main()
