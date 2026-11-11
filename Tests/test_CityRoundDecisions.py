import logbook
import typing
from pathlib import Path as FilePath

from base.client.map import Score
from base.client.tile import Tile, TILE_FOG, TILE_OBSTACLE
from Models import Move
from BotModules.BotStateQueries import BotStateQueries
from Gather.GatherCapturePlan import GatherCapturePlan
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class CityRoundDecisionTests(TestBase):
    """
    Reproduction tests for Human.exe-1v1-2026-11-09_10-20-09---TtVz86M3i.

    The live bot committed ~18 turns gathering a 42-army neutral city at 1,6
    (selected at t115, captured at t133) while the enemy out-economied it, then
    immediately latched a projected-loss KillAllIn at t133 when the score-based
    city counter inflated the enemy city count 1->5 by crediting the bot's own
    neutral-city chipping damage as enemy city captures.
    """
    __slots__ = ()

    def test_should_expand_instead_of_committing_to_slow_neutral_city_t115(self) -> None:
        """
        At t115 the bot's expansion plan selected the 12-turn-estimated 42-army
        neutral city capture at 1,6; the resulting gather actually ran t115-132.
        The desired contract is that the expansion step keeps expanding instead of
        committing to the slow city. We assert the selected option does not target
        1,6 (not that the city is never offered - a fix may merely deprioritize it).
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_expand_instead_of_committing_to_slow_neutral_city___TtVz86M3i---1--115.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 115, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=115)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        checkedTurns: typing.List[int] = []

        def assert_expansion_decision() -> None:
            """Check the selected plan and move together, before the next decision."""
            turn = simHost.sim.turn
            decidedMoves = bot.history.move_history.get(turn, [])
            decidedMove = decidedMoves[-1] if decidedMoves else None
            self.assertIsNotNone(decidedMove, f'bot returned no move on turn {turn}')
            selectedOption = bot.expansion_plan.selected_option
            targetTile: Tile | None = None
            if isinstance(selectedOption, GatherCapturePlan):
                targetTile = selectedOption.gather_target
            elif selectedOption is not None and selectedOption.tail is not None:
                targetTile = selectedOption.tail.tile
            logbook.info(
                f'city-round replay t{turn}: option={selectedOption} target={targetTile} move={decidedMove}')
            self.assertFalse(
                targetTile is not None and targetTile.coords == (1, 6),
                f't{turn} committed to the slow neutral city: {selectedOption}')
            checkedTurns.append(turn)

        simHost.run_between_turns(assert_expansion_decision)
        self.begin_capturing_logging()
        simHost.run_sim(
            run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
            turn_time=0.25,
            turns=10)
        self.assertTrue(set(range(115, 125)).issubset(checkedTurns))

    def test_should_not_invent_enemy_cities_or_force_all_in_while_chipping_neutral_city(self) -> None:
        """
        Replay of the score-based city counting across the neutral-city chip turns.

        At t131 the bot owns 119/56t with 1 city and the enemy owns 127/71t with
        1 city. At t132 our score drops to 116 (the neutral city at 1,6 still has
        ~4 army chipped off by our gather damage) while the enemy is 128/71t. The
        live score-derived city counter credited that neutral-city damage to the
        enemy and set enemyCityCount to 5, which fed WCA_PROJECTED_ROUND_LOSS and
        latched the KillAllIn at t133. First assertion expects the true count of 1.
        """
        mapFile131 = 'GameContinuationEntries/should_not_invent_enemy_cities_while_chipping_neutral_city___TtVz86M3i---1--131.txtmap'
        mapFile132 = 'GameContinuationEntries/should_not_invent_enemy_cities_while_chipping_neutral_city___TtVz86M3i---1--132.txtmap'
        mapFile133 = 'GameContinuationEntries/should_not_invent_enemy_cities_while_chipping_neutral_city___TtVz86M3i---1--133.txtmap'

        liveMap, _ = self.load_map_and_general(mapFile131, respect_undiscovered=True, turn=131, player_index=1)
        nextMap, _ = self.load_map_and_general(mapFile132, respect_undiscovered=True, turn=132, player_index=1)
        self.assertEqual(1, liveMap.player_index)

        # the txtmap loader does not populate .visible; in its encoding plain
        # tiles are in-vision, 'D'-marked tiles are discovered-not-visible
        # (.discovered), fog is TILE_FOG/TILE_OBSTACLE, and undiscovered
        # inferred tiles carry isTempFogPrediction.
        for tile in liveMap.get_all_tiles():
            tile.visible = (tile.tile != TILE_FOG and tile.tile != TILE_OBSTACLE
                            and not tile.discovered and not tile.isTempFogPrediction)
        for tile in nextMap.get_all_tiles():
            tile.visible = (tile.tile != TILE_FOG and tile.tile != TILE_OBSTACLE
                            and not tile.discovered and not tile.isTempFogPrediction)

        liveMap.update_scores([Score(0, 127, 71, False), Score(1, 119, 56, False)])
        # update() shifts scoreHistory[0] into [1] and computes score deltas against
        # [1]; seed it with the authoritative t131 scores so the t132 delta matches live.
        liveMap.scoreHistory[0] = [Score(0, 127, 71, False), Score(1, 119, 56, False)]

        liveMap.update_turn(132)
        liveMap.update_scores([Score(0, 128, 71, False), Score(1, 116, 56, False)])
        # the live t131 submitted move chipped the neutral city at 1,6 from 2,6;
        # the map's neutral-damage accounting uses this to exclude the spend from
        # friendlyFightDelta instead of crediting it to the enemy city count.
        liveMap.last_player_index_submitted_move = (
            liveMap.GetTile(2, 6), liveMap.GetTile(1, 6), False)
        for tile in nextMap.get_all_tiles():
            if not tile.visible:
                continue
            liveMap.update_visible_tile(
                tile.x,
                tile.y,
                tile.player,
                tile.army,
                is_city=tile.isCity,
                is_general=tile.isGeneral)
        liveMap.update()

        enemyPlayer = liveMap.players[0]
        friendlyFightDelta = liveMap.players[1].actualScoreDelta - liveMap.players[1].expectedScoreDelta
        logbook.info(
            f't132 replayed city counts: enemy {enemyPlayer.cityCount} '
            f'own {liveMap.players[1].cityCount} friendlyFightDelta {friendlyFightDelta} scores {liveMap.scores}')
        # live friendlyFightDelta was 4 at t132 (expected +1 vs actual -3 from
        # neutral-city chipping); verify the replayed delta mechanics match.
        self.assertEqual(4, abs(friendlyFightDelta))
        self.assertEqual(
            1,
            enemyPlayer.cityCount,
            f'score-based city counter invented enemy cities while chipping the neutral city (got {enemyPlayer.cityCount})')

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # Feed the corrected enemy city count into the t133 decision maps; the
        # 133 txtmap persists the bogus 5 and would otherwise poison the verdict.
        # Correct metadata BEFORE fog filling, or the loader creates four fake
        # owned cities whose simulated income recreates the original bad belief.
        rawText = (FilePath(__file__).parent / mapFile133).read_text()
        correctedText = '\n'.join(
            f'aCityCount={enemyPlayer.cityCount}' if line.startswith('aCityCount=') else line
            for line in rawText.splitlines())
        map, general, enemyGeneral = self.load_map_and_generals_from_string(
            correctedText, 133, player_index=1, fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general_from_string(
            correctedText, 133, player_index=1, respect_undiscovered=True)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # The txtmap serializes the all-in flags the live decision produced; reset
        # them so the test measures whether the CAUSE (bogus city counts) still
        # triggers the all-in rather than inheriting its own conclusion.
        bot.is_all_in_losing = False
        bot.all_in_losing_counter = 0
        # Also feed the corrected count into the decision's real inputs: the bot's
        # own player map and the opponent tracker's stored TeamStats, both of which
        # can be restored from the txtmap's bogus serialized values.
        bot._map.players[0].cityCount = enemyPlayer.cityCount
        bot.opponent_tracker.get_current_team_scores_by_player(0).cityCount = enemyPlayer.cityCount

        # Check subsequent decisions too, so an immediate re-latch cannot be
        # hidden by asserting only the first post-capture move.
        checkedTurns: typing.List[int] = []

        def record_all_in_state() -> None:
            """Verify the corrected city count and continued non-all-in movement."""
            turn = simHost.sim.turn
            self.assertEqual(1, bot._map.players[0].cityCount, f'city invention at t{turn}')
            self.assertFalse(
                bot.win_condition_analyzer.projected_loss_all_in_active,
                f'projected-loss all-in latched at t{turn}')
            self.assertFalse(BotStateQueries.is_all_in(bot), f'all-in at t{turn}')
            decidedMoves = bot.history.move_history.get(turn, [])
            self.assertTrue(decidedMoves, f'no decision recorded at t{turn}')
            self.assertIsNotNone(decidedMoves[-1], f'bot returned no move at t{turn}')
            checkedTurns.append(turn)

        simHost.run_between_turns(record_all_in_state)
        simHost.run_sim(
            run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING,
            turn_time=0.25,
            turns=7)

        # the callback also fires for the sim's trailing t134 make_move; only the
        # t133 entry is the decision under test.
        self.assertTrue(set(range(133, 140)).issubset(checkedTurns))
        simHost.assert_last_move_not_none(general.player)
