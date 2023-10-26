import typing
from ExpandUtils import get_optimal_expansion
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase

class ExpansionTests(TestBase):

    def run_expansion(
            self,
            map: MapBase,
            general: Tile,
            enemyGeneral: Tile,
            turns: int,
            negativeTiles: typing.Set[Tile],
            mapVision: MapBase | None,
            debugMode: bool = False,
    ) -> typing.Tuple[Path | None, typing.List[Path]]:
        targetPlayer = enemyGeneral.player

        # self.render_view_info(map, ViewInfo("h", map.cols, map.rows))
        # self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=mapVision, allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)
        bot.viewInfo.turnInc()

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        path, otherPaths = get_optimal_expansion(
            bot._map,
            general.player,
            targetPlayer,
            turns,
            bot.board_analysis,
            territoryMap=bot.territories.territoryMap,
            negativeTiles=negativeTiles,
            leafMoves=bot.leafMoves,
            # allowMultiPathReturn=True,
            useIterativeNegTiles=bot.expansion_use_iterative_negative_tiles,
            forceNoGlobalVisited=bot.expansion_force_no_global_visited,
            allowMultiPathMultiDistReturn=bot.expansion_use_multi_per_dist_per_tile,
            lengthWeightOffset=bot.expansion_length_weight_offset,
            useCutoff=bot.expansion_use_cutoff,
            useLeafMovesFirst=bot.expansion_use_leaf_moves_first,
            viewInfo=bot.viewInfo
        )

        if debugMode:
            bot.prep_view_info_for_render()
            bot.viewInfo.addAdditionalInfoLine(f'max {str(path)}')
            for otherPath in otherPaths:
                bot.viewInfo.addAdditionalInfoLine(f'other {str(otherPath)}')

            self.render_view_info(bot._map, viewInfo=bot.viewInfo)

        return path, otherPaths

    def assertTilesCaptured(
            self,
            searchingPlayer: int,
            firstPath: Path,
            otherPaths: typing.List[Path],
            enemyAmount: int,
            neutralAmount: int = 0,
            assertNoDuplicates: bool = True):
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
                        failures.append(f'tile path {str(path.start.tile)} had duplicate from other path {str(tile)}')
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
            firstPath: Path,
            otherPaths: typing.List[Path],
            enemyAmount: int,
            neutralAmount: int = 0,
            assertNoDuplicates: bool = True):
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
                        failures.append(f'tile path {str(path.start.tile)} had duplicate from other path {str(tile)}')
                    continue
                visited.add(tile)
                if tile.player != searchingPlayer:
                    if tile.isNeutral:
                        neutralCapped += 1
                    else:
                        enemyCapped += 1

        if neutralCapped > neutralAmount:
            failures.append(f'Expected at least {neutralAmount} neutral capped, instead found {neutralCapped}')
        if enemyCapped > enemyAmount:
            failures.append(f'Expected at least {enemyAmount} enemy capped, instead found {enemyCapped}')

        if len(failures) > 0:
            self.fail("Path captures didn't match expected:\r\n  " + "\r\n  ".join(failures))

    def test__first_25_reroute__2_moves__should_find_2_tile_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = f'ExpandUtilsTestMaps/did_not_find_2_move_cap__turn34'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn=34, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=245)
        negTiles = set()
        negTiles.add(general)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=2, negativeTiles=negTiles, mapVision=rawMap, debugMode=debugMode)
        # should go 5,9 -> 5,10 -> 4,10
        self.assertIsNotNone(path)
        self.assertEquals(path.length, 2)
        self.assertEquals(path.start.tile, map.GetTile(5, 9))
        self.assertEquals(path.start.next.tile, map.GetTile(5, 10))
        self.assertEquals(path.start.next.next.tile, map.GetTile(4, 10))

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
a1   a1   a1   a1   a1                                 b1
a1   a1   a1   aG1 
     a5   a1   a1   
     a1   a1   a1   
     b1
     b1      
       
      
                                                       bG50
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
            enemyGeneral,
            turns=remainingTurns,
            negativeTiles=set(),
            mapVision=map,
            debugMode=debugMode)

        self.assertIsNotNone(path)

        self.assertTilesCaptured(general.player, path, otherPaths, enemyAmount=4, neutralAmount=1)  #

        # should not move the general first
        self.assertNotEqual(general, path.start.tile)

    def test_validate_expansion__calculates_city_expansion_correctly(self):
        # TODO expansion doesn't take city increment into account currently so this test will never pass until that is implemented.
        rawMapData = """
|    |    |    |    |    |    |    |    |    |    |    |   
a8   a1   a1   a2   a1   a2   a2   a2   a2   a1   a1   a5  
a1   a1   a1   a1   a1   a1   a1   a1   a1             b1
a1   a1   a1   a1   a1                                 b1
a1   a1   a1   aG11 
     a5   a1   a1   
     a1   a1   a1   
     b1
     b1      
       
      
                                                       bG50
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

        path, otherPaths = self.run_expansion(
            map,
            general,
            enemyGeneral,
            turns=remainingTurns,
            negativeTiles=set(),
            mapVision=map,
            debugMode=debugMode)

        with self.subTest(careLess=False):

            self.assertIsNotNone(path)
            self.assertMinTilesCaptured(general.player, path, otherPaths, enemyAmount=4, neutralAmount=11)

            # should not move the general first
            self.assertNotEqual(general, path.start.tile)

        with self.subTest(careLess=True):
            self.assertTilesCaptured(general.player, path, otherPaths, enemyAmount=4, neutralAmount=12)

    def test_should_not_launch_attack_at_suboptimal_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_launch_attack_at_suboptimal_time___uClPcbQ7W---1--89.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 89, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=89)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
        bot.expansion_use_cutoff = False
        # bot.expansion_use_leaf_moves_first = True
        simHost.queue_player_moves_str(enemyGeneral.player, '7,6->7,5->7,4  9,6->10,6->11,6->11,5')

        # achieves 51 (12 diff)
        # simHost.queue_player_moves_str(general.player, '12,12->12,11->12,10->12,9->11,9->10,9->10,8->9,8->9,7->9,6->8,6->7,6->6,6  17,12->17,11  18,12->18,11  5,12->5,13->5,14')

        # achieves 13 diff
        # simHost.queue_player_moves_str(general.player, '6,12->5,12->5,13->5,14  17,12->17,11  18,12->18,11  12,12->12,11->13,11->14,11')

        # achieves 14 diff
        # simHost.queue_player_moves_str(general.player, '5,12->5,13->5,14  17,12->17,11  18,12->18,11  12,12->12,11->13,11->14,11')

        bot.timings.launchTiming = 30
        bot.timings.splitTurns = 30

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        # beginning at 67 tiles, 14 moves, 8 on general

        # instantly rallying general at 9,7->9,6 yields 51 tiles after neutral expands

        # alternatively
        # 3 in 4 by pushing out the 6,12 2+3, thats 70@10t

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=14)
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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=11)
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
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=20)
        self.assertIsNone(winner)

        self.assertPlayerTileCountGreater(simHost, general.player, 48)
    
    def test_should_finish_expanding_with_army_already_near_leaves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_finish_expanding_with_army_already_near_leaves___emFpDYTkm---0--96.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 96, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=96)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=4)
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
        bot = simHost.get_bot(general.player)
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
        self.assertEqual(finalTileDiff - initDifferential, 12, "should be able to eek this much differential out of this AT LEAST. Change the assert if greater is found.")

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
        bot = simHost.get_bot(general.player)
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
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_expand_into_neutral_city_wtf
    
    def test_should_just_fucking_capture_tiles_not_dance_back_and_forth_wasting_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_just_fucking_capture_tiles_not_dance_back_and_forth_wasting_moves___KyRTYaDCf---2--87.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 87, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=87)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,6->7,5')
        simHost.queue_player_moves_str(enemyAllyGen.player, '7,6->7,5')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=13)
        self.assertNoFriendliesKilled(map, general, allyGen)

    
    def test_should_not_run_down_into_non_enemy_territory_with_kill_threat_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_run_down_into_non_enemy_territory_with_kill_threat_army___m31icdCyc---1--344.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 344, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=344)
        
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = simHost.get_bot(general.player)
        playerMap = simHost.get_player_map(general.player)

        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

        self.fail("TODO add asserts for should_not_run_down_into_non_enemy_territory_with_kill_threat_army")
