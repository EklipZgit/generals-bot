import logbook
import typing

import DebugHelper
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix
from SearchUtils import Counter
from Utils import ScaleUtils
from base.client.map import MapBase, Tile, Player


class CityScoreData(object):
    def __init__(self, tile: Tile):
        self.tile: Tile = tile
        self.city_expandability_score: float = 0.0
        """How much the city opens up our generals expansion"""
        self.city_defensability_score: float = 0.0
        """How defendable the city appears to be"""
        self.city_general_defense_score: float = 0.0
        """How much the city helps us defend our general"""
        self.city_relevance_score: float = 0.0
        """How relevant the cities position is to the game"""

        # other data, everything below is intermediate data used to calculate the scores above
        self.intergeneral_distance_differential: int = 0
        """The difference between the path through the city between gens, and the current map shortest path. 
        If this value is positive, it decreased the shortest path by that much.
        If the difference is negative, the amount negative indicates how 'out of the way' of the main path the city is. 
        Measured in moves from both generals so 1 off the main path with be -2, then -4. Odd numbers cant exist.
        """

        self.general_distances_ratio: float = 1.0
        """1.0 means equadistant from enemy and player. 3.0 means 3x closer to enemy than player. 0.3333 = 3x closer to player than enemy."""

        self.general_distances_ratio_squared_capped: float = 1.0
        """Squared and 0.1 capped general_distances_ratio, to make it much more extreme weighting without over-prioritizing cities behind us"""

        self.friendly_city_nearby_score: int = 0
        """how many friendly cities are nearby scored by distance to friendly cities(gen) in tiles weighted by intergen distance. 
        A single friendly city directly next to the city will score as 1/3 the distance between generals."""
        self.enemy_city_nearby_score: int = 0
        """how many enemy cities are nearby scored by distance to friendly cities(gen) in tiles weighted by intergen distance. 
        A single enemy city directly next to the city will score as 1/3 the distance between generals."""
        self.neutral_city_nearby_score: int = 0
        """how many enemy cities are nearby scored by distance to friendly cities(gen) in tiles weighted by intergen distance. 
        A single neutral city directly next to the city will score as 1/3 the distance between generals."""

        self.neighboring_city_relevance: float = 0
        """Cumulative score of nearby friendly cities vs nearby enemy cities
        """

        self.distance_from_player_general: int = 1000
        self.distance_from_enemy_general: int = 1000
        self.intergeneral_distance_through_city: int = 1000

    def get_weighted_neutral_value(self, log: bool = True) -> float:
        totalScore = self.city_defensability_score * self.city_relevance_score * self.city_expandability_score * self.city_general_defense_score
        totalScore = totalScore
        if log:
            logbook.info(f"cityScore neut {self.tile.x},{self.tile.y}: re{self.city_relevance_score:.4f}, ex{self.city_expandability_score:.4f}, def{self.city_defensability_score:.4f}, gdef{self.city_general_defense_score:.4f}, tot{totalScore:.3f}")
        return totalScore

    def get_weighted_enemy_capture_value(self, log: bool = True) -> float:
        totalScore = self.city_defensability_score * self.city_relevance_score
        if not self.tile.discovered:
            totalScore = totalScore / 2
        if log:
            logbook.info(f"cityScore enemy {self.tile.x},{self.tile.y}: re{self.city_relevance_score:.4f}, def{self.city_defensability_score:.4f}, tot{totalScore:.3f}")
        return totalScore


class CityAnalyzer(object):
    def __init__(self, map: MapBase, playerGeneral: Tile):
        self.map: MapBase = map
        self.general: Tile = playerGeneral
        self.city_scores: typing.Dict[Tile, CityScoreData] = {}
        self.player_city_scores: typing.Dict[Tile, CityScoreData] = {}
        self.enemy_city_scores: typing.Dict[Tile, CityScoreData] = {}
        self.undiscovered_mountain_scores: typing.Dict[Tile, CityScoreData] = {}
        self.owned_contested_cities: typing.Set[Tile] = set()
        """Contains all player owned cities that have been recently contested."""

        self.enemy_contested_cities: typing.Set[Tile] = set()
        """Contains all player owned cities that have been recently contested."""

        self.reachability_costs_matrix: MapMatrixInterface[int] = None
        self.reachable_from_matrix: MapMatrixInterface[Tile | None] = None

        self.ensure_reachability_matrix_built()

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def re_scan(self, board_analysis: BoardAnalyzer):
        self.city_scores: typing.Dict[Tile, CityScoreData] = {}
        self.player_city_scores: typing.Dict[Tile, CityScoreData] = {}
        self.enemy_city_scores: typing.Dict[Tile, CityScoreData] = {}
        self.undiscovered_mountain_scores: typing.Dict[Tile, CityScoreData] = {}
        self.owned_contested_cities: typing.Set[Tile] = set()
        self.enemy_contested_cities: typing.Set[Tile] = set()

        if self.reachability_costs_matrix is None:
            self.ensure_reachability_matrix_built(force=True)

        allyDistMap = None
        teammate = None

        if self.map.is_2v2:
            teammate = self.map.players[[t for t in self.map.teammates][0]]
            if not teammate.dead:
                allyDistMap = self.map.distance_mapper.get_tile_dist_matrix(teammate.general)

        expensiveCities = []
        numCities = [0]

        def foreachFunc(tile: Tile, dist: int):
            # TODO calculate predicted enemy city locations in fog and explore mountains more in places we would WANT cities to be
            # tileMightBeUndiscCity = not tile.discovered and tile.isObstacle and tile in self.map.reachable_tiles
            # if not (tile.isCity or tileMightBeUndiscCity):
            if tile.isMountain:
                return True

            if not tile.isCity:
                return False

            numCities[0] += 1

            score = CityScoreData(tile)
            isCostlyCity = tile.army > 5 or self.map.is_tile_enemy(tile)
            isNegCity = tile.army <= 0
            isFriendly = self.map.is_player_on_team_with(tile.player, board_analysis.general.player)

            if isCostlyCity and len(expensiveCities) < 30:
                expensiveCities.append(tile)
                self._calculate_nearby_city_scores(tile, board_analysis, score)
            else:
                if isNegCity:
                    score.neutral_city_nearby_score = 100 - tile.army
                    score.friendly_city_nearby_score = 50 - tile.army
                else:
                    score.neutral_city_nearby_score = 50000 / (1 + tile.army)
                    score.friendly_city_nearby_score = 20000 / (1 + tile.army)

            self._calculate_distance_scores(tile, board_analysis, score)
            self._calculate_relevance_score(tile, board_analysis, score)

            if isCostlyCity and len(expensiveCities) < 30:
                self._calculate_danger_score(tile, board_analysis, score)
                self._calculate_expandability_score(tile, board_analysis, score)
            else:
                score.city_defensability_score = 20000.0 / numCities[0]
                score.city_expandability_score = 2000.0 / numCities[0]
                if isCostlyCity:
                    score.city_general_defense_score = 10.0 / numCities[0]
                else:
                    score.city_general_defense_score = 20.0 / numCities[0]

            if allyDistMap is not None:
                self._calculate_2v2_score(tile, board_analysis, allyDistMap, teammate, score)

            # if tile.isCity:
            if tile.isNeutral:
                self.city_scores[tile] = score
            elif isFriendly:
                self.player_city_scores[tile] = score
                if self.is_contested(tile):
                    self.owned_contested_cities.add(tile)
            else:
                self.enemy_city_scores[tile] = score
                if self.is_contested(tile):
                    self.enemy_contested_cities.add(tile)
            #
            # else:
            #     self.undiscovered_mountain_scores[tile] = score

        SearchUtils.breadth_first_foreach_dist(
            self.map,
            self.map.players[self.general.player].tiles,
            maxDepth=30,
            foreachFunc=foreachFunc,
            bypassDefaultSkip=True
        )

    def reset_reachability(self):
        self.reachability_costs_matrix = None
        self.reachable_from_matrix = None

    def ensure_reachability_matrix_built(self, force: bool = False):
        if self.reachability_costs_matrix is not None and not force:
            return
        if len(self.map.swamps) > 0 or self.map.is_walled_city_game:
            self.reachable_from_matrix, self.reachability_costs_matrix = SearchUtils.build_reachability_cost_map_matrix(self.map, [self.general])
        else:
            self.reachability_costs_matrix = MapMatrix(self.map, 0)
            self.reachable_from_matrix = MapMatrix(self.map, None)

    def _calculate_distance_scores(self, city: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        """
        O(1)

        if the sum of the cities distance from both generals is equal to or greater than the shortest path
        between generals currently, then it does not decrease the path at all. If the sum is less than the shortest
        path lengh, then it decreases the path by that much.

        If the difference is negative, the amount negative indicates how 'out of the way' of the main path the city is.

        The score is then the amount it shortens the path multiplied by how much closer it is to us than the enemy.

        @param city:
        @param board_analysis:
        @return:
        """

        for adj in city.movable:
            if adj.isObstacle:
                continue
            score.distance_from_player_general = min(score.distance_from_player_general, board_analysis.intergeneral_analysis.aMap[adj] + 1)
            score.distance_from_enemy_general = min(score.distance_from_enemy_general, board_analysis.intergeneral_analysis.bMap[adj] + 1)

        currentShortest = board_analysis.intergeneral_analysis.shortestPathWay.distance

        score.intergeneral_distance_through_city = score.distance_from_enemy_general + score.distance_from_player_general

        score.intergeneral_distance_differential = currentShortest - score.intergeneral_distance_through_city

        score.general_distances_ratio = score.distance_from_player_general / max(1, score.distance_from_enemy_general)

        # make this MUCH more impactful to the score, but cap it so we don't massively prioritize cities behind us
        distanceRatioSquared = score.general_distances_ratio * score.general_distances_ratio
        distanceRatioSquared = max(distanceRatioSquared, 0.1)

        score.general_distances_ratio_squared_capped = distanceRatioSquared

    def _calculate_danger_score(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        """
        O(N) worst case

        @param tile:
        @param board_analysis:
        @param score:
        @return:
        """
        # used to prevent tiles right next to general from being weighted WAY better than tiles 2 tiles away etc
        if self.map.turn > 200 or not tile.isNeutral:
            scaleOffset = 10
        else:
            scaleOffset = max(0, tile.army - 34)

        score.city_general_defense_score = 0.2 + 1.0 / max(1, score.distance_from_player_general + scaleOffset) / max(0.2, score.general_distances_ratio)

        tilesNearbyFriendlyCounter = Counter(3)
        tilesNearbyEnemyCounter = Counter(3)
        def scoreNearbyTerritoryFunc(curTile: Tile, distance: int):
            if curTile.isNeutral or curTile.isObstacle:
                return

            if self.map.is_player_on_team_with(curTile.player, board_analysis.general.player):
                tilesNearbyFriendlyCounter.add(1)
            else:
                tilesNearbyEnemyCounter.add(1)

        maxDist = min(15, board_analysis.intergeneral_analysis.shortestPathWay.distance // 4)
        self.foreach_around_city(tile, board_analysis, maxDist, scoreNearbyTerritoryFunc)

        score.city_defensability_score = (score.friendly_city_nearby_score + tilesNearbyFriendlyCounter.value // 2) / score.general_distances_ratio_squared_capped / tilesNearbyEnemyCounter.value

    def _calculate_nearby_city_scores(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        """
        O(N) to map size worst case
        @param tile:
        @param board_analysis:
        @param score:
        @return:
        """
        nearbyFriendlyCityScore = Counter(0)
        nearbyEnemyCityScore = Counter(0)
        nearbyNeutralCityScore = Counter(0)
        maxDist = min(15, board_analysis.intergeneral_analysis.shortestPathWay.distance // 3)
        frPlayer = board_analysis.general.player
        def scoreNearbyCitiesFunc(curTile: Tile, distance: int):
            if curTile == tile:
                return
            isFriendly = self.map.is_player_on_team_with(curTile.player, frPlayer)
            if curTile.isCity or curTile.isGeneral:
                if isFriendly:
                    nearbyFriendlyCityScore.value += (maxDist - distance)
                elif curTile.player == -1:
                    distMult = maxDist - distance
                    if curTile.army < 4:
                        nearbyNeutralCityScore.value += (distMult * ScaleUtils.rescale_value(min(curTile.army, -100), -100, 4, 40, 5))
                    elif curTile.army < 40:
                        nearbyNeutralCityScore.value += (distMult * ScaleUtils.rescale_value(curTile.army, 4, 40, 4, 1))
                    else:
                        nearbyNeutralCityScore.value += distMult
                else:
                    nearbyEnemyCityScore.value += (maxDist - distance)
            elif curTile.player >= 0:
                distMult = maxDist - distance
                if isFriendly:
                    nearbyFriendlyCityScore.value += 0.1 * distMult * (curTile.army - 1)
                else:
                    nearbyEnemyCityScore.value += 0.1 * distMult * (curTile.army - 1)

        self.foreach_around_city(tile, board_analysis, maxDist, scoreNearbyCitiesFunc)

        score.enemy_city_nearby_score = nearbyEnemyCityScore.value
        score.neutral_city_nearby_score = nearbyNeutralCityScore.value
        score.friendly_city_nearby_score = nearbyFriendlyCityScore.value

    def _calculate_relevance_score(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        """
        O(1)

        @param tile:
        @param board_analysis:
        @param score:
        @return:
        """
        score.neighboring_city_relevance = (2 * score.friendly_city_nearby_score + score.neutral_city_nearby_score) / (score.enemy_city_nearby_score + 2)

        # base offset keeps the very closest cities from being orders of magnitude higher score than 1-2 tiles away
        baseOffset = -5
        # +baseOffset - 15 for example, where +baseOffset is on the shortest path and 15 is way out of the way
        differentialNormalizedPositive = 0 - min(baseOffset, score.intergeneral_distance_differential + baseOffset)
        pathRelevance = score.neighboring_city_relevance / differentialNormalizedPositive
        # logbook.warn(f'TODO REMOVE pathRelevance probably not working right, tile {tile} scored {pathRelevance:.3f} (from neighboring_city_relevance {score.neighboring_city_relevance:.3f} / differentialNormalizedPositive {differentialNormalizedPositive}; intergeneral_distance_differential {score.intergeneral_distance_differential})')
        if pathRelevance < 0:
            pathRelevance = 0

        score.city_relevance_score = pathRelevance

    def _calculate_expandability_score(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        """
        O(N) worst case

        @param tile:
        @param board_analysis:
        @param score:
        @return:
        """
        initExpValue = 40
        if tile.isNeutral:
            initExpValue = max(1, 60 - tile.army)
        expCounter = Counter(initExpValue)
        cityDist = score.distance_from_player_general
        # when the tiles were previously unreachable, or on the other side of a long wall, caps how much value they are worth
        cap = 8
        def scoreNearbyExpandabilityFunc(curTile: Tile, distance: int):
            if not curTile.isNeutral or curTile.isCity or curTile.isMountain:
                return

            tileNewDist = distance + cityDist
            oldDist = min(tileNewDist + cap, board_analysis.intergeneral_analysis.aMap[curTile])
            # if positive, we open this tile up, if negative ignore
            tileExplorabilityDifferential = oldDist - tileNewDist
            if tileExplorabilityDifferential >= 0:
                expCounter.add(tileExplorabilityDifferential)

            # and then just give points for nearby neutral tiles in general
            expCounter.add(0.4)

        maxDist = min(15, board_analysis.intergeneral_analysis.shortestPathWay.distance // 4)
        self.foreach_around_city(tile, board_analysis, maxDist, scoreNearbyExpandabilityFunc)

        score.city_expandability_score = expCounter.value

    def _calculate_2v2_score(
            self,
            tile: Tile,
            board_analysis: BoardAnalyzer,
            ally_dist_map: MapMatrixInterface[int],
            teammate: Player,
            score: CityScoreData):
        """
        O(1)

        @param tile:
        @param board_analysis:
        @param ally_dist_map:
        @param teammate:
        @param score:
        @return:
        """

        usDistFromCity = board_analysis.intergeneral_analysis.aMap[tile]
        allyDistFromUs = board_analysis.intergeneral_analysis.aMap[teammate.general]
        allyDistFromCity = ally_dist_map[tile]

        cityDistSum = usDistFromCity + allyDistFromCity
        if DebugHelper.IS_DEBUGGING:
            logbook.info(f'2v2 ally city calc, {str(tile)} - cityDistSum {cityDistSum} = usDistFromCity {usDistFromCity} + allyDistFromCity {allyDistFromCity}, vs allyDistFromUs {allyDistFromUs}')
        if cityDistSum < allyDistFromUs:
            oldExpScore = score.city_expandability_score
            oldRelScore = score.city_relevance_score
            score.city_expandability_score += 100
            score.city_relevance_score *= 2
            score.city_defensability_score *= 2
            score.city_general_defense_score *= 2
            if DebugHelper.IS_DEBUGGING:
                logbook.info(
                    f'2v2 CHOKE city, {str(tile)} - exp {oldExpScore} -> {score.city_expandability_score},  rel {oldRelScore} -> {score.city_relevance_score}')
        #
        # if allyDistFromCity < usDistFromCity:
        #     score.city_expandability_score += 0.05

    def foreach_around_city(self, tile: Tile, board_analysis: BoardAnalyzer, maxDist: int, foreachFunc: typing.Callable[[Tile, int], None]):
        def newForeach(t: Tile, dist: int) -> bool:
            foreachFunc(t, dist)
            return t.isObstacle and t != tile

        SearchUtils.breadth_first_foreach_dist(
            board_analysis.map,
            [tile],
            maxDist,
            newForeach,
            noLog=True,
            bypassDefaultSkip=True)

    def get_sorted_neutral_scores(self) -> typing.List[typing.Tuple[Tile, CityScoreData]]:
        tileScores = [t for t in sorted(self.city_scores.items(), reverse=True, key=lambda ts: ts[1].get_weighted_neutral_value(log=len(self.city_scores) < 20))]
        return tileScores

    def get_sorted_enemy_scores(self) -> typing.List[typing.Tuple[Tile, CityScoreData]]:
        enemyTileScores = [t for t in sorted(self.enemy_city_scores.items(), reverse=True, key=lambda ts: ts[1].get_weighted_enemy_capture_value(log=len(self.enemy_city_scores) < 20))]
        return enemyTileScores

    def is_contested(self, city: Tile, captureCutoffAgoTurns: int = 20, enemyTerritorySearchDepth: int = 4) -> bool:
        if city.turn_captured > self.map.turn - captureCutoffAgoTurns:
            return True

        countFriendlyNear = SearchUtils.Counter(0)
        countEnemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile, dist: int):
            if self.map.is_player_on_team_with(tile.player, city.player):
                countFriendlyNear.add(1)
            elif tile.player >= 0:
                countEnemyNear.add(1)

        SearchUtils.breadth_first_foreach_dist_fast_no_neut_cities(
            self.map,
            [city],
            maxDepth=enemyTerritorySearchDepth,
            foreachFunc=counterFunc,
        )

        if countEnemyNear.value > countFriendlyNear.value:
            return True

        return False
