from __future__ import annotations

import typing

import logbook

import DebugHelper
import Utils
from MapMatrix import MapMatrixSet
from Path import Path
from Sim.TextMapLoader import TextMapLoader
from ViewInfo import TargetStyle, PathColorer, ViewInfo
from base import Colors
from base.client.map import MapBase, PLAYER_CHAR_BY_INDEX
from ViewInfo import ViewInfo

from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from BotModules.BotSerialization import BotSerialization
from base.client.tile import Tile

if typing.TYPE_CHECKING:
    import EklipZBot

class BotRendering:
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
            if bot._map.is_2v2:
                data.append(f'{char}KnowsAllyKingLocation={player.knowsAllyKingLocation}')
            data.append(f'{char}Dead={player.dead}')
            data.append(f'{char}LeftGame={player.leftGame}')
            data.append(f'{char}LeftGameTurn={player.leftGameTurn}')
            data.append(f'{char}AggressionFactor={player.aggression_factor}')
            data.append(f'{char}Delta25Tiles={player.delta25tiles}')
            data.append(f'{char}Delta25Score={player.delta25score}')
            data.append(f'{char}CityGainedTurn={player.cityGainedTurn}')
            data.append(f'{char}CityLostTurn={player.cityLostTurn}')
            data.append(f'{char}LastSeenMoveTurn={player.last_seen_move_turn}')
            data.append(f'{char}Emergences={BotSerialization.convert_float_map_matrix_to_string(bot, bot.armyTracker.emergenceLocationMap[player.index])}')
            data.append(f'{char}ValidGeneralPos={BotSerialization.convert_bool_map_matrix_to_string(bot, bot.armyTracker.valid_general_positions_by_player[player.index])}')
            data.append(f'{char}TilesEverOwned={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.tiles_ever_owned_by_player[player.index])}')
            data.append(f'{char}UneliminatedEmergences={BotSerialization.convert_tile_int_dict_to_string(bot, bot.armyTracker.uneliminated_emergence_events[player.index])}')
            data.append(f'{char}UneliminatedEmergenceCityPerfectInfo={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index])}')
            data.append(f'{char}UnrecapturedEmergences={BotSerialization.convert_tile_set_to_string(bot, bot.armyTracker.unrecaptured_emergence_events[player.index])}')
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
