import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2, FlowStreamIslandContribution, FlowBorderPairKey
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from ViewInfo import TargetStyle
from base import Colors
from base.client.map import MapBase
from base.client.tile import Tile
from bot_ek0x45 import EklipZBot


class FlowExpansionStreamOrderingMetadataTests(TestBase):
    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        GatherDebug.USE_DEBUG_ASSERTS = True
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)
        return bot

    # ------------------------------------------------------------------
    # Debug rendering helpers
    # ------------------------------------------------------------------

    def render_border_pair_debug(
        self,
        map: MapBase,
        expander: ArmyFlowExpanderV2,
        border_pair: FlowBorderPairKey | None,
        friendly_contributions: typing.List[FlowStreamIslandContribution],
        target_contributions: typing.List[FlowStreamIslandContribution],
        title: str = 'border pair stream ordering',
    ):
        """
        Full border-pair visualization:
        - Draws flow graph arrows (purple=withNeut, black=noNeut) via add_flow_graph_to_view_info
        - Colors each tile by role:
            GREEN  = friendly stream (darker = higher rank)
            RED    = enemy target stream (darker = higher rank)
            YELLOW = neutral in target stream
            TEAL   = target-crossable friendly island
        - Draws a bold arrow from the friendly border node centroid to the target border
          node centroid to highlight the border pair crossing.
        - Labels tiles:
            topRight    = role+rank (F0, T0, N0, X0)
            midRight    = sort_score
            bottomRight = army/tiles
            bottomLeft  = flow magnitude
        - Adds detailed island info lines.
        """
        view_info = self.get_renderable_view_info(map)

        # -- flow graph arrows (background layer) --
        if expander.flow_graph is not None:
            ArmyFlowExpander.add_flow_graph_to_view_info(expander.flow_graph, view_info, lastRun=None)

        # -- island outlines via add_tile_islands_to_view_info --
        from Algorithms.TileIslandBuilder import TileIslandBuilder as _TIB
        builder_ref = expander._networkx_finder._island_builder if hasattr(expander._networkx_finder, '_island_builder') else None

        view_info.add_info_line(f'=== {title} ===')
        if border_pair is not None:
            view_info.add_info_line(f'Border pair: friendly_island={border_pair.friendly_island_id} -> target_island={border_pair.target_island_id}')

        # -- draw border-pair crossing arrow --
        if border_pair is not None and expander.flow_graph is not None:
            island_lookup = expander.flow_graph.flow_node_lookup_by_island_inc_neut
            friendly_flow_node = island_lookup.get(border_pair.friendly_island_id)
            target_flow_node = island_lookup.get(border_pair.target_island_id)
            if friendly_flow_node and target_flow_node:
                friendly_centroid_x = sum(t.x for t in friendly_flow_node.island.tile_set) / len(friendly_flow_node.island.tile_set)
                friendly_centroid_y = sum(t.y for t in friendly_flow_node.island.tile_set) / len(friendly_flow_node.island.tile_set)
                target_centroid_x = sum(t.x for t in target_flow_node.island.tile_set) / len(target_flow_node.island.tile_set)
                target_centroid_y = sum(t.y for t in target_flow_node.island.tile_set) / len(target_flow_node.island.tile_set)
                view_info.draw_diagonal_arrow_between_xy(friendly_centroid_x, friendly_centroid_y, target_centroid_x, target_centroid_y, label='BP', color=Colors.ORANGE)

        # -- friendly contributions (green) --
        view_info.add_info_line(f'Friendly stream ({len(friendly_contributions)} islands):')
        for rank, contrib in enumerate(friendly_contributions):
            island = contrib.flow_node.island
            view_info.add_info_line(
                f'  F[{rank}] {island.unique_id}/{island.name}  '
                f'army={contrib.army_amount} tiles={contrib.tile_count} '
                f'flow={contrib.marginal_flow} score={contrib.sort_score:.3f}'
            )
            for tile in island.tile_set:
                view_info.topRightGridText[tile] = f'F{rank}'
                view_info.midRightGridText[tile] = f'{contrib.sort_score:.1f}'
                view_info.bottomRightGridText[tile] = f'{contrib.army_amount}/{contrib.tile_count}'
                view_info.bottomLeftGridText[tile] = f'fl{contrib.marginal_flow}'
                view_info.add_targeted_tile(tile, TargetStyle.GREEN, radiusReduction=6)

        # -- target contributions (red / yellow for neutral / teal for crossing) --
        view_info.add_info_line(f'Target stream ({len(target_contributions)} islands):')
        for rank, contrib in enumerate(target_contributions):
            island = contrib.flow_node.island
            cross_tag = ' [CROSS]' if contrib.is_crossing else ''
            neut_tag = ' [NEUT]' if island.team == -1 else ''
            view_info.add_info_line(
                f'  T[{rank}] {island.unique_id}/{island.name}{cross_tag}{neut_tag}  '
                f'army={contrib.army_amount} tiles={contrib.tile_count} '
                f'flow={contrib.marginal_flow} score={contrib.sort_score:.3f}'
            )
            if contrib.is_crossing:
                tile_style = TargetStyle.TEAL
            elif island.team == -1:
                tile_style = TargetStyle.YELLOW
            else:
                tile_style = TargetStyle.RED
            for tile in island.tile_set:
                view_info.topRightGridText[tile] = f'T{rank}'
                view_info.midRightGridText[tile] = f'{contrib.sort_score:.1f}'
                view_info.bottomRightGridText[tile] = f'{contrib.army_amount}/{contrib.tile_count}'
                view_info.bottomLeftGridText[tile] = f'fl{contrib.marginal_flow}'
                view_info.add_targeted_tile(tile, tile_style, radiusReduction=6)

        self.render_view_info(map, view_info, title)

    def render_stream_ordering_debug(
        self,
        map: MapBase,
        expander: ArmyFlowExpanderV2,
        friendly_contributions: typing.List[FlowStreamIslandContribution],
        target_contributions: typing.List[FlowStreamIslandContribution],
        title: str = 'stream ordering metadata',
    ):
        """Thin wrapper around render_border_pair_debug when no specific border pair is highlighted."""
        self.render_border_pair_debug(map, expander, None, friendly_contributions, target_contributions, title)

    def _setup_expander_with_flow_graph(
        self,
        map: MapBase,
        general: Tile,
        enemyGeneral: Tile,
    ) -> tuple[ArmyFlowExpanderV2, TileIslandBuilder]:
        """Build the flow expander and flow graph for a given map/generals."""

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemyGeneral, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.enemy_general = enemyGeneral
        expander._ensure_flow_graph_exists(builder, turns=50)
        return expander, builder

    def _get_border_pair_stream_contributions(
        self,
        expander: ArmyFlowExpanderV2,
        builder: TileIslandBuilder,
    ) -> list[tuple]:
        """
        Enumerate border pairs and return list of
        (border_pair, friendly_contributions, target_contributions).
        """
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )

        results = []
        for border_pair in border_pairs:
            stream_data = expander._build_border_pair_stream_data(border_pair, expander.flow_graph, target_crossable, 50)
            if not stream_data:
                continue
            friendly_contribs, target_contribs = expander._preprocess_flow_stream_tilecounts(stream_data, border_pair)
            results.append((border_pair, friendly_contribs, target_contribs, stream_data))
        return results

    def _get_island_contribution_by_xy(
        self,
        contributions: typing.List[FlowStreamIslandContribution],
        x: int,
        y: int,
    ) -> FlowStreamIslandContribution:
        for contribution in contributions:
            for tile in contribution.flow_node.island.tile_set:
                if tile.x == x and tile.y == y:
                    return contribution
        raise AssertionError(f'No contribution found containing tile ({x},{y})')

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_stream_ordering__friendly_ranking_prefers_better_army_per_tile(self):
        """
        Friendly stream: an island with higher army/tile ratio ranks before one with a lower ratio.
        Map layout (all single-tile islands): aG1  a6  a2  b1  bG1

        There is exactly one border pair (a2 borders b1; a6 is one hop upstream of a2).
        Friendly sort_score = (army/tiles) * 1000 + flow_magnitude * 0.1:
          a6: 6/1*1000 + 5*0.1 = 6000.5
          a2: 2/1*1000 + 4*0.1 = 2000.4
        Target sort_score = cost_score + type_bonus(2.05) + flow*0.1 + dEcon + dCity*50 + dTile*0.25,
        with downstream potentials bubbled along the flow chain b1 -> bG1:
          b1:  downstream {b1, bG1} -> econ 4.10, tiles 2, cities 1 (the general), enemy army 2
          bG1: downstream {bG1}     -> econ 2.05, tiles 1, cities 1, enemy army 1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a6   a2   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, friendly_contribs, target_contribs, _ = stream_results[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_results[0][0], friendly_contribs, target_contribs, 'friendly ranking by army/tile')

        # Friendly contributions: exactly [a6, a2] in descending sort_score order.
        self.assertEqual(2, len(friendly_contribs))
        a6, a2 = friendly_contribs
        self.assertEqual((1, 0), min((t.x, t.y) for t in a6.flow_node.island.tile_set))
        self.assertEqual(1, a6.tile_count)
        self.assertEqual(6, a6.army_amount)
        self.assertAlmostEqual(6000.5, a6.sort_score, places=4)
        self.assertEqual((2, 0), min((t.x, t.y) for t in a2.flow_node.island.tile_set))
        self.assertEqual(1, a2.tile_count)
        self.assertEqual(2, a2.army_amount)
        self.assertAlmostEqual(2000.4, a2.sort_score, places=4)

        # Target contributions: exactly [b1, bG1] in physical path order.
        self.assertEqual(2, len(target_contribs))
        b1 = self._get_island_contribution_by_xy(target_contribs, 3, 0)
        bg = self._get_island_contribution_by_xy(target_contribs, 4, 0)
        self.assertEqual(b1, target_contribs[0])
        self.assertEqual(bg, target_contribs[1])
        self.assertAlmostEqual(4.10, b1.downstream_econ_potential, places=4)
        self.assertEqual(2, b1.downstream_enemy_tile_potential)
        self.assertEqual(1, b1.downstream_enemy_city_potential)
        self.assertEqual(2, b1.downstream_enemy_army_potential)
        self.assertEqual(4, b1.downstream_capture_army_potential)
        self.assertAlmostEqual(57.35, b1.sort_score, places=4)
        self.assertAlmostEqual(2.05, bg.downstream_econ_potential, places=4)
        self.assertEqual(1, bg.downstream_enemy_tile_potential)
        self.assertEqual(1, bg.downstream_enemy_city_potential)
        self.assertEqual(1, bg.downstream_enemy_army_potential)
        self.assertEqual(2, bg.downstream_capture_army_potential)
        self.assertAlmostEqual(54.85, bg.sort_score, places=4)

    def test_stream_ordering__target_ranking_prefers_enemy_over_neutral_at_equal_cost(self):
        """
        Layout (1 row): aG1  a5  neut  b1  bG1  neut(overflow sink)

        The min-cost flow chain is neut(2) -> b1(3) -> bG1(4) -> neut(5), so the four target
        contributions appear in that exact physical path order. Downstream potentials bubble up the
        chain (neutral tiles 1.0 econ, enemy tiles 2.05 econ, the general counts as one enemy city):
          neut(2): downstream {neut2,b1,bG1,neut5} econ 6.10 tiles 2 cities 1 enArmy 2 capArmy 6
          b1(3):   downstream {b1,bG1,neut5}        econ 5.10 tiles 2 cities 1 enArmy 2 capArmy 5
          bG1(4):  downstream {bG1,neut5}           econ 3.05 tiles 1 cities 1 enArmy 1 capArmy 3
          neut(5): downstream {neut5}               econ 1.00 tiles 0 cities 0 enArmy 0 capArmy 1
        sort_score = cost_score + type_bonus + flow*0.1 + dEcon + dCity*50 + dTile*0.25.
        The enemy b1 type_bonus (2.05) exceeds the neutral type_bonus (1.0) at equal army/tile cost;
        its total score is lower only because the gateway neutral bubbles one extra downstream tile.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a5        b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, friendly_contribs, target_contribs, _ = stream_results[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_results[0][0], friendly_contribs, target_contribs, 'enemy vs neutral ranking')

        # Exactly four target contributions in physical path order: neut, b1, bG1, neut(sink).
        self.assertEqual(4, len(target_contribs))
        neut_gate = self._get_island_contribution_by_xy(target_contribs, 2, 0)
        b1 = self._get_island_contribution_by_xy(target_contribs, 3, 0)
        bg = self._get_island_contribution_by_xy(target_contribs, 4, 0)
        neut_sink = self._get_island_contribution_by_xy(target_contribs, 5, 0)
        self.assertEqual([neut_gate, b1, bg, neut_sink], target_contribs)

        self.assertEqual(-1, neut_gate.flow_node.island.team)
        self.assertEqual(expander.target_team, b1.flow_node.island.team)

        self.assertAlmostEqual(6.10, neut_gate.downstream_econ_potential, places=4)
        self.assertEqual(2, neut_gate.downstream_enemy_tile_potential)
        self.assertEqual(1, neut_gate.downstream_enemy_city_potential)
        self.assertEqual(2, neut_gate.downstream_enemy_army_potential)
        self.assertEqual(6, neut_gate.downstream_capture_army_potential)
        self.assertAlmostEqual(59.10, neut_gate.sort_score, places=4)

        self.assertAlmostEqual(5.10, b1.downstream_econ_potential, places=4)
        self.assertEqual(2, b1.downstream_enemy_tile_potential)
        self.assertEqual(1, b1.downstream_enemy_city_potential)
        self.assertEqual(2, b1.downstream_enemy_army_potential)
        self.assertEqual(5, b1.downstream_capture_army_potential)
        self.assertAlmostEqual(58.45, b1.sort_score, places=4)

        self.assertAlmostEqual(3.05, bg.downstream_econ_potential, places=4)
        self.assertEqual(1, bg.downstream_enemy_tile_potential)
        self.assertEqual(1, bg.downstream_enemy_city_potential)
        self.assertEqual(1, bg.downstream_enemy_army_potential)
        self.assertEqual(3, bg.downstream_capture_army_potential)
        self.assertAlmostEqual(55.95, bg.sort_score, places=4)

        self.assertAlmostEqual(1.00, neut_sink.downstream_econ_potential, places=4)
        self.assertEqual(0, neut_sink.downstream_enemy_tile_potential)
        self.assertEqual(0, neut_sink.downstream_enemy_city_potential)
        self.assertEqual(0, neut_sink.downstream_enemy_army_potential)
        self.assertEqual(1, neut_sink.downstream_capture_army_potential)
        self.assertAlmostEqual(3.00, neut_sink.sort_score, places=4)

        # Type bonus alone (sort_score minus the bubbled downstream terms) still favors enemy over neutral.
        def base_type_score(contribution: FlowStreamIslandContribution) -> float:
            return (
                contribution.sort_score
                - contribution.downstream_econ_potential
                - contribution.downstream_enemy_city_potential * 50
                - contribution.downstream_enemy_tile_potential * 0.25
            )

        self.assertAlmostEqual(2.85, base_type_score(b1), places=4)
        self.assertAlmostEqual(2.50, base_type_score(neut_gate), places=4)
        self.assertGreater(base_type_score(b1), base_type_score(neut_gate))

    def test_stream_ordering__target_ranking_prefers_lower_army_tiles_first(self):
        """
        Layout: aG1  a10  b1  b5  bG1  (with a neutral overflow sink at col 5).

        Target contributions are in physical path order along the flow chain b1 -> b5 -> bG1 -> neut:
          b1(2):  cost 0.5 (army/tile 1), downstream {b1,b5,bG1,neut} econ 7.15 tiles 3 cities 1 enArmy 7 capArmy 11
          b5(3):  cost 1/6 (army/tile 5), downstream {b5,bG1,neut}     econ 5.10 tiles 2 cities 1 enArmy 6 capArmy 9
          bG1(4): cost 0.5,               downstream {bG1,neut}        econ 3.05 tiles 1 cities 1 enArmy 1 capArmy 3
          neut(5):                        downstream {neut}            econ 1.00 tiles 0 cities 0 enArmy 0 capArmy 1
        b1 (the lower-army enemy) is physically first; its higher downstream bubbling AND lower
        army-per-tile cost both make it outscore b5.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a10  b1   b5   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, friendly_contribs, target_contribs, _ = stream_results[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_results[0][0], friendly_contribs, target_contribs, 'lower army first in target')

        # Exactly four target contributions in physical path order: b1, b5, bG1, neut(sink).
        self.assertEqual(4, len(target_contribs))
        b1 = self._get_island_contribution_by_xy(target_contribs, 2, 0)
        b5 = self._get_island_contribution_by_xy(target_contribs, 3, 0)
        bg = self._get_island_contribution_by_xy(target_contribs, 4, 0)
        neut_sink = self._get_island_contribution_by_xy(target_contribs, 5, 0)
        self.assertEqual([b1, b5, bg, neut_sink], target_contribs)

        self.assertEqual(1, b1.army_amount)
        self.assertAlmostEqual(7.15, b1.downstream_econ_potential, places=4)
        self.assertEqual(3, b1.downstream_enemy_tile_potential)
        self.assertEqual(1, b1.downstream_enemy_city_potential)
        self.assertEqual(7, b1.downstream_enemy_army_potential)
        self.assertEqual(11, b1.downstream_capture_army_potential)
        self.assertAlmostEqual(61.35, b1.sort_score, places=4)

        self.assertEqual(5, b5.army_amount)
        self.assertAlmostEqual(5.10, b5.downstream_econ_potential, places=4)
        self.assertEqual(2, b5.downstream_enemy_tile_potential)
        self.assertEqual(1, b5.downstream_enemy_city_potential)
        self.assertEqual(6, b5.downstream_enemy_army_potential)
        self.assertEqual(9, b5.downstream_capture_army_potential)
        self.assertAlmostEqual(58.116666666666667, b5.sort_score, places=4)

        # The lower-army enemy (b1) outscores the higher-army one (b5).
        self.assertGreater(b1.sort_score, b5.sort_score)

    def test_stream_ordering__target_ranking_sorts_descending(self):
        """
        Target contributions stay in physical path order (BFS from the friendly border outward),
        NOT sorted by score. Layout: aG1  a8  b1  b4  b2  bG1 (plus a neutral overflow sink at col 6).

        b4(col3) and b2(col4) are contiguous same-team enemy tiles, so they merge into ONE island
        (2 tiles, army 6). The flow chain is b1 -> [b4b2] -> bG1 -> neut, giving target contributions
        in ascending-x physical order:
          b1(2):    downstream {b1,b4b2,bG1,neut} econ 9.20 tiles 4 cities 1 enArmy 8 capArmy 13 score 63.65
          b4b2(3):  downstream {b4b2,bG1,neut}    econ 7.15 tiles 3 cities 1 enArmy 7 capArmy 11 score 60.30
          bG1(5):   downstream {bG1,neut}         econ 3.05 tiles 1 cities 1 enArmy 1 capArmy 3  score 55.95
          neut(6):  downstream {neut}             econ 1.00 tiles 0 cities 0 enArmy 0 capArmy 1  score 3.00
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
aG1  a8   b1   b4   b2   bG1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, friendly_contribs, target_contribs, _ = stream_results[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_results[0][0], friendly_contribs, target_contribs, 'target sort descending 3-segment')

        # Exactly four target contributions (b4 and b2 merge) in ascending-x physical path order.
        self.assertEqual(4, len(target_contribs))
        b1 = self._get_island_contribution_by_xy(target_contribs, 2, 0)
        b4b2 = self._get_island_contribution_by_xy(target_contribs, 3, 0)
        bg = self._get_island_contribution_by_xy(target_contribs, 5, 0)
        neut_sink = self._get_island_contribution_by_xy(target_contribs, 6, 0)
        self.assertEqual([b1, b4b2, bg, neut_sink], target_contribs)

        self.assertEqual(1, b1.tile_count)
        self.assertAlmostEqual(9.20, b1.downstream_econ_potential, places=4)
        self.assertEqual(4, b1.downstream_enemy_tile_potential)
        self.assertEqual(1, b1.downstream_enemy_city_potential)
        self.assertEqual(8, b1.downstream_enemy_army_potential)
        self.assertEqual(13, b1.downstream_capture_army_potential)
        self.assertAlmostEqual(63.65, b1.sort_score, places=4)

        # b4 and b2 merged into a single 2-tile, 6-army island.
        self.assertEqual(2, b4b2.tile_count)
        self.assertEqual(6, b4b2.army_amount)
        self.assertAlmostEqual(7.15, b4b2.downstream_econ_potential, places=4)
        self.assertEqual(3, b4b2.downstream_enemy_tile_potential)
        self.assertEqual(1, b4b2.downstream_enemy_city_potential)
        self.assertEqual(7, b4b2.downstream_enemy_army_potential)
        self.assertEqual(11, b4b2.downstream_capture_army_potential)
        self.assertAlmostEqual(60.30, b4b2.sort_score, places=4)

        # Physical path order must hold regardless of score values.
        contrib_xs = [min(t.x for t in c.flow_node.island.tile_set) for c in target_contribs]
        self.assertEqual(sorted(contrib_xs), contrib_xs)

    def test_stream_ordering__single_city_stream_bubbles_downstream_city_potential(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |
aG1  a4   a1   a1   a1   a4   bC3  bG1
|    |    |    |    |    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, _, target_contribs, stream_data = stream_results[0]

        # Layout: aG1 a4 a1 a1 a1 a4 bC3 bG1. The enemy side is a single city bC3(6) feeding the
        # enemy general bG1(7). Flow chain bC3 -> bG1, so exactly two target contributions:
        #   bC3(6): downstream {bC3(city), bG1(general)} -> econ 4.10 tiles 2 cities 2 enArmy 4 capArmy 6
        #   bG1(7): downstream {bG1(general)}            -> econ 2.05 tiles 1 cities 1 enArmy 1 capArmy 2
        self.assertEqual(2, len(target_contribs))
        city_contrib = self._get_island_contribution_by_xy(target_contribs, 6, 0)
        bg = self._get_island_contribution_by_xy(target_contribs, 7, 0)
        self.assertEqual([city_contrib, bg], target_contribs)

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_data.border_pair, [], target_contribs, 'single city downstream potential')

        # bC3 bubbles both its own city and the downstream enemy general (counted as a city).
        self.assertEqual(2, city_contrib.downstream_enemy_city_potential)
        self.assertAlmostEqual(4.10, city_contrib.downstream_econ_potential, places=4)
        self.assertEqual(2, city_contrib.downstream_enemy_tile_potential)
        self.assertEqual(6, city_contrib.downstream_capture_army_potential)
        self.assertEqual(4, city_contrib.downstream_enemy_army_potential)

        self.assertEqual(1, bg.downstream_enemy_city_potential)
        self.assertAlmostEqual(2.05, bg.downstream_econ_potential, places=4)
        self.assertEqual(1, bg.downstream_enemy_tile_potential)
        self.assertEqual(2, bg.downstream_capture_army_potential)
        self.assertEqual(1, bg.downstream_enemy_army_potential)

        # Contribution fields must exactly mirror the underlying precomputed node potential.
        city_potential = stream_data.target_node_potentials[city_contrib.island_id]
        self.assertEqual(city_contrib.downstream_enemy_city_potential, city_potential.captured_downstream_target_city_count)
        self.assertEqual(city_contrib.downstream_enemy_tile_potential, city_potential.captured_downstream_target_tile_count)
        self.assertEqual(city_contrib.downstream_enemy_army_potential, city_potential.captured_downstream_target_army)
        self.assertEqual(
            city_contrib.downstream_capture_army_potential,
            city_potential.captured_downstream_target_army
            + city_potential.captured_downstream_target_tile_count
            + city_potential.captured_downstream_neut_army
            + city_potential.captured_downstream_neut_tile_count,
        )

    def test_stream_ordering__two_city_stream_bubbles_incremental_city_potential(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |
aG7  a4   a1   a1   a1   a4   bC3  b1   bC1  b1   bG1
|    |    |    |    |    |    |    |    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, _, target_contribs, stream_data = stream_results[0]

        # Layout enemy side: bC3(6) b1(7) bC1(8) b1(9) bG1(10). Flow chain bC3->b1->bC1->b1->bG1.
        # Downstream potentials accumulate self + everything further down the chain (5 enemy tiles
        # total, 3 of them cities: bC3, bC1, and the bG1 general):
        #   bC3(6):  {6,7,8,9,10} econ 10.25 tiles 5 cities 3 enArmy 7 capArmy 12 score 164.60
        #   b1(7):   {7,8,9,10}   econ  8.20 tiles 4 cities 2 enArmy 4 capArmy  8 score 112.35
        #   bC1(8):  {8,9,10}     econ  6.15 tiles 3 cities 2 enArmy 3 capArmy  6 score 109.85
        #   b1(9):   {9,10}       econ  4.10 tiles 2 cities 1 enArmy 2 capArmy  4 score  57.35
        #   bG1(10): {10}         econ  2.05 tiles 1 cities 1 enArmy 1 capArmy  2 score  54.85
        self.assertEqual(5, len(target_contribs))
        first_city = self._get_island_contribution_by_xy(target_contribs, 6, 0)
        middle_enemy = self._get_island_contribution_by_xy(target_contribs, 7, 0)
        second_city = self._get_island_contribution_by_xy(target_contribs, 8, 0)
        third_enemy = self._get_island_contribution_by_xy(target_contribs, 9, 0)
        bg = self._get_island_contribution_by_xy(target_contribs, 10, 0)
        self.assertEqual([first_city, middle_enemy, second_city, third_enemy, bg], target_contribs)

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_data.border_pair, [], target_contribs, 'two city downstream potential')

        self.assertEqual(3, first_city.downstream_enemy_city_potential)
        self.assertAlmostEqual(10.25, first_city.downstream_econ_potential, places=4)
        self.assertEqual(5, first_city.downstream_enemy_tile_potential)
        self.assertEqual(7, first_city.downstream_enemy_army_potential)
        self.assertEqual(12, first_city.downstream_capture_army_potential)

        self.assertEqual(2, middle_enemy.downstream_enemy_city_potential)
        self.assertAlmostEqual(8.20, middle_enemy.downstream_econ_potential, places=4)
        self.assertEqual(4, middle_enemy.downstream_enemy_tile_potential)
        self.assertEqual(4, middle_enemy.downstream_enemy_army_potential)
        self.assertEqual(8, middle_enemy.downstream_capture_army_potential)

        self.assertEqual(2, second_city.downstream_enemy_city_potential)
        self.assertAlmostEqual(6.15, second_city.downstream_econ_potential, places=4)
        self.assertEqual(3, second_city.downstream_enemy_tile_potential)
        self.assertEqual(3, second_city.downstream_enemy_army_potential)
        self.assertEqual(6, second_city.downstream_capture_army_potential)

        self.assertEqual(1, third_enemy.downstream_enemy_city_potential)
        self.assertEqual(1, bg.downstream_enemy_city_potential)

        self.assertEqual(
            first_city.downstream_enemy_city_potential,
            stream_data.target_node_potentials[first_city.island_id].captured_downstream_target_city_count,
        )
        self.assertEqual(
            second_city.downstream_enemy_city_potential,
            stream_data.target_node_potentials[second_city.island_id].captured_downstream_target_city_count,
        )

    def test_stream_ordering__city_path_preserves_physical_order_while_scores_reflect_bubbled_value(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |    |    |    |    |
aG7  a4   a1   a1   a1   a4   bC3  b1   bC1  b1   bG1
|    |    |    |    |    |    |    |    |    |    |
player_index=0
"""
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, _, target_contribs, stream_data = stream_results[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_results[0][0], [], target_contribs, 'city order with bubbled scores')

        # Contributions remain in physical left-to-right order (x = 6,7,8,9,10), NOT sorted by score.
        ordered_xs = [min(tile.x for tile in contrib.flow_node.island.tile_set) for contrib in target_contribs]
        self.assertEqual([6, 7, 8, 9, 10], ordered_xs)

        # Even though bC3(6) sits earlier in the (unsorted) path, its score is the highest because it
        # bubbles the entire downstream city chain; the second city bC1(8) bubbles strictly less.
        first_city = self._get_island_contribution_by_xy(target_contribs, 6, 0)
        second_city = self._get_island_contribution_by_xy(target_contribs, 8, 0)
        self.assertAlmostEqual(164.60, first_city.sort_score, places=4)
        self.assertAlmostEqual(109.85, second_city.sort_score, places=4)
        self.assertGreater(first_city.sort_score, second_city.sort_score)

    def test_stream_ordering__friendly_sort_descending_always(self):
        """
        _preprocess_flow_stream_tilecounts must always return friendly contributions
        sorted by sort_score descending regardless of input order.
        Multi-island friendly side with different army values.
          aG1  a2   a8   a3   b1  bG1
        a8 has the best ratio (8/1), so it should rank first.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |    |
aG1  a2   a8   a3   b1   bG1
|    |    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')
        _, friendly_contribs, target_contribs, _ = stream_results[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, stream_results[0][0], friendly_contribs, target_contribs, 'friendly sort descending multi-island')

        # The gather flow routes a8 -> a3 -> b1, so the friendly stream contains exactly a8 and a3
        # (a2/aG1 contribute no routed gather here). Friendly sort_score = army/tiles*1000 + flow*0.1:
        #   a8(2): 8/1*1000 + 7*0.1 = 8000.7
        #   a3(3): 3/1*1000 + 5*0.1 = 3000.5
        self.assertEqual(2, len(friendly_contribs))
        a8, a3 = friendly_contribs
        self.assertEqual((2, 0), min((t.x, t.y) for t in a8.flow_node.island.tile_set))
        self.assertEqual(8, a8.army_amount)
        self.assertAlmostEqual(8000.7, a8.sort_score, places=4)
        self.assertEqual((3, 0), min((t.x, t.y) for t in a3.flow_node.island.tile_set))
        self.assertEqual(3, a3.army_amount)
        self.assertAlmostEqual(3000.5, a3.sort_score, places=4)
        # Descending order, with the highest army/tile island (a8) ranked first.
        self.assertGreater(a8.sort_score, a3.sort_score)

    def test_stream_ordering__contributions_cover_all_stream_nodes(self):
        """
        Each island node in the upstream friendly stream and downstream target stream
        should have exactly one corresponding FlowStreamIslandContribution.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a3   a2   b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        target_crossable = expander._detect_target_crossable_friendly_islands(
            builder, expander.flow_graph, expander.team, expander.target_team
        )
        border_pairs = expander._enumerate_border_pairs(
            expander.flow_graph, builder, expander.team, expander.target_team, target_crossable
        )
        self.assertEqual(1, len(border_pairs), 'Expected exactly one border pair')

        border_pair = border_pairs[0]
        stream_data = expander._build_border_pair_stream_data(border_pair, expander.flow_graph, target_crossable, 50)
        self.assertIsNotNone(stream_data)

        friendly_stream = stream_data.friendly_stream
        target_stream = stream_data.target_stream

        friendly_contribs, target_contribs = expander._preprocess_flow_stream_tilecounts(stream_data, border_pair)

        if debugMode:
            self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'coverage: all stream nodes have contributions')

        # Every node in friendly_stream must appear in friendly_contribs
        friendly_contrib_island_ids = {c.island_id for c in friendly_contribs}
        for node in friendly_stream:
            self.assertIn(
                node.island.unique_id, friendly_contrib_island_ids,
                f'Friendly stream node {node.island.unique_id} missing from friendly contributions'
            )

        # Every node in target_stream must appear in target_contribs
        target_contrib_island_ids = {c.island_id for c in target_contribs}
        for node in target_stream:
            self.assertIn(
                node.island.unique_id, target_contrib_island_ids,
                f'Target stream node {node.island.unique_id} missing from target contributions'
            )

        # No duplicate island_ids in each list
        self.assertEqual(len(friendly_contrib_island_ids), len(friendly_contribs), 'Duplicate island in friendly contributions')
        self.assertEqual(len(target_contrib_island_ids), len(target_contribs), 'Duplicate island in target contributions')

    def test_stream_ordering__crossing_island_has_zero_army_cost(self):
        """
        A target-crossable friendly island that appears in the target stream should have
        army_amount=0 in its contribution (no direct capture cost) and is_crossing=True.
        We simulate this by calling _compute_target_contributions directly with a mock
        crossing node in the cache.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |
aG1  a5   b1   bG1
|    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)

        # Find the friendly border island and force it into the target_crossable_cache
        friendly_border_island = builder.tile_island_lookup.raw[general.tile_index]
        expander._target_crossable_cache = {friendly_border_island.unique_id}

        # Grab its flow node from the graph
        flow_lookup = expander.flow_graph.flow_node_lookup_by_island_inc_neut
        if friendly_border_island.unique_id not in flow_lookup:
            flow_lookup = expander.flow_graph.flow_node_lookup_by_island_no_neut

        self.assertIn(
            friendly_border_island.unique_id, flow_lookup,
            'Friendly island should be in flow graph'
        )
        crossing_flow_node = flow_lookup[friendly_border_island.unique_id]

        # Compute target contributions with this node in the stream
        contribs = expander._compute_target_contributions([crossing_flow_node])

        self.assertEqual(1, len(contribs), 'Should produce one contribution')
        contrib = contribs[0]

        if debugMode:
            self.render_border_pair_debug(map, expander, None, [], [contrib], 'crossing island zero army cost')

        self.assertTrue(contrib.is_crossing, 'Contribution should be marked as crossing')
        self.assertEqual(0, contrib.army_amount, 'Crossing island should have army_amount=0')

    def test_stream_ordering__contribution_fields_match_island_data(self):
        """
        Verify tile_count and army_amount in each FlowStreamIslandContribution
        match the actual island data from the flow node.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  a3   b1   bG1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)
        self.assertEqual(1, len(stream_results), 'Expected exactly one border pair')

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'contribution fields match island data')

        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            for contrib in friendly_contribs:
                island = contrib.flow_node.island
                self.assertEqual(island.tile_count, contrib.tile_count, f'tile_count mismatch for island {island.unique_id}')
                self.assertEqual(island.sum_army, contrib.army_amount, f'army_amount mismatch for island {island.unique_id}')
                self.assertTrue(contrib.is_friendly, 'Friendly contribution should have is_friendly=True')
                self.assertFalse(contrib.is_crossing, 'Non-crossable friendly should have is_crossing=False')

            for contrib in target_contribs:
                island = contrib.flow_node.island
                self.assertEqual(island.tile_count, contrib.tile_count, f'tile_count mismatch for target island {island.unique_id}')
                if not contrib.is_crossing:
                    self.assertEqual(island.sum_army, contrib.army_amount, f'army_amount mismatch for target island {island.unique_id}')

    def test_stream_ordering__border_pair_found_through_neutral_gap(self):
        """
        Friendly and enemy islands separated by a neutral island must still produce
        a border pair, because the flow graph routes through the neutral and
        _enumerate_border_pairs must walk through neutral borders to find the
        upstream friendly source.

        Layout (1 row):
          aG1  a5   neut0   b1   bG1

        The neutral tile at col 2 is between a5 (friendly) and b1 (enemy).
        _enumerate_border_pairs must find the (a5, bG1) border pair by walking
        through the neutral island's border_islands.
        _is_flow_supported must BFS through the neutral flow node to confirm flow
        reaches bG1.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |    |    |
aG1  a4        b1   bG1
|    |    |    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=False)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'neutral-gap border pair')

        # Exactly one border pair is found even though a neutral separates friendly a4 from enemy b1.
        self.assertEqual(1, len(stream_results),
                         'Should find exactly one border pair even with neutral island separating friendly and enemy')
        _, _, target_contribs, _ = stream_results[0]

        # Target contributions are the full flow chain in physical order: neut(2), b1(3), bG1(4), neut(5).
        target_teams_by_x = [(min(t.x for t in c.flow_node.island.tile_set), c.flow_node.island.team) for c in target_contribs]
        self.assertEqual([(2, -1), (3, expander.target_team), (4, expander.target_team), (5, -1)], target_teams_by_x)

        # The gateway neutral between friendly and enemy is encountered first.
        neutral_contribs = [c for c in target_contribs if c.flow_node.island.team == -1]
        self.assertEqual(2, len(neutral_contribs))
        self.assertEqual(-1, target_contribs[0].flow_node.island.team)
        self.assertEqual((2, 0), min((t.x, t.y) for t in target_contribs[0].flow_node.island.tile_set))

    def test_stream_ordering__two_border_pairs_produce_independent_contributions(self):
        """
        When there are two independent border pairs (e.g. two separate friendly islands
        each bordering the same enemy island), each pair should produce its own
        independent contribution list, not shared/merged data.
        Uses a vertical 2-row map where aG is top-left and an extra a5 is bottom-left.
          aG1  b1  bG1
          a5   b1
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapData = """
|    |    |    |
aG1  b1   bG1
a5   b1
|    |    |    |
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(mapData, 250, fill_out_tiles=True)
        self.begin_capturing_logging()

        expander, builder = self._setup_expander_with_flow_graph(map, general, enemyGeneral)
        stream_results = self._get_border_pair_stream_contributions(expander, builder)

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'two border pairs')

        # Exactly two independent border pairs: one seeded from aG1(0,0), one from a5(0,1).
        self.assertEqual(2, len(stream_results))

        # The two pairs are seeded from distinct friendly islands: aG1 at (0,0) and a5 at (0,1).
        friendly_border_xys = set()
        for _, friendly_contribs, _, _ in stream_results:
            for c in friendly_contribs:
                friendly_border_xys.update(xy for xy in [min((t.x, t.y) for t in c.flow_node.island.tile_set)] if xy[0] == 0)
        self.assertEqual({(0, 0), (0, 1)}, friendly_border_xys)

        # Each pair's friendly contribution island set is independent (not the same set of islands).
        friendly_id_sets = [frozenset(c.island_id for c in friendly_contribs) for _, friendly_contribs, _, _ in stream_results]
        self.assertNotEqual(friendly_id_sets[0], friendly_id_sets[1])

        # All contributions have valid, finite sort_scores.
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            for contrib in friendly_contribs + target_contribs:
                self.assertIsNotNone(contrib.island_id)
                self.assertIsInstance(contrib.sort_score, float)
                self.assertFalse(contrib.sort_score != contrib.sort_score, 'sort_score should not be NaN')
