import logbook
import time
import typing
from enum import Enum

import DebugHelper
import Gather
import SearchUtils
from BoardAnalyzer import BoardAnalyzer
from CityAnalyzer import CityAnalyzer
from Models import GatherTreeNode
from MapMatrix import TileSet
from Gather import GatherCapturePlan
from Path import Path
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
        self.last_viable_win_conditions: typing.Set[WinCondition] = set()
        self.is_contesting_cities: bool = False
        self.target_player: int = -1
        self.target_player_location: Tile = map.GetTile(0, 0)
        self.recommended_offense_plan_turns: int = 0
        self.recommended_city_defense_plan_turns: int = 0
        self.our_best_attack_plan: GatherCapturePlan | None = None

        self.contestable_city_offense_plans: typing.Dict[Tile, GatherCapturePlan | None] = {}

        self.most_forward_defense_city: Tile | None = None
        self.contestable_cities: typing.Set[Tile] = set()
        """Cities that are easy to attack that we should consider attacking."""
        self.defend_cities: typing.Set[Tile] = set()
        """Cities we own who are very likely to be attacked and should be defended."""

    def analyze(self, targetPlayer: int, targetPlayerExpectedGeneralLocation: Tile):
        self.last_viable_win_conditions = self.viable_win_conditions
        self.viable_win_conditions = set()

        self.contestable_cities = set()
        self.defend_cities = set()

        self.target_player = targetPlayer
        self.target_player_location: Tile = targetPlayerExpectedGeneralLocation

        if self.target_player == -1:
            self.viable_win_conditions.add(WinCondition.WinOnEconomy)
            return

        self._get_rough_offense()

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
            if WinCondition.WinOnEconomy in self.viable_win_conditions:
                self.viable_win_conditions.add(WinCondition.DefendContestedFriendlyCity)

    def is_able_to_contest_enemy_city(self) -> bool:
        didEnemyTakeHardToDefendEarlyCity = False
        cycleTurn = self.map.turn % 50
        remainingTurns = 50 - cycleTurn
        if cycleTurn == 0:
            self.is_contesting_cities = False

        enTargetCities = self.city_analyzer.get_sorted_enemy_scores()

        ourOffense = 0
        attackTime = self.recommended_offense_plan_turns
        if self.our_best_attack_plan is not None:
            ourOffense = self.our_best_attack_plan.gathered_army

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
            if city not in currentlyOwnedContestedEnCities and self.board_analysis.intergeneral_analysis.bMap[city] * 2 < self.board_analysis.intergeneral_analysis.aMap[city]:
                currentlyOwnedContestedEnCities.append(city)

        baseFrCities = frScores.cityCount - len(currentlyOwnedContestedEnCities)
        baseEnCities = enScores.cityCount + len(currentlyOwnedContestedEnCities)

        ableToContest = False

        contestableCities = [c for c, score in enTargetCities if self.map.is_tile_on_team_with(c, self.target_player)][0:3]

        baselineWinRequirement = 0.5   # 0.5 equates to 12.5 tile econ advantage by holding the city
        if self.is_contesting_cities:
            baselineWinRequirement = 0.2
        cityCapsRequiredToReachWinningStatus = baselineWinRequirement + enScores.tileCount / 25 - frScores.tileCount / 25 + baseEnCities - baseFrCities

        cityCaps = len(currentlyOwnedContestedEnCities)

        if cityCaps >= cityCapsRequiredToReachWinningStatus:
            ableToContest = True

        self.contestable_cities.update(currentlyOwnedContestedEnCities)

        logbook.info(f'baseFrCities {baseFrCities}, baseEnCities {baseEnCities}, cityCapsRequiredToReachWinningStatus {cityCapsRequiredToReachWinningStatus:.2f}. Cities already contested: {len(currentlyOwnedContestedEnCities)}  {str(currentlyOwnedContestedEnCities)}')

        self.contestable_city_offense_plans = {}
        # self.contestable_city_defense_plans = {}
        if len(contestableCities) > 0:
            # then we can plan around one of their cities
            for city in contestableCities:
                ourOffensePlan = self.get_approximate_attack_plan_against([city], inTurns=attackTime, asPlayer=self.map.player_index)
                self.contestable_city_offense_plans[city] = ourOffensePlan
                ourOffense = ourOffensePlan.gathered_army

                enDefense = self.opponent_tracker.get_approximate_fog_army_risk(self.target_player, cityLimit=4, inTurns=attackTime)
                # TODO why we using this instead of just the get attack plan against... which should do the same thing?
                bestVisibleDefenseTurns, bestVisibleDefenseValue = self.get_dynamic_turns_visible_defense_against([city], attackTime, asPlayer=self.target_player, minArmy=ourOffense)
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
                    # TODO expected control turns?
                    self.contestable_cities.add(city)
                    cityCaps += 1
                    if cityCaps >= cityCapsRequiredToReachWinningStatus:
                        ableToContest = True
                else:
                    logbook.info(f'NOT able to contest {str(city)} with expected enDefense {enDefense} vs our offense {ourOffense}')
                    self.contestable_city_offense_plans.pop(city, None)
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
                self.contestable_cities.add(self.target_player_location)
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

        enScoreMinus1 = self.opponent_tracker.get_last_cycle_score_by_player(self.target_player, cyclesToGoBack=0)
        frScoreMinus1 = self.opponent_tracker.get_last_cycle_score_by_player(self.map.player_index, cyclesToGoBack=0)

        enStatsMinus2 = self.opponent_tracker.get_last_cycle_stats_by_player(self.target_player, cyclesToGoBack=1)
        frStatsMinus2 = self.opponent_tracker.get_last_cycle_stats_by_player(self.map.player_index, cyclesToGoBack=1)

        enScoreMinus2 = self.opponent_tracker.get_last_cycle_score_by_player(self.target_player, cyclesToGoBack=1)
        frScoreMinus2 = self.opponent_tracker.get_last_cycle_score_by_player(self.map.player_index, cyclesToGoBack=1)

        if frScoreMinus2 is None or frScoreMinus1 is None or frStatsMinus2 is None or frStatsMinus1 is None:
            return True

        losingByTwoCyclesAgo = self.get_economic_diff_against_target_player(cyclesAgo=2)

        losingByOneCyclesAgo = self.get_economic_diff_against_target_player(cyclesAgo=1)

        # losingByNow = self.get_economic_diff_against_target_player(cyclesAgo=0)

        logbook.info(f'losingByTwoCyclesAgo {losingByTwoCyclesAgo}, losingByOneCyclesAgo {losingByOneCyclesAgo}')

        if -1 > losingByTwoCyclesAgo > losingByOneCyclesAgo + 1:
            logbook.info(f'We appear to be losing more and more on economy.')
            return False

        return True

    def is_winning_and_defending_economic_lead_wont_lose_economy(self) -> bool:
        return self.opponent_tracker.winning_on_economy(byRatio=1.07, offset=-15)

    def is_threat_of_loss_to_city_contest(self) -> bool:
        weAreSlightlyAhead = self.opponent_tracker.winning_on_economy(byRatio=1.1, offset=-10)
        if WinCondition.DefendContestedFriendlyCity in self.last_viable_win_conditions:
            weAreSlightlyAhead = self.opponent_tracker.winning_on_economy(byRatio=1.03, offset=-4)

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
        analyzedCount = 0
        for city in sorted(self.map.players[self.map.player_index].cities, key=lambda t: self.board_analysis.intergeneral_analysis.bMap[t]):
            isEnemySide = self.board_analysis.intergeneral_analysis.bMap[city] * 1.2 < self.board_analysis.intergeneral_analysis.aMap[city]
            isContested = city in self.city_analyzer.owned_contested_cities

            if not isEnemySide and not isContested:
                continue
            analyzedCount += 1

            if analyzedCount > 4:
                break

            threatAllowedTurns = oldDefTurns - 1
            if threatAllowedTurns < 5:
                threatAllowedTurns = 20

            approxThreatTurns, approxThreat = self.get_dynamic_turns_approximate_attack_against(city, maxTurns=threatAllowedTurns, asPlayer=self.target_player)

            approxDefTurns, approxDef = self.get_dynamic_turns_visible_defense_against(tiles=[city], maxTurns=threatAllowedTurns, asPlayer=self.map.player_index, minArmy=approxThreat)

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

        if not weAreSlightlyAhead:
            return False

        self.recommended_city_defense_plan_turns = maxThreatTurns

        couldLose = numRiskyCities > 0 and sortOfWinningEconCurrently and not wouldStillBeWinningIfLostRiskies

        return couldLose

    def get_approximate_attack_against(
            self,
            tiles: typing.List[Tile],
            inTurns: int,
            asPlayer: int,
            timeLimit: float = 0.005,
            forceFogRisk: bool = False,
            negativeTiles: typing.Set[Tile] | None = None,
            noLog: bool = False
    ) -> int:
        """
        Does NOT include the army ON the target tile.

        @param tiles:
        @param inTurns:
        @param asPlayer:
        @param timeLimit:
        @param forceFogRisk: If true, force a return of the fog risk
        @param negativeTiles:
        @param noLog:
        @return:
        """
        plan = self.get_approximate_attack_plan_against(
            tiles=tiles,
            inTurns=inTurns,
            asPlayer=asPlayer,
            timeLimit=timeLimit,
            forceFogRisk=forceFogRisk,
            negativeTiles=negativeTiles,
            noLog=noLog,
        )

        return plan.gathered_army

    def get_approximate_attack_plan_against(
            self,
            tiles: typing.List[Tile],
            inTurns: int,
            asPlayer: int,
            timeLimit: float = 0.005,
            forceFogRisk: bool = False,
            negativeTiles: typing.Set[Tile] | None = None,
            noLog: bool = False,
    ) -> Gather.GatherCapturePlan:
        """
        Does NOT include the army ON the target tile.

        @param tiles:
        @param inTurns:
        @param asPlayer:
        @param timeLimit:
        @param forceFogRisk: If true, force a return of the fog risk
        @param negativeTiles:
        @param noLog:
        @return:
        """
        if DebugHelper.IS_DEBUGGING:
            timeLimit *= 4
            timeLimit += 0.01

        if negativeTiles is None:
            negativeTiles = set(tiles)
        else:
            negativeTiles.update(tiles)

        bestPlan = []
        bestValue = 0
        bestFogRisk = 0

        value, usedTurns, gatherNodes = Gather.knapsack_depth_gather_with_values(
            self.map,
            tiles,
            inTurns - 1,
            negativeTiles=set(tiles),
            searchingPlayer=asPlayer,
            # skipFunc=lambda t, o: not t.visible,
            # viewInfo=self.viewInfo if self.info_render_gather_values else None,
            # skipTiles=skipTiles,
            distPriorityMap=self.board_analysis.intergeneral_analysis.bMap,
            # priorityTiles=priorityTiles,
            includeGatherTreeNodesThatGatherNegative=True,
            incrementBackward=False,
            useTrueValueGathered=True,
            cutoffTime=time.perf_counter() + timeLimit,
            shouldLog=False,
            fastMode=True,
            # priorityMatrix=priorityMatrix
        )

        fogVal = self.get_additional_fog_gather_risk(gatherNodes, asPlayer, inTurns, forceFogRisk=forceFogRisk)
        fogRiskValue = value + fogVal

        if fogRiskValue > bestValue:
            if not noLog:
                logbook.info(f'>> RAW gather attack {fogRiskValue} in {inTurns}, > best {bestValue}')
            bestValue = fogRiskValue
            bestPlan = gatherNodes
            bestFogRisk = fogVal
        elif not noLog:
            logbook.info(f'<  RAW gather attack {fogRiskValue} in {inTurns}, < best {bestValue}')

        prunedGatherTurns, prunedValue, prunedGatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
            GatherTreeNode.clone_nodes(gatherNodes),
            minArmy=1,
            searchingPlayer=asPlayer,
            teams=MapBase.get_teams_array(self.map),
            additionalIncrement=0,
            noLog=noLog,
            # preferPrune=self.expansion_plan.preferred_tiles if self.expansion_plan is not None else None
            )

        fogVal = self.get_additional_fog_gather_risk(prunedGatherNodes, asPlayer, inTurns, forceFogRisk=forceFogRisk)
        prunedFogRiskValue = prunedValue + fogVal

        if prunedFogRiskValue > bestValue:
            if not noLog:
                logbook.info(f'>> PRUNE + FOG gather attack {prunedFogRiskValue} in {inTurns}, > best {bestValue}')
            bestValue = prunedFogRiskValue
            bestPlan = prunedGatherNodes
            bestFogRisk = fogVal
        elif not noLog:
            logbook.info(f'<  PRUNE + FOG gather attack {prunedFogRiskValue} in {inTurns}, < best {bestValue}')

        attackPathRiskVal = 0
        maxAttack = self.get_best_attack_path_from_fog_by_army_per_turn(tiles, asPlayer, inTurns, negativeTiles=negativeTiles)
        if maxAttack is not None:
            attackPathRiskVal = maxAttack.value
            fakeGathNodes = [maxAttack.convert_to_tree_nodes(self.map, asPlayer)]
            addlRisk = self.get_additional_fog_gather_risk(fakeGathNodes, asPlayer, inTurns, forceFogRisk=forceFogRisk)
            attackPathRiskVal += addlRisk

            if attackPathRiskVal > bestValue:
                if not noLog:
                    logbook.info(f'>> PATH + FOG {attackPathRiskVal} in {inTurns}, > best {bestValue}')
                bestValue = attackPathRiskVal
                bestPlan = fakeGathNodes
                bestFogRisk = addlRisk
            elif not noLog:
                logbook.info(f'<  PATH + FOG {attackPathRiskVal} in {inTurns}, < best {bestValue}')
        elif not noLog:
            logbook.info(f'<  NO MAX PATH FOUND')

        if not noLog:
            logbook.info(f'concluded get_approximate_attack_against, value {fogRiskValue} or {prunedFogRiskValue} or {attackPathRiskVal}')

        plan = Gather.GatherCapturePlan.build_from_root_nodes(
            self.map,
            bestPlan,
            negativeTiles=negativeTiles,
            searchingPlayer=asPlayer,
            onlyCalculateFriendlyArmy=False,
            priorityMatrix=None,
            includeGatherPriorityAsEconValues=False,
            includeCapturePriorityAsEconValues=False,
            cloneNodes=False,
        )
        fogTurns = inTurns - plan.length
        if fogTurns > 0:
            plan.include_additional_fog_gather(fogTurns, bestFogRisk)

        return plan

    def get_dynamic_turns_visible_defense_against(
            self,
            tiles: typing.List[Tile],
            maxTurns: int,
            asPlayer: int,
            timeLimit: float = 0.05,
            minArmy: int = 1,
            negativeTiles: typing.Set[Tile] | None = None
    ) -> typing.Tuple[int, int]:
        """
        Max-value-per-turn known tile gather + fog option, or full gather minus fog option.
        Use for players you have full vision of, or when you do not want to include the players fogRisk army.

        returns turns, gatheredVal
        """
        plan = self.get_dynamic_turns_visible_defense_plan_against(
            tiles=tiles,
            maxTurns=maxTurns,
            asPlayer=asPlayer,
            timeLimit=timeLimit,
            minArmy=minArmy,
            negativeTiles=negativeTiles,
        )
        return plan.length, plan.gathered_army

    def get_dynamic_turns_visible_defense_plan_against(
            self,
            tiles: typing.List[Tile],
            maxTurns: int,
            asPlayer: int,
            timeLimit: float = 0.05,
            minArmy: int = 1,
            negativeTiles: typing.Set[Tile] | None = None
    ) -> Gather.GatherCapturePlan:
        """
        Max-value-per-turn known tile gather + fog option, or full gather minus fog option.
        Use for players you have full vision of, or when you do not want to include the players fogRisk army.

        returns turns, gatheredVal, gatheredNodes
        """
        if DebugHelper.IS_DEBUGGING:
            timeLimit *= 4

        negs = set([t for t in self.map.players[asPlayer].tiles if not t.visible])
        if negativeTiles is not None:
            negs.update(negativeTiles)

        value, usedTurns, gatherNodes = Gather.knapsack_depth_gather_with_values(
            self.map,
            tiles,
            maxTurns,
            negativeTiles=negs,
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
            prunedTurns, prunedValue, prunedNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                minArmy=minArmy,
                searchingPlayer=asPlayer,
                teams=MapBase.get_teams_array(self.map),
                # viewInfo=self.viewInfo if self.info_render_gather_values else None,
                allowBranchPrune=False
            )

            for tile in tiles:
                if self.map.is_tile_on_team_with(tile, asPlayer):
                    value += tile.army - 1

            logbook.info(f'concluded get_dynamic_visible_defense_against prune, value {prunedValue}')

            plan = Gather.GatherCapturePlan.build_from_root_nodes(
                self.map,
                prunedNodes,
                negativeTiles=negativeTiles,
                searchingPlayer=asPlayer,
                onlyCalculateFriendlyArmy=False,
                priorityMatrix=None,
                includeGatherPriorityAsEconValues=False,
                includeCapturePriorityAsEconValues=False,
                cloneNodes=False,
            )

            return plan

        logbook.info(f'concluded get_dynamic_visible_defense_against zeros')
        return Gather.GatherCapturePlan(
            [],
            self.map,
            econValue=0.0,
            turnsTotalInclCap=0,
            gatherValue=0,
            gatherCapturePoints=0.0,
            gatherTurns=0,
            requiredDelay=0,
            friendlyCityCount=0,
            enemyCityCount=0,
        )

    def get_dynamic_turns_approximate_attack_against(
            self,
            tile: Tile,
            maxTurns: int,
            asPlayer: int,
            timeLimit: float = 0.005
    ) -> typing.Tuple[int, int]:
        """
        Max-value-per-turn known tile gather + fog option, or full gather minus fog option.
        Use for fog players attacking things, as well as attacking as visible / friendly players.

        returns turns, attackValue
        @param tile:
        @param maxTurns:
        @param asPlayer:
        @param timeLimit:
        @return:
        """

        plan = self.get_dynamic_turns_approximate_attack_plan_against(
            tile=tile,
            maxTurns=maxTurns,
            asPlayer=asPlayer,
            timeLimit=timeLimit,
        )

        return plan.length, plan.gathered_army

    def get_dynamic_turns_approximate_attack_plan_against(
            self,
            tile: Tile,
            maxTurns: int,
            asPlayer: int,
            timeLimit: float = 0.005,
            negativeTiles: TileSet | None = None,
            minTurns: int = 0
    ) -> Gather.GatherCapturePlan:
        """
        returns gather capture plan.
        Max-value-per-turn known tile gather + fog option.
        Use for fog players attacking things, as well as attacking as visible / friendly players.

        @param tile:
        @param maxTurns:
        @param asPlayer:
        @param timeLimit:
        @param minTurns:
        @param negativeTiles:

        @return: turns, attackValue, nodes
        """
        curTiles = [tile]
        if DebugHelper.IS_DEBUGGING:
            timeLimit *= 4

        value, usedTurns, gatherNodes = Gather.knapsack_depth_gather_with_values(
            self.map,
            curTiles,
            maxTurns,
            negativeTiles=negativeTiles,
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

        attackVal = value
        playerHasFog = not self.map.is_player_on_team_with(self.map.player_index, asPlayer)

        logbook.info(f'get_dynamic_attack_against {tile} gather for total {attackVal}, raw gather {value}')

        finalTurns: int = 0
        finalAttack: int = 0
        finalFogRisk: int = 0
        finalNodes = []

        if attackVal > 0:
            prunedTurns, prunedValue, prunedNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                [g.deep_clone() for g in gatherNodes],
                minArmy=1,
                searchingPlayer=asPlayer,
                teams=MapBase.get_teams_array(self.map),
                minTurns=minTurns,
                noLog=True,
                allowNegative=False,
                # viewInfo=self.viewInfo if self.info_render_gather_values else None,
                allowBranchPrune=False
            )

            pruneFogRisk = 0
            if playerHasFog:
                pruneFogRisk = self.get_additional_fog_gather_risk(prunedNodes, asPlayer, prunedTurns)
                prunedValue += pruneFogRisk
            attackPruned = prunedValue + pruneFogRisk
            logbook.info(f'concluded get_dynamic_attack_against prune {tile} gather turns {prunedTurns} for total {attackPruned}, pruned gather {prunedValue}, pruneFogRisk {pruneFogRisk}')

            if prunedTurns > 0 and attackPruned / prunedTurns > attackVal / maxTurns:
                finalTurns, finalAttack, finalNodes = prunedTurns, max(0, attackPruned), prunedNodes
                finalFogRisk = pruneFogRisk
            else:
                logbook.error(f'Prune wasnt the max value per turn...?')
                finalTurns, finalAttack, finalNodes = maxTurns, max(0, attackVal), gatherNodes
        else:
            logbook.info(f'concluded get_dynamic_attack_against, zeros')

        plan = Gather.GatherCapturePlan.build_from_root_nodes(
            self.map,
            finalNodes,
            negativeTiles=negativeTiles,
            searchingPlayer=asPlayer,
            onlyCalculateFriendlyArmy=False,
            priorityMatrix=None,
            includeGatherPriorityAsEconValues=False,
            includeCapturePriorityAsEconValues=False,
            cloneNodes=False,
        )

        fogTurns = finalTurns - plan.length
        if fogTurns > 0:
            plan.include_additional_fog_gather(fogTurns, finalFogRisk)

        return plan

    def get_dynamic_approximate_attack_defense(
            self,
            tile: Tile,
            negativeTiles: TileSet,
            minTurns: int = 0,
            maxTurns: int = 35,
            attackingPlayer: int = -1,
            defendingPlayer: int = -1,
            noLog: bool = False
    ) -> typing.Tuple[int, int, int]:
        """
        returns foundTurns, approxAttack, approxDef

        @param tile: The tile to attack
        @param negativeTiles: negative tiles in the attack (but not the defense)
        @param minTurns: The minimum number of turns allowed
        @param maxTurns: The maximum number of turns allowed.
        @param attackingPlayer:
        @param defendingPlayer:
        @param noLog: if False, do not log.
        @return:
        """

        attackPlan, defPlan = self.get_dynamic_approximate_attack_defense_plans(
            tile=tile,
            negativeTiles=negativeTiles,
            minTurns=minTurns,
            maxTurns=maxTurns,
            attackingPlayer=attackingPlayer,
            defendingPlayer=defendingPlayer,
            noLog=noLog,
        )

        return attackPlan.length, attackPlan.gathered_army, defPlan.gathered_army

    def get_dynamic_approximate_attack_defense_plans(
            self,
            tile: Tile,
            negativeTiles: TileSet,
            minTurns: int = 0,
            maxTurns: int = 35,
            attackingPlayer: int = -1,
            defendingPlayer: int = -1,
            noLog: bool = False
    ) -> typing.Tuple[Gather.GatherCapturePlan, Gather.GatherCapturePlan]:
        """
        returns attackPlan, defensePlan

        @param tile: The tile to attack
        @param negativeTiles: negative tiles in the attack (but not the defense)
        @param minTurns: The minimum number of turns allowed
        @param maxTurns: The maximum number of turns allowed.
        @param attackingPlayer:
        @param defendingPlayer:
        @param noLog: if False, do not log.
        @return:
        """

        if attackingPlayer == -1:
            attackingPlayer = self.map.player_index
        if defendingPlayer == -1:
            defendingPlayer = tile.player

        attackPlan = self.get_dynamic_turns_approximate_attack_plan_against(
            tile,
            maxTurns,
            attackingPlayer,
            0.005,
            negativeTiles=negativeTiles,
            minTurns=minTurns,
        )

        defensePlan = self.get_approximate_attack_plan_against(
            [tile],
            attackPlan.length,
            defendingPlayer,
            0.005,
            forceFogRisk=False,
            negativeTiles=None,
            noLog=True,
        )

        curDiff = attackPlan.gathered_army - defensePlan.gathered_army
        if not noLog:
            logbook.info(f'atk/def @{tile}: diff {curDiff} in {attackPlan.length}t (attack {attackPlan.gathered_army}, def {defensePlan.gathered_army}')

        return attackPlan, defensePlan

    def is_city_forward_relative_to_central_point(self, city: Tile, offset: int = 3):
        if self.board_analysis.central_defense_point is None:
            return True

        if self.get_tile_dist_to_enemy(city) + offset < self.get_tile_dist_to_enemy(self.board_analysis.central_defense_point):
            return True

        return False

    def get_tile_dist_to_enemy(self, tile: Tile) -> int:
        return self.board_analysis.intergeneral_analysis.bMap[tile]

    def get_additional_fog_gather_risk(self, gatherNodes: typing.List[GatherTreeNode], asPlayer: int, inTurns: int, forceFogRisk: bool = False) -> int:
        """

        @param gatherNodes:
        @param asPlayer:
        @param inTurns:
        @param forceFogRisk:
        @return:
        """
        if self.map.is_player_on_team_with(asPlayer, self.map.player_index):
            return 0

        numFogTiles = SearchUtils.Counter(0)

        fogValue = SearchUtils.Counter(0)

        for node in GatherTreeNode.iterate_tree_nodes(gatherNodes):
            if node.tile.visible:
                continue

            numFogTiles.value += 1
            if self.map.is_player_on_team_with(node.tile.player, asPlayer):
                fogValue.value += node.tile.army - 1
            else:
                fogValue.value -= node.tile.army + 1

        turnsUsed = 0
        for t in gatherNodes:
            turnsUsed += t.gatherTurns

        # if their gather doesn't hit the fog, or they didn't gather at all, we can't include fog in this plan. :)
        if turnsUsed == 0 or numFogTiles.value == 0:
            return 0

        turnsLeft = inTurns - turnsUsed

        result = self.opponent_tracker.get_approximate_fog_army_risk(asPlayer, inTurns=turnsLeft) - fogValue.value
        distPenalty = max(0, 8 - turnsLeft)
        logbook.info(f'get_additional_fog_gather_risk fogValue {fogValue.value}, numFogTiles {numFogTiles.value}, inTurns {turnsLeft} ({turnsUsed} used for attack of {inTurns}), result {result}')
        if numFogTiles.value > inTurns // 7 + 1:
            return max(0, result - distPenalty)

        if forceFogRisk:
            if numFogTiles.value > 0:
                return max(0, result - distPenalty)

            # TODO this is very wrong; rough approximation of the cost to go through our territory. In reality we should use the worst case flank path, instead.
            return max(0, result - 10 - distPenalty)

        return 0

    def get_economic_diff_against_target_player(self, cyclesAgo: int = 0) -> int:
        """
        Negative means we are losing. Positive means we are winning.

        By emptyVal, returns the economic diff RIGHT NOW. If cyclesAgo > 0, checks that many cycles ago (where 1 means the start of this cycle).

        @param cyclesAgo:
        @return:
        """

        enStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.target_player)
        frStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.map.player_index)

        enScore = self.opponent_tracker.get_current_team_scores_by_player(self.target_player)
        frScore = self.opponent_tracker.get_current_team_scores_by_player(self.map.player_index)

        if cyclesAgo > 0:
            enStats = self.opponent_tracker.get_last_cycle_stats_by_player(self.target_player, cyclesToGoBack=cyclesAgo - 1)
            frStats = self.opponent_tracker.get_last_cycle_stats_by_player(self.map.player_index, cyclesToGoBack=cyclesAgo - 1)

            enScore = self.opponent_tracker.get_last_cycle_score_by_player(self.target_player, cyclesToGoBack=cyclesAgo - 1)
            frScore = self.opponent_tracker.get_last_cycle_score_by_player(self.map.player_index, cyclesToGoBack=cyclesAgo - 1)

        frEcon = frScore.tileCount + (frScore.cityCount - frStats.cities_gained) * 25
        enEcon = enScore.tileCount + (enScore.cityCount - enStats.cities_gained) * 25

        return frEcon - enEcon

    def get_best_attack_path_from_fog_by_army_per_turn(self, tiles: typing.List[Tile], asPlayer: int, inTurns: int, negativeTiles: typing.Set[Tile] | None) -> Path | None:
        if negativeTiles is None:
            negativeTiles = set()
        negativeTiles.update(tiles)

        def valueFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if not tile in self.board_analysis.flankable_fog_area_matrix:
                return None
            if tile.visible:
                return None
            if tile.player != asPlayer:
                return None

            depth, negArmySum = prioVals
            if depth == 0:
                return None
            if negArmySum > 0:
                return 0 - negArmySum
            else:
                return (0 - negArmySum) / depth

        def prioFunc(nextTile: Tile, prioVals) -> typing.Tuple | None:
            depth, negArmySum = prioVals

            if (negativeTiles is None or nextTile not in negativeTiles) and nextTile.visible:
                if self.map.is_player_on_team_with(nextTile.player, asPlayer):
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            # always leaving 1 army behind. + because this is negative.
            negArmySum += 1

            return depth + 1, negArmySum

        startTiles = {}
        for tile in tiles:
            startTiles[tile] = ((0, 0), 0)

        logbook.info(f'Looking for max path to fog from {str(tiles)}')
        path = SearchUtils.breadth_first_dynamic_max(
            self.map,
            startTiles,
            # goalFunc=lambda tile, armyAmt, dist: armyAmt + tile.army > 0 and tile in self.player_targets,  # + tile.army so that we find paths that reach tiles regardless of killing them.
            valueFunc=valueFunc,
            priorityFunc=prioFunc,
            negativeTiles=negativeTiles,
            # skipTiles=skip,
            maxTime=0.1,
            maxDepth=inTurns,
            noNeutralCities=True,
            searchingPlayer=asPlayer,
            noLog=True)

        if path is not None:
            return path.get_reversed()
        return None

    def _get_rough_offense(self):
        attackTime = min(self.map.remainingCycleTurns, self.board_analysis.inter_general_distance + 5)
        self.our_best_attack_plan = None

        if self.target_player_location is not None and not self.target_player_location.isObstacle:
            self.our_best_attack_plan = self.get_dynamic_turns_approximate_attack_plan_against(self.target_player_location, maxTurns=attackTime, asPlayer=self.map.player_index)
            if self.our_best_attack_plan:
                attackTime = self.our_best_attack_plan.gather_turns

        self.recommended_offense_plan_turns = attackTime
