import typing
from ExpandUtils import get_round_plan_with_expansion
from Interfaces import TilePlanInterface
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import Tile, MapBase


class ExpansionContinuationTests(TestBase):
    def run_expansion(
            self,
            map: MapBase,
            general: Tile,
            enemyGeneral: Tile,
            turns: int,
            negativeTiles: typing.Set[Tile],
            mapVision: MapBase | None,
            debugMode: bool = False,
    ) -> typing.Tuple[TilePlanInterface | None, typing.List[TilePlanInterface]]:
        targetPlayer = enemyGeneral.player

        # self.render_view_info(map, ViewInfo("h", map))
        # self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=mapVision, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.viewInfo.turnInc()

        self.begin_capturing_logging()
        self.enable_search_time_limits_and_disable_debug_asserts()
        plan = get_round_plan_with_expansion(
            bot._map,
            general.player,
            targetPlayer,
            turns,
            bot.board_analysis,
            territoryMap=bot.territories.territoryMap,
            tileIslands=bot.tileIslandBuilder,
            negativeTiles=negativeTiles,
            leafMoves=bot.leafMoves,
            # allowMultiPathReturn=True,
            forceNoGlobalVisited=False,
            viewInfo=bot.viewInfo
        )
        path = plan.selected_option
        otherPaths = plan.all_paths

        if debugMode:
            bot.prep_view_info_for_render()
            bot.viewInfo.add_info_line(f'max {str(path)}')
            for otherPath in otherPaths:
                bot.viewInfo.add_info_line(f'other {str(otherPath)}')

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

    def test_validate_expansion__70__6VUCSV74d(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__6VUCSV74d___6VUCSV74d---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70___xecfyk2z(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70___xecfyk2z___-xecfyk2z---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__nls8cnXsw___nls8cnXsw---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__u1VlLN9zB___u1VlLN9zB---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__dqxk_yUgh(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__dqxk_yUgh___dqxk-yUgh---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__Bf6qQtn9J(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__Bf6qQtn9J___Bf6qQtn9J---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__CtyQf3LFd___CtyQf3LFd---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__DfPncBCih(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__DfPncBCih___DfPncBCih---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__p3EGc7qPJ___p3EGc7qPJ---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__86fpHvxcf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__86fpHvxcf___86fpHvxcf---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__hadpjDGHG(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__hadpjDGHG___hadpjDGHG---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__xP1ct56px___xP1ct56px---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__C60XoJsYP___C60XoJsYP---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__3tCczBZAc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__3tCczBZAc___3tCczBZAc---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__clSe6d52C(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__clSe6d52C___clSe6d52C---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__n32rVGV8N(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__n32rVGV8N___n32rVGV8N---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__ehLAGG_AO(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__ehLAGG_AO___ehLAGG-AO---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__luRGzg19o___luRGzg19o---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__XZHq6JAQR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__XZHq6JAQR___XZHq6JAQR---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__0w0pGm4qa___0w0pGm4qa---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__tmhkvg0BM(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__tmhkvg0BM___tmhkvg0BM---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__BWmUz6UW6(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__BWmUz6UW6___BWmUz6UW6---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__vk2cIqiC3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__vk2cIqiC3___vk2cIqiC3---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__NF8xwDttC(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__NF8xwDttC___NF8xwDttC---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__3ilqVxvzF(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__3ilqVxvzF___3ilqVxvzF---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__bO9ac2krY(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__bO9ac2krY___bO9ac2krY---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__JsssU9idV(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__JsssU9idV___JsssU9idV---1--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__LoTkzTB0W___LoTkzTB0W---4--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__GebA0bdAT(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__GebA0bdAT___GebA0bdAT---3--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__UCAA7tDxS(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__UCAA7tDxS___UCAA7tDxS---7--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__9njYcfuZR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__9njYcfuZR___9njYcfuZR---3--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__32YTavdft(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__32YTavdft___32YTavdft---2--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__0CClHAmA0(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__0CClHAmA0___0CClHAmA0---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__5f70GpT1T(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__5f70GpT1T___5f70GpT1T---7--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__7Z_OkCAk3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__7Z_OkCAk3___7Z-OkCAk3---0--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__ZG3PGgtLk(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__ZG3PGgtLk___ZG3PGgtLk---5--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__GMpI5pzP4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__GMpI5pzP4___GMpI5pzP4---7--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__TagXHz0X4___TagXHz0X4---4--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion__70__4RWu5H5xH(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion__70__4RWu5H5xH___4RWu5H5xH---4--70.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 70, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=70)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=30, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175___xecfyk2z(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175___xecfyk2z___-xecfyk2z---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__nls8cnXsw___nls8cnXsw---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__u1VlLN9zB___u1VlLN9zB---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__Bf6qQtn9J(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__Bf6qQtn9J___Bf6qQtn9J---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__CtyQf3LFd___CtyQf3LFd---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__p3EGc7qPJ___p3EGc7qPJ---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__86fpHvxcf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__86fpHvxcf___86fpHvxcf---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__hadpjDGHG(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__hadpjDGHG___hadpjDGHG---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__xP1ct56px___xP1ct56px---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__C60XoJsYP___C60XoJsYP---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__3tCczBZAc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__3tCczBZAc___3tCczBZAc---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__luRGzg19o___luRGzg19o---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__XZHq6JAQR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__XZHq6JAQR___XZHq6JAQR---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__0w0pGm4qa___0w0pGm4qa---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__tmhkvg0BM(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__tmhkvg0BM___tmhkvg0BM---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__BWmUz6UW6(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__BWmUz6UW6___BWmUz6UW6---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__vk2cIqiC3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__vk2cIqiC3___vk2cIqiC3---1--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__LoTkzTB0W___LoTkzTB0W---4--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__GebA0bdAT(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__GebA0bdAT___GebA0bdAT---3--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__QxzyvHjfo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__QxzyvHjfo___QxzyvHjfo---5--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__32YTavdft(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__32YTavdft___32YTavdft---2--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__5f70GpT1T(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__5f70GpT1T___5f70GpT1T---7--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__7Z_OkCAk3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__7Z_OkCAk3___7Z-OkCAk3---0--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__GMpI5pzP4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__GMpI5pzP4___GMpI5pzP4---7--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_later__175__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_later__175__TagXHz0X4___TagXHz0X4---4--175.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 175, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=175)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240___xecfyk2z(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240___xecfyk2z___-xecfyk2z---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__nls8cnXsw___nls8cnXsw---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__u1VlLN9zB___u1VlLN9zB---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__Bf6qQtn9J(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__Bf6qQtn9J___Bf6qQtn9J---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__CtyQf3LFd___CtyQf3LFd---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__p3EGc7qPJ___p3EGc7qPJ---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__86fpHvxcf(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__86fpHvxcf___86fpHvxcf---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__xP1ct56px___xP1ct56px---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__C60XoJsYP___C60XoJsYP---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__3tCczBZAc(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__3tCczBZAc___3tCczBZAc---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__luRGzg19o___luRGzg19o---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__XZHq6JAQR(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__XZHq6JAQR___XZHq6JAQR---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__0w0pGm4qa___0w0pGm4qa---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__vk2cIqiC3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__vk2cIqiC3___vk2cIqiC3---1--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__LoTkzTB0W___LoTkzTB0W---4--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__QxzyvHjfo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__QxzyvHjfo___QxzyvHjfo---5--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__32YTavdft(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__32YTavdft___32YTavdft---2--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__5f70GpT1T(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__5f70GpT1T___5f70GpT1T---7--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__7Z_OkCAk3(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__7Z_OkCAk3___7Z-OkCAk3---0--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__GMpI5pzP4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__GMpI5pzP4___GMpI5pzP4---7--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_10_moves_remaining__240__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_10_moves_remaining__240__TagXHz0X4___TagXHz0X4---4--240.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 240, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=240)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=10, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__nls8cnXsw(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__nls8cnXsw___nls8cnXsw---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__u1VlLN9zB(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__u1VlLN9zB___u1VlLN9zB---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__CtyQf3LFd(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__CtyQf3LFd___CtyQf3LFd---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__p3EGc7qPJ(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__p3EGc7qPJ___p3EGc7qPJ---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__xP1ct56px(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__xP1ct56px___xP1ct56px---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__C60XoJsYP(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__C60XoJsYP___C60XoJsYP---1--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__luRGzg19o(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__luRGzg19o___luRGzg19o---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__0w0pGm4qa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__0w0pGm4qa___0w0pGm4qa---0--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__LoTkzTB0W(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__LoTkzTB0W___LoTkzTB0W---4--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__QxzyvHjfo(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__QxzyvHjfo___QxzyvHjfo---5--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)

    def test_validate_expansion_late_25_moves_remaining__375__TagXHz0X4(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/validate_expansion_late_25_moves_remaining__375__TagXHz0X4___TagXHz0X4---4--375.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 375, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=375)

        path, otherPaths = self.run_expansion(map, general, enemyGeneral, turns=25, negativeTiles=set(),
                                              mapVision=rawMap, debugMode=debugMode)
        self.assertIsNotNone(path)
