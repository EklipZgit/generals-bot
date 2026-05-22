import unittest

from Strategy.OpponentTracker import OpponentTracker
from StrategyModels.OpponentTrackerModels import CycleStatsData


class OpponentTrackerUnitTests(unittest.TestCase):
    def test_should_return_false_for_invalid_player_when_checking_if_player_already_attacked_this_round(self):
        opponent_tracker = object.__new__(OpponentTracker)
        opponent_tracker.map = type('MapStub', (), {'team_ids_by_player_index': [0, 1]})()
        opponent_tracker.current_team_cycle_stats = [CycleStatsData(0, [0]), CycleStatsData(1, [1])]

        self.assertFalse(opponent_tracker.did_player_already_attack_this_round(-1))
        self.assertFalse(opponent_tracker.did_player_already_attack_this_round(2))

    def test_should_return_false_when_team_cycle_stats_are_missing_for_player_attack_check(self):
        opponent_tracker = object.__new__(OpponentTracker)
        opponent_tracker.map = type('MapStub', (), {'team_ids_by_player_index': [0, 1]})()
        opponent_tracker.current_team_cycle_stats = [None, CycleStatsData(1, [1])]

        self.assertFalse(opponent_tracker.did_player_already_attack_this_round(0))


if __name__ == '__main__':
    unittest.main()
