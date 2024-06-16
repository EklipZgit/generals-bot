import time
import typing

import SearchUtils
from ExpandUtils import get_round_plan_with_expansion
from Interfaces import TilePlanInterface
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot


class ExpansionLegacyUnitTests(TestBase):
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
        #
        # path = filter(lambda p: p.start.tile == map.GetTile(0, 0), otherPaths)[0]

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
