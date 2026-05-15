import typing

import logbook

import SearchUtils
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix
from ViewInfo import TargetStyle
from base.client.map import Tile

if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot


class BotCentralDefense:
    @staticmethod
    def rebuild_intergeneral_analysis_for_central_defense(bot: EklipZBot):
        citiesInPlay = BotCentralDefense._get_central_defense_cities_in_play(bot)
        bot.board_analysis.rebuild_intergeneral_analysis(
            bot.targetPlayerExpectedGeneralLocation,
            bot.armyTracker.valid_general_positions_by_player,
            citiesInPlay)

    @staticmethod
    def calculate_central_defense_point_if_needed(bot: EklipZBot, force: bool = False):
        if bot.cityAnalyzer.last_scan_turn != bot._map.turn:
            # logbook.info(
            #     f'CENTRAL_DEFENSE_POINT skipped calculation because cityAnalyzer turn {bot.cityAnalyzer.last_scan_turn} != map turn {bot._map.turn}')
            return

        citiesInPlay = BotCentralDefense._get_central_defense_cities_in_play(bot)
        signature = BotCentralDefense._get_central_defense_signature(bot, citiesInPlay)
        if not force and bot.last_central_defense_signature == signature and bot.board_analysis.central_defense_point is not None:
            # logbook.info(f'CENTRAL_DEFENSE_POINT skipped calculation current={bot.board_analysis.central_defense_point} because signature unchanged {signature}')
            return

        bot.last_central_defense_signature = signature
        # logbook.info(f'CENTRAL_DEFENSE_POINT calculating because signature changed to {signature}')
        BotCentralDefense.rebuild_defensive_chokes(bot)
        BotCentralDefense.calculate_central_defense_point(bot)

    @staticmethod
    def rebuild_defensive_chokes(bot: EklipZBot):
        bot.board_analysis.defensive_chokes_by_tile = {}
        bot.board_analysis.defensive_furthest_choke_tiles_by_defensive_tile = {}
        chokeTiles: typing.Set[Tile] = set()

        defensiveChokePoint = bot.board_analysis._get_defensive_choke_point(bot.general)
        chokeTiles.update(defensiveChokePoint.choke_tiles)
        # logbook.info(
        #     f'CENTRAL_DEFENSE_POINT defended general {str(bot.general)} uses point {bot.board_analysis._defensive_choke_point_to_string(defensiveChokePoint)}')
        for city in bot.board_analysis.friendly_city_distances.keys():
            defensiveChokePoint = bot.board_analysis._get_defensive_choke_point(city)
            chokeTiles.update(defensiveChokePoint.choke_tiles)
            # logbook.info(
            #     f'CENTRAL_DEFENSE_POINT defended city {str(city)} uses point {bot.board_analysis._defensive_choke_point_to_string(defensiveChokePoint)}')
        bot.viewInfo.add_targeted_tiles_with_legend(chokeTiles, 'Defensive choke tiles', TargetStyle.ORANGE, radiusReduction=12)

    @staticmethod
    def calculate_central_defense_point(bot: EklipZBot):
        defensePoints = list(bot.board_analysis.defensive_chokes_by_tile.values())
        if len(defensePoints) == 0:
            bot.board_analysis.central_defense_point = bot.general
            return

        bot.board_analysis.defense_centrality_sums = MapMatrix(bot._map, 1000000)
        averagePointCount = len(defensePoints) + 1
        averageX = (bot.general.x + sum(defensePoint.x for defensePoint in defensePoints)) / averagePointCount
        averageY = (bot.general.y + sum(defensePoint.y for defensePoint in defensePoints)) / averagePointCount
        attackPathFogExitTile = BotCentralDefense._get_enemy_attack_path_fog_exit_tile(bot)
        distanceToFogExit = bot._map.distance_mapper.get_tile_dist_matrix(attackPathFogExitTile) if attackPathFogExitTile is not None else None
        lowestScore: tuple[float, int, int] | None = None
        lowestAvgTile: Tile = bot.general
        topCentralityTiles: typing.List[typing.Tuple[tuple[float, int, int], Tile]] = []

        for tile in bot.defensive_spanning_tree:
            # if not bot._map.is_tile_on_team_with(tile, bot.general.player):
            #     continue

            distSum = abs(tile.x - averageX) + abs(tile.y - averageY)
            interceptDist = 0
            if distanceToFogExit is not None:
                rawInterceptDist = distanceToFogExit.raw[tile.tile_index]
                if rawInterceptDist is None:
                    continue
                interceptDist = rawInterceptDist

            tileEnemyDist = bot.board_analysis.intergeneral_analysis.bMap.raw[tile.tile_index] if bot.board_analysis.intergeneral_analysis is not None else 0
            score = (distSum + interceptDist * 0.5, interceptDist, tileEnemyDist)

            if lowestScore is None or score < lowestScore:
                lowestAvgTile = tile
                lowestScore = score

            bot.board_analysis.defense_centrality_sums.raw[tile.tile_index] = score[0]
            topCentralityTiles.append((score, tile))
            topCentralityTiles.sort(key=lambda item: item[0])
            if len(topCentralityTiles) > 10:
                topCentralityTiles.pop()

        # logbook.info(
        #     'CENTRAL_DEFENSE_POINT top candidates: '
        #     + ' | '.join(
        #         [
        #             f'{str(tile)} score={score} enemyDist={bot.board_analysis.intergeneral_analysis.bMap.raw[tile.tile_index] if bot.board_analysis.intergeneral_analysis is not None else None}'
        #             for score, tile in topCentralityTiles
        #         ]))
        # logbook.info(
        #     f'calculated central defense point to be {str(lowestAvgTile)} due to chokeAverage {averageX:.2f},{averageY:.2f} score {lowestScore} attackPathFogExit={attackPathFogExitTile}')
        bot.board_analysis.central_defense_point = lowestAvgTile

    @staticmethod
    def _get_central_defense_cities_in_play(bot: EklipZBot) -> typing.Set[Tile] | None:
        if bot.cityAnalyzer is None:
            return None

        citiesInPlay = bot.cityAnalyzer.cities_in_play
        if not citiesInPlay:
            return citiesInPlay

        enemyLandDistanceMap = BotCentralDefense._get_enemy_land_distance_map(bot)
        filteredCities: typing.Set[Tile] = set()
        for city in citiesInPlay:
            if not bot._map.is_tile_on_team_with(city, bot.general.player):
                continue

            enemyHasSeen = SearchUtils.any_where(city.visibleTo, lambda t: t in bot.armyTracker.tiles_ever_owned_by_player[bot.targetPlayer])
            nearestEnemyLandDist = enemyLandDistanceMap.raw[city.tile_index] if enemyLandDistanceMap is not None else None
            shouldExclude = (
                    not enemyHasSeen
                    and nearestEnemyLandDist is not None
                    and nearestEnemyLandDist >= 3)
            # logbook.info(
            #     f'CENTRAL_DEFENSE_POINT city filter city={str(city)} enemyHasSeen={enemyHasSeen} nearestEnemyLandDist={nearestEnemyLandDist} exclude={shouldExclude}')
            if not shouldExclude:
                filteredCities.add(city)

        return filteredCities

    @staticmethod
    def _get_central_defense_signature(bot: EklipZBot, citiesInPlay: typing.Set[Tile] | None) -> tuple[int | None, tuple[tuple[int, int], ...]]:
        expectedGeneralIndex = bot.targetPlayerExpectedGeneralLocation.tile_index if bot.targetPlayerExpectedGeneralLocation is not None else None
        citySignature = tuple(
            sorted(
                [
                    (city.tile_index, city.player)
                    for city in citiesInPlay
                ])) if citiesInPlay is not None else tuple()
        return expectedGeneralIndex, citySignature

    @staticmethod
    def _get_enemy_land_distance_map(bot: EklipZBot) -> MapMatrixInterface[int] | None:
        enemyLandTiles = [
            tile
            for player in bot._map.players
            if player.index != bot.general.player and bot._map.is_player_on_team_with(player.index, bot.targetPlayer)
            for tile in player.tiles
        ]
        if len(enemyLandTiles) == 0:
            return None

        return SearchUtils.build_distance_map_matrix(bot._map, enemyLandTiles)

    @staticmethod
    def _can_enemy_see_tile(bot: EklipZBot, tile: Tile) -> bool:
        for visibleSource in tile.visibleTo:
            if visibleSource.player >= 0 and bot._map.is_player_on_team_with(visibleSource.player, bot.targetPlayer):
                return True

        return False

    @staticmethod
    def _get_enemy_attack_path_fog_exit_tile(bot: EklipZBot) -> Tile | None:
        if bot.enemy_attack_path is None or bot.enemy_attack_path.length <= 1:
            return None

        sawFog = False
        for tile in bot.enemy_attack_path.tileList:
            if not tile.visible:
                sawFog = True
                continue
            if sawFog:
                return tile

        return None
