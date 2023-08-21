import logging
import typing

from ArmyEngine import ArmyEngine, ArmySimResult
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import Tile, MapBase


class ArmyEngineTests(TestBase):

    def test_brute_force__armies_suicide(self):
        rawMap = """
|    |    |    |    |    
          aG1          
                    
                    
                    
     a25               
               b25     
                    
                    
                    
          bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
        result = armyEngine.scan_brute_force(5)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertEqual(0, result.best_result_state.tile_differential)
        self.assertEqual(0, result.best_result_state.city_differential)
        self.assertGreater(len(result.expected_best_moves), 1)
        # simHost = GameSimulatorHost(map, player_with_viewer=-2)
        # simHost.reveal_player_general(enemyGen.player, general.player, hidden=True)
        #
        #
        #
        # # give both players info about the others
        # simHost.apply_map_vision(0, map)
        # simHost.apply_map_vision(1, map)
        #
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=70)
        # self.assertIsNone(winner)

    def test_brute_force__a_can_cap_b_tiles_with_kill_threat(self):
        rawMap = """
|    |    |    |    |    
          aG1          
                    
     M               
                    b1
                
                    
                    
                    
a25  M    b25          
          bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan_brute_force(5)
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
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan_brute_force(4)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

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
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan_brute_force(5, logEvals=False)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

    def test_brute_force__detects_basic_forced_move(self):
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
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                blueHasPriority = ArmyEngine.player_has_priority(1, turn)
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan_brute_force(3, logEvals=True)
                if debugMode:
                    self.render_sim_analysis(map, result)

                # b must assume a will attack and block
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)

        def test_brute_force__detects_basic_forced_move(self):
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
            debugMode = True
            # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
            # Both should have half the board if this gens correctly..
            map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
            self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

            self.enable_search_time_limits_and_disable_debug_asserts()

            for turn in [0, 1]:
                with self.subTest(turn=turn):
                    blueHasPriority = ArmyEngine.player_has_priority(1, turn)
                    self.begin_capturing_logging()
                    map.turn = map.turn + turn
                    aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                    boardAnalysis = BoardAnalyzer(map, general)
                    boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
                    armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
                    baseState = armyEngine.get_base_board_state()
                    self.assertEqual(0, baseState.tile_differential)
                    self.assertEqual(0, baseState.city_differential)

                    result = armyEngine.scan_brute_force(3, logEvals=True)
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
            debugMode = True
            # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
            # Both should have half the board if this gens correctly..
            map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                    baseState = armyEngine.get_base_board_state()
                    self.assertEqual(0, baseState.tile_differential)
                    self.assertEqual(0, baseState.city_differential)

                    result = armyEngine.scan_brute_force(3, logEvals=True)
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
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                baseState = armyEngine.get_base_board_state()
                self.assertEqual(0, baseState.tile_differential)
                self.assertEqual(0, baseState.city_differential)

                result = armyEngine.scan_brute_force(2, logEvals=True)
                if debugMode:
                    self.render_sim_analysis(map, result)

                if ArmyEngine.player_has_priority(general.player, turn):
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                    self.assertFalse(result.best_result_state.captures_enemy)
                    self.assertTrue(result.best_result_state.kills_all_friendly_armies)
                    self.assertTrue(result.best_result_state.kills_all_enemy_armies)
                else:
                    self.assertFalse(result.best_result_state.captured_by_enemy)
                    self.assertTrue(result.best_result_state.captures_enemy)
                    self.assertFalse(result.best_result_state.kills_all_friendly_armies)
                    self.assertFalse(result.best_result_state.kills_all_enemy_armies)

    def test_brute_force__recognizes_wins_on_general_distances(self):
        rawMap = """
|    |    |    |    |    
     aG1               


          a25       b25
                 

     
M              
          bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                result = armyEngine.scan_brute_force(2)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertTrue(result.best_result_state.captures_enemy)

    def test_brute_force__recognizes_losses_on_general_distances(self):
        rawMap = """
|    |    |    |    |    
     bG1               



          b25       a25
                 

     
M              
          aG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = False
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                result = armyEngine.scan_brute_force(2)
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
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
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
                result = armyEngine.scan_brute_force(5)
                if debugMode:
                    self.render_sim_analysis(map, result)
                # b can make a run safely for a's general, but a has time to capture b if b does that (?)
                self.assertFalse(result.best_result_state.captured_by_enemy)
                self.assertFalse(result.best_result_state.captures_enemy)
                self.assertEqual(6, result.best_result_state.tile_differential)
                self.assertEqual(0, result.best_result_state.city_differential)

    def test_brute_force__b_can_chase_as_army(self):
        rawMap = """
|    |    |    |    |    
          aG1          
                    
                    
                    
                    
                    
                    
     M              
                    
     a23  bG25          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        t0_9 = map.GetTile(0,9)
        t1_9 = map.GetTile(1,9)
        t0_8 = map.GetTile(0,8)

        for turn in [0, 1]:
            with self.subTest(turn=turn):
                self.begin_capturing_logging()
                map.turn = map.turn + turn
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
                baseBoardState = armyEngine.get_base_board_state()
                # result = armyEngine.scan_brute_force(3, logEvals=True)
                simState1 = armyEngine.get_next_board_state(
                    map.turn + 1,
                    baseBoardState,
                    frMove=Move(t1_9, t0_9),
                    enMove=Move(enemyGen, t1_9),
                    logEvals=True
                )
                simState2 = armyEngine.get_next_board_state(
                    map.turn + 2,
                    simState1,
                    frMove=Move(t0_9, t0_8),
                    enMove=Move(t1_9, t0_9),
                    logEvals=True
                )

                # chasing another army should capture it within 2 moves, always
                self.assertEqual(0, len(simState2.friendly_living_armies))
                self.assertEqual(0, len(simState2.enemy_living_armies))
                for tile in simState2.sim_tiles.values():
                    self.assertEqual(1, tile.army)
                    self.assertEqual(1, tile.player)
                self.assertFalse(simState2.captured_by_enemy)
                self.assertFalse(simState2.captures_enemy)
                self.assertEqual(0, simState2.tile_differential)
                self.assertEqual(0, simState2.city_differential)

    def test_brute_force__a_can_cap_bs_general(self):
        rawMap = """
|    |    |    |    |    
          aG1          





               b25
     M              

a25       bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = True
        # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
        # Both should have half the board if this gens correctly..
        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 100)
        self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

        self.enable_search_time_limits_and_disable_debug_asserts()

        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis)
        result = armyEngine.scan_brute_force(3)
        if debugMode:
            self.render_sim_analysis(map, result)
        self.assertTrue(result.best_result_state.captures_enemy)

        # simHost = GameSimulatorHost(map, player_with_viewer=-2)
        # simHost.reveal_player_general(enemyGen.player, general.player, hidden=True)
        #
        #
        #
        # # give both players info about the others
        # simHost.apply_map_vision(0, map)
        # simHost.apply_map_vision(1, map)
        #
        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.5, turns=70)
        # self.assertIsNone(winner)

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

    def render_sim_analysis(self, map: MapBase, simResult: ArmySimResult):
        aMoves = [aMove for aMove, bMove in simResult.expected_best_moves]
        bMoves = [bMove for aMove, bMove in simResult.expected_best_moves]
        self.render_moves(map, str(simResult), aMoves, bMoves)