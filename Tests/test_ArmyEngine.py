import logging
import time
import traceback
import typing

import SearchUtils
from ArmyEngine import ArmyEngine, ArmySimResult
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Engine.ArmyEngineModels import calc_value_int, calc_econ_value, ArmySimState
from MctsLudii import MctsDUCT, MoveSelectionFunction
from Sim.GameSimulator import GameSimulatorHost, GameSimulator
from TestBase import TestBase
from base.client.map import Tile, MapBase
from bot_ek0x45 import EklipZBot


class ArmyEngineTests(TestBase):
    def render_step_engine_analysis(
            self,
            engine: ArmyEngine,
            sim: GameSimulator,
            result: ArmySimResult,
            armyA: Army,
            armyB: Army
    ):
        aTile = armyA.tile
        bTile = armyB.tile
        genPlayer = aTile.player
        enemyPlayer = bTile.player
        map = sim.players[genPlayer].map
        engine.map = map
        self.render_sim_analysis(map, result)
        if result.best_result_state.depth > 0:
            frMove, enMove = result.expected_best_moves[0]
            if frMove is not None:
                sim.make_move(map.player_index, frMove)
                aTile = frMove.dest
            if enMove is not None:
                sim.make_move((map.player_index + 1) & 1, enMove)
                bTile = enMove.dest

            sim.execute_turn(dont_require_all_players_to_move=True)

            simA = sim.sim_map.GetTile(aTile.x, aTile.y)
            simB = sim.sim_map.GetTile(bTile.x, bTile.y)
            if simA.player == genPlayer:
                armyA = Army(map.GetTile(aTile.x, aTile.y))
            else:
                armyA = None
            if simB.player == enemyPlayer:
                armyB = Army(map.GetTile(bTile.x, bTile.y))
            else:
                armyB = None

            if armyA is not None and armyB is not None:
                engine.friendly_armies = [armyA]
                engine.enemy_armies = [armyB]
                engine.log_payoff_depth = 1
                nextResult = engine.scan(result.best_result_state.depth - 1, mcts=True)
                self.render_step_engine_analysis(engine, sim, nextResult, armyA, armyB)
            else:
                # this is the last thing we do before we return
                self.render_sim_analysis(map, result)

    def test_brute_force__armies_suicide(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        rawMap = """
|    |    |    |    |    
          aG1          
                    
                    
                    
     a25               
               b25     
                    
                    
                    
          bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
                # Both should have half the board if this gens correctly..
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)
                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.time_limit = 100000000000000.0
                armyEngine.iteration_limit = 1000
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                armyEngine.allow_friendly_no_op = True
                armyEngine.allow_enemy_no_op = True
                result = armyEngine.scan(4, mcts=True)
                if debugMode:
                    sim = GameSimulator(map_raw=map, ignore_illegal_moves=True)
                    sim.players[general.player].set_map_vision(map)
                    # self.render_sim_analysis(map, result)
                    self.render_step_engine_analysis(armyEngine, sim, result, aArmy, bArmy)

                # this should be +2 / -2 if we're considering no-op moves to be worth 1 economy, otherwise this is +1 -1
                #  as priority player goes towards other end of board capping tile towards king and other player must chase sideways
                if MapBase.player_has_priority(general.player, turn):
                    self.assertEqual(-2, result.best_result_state.tile_differential)
                else:
                    self.assertEqual(2, result.best_result_state.tile_differential)

                self.assertEqual(0, result.best_result_state.city_differential)
                self.assertGreater(len(result.expected_best_moves), 1)

    def test_brute_force__recognizes_general_race_winner__by_priority(self):
        rawMap = """
|    |    |    |    |    |
     M    aG1  M        
     M         M           
     M         M           
     M         M           
     M    b25  M
     M         M     
     M    a25  M        
     M         M           
     M         M           
     M         M           
     M    bG1  M        
|    |    |    |    |    |
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()

        for shortCircuit in [False, True]:
            for turn in [0, 1]:
                with self.subTest(turn=turn, shortCircuit=shortCircuit):
                    map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                    self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                    self.begin_capturing_logging()
                    aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                    boardAnalysis = BoardAnalyzer(map, general)
                    boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                    mcts: MctsDUCT = MctsDUCT()
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                    armyEngine.friendly_has_kill_threat = shortCircuit
                    armyEngine.enemy_has_kill_threat = shortCircuit
                    result = armyEngine.scan(5, mcts=True)
                    if debugMode:
                        self.render_sim_analysis(map, result)
                    # whoever has priority this turn should also have priority in 4 moves, which is when the king kill would happen
                    if not MapBase.player_has_priority(general.player, map.turn):
                        self.assertTrue(result.best_result_state.captures_enemy)
                        self.assertFalse(result.best_result_state.captured_by_enemy)
                    else:
                        self.assertFalse(result.best_result_state.captures_enemy)
                        self.assertTrue(result.best_result_state.captured_by_enemy)

    def test_brute_force__recognizes_general_race_winner__by_priority__forced(self):
        rawMap = """
|    |    |    |    |    |
     M    aG1  M        
     M         M           
     M         M           
     M         M           
     M    b25  M
     M         M     
     M    a25  M        
     M         M           
     M         M           
     M         M           
     M    bG1  M        
|    |    |    |    |    |
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                result = armyEngine.scan(5, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # whoever has priority this turn should also have priority in 4 moves, which is when the king kill would happen
                if not MapBase.player_has_priority(general.player, map.turn):
                    self.assertTrue(result.best_result_state.captures_enemy)
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                else:
                    self.assertFalse(result.best_result_state.captures_enemy)
                    self.assertTrue(result.best_result_state.captured_by_enemy)

    def test_brute_force__recognizes_general_race_winner__by_priority__odd_distance(self):
        rawMap = """
|    |    |    |    |    |
          aG1          


          b25

          a25          


          bG1          
|    |    |    |    |    |
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()

        for shortCircuit in [False, True]:
            for turn in [1, 0]:
                with self.subTest(turn=turn, shortCircuit=shortCircuit):
                    map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                    self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)
                    self.begin_capturing_logging()
                    aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                    boardAnalysis = BoardAnalyzer(map, general)
                    boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                    mcts: MctsDUCT = MctsDUCT()
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                    armyEngine.friendly_has_kill_threat = shortCircuit
                    armyEngine.enemy_has_kill_threat = shortCircuit
                    armyEngine.log_payoff_depth = 3
                    result = armyEngine.scan(4, mcts=True)
                    if debugMode:
                        self.render_sim_analysis(map, result)
                    # whoever has priority this turn should NOT have priority in 5 moves, which is when the king kill would happen
                    if MapBase.player_has_priority(general.player, map.turn):
                        self.assertTrue(result.best_result_state.captures_enemy)
                        self.assertFalse(result.best_result_state.captured_by_enemy)
                    else:
                        self.assertFalse(result.best_result_state.captures_enemy)
                        self.assertTrue(result.best_result_state.captured_by_enemy)

    def test_brute_force__recognizes_general_race_winner__by_priority__odd_distance__misbehaving(self):
        rawMap = """
|    |    |    |    |    |
          aG1          


          b25

          a25          


          bG1          
|    |    |    |    |    |
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()
        turn = 1
        shortCircuit = False

        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)
        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
        armyEngine.friendly_has_kill_threat = shortCircuit
        armyEngine.enemy_has_kill_threat = shortCircuit
        armyEngine.log_payoff_depth = 3
        result = armyEngine.scan(4, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        # whoever has priority this turn should NOT have priority in 5 moves, which is when the king kill would happen
        if MapBase.player_has_priority(general.player, map.turn):
            self.assertTrue(result.best_result_state.captures_enemy)
            self.assertFalse(result.best_result_state.captured_by_enemy)
        else:
            self.assertFalse(result.best_result_state.captures_enemy)
            self.assertTrue(result.best_result_state.captured_by_enemy)

    def test_brute_force__recognizes_general_race_winner__by_priority__odd_distance__forced(self):
        rawMap = """
|    |    |    |    |    |
     M    aG1  M        
     M         M           
     M         M           
     M    b25  M    
     M         M        
     M    a25  M          
     M         M           
     M         M           
     M    bG1  M        
|    |    |    |    |    |
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()

        for shortCircuit in [False, True]:
            for turn in [0, 1]:
                with self.subTest(turn=turn, shortCircuit=shortCircuit):
                    map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                    self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)
                    self.begin_capturing_logging()
                    aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                    boardAnalysis = BoardAnalyzer(map, general)
                    boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                    mcts: MctsDUCT = MctsDUCT()
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                    armyEngine.friendly_has_kill_threat = shortCircuit
                    armyEngine.enemy_has_kill_threat = shortCircuit
                    result = armyEngine.scan(5, mcts=True)
                    if debugMode:
                        self.render_sim_analysis(map, result)
                    # whoever has priority this turn should NOT have priority in 5 moves, which is when the king kill would happen
                    if MapBase.player_has_priority(general.player, map.turn):
                        self.assertTrue(result.best_result_state.captures_enemy)
                        self.assertFalse(result.best_result_state.captured_by_enemy)
                    else:
                        self.assertFalse(result.best_result_state.captures_enemy)
                        self.assertTrue(result.best_result_state.captured_by_enemy)

    def test_brute_force__a_can_cap_b_tiles_with_kill_threat(self):
        rawMap = """
|    |    |    |    |    
          aG1          
                    
     M               
                    b1
                
                    
                    
                    
a25  M    b25          
          bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        for turn in [1, 0]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(5, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

    def test_brute_force__detects_running_from_scrim_is_good(self):
        rawMap = """
|    |    |    |    |    
          aG10          
     M    M    M    M
     M          
                    
                   
               a1   a1
                    a1
          b20       a20


a1
a1                
a1        bG17          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
                # Both should have half the board if this generates correctly..
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=25)
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                # armyEngine.friendly_has_kill_threat = True
                # armyEngine.enemy_has_kill_threat = False
                # baseState = armyEngine.get_base_board_state()
                # self.assertEqual(0, baseState.tile_differential)
                # self.assertEqual(0, baseState.city_differential)

                armyEngine.iteration_limit = 1000
                armyEngine.time_limit = 1000
                result = armyEngine.scan(5, logEvals=False, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)

                self.assertGreater(result.best_result_state.tile_differential, 0)
                self.assertEqual(0, result.best_result_state.city_differential)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)
                for aMove, bMove in result.expected_best_moves:
                    self.assertIsNotNone(aMove)
                    self.assertIsNotNone(bMove)

    def test_brute_force__doesnt_blow_up_on_1_army_armies(self):
        rawMap = """
|    |    |    |    |    
          aG10          
     M    M    M    M
     M          


               a1   a1
                    a1
          b20       a20


a1
a1                
a1        bG20          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this generates correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=25)

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)
                # make B's army be a 1-tile
                bArmy = Army(map.GetTile(3,9))

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(4, logEvals=False, mcts=True)
                armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
                if debugMode:
                    self.render_sim_analysis(map, result)

                self.assertGreater(result.best_result_state.tile_differential, 0)
                self.assertEqual(0, result.best_result_state.city_differential)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)
                for aMove, bMove in result.expected_best_moves:
                    self.assertIsNotNone(aMove)
                    self.assertIsNone(bMove)

    def test_brute_force__detects_running_from_scrim_is_good_DEBUG(self):
        rawMap = """
|    |    |    |    |    
          aG10          
     M    M    M    M
     M          


          M    a1   a1
                    a1
     M    b20       a20
     M         M 
     M         M                 
     M         M   
     M         M   
b1   M    bG20 M    a1     
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=25)

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                # armyEngine.friendly_has_kill_threat = True
                # armyEngine.enemy_has_kill_threat = True
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(5, logEvals=False, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)
                self.assertIsNotNone(result.expected_best_moves[0][0], "red should cap tiles")
                self.assertEqual(3, result.net_economy_differential, "red should cap tiles")

    def test_brute_force__detects_basic_forced_move__and_waits_to_react_with_priority(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1



     M         
     b25  M        
a25       bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = False
                armyEngine.allow_enemy_no_op = True
                armyEngine.allow_friendly_no_op = True
                armyEngine.repetition_threshold = 3
                armyEngine.log_payoff_depth = 2
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(4, logEvals=True, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                if not MapBase.player_had_priority(enemyGen.player, turn):
                    # B should just wait to see what A does this turn, as he'll have priority next turn.
                    self.assertIsNone(result.expected_best_moves[0][1])
                else:
                    # B must assume A will attack and block
                    self.assertEqual(map.GetTile(1, 12), result.expected_best_moves[0][1].dest)

                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

    def test_brute_force__detects_basic_forced_move__can_only_move_towards_gen(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1



     M         
     b25  M        
a25       bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
                # Both should have half the board if this gens correctly..
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                armyEngine.force_friendly_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [enemyGen])
                armyEngine.allow_friendly_no_op = False
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(3, logEvals=True, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)

                # b must assume a will attack and block
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

    def test_brute_force__detects_chase_save(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1

          M
     M    b25  M
     M    a25  M   
     M         M 
          bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
                # Both should have half the board if this gens correctly..
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(2, logEvals=True, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)

                # b should catch a, always. a should force b to chase only on the turn where he gets priority
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)
                self.assertTrue(result.best_result_state.kills_all_friendly_armies)
                self.assertTrue(result.best_result_state.kills_all_enemy_armies)

    def test_brute_force__detects_wins_on_priority(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1


     M         M 
     M    b25  M
     M    a25  M   
          bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(2, logEvals=True, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)

                if MapBase.player_has_priority(general.player, turn):
                    # then has priority next turn
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                    self.assertTrue(result.best_result_state.captures_enemy)
                    self.assertFalse(result.best_result_state.kills_all_friendly_armies)
                    self.assertFalse(result.best_result_state.kills_all_enemy_armies)
                else:
                    # then doesn't have priority next turn
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                    self.assertFalse(result.best_result_state.captures_enemy)
                    self.assertTrue(result.best_result_state.kills_all_friendly_armies)
                    self.assertTrue(result.best_result_state.kills_all_enemy_armies)

    def test_engine_should_intercept_army_not_threat_killer_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/engine_should_intercept_army_not_threat_killer_move___YcpRMr0HG---0--233.txtmap'
        turn = 233
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, turn, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGeneral)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGeneral)

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
        armyEngine.friendly_has_kill_threat = True
        armyEngine.enemy_has_kill_threat = True

        result = armyEngine.scan(2, logEvals=False, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)



    def test_does_not_over_recognize_losses_on_general_distances(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/does_not_fail_defense___BgVc48Chn---b--792.txtmap'

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                map, general, enemyGen = self.load_map_and_generals(mapFile, 792 + turn)
                self.begin_capturing_logging()
                blocked = map.GetTile(14, 1)
                map.convert_tile_to_mountain(blocked)

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapFile, 792 + turn)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
                simHost.queue_player_moves_str(enemyGen.player, '15,6->16,6->16,5->16,4->16,3->16,2->16,1->15,1')

                eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                for i in range(8):
                    mcts: MctsDUCT = MctsDUCT()
                    aArmies = eklipz_bot.find_large_tiles_near(
                        fromTiles=[
                            self.get_player_tile(15, 1, simHost.sim, general.player),
                            self.get_player_tile(15, 6, simHost.sim, general.player),
                            self.get_player_tile(12, 4, simHost.sim, general.player),
                        ],
                        forPlayer=general.player,
                        limit=1,
                        distance=5
                    )
                    bArmies = eklipz_bot.find_large_tiles_near(
                        fromTiles=[
                            self.get_player_tile(15, 1, simHost.sim, general.player),
                            self.get_player_tile(15, 6, simHost.sim, general.player),
                            self.get_player_tile(12, 4, simHost.sim, general.player),
                        ],
                        forPlayer=enemyGen.player,
                        limit=1,
                        distance=5
                    )
                    if len(bArmies) == 0:
                        break
                    armyEngine = ArmyEngine(map, [Army(t) for t in aArmies], [Army(t) for t in bArmies], boardAnalysis, mctsRunner=mcts)
                    armyEngine.friendly_has_kill_threat = False
                    armyEngine.enemy_has_kill_threat = True
                    # armyEngine.time_limit = 0.05
                    # armyEngine.time_limit = 2.0
                    armyEngine.iteration_limit = 1000
                    armyEngine.time_limit = 100
                    result = armyEngine.scan(4, mcts=True)
                    if debugMode:
                        self.render_sim_analysis(map, result)
                    # b can make a run safely for a's general, but a has time to capture b if b does that. Neither caps each other.
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                    self.assertFalse(result.best_result_state.captures_enemy)
                    simHost.queue_player_move(general.player, result.expected_best_moves[0][0])
                    winner = simHost.run_sim(run_real_time=False, turn_time=5, turns=1)
                    self.assertIsNone(winner)

    def test_brute_force__does_not_over_recognize_wins_on_general_distances(self):
        rawMap = """
|    |    |    |    |    
          aG1             


          
a24
          b25


              
          bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        # self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                result = armyEngine.scan(4, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that. Neither caps each other.
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

    def test_brute_force__recognizes_losses_on_general_distances(self):
        rawMap = """
|    |    |    |    |    
     bG1               



          b25       a25
                 

     
M              
          aG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                result = armyEngine.scan(2, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertTrue(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

    def test_brute_force__a_can_cap_b_tiles_with_kill_threat__v2(self):
        rawMap = """
|    |    |    |    |    
          aG1     
                    
               M     
                    
                    
                    
                    
                   
a25  M              
     bG1  b25      
|    |    |    |    | 
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                self.begin_capturing_logging()
                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = False
                armyEngine.allow_enemy_no_op = True
                armyEngine.allow_friendly_no_op = True
                armyEngine.log_payoff_depth = 1
                armyEngine.time_limit = 1000.0
                armyEngine.iteration_limit = 1000
                result = armyEngine.scan(5, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                if MapBase.player_has_priority(enemyGen.player, turn):
                    # B must assume A will attack and block, because A will have priority next turn.
                    self.assertIsNotNone(result.expected_best_moves[0][1])
                    self.assertEqual(map.GetTile(1, 9), result.expected_best_moves[0][1].dest)
                else:
                    # B should just wait to see what A does this turn, as he'll have priority next turn to defend.
                    # TODO this might not be right, B might just be screwed and making random moves because they cant change the outcome, no-op might not be any better than moving to king always
                    # self.assertIsNone(result.expected_best_moves[0][1])
                    pass
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)
                # depending on depth this calculates different differentials, but should p much always be more than 7
                self.assertGreater(result.best_result_state.tile_differential, 6)
                self.assertEqual(0, result.best_result_state.city_differential)

    def test_b_can_chase_as_army(self):
        rawMap = """
|    |    |    |    |    
          aG1          
                    
                     
                    
                    
                    
                    
                    
                    
     a23  bG25          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=15
bTiles=15
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102 + turn)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=15)

                t0_9 = map.GetTile(0,9)
                t1_9 = map.GetTile(1,9)
                t0_8 = map.GetTile(0,8)

                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                armyEngine.log_everything = True
                baseBoardState = armyEngine.get_base_board_state()
                # result = armyEngine.scan(3, logEvals=True, mcts=True)
                simState1 = armyEngine.get_next_board_state(
                    map.turn + 1,
                    baseBoardState,
                    frMove=Move(t1_9, t0_9),
                    enMove=Move(enemyGen, t1_9)
                )
                simState2 = simState1
                if not MapBase.player_had_priority(enemyGen.player, map.turn + 1):
                    simState2 = armyEngine.get_next_board_state(
                        map.turn + 2,
                        simState1,
                        frMove=Move(t0_9, t0_8),
                        enMove=Move(t1_9, t0_9)
                    )
                if debugMode:
                    fakeResult = ArmySimResult(simState2)
                    self.render_sim_analysis(map, fakeResult)

                # chasing another army should capture it within 2 moves, always
                self.assertEqual(0, len(simState2.friendly_living_armies))
                self.assertEqual(0, len(simState2.enemy_living_armies))
                for tile in simState2.sim_tiles.values():
                    self.assertEqual(1, tile.army)
                    self.assertEqual(1, tile.player)
                self.assertFalse(simState2.captured_by_enemy)
                self.assertFalse(simState2.captures_enemy)
                self.assertEqual(-2, simState2.tile_differential)
                self.assertEqual(0, simState2.city_differential)

    def test_armies_that_move_through_each_other_cancel_out(self):
        rawMap = """
|    |    |    |     
          aG1          



     b23  a23
     


     bG1          
|    |    |    |     
bot_player_index=0
bot_target_player=1
aTiles=15
bTiles=15
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=15)

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                armyEngine.log_everything = True
                baseBoardState = armyEngine.get_base_board_state()
                # result = armyEngine.scan(3, logEvals=True, mcts=True)
                simState1 = armyEngine.get_next_board_state(
                    map.turn + 1,
                    baseBoardState,
                    frMove=Move(aArmy.tile, bArmy.tile),
                    enMove=Move(bArmy.tile, aArmy.tile)
                )
                armyEngine.to_turn = map.turn + 7
                result = armyEngine.simulate_recursive_brute_force(simState1, currentTurn=7)
                if debugMode:
                    self.render_sim_analysis(map, result)

                self.assertEqual(0, len(simState1.friendly_living_armies))
                self.assertEqual(0, len(simState1.enemy_living_armies))
                for tile, simTile in simState1.sim_tiles.items():
                    self.assertEqual(1, simTile.army)
                    if aArmy.tile == simTile.source_tile:
                        self.assertEqual(general.player, simTile.player)
                    elif bArmy.tile == simTile.source_tile:
                        self.assertEqual(enemyGen.player, simTile.player)
                self.assertFalse(simState1.captured_by_enemy)
                self.assertFalse(simState1.captures_enemy)
                self.assertEqual(0, simState1.tile_differential)
                self.assertEqual(0, simState1.city_differential)
                self.assertTrue(simState1.kills_all_enemy_armies)
                self.assertTrue(simState1.kills_all_friendly_armies)

    def test_armies_that_move_through_each_other__biggest_wins_and_remains_army(self):
        rawMap = """
|    |    |    |     
          aG7          



     b23  a23
     


     bG7          
|    |    |    |     
bot_player_index=0
bot_target_player=1
aTiles=15
bTiles=15
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..

        self.enable_search_time_limits_and_disable_debug_asserts()

        for genBigger in [True, False]:
            for turn in [0, 1]:
                with self.subTest(turn=turn, genBigger=genBigger):
                    map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
                    self.ensure_player_tiles_and_scores(map, general, generalTileCount=15)

                    self.begin_capturing_logging()
                    map.turn = map.turn + turn
                    aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                    if genBigger:
                        aArmy.tile.army += 10
                        aArmy.value += 10
                    else:
                        bArmy.tile.army += 10
                        bArmy.value += 10

                    boardAnalysis = BoardAnalyzer(map, general)
                    boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                    mcts: MctsDUCT = MctsDUCT()
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                    armyEngine.friendly_has_kill_threat = True
                    armyEngine.enemy_has_kill_threat = True
                    armyEngine.log_everything = True
                    baseBoardState = armyEngine.get_base_board_state()
                    armyEngine.to_turn = map.turn + 7
                    # result = armyEngine.scan(3, logEvals=True, mcts=True)
                    simState1 = armyEngine.get_next_board_state(
                        map.turn + 1,
                        baseBoardState,
                        frMove=Move(aArmy.tile, bArmy.tile),
                        enMove=Move(bArmy.tile, aArmy.tile)
                    )
                    if debugMode:
                        result = armyEngine.simulate_recursive_brute_force(simState1, currentTurn=7)
                        self.render_sim_analysis(map, result)

                    expect9ArmyTile = aArmy.tile
                    winningPlayer = enemyGen.player
                    # why -3...?
                    expectedTileDifferential = -2
                    if genBigger:
                        self.assertEqual(1, len(simState1.friendly_living_armies))
                        self.assertEqual(0, len(simState1.enemy_living_armies))
                        self.assertIn(bArmy.tile, simState1.friendly_living_armies, "a should have an army left where b's army used to be")
                        self.assertTrue(simState1.kills_all_enemy_armies)
                        self.assertFalse(simState1.kills_all_friendly_armies)
                        expect9ArmyTile = bArmy.tile
                        winningPlayer = general.player
                        expectedTileDifferential = 0 - expectedTileDifferential
                    else:
                        self.assertEqual(1, len(simState1.enemy_living_armies))
                        self.assertEqual(0, len(simState1.friendly_living_armies))
                        self.assertIn(aArmy.tile, simState1.enemy_living_armies, "b should have an army left where a's army used to be")
                        self.assertFalse(simState1.kills_all_enemy_armies)
                        self.assertTrue(simState1.kills_all_friendly_armies)

                    for tile, simTile in simState1.sim_tiles.items():
                        if simTile.source_tile == expect9ArmyTile:
                            self.assertEqual(9, simTile.army)
                            self.assertEqual(winningPlayer, simTile.player)
                        else:
                            self.assertEqual(1, simTile.army)
                            self.assertEqual(tile.player, simTile.player)

                    self.assertFalse(simState1.captured_by_enemy)
                    self.assertFalse(simState1.captures_enemy)
                    self.assertEqual(0, simState1.city_differential)
                    self.assertEqual(expectedTileDifferential, simState1.tile_differential)

    def test_brute_force__a_can_cap_bs_general(self):
        rawMap = """
|    |    |    |    |    
          aG1          





               b25
     M              

a25       bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
        # armyEngine.friendly_has_kill_threat = True
        # armyEngine.enemy_has_kill_threat = True
        result = armyEngine.scan(3, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertTrue(result.best_result_state.captures_enemy)
        self.assertFalse(result.best_result_state.captured_by_enemy)

    def test_brute_force__a_can_cap_bs_general_point_blank(self):
        rawMap = """
|    |    |    |    |    
          aG1          





               b25
     M              

     a25  bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
        # armyEngine.friendly_has_kill_threat = True
        # armyEngine.enemy_has_kill_threat = True
        result = armyEngine.scan(3, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertEqual(enemyGen, result.expected_best_moves[0][0].dest)
        self.assertTrue(result.best_result_state.captures_enemy)
        self.assertFalse(result.best_result_state.captured_by_enemy)

    def test_brute_force__a_can_cap_bs_general_point_blank_forced(self):
        rawMap = """
|    |    |    |    |    
          aG1          





               b25
     M              
     M
M    a25  bG1          
|    |    |    |    |    
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
        # armyEngine.friendly_has_kill_threat = True
        # armyEngine.enemy_has_kill_threat = True
        result = armyEngine.scan(3, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertEqual(enemyGen, result.expected_best_moves[0][0].dest)
        self.assertTrue(result.best_result_state.captures_enemy)
        self.assertFalse(result.best_result_state.captured_by_enemy)

    def test_should_scrim_against_incoming_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                mapFile = 'GameContinuationEntries/should_scrim_against_incoming_army__turn_241.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 241 + turn, fill_out_tiles=True)

                # self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapFile, 241 + turn)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

                eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
                ekThreat = eklipz_bot.threat.path.start.tile
                aArmy = Army(map.GetTile(4, 14))
                bArmy = Army(map.GetTile(ekThreat.x, ekThreat.y))

                self.begin_capturing_logging()
                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, mctsRunner=mcts)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                armyEngine.log_everything = True
                armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
                result = armyEngine.scan(5, mcts=True)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # both players should have moves until they cancel out
                for aMove, bMove in result.expected_best_moves[0:2]:
                    self.assertIsNotNone(aMove)
                    self.assertIsNotNone(bMove)

    def test_army_scrim_defense_should_not_avoid_kill_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/army_scrim_defense_should_not_avoid_kill_threat___rgNPA7Zan---b--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 388)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
        ekThreat = eklipz_bot.threat.path.start.tile
        aArmy = Army(map.GetTile(3, 12))
        bArmy = Army(map.GetTile(ekThreat.x, ekThreat.y))

        self.begin_capturing_logging()

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, mctsRunner=mcts)
        armyEngine.friendly_has_kill_threat = True
        armyEngine.enemy_has_kill_threat = True
        # TODO switch to this method of parameterizing this
        armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
        result = armyEngine.scan(5, logEvals=False, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertEqual(map.GetTile(2, 12), result.expected_best_moves[0][0].dest)

        # player b should be capping as many tiles as possible
        for aMove, bMove in result.expected_best_moves[0:2]:
            self.assertIsNotNone(aMove)
            self.assertIsNotNone(bMove)
        for aMove, bMove in result.expected_best_moves[2:5]:
            self.assertIsNone(aMove)
            self.assertIsNotNone(bMove)

    def test__brute_force_respects_time_limit(self):
        # pre-jit these
        calc_value_int(1, 2, 3, 4, False, False, True, True, 1, -1)
        calc_econ_value(1, 2, 3)

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/army_scrim_defense_should_not_avoid_kill_threat___rgNPA7Zan---b--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 388)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
        ekThreat = eklipz_bot.threat.path.start.tile
        aArmy = Army(map.GetTile(3, 12))
        bArmy = Army(map.GetTile(ekThreat.x, ekThreat.y))

        self.begin_capturing_logging()
        startTime = time.perf_counter()

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, timeCap=0.05, mctsRunner=mcts)
        armyEngine.friendly_has_kill_threat = True
        armyEngine.enemy_has_kill_threat = True
        # armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
        alwaysBruteForce = True
        result = armyEngine.scan(8, logEvals=False, mcts=not alwaysBruteForce)
        duration = time.perf_counter() - time.perf_counter()
        if debugMode:
            self.render_sim_analysis(map, result)

        # decrements like, 4 times down to depth 3 at a cost of 30ms each so 210 ms of post
        self.assertLess(duration, 0.07)
        self.assertEqual(map.GetTile(2, 12), result.expected_best_moves[0][0].dest)

        # player b should be capping as many tiles as possible
        for aMove, bMove in result.expected_best_moves:
            self.assertIsNotNone(bMove)

    def test__mcts_respects_time_limit(self):
        # pre-jit these
        calc_value_int(1, 2, 3, 4, False, False, True, True, 1, -1)
        calc_econ_value(1, 2, 3)

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/army_scrim_defense_should_not_avoid_kill_threat___rgNPA7Zan---b--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)

        # self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 388)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
        ekThreat = eklipz_bot.threat.path.start.tile
        aArmy = Army(map.GetTile(3, 12))
        bArmy = Army(map.GetTile(ekThreat.x, ekThreat.y))

        self.begin_capturing_logging()
        startTime = time.perf_counter()

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, timeCap=0.05, mctsRunner=mcts)
        armyEngine.friendly_has_kill_threat = True
        armyEngine.enemy_has_kill_threat = True
        # armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
        alwaysMcts = True
        result = armyEngine.scan(8, logEvals=False, mcts=alwaysMcts)
        duration = time.perf_counter() - time.perf_counter()
        if debugMode:
            self.render_sim_analysis(map, result)

        # decrements like, 4 times down to depth 3 at a cost of 30ms each so 210 ms of post
        self.assertLess(duration, 0.07)
        self.assertEqual(map.GetTile(2, 12), result.expected_best_moves[0][0].dest)

        # player b should be capping as many tiles as possible
        for aMove, bMove in result.expected_best_moves[0:4]:
            self.assertIsNotNone(bMove)
    
    def test_should_intercept_army_and_kill_incoming_before_it_does_damage(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        for turn in [0, 1]:
            with self.subTest(turn=turn):
                mapFile = 'GameContinuationEntries/should_intercept_army_and_kill_incoming_before_it_does_damage___rliiLZ7ph---b--238.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 238 + turn, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                m, _ = self.load_map_and_general(mapFile, 238 + turn)

                # simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptViewer=True)
                # simHost.bot_hosts[general.player].eklipz_bot.next_scrimming_army_tile = self.get_player_tile(10, 13, simHost.sim, general.player)
                # simHost.sim.ignore_illegal_moves = True

                # 10,13 scrim against 12,12
                boardAnalysis = BoardAnalyzer(m, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGeneral)
                aArmy = Army(m.GetTile(10, 13))
                bArmy = Army(m.GetTile(12, 12))

                self.begin_capturing_logging()
                armyEngine = ArmyEngine(m, [aArmy], [bArmy], boardAnalysis)
                armyEngine.friendly_has_kill_threat = False
                armyEngine.enemy_has_kill_threat = True
                # armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(m, [general])
                armyEngine.log_payoff_depth = 2
                armyEngine.repetition_threshold = 3
                result = armyEngine.scan(5, logEvals=False, mcts=True)
                if debugMode:
                    sim = GameSimulator(map_raw=map, ignore_illegal_moves=True)
                    sim.players[general.player].set_map_vision(m)
                    self.render_step_engine_analysis(armyEngine, sim, result, aArmy, bArmy)
                self.assertIsNone(result.expected_best_moves[0][0])

                # player b should be capping as many tiles as possible
                for aMove, bMove in result.expected_best_moves:
                    self.assertIsNotNone(bMove)

                # # some of these will be illegal if the bot does its thing and properly kills the inbound army
                # simHost.queue_player_moves_str(enemyGeneral.player, '12,12 -> 11,12 -> 10,12 -> 9,12 -> 8,12 -> 7,12')
                # winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=3)
                # self.assertPlayerTileCount(simHost, enemyGeneral.player, 66)
    
    def test_should_just_kill_army_not_dodge_off_general_into_death(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_just_kill_army_not_dodge_off_general_into_death___re2uZGNTn---b--445.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 445, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 445)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # # alert enemy of the player general
        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        #
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        # self.assertIsNone(winner)

        m = simHost.sim.players[general.player].map
        eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
        ekThreat = eklipz_bot.threat.path.start.tile
        aArmy = Army(general)
        bArmy = Army(m.GetTile(ekThreat.x, ekThreat.y))

        self.begin_capturing_logging()
        armyEngine = ArmyEngine(m, [aArmy], [bArmy], eklipz_bot.board_analysis)
        armyEngine.friendly_has_kill_threat = True
        armyEngine.enemy_has_kill_threat = True
        armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(m, [general])
        result = armyEngine.scan(5, logEvals=False, mcts=True)
        if debugMode:
            self.render_sim_analysis(m, result)
        self.assertEqual(m.GetTile(14, 7), result.expected_best_moves[0][0].dest)

        # player b should be capping as many tiles as possible
        for aMove, bMove in result.expected_best_moves:
            self.assertIsNotNone(bMove)

    def test_should_not_blow_up(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_blow_up___Se9iLCLpn---b--291.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 291)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 291)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        m = simHost.sim.players[general.player].map
        eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
        aArmy = eklipz_bot.get_army_at_x_y(7,13)
        bArmy = eklipz_bot.get_army_at_x_y(6,11)

        self.begin_capturing_logging()
        armyEngine = ArmyEngine(m, [aArmy], [bArmy], eklipz_bot.board_analysis)
        armyEngine.friendly_has_kill_threat = False
        armyEngine.enemy_has_kill_threat = False
        armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(m, [general])
        result = armyEngine.scan(6, logEvals=False, noThrow=debugMode, mcts=True)
        if debugMode:
            self.render_step_engine_analysis(armyEngine, simHost.sim, result, aArmy, bArmy)
            # self.render_sim_analysis(m, result)
    
    def test_should_not_generate_idkQQ_error_in_scrim_8_11__7_12(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_generate_idkQQ_error_in_scrim_8_11__7_12___rxjjRQqTn---b--484.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 484, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 484)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_generate_idkQQ_error_in_scrim_8_11__7_12
    
    def test_should_not_lock_up_mcts(self):
        for i in range(10):
            with self.subTest(i=i):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
                mapFile = 'GameContinuationEntries/should_not_lock_up_mcts___EklipZ_ai-rel2QZ4Ch---1--197.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 197, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, 197)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '13,11->14,11->14,12')
                simHost.get_bot(general.player).engine_use_mcts = True

                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=3)
                self.assertIsNone(winner)
    
    def test_should_not_lock_up_mcts_2(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for i in range(10):
            with self.subTest(i=i):
                mapFile = 'GameContinuationEntries/should_not_lock_up_mcts_2___EklipZ_ai-rel2QZ4Ch---1--196.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 196, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, 196)

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '12,11->13,11->14,11->14,12')
                simHost.get_bot(general.player).engine_use_mcts = True

                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=3)
                self.assertIsNone(winner)
    
    def test_should_not_die_scrimming_general_at_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_die_scrimming_general_at_threat___BgX63UBAn---1--439.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 439, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 439)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,6->3,6->2,6')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=3)
        self.assertIsNone(winner)
    
    def test_should_not_dance_around_armies_standing_still(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_dance_around_armies_standing_still___HeEzmHU03---0--269.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 269, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 269)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        eklipz_bot = simHost.bot_hosts[general.player].eklipz_bot
        ekThreat = eklipz_bot.threat.path.start.tile
        aArmy = Army(map.GetTile(10, 8))
        bArmy = Army(map.GetTile(10, 9))

        self.begin_capturing_logging()

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, mctsRunner=mcts)
        armyEngine.friendly_has_kill_threat = False
        # TODO TEST WITH BOTH KILL THREAT AND NOT KILL THREAT
        # TODO TEST WITH BOTH FORCED TOWARDS AND NOT FORCED TOWARDS
        armyEngine.enemy_has_kill_threat = True
        # armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
        # armyEngine.time_limit = 0.1
        armyEngine.iteration_limit = 1000
        armyEngine.time_limit = 10000
        result = armyEngine.scan(4, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertNotEqual(map.GetTile(9, 8), result.expected_best_moves[0][0].dest, "should not do ridiculous dancing around on friendly tiles.")
        self.assertEqual(bArmy.tile, result.expected_best_moves[0][0].dest, "should immediately capture enemy army threatening to capture tiles.")
        self.assertGreater(result.net_economy_differential, 7, 'might be inconsistent depending on the depth MCTS / Brute force reach but should cap enemy army then cap tiles resulting in positive econ')
    
    def test_should_complete_scrim_army_intercept_instead_of_letting_enemy_cap_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_complete_scrim_army_intercept_instead_of_letting_enemy_cap_tiles___Bgk8TIUR2---0--86.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 86, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 86)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,14->4,14->3,14->2,14->2,13->2,12')
        simHost.queue_player_moves_str(general.player, '2,16->3,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=5)
        self.assertIsNone(winner)
        shouldNotBeCapped = self.get_player_tile(2, 13, simHost.sim, general.player)
        self.assertEqual(general.player, shouldNotBeCapped.player)

    def test_should_intercept_enemy_kill_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_enemy_kill_threat___Svxvcvovg---1--225.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 224, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 224)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '17,13->17,14->17,15->17,16->16,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=3.0, turns=5)
        self.assertIsNone(winner)
    
    def test_should_intercept_army__should_not_repetition_against_non_moving_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_army_not_leave_gen_defenseless___Svxvcvovg---1--223.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 223)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=15)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=2)

    def test_should_intercept_army_not_leave_gen_defenseless(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_army_not_leave_gen_defenseless___Svxvcvovg---1--223.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 223)

        self.begin_capturing_logging()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '18,12->18,13->17,13->17,14->17,15->17,16->16,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=8)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=2)

    def test__board_state_value_compression(self):
        testCases = [
            40,
            0,
            1,
            2,
            4,
            8,
            12,
            20,
            1000,
            -1,
            -2,
            -4,
            -8,
            -12,
            -20,
            -40,
            -1000,
        ]

        for boardValue in testCases:
            with self.subTest(boardValue=boardValue):
                basicMcts = MctsDUCT()
                fakeState = ArmySimState(0, basicMcts.eval_params, {}, {}, {})
                # this will be the only value on the board
                fakeState.controlled_city_turn_differential = boardValue

                actualExpectedValueInt = boardValue * 10
                self.assertEqual(actualExpectedValueInt, fakeState.calculate_value_int())

                compressed0, compressed1 = basicMcts.get_player_utilities_n1_1(fakeState)

                rawAsFloat = actualExpectedValueInt * 1.0
                rawScaled = rawAsFloat * basicMcts.utility_compression_ratio
                expectedCompressedRawPython = rawScaled / (1.0 + abs(rawScaled))

                self.assertAlmostEqual(expectedCompressedRawPython, compressed0, places=7)

                self.assertGreater(compressed0, -1.0)
                self.assertLess(compressed0, 1.0)
                self.assertGreater(compressed1, -1.0)
                self.assertLess(compressed1, 1.0)

                decompressed0 = basicMcts.decompress_player_utility(compressed0)

                if compressed0 > 0:
                    self.assertTrue(
                        actualExpectedValueInt * 1.001 >= decompressed0 >= actualExpectedValueInt * 0.999,
                        f'actualExpectedValueInt * 1.001 ({actualExpectedValueInt * 1.001}) >= decompressed0 ({decompressed0}) >= actualExpectedValueInt * 0.999 ({actualExpectedValueInt * 0.999})')
                else:
                    self.assertTrue(
                        actualExpectedValueInt * 1.001 <= decompressed0 <= actualExpectedValueInt * 0.999,
                        f'actualExpectedValueInt * 1.001 ({actualExpectedValueInt * 1.001}) <= decompressed0 ({decompressed0}) <= actualExpectedValueInt * 0.999 ({actualExpectedValueInt * 0.999})')

    def test__mcts_should_always_win__vs__brute_force__top_left_bottom_right(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'SymmetricTestMaps/even_playground_map_small__top_left_bot_right.txtmap'

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__mcts_should_always_win__vs__brute_force__top_right_bottom_left(self):
        numRuns = 50
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'SymmetricTestMaps/even_playground_map_small__top_right_bot_left.txtmap'

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            # aBot.mcts_engine.final_playout_estimation_depth = 1
            aBot.engine_honor_mcts_expanded_expected_score = True
            aBot.engine_army_nearby_tiles_range = 6

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False
            # this was how brute force was during the original testing.
            bBot.engine_allow_enemy_no_op = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__mcts_should_always_win__vs__brute_force__left_right(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'SymmetricTestMaps/even_playground_map_small__left_right.txtmap'

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            aBot.engine_force_multi_tile_mcts = True

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False
            # this was how brute force was during the original testing.
            bBot.engine_allow_enemy_no_op = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__brute_force_should_beat_no_engine(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = False

            # original brute force had this false while it was true for mcts.
            # it is now true for both. and brute force is still beating no engine.
            # 13-7
            # aBot.engine_allow_enemy_no_op = False

            # see if brute force does better with the force or not.
            # brute force lost 9-11 with this, lol.
            # aBot.engine_allow_force_incoming_armies_towards = True

            # aBot.engine_allow_enemy_no_op = False

        def configure_b(bBot: EklipZBot):
            bBot.disable_engine = True

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__mcts_should_beat_no_engine(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            # hodgepodge of currently winning a-b tests
            # 10-9
            # aBot.mcts_engine.total_playout_move_count = 6
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 0
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = 0
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = True
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5

            #13-7
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = True
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5

            # (Same as above but using maxValue selection instead of robust child)
            # 10-10

            # try robust child again?
            # 12-7, codified
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)

            # 12-8...?
            # 15-5
            # 11-9
            # TODO come back to this.
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False

            # nothing? 10-10

            # 10-10 D:
            aBot.engine_force_multi_tile_mcts = True

        def configure_b(bBot: EklipZBot):
            bBot.disable_engine = True

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__mcts_should_always_win__vs__brute_force__left_vs_right(self):
        mapFile = 'SymmetricTestMaps/even_playground_map_small__left_right.txtmap'
        numRuns = 100
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            # 4 went 46-54
            # 2 went 51-48
            # aBot.mcts_engine.final_playout_estimation_depth = 2

            # aBot.mcts_engine.final_playout_estimation_depth = 2
            aBot.engine_honor_mcts_expanded_expected_score = True

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False
            bBot.engine_allow_enemy_no_op = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__A_B_test_mcts__num1__left_vs_right(self):
        numRuns = 250
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        def configure_a(aBot: EklipZBot):
            aBot.expansion_full_time_limit = 0.15  # b is 0.2

            #47-53, again
            #70-97, meh
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 4  # was 0

            # 244-256
            # aBot.expansion_allow_leaf_moves = False

            # doesn't seem to do too much, but does seem to lose.
            # aBot.mcts_engine.explore_factor = 1.5

            # # a winning!? nvm pretty even-ish
            # aBot.mcts_engine.utility_compression_ratio = 0.005
            # bBot.mcts_engine.utility_compression_ratio = 0.01

            # not meaningful
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 10
            # aBot.mcts_engine.total_playout_move_count = 15

            # so far, significant. WHOO won quite a few in a row. Codified.
            # aBot.allow_force_incoming_armies_towards = False

            # seemed about 50-50...? Maybe slightly better, worth coming back to
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 5
            # aBot.mcts_engine.total_playout_move_count = 7

            # failure
            # aBot.mcts_engine.biased_move_ratio_while_available = 1.0
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 5
            # aBot.mcts_engine.total_playout_move_count = 4
            # aBot.mcts_engine.min_random_playout_moves_initial = 2

            # this shit does nothing...?
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 5
            # aBot.mcts_engine.total_playout_move_count = 4

            # seems to be winning, codified
            # aBot.mcts_engine.eval_params.kills_friendly_armies_10_fraction = -10
            # aBot.mcts_engine.eval_params.kills_enemy_armies_10_fraction = 10

            # seems to be winning, codified
            # aBot.mcts_engine.explore_factor = 1.3

            # seems to be winning! codified
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)
            # aBot.mcts_engine.explore_factor = 1.5

            # bad
            # aBot.mcts_engine.utility_compression_ratio = 0.03
            # aBot.mcts_engine.utility_compression_ratio = 0.005

            # seems good, codified
            # aBot.mcts_engine.total_playout_move_count = 6

            # a won 193 vs b won 200. So my biased stuff is fucked, good to know. Disabling it for now.
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.1
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 2

            # TODO above might be last good change? Everything after inversed? Start reverse verifying...
            # 28-21, re-codified for now. Come back to this.
            # aBot.mcts_engine.total_playout_move_count = 6

            ####### ok this was 18-32 loss, the 'dont propogate initial results' is correct.
            # 22-28 on re-verification.
            # aBot.mcts_engine.skip_first_result_backpropogation = False

            # ###20-18, maybe just because more iterations? Keep trying.
            # ######18-22, so 38-40. try again
            # #####22-18, so 60-58. Seems meaningless.
            # #####TODO revisit later after tuning other things.
            # 28-22, try again.
            # 24-26 after starting by winning almost 10 in a row, wtf distribution. AGAIN!
            # 32-18, so 84-66, codified
            # aBot.mcts_engine.allow_random_repetitions = True

            # #####24-15? Continuing
            # ######round 2, 28-22 so 52-37. Codifying as 4.
            # test 5 again.
            # 23-27. TEST AGAIN.
            # 24-26. OK TRY HIGHER :D
            # aBot.mcts_engine.total_playout_move_count = 5

            # 27-22, AGAIN
            # 28-22 codifying
            # aBot.mcts_engine.total_playout_move_count = 7

            # try 8?
            # 46-54 ok 7 it is.
            # aBot.mcts_engine.total_playout_move_count = 8

            # 53-44, AGAIN
            # 115-132, (so 168-176). try reducing to 1?
            # aBot.mcts_engine.min_random_playout_moves_initial = 3

            # 133-113, AGAIN
            # killed at 20-15, codifying
            # aBot.mcts_engine.min_random_playout_moves_initial = 1

            # 135-115, codified. Confirmed by expanded_expected vs _expected which won by similar marging, and just _expected won against none at all, so very conclusively good.
            # aBot.engine_honor_mcts_expanded_expected_score = True

            # killed 61-79
            # 114-131 fml
            # aBot.engine_army_nearby_tiles_range = 6  # was 4. 5 being tested in parallel, as well.

            # try 3
            # killed 45-70
            # aBot.engine_army_nearby_tiles_range = 3  # was 4. 5 being tested in parallel, as well.
            # ok so based on the other data I think we need to increase range but reduce the armies-per-scrim limit for now. To like, 3 or 2 or something.

            # 117-130, try 6?
            # aBot.engine_army_nearby_tiles_range = 8
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 120-125
            # aBot.engine_army_nearby_tiles_range = 6
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 90-158
            # aBot.expansion_use_multi_per_dist_per_tile = True  # note no force single
            # aBot.expansion_single_iteration_time_cap = 0.01

            # 121-94. Unclear based on other runs, and dont know what B was. Rerunning against b=2
            # 116-132, so 2 seems to be winner. Try 1...?
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 3

            # 84-79 killed due to lots of errors, restarting
            # 120-130
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 1
            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=lambda bBot: bBot,
            debugMode=debugMode)

    def test__A_B_test_mcts__num2__left_vs_right(self):
        numRuns = 250
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            pass

        def configure_a(aBot: EklipZBot):
            aBot.engine_mcts_move_estimation_net_differential_cutoff = 2

            # 70-108, definitely bad
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -1

            # 40-60, trying -1
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -6

            # 25-25, codifying for now.
            # aBot.mcts_engine.offset_initial_differential = True

            # ####187-204, so, bad.
            # retrying, 21-28, so ok, legit bad.
            # aBot.mcts_engine.offset_initial_differential = True
            # aBot.mcts_engine.utility_compression_ratio = 0.07

            # 21-29 yikes
            # aBot.mcts_engine.utility_compression_ratio = 0.03

            # try other direction...?
            # 22-28
            # if bad, try scaling down explore to compensate.
            # 28-22, try MORE
            # 51-47 (so 79-69, codified! WHOO!)
            # aBot.mcts_engine.utility_compression_ratio = 0.005
            # aBot.mcts_engine.explore_factor = 1.1

            # play with it a bit more.
            # 48-52, lets try a bit lower
            # aBot.mcts_engine.utility_compression_ratio = 0.007
            # aBot.mcts_engine.explore_factor = 1.1

            #lower
            # 56-44, codified
            # aBot.mcts_engine.utility_compression_ratio = 0.004
            # aBot.mcts_engine.explore_factor = 1.1

            # try even lower...?
            # 47-52, .0035?
            # aBot.mcts_engine.utility_compression_ratio = 0.003
            # aBot.mcts_engine.explore_factor = 1.1

            # 123-122, perfectly even. Try in tweaking explore factor......?
            # aBot.mcts_engine.utility_compression_ratio = 0.0035
            # aBot.mcts_engine.explore_factor = 1.1

            # Try in tweaking explore factor
            # 134-112, AGAIN but codified
            # 115-133, test again...?
            # aBot.mcts_engine.utility_compression_ratio = 0.004  # default, just noting
            # aBot.mcts_engine.explore_factor = 1.0  # was 1.1 when starting this run

            # try 1.05...?
            # killed 81-75, codifying...? I'm bored of this
            # aBot.mcts_engine.utility_compression_ratio = 0.004  # default, just noting
            # aBot.mcts_engine.explore_factor = 1.05  # was 1.0 when starting this run

            # TESTING B == 0.0
            # 124-124
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.5

            # b = 0.5
            # codified in advance, at 126-105
            # 130-116
            # wait, what? with b at 0.5 this went 86-160
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.85

            # accidentally killed 52-66 but wanted to switch to dist 3 anyway
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.0
            # aBot.gather_include_distance_from_enemy_general_large_map_as_negatives = 0.0

            # just per_tile
            # 78-172 lol
            # aBot.expansion_use_multi_per_tile = True
            # aBot.expansion_force_no_global_visited = False

            # 104-118, try again inversed...?
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 2  # was 0 but codified in the meantime

            # 112-138
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 1  # b is 2
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4  # b is 3

            # 129-119 buth other one went 120-130 so even, try again.
            # 218-279, ok definitely bad
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4  # b is 3

            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__A_B_test_mcts__num3__left_vs_right(self):
        numRuns = 250
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            pass

        def configure_a(aBot: EklipZBot):
            # 88-92, meaningless, again
            aBot.engine_mcts_move_estimation_net_differential_cutoff = +1

            # 39-58, try +1
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -20

            # Test reverting the no op bonus...
            # 24-26
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 0
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = 0

            # try middle ground
            # 25-25, seems this doesn't matter...?
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 5
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -5

            # try increasing it a bit to 1 full econ...?
            # 23-27
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 10
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -10

            # try asymmetric enemy vs friendly...?
            # 27-23, try more.
            # 29-31, f it.
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 12
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -5

            # try near 0 one more time..
            # 24-26, meaningless. Ok ignore.
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 2
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -2

            # play with penalty
            # 46-52, try increasing...?
            # aBot.mcts_engine.eval_params.friendly_move_penalty_10_fraction = 0
            # aBot.mcts_engine.eval_params.enemy_move_penalty_10_fraction = 0

            # 46-54, try again, variance...?
            # 58-42 lol...? AGAIN?
            # 129-118, AGAIN @ 233-214 ACTUALLY NVM WHO CARES CODIFIED FOR NOW LETS TEST MORE INTERESTING STUFF LIKE FINAL PLAYOUT
            # aBot.mcts_engine.eval_params.friendly_move_penalty_10_fraction = 4
            # aBot.mcts_engine.eval_params.enemy_move_penalty_10_fraction = -4

            # 108-142 :s
            # aBot.mcts_engine.final_playout_estimation_depth = 4

            # try reducing to 2...?
            # aBot.mcts_engine.final_playout_estimation_depth = 2

            # 131-118, confirms other results too, codified.
            # aBot.engine_honor_mcts_expanded_expected_score = True
            # aBot.engine_honor_mcts_expected_score = False

            # killed 82-88, again
            # 123-124, meaningless or worse
            # aBot.engine_army_nearby_tiles_range = 5  # was 4

            # codified, 128-119
            # aBot.mcts_engine.eval_params.always_reward_dead_army_no_ops = True  # was false

            # 108-138, huh
            # aBot.engine_army_nearby_tiles_range = 6
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3

            # what about range 5...?
            # 122-125
            # aBot.engine_army_nearby_tiles_range = 5
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3

            # try 3.....?
            # 125-123. What about a lower limit?
            # aBot.engine_army_nearby_tiles_range = 5
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3

            # 106-131
            # aBot.engine_army_nearby_tiles_range = 5
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 125-104, codified
            # aBot.engine_army_nearby_tiles_range = 4
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 115-135, ok per tile is worse as expected.
            # aBot.expansion_use_multi_per_tile = True
            # aBot.expansion_use_multi_per_dist_per_tile = False

            # 117-132
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.5  # was 0

            # 262-236, interesting. Codified.
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 7  # current 4

            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__A_B_test_mcts__num4__left_vs_right(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False  # currently true

            # 27-23 after fixing a-b. Trying more. (now with offset true and 6 rollouts):
            # 29-21, codifying. :D BIASED IS BACK BABYYYYY
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = True
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5

            # try leaving bias up but re-including positional win detection:
            # 31-19, fucking, bias worked the whole time and we didn't need this shit...?
            # try again. 20-30 lmao, so 51-49, try again...?
            # 26-24, seems basically completely even weirdly enough.
            # TODO come back and play with this later after tweaking other bias stuff.
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False

            # play with biased moves always first.
            # 24-26, try again.
            # 47-53, ok. what about 75% of the time?
            # aBot.mcts_engine.biased_move_ratio_while_available = 1.0
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4

            # 47-53 again. Try lower...?
            # 48-51, ignore for now
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.4
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4

            # try 7->8 with high sim count
            # 159-134, ok so bigger is better...? AGAIN just to be sure.
            # 150-145, codifying
            # aBot.mcts_engine.total_playout_move_count = 8

            # 153-146, nuked in favor of _expanded_expected_score which did much better both against this and against neither.
            # aBot.engine_honor_mcts_expected_score = True

            # killed 80-76, again
            # killed at 140-124, codified
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3  # currently 4

            # 158-137, codified...?
            # aBot.expansion_single_iteration_time_cap = 0.03  # currently 0.02
            # re-confirm but flipped, b is 0.03 now and this is 0.02

            # 145-149, about even
            # aBot.expansion_single_iteration_time_cap = 0.02  # currently 0.03

            # 134-162. Ok, try 10
            # aBot.mcts_engine.total_playout_move_count = 15  # current 8

            # even
            # aBot.mcts_engine.total_playout_move_count = 10  # current 8

            # 146-128, codified
            # aBot.engine_always_include_last_move_tile_in_scrims = True  # was false but codified in meantime

            # 136-162
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 3  # was 2

            # 120-130
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4 # was 3

            # 123-127
            # aBot.expansion_single_iteration_time_cap = 0.12

            # 254-243. Confirming with another run since previous runs indicated otherwise. This may have changed due to the 'tiles gathered to this turn' de-restriction?
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 3  # currently 2

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=lambda bBot: bBot,
            debugMode=debugMode)

    def test__A_B_test_mcts__num5__left_vs_right(self):
        numRuns = 250
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            # 245-255. Implemented long-move-cutoff and trying again
            aBot.expansion_single_iteration_time_cap = 0.055  # from 0.1, small tile time at 0.055

            # 18-22, bad.
            # aBot.mcts_engine.explore_factor = 2.0
            # aBot.mcts_engine.offset_initial_differential = True

            # 29-20. Trying again.
            # killed @ 18-11 making it 48-31 in favor of robust child.
            # Codified.
            # TODO test again later with large game size to be sure. with
            #  configureB=lambda bBot: bBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue),
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)

            # This should not be good, but if it is, that might be why brute force was winning sometimes.
            #  Assuming that a and b werent swapped and mcts was beating brute force the whole time.
            # 28-22, shit. TODO try again later
            # aBot.engine_allow_enemy_no_op = False

            # NEXT try this instead...?
            # 21-29, shit, try engine_allow_enemy_no_op_false again
            # aBot.mcts_engine.allow_random_no_ops = False

            # 24-25, try again.
            # 25-24, so 49-49, boring, who cares.
            # aBot.engine_allow_enemy_no_op = False

            # 25-25
            # 27-22, codified because thats the direction we want to go anyway.
            # aBot.engine_force_multi_tile_mcts = True

            # try reducing this...?
            # 22-27, AGAIN
            # 112-136, so SOME bias is definitely good.
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 2

            # try more...?
            # 113-131
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 6
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5  # default, just noting what it is right now.

            # try adjusting the ratio
            # 118-130
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.6

            # 119-122 ...? but everything else did well so still codified.
            # aBot.engine_honor_mcts_expanded_expected_score = True

            # try this again
            # killed at 89-76 due to long running, running again.
            # 122-125
            # aBot.engine_allow_enemy_no_op = False

            # 123-119, codified i guess
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.3  # b is 0.5

            # 117-130, but 0.75 has already been codified
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.4  # b is 0.3

            # 124-121
            # aBot.expansion_use_multi_per_dist_per_tile = True
            # aBot.expansion_single_iteration_time_cap = 0.01  # current 0.02

            # try again, against 0.03, with multi-tile
            # 103-141. Fixed now, though. Try again.
            # aBot.expansion_use_multi_per_dist_per_tile = True
            # aBot.expansion_force_no_global_visited = True

            # 119-109, codified
            # aBot.expansion_single_iteration_time_cap = 0.06

            # 122-127
            # aBot.expansion_small_tile_time_ratio = 0.5  # was 1.0

            # 127-122, try full small time...?
            # aBot.expansion_single_iteration_time_cap = 0.1  # was 0.06
            # aBot.expansion_small_tile_time_ratio = 0.5  # was 1.0

            # 126-121
            # aBot.expansion_small_tile_time_ratio = 1.0

        def configure_b(bBot: EklipZBot):
            # bBot.expansion_use_multi_per_dist_per_tile = True
            # bBot.expansion_single_iteration_time_cap = 0.03
            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            # configureB=lambda bBot: bBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue),
            debugMode=debugMode)
