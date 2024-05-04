import time
import typing

import SearchUtils
from ExpandUtils import get_round_plan_with_expansion
from Interfaces import TilePlanInterface
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.tile import Tile, MapBase
from bot_ek0x45 import EklipZBot


class ExpansionTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_expansion_matrix_values = True
        bot.info_render_general_undiscovered_prediction_values = True
        bot.info_render_leaf_move_values = True

        return bot

    def run_expansion(
            self,
            map: MapBase,
            general: Tile,
            turns: int,
            negativeTiles: typing.Set[Tile],
            mapVision: MapBase | None,
            debugMode: bool = False,
            timeLimit: float | None = None,
    ) -> typing.Tuple[TilePlanInterface | None, typing.List[TilePlanInterface]]:
        # self.render_view_info(map, ViewInfo("h", map))
        # self.begin_capturing_logging()
        # SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = DebugHelper.IS_DEBUGGING
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=mapVision, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.viewInfo.turnInc()

        path, otherPaths = self.run_expansion_raw(bot, turns, negativeTiles, timeLimit)

        if debugMode:
            bot.prep_view_info_for_render()
            bot.viewInfo.add_info_line(f'max {str(path)}')
            for otherPath in otherPaths:
                bot.viewInfo.add_info_line(f'other {str(otherPath)}')

            self.render_view_info(bot._map, viewInfo=bot.viewInfo)

        return path, otherPaths

    def run_expansion_raw(
            self,
            bot: EklipZBot,
            turns: int,
            negativeTiles: typing.Set[Tile] | None,
            timeLimit: float,
    ) -> typing.Tuple[TilePlanInterface | None, typing.List[TilePlanInterface]]:

        if timeLimit is None:
            timeLimit = bot.expansion_full_time_limit

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()

        plan = get_round_plan_with_expansion(
            bot._map,
            searchingPlayer=bot.player.index,
            targetPlayer=bot.targetPlayer,
            turns=turns,
            boardAnalysis=bot.board_analysis,
            territoryMap=bot.territories.territoryMap,
            tileIslands=bot.tileIslandBuilder,
            negativeTiles=negativeTiles,
            leafMoves=bot.leafMoves,
            useLeafMovesFirst=bot.expansion_use_leaf_moves_first,
            viewInfo=bot.viewInfo,
            singleIterationPathTimeCap=bot.expansion_single_iteration_time_cap,
            forceNoGlobalVisited=bot.expansion_force_no_global_visited,
            forceGlobalVisitedStage1=bot.expansion_force_global_visited_stage_1,
            useIterativeNegTiles=bot.expansion_use_iterative_negative_tiles,
            allowLeafMoves=bot.expansion_allow_leaf_moves,
            allowGatherPlanExtension=bot.expansion_allow_gather_plan_extension,
            alwaysIncludeNonTerminatingLeavesInIteration=bot.expansion_always_include_non_terminating_leafmoves_in_iteration,
            time_limit=timeLimit,
            lengthWeightOffset=bot.expansion_length_weight_offset,
            useCutoff=bot.expansion_use_cutoff,
            smallTileExpansionTimeRatio=bot.expansion_small_tile_time_ratio,
            bonusCapturePointMatrix=bot._get_standard_expansion_capture_weight_matrix())
        path = plan.selected_option
        otherPaths = plan.all_paths

        return path, otherPaths

    def assertTilesCaptured(
            self,
            searchingPlayer: int,
            firstPath: TilePlanInterface,
            otherPaths: typing.List[TilePlanInterface],
            enemyAmount: int,
            neutralAmount: int = 0,
            assertNoDuplicates: bool = True):
        allPaths = [firstPath]
        allPaths.extend(p for p in otherPaths if p != firstPath)
        visited = set()
        failures = []
        enemyCapped = 0
        neutralCapped = 0
        for path in allPaths:
            for tile in path.tileList:
                if tile in visited:
                    if assertNoDuplicates:
                        failures.append(f'tile path {str(path.get_first_move().source)} had duplicate from other path {str(tile)}')
                    continue
                visited.add(tile)
                if tile.player != searchingPlayer:
                    if tile.isNeutral:
                        neutralCapped += 1
                    else:
                        enemyCapped += 1

        if neutralCapped != neutralAmount:
            failures.append(f'Expected {neutralAmount} neutral capped, instead found {neutralCapped}')
        if enemyCapped != enemyAmount:
            failures.append(f'Expected {enemyAmount} enemy capped, instead found {enemyCapped}')

        if len(failures) > 0:
            self.fail("Path captures didn't match expected:\r\n  " + "\r\n  ".join(failures))

    def assertMinTilesCaptured(
            self,
            searchingPlayer: int,
            firstPath: TilePlanInterface,
            otherPaths: typing.List[TilePlanInterface],
            minEnemyCaptures: int,
            minNeutralCaptures: int = 0,
            assertNoDuplicates: bool = True
    ):
        allPaths = [firstPath]
        allPaths.extend(otherPaths)
        visited = set()
        failures = []
        enemyCapped = 0
        neutralCapped = 0
        for path in allPaths:
            for tile in path.tileList:
                if tile in visited:
                    if assertNoDuplicates:
                        failures.append(f'tile path {str(path.get_first_move().source)} had duplicate from other path {str(tile)}')
                    continue
                visited.add(tile)
                if tile.player != searchingPlayer:
                    if tile.isNeutral:
                        neutralCapped += 1
                    else:
                        enemyCapped += 1

        if neutralCapped < minNeutralCaptures:
            failures.append(f'Expected at least {minNeutralCaptures} neutral capped, instead found {neutralCapped}')
        if enemyCapped < minEnemyCaptures:
            failures.append(f'Expected at least {minEnemyCaptures} enemy capped, instead found {enemyCapped}')

        if len(failures) > 0:
            self.fail("Path captures didn't match expected:\r\n  " + "\r\n  ".join(failures))

    def test__first_25_reroute__2_moves__should_find_2_tile_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = f'ExpandUtilsTestMaps/did_not_find_2_move_cap__turn34'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn=34, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=245)
        negTiles = set()
        negTiles.add(general)

        path, otherPaths = self.run_expansion(map, general, turns=2, negativeTiles=negTiles, mapVision=rawMap, debugMode=debugMode)
        # should go 5,9 -> 5,10 -> 4,10
        self.assertIsNotNone(path)
        self.assertEquals(path.length, 2)
        self.assertEquals(path.get_first_move().source, map.GetTile(5, 9))
        self.assertEquals(path.get_first_move().dest, map.GetTile(5, 10))
        self.assertEquals(path.get_first_move().dest, map.GetTile(4, 10))

    def test_should_not_split_for_neutral_while_exploring_enemy_path_with_largish_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_split_for_neutral_while_exploring_enemy_path_with_largish_army___SxyrToG62---b--95.txtmap'
        # intentionally pretend it is turn 94 so we give it time for the last neutral capture
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 94)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=94)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.sim.set_tile_vision(general.player, 12, 1, hidden=True, undiscovered=False)
        simHost.sim.set_tile_vision(general.player, 13, 1, hidden=True, undiscovered=True)
        simHost.sim.set_tile_vision(general.player, 13, 2, hidden=True, undiscovered=True)
        simHost.sim.set_tile_vision(general.player, 13, 3, hidden=True, undiscovered=True)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=6)
        self.assertIsNone(winner)
        #should have taken 5 enemy tiles and one neutral
        self.assertEqual(45, simHost.sim.players[general.player].map.players[general.player].tileCount)

        # this should be how many tiles the enemy has left after.
        self.assertEqual(17, simHost.sim.players[enemyGeneral.player].map.players[enemyGeneral.player].tileCount)

    def test_validate_expansion__calculates_basic_longer_to_enemy_tiles_expansion_correctly(self):
        rawMapData = """
|    |    |    |    |    |    |    |    |    |    |    |   
a8   a1   a1   a2   a1   a2   a2   a2   a2   a1   a1   a5  
a1   a1   a1   a1   a1   a1   a1   a1   a1             b1
a1   a1   a1   a1   a1                                 b1D
a1   a1   a1   aG1 
     a5   a1   a1   
     a1   a1   a1   
     b1
     b1D
       
      
                                                       bG50D
|    |    |    |    |    |    |    |    |    |    |    |
player_index=0
bot_target_player=1   
"""
        # 2 in 3 moves
        # 4 in 5 moves
        # 5 in 7 with one of the two's up top

        remainingTurns = 7
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general, enemyGeneral = self.load_map_and_generals_from_string(rawMapData, 400 - remainingTurns, fill_out_tiles=False)

        path, otherPaths = self.run_expansion(
            map,
            general,
            turns=remainingTurns,
            negativeTiles=set(),
            mapVision=map,
            debugMode=debugMode)

        self.assertIsNotNone(path)

        self.assertTilesCaptured(general.player, path, otherPaths, enemyAmount=4, neutralAmount=1)  #

        # should not move the general first
        self.assertNotEqual(general, path.get_first_move().source)

    def test_validate_expansion__calculates_city_expansion_correctly(self):
        # TODO expansion doesn't take city increment into account currently so this test will never pass until that is implemented.
        rawMapData = """
|    |    |    |    |    |    |    |    |    |    |    |   
a8   a1   a1   a2   a1   a2   a2   a2   a2   a1   a1   a5  
a1   a1   a1   a1   a1   a1   a1   a1   a1             b1
a1   a1   a1   a1   a1                                 b1D
a1   a1   a1   aG11 
     a5   a1   a1   
     a1   a1   a1   
     b1
     b1D      
       
      
                                                       bG50D
|    |    |    |    |    |    |    |    |    |    |    |
player_index=0
bot_target_player=1   
"""
        # 2 in 3 moves
        # 4 in 5 moves
        # gen has 13 army so then 12 more in 12 moves for 16 in 17 moves

        remainingTurns = 17
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        map, general, enemyGeneral = self.load_map_and_generals_from_string(rawMapData, 400 - remainingTurns, fill_out_tiles=False)

        self.begin_capturing_logging()
        path, otherPaths = self.run_expansion(
            map,
            general,
            turns=remainingTurns,
            negativeTiles=set(),
            mapVision=map,
            debugMode=debugMode)

        with self.subTest(careLess=False):
            self.assertIsNotNone(path)
            self.assertMinTilesCaptured(general.player, path, otherPaths, minEnemyCaptures=4, minNeutralCaptures=11, assertNoDuplicates=False)

            # should not move the general first
            self.assertNotEqual(general, path.get_first_move().source)

        with self.subTest(careLess=True):
            self.assertTilesCaptured(general.player, path, otherPaths, enemyAmount=4, neutralAmount=12, assertNoDuplicates=False)

    def test_validate_expansion__calculates_city_expansion_correctly__live_sim(self):
        # TODO expansion doesn't take city increment into account currently so this test will never pass until that is implemented.
        rawMapData = """
|    |    |    |    |    |    |    |    |    |    |    |   
a8   a1   a1   a2   a1   a2   a2   a2   a2   a1   a1   a5  
a1   a1   a1   a1   a1   a1   a1   a1   a1             b1
a1   a1   a1   a1   a1                                 b1D
a1   a1   a1   aG11 
     a5   a1   a1   
     a1   a1   a1   
     b1
     b1D      


                                                       bG50D
|    |    |    |    |    |    |    |    |    |    |    |
player_index=0
bot_target_player=1   
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 2 in 3 moves
        # 4 in 5 moves
        # gen has 13 army so then 12 more in 12 moves for 16 in 17 moves

        remainingTurns = 17
        turn = 400 - remainingTurns
        map, general, enemyGeneral = self.load_map_and_generals_from_string(rawMapData, turn, fill_out_tiles=False)

        rawMap, _ = self.load_map_and_general_from_string(rawMapData, respect_undiscovered=True, turn=turn)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=remainingTurns)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 50, '?')

    def test_should_not_launch_attack_at_suboptimal_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_launch_attack_at_suboptimal_time___uClPcbQ7W---1--89.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 89, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=89)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.quickExpandTurns = 0
        bot.timings.launchTiming = 25
        bot.timings.splitTurns = 13

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=11)
        self.assertIsNone(winner)

        self.assertEqual(36, simHost.get_player_map(general.player).players[general.player].tileCount)

    def test_should_expand_away_from_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_launch_attack_at_suboptimal_time___uClPcbQ7W---1--89.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 89, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=89)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.quickExpandTurns = 0
        bot.timings.launchTiming = 25
        bot.timings.splitTurns = 13

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=11)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 35)
    
    def test_should_not_find_no_expansion_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_find_no_expansion_moves___09Pxy0uTG---1--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=136)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.expansion_use_cutoff = False
        # bot.expansion_use_leaf_moves_first = True
        simHost.queue_player_moves_str(enemyGeneral.player, '7,6->7,5->7,4  9,6->10,6->11,6->11,5')

        # achieves 51 (12 diff)
        # simHost.queue_player_moves_str(general.player, '12,12->12,11->12,10->12,9->11,9->10,9->10,8->9,8->9,7->9,6->8,6->7,6->6,6  17,12->17,11  18,12->18,11  5,12->5,13->5,14')

        # achieves 13 diff
        # simHost.queue_player_moves_str(general.player, '6,12->5,12->5,13->5,14  17,12->17,11  18,12->18,11  12,12->12,11->13,11->14,11')

        # achieves 14 diff
        # simHost.queue_player_moves_str(general.player, '5,12->5,13->5,14  17,12->17,11  18,12->18,11  12,12->12,11->13,11->14,11')

        bot.timings = bot.get_timings()
        bot.timings.launchTiming = 30
        bot.timings.splitTurns = 30

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        # beginning at 67 tiles, 14 moves, 8 on general

        # instantly rallying general at 9,7->9,6 yields 51 tiles after neutral expands

        # alternatively
        # 3 in 4 by pushing out the 6,12 2+3, thats 70@10t

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=14)
        self.assertIsNone(winner)
        pMap = simHost.get_player_map(general.player)
        genPlayer = pMap.players[general.player]
        enPlayer = pMap.players[enemyGeneral.player]
        tileCountDiff = genPlayer.tileCount - enPlayer.tileCount
        # self.assertGreater(tileCountDiff, 11, 'instantly rallying general at 9,7->9,6 yields 51 tiles vs 39, a diff of 12')
        self.assertGreater(tileCountDiff, 13, 'expanding all neutral leaf moves and then rallying general to nearest neutral achieves 14')
    
    def test_should_capture_tiles_expanding_from_general__through_2s(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_tiles_expanding_from_general___sAmhiG3EO---0--143.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 143, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=143)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 46)
    
    def test_should_capture_tiles_towards_enemy(self):
        # it can cap downward and then rally immediate from gen
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_tiles_towards_enemy___Cuh4gfLI2---1--89.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 89, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=89)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        self.set_general_emergence_around(6, 13, simHost, general.player, enemyGeneral.player, emergenceAmt=20)
        bot = self.get_debug_render_bot(simHost, general.player)
        # bot.expansion_length_weight_offset = 0.0
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=11)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 39)
        self.assertPlayerTileCountLess(simHost, enemyGeneral.player, 30, 'should have captured 6 red tiles, not 5 or less.')

    def test_should_capture_tiles_towards_enemy__extra_turns(self):
        # it can cap downward and then rally immediate from gen, with extra moves
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_tiles_towards_enemy___Cuh4gfLI2---1--89.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        self.set_general_emergence_around(6, 13, simHost, general.player, enemyGeneral.player, emergenceAmt=20)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        ogDiff = self.get_tile_differential(simHost, general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=20)
        self.assertIsNone(winner)

        finalDiff = self.get_tile_differential(simHost, general.player)

        self.assertGreater(finalDiff, 20)
    
    def test_should_finish_expanding_with_army_already_near_leaves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_finish_expanding_with_army_already_near_leaves___emFpDYTkm---0--96.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 96, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=96)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=4)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 44)
    
    def test_should_capture_tiles_effectively_when_just_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_capture_tiles_effectively_when_just_gen___ws5z5FLzd---1--80.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 8, 19)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        self.set_general_emergence_around(10, 14, simHost, general.player, enemyGeneral.player, 21)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        initDifferential = self.get_tile_differential(simHost, general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=20)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 33)
        # 16 mv 2 en 3 neut if down+right
        # 4 remaining = 1 neut, so total 2 en, 4 neut in 20 moves is possible.
        finalTileDiff = self.get_tile_differential(simHost, general.player)
        self.assertEqual(12, finalTileDiff - initDifferential, "should be able to eek this much differential out of this AT LEAST. Change the assert if greater is found.")

    def test_should_attack_in_to_opponent_after_launch(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attack_in_to_opponent_after_launch___ws5z5FLzd---1--122.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 122, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 8, 19)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=122)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        self.set_general_emergence_around(9, 15, simHost, general.player, enemyGeneral.player, 21)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.3, turns=28)
        self.assertIsNone(winner)

        self.assertPlayerTileCountLess(simHost, enemyGeneral.player, 44)

        self.assertPlayerTileCountGreater(simHost, general.player, 58)
    
    def test_should_not_expand_into_neutral_city_wtf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_expand_into_neutral_city_wtf___2SlTV54vq---3--80.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts")  #  for should_not_expand_into_neutral_city_wtf
    
    def test_should_just_fucking_capture_tiles_not_dance_back_and_forth_wasting_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_just_fucking_capture_tiles_not_dance_back_and_forth_wasting_moves___KyRTYaDCf---2--87.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 87, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=87)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,6->7,5')
        simHost.queue_player_moves_str(enemyAllyGen.player, '7,6->7,5')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=13)
        self.assertNoFriendliesKilled(map, general, allyGen)

    
    def test_should_not_run_down_into_non_enemy_territory_with_kill_threat_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_run_down_into_non_enemy_territory_with_kill_threat_army___m31icdCyc---1--344.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 344, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=344)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.2, turns=10)
        self.assertIsNone(winner)

        self.skipTest("TODO add asserts for should_not_run_down_into_non_enemy_territory_with_kill_threat_army")
    
    def test_should_make_6_moves_with_2s_rather_than_gen_expansion__long_term_expansion_fix(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_make_6_moves_with_2s_rather_than_gen_expansion__long_term_expansion_fix___egm4K-VWp---1--144.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 144, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=144)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)

        self.assertPlayerTileCount(simHost, general.player, 53, "should capture 2 blue tiles and 2 neutrals")
        self.assertPlayerTileCount(simHost, enemyGeneral.player, 41, "should have captured 2 blue tiles")
    
    def test_should_not_expand_backwards_into_cave_with_full_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_expand_backwards_into_cave_with_full_army___31zZmf2vC---0--135.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 135, fill_out_tiles=True)

        path, otherPaths = self.run_expansion(
            map,
            general,
            turns=15,
            negativeTiles=set(),
            mapVision=map,
            debugMode=debugMode)

        self.assertIsNotNone(path)
        self.assertMinTilesCaptured(general.player, path, otherPaths, minEnemyCaptures=7, minNeutralCaptures=1)
    
    def test_should_piggyback_f25_well_and_recover_gracefully_from_interruptions(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_piggyback_f25_well_and_recover_gracefully_from_interruptions___lZ32yZ1q5---0--76.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 76, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=76)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,8->13,7->12,7->12,6->12,5->12,4->13,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=24)
        self.assertIsNone(winner)

        self.assertPlayerTileCountLess(simHost, enemyGeneral.player, 21)
        self.assertPlayerTileCountGreater(simHost, general.player, 36)
    #
    # def test_should_use_short_f25_piggyback_time_limit_when_told_to(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
    #     mapFile = 'GameContinuationEntries/should_piggyback_f25_well_and_recover_gracefully_from_interruptions___lZ32yZ1q5---0--76.txtmap'
    #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 56, fill_out_tiles=True)
    #
    #     rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=56)
    #
    #     self.enable_search_time_limits_and_disable_debug_asserts()
    #     simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
    #                                 allAfkExceptMapPlayer=True)
    #     simHost.queue_player_moves_str(enemyGeneral.player, '13,8->13,7->12,7->12,6->12,5->12,4->13,4')
    #     bot = self.get_debug_render_bot(simHost, general.player)
    #     playerMap = simHost.get_player_map(general.player)

    def test_should_use_short_expansion_time_limit_when_told_to__low_tile_count(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_make_6_moves_with_2s_rather_than_gen_expansion__long_term_expansion_fix___egm4K-VWp---1--144.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        timeStart = time.perf_counter()
        path, otherPaths = self.run_expansion_raw(
            bot,
            turns=50,
            negativeTiles=set(),
            timeLimit=0.03)
        duration = time.perf_counter() - timeStart

        if debugMode:
            self.render_view_info(bot._map, viewInfo=bot.viewInfo)

        self.assertLess(duration, 0.05, 'should not use much more time than what it was told to')

        self.assertMinTilesCaptured(general.player, path, otherPaths, 1, 7)

    def test_should_use_short_expansion_time_limit_when_told_to__high_tile_count(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_expand_into_neutral_city_wtf___2SlTV54vq---3--80.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 80, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=80)

        # self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        timeStart = time.perf_counter()
        path, otherPaths = self.run_expansion_raw(
            bot,
            turns=50,
            negativeTiles=set(),
            timeLimit=0.03)
        duration = time.perf_counter() - timeStart

        if debugMode:
            self.render_view_info(bot._map, viewInfo=bot.viewInfo)

        self.assertLess(duration, 0.05, 'should not use much more time than what it was told to')

        self.assertMinTilesCaptured(general.player, path, otherPaths, 11, 5)
    
    def test_should_piggyback_early_expand_correctly(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_piggyback_early_expand_correctly___9Zu7FGij5---0--74.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 74, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=74)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_should_use_large_army_taking_en_tiles_first(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_use_large_army_taking_en_tiles_first___nC_9ZP7XV---0--74.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 74, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 4, 15)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=74)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.completed_first_100 = True
        bot.timings = bot.get_timings()
        bot.timings.launchTiming = 24
        bot.timings.splitTurns = 24
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        shouldBeGen = playerMap.GetTile(7, 14)
        self.assertEqual(general.player, shouldBeGen.player)

    def test_should_prefer_enemy_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prefer_enemy_tiles___T60rbPlAO---0--81.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 81, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=81)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        initTileDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=19)
        self.assertIsNone(winner)

        self.assertGreater(self.get_tile_differential(simHost) - initTileDiff, 16)
        # we can beat 16
    
    def test_should_not_immediately_launch_from_general_before_launch_split(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_immediately_launch_from_general_before_launch_split___W0AVxc1fu---1--113.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 113, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=113)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.launchTiming = 27
        bot.timings.splitTurns = 24
        bot.curPath = None
        bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player).approximate_fog_army_available_total -= 20
        bot.opponent_tracker.get_current_cycle_stats_by_player(enemyGeneral.player).moves_spent_gathering_fog_tiles -= 4
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
        self.assertIsNone(winner)

        self.assertGreater(playerMap.GetTile(general.x, general.y).army, 32, 'should not have launched from general yet.')
        self.assertGreater(self.get_tile_differential(simHost), 5, "should have captured tiles, though")
    
    def test_should_launch_attack_when_attack_path_captures_more_than_expansion_plan(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_launch_attack_when_attack_path_captures_more_than_expansion_plan___HKJztNNqg---0--74.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 74, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=74)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=26)
        self.assertIsNone(winner)

        self.assertGreater(playerMap.players[general.player].tileCount, 43, "should have launched off general for more tiles than expansion plan")

    # 11f-14p with cycleTurns not launchDist turns    
    def test_should_not_interrupt_expansion_to_poorly_intercept_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_interrupt_expansion_to_poorly_intercept_army___z0rpikmEo---1--192.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 192, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=192)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,7->8,8->10,8->10,6')
        simHost.queue_player_moves_str(general.player, '9,4->8,4')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)
        self.assertPlayerTileCountGreater(simHost, general.player, 58)

    def test_should_perform_early_gather_to_tendrils__cramped(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_perform_early_gather_to_tendrils___SlFziucN6---0--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=50)
        self.assertIsNone(winner)
    
    def test_should_perform_early_gather_to_tendrils__open(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_perform_early_gather_to_tendrils__open___3HWW81zRD---1--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=False)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=50)
        self.assertIsNone(winner)

        self.assertGreater(playerMap.players[general.player].tileCount, 56)
    
    def test_should_not_blow_up(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_blow_up___EMfTbz1Ig---1--78.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 78, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=78)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=1)
        self.assertIsNone(winner)
    
    def test_should_not_launch_super_early_v1(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_super_early_v1___Sxz0Jeer6---1--121.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 121, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=121)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_launch_super_early_v2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_super_early_v1___Sxz0Jeer6---1--120.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 120, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=120)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)
    
    def test_should_not_take_ages_predicting_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_take_ages_predicting_expansion___rETyBtOqf---0--277.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 277, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=277)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertEqual(0, simHost.dropped_move_counts_by_player[general.player])
    
    def test_should_not_launch_on_inefficient_wasteful_capture_path(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_on_inefficient_wasteful_capture_path___TS0Bqk2B5---1--83.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 83, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=83)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        self.set_general_emergence_around(9, 17, simHost, general.player, enemyGeneral.player, emergenceAmt=30)
        playerMap = simHost.get_player_map(general.player)

        tileDiff = self.get_tile_differential(simHost, general.player, enemyGeneral.player)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertIsNone(winner)

        finalTileDiff = self.get_tile_differential(simHost, general.player, enemyGeneral.player)

        # we can do 13 by going immediately down with the 5 and the up right then up left from gen
        self.assertGreater(finalTileDiff-tileDiff, 12)

    def test_should_launch_when_no_other_options(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_launch_when_no_other_options___Na9JsoSCp---1--74.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 74, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=74)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_leafmoves(enemyGeneral.player)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=26)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 56)
    
    def test_should_not_bypass_launch_path_leaving_unused_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_bypass_launch_path_leaving_unused_tiles___-NIEW0it3---1--79.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 79, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=79)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = bot.get_timings()
        bot.timings.splitTurns = 19
        bot.timings.launchTiming = 28
        bot.completed_first_100 = False
        playerMap = simHost.get_player_map(general.player)

        tileDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=21)
        self.assertIsNone(winner)

        finalTileDiff = self.get_tile_differential(simHost)

        self.assertGreater(finalTileDiff - tileDiff, 21)

    def test_should_spend_rest_of_round_capturing_tiles_unless_threat_defense_immediately_necessary(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_spend_rest_of_round_capturing_tiles_unless_threat_defense_immediately_necessary___XvcaedBMu---0--233.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 233, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=233)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,9->12,9->12,10->12,11z->12,14->14,14->14,15  12,10->13,10->13,11z->13,13->14,13  13,10->14,10->14,8')
        # example good play
        # simHost.queue_player_moves_str(general.player, '12,10->10,10->10,9->9,9->9,8  14,17->14,16  16,17->16,16')

        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=17)
        self.assertIsNone(winner)

        diff = self.get_tile_differential(simHost)
        self.assertGreater(diff, 3, "should not lose entire advantage when can spend most of round safely capping tiles")
    
    def test_should_take_2_en_tiles_and_then_cap_one_behind_gen(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_take_2_en_tiles_and_then_cap_one_behind_gen___B_DQQI22q---0--93.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 93, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=93)
        self.reset_general(rawMap, enemyGeneral)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        initDiff = self.get_tile_differential(simHost)
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        finalDiff = self.get_tile_differential(simHost)

        self.assertEqual(5, finalDiff - initDiff, "should have capped two en tiles and then taken one behind general, wtf")

    def test_should_not_make_ineficient_interception_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_use_leaves_or_just_go_meet_army___XZ3WLBOYh---1--232.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 232, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=232)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,11->5,11->5,10->4,10->4,6->1,6  2,11->3,11->3,10  1,13->0,13->0,11')
        # proof of concept tile diff
        # simHost.queue_player_moves_str(general.player, '10,6->10,5->10,4->12,4  0,6->4,6  1,8->1,10->2,10->2,12  2,8->2,7->4,7->4,8  5,0->4,0  12,4->13,4')  # achieves +7
        # simHost.queue_player_moves_str(general.player, '10,5->10,4->12,4  5,0->4,0  0,6->4,6  2,8->2,7  0,7->0,6->2,6->2,7->3,7->4,7')  # achieves +7 as well
        # simHost.queue_player_moves_str(general.player, '0,7->0,6  0,5->0,6  5,0->4,0  10,4->11,4  0,6->4,6->4,7  1,8->2,8->2,7->4,7')  # achieves +8
        simHost.sim.ignore_illegal_moves = True
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=18)
        self.assertIsNone(winner)

        tileDiff = self.get_tile_differential(simHost)
        self.assertGreater(tileDiff, 6)
    
    def test_should_just_cap_tiles_not_switch_to_f25(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_just_cap_tiles_not_switch_to_f25___jsIvQ7xFx---0--95.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 95, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=95)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(-5, simHost)
    
    def test_should_pull_nearby_50_to_recap_many_tiles_in_row(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_pull_nearby_50_to_recap_many_tiles_in_row___F3sBBpuZL---1--285.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 285, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=285)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # simHost.queue_player_moves_str(general.player, '17,7->14,7->14,8->13,8->13,9->12,9->12,12->10,12->10,14->9,14')  # proof
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(10, simHost)
    
    def test_should_not_use_blocking_army_to_expand(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_use_blocking_army_to_expand__actual___o0Re_00zz---1--88.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 88, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_not_use_blocking_army_to_expand___o0Re_00zz---1--88.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=88)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '12,4->13,4  None  13,4->14,4->14,3->16,3->16,8')
        # proof
        simHost.queue_player_moves_str(general.player, '14,3->14,4  19,12->15,12')
        # simHost.queue_player_moves_str(general.player, '14,3->14,4  19,12->19,15->17,15->17,17->16,17->16,19->13,19')
        simHost.sim.ignore_illegal_moves = True
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=12)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(4, simHost)
    
    def test_should_more_correctly_estimate_captures_after_launch(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_more_correctly_estimate_captures_after_launch___6aWA3rCgP---1--229.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 229, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 15, 15)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=229)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=21)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(-8, simHost)
    
    def test_should_not_let_first50_plan_not_capture_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_let_first50_plan_not_capture_tiles___ae7MwH_nV---1--83.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 83, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=83)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
    
    def test_on_discover_should_not_let_first50_plan_not_capture_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_let_first50_plan_not_capture_tiles___ae7MwH_nV---1--82.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 82, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=82)
        for t in rawMap.players[enemyGeneral.player].tiles:
            t.reset_wrong_undiscovered_fog_guess()
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(16, simHost)
    
    def test_should_not_exp_launch_when_useless_at_end_of_round(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_exp_launch_when_useless_at_end_of_round___1dpEgVWD----0--147.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 147, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=147)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '16,14->17,14->17,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        self.assertEqual(50, playerMap.players[general.player].tileCount, "should have capped 2 tiles at end.")
    
    def test_should_not_launch_early(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_early___fCXeJcOTo---1--128.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 128, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=128)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertIsNone(winner)

        self.assertGreater(playerMap.GetTile(3, 11).army, 40)
    
    def test_should_not_find_no_expansion_weirdly__should_not_move_blocking_3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_find_no_expansion_weirdly___H7BosNYKZ---0--241.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=241)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,5->6,5->6,7->7,7->7,9  7,10->7,9  11,7->11,8->10,8')
        simHost.sim.ignore_illegal_moves = True
        # proof, does -8.
        # simHost.queue_player_moves_str(general.player, '8,3->9,3  7,0->8,0  2,0->1,0  2,1->1,1->1,2  8,11->9,11  9,6->9,8  7,1->8,1  2,13->1,13->1,14')
        # this semi-interception ALSO does -8
        # simHost.queue_player_moves_str(general.player, '2,6->2,7->5,7')

        # this is actually worse, -12
        # simHost.queue_player_moves_str(general.player, '2,6->2,5->4,5->4,7->6,7')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)
        self.assertTileDifferentialGreaterThan(-9, simHost)

    def test_should_not_delay_launches_when_opp_has_taken_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_delay_launches_when_opp_has_taken_tiles___IgikUItoa---1--126.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 126, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 10, 2)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=126)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=24)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(18, simHost)
        self.assertLess(general.army, 20)

    def test_should_attack_early_when_planning_attacks_into_alt_fog_paths(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attack_early_when_planning_attacks_into_alt_fog_paths___g-zTgcDhg---1--100.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 100, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.timings = None
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=20)
        self.assertIsNone(winner)

        self.assertLess(general.army, 10, 'should have launched with general army too')
        self.assertEqual(general.player, playerMap.GetTile(15, 16).player)

    def test_should_not_launch_enemy_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_launch_enemy_tiles___wMQvr_kVV---1--229.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 229, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=229)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '6,6->7,6')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=2)
        self.assertIsNone(winner)
        # would blow up if bug were reproing

        self.assertPlayerTileCountGreater(simHost, general.player, 72)
    
    def test_should_not_waste_moves_that_could_be_used_for_multi_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_waste_moves_that_could_be_used_for_multi_general___ugvxcq5TK---1--89.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 89, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=89)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        #proof, 42-34 (+8)
        # simHost.queue_player_moves_str(general.player, '14,9->13,9->13,8  17,5->15,5->15,6->11,6->11,7  17,5->17,8')
        #proof, 39-32 (+7)
        # simHost.queue_player_moves_str(general.player, '17,5->15,5->15,9->13,9->13,10->12,10  17,5->17,8')
        #proof, 41-33 (+8)
        # simHost.queue_player_moves_str(general.player, '14,9->14,10->13,10  17,5->15,5->15,8->13,8->13,9z  13,8->12,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=11)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(7, simHost)
    
    def test_should_not_waste_more_multi_general_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_waste_more_multi_general_moves___zlJdFHCdv---1--195.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 195, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=195)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        #proof
        # simHost.queue_player_moves_str(general.player, '7,13->7,11  7,13->7,15->9,15')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)
        self.assertTileDifferentialGreaterThan(0, simHost)
    
    def test_should_not_waste_more_multi_general_moves__or_open_up_enemy_caps(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_waste_more_multi_general_moves___zlJdFHCdv---1--191.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 191, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=191)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None  None  None  None  None  10,10->9,10')
        #proof, this simple approach achieves +5
        # simHost.queue_player_moves_str(general.player, '8,10->10,10  5,16->4,16  9,13->7,13->7,10')
        #proof, this VERY CALCULATED option manages to achieve +6, but it is convoluted
        # simHost.queue_player_moves_str(general.player, '8,10->10,10  6,11->7,11  9,13->7,13->7,9')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=9)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(4, simHost)
        with self.subTest(careLess=True):
            self.assertTileDifferentialGreaterThan(5, simHost, 'See convoluted proof above. +6 is POSSIBLE, though hard to calculate this. Heuristically, dont break up tile lines, instead see how much you can gather to the recapture line before end.')

    def test_should_not_expand_into_general__pre_split(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_dive_few_fog_tiles_when_cannot_kill__actual___Je4XxW4D9---1--76.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 76, fill_out_tiles=True)

        mapFile = 'GameContinuationEntries/should_not_dive_few_fog_tiles_when_cannot_kill___Je4XxW4D9---1--76.txtmap'
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=76)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,8->8,7z  8,8->12,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=6)
        self.assertIsNone(winner)
        self.assertOwned(general.player, playerMap.GetTile(6, 7), 'should expand away from general, not into it')
        self.assertOwned(general.player, playerMap.GetTile(5, 7), 'should expand away from general, not into it')
        self.assertOwned(general.player, playerMap.GetTile(4, 7), 'should expand away from general, not into it')
        self.assertOwned(general.player, playerMap.GetTile(4, 8), 'should expand away from general, not into it')
        self.assertOwned(general.player, playerMap.GetTile(4, 9), 'should expand away from general, not into it')

    def test_should_not_loop_on_greedy_expansion(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_loop_on_greedy_expansion___0Du9c3abI---0--156.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 156, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=156)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)

    def test_should_not_try_to_expand_with_potential_threat_blocking_tile(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_try_to_expand_with_potential_threat_blocking_tile___GHDkFXb1M---0--345.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 345, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=345)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,8->9,13->10,13->10,14->11,14->11,15->13,15->13,14->15,14->15,13')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=10)
        self.assertIsNone(winner)

        self.assertNoRepetition(simHost)
        self.assertTileDifferentialGreaterThan(-3, simHost, 'intercepting left and running downward results in -2 diff, whether we wait one turn on the intercept or not.')
    
    def test_should_not_prefer_intercept_when_can_just_tile_trade_while_ahead(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for enPath, proof in [
            ('12,5->11,5->11,6  19,5->19,6  11,6->12,6->12,7->11,7', '11,7->12,7->12,8z  12,7->12,6  12,8->16,8'),
            ('12,5->11,5->11,6->11,7->12,7->12,8', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
            ('12,5->8,5->8,10', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
            ('12,5->11,5->11,7->12,7->12,8->14,8', '11,7->12,7->12,8z  12,7->12,6->13,6->14,6'),
        ]:
            with self.subTest(enPath=enPath):
                mapFile = 'GameContinuationEntries/should_not_prefer_intercept_when_can_just_tile_trade_while_ahead___TooE-srNn---1--145.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 145, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=145)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, enPath)
                simHost.queue_player_moves_str(general.player, proof)
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=5)
                self.assertIsNone(winner)

                with self.subTest('main test'):
                    self.assertTileDifferentialGreaterThan(2, simHost, 'can easily get this just by going along the bottom path')
                with self.subTest('fancy'):
                    self.assertTileDifferentialGreaterThan(3, simHost, 'splitting on 12,7->12,8 guarantees only 1 missed enemy capture for rest of round. Thats harder to code for, though.')
    
    def test_should_maximize_expansion_when_cant_intercept(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        for path in [
            '9,5->8,5->8,6->9,6->9,7->4,7',
            '9,5->8,5->8,6->9,6->9,8->10,8->10,9',
            '9,5->6,5->6,0',
        ]:
            with self.subTest(path=path):
                mapFile = 'GameContinuationEntries/should_maximize_expansion_when_cant_intercept___TooE-srNn---1--343.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 343, fill_out_tiles=True)

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=343)

                self.enable_search_time_limits_and_disable_debug_asserts()
                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, path)
                # simHost.queue_player_moves_str(general.player, '4,8->8,8')
                bot = self.get_debug_render_bot(simHost, general.player)
                playerMap = simHost.get_player_map(general.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=7)
                self.assertIsNone(winner)

                self.assertTileDifferentialGreaterThan(1, simHost, 'can at worst achieve 1 tile diff by just taking neutrals rest of round')
    
    def test_should_not_leave_army_completely_unused_when_no_real_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_leave_army_completely_unused_when_no_real_threat___toc3VvzIE---1--442.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 442, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=442)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=8)
        self.assertIsNone(winner)

        self.assertTileDifferentialGreaterThan(9, simHost)

    def test_should_launch_full_army_if_launching__maximize_army_per_turn_caps__full_run(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_launch_full_army_if_launching,_maximize_army_per_turn_caps___Cq4LFDNyO---0--109.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 109, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=109)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # THIS IS ALL PROOF THAT THIS IS THE RIGHT CHOICE
        #proof ACTUALLY LAUNCH IS BAD LMAO, only gets 43
        # simHost.queue_player_moves_str(general.player, '0,19->2,19->2,18->4,18->4,17->8,17->8,16->11,16->11,15->13,15->13,18')
        # proof launch is bad, non-launch:
        # simHost.queue_player_moves_str(general.player, '2,19->2,18->4,18->4,17->8,17->8,16->11,16->11,15->13,15->13,18')  # force us not to find opponent, to make test consistent

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=41)
        self.assertNoFriendliesKilled(map, general)

        self.assertTileDifferentialGreaterThan(43, simHost, 'should spend the whole damn time capping tiles and pull from corner.')
        self.assertTileDifferentialGreaterThan(44, simHost, 'shouldnt move leafmove into the capture-path of the main push, wasting a move')

    def test_should_launch_full_army_if_launching__maximize_army_per_turn_caps(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_launch_full_army_if_launching,_maximize_army_per_turn_caps___Cq4LFDNyO---0--109.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 109, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=109)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # SEE PREVIOUS TEST FOR PROOF OF PLAN

        # really though, we should just have pulling the 2,19 tile out into the open as part of the expansion plan, and have a full plan.
        shouldMoveFirstTile = playerMap.GetTile(2, 19)
        self.begin_capturing_logging()
        # DebugHelper.IS_DEBUGGING = True
        move = bot.find_move()
        planOpts = SearchUtils.where(bot.expansion_plan.all_paths, lambda p: p.get_first_move().source == shouldMoveFirstTile)
        if len(planOpts) != 1:
            self.fail(f'found {len(planOpts)} plan options that started with the 2,19 tile.')

        plan = planOpts[0]
        nextMove = plan.get_first_move()
        self.assertEqual(playerMap.GetTile(2, 18), nextMove.dest)
        self.assertTrue(move.dest.player == -1 or move.source == shouldMoveFirstTile)
        self.assertGreater(plan.econValue / plan.length, 0.7)
        self.assertEqual(41, bot.expansion_plan.turns_used)

# 15f-23p-2s totally original
# 17f-21p RE 19-19 minus the self-tile-penalty
# 15f-23p-2s self-tile-penalty 0.2 instead of 0.5
# 16f-22p-2s with cutoff
# 17f-21p-2s no cutoff
# 14-24 with cutoff tweak
# 15-23 with revamp of including all paths from tile if any path from tile meets value per turn cutoff
# 13-25 ^ but rolled back early one?
# 25f 30p
# 28f 49p 2s ish, some are inconsistent, between 26 and 30f    
    def test_should_prefer_capping_central_tiles_over_edges_near_end_of_round(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_prefer_capping_central_tiles_over_edges_near_end_of_round___CqXBGqAAd---0--147.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 147, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=147)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=3)
        self.assertNoFriendliesKilled(map, general)

        self.assertOwned(general.player, playerMap.GetTile(9, 10), "should capture this central tile with a 2, no reason not to.")

        twoOf = [
            playerMap.GetTile(9, 12),
            playerMap.GetTile(10, 12),
            playerMap.GetTile(10, 13),
            playerMap.GetTile(11, 13),
        ]

        numCapped = SearchUtils.count(twoOf, lambda t: t.player == general.player)
        self.assertEqual(2, numCapped, f'should have captured two of {"  |  ".join([repr(t) for t in twoOf])}')
