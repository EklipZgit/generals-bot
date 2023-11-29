import logging
import time
import typing
from enum import Enum

import GatherUtils
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from CityAnalyzer import CityAnalyzer
from MapMatrix import MapMatrix
from Territory import TerritoryClassifier
from .OpponentTracker import OpponentTracker
from base.client.map import MapBase, Tile


class WinCondition(Enum):
    WinOnEconomy = 0
    KillAllIn = 1
    DefendEconomicLead = 2
    DefendContestedFriendlyCity = 3
    ContestEnemyCity = 4


class WinConditionAnalyzer(object):
    def __init__(
            self,
            map: MapBase,
            opponentTracker: OpponentTracker,
            cityAnalyzer: CityAnalyzer,
            territories: TerritoryClassifier,
            boardAnalyzer: BoardAnalyzer
    ):
        self.map: MapBase = map
        self.opponent_tracker: OpponentTracker = opponentTracker
        self.city_analyzer: CityAnalyzer = cityAnalyzer
        self.territories: TerritoryClassifier = territories
        self.board_analysis: BoardAnalyzer = boardAnalyzer
        self.viable_win_conditions: typing.Set[WinCondition] = set()
        self.target_player: int = -1
        self.target_player_location: Tile = map.GetTile(0, 0)

        self.target_cities: typing.Set[Tile] = set()
        self.defend_cities: typing.Set[Tile] = set()

    def analyze(self, targetPlayer: int, targetPlayerExpectedGeneralLocation: Tile):
        self.viable_win_conditions = set()

        self.target_cities = set()
        self.defend_cities = set()

        self.target_player = targetPlayer
        self.target_player_location: Tile = targetPlayerExpectedGeneralLocation

        if self.target_player == -1:
            self.viable_win_conditions.add(WinCondition.WinOnEconomy)
            return

        if self.is_able_to_contest_enemy_city():
            self.viable_win_conditions.add(WinCondition.ContestEnemyCity)
            if self.opponent_tracker.get_current_team_scores_by_player(self.target_player).cityCount == 2:
                self.viable_win_conditions.add(WinCondition.KillAllIn)

        if self.is_able_to_win_or_recover_economically():
            self.viable_win_conditions.add(WinCondition.WinOnEconomy)
        else:
            self.viable_win_conditions.add(WinCondition.KillAllIn)

        if self.is_winning_and_defending_economic_lead_wont_lose_economy():
            self.viable_win_conditions.add(WinCondition.DefendEconomicLead)
        if self.opponent_tracker.winning_on_economy(byRatio=1.05, offset=-5) and self.is_threat_of_loss_to_city_contest():
            self.viable_win_conditions.add(WinCondition.DefendContestedFriendlyCity)

    def is_able_to_contest_enemy_city(self) -> bool:
        didEnemyTakeHardToDefendEarlyCity = False

        enTargetCities = self.city_analyzer.get_sorted_enemy_scores()

        attackTime = self.board_analysis.inter_general_distance + 5

        if self.target_player_location is not None and not self.target_player_location.isObstacle:
            ourOffenseTurns, ourOffense = self.get_dynamic_attack_against(self.target_player_location, maxTurns=self.board_analysis.inter_general_distance * 2, asPlayer=self.map.player_index)
            attackTime = ourOffenseTurns

        # frCapThreat = self.get_rough_estimate_friendly_attack(turns=15)
        # enDefPoss = self.get_rough_estimate_enemy_defense(turns=15)

        frArmyStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.map.player_index)
        enArmyStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.target_player)

        frScores = self.opponent_tracker.get_current_team_scores_by_player(self.map.player_index)
        enScores = self.opponent_tracker.get_current_team_scores_by_player(self.target_player)
        if enScores.cityCount == len(enArmyStats.players):
            return False

        currentlyOwnedContestedEnCities = [c for c in self.city_analyzer.owned_contested_cities if not self.territories.is_tile_in_friendly_territory(c)]

        baseFrCities = frScores.cityCount - len(currentlyOwnedContestedEnCities)
        baseEnCities = enScores.cityCount + len(currentlyOwnedContestedEnCities)

        ableToContest = False

        contestableCities = [c for c, score in enTargetCities if self.map.is_tile_on_team_with(c, self.target_player)][0:3]

        baselineWinRequirement = -0.6   # 0.5 equates to 12.5 tile econ advantage by holding the city
        cityCapsRequiredToReachWinningStatus = baselineWinRequirement + enScores.tileCount / 25 - frScores.tileCount / 25 + baseEnCities - baseFrCities

        cityCaps = len(currentlyOwnedContestedEnCities)

        if cityCaps >= cityCapsRequiredToReachWinningStatus:
            ableToContest = True

        self.target_cities.update(currentlyOwnedContestedEnCities)

        logging.info(f'baseFrCities {baseFrCities}, baseEnCities {baseEnCities}, cityCapsRequiredToReachWinningStatus {cityCapsRequiredToReachWinningStatus:.2f}. Cities already contested: {len(currentlyOwnedContestedEnCities)}  {str(currentlyOwnedContestedEnCities)}')

        if len(contestableCities) > 0:
            # then we can plan around one of their cities
            for city in contestableCities:
                ourOffense = self.get_approximate_attack_against(city, inTurns=attackTime, asPlayer=self.map.player_index)
                enDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=4, inTurns=attackTime)

                if ourOffense > enDefense:
                    logging.info(f'able to contest {str(city)} with expected enDefense {enDefense} vs our offense {ourOffense}')
                    self.target_cities.add(city)
                    cityCaps += 1
                    if cityCaps >= cityCapsRequiredToReachWinningStatus:
                        ableToContest = True
                else:
                    logging.info(f'NOT able to contest {str(city)} with expected enDefense {enDefense} vs our offense {ourOffense}')
        else:
            # we dont know where their cities are, but we can try to search if the attack is strong enough.
            # ourOffense = self.get_approximate_attack_against(self.target_player_location, inTurns=attackTime, asPlayer=self.map.player_index)
            enDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=4, inTurns=attackTime)

            if ourOffense > enDefense:
                logging.info(f'able to contest {str(self.target_player_location)} with expected enDefense {enDefense} vs our offense {ourOffense}')
                self.target_cities.add(self.target_player_location)
                cityCaps += 1
                if cityCaps >= cityCapsRequiredToReachWinningStatus:
                    ableToContest = True
            else:
                logging.info(f'NOT able to contest {str(self.target_player_location)} with expected enDefense {enDefense} vs our offense {ourOffense}')

        return ableToContest

    def is_able_to_win_or_recover_economically(self) -> bool:
        enStatsMinus1 = self.opponent_tracker.get_last_cycle_stats_by_player(self.target_player, cyclesToGoBack=0)
        frStatsMinus1 = self.opponent_tracker.get_last_cycle_stats_by_player(self.map.player_index, cyclesToGoBack=0)

        enStatsMinus2 = self.opponent_tracker.get_last_cycle_stats_by_player(self.target_player, cyclesToGoBack=1)
        frStatsMinus2 = self.opponent_tracker.get_last_cycle_stats_by_player(self.map.player_index, cyclesToGoBack=1)

        enScoreMinus1 = self.opponent_tracker.get_last_cycle_score_by_player(self.target_player, cyclesToGoBack=0)
        frScoreMinus1 = self.opponent_tracker.get_last_cycle_score_by_player(self.map.player_index, cyclesToGoBack=0)

        enScoreMinus2 = self.opponent_tracker.get_last_cycle_score_by_player(self.target_player, cyclesToGoBack=1)
        frScoreMinus2 = self.opponent_tracker.get_last_cycle_score_by_player(self.map.player_index, cyclesToGoBack=1)

        if frScoreMinus2 is None or frScoreMinus1 is None or frStatsMinus2 is None or frStatsMinus1 is None:
            return True

        losingByTwoCyclesAgo = enScoreMinus2.tileCount + (enScoreMinus2.cityCount - enStatsMinus2.cities_gained) * 25 - frScoreMinus2.tileCount - (frScoreMinus2.cityCount - frStatsMinus2.cities_gained) * 25

        losingByOneCyclesAgo = enScoreMinus1.tileCount + (enScoreMinus1.cityCount - enStatsMinus1.cities_gained) * 25 - frScoreMinus1.tileCount - (frScoreMinus1.cityCount - frStatsMinus1.cities_gained) * 25

        logging.info(f'losingByTwoCyclesAgo {losingByTwoCyclesAgo}, losingByOneCyclesAgo {losingByOneCyclesAgo}')

        if losingByTwoCyclesAgo < 0 and losingByTwoCyclesAgo > losingByOneCyclesAgo - 2:
            return False

        return True

    def is_winning_and_defending_economic_lead_wont_lose_economy(self) -> bool:
        return self.opponent_tracker.winning_on_economy(byRatio=1.07, offset=-15)

    def is_threat_of_loss_to_city_contest(self) -> bool:
        for city, score in self.city_analyzer.player_city_scores.items():
            if self.is_city_forward_relative_to_central_point(city, offset=2):
                self.defend_cities.add(city)

        for city in self.city_analyzer.owned_contested_cities:
            # if not self.territories.is_tile_in_enemy_territory()
            # if self.is_city_forward_relative_to_central_point(city, offset=-3):
            self.defend_cities.add(city)

        numRiskyCities = len(self.defend_cities)
        sortOfWinningEconCurrently = self.opponent_tracker.winning_on_economy(byRatio=0.9)

        wouldStillBeWinningIfLostRiskies = self.opponent_tracker.winning_on_economy(byRatio=1.0, offset=-50 * numRiskyCities)

        return numRiskyCities > 0 and sortOfWinningEconCurrently and not wouldStillBeWinningIfLostRiskies

    def get_approximate_attack_against(self, tile: Tile, inTurns: int, asPlayer: int) -> int:
        curTiles = [tile]

        value, gatherNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
            self.map,
            curTiles,
            inTurns,
            negativeTiles=set(),
            searchingPlayer=asPlayer,
            # skipFunc=skipFunc,
            # viewInfo=self.viewInfo if self.info_render_gather_values else None,
            # skipTiles=skipTiles,
            distPriorityMap=self.board_analysis.intergeneral_analysis.bMap,
            # priorityTiles=priorityTiles,
            includeGatherTreeNodesThatGatherNegative=False,
            incrementBackward=False,
            useTrueValueGathered=True,
            cutoffTime=time.perf_counter() + 0.111,
            shouldLog=False
            # priorityMatrix=priorityMatrix
        )

        return value

    def get_dynamic_attack_against(self, tile: Tile, maxTurns: int, asPlayer: int) -> typing.Tuple[int, int]:
        curTiles = [tile]

        value, gatherNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
            self.map,
            curTiles,
            maxTurns,
            negativeTiles=set(),
            searchingPlayer=asPlayer,
            # skipFunc=skipFunc,
            # viewInfo=self.viewInfo if self.info_render_gather_values else None,
            # skipTiles=skipTiles,
            distPriorityMap=self.board_analysis.intergeneral_analysis.bMap,
            # priorityTiles=priorityTiles,
            includeGatherTreeNodesThatGatherNegative=False,
            incrementBackward=False,
            useTrueValueGathered=True,
            cutoffTime=time.perf_counter() + 0.111,
            shouldLog=False
            # priorityMatrix=priorityMatrix
        )

        prunedTurns, prunedValue, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
            gatherNodes,
            minArmy=1,
            searchingPlayer=asPlayer,
            teams=MapBase.get_teams_array(self.map),
            # viewInfo=self.viewInfo if self.info_render_gather_values else None,
            allowBranchPrune=False
        )

        return prunedTurns, prunedValue

    def is_city_forward_relative_to_central_point(self, city: Tile, offset: int = 3):
        if self.board_analysis.central_defense_point is None:
            return True

        if self.board_analysis.intergeneral_analysis.bMap[city.x][city.y] + offset < self.board_analysis.intergeneral_analysis.bMap[self.board_analysis.central_defense_point.x][self.board_analysis.central_defense_point.y]:
            return True

        return False
