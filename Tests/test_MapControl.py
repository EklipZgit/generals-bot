import DebugHelper
import GatherUtils
from DataModels import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.tile import Tile_MOUNTAIN, TILE_EMPTY
from bot_ek0x45 import EklipZBot


class MapControlTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        # bot.info_render_centrality_distances = True
        GatherUtils.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True
        bot.info_render_expansion_matrix_values = True
        # bot.info_render_general_undiscovered_prediction_values = True
        bot.info_render_leaf_move_values = True

        return bot
    
    def test_should_prevent_large_attack_from_running_around_right_bottom(self):
        # around turn 187 opp starts moving down the right size in the fog, which the bot can guess based on tiles being captured.
        # TODO realistically, the bot should have already explored this land instead of just the land up above.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prevent_large_attack_from_running_around_right_bottom___qPcfqRptY---1--152.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 152, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=152)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=35)
        self.assertNoFriendliesKilled(map, general)
    
    def test_expansion_should_prefer_tiles_moving_towards_flank_routes(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/expansion_should_prefer_tiles_moving_towards_flank_routes___qPcfqRptY---1--187.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 187, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=187)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        if debugMode:
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=0)

        leaves = [l for l in bot.prioritize_expansion_leaves(bot.leafMoves) if l.dest.player == -1]

        expectedBestSrc = playerMap.GetTile(12, 14)
        # can go up or down, so dont assert dest
        # expectedBestDest = playerMap.GetTile(12, 15)
        bestLeaf = leaves[0]
        self.assertEqual(expectedBestSrc, bestLeaf.source)
        # self.assertEqual(expectedBestDest, bestLeaf.dest)

        expectedNextSrc = playerMap.GetTile(4, 5)
        expectedNextDest = playerMap.GetTile(5, 5)
        nextLeaf = leaves[1]
        self.assertEqual(expectedNextSrc, nextLeaf.source)
        self.assertEqual(expectedNextDest, nextLeaf.dest)

