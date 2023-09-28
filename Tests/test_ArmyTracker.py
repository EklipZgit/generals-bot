import logging

from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class ArmyTrackerTests(TestBase):
    def assertNoFogMismatches(
            self,
            simHost: GameSimulatorHost,
            player: int = -1,
            excludeEntangledFog: bool = True,
            excludeFogMoves: bool = False
    ):
        realMap = simHost.sim.sim_map

        players = [i for i, botHost in enumerate(simHost.bot_hosts) if botHost is not None]
        if player > -1:
            players = [player]

        failures = []

        for player in players:
            playerMap = simHost.get_player_map(player)
            playerBot = simHost.get_bot(player)
            if playerBot.armyTracker.lastTurn != realMap.turn:
                playerBot.init_turn()

            for tile in realMap.get_all_tiles():
                playerTile = playerMap.GetTile(tile.x, tile.y)
                if not playerTile.visible:
                    # TODO FIX THIS
                    if playerTile.lastSeen < playerMap.turn - 2 and excludeFogMoves:
                        continue
                    #
                    # pTilePlayer = simHost.sim.players[playerTile.player]
                    # if pTilePlayer.move_history[-1] is not None and
                    if playerTile.isGeneral != tile.isGeneral:
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
                            failures.append(f'(bot{player}) ARMY expected tile.army {tile.army} on {repr(tile)}, found ARMY {repr(playerFogArmy)} playerFogArmy.value + 1 {playerFogArmy.value + 1}')
                        if playerFogArmy.player != tile.player:
                            failures.append(f'(bot{player}) ARMY expected player {tile.player} on {repr(tile)}, found {repr(playerFogArmy)} {playerFogArmy.player}')
                        continue

                if not playerTile.discovered and playerTile.army == 0 and playerTile.player == -1:
                    continue

                if playerTile.army != tile.army:
                    failures.append(f'(bot{player}) expected tile.army {tile.army} on {repr(tile)}, found {playerTile.army} - {repr(playerTile)}')
                if playerTile.player != tile.player:
                    failures.append(f'(bot{player}) expected player {tile.player} on {repr(tile)}, found {playerTile.player} - {repr(playerTile)}')
                if playerTile.isCity != tile.isCity:
                    failures.append(f'(bot{player}) expected isCity {tile.isCity} on {repr(tile)}, found {playerTile.isCity} - {repr(playerTile)}')

        if len(failures) > 0:
            self.fail(f'TURN {simHost.sim.turn}\r\n' + '\r\n'.join(failures))

    def test_small_gather_adj_to_fog_should_not_double_gather_from_fog(self):
        # SEE TEST WITH THE SAME NAME IN test_Map.py which proves that this bug is not the map engines fault, and is instead armytracker emergence as the cause.
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/small_gather_adj_to_fog_should_not_double_gather_from_fog___rgI9fxNa3---a--451.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 451, fill_out_tiles=True)
        rawMap, gen = self.load_map_and_general(mapFile, 451)

        self.enable_search_time_limits_and_disable_debug_asserts()

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.queue_player_moves_str(general.player, "8,12 -> 7,12 -> 8,12 -> 7,12")
        simHost.queue_player_moves_str(enemyGeneral.player, "10,13 -> 10,14")

        self.begin_capturing_logging()

        if debugMode:
            simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player))
            simHost.run_sim(run_real_time=debugMode, turn_time=5, turns=2)
            return

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
                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=136)

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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=499)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=431)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=398)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=397)
        
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
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=427)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,12->9,12->8,12->7,12->7,11->7,10')

        # alert enemy of the player general
        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()

        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

    def template(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_gather_army_exit_from_fog___BeXQydQAn---b--243.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)

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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=245)
        
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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=350)

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

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=351)
        
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,9->5,8')
        simHost.queue_player_moves_str(general.player, '4,8->5,8')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=2)
        self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_duplicate_army_collision_backwards_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_duplicate_army_collision_backwards_into_fog___reQb1i8Rh---0--285.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 285, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=285)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '13,9->12,9')
        simHost.queue_player_moves_str(general.player, '11,9->12,9')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=2)
        # self.assertNoFogMismatches(simHost, general.player)
    
    def test_should_not_warp_army_through_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_warp_army_through_fog___NblaO2209---1--392.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 392, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=392)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '20,1->21,1->21,2->21,3->21,4->21,5->21,6->20,6')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        simHost.reveal_player_general(playerToReveal=enemyGeneral.player, playerToRevealTo=general.player, hidden=True)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=10)
        self.assertIsNone(winner)

    def test_should_intercept_army_that_enters_fog__army_tracker_not_predicting_fog_moves(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_intercept_army_in_fog___BWe8LBMww---0--271.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 271, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=271)
        
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for extraArmyAmt in [-2, -1, 0, 1, 2]:
            with self.subTest(extraArmyAmt=extraArmyAmt):
                mapFile = 'GameContinuationEntries/should_not_duplicate_stationary_army_into_fog_when_attacking_it___5qzSTHi-r---1--348.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 348, fill_out_tiles=True)

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=348)
                rawMap.GetTile(19, 2).army += extraArmyAmt
                map.GetTile(19, 2).army += extraArmyAmt

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(general.player, '19,2->19,1')

                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
                self.assertIsNone(winner)
    
    def test_should_detect_cities_based_on_incontroversial_moves_from_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_detect_cities_based_on_incontroversial_moves_from_fog___z2GMYKXZ1---1--388.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 388, fill_out_tiles=True)
        actualCity = map.GetTile(4, 9)
        map.update_visible_tile(4, 9, enemyGeneral.player, 165, is_city=True, is_general=False)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=388)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '4,9->5,9')

        bot = simHost.get_bot(general.player)
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][4][3] = 11
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][5][3] = 11
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][5][4] = 11
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][5][5] = 5
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][4][5] = 3

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=3)
        self.assertIsNone(winner)

        botTile = self.get_player_tile(4, 9, simHost.sim, general.player)
        self.assertTrue(botTile.isCity)
        self.assertEqual(enemyGeneral.player, botTile.player)
        self.assertEqual(2, botTile.army)

        # should also run army emergence to indicate that the player is probably behind the wall if broken through a wall
        emergeTile1 = self.get_player_tile(3, 9, simHost.sim, general.player)
        emergeTile2 = self.get_player_tile(4, 8, simHost.sim, general.player)
        self.assertGreater(bot.armyTracker.emergenceLocationMap[enemyGeneral.player][emergeTile1.x][emergeTile1.y], 9)
        self.assertGreater(bot.armyTracker.emergenceLocationMap[enemyGeneral.player][emergeTile2.x][emergeTile2.y], 9)
    
    def test_should_not_think_fog_city_when_reasonable_fog_move(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_think_fog_city_when_reasonable_fog_move___SdYjMpN_b---0--239.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 239, fill_out_tiles=True)
        map.GetTile(8, 3).army = 4

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=239)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '8,3->7,3->6,3->6,2')
        bot = simHost.get_bot(general.player)
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][16][1] = 4
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][16][3] = 23
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][16][4] = 23

        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][17][1] = 15
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][17][2] = 18
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][17][3] = 25
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][17][4] = 14
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][17][5] = 25

        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][18][1] = 12
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][18][2] = 15
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][18][3] = 18
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][18][4] = 25

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        # simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=4)
        self.assertIsNone(winner)
        notCity = self.get_player_tile(9, 1, simHost.sim, general.player)
        self.assertFalse(notCity.isCity)
        notCity = self.get_player_tile(10, 2, simHost.sim, general.player)
        self.assertFalse(notCity.isCity)
    
    def test_mutual_tile_attacks_should_not_dupe_out_of_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/mutual_tile_attacks_should_not_dupe_out_of_fog___sN_jR1oaU---0--231.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 231, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=231)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '11,11->11,12->11,11')
        simHost.queue_player_moves_str(general.player, '11,12->11,11')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=3)
        self.assertIsNone(winner)
    
    def test_should_not_duplicate_prio_loss_move_capture_backwards_into_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_prio_loss_move_capture_backwards_into_fog___zyb7uceLk---0--335.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 335, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=335)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '10,9->11,9')
        simHost.queue_player_moves_str(general.player, '11,9->11,10')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)
    
    def test_should_recognize_army_collision_from_new_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_new_fog___GXjkHOUVV---0--230.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 230, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=230)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '5,9->5,10')
        simHost.queue_player_moves_str(general.player, '5,11->5,10')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)

    def test_should_determine_opp_took_city_in_fog_and_register_scary_alternate_attack_threat(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        # the results are kinda randomized based on how the tile movables are shuffled; make sure they all result in finding the city.

        for i in range(10):
            with self.subTest(i=i):
                mapFile = 'GameContinuationEntries/should_determine_opp_took_city_in_fog_and_register_scary_alternate_attack_threat___fdMpgqEU7---1--306.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 306, fill_out_tiles=True)
                fakeCity = map.GetTile(9, 18)
                fakeCity.isCity = True
                fakeCity.isMountain = False
                fakeCity.player = enemyGeneral.player
                fakeCity.army = 18

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=306)

                simHost = GameSimulatorHost(
                    map,
                    player_with_viewer=general.player,
                    playerMapVision=rawMap,
                    allAfkExceptMapPlayer=True)
                simHost.queue_player_moves_str(enemyGeneral.player, '9,18->10,18->11,18->11,17->11,16->11,15->12,15')
                genBot = simHost.get_bot(general.player)
                genBot.armyTracker.new_army_emerged(genBot._map.GetTile(4, 13), 300)

                simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.25, turns=25)
                self.assertIsNone(winner)
                self.assertEqual(general.player, fakeCity.player)
    
    def test_should_not_assume_absurd_fog_city(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_assume_absurd_fog_city___WZdfgJ-6t---0--527.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 527, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=527)

        # problemMountain = rawMap.GetTile(11, 4)
        # self.assertFalse(problemMountain.discovered)
        # self.assertFalse(problemMountain.isMountain)
        # self.assertTrue(problemMountain.isUndiscoveredObstacle)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '14,4->14,5')
        simHost.queue_player_moves_str(general.player, '3,13->3,14')
        bot = simHost.get_bot(general.player)
        problemMountain = bot._map.GetTile(11, 4)
        self.assertFalse(problemMountain.discovered)
        self.assertFalse(problemMountain.isMountain)
        self.assertTrue(problemMountain.isUndiscoveredObstacle)

        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][10][3] = 36
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][11][3] = 44
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][11][4] = 36
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][11][5] = 3
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][12][3] = 51
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][12][4] = 44
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][12][5] = 70
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][13][3] = 65
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][14][3] = 70
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][14][2] = 65
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][14][1] = 51
        bot.armyTracker.emergenceLocationMap[enemyGeneral.player][15][1] = 50

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=2)
        self.assertIsNone(winner)
    
    def test_should_force_entangled_armies_different_directions_and_never_merge_them(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_force_entangled_armies_different_directions_and_never_merge_them___Qd-vuxnl9---1--179.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 179, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=179)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,5->9,6->9,7->9,8->9,9->8,9->8,10->7,10->7,9->7,8->8,8->8,7->8,6->7,6->7,5->6,5->5,5->5,6->5,7->5,8')

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        bot = simHost.get_bot(general.player)

        armyShouldEntangle = bot.get_army_at_x_y(9, 5)

        self.begin_capturing_logging()
        genMap = simHost.get_player_map(general.player)
        simHost.run_between_turns(lambda: self.assertLess(genMap.GetTile(10, 10).army, 75))
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=20)
        self.assertIsNone(winner)

        countOrigName = 0
        for armyTile, army in bot.armyTracker.armies.items():
            if army.player == enemyGeneral.player and army.name == armyShouldEntangle.name:
                countOrigName += 1
                self.assertLess(army.value, 60)

        armyAtExpectedDest = bot.get_army_at_x_y(10, 10)
        self.assertEqual(armyShouldEntangle.name, armyAtExpectedDest.name)

        self.assertEqual(2, countOrigName)

        self.assertEqual(1, len(armyAtExpectedDest.entangledArmies))

        #entangled should have moved around the map the other way.
        entangled = armyAtExpectedDest.entangledArmies[0]
        self.assertEqual(0, entangled.tile.x)
        self.assertEqual(13, entangled.tile.y)

    
    def test_attacking_general_should_not_be_a_fog_path_wtf(self):
        for general10PlusMinus in [1, 2, -2, -1, 0]:
            with self.subTest(general10PlusMinus=general10PlusMinus):
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
                mapFile = 'GameContinuationEntries/attacking_general_should_not_be_a_fog_path_wtf___n35SxPk5n---0--244.txtmap'
                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 243, fill_out_tiles=True)

                enemyGeneral.army += general10PlusMinus

                self.enable_search_time_limits_and_disable_debug_asserts()

                rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=243)
                rawMap.GetTile(4, 7).isCity = False
                rawMap.GetTile(4, 7).army = 0
                rawMap.GetTile(4, 7).player = -1
                rawMap.GetTile(3, 11).isCity = False
                rawMap.GetTile(3, 11).army = 0
                rawMap.GetTile(3, 11).player = -1

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
                bot = simHost.get_bot(general.player)
                simHost.queue_player_moves_str(general.player, '6,11->6,10->5,10')

                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][4][10] = 8
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][5][8] = 8
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][5][7] = 2
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][6][7] = 2
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][7][7] = 2
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][6][8] = 2
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][7][8] = 2
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][4][11] = 2
                bot.armyTracker.emergenceLocationMap[enemyGeneral.player][4][12] = 5

                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

                self.begin_capturing_logging()
                simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, general.player, excludeFogMoves=False))
                winner = simHost.run_sim(run_real_time=debugMode, turn_time=1.0, turns=3)
                self.assertIsNone(winner)

    def test_generate_all_adjacent_army_scenarios(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        # 4x4 map, with all fog scenarios covered.
        data = """
|    |    |    |
aG1  a1   a1   b1
a1   a1   b1   b1
a1   a1   b1   b1
a1   b1   b1   bG1
|    |    |    |
"""
        moveOpts = [None, (1, 0), (-1, 0), (0, 1), (0, -1)]

        for aArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
            for bArmy in [10, 11, 12, 15, 20, 2, 5, 8, 9]:
                for aMove in moveOpts:
                    for bMove in moveOpts:
                        with self.subTest(aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove):
                            # rerun = True
                            # debugMode = False
                            # while rerun:
                            #     rerun = False
                            #
                            map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 97, fill_out_tiles=False, player_index=0)

                            aTile = map.GetTile(1, 1)
                            bTile = map.GetTile(2, 1)

                            aTile.army = aArmy
                            bTile.army = bArmy

                            simHost = GameSimulatorHost(map, player_with_viewer=-2)
                            simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, excludeFogMoves=False))

                            if aMove is not None:
                                aX, aY = aMove
                                simHost.queue_player_moves_str(general.player, f'None  {aTile.x},{aTile.y}->{aTile.x + aX},{aTile.y + aY}  None')
                            else:
                                simHost.queue_player_moves_str(general.player, f'None  None  None')

                            if bMove is not None:
                                bX, bY = bMove
                                simHost.queue_player_moves_str(enemyGeneral.player, f'None  {bTile.x},{bTile.y}->{bTile.x + bX},{bTile.y + bY}  None')
                            else:
                                simHost.queue_player_moves_str(enemyGeneral.player, f'None  None  None')

                            simHost.run_sim(run_real_time=debugMode, turn_time=5.5, turns=3)

    def test_should_not_duplicate_on_army_collision_next_to_fog(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_duplicate_on_army_collision_next_to_fog___rEzKs5ig0---0--131.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 131, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=131)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for should_not_duplicate_on_army_collision_next_to_fog
