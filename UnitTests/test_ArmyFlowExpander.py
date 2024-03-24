import time
import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from BoardAnalyzer import BoardAnalyzer
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase, Tile
from bot_ek0x45 import EklipZBot


class ArmyFlowExpanderUnitTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_should_recognize_gather_into_top_path_is_best(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        if debugMode:
            self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        self.run_army_flow_expansion(map, general, enemyGeneral, turns=50)

    # """
    # PRIMS
    # """
    # def test_analyze_spanning_tree_stuff(self):
    #     debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
    #     mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
    #     map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)
    #
    #     if debugMode:
    #         self.render_map(map)
    #
    #     self.enable_search_time_limits_and_disable_debug_asserts()
    #     self.begin_capturing_logging()
    #
    #     self.run_army_flow_expansion(map, general, enemyGeneral, turns=50)

    def run_army_flow_expansion(self, map: MapBase, general: Tile, enemyGeneral: Tile, turns: int, negativeTiles: typing.Set[Tile] | None = None):
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands()
        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)

        expander = ArmyFlowExpander(map)
        return expander.get_expansion_options(
            islands=builder,
            asPlayer=general.player,
            targetPlayer=enemyGeneral.player,
            turns=turns,
            boardAnalysis=analysis,
            territoryMap=None,
            negativeTiles=negativeTiles,
        )
