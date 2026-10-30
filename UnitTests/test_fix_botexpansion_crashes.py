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


class _StubTile:
    """Minimal tile stub for BotExpansionOps crash-regression tests."""

    def __init__(
            self,
            tile_index: int = 0,
            x: int = 0,
            y: int = 0,
            visible: bool = False,
            player: int = -1,
            army: int = 0,
            isCity: bool = False,
            isGeneral: bool = False,
            isNeutral: bool = True,
            discovered: bool = False):
        self.tile_index = tile_index
        self.x = x
        self.y = y
        self.coords = (x, y)
        self.visible = visible
        self.player = player
        self.army = army
        self.isCity = isCity
        self.isGeneral = isGeneral
        self.isNeutral = isNeutral
        self.discovered = discovered
        self.isSwamp = False
        self.isDesert = False
        self.isObstacle = False
        self.isNotPathable = False
        self.isUndiscoveredObstacle = False
        self.adjacents = []
        self.movable = []
        self.movableNoObstacles = []

    def __str__(self):
        return f'{self.x},{self.y}'

    def __repr__(self):
        return str(self)


class _StubPath:
    """Minimal path stub exposing the attributes BotExpansionOps touches."""

    def __init__(self, tile_list: list, length: int | None = None, econ_value: float = 0.0):
        self._tileList = tile_list
        self._length = length if length is not None else max(0, len(tile_list) - 1)
        self._econValue = econ_value
        self.path = self
        if len(tile_list) > 0:
            self.start = SimpleNamespace(tile=tile_list[0])
            self.tail = SimpleNamespace(tile=tile_list[-1])
        else:
            self.start = SimpleNamespace(tile=None)
            self.tail = SimpleNamespace(tile=None)

    @property
    def length(self) -> int:
        return self._length

    @property
    def econValue(self) -> float:
        return self._econValue

    @property
    def requiredDelay(self) -> int:
        return 0

    @property
    def tileList(self) -> list:
        return self._tileList

    @property
    def tileSet(self) -> set:
        return set(self._tileList)

    @property
    def tiles(self):
        return iter(self._tileList)

    def __iter__(self):
        return iter(())

    def get_first_move(self):
        return None

    def pop_first_move(self):
        return None

    def get_move_list(self):
        return []

    def clone(self):
        return _StubPath(list(self._tileList), self._length, self._econValue)

    def get_subsegment_excluding_trailing_visible(self):
        return self

    def __str__(self):
        return f'stubPath len={self._length}'

    def __repr__(self):
        return str(self)


class _FakeFlowExpander:
    """Stands in for ArmyFlowExpanderV2; returns a canned option collection."""

    def __init__(self, map, perf_timer):
        self.log_debug = False
        self.use_debug_asserts = False
        self.debug_render_capture_count_threshold = 0
        self.friendlyGeneral = None
        self.enemyGeneral = None
        self.options_to_return = []

    def reset_for_turn(self, map, perf_timer):
        pass

    def get_expansion_options(self, **kwargs):
        return SimpleNamespace(expansion_options=list(self.options_to_return))


def _build_weight_matrix_bot(enemy_attack_path, gather_path) -> SimpleNamespace:
    """
    Builds the minimum bot surface _get_standard_expansion_capture_weight_matrix needs
    to reach (and pass) the enemy_attack_path bonus block, with an empty tile loop.
    """
    map_stub = SimpleNamespace(
        cols=8,
        rows=8,
        turn=200,
        cycleTurn=10,
        lookouts=[],
        observatories=[],
        get_all_tiles=lambda: [],
        remainingCycleTurns=30,
    )
    return SimpleNamespace(
        _map=map_stub,
        board_analysis=SimpleNamespace(innerChokes=SimpleNamespace(raw=[0] * 64)),
        targetPlayer=1,
        opponent_tracker=SimpleNamespace(
            winning_on_economy=lambda **kwargs: False,
            winning_on_army=lambda **kwargs: False),
        alt_en_gen_positions={1: [_StubTile(tile_index=5, x=5, y=0)]},
        _alt_en_gen_position_distances={1: SimpleNamespace(raw=[3] * 64)},
        armyTracker=SimpleNamespace(
            seen_player_lookup={1: True},
            uneliminated_emergence_events={1: [object(), object()]}),
        targetPlayerObj=SimpleNamespace(tiles=[object()]),
        territories=SimpleNamespace(territoryDistances={1: SimpleNamespace(raw=[0] * 64)}),
        enemy_attack_path=enemy_attack_path,
        target_player_gather_path=gather_path,
        sketchiest_potential_inbound_flank_path=None,
        cityAnalyzer=SimpleNamespace(get_sorted_neutral_scores=lambda: []),
        threats_we_care_about_by_tile=None,
        enemy_expansion_plan=None,
        info_render_expansion_matrix_values=False,
        viewInfo=SimpleNamespace(
            add_info_line=lambda value: None,
            add_targeted_tile=lambda *args, **kwargs: None),
        info=lambda value: None,
    )


class BotExpansionOpsCrashRegressionTests(unittest.TestCase):
    """
    Regression tests for three live-FFA crash bugs in BotModules/BotExpansionOps.py.

    The FFA-only trigger for the two None-attribute crashes: when the current target
    player is eliminated, scan_map_for_large_tiles_and_leaf_moves retargets and calls
    _reset_all_in_state_after_target_player_change, which sets
    target_player_gather_path / shortest_path_to_target_player to None while leaving
    enemy_attack_path and sketchiest_potential_inbound_flank_path stale. The expansion
    weight matrix is rebuilt before recalculate_player_paths runs, so the matrix code
    must tolerate the paths being legitimately None.

    The ZeroDivisionError: plan options can legitimately have length 0 (a Path with a
    single tile has length == len(tiles) - 1 == 0), so econ-per-turn computations must
    use the max(length, 1) convention already used elsewhere in this file.
    """

    def test_standard_weight_matrix_handles_missing_gather_path_after_target_reset(self):
        """
        Reproduces AttributeError: 'NoneType' object has no attribute 'tileSet' at
        _get_standard_expansion_capture_weight_matrix when enemy_attack_path exists
        but target_player_gather_path is None post-retarget.
        """
        hiddenA = _StubTile(tile_index=1, x=1, y=0)
        hiddenB = _StubTile(tile_index=2, x=2, y=0)
        visibleC = _StubTile(tile_index=3, x=3, y=0, visible=True)
        enemyAttackPath = _StubPath([hiddenA, hiddenB, visibleC])
        bot = _build_weight_matrix_bot(enemyAttackPath, gather_path=None)

        matrix = BotExpansionOpsModule.BotExpansionOps._get_standard_expansion_capture_weight_matrix(bot)

        # With no gather path, no enemy-attack-path tiles are excluded from the +0.2 bonus.
        self.assertEqual(0.2, matrix.raw[hiddenA.tile_index])
        self.assertEqual(0.2, matrix.raw[hiddenB.tile_index])
        self.assertEqual(0.0, matrix.raw[visibleC.tile_index])

    def test_standard_weight_matrix_still_excludes_gather_path_tiles(self):
        """
        Guard test for the fixed branch: when target_player_gather_path DOES exist,
        tiles on it must remain excluded from the enemy-attack-path bonus.
        """
        hiddenA = _StubTile(tile_index=1, x=1, y=0)
        hiddenB = _StubTile(tile_index=2, x=2, y=0)
        enemyAttackPath = _StubPath([hiddenA, hiddenB])
        gatherPath = _StubPath([hiddenB])
        bot = _build_weight_matrix_bot(enemyAttackPath, gather_path=gatherPath)

        matrix = BotExpansionOpsModule.BotExpansionOps._get_standard_expansion_capture_weight_matrix(bot)

        self.assertEqual(0.2, matrix.raw[hiddenA.tile_index])
        self.assertEqual(0.0, matrix.raw[hiddenB.tile_index])

    def test_super_careful_flank_bonuses_skip_when_shortest_path_missing(self):
        """
        Reproduces AttributeError: 'NoneType' object has no attribute 'length' at
        _add_super_careful_flank_gath_capture_bonuses when a stale flank path exists
        but shortest_path_to_target_player is None post-retarget (2-player endgame,
        so is_ffa_situation is False).
        """
        flankTail = _StubTile(tile_index=7, x=7, y=0)
        flankPath = _StubPath([_StubTile(tile_index=6, x=6, y=0), flankTail])
        bot = SimpleNamespace(
            sketchiest_potential_inbound_flank_path=flankPath,
            targetPlayerObj=SimpleNamespace(tiles=[object()]),
            enemy_attack_path=None,
            likely_kill_push=False,
            _is_ffa_situation=False,
            opponent_tracker=SimpleNamespace(
                winning_on_army=lambda **kwargs: True,
                winning_on_economy=lambda **kwargs: True),
            distance_from_general=lambda tile: 5,
            shortest_path_to_target_player=None,
            viewInfo=SimpleNamespace(add_targeted_tile=lambda *args, **kwargs: None),
            info_render_expansion_matrix_values=False,
        )
        matrix = SimpleNamespace(raw=[0.0] * 64)

        BotExpansionOpsModule.BotExpansionOps._add_super_careful_flank_gath_capture_bonuses(bot, matrix)

        # With no target-distance baseline the super-careful bonus cannot be evaluated;
        # the matrix must be untouched.
        self.assertEqual([0.0] * 64, matrix.raw)

    def test_super_careful_flank_bonuses_still_apply_when_path_present(self):
        """
        Guard test for the fixed branch: with a real shortest path far from the
        general, invisible non-swamp flank tiles near our general still get +0.08.
        """
        flankTail = _StubTile(tile_index=7, x=7, y=0)
        flankPath = _StubPath([_StubTile(tile_index=6, x=6, y=0), flankTail])
        shortestPath = _StubPath([_StubTile(tile_index=10), _StubTile(tile_index=11)], length=20)
        bot = SimpleNamespace(
            sketchiest_potential_inbound_flank_path=flankPath,
            targetPlayerObj=SimpleNamespace(tiles=[object()]),
            enemy_attack_path=None,
            likely_kill_push=False,
            _is_ffa_situation=False,
            opponent_tracker=SimpleNamespace(
                winning_on_army=lambda **kwargs: True,
                winning_on_economy=lambda **kwargs: True),
            distance_from_general=lambda tile: 1,
            shortest_path_to_target_player=shortestPath,
            viewInfo=SimpleNamespace(add_targeted_tile=lambda *args, **kwargs: None),
            info_render_expansion_matrix_values=False,
        )
        matrix = SimpleNamespace(raw=[0.0] * 64)

        BotExpansionOpsModule.BotExpansionOps._add_super_careful_flank_gath_capture_bonuses(bot, matrix)

        self.assertEqual(0.08, matrix.raw[flankTail.tile_index])

    def test_build_expansion_plan_logs_zero_length_option(self):
        """
        Reproduces ZeroDivisionError at the 'FE: econValue/length' bot.info log line
        in build_expansion_plan when the flow expander returns a length-0 option.
        """
        optTile = _StubTile(tile_index=1, x=1, y=0, player=-1, army=0)
        zeroLenOpt = _StubPath([optTile], length=0, econ_value=5.0)
        normalTileA = _StubTile(tile_index=2, x=2, y=0, player=0, army=5)
        normalTileB = _StubTile(tile_index=3, x=3, y=0, player=-1, army=0)
        normalOpt = _StubPath([normalTileA, normalTileB], length=1, econ_value=4.0)

        expander = _FakeFlowExpander(None, None)
        expander.options_to_return = [zeroLenOpt, normalOpt]

        def fake_expander_ctor(map, perf_timer):
            return expander

        def get_round_plan_with_expansion(map, **kwargs):
            return BotExpansionOpsModule.ExpandUtils.RoundPlan(
                0,
                0,
                normalOpt,
                [normalOpt],
                map.turn)

        bot = SimpleNamespace(
            territories=SimpleNamespace(territoryMap=None),
            general=SimpleNamespace(movable=[], army=1, lastMovedTurn=0, delta=SimpleNamespace(toTile=None)),
            _map=SimpleNamespace(turn=195, is_tile_enemy=lambda tile: False, team_ids_by_player_index=[0, 1]),
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
            enemy_attack_path=None,
            tileIslandBuilder=SimpleNamespace(
                all_tile_islands=[],
                tile_islands_by_player={0: []},
                tile_islands_by_team_id={1: []}),
            player=SimpleNamespace(index=0),
            targetPlayer=1,
            target_player_gather_path=None,
            shortest_path_to_target_player=None,
            opponent_tracker=SimpleNamespace(did_player_already_attack_this_round=lambda player: False),
            board_analysis=SimpleNamespace(
                intergeneral_analysis=SimpleNamespace(aMap=SimpleNamespace(raw=[0] * 64))),
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

        with patch.object(BotExpansionOpsModule, 'ArmyFlowExpanderV2', side_effect=fake_expander_ctor), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, 'get_expansion_weight_matrix', return_value=SimpleNamespace(raw=[0.0] * 64)), \
                patch.object(BotExpansionOpsModule, 'get_tile_army_mapmatrix', return_value=SimpleNamespace(raw=[0] * 64)), \
                patch.object(BotExpansionOpsModule.BotTimings, 'get_remaining_move_time', return_value=1.0), \
                patch.object(BotExpansionOpsModule.ExpandUtils, 'get_round_plan_with_expansion', side_effect=get_round_plan_with_expansion), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, '_should_use_iterative_negative_expand', return_value=False), \
                patch.object(BotExpansionOpsModule.BotExpansionOps, 'check_launch_against_expansion_plan', side_effect=lambda bot_arg, plan, expansion_negatives: plan):
            plan = BotExpansionOpsModule.BotExpansionOps.build_expansion_plan(
                bot,
                timeLimit=0.1,
                expansionNegatives=set(),
                pathColor=(50, 30, 255))

        self.assertIs(normalOpt, plan.selected_option)
        self.assertIs(expander, bot.last_flow_expander)

    def test_condensed_intercept_options_sort_handles_zero_length(self):
        """
        Same root cause as the FE log crash: intercept options with length 0 crash
        the econValue/length sort key in _get_condensed_intercept_options_for_info.
        """
        tileA = _StubTile(tile_index=1, x=1, y=0)
        zeroLen = _StubPath([tileA], length=0, econ_value=3.0)
        normalLen = _StubPath([_StubTile(tile_index=2, x=2, y=0), _StubTile(tile_index=3, x=3, y=0)], length=1, econ_value=4.0)

        result = BotExpansionOpsModule.BotExpansionOps._get_condensed_intercept_options_for_info([zeroLen, normalLen])

        self.assertEqual(2, len(result))

    def test_quick_capture_move_handles_missing_gather_path(self):
        """
        Same root cause as the gather-path crashes: _get_expansion_plan_quick_capture_move
        dereferences target_player_gather_path.tileList without a None check while the
        retarget window is open.
        """
        bot = SimpleNamespace(
            behavior_allow_pre_gather_greedy_leaves=True,
            currently_forcing_out_of_play_gathers=False,
            _map=SimpleNamespace(
                remainingPlayers=2,
                is_2v2=False,
                turn=300,
                reachable_tiles=[],
                is_tile_on_team_with=lambda tile, player: False),
            approximate_greedy_turns_avail=10,
            opponent_tracker=SimpleNamespace(winning_on_economy=lambda **kwargs: False),
            behavior_pre_gather_greedy_leaves_offset=0,
            timings=SimpleNamespace(in_launch_timing=lambda turn: False),
            target_player_gather_path=None,
            expansion_plan=SimpleNamespace(all_paths=[]),
            targetPlayer=1,
            board_analysis=SimpleNamespace(flankable_fog_area_matrix=SimpleNamespace()),
            viewInfo=SimpleNamespace(add_info_line=lambda value: None),
        )

        move = BotExpansionOpsModule.BotExpansionOps._get_expansion_plan_quick_capture_move(bot, set())

        self.assertIsNone(move)


if __name__ == '__main__':
    unittest.main()
