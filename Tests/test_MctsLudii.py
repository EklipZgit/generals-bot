from ArmyEngine import ArmyEngine, ArmySimResult
from BoardAnalyzer import BoardAnalyzer
from Engine.ArmyEngineModels import SimTile
from MctsLudii import MctsDUCT, Context, Game
from TestBase import TestBase


class MctsLudiiTests(TestBase):
    def test_biased_move_selector__prioritizes_out_of_scrim_captures(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1

          b1
     b1   b10       a1
     M    a1   a1   a10
          M        
          bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for friendlyNearbyTilesAlsoInScrim in [False, True]:
            with self.subTest(friendlyNearbyTilesAlsoInScrim=friendlyNearbyTilesAlsoInScrim):
                # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
                # Both should have half the board if this gens correctly..
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                state = armyEngine.get_base_board_state()

                context = Context()
                game = Game(general.player, [enemyGen.player])
                context.set_initial_board_state(armyEngine, state, game, map.turn)
                # state.sim_tiles[map.GetTile()]
                expectBDest = map.GetTile(2, 7)  # a should cap the tiles downward rather than its own tile next to it
                expectADest = map.GetTile(4, 8)  # b should cap the a tile below it

                if friendlyNearbyTilesAlsoInScrim:
                    for tile in map.get_all_tiles():
                        if tile.player >= 0:
                            state.sim_tiles[tile] = SimTile(tile)

                    del state.sim_tiles[expectBDest]
                    del state.sim_tiles[expectADest]

                bestFr = Game.pick_best_move_heuristic(general.player, state.generate_friendly_moves(), state, prevMove=None)
                bestEn = Game.pick_best_move_heuristic(enemyGen.player, state.generate_enemy_moves(), state, prevMove=None)

                if debugMode:
                    self.render_sim_analysis(map, ArmySimResult(state))

                self.assertEqual(aArmy.tile, bestFr.source)
                self.assertEqual(expectADest, bestFr.dest)

                self.assertEqual(bArmy.tile, bestEn.source)
                self.assertEqual(expectBDest, bestEn.dest)

    def test_biased_move_selector__prioritizes_in_scrim_captures(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1

          b1
     b1   b10       a1
     M    a1   a1   a10
          M        
          bG1          
|    |    |    |    |    
loadAsIs=True
bot_player_index=0
bot_target_player=1
aTiles=20
bTiles=20
"""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for friendlyNearbyTilesAlsoInScrim in [False, True]:
            with self.subTest(friendlyNearbyTilesAlsoInScrim=friendlyNearbyTilesAlsoInScrim):
                # 5x10 map with gens opposite, both armies near middle, neither can do anything special.
                # Both should have half the board if this gens correctly..
                map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 102)
                self.ensure_player_tiles_and_scores(map, general, generalTileCount=20)

                self.begin_capturing_logging()
                aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

                boardAnalysis = BoardAnalyzer(map, general)
                boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

                mcts: MctsDUCT = MctsDUCT()
                armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
                state = armyEngine.get_base_board_state()

                context = Context()
                game = Game(general.player, [enemyGen.player])
                context.set_initial_board_state(armyEngine, state, game, map.turn)
                # state.sim_tiles[map.GetTile()]
                expectBDest = map.GetTile(2, 7)  # a should cap the tiles downward rather than its own tile next to it
                expectADest = map.GetTile(4, 8)  # b should cap the a tile below it
                # same as previous test, except the tiles are in the sim area now
                state.sim_tiles[expectBDest] = SimTile(expectBDest)
                state.sim_tiles[expectADest] = SimTile(expectADest)

                if friendlyNearbyTilesAlsoInScrim:
                    for tile in map.get_all_tiles():
                        if tile.player >= 0:
                            state.sim_tiles[tile] = SimTile(tile)

                bestFr = Game.pick_best_move_heuristic(general.player, state.generate_friendly_moves(), state, prevMove=None)
                bestEn = Game.pick_best_move_heuristic(enemyGen.player, state.generate_enemy_moves(), state, prevMove=None)

                if debugMode:
                    self.render_sim_analysis(map, ArmySimResult(state))

                self.assertEqual(aArmy.tile, bestFr.source)
                self.assertEqual(expectADest, bestFr.dest)

                self.assertEqual(bArmy.tile, bestEn.source)
                self.assertEqual(expectBDest, bestEn.dest)

    def test_biased_move_selector__prioritizes_out_of_scrim_captures_over_in_scrim_captures(self):
        rawMap = """
|    |    |    |    |    
          aG1          

     M    M           
                    b1

          b1
     a1   b10       b1
     M    a1   a1   a10
          M        
          bG1          
|    |    |    |    |    
loadAsIs=True
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

        self.begin_capturing_logging()
        aArmy, bArmy = self.get_test_army_tiles(map, general, enemyGen)

        boardAnalysis = BoardAnalyzer(map, general)
        boardAnalysis.rebuild_intergeneral_analysis(enemyGen)

        mcts: MctsDUCT = MctsDUCT()
        armyEngine = ArmyEngine(map, [aArmy], [bArmy], boardAnalysis, mctsRunner=mcts)
        state = armyEngine.get_base_board_state()

        context = Context()
        game = Game(general.player, [enemyGen.player])
        context.set_initial_board_state(armyEngine, state, game, map.turn)
        # state.sim_tiles[map.GetTile()]
        bInScrim = map.GetTile(2, 7)  # a should cap the tiles downward rather than its own tile next to it
        aInScrim = map.GetTile(4, 8)  # b should cap the a tile below it
        # these tiles should be prioritized less than the out-of-scrim captures available in this test
        state.sim_tiles[bInScrim] = SimTile(bInScrim)
        state.sim_tiles[aInScrim] = SimTile(aInScrim)

        expectedBDest = map.GetTile(1, 6)  # should move left because the tile below is already in the sim
        expectedADest = map.GetTile(4, 6)  # should move up because the tile below is already in the sim

        bestFr = Game.pick_best_move_heuristic(general.player, state.generate_friendly_moves(), state, prevMove=None)
        bestEn = Game.pick_best_move_heuristic(enemyGen.player, state.generate_enemy_moves(), state, prevMove=None)

        if debugMode:
            self.render_sim_analysis(map, ArmySimResult(state))

        self.assertEqual(aArmy.tile, bestFr.source)
        self.assertEqual(expectedADest, bestFr.dest)

        self.assertEqual(bArmy.tile, bestEn.source)
        self.assertEqual(expectedBDest, bestEn.dest)
