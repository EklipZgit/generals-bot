import logbook
import time
import typing
from dataclasses import dataclass
from unittest.mock import Mock, patch

import DebugHelper
import Gather
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from BotModules.BotCombatOps import BotCombatOps
from CityAnalyzer import CityAnalyzer
from Directives import Timings
from Models import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Strategy.OpponentTracker import OpponentTracker
from Strategy.WinConditionAnalyzer import WinConditionAnalyzer
from StrategyModels import ExpansionPotential
from Territory import TerritoryClassifier
from TestBase import TestBase
from base.client.tile import TILE_EMPTY
from bot_ek0x45 import EklipZBot


@dataclass(slots=True, frozen=True)
class SurrenderScoreSnapshot:
    turn: int
    friendly_tiles: int
    friendly_score: int
    friendly_cities: int
    enemy_tiles: int
    enemy_score: int
    enemy_cities: int


class AllInSurrenderTests(TestBase):
    __slots__ = ()

    def _create_bot(self, snapshot: SurrenderScoreSnapshot, projected_loss_active: bool = True) -> tuple[EklipZBot, Mock]:
        """Build real bot analyzers with scoreboard inputs isolated from the reported _VgTOLX7A game."""
        map_data = (
            '|   |   |\n'
            'aG18bG6 \n'
            '|   |   |\n'
            f'turn={snapshot.turn}\n'
            'player_index=0\n'
            f'aTiles={snapshot.friendly_tiles}\n'
            f'aScore={snapshot.friendly_score}\n'
            f'aStandingArmy={snapshot.friendly_score - snapshot.friendly_tiles}\n'
            f'aCityCount={snapshot.friendly_cities}\n'
            f'bTiles={snapshot.enemy_tiles}\n'
            f'bScore={snapshot.enemy_score}\n'
            f'bStandingArmy={snapshot.enemy_score - snapshot.enemy_tiles}\n'
            f'bCityCount={snapshot.enemy_cities}\n')
        game_map, general = self.load_map_and_general_from_string(map_data, turn=snapshot.turn, player_index=0)
        bot = EklipZBot()
        bot._map = game_map
        bot.general = general
        bot.targetPlayer = 1
        bot.is_all_in_losing = True
        bot.all_in_losing_counter = 51
        bot.timings = Timings(50, 0, 24, 32, 0, snapshot.turn, False)
        bot.cityAnalyzer = CityAnalyzer(game_map, general)
        bot.opponent_tracker = OpponentTracker(game_map)
        bot.territories = TerritoryClassifier(game_map)
        bot.board_analysis = BoardAnalyzer(game_map, general, None)
        bot.win_condition_analyzer = WinConditionAnalyzer(
            game_map,
            bot.opponent_tracker,
            bot.cityAnalyzer,
            bot.territories,
            bot.board_analysis)
        bot.win_condition_analyzer.projected_loss_all_in_active = projected_loss_active
        bot._afk_players = []
        surrender = Mock(name='surrender')
        bot.surrender_func = surrender
        return bot, surrender

    def _assert_surrenders(self, snapshot: SurrenderScoreSnapshot, projected_loss_active: bool = True) -> None:
        """Assert hopeless endgames submit surrender without sleeping or contacting a game server."""
        bot, surrender = self._create_bot(snapshot, projected_loss_active)
        friendly = bot._map.get_team_stats(0)
        enemy = bot._map.get_team_stats(1)
        self.assertGreater(enemy.tileCount + 35 * enemy.cityCount, friendly.tileCount * 1.5 + 5 + 35 * friendly.cityCount)
        self.assertGreater(enemy.score, friendly.score * 1.6 + 5)
        with patch('BotModules.BotCombatOps.time.sleep'), patch('BotModules.BotCombatOps.BotComms.send_all_chat_communication') as chat:
            self.assertTrue(BotCombatOps.check_should_be_all_in_losing(bot))
        surrender.assert_called_once_with()
        chat.assert_called_once_with(bot, 'gg')
        self.assertEqual(1, bot.giving_up_counter)
        self.assertTrue(bot._map.complete)
        self.assertFalse(bot._map.result)

    def test_should_surrender_when_projected_loss_active_at_turn_448(self) -> None:
        """Surrender at the first reported-game turn meeting both existing surrender thresholds."""
        self._assert_surrenders(SurrenderScoreSnapshot(448, 66, 121, 2, 106, 227, 2))

    def test_should_surrender_when_projected_loss_active_at_turn_500(self) -> None:
        """Surrender at the turn called out in the reported game."""
        self._assert_surrenders(SurrenderScoreSnapshot(500, 57, 160, 2, 118, 371, 2))

    def test_should_surrender_when_projected_loss_active_at_turn_818(self) -> None:
        """Surrender when the bot has first been confined to its general tile."""
        self._assert_surrenders(SurrenderScoreSnapshot(818, 1, 2, 1, 188, 927, 3))

    def test_should_surrender_when_projected_loss_active_at_turn_1100(self) -> None:
        """Surrender even after projected-loss mode has persisted for hundreds of turns."""
        self._assert_surrenders(SurrenderScoreSnapshot(1100, 1, 144, 1, 193, 2522, 4))

    def test_should_surrender_without_projected_loss_mode(self) -> None:
        """Keep the existing non-projected-loss surrender behavior unchanged."""
        self._assert_surrenders(SurrenderScoreSnapshot(500, 57, 160, 2, 118, 371, 2), projected_loss_active=False)

    def test_should_preserve_projected_loss_all_in_when_not_losing_enough_to_surrender(self) -> None:
        """Do not clear projected-loss all-in state, counters, or plans through legacy score checks."""
        bot, surrender = self._create_bot(SurrenderScoreSnapshot(300, 69, 302, 2, 84, 342, 2))
        bot.is_all_in_losing = False
        bot.all_in_losing_counter = 0
        bot.giving_up_counter = 3
        plan = ExpansionPotential(1, 0, 1, None, [], 1.0, bot._map.turn)
        bot.expansion_plan = plan
        bot.enemy_expansion_plan = plan
        with patch('BotModules.BotCombatOps.time.sleep') as sleep, patch('BotModules.BotCombatOps.BotComms.send_all_chat_communication') as chat:
            self.assertTrue(BotCombatOps.check_should_be_all_in_losing(bot))
        self.assertTrue(bot.is_all_in_losing)
        self.assertTrue(bot.win_condition_analyzer.projected_loss_all_in_active)
        self.assertEqual(51, bot.all_in_losing_counter)
        self.assertEqual(0, bot.giving_up_counter)
        self.assertIs(plan, bot.expansion_plan)
        self.assertIs(plan, bot.enemy_expansion_plan)
        surrender.assert_not_called()
        chat.assert_not_called()
        sleep.assert_not_called()
        self.assertFalse(bot._map.complete)

    def test_should_not_complete_simulated_map_without_surrender_callback(self) -> None:
        """A hopeless simulated game must not be completed when no real surrender callback exists."""
        bot, surrender = self._create_bot(SurrenderScoreSnapshot(1100, 1, 144, 1, 193, 2522, 4))
        bot.surrender_func = None
        with patch('BotModules.BotCombatOps.time.sleep'), patch('BotModules.BotCombatOps.BotComms.send_all_chat_communication'):
            self.assertTrue(BotCombatOps.check_should_be_all_in_losing(bot))
        self.assertEqual(1, bot.giving_up_counter)
        self.assertFalse(bot._map.complete)

    def test_should_not_surrender_in_non_endgame_ffa(self) -> None:
        """Preserve the existing endgame gate even while projected-loss all-in is active."""
        bot, surrender = self._create_bot(SurrenderScoreSnapshot(500, 57, 160, 2, 118, 371, 2))
        bot._map.remainingPlayers = 4
        with patch('BotModules.BotCombatOps.time.sleep') as sleep, patch('BotModules.BotCombatOps.BotComms.send_all_chat_communication') as chat:
            self.assertTrue(BotCombatOps.check_should_be_all_in_losing(bot))
        surrender.assert_not_called()
        chat.assert_not_called()
        sleep.assert_not_called()
        self.assertFalse(bot._map.complete)


class AllInTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.gather_use_pcst = True
        # bot.info_render_centrality_distances = True

        return bot

    def test_should_execute_the_full_all_in(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_execute_the_full_all_in___ESW_l8ssb---1--358.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 358, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=358)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=75)
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(general.player, winner)

    def test_should_not_make_unsafe_winning_all_in_plans(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # TODO should just keep some army near general? As much as 30 turn attack risk?
        #  Or, should make sure to launch attacks down the straight line path?
        mapFile = 'GameContinuationEntries/should_not_make_unsafe_winning_all_in_plans___f1tVhCbAr---1--458.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 458, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=458)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=55)
        self.assertNoFriendliesKilled(map, general)

    def test_should_stop_allinning_and_city_after_failed_attack(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_stop_allinning_and_city_after_failed_attack___AANZekIm8---1--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->16,13')
        simHost.queue_player_moves_str(general.player, '16,14->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.is_all_in_losing = True
        bot.all_in_losing_counter = 136
        bot.all_in_army_advantage_counter = 23
        bot.all_in_army_advantage_cycle = 35
        bot.timings.launchTiming = 5
        bot.timings.splitTurns = 2
        bot.targetingArmy = bot.get_army_at(simHost.get_player_map(general.player).GetTile(9, 3))
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)
        self.assertFalse(bot.is_all_in_losing)
        self.assertEqual(0, bot.all_in_losing_counter)
        self.assertFalse(bot.is_all_in_army_advantage)
        self.assertFalse(bot.all_in_city_behind)

    def test_should_stop_allinning_and_city_after_failed_attack__long(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_stop_allinning_and_city_after_failed_attack___AANZekIm8---1--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->16,13')
        simHost.queue_player_moves_str(general.player, '16,14->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.is_all_in_losing = True
        bot.all_in_losing_counter = 136
        bot.all_in_army_advantage_counter = 23
        bot.all_in_army_advantage_cycle = 35
        bot.timings.launchTiming = 5
        bot.timings.splitTurns = 2
        bot.targetingArmy = bot.get_army_at(simHost.get_player_map(general.player).GetTile(9, 3))
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=35)
        self.assertNoFriendliesKilled(map, general)
        self.assertFalse(bot.is_all_in_losing)
        self.assertEqual(0, bot.all_in_losing_counter)
        self.assertFalse(bot.is_all_in_army_advantage)
        self.assertFalse(bot.all_in_city_behind)

        self.assertOwnedXY(2, 17)

    def test_should_stop_allinning_and_city_after_failed_attack__no_flags_450_repro(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_stop_allinning_and_city_after_failed_attack___AANZekIm8---1--426.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 426, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=426)

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(enemyGeneral.player, '15,13->16,13')
        simHost.queue_player_moves_str(general.player, '16,14->16,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.is_all_in_army_advantage = True
        bot.targetingArmy = bot.get_army_at(simHost.get_player_map(general.player).GetTile(9, 3))
        playerMap = simHost.get_player_map(general.player)

        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=45)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwnedXY(2, 17)

    def test_shouldnt_fucking_lose_the_game_when_ahead_on_econ_but_behind_on_cities_and_way_ahead_on_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_fucking_lose_the_game_when_ahead_on_econ_but_behind_on_cities_and_way_ahead_on_army___0fCOKyQJ3---0--850.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 850, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=850)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.info_render_gather_values = False
        bot.info_render_general_undiscovered_prediction_values = True
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=50)
        self.assertNoFriendliesKilled(map, general)

    def test_should_not_idle_during_projected_loss_all_in_with_uncertain_enemy_general(self) -> None:
        """
        Regression for Human.exe-1v1-2026-11-09_10-20-09---TtVz86M3i: at t133 the WCA
        projected-round-loss check activated KillAllIn and the bot idled t134-149.
        projected_loss_all_in_active is never persisted into txtmaps, so it is
        restored manually to reproduce the live path. Note the replay recalculates
        3 candidate enemy general positions vs 8 in the live game, so this exercises
        the same idle outcome but not the >6-alt-positions skip branch.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_idle_during_projected_loss_all_in_with_uncertain_enemy_general___TtVz86M3i---1--134.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 134, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=134)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.assertTrue(bot.is_all_in_losing)
        bot.win_condition_analyzer.projected_loss_all_in_active = True
        bot.win_condition_analyzer.projected_loss_all_in_target = playerMap.GetTile(15, 11)
        self.assertTrue(bot.win_condition_analyzer.projected_loss_all_in_active)

        def assert_bot_made_a_move_this_turn() -> None:
            """Between-turns hook: assert the bot returned a move for the turn just decided."""
            turn: int = simHost.sim.turn
            altGenCount: int = -1
            if 0 <= bot.targetPlayer < len(bot.alt_en_gen_positions):
                altGenCount = len(bot.alt_en_gen_positions[bot.targetPlayer])
            decidedMoves: typing.List[Move] = bot.history.move_history.get(turn, [])
            decidedMove: Move | None = decidedMoves[-1] if len(decidedMoves) > 0 else None
            logbook.info(
                f'idle-repro check t{turn}: '
                f'projected_loss_all_in_active={bot.win_condition_analyzer.projected_loss_all_in_active} '
                f'altEnGenPositions={altGenCount} decidedMove={decidedMove}')
            self.assertIsNotNone(decidedMove, f'bot returned no move on turn {turn} during projected-loss all-in')

        simHost.run_between_turns(assert_bot_made_a_move_this_turn)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=10)

