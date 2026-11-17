from unittest.mock import patch

from ArmyTracker import ArmyTracker
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile


class ArmyTrackerEmergenceDepthTests(TestBase):
    """
    Unit coverage for ArmyTracker.get_emergence_max_depth_to_general_or_none's
    default residual resolution.

    Tests/test_ArmyTracker.py::ArmyTrackerTests.test_should_not_double_fog_capture_emergence
    reproduces the live t156->t157 case at game scale: a fully explained fog
    capture leaves the destination tile with armyDelta -87 but
    unexplainedDelta 0. The standing-army general bound must key off the
    unexplained residual, not the raw delta, or explained captures keep
    eliminating the enemy's real general position.
    """
    __slots__ = ()

    @staticmethod
    def _explained_capture_tile() -> Tile:
        """A tile whose -87 army delta is fully explained (unexplainedDelta 0)."""
        tile = Tile(0, 0)
        tile.delta.armyDelta = -87
        tile.delta.unexplainedDelta = 0
        return tile

    def _load_small_map(self) -> tuple[MapBase, ArmyTracker]:
        """Loads a tiny 3-player map and returns it with a fresh ArmyTracker."""
        rawMap = """|  |  |
aG1f58gG1
a1 M
|  |  |
aTiles=2
fTiles=1
gTiles=1
"""
        map, _ = self.load_map_and_general_from_string(rawMap, turn=200, player_index=0)
        return map, ArmyTracker(map)

    def test_default_residual_zero_returns_none_without_touching_map(self) -> None:
        """Default resolution must read unexplainedDelta; a fully explained
        capture has no emergence evidence, so the bound is None before any
        map/player state is consulted (a bare tracker proves the early return)."""
        tracker = object.__new__(ArmyTracker)
        tile = self._explained_capture_tile()

        self.assertIsNone(tracker.get_emergence_max_depth_to_general_or_none(5, tile))

    def test_default_residual_zero_skips_standing_army_bound_on_real_map(self) -> None:
        """Same scenario on a real map with tiny fog standing army: pre-fix the
        raw -87 delta exceeded the bound threshold and returned a distance;
        post-fix the unexplained residual 0 short-circuits to None and the
        standing-army calculator is never consulted."""
        map, tracker = self._load_small_map()
        player = map.players[5]
        player.standingArmy = 10
        player.visibleStandingArmy = 0
        tile = map.At(0, 1)
        tile.delta.armyDelta = -87
        tile.delta.unexplainedDelta = 0

        with patch.object(tracker, '_calculate_maximum_general_distance_for_raw_fog_standing_army', return_value=17) as calcMock:
            result = tracker.get_emergence_max_depth_to_general_or_none(5, tile, useOpponentKnownFogTileArmy=False)

        self.assertIsNone(result)
        calcMock.assert_not_called()

    def test_explicit_zero_returns_none(self) -> None:
        """An explicit 0 amount is not emergence evidence even when the raw
        delta is large."""
        map, tracker = self._load_small_map()
        player = map.players[5]
        player.standingArmy = 53
        player.visibleStandingArmy = 0
        tile = map.At(0, 1)
        tile.delta.armyDelta = -87
        tile.delta.unexplainedDelta = 0

        self.assertIsNone(
            tracker.get_emergence_max_depth_to_general_or_none(5, tile, 0, useOpponentKnownFogTileArmy=False))

    def test_explicit_positive_amount_still_uses_standing_army_heuristic(self) -> None:
        """Explicit emergence amounts bypass the residual default entirely:
        87 <= 2*53-4 produces no bound, while 110 > 102 invokes the raw
        standing-army distance calculation unchanged."""
        map, tracker = self._load_small_map()
        player = map.players[5]
        player.standingArmy = 53
        player.visibleStandingArmy = 0
        tile = map.At(0, 1)
        tile.delta.armyDelta = -87
        tile.delta.unexplainedDelta = 0

        self.assertIsNone(
            tracker.get_emergence_max_depth_to_general_or_none(5, tile, 87, useOpponentKnownFogTileArmy=False))

        with patch.object(tracker, '_calculate_maximum_general_distance_for_raw_fog_standing_army', return_value=17) as calcMock:
            result = tracker.get_emergence_max_depth_to_general_or_none(5, tile, 110, useOpponentKnownFogTileArmy=False)

        self.assertEqual(17, result)
        calcMock.assert_called_once_with(player, 53)
