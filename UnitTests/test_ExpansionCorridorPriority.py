"""
Tests for the ExpandUtils ``preferredCaptureTarget`` corridor-attack priority.

Context: Tests/test_BotBehavior.py::BotBehaviorTests
.test_should_attack_early_without_gather_repetition (QaFHRLrxn t213 import). The
directional defensive corridor (BotExpansionOps.get_defensive_flow_path, supplied to
iterative flow as constrainedFlowPaths) removed gather repetition, but the round-plan
selector still deferred the corridor's gather plan via path_has_cities_and_should_wait
and preferred a higher econ/turn flank plan, leaving the first qualifying attack at
turn 231 instead of the required <=225.

Specified contract: an optional ``preferredCaptureTarget: Tile | None = None``
parameter on ExpandUtils.get_round_plan_with_expansion and
ExpandUtils.find_optimal_expansion_path_to_move_first. Among already-knapsacked viable
GatherCapturePlan options -- viable means ``requiredDelay == 0`` and
``get_first_move()`` is not None -- a plan whose ``tileSet`` contains a non-friendly
target gains a priority tier evaluated before the existing city-capture priority and
the existing uncertainty+econ/turn ranking. ``tileSet`` is the union of the plan's
executable tree tiles and ``approximate_capture_tiles``: a nonfriendly executable
tree node is itself a capture, while ``approximate_capture_tiles`` only holds
captures outside that tree (GatherCapturePlan._include_capture_estimation_in_calculation
subtracts tileSet members before recording approximations). Preferred plans bypass
only the generic city-source income wait (path_has_cities_and_should_wait), never
``requiredDelay``. ``None``, an unmatched target, or an already-friendly target
leaves existing behavior unchanged. Only actual GatherCapturePlan options qualify;
external city/intercept plans gain no priority.
"""

from __future__ import annotations

import typing
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ExpandUtils
import Gather
from Gather.GatherCapturePlan import GatherCapturePlan
from Interfaces import MapMatrixInterface, TilePlanInterface
from Models import GatherTreeNode, Move
from Tests.TestBase import TestBase
from base.client.map import MapBase, Tile

from UnitTests import test_fix_expandutils_zerodiv as zerodiv_fixtures


def _econ_value_eval(path: TilePlanInterface, original_negative_tiles: set[Tile]) -> float:
    """postPathEvalFunction stand-in returning the option's econValue unchanged."""
    return path.econValue


def _first_move_lookup(
        first_moves: dict[GatherCapturePlan, Move | None],
) -> typing.Callable[[GatherCapturePlan], Move | None]:
    """Returns a get_first_move stand-in resolving each plan through first_moves (absent => None)."""

    def _fake_first_move(plan_self: GatherCapturePlan) -> Move | None:
        return first_moves.get(plan_self)

    return _fake_first_move


def _waiting_only_for(
        waiting_paths: set[TilePlanInterface],
) -> typing.Callable[..., bool]:
    """Builds a path_has_cities_and_should_wait stand-in that waits only for the given plan objects."""

    def _fake_wait(
            path: TilePlanInterface,
            friendly_players: list[int],
            negative_tiles: set[Tile],
            territory_map: MapMatrixInterface[int] | None,
            remaining_turns: int) -> bool:
        return path in waiting_paths

    return _fake_wait


class ExpansionCorridorPriorityTests(TestBase):
    """Selector-level and wiring coverage for ExpandUtils preferredCaptureTarget."""

    __slots__ = (
        'scenarioMap',
        'scenarioGeneral',
        'scenarioEnemyGeneral',
        'searchingPlayer',
        '_priorDoNotRandomize',
    )

    # Single-row map, player_index=1 makes 'b' our side. (4,0) N5 is the neutral
    # frontier tile standing in for defensiveFlowPath.tail.tile; (3,0) C6 is a
    # neutral city (player -1 still counts as a city capture for _plan_captures_city);
    # (1,0)/(2,0) are plain enemy tiles used by the flank plan. aTiles/bTiles keep
    # fill_out_tiles' tile-count reconciliation satisfied without score directives.
    _MAP_DATA = """
|    |    |    |    |    |    |    |    |    |    |
aG20 a4   a3   C6   N5   b2   bG30 b12  b6   b3
|    |    |    |    |    |    |    |    |    |    |
player_index=1
bot_target_player=0
aTiles=3
bTiles=5
"""

    def setUp(self) -> None:
        super().setUp()
        self._priorDoNotRandomize = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(self._restore_do_not_randomize)
        MapBase.DO_NOT_RANDOMIZE = True
        self.scenarioMap, self.scenarioGeneral, self.scenarioEnemyGeneral = (
            self.load_map_and_generals_from_string(self._MAP_DATA, 250, fill_out_tiles=True))
        self.searchingPlayer = self.scenarioGeneral.player

    def _restore_do_not_randomize(self) -> None:
        """Restores MapBase.DO_NOT_RANDOMIZE to its pre-test value (addCleanup from setUp)."""
        MapBase.DO_NOT_RANDOMIZE = self._priorDoNotRandomize

    def _build_plan(
            self,
            econ_value: float,
            turns: int,
            approximate_tiles: set[Tile],
            required_delay: int = 0,
            root_nodes: list[GatherTreeNode] | None = None) -> GatherCapturePlan:
        """
        Builds a real GatherCapturePlan with no gather roots (or the given roots) and the
        given approximate capture tiles, which populate the plan's tileSet alongside any
        root-node tiles. get_first_move is stubbed per-test through
        patch.object(GatherCapturePlan, 'get_first_move', ...).
        """
        plan = GatherCapturePlan(
            rootNodes=root_nodes if root_nodes is not None else [],
            map=self.scenarioMap,
            econValue=econ_value,
            turnsTotalInclCap=turns,
            gatherValue=30,
            gatherCapturePoints=float(econ_value),
            gatherTurns=0,
            requiredDelay=required_delay,
            friendlyCityCount=0,
            enemyCityCount=0,
            asPlayer=self.searchingPlayer)
        plan.include_approximate_capture_tiles(approximate_tiles)
        return plan

    def _select_first_path(
            self,
            plans: list[GatherCapturePlan],
            preferred_target: Tile | None,
            waiting_plans: set[TilePlanInterface] | None = None,
            first_moves: dict[GatherCapturePlan, Move | None] | None = None,
            stub_first_moves: bool = True) -> TilePlanInterface | None:
        """
        Runs ExpandUtils.find_optimal_expansion_path_to_move_first over real
        GatherCapturePlans with city-waiting stubbed per plan. get_first_move is
        stubbed per plan unless stub_first_moves is False (real-tree plans keep
        their executable moves).
        """
        if waiting_plans is None:
            waiting_plans = set()
        if first_moves is None:
            first_moves = {}
        friendly_players = self.scenarioMap.get_teammates(self.searchingPlayer)
        if stub_first_moves:
            with patch.object(GatherCapturePlan, 'get_first_move', _first_move_lookup(first_moves)), \
                    patch.object(ExpandUtils, 'path_has_cities_and_should_wait', _waiting_only_for(waiting_plans)):
                return ExpandUtils.find_optimal_expansion_path_to_move_first(
                    self.scenarioMap,
                    plans,
                    set(),
                    set(),
                    _econ_value_eval,
                    remainingTurns=30,
                    searchingPlayer=self.searchingPlayer,
                    friendlyPlayers=friendly_players,
                    territoryMap=None,
                    preferredCaptureTarget=preferred_target)
        with patch.object(ExpandUtils, 'path_has_cities_and_should_wait', _waiting_only_for(waiting_plans)):
            return ExpandUtils.find_optimal_expansion_path_to_move_first(
                self.scenarioMap,
                plans,
                set(),
                set(),
                _econ_value_eval,
                remainingTurns=30,
                searchingPlayer=self.searchingPlayer,
                friendlyPlayers=friendly_players,
                territoryMap=None,
                preferredCaptureTarget=preferred_target)

    def _assert_preferred_target_forwarded(self, find_mock: MagicMock, target: Tile) -> None:
        """Asserts the selector mock received preferredCaptureTarget (kwarg or positional)."""
        call = find_mock.call_args
        self.assertIsNotNone(call)
        forwarded = call.kwargs.get('preferredCaptureTarget')
        if forwarded is None:
            forwarded = next((arg for arg in call.args if arg is target), None)
        self.assertIs(target, forwarded)

    def test_preferred_capture_target_beats_city_waiting_and_lower_econ_per_turn(self) -> None:
        """
        The corridor plan waits on generic city-source income and has lower econ/turn
        than the flank plan, yet must win when its tileSet contains the preferred
        frontier target; without the target the flank plan still wins.
        """
        frontier = self.scenarioMap.At(4, 0)
        corridorPlan = self._build_plan(30.0, 10, {frontier})
        flankPlan = self._build_plan(60.0, 5, {self.scenarioMap.At(1, 0)})
        first_moves = {
            corridorPlan: Move(self.scenarioMap.At(5, 0), frontier),
            flankPlan: Move(self.scenarioMap.At(8, 0), self.scenarioMap.At(9, 0)),
        }

        selected = self._select_first_path(
            [corridorPlan, flankPlan],
            preferred_target=frontier,
            waiting_plans={corridorPlan},
            first_moves=first_moves)
        self.assertIs(corridorPlan, selected)

        selected_without_target = self._select_first_path(
            [corridorPlan, flankPlan],
            preferred_target=None,
            waiting_plans={corridorPlan},
            first_moves=first_moves)
        self.assertIs(flankPlan, selected_without_target)

    def test_real_tree_capture_qualifies_via_tile_set_membership(self) -> None:
        """
        Real-tree regression: a plan built by
        Gather.convert_contiguous_capture_tiles_to_gather_capture_plan carries the
        frontier as an executable tree tile (tileSet/tileList) while
        approximate_capture_tiles stays empty -- the same shape as the production
        corridor plan that motivated this feature. tileSet membership plus
        nonfriendly ownership is the authoritative eligibility, so this plan must
        gain the preference and beat a richer flank even while generic
        city-waiting applies to it.
        """
        frontier = self.scenarioMap.At(4, 0)
        corridor_plan = Gather.convert_contiguous_capture_tiles_to_gather_capture_plan(
            self.scenarioMap,
            rootTiles={frontier},
            tiles={self.scenarioMap.At(5, 0), self.scenarioMap.At(6, 0), self.scenarioMap.At(7, 0)},
            negativeTiles=set(),
            searchingPlayer=self.searchingPlayer,
            captures={frontier})
        flank_plan = self._build_plan(60.0, 5, {self.scenarioMap.At(1, 0)})

        # Preconditions proving the real-tree distinction this test exists for:
        # nonfriendly executable capture in tileSet, absent from approximate tiles,
        # real executable moves including one into the frontier.
        self.assertNotIn(frontier.player, self.scenarioMap.get_teammates(self.searchingPlayer))
        self.assertIn(frontier, corridor_plan.tileSet)
        self.assertNotIn(frontier, corridor_plan.approximate_capture_tiles)
        self.assertIsNotNone(corridor_plan.get_first_move())
        self.assertTrue(any(
            move.dest is not None and move.dest.tile_index == frontier.tile_index
            for move in corridor_plan.get_move_list()))
        self.assertLess(
            corridor_plan.econValue / corridor_plan.length,
            flank_plan.econValue / flank_plan.length)

        # stub_first_moves=False: the real plan keeps its real get_first_move.
        selected = self._select_first_path(
            [corridor_plan, flank_plan],
            preferred_target=frontier,
            waiting_plans={corridor_plan},
            stub_first_moves=False)
        self.assertIs(corridor_plan, selected)

        selected_without_target = self._select_first_path(
            [corridor_plan, flank_plan],
            preferred_target=None,
            waiting_plans={corridor_plan},
            stub_first_moves=False)
        self.assertIs(flank_plan, selected_without_target)

    def test_missing_or_unmatched_preferred_target_leaves_existing_ranking(self) -> None:
        """None, unmatched, or already-friendly targets confer no priority and leave ranking unchanged."""
        frontier = self.scenarioMap.At(4, 0)
        friendly_target = self.scenarioMap.At(5, 0)
        # The friendly tile is inside the plan's tileSet (via approximate_capture_tiles)
        # so the 'already-friendly' case isolates the target.player not in
        # friendlyPlayers eligibility clause.
        corridorPlan = self._build_plan(30.0, 10, {frontier, friendly_target})
        flankPlan = self._build_plan(60.0, 5, {self.scenarioMap.At(1, 0)})
        first_moves = {
            corridorPlan: Move(self.scenarioMap.At(5, 0), frontier),
            flankPlan: Move(self.scenarioMap.At(8, 0), self.scenarioMap.At(9, 0)),
        }

        for case, target in (
                ('none', None),
                ('unmatched-enemy-general', self.scenarioMap.At(0, 0)),
                ('already-friendly', friendly_target)):
            with self.subTest(case=case):
                selected = self._select_first_path(
                    [corridorPlan, flankPlan],
                    preferred_target=target,
                    first_moves=first_moves)
                self.assertIs(flankPlan, selected)

    def test_required_delay_plan_never_gets_preference_or_delay_bypass(self) -> None:
        """
        A target-containing plan with requiredDelay > 0 must stay waiting and gain no
        preference. The immediately actionable viable corridor plan still wins, so a
        delay bypass would be observable as the huge-value delayed plan winning.
        """
        frontier = self.scenarioMap.At(4, 0)
        delayedCorridor = self._build_plan(200.0, 2, {frontier}, required_delay=1)
        viableCorridor = self._build_plan(30.0, 10, {frontier})
        flankPlan = self._build_plan(60.0, 5, {self.scenarioMap.At(1, 0)})
        first_moves = {
            delayedCorridor: Move(self.scenarioMap.At(5, 0), frontier),
            viableCorridor: Move(self.scenarioMap.At(5, 0), frontier),
            flankPlan: Move(self.scenarioMap.At(8, 0), self.scenarioMap.At(9, 0)),
        }

        selected = self._select_first_path(
            [delayedCorridor, viableCorridor, flankPlan],
            preferred_target=frontier,
            waiting_plans={delayedCorridor, viableCorridor},
            first_moves=first_moves)
        self.assertIs(viableCorridor, selected)

    def test_plan_without_first_move_does_not_qualify_for_preference(self) -> None:
        """A target-containing plan whose get_first_move() is None gains no preference."""
        frontier = self.scenarioMap.At(4, 0)
        no_move_corridor = self._build_plan(30.0, 10, {frontier})
        flankPlan = self._build_plan(60.0, 5, {self.scenarioMap.At(1, 0)})
        # no_move_corridor is deliberately absent from first_moves -> get_first_move() is None.
        first_moves = {
            flankPlan: Move(self.scenarioMap.At(8, 0), self.scenarioMap.At(9, 0)),
        }

        selected = self._select_first_path(
            [no_move_corridor, flankPlan],
            preferred_target=frontier,
            first_moves=first_moves)
        self.assertIs(flankPlan, selected)

    def test_two_preferred_plans_preserve_city_then_value_ranking(self) -> None:
        """
        When multiple viable plans contain the target, the existing ranking still
        applies inside the preferred tier: city-capture priority first, then the
        existing uncertainty+econ/turn comparison.
        """
        frontier = self.scenarioMap.At(4, 0)
        enemy_city = self.scenarioMap.At(3, 0)
        city_plan = self._build_plan(20.0, 10, {frontier, enemy_city})
        plain_plan = self._build_plan(60.0, 5, {frontier})
        richer_plan = self._build_plan(80.0, 4, {frontier})
        weaker_plan = self._build_plan(20.0, 10, {frontier})
        flank_plan = self._build_plan(90.0, 3, {self.scenarioMap.At(1, 0)})
        first_moves = {
            city_plan: Move(self.scenarioMap.At(5, 0), frontier),
            plain_plan: Move(self.scenarioMap.At(7, 0), self.scenarioMap.At(8, 0)),
            richer_plan: Move(self.scenarioMap.At(5, 0), frontier),
            weaker_plan: Move(self.scenarioMap.At(5, 0), frontier),
            flank_plan: Move(self.scenarioMap.At(8, 0), self.scenarioMap.At(9, 0)),
        }

        with self.subTest(case='city-capture-priority-within-preferred'):
            selected = self._select_first_path(
                [city_plan, plain_plan, flank_plan],
                preferred_target=frontier,
                first_moves=first_moves)
            self.assertIs(city_plan, selected)

        with self.subTest(case='value-ranking-within-preferred'):
            selected = self._select_first_path(
                [weaker_plan, richer_plan, flank_plan],
                preferred_target=frontier,
                first_moves=first_moves)
            self.assertIs(richer_plan, selected)

    def test_get_round_plan_forwards_preferred_capture_target_when_skip_knapsacking(self) -> None:
        """get_round_plan_with_expansion must pass preferredCaptureTarget to the selector in the skipKnapsacking branch."""
        zero_opt = zerodiv_fixtures._StubPath(
            [zerodiv_fixtures._StubTile(tile_index=1, x=1, y=0)],
            length=0,
            econ_value=5.0)
        normal_opt = zerodiv_fixtures._StubPath(
            [
                zerodiv_fixtures._StubTile(tile_index=2, x=2, y=0, player=0, army=5),
                zerodiv_fixtures._StubTile(tile_index=3, x=3, y=0),
            ],
            length=1,
            econ_value=4.0)
        kwargs = zerodiv_fixtures._build_round_plan_kwargs(zero_opt, normal_opt)
        target = self.scenarioMap.At(4, 0)

        with patch.object(ExpandUtils, '_try_include_alt_sourced_path', return_value=None), \
                patch.object(ExpandUtils, 'find_optimal_expansion_path_to_move_first', return_value=normal_opt) as find_mock, \
                patch.object(ExpandUtils, '_get_capture_counts', return_value=(0, 0, 0, set())):
            ExpandUtils.get_round_plan_with_expansion(
                SimpleNamespace(turn=195, team_ids_by_player_index=[0, 1]),
                skipKnapsacking=True,
                preferredCaptureTarget=target,
                **kwargs)

        self._assert_preferred_target_forwarded(find_mock, target)

    def test_get_round_plan_forwards_preferred_capture_target_when_knapsacking(self) -> None:
        """get_round_plan_with_expansion must pass preferredCaptureTarget to the selector in the knapsack branch."""
        zero_opt = zerodiv_fixtures._StubPath(
            [zerodiv_fixtures._StubTile(tile_index=1, x=1, y=0)],
            length=0,
            econ_value=5.0)
        normal_opt = zerodiv_fixtures._StubPath(
            [
                zerodiv_fixtures._StubTile(tile_index=2, x=2, y=0, player=0, army=5),
                zerodiv_fixtures._StubTile(tile_index=3, x=3, y=0),
            ],
            length=1,
            econ_value=4.0)
        kwargs = zerodiv_fixtures._build_round_plan_kwargs(zero_opt, normal_opt)
        target = self.scenarioMap.At(4, 0)

        with patch.object(ExpandUtils, '_try_include_alt_sourced_path', return_value=None), \
                patch.object(ExpandUtils, 'knapsack_multi_paths', return_value=([zero_opt, normal_opt], 10.0)), \
                patch.object(ExpandUtils, 'knapsack_multi_paths_no_crossover', return_value=([], 0.0)), \
                patch.object(ExpandUtils, 'find_optimal_expansion_path_to_move_first', return_value=None) as find_mock, \
                patch.object(ExpandUtils, '_get_capture_counts', return_value=(0, 0, 0, set())):
            ExpandUtils.get_round_plan_with_expansion(
                SimpleNamespace(turn=195, team_ids_by_player_index=[0, 1]),
                skipKnapsacking=False,
                preferredCaptureTarget=target,
                **kwargs)

        self._assert_preferred_target_forwarded(find_mock, target)


if __name__ == '__main__':
    unittest.main()
