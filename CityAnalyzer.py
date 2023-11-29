import logging
import typing

import DebugHelper
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from SearchUtils import Counter
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

    def get_weighted_neutral_value(self) -> float:
        totalScore = self.city_defensability_score * self.city_relevance_score * self.city_expandability_score * self.city_general_defense_score
        totalScore = totalScore
        logging.info(f"cityScore neut {self.tile.x},{self.tile.y}: re{self.city_relevance_score:.4f}, ex{self.city_expandability_score:.4f}, def{self.city_defensability_score:.4f}, gdef{self.city_general_defense_score:.4f}, tot{totalScore:.3f}")
        return totalScore

    def get_weighted_enemy_capture_value(self) -> float:
        totalScore = self.city_defensability_score * self.city_relevance_score
        if not self.tile.discovered:
            totalScore = totalScore / 2
        logging.info(f"cityScore enemy {self.tile.x},{self.tile.y}: re{self.city_relevance_score:.4f}, def{self.city_defensability_score:.4f}, tot{totalScore:.3f}")
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

        allyDistMap = None
        teammate = None

        if self.map.is_2v2:
            teammate = self.map.players[[t for t in self.map.teammates][0]]
            if not teammate.dead:
                allyDistMap = SearchUtils.build_distance_map(self.map, [teammate.general])

        for tile in self.map.reachableTiles:
            # TODO calculate predicted enemy city locations in fog and explore mountains more in places we would WANT cities to be
            tileMightBeUndiscCity = not tile.discovered and tile.isObstacle and tile in self.map.reachableTiles
            # if not (tile.isCity or tileMightBeUndiscCity):
            if not tile.isCity:
                continue

            score = CityScoreData(tile)

            self._calculate_nearby_city_scores(tile, board_analysis, score)
            self._calculate_distance_scores(tile, board_analysis, score)
            self._calculate_relevance_score(tile, board_analysis, score)
            self._calculate_danger_score(tile, board_analysis, score)
            self._calculate_expandability_score(tile, board_analysis, score)
            if allyDistMap is not None:
                self._calculate_2v2_score(tile, board_analysis, allyDistMap, teammate, score)

            if tile.isCity:
                if tile.isNeutral:
                    self.city_scores[tile] = score
                elif self.map.is_player_on_team_with(tile.player, board_analysis.general.player):
                    self.player_city_scores[tile] = score
                    if self.is_contested(tile):
                        self.owned_contested_cities.add(tile)
                elif tile.player not in self.map.teammates:
                    self.enemy_city_scores[tile] = score
                    if self.is_contested(tile):
                        self.enemy_contested_cities.add(tile)

            else:
                self.undiscovered_mountain_scores[tile] = score

    def _calculate_distance_scores(self, city: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        """
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
            score.distance_from_player_general = min(score.distance_from_player_general, board_analysis.intergeneral_analysis.aMap[adj.x][adj.y] + 1)
            score.distance_from_enemy_general = min(score.distance_from_enemy_general, board_analysis.intergeneral_analysis.bMap[adj.x][adj.y] + 1)

        currentShortest = board_analysis.intergeneral_analysis.shortestPathWay.distance

        score.intergeneral_distance_through_city = score.distance_from_enemy_general + score.distance_from_player_general

        score.intergeneral_distance_differential = currentShortest - score.intergeneral_distance_through_city

        score.general_distances_ratio = score.distance_from_player_general / max(1, score.distance_from_enemy_general)

        # make this MUCH more impactful to the score, but cap it so we don't massively prioritize cities behind us
        distanceRatioSquared = score.general_distances_ratio * score.general_distances_ratio
        distanceRatioSquared = max(distanceRatioSquared, 0.1)

        score.general_distances_ratio_squared_capped = distanceRatioSquared

    def _calculate_danger_score(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        # used to prevent tiles right next to general from being weighted WAY better than tiles 2 tiles away etc
        if self.map.turn > 200 or not tile.isNeutral:
            scaleOffset = 10
        else:
            scaleOffset = max(0, tile.army - 34)

        score.city_general_defense_score = 0.3 + 1.0 / max(1, score.distance_from_player_general + scaleOffset) / max(0.2, score.general_distances_ratio)

        tilesNearbyFriendlyCounter = Counter(3)
        tilesNearbyEnemyCounter = Counter(3)
        def scoreNearbyTerritoryFunc(curTile: Tile, distance: int):
            if curTile.isNeutral or curTile.isObstacle:
                return

            if self.map.is_player_on_team_with(curTile.player, board_analysis.general.player):
                tilesNearbyFriendlyCounter.add(1)
            else:
                tilesNearbyEnemyCounter.add(1)

        maxDist = board_analysis.intergeneral_analysis.shortestPathWay.distance // 4
        self.foreach_around_city(tile, board_analysis, maxDist, scoreNearbyTerritoryFunc)

        score.city_defensability_score = (score.friendly_city_nearby_score + tilesNearbyFriendlyCounter.value // 2) / score.general_distances_ratio_squared_capped / tilesNearbyEnemyCounter.value


    def _calculate_nearby_city_scores(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        nearbyFriendlyCityScore = Counter(0)
        nearbyEnemyCityScore = Counter(0)
        nearbyNeutralCityScore = Counter(0)
        maxDist = board_analysis.intergeneral_analysis.shortestPathWay.distance // 3

        def scoreNearbyCitiesFunc(curTile: Tile, distance: int):
            if curTile.isCity or curTile.isGeneral:
                if self.map.is_player_on_team_with(curTile.player, board_analysis.general.player):
                    nearbyFriendlyCityScore.add(maxDist - distance)
                elif curTile.player == -1:
                    nearbyNeutralCityScore.add(maxDist - distance)
                else:
                    nearbyEnemyCityScore.add(maxDist - distance)

        self.foreach_around_city(tile, board_analysis, maxDist, scoreNearbyCitiesFunc)

        score.enemy_city_nearby_score = nearbyEnemyCityScore.value
        score.neutral_city_nearby_score = nearbyNeutralCityScore.value
        score.friendly_city_nearby_score = nearbyFriendlyCityScore.value

    def _calculate_relevance_score(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
        score.neighboring_city_relevance = (2 * score.friendly_city_nearby_score + score.neutral_city_nearby_score) / (score.enemy_city_nearby_score + 2)

        # base offset keeps the very closest cities from being orders of magnitude higher score than 1-2 tiles away
        baseOffset = -5
        # +baseOffset - 15 for example, where +baseOffset is on the shortest path and 15 is way out of the way
        differentialNormalizedPositive = 0 - min(baseOffset, score.intergeneral_distance_differential + baseOffset)

        pathRelevance = score.neighboring_city_relevance / differentialNormalizedPositive

        if pathRelevance < 0:
            pathRelevance = 0

        score.city_relevance_score = pathRelevance

    def _calculate_expandability_score(self, tile: Tile, board_analysis: BoardAnalyzer, score: CityScoreData):
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
            oldDist = min(tileNewDist + cap, board_analysis.intergeneral_analysis.aMap[curTile.x][curTile.y])
            # if positive, we open this tile up, if negative ignore
            tileExplorabilityDifferential = oldDist - tileNewDist
            if tileExplorabilityDifferential >= 0:
                expCounter.add(tileExplorabilityDifferential)

            # and then just give points for nearby neutral tiles in general
            expCounter.add(0.4)

        maxDist = board_analysis.intergeneral_analysis.shortestPathWay.distance // 4
        self.foreach_around_city(tile, board_analysis, maxDist, scoreNearbyExpandabilityFunc)

        score.city_expandability_score = expCounter.value

    def _calculate_2v2_score(
            self,
            tile: Tile,
            board_analysis: BoardAnalyzer,
            ally_dist_map: typing.List[typing.List[int]],
            teammate: Player,
            score: CityScoreData):

        usDistFromCity = board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
        allyDistFromUs = board_analysis.intergeneral_analysis.aMap[teammate.general.x][teammate.general.y]
        allyDistFromCity = ally_dist_map[tile.x][tile.y]

        cityDistSum = usDistFromCity + allyDistFromCity
        if DebugHelper.IS_DEBUGGING:
            logging.info(f'2v2 ally city calc, {str(tile)} - cityDistSum {cityDistSum} = usDistFromCity {usDistFromCity} + allyDistFromCity {allyDistFromCity}, vs allyDistFromUs {allyDistFromUs}')
        if cityDistSum < allyDistFromUs:
            oldExpScore = score.city_expandability_score
            oldRelScore = score.city_relevance_score
            score.city_expandability_score += 100
            score.city_relevance_score *= 2
            score.city_defensability_score *= 2
            score.city_general_defense_score *= 2
            if DebugHelper.IS_DEBUGGING:
                logging.info(
                    f'2v2 CHOKE city, {str(tile)} - exp {oldExpScore} -> {score.city_expandability_score},  rel {oldRelScore} -> {score.city_relevance_score}')
        #
        # if allyDistFromCity < usDistFromCity:
        #     score.city_expandability_score += 0.05

    def foreach_around_city(self, tile: Tile, board_analysis: BoardAnalyzer, maxDist: int, foreachFunc: typing.Callable[[Tile, int], None]):
        SearchUtils.breadth_first_foreach_dist(
            board_analysis.map,
            [tile],
            maxDist,
            foreachFunc,
            skipFunc=lambda t: t != tile and t.isObstacle,
            noLog=True,
            bypassDefaultSkip=True)

    def get_sorted_neutral_scores(self) -> typing.List[typing.Tuple[Tile, CityScoreData]]:
        tileScores = [t for t in sorted(self.city_scores.items(), reverse=True, key=lambda ts: ts[1].get_weighted_neutral_value())]
        return tileScores

    def get_sorted_enemy_scores(self) -> typing.List[typing.Tuple[Tile, CityScoreData]]:
        enemyTileScores = [t for t in sorted(self.enemy_city_scores.items(), reverse=True, key=lambda ts: ts[1].get_weighted_enemy_capture_value())]
        return enemyTileScores

    def is_contested(self, city: Tile) -> bool:
        if city.turn_captured > self.map.turn - 20:
            return True

        countFriendlyNear = SearchUtils.Counter(0)
        countEnemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile, dist: int):
            if self.map.is_player_on_team_with(tile.player, city.player):
                countFriendlyNear.add(1)
            elif tile.player >= 0:
                countEnemyNear.add(1)

        SearchUtils.breadth_first_foreach_dist(
            self.map,
            [city],
            maxDepth=5,
            noLog=True,
            foreachFunc=counterFunc,
        )

        if countEnemyNear.value > countFriendlyNear.value:
            return True

        return False








