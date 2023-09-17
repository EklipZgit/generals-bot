import logging
import time
import typing

import SearchUtils
from ArmyEngine import ArmyEngine, ArmySimResult
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Engine.ArmyEngineModels import calc_value_int, calc_econ_value
from Sim.GameSimulator import GameSimulatorHost, GameSimulator
from TestBase import TestBase
from base.client.map import Tile, MapBase


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

    def get_test_army_tiles(self, map: MapBase, general: Tile, enemyGen: Tile) -> typing.Tuple[Army, Army]:
        enemyArmy = None
        generalArmy = None
        for tile in map.get_all_tiles():
            if tile.player == enemyGen.player and tile.army > 3 and not tile.isGeneral:
                enemyArmy = tile
            elif tile.player == general.player and tile.army > 3 and not tile.isGeneral:
                generalArmy = tile

        # now include generals
        for tile in map.get_all_tiles():
            if enemyArmy is None and tile.player == enemyGen.player and tile.army > 3:
                enemyArmy = tile
            elif generalArmy is None and tile.player == general.player and tile.army > 3:
                generalArmy = tile

        if enemyArmy is None:
            raise AssertionError("Couldn't find an enemy tile with army > 3")
        if generalArmy is None:
            raise AssertionError("Couldn't find a friendly tile with army > 3")

        return Army(generalArmy), Army(enemyArmy)

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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
                # armyEngine.friendly_has_kill_threat = True
                # armyEngine.enemy_has_kill_threat = False
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan(4, logEvals=False, mcts=True)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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

        def test_brute_force__recognizes_wins_on_general_distances(self):
            rawMap = """
    |    |    |    |    |    
         aG1               


              a25       b25



    M              
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

            self.enable_search_time_limits_and_disable_debug_asserts()

            for turn in [0, 1]:
                with self.subTest(turn=turn):
                    self.begin_capturing_logging()
                    map.turn = map.turn + turn
                    aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                    boardAnalysis = BoardAnalyzer(map, general)
                    boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
                    armyEngine.friendly_has_kill_threat = True
                    armyEngine.enemy_has_kill_threat = True
                    result = armyEngine.scan(2, mcts=True)
                    if debugMode:
                        self.render_sim_analysis(map, result)
                    # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                    self.assertTrue(result.best_result_state.captures_enemy)

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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                self.enable_search_time_limits_and_disable_debug_asserts()

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = False
                armyEngine.allow_enemy_no_op = True
                armyEngine.allow_friendly_no_op = True
                armyEngine.log_payoff_depth = 1
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
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
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis)
                armyEngine.friendly_has_kill_threat = True
                armyEngine.enemy_has_kill_threat = True
                # TODO switch to this method of parameterizing this
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis)
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, timeCap=0.05)
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis, timeCap=0.05)
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
                simHost.get_bot(general.player).use_mcts = True

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
                simHost.get_bot(general.player).use_mcts = True

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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], eklipz_bot.board_analysis)
        armyEngine.friendly_has_kill_threat = False
        # TODO TEST WITH BOTH KILL THREAT AND NOT KILL THREAT
        # TODO TEST WITH BOTH FORCED TOWARDS AND NOT FORCED TOWARDS
        armyEngine.enemy_has_kill_threat = True
        armyEngine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(map, [general])
        result = armyEngine.scan(4, mcts=True)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertNotEqual(map.GetTile(9, 8), result.expected_best_moves[0][0].dest, "should not do ridiculous dancing around on friendly tiles.")
        self.assertEqual(bArmy.tile, result.expected_best_moves[0][0].dest, "should immediately capture enemy army threatening to capture tiles.")
    
    def test_should_complete_scrim_army_intercept_instead_of_letting_enemy_cap_tiles(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_army_not_leave_gen_defenseless___Svxvcvovg---1--223.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 223, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 223)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                    allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '18,12->18,13->17,13->17,14->17,15->17,16->16,16')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=8)
        self.assertIsNone(winner)
        self.assertNoRepetition(simHost, minForRepetition=2)

    def test__deep_mcts_should_always_win__vs__brute_force__top_left_bottom_right(self):
        for playerWithMcts in [0, 1]:
            with self.subTest(playerWithMcts=playerWithMcts):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/even_playground_map_small__top_left_bot_right.txtmap'
                map, general, enemyGen = self.load_map_and_generals(mapFile, 399, fill_out_tiles=True)
                map.usernames[playerWithMcts] = 'mcts'
                map.usernames[(playerWithMcts + 1) % 2] = 'brute'
                self.reset_map_to_just_generals(map)
                self.begin_capturing_logging()

                self.enable_search_time_limits_and_disable_debug_asserts()

                simHost = GameSimulatorHost(map, player_with_viewer=-2)
                if general.player == playerWithMcts:
                    simHost.get_bot(general.player).use_mcts = True
                    simHost.get_bot(enemyGen.player).use_mcts = False
                else:
                    simHost.get_bot(general.player).use_mcts = False
                    simHost.get_bot(enemyGen.player).use_mcts = True
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1)
                self.assertEqual(playerWithMcts, winner)

    def test__deep_mcts_should_always_win__vs__brute_force__top_right_bottom_left(self):
        for playerWithMcts in [0, 1]:
            with self.subTest(playerWithMcts=playerWithMcts):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/even_playground_map_small__top_right_bot_left.txtmap'
                map, general, enemyGen = self.load_map_and_generals(mapFile, 399, fill_out_tiles=True)
                map.usernames[playerWithMcts] = 'mcts'
                map.usernames[(playerWithMcts + 1) % 2] = 'brute'
                self.reset_map_to_just_generals(map)
                self.begin_capturing_logging()

                self.enable_search_time_limits_and_disable_debug_asserts()

                simHost = GameSimulatorHost(map, player_with_viewer=-2)
                if general.player == playerWithMcts:
                    simHost.get_bot(general.player).use_mcts = True
                    simHost.get_bot(enemyGen.player).use_mcts = False
                else:
                    simHost.get_bot(general.player).use_mcts = False
                    simHost.get_bot(enemyGen.player).use_mcts = True
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.1)
                self.assertEqual(playerWithMcts, winner)
