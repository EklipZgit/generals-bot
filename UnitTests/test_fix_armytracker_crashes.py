import sys
import typing

import logbook

from Army import Army
from ArmyTracker import ArmyTracker
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile


class ArmyTrackerCrashFixTests(TestBase):
    """
    Reproductions for two crashes observed in live generals.io game logs.

    Crash 1 (RecursionError, ffa 1rMOTScJ5 t129 and 1v1 icLXQIWYa t290):
        _check_over_elimination -> re_limit_player_gen_locations ->
        _limit_general_position_to_within_tile_and_distance -> _check_over_elimination -> ...
        The over-elimination reset could restore zero valid general positions (its filter
        `tile.player in (-1, player)` trusts fog-ownership predictions on undiscovered tiles),
        so every nested re-limit over-eliminated again and recursed forever with the recorded
        emergence distances growing by +2 each reset.

    Crash 2 (AssertionError 'trying to set general tile 11,10 player from 6 to 5', ffa
        UZaLRtz-e t226): try_track_army offered another player's known general tile as a
        fog-move destination (fogBoi) and move_army_into_fog then attempted to flip the
        general tile's player, tripping the deliberate guard in Tile.player setter.
    """

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)
        TestBase.GLOBAL_BYPASS_RENDERING = True

    # region crash 2 repros

    def _load_fog_move_onto_enemy_general_map(self) -> typing.Tuple[MapBase, Tile]:
        """
        p5 owns a large army at (1,0) directly adjacent to p6's known general gG1 at (2,0).
        The general is not currently visible (in fog) so it surfaces as a fog-move candidate.
        """
        rawMap = """|  |  |
aG1f58gG1
a1 M
|  |  |
aTiles=2
fTiles=1
gTiles=1
"""
        map, general = self.load_map_and_general_from_string(rawMap, turn=226, player_index=0)
        enemyGeneral = map.At(2, 0)
        enemyGeneral.visible = False
        map.generals[enemyGeneral.player] = enemyGeneral
        map.players[enemyGeneral.player].general = enemyGeneral
        return map, general

    def test_move_army_into_fog_does_not_flip_enemy_general_ownership(self):
        """Direct repro of the tile.py:449 assert at ArmyTracker.py move_army_into_fog."""
        map, _ = self._load_fog_move_onto_enemy_general_map()
        tracker = ArmyTracker(map)
        armyTile = map.At(1, 0)
        enemyGeneral = map.At(2, 0)

        army = Army(armyTile)
        tracker.armies[armyTile] = army

        tracker.move_army_into_fog(army, enemyGeneral)

        self.assertEqual(6, enemyGeneral.player)
        self.assertTrue(enemyGeneral.isGeneral)
        # capture sim still applied: the tile army went negative and was flipped positive
        self.assertEqual(56, enemyGeneral.army)

    def test_try_track_army_does_not_offer_enemy_general_as_fog_destination(self):
        """Full-path repro: the entangled/fog move scan must not pick a known enemy general."""
        map, _ = self._load_fog_move_onto_enemy_general_map()
        tracker = ArmyTracker(map)
        armyTile = map.At(1, 0)
        enemyGeneral = map.At(2, 0)

        army = Army(armyTile)
        tracker.armies[armyTile] = army
        # the army's tile lost all its army this turn: the army moved somewhere unexplained
        armyTile.delta.armyDelta = -58

        tracker.try_track_army(army, set(), {})

        self.assertEqual(6, enemyGeneral.player)
        self.assertTrue(enemyGeneral.isGeneral)
        # the general tile must never have been registered as a fog destination
        self.assertIsNone(tracker.armies.get(enemyGeneral))
        self.assertEqual(armyTile, army.tile)

    # endregion

    # region crash 1 repros

    def test_re_limit_player_gen_locations_terminates_when_no_tiles_can_be_restored(self):
        """Every tile is discovered/visible so the over-elimination reset can restore
        nothing; pre-fix this recursed until RecursionError."""
        rawMap = """|  |  |
aG1
   bG1b1
|  |  |
aTiles=1
bTiles=2
"""
        map, _ = self.load_map_and_general_from_string(rawMap, turn=200, player_index=0)
        tracker = ArmyTracker(map)

        elimTile = map.At(0, 1)
        events = tracker.uneliminated_emergence_events[1]
        events[elimTile] = 3

        oldLimit = sys.getrecursionlimit()
        sys.setrecursionlimit(300)
        try:
            tracker.re_limit_player_gen_locations(1, events)
        finally:
            sys.setrecursionlimit(oldLimit)

        # each over-elimination reset bumps the stored emergence distances by 2
        self.assertGreaterEqual(events[elimTile], 5)

    def test_over_elimination_reset_restores_undiscovered_tiles_owned_by_other_players(self):
        """All undiscovered tiles carry another player's fog-ownership prediction, so the
        strict reset filter restores nothing; the broadened fallback must restore them as
        candidates instead of recursing forever."""
        rawMap = """|  |  |  |
aG1
   bG1
      b1 c1
|  |  |  |
aTiles=1
bTiles=2
cTiles=1
"""
        map, _ = self.load_map_and_general_from_string(rawMap, turn=200, player_index=0)

        # simulate fog-ownership predictions: undiscovered, invisible tiles 'owned' by p2
        foggedTiles: typing.List[Tile] = []
        for coords in [(2, 0), (3, 0), (2, 1), (3, 1), (0, 2), (1, 2)]:
            tile = map.At(*coords)
            tile.visible = False
            tile.discovered = False
            tile.player = 2
            tile.isTempFogPrediction = True
            foggedTiles.append(tile)

        tracker = ArmyTracker(map)

        # simulate prior elimination having wiped out all p1 general candidates
        validPositions = tracker.valid_general_positions_by_player[1]
        for i in range(len(validPositions.raw)):
            validPositions.raw[i] = False

        elimTile = map.At(0, 0)
        events = tracker.uneliminated_emergence_events[1]
        events[elimTile] = 5

        oldLimit = sys.getrecursionlimit()
        sys.setrecursionlimit(300)
        try:
            tracker.re_limit_player_gen_locations(1, events)
        finally:
            sys.setrecursionlimit(oldLimit)

        # the reset must leave the player with at least one general candidate again;
        # undiscovered fog-predicted tiles owned by other players are legitimate candidates.
        self.assertTrue(any(validPositions.raw))

    # endregion
