import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ExpandUtils


class _PerfEvent:
    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _PerfTimer:
    __slots__ = ()

    def begin_move_event(self, name: str):
        return _PerfEvent()


class _StubTile:
    """Minimal tile stub for ExpandUtils zero-division regression tests."""

    __slots__ = (
        'tile_index', 'x', 'y', 'coords', 'visible', 'player', 'army',
        'isCity', 'isGeneral', 'isNeutral', 'discovered', 'isSwamp',
        'isDesert', 'isObstacle', 'isNotPathable', 'isUndiscoveredObstacle',
        'adjacents', 'movable', 'movableNoObstacles')

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
    """Minimal path stub exposing the TilePlanInterface attributes ExpandUtils touches."""

    __slots__ = ('_tileList', '_length', '_econValue', 'path', 'start', 'tail')

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

    def __str__(self):
        return f'stubPath len={self._length} econ={self._econValue}'

    def __repr__(self):
        return str(self)


def _build_round_plan_kwargs(zero_len_opt: _StubPath, normal_opt: _StubPath) -> dict:
    """
    Builds the minimum argument surface get_round_plan_with_expansion needs to reach the
    additionalOptionValues econ-per-turn sort at ExpandUtils.py:341, with expansion search
    disabled so the flow expander options are the only paths in play.
    """
    map_stub = SimpleNamespace(turn=195, team_ids_by_player_index=[0, 1])
    board_analysis = SimpleNamespace(
        intergeneral_analysis=SimpleNamespace(
            aMap=SimpleNamespace(raw=[0] * 64),
            bMap=SimpleNamespace(raw=[0] * 64)),
        inter_general_distance=20)
    return dict(
        searchingPlayer=0,
        targetPlayer=1,
        turns=10,
        boardAnalysis=board_analysis,
        territoryMap=None,
        tileIslands=None,
        negativeTiles=set(),
        leafMoves=None,
        viewInfo=None,
        additionalOptionValues=[zero_len_opt, normal_opt],
        includeExpansionSearch=False,
        perfTimer=_PerfTimer())


class ExpandUtilsZeroDivRegressionTests(unittest.TestCase):
    """
    Regression tests for the ZeroDivisionError at
    ExpandUtils.get_round_plan_with_expansion (ExpandUtils.py:341, plus the matching
    econ-per-turn otherPaths re-sorts at :622 in the skipKnapsacking branch and :711 in
    the knapsack branch) seen every turn t356-t372 in live FFA log
    Human.exe-ffa-2026-09-30_08-00-27---9FgD_p-iM.

    additionalOptionValues entries can legitimately have length == 0 (a Path with a
    single tile has length == tiles - 1 == 0, eg an in-place/stay option), so
    econ-per-turn sort keys must use the max(length, 1) convention already used
    throughout BotModules/BotExpansionOps.py (see UnitTests/test_fix_botexpansion_crashes.py).
    """

    def test_additional_options_zero_length_sort_skip_knapsack(self):
        """
        Reproduces ZeroDivisionError at ExpandUtils.py:341 on the live crash path:
        expansion_use_iterative_flow means FlowExpansion already knapsacked, so
        build_expansion_plan calls get_round_plan_with_expansion with
        skipKnapsacking=True and the flow options arrive as additionalOptionValues.
        Also covers the :622 re-sort of otherPaths in the same branch, which a
        length-0 non-selected option would hit immediately after the :341 fix.
        """
        zeroLenOpt = _StubPath([_StubTile(tile_index=1, x=1, y=0)], length=0, econ_value=5.0)
        normalOpt = _StubPath(
            [_StubTile(tile_index=2, x=2, y=0, player=0, army=5), _StubTile(tile_index=3, x=3, y=0)],
            length=1,
            econ_value=4.0)
        map_stub = SimpleNamespace(turn=195, team_ids_by_player_index=[0, 1])
        kwargs = _build_round_plan_kwargs(zeroLenOpt, normalOpt)

        with patch.object(ExpandUtils, '_try_include_alt_sourced_path', return_value=None), \
                patch.object(ExpandUtils, 'find_optimal_expansion_path_to_move_first', return_value=normalOpt), \
                patch.object(ExpandUtils, '_get_capture_counts', return_value=(0, 0, 0, set())):
            plan = ExpandUtils.get_round_plan_with_expansion(
                map_stub,
                skipKnapsacking=True,
                **kwargs)

        self.assertIs(normalOpt, plan.selected_option)
        self.assertIn(zeroLenOpt, plan.all_paths)

    def test_additional_options_zero_length_sort_knapsack(self):
        """
        Same root cause in the non-skipKnapsacking branch: the econ-per-turn re-sort of
        otherPaths at ExpandUtils.py:711 divides by pa.length, so a length-0 option
        that survived knapsacking crashes there (in addition to the :341 sort).
        """
        zeroLenOpt = _StubPath([_StubTile(tile_index=1, x=1, y=0)], length=0, econ_value=5.0)
        normalOpt = _StubPath(
            [_StubTile(tile_index=2, x=2, y=0, player=0, army=5), _StubTile(tile_index=3, x=3, y=0)],
            length=1,
            econ_value=4.0)
        map_stub = SimpleNamespace(turn=195, team_ids_by_player_index=[0, 1])
        kwargs = _build_round_plan_kwargs(zeroLenOpt, normalOpt)

        with patch.object(ExpandUtils, '_try_include_alt_sourced_path', return_value=None), \
                patch.object(ExpandUtils, 'knapsack_multi_paths', return_value=([zeroLenOpt, normalOpt], 10.0)), \
                patch.object(ExpandUtils, 'knapsack_multi_paths_no_crossover', return_value=([], 0.0)), \
                patch.object(ExpandUtils, 'find_optimal_expansion_path_to_move_first', return_value=None), \
                patch.object(ExpandUtils, '_get_capture_counts', return_value=(0, 0, 0, set())):
            plan = ExpandUtils.get_round_plan_with_expansion(
                map_stub,
                skipKnapsacking=False,
                **kwargs)

        self.assertIsNone(plan.selected_option)
        self.assertEqual(2, len(plan.all_paths))


if __name__ == '__main__':
    unittest.main()
