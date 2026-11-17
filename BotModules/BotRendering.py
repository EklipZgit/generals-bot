from __future__ import annotations

import typing

import logbook

import DebugHelper
import Utils
from ArmyTracker import EMERGENCE_PATH_CONSISTENCY_FLOOR
from MapMatrix import MapMatrixSet
from Path import Path
from Sim.TextMapLoader import TextMapLoader
from FfaGeneralPlacement import FfaGeneralPlacement
from ViewInfo import TargetStyle, PathColorer, ViewInfo, PlayerGeneralPredictionTarget
from base import Colors
from base.client.map import MapBase, PLAYER_CHAR_BY_INDEX
from ViewInfo import ViewInfo

from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from BotModules.BotSerialization import BotSerialization
from BotModules import BotFfaKillGather
from BotModules import BotFfaEndgame
from BotModules import BotGeneralSafety
from base.client.tile import Tile

if typing.TYPE_CHECKING:
    import EklipZBot

class BotRendering:
    # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown
    # and test_should_commit_wrp_hunt_when_enemy_cannot_defend: render only pending results or route remainder.
    @staticmethod
    def get_stealth_wrp_route_for_render(bot: EklipZBot) -> Path | None:
        """Return the remaining committed route or a completed pending WRP route."""
        state = bot.stealth_all_in
        if state is not None and state.committed_route is not None:
            if state.committed_route.length > 0:
                return state.committed_route
            return None
        if (state is None
                and bot.stealth_hunt_render_path is not None
                and bot.stealth_hunt_render_path.length > 0):
            return bot.stealth_hunt_render_path

        job = (
            state.wrp_job
            if state is not None
            else bot.stealth_hunt_job)
        # StealthWrpJob.done is a plain bool (not a threading.Event) - every
        # other caller reads it as `not job.done`. is_set() threw every turn
        # a hunt job was pending, dropping the move entirely (live t129+).
        if job is None or not job.done or job.result_tile_indexes is None:
            return None

        wrp_path = Path()
        for tile_index in job.result_tile_indexes:
            wrp_path.add_next(bot._map.tiles_by_index[tile_index])
        if wrp_path.length == 0:
            return None
        if state is None:
            return wrp_path

        wrp_tiles = wrp_path.tileList
        if (not wrp_tiles
                or wrp_tiles[0].tile_index != state.entry_tile.tile_index):
            return None
        route = Path()
        for tile in state.flank_path.tileList:
            route.add_next(tile)
        for tile in wrp_tiles[1:]:
            route.add_next(tile)
        return route if route.length > 0 else None

    @staticmethod
    def render_general_prediction_weights_in_view_info(bot: EklipZBot) -> None:
        """
        Render the spawn-fairness weight (bottom left, 'sf') and emergence locality bonus (top right, 'ed') of every
        undiscovered candidate tile for the enemy general prediction, gated by their info_render flags.

        @param bot: the bot whose viewInfo receives the text.
        """
        enemyPlayer = bot.targetPlayer
        if enemyPlayer == -1 and len(bot._map.players) == 2:
            enemyPlayer = 1 - bot._map.player_index
        if enemyPlayer == -1:
            return

        if bot.info_render_general_prediction_spawn_fairness_weights and bot.armyTracker.spawn_fairness_active:
            weightsRaw = bot.armyTracker.spawn_fairness_weights_by_player[enemyPlayer].raw
            for tile in bot._map.pathable_tiles:
                if tile.discovered or tile.isCity:
                    continue
                bot.viewInfo.bottomLeftGridText.raw[tile.tile_index] = f'sf{weightsRaw[tile.tile_index]:.1f}'

        if (
                bot.info_render_general_prediction_emergence_locality_weights
                and bot.targetPlayer != -1
                and bot.shortest_path_to_target_player is not None
        ):
            expectedGeneralDistance = bot.shortest_path_to_target_player.length
            bonusMatrix = bot.armyTracker.build_emergence_distance_bonus_matrix(
                bot.targetPlayer,
                expectedGeneralDistance)
            # Tests/test_GeneralPrediction.py::GeneralPredictionTests.test_should_infer_bottom_right_spawn_from_emergence_direction - render the gated net emergence-locality contribution (locality x path-consistency gate), matching get_predicted_target_player_general_location.
            sourceWeights = bot.armyTracker.build_emergence_path_source_weights(
                bot.targetPlayer,
                bot.win_condition_analyzer.city_contestation_history)
            penaltyMatrix = None
            if len(sourceWeights) > 0:
                distanceToOurGeneral = bot._map.get_distance_matrix_including_obstacles(bot.general)
                penaltyMatrix = bot.armyTracker.build_emergence_path_consistency_penalty_matrix(
                    bot.targetPlayer,
                    sourceWeights,
                    distanceToOurGeneral,
                    expectedGeneralDistance)
            for tile in bot._map.pathable_tiles:
                if tile.discovered or tile.isCity:
                    continue
                tileIndex = tile.tile_index
                netValue = (
                    bot.armyTracker.emergenceLocationMap[bot.targetPlayer][tile] * 10
                    + bonusMatrix.raw[tileIndex])
                if penaltyMatrix is not None:
                    netValue *= max(
                        EMERGENCE_PATH_CONSISTENCY_FLOOR,
                        1.0 - penaltyMatrix.raw[tileIndex])
                if netValue > 0.5:
                    bot.viewInfo.topRightGridText.raw[tileIndex] = f'ed{netValue:.0f}'

    @staticmethod
    def populate_predicted_general_targets(viewInfo: ViewInfo, map: MapBase, placement: FfaGeneralPlacement) -> None:
        """
        Emit one large prediction ring per living player whose general is still
        unknown, seeded from the joint FFA placement. Known generals
        (map.generals[player] set), dead players, and our own general get no
        marker - only genuinely predicted locations are drawn.

        Tests: UnitTests/test_FfaGeneralPlacement.py
        """
        # Rebuild rather than append so repeated populate calls within one frame
        # cannot duplicate markers.
        viewInfo.predicted_general_targets = []
        for player in map.players:
            if player.dead or player.capturedBy is not None or player.index == map.player_index:
                continue
            if map.generals[player.index] is not None:
                continue
            if player.index >= len(placement.positions):
                continue
            seed = placement.positions[player.index]
            if seed is None:
                continue
            viewInfo.predicted_general_targets.append(
                PlayerGeneralPredictionTarget(tile=seed, player=player.index))

    @staticmethod
    def prep_view_info_for_render(bot: EklipZBot, move=None):
        viewInfo = bot.viewInfo
        map: MapBase = bot._map
        viewInfo.board_analysis = bot.board_analysis
        viewInfo.targetingArmy = bot.targetingArmy
        viewInfo.armyTracker = bot.armyTracker
        viewInfo.dangerAnalyzer = bot.dangerAnalyzer
        viewInfo.currentPath = bot.curPath
        viewInfo.gatherNodes = bot.gatherNodes
        viewInfo.redGatherNodes = bot.redGatherTreeNodes
        viewInfo.territories = bot.territories
        viewInfo.allIn = bot.is_all_in_losing
        viewInfo.timings = bot.timings
        viewInfo.allInCounter = bot.all_in_losing_counter
        viewInfo.givingUpCounter = bot.giving_up_counter
        viewInfo.targetPlayer = bot.targetPlayer
        viewInfo.generalApproximations = bot.generalApproximations
        viewInfo.playerTargetScores = bot.playerTargetScores

        stealthWrpRoute = BotRendering.get_stealth_wrp_route_for_render(bot)
        if stealthWrpRoute is not None:
            viewInfo.color_path(
                PathColorer(
                    stealthWrpRoute,
                    255, 105, 180,
                    alpha=255,
                    alphaDecreaseRate=0,
                    alphaMinimum=255))

        movePath = Path()
        if move is not None:
            movePath.add_next(move.source)
            movePath.add_next(move.dest)
            viewInfo.color_path(
                PathColorer(
                    movePath,
                    254, 254, 254,
                    alpha=255,
                    alphaDecreaseRate=0
                ),
                renderOnBottom=True)

        if bot.armyTracker is not None:
            if bot.info_render_army_emergence_values:
                for tile in map.reachable_tiles:
                    val = bot.armyTracker.emergenceLocationMap[bot.targetPlayer][tile]
                    if val != 0:
                        textVal = f"e{val:.1f}"
                        viewInfo.bottomMidRightGridText[tile] = textVal

            # General prediction only re-runs on turns where the prediction is missing or invalidated, and viewInfo
            # is cleared every turn, so render these stored per-tile contributions here every turn instead.
            BotRendering.render_general_prediction_weights_in_view_info(bot)

            # Per-player FFA predicted-general rings (known generals are skipped inside).
            BotRendering.populate_predicted_general_targets(
                viewInfo, map, bot.armyTracker.ffa_general_placement)

            for tile in bot.armyTracker.dropped_fog_tiles_this_turn:
                viewInfo.add_targeted_tile(tile, TargetStyle.RED)

            for tile in bot.armyTracker.decremented_fog_tiles_this_turn:
                viewInfo.add_targeted_tile(tile, TargetStyle.GREEN)

        if bot.info_render_gather_locality_values and bot.gatherAnalyzer is not None:
            for tile in map.pathable_tiles:
                if tile.player == bot.general.player:
                    viewInfo.bottomMidRightGridText[tile] = f'l{bot.gatherAnalyzer.gather_locality_map[tile]}'

        if bot.info_render_tile_deltas:
            BotRendering.render_tile_deltas_in_view_info(bot.viewInfo, map)
        if bot.info_render_tile_states:
            BotRendering.render_tile_state_in_view_info(bot.viewInfo, map)

        if bot.target_player_gather_path is not None:
            alpha = 140
            minAlpha = 100
            alphaDec = 5
            viewInfo.color_path(PathColorer(bot.target_player_gather_path, 60, 50, 0, alpha, alphaDec, minAlpha))

        if bot.board_analysis.intergeneral_analysis is not None:
            nonZoneMatrix = MapMatrixSet(map)
            for tile in map.get_all_tiles():
                if tile not in bot.board_analysis.core_play_area_matrix:
                    nonZoneMatrix.add(tile)
            viewInfo.add_map_zone(nonZoneMatrix, (100, 100, 50), alpha=35)

            if bot.info_render_board_analysis_zones:
                viewInfo.add_map_division(bot.board_analysis.core_play_area_matrix, (10, 230, 0), alpha=150)
                viewInfo.add_map_division(bot.board_analysis.extended_play_area_matrix, (255, 230, 0), alpha=150)
                viewInfo.add_map_division(bot.board_analysis.flank_danger_play_area_matrix, (205, 80, 40), alpha=255)
                viewInfo.add_map_division(bot.board_analysis.flankable_fog_area_matrix, (0, 0, 0), alpha=255)
                viewInfo.add_map_zone(bot.board_analysis.flankable_fog_area_matrix, (255, 255, 255), alpha=40)
                viewInfo.add_map_zone(bot.board_analysis.backwards_tiles, (50, 100, 50), 75)

        viewInfo.team_cycle_stats = bot.opponent_tracker.current_team_cycle_stats
        viewInfo.team_last_cycle_stats = bot.opponent_tracker.get_last_cycle_stats_per_team()
        viewInfo.player_fog_tile_counts = bot.opponent_tracker.get_all_player_fog_tile_count_dict()
        viewInfo.player_fog_risks = [bot.opponent_tracker.get_approximate_fog_army_risk(p) for p in range(len(map.players))]

        if bot.info_render_centrality_distances:
            for tile in map.get_all_tiles():
                viewInfo.bottomLeftGridText[tile] = f'cen{bot.board_analysis.defense_centrality_sums[tile]}'

        if bot.info_render_pathway_distances:
            for tile in map.get_all_tiles():
                pw = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix.raw[tile.tile_index]
                if pw is None:
                    viewInfo.bottomLeftGridText[tile] = f'pwN'
                else:
                    viewInfo.bottomLeftGridText[tile] = f'pw{pw.distance}'

        if bot.enemy_attack_path is not None:
            viewInfo.color_path(PathColorer(
                bot.enemy_attack_path,
                255, 185, 75,
                alpha=255,
                alphaDecreaseRate=5
            ))

        if bot.targetPlayer >= 0 and not bot.targetPlayerExpectedGeneralLocation.isGeneral:
            for t in bot.alt_en_gen_positions[bot.targetPlayer]:
                viewInfo.add_targeted_tile(t, TargetStyle.YELLOW, radiusReduction=3)

        if bot.info_render_board_analysis_choke_widths and bot.board_analysis.intergeneral_analysis:
            for tile in map.get_all_tiles():
                w = ''
                if tile in bot.board_analysis.intergeneral_analysis.chokeWidths:
                    w = str(bot.board_analysis.intergeneral_analysis.chokeWidths[tile])
                viewInfo.topRightGridText[tile] = f'cw{w}'

        for p in bot.armyTracker.unconnectable_tiles:
            for t in p:
                viewInfo.add_targeted_tile(t, targetStyle=TargetStyle.RED, radiusReduction=-5)
        for p, matrix in enumerate(bot.armyTracker.player_connected_tiles):
            if not map.is_player_on_team_with(bot.player.index, p) and not map.players[p].dead:
                scaledColor = Utils.rescale_color(0.55, 0, 1.0, Colors.PLAYER_COLORS[p], Colors.GRAY_DARK)
                viewInfo.add_map_division(matrix, scaledColor, alpha=150)
                viewInfo.add_map_zone(matrix, scaledColor, alpha=65)

        if move is not None:
            viewInfo.color_path(PathColorer(
                movePath,
                254, 254, 254,
                alpha=135,
                alphaDecreaseRate=0
            ))

        if bot.info_render_defense_spanning_tree and bot.defensive_spanning_tree:
            viewInfo.add_map_division(bot.defensive_spanning_tree, Colors.WHITE, alpha=200, thickness=4)
            viewInfo.add_map_zone(bot.defensive_spanning_tree, Colors.P_MAROON, alpha=100)

        if bot.win_condition_analyzer.defend_cities:
            viewInfo.add_targeted_tiles_with_legend(bot.win_condition_analyzer.defend_cities, 'DEFEND CITIES', TargetStyle.PURPLE, radiusReduction=3)

        if bot.info_render_friendly_city_spanning_tree and bot.friendly_city_spanning_tree:
            viewInfo.add_map_zone(bot.friendly_city_spanning_tree, Colors.GOLD, alpha=50)

        if bot.info_render_tile_islands:
            for island in sorted(bot.tileIslandBuilder.all_tile_islands, key=lambda i: (i.team, str(i.name))):
                if island.name:
                    for tile in island.tile_set:
                        if viewInfo.topRightGridText[tile]:
                            viewInfo.midRightGridText[tile] = island.name
                        else:
                            viewInfo.topRightGridText[tile] = island.name

        if bot.last_flow_expander is not None and bot.last_flow_opt_collection is not None:
            if bot.info_render_flow_expand:
                BotRendering.render_flow_expand_in_view_info(bot, dontLogOpts=True)
            else:
                if bot.last_flow_expander.log_debug:
                    logbook.warning('FLOW_RENDER_SKIPPED info_render_flow_expand=False')

        if bot.info_render_enemy_vision_data and bot.targetPlayer != -1 and bot.armyTracker is not None:
            visRaw = bot.armyTracker.visible_tiles_by_player[bot.targetPlayer].raw
            for tile in map.tiles_by_index:
                viewInfo.midLeftGridText.raw[tile.tile_index] = f'+' if visRaw[tile.tile_index] else '-'
            seenRaw = bot.armyTracker.seen_tiles_by_player[bot.targetPlayer].raw
            for tile in map.tiles_by_index:
                viewInfo.midRightGridText.raw[tile.tile_index] = f'+' if seenRaw[tile.tile_index] else '-'

    @staticmethod
    def render_flow_expand_in_view_info(bot: EklipZBot, dontLogOpts: bool = False):
        expander = bot.last_flow_expander
        optCollection = bot.last_flow_opt_collection
        vi: ViewInfo = bot.viewInfo
        general = expander.friendlyGeneral
        enemyGeneral = expander.enemyGeneral
        opts = optCollection.expansion_options

        optsSorted = sorted(opts, key=lambda opt: (opt.length, opt.econValue), reverse=True)

        first = set()
        dupes = set()
        first_option_by_tile = {}
        duplicate_option_details = []

        for opt in optsSorted:
            for tile in opt.tileSet:
                if tile in first:
                    dupes.add(tile)
                    duplicate_option_details.append(
                        f'{tile.x},{tile.y}: first={first_option_by_tile[tile]} duplicate={str(opt)}'
                    )
                else:
                    first.add(tile)
                    first_option_by_tile[tile] = str(opt)

        if len(dupes) > 0:
            vi.add_targeted_tiles_with_legend(dupes, 'GRAY = DUPLICATE FLOW OPTION TILES', TargetStyle.GRAY, radiusReduction=-1, )
        if dupes:
            vi.add_info_line('FE DUPE: ' + f'|'.join(f'{t.x},{t.y}' for t in dupes))
            logbook.warning(
                f'FLOW_RENDER_DUPLICATE_OPTION_TILES count={len(dupes)} '
                f'details=[{" || ".join(duplicate_option_details[:64])}]'
            )

        if optsSorted:
            try:
                bestOpt = next(filter(lambda opt: opt.length > 3, optsSorted))
            except StopIteration:
                bestOpt = optsSorted[0]

            vi.add_info_line_no_log(str(bestOpt) + '   ' + '|'.join(f'{t.x},{t.y}' for t in bestOpt.tileList))
            if enemyGeneral is not None:
                ArmyFlowExpander.add_flow_expansion_option_to_view_info(bot._map, bestOpt, general.player, enemyGeneral.player, vi)

        if not dontLogOpts:
            vi.add_info_line('-------- v all options --------')
            for opt in opts:
                vi.add_info_line_no_log(str(opt) + '   ' + '|'.join(f'{t.x},{t.y}' for t in opt.tileList))
                if enemyGeneral is not None:
                    ArmyFlowExpander.add_flow_expansion_option_to_view_info(bot._map, opt, general.player, enemyGeneral.player, vi)

        flowGraph = expander.flow_graph
        if flowGraph is not None:
            arrowsBefore = len(vi.arrows)
            ArmyFlowExpander.add_flow_graph_to_view_info(flowGraph, vi, lastRun=expander.last_run, noLog=True)
            arrowsAfter = len(vi.arrows)
            noNeutRoots = len(flowGraph.root_flow_nodes_no_neut)
            noNeutEdges = sum(len(node.flow_to) for node in flowGraph.root_flow_nodes_no_neut)
            incNeutRoots = len(flowGraph.root_flow_nodes_inc_neut)
            incNeutEdges = sum(len(node.flow_to) for node in flowGraph.root_flow_nodes_inc_neut)
            if expander.log_debug:
                logbook.warning(
                    f'FLOW_RENDER_GRAPH rootsNoNeut={noNeutRoots} rootEdgesNoNeut={noNeutEdges} '
                    f'rootsIncNeut={incNeutRoots} rootEdgesIncNeut={incNeutEdges} '
                    f'arrowsAdded={arrowsAfter - arrowsBefore} arrowsTotal={arrowsAfter}'
                )

            # Render red target circles around islands connected to fake nodes
            graph_data = expander.flow_graph_data
            if graph_data is not None:
                fake_connected_island_ids = set()
                fake_connected_island_ids.update(graph_data.disconnected_component_island_ids)
                fake_connected_island_ids.update(graph_data.directed_repair_source_island_ids)
                fake_connected_island_ids.update(graph_data.directed_repair_sink_island_ids)
                fake_connected_island_ids.update(graph_data.overflow_dump_target_island_ids)

                if fake_connected_island_ids:
                    for island_id in fake_connected_island_ids:
                        island = expander.island_builder.tile_islands_by_unique_id.get(island_id)
                        if island is not None:
                            for tile in island.tile_set:
                                vi.add_targeted_tile(tile, TargetStyle.RED, radiusReduction=-5)
        if not bot.info_render_tile_islands:
            expander.island_builder.add_tile_islands_to_view_info(vi, printIslandInfoLines=False, renderIslandNames=True, renderIslandColors=False)

    @staticmethod
    def mark_tile(bot: EklipZBot, tile, alpha=100):
        bot.viewInfo.evaluatedGrid[tile.x][tile.y] = alpha

    @staticmethod
    def render_tile_deltas_in_view_info(viewInfo: ViewInfo, map: MapBase):
        for tile in map.tiles_by_index:
            renderMore = False
            if (
                    tile.delta.armyMovedHere
                    or tile.delta.lostSight
                    or tile.delta.gainedSight
                    or tile.delta.discovered
                    or tile.delta.armyDelta != 0
                    or tile.delta.unexplainedDelta != 0
                    or tile.delta.fromTile is not None
                    or tile.delta.toTile is not None
            ):
                renderMore = True

            s = []
            if tile.delta.armyMovedHere:
                s.append('M')
            if tile.delta.imperfectArmyDelta:
                s.append('I')
            if tile.delta.lostSight:
                s.append('L')
            if tile.delta.gainedSight:
                s.append('G')
            if tile.delta.discovered:
                s.append('D')
            s.append(' ')
            viewInfo.bottomRightGridText.raw[tile.tile_index] = ''.join(s)

            if tile.delta.armyDelta != 0:
                viewInfo.bottomLeftGridText.raw[tile.tile_index] = f'd{tile.delta.armyDelta:+d}'
            if tile.delta.unexplainedDelta != 0:
                viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'u{tile.delta.unexplainedDelta:+d}'
            if renderMore:
                moves = ''
                if tile.delta.toTile and tile.delta.fromTile:
                    moves = f'{str(tile.delta.fromTile)}-{str(tile.delta.toTile)}'
                elif tile.delta.fromTile:
                    moves = f'<-{str(tile.delta.fromTile)}'
                elif tile.delta.toTile:
                    moves = f'->{str(tile.delta.toTile)}'
                viewInfo.topRightGridText.raw[tile.tile_index] = moves
                viewInfo.midRightGridText.raw[tile.tile_index] = f'{tile.delta.oldArmy}'
                if tile.delta.oldOwner != tile.delta.newOwner:
                    viewInfo.bottomMidRightGridText.raw[tile.tile_index] = f'{tile.delta.oldOwner}-{tile.delta.newOwner}'

    @staticmethod
    def render_tile_state_in_view_info(viewInfo: ViewInfo, map: MapBase):
        for tile in map.tiles_by_index:
            s = []
            if tile.isPathable:
                pass
            else:
                s.append('-')
            if tile in map.pathable_tiles:
                pass
            else:
                s.append('-')
            if tile.isCostlyNeutralCity:
                s.append('C')
            if tile not in map.reachable_tiles:
                s.append('X')
            if tile.isObstacle:
                s.append('O')
            if tile.isMountain:
                s.append('M')
            if tile.overridePathable is not None:
                if tile.overridePathable:
                    s.append('p')
                else:
                    s.append('z')
            s.append(' ')
            viewInfo.bottomMidRightGridText.raw[tile.tile_index] = ''.join(s)

    @staticmethod
    def add_city_score_to_view_info(score, viewInfo):
        tile = score.tile
        viewInfo.topRightGridText[tile] = f'r{f"{score.city_relevance_score:.2f}".strip("0")}'
        viewInfo.midRightGridText[tile] = f'e{f"{score.city_expandability_score:.2f}".strip("0")}'
        viewInfo.bottomMidRightGridText[tile] = f'd{f"{score.city_defensability_score:.2f}".strip("0")}'
        viewInfo.bottomRightGridText[tile] = f'g{f"{score.city_general_defense_score:.2f}".strip("0")}'

        if tile.player >= 0:
            scoreVal = score.get_weighted_enemy_capture_value()
            viewInfo.bottomLeftGridText[tile] = f'e{f"{scoreVal:.2f}".strip("0")}'
        else:
            scoreVal = score.get_weighted_neutral_value()
            viewInfo.bottomLeftGridText[tile] = f'n{f"{scoreVal:.2f}".strip("0")}'

    @staticmethod
    def render_intercept_plan(bot: EklipZBot, plan, colorIndex: int = 0):
        targetStyle = TargetStyle(((colorIndex + 1) % 9) + 1)
        for tile, interceptInfo in plan.common_intercept_chokes.items():
            bot.viewInfo.add_targeted_tile(tile, targetStyle, radiusReduction=11 - colorIndex)

            bot.viewInfo.bottomMidRightGridText[tile] = f'cw{interceptInfo.max_choke_width}'

            bot.viewInfo.bottomMidLeftGridText[tile] = f'ic{interceptInfo.max_intercept_turn_offset}'

            bot.viewInfo.bottomLeftGridText[tile] = f'it{interceptInfo.max_delay_turns}'

            bot.viewInfo.midRightGridText[tile] = f'im{interceptInfo.max_extra_moves_to_capture}'

        if DebugHelper.is_debug_or_unit_test_mode():
            bot.viewInfo.add_info_line(f'  intChokes @{plan.target_tile} = {targetStyle}')

        if DebugHelper.is_debug_or_unit_test_mode():
            for dist, opt in plan.intercept_options.items():
                logbook.info(f'intercept plan opt {plan.target_tile} dist {dist}: {str(opt)}')

    @staticmethod
    def dump_turn_data_to_string(bot: EklipZBot):
        charMap = PLAYER_CHAR_BY_INDEX

        data = []

        data.append(f'bot_target_player={bot.targetPlayer}')
        if bot.targetPlayerExpectedGeneralLocation and bot.targetPlayer != -1:
            data.append(f'targetPlayerExpectedGeneralLocation={bot.targetPlayerExpectedGeneralLocation.x},{bot.targetPlayerExpectedGeneralLocation.y}')
        if bot.locked_launch_point is not None:
            data.append(f'bot_locked_launch_point={bot.locked_launch_point.x},{bot.locked_launch_point.y}')
        data.append(f'bot_is_all_in_losing={bot.is_all_in_losing}')
        data.append(f'bot_all_in_losing_counter={bot.all_in_losing_counter}')

        data.append(f'bot_is_winning_gather_cyclic={bot.is_winning_gather_cyclic}')
        data.append(f'bot_is_all_in_army_advantage={bot.is_all_in_army_advantage}')
        data.append(f'bot_all_in_army_advantage_counter={bot.all_in_army_advantage_counter}')
        data.append(f'bot_all_in_army_advantage_cycle={bot.all_in_army_advantage_cycle}')
        # Tests/test_AllIn.py::AllInTests.test_should_stop_allinning_and_city_after_failed_attack:
        # Dump resume-only all-in/city and failed-attack state so continuation tests preserve the live failed attack branch.
        data.append(f'bot_all_in_city_behind={bot.all_in_city_behind}')
        data.append(f'bot_defend_economy={bot.defend_economy}')
        data.append(f'bot_attack_failed_turn={bot.attackFailedTurn}')
        data.append(f'bot_count_failed_quick_attacks={bot.countFailedQuickAttacks}')
        data.append(f'bot_count_failed_high_depth_attacks={bot.countFailedHighDepthAttacks}')
        data.append(f'bot_last_target_attack_turn={bot.lastTargetAttackTurn}')
        data.append(f'bot_force_far_gathers={bot.force_far_gathers}')
        data.append(f'bot_force_far_gathers_turns={bot.force_far_gathers_turns}')
        data.append(f'bot_force_far_gathers_sleep_turns={bot.force_far_gathers_sleep_turns}')
        if bot.timings is not None:
            data.append(f'bot_timings_launch_timing={bot.timings.launchTiming}')
            data.append(f'bot_timings_split_turns={bot.timings.splitTurns}')
            data.append(f'bot_timings_quick_expand_turns={bot.timings.quickExpandTurns}')
            data.append(f'bot_timings_cycle_turns={bot.timings.cycleTurns}')
            data.append(f'bot_timings_disallow_enemy_gather={bot.timings.disallowEnemyGather}')

        data.append(f'bot_is_rapid_capturing_neut_cities={bot.is_rapid_capturing_neut_cities}')
        data.append(f'bot_is_blocking_neutral_city_captures={bot.is_blocking_neutral_city_captures}')
        data.append(f'bot_was_allowing_neutral_cities_last_turn={bot.was_allowing_neutral_cities_last_turn}')
        # Tests/test_CityContestation.py CityContestationTests.test_should_serialize_and_deserialize_city_capture_plan_tiles:
        # Resume tests need the existing city plan preserved so CITY_SAFETY_NEGS existing-plan behavior can be exercised.
        data.append(f'bot_city_capture_plan_tiles={BotSerialization.convert_tile_set_to_string(bot, bot.city_capture_plan_tiles)}')
        data.append(f'bot_city_capture_plan_last_updated={bot.city_capture_plan_last_updated}')
        data.append(f'bot_finishing_exploration={bot.finishing_exploration}')
        if bot.targetingArmy:
            data.append(f'bot_targeting_army={bot.targetingArmy.tile.x},{bot.targetingArmy.tile.y}')
        data.append(f'bot_cur_path={str(bot.curPath)}')
        if bot.last_move is not None:
            data.append(f'bot_last_move={BotSerialization.convert_move_to_string(bot.last_move)}')
        # Tests/test_AllIn.py resume support: persist the committed stealth/WRP route so a txtmap
        # dumped mid-all-in reloads into the same committed state (restored by
        # BotStealthAllIn.load_committed_route_from_resume_data). str(Path) only contains the
        # remaining not-yet-walked nodes, which is exactly what must resume.
        if bot.stealth_all_in is not None and bot.stealth_all_in.committed_route is not None:
            stealthState = bot.stealth_all_in
            data.append(f'bot_stealth_committed_route={str(stealthState.committed_route)}')
            data.append(f'bot_stealth_launch_tile={stealthState.launch_tile.x},{stealthState.launch_tile.y}')
            data.append(f'bot_stealth_entry_tile={stealthState.entry_tile.x},{stealthState.entry_tile.y}')
            data.append(f'bot_stealth_flank_path={str(stealthState.flank_path)}')
            data.append(f'bot_stealth_launch_turn={stealthState.launch_turn}')
            data.append(f'bot_stealth_committed_turn={stealthState.committed_turn}')
            data.append(f'bot_stealth_generation={stealthState.generation}')
            data.append(f'bot_stealth_is_undefendable_hunt={stealthState.is_undefendable_hunt}')
            data.append(f'bot_stealth_is_truncated_front={stealthState.is_truncated_front}')
            data.append(f'bot_stealth_is_desperation_dive={stealthState.is_desperation_dive}')
            data.append(f'bot_stealth_gather_fallback_turns={stealthState.used_normal_gather_fallback_turns}')
            # Tests/test_AllIn.py::AllInTests.test_should_keep_diving_general_candidates_after_revealing_empty_tile:
            # mid-route resumes need the commit-time army baseline so a wall revealed between
            # commit and dump is not re-flagged as new.
            data.append(
                'bot_stealth_route_army_snapshot='
                + ','.join(
                    f'{idx}:{army}'
                    for idx, army in stealthState.committed_route_army_snapshot.items()))
            data.append(f'bot_stealth_all_in_generation={bot.stealth_all_in_generation}')
        data.append(f'bot_stealth_cannot_kill_counter={bot.stealth_all_in_cannot_kill_counter}')

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # persist the latched FFA endgame retaliation target and direct-kill history across
        # mid-fight txtmap resumes (capturedBy is runtime state not preserved on import).
        for key, value in BotFfaEndgame.save_state(bot).items():
            data.append(f'{key}={value}')

        # FFA (>2 living teams) kill-gather committed state, restored by
        # BotFfaKillGather.load_state from load_resume_data. Values never contain '='.
        for key, value in BotFfaKillGather.save_state(bot).items():
            data.append(f'{key}={value}')

        # General-safety reservation episodes/anchor/literal gather, restored by
        # BotGeneralSafety.load_state from load_resume_data. Values never contain '='.
        for key, value in BotGeneralSafety.save_state(bot).items():
            data.append(f'{key}={value}')

        for player in bot._map.players:
            char = charMap[player.index]
            unsafeUserName = bot._map.usernames[player.index].replace('=', '__')

            safeUserName = ''.join([i if ord(i) < 128 else ' ' for i in unsafeUserName])
            data.append(f'{char}Username={safeUserName}')
            data.append(f'{char}Tiles={player.tileCount}')
            data.append(f'{char}Score={player.score}')
            data.append(f'{char}StandingArmy={player.standingArmy}')
            data.append(f'{char}Stars={player.stars}')
            data.append(f'{char}CityCount={player.cityCount}')
            if player.general is not None:
                data.append(f'{char}General={player.general.x},{player.general.y}')
            data.append(f'{char}KnowsKingLocation={player.knowsKingLocation}')
            data.append(f'{char}KnowsKingSinceTurn={player.king_location_revealed_turn}')
            if bot._map.is_2v2:
                data.append(f'{char}KnowsAllyKingLocation={player.knowsAllyKingLocation}')
            data.append(f'{char}Dead={player.dead}')
            # Tests/test_FFA.py credited-kill persistence: write the authoritative has_kill flag
            # only when known so a SilentWar/unknown state round-trips as absent (None), never False.
            if player.has_kill is not None:
                data.append(f'{char}HasKill={player.has_kill}')
            data.append(f'{char}LeftGame={player.leftGame}')
            data.append(f'{char}LeftGameTurn={player.leftGameTurn}')
            data.append(f'{char}AggressionFactor={player.aggression_factor}')
            data.append(f'{char}Delta25Tiles={player.delta25tiles}')
            data.append(f'{char}Delta25Score={player.delta25score}')
            data.append(f'{char}CityGainedTurn={player.cityGainedTurn}')
            data.append(f'{char}CityLostTurn={player.cityLostTurn}')
            data.append(f'{char}LastSeenMoveTurn={player.last_seen_move_turn}')
            data.append(f'{char}Emergences={BotSerialization.convert_float_map_matrix_to_string(bot, bot.armyTracker.emergenceLocationMap[player.index])}')
            # UnitTests/test_SpawnFairness.py::SpawnFairnessTests.test_serialization_round_trip_and_missing_matrix_rebuild - persist negative weights so resumed games retain hard eliminations.
            data.append(f'{char}SpawnFairness={BotSerialization.convert_float_map_matrix_to_string(bot, bot.armyTracker.spawn_fairness_weights_by_player[player.index])}')
            data.append(f'{char}ValidGeneralPos={BotSerialization.convert_bool_map_matrix_to_string(bot, bot.armyTracker.valid_general_positions_by_player[player.index])}')
            data.append(f'{char}TilesEverOwned={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.tiles_ever_owned_by_player[player.index])}')
            data.append(f'{char}UneliminatedEmergences={BotSerialization.convert_tile_int_dict_to_string(bot, bot.armyTracker.uneliminated_emergence_events[player.index])}')
            data.append(f'{char}UneliminatedEmergenceCityPerfectInfo={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index])}')
            data.append(f'{char}UnrecapturedEmergences={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.unrecaptured_emergence_events[player.index])}')
            # Joint FFA general-placement land evidence (frozen inverse-tileCount
            # weights + witnessed-transfer flags) so resumed games keep identical
            # centroids; missing key on legacy fixtures bootstraps from discovered
            # tiles only. Tests: UnitTests/test_FfaGeneralPlacement.py
            data.append(f'{char}GeneralLandEvidence={BotSerialization.convert_general_land_evidence_to_string(bot, bot.armyTracker.ffa_general_land_evidence[player.index])}')
            if len(bot.generalApproximations) > player.index:
                if bot.generalApproximations[player.index][3] is not None:
                    data.append(f'{char}_bot_general_approx={str(bot.generalApproximations[player.index][3])}')

        tempSet = set()
        neutDiscSet = set()
        lastMovedTiles: typing.Dict[Tile, int] = {}
        for tile in bot._map.get_all_tiles():
            if tile.isTempFogPrediction:
                tempSet.add(tile)
            if tile.discoveredAsNeutral:
                neutDiscSet.add(tile)
            # Serialize lastMovedTurn for tiles that moved recently (within last 5 turns)
            if tile.lastMovedTurn >= bot._map.turn - 5 and tile.lastMovedTurn >= 0:
                lastMovedTiles[tile] = tile.lastMovedTurn
        # Retained ex-general exclusion anchors for joint FFA placement (dead
        # players' former generals + discoveredExGeneralCity discoveries).
        data.append(f'FFAExGeneralBlockers={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.ffa_general_placement.ex_general_blockers)}')
        # Joint FFA predicted-general positions so a resumed game restores the
        # same seeds as sticky no-info priors; '-1' slots for unplaced players.
        # Tests: UnitTests/test_FfaGeneralPlacement.py,
        # Tests/test_FogLandBuilder.py::FogLandBuilderTests.test_should_roundtrip_ffa_predicted_general_positions
        data.append(f'FFAPredictedGeneralPositions={BotSerialization.convert_general_positions_to_string(bot)}')
        data.append(f'TempFogTiles={BotSerialization.convert_tile_set_to_string(bot, tempSet)}')
        data.append(f'DiscoveredNeutral={BotSerialization.convert_tile_set_to_string(bot, neutDiscSet)}')
        data.append(f'DefensiveSpanningTree={BotSerialization.convert_tile_set_to_string(bot, bot.defensive_spanning_tree)}')
        data.append(f'FriendlyCitySpanningTree={BotSerialization.convert_tile_set_to_string(bot, bot.friendly_city_spanning_tree)}')
        data.extend(bot.win_condition_analyzer.dump_city_contestation_history())
        # Serialize lastMovedTurn as tile_index:turn pairs
        if lastMovedTiles:
            lastMovedStr = ','.join(f'{t.tile_index}:{turn}' for t, turn in lastMovedTiles.items())
            data.append(f'LastMovedTiles={lastMovedStr}')

        data.append(f'Armies={TextMapLoader.dump_armies(bot._map, bot.armyTracker.armies)}')

        data.append(bot.opponent_tracker.dump_to_string_data())
        data.append(BotSerialization.convert_army_tracker_seen_tiles_to_string(bot))

        # Serialize island_ids if tileIslandBuilder exists
        if bot.tileIslandBuilder is not None:
            data.append(BotSerialization.convert_island_builder_to_string(bot, bot.tileIslandBuilder))

        return '\n'.join(data)
