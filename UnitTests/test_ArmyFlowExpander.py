import itertools
import math
import random
import time
import typing
from collections import deque

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, FlowExpansionPlanOption, IslandFlowNode, FlowGraphMethod
from BoardAnalyzer import BoardAnalyzer
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import PathColorer
from base import Colors
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
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 250, fill_out_tiles=True)

        # if debugMode:
        #     self.render_map(map)

        self.enable_search_time_limits_and_disable_debug_asserts()
        self.begin_capturing_logging()

        opts = self.run_army_flow_expansion(map, general, enemyGeneral, turns=50, debugMode=debugMode)
        self.assertNotEqual(0, len(opts))
        self.assertGreater(opts[0].econValue / opts[0].length, 1.5, 'should find a plan with pretty high value per turn')


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

    def run_army_flow_expansion(self, map: MapBase, general: Tile, enemyGeneral: Tile, turns: int, negativeTiles: typing.Set[Tile] | None = None, debugMode: bool = False) -> typing.List[FlowExpansionPlanOption]:
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)
        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)

        expander = ArmyFlowExpander(map)
        expander.friendlyGeneral = general
        expander.enemyGeneral = enemyGeneral

        opts = expander.get_expansion_options(
            islands=builder,
            asPlayer=general.player,
            targetPlayer=enemyGeneral.player,
            turns=turns,
            boardAnalysis=analysis,
            territoryMap=None,
            negativeTiles=negativeTiles,
        )

        if debugMode:
            targetIslands = builder.tile_islands_by_player[enemyGeneral.player]
            ourIslands = builder.tile_islands_by_player[general.player]
            neutralIslands = builder.tile_islands_by_player[-1]

            bestOpt = opts[0]
            vi = self.get_renderable_view_info(map)
            for move in bestOpt.get_move_list():
                path = Path.from_move(move)
                vi.color_path(PathColorer(
                    path,
                    100, 200, 100,
                    200,
                    0, 0
                ))

            for island in sorted(itertools.chain.from_iterable([targetIslands, ourIslands, neutralIslands]), key=lambda i: (i.team, str(i.name))):
                color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                zoneAlph = 80
                divAlph = 200
                if island.team == -1:
                    zoneAlph //= 2
                    divAlph //= 2

                vi.add_map_zone(island.tile_set, color, alpha=zoneAlph)
                vi.add_map_division(island.tile_set, color, alpha=divAlph)
                if island.name:
                    for tile in island.tile_set:
                        if vi.bottomRightGridText[tile]:
                            vi.midRightGridText[tile] = island.name
                        else:
                            vi.bottomRightGridText[tile] = island.name

                vi.add_info_line_no_log(f'{island.team}: island {island.name} - {island.sum_army}a/{island.tile_count}t ({island.sum_army_all_adjacent_friendly}a/{island.tile_count_all_adjacent_friendly}t) {str(island.tile_set)}')

            sourceNodes = expander.build_flow_graph(
                builder,
                ourIslands,
                targetIslands,
                general.player,
                turns,
                # blockGatherFromEnemyBorders=
                includeNeutralDemand=True,
                negativeTiles=negativeTiles,
                # method=FlowGraphMethod.CapacityScaling
            )
            q: typing.Deque[IslandFlowNode] = deque()

            for flowSource in sourceNodes.root_flow_nodes:
                q.append(flowSource)

            while q:
                flowNode: IslandFlowNode = q.popleft()

                allSourceX = [t.x for t in flowNode.island.tile_set]
                allSourceY = [t.y for t in flowNode.island.tile_set]
                sourceX = sum(allSourceX) / len(allSourceX)
                sourceY = sum(allSourceY) / len(allSourceY)

                for destinationEdge in flowNode.flow_to:
                    allDestX = [t.x for t in destinationEdge.target_flow_node.island.tile_set]
                    allDestY = [t.y for t in destinationEdge.target_flow_node.island.tile_set]
                    destX = sum(allDestX) / len(allDestX)
                    destY = sum(allDestY) / len(allDestY)

                    vi.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{destinationEdge.edge_army}', color=Colors.BLACK)
                    q.append(destinationEdge.target_flow_node)

            for flowSource in sourceNodes.enemy_backfill_nodes:
                q.append(flowSource)

            while q:
                flowNode: IslandFlowNode = q.popleft()

                allSourceX = [t.x for t in flowNode.island.tile_set]
                allSourceY = [t.y for t in flowNode.island.tile_set]
                sourceX = sum(allSourceX) / len(allSourceX)
                sourceY = sum(allSourceY) / len(allSourceY)

                for destinationEdge in flowNode.flow_to:
                    allDestX = [t.x for t in destinationEdge.target_flow_node.island.tile_set]
                    allDestY = [t.y for t in destinationEdge.target_flow_node.island.tile_set]
                    destX = sum(allDestX) / len(allDestX)
                    destY = sum(allDestY) / len(allDestY)

                    vi.draw_diagonal_arrow_between_xy(sourceX, sourceY, destX, destY, label=f'{destinationEdge.edge_army}', color=Colors.GRAY, alpha=155)
                    q.append(destinationEdge.target_flow_node)

            self.render_view_info(map, vi)

        return opts