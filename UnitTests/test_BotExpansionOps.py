import unittest
from types import SimpleNamespace
from unittest.mock import patch

from Algorithms import TileIslandBuilder
from BoardAnalyzer import BoardAnalyzer
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from Path import Path
from Tests.TestBase import TestBase
from base.client.map import MapBase

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
        self.coords = (0, 0)
        self.visible = visible
        self.player = player
        self.discovered = discovered
        self.isCity = isCity
        self.isGeneral = isGeneral
        self.army = army
        self.isNeutral = isNeutral
        self.adjacents = []


class _PlanOption:
    def __init__(self, name: str, value: float, length: int = 1, tile_list: list | None = None, required_delay: int = 0):
        self.name = name
        self._econValue = value
        self._length = length
        self._tileList = tile_list if tile_list is not None else []
        self._requiredDelay = required_delay
        self.path = self
        if len(self._tileList) > 0:
            self.start = SimpleNamespace(tile=self._tileList[0])
            self.tail = SimpleNamespace(tile=self._tileList[-1])
        else:
            self.start = SimpleNamespace(tile=None)
            self.tail = SimpleNamespace(tile=None)

    @property
    def length(self) -> int:
        return self._length

    @property
    def requiredDelay(self) -> int:
        return self._requiredDelay

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
        return _PlanOption(self.name, self._econValue, self._length, self._tileList, self._requiredDelay)

    def get_move_list(self):
        return []

    def str_no_vals(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return self.name


class _InterceptPlan(_PlanOption):
    pass


class _FakeFlowExpander:
    instances = []

    def __init__(self, map, perf_timer):
        self.received_additional_options = None
        self.received_constrained_flow_paths = None
        self.log_debug = False
        _FakeFlowExpander.instances.append(self)

    def get_expansion_options(self, **kwargs):
        self.received_additional_options = kwargs["additional_options"]
        self.received_constrained_flow_paths = kwargs["constrainedFlowPaths"]
        return SimpleNamespace(
            flow_plans=[BotExpansionOpsUnitTests.flow_plan],
            expansion_options=[BotExpansionOpsUnitTests.flow_plan])


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
        raw_intercept = _InterceptPlan("raw_intercept", -0.4, tile_list=[_PlanTile(), _PlanTile()])
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
            _map=SimpleNamespace(turn=195, is_tile_enemy=lambda tile: False, team_ids_by_player_index=[0, 1]),
            timings=SimpleNamespace(cycleTurns=5, get_turn_in_cycle=lambda turn: 0),
            city_expand_plan=None,
            perf_timer=_PerfTimer(),
            teammate_general=None,
            intercept_plans={object(): SimpleNamespace(intercept_options={4: raw_intercept})},
            cityAnalyzer=SimpleNamespace(owned_contested_cities=set()),
            city_capture_plan_option=None,
            contest_city_plan_option=None,
            quick_kill_city_plan_option=None,
            expansion_use_iterative_flow=True,
            flow_expander=None,
            expansion_use_legacy=False,
            targetPlayerExpectedGeneralLocation=None,
            expansion_allow_leaf_moves=False,
            captureLeafMoves=[],
            tileIslandBuilder=None,
            player=SimpleNamespace(index=0),
            targetPlayer=1,
            target_player_gather_path=None,
            shortest_path_to_target_player=None,
            opponent_tracker=SimpleNamespace(did_player_already_attack_this_round=lambda player: False),
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
            blocking_tile_info={},
            expansion_small_tile_time_ratio=1.0,
            last_flow_expander=None,
            last_flow_opt_collection=None,
            info=lambda value: None)

        with patch.object(BotExpansionOpsModule, "InterceptionOptionInfo", _InterceptPlan), \
                patch.object(BotExpansionOpsModule, "ArmyFlowExpanderV2", _FakeFlowExpander), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "get_expansion_weight_matrix", return_value=SimpleNamespace(raw=[])), \
                patch.object(BotExpansionOpsModule, "get_tile_army_mapmatrix", return_value=SimpleNamespace(raw=[])), \
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

    def test_iterative_flow_passes_defensive_corridor_as_constrained_flow_paths(self) -> None:
        """build_expansion_plan must hand the corridor to the flow expander as constrainedFlowPaths
        and the corridor's first nonfriendly frontier tile to the round-plan selector as
        preferredCaptureTarget (UnitTests/test_ExpansionCorridorPriority.py)."""
        # Tests/test_BotBehavior.py::BotBehaviorTests.test_should_attack_early_without_gather_repetition
        # and UnitTests/test_BotExpansionOps.py::BotExpansionOpsDefensiveFlowPathTests: while a
        # likely-kill-push corridor is active, build_expansion_plan must hand the directional
        # defensive path to ArmyFlowExpanderV2 as constrainedFlowPaths so flow cannot pull back
        # off the threatened home corridor. This asserts the wiring end-to-end through the real
        # build_expansion_plan call, not just that the helper exists.
        _FakeFlowExpander.instances.clear()
        capturedPreferredCaptureTargets: list[_PlanTile | None] = []

        def get_round_plan_with_expansion(map: MapBase, **kwargs) -> BotExpansionOpsModule.ExpandUtils.RoundPlan:
            capturedPreferredCaptureTargets.append(kwargs.get('preferredCaptureTarget'))
            return BotExpansionOpsModule.ExpandUtils.RoundPlan(
                0,
                0,
                self.flow_plan,
                [self.flow_plan],
                map.turn)

        farEnemyTile = _PlanTile(player=1, army=6)
        hostileEndpointTile = _PlanTile(player=1, army=4)
        friendlyCorridorTile = _PlanTile(player=0, army=3)
        friendlyGeneralTile = _PlanTile(player=0, army=5)
        farEnemyTile.coords = (1, 1)
        farEnemyTile.x = 1
        farEnemyTile.y = 1
        hostileEndpointTile.coords = (2, 1)
        hostileEndpointTile.x = 2
        hostileEndpointTile.y = 1
        friendlyCorridorTile.coords = (2, 0)
        friendlyCorridorTile.x = 2
        friendlyCorridorTile.y = 0
        friendlyGeneralTile.coords = (3, 0)
        friendlyGeneralTile.x = 3
        friendlyGeneralTile.y = 0
        # enemy_attack_path runs enemy general -> our general; reversed it yields our
        # general -> corridor -> first hostile tile, which is the defensive flow direction.
        enemyAttackPath = Path()
        enemyAttackPath.add_next(farEnemyTile)
        enemyAttackPath.add_next(hostileEndpointTile)
        enemyAttackPath.add_next(friendlyCorridorTile)
        enemyAttackPath.add_next(friendlyGeneralTile)

        bot = SimpleNamespace(
            territories=SimpleNamespace(territoryMap=None),
            general=SimpleNamespace(movable=[], army=1, lastMovedTurn=0, delta=SimpleNamespace(toTile=None)),
            _map=SimpleNamespace(
                turn=195,
                is_tile_enemy=lambda tile: False,
                is_tile_friendly=lambda tile: tile.player == 0,
                team_ids_by_player_index=[0, 1]),
            timings=SimpleNamespace(cycleTurns=50, get_turn_in_cycle=lambda turn: 0),
            city_expand_plan=None,
            perf_timer=_PerfTimer(),
            teammate_general=None,
            intercept_plans={},
            cityAnalyzer=SimpleNamespace(owned_contested_cities=set()),
            city_capture_plan_option=None,
            contest_city_plan_option=None,
            quick_kill_city_plan_option=None,
            blocking_tile_info={},
            expansion_use_iterative_flow=True,
            flow_expander=None,
            expansion_use_legacy=False,
            targetPlayerExpectedGeneralLocation=None,
            expansion_allow_leaf_moves=False,
            captureLeafMoves=[],
            leafMoves=[],
            enemy_attack_path=enemyAttackPath,
            likely_kill_push=True,
            is_all_in_losing=False,
            is_all_in_army_advantage=False,
            all_in_city_behind=False,
            _is_ffa_situation=False,
            tileIslandBuilder=SimpleNamespace(
                all_tile_islands=[],
                tile_islands_by_player={0: []},
                tile_islands_by_team_id={1: []}),
            player=SimpleNamespace(index=0),
            targetPlayer=1,
            target_player_gather_path=None,
            shortest_path_to_target_player=SimpleNamespace(length=5),
            opponent_tracker=SimpleNamespace(did_player_already_attack_this_round=lambda player: False),
            board_analysis=SimpleNamespace(
                intergeneral_analysis=SimpleNamespace(aMap=SimpleNamespace(raw=[0] * 64))),
            enemy_expansion_plan=None,
            expansion_use_leaf_moves_first=False,
            viewInfo=SimpleNamespace(
                add_stats_line=lambda value: None,
                add_info_line=lambda value: None,
                add_targeted_tile=lambda *args, **kwargs: None),
            expansion_single_iteration_time_cap=0.03,
            expansion_force_no_global_visited=True,
            expansion_force_global_visited_stage_1=False,
            expansion_allow_gather_plan_extension=False,
            expansion_always_include_non_terminating_leafmoves_in_iteration=False,
            expansion_length_weight_offset=-0.3,
            expansion_use_cutoff=True,
            expansion_small_tile_time_ratio=1.0,
            last_flow_expander=None,
            last_flow_opt_collection=None,
            info=lambda value: None)

        with patch.object(BotExpansionOpsModule, "ArmyFlowExpanderV2", _FakeFlowExpander), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "get_expansion_weight_matrix", return_value=SimpleNamespace(raw=[0.0] * 64)), \
                patch.object(BotExpansionOpsModule, "get_tile_army_mapmatrix", return_value=SimpleNamespace(raw=[0] * 64)), \
                patch.object(BotExpansionOpsModule.BotTimings, "get_remaining_move_time", return_value=1.0), \
                patch.object(BotExpansionOpsModule.ExpandUtils, "get_round_plan_with_expansion", side_effect=get_round_plan_with_expansion), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "_should_use_iterative_negative_expand", return_value=False), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "check_launch_against_expansion_plan", side_effect=lambda bot_arg, plan, expansion_negatives: plan):
            plan = BotExpansionOpsModule.BotExpansionOps.build_expansion_plan(
                bot,
                timeLimit=0.1,
                expansionNegatives=set(),
                pathColor=(50, 30, 255))

        self.assertIs(self.flow_plan, plan.selected_option)
        self.assertEqual(1, len(_FakeFlowExpander.instances))
        constrained = _FakeFlowExpander.instances[0].received_constrained_flow_paths
        self.assertIsNotNone(constrained)
        self.assertEqual(1, len(constrained))
        corridorPath = constrained[0]
        self.assertIsInstance(corridorPath, Path)
        # reversed enemy path: our general (3,0) -> (2,0) -> first hostile (2,1); (1,1)-side
        # enemy tiles beyond the first hostile endpoint must be excluded.
        self.assertEqual(
            [(3, 0), (2, 0), (2, 1)],
            [(t.coords[0], t.coords[1]) for t in corridorPath.tileList])
        # The selector must also receive the corridor's first nonfriendly frontier tile
        # (the path tail) as preferredCaptureTarget so corridor-attacking gather plans
        # outrank higher econ/turn flank plans (see UnitTests/test_ExpansionCorridorPriority.py).
        self.assertEqual(1, len(capturedPreferredCaptureTargets))
        self.assertIs(hostileEndpointTile, capturedPreferredCaptureTargets[0])

    def test_expandutils_skips_flow_option_with_no_first_move(self):
        no_move_flow_plan = _PlanOption(
            "no_move_flow_plan",
            8.8,
            length=1,
            tile_list=[_PlanTile(), _PlanTile()])

        plan = BotExpansionOpsModule.ExpandUtils.get_round_plan_with_expansion(
            map=SimpleNamespace(
                turn=195,
                players=[],
                team_ids_by_player_index=[0, 1],
                is_player_on_team_with=lambda tile_player, searching_player: tile_player == searching_player),
            searchingPlayer=0,
            targetPlayer=1,
            turns=5,
            boardAnalysis=SimpleNamespace(
                intergeneral_analysis=SimpleNamespace(aMap=None, bMap=None),
                inter_general_distance=10,
                within_extended_play_area_threshold=0,
                within_core_play_area_threshold=0),
            territoryMap=None,
            tileIslands=None,
            negativeTiles=set(),
            leafMoves=[],
            viewInfo=None,
            includeExpansionSearch=False,
            additionalOptionValues=[no_move_flow_plan],
            perfTimer=_PerfTimer(),
            skipKnapsacking=False)

        self.assertIsNone(plan.selected_option)
        self.assertEqual([], plan.all_paths)

    def test_build_expansion_plan_should_not_check_target_attack_state_without_valid_target_player(self):
        _FakeFlowExpander.instances.clear()

        def get_round_plan_with_expansion(map, **kwargs):
            return BotExpansionOpsModule.ExpandUtils.RoundPlan(
                0,
                0,
                self.flow_plan,
                [self.flow_plan],
                map.turn)

        opponent_tracker = SimpleNamespace(
            did_player_already_attack_this_round=lambda player: (_ for _ in ()).throw(AssertionError("should not be called for invalid target player")))

        bot = SimpleNamespace(
            territories=SimpleNamespace(territoryMap=None),
            general=SimpleNamespace(movable=[], army=1),
            _map=SimpleNamespace(turn=195, is_tile_enemy=lambda tile: False, team_ids_by_player_index=[0, 1, 2]),
            timings=SimpleNamespace(cycleTurns=5, get_turn_in_cycle=lambda turn: 0),
            city_expand_plan=None,
            perf_timer=_PerfTimer(),
            teammate_general=None,
            intercept_plans={},
            cityAnalyzer=SimpleNamespace(owned_contested_cities=set()),
            city_capture_plan_option=None,
            contest_city_plan_option=None,
            quick_kill_city_plan_option=None,
            expansion_use_iterative_flow=True,
            flow_expander=None,
            expansion_use_legacy=False,
            targetPlayerExpectedGeneralLocation=None,
            expansion_allow_leaf_moves=False,
            captureLeafMoves=[],
            tileIslandBuilder=None,
            player=SimpleNamespace(index=0),
            targetPlayer=-1,
            target_player_gather_path=SimpleNamespace(),
            shortest_path_to_target_player=SimpleNamespace(tileList=[]),
            opponent_tracker=opponent_tracker,
            enemy_attack_path=None,
            board_analysis=None,
            expansion_use_leaf_moves_first=False,
            viewInfo=SimpleNamespace(
                add_stats_line=lambda value: None,
                add_info_line=lambda value: None,
                add_targeted_tile=lambda tile, style: None,
                bottomLeftGridText=SimpleNamespace(raw=[]),
                bottomMidLeftGridText=SimpleNamespace(raw=[])),
            expansion_single_iteration_time_cap=0.03,
            expansion_force_no_global_visited=True,
            expansion_force_global_visited_stage_1=False,
            expansion_allow_gather_plan_extension=False,
            expansion_always_include_non_terminating_leafmoves_in_iteration=False,
            expansion_length_weight_offset=-0.3,
            expansion_use_cutoff=True,
            blocking_tile_info={},
            expansion_small_tile_time_ratio=1.0,
            last_flow_expander=None,
            last_flow_opt_collection=None,
            info=lambda value: None)

        with patch.object(BotExpansionOpsModule, "ArmyFlowExpanderV2", _FakeFlowExpander), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "get_expansion_weight_matrix", return_value=SimpleNamespace(raw=[])), \
                patch.object(BotExpansionOpsModule, "get_tile_army_mapmatrix", return_value=SimpleNamespace(raw=[])), \
                patch.object(BotExpansionOpsModule.BotTimings, "get_remaining_move_time", return_value=1.0), \
                patch.object(BotExpansionOpsModule.ExpandUtils, "get_round_plan_with_expansion", side_effect=get_round_plan_with_expansion), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "_should_use_iterative_negative_expand", return_value=False), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "check_launch_against_expansion_plan", side_effect=lambda bot_arg, plan, expansion_negatives: plan):
            plan = BotExpansionOpsModule.BotExpansionOps.build_expansion_plan(
                bot,
                timeLimit=0.1,
                expansionNegatives=set(),
                pathColor=(50, 30, 255))

        self.assertIs(self.flow_plan, plan.selected_option)

    def test_build_expansion_plan_does_not_leave_delayed_intercept_as_selected_option(self):
        _FakeFlowExpander.instances.clear()
        source_tile = _PlanTile(player=0, army=39)
        dest_tile = _PlanTile(player=0, army=1)
        delayed_intercept = _InterceptPlan(
            "delayed_intercept",
            20.21,
            length=5,
            tile_list=[source_tile, dest_tile],
            required_delay=1)

        def get_round_plan_with_expansion(map, **kwargs):
            return BotExpansionOpsModule.ExpandUtils.RoundPlan(
                0,
                0,
                delayed_intercept,
                [delayed_intercept],
                map.turn)

        intercept_plan = SimpleNamespace(
            intercept_options={5: delayed_intercept},
            get_intercept_option_by_path=lambda path: delayed_intercept if path is delayed_intercept else None,
            threats=[])

        bot = SimpleNamespace(
            territories=SimpleNamespace(territoryMap=None),
            general=SimpleNamespace(movable=[], army=1),
            _map=SimpleNamespace(turn=238, is_tile_enemy=lambda tile: False, team_ids_by_player_index=[0, 1]),
            timings=SimpleNamespace(cycleTurns=50, get_turn_in_cycle=lambda turn: 38),
            cityAnalyzer=SimpleNamespace(owned_contested_cities=set()),
            city_expand_plan=None,
            perf_timer=_PerfTimer(),
            teammate_general=None,
            intercept_plans={object(): intercept_plan},
            city_capture_plan_option=None,
            contest_city_plan_option=None,
            quick_kill_city_plan_option=None,
            expansion_use_iterative_flow=False,
            expansion_use_legacy=False,
            targetPlayerExpectedGeneralLocation=None,
            expansion_allow_leaf_moves=False,
            captureLeafMoves=[],
            tileIslandBuilder=None,
            player=SimpleNamespace(index=0),
            targetPlayer=1,
            target_player_gather_path=None,
            shortest_path_to_target_player=None,
            opponent_tracker=SimpleNamespace(did_player_already_attack_this_round=lambda player: False),
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
            blocking_tile_info={},
            expansion_small_tile_time_ratio=1.0,
            last_flow_expander=None,
            last_flow_opt_collection=None,
            info=lambda value: None)

        with patch.object(BotExpansionOpsModule, "InterceptionOptionInfo", _InterceptPlan), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "get_expansion_weight_matrix", return_value=SimpleNamespace(raw=[])), \
                patch.object(BotExpansionOpsModule, "get_tile_army_mapmatrix", return_value=SimpleNamespace(raw=[])), \
                patch.object(BotExpansionOpsModule.BotTimings, "get_remaining_move_time", return_value=1.0), \
                patch.object(BotExpansionOpsModule.ExpandUtils, "get_round_plan_with_expansion", side_effect=get_round_plan_with_expansion), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "_should_use_iterative_negative_expand", return_value=False), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, "check_launch_against_expansion_plan", side_effect=lambda bot_arg, plan, expansion_negatives: plan):
            plan = BotExpansionOpsModule.BotExpansionOps.build_expansion_plan(
                bot,
                timeLimit=0.1,
                expansionNegatives=set(),
                pathColor=(50, 30, 255))

        self.assertIsNone(plan.selected_option)
        self.assertFalse(plan.includes_intercept)
        self.assertEqual([delayed_intercept], plan.intercept_waiting)


class BotExpansionOpsDefensiveFlowPathTests(TestBase):
    """Focused coverage for BotExpansionOps.get_defensive_flow_path.

    Regression context: Tests/test_BotBehavior.py::BotBehaviorTests
    .test_should_attack_early_without_gather_repetition (QaFHRLrxn t213 import)
    showed the bot gathering/repeating instead of holding the threatened home
    corridor when likely_kill_push flickered with own-army changes. The helper
    returns a stable forward defensive corridor path (used as constrainedFlowPaths
    by iterative flow expansion) that is independent of that flicker.
    """

    __slots__ = (
        'scenarioMap',
        'scenarioGeneral',
        'scenarioEnemyGeneral',
        'enemyAttackPath',
        '_alreadyAttacked',
        'scenarioBot',
        '_priorDoNotRandomize',
    )

    # 4x3 map: 'b' (player 1) is our side via player_index=1, 'a' (player 0) is the
    # enemy. Our general (3,0) is threatened from enemy general (0,2); the hand-built
    # enemy_attack_path below walks (0,2)->(0,1)->(1,1)->(2,1)->(2,0)->(3,0). Cell (3,1)
    # is a friendly side tile (b7) adjacent to the general island but off the corridor.
    _MAP_DATA = """
|    |    |    |
b3   M    b2   bG8
a4   a6   a3   b7
aG30 a1   a1   a1
|
player_index=1
"""

    def setUp(self) -> None:
        super().setUp()
        self._priorDoNotRandomize = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(self._restore_do_not_randomize)
        MapBase.DO_NOT_RANDOMIZE = True
        self.scenarioMap, self.scenarioGeneral, self.scenarioEnemyGeneral = (
            self.load_map_and_generals_from_string(self._MAP_DATA, 250, fill_out_tiles=True))
        self.enemyAttackPath = Path()
        for coord in [(0, 2), (0, 1), (1, 1), (2, 1), (2, 0), (3, 0)]:
            self.enemyAttackPath.add_next(self.scenarioMap.At(*coord))
        self._alreadyAttacked = False
        self.scenarioBot = SimpleNamespace(
            expansion_use_iterative_flow=True,
            enemy_attack_path=self.enemyAttackPath,
            targetPlayer=0,
            shortest_path_to_target_player=SimpleNamespace(length=5),
            likely_kill_push=True,
            opponent_tracker=SimpleNamespace(
                did_player_already_attack_this_round=lambda player: self._alreadyAttacked),
            is_all_in_losing=False,
            is_all_in_army_advantage=False,
            all_in_city_behind=False,
            _is_ffa_situation=False,
            _map=self.scenarioMap,
            general=SimpleNamespace(army=30),
            player=SimpleNamespace(index=1))

    def _restore_do_not_randomize(self) -> None:
        """Restores MapBase.DO_NOT_RANDOMIZE to its pre-test value (addCleanup from setUp)."""
        MapBase.DO_NOT_RANDOMIZE = self._priorDoNotRandomize

    def _coords(self, path: Path) -> list[tuple[int, int]]:
        """Returns (x, y) coordinate tuples for each tile in the path, in path order."""
        return [(t.x, t.y) for t in path.tileList]

    def test_get_defensive_flow_path_returns_forward_friendly_prefix_with_hostile_endpoint(self) -> None:
        """Corridor path keeps the friendly prefix plus first hostile endpoint only."""
        result = BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot)

        self.assertIsNotNone(result)
        # enemy path is enemy-general -> our-general; reversed it is our-general ->
        # corridor -> first hostile tile. Friendly prefix (3,0),(2,0) plus the first
        # nonfriendly endpoint (2,1); the remaining enemy suffix is excluded.
        self.assertEqual([(3, 0), (2, 0), (2, 1)], self._coords(result))
        self.assertEqual(2, result.length)

    def test_get_defensive_flow_path_does_not_mutate_enemy_attack_path(self) -> None:
        """Building the corridor must not reorder or edit the source enemy path."""
        before = self._coords(self.enemyAttackPath)

        BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot)

        self.assertEqual(before, self._coords(self.enemyAttackPath))
        self.assertEqual((0, 2), (self.enemyAttackPath.tileList[0].x, self.enemyAttackPath.tileList[0].y))

    def test_get_defensive_flow_path_stays_active_when_likely_kill_push_clears_with_sufficient_army(self) -> None:
        """Flicker regression: corridor stays active with LKP false on density evidence alone.

        The helper must not gate on our own army amount, so collecting enough defense
        army does not immediately release sideways flow (the QaFHRLrxn alternation bug).
        """
        self.scenarioBot.likely_kill_push = False
        self._alreadyAttacked = False
        self.scenarioBot.shortest_path_to_target_player = SimpleNamespace(length=5)

        for army in (1, 500):
            with self.subTest(ownArmy=army):
                self.scenarioBot.general = SimpleNamespace(army=army)
                result = BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot)
                self.assertIsNotNone(result)
                self.assertEqual([(3, 0), (2, 0), (2, 1)], self._coords(result))

    def test_get_defensive_flow_path_returns_none_when_density_evidence_insufficient(self) -> None:
        """LKP false + sparse enemy path-density evidence yields no corridor."""
        self.scenarioBot.likely_kill_push = False
        self._alreadyAttacked = False
        # halfDist=15 pushes the evidence window past the enemy-heavy segment and the
        # weighted density (5.0) no longer exceeds halfDist//2 (7).
        self.scenarioBot.shortest_path_to_target_player = SimpleNamespace(length=30)

        self.assertIsNone(BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot))

    def test_get_defensive_flow_path_returns_none_when_opponent_already_attacked_unless_likely_kill_push(self) -> None:
        """Opponent already attacking suppresses the corridor unless LKP explicitly set."""
        self.scenarioBot.likely_kill_push = False
        self._alreadyAttacked = True
        self.scenarioBot.shortest_path_to_target_player = SimpleNamespace(length=5)

        self.assertIsNone(BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot))

        # An explicit likely_kill_push accepts immediately, bypassing both the
        # already-attacked and density-evidence gates.
        self.scenarioBot.likely_kill_push = True
        self.scenarioBot.shortest_path_to_target_player = SimpleNamespace(length=30)
        result = BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot)
        self.assertIsNotNone(result)
        self.assertEqual([(3, 0), (2, 0), (2, 1)], self._coords(result))

    def test_get_defensive_flow_path_returns_none_for_unsupported_states(self) -> None:
        """Non-iterative/all-in/FFA/missing-path/invalid-target states yield no corridor."""
        get_path = BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path

        with self.subTest(case='non-iterative'):
            self.scenarioBot.expansion_use_iterative_flow = False
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.expansion_use_iterative_flow = True

        with self.subTest(case='all-in'):
            self.scenarioBot.is_all_in_losing = True
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.is_all_in_losing = False

        with self.subTest(case='ffa'):
            self.scenarioBot._is_ffa_situation = True
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot._is_ffa_situation = False

        with self.subTest(case='missing-enemy-attack-path'):
            self.scenarioBot.enemy_attack_path = None
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.enemy_attack_path = self.enemyAttackPath

        with self.subTest(case='invalid-target'):
            self.scenarioBot.targetPlayer = -1
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.targetPlayer = 0

        with self.subTest(case='missing-shortest-path'):
            self.scenarioBot.shortest_path_to_target_player = None
            self.assertIsNone(get_path(self.scenarioBot))

    def test_get_defensive_flow_path_returns_none_for_degenerate_paths(self) -> None:
        """Empty, single-tile, and nonfriendly-start paths yield no corridor.

        All cases run under explicit likely_kill_push so the evidence gate is bypassed
        and only the path-shape guards are exercised.
        """
        get_path = BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path
        self.scenarioBot.likely_kill_push = True

        with self.subTest(case='empty-path'):
            self.scenarioBot.enemy_attack_path = Path()
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.enemy_attack_path = self.enemyAttackPath

        with self.subTest(case='single-friendly-tile-no-transition'):
            singleTilePath = Path()
            singleTilePath.add_next(self.scenarioMap.At(3, 0))
            self.scenarioBot.enemy_attack_path = singleTilePath
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.enemy_attack_path = self.enemyAttackPath

        with self.subTest(case='reversed-start-nonfriendly'):
            nonfriendlyStartPath = Path()
            nonfriendlyStartPath.add_next(self.scenarioMap.At(2, 0))
            nonfriendlyStartPath.add_next(self.scenarioMap.At(2, 1))
            self.scenarioBot.enemy_attack_path = nonfriendlyStartPath
            self.assertIsNone(get_path(self.scenarioBot))
            self.scenarioBot.enemy_attack_path = self.enemyAttackPath

    def test_defensive_flow_path_constrains_only_corridor_outgoing_arcs(self) -> None:
        """Corridor constraint removes off-path outgoing arcs but keeps inbound flow.

        Transition-geometry coverage mirroring
        UnitTests/FlowExpansionSubtests/test_FlowExpansion_ExternalOptions.py
        ::ExternalOptionsTests.test_constrained_flow_paths_limit_only_outgoing_edges_from_path_islands:
        outgoing arcs from corridor source islands may only follow the corridor
        (forward progress into the hostile endpoint stays allowed), off-corridor
        outgoing arcs and pullback arcs are removed, and arcs INTO corridor islands
        from unconstrained sources (friendly side reinforcements, enemy outgoing)
        remain.
        """
        defensivePath = BotExpansionOpsModule.BotExpansionOps.get_defensive_flow_path(self.scenarioBot)
        self.assertIsNotNone(defensivePath)
        self.assertEqual([(3, 0), (2, 0), (2, 1)], self._coords(defensivePath))

        analysis = BoardAnalyzer(self.scenarioMap, self.scenarioGeneral)
        analysis.rebuild_intergeneral_analysis(self.scenarioEnemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(self.scenarioMap, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(self.scenarioEnemyGeneral)

        expander = ArmyFlowExpanderV2(self.scenarioMap)
        expander.friendlyGeneral = self.scenarioGeneral
        expander.enemyGeneral = self.scenarioEnemyGeneral
        expander.target_team = self.scenarioMap.team_ids_by_player_index[self.scenarioEnemyGeneral.player]
        expander.island_builder = builder
        expander.constrained_flow_paths = [defensivePath]
        expander.log_debug = False

        expander._ensure_flow_graph_exists(builder, turns=50)
        graph_data = expander._ortools_finder.ortools_graph_data_no_neut
        arcs = {
            (
                graph_data.idx_to_node[int(graph_data.start_nodes[arc_idx])],
                graph_data.idx_to_node[int(graph_data.end_nodes[arc_idx])],
            )
            for arc_idx in range(len(graph_data.start_nodes))
        }

        def island_id(x: int, y: int) -> int:
            island = builder.tile_island_lookup.raw[self.scenarioMap.At(x, y).tile_index]
            self.assertIsNotNone(island)
            return island.unique_id

        gen_island = island_id(3, 0)
        corridor_island = island_id(2, 0)
        hostile_island = island_id(2, 1)
        side_island = island_id(3, 1)
        off_corridor_friendly_island = island_id(0, 0)
        enemy_near_island = island_id(0, 1)

        # The (3,1) side tile must be friendly and in its own island distinct from both
        # corridor source islands, or the edge claims below are meaningless.
        self.assertTrue(self.scenarioMap.is_tile_friendly(self.scenarioMap.At(3, 1)))
        self.assertNotEqual(side_island, gen_island)
        self.assertNotEqual(side_island, corridor_island)

        # corridor hop: our general island -> corridor island (forward along path)
        self.assertIn((-gen_island, corridor_island), arcs)
        # off-corridor outgoing from the general island is forbidden, even toward the
        # friendly side tile
        self.assertNotIn((-gen_island, side_island), arcs)
        # forward progress: corridor island -> first hostile endpoint island
        self.assertIn((-corridor_island, hostile_island), arcs)
        # pullback: corridor island -> our general island is forbidden (no gather-pullback)
        self.assertNotIn((-corridor_island, gen_island), arcs)
        # friendly side reinforcement into the general/corridor island stays allowed
        self.assertIn((-side_island, gen_island), arcs)
        # enemy outgoing from the unconstrained hostile island into the corridor stays allowed
        self.assertIn((-hostile_island, corridor_island), arcs)
        # unrelated islands are unconstrained in both directions
        self.assertIn((-off_corridor_friendly_island, enemy_near_island), arcs)
        self.assertIn((-enemy_near_island, off_corridor_friendly_island), arcs)


if __name__ == '__main__':
    unittest.main()
