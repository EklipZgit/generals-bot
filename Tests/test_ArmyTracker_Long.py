import random
import time
import typing

import logbook

import Gather
import SearchUtils
from Algorithms import MapSpanningUtils
from Gather import GatherDebug
from Models import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost, GameSimulator
from TestBase import TestBase
from base.client.tile import TILE_EMPTY, Tile
from bot_ek0x45 import EklipZBot


class ArmyTrackerTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_tile_deltas = True
        bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def assertNoFogMismatches(
            self,
            simHost: GameSimulatorHost,
            player: int = -1,
            excludeEntangledFog: bool = True,
            excludeFogMoves: bool = False,
            excludeTempFogPredictions: bool = True,
            aroundTile: Tile | None = None
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

            tilesToCheck = realMap.get_all_tiles()
            if aroundTile is not None:
                tilesToCheck = realMap.GetTile(aroundTile.x, aroundTile.y).adjacents

            for tile in tilesToCheck:
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

                if playerTile.isTempFogPrediction and excludeTempFogPredictions:
                    continue

                if playerTile.army != tile.army:
                    failures.append(f'(bot{player}) expected tile.army {tile.army} on {repr(tile)}, found {playerTile.army} - {repr(playerTile)}')
                if playerTile.player != tile.player:
                    failures.append(f'(bot{player}) expected player {tile.player} on {repr(tile)}, found {playerTile.player} - {repr(playerTile)}')
                if playerTile.isCity != tile.isCity:
                    failures.append(f'(bot{player}) expected isCity {tile.isCity} on {repr(tile)}, found {playerTile.isCity} - {repr(playerTile)}')

        if len(failures) > 0:
            self.fail(f'TURN {simHost.sim.turn}\r\n' + '\r\n'.join(failures))

    def assertNoArmyOn(self, tile: Tile, bot: EklipZBot):
        army = bot.armyTracker.armies.get(tile, None)
        if army is not None and army.value > 0 and not army.scrapped:
            self.fail(f'Expected no army on {repr(tile)}, instead found {repr(army)}')

    def run_generated_adj_test(self, aArmy, aMove, bArmy, bMove, data, debugMode):
        map, general, enemyGeneral = self.load_map_and_generals_from_string(data, 97, fill_out_tiles=False, player_index=0)
        aTile = map.GetTile(1, 1)
        bTile = map.GetTile(2, 1)
        aTile.army = aArmy
        bTile.army = bArmy
        GatherDebug.USE_DEBUG_ASSERTS = False
        mapVision = map
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=mapVision)
        simHost.apply_map_vision(enemyGeneral.player, mapVision)
        simHost.sim.ignore_illegal_moves = True
        simHost.run_between_turns(lambda: self.assertNoFogMismatches(simHost, excludeFogMoves=False))
        if aMove is not None:
            aX, aY = aMove
            simHost.queue_player_moves_str(general.player, f'{aTile.x},{aTile.y}->{aTile.x + aX},{aTile.y + aY}')
        else:
            simHost.queue_player_moves_str(general.player, f'None')
        if bMove is not None:
            bX, bY = bMove
            simHost.queue_player_moves_str(enemyGeneral.player, f'{bTile.x},{bTile.y}->{bTile.x + bX},{bTile.y + bY}')
        else:
            simHost.queue_player_moves_str(enemyGeneral.player, f'None')
        if debugMode:
            self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=1)

    def test_generate_all_adjacent_army_scenarios(self):
        # self.skipTest('takes too long right now, and currently passing')

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
        moveOpts = [(0, -1), (-1, 0), (0, 1), None, (1, 0)]

        combos = []

        for aArmy in [12, 10, 11, 15, 20, 2, 5, 8, 9]:
            for bArmy in [5, 10, 11, 12, 15, 20, 2, 8, 9]:
                for aMove in moveOpts:
                    for bMove in moveOpts:
                        combos.append((aArmy, bArmy, aMove, bMove))

        random.shuffle(combos)
        for aArmy, bArmy, aMove, bMove in combos:
            with self.subTest(aArmy=aArmy, bArmy=bArmy, aMove=aMove, bMove=bMove):
                self.run_generated_adj_test(aArmy, aMove, bArmy, bMove, data, debugMode)
