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
            allowMultiPathMultiDistReturn=True,
            forceNoGlobalVisited=False,
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

    def test__first_25_reroute__2_moves__should_find_2_tile_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
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
    def test_validate_expansion__70__6VUCSV74d(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__6VUCSV74d___6VUCSV74d---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70___xecfyk2z(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70___xecfyk2z___-xecfyk2z---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__nls8cnXsw___nls8cnXsw---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__u1VlLN9zB___u1VlLN9zB---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__dqxk_yUgh(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__dqxk_yUgh___dqxk-yUgh---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__Bf6qQtn9J(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__Bf6qQtn9J___Bf6qQtn9J---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__CtyQf3LFd___CtyQf3LFd---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__DfPncBCih(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__DfPncBCih___DfPncBCih---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__p3EGc7qPJ___p3EGc7qPJ---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__86fpHvxcf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__86fpHvxcf___86fpHvxcf---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__hadpjDGHG(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__hadpjDGHG___hadpjDGHG---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__xP1ct56px___xP1ct56px---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__C60XoJsYP___C60XoJsYP---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__3tCczBZAc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__3tCczBZAc___3tCczBZAc---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__clSe6d52C(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__clSe6d52C___clSe6d52C---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__n32rVGV8N(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__n32rVGV8N___n32rVGV8N---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__ehLAGG_AO(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__ehLAGG_AO___ehLAGG-AO---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__luRGzg19o___luRGzg19o---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__XZHq6JAQR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__XZHq6JAQR___XZHq6JAQR---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__0w0pGm4qa___0w0pGm4qa---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__tmhkvg0BM(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__tmhkvg0BM___tmhkvg0BM---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__BWmUz6UW6(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__BWmUz6UW6___BWmUz6UW6---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__vk2cIqiC3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__vk2cIqiC3___vk2cIqiC3---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__NF8xwDttC(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__NF8xwDttC___NF8xwDttC---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__3ilqVxvzF(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__3ilqVxvzF___3ilqVxvzF---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__bO9ac2krY(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__bO9ac2krY___bO9ac2krY---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__JsssU9idV(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__JsssU9idV___JsssU9idV---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__LoTkzTB0W___LoTkzTB0W---4--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__GebA0bdAT(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__GebA0bdAT___GebA0bdAT---3--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__UCAA7tDxS(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__UCAA7tDxS___UCAA7tDxS---7--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__9njYcfuZR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__9njYcfuZR___9njYcfuZR---3--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__32YTavdft(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__32YTavdft___32YTavdft---2--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__0CClHAmA0(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__0CClHAmA0___0CClHAmA0---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__5f70GpT1T(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__5f70GpT1T___5f70GpT1T---7--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__7Z_OkCAk3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__7Z_OkCAk3___7Z-OkCAk3---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__ZG3PGgtLk(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__ZG3PGgtLk___ZG3PGgtLk---5--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__GMpI5pzP4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__GMpI5pzP4___GMpI5pzP4---7--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__TagXHz0X4___TagXHz0X4---4--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion__70__4RWu5H5xH(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__4RWu5H5xH___4RWu5H5xH---4--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175___xecfyk2z(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175___xecfyk2z___-xecfyk2z---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__nls8cnXsw___nls8cnXsw---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__u1VlLN9zB___u1VlLN9zB---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__Bf6qQtn9J(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__Bf6qQtn9J___Bf6qQtn9J---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__CtyQf3LFd___CtyQf3LFd---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__p3EGc7qPJ___p3EGc7qPJ---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__86fpHvxcf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__86fpHvxcf___86fpHvxcf---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__hadpjDGHG(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__hadpjDGHG___hadpjDGHG---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__xP1ct56px___xP1ct56px---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__C60XoJsYP___C60XoJsYP---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__3tCczBZAc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__3tCczBZAc___3tCczBZAc---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__luRGzg19o___luRGzg19o---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__XZHq6JAQR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__XZHq6JAQR___XZHq6JAQR---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__0w0pGm4qa___0w0pGm4qa---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__tmhkvg0BM(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__tmhkvg0BM___tmhkvg0BM---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__BWmUz6UW6(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__BWmUz6UW6___BWmUz6UW6---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__vk2cIqiC3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__vk2cIqiC3___vk2cIqiC3---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__LoTkzTB0W___LoTkzTB0W---4--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__GebA0bdAT(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__GebA0bdAT___GebA0bdAT---3--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__QxzyvHjfo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__QxzyvHjfo___QxzyvHjfo---5--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__32YTavdft(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__32YTavdft___32YTavdft---2--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__5f70GpT1T(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__5f70GpT1T___5f70GpT1T---7--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__7Z_OkCAk3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__7Z_OkCAk3___7Z-OkCAk3---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__GMpI5pzP4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__GMpI5pzP4___GMpI5pzP4---7--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_later__175__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__TagXHz0X4___TagXHz0X4---4--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240___xecfyk2z(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240___xecfyk2z___-xecfyk2z---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__nls8cnXsw___nls8cnXsw---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__u1VlLN9zB___u1VlLN9zB---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__Bf6qQtn9J(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__Bf6qQtn9J___Bf6qQtn9J---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__CtyQf3LFd___CtyQf3LFd---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__p3EGc7qPJ___p3EGc7qPJ---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__86fpHvxcf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__86fpHvxcf___86fpHvxcf---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__xP1ct56px___xP1ct56px---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__C60XoJsYP___C60XoJsYP---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__3tCczBZAc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__3tCczBZAc___3tCczBZAc---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__luRGzg19o___luRGzg19o---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__XZHq6JAQR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__XZHq6JAQR___XZHq6JAQR---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__0w0pGm4qa___0w0pGm4qa---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__vk2cIqiC3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__vk2cIqiC3___vk2cIqiC3---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__LoTkzTB0W___LoTkzTB0W---4--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__QxzyvHjfo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__QxzyvHjfo___QxzyvHjfo---5--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__32YTavdft(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__32YTavdft___32YTavdft---2--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__5f70GpT1T(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__5f70GpT1T___5f70GpT1T---7--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__7Z_OkCAk3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__7Z_OkCAk3___7Z-OkCAk3---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__GMpI5pzP4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__GMpI5pzP4___GMpI5pzP4---7--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_10_moves_remaining__240__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__TagXHz0X4___TagXHz0X4---4--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__nls8cnXsw___nls8cnXsw---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__u1VlLN9zB___u1VlLN9zB---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__CtyQf3LFd___CtyQf3LFd---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__p3EGc7qPJ___p3EGc7qPJ---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__xP1ct56px___xP1ct56px---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__C60XoJsYP___C60XoJsYP---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__luRGzg19o___luRGzg19o---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__0w0pGm4qa___0w0pGm4qa---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__LoTkzTB0W___LoTkzTB0W---4--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
    
    def test_validate_expansion_late_25_moves_remaining__375__QxzyvHjfo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__QxzyvHjfo___QxzyvHjfo---5--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__TagXHz0X4___TagXHz0X4---4--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(), mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

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
bot_player_index=0
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
bot_player_index=0
bot_target_player=1   
"""
        # 2 in 3 moves
        # 4 in 5 moves
        # gen has 13 army so then 12 more in 12 moves for 16 in 17 moves

        remainingTurns = 17
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

        self.assertTilesCaptured(general.player, path, otherPaths, enemyAmount=4, neutralAmount=12)

        # should not move the general first
        self.assertNotEqual(general, path.start.tile)

    def test_should_not_launch_attack_at_suboptimal_time(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        if debugMode:
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=11)
            self.assertIsNone(winner)

            self.assertEqual(36, simHost.get_player_map(general.player).players[general.player].tileCount)
            self.fail('cant actually run this test in debug mode, this is just to observe')

        simHost.run_sim(run_real_time=False, turns=1)
        simHost.assert_last_move(general.player, None)

        simHost.run_sim(run_real_time=False, turns=1)
        simHost.assert_last_move(general.player, None)

    def test_should_expand_away_from_general(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        if debugMode:
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=15)
            self.assertIsNone(winner)
            self.fail('cant actually run this test in debug mode, this is just to observe')

        simHost.run_sim(run_real_time=False, turns=1)
        simHost.assert_last_move(general.player, None)

        simHost.run_sim(run_real_time=False, turns=1)
        simHost.assert_last_move(general.player, None)

        simHost.run_sim(run_real_time=False, turns=9)
        self.assertEqual(36, simHost.sim.sim_map.players[general.player].tileCount)
    
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
