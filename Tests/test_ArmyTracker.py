import logging

from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class ArmyTrackerTests(TestBase):
    def assertNoFogMismatches(
            self,
            simHost: GameSimulatorHost,
            player: int,
            excludeEntangledFog: bool = True,
            excludeFogMoves: bool = False
    ):
        realMap = simHost.sim.sim_map
        playerMap = simHost.get_player_map(player)
        playerBot = simHost.get_bot(player)
        if playerBot.armyTracker.lastTurn != realMap.turn:
            playerBot.init_turn()

        failures = []
        for tile in realMap.get_all_tiles():
            playerTile = playerMap.GetTile(tile.x, tile.y)
            if not playerTile.visible:
                if playerTile.lastSeen < playerMap.turn - 2 and excludeFogMoves:
                    continue

                playerFogArmy = playerBot.armyTracker.armies.get(playerTile, None)
                if playerFogArmy is not None:
                    if len(playerFogArmy.entangledArmies) > 0 and excludeEntangledFog:
                        # make sure ONE of the fogged armies is correct, if not, this one MUST be correct:
                        atLeastOneCorrect = False
                        for fogArmy in playerFogArmy.entangledArmies:
                            mapTile = realMap.GetTile(fogArmy.tile.x, fogArmy.tile.y)
                            if fogArmy.value + 1 == mapTile.army:
                                atLeastOneCorrect = True
                        if atLeastOneCorrect:
                            continue

                    if playerFogArmy.value + 1 != tile.army:
                        failures.append(f'ARMY expected army {repr(tile)}, found {repr(playerFogArmy)} {playerFogArmy.value + 1}')
                    if playerFogArmy.player != tile.player:
                        failures.append(f'ARMY expected player {repr(tile)}, found {repr(playerFogArmy)} {playerFogArmy.value + 1}')
                    continue

            if not playerTile.discovered and playerTile.army == 0 and playerTile.player == -1:
                continue

            if playerTile.army != tile.army:
                failures.append(f'expected army {repr(tile)}, found {repr(playerTile)}')
            if playerTile.player != tile.player:
                failures.append(f'expected player {repr(tile)}, found {repr(playerTile)}')

        if len(failures) > 0:
            self.fail(f'TURN {simHost.sim.turn}\r\n' + '\r\n'.join(failures))

    def test_small_gather_adj_to_fog_should_not_double_gather_from_fog(self):
        # SEE TEST WITH THE SAME NAME IN test_Map.py which proves that this bug is not the map engines fault, and is instead armytracker emergence as the cause.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/small_gather_adj_to_fog_should_not_double_gather_from_fog___rgI9fxNa3---a--451.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 451, fill_out_tiles=True)
        rawMap, gen = self.load_map_and_general(mapFile, 451)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.queue_player_moves_str(general.player, "8,12 -> 7,12 -> 8,12 -> 7,12")
        simHost.queue_player_moves_str(enemyGeneral.player, "10,13 -> 10,14")

        self.begin_capturing_logging()

        if debugMode:
            simHost.run_sim(run_real_time=debugMode, turn_time=10, turns=5)

        bot = simHost.get_bot()
        enemyPlayer = (gen.player + 1) & 1

        m = simHost.get_player_map()

        self.assertEqual(3, m.GetTile(10, 13).army)
        self.assertEqual(3, m.GetTile(11, 13).army)
        self.assertEqual(8, m.GetTile(10, 14).army)
        self.assertEqual(6, m.GetTile(9, 13).army)

        simHost.execute_turn()
        bot.init_turn()

        # NONE of this should have changed via army emergence.
        self.assertEqual(1, m.GetTile(10, 13).army)
        self.assertEqual(3, m.GetTile(11, 13).army)
        self.assertEqual(6, m.GetTile(9, 13).army)
        self.assertEqual(10, m.GetTile(10, 14).army)
        self.assertEqual(2, m.GetTile(10, 14).delta.armyDelta)
        self.assertEqual(-2, m.GetTile(10, 13).delta.armyDelta)

        # Except, now fromTile / toTile should have updated.
        self.assertEqual(m.GetTile(10, 13), m.GetTile(10, 14).delta.fromTile)
        self.assertEqual(m.GetTile(10, 14), m.GetTile(10, 13).delta.toTile)
        self.assertNoFogMismatches(simHost, general.player)

    def test_should_recognize_army_collision_from_fog(self):
        for frArmy, enArmy, expectedTileArmy in [(53, 58, 0), (52, 58, -1), (62, 58, 11), (42, 58, -9), (54, 58, 1)]:
            with self.subTest(frArmy=frArmy, enArmy=enArmy, expectedTileArmy=expectedTileArmy):
                mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

                self.enable_search_time_limits_and_disable_debug_asserts()

                # Grant the general the same fog vision they had at the turn the map was exported
                rawMap, _ = self.load_map_and_general(mapFile, 136)

                map.GetTile(5, 15).army = frArmy
                rawMap.GetTile(5, 15).army = frArmy
                map.GetTile(12, 16).army = enArmy
                rawMap.GetTile(12, 16).army = enArmy

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(general.player,      "5,15->6,15->7,15->8,15->9,15")
                simHost.queue_player_moves_str(enemyGeneral.player, "12,16->11,16->10,16->10,15->9,15")

                # debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                # if debugMode:
                #     self.begin_capturing_logging()
                #
                #     simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=6)
                #     self.assertIsNone(winner)
                #     continue

                bot = simHost.get_bot()
                m = simHost.get_player_map()
                # alert enemy of the player general
                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
                origArmy = bot.armyTracker.armies[m.GetTile(12, 16)]
                origName = origArmy.name

                t11_16 = m.GetTile(11, 16)
                t12_17 = m.GetTile(12, 17)
                self.begin_capturing_logging()
                simHost.execute_turn()
                bot.init_turn()

                # ok, now that army should be duplicated on 12,17 and 11,16 because we dont know where the tile went
                entangledIncorrect = bot.armyTracker.armies[m.GetTile(12, 17)]
                entangledCorrect = bot.armyTracker.armies[t11_16]
                self.assertTrue(origArmy.scrapped)
                self.assertEqual(origName, origArmy.name)
                self.assertEqual(origName, entangledIncorrect.name)
                self.assertEqual(origName, entangledCorrect.name)
                self.assertIn(entangledIncorrect, entangledCorrect.entangledArmies)
                self.assertIn(entangledCorrect, entangledIncorrect.entangledArmies)
                self.assertNotIn(origArmy.tile, bot.armyTracker.armies)
                self.assertFalse(entangledIncorrect.scrapped)
                self.assertFalse(entangledCorrect.scrapped)
                self.assertEqual(57, t11_16.army)
                self.assertEqual(enemyGeneral.player, t11_16.player)
                self.assertEqual(57, t12_17.army)
                self.assertEqual(enemyGeneral.player, t12_17.player)
                self.assertEqual(0, t11_16.delta.armyDelta)
                self.assertEqual(0, t12_17.delta.armyDelta)
                self.assertEqual(enemyGeneral.player, t11_16.player)

                simHost.execute_turn()
                bot.init_turn()
                # ok now that army comes out of the fog at 10,16 again, should be the same army still, and nuke the entangled armies:
                emergedFirst = bot.armyTracker.armies[m.GetTile(10, 16)]
                self.assertEqual(origName, emergedFirst.name)
                self.assertEqual(origName, entangledIncorrect.name)
                self.assertEqual(origName, entangledCorrect.name)
                self.assertNotIn(entangledIncorrect, entangledCorrect.entangledArmies)
                self.assertEqual(entangledCorrect, emergedFirst)
                self.assertFalse(emergedFirst.scrapped)
                # reuses the entangled army that was resolved as the fog emergence source.
                self.assertTrue(entangledIncorrect.scrapped)
                self.assertNotIn(entangledIncorrect.tile, bot.armyTracker.armies)
                # the correct entangled tile should be the players and have 1 army.
                self.assertEqual(1, t11_16.army)
                self.assertEqual(enemyGeneral.player, t11_16.player)
                # The incorrect entangled tile should have gone back to being neutral, now that we know it wasn't the army dest
                self.assertEqual(0, t12_17.army)
                self.assertEqual(-1, t12_17.player)
                # TODO this assert should be correct, but fails at the moment
                # self.assertEqual(0, t11_16.delta.armyDelta)
                # self.assertEqual(0, t12_17.delta.armyDelta)

                simHost.execute_turn()
                bot.init_turn()

                t10_15 = m.GetTile(10, 15)
                # ok now that army goes BACK into the fog, should split to 10,15 and 11,16 again.
                entangledCorrect = bot.armyTracker.armies[t10_15]
                entangledIncorrect = bot.armyTracker.armies[t11_16]
                self.assertTrue(emergedFirst.scrapped)
                self.assertEqual(origName, emergedFirst.name)
                self.assertEqual(origName, entangledIncorrect.name)
                self.assertEqual(origName, entangledCorrect.name)
                self.assertIn(entangledIncorrect, entangledCorrect.entangledArmies)
                self.assertIn(entangledCorrect, entangledIncorrect.entangledArmies)
                self.assertNotIn(emergedFirst.tile, bot.armyTracker.armies)
                self.assertFalse(entangledIncorrect.scrapped)
                self.assertFalse(entangledCorrect.scrapped)
                self.assertEqual(56, t11_16.army)
                self.assertEqual(0, t11_16.delta.armyDelta)

                playerArmy = bot.armyTracker.armies[m.GetTile(8, 15)]
                playerArmyName = playerArmy.name

                simHost.execute_turn()
                bot.init_turn()
                collisionTile = m.GetTile(9, 15)
                # ok now that army comes out of the fog, COLLIDING with our generals army that is moving 8,15->9,15
                collision = bot.armyTracker.armies[collisionTile]
                #fr army collects 5 more than enemy army, adjust by 5
                frCollisionArmy = frArmy + 5
                if frCollisionArmy >= enArmy:  # >= because player wins the tiebreak in this specific cycle
                    self.assertEqual(playerArmyName, collision.name)
                    self.assertTrue(entangledCorrect.scrapped)
                    self.assertEqual(playerArmy, collision)
                else:
                    self.assertEqual(origName, collision.name)
                    self.assertFalse(entangledCorrect.scrapped)
                    self.assertEqual(entangledCorrect, collision)

                self.assertEqual(origName, entangledIncorrect.name)
                self.assertEqual(origName, entangledCorrect.name)
                self.assertNotIn(entangledIncorrect, entangledCorrect.entangledArmies)
                self.assertFalse(collision.scrapped, "collision army should always stick around for a turn")
                # reuses the entangled army that was resolved as the fog emergence source.
                self.assertTrue(entangledIncorrect.scrapped)
                self.assertNotIn(entangledIncorrect.tile, bot.armyTracker.armies)

                # Also assert that when ONLY one fog resolution happened, we 100% update the fog source tile to be the enemy player and army amount.
                self.assertNotIn(t11_16, bot.armyTracker.armies, "should have scrapped the entangled army that collided on 9,15")
                self.assertEqual(collisionTile.player, collision.player, "the player who owns the tile should be the one whose army gets left.")

                simHost.execute_turn()
                bot.init_turn()

                if collision.value > 8:
                    self.assertFalse(collision.scrapped)
                else:
                    self.assertTrue(collision.scrapped)
            with self.subTest(careLess=True, frArmy=frArmy, enArmy=enArmy, expectedTileArmy=expectedTileArmy):
                # eh, dunno how much I care about this
                self.assertEqual(enemyGeneral.player, t11_16.player, "eh, dunno how much I care but technically we know for sure that this tile was crossed despite undiscovered, should be en player.")
                self.assertEqual(1, t11_16.army, "eh, dunno how much I care but technically we know for sure that this tile was crossed despite undiscovered, should have army 1")

    def test_should_track_army_fog_island_capture(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_track_army_fog_island_capture___HlPWKpCT3---b--499.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 499, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 499)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,13->10,13->10,12->9,12')
        simHost.queue_player_moves_str(general.player, '2,9->3,9->4,9->3,9')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()

        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=4)
        self.assertIsNone(winner)
    
    def test_should_not_duplicate_fog_island_armies(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_fog_island_armies___rxEQ8qJR2---b--431.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 431, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 431)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '7,16->7,15')
        simHost.queue_player_moves_str(general.player, '10,7->11,7')

        m = simHost.get_player_map(general.player)
        bot = simHost.get_bot(general.player)
        t7_16 = m.GetTile(7, 16) # army moves from here
        t7_15 = m.GetTile(7, 15) # army captures here, dropping everything around it into fog
        t7_14 = m.GetTile(7, 14)
        t6_15 = m.GetTile(6, 15)
        t8_15_mtn = m.GetTile(8, 15)
        self.assertEqual(25, t7_16.army)
        self.assertEqual(2, t7_15.army)
        self.assertEqual(3, t6_15.army)
        self.assertEqual(1, t7_14.army)
        self.assertEqual(0, t8_15_mtn.army)
        self.assertTrue(t8_15_mtn.isMountain)
        enArmy = bot.armyTracker.armies[t7_16]

        self.begin_capturing_logging()
        simHost.execute_turn()
        self.assertEqual(1, t7_16.army)
        self.assertEqual(22, t7_15.army)
        self.assertEqual(enemyGeneral.player, t7_15.player)
        self.assertEqual(3, t6_15.army)
        self.assertEqual(1, t7_14.army)
        self.assertEqual(0, t8_15_mtn.army)
        bot.init_turn()

        self.assertEqual(1, t7_16.army)
        self.assertEqual(22, t7_15.army)
        self.assertEqual(enemyGeneral.player, t7_15.player)
        self.assertEqual(3, t6_15.army)
        self.assertEqual(1, t7_14.army)
        self.assertEqual(0, t8_15_mtn.army)

        self.assertEqual(t7_15, enArmy.tile)
        self.assertEqual(0, len(enArmy.entangledArmies))
        self.assertEqual(21, enArmy.value)
        self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_duplicate_half_visible_fog_island_armies(self):
        mapFile = 'GameContinuationEntries/should_not_duplicate_half_visible_fog_island_armies___rxEQ8qJR2---b--398.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 398, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 398)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,16->5,15')
        simHost.queue_player_moves_str(general.player, '5,15->4,15')

        # debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        # if debugMode:
        #     simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
        #     simHost.run_sim(run_real_time=True, turn_time=5.0, turns = 2)
        #     return

        m = simHost.get_player_map(general.player)
        bot = simHost.get_bot(general.player)
        t3_16 = m.GetTile(3, 16) # should be a mountain, and never a 'fromTile'
        t5_16 = m.GetTile(5, 16) # army moves from here
        t5_15 = m.GetTile(5, 15) # army captures here, dropping everything around it into fog. Player WAS trying to move this tile to 4,15
        t4_15 = m.GetTile(4, 15)
        t4_14 = m.GetTile(4, 14)
        t4_16_enGen = m.GetTile(4, 16)

        self.assertEqual(0, t3_16.delta.armyDelta)
        self.assertEqual(0, t3_16.army)
        self.assertIsNone(t4_16_enGen.delta.fromTile)
        self.assertIsNone(t3_16.delta.toTile)

        self.assertEqual(38, t5_16.army)
        self.assertEqual(12, t5_15.army)
        self.assertEqual(1, t4_15.army)
        self.assertEqual(1, t4_14.army)
        self.assertEqual(2, t4_16_enGen.army)
        enArmy = bot.armyTracker.armies[t5_16]
        enArmyName = enArmy.name

        self.begin_capturing_logging()
        simHost.execute_turn()

        self.assertEqual(0, t3_16.delta.armyDelta)
        self.assertEqual(0, t3_16.army)
        self.assertIsNone(t4_16_enGen.delta.fromTile)
        self.assertIsNone(t3_16.delta.toTile)

        self.assertEqual(1, t5_16.army)
        self.assertEqual(25, t5_15.army)
        self.assertEqual(enemyGeneral.player, t5_15.player)
        self.assertEqual(1, t4_15.army)
        self.assertEqual(1, t4_14.army)
        self.assertEqual(2, t4_16_enGen.army)
        self.assertNotIn(t4_15, bot.armyTracker.armies)
        self.assertNotIn(m.GetTile(4,18), bot.armyTracker.armies)
        bot.init_turn()

        self.assertEqual(0, t3_16.delta.armyDelta)
        self.assertEqual(0, t3_16.army)
        self.assertIsNone(t4_16_enGen.delta.fromTile)
        self.assertIsNone(t3_16.delta.toTile)

        self.assertEqual(1, t5_16.army)
        self.assertEqual(25, t5_15.army)
        self.assertEqual(enemyGeneral.player, t5_15.player)
        self.assertEqual(1, t4_15.army)
        self.assertEqual(1, t4_14.army)
        self.assertEqual(2, t4_16_enGen.army)
        self.assertNotIn(t4_15, bot.armyTracker.armies)
        self.assertNotIn(m.GetTile(4,18), bot.armyTracker.armies)

        self.assertEqual(t5_15, enArmy.tile)
        self.assertEqual(0, len(enArmy.entangledArmies))
        self.assertEqual(24, enArmy.value)
        self.assertEqual(enArmyName, enArmy.name)
        self.assertFalse(enArmy.scrapped)
        self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_duplicate_army_when_en_chasing_near_fog(self):
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_when_en_chasing_near_fog___rxEQ8qJR2---b--397.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 397, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 397)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,16->5,16')
        simHost.queue_player_moves_str(general.player, '5,16->5,15')

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        self.begin_capturing_logging()
        if debugMode:
            simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
            winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
            self.assertIsNone(winner)

        m = simHost.get_player_map(general.player)
        bot = simHost.get_bot(general.player)
        t5_16 = m.GetTile(5, 16) # fr army moves from here
        t5_15 = m.GetTile(5, 15) # fr army moves to here
        t3_16_mtn = m.GetTile(3, 16)
        t4_17 = m.GetTile(4, 17) # army gets duplicated here
        t4_16_enGen = m.GetTile(4, 16) # en army moves from here to 5,16

        self.assertEqual(14, t5_16.army)
        self.assertEqual(1, t5_15.army)
        self.assertEqual(0, t3_16_mtn.army)
        self.assertEqual(1, t4_17.army)
        self.assertEqual(40, t4_16_enGen.army)
        enArmy = bot.armyTracker.armies[t4_16_enGen]
        enArmyName = enArmy.name
        frArmy = bot.armyTracker.armies[t5_16]
        frArmyName = frArmy.name

        self.begin_capturing_logging()
        simHost.execute_turn()

        self.assertEqual(38, t5_16.army)
        self.assertEqual(12, t5_15.army)
        self.assertEqual(general.player, t5_15.player)
        self.assertEqual(enemyGeneral.player, t5_16.player)
        self.assertEqual(0, t3_16_mtn.army)
        self.assertEqual(1, t4_17.army)
        self.assertNotIn(t4_17, bot.armyTracker.armies)
        self.assertNotIn(t3_16_mtn, bot.armyTracker.armies)
        self.assertEqual(2, t4_16_enGen.army)
        bot.init_turn()

        self.assertEqual(t5_15, frArmy.tile)
        self.assertIn(t5_15, bot.armyTracker.armies)

        self.assertEqual(38, t5_16.army)
        self.assertEqual(12, t5_15.army)
        self.assertEqual(general.player, t5_15.player)
        self.assertEqual(enemyGeneral.player, t5_16.player)
        self.assertEqual(0, t3_16_mtn.army)
        self.assertEqual(1, t4_17.army)
        self.assertNotIn(t4_17, bot.armyTracker.armies)
        self.assertNotIn(t3_16_mtn, bot.armyTracker.armies)
        self.assertEqual(2, t4_16_enGen.army)

        self.assertEqual(t5_15, frArmy.tile)
        self.assertEqual(0, len(frArmy.entangledArmies))
        self.assertEqual(11, frArmy.value)
        self.assertEqual(frArmyName, frArmy.name)
        self.assertFalse(frArmy.scrapped)

        self.assertEqual(t5_16, enArmy.tile)
        self.assertEqual(0, len(enArmy.entangledArmies))
        self.assertEqual(37, enArmy.value)
        self.assertEqual(enArmyName, enArmy.name)
        self.assertFalse(enArmy.scrapped)
        self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_duplicate_army_into_fog_when_running_into_other_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_into_fog_when_running_into_other_fog___SxvzBPWR2---b--427.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 427, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 427)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,12->9,12->8,12->7,12->7,11->7,10')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()

        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=True))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

    def template(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_gather_army_exit_from_fog___BeXQydQAn---b--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 243)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)
    
    def test_should_not_duplicate_gather_army_exit_from_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_gather_army_exit_from_fog___BeXQydQAn---b--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        # self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 243)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,3->9,3->9,4->9,5->8,5->8,4')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)
    
    def test_should_not_resolve_fog_path_for_normal_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_resolve_fog_path_for_normal_move___b-TEST__259fdd8d-1e8d-469c-8dbb-d1cfca2a67eb---1--245.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 245, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 245)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,4->9,5')
        simHost.queue_player_moves_str(general.player, '8,4->9,4')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)

    def test_should_not_perform_army_increment_or_city_increment_on_initial_test_map_load(self):
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_back_into_fog_on_small_player_intersection___HeEzmHU03---0--350.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 350, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 350)

        simHost = GameSimulatorHost(
            map,
            player_with_viewer=general.player,
            playerMapVision=rawMap,
            allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_duplicate_army_back_into_fog_on_small_player_army_collision(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_back_into_fog_on_small_player_intersection___HeEzmHU03---0--350.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 351, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 351)
        
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,9->5,8')
        simHost.queue_player_moves_str(general.player, '4,8->5,8')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=True))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=2)
        self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_duplicate_army_collision_backwards_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_collision_backwards_into_fog___reQb1i8Rh---0--285.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 285, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 285)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,9->12,9')
        simHost.queue_player_moves_str(general.player, '11,9->12,9')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=True))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=2)
        # self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_warp_army_through_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_warp_army_through_fog___NblaO2209---1--392.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 392, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 392)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '20,1->21,1->21,2->21,3->21,4->21,5->21,6->20,6')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player, hidden=True)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

    def test_should_intercept_army_that_enters_fog__army_tracker_not_predicting_fog_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_intercept_army_in_fog___BWe8LBMww---0--271.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 271, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 271)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player,
                                       '18,9->18,8->17,8->16,8->15,8->15,7->14,7->14,6->13,6->12,6->12,5->12,4->11,4->10,4->9,4->8,4->7,4->6,4->6,3')
        bot = simHost.get_bot(general.player)
        bot.curPath = Path()
        bot.curPath.add_next(self.get_player_tile(11, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(12, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(13, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(14, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(15, 4, simHost.sim, general.player))
        bot.curPath.add_next(self.get_player_tile(15, 5, simHost.sim, general.player))

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.sim.ignore_illegal_moves = True
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=20)
        self.assertIsNone(winner)

    
    def test_should_not_duplicate_stationary_army_into_fog_when_attacking_it(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_stationary_army_into_fog_when_attacking_it___5qzSTHi-r---1--348.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 348, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, 348)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_duplicate_stationary_army_into_fog_when_attacking_it
