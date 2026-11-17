import random
import time
import typing
from unittest.mock import patch

from Algorithms import MapSpanningUtils
from BotModules.BotRendering import BotRendering
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot


class _ChoiceForbiddenRandom(random.Random):
    """random.Random whose choice() always raises AssertionError: proves the
    post-resume placement refresh retained every still-legal prior without a
    single random pick."""

    __slots__ = ()

    def choice(self, seq: typing.Sequence[Tile]) -> Tile:
        """Fail loudly if any code path still needs a random pick."""
        raise AssertionError('rng.choice must not run when restored priors all survive')


class FogLandBuilderTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_tile_deltas = True
        bot.info_render_army_emergence_values = True
        bot.armyTracker.log_debug = True
        # bot.info_render_
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_should_drop_bad_fog_predictions_after_discovering_army_came_from_different_direction(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_drop_bad_fog_predictions_after_discovering_army_came_from_different_direction___lUHbWMb9w---2--211.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 211, fill_out_tiles=True)

        goodTiles = [
            map.GetTile(10, 15),
            map.GetTile(11, 15),
            map.GetTile(12, 15),
            map.GetTile(13, 15),
            map.GetTile(14, 15),
            map.GetTile(13, 16),
            map.GetTile(13, 17),
        ]
        badTiles = [
            map.GetTile(8, 15),
            map.GetTile(8, 16),
            map.GetTile(7, 16),
            map.GetTile(6, 16),
            map.GetTile(5, 16),
            map.GetTile(4, 16),
            map.GetTile(3, 16),
            map.GetTile(3, 15),
            map.GetTile(3, 14),
            map.GetTile(3, 13),
            map.GetTile(4, 13),
            map.GetTile(6, 13),
            map.GetTile(6, 12),
        ]
        for tile in goodTiles:
            tile.player = enemyGeneral.player
            tile.army = 2
        for tile in badTiles:
            tile.army = 0
            tile.player = -1

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=211)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(general.player, '9,13->9,14->9,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        for tile in goodTiles:
            playerTile = playerMap.GetTile(tile.x, tile.y)
            self.assertEqual(-1, playerTile.player)

        for tile in badTiles:
            playerTile = playerMap.GetTile(tile.x, tile.y)
            self.assertEqual(enemyGeneral.player, playerTile.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general, allyGen)

        for tile in badTiles:
            playerTile = playerMap.GetTile(tile.x, tile.y)
            self.assertEqual(-1, playerTile.player)

    def test_should_build_land_between_known_emergences(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49_actual_spawn.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 49, fill_out_tiles=True)

        ogFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49.txtmap'
        rawMap, _ = self.load_map_and_general(ogFile, respect_undiscovered=True, turn=49)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->9,3  5,11->6,11->7,11->8,11->9,11->10,11->11,11->12,11->13,11  5,11->5,10->5,9->4,9->4,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 34
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.5, turns=15)
        self.assertIsNone(winner)

        self.assertGreater(len(playerMap.players[enemyGeneral.player].tiles), 16)
        self.assertOwned(enemyGeneral.player, playerMap.GetTile(10, 8))
        self.assertTileIn(playerMap.GetTile(11, 11), bot.armyTracker.player_connected_tiles[enemyGeneral.player])
        self.assertTileXYIn(playerMap, 10, 7, bot.armyTracker.player_connected_tiles[enemyGeneral.player])
        self.assertTileXYIn(playerMap, 8, 6, bot.armyTracker.player_connected_tiles[enemyGeneral.player])
        self.assertTileXYIn(playerMap, 10, 11, bot.armyTracker.player_connected_tiles[enemyGeneral.player])

    def test_should_build_land_between_known_emergences__single_emergence(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49_actual_spawn.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 49, fill_out_tiles=True)

        ogFile = 'GameContinuationEntries/should_immediately_re_evaluate_target_path___Pmzuw7IAX---0--49.txtmap'
        rawMap, _ = self.load_map_and_general(ogFile, respect_undiscovered=True, turn=49)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->9,3  5,11->6,11->7,11->8,11->9,11->10,11->11,11->12,11->13,11  5,11->5,10->5,9->4,9->4,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.armyTracker.player_launch_timings[enemyGeneral.player] = 34
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.5, turns=3)
        self.assertIsNone(winner)

        self.assertGreater(len(playerMap.players[enemyGeneral.player].tiles), 10)

    def test_should_set_emergence_around_uncovered_initial_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_set_emergence_around_uncovered_initial_tiles___gUX8yTL0J---1--194.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 194, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=194)
        rawMap.GetTile(17, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(18, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(19, 17).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(19, 16).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(20, 16).reset_wrong_undiscovered_fog_guess()
        rawMap.GetTile(20, 15).reset_wrong_undiscovered_fog_guess()

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertTrue(bot._map.euclidDist(20, 14, bot.targetPlayerExpectedGeneralLocation.x, bot.targetPlayerExpectedGeneralLocation.y) < 5)

    def test_should_not_overcreate_fog_land_when_army_moves_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_track_army_into_the_fog___J2DCEX-R3---1--570.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 570, fill_out_tiles=True)
        map.GetTile(9, 11).army = 3

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=570)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,9->7,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.skipTest('need to add new assertions for the fog land builder specifically')

    def test_fog_land_builder_should_not_take_ages_to_build__when_just_one_big_massive_emergence_set_from_ffa_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/fog_land_builder_should_not_take_ages_to_build___Sx5Tl3mwJ---2--880.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 880, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=880)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        start = time.perf_counter()
        MapSpanningUtils.LOG_VERBOSE = True
        bot.armyTracker.update_fog_prediction(enemyGeneral.player, bot.opponent_tracker.get_player_fog_tile_count_dict(enemyGeneral.player), bot.targetPlayerExpectedGeneralLocation, force=True)
        duration = time.perf_counter() - start
        self.assertLess(duration, 0.003, 'should not take ages to build fog land')

    def test_shouldnt_over_build_fog_land_on_vision_loss__when_enemy_out_of_cave_tiles_but_has_wallbreak_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_over_build_fog_land_on_vision_loss_and_fog_adjacent_captures___oNee0ECyL---0--206.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 206, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=206)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,16->15,16->15,17->7,17')
        simHost.queue_player_moves_str(general.player, 'None  None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general)
        self.assertOwned(-1, playerMap.GetTile(18, 17), 'this OBVIOUSLY was not captured, at no point could it have been')
        self.assertOwned(-1, playerMap.GetTile(17, 16), 'this OBVIOUSLY was not captured, at no point could it have been')
        self.assertOwned(-1, playerMap.GetTile(16, 17), 'this OBVIOUSLY was not captured, at no point could it have been')
        self.assertOwned(-1, playerMap.GetTile(15, 18), 'this OBVIOUSLY was not captured, at no point could it have been')

    def test_fog_fill_prefers_land_near_valid_general_positions__fills_19_0_over_17_16(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # Imported t207 continuation of the wallbreak vision-loss scenario: (17,16) was
        # sighted neutral during the t206->t207 turn, so the file records it as
        # discovered-neutral memory ('D') — but lastSeen is not serialized, so the
        # imported state does NOT know the sighting was fresh. The ONLY reason (19,0)
        # can win over (17,16) here is general-position proximity: enemy land is
        # contiguous with some remaining valid spawn, so gen-proximal fog (19,0 at
        # genDist ~4) is a strictly better prediction than a vision-edge tile far from
        # every spawn (17,16, genDist 14).
        mapFile = 'GameContinuationEntries/fog_fill_prefers_gen_proximity___oNee0ECyL---0--207.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 207, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=207)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        bot.armyTracker.should_recalc_fog_land_by_player[enemyGeneral.player] = True
        bot.armyTracker.update_fog_prediction(enemyGeneral.player, bot.opponent_tracker.get_player_fog_tile_count_dict(enemyGeneral.player), bot.targetPlayerExpectedGeneralLocation, force=True)

        self.assertOwned(enemyGeneral.player, playerMap.GetTile(19, 0), 'fog land should be filled near the remaining valid general positions')
        self.assertOwned(-1, playerMap.GetTile(17, 16), 'without fresh-sighting info, (17,16) is a stale everOwned fog tile far from every valid general position — it must lose to gen-proximal (19,0)')

    def test_shouldnt_over_build_fog_land_on_vision_loss_and_fog_adjacent_captures(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_over_build_fog_land_on_vision_loss_and_fog_adjacent_captures___oNee0ECyL---0--206.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 206, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=206)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,15->16,16->15,16->15,17->7,17')
        simHost.queue_player_moves_str(general.player, 'None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=8)
        self.assertNoFriendliesKilled(map, general)
        self.assertOwned(-1, playerMap.GetTile(9, 17), 'this cannot have been captured yet. Fog land builder should expand armies in the fog before rebuilding and redistributing.')

    def test_shouldnt_pick_wonky_far_city_just_because_wall_breach(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/shouldnt_pick_wonky_far_city_just_because_wall_breach___C2LBGDHPN---0--179.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 179, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=179)
        rawMap.GetTile(19, 11).reset_wrong_undiscovered_fog_guess()

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=1)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwned(-1, playerMap.GetTile(19, 11))

    def test_should_prune_dead_fog_land_prediction_on_empty_discovery(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prune_dead_fog_land_prediction_on_empty_discovery___N92iSpgIx---1--140.txtmap'
        trueMapFile = 'GameContinuationEntries/should_prune_dead_fog_land_prediction_on_empty_discovery___N92iSpgIx---1--140.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 140, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=140)

        # the imported fog state had all of these predicted as enemy 1s when they are
        # really empty; the reveal must drop the whole disconnected prediction, not
        # just the two tiles that get sighted.
        newlyDiscoveredNeutralTiles = [(4, 13), (5, 13)]
        deadFogPredictionTiles = [
            (3, 14), (4, 14), (5, 14), (6, 14),
            (2, 15), (3, 15), (5, 15), (6, 15),
            (2, 16), (3, 16), (4, 16), (6, 16),
            (3, 17),
        ]
        for x, y in newlyDiscoveredNeutralTiles + deadFogPredictionTiles:
            self.assertEqual(enemyGeneral.player, rawMap.GetTile(x, y).player,
                             f'import sanity: ({x},{y}) should have been fog-predicted enemy land')

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        simHost.queue_player_moves_str(general.player, '6,11->6,12->5,12  None  None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        # exactly two moves land us at turn 142: the turn (4,13) is sighted after
        # (5,13) was sighted at 141. Any still-standing dead prediction here means
        # the disproof flood did not trigger the rebuild at the discovery turn.
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
        self.assertNoFriendliesKilled(map, general)

        for x, y in newlyDiscoveredNeutralTiles:
            tile = playerMap.GetTile(x, y)
            self.assertEqual(-1, tile.player, f'discovered tile ({x},{y}) should be empty, not enemy-owned')
            self.assertEqual(0, tile.army, f'discovered tile ({x},{y}) should be empty, not an enemy 1')
            self.assertTrue(tile.discovered, f'discovered tile ({x},{y}) should be marked discovered')

        for x, y in deadFogPredictionTiles:
            tile = playerMap.GetTile(x, y)
            self.assertEqual(-1, tile.player,
                             f'dead fog prediction ({x},{y}) should be pruned to neutral once (4,13)/(5,13) proved empty')
            self.assertFalse(tile.isTempFogPrediction,
                             f'dead fog prediction ({x},{y}) should not still be temp-predicted enemy land')

        # (3,11) stays on the still-connected side of the 'a' flood claim; the prune
        # must only kill the fog cut off behind the disproved neutrals, not the
        # prediction blob that remains anchored to real enemy land.
        self.assertEqual(enemyGeneral.player, playerMap.GetTile(3, 11).player)
        self.assertFogOwnedByXY(-1, 6, 17, 'not connected to any general spawns.')
        self.assertFogOwnedByXY(-1, 9, 17, 'not connected to any general spawns.')
        self.assertFogOwnedByXY(-1, 7, 16, 'not connected to any general spawns.')
        self.assertFogOwnedByXY(-1, 9, 16, 'not connected to any general spawns.')
        self.assertFogOwnedByXY(-1, 10, 16, 'not connected to any general spawns.')
        self.assertFogOwnedByXY(-1, 0, 16, 'not connected to any general spawns.')
        self.assertFogOwnedByXY(-1, 0, 17, 'not connected to any general spawns.')

    def test_should_separate_ffa_fog_land_from_predicted_generals(self) -> None:
        """
        Regression: at turn 31 of the Human.exe FFA replay the pre-joint code
        passed the TARGET player's (treasurecritter8, player 4) predicted
        general seed to EVERY player's FogLandBuilder.update_fog_prediction, so
        speculative fog land near player 4's four-tile candidate region
        {(16,7),(17,7),(18,8),(18,9)} - including the observed 'e' strip at
        x=17,y=4..8 - could be anchored to the wrong player's prediction. The
        joint FFA placement (ArmyTracker.ffa_general_placement) now gives each
        player their own seed; this test asserts every living player's seed is
        hard-valid, mutually >= min_spawn_distance, owned by that player in
        their own fog build, and that no foreign temp land touches player 4's
        seed or candidate region.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_separate_ffa_fog_land_from_predicted_generals___CHZf7CtWk---2--31.txtmap'
        trueMapFile = 'GameContinuationEntries/should_separate_ffa_fog_land_from_predicted_generals___CHZf7CtWk---2--31.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 31, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=31)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # replay moves for the 3 turns after turn 31
        simHost.queue_player_moves_str(0, '22,20->21,20->21,21->20,21->20,22')  # replay moves: 12314
        simHost.queue_player_moves_str(1, '10,5->11,5->11,6->11,7->10,7')  # replay moves: gababool
        # proof (reference trajectory only - prediction is not a move goal):
        # simHost.queue_player_moves_str(general.player, 'none  none  23,4->23,3->22,3')  # replay line for Human.exe
        simHost.queue_player_moves_str(3, 'none  1,19->2,19  none  1,19->2,19')  # replay moves: ghjddfghjhgf
        simHost.queue_player_moves_str(4, '18,4->18,3->18,2->18,1')  # replay moves: treasurecritter8
        simHost.queue_player_moves_str(6, '16,23->16,22->16,23->17,23->18,23')  # replay moves: shoopshoopadoop
        simHost.queue_player_moves_str(7, '3,6->3,7->4,7->5,7->6,7')  # replay moves: Hckfjxjdn
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # treasurecritter8's settled candidate region at turn 31 (bot view):
        # the fixture must carry EXACTLY these four tiles.
        targetPlayer = 4
        tracker = bot.armyTracker
        originalRegion = {
            tile for tile in tracker.valid_general_positions_by_player[targetPlayer]}
        self.assertEqual(
            {(t.x, t.y) for t in originalRegion},
            {(16, 7), (17, 7), (18, 8), (18, 9)},
            'fixture must carry exactly treasurecritter8\'s settled 4-tile candidate region')

        def assert_joint_ffa_placement() -> None:
            """Per-turn joint-placement + fog-seed invariants, run after each sim turn."""
            placement = tracker.ffa_general_placement
            living = [p for p in playerMap.players if not p.dead and p.capturedBy is None]
            enemyLiving = [p for p in living if p.index != general.player]

            # every living player has a predicted position
            for p in living:
                self.assertIsNotNone(
                    placement.positions[p.index],
                    f'p{p.index} has no predicted general position')

            seeds = {}
            for p in living:
                seed = placement.positions[p.index]
                seeds[p.index] = seed
                if p.index == general.player:
                    continue
                # each unknown prediction is hard-valid and not neutral-discovered
                self.assertTrue(
                    tracker.valid_general_positions_by_player[p.index][seed],
                    f'p{p.index} seed {seed} is not a hard-valid general position')
                self.assertFalse(
                    seed.discoveredAsNeutral,
                    f'p{p.index} seed {seed} was discovered as neutral')

            # pairwise seeds >= min_spawn_distance, including vs our known general
            minDist = tracker.min_spawn_distance
            livingIndices = [p.index for p in living]
            for i, idxA in enumerate(livingIndices):
                for idxB in livingIndices[i + 1:]:
                    dist = playerMap.manhattan_dist(seeds[idxA], seeds[idxB])
                    self.assertGreaterEqual(
                        dist, minDist,
                        f'p{idxA} seed {seeds[idxA]} and p{idxB} seed {seeds[idxB]} are {dist} < {minDist} apart')

            # seeds must also stay >= min_spawn_distance from retained former
            # (dead/captured) general anchors.
            for p in enemyLiving:
                for blocker in placement.ex_general_blockers:
                    dist = playerMap.manhattan_dist(seeds[p.index], blocker)
                    self.assertGreaterEqual(
                        dist, minDist,
                        f'p{p.index} seed {seeds[p.index]} is {dist} < {minDist} '
                        f'from ex-general blocker {blocker}')

            # treasurecritter8 stays inside its original candidate region until new
            # evidence rules candidates out.
            targetSeed = seeds[targetPlayer]
            stillValid = {
                t for t in originalRegion
                if tracker.valid_general_positions_by_player[targetPlayer][t]}
            if len(stillValid) > 0:
                self.assertIn(
                    targetSeed, stillValid,
                    f'treasurecritter8 seed {targetSeed} left still-valid region {stillValid}')
            else:
                self.assertTrue(
                    tracker.valid_general_positions_by_player[targetPlayer][targetSeed],
                    f'treasurecritter8 seed {targetSeed} not hard-valid after region disproven')

            # no OTHER player's temporary land may sit on treasurecritter8's seed
            # or anywhere inside its original four-tile candidate region.
            self.assertFalse(
                targetSeed.isTempFogPrediction
                and targetSeed.player >= 0
                and targetSeed.player != targetPlayer,
                f'treasurecritter8 seed {targetSeed} is temp-owned by p{targetSeed.player}')
            for regionTile in originalRegion:
                self.assertFalse(
                    regionTile.isTempFogPrediction
                    and regionTile.player >= 0
                    and regionTile.player != targetPlayer,
                    f'region tile {regionTile} is temp-owned by p{regionTile.player}')

            # every living enemy with tiles actually has fog-predicted land:
            # its OWN seed must appear in that player's connected set, be owned
            # by that player as a temp prediction (the real fog seed), and the
            # player must hold temp-predicted tiles.
            for p in enemyLiving:
                if playerMap.players[p.index].tileCount <= 0:
                    continue
                seed = seeds[p.index]
                self.assertIsNotNone(seed, f'p{p.index} has tiles but no seed')
                connected = tracker.connectedByPlayer[p.index]
                self.assertTrue(
                    connected,
                    f'p{p.index} tileCount>0 but connectedByPlayer is empty')
                self.assertIn(
                    seed, connected,
                    f'p{p.index} fog connected set does not contain its own seed {seed}')
                self.assertEqual(
                    seed.player, p.index,
                    f'p{p.index} seed {seed} is owned by p{seed.player}, not its own fog build')
                self.assertTrue(
                    seed.isTempFogPrediction,
                    f'p{p.index} seed {seed} is not a temp fog prediction')
                self.assertTrue(
                    any(t.isTempFogPrediction and t.player == p.index
                        for t in playerMap.players[p.index].tiles),
                    f'p{p.index} tileCount>0 but has no temp-predicted fog land')

            # no-information players' speculative temp fill must respect the
            # nearest-seed Voronoi policy except on hard-evidence tiles.
            for p in enemyLiving:
                hasEmergence = bool(
                    tracker.uneliminated_emergence_events[p.index]
                    or tracker.unrecaptured_emergence_events[p.index])
                hasLandEvidence = len(tracker.ffa_general_land_evidence[p.index]) > 0
                if hasEmergence or hasLandEvidence:
                    continue
                ownSeed = seeds[p.index]
                if ownSeed is None:
                    continue
                hardEvidence = (
                    set(tracker.uneliminated_emergence_events[p.index].keys())
                    | set(tracker.unrecaptured_emergence_events[p.index])
                    | set(tracker.tiles_ever_owned_by_player[p.index])
                    | set(tracker.discovered_enemy_land_connector_tiles[p.index]))
                rivalSeeds = [
                    seeds[idx] for idx in livingIndices
                    if idx != p.index and seeds[idx] is not None]
                for tile in playerMap.players[p.index].tiles:
                    if not tile.isTempFogPrediction or tile in hardEvidence:
                        continue
                    ownDist = playerMap.manhattan_dist(tile, ownSeed)
                    for rivalSeed in rivalSeeds:
                        self.assertGreaterEqual(
                            playerMap.manhattan_dist(tile, rivalSeed), ownDist,
                            f'p{p.index} temp tile {tile} is closer to rival seed {rivalSeed} '
                            f'than its own {ownSeed} without hard evidence')

        simHost.run_between_turns(assert_joint_ffa_placement)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=3)
        self.assertIsNone(winner)
        self.assertNoFriendliesKilled(map, general)

    def test_should_roundtrip_ffa_predicted_general_positions(self) -> None:
        """
        Stage6: the FFAPredictedGeneralPositions footer persists the joint
        placement vector (one row-major tile_index per player, -1 for empty
        slots). A resumed bot must restore those tiles on its OWN map, keep
        every still-legal no-info prior through the first refresh WITHOUT any
        rng.choice, and dump the identical vector again.
        """
        mapFile = 'GameContinuationEntries/should_separate_ffa_fog_land_from_predicted_generals___CHZf7CtWk---2--31.txtmap'
        trueMapFile = 'GameContinuationEntries/should_separate_ffa_fog_land_from_predicted_generals___CHZf7CtWk---2--31.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 31, fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=31)
        # the fixture predates the footer key: the first host exercises the
        # legacy no-key load path, which must keep working unchanged.
        self.assertNotIn('FFAPredictedGeneralPositions', rawMap.resume_data)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)

        # NOTE: no player is artificially marked dead here - the reload host
        # builds its own map copy, so a post-load .dead mutation would not
        # round-trip and the revived player would legitimately need a random
        # pick. '-1'/None slot coverage lives in the codec unit tests
        # (UnitTests.test_FfaGeneralPlacement serialization tests); this
        # integration test exercises the real dump -> resume -> refresh ->
        # redump path with every player alive.
        placement = bot.armyTracker.ffa_general_placement
        placement.refresh(bot.armyTracker, bot.targetPlayer)
        self.assertTrue(placement.complete)
        savedPositions = list(placement.positions)
        savedIndices = [
            tile.tile_index if tile is not None else -1 for tile in savedPositions]
        expectedVector = ','.join(str(index) for index in savedIndices)

        dumped = BotRendering.dump_turn_data_to_string(bot)
        resumeData = {}
        for line in dumped.split('\n'):
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            resumeData[key] = value
        self.assertEqual(expectedVector, resumeData['FFAPredictedGeneralPositions'])

        rawMap.resume_data.update(resumeData)
        reloadHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        reloadBot = self.get_debug_render_bot(reloadHost, general.player)
        reloadPlacement = reloadBot.armyTracker.ffa_general_placement

        # restored slots resolve to Tile objects on the RELOAD bot's own map
        self.assertEqual(len(savedIndices), len(reloadPlacement.positions))
        for playerIndex, tileIndex in enumerate(savedIndices):
            restored = reloadPlacement.positions[playerIndex]
            if tileIndex == -1:
                self.assertIsNone(restored, f'p{playerIndex} must stay unplaced')
                continue
            self.assertIsNotNone(restored, f'p{playerIndex} lost its saved position')
            self.assertEqual(tileIndex, restored.tile_index)
            self.assertIs(
                reloadBot._map.GetTile(restored.x, restored.y), restored,
                f'p{playerIndex} position must be a tile of the reload map')

        # first refresh after resume: every still-legal prior is reserved, so
        # not a single rng.choice may run.
        with patch('random.Random', _ChoiceForbiddenRandom):
            reloadPlacement.invalidate()
            reloadPlacement.refresh(reloadBot.armyTracker, reloadBot.targetPlayer)

        for playerIndex, tileIndex in enumerate(savedIndices):
            restored = reloadPlacement.positions[playerIndex]
            if tileIndex == -1:
                self.assertIsNone(restored, f'p{playerIndex} must stay unplaced')
                continue
            self.assertIsNotNone(restored)
            self.assertEqual(
                tileIndex, restored.tile_index,
                f'p{playerIndex} still-legal prior must survive refresh un-re-rolled')

        # a second dump emits the identical vector
        redumped = BotRendering.dump_turn_data_to_string(reloadBot)
        redumpedData = {}
        for line in redumped.split('\n'):
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            redumpedData[key] = value
        self.assertEqual(
            resumeData['FFAPredictedGeneralPositions'],
            redumpedData['FFAPredictedGeneralPositions'])


    def test_should_not_drag_informed_general_prediction_to_enemy_emergence(self):
        """
        Regression: replay pbqrasXyY turn 94->95. Our move 25,8->24,8->24,9
        reveals GREEN (Undefeatable, p2) land at (23,15). The flipped-tile
        emergence spread in ArmyTracker._post_army_track_handle_flipped_tiles
        wrote emergence//2 into EVERY player's matrix on the discovery, smearing
        pink's (carrotopx, p5) own emergence field into the fog tiles beside
        green's reveal ((22,15) hit 19+20/2=29). Pink's informed pick then jumped
        from ~(17,7) to (22,15) - next to GREEN's land, 20+ tiles from pink's
        true general at (10,7) - and green got leftovers at (23,24). Assert the
        informed predictions stay near each player's own evidence: pink within 6
        of (18,9), green within 6 of its only observed land/emergence (23,15).
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_drag_informed_general_prediction_to_enemy_emergence___pbqrasXyY---4--94.txtmap'
        trueMapFile = 'GameContinuationEntries/should_not_drag_informed_general_prediction_to_enemy_emergence___pbqrasXyY---4--94.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 94, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=94)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # replay moves for the 4 turns after turn 94
        simHost.queue_player_moves_str(0, '4,23->5,23->5,22->6,22')  # replay moves: andrzejo
        simHost.queue_player_moves_str(1, '1,5->1,6->1,7->2,7->3,7')  # replay moves: KillaK
        simHost.queue_player_moves_str(2, '19,16->18,16->18,15->17,15->17,16')  # replay moves: Undefeatable
        simHost.queue_player_moves_str(3, '15,14->16,14->17,14')  # replay moves: Creesch
        # replaying our real moves is required - 25,8->24,8->24,9 reveals the
        # green tile at (23,15) that triggered the bad turn-95 recompute.
        simHost.queue_player_moves_str(general.player, '24,13->24,14->25,14  25,8->24,8->24,9')  # replay line for Human.exe
        simHost.queue_player_moves_str(5, '17,0->16,0->15,0->15,1->15,2')  # replay moves: carrotopx
        simHost.queue_player_moves_str(6, '3,17->2,17  none  2,17->1,17')  # replay moves: Fear
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        pinkPlayer = 5    # carrotopx - true general (10,7), evidence around x16-22,y4-8
        greenPlayer = 2   # Undefeatable - true general (21,20), only evidence at (23,15)
        placementByTurn = {}

        def capture_ffa_placements() -> None:
            placement = bot.armyTracker.ffa_general_placement
            placementByTurn[playerMap.turn] = dict(
                (p, placement.positions[p]) for p in (pinkPlayer, greenPlayer))

        simHost.run_between_turns(capture_ffa_placements)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)

        self.assertIn(95, placementByTurn, 'expected a turn-95 placement snapshot after the reveal')
        turn95 = placementByTurn[95]
        pinkSeed = turn95[pinkPlayer]
        greenSeed = turn95[greenPlayer]
        self.assertIsNotNone(pinkSeed, 'pink has no predicted general position at turn 95')
        self.assertIsNotNone(greenSeed, 'green has no predicted general position at turn 95')
        self.assertLessEqual(
            playerMap.manhattan_dist(pinkSeed, playerMap.At(18, 9)), 6,
            f'pink seed {pinkSeed} was dragged away from its own land/emergence evidence (18,9 area)')
        self.assertLessEqual(
            playerMap.manhattan_dist(greenSeed, playerMap.At(23, 15)), 6,
            f'green seed {greenSeed} left the region of its only observed evidence (23,15)')

    def test_should_not_swap_ffa_predictions_to_enemy_land(self):
        """
        Regression: replay pbqrasXyY turn 114->115. Fear captures andrzejo and
        green's (Undefeatable, p2) emergence at (23,15) is resolved, but the
        joint prediction landed green at (18,10) - directly under pink's
        (carrotopx, p5) observed land - while pink stayed at (22,15) next to
        GREEN's land: the two predictions were effectively swapped onto each
        other's evidence. Diffuse emergence-matrix deposits (fog-frontier
        incAmount spread, pruning bonuses) in green's matrix out-scored the
        tiles beside its real (23,15) emergence under the old 10*emergenceMap
        scoring. Assert pink stays within 6 of its own evidence (18,9 area) and
        green within 6 of its own emergence (23,15).
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_swap_ffa_predictions_to_enemy_land___pbqrasXyY---4--114.txtmap'
        trueMapFile = 'GameContinuationEntries/should_not_swap_ffa_predictions_to_enemy_land___pbqrasXyY---4--114.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 114, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=114)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # replay moves for the 4 turns after turn 114
        simHost.queue_player_moves_str(0, '1,23->2,23')  # replay moves: andrzejo
        simHost.queue_player_moves_str(1, '0,5->0,6->0,7->0,8  5,7->4,7')  # replay moves: KillaK
        simHost.queue_player_moves_str(2, '23,16->23,15  none  24,16->23,16  24,17->23,17')  # replay moves: Undefeatable
        simHost.queue_player_moves_str(3, '22,15->22,16->23,16->23,17')  # replay moves: Creesch
        simHost.queue_player_moves_str(general.player, '25,11->25,10  23,6->23,7->24,7  24,11->24,10')  # replay line for Human.exe
        simHost.queue_player_moves_str(5, '19,5->20,5  none  14,0->15,0->16,0')  # replay moves: carrotopx
        simHost.queue_player_moves_str(6, '2,17->2,18  none  2,23->2,22  2,21->2,22')  # replay moves: Fear
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        pinkPlayer = 5    # carrotopx - true general (10,7), evidence around x16-22,y4-8
        greenPlayer = 2   # Undefeatable - true general (21,20), emergence at (23,15)
        placementByTurn = {}

        def capture_ffa_placements() -> None:
            placement = bot.armyTracker.ffa_general_placement
            placementByTurn[playerMap.turn] = dict(
                (p, placement.positions[p]) for p in (pinkPlayer, greenPlayer))

        simHost.run_between_turns(capture_ffa_placements)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=2)
        self.assertNoFriendliesKilled(map, general)

        self.assertIn(115, placementByTurn, 'expected a turn-115 placement snapshot after the emergence')
        turn115 = placementByTurn[115]
        pinkSeed = turn115[pinkPlayer]
        greenSeed = turn115[greenPlayer]
        self.assertIsNotNone(pinkSeed, 'pink has no predicted general position at turn 115')
        self.assertIsNotNone(greenSeed, 'green has no predicted general position at turn 115')
        self.assertLessEqual(
            playerMap.manhattan_dist(pinkSeed, playerMap.At(18, 9)), 6,
            f'pink seed {pinkSeed} was dragged away from its own land/emergence evidence (18,9 area)')
        self.assertLessEqual(
            playerMap.manhattan_dist(greenSeed, playerMap.At(23, 15)), 6,
            f'green seed {greenSeed} left the region of its own emergence evidence (23,15)')
