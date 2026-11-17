"""Unit tests for Strategy/CityContestationSafety.py speculative-city helpers.

Regression: Tests/test_CityGather.py
CityGatherTests.test_should_take_nearby_city_instead_of_attacking_predicted_city_through_cave
"""
import typing

from Strategy.CityContestationSafety import (
    PREDICTED_CITY_ARMY_RESERVE,
    get_predicted_city_army_reserve,
    get_safe_predicted_city_approaches,
    is_speculative_predicted_city,
)
from Tests.TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile


def _mark_speculative(city: Tile) -> Tile:
    """Mark a city tile as an undiscovered isTempFogPrediction city in-place."""
    city.isTempFogPrediction = True
    city.discovered = False
    city.visible = False
    return city


class CityContestationSafetyTests(TestBase):
    """Tests for speculative predicted-city reserve and safe-approach helpers."""

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    def _load(self, mapData: str) -> typing.Tuple[MapBase, Tile, Tile]:
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 100, fill_out_tiles=False)
        return map, general, enemyGeneral

    def test_reserve__known_enemy_city_gets_zero(self):
        mapData = """
|    |    |    |    |
aG20 a1   bC3  bG20
|    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = map.At(2, 0)
        self.assertTrue(city.isCity)
        self.assertEqual(0, get_predicted_city_army_reserve(city))
        self.assertFalse(is_speculative_predicted_city(city))

    def test_reserve__discovered_fog_city_gets_zero(self):
        mapData = """
|    |    |    |    |
aG20 a1   bC3  bG20
|    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = map.At(2, 0)
        city.isTempFogPrediction = True
        city.discovered = True
        self.assertEqual(0, get_predicted_city_army_reserve(city))
        self.assertFalse(is_speculative_predicted_city(city))

    def test_reserve__speculative_enemy_city_gets_reserve(self):
        mapData = """
|    |    |    |    |
aG20 a1   bC3  bG20
|    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = _mark_speculative(map.At(2, 0))
        self.assertEqual(PREDICTED_CITY_ARMY_RESERVE, get_predicted_city_army_reserve(city))
        self.assertTrue(is_speculative_predicted_city(city))

    def test_reserve__neutral_city_and_general_get_zero(self):
        mapData = """
|    |    |    |    |
aG20 a1   C4   bG20
|    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        neutralCity = _mark_speculative(map.At(2, 0))
        self.assertEqual(0, get_predicted_city_army_reserve(neutralCity))
        self.assertFalse(is_speculative_predicted_city(neutralCity))
        self.assertFalse(is_speculative_predicted_city(map.At(0, 0)))
        self.assertEqual(0, get_predicted_city_army_reserve(map.At(0, 0)))

    def test_safe_approaches__cave_side_denied_enemy_side_allowed(self):
        # City at (5,1). Approach (4,1) is a mountain-walled pocket whose BFS
        # finds no alternate enemy targets within 3 steps (cave side) and must
        # be denied; the enemy-land side approaches must stay safe.
        mapData = """
|    |    |    |    |    |    |    |    |    |
aG20 a1   a1   a1   a1   a1   a1   a1   b1
M    M    M    M    a1   bC3  b1   b1   b1
M    M    M    M    M    b1   b1   b1   b1
M    M    M    M    a1   a1   a1   a1   bG20
a1   a1   a1   a1   a1   a1   a1   a1   a1
|    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = _mark_speculative(map.At(5, 1))
        safe = get_safe_predicted_city_approaches(map, city)
        self.assertNotIn(map.At(4, 1), safe)
        self.assertIn(map.At(6, 1), safe)
        self.assertIn(map.At(5, 2), safe)
        self.assertIn(map.At(5, 0), safe)

    def test_safe_approaches__non_speculative_returns_all_pathable(self):
        mapData = """
|    |    |    |    |
aG20 a1   bC3  bG20
|    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = map.At(2, 0)
        safe = get_safe_predicted_city_approaches(map, city)
        neighbors = {t for t in city.movable if not t.isObstacle and not t.isNotPathable}
        self.assertEqual(neighbors, safe)

    def test_safe_approaches__known_city_not_denied(self):
        # Same cave topology as above but the city is discovered/known: every
        # pathable approach must be returned.
        mapData = """
|    |    |    |    |    |    |    |    |    |
aG20 a1   a1   a1   a1   a1   a1   a1   b1
M    M    M    M    a1   bC3  b1   b1   b1
M    M    M    M    M    b1   b1   b1   b1
M    M    M    M    a1   a1   a1   a1   bG20
a1   a1   a1   a1   a1   a1   a1   a1   a1
|    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = map.At(5, 1)
        city.isTempFogPrediction = True
        city.discovered = True
        safe = get_safe_predicted_city_approaches(map, city)
        neighbors = {t for t in city.movable if not t.isObstacle and not t.isNotPathable}
        self.assertEqual(neighbors, safe)
        self.assertIn(map.At(4, 1), safe)

    def test_safe_approaches__targets_beyond_city_do_not_count(self):
        # Approach (2,0) sits on the friendly side; the only enemy land is on
        # the far side of the city itself plus a mountain wall, so BFS can
        # never reach 3 alternate targets and the approach is denied. The
        # enemy-side approach (4,0) stays safe.
        mapData = """
|    |    |    |    |    |    |    |    |
aG20 a1   a1   bC3  b1   b1   b1   b1
M    M    M    M    b1   b1   b1   bG20
a1   a1   a1   a1   a1   a1   a1   a1
|    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = _mark_speculative(map.At(3, 0))
        safe = get_safe_predicted_city_approaches(map, city)
        self.assertNotIn(map.At(2, 0), safe)
        self.assertIn(map.At(4, 0), safe)

    def test_safe_approaches__targets_beyond_speculative_bridge_do_not_count(self):
        # Approach (3,0) is enemy land adjacent to the speculative city at
        # (2,0). The only corridor to the >=3 enemy targets beyond it passes
        # through a SECOND undiscovered predicted city at (4,0), which BFS may
        # not traverse - so the approach is denied. Control: with (4,0) as
        # ordinary enemy land the corridor opens and the same approach is
        # safe, isolating the bridge effect.
        mapDataSpec = """
|    |    |    |    |    |    |    |    |
aG20 a1   bC3  b1   bC3  b1   b1   b1
a1   a1   a1   a1   a1   a1   a1   bG20
|    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self._load(mapDataSpec)
        city = _mark_speculative(map.At(2, 0))
        _mark_speculative(map.At(4, 0))
        safe = get_safe_predicted_city_approaches(map, city)
        self.assertNotIn(map.At(3, 0), safe)
        self.assertEqual(0, len(safe))

        mapDataLand = """
|    |    |    |    |    |    |    |    |
aG20 a1   bC3  b1   b1   b1   b1   b1
a1   a1   a1   a1   a1   a1   a1   bG20
|    |    |    |    |    |    |    |
        """
        map2, general2, enemyGeneral2 = self._load(mapDataLand)
        city2 = _mark_speculative(map2.At(2, 0))
        safe2 = get_safe_predicted_city_approaches(map2, city2)
        self.assertIn(map2.At(3, 0), safe2)

    def test_safe_approaches__distant_enemy_outside_depth_does_not_count(self):
        # The only enemy land is a single b1 tile far outside BFS depth 3 of
        # every approach, so all approaches are denied.
        mapData = """
|    |    |    |    |    |    |    |    |    |
aG20 a1   a1   a1   bC3  a1   a1   a1   a1   a1
a1   a1   a1   a1   a1   a1   a1   a1   bG20
a1   a1   a1   a1   a1   a1   a1   a1   b1
|    |    |    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self._load(mapData)
        city = _mark_speculative(map.At(4, 0))
        safe = get_safe_predicted_city_approaches(map, city)
        self.assertEqual(0, len(safe))
