import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from bot_ek0x45 import EklipZBot


@dataclass(slots=True)
class _PlayerStub:
    index: int
    dead: bool


@dataclass(slots=True)
class _MapStub:
    players: list[_PlayerStub]
    team_ids_by_player_index: list[int]
    teammates: list[int]
    turn: int


@dataclass(slots=True)
class _GeneralStub:
    player: int


class TargetPlayerRetargetingTests(unittest.TestCase):
    def _create_bot(self, players: list[_PlayerStub], teams: list[int]) -> EklipZBot:
        bot = EklipZBot()
        bot._map = _MapStub(players=players, team_ids_by_player_index=teams, teammates=[], turn=100)
        bot.general = _GeneralStub(player=0)
        bot.targetPlayer = 1
        bot.is_all_in_losing = True
        bot.all_in_losing_counter = 99
        bot.is_all_in_army_advantage = True
        bot.all_in_army_advantage_counter = 44
        bot.all_in_city_behind = True
        bot.win_condition_analyzer = SimpleNamespace(
            projected_loss_all_in_active=True,
            projected_loss_all_in_target=object(),
            all_in_plan=object(),
        )
        bot.shortest_path_to_target_player = object()
        bot.target_player_gather_path = object()
        bot.target_player_gather_targets = {object()}
        return bot

    def assert_all_in_state_reset(self, bot: EklipZBot) -> None:
        self.assertFalse(bot.is_all_in_losing)
        self.assertEqual(0, bot.all_in_losing_counter)
        self.assertFalse(bot.is_all_in_army_advantage)
        self.assertEqual(0, bot.all_in_army_advantage_counter)
        self.assertFalse(bot.all_in_city_behind)
        self.assertFalse(bot.win_condition_analyzer.projected_loss_all_in_active)
        self.assertIsNone(bot.win_condition_analyzer.projected_loss_all_in_target)
        self.assertIsNone(bot.win_condition_analyzer.all_in_plan)
        self.assertIsNone(bot.shortest_path_to_target_player)
        self.assertIsNone(bot.target_player_gather_path)
        self.assertIsNone(bot.target_player_gather_targets)

    def test_dead_target_player_retargets_to_living_teammate_and_resets_all_in_state(self):
        players = [
            _PlayerStub(index=0, dead=False),
            _PlayerStub(index=1, dead=True),
            _PlayerStub(index=2, dead=False),
            _PlayerStub(index=3, dead=False),
        ]
        bot = self._create_bot(players, [0, 1, 1, 2])

        with patch('bot_ek0x45.BotTargeting.calculate_target_player', return_value=3) as calculate_target_player:
            newTargetPlayer = bot._calculate_target_player_considering_dead_current_target()

        self.assertEqual(2, newTargetPlayer)
        calculate_target_player.assert_not_called()

        bot._reset_all_in_state_after_target_player_change(1, newTargetPlayer)
        self.assert_all_in_state_reset(bot)

    def test_dead_target_player_without_living_teammate_uses_normal_target_calc_and_resets_all_in_state(self):
        players = [
            _PlayerStub(index=0, dead=False),
            _PlayerStub(index=1, dead=True),
            _PlayerStub(index=2, dead=True),
            _PlayerStub(index=3, dead=False),
        ]
        bot = self._create_bot(players, [0, 1, 1, 2])

        with patch('bot_ek0x45.BotTargeting.calculate_target_player', return_value=3) as calculate_target_player:
            newTargetPlayer = bot._calculate_target_player_considering_dead_current_target()

        self.assertEqual(3, newTargetPlayer)
        calculate_target_player.assert_called_once_with(bot)

        bot._reset_all_in_state_after_target_player_change(1, newTargetPlayer)
        self.assert_all_in_state_reset(bot)


if __name__ == '__main__':
    unittest.main()
