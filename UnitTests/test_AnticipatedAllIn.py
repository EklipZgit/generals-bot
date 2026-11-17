"""Chronological outgoing-wave bounds, independent of fog-location guesses."""

import unittest

from Strategy.AnticipatedAllIn import (
    EnemyAllInDefense,
    forecast_enemy_all_in,
    minimum_combined_mobile_army,
    minimum_mobile_army,
)


class AnticipatedAllInTests(unittest.TestCase):
    """Check material conservation and the preparation/response split."""

    __slots__ = ()

    def test_immediate_wave_cannot_collect_ordinary_sources(self) -> None:
        """An immediate launch gets its existing bank, not queued tile armies."""
        wave = forecast_enemy_all_in(
            180, 0, 15, 7, 35, 52, (21, 12), 2, 1)
        self.assertEqual(36, wave.launch_army)
        self.assertEqual(0, wave.ordinary_army)
        self.assertEqual(187, wave.ready_turn)
        self.assertEqual(195, wave.arrival_turn)

    def test_each_gather_move_collects_at_most_one_source(self) -> None:
        """Travel-free collection still costs one move per ordinary donor."""
        first = forecast_enemy_all_in(
            101, 1, 15, 7, 4, 10, (4, 3, 2), 3, 0)
        second = forecast_enemy_all_in(
            101, 2, 15, 7, 4, 10, (4, 3, 2), 3, 0)
        self.assertEqual(8, first.launch_army)
        self.assertEqual(10, second.launch_army)
        self.assertEqual((3, 5), (first.ordinary_army, second.ordinary_army))

    def test_round_bonus_requires_real_collection_moves(self) -> None:
        """Twenty newly-grown tiles are not twenty freely delivered armies."""
        wave = forecast_enemy_all_in(
            48, 3, 15, 7, 0, 0, (), 20, 0)
        self.assertEqual(2, wave.tile_growth)
        self.assertEqual(3, wave.launch_army)
        before_collection = forecast_enemy_all_in(
            48, 2, 15, 7, 0, 0, (), 20, 0)
        self.assertEqual(1, before_collection.tile_growth)

    def test_drained_sources_can_be_revisited_after_round_growth(self) -> None:
        """Leaving a one behind does not erase that tile's future production."""
        wave = forecast_enemy_all_in(
            48, 3, 15, 7, 0, 5, (6,), 1, 0)
        self.assertEqual(5, wave.ordinary_army)
        self.assertEqual(2, wave.tile_growth)
        self.assertEqual(8, wave.launch_army)

    def test_stale_tracker_sources_cannot_exceed_standing_cap(self) -> None:
        """Queue and bank disagreement must not duplicate pre-existing army."""
        wave = forecast_enemy_all_in(
            101, 5, 15, 7, 4, 5, (50, 40, 30), 3, 0)
        self.assertEqual(1, wave.ordinary_army)
        self.assertEqual(6, wave.launch_army)

    def test_delayed_wave_prices_growth_before_launch_not_during_attack(self) -> None:
        """A 25-move gather crosses a round, without gifting city teleportation."""
        wave = forecast_enemy_all_in(
            180, 25, 15, 5, 35, 52, (2,) * 20 + (1,) * 10, 30, 1)
        self.assertEqual(17, wave.ordinary_army)
        self.assertEqual(12, wave.city_growth)
        self.assertEqual(6, wave.tile_growth)
        self.assertEqual(71, wave.launch_army)
        self.assertEqual(214, wave.ready_turn)
        self.assertEqual(220, wave.arrival_turn)

    def test_warning_cannot_exceed_attack_travel_time(self) -> None:
        """An invalid geometry input raises rather than inventing extra time."""
        with self.assertRaises(ValueError):
            forecast_enemy_all_in(100, 0, 5, 7, 0, 0, (), 0, 0)

    def test_donating_general_does_not_create_free_defense(self) -> None:
        """Draining the original garrison increases the required mobile reserve."""
        wave = forecast_enemy_all_in(
            180, 0, 13, 7, 35, 52, (2,) * 18, 55, 1)
        retained = minimum_mobile_army(wave, 180, 31, 53, 14, 1)
        donated = minimum_mobile_army(wave, 180, 1, 53, 14, 1)
        self.assertEqual(40, retained)
        self.assertEqual(70, donated)
        self.assertEqual(30, donated - retained)

    def test_existing_visible_attack_is_not_a_second_free_garrison(self) -> None:
        """A current invasion may combine with the later fog wave."""
        wave = forecast_enemy_all_in(
            180, 25, 13, 5, 35, 52, (2,) * 18 + (1,) * 37, 55, 1)
        without_current_attack = minimum_mobile_army(wave, 200, 1, 0, 14, 1)
        with_current_attack = minimum_mobile_army(wave, 200, 1, 60, 14, 1)
        self.assertEqual(wave.launch_army, without_current_attack)
        self.assertGreater(with_current_attack, without_current_attack)

    def test_independent_enemies_share_only_one_home_garrison(self) -> None:
        """Two invaders cannot each be countered by the same retained general."""
        wave = forecast_enemy_all_in(
            180, 0, 13, 7, 35, 52, (2,) * 18, 55, 1)
        enemy = EnemyAllInDefense(wave, 53, 14)
        self.assertEqual(
            40,
            minimum_combined_mobile_army((enemy,), 180, 31, 1),
        )
        self.assertEqual(
            121,
            minimum_combined_mobile_army((enemy, enemy), 180, 31, 1),
        )

    def test_no_enemy_does_not_require_a_reserve(self) -> None:
        """Releasing the last danger episode releases its material requirement."""
        self.assertEqual(0, minimum_combined_mobile_army((), 180, 31, 1))
