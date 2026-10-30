import unittest
import typing

from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile, TILE_EMPTY


class SetTileMovedFogNeutralFixTests(TestBase):
    """
    Repro for live FFA crashes:
        - Human.exe-ffa-2026-09-30_07-15-12---0uXgRCOQ4 turn 24
        - Human.exe-ffa-2026-09-30_07-46-57---RSGhqHwZ1 turn 33

    Both died with:
        AssertionError('must supply a player for moves from fog with unknown ownership when
        setting definitely-moved. fromTile was neutral. fromTile (25,6 ) -> toTile (24,6  0d|3u)')
    raised in base/client/map.py set_tile_moved, reached from
    run_positive_delta_movement_scan with allowFogSource=True.

    Root cause: the positive-delta scan found an exclusive source tile that lives in fog and that
    we believe is neutral (delta.oldOwner == -1), moving onto a dest tile that is also neutral, so
    every byPlayer fallback in the scan returned -1 and set_tile_moved asserted. The sibling
    run_attacked_tile_movement_scan handles the exact same unattributable-fog-move case with a
    byPlayer fallback chain plus an 'UNABLE TO EXECUTE DUE TO UNABLE TO FIND byPlayer THAT ISNT
    NEUTRAL' error log instead of crashing; the positive-delta scan now mirrors that handling.
    """

    def _build_fog_neutral_delta_map(self, with_adjacent_enemy: bool = False) -> typing.Tuple[MapBase, Tile, Tile]:
        """
        Builds a single-row FFA map: [our tile][neutral dest][fog neutral source]([enemy tile]).

        The dest tile is staged exactly like the live crash dest '(24,6  0d|3u)': visible, neutral
        before and after the update, armyDelta 0 but carrying a positive unexplainedDelta with
        armyMovedHere still set (a leftover from a partial delta attribution earlier in the
        detection pass). The source is a fog tile we believe is neutral with no delta info.

        @param with_adjacent_enemy: when True a fourth tile owned by p1 is appended adjacent to the
            fog source so the adjacent-enemy byPlayer fallback can attribute the move.
        @return: (map, destTile, fogSourceTile)
        """
        width = 4 if with_adjacent_enemy else 3
        tiles = [
            Tile(
                x,
                0,
                tile=TILE_EMPTY,
                army=1,
                player=0 if x == 0 else (1 if with_adjacent_enemy and x == 3 else -1),
                tileIndex=x)
            for x in range(width)
        ]
        map = self.get_test_map([tiles], turn=24, num_players=8)

        ourTile = tiles[0]
        dest = tiles[1]
        fogSource = tiles[2]

        # our own tile was already tracked this turn, so mark its delta ownership as ours and the
        # scan will skip it as a potential source outright.
        ourTile.delta.oldOwner = map.player_index
        ourTile.delta.newOwner = map.player_index

        # dest: visible neutral tile with a positive unexplained delta and armyMovedHere set,
        # matching the live crash tile state exactly.
        dest.delta.oldOwner = -1
        dest.delta.newOwner = -1
        dest.delta.oldArmy = 0
        dest.delta.armyDelta = 0
        dest.delta.unexplainedDelta = 3
        dest.delta.armyMovedHere = True
        map.moved_here_set.add(dest)
        map.unexplained_deltas[dest] = 3

        # source: a fog tile we last knew as a neutral empty tile; no sight was gained or lost of
        # it this turn so was_visible_last_turn() is False and its delta ownership is unknown.
        fogSource.visible = False
        fogSource.delta.oldOwner = -1
        fogSource.delta.newOwner = -1
        fogSource.delta.imperfectArmyDelta = True
        fogSource.delta.armyDelta = 0
        fogSource.delta.unexplainedDelta = 0

        return map, dest, fogSource

    def test_run_positive_delta_movement_scan__unattributable_neutral_fog_source_does_not_crash(self):
        """
        Direct live crash repro: an exclusive fog source we believe is neutral moving onto a
        neutral dest leaves byPlayer == -1 through every fallback. The scan must log
        'UNABLE TO EXECUTE DUE TO UNABLE TO FIND byPlayer THAT ISNT NEUTRAL' and skip the move
        instead of asserting inside set_tile_moved.
        """
        map, dest, fogSource = self._build_fog_neutral_delta_map()

        map.run_positive_delta_movement_scan([], {}, allowFogSource=True)

        # the move could not be attributed to any player, so it must remain unexecuted and
        # the dest delta stays unexplained for downstream handling.
        self.assertEqual(3, dest.delta.unexplainedDelta)
        self.assertIsNone(dest.delta.fromTile)
        for player in map.players:
            self.assertIsNone(player.last_move)

    def test_run_positive_delta_movement_scan__fog_source_attributes_to_adjacent_enemy(self):
        """
        Same crash scenario, but the fog source borders a visible p1 tile. The fallback chain
        mirrored from run_attacked_tile_movement_scan attributes the move to p1 and executes it
        instead of crashing or skipping the tile entirely.
        """
        map, dest, fogSource = self._build_fog_neutral_delta_map(with_adjacent_enemy=True)
        # set_tile_probably_moved has a secondary ENABLE_DEBUG_ASSERTS-only assert
        # ('fromTile was neutral/otherPlayer -1 with positive army in the fog') that fires when a
        # believed-neutral fog source is attributed positive army. Live games run with these
        # disabled (that path logs an error and continues), so disable them to exercise the
        # production behavior.
        self.enable_search_time_limits_and_disable_debug_asserts()

        map.run_positive_delta_movement_scan([], {}, allowFogSource=True)

        self.assertIsNotNone(map.players[1].last_move)
        source, destination, isMoveHalf = map.players[1].last_move
        self.assertEqual(fogSource, source)
        self.assertEqual(dest, destination)
        self.assertEqual(0, dest.delta.unexplainedDelta)
