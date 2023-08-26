import logging

from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase


class ArmyTrackerTests(TestBase):

    def test_should_recognize_army_collision_from_fog(self):
        debugMode = True
        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 136)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)
        simHost.queue_player_moves_str(general.player,      "5,15->6,15->7,15->8,15->9,15")
        simHost.queue_player_moves_str(enemyGeneral.player, "12,16->11,16->10,16->10,15->9,15")

        # winner = simHost.run_sim(run_real_time=debugMode, turn_time=5.0, turns=15)
        # self.assertIsNone(winner

        bot = simHost.bot_hosts[general.player].eklipz_bot
        # alert enemy of the player general
        # simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)
        origArmy = bot.armyTracker.armies[self.get_player_tile(12, 16, simHost.sim, general.player)]
        origName = origArmy.name

        simHost.execute_turn()
        bot.init_turn()
        # ok, now that army should be duplicated on 12,17 and 11,16 because we dont know where the tile went
        entangledIncorrect = bot.armyTracker.armies[self.get_player_tile(12, 17, simHost.sim, general.player)]
        entangledCorrect = bot.armyTracker.armies[self.get_player_tile(11, 16, simHost.sim, general.player)]
        self.assertTrue(origArmy.scrapped)
        self.assertEqual(origName, origArmy.name)
        self.assertEqual(origName, entangledIncorrect.name)
        self.assertEqual(origName, entangledCorrect.name)
        self.assertIn(entangledIncorrect, entangledCorrect.entangledArmies)
        self.assertIn(entangledCorrect, entangledIncorrect.entangledArmies)
        self.assertNotIn(origArmy.tile, bot.armyTracker.armies)
        self.assertFalse(entangledIncorrect.scrapped)
        self.assertFalse(entangledCorrect.scrapped)

        simHost.execute_turn()
        bot.init_turn()
        # ok now that army comes out of the fog at 10,16 again, should be the same army still, and nuke the entangled armies:
        emergedFirst = bot.armyTracker.armies[self.get_player_tile(10, 16, simHost.sim, general.player)]
        self.assertEqual(origName, emergedFirst.name)
        self.assertEqual(origName, entangledIncorrect.name)
        self.assertEqual(origName, entangledCorrect.name)
        self.assertIn(entangledIncorrect, entangledCorrect.entangledArmies)
        self.assertIn(entangledCorrect, entangledIncorrect.entangledArmies)
        self.assertEqual(entangledCorrect, emergedFirst)
        self.assertFalse(emergedFirst.scrapped)
        # reuses the entangled army that was resolved as the fog emergence source.
        self.assertTrue(entangledIncorrect.scrapped)
        self.assertNotIn(entangledIncorrect.tile, bot.armyTracker.armies)



        # army = bot.as

        # TODO add asserts for should_recognize_army_collision_from_fog
