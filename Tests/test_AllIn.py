import io
import random
import re
import sys
import time
import typing
from dataclasses import dataclass
from pathlib import Path as OutputPath
from unittest.mock import Mock, patch

import DebugHelper
import Gather
import SearchUtils
import logbook
from BoardAnalyzer import BoardAnalyzer
from BotModules.BotCombatOps import BotCombatOps
from BotModules.BotStealthAllIn import BotStealthAllIn, StealthAllInState
from BotModules.BotStateQueries import BotStateQueries
from CityAnalyzer import CityAnalyzer
from Directives import Timings
from MapMatrix import MapMatrix
from Models import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Strategy.OpponentTracker import OpponentTracker
from Strategy.WinConditionAnalyzer import WinCondition, WinConditionAnalyzer
from StrategyModels import ExpansionPotential
from Territory import TerritoryClassifier
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import TILE_EMPTY, Tile
from bot_ek0x45 import EklipZBot


# Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
# restore map-order state after pinning the imported continuation's randomized adjacency order.
def _restore_map_randomization(value: bool) -> None:
    """Restore the process-wide map randomization setting."""
    MapBase.DO_NOT_RANDOMIZE = value


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

    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
    # verify the imported-turn gather, route commitment, and enemy-general reveal end-to-end.
    def test_should_stealth_flank_all_in_when_enemy_general_unknown(self) -> None:
        """Execute the unknown-general losing all-in through its stealth WRP route."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        previousRandomState = random.getstate()
        self.addCleanup(random.setstate, previousRandomState)
        random.seed(0)
        previousMapRandomization = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(_restore_map_randomization, previousMapRandomization)
        MapBase.DO_NOT_RANDOMIZE = False
        mapFile = (
            "GameContinuationEntries/"
            "should_stealth_flank_all_in_when_enemy_general_unknown___"
            "0ES5f2iai---1--427.txtmap")
        map, general, enemyGeneral = self.load_map_and_generals(
            mapFile,
            427,
            fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(
            mapFile,
            respect_undiscovered=True,
            turn=427)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(
            map,
            player_with_viewer=general.player,
            playerMapVision=rawMap,
            allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, "None")
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.enable_stealth_all_in = True
        playerMap = simHost.get_player_map(general.player)
        self.assertTrue(bot.is_all_in_losing)
        self.assertFalse(bot.targetPlayerExpectedGeneralLocation.isGeneral)

        self.begin_capturing_logging()
        logOutput = io.StringIO()
        logHandler = logbook.StreamHandler(logOutput, level=logbook.INFO)
        logHandler.push_application()
        stealthLogPath = OutputPath(
            r"C:\cascade-debug-output\generals-bot\stealth_allin_test_logs.txt")
        committedRoute: Path | None = None
        routeWasCommitted = False
        visibleGatherMoves: list[str] = []
        routeMoveKinds: list[str] = []
        resumeRouteGeneration: int | None = None
        try:
            for turn_index in range(60):
                decisionTurn = bot._map.turn
                stateBefore = bot.stealth_all_in
                previousFallbackCount = (
                    stateBefore.used_normal_gather_fallback_turns
                    if stateBefore is not None
                    else 0)
                expectedMove: Move | None = None
                if stateBefore is not None and stateBefore.committed_route is not None:
                    if committedRoute is None:
                        committedRoute = stateBefore.committed_route
                        routeWasCommitted = True
                    else:
                        self.assertIs(committedRoute, stateBefore.committed_route)
                    if resumeRouteGeneration is not None:
                        self.assertEqual(
                            resumeRouteGeneration,
                            stateBefore.generation)
                        resumeRouteGeneration = None
                    expectedMove = stateBefore.committed_route.get_first_move()

                playerMoves = simHost.sim.players[general.player].move_history
                previousMoveCount = len(playerMoves)
                simHost.execute_turn(
                    run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
                    turn_time=0.25)
                actualMove = (
                    playerMoves[-1]
                    if len(playerMoves) > previousMoveCount
                    else None)
                stateAfter = bot.stealth_all_in

                if turn_index == 0:
                    if stateAfter is None:
                        self.fail(
                            f"STEALTH_ALLIN state was not created on turn 427; "
                            f"losing={bot.is_all_in_losing} "
                            f"generalKnown={bot.targetPlayerExpectedGeneralLocation.isGeneral}; "
                            f"logs={logOutput.getvalue()}")
                    enemyVision = BotStealthAllIn.build_enemy_vision_matrix(bot)
                    for tile in stateAfter.flank_path.tileList:
                        self.assertFalse(enemyVision.raw[tile.tile_index])
                if stateAfter is not None and stateAfter.committed_route is None:
                    if actualMove is not None:
                        sourceOnTrueMap = simHost.sim.sim_map.tiles_by_index[
                            actualMove.source.tile_index]
                        if any(
                            adjacent.player == enemyGeneral.player
                            for adjacent in sourceOnTrueMap.adjacents
                        ):
                            sourceOnBotMap = bot._map.tiles_by_index[
                                actualMove.source.tile_index]
                            botVisible = (
                                bot._map.is_tile_enemy(sourceOnBotMap)
                                or any(
                                    bot._map.is_tile_enemy(adjacent)
                                    for adjacent in sourceOnBotMap.adjacents))
                            usedFallback = (
                                stateAfter.used_normal_gather_fallback_turns
                                > previousFallbackCount)
                            visibleGatherMoves.append(
                                f"t{simHost.sim.turn} {actualMove} "
                                f"botVisible={botVisible} usedFallback={usedFallback}")

                interrupt = bot.last_stealth_route_defense_interrupt
                if (stateBefore is not None
                        and stateBefore.committed_route is not None):
                    route_active, resume_route = self._verify_committed_route_step(
                        bot,
                        stateBefore,
                        stateAfter,
                        stateBefore.committed_route,
                        expectedMove,
                        actualMove,
                        decisionTurn,
                        routeMoveKinds)
                    if resume_route:
                        resumeRouteGeneration = stateBefore.generation
                    if not route_active:
                        committedRoute = None
                elif (stateAfter is not None
                        and stateAfter.committed_route is not None):
                    routeWasCommitted = True
                    committedRoute = stateAfter.committed_route
                    interruptThisTurn = (
                        interrupt is not None
                        and interrupt.turn == decisionTurn)
                    if interruptThisTurn:
                        if interrupt is None:
                            raise AssertionError("Missing route defense interrupt")
                        self.assertIsNotNone(actualMove)
                        if actualMove is not None:
                            self.assertEqual(
                                self._move_signature(interrupt.move),
                                self._move_signature(actualMove))
                        routeMoveKinds.append("defense_interrupt")
                        if not interrupt.aborted_route:
                            resumeRouteGeneration = stateAfter.generation
                    else:
                        expectedMove = stateAfter.last_route_move
                        if expectedMove is not None:
                            self.assertIsNotNone(actualMove)
                            self.assertEqual(
                                self._move_signature(expectedMove),
                                self._move_signature(actualMove))
                            routeMoveKinds.append("route")
                elif (interrupt is not None
                        and interrupt.turn == decisionTurn):
                    routeWasCommitted = True
                    self.assertIsNotNone(actualMove)
                    if actualMove is not None:
                        self.assertEqual(
                            self._move_signature(interrupt.move),
                            self._move_signature(actualMove))
                    routeMoveKinds.append("defense_interrupt")
                    if turn_index == 0:
                        self.assertEqual(
                            startArmyTile.tile_index,
                            interrupt.launch_tile_index)

                if (bot.targetPlayerExpectedGeneralLocation.isGeneral
                        or playerMap.generals[enemyGeneral.player] is not None):
                    break
        finally:
            logHandler.pop_application()
            # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
            # retain structured stealth decisions outside the repo for diagnosis and handoff evidence.
            stealthLogPath.write_text(
                "\n".join(
                    line for line in logOutput.getvalue().splitlines()
                    if "STEALTH_ALLIN_" in line),
                encoding="utf-8")

        abortReasons = re.findall(
            r"STEALTH_ALLIN_ABORT .*?reason=([a-z_]+)",
            logOutput.getvalue())
        gatherLogLines = [
            line for line in logOutput.getvalue().splitlines()
            if "STEALTH_ALLIN_GATHER" in line]
        for reason in abortReasons:
            self.assertTrue(
                reason == "general_known"
                or reason.startswith("broken_")
                or reason == "route_complete"
                or reason == "cannot_kill",
                f"unexpected stealth route abort reason: {reason}")
        self.assertTrue(routeWasCommitted, "the stealth WRP route was never committed")
        self.assertIn("route", routeMoveKinds)
        self.assertLessEqual(
            len(visibleGatherMoves),
            2,
            f"true-enemy-visible gather moves: {visibleGatherMoves}; "
            f"gather logs: {gatherLogLines}")
        self.assertTrue(
            bot.targetPlayerExpectedGeneralLocation.isGeneral
            or playerMap.generals[enemyGeneral.player] is not None,
            "the enemy general was not revealed by the end of the stealth route")
        self.assertNoFriendliesKilled(map, general)

    def _move_signature(self, move: Move) -> tuple[int, int, int, int, bool]:
        """Return stable coordinates and half-move state for route comparisons."""
        return (
            move.source.x,
            move.source.y,
            move.dest.x,
            move.dest.y,
            move.move_half)

    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown
    # and test_should_commit_wrp_hunt_when_enemy_cannot_defend: classify route versus defense steps.
    def _verify_committed_route_step(
        self,
        bot: EklipZBot,
        state_before: StealthAllInState,
        state_after: StealthAllInState | None,
        route: Path,
        expected_move: Move | None,
        actual_move: Move | None,
        decision_turn: int,
        move_kinds: list[str],
    ) -> tuple[bool, bool]:
        """Check a route step or a recorded BotDefense interruption."""
        if (expected_move is not None
                and actual_move is not None
                and self._move_signature(expected_move)
                == self._move_signature(actual_move)):
            move_kinds.append("route")
            if (state_after is not None
                    and state_after.committed_route is not None):
                self.assertIs(route, state_after.committed_route)
                self.assertIsNotNone(state_after.last_route_move)
                if state_after.last_route_move is not None:
                    self.assertEqual(
                        self._move_signature(expected_move),
                        self._move_signature(state_after.last_route_move))
                return True, False
            return False, False

        interrupt = bot.last_stealth_route_defense_interrupt
        if (interrupt is not None
                and interrupt.turn == decision_turn
                and interrupt.generation == state_before.generation):
            self.assertIsNotNone(actual_move)
            if actual_move is not None:
                self.assertEqual(
                    self._move_signature(interrupt.move),
                    self._move_signature(actual_move))
            move_kinds.append("defense_interrupt")
            if interrupt.aborted_route:
                self.assertTrue(
                    state_after is None
                    or state_after.committed_route is None)
                return False, False

            self.assertIsNotNone(state_after)
            self.assertIs(route, state_after.committed_route)
            self.assertEqual(
                state_before.last_route_move,
                state_after.last_route_move)
            return True, True

        if (expected_move is None
                or state_after is None
                or state_after.committed_route is None):
            move_kinds.append("route_abort_or_handoff")
            return False, False
        self.fail(
            f"committed route moved unexpectedly at turn {decision_turn}: "
            f"expected={expected_move}, actual={actual_move}")
        return False, False

    # Tests/test_AllIn.py::AllInTests.test_process_wrp_job_converts_tile_indexes:
    # run WRP in a spawned process and map its returned indexes to live-map tiles.
    def test_process_wrp_job_converts_tile_indexes(self) -> None:
        """Run a real process-backed WRP job and convert its result to live tiles."""
        # Tests/test_AllIn.py::AllInTests.test_process_wrp_job_converts_tile_indexes:
        # isolate map randomization so the process smoke test cannot perturb later simulator tests.
        previousRandomState = random.getstate()
        self.addCleanup(random.setstate, previousRandomState)
        previousMapRandomization = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(_restore_map_randomization, previousMapRandomization)
        MapBase.DO_NOT_RANDOMIZE = False
        map_data = (
            "|   |   |   |\n"
            "aG18a1  bG6 \n"
            "|   |   |   |\n"
            "turn=427\n"
            "player_index=0\n"
            "aTiles=2\n"
            "aScore=19\n"
            "bTiles=1\n"
            "bScore=6\n")
        game_map, general = self.load_map_and_general_from_string(
            map_data,
            turn=427,
            player_index=0)
        bot = EklipZBot()
        bot._map = game_map
        bot.general = general
        bot.enable_stealth_all_in = True
        start_tile = game_map.GetTile(0, 0)
        destination_tile = game_map.GetTile(2, 0)
        wrp_log_handler = logbook.StreamHandler(sys.stderr, level=logbook.INFO)
        wrp_log_handler.push_application()
        try:
            job = BotStealthAllIn.start_wrp_job(
                bot,
                start_tile,
                [destination_tile],
                17,
                1)
            bot.stealth_hunt_job = job
            worker = bot.wrp_worker_process
            self.assertIsNotNone(worker)
            if worker is None:
                self.fail("live-mode WRP job did not create a worker process")
            self.addCleanup(worker.close)
            deadline = time.perf_counter() + 30.0
            while not job.done and time.perf_counter() < deadline:
                BotStealthAllIn.poll_wrp_worker_results(bot)
                if not job.done:
                    time.sleep(0.01)
            self.assertTrue(job.done, "process-backed WRP did not finish within 30 seconds")
            converted_path = BotStealthAllIn.convert_wrp_job_result(game_map, job)

            self.assertIsNotNone(job.duration_sec)
            logbook.info(
                f"STEALTH_ALLIN_TEST_WRP_PROCESS generation={job.generation} "
                f"durationSec={job.duration_sec:.6f} payloadBytes={job.payload_bytes}")
        finally:
            wrp_log_handler.pop_application()

        self.assertIsNotNone(converted_path)
        if converted_path is None:
            self.fail("process WRP result was not converted")
        self.assertGreater(converted_path.length, 0)
        self.assertIs(game_map.tiles_by_index[start_tile.tile_index],
                      converted_path.start.tile)
        for tile in converted_path.tileList:
            self.assertIs(game_map.tiles_by_index[tile.tile_index], tile)

    # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
    # exercise the non-losing unknown-general hunt from a reproducible live turn.
    def test_should_commit_wrp_hunt_when_enemy_cannot_defend(self) -> None:
        """Commit an undefendable WRP hunt and capture the unknown enemy general."""
        # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
        # restore shared RNG and map-randomization state before subsequent baseline tests run.
        previousRandomState = random.getstate()
        self.addCleanup(random.setstate, previousRandomState)
        previousMapRandomization = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(_restore_map_randomization, previousMapRandomization)
        random.seed(0)
        MapBase.DO_NOT_RANDOMIZE = False
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = (
            "GameContinuationEntries/"
            "should_commit_wrp_hunt_when_enemy_cannot_defend___"
            "lC_ghoQhY---0--534.txtmap")
        map, general, enemyGeneral = self.load_map_and_generals(
            mapFile,
            534,
            fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(
            mapFile,
            respect_undiscovered=True,
            turn=534)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(
            map,
            player_with_viewer=general.player,
            playerMapVision=rawMap,
            allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, "None")
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.enable_stealth_all_in = True
        playerMap = simHost.get_player_map(general.player)
        armyTiles = [
            tile for tile in map.get_all_tiles()
            if tile.player == general.player
            and not tile.isGeneral
            and tile.army > 1]
        self.assertTrue(armyTiles, "the imported map has no movable army tile")
        startArmyTile = max(
            armyTiles,
            key=lambda tile: (tile.army, -tile.tile_index))
        self.assertFalse(bot.is_all_in_losing)
        self.assertFalse(bot.targetPlayerExpectedGeneralLocation.isGeneral)

        self.begin_capturing_logging()
        logOutput = io.StringIO()
        logHandler = logbook.StreamHandler(logOutput, level=logbook.INFO)
        logHandler.push_application()
        committedRoute: Path | None = None
        routeWasCommitted = False
        routeMoveKinds: list[str] = []
        resumeRouteGeneration: int | None = None
        commitTurnIndex: int | None = None
        winner: int | None = None
        try:
            for turnIndex in range(40):
                decisionTurn = bot._map.turn
                stateBefore = bot.stealth_all_in
                expectedMove: Move | None = None
                if stateBefore is not None and stateBefore.committed_route is not None:
                    self.assertIs(committedRoute, stateBefore.committed_route)
                    if resumeRouteGeneration is not None:
                        self.assertEqual(
                            resumeRouteGeneration,
                            stateBefore.generation)
                        resumeRouteGeneration = None
                    expectedMove = stateBefore.committed_route.get_first_move()

                moveHistory = simHost.sim.players[general.player].move_history
                previousMoveCount = len(moveHistory)
                winner = simHost.execute_turn(
                    run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
                    turn_time=0.25)
                actualMove = (
                    moveHistory[-1]
                    if len(moveHistory) > previousMoveCount
                    else None)
                stateAfter = bot.stealth_all_in
                interrupt = bot.last_stealth_route_defense_interrupt
                if (stateBefore is not None
                        and stateBefore.committed_route is not None):
                    routeActive, resumeRoute = self._verify_committed_route_step(
                        bot,
                        stateBefore,
                        stateAfter,
                        stateBefore.committed_route,
                        expectedMove,
                        actualMove,
                        decisionTurn,
                        routeMoveKinds)
                    if resumeRoute:
                        resumeRouteGeneration = stateBefore.generation
                    if not routeActive:
                        committedRoute = None
                elif (stateAfter is not None
                        and stateAfter.committed_route is not None):
                    routeWasCommitted = True
                    committedRoute = stateAfter.committed_route
                    if commitTurnIndex is None:
                        commitTurnIndex = turnIndex
                        self.assertEqual(
                            startArmyTile.tile_index,
                            stateAfter.launch_tile.tile_index)
                    interruptThisTurn = (
                        interrupt is not None
                        and interrupt.turn == decisionTurn)
                    if interruptThisTurn:
                        if interrupt is None:
                            raise AssertionError("Missing route defense interrupt")
                        self.assertIsNotNone(actualMove)
                        if actualMove is not None:
                            self.assertEqual(
                                self._move_signature(interrupt.move),
                                self._move_signature(actualMove))
                        routeMoveKinds.append("defense_interrupt")
                        if not interrupt.aborted_route:
                            resumeRouteGeneration = stateAfter.generation
                    else:
                        expectedMove = stateAfter.last_route_move
                        if expectedMove is not None:
                            self.assertIsNotNone(actualMove)
                            self.assertEqual(
                                self._move_signature(expectedMove),
                                self._move_signature(actualMove))
                            routeMoveKinds.append("route")
                elif (interrupt is not None
                        and interrupt.turn == decisionTurn):
                    routeWasCommitted = True
                    if commitTurnIndex is None:
                        commitTurnIndex = turnIndex
                        self.assertEqual(
                            startArmyTile.tile_index,
                            interrupt.launch_tile_index)
                    self.assertIsNotNone(actualMove)
                    if actualMove is not None:
                        self.assertEqual(
                            self._move_signature(interrupt.move),
                            self._move_signature(actualMove))
                    routeMoveKinds.append("defense_interrupt")

                if winner is not None:
                    break
                if turnIndex == 2 and not routeWasCommitted:
                    self.fail(
                        "undefendable WRP hunt was not committed within three turns")
        finally:
            logHandler.pop_application()
            OutputPath(
                r"C:\cascade-debug-output\generals-bot\stealth_hunt_test_logs.txt"
            ).write_text(
                "\n".join(
                    line for line in logOutput.getvalue().splitlines()
                    if "STEALTH_ALLIN_" in line),
                encoding="utf-8")

        abortReasons = re.findall(
            r"STEALTH_ALLIN_ABORT .*?reason=([a-z_]+)",
            logOutput.getvalue())
        for reason in abortReasons:
            self.assertTrue(
                reason == "general_known"
                or reason.startswith("broken_")
                or reason == "route_complete"
                or reason == "cannot_kill",
                f"unexpected stealth route abort reason: {reason}")
        self.assertTrue(routeWasCommitted, "the WRP hunt route was never committed")
        self.assertIn("route", routeMoveKinds)
        self.assertIsNotNone(commitTurnIndex)
        if commitTurnIndex is not None:
            self.assertLessEqual(commitTurnIndex, 2)
        self.assertIsNotNone(playerMap.generals[enemyGeneral.player])
        self.assertNoFriendliesKilled(map, general)
        self.assertEqual(general.player, winner)

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

    def test_should_finish_losing_all_in_attack_instead_of_replanning_forever(self) -> None:
        """
        Regression for Human.exe-1v1-2026-11-13_04-03-10---IvN03GcjH: from t243 onward the
        losing all-in stealth planner aborted with reason=cannot_kill nearly every turn
        (projected army below the fog-defense requirement), wiping stealth state and curPath
        each time. The bot hovered a 200+ stack next to enemy land for ~220 turns while the
        enemy ran away with the game, instead of committing the stack to an attack.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        previousRandomState = random.getstate()
        self.addCleanup(random.setstate, previousRandomState)
        random.seed(0)
        previousMapRandomization = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(_restore_map_randomization, previousMapRandomization)
        MapBase.DO_NOT_RANDOMIZE = False
        mapFile = (
            "GameContinuationEntries/"
            "should_finish_losing_all_in_attack_instead_of_replan_gather_forever___"
            "IvN03GcjH---1--410.txtmap")
        map, general, enemyGeneral = self.load_map_and_generals(
            mapFile,
            410,
            fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(
            mapFile,
            respect_undiscovered=True,
            turn=410)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(
            map,
            player_with_viewer=general.player,
            playerMapVision=rawMap,
            allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, "None")
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.enable_stealth_all_in = True
        playerMap = simHost.get_player_map(general.player)
        self.assertTrue(bot.is_all_in_losing)

        startingEnemyTiles = map.players[enemyGeneral.player].tileCount
        startingFriendlyTiles = map.players[general.player].tileCount

        self.begin_capturing_logging()
        logOutput = io.StringIO()
        logHandler = logbook.StreamHandler(logOutput, level=logbook.INFO)
        logHandler.push_application()
        try:
            winner = simHost.run_sim(
                run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
                turn_time=0.25,
                turns=45)
        finally:
            logHandler.pop_application()
            OutputPath(
                r"C:\cascade-debug-output\generals-bot\stealth_stall_repro_410_logs.txt").write_text(
                "\n".join(
                    line for line in logOutput.getvalue().splitlines()
                    if "STEALTH_ALLIN_" in line),
                encoding="utf-8")

        abortReasons = re.findall(
            r"STEALTH_ALLIN_ABORT .*?reason=([a-z_]+)",
            logOutput.getvalue())
        cannotKillAborts = sum(
            1 for reason in abortReasons if reason == "cannot_kill")
        committedRouteMoves = len(
            re.findall(r"STEALTH_ALLIN_ROUTE_MOVE", logOutput.getvalue()))
        enemyTilesEnd = map.players[enemyGeneral.player].tileCount
        friendlyTilesEnd = map.players[general.player].tileCount
        # targetPlayerExpectedGeneralLocation falls back to bot.general when no prediction
        # exists, which makes .isGeneral trivially true and useless here; playerMap.generals
        # only lists the enemy general once the bot has actually discovered it.
        enemyGeneralRevealed = playerMap.generals[enemyGeneral.player] is not None
        logbook.info(
            f"stall repro results: winner={winner} "
            f"enemyTiles {startingEnemyTiles}->{enemyTilesEnd} "
            f"friendlyTiles {startingFriendlyTiles}->{friendlyTilesEnd} "
            f"cannotKillAborts={cannotKillAborts} "
            f"committedRouteMoves={committedRouteMoves} "
            f"enemyGeneralRevealed={enemyGeneralRevealed}")
        self.assertNoFriendliesKilled(map, general)
        # A losing all-in that actually executes must take the fight to the enemy: the stack
        # either reveals the general or takes enough enemy land that the abort loop cannot
        # have owned every turn like it did in the live game.
        self.assertLessEqual(
            cannotKillAborts,
            8,
            f"stealth all-in aborted cannot_kill {cannotKillAborts} times in 45 turns; "
            f"the planner is thrashing instead of attacking")
        self.assertTrue(
            enemyGeneralRevealed
            or committedRouteMoves >= 10
            or enemyTilesEnd < startingEnemyTiles - 12
            or friendlyTilesEnd > startingFriendlyTiles + 25,
            f"no attack progress in 45 turns: enemyTiles "
            f"{startingEnemyTiles}->{enemyTilesEnd}, friendlyTiles "
            f"{startingFriendlyTiles}->{friendlyTilesEnd}, "
            f"committedRouteMoves={committedRouteMoves}, "
            f"enemyGeneralRevealed={enemyGeneralRevealed}")

    def test_should_not_suppress_expansion_and_never_attack_when_losing(self) -> None:
        """
        Regression for Human.exe-1v1-2026-11-13_04-03-10---IvN03GcjH: after the losing all-in
        latched around t243 the bot gained ~2 tiles over the next 50 turns while the enemy
        gained ~22. Expansion was suppressed by is_all_in_losing but the stealth all-in never
        produced an attack either, so the bot did nothing for the whole midgame.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        previousRandomState = random.getstate()
        self.addCleanup(random.setstate, previousRandomState)
        random.seed(0)
        previousMapRandomization = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(_restore_map_randomization, previousMapRandomization)
        MapBase.DO_NOT_RANDOMIZE = False
        mapFile = (
            "GameContinuationEntries/"
            "should_not_suppress_expansion_and_never_attack_when_losing___"
            "IvN03GcjH---1--250.txtmap")
        map, general, enemyGeneral = self.load_map_and_generals(
            mapFile,
            250,
            fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(
            mapFile,
            respect_undiscovered=True,
            turn=250)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(
            map,
            player_with_viewer=general.player,
            playerMapVision=rawMap,
            allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, "None")
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.enable_stealth_all_in = True
        playerMap = simHost.get_player_map(general.player)
        self.assertTrue(bot.is_all_in_losing)

        startingFriendlyTiles = map.players[general.player].tileCount
        startingEnemyTiles = map.players[enemyGeneral.player].tileCount

        self.begin_capturing_logging()
        logOutput = io.StringIO()
        logHandler = logbook.StreamHandler(logOutput, level=logbook.INFO)
        logHandler.push_application()
        try:
            winner = simHost.run_sim(
                run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
                turn_time=0.25,
                turns=50)
        finally:
            logHandler.pop_application()
            OutputPath(
                r"C:\cascade-debug-output\generals-bot\stealth_stall_repro_250_logs.txt").write_text(
                "\n".join(
                    line for line in logOutput.getvalue().splitlines()
                    if "STEALTH_ALLIN_" in line or "ALLIN" in line),
                encoding="utf-8")
        friendlyTilesEnd = map.players[general.player].tileCount
        enemyTilesEnd = map.players[enemyGeneral.player].tileCount
        abortReasons = re.findall(
            r"STEALTH_ALLIN_ABORT .*?reason=([a-z_]+)",
            logOutput.getvalue())
        cannotKillAborts = sum(
            1 for reason in abortReasons if reason == "cannot_kill")
        committedRouteMoves = len(
            re.findall(r"STEALTH_ALLIN_ROUTE_MOVE", logOutput.getvalue()))
        enemyGeneralRevealed = playerMap.generals[enemyGeneral.player] is not None
        logbook.info(
            f"expansion suppress repro results: winner={winner} "
            f"friendlyTiles {startingFriendlyTiles}->{friendlyTilesEnd} "
            f"cannotKillAborts={cannotKillAborts} "
            f"committedRouteMoves={committedRouteMoves} "
            f"enemyGeneralRevealed={enemyGeneralRevealed} "
            f"is_all_in_losing={bot.is_all_in_losing}")
        self.assertNoFriendliesKilled(map, general)
        # In the live game the losing all-in sat in a cannot_kill abort loop for ~170 turns:
        # expansion is gated off while all-in, so the bot gained ~2 tiles in 50 turns while the
        # enemy gained ~22. The fix is not to un-gate expansion (one move per turn means an
        # all-in and expansion are mutually exclusive anyway) but to make the all-in actually
        # attack: a committed stack marching the route every turn is the productive action the
        # abort loop prevented.
        self.assertLessEqual(
            cannotKillAborts,
            8,
            f"stealth all-in aborted cannot_kill {cannotKillAborts} times in 50 turns; "
            f"the planner is thrashing instead of attacking or expanding")
        self.assertTrue(
            committedRouteMoves >= 10
            or enemyGeneralRevealed
            or friendlyTilesEnd > startingFriendlyTiles + 12
            or enemyTilesEnd < startingEnemyTiles - 12,
            f"bot stagnated for 50 turns: friendlyTiles "
            f"{startingFriendlyTiles}->{friendlyTilesEnd}, "
            f"enemyTiles {startingEnemyTiles}->{enemyTilesEnd}, "
            f"committedRouteMoves={committedRouteMoves}, "
            f"enemyGeneralRevealed={enemyGeneralRevealed}")

    def test_should_continue_committed_kill_attack_instead_of_slow_gather(self) -> None:
        """
        Regression for Human.exe-1v1-2026-11-13_04-35-50---BkuI_3_3L: at t526 the quick-kill
        eval committed a 158-army attack on the known enemy general at 15,7 (kill in ~10t).
        One turn later the pessimistic cutoffKillArmy estimate drifted 109->149, the eval
        flipped, and the attack was abandoned for a 28-turn all-in gather that delivered
        only ~70 more army. The stack parked at 9,5 for 22 turns, resumed too late, and the
        bot lost. A committed kill attack must keep executing through marginal re-eval noise.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        previousRandomState = random.getstate()
        self.addCleanup(random.setstate, previousRandomState)
        random.seed(0)
        previousMapRandomization = MapBase.DO_NOT_RANDOMIZE
        self.addCleanup(_restore_map_randomization, previousMapRandomization)
        MapBase.DO_NOT_RANDOMIZE = False
        mapFile = (
            "GameContinuationEntries/"
            "should_continue_committed_kill_attack_instead_of_slow_gather___"
            "BkuI_3_3L---0--527.txtmap")
        map, general, enemyGeneral = self.load_map_and_generals(
            mapFile,
            527,
            fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(
            mapFile,
            respect_undiscovered=True,
            turn=527)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(
            map,
            player_with_viewer=general.player,
            playerMapVision=rawMap,
            allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, "None")
        bot = self.get_debug_render_bot(simHost, general.player)

        self.begin_capturing_logging()
        logOutput = io.StringIO()
        logHandler = logbook.StreamHandler(logOutput, level=logbook.INFO)
        logHandler.push_application()
        try:
            winner = simHost.run_sim(
                run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
                turn_time=0.25,
                turns=14)
        finally:
            logHandler.pop_application()
            OutputPath(
                r"C:\cascade-debug-output\generals-bot\qk_abandon_repro_logs.txt").write_text(
                "\n".join(
                    line for line in logOutput.getvalue().splitlines()
                    if "quick-kill" in line or "QK " in line or "cutoffKillArmy" in line),
                encoding="utf-8")

        # The committed kill path is 8,5->9,5->10,5->11,5->12,5->12,6->13,6->14,6->15,6->15,7.
        # With the bug the attack is dropped after a single move and the 154 stack parks at
        # 9,5 while the bot runs gather moves on the far side of the map.
        killCorridor = {
            (8, 5), (9, 5), (10, 5), (11, 5), (12, 5),
            (12, 6), (13, 6), (14, 6), (15, 6), (15, 7)}
        playerMoves = simHost.sim.players[general.player].move_history
        corridorMoves = [
            m for m in playerMoves
            if m is not None and (m.source.x, m.source.y) in killCorridor]
        enemyGeneralCaptured = (
            simHost.sim.sim_map.GetTile(15, 7).player == general.player)
        logbook.info(
            f"qk abandon repro results: winner={winner} "
            f"corridorMoves={len(corridorMoves)} "
            f"moves={[str(m) for m in playerMoves if m is not None]} "
            f"enemyGeneralCaptured={enemyGeneralCaptured}")
        self.assertNoFriendliesKilled(map, general)
        self.assertTrue(
            enemyGeneralCaptured
            or winner == general.player
            or len(corridorMoves) >= 5,
            f"committed kill attack was abandoned: only {len(corridorMoves)} "
            f"corridor moves in 14 turns, moves="
            f"{[str(m) for m in playerMoves if m is not None]}")

    def test_should_all_in_along_short_top_path_instead_of_long_bottom_flank(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_along_short_top_path_instead_of_long_bottom_flank___BkuI_3_3L---0--450.txtmap'
        trueMapFile = 'GameContinuationEntries/should_all_in_along_short_top_path_instead_of_long_bottom_flank___BkuI_3_3L---0--450.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 450, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=450)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        # The enemy general is known to sit on one of ~5 adjacent tiles, a ~12-move top
        # path away. Gathering a few extra 5's/6's onto the attack line justifies ~7 more
        # turns; anything slower means the bot took the long bottom flank again.
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=32)
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(general.player, winner, 'bot should kill the enemy general within 32 turns via the short top all-in')

    def test_going_all_in_on_army_advantage_should_gather_at_the_opp_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/going_all_in_on_army_advantage_should_gather_at_the_opp_general___HgFB_1ohh---b--242.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 242, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=242)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        bot = self.get_debug_render_bot(simHost)

        bot.is_all_in_army_advantage = True

        # alert enemy of the player general
        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        startTurn = simHost.sim.turn
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.2, turns=80)
        logbook.info(f'game over after {simHost.sim.turn - startTurn} turns')
        self.assertIsNotNone(winner)
        self.assertEqual(map.player_index, winner)

    def test_when_all_in_with_large_tile_should_keep_attacking_effectively(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/when_all_in_with_large_tile_should_keep_attacking_effectively___rgKAG2M6n---b--299.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 299, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=299)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.2, turns=30)
        self.assertEqual(map.player_index, winner)

    def test_set_all_in_to_hit_with_timings(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_spend_nearly_full_cycle_gathering_out_of_play_armies___Nw5bXrfqz---0--102.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 102, fill_out_tiles=True, respect_player_vision=True)
        for x in range(5, 15):
            y = 6
            tile = map.GetTile(x, y)
            tile.army = 0
            tile.player = -1
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 2, 2)

        def update_player(t: Tile):
            t.player = enemyGeneral.player
            t.army = 2

        SearchUtils.breadth_first_foreach(map, [enemyGeneral], 3, update_player)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=102)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.targetPlayerExpectedGeneralLocation = self.get_player_tile(14, 5, simHost.sim, general.player)
        bot.armyTracker.emergenceLocationMap = [MapMatrix(rawMap, 0) for p in map.players]
        bot.timings = Timings(50, 5, 20, 31, 0, 0, disallowEnemyGather=False)
        bot.behavior_out_of_play_defense_threshold = 0.3

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.5, turns=75)
        self.assertIsNone(winner)

        sumArmyNear = BotCombatOps.sum_player_standing_army_near_or_on_tiles(bot,bot.shortest_path_to_target_player.tileList, distance=3)
        self.assertGreater(sumArmyNear, 60)

    def test_should_all_in_enemy_general_since_no_meaningful_defense(self):
        # exploration is a bit random, run the test a bunch to make sure its consistent.
        for i in range(10):
            with self.subTest(i=i):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
                mapFile = 'GameContinuationEntries/should_all_in_enemy_general_since_no_meaningful_defense___SRrkSRhku---0--187.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 187, fill_out_tiles=True)
                enemyGeneral = self.move_enemy_general(map, enemyGeneral, 15, 0)
                enemyGeneral.army = 4

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=187)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '14,13->13,13->12,13  None  12,13->11,13->10,13->9,13  None  9,13->8,13->8,12->8,11->8,10->8,11->9,11')
                bot = self.get_debug_render_bot(simHost, general.player)
                bot.armyTracker.new_army_emerged(bot._map.GetTile(14, 4), 40)
                # SPECIFICALLY NOT REVEALED, BOT SHOULD KNOW IT HAS AN EXPLORATION RACE
                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                genPlayer = general.player
                winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.1, turns=14)
                self.assertEqual(genPlayer, winner)

    def test_should_contest_cities_when_all_in_gathering_at_opp(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_contest_cities_when_all_in_gathering_at_opp___n35SxPk5n---0--235.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 235, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 5, 10)
        enemyGeneral.army = 35

        # self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=235)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.finishing_exploration = True
        bot.is_all_in_army_advantage = True
        bot.all_in_army_advantage_counter = 15
        bot.all_in_army_advantage_cycle = 50
        bot.armyTracker.new_army_emerged(bot._map.GetTile(8, 12), 50)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.2, turns=3)
        self.assertIsNone(winner)
        city = self.get_player_tile(7, 10, simHost.sim, general.player)
        self.assertGreater(city.army, 30, 'should not abandon contested city when contesting it guarantees an army+economy win condition.')

    def test_should_all_in_general_when_contested_cities_out_of_position_and_knows_no_army_on_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_general_when_contested_cities_out_of_position_and_knows_no_army_on_general___z1yhdwnBO---0--327.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 327, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=327)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.2, turns=15)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_all_in_general_when_contested_cities_out_of_position_and_knows_no_army_on_general")

    def test_should_not_switch_to_all_in_and_time_with_cycle_appropriately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for turn, expectCityTaken in [(199, True), (179, False)]:
            with self.subTest(turn=turn):
                mapFile = 'GameContinuationEntries/should_switch_to_all_in_and_time_with_cycle_appropriately___zXtNQLyfR---1--179.txtmap'
                # has enough army to take city in this variation in both cases
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)
                self.move_enemy_general(map, enemyGeneral, 16, 1)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                self.set_general_emergence_around(13, 5, simHost, general.player, enemyGeneral.player, 8)
                bot = self.get_debug_render_bot(simHost, general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.5, turns=21)
                self.assertIsNone(winner)

                self.assertNoRepetition(simHost, minForRepetition=2)
                city = self.get_player_tile(15, 12, simHost.sim, general.player)
                if expectCityTaken:
                    self.assertEqual(general.player, city.player)
                else:
                    self.assertGreater(bot._map.players[general.player].tileCount, 65)
                    self.assertEqual(-1, city.player)

                self.assertFalse(BotStateQueries.is_all_in(bot))

    def test_should_switch_to_all_in_and_time_with_cycle_appropriately(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        for turn, shouldAllIn, moveEnemyCity, runForTurns in [(200, True, True, 25), (200, True, False, 15), (200, False, True, 10), (225, True, True, 25), (225, True, False, 15), (179, False, True, 15)]:
            with self.subTest(turn=turn, moveEnemyCity=moveEnemyCity):
                mapFile = 'GameContinuationEntries/should_switch_to_all_in_and_time_with_cycle_appropriately___zXtNQLyfR---1--179.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)
                cityToRemove = map.GetTile(15, 12)
                map.convert_tile_to_mountain(cityToRemove)
                enCity = map.GetTile(14, 5)

                if moveEnemyCity:
                    map.convert_tile_to_mountain(enCity)
                    map.players[enemyGeneral.player].cities.remove(enCity)
                    newEnCity = map.GetTile(8, 0)
                    newEnCity.tile = enemyGeneral.player
                    newEnCity.isMountain = False
                    newEnCity.isCity = True
                    newEnCity.army = 2
                    newEnCity.player = enemyGeneral.player
                    enCity = newEnCity
                    map.players[enemyGeneral.player].cities.append(enCity)

                self.move_enemy_general(map, enemyGeneral, 18, 0)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)
                rawMap.convert_tile_to_mountain(rawMap.GetTile(15, 12))

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, 'None')
                self.set_general_emergence_around(13, 5, simHost, general.player, enemyGeneral.player, 12)
                bot = self.get_debug_render_bot(simHost, general.player)

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.1, turns=runForTurns)
                self.assertIsNone(winner)

                city = self.get_player_tile(enCity.x, enCity.y, simHost.sim, general.player)
                if shouldAllIn:
                    if not moveEnemyCity and turn > 210:
                        self.assertEqual(general.player, city.player)
                        self.assertFalse(BotStateQueries.is_all_in(bot), "should have immediately found and sat on the enemy city, and stopped all-inning to hold the city instead.")
                        self.assertNoRepetition(simHost, minForRepetition=2)
                    else:
                        self.assertTrue(bot.all_in_city_behind, "should still be all-inning for cities")
                        self.assertTrue(BotStateQueries.is_all_in(bot), "should not have immediately found and sat on the enemy city, and still be all-inning")
                else:
                    if runForTurns > 15 or turn > 215:
                        self.assertGreater(bot._map.players[general.player].tileCount, 63)
                        self.assertEqual(-1, city.player)
                    self.assertNoRepetition(simHost, minForRepetition=2)

    def test_should_detect_incoming_all_in_attack_and_maintain_defense_when_up_on_econ_and_opp_keeps_gathering(self):
        # ref D:/KeptGeneralsLogs/almostBeatSpraget_Human.exe-1v1-2023-10-09_01-49-26---6ZAGySdUX
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_play_defensive_when_just_recaptured_city___6ZAGySdUX---1--214.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 214, fill_out_tiles=True)
        self.move_enemy_general(map, enemyGeneral, 14, 6)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=214)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.5, turns=36)
        self.assertIsNone(winner)

        self.assertGatheredNear(simHost, general.player, 3, 9, 4, requiredAvgTileValue=1.5)

        botTiles = playerMap.players[general.player].tileCount
        enTiles = playerMap.players[enemyGeneral.player].tileCount

        self.assertGreater(botTiles, enTiles - 6, "Bot should kind of catch up on tiles a little while playing super defensive gatherwise.")
        self.assertCleanedUpTilesNear(simHost, general.player, 6, 3, 4, capturedWithinLastTurns=30, requireCountCapturedInWindow=7)

    def test_should_go_all_in_along_existing_path_with_army_on_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_go_all_in_along_existing_path_with_army_on_it___Teammate.exe-7wShG5xG7---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_go_all_in_along_existing_path_with_army_on_it")

    def test_should_all_in_gen_trade_when_almost_certain_of_general_location(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_all_in_gen_trade_when_almost_certain_of_general_location___Qn0ivuj37---1--433.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 433, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=433)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,15->8,14->8,13->9,13->9,12->10,12->11,12->11,11->11,10->12,10')
        bot = self.get_debug_render_bot(simHost, general.player)
        self.set_general_emergence_around(0, 16, simHost, general.player, enemyGeneral.player, 50)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.2, turns=10)
        self.assertEqual(map.player_index, winner)

    def test_should_immediately_all_in_hold_wall_break_by_opp__should_pull_out_of_position_army_to_hold(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # https://generals.io/replays/089dxyou6
        mapFile = 'GameContinuationEntries/should_immediately_all_in_out_of_position_army_to_hold_wall_break_choke_city_captured_by_opp___089dxyou6---0--524.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 524, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 19, 17)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=524)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=75)
        self.assertIsNone(winner)

        wallBreakCity = self.get_player_tile(12, 11, simHost.sim, general.player)
        self.assertEqual(general.player, wallBreakCity.player)
        self.assertGreater(wallBreakCity.army, 300, "should all-in hold city as long as economically ahead.")

    def test_should_all_in_en_gen_when_opp_doesnt_know_our_gen_and_cannot_hold_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_en_gen_when_opp_doesnt_know_our_gen_and_cannot_hold_city___Hx1ru6UDJ---0--284.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 284, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=284)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_all_in_en_gen_when_opp_doesnt_know_our_gen_and_cannot_hold_city")

    def test_should_all_in_gather_own_defensive_line_to_en_until_safe(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_gather_own_defensive_line_to_en_until_safe___JZtyCrKWK---4--330.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 330, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=330)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=75)
        self.assertIsNone(winner)

        gatheredNear = BotCombatOps.sum_player_standing_army_near_or_on_tiles(bot,[playerMap.players[general.player].general], distance=10, player=general.player)
        self.assertGreater(gatheredNear, 400)

    def test_should_not_go_all_in_so_early(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_go_all_in_so_early____5kMDUymF---0--176.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 176, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=176)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        simHost.sim.ignore_illegal_moves = True
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertEqual(0, bot.all_in_losing_counter)

    def test_should_not_let_opp_catch_up_when_going_temp_all_in(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_let_opp_catch_up_when_going_temp_all_in___pPZuQD1Iq---1--541.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 541, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=541)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=35)
        self.assertEqual(general.player, winner)

    def test_should_not_early_all_in_when_not_necessary(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_early_all_in_when_not_necessary___CaVJAhDen---1--115.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 115, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=115)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(0, bot.all_in_losing_counter)

    def test_should_finish_all_in_attacks(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_finish_all_in_attacks___QoMfyZD0B---1--824.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 824, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=824)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        self.assertNoFriendliesKilled(map, general)

        self.skipTest("TODO add asserts for should_finish_all_in_attacks")

    def test_should_detect_lost_round_and_detect_all_in_opportunity_and_set_up_all_in_instead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_detect_lost_round_and_detect_all_in_opportunity_and_set_up_all_in_instead___5vkV_-LbW---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 19, 9)
        enemyGeneral.army = 11

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)

        # the all-in setup here is attack from gen on the exact turn that would reach the enemy general on round end, so IMMEDIATELY here.
        # then pull our 3 and all in immediately.

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,16->12,13->12,12z  12,13->11,13  15,9->15,10  13,10->13,9  15,12->14,12->14,11  19,9->19,10->16,10')
        # next round
        simHost.queue_player_moves_str(enemyGeneral.player, '12,16->11,16  12,17->11,17  12,15->11,15  14,12->15,12->14,12  19,14->19,12->20,12  20,7->19,7->19,9  20,14->20,9->19,9  17,8->19,8->19,9')

        # proof
        # simHost.queue_player_moves_str(general.player, '14,19->14,18->16,18->16,10->18,10  17,19->16,19->16,18  17,12->16,12  14,20->14,18->16,18->16,10->19,10->19,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=1)
        self.assertIsNone(winner)
        self.assertIn(WinCondition.KillAllIn, bot.win_condition_analyzer.viable_win_conditions)
        self.assertTrue(bot.is_all_in_losing)
        self.assertGreater(bot.all_in_losing_counter, 0)
        self.assertTrue(BotStateQueries.is_all_in(bot))
        self.assertIsNotNone(bot.win_condition_analyzer.all_in_plan)
        self.assertTrue(bot.win_condition_analyzer.projected_loss_all_in_active)
        # self.assertEqual(enemyGeneral, bot.win_condition_analyzer.projected_loss_all_in_target)
        # self.assertEqual(enemyGeneral, bot.win_condition_analyzer.all_in_plan.tail.tile)
        self.assertIn(map.GetTile(14, 18), bot.win_condition_analyzer.all_in_plan.tileSet)
        self.assertNoFriendliesKilled(map, general)
        self.assertLess(general.army, 3, 'should have moved the general or tbh just attacked with the 36, not sure which is better.')

    def test_should_detect_lost_round_and_detect_all_in_opportunity_and_set_up_all_in_instead__long(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_detect_lost_round_and_detect_all_in_opportunity_and_set_up_all_in_instead___5vkV_-LbW---1--137.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 137, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 19, 9)
        enemyGeneral.army = 11

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=137)

        # the all-in setup here is attack from gen on the exact turn that would reach the enemy general on round end, so IMMEDIATELY here.
        # then pull our 3 and all in immediately.

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,16->12,13->12,12z  12,13->11,13  15,9->15,10  13,10->13,9  15,12->14,12->14,11  19,9->19,10->16,10')
        # next round
        simHost.queue_player_moves_str(enemyGeneral.player, '12,16->11,16  12,17->11,17  12,15->11,15  14,12->16,12  19,14->19,12->20,12  20,7->19,7->19,9  20,14->20,9->19,9  17,8->19,8->19,9')

        # proof
        # simHost.queue_player_moves_str(general.player, '14,19->14,18->16,18->16,10->18,10  17,19->16,19->16,18  17,12->16,12  14,20->14,18->16,18->16,10->19,10->19,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=32)
        self.assertNoFriendliesKilled(map, general)
        self.assertOwned(general.player, enemyGeneral)
