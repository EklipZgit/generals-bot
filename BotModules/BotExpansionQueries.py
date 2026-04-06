import SearchUtils
import logbook
from BotModules.BotStateQueries import BotStateQueries
from MapMatrix import MapMatrix, MapMatrixInterface
from ViewInfo import TargetStyle


class BotExpansionQueries:
    @staticmethod
    def get_expansion_weight_matrix(bot, copy: bool = False, mult: int = 1) -> MapMatrixInterface[float]:
        if bot._expansion_value_matrix is None:
            logbook.info(f'rebuilding expansion weight matrix for turn {bot._map.turn}')
            if BotStateQueries.is_still_ffa_and_non_dominant(bot):
                bot._expansion_value_matrix = BotExpansionQueries._get_avoid_other_players_expansion_matrix(bot)
            else:
                bot._expansion_value_matrix = BotExpansionQueries._get_standard_expansion_capture_weight_matrix(bot)

        if mult != 1:
            copyMat = bot._expansion_value_matrix.copy()
            for t in bot._map.get_all_tiles():
                copyMat.raw[t.tile_index] *= mult
            return copyMat

        if copy:
            return bot._expansion_value_matrix.copy()

        return bot._expansion_value_matrix

    @staticmethod
    def _get_avoid_other_players_expansion_matrix(bot) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, 0.0)
        for tile in bot._map.get_all_tiles():
            if bot.targetPlayer != -1 and (tile.player == bot.targetPlayer or bot.territories.territoryMap[tile] == bot.targetPlayer):
                if tile in bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles:
                    continue

            if tile.player != -1:
                matrix[tile] -= 0.6

            for adj in tile.adjacents:
                if not adj.discovered and not adj.isObstacle:
                    matrix[tile] -= 0.1
                if bot.targetPlayer != -1 and (adj.player == bot.targetPlayer or bot.territories.territoryMap[adj] == bot.targetPlayer):
                    matrix[tile] = 0.0
                    break
            if bot.info_render_expansion_matrix_values:
                val = matrix[tile]
                if val:
                    bot.viewInfo.bottomLeftGridText[tile] = f'hx{val:0.3f}'

        return matrix

    @staticmethod
    def _get_standard_expansion_capture_weight_matrix(bot) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, 0.0)

        innerChokes = bot.board_analysis.innerChokes

        dontRevealCities = bot.targetPlayer != -1 and bot.opponent_tracker.winning_on_economy(byRatio=1.05) and not bot.opponent_tracker.winning_on_army(byRatio=1.10)

        numEnGenPos = len(bot.alt_en_gen_positions[bot.targetPlayer])
        enPotentialGenDistances = bot._alt_en_gen_position_distances[bot.targetPlayer]
        genPosesToConsider = bot.alt_en_gen_positions[bot.targetPlayer]

        searchingForFirstContact = False
        if bot.targetPlayer != -1 and not bot.armyTracker.seen_player_lookup[bot.targetPlayer]:
            searchingForFirstContact = True

        if numEnGenPos > 6:
            bot.info(f'filtering down valid general set')
            avgDist = sum(bot.board_analysis.intergeneral_analysis.aMap.raw[t.tile_index] for t in genPosesToConsider) / len(genPosesToConsider)
            genPosesToConsider = [t for t in genPosesToConsider if bot.board_analysis.intergeneral_analysis.aMap.raw[t.tile_index] >= avgDist]
            for pos in genPosesToConsider:
                bot.viewInfo.add_targeted_tile(pos, targetStyle=TargetStyle.GREEN, radiusReduction=8)
            numEnGenPos = len(genPosesToConsider)
            enPotentialGenDistances = None

        if enPotentialGenDistances is None:
            enPotentialGenDistances = SearchUtils.build_distance_map_matrix(bot._map, genPosesToConsider)
            bot._alt_en_gen_position_distances[bot.targetPlayer] = enPotentialGenDistances
        tgPlayerTerritoryDists = bot.territories.territoryDistances[bot.targetPlayer]

        if dontRevealCities:
            bot.viewInfo.add_info_line(f'!@! expansion avoiding revealing cities')
            for city in bot.win_condition_analyzer.defend_cities:
                cityDist = bot.territories.territoryDistances[bot.targetPlayer][city]
                for tile in city.movable:
                    if tile.isNeutral and tgPlayerTerritoryDists.raw[tile.tile_index] < cityDist:
                        bot.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.PURPLE, radiusReduction=12)
                        matrix.raw[tile.tile_index] -= 100

        if bot.enemy_attack_path is not None:
            for tile in bot.enemy_attack_path.tileList:
                if not tile.visible and tile not in bot.target_player_gather_path.tileSet:
                    matrix.raw[tile.tile_index] += 0.2

        if bot.sketchiest_potential_inbound_flank_path is not None and bot.targetPlayerObj and len(bot.targetPlayerObj.tiles) > 0:
            cutoff = 2 * bot.board_analysis.inter_general_distance // 5

            for tile in bot.sketchiest_potential_inbound_flank_path.adjacentSet:
                if bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, tile) < cutoff:
                    continue

                if not tile.visible:
                    matrix.raw[tile.tile_index] += 0.1
                else:
                    matrix.raw[tile.tile_index] += 0.03

            for tile in bot.sketchiest_potential_inbound_flank_path.tileSet:
                if bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, tile) < cutoff:
                    continue
                if not tile.visible:
                    matrix.raw[tile.tile_index] += 0.15
                else:
                    matrix.raw[tile.tile_index] += 0.03

        endOfCyclePenaltyRatio = 35 / (bot._map.cycleTurn + 5)
        if searchingForFirstContact:
            endOfCyclePenaltyRatio = 0
        bot.info(f'enemy expansion endOfCyclePenaltyRatio {endOfCyclePenaltyRatio:.3f}')

        for tile, scoreData in bot.cityAnalyzer.get_sorted_neutral_scores()[0:2]:
            if scoreData.general_distances_ratio < 1.1:
                for adj in tile.adjacents:
                    if bot._map.is_tile_enemy(adj):
                        matrix.raw[adj.tile_index] += 0.5

                    if adj.isNeutral and not adj.isUndiscoveredObstacle and scoreData.general_distances_ratio > 0.6:
                        matrix.raw[adj.tile_index] += max(0.0, 0.05 * (scoreData.general_distances_ratio - 0.1))
                        if not adj.discovered:
                            matrix.raw[adj.tile_index] += max(0.0, 0.05 * (scoreData.general_distances_ratio - 0.1))

        if bot.enemy_expansion_plan is not None:
            for enPath in bot.enemy_expansion_plan.all_paths:
                for tile in enPath.tileList[1:]:
                    if bot._map.is_tile_friendly(tile):
                        matrix.raw[tile.tile_index] -= bot.expansion_enemy_expansion_plan_inbound_penalty * endOfCyclePenaltyRatio

        for lookout in bot._map.lookouts:
            for tile in lookout.movableNoObstacles:
                if (bot.targetPlayer == -1 and not bot._map.is_tile_friendly(tile)) or (bot.targetPlayer >= 0 and bot._map.is_tile_on_team_with(tile, bot.targetPlayer)):
                    matrix.raw[tile.tile_index] += 0.5
                elif tile.player == -1:
                    matrix.raw[tile.tile_index] += 0.25

        for observatory in bot._map.observatories:
            for tile in observatory.movableNoObstacles:
                if (bot.targetPlayer == -1 and not bot._map.is_tile_friendly(tile)) or (bot.targetPlayer >= 0 and bot._map.is_tile_on_team_with(tile, bot.targetPlayer)):
                    matrix.raw[tile.tile_index] += 0.5
                elif tile.player == -1:
                    matrix.raw[tile.tile_index] += 0.25

        for tile in bot._map.get_all_tiles():
            bonus = 0.0
            if innerChokes.raw[tile.tile_index]:
                bonus += 0.002

            enDist = enPotentialGenDistances.raw[tile.tile_index]
            genDist = bot._map.get_distance_between(bot.general, tile)

            isCloserToEn = enDist < genDist * 0.9
            enDistRatio = (genDist + 3) / max(1, (enDist + numEnGenPos // 3))

            enExpVal = bot.enemy_expansion_plan_tile_path_cap_values.get(tile, None)
            if enExpVal is not None:
                bonus += enExpVal / 2

            if bot.board_analysis.intergeneral_analysis.is_choke(tile):
                bonus += 0.01

            isNeutral = tile.isNeutral
            isFriendly = not isNeutral and bot._map.is_tile_friendly(tile)
            isTarget = not isNeutral and bot._map.is_player_on_team_with(tile.player, bot.targetPlayer)

            if isFriendly and tile.army < 2:
                bonus -= 0.2

            if tile.isSwamp:
                if isTarget:
                    bonus -= 4.0
                elif isNeutral:
                    bonus -= 2.0

            if tile.isDesert:
                if isTarget:
                    bonus -= 2.0
                elif isNeutral:
                    bonus -= 1.0

            anyFlankVis = False
            for vis in tile.adjacents:
                if vis in bot.board_analysis.flankable_fog_area_matrix:
                    anyFlankVis = True
                    break

            if anyFlankVis:
                bonus += 0.05

            if tile.player == -1 and tgPlayerTerritoryDists.raw[tile.tile_index] < 3:
                bonus += 0.03

            if tile.isCity:
                cityScore = bot.cityAnalyzer.city_scores.get(tile, None)
                isCityGapping = (cityScore is None or cityScore.intergeneral_distance_differential > 0) and not bot._map.is_tile_friendly(tile)
                for vis in tile.adjacents:
                    if vis.isNotPathable or bot._map.is_tile_friendly(vis):
                        continue
                    if isCloserToEn or not isCityGapping or enPotentialGenDistances.raw[tile.tile_index] <= enPotentialGenDistances.raw[vis.tile_index]:
                        matrix.raw[vis.tile_index] += 0.05

            if isTarget:
                if tile.army > 1:
                    bonus += 0.02 + min(50, tile.army) * 0.02

            if not tile.discovered and bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer].raw[tile.tile_index] and numEnGenPos < 10:
                bonus -= 0.01

            if bot._map.is_tile_on_team_with(tile, bot.targetPlayer) and bot.territories.is_tile_in_friendly_territory(tile):
                bonus += 0.05

            libertyCount = 0
            for mv in tile.movable:
                if not mv.isObstacle and not (mv.isNeutral and mv.army > 1):
                    libertyCount += 1
            if libertyCount == 1:
                bonus += 0.1
                if isTarget:
                    bonus += 0.3

            pathway = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix.raw[tile.tile_index]
            if pathway is not None:
                extendedDist = pathway.distance - bot.board_analysis.within_extended_play_area_threshold
                outsideExtendedPlay = extendedDist > 0
                if outsideExtendedPlay and not (tile in bot.board_analysis.flank_danger_play_area_matrix and SearchUtils.any_where(pathway.tiles, lambda t: not t.visible and t in bot.board_analysis.flankable_fog_area_matrix)):
                    isEnTile = bot._map.is_player_on_team_with(bot.targetPlayer, tile.player)
                    if isEnTile:
                        factor = 0.5
                        if not tile.discovered:
                            factor = 0.2
                        bonus -= factor / max(4, 15 - extendedDist)
                    else:
                        bonus -= 1.0 / max(4, 15 - extendedDist)
            else:
                bonus -= 10

            if bot._map.remainingCycleTurns > 8 and not searchingForFirstContact:
                cappedRat = max(1.1, enDistRatio)
                if tile.player == -1:
                    bonus += 0.1 - 0.05 * cappedRat
                else:
                    bonus += 0.06 - 0.03 * cappedRat

            excessDist = enPotentialGenDistances.raw[tile.tile_index] - bot.board_analysis.inter_general_distance - numEnGenPos
            if excessDist > 0:
                bonus -= 0.10 * excessDist / max(2, len(genPosesToConsider))

            if bot._map.is_tile_friendly(tile):
                if tile.army < 2:
                    bonus -= -0.05
                matrix.raw[tile.tile_index] = min(bonus, 0.0)
            else:
                matrix.raw[tile.tile_index] += bonus

            if bot.info_render_expansion_matrix_values:
                bot.viewInfo.bottomLeftGridText[tile] = f'x{matrix.raw[tile.tile_index]:0.3f}'

        return matrix
