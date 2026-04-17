import logbook

import Utils
from MapMatrix import MapMatrixSet
from Path import Path
from Sim.TextMapLoader import TextMapLoader
from ViewInfo import TargetStyle, PathColorer
from base import Colors
from base.client.map import MapBase, PLAYER_CHAR_BY_INDEX
from ViewInfo import ViewInfo

from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from BotModules.BotSerialization import BotSerialization

class BotRendering:
    @staticmethod
    def prep_view_info_for_render(bot, move=None):
        bot.viewInfo.board_analysis = bot.board_analysis
        bot.viewInfo.targetingArmy = bot.targetingArmy
        bot.viewInfo.armyTracker = bot.armyTracker
        bot.viewInfo.dangerAnalyzer = bot.dangerAnalyzer
        bot.viewInfo.currentPath = bot.curPath
        bot.viewInfo.gatherNodes = bot.gatherNodes
        bot.viewInfo.redGatherNodes = bot.redGatherTreeNodes
        bot.viewInfo.territories = bot.territories
        bot.viewInfo.allIn = bot.is_all_in_losing
        bot.viewInfo.timings = bot.timings
        bot.viewInfo.allInCounter = bot.all_in_losing_counter
        bot.viewInfo.givingUpCounter = bot.giving_up_counter
        bot.viewInfo.targetPlayer = bot.targetPlayer
        bot.viewInfo.generalApproximations = bot.generalApproximations
        bot.viewInfo.playerTargetScores = bot.playerTargetScores

        movePath = Path()
        if move is not None:
            movePath.add_next(move.source)
            movePath.add_next(move.dest)
            bot.viewInfo.color_path(
                PathColorer(
                    movePath,
                    254, 254, 254,
                    alpha=255,
                    alphaDecreaseRate=0
                ),
                renderOnBottom=True)

        if bot.armyTracker is not None:
            if bot.info_render_army_emergence_values:
                for tile in bot._map.reachable_tiles:
                    val = bot.armyTracker.emergenceLocationMap[bot.targetPlayer][tile]
                    if val != 0:
                        textVal = f"e{val:.0f}"
                        bot.viewInfo.bottomMidRightGridText[tile] = textVal

            for tile in bot.armyTracker.dropped_fog_tiles_this_turn:
                bot.viewInfo.add_targeted_tile(tile, TargetStyle.RED)

            for tile in bot.armyTracker.decremented_fog_tiles_this_turn:
                bot.viewInfo.add_targeted_tile(tile, TargetStyle.GREEN)

        if bot.info_render_gather_locality_values and bot.gatherAnalyzer is not None:
            for tile in bot._map.pathable_tiles:
                if tile.player == bot.general.player:
                    bot.viewInfo.bottomMidRightGridText[tile] = f'l{bot.gatherAnalyzer.gather_locality_map[tile]}'

        if bot.info_render_tile_deltas:
            BotRendering.render_tile_deltas_in_view_info(bot.viewInfo, bot._map)
        if bot.info_render_tile_states:
            BotRendering.render_tile_state_in_view_info(bot.viewInfo, bot._map)

        if bot.target_player_gather_path is not None:
            alpha = 140
            minAlpha = 100
            alphaDec = 5
            bot.viewInfo.color_path(PathColorer(bot.target_player_gather_path, 60, 50, 0, alpha, alphaDec, minAlpha))

        if bot.board_analysis.intergeneral_analysis is not None:
            nonZoneMatrix = MapMatrixSet(bot._map)
            for tile in bot._map.get_all_tiles():
                if tile not in bot.board_analysis.core_play_area_matrix:
                    nonZoneMatrix.add(tile)
            bot.viewInfo.add_map_zone(nonZoneMatrix, (100, 100, 50), alpha=35)

            if bot.info_render_board_analysis_zones:
                bot.viewInfo.add_map_division(bot.board_analysis.core_play_area_matrix, (10, 230, 0), alpha=150)
                bot.viewInfo.add_map_division(bot.board_analysis.extended_play_area_matrix, (255, 230, 0), alpha=150)
                bot.viewInfo.add_map_division(bot.board_analysis.flank_danger_play_area_matrix, (205, 80, 40), alpha=255)
                bot.viewInfo.add_map_division(bot.board_analysis.flankable_fog_area_matrix, (0, 0, 0), alpha=255)
                bot.viewInfo.add_map_zone(bot.board_analysis.flankable_fog_area_matrix, (255, 255, 255), alpha=40)
                bot.viewInfo.add_map_zone(bot.board_analysis.backwards_tiles, (50, 100, 50), 75)

        bot.viewInfo.team_cycle_stats = bot.opponent_tracker.current_team_cycle_stats
        bot.viewInfo.team_last_cycle_stats = bot.opponent_tracker.get_last_cycle_stats_per_team()
        bot.viewInfo.player_fog_tile_counts = bot.opponent_tracker.get_all_player_fog_tile_count_dict()
        bot.viewInfo.player_fog_risks = [bot.opponent_tracker.get_approximate_fog_army_risk(p) for p in range(len(bot._map.players))]

        if bot.info_render_centrality_distances:
            for tile in bot._map.get_all_tiles():
                bot.viewInfo.bottomLeftGridText[tile] = f'cen{bot.board_analysis.defense_centrality_sums[tile]}'

        if bot.info_render_pathway_distances:
            for tile in bot._map.get_all_tiles():
                pw = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix.raw[tile.tile_index]
                if pw is None:
                    bot.viewInfo.bottomLeftGridText[tile] = f'pwN'
                else:
                    bot.viewInfo.bottomLeftGridText[tile] = f'pw{pw.distance}'

        if bot.enemy_attack_path is not None:
            bot.viewInfo.color_path(PathColorer(
                bot.enemy_attack_path,
                255, 185, 75,
                alpha=255,
                alphaDecreaseRate=5
            ))

        if bot.targetPlayer >= 0 and not bot.targetPlayerExpectedGeneralLocation.isGeneral:
            for t in bot.alt_en_gen_positions[bot.targetPlayer]:
                bot.viewInfo.add_targeted_tile(t, TargetStyle.YELLOW, radiusReduction=3)

        if bot.info_render_board_analysis_choke_widths and bot.board_analysis.intergeneral_analysis:
            for tile in bot._map.get_all_tiles():
                w = ''
                if tile in bot.board_analysis.intergeneral_analysis.chokeWidths:
                    w = str(bot.board_analysis.intergeneral_analysis.chokeWidths[tile])
                bot.viewInfo.topRightGridText[tile] = f'cw{w}'

        for p in bot.armyTracker.unconnectable_tiles:
            for t in p:
                bot.viewInfo.add_targeted_tile(t, targetStyle=TargetStyle.RED, radiusReduction=-5)
        for p, matrix in enumerate(bot.armyTracker.player_connected_tiles):
            if not bot._map.is_player_on_team_with(bot.player.index, p) and not bot._map.players[p].dead:
                scaledColor = Utils.rescale_color(0.55, 0, 1.0, Colors.PLAYER_COLORS[p], Colors.GRAY_DARK)
                bot.viewInfo.add_map_division(matrix, scaledColor, alpha=150)
                bot.viewInfo.add_map_zone(matrix, scaledColor, alpha=65)

        if move is not None:
            bot.viewInfo.color_path(PathColorer(
                movePath,
                254, 254, 254,
                alpha=135,
                alphaDecreaseRate=0
            ))

        if bot.info_render_defense_spanning_tree and bot.defensive_spanning_tree:
            bot.viewInfo.add_map_zone(bot.defensive_spanning_tree, Colors.WHITE_PURPLE, alpha=90)

        if bot.info_render_friendly_city_spanning_tree and bot.friendly_city_spanning_tree:
            bot.viewInfo.add_map_zone(bot.friendly_city_spanning_tree, Colors.GOLD, alpha=50)

        if bot.info_render_tile_islands:
            for island in sorted(bot.tileIslandBuilder.all_tile_islands, key=lambda i: (i.team, str(i.name))):
                if island.name:
                    for tile in island.tile_set:
                        if bot.viewInfo.topRightGridText[tile]:
                            bot.viewInfo.midRightGridText[tile] = island.name
                        else:
                            bot.viewInfo.topRightGridText[tile] = island.name

        if bot.info_render_flow_expand and bot.last_flow_expander is not None and bot.last_flow_opt_collection is not None:
            BotRendering.render_flow_expand_in_view_info(bot)

    @staticmethod
    def render_flow_expand_in_view_info(bot):
        expander = bot.last_flow_expander
        optCollection = bot.last_flow_opt_collection
        vi: ViewInfo = bot.viewInfo
        general = expander.friendlyGeneral
        enemyGeneral = expander.enemyGeneral
        opts = optCollection.flow_plans

        optsSorted = sorted(opts, key=lambda opt: (opt.length, opt.econValue), reverse=True)

        first = set()
        dupes = set()

        for opt in optsSorted:
            for tile in opt.tileSet:
                if tile in first:
                    dupes.add(tile)
                else:
                    first.add(tile)

        for tile in dupes:
            vi.add_targeted_tile(tile, TargetStyle.GRAY, radiusReduction=-1)
        if dupes:
            vi.add_info_line('GRAY = DUPLICATE FLOW OPTION TILES:')
            vi.add_info_line(f'|'.join(f'{t.x},{t.y}' for t in dupes))

        if optsSorted:
            try:
                bestOpt = next(filter(lambda opt: opt.length > 3, optsSorted))
            except StopIteration:
                bestOpt = optsSorted[0]

            vi.add_info_line_no_log(str(bestOpt) + '   ' + '|'.join(f'{t.x},{t.y}' for t in bestOpt.tileList))
            if enemyGeneral is not None:
                ArmyFlowExpander.add_flow_expansion_option_to_view_info(bot._map, bestOpt, general.player, enemyGeneral.player, vi)

        vi.add_info_line('-------- v all options --------')
        for opt in opts:
            vi.add_info_line_no_log(str(opt) + '   ' + '|'.join(f'{t.x},{t.y}' for t in opt.tileList))
            if enemyGeneral is not None:
                ArmyFlowExpander.add_flow_expansion_option_to_view_info(bot._map, opt, general.player, enemyGeneral.player, vi)

        flowGraph = expander.flow_graph
        if flowGraph is not None:
            ArmyFlowExpander.add_flow_graph_to_view_info(flowGraph, vi, lastRun=expander.last_run, noLog=True)

        expander.island_builder.add_tile_islands_to_view_info(vi, printIslandInfoLines=False, renderIslandNames=True)

    @staticmethod
    def mark_tile(bot, tile, alpha=100):
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
    def render_intercept_plan(bot, plan, colorIndex: int = 0):
        targetStyle = TargetStyle(((colorIndex + 1) % 9) + 1)
        for tile, interceptInfo in plan.common_intercept_chokes.items():
            bot.viewInfo.add_targeted_tile(tile, targetStyle, radiusReduction=11 - colorIndex)

            bot.viewInfo.bottomMidRightGridText[tile] = f'cw{interceptInfo.max_choke_width}'

            bot.viewInfo.bottomMidLeftGridText[tile] = f'ic{interceptInfo.max_intercept_turn_offset}'

            bot.viewInfo.bottomLeftGridText[tile] = f'it{interceptInfo.max_delay_turns}'

            bot.viewInfo.midRightGridText[tile] = f'im{interceptInfo.max_extra_moves_to_capture}'

        bot.viewInfo.add_info_line(f'  intChokes @{plan.target_tile} = {targetStyle}')

        for dist, opt in plan.intercept_options.items():
            logbook.info(f'intercept plan opt {plan.target_tile} dist {dist}: {str(opt)}')

    @staticmethod
    def dump_turn_data_to_string(bot):
        charMap = PLAYER_CHAR_BY_INDEX

        data = []

        data.append(f'bot_target_player={bot.targetPlayer}')
        if bot.targetPlayerExpectedGeneralLocation and bot.targetPlayer != -1:
            data.append(f'targetPlayerExpectedGeneralLocation={bot.targetPlayerExpectedGeneralLocation.x},{bot.targetPlayerExpectedGeneralLocation.y}')
        data.append(f'bot_is_all_in_losing={bot.is_all_in_losing}')
        data.append(f'bot_all_in_losing_counter={bot.all_in_losing_counter}')

        data.append(f'bot_is_winning_gather_cyclic={bot.is_winning_gather_cyclic}')
        data.append(f'bot_is_all_in_army_advantage={bot.is_all_in_army_advantage}')
        data.append(f'bot_all_in_army_advantage_counter={bot.all_in_army_advantage_counter}')
        data.append(f'bot_all_in_army_advantage_cycle={bot.all_in_army_advantage_cycle}')
        data.append(f'bot_defend_economy={bot.defend_economy}')
        if bot.timings is not None:
            data.append(f'bot_timings_launch_timing={bot.timings.launchTiming}')
            data.append(f'bot_timings_split_turns={bot.timings.splitTurns}')
            data.append(f'bot_timings_quick_expand_turns={bot.timings.quickExpandTurns}')
            data.append(f'bot_timings_cycle_turns={bot.timings.cycleTurns}')

        data.append(f'bot_is_rapid_capturing_neut_cities={bot.is_rapid_capturing_neut_cities}')
        data.append(f'bot_is_blocking_neutral_city_captures={bot.is_blocking_neutral_city_captures}')
        data.append(f'bot_finishing_exploration={bot.finishing_exploration}')
        if bot.targetingArmy:
            data.append(f'bot_targeting_army={bot.targetingArmy.tile.x},{bot.targetingArmy.tile.y}')
        data.append(f'bot_cur_path={str(bot.curPath)}')

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
        for tile in bot._map.get_all_tiles():
            if tile.isTempFogPrediction:
                tempSet.add(tile)
            if tile.discoveredAsNeutral:
                neutDiscSet.add(tile)
        data.append(f'TempFogTiles={BotSerialization.convert_tile_set_to_string(bot, tempSet)}')
        data.append(f'DiscoveredNeutral={BotSerialization.convert_tile_set_to_string(bot, neutDiscSet)}')

        data.append(f'Armies={TextMapLoader.dump_armies(bot._map, bot.armyTracker.armies)}')

        data.append(bot.opponent_tracker.dump_to_string_data())

        return '\n'.join(data)
