import logbook
import time
import typing
from enum import Enum

import DebugHelper
import GatherUtils
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from CityAnalyzer import CityAnalyzer
from DataModels import GatherTreeNode
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
        self.is_contesting_cities: bool = False
        self.target_player: int = -1
        self.target_player_location: Tile = map.GetTile(0, 0)
        self.recommended_offense_plan_turns: int = 0
        self.recommended_city_defense_plan_turns: int = 0

        self.most_forward_defense_city: Tile | None = None
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
            self.is_contesting_cities = True
            if self.opponent_tracker.get_current_team_scores_by_player(self.target_player).cityCount == 2:
                self.viable_win_conditions.add(WinCondition.KillAllIn)

        if self.is_able_to_win_or_recover_economically():
            self.viable_win_conditions.add(WinCondition.WinOnEconomy)
        else:
            self.viable_win_conditions.add(WinCondition.KillAllIn)

        if self.is_winning_and_defending_economic_lead_wont_lose_economy():
            self.viable_win_conditions.add(WinCondition.DefendEconomicLead)
        if self.is_threat_of_loss_to_city_contest():
            self.viable_win_conditions.add(WinCondition.DefendContestedFriendlyCity)

    def is_able_to_contest_enemy_city(self) -> bool:
        didEnemyTakeHardToDefendEarlyCity = False
        if self.map.turn % 50 == 0:
            self.is_contesting_cities = False

        enTargetCities = self.city_analyzer.get_sorted_enemy_scores()

        attackTime = self.board_analysis.inter_general_distance + 5

        ourOffense = 0

        if self.target_player_location is not None and not self.target_player_location.isObstacle:
            ourOffenseTurns, ourOffense = self.get_dynamic_turns_approximate_attack_against(self.target_player_location, maxTurns=self.board_analysis.inter_general_distance, asPlayer=self.map.player_index)
            attackTime = ourOffenseTurns
            
        self.recommended_offense_plan_turns = attackTime

        # frCapThreat = self.get_rough_estimate_friendly_attack(turns=15)
        # enDefPoss = self.get_rough_estimate_enemy_defense(turns=15)

        frArmyStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.map.player_index)
        enArmyStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.target_player)
        if enArmyStats is None:
            self.is_contesting_cities = False
            return False

        frScores = self.opponent_tracker.get_current_team_scores_by_player(self.map.player_index)
        enScores = self.opponent_tracker.get_current_team_scores_by_player(self.target_player)
        if enScores.cityCount == len(enArmyStats.players):
            self.is_contesting_cities = False
            return False

        currentlyOwnedContestedEnCities = [c for c in self.city_analyzer.owned_contested_cities if not self.territories.is_tile_in_friendly_territory(c)]
        for city in self.map.players[self.map.player_index].cities:
            if city not in currentlyOwnedContestedEnCities and self.board_analysis.intergeneral_analysis.bMap[city.x][city.y] * 2 < self.board_analysis.intergeneral_analysis.aMap[city.x][city.y]:
                currentlyOwnedContestedEnCities.append(city)

        baseFrCities = frScores.cityCount - len(currentlyOwnedContestedEnCities)
        baseEnCities = enScores.cityCount + len(currentlyOwnedContestedEnCities)

        ableToContest = False

        contestableCities = [c for c, score in enTargetCities if self.map.is_tile_on_team_with(c, self.target_player)][0:3]

        baselineWinRequirement = 0.4   # 0.5 equates to 12.5 tile econ advantage by holding the city
        if self.is_contesting_cities:
            baselineWinRequirement = 0.1
        cityCapsRequiredToReachWinningStatus = baselineWinRequirement + enScores.tileCount / 25 - frScores.tileCount / 25 + baseEnCities - baseFrCities

        cityCaps = len(currentlyOwnedContestedEnCities)

        if cityCaps >= cityCapsRequiredToReachWinningStatus:
            ableToContest = True

        self.target_cities.update(currentlyOwnedContestedEnCities)

        logbook.info(f'baseFrCities {baseFrCities}, baseEnCities {baseEnCities}, cityCapsRequiredToReachWinningStatus {cityCapsRequiredToReachWinningStatus:.2f}. Cities already contested: {len(currentlyOwnedContestedEnCities)}  {str(currentlyOwnedContestedEnCities)}')

        enDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=4, inTurns=attackTime)

        if len(contestableCities) > 0:
            # then we can plan around one of their cities
            for city in contestableCities:
                ourOffense = self.get_approximate_attack_against([city], inTurns=attackTime, asPlayer=self.map.player_index)

                enDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=4, inTurns=attackTime)
                bestVisibleDefenseTurns, bestVisibleDefenseValue = self.get_dynamic_turns_visible_defense_against([city], attackTime, asPlayer=self.target_player)
                if bestVisibleDefenseTurns > 0:
                    visibleVt = bestVisibleDefenseValue / bestVisibleDefenseTurns
                    fogVt = enDefense / attackTime

                    if visibleVt > fogVt:
                        remainingFogDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=2, inTurns=attackTime - bestVisibleDefenseTurns)
                        logbook.info(
                            f'assuming visible defense of {str(city)} with value {bestVisibleDefenseValue} in {bestVisibleDefenseTurns} ({visibleVt:.2f}v/t), resulting in remainingFogDefense {remainingFogDefense}')
                        enDefense = bestVisibleDefenseValue + remainingFogDefense

                if ourOffense > enDefense:
                    logbook.info(f'able to contest {str(city)} with expected enDefense {enDefense} vs our offense {ourOffense}')
                    self.target_cities.add(city)
                    cityCaps += 1
                    if cityCaps >= cityCapsRequiredToReachWinningStatus:
                        ableToContest = True
                else:
                    logbook.info(f'NOT able to contest {str(city)} with expected enDefense {enDefense} vs our offense {ourOffense}')
            #
            # if len(contestableCities) > 3:
            #     remainingCities = contestableCities[3:]
            #     ourOffense = self.get_approximate_attack_against(remainingCities, inTurns=attackTime, asPlayer=self.map.player_index)
            #
            #     if ourOffense > enDefense:
            #         logbook.info(f'able to contest some cities with expected enDefense {enDefense} vs our offense {ourOffense}')
            #         self.target_cities.update(remainingCities)
            #         cityCaps += 1
            #         if cityCaps >= cityCapsRequiredToReachWinningStatus:
            #             ableToContest = True
            #     else:
            #         logbook.info(f'NOT able to contest some cities with expected enDefense {enDefense} vs our offense {ourOffense}')
        elif self.target_player_location is not None:
            # we dont know where their cities are, but we can try to search if the attack is strong enough.
            # ourOffense = self.get_approximate_attack_against(self.target_player_location, inTurns=attackTime, asPlayer=self.map.player_index)
            defenseExtraTurns = 0
            if not self.target_player_location.isGeneral:
                targetPlayerObj = self.map.players[self.target_player]
                tilesWeHaveSeen = set([t for t in targetPlayerObj.tiles if t.discovered])
                tileCountUnseen = targetPlayerObj.tileCount - len(tilesWeHaveSeen)

                cutoffIncrease = 1 + int(tileCountUnseen / 2)
                defenseExtraTurns = cutoffIncrease

                # todo also support valid general positions

            enDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=4, inTurns=attackTime + defenseExtraTurns)

            bestVisibleDefenseTurns, bestVisibleDefenseValue = self.get_dynamic_turns_visible_defense_against([self.target_player_location], attackTime, asPlayer=self.target_player)
            if bestVisibleDefenseTurns > 0:
                visibleVt = bestVisibleDefenseValue / bestVisibleDefenseTurns
                fogVt = enDefense / attackTime

                if visibleVt > fogVt:
                    remainingFogDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=2, inTurns=attackTime - bestVisibleDefenseTurns)
                    logbook.info(f'assuming visible defense of {str(self.target_player_location)} with value {bestVisibleDefenseValue} in {bestVisibleDefenseTurns} ({visibleVt:.2f}v/t), resulting in remainingFogDefense {remainingFogDefense}')
                    enDefense = bestVisibleDefenseValue + remainingFogDefense

            if ourOffense > enDefense:
                logbook.info(f'able to contest {str(self.target_player_location)} with expected enDefense {enDefense} vs our offense {ourOffense}')
                self.target_cities.add(self.target_player_location)
                cityCaps += 1
                if cityCaps >= cityCapsRequiredToReachWinningStatus:
                    ableToContest = True
            else:
                logbook.info(f'NOT able to contest {str(self.target_player_location)} with expected enDefense {enDefense} vs our offense {ourOffense}')

        self.is_contesting_cities = ableToContest
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

        logbook.info(f'losingByTwoCyclesAgo {losingByTwoCyclesAgo}, losingByOneCyclesAgo {losingByOneCyclesAgo}')

        if losingByTwoCyclesAgo < 0 and losingByTwoCyclesAgo > losingByOneCyclesAgo - 2:
            return False

        return True

    def is_winning_and_defending_economic_lead_wont_lose_economy(self) -> bool:
        return self.opponent_tracker.winning_on_economy(byRatio=1.07, offset=-15)

    def is_threat_of_loss_to_city_contest(self) -> bool:
        weAreSlightlyAhead = self.opponent_tracker.winning_on_economy(byRatio=1.05, offset=-5)

        oldDefTurns = self.recommended_city_defense_plan_turns
        self.recommended_city_defense_plan_turns = 0

        mostForwardCity = None
        mostForwardDist = 1000

        for city, score in self.city_analyzer.player_city_scores.items():
            cityDist = self.get_tile_dist_to_enemy(city)
            if cityDist < mostForwardDist:
                mostForwardCity = city
                mostForwardDist = cityDist

            if self.is_city_forward_relative_to_central_point(city, offset=5):
                self.defend_cities.add(city)

        self.most_forward_defense_city = mostForwardCity

        maxThreat = 0
        maxThreatTurns = 0
        for city in self.map.players[self.map.player_index].cities:
            isEnemySide = self.board_analysis.intergeneral_analysis.bMap[city.x][city.y] * 1.2 < self.board_analysis.intergeneral_analysis.aMap[city.x][city.y]
            isContested = city in self.city_analyzer.owned_contested_cities

            if not isEnemySide and not isContested:
                continue

            threatAllowedTurns = oldDefTurns - 1
            if threatAllowedTurns < 5:
                threatAllowedTurns = 20

            approxThreatTurns, approxThreat = self.get_dynamic_turns_approximate_attack_against(city, maxTurns=threatAllowedTurns, asPlayer=self.target_player)

            approxDefTurns, approxDef = self.get_dynamic_turns_visible_defense_against(tiles=[city], maxTurns=threatAllowedTurns, asPlayer=self.map.player_index)

            if approxThreat > approxDef + city.army:
                self.defend_cities.add(city)
                if approxThreat - city.army > maxThreat:
                    maxThreat = approxThreat - city.army
                    maxThreatTurns = approxThreatTurns

        numRiskyCities = len(self.defend_cities)
        sortOfWinningEconCurrently = self.opponent_tracker.winning_on_economy(byRatio=0.9)

        wouldStillBeWinningIfLostRiskies = self.opponent_tracker.winning_on_economy(byRatio=1.0, offset=-50 * numRiskyCities)

        sumArmyOnDefCities = 0
        for city in self.defend_cities:
            sumArmyOnDefCities += city.army

        fogRisk = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=5, inTurns=10)
        if fogRisk < sumArmyOnDefCities:
            return False

        self.recommended_city_defense_plan_turns = maxThreatTurns

        couldLose = numRiskyCities > 0 and sortOfWinningEconCurrently and not wouldStillBeWinningIfLostRiskies

        return couldLose

    def get_approximate_attack_against(self, tiles: typing.List[Tile], inTurns: int, asPlayer: int, timeLimit: float = 0.005) -> int:
        curTiles = tiles
        if DebugHelper.IS_DEBUGGING:
            timeLimit *= 4

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
            cutoffTime=time.perf_counter() + timeLimit,
            shouldLog=False,
            fastMode=True
            # priorityMatrix=priorityMatrix
        )

        value += self.get_additional_fog_gather_risk(gatherNodes, asPlayer, inTurns)
        logbook.info(f'concluded get_approximate_attack_against gather, value {value}')

        return max(0, value)

    def get_dynamic_turns_visible_defense_against(self, tiles: typing.List[Tile], maxTurns: int, asPlayer: int, timeLimit: float = 0.005) -> typing.Tuple[int, int]:
        curTiles = tiles
        if DebugHelper.IS_DEBUGGING:
            timeLimit *= 4

        value, gatherNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
            self.map,
            curTiles,
            maxTurns,
            negativeTiles = set([t for t in self.map.players[asPlayer].tiles if not t.visible]),
            searchingPlayer=asPlayer,
            # skipFunc=skipFunc,
            # viewInfo=self.viewInfo if self.info_render_gather_values else None,
            # skipTiles=skipTiles,
            distPriorityMap=self.board_analysis.intergeneral_analysis.bMap,
            # priorityTiles=priorityTiles,
            includeGatherTreeNodesThatGatherNegative=False,
            incrementBackward=False,
            useTrueValueGathered=True,
            cutoffTime=time.perf_counter() + timeLimit,
            shouldLog=False,
            fastMode=True
            # priorityMatrix=priorityMatrix
        )

        logbook.info(f'concluded get_dynamic_visible_defense_against gather, value {value}')

        if value > 0:
            prunedTurns, prunedValue, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                minArmy=1,
                searchingPlayer=asPlayer,
                teams=MapBase.get_teams_array(self.map),
                # viewInfo=self.viewInfo if self.info_render_gather_values else None,
                allowBranchPrune=False
            )

            logbook.info(f'concluded get_dynamic_visible_defense_against prune, value {prunedValue}')

            return prunedTurns, max(0, prunedValue)

        logbook.info(f'concluded get_dynamic_visible_defense_against zeros')
        return 0, 0

    def get_dynamic_turns_approximate_attack_against(self, tile: Tile, maxTurns: int, asPlayer: int, timeLimit: float = 0.005) -> typing.Tuple[int, int]:
        curTiles = [tile]
        if DebugHelper.IS_DEBUGGING:
            timeLimit *= 4

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
            cutoffTime=time.perf_counter() + timeLimit,
            shouldLog=False,
            fastMode=True
            # priorityMatrix=priorityMatrix
        )

        logbook.info(f'concluded get_dynamic_attack_against gather')

        fogRisk = self.get_additional_fog_gather_risk(gatherNodes, asPlayer, maxTurns)

        if value + fogRisk > 0:
            prunedTurns, prunedValue, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                minArmy=1,
                searchingPlayer=asPlayer,
                teams=MapBase.get_teams_array(self.map),
                # viewInfo=self.viewInfo if self.info_render_gather_values else None,
                allowBranchPrune=False
            )

            prunedValue += self.get_additional_fog_gather_risk(gatherNodes, asPlayer, prunedTurns)

            logbook.info(f'concluded get_dynamic_attack_against prune, value {prunedValue}')

            return prunedTurns, max(0, prunedValue)

        logbook.info(f'concluded get_dynamic_attack_against zeros')

        return 0, 0

    def is_city_forward_relative_to_central_point(self, city: Tile, offset: int = 3):
        if self.board_analysis.central_defense_point is None:
            return True

        if self.get_tile_dist_to_enemy(city) + offset < self.get_tile_dist_to_enemy(self.board_analysis.central_defense_point):
            return True

        return False

    def get_tile_dist_to_enemy(self, tile: Tile) -> int:
        return self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]

    def get_additional_fog_gather_risk(self, gatherNodes: typing.List[GatherTreeNode], asPlayer: int, inTurns: int) -> int:
        if self.map.is_player_on_team_with(asPlayer, self.map.player_index):
            return 0

        numFogTiles = SearchUtils.Counter(0)

        fogValue = SearchUtils.Counter(0)

        def fogCounterFunc(node: GatherTreeNode):
            if not node.tile.visible:
                numFogTiles.value += 1
                if self.map.is_player_on_team_with(node.tile.player, asPlayer):
                    fogValue.value += node.tile.army - 1
                else:
                    fogValue.value -= node.tile.army + 1

        GatherUtils.iterate_tree_nodes(gatherNodes, forEachFunc=fogCounterFunc)

        result = self.opponent_tracker.get_approximate_fog_army_risk(asPlayer, inTurns=inTurns) - fogValue.value
        logbook.info(f'get_additional_fog_gather_risk fogValue {fogValue.value}, numFogTiles {numFogTiles.value}, inTurns {inTurns}, result {result}')
        if numFogTiles.value > inTurns // 4:
            return max(0, result)

        return 0
