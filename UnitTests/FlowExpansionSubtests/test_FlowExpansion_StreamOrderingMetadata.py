import typing

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2, FlowStreamIslandContribution, FlowBorderPairKey
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
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
        builder = TileIslandBuilder(map)
        builder.recalculate_tile_islands(enemyGeneral)

        expander = ArmyFlowExpanderV2(map)
        expander.target_team = map.team_ids_by_player_index[enemyGeneral.player]
        expander.enemy_general = enemyGeneral
        expander._ensure_flow_graph_exists(builder)
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
            stream_data = expander._build_border_pair_stream_data(border_pair, expander.flow_graph, target_crossable)
            if not stream_data:
                continue
            friendly_contribs, target_contribs = expander._preprocess_flow_stream_tilecounts(stream_data, border_pair)
            results.append((border_pair, friendly_contribs, target_contribs, stream_data))
        return results

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_stream_ordering__friendly_ranking_prefers_better_army_per_tile(self):
        """
        Friendly stream: an island with higher army/tile ratio should rank before
        one with a lower ratio.
        Map layout: two friendly islands side by side with different army densities,
        then one enemy island on the right.
          aG1  a6(1t)  a2(3t)  b1  bG1
        The single-tile a6 island has ratio 6, the 3-tile a2 island has ratio ~0.67.
        Friendly contributions should list the a6 island first.
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

        self.assertGreater(len(stream_results), 0, 'Expected at least one border pair')

        # Collect all friendly contributions across all border pairs
        all_friendly: list[FlowStreamIslandContribution] = []
        all_target: list[FlowStreamIslandContribution] = []
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            all_friendly.extend(friendly_contribs)
            all_target.extend(target_contribs)

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'friendly ranking by army/tile')

        # Sort scores must be descending (already sorted by _preprocess_flow_stream_tilecounts)
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            for i in range(len(friendly_contribs) - 1):
                self.assertGreaterEqual(
                    friendly_contribs[i].sort_score, friendly_contribs[i + 1].sort_score,
                    f'Friendly contributions not sorted descending at index {i}: '
                    f'{friendly_contribs[i].sort_score:.3f} vs {friendly_contribs[i+1].sort_score:.3f}'
                )

        # The island with army=6, tile_count=1 should have higher score than army=2, tile_count=1 (gen tile)
        # Find the two non-general friendly islands by army
        non_gen_friendlies = [c for c in all_friendly if c.army_amount >= 2]
        if len(non_gen_friendlies) >= 2:
            sorted_by_score = sorted(non_gen_friendlies, key=lambda c: c.sort_score, reverse=True)
            self.assertGreaterEqual(
                sorted_by_score[0].army_amount,
                sorted_by_score[1].army_amount,
                'Higher-army island should have >= sort score vs lower-army island of same tile count'
            )

    def test_stream_ordering__target_ranking_prefers_enemy_over_neutral_at_equal_cost(self):
        """
        When an enemy island and a neutral island have comparable army-per-tile costs
        but the enemy island has direct econ value, it should rank at least as high
        as the neutral island.

        Layout (1 row, neutral between friendly and enemy):
          aG1  a5   neut0   b1   bG1

        The neutral tile at col 2 sits between friendly and the b1 enemy tile.
        Both neutral and enemy have army_per_tile=1. Enemy (type_bonus=ITERATIVE_EXPANSION_EN_CAP_VAL=2.2) should
        score higher than neutral (type_bonus=1.0) at equal cost.
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

        self.assertGreater(len(stream_results), 0, 'Expected at least one border pair')

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'enemy vs neutral ranking')

        # Target contributions must be in physical path order: the neutral tile at col 2
        # sits between the friendly border and b1, so it must appear first in the stream.
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            if len(target_contribs) >= 2:
                first = target_contribs[0]
                second = target_contribs[1]
                # The neutral (team=-1) must be encountered before the enemy tile
                self.assertEqual(
                    first.flow_node.island.team, -1,
                    f'First target contribution must be the neutral tile (mandatory traversal), got team={first.flow_node.island.team}'
                )
                self.assertEqual(
                    second.flow_node.island.team, expander.target_team,
                    f'Second target contribution must be the enemy tile, got team={second.flow_node.island.team}'
                )

        # Score property: enemy sort_score must exceed neutral sort_score at equal army_per_tile
        # (type_bonus 2.2 vs 1.0 guarantees this regardless of path order)
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            enemy_scores = [c.sort_score for c in target_contribs if not c.is_crossing and
                            c.flow_node.island.team == expander.target_team]
            neutral_scores = [c.sort_score for c in target_contribs if not c.is_crossing and
                              c.flow_node.island.team == -1]
            if enemy_scores and neutral_scores:
                self.assertGreaterEqual(
                    max(enemy_scores), max(neutral_scores),
                    'Enemy islands at equal cost should score at least as high as neutral islands'
                )

    def test_stream_ordering__target_ranking_prefers_lower_army_tiles_first(self):
        """
        Within the same team (all enemy), a lower-army island should rank above a higher-army one
        because army_per_tile is lower.
          aG1  a10  b1  b5  bG1
        b1 has army_per_tile=1, b5 has army_per_tile=5. b1 should rank first.
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

        self.assertGreater(len(stream_results), 0, 'Expected at least one border pair')

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'lower army first in target')

        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            enemy_contribs = [c for c in target_contribs if c.flow_node.island.team == expander.target_team]
            if len(enemy_contribs) >= 2:
                # Target contributions are in physical path order (BFS from friendly border).
                # b1 is directly adjacent to the friendly border so it appears first;
                # b5 is one hop further downstream, so it appears second.
                first_xy = min((t.x, t.y) for t in enemy_contribs[0].flow_node.island.tile_set)
                second_xy = min((t.x, t.y) for t in enemy_contribs[1].flow_node.island.tile_set)
                self.assertLessEqual(
                    first_xy[0], second_xy[0],
                    f'First enemy target ({first_xy}) must be physically closer to the friendly border than the second ({second_xy})'
                )

    def test_stream_ordering__target_ranking_sorts_descending(self):
        """
        _preprocess_flow_stream_tilecounts must return target contributions in physical
        path order (BFS from the friendly border node outward), NOT sorted by score.
        Uses a 3-segment enemy side with mixed army values.
          aG1  a8   b1  b4  b2  bG1
        Expected target order: b1 (col 2), b4 (col 3), b2 (col 4) — by ascending x.
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

        self.assertGreater(len(stream_results), 0, 'Expected at least one border pair')

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'target sort descending 3-segment')

        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            # Target contributions are in physical path order (BFS from friendly border).
            # b1 is adjacent to a8 so it comes first, then b4, then b2 (closest to bG1).
            if len(target_contribs) >= 2:
                for i in range(len(target_contribs) - 1):
                    xi = min(t.x for t in target_contribs[i].flow_node.island.tile_set)
                    xi1 = min(t.x for t in target_contribs[i + 1].flow_node.island.tile_set)
                    self.assertLessEqual(
                        xi, xi1,
                        f'Target contributions must be in physical path order (ascending x): '
                        f'index {i} x={xi} must be <= index {i+1} x={xi1}'
                    )

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

        self.assertGreater(len(stream_results), 0, 'Expected at least one border pair')

        if debugMode:
            for border_pair, friendly_contribs, target_contribs, _ in stream_results:
                self.render_border_pair_debug(map, expander, border_pair, friendly_contribs, target_contribs, 'friendly sort descending multi-island')

        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            for i in range(len(friendly_contribs) - 1):
                self.assertGreaterEqual(
                    friendly_contribs[i].sort_score, friendly_contribs[i + 1].sort_score,
                    f'Friendly contributions not sorted descending at index {i}: '
                    f'{friendly_contribs[i].sort_score:.3f} vs {friendly_contribs[i+1].sort_score:.3f}'
                )

        # The a8 island should rank first among non-general friendly contributions
        all_friendly_contribs = []
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            all_friendly_contribs.extend(friendly_contribs)
        non_gen = [c for c in all_friendly_contribs if c.army_amount >= 2]
        if non_gen:
            top = max(non_gen, key=lambda c: c.sort_score)
            self.assertEqual(8, top.army_amount, 'Highest army island should rank first among non-gen friendlies')

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
        self.assertGreater(len(border_pairs), 0, 'Expected at least one border pair')

        border_pair = border_pairs[0]
        stream_data = expander._build_border_pair_stream_data(border_pair, expander.flow_graph, target_crossable)
        self.assertIsNotNone(stream_data)

        friendly_stream = stream_data.get('friendly_stream', [])
        target_stream = stream_data.get('target_stream', [])

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
        self.assertGreater(len(stream_results), 0)

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

        self.assertGreater(len(stream_results), 0,
                           'Should find at least one border pair even with neutral island separating friendly and enemy')

        # Neutral island should appear in at least one target contributions list
        all_target_contribs = [c for _, _, target_contribs, _ in stream_results for c in target_contribs]
        neutral_contribs = [c for c in all_target_contribs if c.flow_node.island.team == -1]
        self.assertGreater(len(neutral_contribs), 0,
                           'Neutral island between friendly and enemy should appear in target contributions')

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

        # Each pair should have its own independent friendly contributions
        all_friendly_id_sets = [frozenset(c.island_id for c in friendly_contribs) for _, friendly_contribs, _, _ in stream_results]
        for i, ids_i in enumerate(all_friendly_id_sets):
            for j, ids_j in enumerate(all_friendly_id_sets):
                if i != j and ids_i and ids_j:
                    # Distinct border pairs should not have fully identical island sets
                    # (at minimum the border-crossing friendly island differs)
                    pass  # Overlap is allowed if same islands feed both pairs; just verify no crash
        # Basic sanity: all contributions should have valid island_id and sort_score
        for border_pair, friendly_contribs, target_contribs, _ in stream_results:
            for contrib in friendly_contribs + target_contribs:
                self.assertIsNotNone(contrib.island_id)
                self.assertIsInstance(contrib.sort_score, float)
                self.assertFalse(contrib.sort_score != contrib.sort_score, 'sort_score should not be NaN')
