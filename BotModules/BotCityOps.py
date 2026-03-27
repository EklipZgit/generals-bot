import typing

import Gather
import logbook

import SearchUtils
from BotModules.BotRendering import BotRendering
from DangerAnalyzer import ThreatType
from Gather import GatherTreeNode
from MoveListPath import MoveListPath
from Path import Path
from Strategy.WinConditionAnalyzer import WinCondition
from StrategyModels import ExpansionPotential
from ViewInfo import TargetStyle, PathColorer
from base.client.map import Move, Player, Tile, MapBase


class BotCityOps:
    @staticmethod
    def capture_cities(
            bot,
            negativeTiles: typing.Set[Tile],
            forceNeutralCapture: bool = False,
    ) -> typing.Tuple[Path | None, Move | None]:
        negativeTiles = negativeTiles.copy()
        if bot.is_all_in() and not bot.all_in_city_behind:
            return None, None
        logbook.info(f"------------\n     CAPTURE_CITIES (force_city_take {bot.force_city_take}), negative_tiles {str(negativeTiles)}\n--------------")
        genDist = min(30, bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation))
        killSearchDist = max(4, int(genDist * 0.2))
        isNeutCity = False

        wasCityAllIn = bot.all_in_city_behind

        with bot.perf_timer.begin_move_event('Build City Analyzer'):
            tileScores = bot.cityAnalyzer.get_sorted_neutral_scores()
            enemyTileScores = bot.cityAnalyzer.get_sorted_enemy_scores()

            if bot.info_render_city_priority_debug_info:
                for i, ts in enumerate(tileScores):
                    tile, cityScore = ts
                    bot.viewInfo.midLeftGridText[tile] = f'c{i}'
                    BotRendering.add_city_score_to_view_info(cityScore, bot.viewInfo)

                for i, ts in enumerate(enemyTileScores):
                    tile, cityScore = ts
                    bot.viewInfo.midLeftGridText[tile] = f'm{i}'
                    BotRendering.add_city_score_to_view_info(cityScore, bot.viewInfo)

        rapidCityPath = bot.find_rapid_city_path()
        if rapidCityPath is not None:
            return rapidCityPath, None

        with bot.perf_timer.begin_move_event('finding neutral city path'):
            neutPath = bot.find_neutral_city_path()

        desiredGatherTurns = -1
        with bot.perf_timer.begin_move_event('Find Enemy City Path'):
            desiredGatherTurns, path = bot.find_enemy_city_path(negativeTiles=set(bot.win_condition_analyzer.defend_cities), force=neutPath is None)

        if path:
            logbook.info(f"   find_enemy_city_path returned {str(path)}")
        else:
            logbook.info("   find_enemy_city_path returned None.")
        player = bot._map.players[bot.general.player]
        largestTile = bot.general
        for tile in player.tiles:
            if tile.army > largestTile.army:
                largestTile = tile

        mustContestEnemy = False
        if path is not None:
            enCity = path.tail.tile
            if not bot.territories.is_tile_in_enemy_territory(enCity) and enCity.discovered:
                logbook.info(f'MUST CONTEST ENEMY CITY {str(enCity)}')
                mustContestEnemy = True

        ourCityCounts = bot._map.players[bot.general.player].cityCount
        if bot.teammate_general is not None:
            ourCityCounts += bot._map.players[bot.teammate_general.player].cityCount

        if bot._map.is_2v2 and bot._map.remainingPlayers == 3 and bot.targetPlayerObj.cityCount <= ourCityCounts:
            mustContestEnemy = True

        shouldAllowNeutralCapture = bot.should_allow_neutral_city_capture(
            genPlayer=player,
            forceNeutralCapture=forceNeutralCapture,
            targetCity=neutPath.tail.tile if neutPath is not None else None
        )

        contestMove = None
        contestGatherVal = 0
        contestGatherTurns = 100
        contestGatherNodes = None
        if WinCondition.ContestEnemyCity in bot.win_condition_analyzer.viable_win_conditions and shouldAllowNeutralCapture:
            with bot.perf_timer.begin_move_event(f'Contest Offensive all-in move'):
                contestMove, contestGatherVal, contestGatherTurns, contestGatherNodes = bot.get_city_contestation_all_in_move(defenseCriticalTileSet=negativeTiles)
            if contestMove is not None:
                return None, contestMove

        if not mustContestEnemy and shouldAllowNeutralCapture:
            if neutPath and (bot.targetPlayer == -1 or path is None or neutPath.length < path.length / 4):
                logbook.info(f"Targeting neutral city {str(neutPath.tail.tile)}")
                path = neutPath
                isNeutCity = True

        if path is None:
            logbook.info(f"xxxxxxxxx\n  xxxxx\n    NO ENEMY CITY FOUND or Neutral city prioritized??? mustContestEnemy {mustContestEnemy} shouldAllowNeutralCapture {shouldAllowNeutralCapture} forceNeutralCapture {forceNeutralCapture}\n  xxxxx\nxxxxxxxx")

            downOnCities = not bot.opponent_tracker.even_or_up_on_cities(bot.targetPlayer)
            if downOnCities:
                cycleTurn = bot.timings.get_turn_in_cycle(bot._map.turn)

                cityHuntTurns = 10
                if cycleTurn < cityHuntTurns and not bot.are_more_teams_alive_than(2) and shouldAllowNeutralCapture:
                    with bot.perf_timer.begin_move_event('fog neut city hunt'):
                        revealPath, move = bot.hunt_for_fog_neutral_city(negativeTiles, maxTurns=cycleTurn % cityHuntTurns)
                    if move is not None or revealPath is not None:
                        bot.info('hunting fog neutral city')
                        return revealPath, move

                if not bot.all_in_city_behind:
                    if cycleTurn < 5:
                        bot.send_teammate_communication("Going all in due to lack of cities, attacking end of cycle", bot.targetPlayerExpectedGeneralLocation)
                        bot.info(f'Going all in, down on cities and no city path found.')
                        bot.is_all_in_army_advantage = True
                        bot.is_all_in_losing = True
                        bot.all_in_city_behind = True
                        bot.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0)
                        bot.city_expand_plan = None
                        bot.enemy_expansion_plan = None

                        bot.set_all_in_cycle_to_hit_with_current_timings(50, bufferTurnsEndOfCycle=5)

            bot.all_in_city_behind = False

            return None, None

        if bot.all_in_city_behind:
            bot.send_teammate_communication("Ceasing all-in, hold", bot.locked_launch_point)
            bot.all_in_city_behind = False
            bot.is_all_in_army_advantage = False
            bot.is_all_in_losing = False
            bot.all_in_army_advantage_counter = 0

        target = path.tail.tile
        if player.standingArmy + 5 <= target.army:
            return None, None

        enemyArmyNearDist = 3
        enemyArmyNear = bot.sum_enemy_army_near_tile(target, enemyArmyNearDist)
        captureNegs = negativeTiles
        if enemyArmyNear > 0:
            captureNegs = captureNegs.copy()
            tgPlayer = target.player
            if tgPlayer == -1:
                tgPlayer = bot.targetPlayer
            killNegs = bot.find_large_tiles_near([target], enemyArmyNearDist, forPlayer=tgPlayer, limit=30, minArmy=1)
            for t in killNegs:
                if t != target:
                    captureNegs.add(t)

        targetArmy = enemyArmyNear

        if not isNeutCity and not bot._map.is_player_on_team_with(bot.territories.territoryMap[target], bot.general.player):
            targetArmy = max(2, int(bot.sum_enemy_army_near_tile(target, 2) * 1.1))
        else:
            killSearchDist = 3
            if wasCityAllIn:
                targetArmy += 5

        targetArmyGather = target.army + targetArmy

        logbook.info(
            f"xxxxxxxxx\n    SEARCHED AND FOUND NEAREST NEUTRAL / ENEMY CITY {target.x},{target.y} dist {path.length}. Searching {targetArmy} army searchDist {killSearchDist}\nxxxxxxxx")
        if path.length > 1 and path.tail.tile.player == -1:
            path = path.get_subsegment(path.length - 1)
        if path.length > 2:
            path = path.get_subsegment(2, end=True)

        if target.player >= 0:
            path = None

        allowGather = False
        gatherDuration = desiredGatherTurns
        if desiredGatherTurns == -1:
            gatherDuration = 20
            if not target.isNeutral:
                gatherDuration = 20
            elif player.tileCount > 125:
                gatherDuration = 10

            if bot._map.is_walled_city_game:
                gatherDuration += 5
            if len(bot._map.tiles_by_index) > 400:
                gatherDuration += 5
            if len(bot._map.tiles_by_index) > 800:
                gatherDuration += 5
            if len(bot._map.tiles_by_index) > 1200:
                gatherDuration += 5
            if len(bot._map.tiles_by_index) > 1600:
                gatherDuration += 5
            if target.army > 50:
                gatherDuration += 5

        winningOnArmy = bot.opponent_tracker.winning_on_army()
        inGathSplit = bot.timings.in_gather_split(bot._map.turn) or bot.timings.in_quick_expand_split(bot._map.turn)
        evenOrUpOnCities = bot.opponent_tracker.even_or_up_on_cities(bot.targetPlayer)
        longSpawns = genDist > 22
        targetCityIsEn = target.player >= 0
        if (winningOnArmy
                or inGathSplit
                or not evenOrUpOnCities
                or longSpawns
                or targetCityIsEn):
            allowGather = True

        bot.city_capture_plan_tiles = set()
        capturePath, move = bot.plan_city_capture(
            target,
            path,
            allowGather=allowGather,
            targetKillArmy=targetArmy,
            targetGatherArmy=targetArmyGather,
            killSearchDist=killSearchDist,
            gatherMaxDuration=gatherDuration,
            gatherMinDuration=max(0, desiredGatherTurns - 5),
            negativeTiles=captureNegs)

        if capturePath is None and move is None:
            logbook.info(
                f"xxxxxxxxx\n  xxxxx\n    GATHERING TO CITY FAILED :( {target.x},{target.y} \n  xxxxx\nxxxxxxxx")
        elif target.player >= 0:
            bot.send_teammate_communication("Lets hold this city", target, cooldown=10)
        else:
            bot.send_teammate_communication("Planning to take a city.", target, cooldown=15)

        return capturePath, move

    @staticmethod
    def should_proactively_take_cities(bot):
        dist = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation)
        if bot.targetPlayer != -1:
            if len(bot.targetPlayerObj.tiles) == 0 and bot._map.is_walled_city_game and dist > 20:
                return True

        if bot.defend_economy:
            logbook.info("No proactive cities because defending economy :)")
            return False

        cityLeadWeight = 0
        dist = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation)
        if bot.targetPlayer != -1:
            opp = bot._map.players[bot.targetPlayer]
            me = bot._map.players[bot.general.player]
            cityLeadWeight = (me.cityCount - opp.cityCount) * 70

        knowsWhereEnemyGenIs = bot.targetPlayer != -1 and bot._map.generals[bot.targetPlayer] is not None
        if knowsWhereEnemyGenIs and dist < 18:
            logbook.info("Not proactively taking neutral cities because we know enemy general location and map distance isn't incredibly short")
            return False

        player = bot._map.players[bot.general.player]
        targetPlayer = None
        if bot.targetPlayer != -1:
            targetPlayer = bot._map.players[bot.targetPlayer]
        safeOnStandingArmy = targetPlayer is None or player.standingArmy > targetPlayer.standingArmy * 0.9
        if (safeOnStandingArmy and ((player.standingArmy > cityLeadWeight and (bot.target_player_gather_path is None or dist > 24))
                                    or (player.standingArmy > 30 + cityLeadWeight and (bot.target_player_gather_path is None or dist > 22))
                                    or (player.standingArmy > 40 + cityLeadWeight and (bot.target_player_gather_path is None or dist > 20))
                                    or (player.standingArmy > 60 + cityLeadWeight and (bot.target_player_gather_path is None or dist > 18))
                                    or (player.standingArmy > 70 + cityLeadWeight and (bot.target_player_gather_path is None or dist > 16))
                                    or (player.standingArmy > 100 + cityLeadWeight))):
            logbook.info(f"Proactively taking cities! dist {dist}, safe {safeOnStandingArmy}, player.standingArmy {player.standingArmy}, cityLeadWeight {cityLeadWeight}")
            return True
        logbook.info(f"No proactive cities :(     dist {dist}, safe {safeOnStandingArmy}, player.standingArmy {player.standingArmy}, cityLeadWeight {cityLeadWeight}")
        return False

    @staticmethod
    def find_neutral_city_path(bot) -> Path | None:
        is1v1 = bot._map.remainingPlayers == 2 or bot._map.is_2v2
        wayAheadOnEcon = bot.opponent_tracker.winning_on_economy(byRatio=1.15, cityValue=40, offset=-5)
        isNotLateGame = bot._map.turn < 500

        isWalledNoAggression = bot._map.is_walled_city_game and (bot.targetPlayer == -1 or bot._map.players[bot.targetPlayer].aggression_factor == 0.0)

        if not isWalledNoAggression:
            if is1v1 and wayAheadOnEcon and isNotLateGame or len(bot.win_condition_analyzer.contestable_cities) > 0:
                return None

            if bot.is_still_ffa_and_non_dominant() and bot.targetPlayer != -1 and bot.targetPlayerObj.aggression_factor > 30:
                return None

            if bot.defend_economy and (bot.targetPlayer == -1 or bot.opponent_tracker.even_or_up_on_cities(bot.targetPlayer)):
                return None

        relevanceCutoff = 0.15 * (16 / max(1, bot.board_analysis.inter_general_distance))
        distRatioThreshNormal = 0.95
        distRatioThreshEnVisionFewCities = 0.35
        distRatioThreshEnVisionLotsOfCities = 0.6
        if bot.opponent_tracker.winning_on_army(offset=-40):
            distRatioThreshEnVisionFewCities = 0.55
            distRatioThreshEnVisionLotsOfCities = 0.8
            relevanceCutoff = 0.10 * (15 / max(1, bot.board_analysis.inter_general_distance))

        logbook.info(
            f'looking for neut city with thresholds relevanceCutoff {relevanceCutoff:.2f}, distRatioThreshNormal {distRatioThreshNormal:.2f}, distRatioThreshEnVisionFewCities {distRatioThreshEnVisionFewCities:.2f}, distRatioThreshEnVisionLotsOfCities {distRatioThreshEnVisionLotsOfCities:.2f}')
        citiesByDist = [c for c in sorted(bot.cityAnalyzer.city_scores.keys(), key=lambda c2: (10 + bot.board_analysis.intergeneral_analysis.aMap.raw[c2.tile_index]) * max(1, c2.army + bot.cityAnalyzer.reachability_costs_matrix.raw[c2.tile_index]))]

        baseLimit = 8
        territoryDistCutoff = max(2, bot.shortest_path_to_target_player.length // 6)

        path: Path | None = None
        targetCity = None
        maxScore = None
        maxScoreNeutVal = -100000.0
        obstacleDict = {}
        toCheck = citiesByDist[:baseLimit]
        i = 0
        toCheckIncluded = set(toCheck)
        while i < len(toCheck):
            city = toCheck[i]
            score = bot.cityAnalyzer.city_scores.get(city, None)
            scoreVal = 0.0
            tryPath = False
            if score is None:
                bot.info(f'WHOAH, obstacle {city} had no city score...')
                tryPath = True
                scoreVal = max(10, city.army) / obstacleDict.get(city, 1)
                bot.mark_tile(city, alpha=150)
            else:
                enemyVision = [tile for tile in filter(lambda t: bot._map.is_tile_enemy(t), city.adjacents)]
                cityDistanceRatioThresh = distRatioThreshNormal
                if len(enemyVision) > 0:
                    if bot.player.cityCount < 4:
                        cityDistanceRatioThresh = distRatioThreshEnVisionFewCities
                    else:
                        cityDistanceRatioThresh = distRatioThreshEnVisionLotsOfCities

                inSafePocket = bot.territories.territoryDistances[bot.targetPlayer][city] > territoryDistCutoff
                inSafePocket = inSafePocket and not SearchUtils.any_where(city.adjacents, lambda a: a in bot.armyTracker.tiles_ever_owned_by_player[bot.targetPlayer])
                inSafePocket = inSafePocket or bot.territories.territoryDistances[bot.targetPlayer][city] > bot.shortest_path_to_target_player.length // 4

                bonus = 4 + obstacleDict.get(city, 0)
                baseScore = score.get_weighted_neutral_value()
                scoreVal = baseScore * bonus

                tryPath = (
                        (maxScoreNeutVal < scoreVal)
                        and (score.general_distances_ratio < cityDistanceRatioThresh or inSafePocket)
                        and (score.city_relevance_score > relevanceCutoff)
                        or city in obstacleDict
                )
                if tryPath:
                    bot.mark_tile(city, alpha=50)
                    bot.info(f'Trying city {city}, bonus {bonus}, score {baseScore:.1f} (*bonus {scoreVal:.1f})')
            if tryPath:
                path = bot.get_path_to_targets(
                    [t for t in city.movable if not t.isObstacle],
                    maxDepth=bot.distance_from_general(city) + 5,
                    skipNeutralCities=False,
                    preferNeutral=False,
                    preferEnemy=False,
                )
                if path is not None:
                    maxScore = score
                    targetCity = city
                    maxScoreNeutVal = scoreVal
                else:
                    for tile, hits in obstacleDict.items():
                        if hits > 0 and len(toCheck) < baseLimit + 4 and tile not in toCheckIncluded:
                            toCheck.append(tile)
                            toCheckIncluded.add(tile)
            i += 1

        if targetCity is not None:
            logbook.info(
                f"Found a neutral city, closest to me and furthest from enemy. Chose city {str(targetCity)} with rating {maxScoreNeutVal}")

            if path is not None:
                path.add_next(targetCity)
            logbook.info(f"    path {str(path)}")
        else:
            logbook.info(f"{bot.get_elapsed()} No neutral city found...")

        return path

    @staticmethod
    def _check_should_wait_city_capture(bot) -> typing.Tuple[Path | None, bool]:
        generalArmy = bot.general.army
        for city, score in sorted(bot.cityAnalyzer.city_scores.items(), key=lambda tup: bot.distance_from_general(tup[0]))[:10]:
            qk = SearchUtils.dest_breadth_first_target(bot._map, [city], preferCapture=True, noNeutralCities=False)
            if qk:
                return qk, False
            if city.army + bot.distance_from_general(city) < generalArmy + 30 - bot._map.turn:
                return None, True

        return None, False

    @staticmethod
    def did_player_just_take_fog_city(bot, player: int) -> bool:
        playerObj = bot._map.players[player]
        if playerObj.unexplainedTileDelta == 0:
            return False
        unexplainedScoreDelta = bot.opponent_tracker.get_team_annihilated_fog_by_player(player)
        if unexplainedScoreDelta < 3:
            return False
        if playerObj.cityGainedTurn == bot._map.turn:
            return True

        return False

    @staticmethod
    def get_enemy_cities_by_priority(bot, cutoffDistanceRatio=100.0) -> typing.List:
        prioTiles = []
        if bot.dangerAnalyzer.fastestThreat is not None:
            if bot.dangerAnalyzer.fastestThreat.path.start.tile.isCity:
                prioTiles.append(bot.dangerAnalyzer.fastestThreat.path.start.tile)

        if bot.dangerAnalyzer.fastestPotentialThreat is not None and bot.dangerAnalyzer.fastestPotentialThreat.path.start.tile not in prioTiles:
            if bot.dangerAnalyzer.fastestPotentialThreat.path.start.tile.isCity:
                prioTiles.append(bot.dangerAnalyzer.fastestPotentialThreat.path.start.tile)

        if bot.dangerAnalyzer.fastestAllyThreat is not None and bot.dangerAnalyzer.fastestAllyThreat.path.start.tile not in prioTiles:
            if bot.dangerAnalyzer.fastestAllyThreat.path.start.tile.isCity:
                prioTiles.append(bot.dangerAnalyzer.fastestAllyThreat.path.start.tile)

        if bot.dangerAnalyzer.fastestCityThreat is not None and bot.dangerAnalyzer.fastestCityThreat.path.start.tile not in prioTiles:
            if bot.dangerAnalyzer.fastestCityThreat.path.start.tile.isCity:
                prioTiles.append(bot.dangerAnalyzer.fastestCityThreat.path.start.tile)

        tiles = [s for s, score in bot.cityAnalyzer.get_sorted_enemy_scores() if s not in prioTiles and score.general_distances_ratio < cutoffDistanceRatio]

        prioTiles.extend(tiles)
        return prioTiles

    @staticmethod
    def get_quick_kill_on_enemy_cities(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Path | None:
        foundCap = None
        enemyCitiesOrderedByPriority = bot.get_enemy_cities_by_priority()
        for enemyCity in enemyCitiesOrderedByPriority:
            enMovedNear = False
            cap = None
            for movable in enemyCity.movableNoObstacles:
                if movable.player == enemyCity.player and movable.lastMovedTurn > bot._map.turn - 2 and movable.delta.toTile != enemyCity:
                    enMovedNear = True
                    break
                if movable.player == bot.general.player and movable.army > enemyCity.army + 1 and movable not in defenseCriticalTileSet and (cap is None or cap.start.tile.army > movable.army):
                    cap = Path()
                    cap.add_next(movable)
                    cap.add_next(enemyCity)

            if not enMovedNear and cap and (foundCap is None or foundCap.start.tile.army > cap.start.tile.army):
                foundCap = cap

        if foundCap:
            bot.info(f'returning 1-move-city-kill {foundCap}')
            return foundCap

        if bot.opponent_tracker.winning_on_economy(byRatio=1.5, cityValue=50):
            return None

        negCutoff = 0 - bot.player.standingArmy // 40
        highValueNegs = [t for t in bot.cityAnalyzer.large_neutral_negatives if t.army < negCutoff]
        if len(highValueNegs) > 0:
            killPath = SearchUtils.dest_breadth_first_target(
                bot._map,
                highValueNegs,
                1,
                0.1,
                25,
                negativeTiles=None,
                preferCapture=True,
                searchingPlayer=bot.general.player,
                dontEvacCities=False,
                additionalIncrement=0,
                noLog=True
            )
            if killPath is not None:
                bot.info(f'returning bulk free-army {killPath}')
                return killPath
        possibleNeutralCities = []
        possibleNeutralCities.extend(c for c in bot.cityAnalyzer.city_scores.keys() if
                                 not bot.territories.is_tile_in_enemy_territory(c) and (
                                         (c.army < 4 and bot.territories.territoryDistances[bot.targetPlayer].raw[c.tile_index] > 3)
                                         or (c.army < 20 and bot.territories.territoryDistances[bot.targetPlayer].raw[c.tile_index] > 9)
                                         or (bot._map.is_walled_city_game and not bot.armyTracker.seen_player_lookup[bot.targetPlayer])))

        if len(possibleNeutralCities) > 0:
            killPath = SearchUtils.dest_breadth_first_target(
                bot._map,
                possibleNeutralCities,
                1,
                0.1,
                8,
                negativeTiles=None,
                preferCapture=True,
                searchingPlayer=bot.general.player,
                dontEvacCities=False,
                additionalIncrement=0,
                noLog=True
            )
            if killPath is not None:
                bot.info(f'returning bulk neut low cost city kill {killPath}')
                return killPath

        tileCountRatio = bot._map.players[bot.general.player].tileCount ** 0.30
        cityDepthCutoffEnTerritory = max(5, int(tileCountRatio))

        singleQuick = SearchUtils.dest_breadth_first_target(
                bot._map,
                enemyCitiesOrderedByPriority,
                1.5,
                0.1,
                3,
                negativeTiles=None,
                preferCapture=True,
                searchingPlayer=bot.general.player,
                dontEvacCities=False,
                additionalIncrement=0,
                noLog=True
            )
        if not singleQuick:
            singleQuick = SearchUtils.dest_breadth_first_target(
                    bot._map,
                    enemyCitiesOrderedByPriority,
                    3.5,
                    0.1,
                    7,
                    negativeTiles=None,
                    preferCapture=True,
                    searchingPlayer=bot.general.player,
                    dontEvacCities=False,
                    additionalIncrement=0.5,
                    noLog=True
                )

        if singleQuick:
            bestDef = bot.get_best_defense(singleQuick.tail.tile, singleQuick.length - 1, list())
            if bestDef is not None and bestDef.value > singleQuick.value:
                bot.viewInfo.color_path(PathColorer(
                    bestDef,
                    175, 30, 0, alpha=150, alphaDecreaseRate=3
                ))
                bot.viewInfo.color_path(PathColorer(
                    singleQuick,
                    0, 175, 0, alpha=150, alphaDecreaseRate=3
                ))
                logbook.info(f'bypassed singleQuick because best defense was easier for opp. {singleQuick.value} vs {bestDef.value}')
            else:
                bot.info(f'Quick kill, single quick EN {singleQuick}')
                return singleQuick

        shortestKill = None

        for enemyCity in enemyCitiesOrderedByPriority[:12]:
            negTilesToUse = defenseCriticalTileSet.copy()

            if enemyCity in defenseCriticalTileSet:
                negTilesToUse = set()

            cityDepthSearch = cityDepthCutoffEnTerritory
            if bot.territories.is_tile_in_friendly_territory(enemyCity):
                cityDepthSearch = cityDepthCutoffEnTerritory + 5
            elif not bot.territories.is_tile_in_enemy_territory(enemyCity):
                cityDepthSearch = cityDepthCutoffEnTerritory + 2

            if not bot._map.is_player_on_team_with(enemyCity.player, bot.targetPlayer):
                cityDepthSearch -= 1

            if bot.dangerAnalyzer.fastestThreat is not None and enemyCity in bot.dangerAnalyzer.fastestThreat.path.tileSet:
                logbook.info(f'bypassing negativeTiles for city quick kill on {str(enemyCity)} due to it being part of threat path')
                negTilesToUse = set()
                cityDepthSearch -= 1

            if bot.dangerAnalyzer.fastestPotentialThreat is not None and enemyCity in bot.dangerAnalyzer.fastestPotentialThreat.path.tileSet:
                logbook.info(f'bypassing negativeTiles for city quick kill on {str(enemyCity)} due to it being part of POTENTIAL threat path')
                negTilesToUse = set()

            logbook.info(
                f"{bot.get_elapsed()} searching for depth {cityDepthSearch} dest bfs kill on city {enemyCity.x},{enemyCity.y}")
            bot.viewInfo.add_targeted_tile(enemyCity, TargetStyle.RED)
            armyToSearch = bot.get_target_army_inc_adjacent_enemy(enemyCity) + 1.5

            addlIncrementing = SearchUtils.Counter(0)

            def counterNearbyIncr(t: Tile):
                if t.isCity and bot._map.is_tile_enemy(t) and t != enemyCity:
                    addlIncrementing.add(1)

            SearchUtils.breadth_first_foreach(bot._map, enemyCity.adjacents, cityDepthSearch, foreachFunc=counterNearbyIncr)

            killPath = SearchUtils.dest_breadth_first_target(
                bot._map,
                [enemyCity],
                1.5,
                0.1,
                2,
                negTilesToUse,
                preferCapture=True,
                searchingPlayer=bot.general.player,
                dontEvacCities=False,
                additionalIncrement=addlIncrementing.value / 2,
            )
            if killPath is None:
                killPath = SearchUtils.dest_breadth_first_target(
                    bot._map,
                    [enemyCity],
                    max(1.5, armyToSearch),
                    0.1,
                    cityDepthSearch,
                    negTilesToUse,
                    preferCapture=True,
                    searchingPlayer=bot.general.player,
                    additionalIncrement=addlIncrementing.value / 2,
                )
            if killPath is None:
                killPath = SearchUtils.dest_breadth_first_target(
                    bot._map,
                    [enemyCity],
                    max(1.5, armyToSearch),
                    0.1,
                    cityDepthSearch,
                    negTilesToUse,
                    preferCapture=False,
                    searchingPlayer=bot.general.player,
                    additionalIncrement=addlIncrementing.value / 2,
                )
            if killPath is not None:
                bestDef = bot.get_best_defense(killPath.tail.tile, killPath.length - 1, list())
                if bestDef is not None and bestDef.value > killPath.value:
                    bot.viewInfo.color_path(PathColorer(
                        bestDef,
                        75, 30, 0, alpha=150, alphaDecreaseRate=3
                    ))
                    bot.viewInfo.color_path(PathColorer(
                        killPath,
                        0, 75, 0, alpha=150, alphaDecreaseRate=3
                    ))
                    logbook.info(f'bypassed city killpath because best defense was easier for opp. {killPath.value} vs {bestDef.value}')
                    continue

                if killPath.start.tile.isCity and bot.should_kill_path_move_half(killPath, int(armyToSearch - enemyCity.army)):
                    killPath.start.move_half = True
                if shortestKill is None or shortestKill.length > killPath.length:
                    bot.info(
                        f"En city kill len {killPath.length} on {str(enemyCity)}: {str(killPath)}")
                    shortestKill = killPath

        if shortestKill is not None:
            tgCity = shortestKill.tail.tile
            negTilesToUse = defenseCriticalTileSet
            if tgCity in defenseCriticalTileSet:
                negTilesToUse = set()

            if bot.dangerAnalyzer.fastestThreat is not None and tgCity in bot.dangerAnalyzer.fastestThreat.path.tileSet:
                logbook.info(f'bypassing negativeTiles for city quick kill on {str(tgCity)} due to it being part of threat path')
                negTilesToUse = set()

            armyToSearch = bot.get_target_army_inc_adjacent_enemy(tgCity) + 1
            cityPath = shortestKill.get_subsegment(3, end=True)
            maxDur = int(bot.player.tileCount ** 0.32) + 1
            path, move = bot.plan_city_capture(
                tgCity,
                cityPath,
                allowGather=True,
                targetKillArmy=armyToSearch - 1,
                targetGatherArmy=tgCity.army + armyToSearch - 1,
                killSearchDist=5,
                gatherMaxDuration=maxDur,
                negativeTiles=negTilesToUse)
            if move is not None:
                bot.info(f'plan_city_capture quick kill @{tgCity}')
                fakePath = Path()
                fakePath.add_next(move.source)
                fakePath.add_next(move.dest)
                return fakePath
            if path is not None:
                return path.get_subsegment(1)
            if shortestKill is not None:
                bot.viewInfo.add_info_line(f'plan_city_capture didnt find plan for {str(tgCity)}, using og kp instead')
                return shortestKill.get_subsegment(1)

        return None

    @staticmethod
    def plan_city_capture(
            bot,
            targetCity: Tile,
            cityGatherPath: Path | None,
            allowGather: bool,
            targetKillArmy: int,
            targetGatherArmy: int,
            killSearchDist: int,
            gatherMaxDuration: int,
            negativeTiles: typing.Set[Tile],
            gatherMinDuration: int = 0,
    ) -> typing.Tuple[Path | None, Move | None]:
        if targetGatherArmy < targetKillArmy + targetCity.army:
            raise AssertionError(f'You cant gather less army {targetGatherArmy} to a city than the kill requirement {targetKillArmy} or the kill requirement will never fire and you will gather-loop.')

        targetKillArmy += 1
        targetGatherArmy += 1

        if cityGatherPath and cityGatherPath.length > killSearchDist:
            killSearchDist = cityGatherPath.length

        if targetCity in negativeTiles or (bot.threat is not None and targetCity in bot.threat.armyAnalysis.shortestPathWay.tiles):
            negativeTiles = set()
        else:
            negativeTiles = negativeTiles.copy()

        if targetCity.isNeutral and bot.targetPlayer != -1 and len(bot.targetPlayerObj.tiles) > 0:
            maxDist = bot.territories.territoryDistances[bot.targetPlayer].raw[targetCity.tile_index] - 1
            maxDist = min(5, maxDist)

            def foreachFunc(tile) -> bool:
                if bot.territories.territoryDistances[bot.targetPlayer].raw[tile.tile_index] < maxDist and tile not in bot.tiles_gathered_to_this_cycle:
                    negativeTiles.add(tile)
            SearchUtils.breadth_first_foreach(bot._map, bot.targetPlayerObj.tiles, maxDist + 5, foreachFunc)

        potentialThreatNegs = bot.get_potential_threat_movement_negatives(targetCity)
        negativeTiles.update(potentialThreatNegs)

        addlIncrementing = SearchUtils.count(targetCity.adjacents, lambda tile: tile.isCity and bot._map.is_tile_enemy(tile))

        logbook.info(
            f"Searching for city kill on {str(targetCity)} in {killSearchDist} turns with targetArmy {targetKillArmy}...")
        killPath = SearchUtils.dest_breadth_first_target(
            bot._map,
            [targetCity],
            targetArmy=targetKillArmy,
            maxTime=0.03,
            maxDepth=killSearchDist,
            noNeutralCities=True,
            preferCapture=True,
            negativeTiles=negativeTiles,
            searchingPlayer=bot.general.player,
            additionalIncrement=addlIncrementing / 2)

        if killPath is None:
            killPath = SearchUtils.dest_breadth_first_target(
                bot._map,
                [targetCity],
                targetArmy=targetKillArmy,
                maxTime=0.03,
                maxDepth=killSearchDist,
                noNeutralCities=True,
                preferCapture=False,
                negativeTiles=negativeTiles,
                searchingPlayer=bot.general.player,
                additionalIncrement=addlIncrementing / 2)

        if targetCity.player >= 0:
            altKillArmy = 1 + bot.sum_enemy_army_near_tile(targetCity, distance=1)
            altKillPath = SearchUtils.dest_breadth_first_target(
                bot._map,
                [targetCity],
                targetArmy=altKillArmy,
                maxTime=0.03,
                maxDepth=3,
                noNeutralCities=True,
                preferCapture=True,
                negativeTiles=negativeTiles,
                searchingPlayer=bot.general.player,
                additionalIncrement=addlIncrementing / 2)
            if altKillPath is not None and (killPath is None or altKillPath.length <= killPath.length // 2):
                if killPath is not None:
                    bot.info(f'Using short enCity cap len {altKillPath.length} {altKillPath.value} over larger len {killPath.length}')
                else:
                    bot.info(f'Using short enCity cap len {altKillPath.length} {altKillPath.value}')
                killPath = altKillPath

        if killPath is not None:
            logbook.info(
                f"found depth {killPath.length} dest bfs kill on Neutral or Enemy city {targetCity.x},{targetCity.y} \n{str(killPath)}")
            bot.info(f"City killpath {killPath}, setting GTN to None")
            bot.viewInfo.evaluatedGrid[targetCity.x][targetCity.y] = 300
            bot.gatherNodes = None
            addlArmy = 0
            if targetCity.player != -1:
                addlArmy += killPath.length
            if addlIncrementing > 0:
                addlArmy += killPath.length
            killPath.start.move_half = bot.should_kill_path_move_half(killPath, targetKillArmy + addlArmy)
            bot.city_capture_plan_tiles.update(killPath.tileList)
            bot.city_capture_plan_last_updated = bot._map.turn
            return killPath, None

        if not allowGather:
            return None, None

        armyAlreadyPrepped = 0
        if cityGatherPath:
            for tile in cityGatherPath.tileList:
                if bot._map.is_player_on_team_with(tile.player, bot.general.player):
                    armyAlreadyPrepped += tile.army - 1
                elif tile != targetCity:
                    armyAlreadyPrepped -= tile.army + 1
        targetGatherArmy -= armyAlreadyPrepped

        targets = [targetCity]
        if cityGatherPath:
            targets = cityGatherPath.tileList
        with bot.perf_timer.begin_move_event(f'Capture City gath to {str(targets)}'):
            gatherDist = gatherMaxDuration
            negativeTiles = negativeTiles.copy()
            for t in targets:
                bot.viewInfo.add_targeted_tile(t, TargetStyle.PURPLE)

            mePlayer = bot._map.players[bot.general.player]

            cycleTurn = bot.timings.get_turn_in_cycle(bot._map.turn)
            turnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)
            notLateGame = mePlayer.tileCount < 150 and (bot._map.remainingPlayers == 2 or bot._map.is_2v2)
            if targetCity.isNeutral and notLateGame:
                genAlreadyInNeg = bot.general in negativeTiles

                offsetByNearEndOfCycle = cycleTurn // 20
                offsetByNearEndOfCycle = 0

                negativeTiles.update(bot.cityAnalyzer.owned_contested_cities)

                if not genAlreadyInNeg and bot.general in negativeTiles:
                    negativeTiles.remove(bot.general)

            bot.viewInfo.add_info_line(
                f"city gath target_tile gatherDist {gatherDist} - targetArmyGather {targetGatherArmy} (prepped {armyAlreadyPrepped}), negatives {'+'.join([str(t) for t in negativeTiles])}")

            if targetCity.player >= 0 and (cityGatherPath is not None and targetCity not in cityGatherPath.tileSet):
                addlIncrementing += 1

            move, gatherValue, gatherTurns, gatherNodes = bot.get_gather_to_target_tiles(
                targets,
                0.03,
                gatherDist,
                negativeSet=negativeTiles,
                targetArmy=targetGatherArmy,
                additionalIncrement=addlIncrementing,
            )

            if move is not None:
                preferPrune = set(bot.expansion_plan.preferred_tiles) if bot.expansion_plan is not None else None

                if preferPrune is not None:
                    for t in bot.expansion_plan.preferred_tiles:
                        if t in bot.tiles_gathered_to_this_cycle:
                            preferPrune.remove(t)

                if targetCity.isNeutral:
                    prunedTurns, prunedValue, prunedGatherNodes = Gather.prune_mst_to_army_with_values(
                        gatherNodes,
                        targetGatherArmy,
                        bot.general.player,
                        teams=MapBase.get_teams_array(bot._map),
                        turn=bot._map.turn,
                        additionalIncrement=addlIncrementing,
                        preferPrune=preferPrune,
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None)
                else:
                    prunedTurns, prunedValue, prunedGatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                        gatherNodes,
                        targetGatherArmy,
                        bot.general.player,
                        teams=MapBase.get_teams_array(bot._map),
                        additionalIncrement=addlIncrementing,
                        preferPrune=preferPrune,
                        minTurns=gatherMinDuration,
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None)

                GatherTreeNode.foreach_tree_node(prunedGatherNodes, lambda n: bot.city_capture_plan_tiles.add(n.tile))
                bot.city_capture_plan_tiles.update(targets)
                bot.city_capture_plan_tiles.add(targetCity)
                bot.city_capture_plan_last_updated = bot._map.turn

                if targetCity.isNeutral and turnsLeft - prunedTurns < 10 and notLateGame and not bot._map.is_walled_city_game and targetCity.army > 10:
                    bot.info(
                        f"GC TOO SLOW {str(targetCity)} {move} t{prunedTurns}/{gatherTurns}/{gatherDist}  prun{prunedValue + armyAlreadyPrepped}/pre{gatherValue + armyAlreadyPrepped}/req{targetGatherArmy + armyAlreadyPrepped} -proact {bot.should_proactively_take_cities()}")
                    bot.viewInfo.evaluatedGrid[targetCity.x][targetCity.y] = 300
                    return None, None

                sameLengthKillPath = SearchUtils.dest_breadth_first_target(
                    bot._map,
                    [targetCity],
                    targetArmy=targetKillArmy,
                    maxTime=0.03,
                    maxDepth=min(16, prunedTurns + len(targets) + 1),
                    noNeutralCities=True,
                    preferCapture=True,
                    negativeTiles=negativeTiles,
                    searchingPlayer=bot.general.player)

                if sameLengthKillPath is not None:
                    pathVal = sameLengthKillPath.calculate_value(
                        bot.player.index,
                        MapBase.get_teams_array(bot._map),
                        negativeTiles=negativeTiles
                    )
                    if pathVal + 4 > prunedValue * 0.8:
                        bot.info(f"GC @{str(targetCity)} killpath found optimizing captures")
                        bot.city_capture_plan_tiles.update(sameLengthKillPath.tileList)
                        bot.city_capture_plan_last_updated = bot._map.turn
                        return sameLengthKillPath, None

                move = bot.get_tree_move_default(prunedGatherNodes, pop=False)
                path = None
                bot.gatherNodes = prunedGatherNodes
                if move and move.dest == targetCity:
                    moveList = []
                    prunedNodes = GatherTreeNode.clone_nodes(prunedGatherNodes)

                    _ = bot.get_tree_move_default(prunedNodes, pop=True)
                    nextMove = move
                    while nextMove is not None:
                        moveList.append(nextMove)
                        nextMove = bot.get_tree_move_default(prunedNodes, pop=True)
                    if len(moveList) > 0:
                        moveList.extend(cityGatherPath.convert_to_move_list())
                        moveListPath = MoveListPath(moveList)
                        path = moveListPath
                        bot.curPath = path

                bot.info(
                    f"GC {str(targetCity)} {move} t{prunedTurns}/{gatherTurns}/{gatherDist}  prun{prunedValue + armyAlreadyPrepped}/pre{gatherValue + armyAlreadyPrepped}/req{targetGatherArmy + armyAlreadyPrepped} -proact {bot.should_proactively_take_cities()}")
                bot.viewInfo.evaluatedGrid[targetCity.x][targetCity.y] = 300
                return path, move

        return None, None

    @staticmethod
    def block_neutral_captures(bot, reason: str = ''):
        if bot.curPath and bot.curPath.tail.tile.isCity and bot.curPath.tail.tile.isNeutral:
            targetNeutCity = bot.curPath.tail.tile
            if bot.is_blocking_neutral_city_captures:
                bot.info(
                    f'forcibly stopped taking neutral city {str(targetNeutCity)} {reason}')
                bot.curPath = None
        logbook.info(f'Preventing neutral city captures for now {reason}')
        bot.is_blocking_neutral_city_captures = True

    @staticmethod
    def ensure_reachability_matrix_built(bot):
        with bot.perf_timer.begin_move_event(f'rebuild_reachability_costs_matrix'):
            bot.cityAnalyzer.ensure_reachability_matrix_built(force=False)

    @staticmethod
    def should_rapid_capture_neutral_cities(bot) -> bool:
        if bot.targetPlayer == -1:
            return True

        if bot._map.is_2v2 and bot.teammate_general is not None:
            seenOtherPlayer = False
            for player in bot._map.players:
                if not bot._map.is_player_on_team_with(player.index, bot.general.player):
                    if len(player.tiles) > 0:
                        seenOtherPlayer = True

            if not seenOtherPlayer:
                return True
            return False

        if (bot._map.is_walled_city_game or bot._map.is_low_cost_city_game) and (bot.target_player_gather_path.length < 5 or not bot.armyTracker.seen_player_lookup[bot.targetPlayer]):
            return True

        mePlayer = bot._map.players[bot.general.player]
        targPlayer = bot._map.players[bot.targetPlayer]
        unseenTargetPlayerAndMapMassive = len(bot.targetPlayerObj.tiles) == 0 and bot._map.is_walled_city_game

        haveLotsOfExcessArmy = mePlayer.standingArmy > mePlayer.tileCount * 2
        aheadOfOppArmyByHundreds = mePlayer.standingArmy > targPlayer.standingArmy + 100
        notWinningEcon = not bot.opponent_tracker.winning_on_economy(byRatio=0.8, cityValue=40)
        hasDoubleEcon = targPlayer.cityCount + 2 < mePlayer.cityCount // 2 and not bot._map.remainingPlayers > 3
        hasTripleEcon = targPlayer.cityCount + 1 < mePlayer.cityCount // 3
        if bot._map.is_2v2:
            hasDoubleEcon = bot.opponent_tracker.winning_on_economy(2.0, cityValue=100)
            hasTripleEcon = bot.opponent_tracker.winning_on_economy(3.0, cityValue=100)

        numberOfTilesEnemyNeedsToExploreToFindUsAvg = mePlayer.tileCount // 2 - 50
        if targPlayer.aggression_factor < 20:
            numberOfTilesEnemyNeedsToExploreToFindUsAvg = mePlayer.tileCount // 2

        if (
                not bot.is_all_in_army_advantage
                and (
                        (mePlayer.tileCount > 200 and mePlayer.standingArmy > mePlayer.tileCount * 3)
                        or (mePlayer.tileCount > 150 and mePlayer.standingArmy > mePlayer.tileCount * 4)
                        or (mePlayer.tileCount > 110 and mePlayer.standingArmy > mePlayer.tileCount * 5)
                )
                and mePlayer.standingArmy > targPlayer.standingArmy - numberOfTilesEnemyNeedsToExploreToFindUsAvg
                and not targPlayer.knowsKingLocation
                and (not hasDoubleEcon or targPlayer.aggression_factor < 30 and not hasTripleEcon)
        ):
            bot.viewInfo.add_info_line(f'RAPID CITY EXPAND due to sheer volume of tiles/army')
            bot.is_rapid_capturing_neut_cities = True
            return True

        haveMinimumArmyAdv = mePlayer.standingArmy > targPlayer.standingArmy * 0.8 or targPlayer.aggression_factor < 150
        haveAchievedEconomicDominance = bot.opponent_tracker.winning_on_economy(byRatio=1.45, cityValue=1000)

        if (
                1 == 1
                and (
                (aheadOfOppArmyByHundreds and notWinningEcon and targPlayer.aggression_factor < 200)
                or (haveLotsOfExcessArmy and bot.is_rapid_capturing_neut_cities)
        )
                and not targPlayer.knowsKingLocation
                and not hasDoubleEcon
        ):
            if not haveMinimumArmyAdv:
                bot.viewInfo.add_info_line(f'Ceasing rapid city expand due to sketchy army amount territory')
            elif haveAchievedEconomicDominance:
                bot.viewInfo.add_info_line(f'Ceasing rapid city expand due to economic dominance achieved')
            else:
                bot.is_rapid_capturing_neut_cities = True
                return True

        bot.is_rapid_capturing_neut_cities = False
        return False

    @staticmethod
    def find_rapid_city_path(bot) -> Path | None:
        if not bot.should_rapid_capture_neutral_cities():
            return None

        longDistSearchCities = []
        for neutCity in bot.cityAnalyzer.city_scores:
            if not neutCity.discovered:
                continue
            if bot.sum_enemy_army_near_tile(neutCity, 2) == 0 and bot.count_enemy_territory_near_tile(neutCity, 3) == 0:
                longDistSearchCities.append(neutCity)

        shortDistSearchCities = []
        if bot.targetPlayerObj is not None and bot.targetPlayerObj.aggression_factor > 200:
            for enCity in bot.cityAnalyzer.enemy_city_scores:
                if not enCity.discovered:
                    continue
                shortDistSearchCities.append(enCity)
                if not bot.territories.is_tile_in_enemy_territory(enCity):
                    longDistSearchCities.append(enCity)

        if len(shortDistSearchCities) > 0:
            quickestKillPath = SearchUtils.dest_breadth_first_target(bot._map, shortDistSearchCities, maxDepth=4)
            if quickestKillPath is not None:
                bot.info(f'RAPID CITY EN EXPAND DUE TO should_rapid_capture_neutral_cities')
                return quickestKillPath

        if len(longDistSearchCities) > 0:
            quickestKillPath = SearchUtils.dest_breadth_first_target(bot._map, longDistSearchCities, maxDepth=9)
            if quickestKillPath is not None:
                bot.info(f'RAPID CITY EXPAND DUE TO should_rapid_capture_neutral_cities')
                return quickestKillPath

        return None

    @staticmethod
    def should_allow_neutral_city_capture(
            bot,
            genPlayer: Player,
            forceNeutralCapture: bool,
            targetCity: Tile | None = None
    ) -> bool:
        cityCost = 44
        if bot._map.walled_city_base_value is not None:
            cityCost = bot._map.walled_city_base_value
        if targetCity is not None:
            cityCost = targetCity.army + 1

        if bot.player.standingArmy - 15 < cityCost and not bot._map.is_walled_city_game:
            return False

        if bot.targetPlayer != -1:
            cycleLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)
            threatTurns = cycleLeft - 12
            minFogDist = bot.shortest_path_to_target_player.length // 2 + 3
            if bot.enemy_attack_path:
                enFogged = bot.enemy_attack_path.get_subsegment_excluding_trailing_visible()
                minFogDist = bot.distance_from_general(enFogged.tail.tile) + 1
            if threatTurns < minFogDist:
                threatTurns = minFogDist
            with bot.perf_timer.begin_move_event(f'approximate attack / def ({threatTurns}t)'):
                defTurns = threatTurns
                generalContribution = defTurns // 2

                cityContribution = (defTurns - len(bot.city_capture_plan_tiles)) // 2
                cityDefVal = generalContribution + cityContribution
                if not bot.was_allowing_neutral_cities_last_turn:
                    cityDefVal -= 10
                searchNegs = set()
                if bot.city_capture_plan_last_updated > bot._map.turn - 2 and targetCity in bot.city_capture_plan_tiles:
                    bot.viewInfo.add_stats_line(f'updating existing city capture plan tiles. cityDefVal {cityDefVal}')
                    searchNegs.update(bot.city_capture_plan_tiles)
                else:
                    cityDefVal -= cityCost
                    tgCities = [targetCity] if targetCity is not None else list(bot.cityAnalyzer.city_scores.keys())
                    if len(tgCities) > 0:
                        playerTilesNearCity = SearchUtils.get_player_tiles_near_up_to_army_amount(map=bot._map, fromTiles=tgCities, armyAmount=tgCities[0].army, asPlayer=bot.general.player, tileAmountCutoff=1)
                        for t in playerTilesNearCity:
                            cityDefVal += t.army - 1
                        searchNegs.update(playerTilesNearCity)
                        bot.viewInfo.add_stats_line(f'new city capture plan tiles? cityDefVal {cityDefVal}')
                    else:
                        bot.viewInfo.add_stats_line(f'bypassing neut cities, 0 neut cities available :( cityDefVal {cityDefVal}')
                        return False

                defTile = bot.general
                if targetCity and bot.board_analysis.intergeneral_analysis.bMap.raw[defTile.tile_index] > bot.board_analysis.intergeneral_analysis.bMap.raw[targetCity.tile_index]:
                    defTile = targetCity
                attackNegs = set(searchNegs)
                attackNegs.update(bot.largePlayerTiles)
                risk = bot.win_condition_analyzer.get_approximate_attack_against(
                    [defTile],
                    inTurns=threatTurns,
                    asPlayer=bot.targetPlayer,
                    forceFogRisk=True,
                    negativeTiles=attackNegs)

                requiredDefenseArmy = risk + cityCost - cityDefVal
                turns, defValue = bot.win_condition_analyzer.get_dynamic_turns_visible_defense_against([defTile], defTurns, asPlayer=bot.general.player, minArmy=requiredDefenseArmy, negativeTiles=searchNegs)

            armyBonusDefense = 2 * max(0, defTurns - cycleLeft)
            hackToEnsureCity = 30 if bot.was_allowing_neutral_cities_last_turn and bot.targetPlayerObj.tileCount > 60 else 0
            defAfterCity = defValue + cityDefVal + armyBonusDefense
            if bot.opponent_tracker.even_or_up_on_cities(bot.targetPlayer):
                if risk > defAfterCity + hackToEnsureCity and risk > 5:
                    bot.is_blocking_neutral_city_captures = True
                    bot.viewInfo.add_stats_line(f'bypassing neut cities, danger {risk} in {threatTurns} > {defAfterCity} ({defValue} + cityDefVal {cityDefVal}) and risk > 5')
                    return False

                if bot.is_blocking_neutral_city_captures:
                    bot.viewInfo.add_stats_line(f'bypassing neut cities due to is_blocking_neutral_city_captures {bot.is_blocking_neutral_city_captures}')
                    return False

            if bot.defend_economy and (bot.targetPlayer == -1 or bot.opponent_tracker.even_or_up_on_cities(bot.targetPlayer)):
                bot.viewInfo.add_stats_line(f'bypassing neut cities due to defend_economy {bot.defend_economy}')
                return False

            if risk <= defAfterCity:
                bot.viewInfo.add_stats_line(f'ALLOW neut cities, danger {risk} in {threatTurns} <= {defAfterCity} ({defValue} + cityDefVal {cityDefVal})')
            else:
                bot.viewInfo.add_stats_line(f'ALLOW neut cities DESPITE danger {risk} in {threatTurns} > {defAfterCity} ({defValue} + cityDefVal {cityDefVal})')

        proactivelyTakeCity = bot.should_proactively_take_cities() or forceNeutralCapture
        safeFromThreat = (
                bot.threat is None
                or bot.threat.threatType != ThreatType.Kill
                or bot.threat.threatValue <= bot.threat.turns
                or (bot.threat.turns > 6 and not bot.threat.path.start.tile.visible)
                or not bot.threat.path.tail.tile.isGeneral
        )
        if not safeFromThreat:
            bot.viewInfo.add_info_line("Will not proactively take cities due to the existing threat....")
            proactivelyTakeCity = False
            if bot.threat.threatValue > cityCost // 2:
                forceNeutralCapture = False
                bot.force_city_take = False

        forceCityOffset = 0
        if bot.force_city_take or bot.is_player_spawn_cramped(bot.shortest_path_to_target_player.length):
            forceCityOffset = 1

        targCities = 1

        targetPlayer = None
        if bot.targetPlayer != -1:
            targetPlayer = bot._map.players[bot.targetPlayer]

        if targetPlayer is not None:
            targCities = targetPlayer.cityCount

        cityTakeThreshold = targCities + forceCityOffset

        logbook.info(f'force_city_take {bot.force_city_take}, cityTakeThreshold {cityTakeThreshold}, targCities {targCities}')
        if bot.targetPlayer == -1 or bot._map.remainingPlayers <= 3 or bot.force_city_take:
            if (
                    targetPlayer is None
                    or (
                    (genPlayer.cityCount < cityTakeThreshold or proactivelyTakeCity)
                    and safeFromThreat
            )
            ):
                logbook.info("Didn't skip neut cities.")
                if forceNeutralCapture or targetPlayer is None or genPlayer.cityCount < cityTakeThreshold or bot.force_city_take:
                    return True
                else:
                    logbook.info(
                        f"We shouldn't be taking more neutral cities, we're too defenseless right now.")
            else:
                logbook.info(
                        f"Skipped neut cities. in_gather_split(bot._map.turn) {bot.timings.in_gather_split(bot._map.turn)} and (player.cityCount < targetPlayer.cityCount {genPlayer.cityCount < targetPlayer.cityCount} or proactivelyTakeCity {proactivelyTakeCity})")
        return False

    @staticmethod
    def get_city_contestation_all_in_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> typing.Tuple[Move | None, int, int, typing.List[GatherTreeNode]]:
        targets = list(bot.win_condition_analyzer.contestable_cities)

        negatives = defenseCriticalTileSet.copy()
        negatives.update(bot.win_condition_analyzer.defend_cities)

        if len(targets) == 0:
            targets = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=7, cutoffEmergenceRatio=0.5)[0:3]

        turns = bot.win_condition_analyzer.recommended_offense_plan_turns

        move, valGathered, gatherTurns, gatherNodes = bot.get_gather_to_target_tiles(
            targets,
            maxTime=0.05,
            gatherTurns=turns,
            maximizeArmyGatheredPerTurn=True,
            useTrueValueGathered=True,
            negativeSet=defenseCriticalTileSet)

        if gatherNodes:
            prunedGatherTurns, sumPruned, prunedGatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                minArmy=1,
                searchingPlayer=bot.general.player,
                teams=bot.teams,
                additionalIncrement=0,
                preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                viewInfo=bot.viewInfo)

            rootGatheredTiles = [n.tile for n in prunedGatherNodes]
            predictedTurns, predictedDefenseVal = bot.win_condition_analyzer.get_dynamic_turns_visible_defense_against(rootGatheredTiles, prunedGatherTurns, prunedGatherNodes[0].tile.player)
            fogRisk = bot.opponent_tracker.get_approximate_fog_army_risk(bot.targetPlayer, inTurns=0)
            if sumPruned < predictedDefenseVal + fogRisk:
                return None, 0, 0, []

            numCaptures = bot.get_number_of_captures_in_gather_tree(prunedGatherNodes)

            if sumPruned / max(1, prunedGatherTurns - numCaptures) > 3 * bot.player.standingArmy / bot.player.tileCount - 1:
                if len(prunedGatherNodes) > 0:
                    move = bot.get_tree_move_default(gatherNodes)

                for tile in targets:
                    bot.viewInfo.add_targeted_tile(tile, TargetStyle.ORANGE, radiusReduction=-1)

                if move is not None:
                    bot.info(f'City Contest Off {move} (val {valGathered}/p{sumPruned} turns {gatherTurns}/p{prunedGatherTurns})')

                return move, sumPruned, prunedGatherTurns, prunedGatherNodes

        return None, 0, 0, []

    @staticmethod
    def get_city_preemptive_defense_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if bot.is_still_ffa_and_non_dominant():
            return None

        sketchyOutOfPlayThresh = bot.player.standingArmy // 6
        sketchyCities = [c for c in bot.win_condition_analyzer.defend_cities]
        targets = list(bot.win_condition_analyzer.defend_cities)

        if len(sketchyCities) > 0:
            sketchyLargeArmyCities = [c for c in sketchyCities if c.army > sketchyOutOfPlayThresh // 4]
            if len(sketchyLargeArmyCities) > 0:
                sketchyLargeArmyCities = sketchyCities
            sketchyArmy = 0
            for t in sketchyCities:
                sketchyArmy += t.army - 1

            if sketchyArmy > sketchyOutOfPlayThresh and bot.sketchiest_potential_inbound_flank_path is not None:
                furthestCity = max(sketchyLargeArmyCities, key=lambda c: bot.board_analysis.intergeneral_analysis.aMap[c])
                furthestDist = bot.board_analysis.intergeneral_analysis.aMap[furthestCity]
                fogDist = bot.board_analysis.intergeneral_analysis.aMap[bot.sketchiest_potential_inbound_flank_path.tail.tile]

                if fogDist <= furthestDist:
                    negs = defenseCriticalTileSet.copy()
                    negs.update(sketchyCities)
                    with bot.perf_timer.begin_move_event('city preemptive flank defense get_flank_vision_defense_move'):
                        flankDefenseMove = bot._get_flank_vision_defense_move_internal(bot.sketchiest_potential_inbound_flank_path, negs, atDist=furthestDist)
                    if flankDefenseMove is not None:
                        bot.info(f'Flank defense {str(flankDefenseMove)}')
                        return flankDefenseMove
                    else:
                        bot.viewInfo.add_info_line(f'There was a flank risk, but we didnt find a flank defense move...?')

        wouldStillBeAheadIfOppTakesCity = bot.opponent_tracker.winning_on_economy(byRatio=1.02, offset=-33)

        turnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)
        turnCutoffLowEcon = int(bot.shortest_path_to_target_player.length * 1.0)
        turnCutoffHighEcon = int(bot.shortest_path_to_target_player.length * 0.4)
        if turnsLeft <= turnCutoffHighEcon:
            bot.viewInfo.add_info_line(f'bypassing preemptive city defense t{turnsLeft}/{turnCutoffHighEcon} (high econ)')
            return None

        if turnsLeft <= turnCutoffLowEcon and not wouldStillBeAheadIfOppTakesCity:
            bot.viewInfo.add_info_line(f'bypassing preemptive city defense t{turnsLeft}/{turnCutoffLowEcon} due to not winning by that much')
            return None

        negs = defenseCriticalTileSet.copy()

        negs.update(targets)
        negs.update(bot.cityAnalyzer.owned_contested_cities)

        tilesFarFromUs = [t for t in bot.player.tiles if t not in bot.tiles_gathered_to_this_cycle and bot.territories.territoryTeamDistances[bot.targetPlayerObj.team].raw[t.tile_index] < 2 and t.army < 5]
        for t in tilesFarFromUs:
            bot.viewInfo.evaluatedGrid[t.x][t.y] = 100
            negs.add(t)

        newTargets = set()
        for t in targets:
            negs.add(t)
            tiles = bot.get_n_closest_team_tiles_near([t], bot.targetPlayer, distance=max(1, bot.board_analysis.inter_general_distance // 7), limit=7, includeNeutral=False)
            if len(tiles) < 1:
                tiles = bot.get_n_closest_team_tiles_near([t], bot.targetPlayer, distance=max(2, bot.board_analysis.inter_general_distance // 5), limit=10, includeNeutral=True)
            if len(tiles) < 1:
                tiles = [t]

            negs.update(bot.get_n_closest_team_tiles_near([t], bot.general.player, distance=max(2, bot.board_analysis.inter_general_distance // 5), limit=6, includeNeutral=False))

            newTargets.update(tiles)

        for tg in newTargets:
            bot.viewInfo.add_targeted_tile(tg, TargetStyle.BLUE, radiusReduction=-3)
        for tg in negs:
            bot.viewInfo.evaluatedGrid[tg.x][tg.y] += 100

        move, valGathered, gatherTurns, gatherNodes = bot.get_gather_to_target_tiles(
            [t for t in newTargets],
            maxTime=0.05,
            gatherTurns=bot.win_condition_analyzer.recommended_city_defense_plan_turns,
            useTrueValueGathered=True,
            priorityMatrix=bot.get_gather_tiebreak_matrix(),
            negativeSet=negs)

        numCaptures = bot.get_number_of_captures_in_gather_tree(gatherNodes)

        if valGathered / max(1, gatherTurns - numCaptures) < bot.player.standingArmy / bot.player.tileCount:
            cycleTurns = bot.timings.get_turns_left_in_cycle(bot._map.turn) % 25
            cycleTurns = max(bot.win_condition_analyzer.recommended_city_defense_plan_turns + 15, cycleTurns)
            bot.info(f'trying longer city preemptive defense turns {cycleTurns}')
            move, valGathered, gatherTurns, gatherNodes = bot.get_gather_to_target_tiles(
                [t for t in newTargets],
                maxTime=0.05,
                gatherTurns=cycleTurns,
                useTrueValueGathered=True,
                priorityMatrix=bot.get_gather_tiebreak_matrix(),
                negativeSet=negs)

            if gatherNodes is not None:
                prunedGatherTurns, sumPruned, prunedGatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                    gatherNodes,
                    minArmy=1,
                    searchingPlayer=bot.general.player,
                    teams=bot.teams,
                    additionalIncrement=0,
                    preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                    viewInfo=bot.viewInfo)

                if prunedGatherNodes is not None and len(prunedGatherNodes) > 0:
                    move = bot.get_tree_move_default(gatherNodes)
                    valGathered = sumPruned
                    gatherTurns = prunedGatherTurns

        for tile in bot.win_condition_analyzer.defend_cities:
            bot.viewInfo.add_targeted_tile(tile, TargetStyle.WHITE, radiusReduction=3)

        if move is not None:
            bot.info(f'C preDef {move} - {valGathered} in turns {gatherTurns}/{bot.win_condition_analyzer.recommended_city_defense_plan_turns}')

        return move
