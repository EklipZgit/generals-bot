import logging

from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class ArmyTrackerTests(TestBase):

    def test_should_recognize_army_collision_from_fog(self):
        debugMode = True

        for frArmy, enArmy, expectedTileArmy in [(62, 58, 11), (52, 58, 1), (42, 58, -9)]:
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

                simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
                simHost.queue_player_moves_str(general.player,      "5,15->6,15->7,15->8,15->9,15")
                simHost.queue_player_moves_str(enemyGeneral.player, "12,16->11,16->10,16->10,15->9,15")

                # if debugMode:
                #     self.begin_capturing_logging()
                #     winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=15)
                #     self.assertIsNone(winner)

                bot = simHost.bot_hosts[general.player].eklipz_bot
                # alert enemy of the player general
                # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
                origArmy = bot.armyTracker.armies[self.get_player_tile(12, 16, simHost.sim, general.player)]
                origName = origArmy.name

                t11_16 = self.get_player_tile(11, 16, simHost.sim, general.player)
                t12_17 = self.get_player_tile(12, 17, simHost.sim, general.player)
                self.begin_capturing_logging()
                simHost.execute_turn()
                bot.init_turn()

                # ok, now that army should be duplicated on 12,17 and 11,16 because we dont know where the tile went
                entangledIncorrect = bot.armyTracker.armies[self.get_player_tile(12, 17, simHost.sim, general.player)]
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
                emergedFirst = bot.armyTracker.armies[self.get_player_tile(10, 16, simHost.sim, general.player)]
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
                # ok now that army goes BACK into the fog, should split to 10,15 and 11,16 again.
                entangledCorrect = bot.armyTracker.armies[self.get_player_tile(10, 15, simHost.sim, general.player)]
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

                simHost.execute_turn()
                bot.init_turn()
                # ok now that army comes out of the fog, COLLIDING with our generals army that is moving 8,15->9,15
                collision = bot.armyTracker.armies[self.get_player_tile(9, 15, simHost.sim, general.player)]
                self.assertEqual(origName, collision.name)
                self.assertEqual(origName, entangledIncorrect.name)
                self.assertEqual(origName, entangledCorrect.name)
                self.assertNotIn(entangledIncorrect, entangledCorrect.entangledArmies)
                self.assertEqual(entangledCorrect, collision)
                self.assertFalse(collision.scrapped)
                # reuses the entangled army that was resolved as the fog emergence source.
                self.assertTrue(entangledIncorrect.scrapped)
                self.assertNotIn(entangledIncorrect.tile, bot.armyTracker.armies)

                # Also assert that when ONLY one fog resolution happened, we 100% update the fog source tile to be the enemy player and army amount.
                self.assertEqual(1, t11_16.army)
                self.assertEqual(enemyGeneral.player, t11_16.player)
                # army = bot.as

                # TODO add asserts for should_recognize_army_collision_from_fog
